"""La constancia de entrega: qué salió de un PDF de origen y si sigue entero en el destino.

Volver a lanzar una carpeta de veinte mil PDF después de un corte -- la luz, la
red, un reinicio -- no puede costar volver a leer y a pagar lo que ya está
entregado. Hasta ahora se saltaba un PDF si su carpeta del destino tenía
**algún** PDF, y eso daba por entregado lo que se cortó a la mitad de la copia,
no servía para las actas (que se entregan en la carpeta espejo) y no veía un
origen que se volvió a escanear con el mismo nombre.

Cada PDF entregado deja ahora, junto a lo suyo, un JSON pequeño:

* ``estado`` «entregando» mientras se copia y «completa» cuando terminó. Una
  constancia que se quedó en «entregando» es una entrega cortada: se rehace.
* El tamaño y la fecha del PDF de origen. Si cambian, el origen es otro y se
  vuelve a procesar.
* Los archivos que se entregaron, con su tamaño. Si falta alguno o cambió, la
  entrega ya no está entera y se rehace.
* Lo que los inventarios generales necesitan de ese PDF -- su fila del
  inventario de procesos, las filas de sus actas, sus unidades --, para que una
  corrida que lo salta lo siga contando.

Comprobarla cuesta mirar el tamaño del origen y listar una carpeta: nada del
contenido del PDF se lee, ni del origen ni del destino.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PureWindowsPath

from ..adapters import red_smb

logger = logging.getLogger(__name__)

#: El nombre de la constancia en la carpeta de un PDF. Con punto delante, para
#: que no estorbe al abrir la carpeta, y no es un PDF: ningún `*.pdf` la cuenta.
NOMBRE = ".bot-entrega.json"
#: Las actas se entregan en una carpeta espejo que comparten todos los PDF de
#: una subcarpeta; ahí la constancia de cada uno va en esta carpeta, con su
#: nombre.
CARPETA_DE_ACTAS = ".bot-entregas"
#: La versión del formato, por si un día cambia lo que se guarda.
VERSION = 1


class EstadoDeEntrega(StrEnum):
    ENTREGANDO = "entregando"
    COMPLETA = "completa"


class Vigencia(StrEnum):
    """Qué dice la constancia de un PDF cuando se vuelve a lanzar la carpeta."""

    #: Entregado entero y el origen es el mismo: no se vuelve a procesar.
    VIGENTE = "vigente"
    #: No hay constancia.
    SIN_CONSTANCIA = "sin constancia"
    #: La copia se cortó, o falta o cambió algún archivo entregado.
    INCOMPLETA = "incompleta"
    #: El PDF de origen no es el que se entregó: otro tamaño u otra fecha.
    ORIGEN_CAMBIADO = "origen cambiado"


@dataclass(slots=True)
class Constancia:
    origen: str
    tamano: int
    modificado_ns: int
    estado: str = EstadoDeEntrega.ENTREGANDO
    #: Lo entregado, relativo a la carpeta de la constancia: {"ruta", "bytes"}.
    archivos: list[dict] = field(default_factory=list)
    habilidad: str = ""
    job_id: str = ""
    fecha: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    #: La fila del inventario general de procesos de este PDF.
    proceso: dict | None = None
    #: Las filas de sus actas, para el Excel de la carpeta.
    actas: list[dict] = field(default_factory=list)
    #: Sus unidades, para la planilla de la entrega entera.
    unidades: list[dict] = field(default_factory=list)
    #: Su Índice Electrónico -- «nic», «territorial», «expediente» y «filas» --,
    #: para rehacer el de la carpeta del NIC con todos sus UPD sin volver a
    #: procesar ninguno (la caja de correspondencia, desde el 2026-10-22).
    indice: dict | None = None
    #: El principio y el final del PDF de origen (``firma_del_origen``): dice si
    #: es el mismo aunque se haya copiado y tenga otra fecha.
    firma: str | None = None
    version: int = VERSION

    def as_dict(self) -> dict:
        return asdict(self)


def huella_del_origen(path: Path) -> tuple[int, int]:
    """Tamaño y fecha de modificación del PDF de origen, sin abrirlo.

    De una carpeta de red leída con SMB, se le pregunta al servidor.
    """
    if red_smb.por_smb(path):
        return red_smb.huella(str(path))
    datos = path.stat()
    return datos.st_size, datos.st_mtime_ns


def leer(ruta: Path) -> Constancia | None:
    """La constancia en ``ruta``, o ``None`` si no hay o no se entiende."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.warning("constancia ilegible en %s", ruta, exc_info=True)
        return None
    if not isinstance(datos, dict):
        return None
    conocidos = set(Constancia.__dataclass_fields__)
    try:
        constancia = Constancia(**{clave: valor for clave, valor in datos.items() if clave in conocidos})
    except (TypeError, ValueError):
        return None
    if (
        not isinstance(constancia.origen, str)
        or type(constancia.tamano) is not int
        or constancia.tamano < 0
        or type(constancia.modificado_ns) is not int
        or not isinstance(constancia.estado, str)
        or not isinstance(constancia.fecha, str)
        or not isinstance(constancia.archivos, list)
        or not all(isinstance(archivo, dict) for archivo in constancia.archivos)
        or not isinstance(constancia.habilidad, str)
        or not isinstance(constancia.job_id, str)
        or (constancia.proceso is not None and not isinstance(constancia.proceso, dict))
        or not isinstance(constancia.actas, list)
        or not isinstance(constancia.unidades, list)
        or (constancia.indice is not None and not isinstance(constancia.indice, dict))
        or (constancia.firma is not None and not isinstance(constancia.firma, str))
        or type(constancia.version) is not int
    ):
        logger.warning("constancia con datos inválidos en %s", ruta)
        return None
    return constancia


