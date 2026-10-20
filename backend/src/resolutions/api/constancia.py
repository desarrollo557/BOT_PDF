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
from pathlib import Path

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
        return Constancia(**{clave: valor for clave, valor in datos.items() if clave in conocidos})
    except TypeError:
        return None


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
    if constancia is None:
        return Vigencia.SIN_CONSTANCIA
    if constancia.estado != EstadoDeEntrega.COMPLETA:
        return Vigencia.INCOMPLETA
    try:
        tamano, modificado = huella if huella and huella != (0, 0) else huella_del_origen(origen)
    except (OSError, red_smb.CredencialesDeRed):
        # Sin poder mirar el origen no se sabe si cambió: se procesa, y será su
        # lectura la que diga qué le pasa.
        return Vigencia.ORIGEN_CAMBIADO
    if tamano != constancia.tamano or modificado != constancia.modificado_ns:
        return Vigencia.ORIGEN_CAMBIADO
    try:
        en_la_carpeta = {entrada.name: entrada for entrada in os.scandir(carpeta)}
    except OSError:
        return Vigencia.INCOMPLETA
    for archivo in constancia.archivos:
        ruta = str(archivo.get("ruta") or "")
        try:
            if "/" in ruta:
                tamano = (carpeta / ruta).stat().st_size
            else:
                entrada = en_la_carpeta.get(ruta)
                if entrada is None:
                    return Vigencia.INCOMPLETA
                tamano = entrada.stat().st_size
        except OSError:
            return Vigencia.INCOMPLETA
        if tamano != archivo.get("bytes"):
            return Vigencia.INCOMPLETA
    return Vigencia.VIGENTE
