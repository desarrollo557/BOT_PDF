"""El FUID de cualquier habilidad: una plantilla, una forma de fila y un escritor.

Lo pidió el operador el 2026-10-29 sobre el REPOSITORIO UDC: «estandarízame
todas esas habilidades, que la idea es volver a usarlo», con el mismo FUID para
cada carpeta y su inventario general. Las habilidades que inventarían papel de
la Universidad -- actas de consejo, actas de grado, historias académicas,
matrículas, recibos, archivos que no se parten -- escriben todas el FO-GD-008
(``assets/fuid-fo-gd-008.xlsx``, la plantilla que dio el operador), con la
oficina productora de su carpeta en la cabecera.

Cada habilidad deja sus filas en el informe de cada PDF (``inventario_actas``),
cada una con su ``tipo``. Aquí se juntan:

* ``fila_del_fuid`` convierte una fila a la del FUID según su tipo. La que no
  lleva fila -- las hojas de una ceremonia de grado, lo de antes de la primera
  ficha de un estudiante -- da ``None``.
* ``filas_del_fuid`` convierte las de una carpeta o una corrida entera,
  numeradas desde 1 y con el nombre de su archivo en NOTAS («Archivo: …»), que
  es lo que deja cruzar la planilla con la carpeta.
* ``escribir_fuid`` las escribe en la plantilla.

Las columnas siguen la fila guía de la plantilla del operador: el orden desde
1; «nombre - título» en el asunto; la cédula y el código en el consecutivo; la
caja y la UPD; los folios. Lo que cada tipo pone en ellas está en su adaptador:
``fuid_actas_de_consejo``, ``fuid_actas_de_grado``, ``fuid_historias``. Un tipo
nuevo que no necesite reglas propias usa ``fila_generica`` con los nombres de
campo de abajo, sin tocar nada más.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from ..application.acta_consejo import TIPO_DOCUMENTAL
from ..application.fuid import Cabecera, FuidRow
from ..application.inventory_document import template_for
from ..domain.doctype import DocumentType
from ..domain.historia_academica import HISTORIA_ACADEMICA, SIN_ESTUDIANTE
from . import fuid_actas_de_consejo, fuid_actas_de_grado, fuid_historias
from .fuid_actas_de_grado import NO_LEIDO, ubicacion
from .fuid_inventory import FuidInventory

#: El sufijo del FUID de cada subcarpeta: «UPD3859753__FUID.xlsx», como el de
#: cada libro de diplomas.
SUFIJO_DEL_FUID = "__FUID.xlsx"

_DIVIDIDO = re.compile(r"^Dividido en (.+\.pdf)$", re.IGNORECASE)
_FECHA = re.compile(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})")


def _entero(valor: object) -> int | None:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def _fecha(valor: object, *, final: bool) -> str:
    """«03-03-2005», «3/3/2005» o un año suelto a «03/03/2005»; N/A si no hay fecha."""
    if anio := _entero(valor):
        return f"31/12/{anio}" if final else f"01/01/{anio}"
    if hallada := _FECHA.fullmatch(str(valor or "").strip()):
        dia, mes, anio_texto = hallada.groups()
        return f"{int(dia):02d}/{int(mes):02d}/{anio_texto}"
    return NO_LEIDO


def fila_generica(fila: Mapping[str, object]) -> FuidRow:
    """La fila de un tipo sin reglas propias: matrícula, recibo, un archivo entero.

    Campos que lee: ``asunto`` (si no, el tipo y el ``nombre``), ``cedula``,
    ``codigo`` (o, si no hay, ``consecutivo``), ``fecha_inicial`` y
    ``fecha_final`` (fecha o año), ``folios``, ``observaciones``, ``carpeta`` y
    ``archivo``.
    """
    caja, upd = ubicacion(str(fila.get("carpeta") or ""), str(fila.get("archivo") or ""))
    asunto = str(fila.get("asunto") or "").strip()
    if not asunto:
        nombre = str(fila.get("nombre") or "").strip() or NO_LEIDO
        asunto = f"{nombre} - {fila.get('tipo') or 'DOCUMENTO'}"
    consecutivo = str(fila.get("consecutivo") or "").strip()
    folios = _entero(fila.get("folios"))
    return FuidRow(
        orden=0,
        asunto=asunto,
        codigo_trd="",
        consecutivo_inicial=str(fila.get("cedula") or "").strip() or consecutivo or NO_LEIDO,
        consecutivo_final=str(fila.get("codigo") or "").strip() or consecutivo or NO_LEIDO,
        fecha_inicial=_fecha(fila.get("fecha_inicial"), final=False),
        fecha_final=_fecha(fila.get("fecha_final") or fila.get("fecha_inicial"), final=True),
        caja=caja,
        carpeta=upd,
        tomo="",
        otro="",
        folios=folios if folios else NO_LEIDO,  # type: ignore[arg-type]
        folios_siar=folios if folios else NO_LEIDO,  # type: ignore[arg-type]
        soporte="",
        frecuencia="",
        notas=str(fila.get("observaciones") or ""),
        pagina_inicial=_entero(fila.get("pagina_inicial")),
    )


def _sin_fila(_fila: Mapping[str, object]) -> None:
    return None


#: El tipo de las filas que llegan ya hechas: las del FUID que escribió su
#: propia habilidad -- un legajo de resoluciones, un archivo inventariado entero,
#: un legajo de matrículas --, guardadas en ``fuid`` tal cual.
FILA_HECHA = "FILA DEL FUID"

#: El tipo de la fila de un PDF que su habilidad no supo partir -- unas
#: historias académicas sin una ficha reconocible -- y se inventaría entero:
#: ningún PDF de la Universidad se queda sin su fila (2026-10-30).
PDF_ENTERO = "PDF ENTERO"

_CAMPOS = frozenset(FuidRow.__dataclass_fields__)

#: Lo que lleva delante el nombre de un PDF y no es su asunto: la UPD
#: («UPD3859752-», «UPD 3859601 », «UPD0077188 - ») y el número de orden pegado
#: («1HISTORIAS ACADEMICAS 1993»).
_UPD_DELANTE = re.compile(r"^\s*UPD\s?\d{7}\s*[-–_]?\s*", re.IGNORECASE)
_ORDEN_PEGADO = re.compile(r"^\d{1,2}(?=[^\W\d_])")
#: Un año del nombre: 1900 a 2030. Pegados («19441969») o con el segundo en dos
#: cifras detrás de un guion («1924-46»).
_ANIO = r"(?:19\d{2}|20[0-3]\d)"
_DOS_PEGADOS = re.compile(rf"(?<!\d)({_ANIO})({_ANIO})(?!\d)")
_CON_CORTO = re.compile(rf"(?<!\d)({_ANIO})\s*-\s*(\d{{2}})(?!\d)")
_CUATRO_CIFRAS = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def asunto_del_nombre(archivo: str) -> str:
    """«UPD3860000-EXAMENES PREPARATORIOS DE GRADO 1924-46.pdf» → «EXAMENES PREPARATORIOS DE GRADO 1924-46»."""
    nombre = Path(str(archivo or "")).stem
    nombre = _ORDEN_PEGADO.sub("", _UPD_DELANTE.sub("", nombre))
    return " ".join(nombre.split()).upper() or NO_LEIDO


def anios_del_nombre(archivo: str) -> tuple[int | None, int | None]:
    """El primer y el último año que dice el nombre del PDF.

    Un número de cuatro cifras que no es un año posible -- «1926-1395», que
    el cliente inventarió como 1926 a 1935 -- deja ese extremo en ``None``: no
    se adivina cuál quiso escribir.
    """
    nombre = Path(str(archivo or "")).stem
    #: Cada año por dónde aparece, y ``None`` donde hay un número imposible.
    vistos: list[tuple[int, int | None]] = []
    for hallado in _DOS_PEGADOS.finditer(nombre):
        vistos += [(hallado.start(1), int(hallado.group(1))), (hallado.start(2), int(hallado.group(2)))]
    nombre = _DOS_PEGADOS.sub(lambda m: " " * len(m.group(0)), nombre)
    for hallado in _CON_CORTO.finditer(nombre):
        largo = int(hallado.group(1))
        corto = int(hallado.group(1)[:2] + hallado.group(2))
        vistos += [(hallado.start(1), largo), (hallado.start(2), corto if corto >= largo else corto + 100)]
    nombre = _CON_CORTO.sub(lambda m: " " * len(m.group(0)), nombre)
    for hallado in _CUATRO_CIFRAS.finditer(nombre):
        numero = int(hallado.group(1))
        vistos.append((hallado.start(1), numero if 1900 <= numero <= 2030 else None))
    vistos.sort()
    anios = [anio for _donde, anio in vistos if anio is not None]
    if not anios:
        return None, None
    if len(anios) == 1 and len(vistos) > 1:
        # Uno se lee y el otro no: el que se lee dice el extremo de su lado.
        return (anios[0], None) if vistos[0][1] is not None else (None, anios[0])
    return min(anios), max(anios)


def _fechas_del_nombre(archivo: str) -> tuple[str, str]:
    inicial, final = anios_del_nombre(archivo)
    return (
        f"01/01/{inicial}" if inicial else NO_LEIDO,
        f"31/12/{final}" if final else NO_LEIDO,
    )


def fila_del_pdf_entero(fila: Mapping[str, object]) -> FuidRow:
    """La fila de un PDF inventariado entero: el asunto y los años de su nombre.

    Es lo que ya hace el inventario del cliente -- «HISTORIAS ACADEMICAS
    1948-1960», 95 folios, 1948 a 1960 --, y lo que queda cuando el papel no se
    deja partir: mejor una fila por PDF que dice de dónde sacó cada dato que un
    PDF sin fila.
    """
    archivo = str(fila.get("archivo") or "")
    caja, upd = ubicacion(str(fila.get("carpeta") or ""), archivo)
    inicial, final = _fechas_del_nombre(archivo)
    folios = _entero(fila.get("folios"))
    hojas = _entero(fila.get("folios_del_cliente"))
    notas = str(fila.get("observaciones") or "")
    if hojas:
        notas = "; ".join(parte for parte in (notas, _NOTA_DE_LOS_FOLIOS) if parte)
    return FuidRow(
        orden=0,
        asunto=asunto_del_nombre(archivo),
        codigo_trd="",
        consecutivo_inicial=NO_LEIDO,
        consecutivo_final=NO_LEIDO,
        fecha_inicial=inicial,
        fecha_final=final,
        caja=caja,
        carpeta=upd,
        tomo="",
        otro="",
        folios=hojas or (folios if folios else NO_LEIDO),  # type: ignore[arg-type]
        folios_siar=folios if folios else NO_LEIDO,  # type: ignore[arg-type]
        soporte="",
        frecuencia="",
        notas=notas,
        pagina_inicial=_entero(fila.get("pagina_inicial")),
    )


#: Lo que dice la nota cuando los folios son los del inventario del cliente.
_NOTA_DE_LOS_FOLIOS = (
    "No. de folios: las hojas del inventario del cliente; No. de folios SIAR: las páginas escaneadas"
)


def fila_hecha(fila: Mapping[str, object]) -> FuidRow | None:
    """La fila que ya escribió su habilidad, con la caja y la UPD de su carpeta.

    Su habilidad no sabe en qué caja está el PDF -- la saca de los ajustes,
    que en una corrida de carpeta no la dicen -- y aquí sí se sabe, por la
    ruta: «00C003303» y «UPD3859990». Lo demás se respeta, salvo lo que un
    archivo inventariado entero no dejó leer de su encabezado -- un libro
    manuscrito de 1924 --: el asunto y los años salen entonces de su nombre, y
    la nota lo dice.
    """
    from ..application.archivo_fuid import SIN_ASUNTO

    datos = fila.get("fuid")
    if not isinstance(datos, Mapping):
        return None
    hecha = FuidRow(**{campo: valor for campo, valor in datos.items() if campo in _CAMPOS})
    archivo = str(fila.get("archivo") or "")
    caja, upd = ubicacion(str(fila.get("carpeta") or ""), archivo)
    hecha = replace(hecha, caja=caja or hecha.caja, carpeta=upd or hecha.carpeta)
    if not fila.get("entero") or not archivo:
        return hecha
    # Opción B del operador (2026-10-30): las hojas del cliente en «No. de
    # folios» y las páginas escaneadas en «No. de folios SIAR».
    if hojas := _entero(fila.get("folios_del_cliente")):
        paginas = hecha.folios_siar if _entero(hecha.folios_siar) else hecha.folios
        hecha = replace(
            hecha,
            folios=hojas,
            folios_siar=paginas,
            notas="; ".join(parte for parte in (hecha.notas, _NOTA_DE_LOS_FOLIOS) if parte),
        )
    tomado: list[str] = []
    if hecha.asunto.strip() in ("", SIN_ASUNTO, NO_LEIDO):
        hecha = replace(hecha, asunto=asunto_del_nombre(archivo))
        tomado.append("el asunto")
    inicial, final = _fechas_del_nombre(archivo)
    if hecha.fecha_inicial == NO_LEIDO and inicial != NO_LEIDO:
        hecha = replace(hecha, fecha_inicial=inicial)
        tomado.append("la fecha inicial")
    if hecha.fecha_final == NO_LEIDO and final != NO_LEIDO:
        hecha = replace(hecha, fecha_final=final)
        tomado.append("la fecha final")
    if tomado:
        nota = f"{', '.join(tomado)}, del nombre del archivo: el papel no los dejó leer"
        hecha = replace(hecha, notas="; ".join(parte for parte in (hecha.notas, nota[0].upper() + nota[1:]) if parte))
    return hecha


#: Qué adaptador convierte cada tipo de fila. El que no está aquí va a
#: ``fila_generica``; una fila sin tipo es de un acta de consejo, que es como
#: llegan las de los informes viejos.
CONVERSORES: dict[str, Callable[[Mapping[str, object]], FuidRow | None]] = {
    TIPO_DOCUMENTAL: fuid_actas_de_consejo.fila_del_fuid,
    fuid_actas_de_grado.ACTA_DE_GRADO: fuid_actas_de_grado.fila_del_fuid,
    fuid_actas_de_grado.CEREMONIA: _sin_fila,
    HISTORIA_ACADEMICA: fuid_historias.fila_del_fuid,
    SIN_ESTUDIANTE: _sin_fila,
    FILA_HECHA: fila_hecha,
    PDF_ENTERO: fila_del_pdf_entero,
}


def archivo_de(fila: Mapping[str, object]) -> str:
    """El archivo de la fila: el PDF en que quedó, o el original y sus páginas."""
    generado = str(fila.get("archivo_generado") or "")
    if not generado and (dividido := _DIVIDIDO.match(str(fila.get("resultado") or ""))):
        generado = dividido.group(1)
    if generado:
        return generado
    archivo = str(fila.get("archivo") or "")
    desde, hasta = _entero(fila.get("pagina_inicial")), _entero(fila.get("pagina_final"))
    if not archivo or desde is None or fila.get("entero"):
        return archivo
    if hasta is None or hasta == desde:
        return f"{archivo}, pág. {desde}"
    return f"{archivo}, págs. {desde} a {hasta}"


def fila_del_fuid(fila: Mapping[str, object]) -> FuidRow | None:
    """La fila del FUID de cualquier tipo, con su archivo en NOTAS; ``None`` si no lleva fila."""
    conversor = CONVERSORES.get(str(fila.get("tipo") or TIPO_DOCUMENTAL), fila_generica)
    convertida = conversor(fila)
    if convertida is None:
        return None
    # La caja que anota el cliente cuando la ruta no la dice: «20.ACTAS DE
    # GRADO 3362» trae sus PDF sueltos, sin subcarpeta de caja (2026-10-30).
    if convertida.caja in ("", NO_LEIDO) and fila.get("caja_del_cliente"):
        convertida = replace(convertida, caja=str(fila["caja_del_cliente"]))
    archivo = archivo_de(fila)
    # Una fila hecha que ya dice su archivo -- la resolución partida en
    # «03_RESOLUCION-00031.pdf» -- no lleva además el del original.
    if archivo and "Archivo: " not in convertida.notas:
        convertida = replace(
            convertida, notas="; ".join(parte for parte in (convertida.notas, f"Archivo: {archivo}") if parte)
        )
    return convertida


def filas_del_fuid(filas: Sequence[Mapping[str, object]]) -> list[FuidRow]:
    """Las filas del FUID, en el orden en que llegan y numeradas desde 1."""
    resultado: list[FuidRow] = []
    for fila in filas:
        convertida = fila_del_fuid(fila)
        if convertida is not None:
            resultado.append(replace(convertida, orden=len(resultado) + 1))
    return resultado


def plantilla_del_fuid() -> Path:
    """La plantilla FO-GD-008 que dio el operador, la misma para todas las habilidades."""
    return template_for(DocumentType.ACTA)


def escribir_fuid(
    filas: Sequence[Mapping[str, object]] | Sequence[FuidRow],
    destino: Path,
    *,
    oficina: str | None = None,
    plantilla: Path | None = None,
) -> Path:
    """Escribe el FUID en ``destino`` con la oficina productora de su carpeta.

    ``filas`` son las de las habilidades (diccionarios con su ``tipo``) o filas
    del FUID ya hechas, que se escriben tal cual.
    """
    if all(isinstance(fila, FuidRow) for fila in filas):
        hechas = list(filas)
    else:
        hechas = filas_del_fuid(filas)  # type: ignore[arg-type]
    return FuidInventory(plantilla or plantilla_del_fuid()).write(
        hechas, destino, cabecera=Cabecera(oficina_productora=oficina or None)
    )


def ruta_del_fuid(carpeta: Path) -> Path:
    """«…\\UPD3859753\\UPD3859753__FUID.xlsx»: el FUID de una subcarpeta, dentro de ella."""
    from ..domain.naming import sheet_filename

    return carpeta / sheet_filename(carpeta.name, SUFIJO_DEL_FUID, directory_length=len(str(carpeta)))