def escribir(ruta: Path, constancia: Constancia) -> None:
    """La escribe entera o no la escribe: a un temporal y luego en su sitio.

    Un corte a media escritura dejaría un JSON roto, que se leería como «sin
    constancia» y daría por entregado lo que no se sabe si lo está.
    """
    nueva = not ruta.parent.exists()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if nueva and ruta.parent.name == CARPETA_DE_ACTAS:
        _ocultar(ruta.parent)
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(json.dumps(constancia.as_dict(), ensure_ascii=False), encoding="utf-8")
    # Windows no deja reemplazar un archivo oculto: se le quita la marca antes.
    _ocultar(ruta, oculto=False)
    os.replace(temporal, ruta)
    _ocultar(ruta)


#: El atributo de Windows que esconde un archivo en el explorador.
_OCULTO = 0x2
_NORMAL = 0x80


def _ocultar(ruta: Path, *, oculto: bool = True) -> None:
    """Esconde la constancia en el explorador de Windows: es del bot, no del cliente.

    En otros sistemas el punto delante del nombre ya la esconde.
    """
    if os.name != "nt" or not ruta.exists():
        return
    try:
        import ctypes

        atributos = _OCULTO if oculto else _NORMAL
        if ruta.is_dir() and not oculto:
            return
        ctypes.windll.kernel32.SetFileAttributesW(str(ruta), atributos | (0x10 if ruta.is_dir() else 0))
    except Exception:  # noqa: BLE001 - esconderla es cortesía, no requisito
        logger.debug("no se pudo cambiar la visibilidad de %s", ruta, exc_info=True)


def archivos_de(carpeta: Path, rutas: list[Path]) -> list[dict]:
    """Lo entregado, con su tamaño, relativo a ``carpeta``."""
    archivos = []
    for ruta in rutas:
        try:
            tamano = ruta.stat().st_size
        except OSError:
            continue
        try:
            relativa = ruta.relative_to(carpeta)
        except ValueError:
            relativa = Path(ruta.name)
        archivos.append({"ruta": relativa.as_posix(), "bytes": tamano})
    return archivos


def vigencia(
    constancia: Constancia | None,
    origen: Path,
    carpeta: Path,
    *,
    huella: tuple[int, int] | None = None,
) -> Vigencia:
    """Si lo que dice la constancia sigue siendo verdad en el disco.

    Los archivos se comprueban con un solo listado de la carpeta cuando están
    en ella -- lo normal --, y uno por uno sólo los que van en subcarpetas.
    ``huella`` es la del origen si ya se sabe -- la trajo el listado de la
    carpeta --; si no, se mira.
    """
    return verificar(constancia, origen, carpeta, huella=huella).vigencia


@dataclass(frozen=True, slots=True)
class Verificacion:
    """Lo que dice la constancia de un PDF, y por qué: lo que lee el operador."""

    vigencia: Vigencia
    motivo: str
    #: Si algún archivo está con el nombre de paso de un orden de la carpeta del
    #: NIC que se cortó: está entregado, pero hay que terminar de ordenarla.
    a_medio_ordenar: bool = False


#: El nombre de paso de un archivo mientras se ordena la carpeta de un NIC:
#: «.ordenando-<puesto>-<nombre>» (ver ``FolderRunner._ordenar_la_caja``).
PREFIJO_DE_PASO = ".ordenando-"


def ruta_de_entrega(carpeta: Path, ruta: object) -> Path | None:
    """Resuelve sólo rutas relativas y contenidas en la carpeta de entrega."""
    if not isinstance(ruta, str):
        return None
    normalizada = ruta.replace("\\", "/")
    partes = normalizada.split("/")
    relativa_windows = PureWindowsPath(normalizada)
    if (
        not normalizada
        or relativa_windows.is_absolute()
        or relativa_windows.drive
        or any(parte in ("", ".", "..") for parte in partes)
    ):
        return None
    return carpeta.joinpath(*partes)


def _cuando(fecha: str) -> str:
    """La fecha de la constancia -- guardada en UTC -- en la hora local, que es la que lee el operador.

    Sin esto el análisis decía «entregado completo el … 18:46» de algo
    entregado a la 13:46 en Colombia.
    """
    try:
        return datetime.fromisoformat(fecha).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(fecha)[:16].replace("T", " ")


def _peso(tamano: int) -> str:
    return f"{tamano / 1024 / 1024:.1f} MB" if tamano >= 1024 * 1024 else f"{max(1, tamano // 1024)} KB"


def verificar(
    constancia: Constancia | None,
    origen: Path,
    carpeta: Path,
    *,
    huella: tuple[int, int] | None = None,
) -> Verificacion:
    """Si lo que dice la constancia sigue siendo verdad en el disco, y por qué no si no lo es.

    Lo pidió el operador el 2026-10-22: que la verificación de lo ya procesado
    sea «más detallada, más informativa», y que cubra «todas las posibles
    excepciones». Cada respuesta dice qué la decidió: el archivo que falta, el
    que cambió de tamaño, el origen que cambió, la entrega que se cortó.

    Un origen con el mismo tamaño y otra fecha -- se copió o se movió, no se
    volvió a escanear -- no se rehace si su SHA-256 completo coincide con el
    que se entregó.
    """
    if constancia is None:
        return Verificacion(Vigencia.SIN_CONSTANCIA, "no tiene constancia de entrega: no se había entregado")
    if not isinstance(constancia.fecha, str):
        return Verificacion(Vigencia.INCOMPLETA, "la constancia tiene una fecha inválida")
    # Una entrega completa sin archivos es válida: el inventario de actas sin
    # dividir no copia ningún PDF. Rehacerla volvería a pagar su lectura.
    if not isinstance(constancia.archivos, list):
        return Verificacion(Vigencia.INCOMPLETA, "la constancia tiene una lista de archivos inválida")
    if constancia.estado != EstadoDeEntrega.COMPLETA:
        return Verificacion(
            Vigencia.INCOMPLETA, f"la entrega anterior se cortó a mitad ({_cuando(constancia.fecha)})"
        )
    try:
        tamano, modificado = huella if huella and huella != (0, 0) else huella_del_origen(origen)
    except (OSError, red_smb.CredencialesDeRed) as error:
        # Sin poder mirar el origen no se sabe si cambió: se procesa, y será su
        # lectura la que diga qué le pasa.
        return Verificacion(Vigencia.ORIGEN_CAMBIADO, f"no se pudo mirar el PDF de origen ({error})")
    if tamano != constancia.tamano:
        return Verificacion(
            Vigencia.ORIGEN_CAMBIADO,
            f"el PDF de origen cambió de tamaño: {_peso(constancia.tamano)} → {_peso(tamano)}",
        )
    if modificado != constancia.modificado_ns and not (
        constancia.firma and _firma_o_nada(origen) == constancia.firma
    ):
        return Verificacion(Vigencia.ORIGEN_CAMBIADO, "el PDF de origen tiene otra fecha de modificación")
    try:
        en_la_carpeta = {entrada.name: entrada for entrada in os.scandir(carpeta)}
    except OSError as error:
        return Verificacion(Vigencia.INCOMPLETA, f"no se pudo leer la carpeta de destino ({error})")
    # Los que un orden cortado de la carpeta del NIC dejó con su nombre de paso:
    # están entregados, con otro nombre por un momento.
    de_paso = {
        nombre.split("-", 2)[2]: entrada
        for nombre, entrada in en_la_carpeta.items()
        if nombre.startswith(PREFIJO_DE_PASO) and nombre.count("-") >= 2
    }
    a_medio_ordenar = False
    for archivo in constancia.archivos:
        if (
            not isinstance(archivo, dict)
            or not isinstance(archivo.get("ruta"), str)
            or type(archivo.get("bytes")) is not int
            or archivo["bytes"] < 0
        ):
            return Verificacion(Vigencia.INCOMPLETA, "la constancia tiene un registro de archivo inválido")
        ruta = archivo["ruta"].replace("\\", "/")
        destino = ruta_de_entrega(carpeta, ruta)
        if destino is None:
            return Verificacion(Vigencia.INCOMPLETA, "la constancia tiene una ruta de archivo inválida")
        try:
            if "/" in ruta:
                if not destino.is_file():
                    return Verificacion(Vigencia.INCOMPLETA, f"falta «{ruta}» en el destino")
                tamano = destino.stat().st_size
            else:
                nombre = destino.name
                entrada = en_la_carpeta.get(nombre)
                if entrada is None and nombre in de_paso:
                    entrada, a_medio_ordenar = de_paso[nombre], True
                if entrada is None:
                    return Verificacion(Vigencia.INCOMPLETA, f"falta «{ruta}» en el destino")
                tamano = entrada.stat().st_size
        except FileNotFoundError:
            return Verificacion(Vigencia.INCOMPLETA, f"falta «{ruta}» en el destino")
        except OSError as error:
            return Verificacion(Vigencia.INCOMPLETA, f"no se pudo verificar «{ruta}» en el destino ({error})")
        if tamano != archivo["bytes"]:
            return Verificacion(
                Vigencia.INCOMPLETA,
                f"«{ruta}» cambió en el destino: {_peso(archivo['bytes'])} → {_peso(tamano)}",
            )
    pdfs = sum(1 for archivo in constancia.archivos if str(archivo.get("ruta") or "").lower().endswith(".pdf"))
    motivo = f"entregado completo el {_cuando(constancia.fecha)} ({pdfs} PDF)"
    if a_medio_ordenar:
        motivo += "; su carpeta quedó a medio ordenar y se termina de ordenar"
    return Verificacion(Vigencia.VIGENTE, motivo, a_medio_ordenar=a_medio_ordenar)


def firma_del_origen(path: Path) -> str:
    """SHA-256 del PDF: permite reconocer una copia idéntica aunque cambie su fecha."""
    import hashlib

    resumen = hashlib.sha256()
    if red_smb.por_smb(path):
        return red_smb.firma(str(path))
    with path.open("rb") as archivo:
        while bloque := archivo.read(1024 * 1024):
            resumen.update(bloque)
    return resumen.hexdigest()


def _firma_o_nada(path: Path) -> str | None:
    try:
        return firma_del_origen(path)
    except (OSError, red_smb.CredencialesDeRed):
        return None
