"""Lo que queda escrito junto a los PDF: la planilla del documento y el FUID.

Las escribe el worker y no el caso de uso, porque las dos son Excel y quien
habla con openpyxl es un adaptador; el caso de uso entrega la agrupación y el
informe, y aquí se convierten en el papel que acompaña la carpeta.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from pathlib import Path

from ...application.progress import Stage
from ...domain.naming import DOCUMENT_PREFIX
from .taller import _anunciar, _reportero

logger = logging.getLogger(__name__)

#: Cómo se llama el Formato Único de Inventario Documental que queda escrito
#: junto al trabajo. El endpoint de descarga lo busca por este sufijo, así que
#: los dos sitios tienen que decir lo mismo.
FUID_SUFFIX = "__FUID.xlsx"


def _escribir_fuid(
    report: dict,
    filas: list,
    *,
    settings: dict,
    destination: Path,
    name: str,
    document_type,
    control=None,
    payload: dict | None = None,
) -> None:
    """Deja el FUID junto a lo demás que produjo el trabajo.

    Que falle no invalida la lectura: el documento se leyó igual y su informe
    sirve. Se anota el motivo en vez de perder el trabajo entero.
    """
    if not filas:
        return
    if payload is not None:
        _anunciar(
            payload,
            Stage.INVENTORYING,
            detail="preparando la planilla",
            done=0,
            total=len(filas),
        )
    if control is not None:
        # Escribir el FUID es lo último que hace el trabajo. Si a estas alturas
        # ya se canceló, no tiene sentido dejar una planilla de un trabajo que
        # el operador dio por abandonado.
        control.check()

    from ...adapters.fuid_inventory import FuidInventory
    from ...application.fuid import Cabecera
    from ...application.inventory_document import default_template, template_for
    from ...domain.naming import sheet_filename

    # La plantilla la decide el tipo de documento que se reconoció, no un ajuste
    # global: en una caja mezclada, cada PDF necesita la suya.
    por_tipo = template_for(document_type) if document_type is not None else default_template()
    plantilla = Path(settings.get("fuid_template") or por_tipo)

    # El nombre que le puso el operador, no el generado con que se almacenó la
    # subida: un FUID llamado "6ea93142663d..." no le dice a nadie de qué libro
    # salió. Recortado a lo que la ruta admite, porque la carpeta de salida ya
    # lleva un identificador de 32 caracteres.
    destino = destination / sheet_filename(
        name, FUID_SUFFIX, directory_length=len(str(destination))
    )
    try:
        escrito = FuidInventory(plantilla, progress=_reportero(payload or {})).write(
            filas,
            destino,
            cabecera=Cabecera(oficina_productora=settings.get("fuid_oficina")),
        )
        report["fuid"] = escrito.name
    except Exception as error:  # noqa: BLE001 - la lectura sirvió igual
        logger.warning("no se pudo escribir el FUID", exc_info=True)
        report["fuid_error"] = f"{type(error).__name__}: {error}"


def _escribir_fuid_de_archivo(
    report: dict,
    filas: list,
    *,
    settings: dict,
    destination: Path,
    name: str,
    control=None,
    payload: dict | None = None,
) -> None:
    """El FUID de un archivo inventariado entero, en el formato F-PSD-001.

    Va por su propio camino y no por `_escribir_fuid` porque el formato es otro:
    veintisiete columnas en vez de dieciocho, sin cabecera en celdas sueltas y
    sin bloque de firmas que recolocar. Lo que comparten es el instructivo, no
    la plantilla, así que compartir el escritor obligaría a llenarlo de "si es
    el formato de la Universidad" en cada paso.

    Que falle no invalida la lectura, igual que en el otro: se anota el motivo.
    """
    if not filas:
        return
    if payload is not None:
        _anunciar(
            payload,
            Stage.INVENTORYING,
            detail="preparando la planilla",
            done=0,
            total=len(filas),
        )
    if control is not None:
        control.check()

    from ...adapters.fuid_psd001 import FuidPsd001
    from ...application.fuid import Cabecera
    from ...application.inventory_document import FORMATO_PSD001, template_named
    from ...domain.naming import sheet_filename

    # El formato lo puede fijar el operador en los ajustes; si no dice nada, el
    # de esta acción es el F-PSD-001, que es para el que se hizo.
    plantilla = template_named(settings.get("fuid_formato")) or template_named(FORMATO_PSD001)
    if settings.get("fuid_template"):
        plantilla = Path(settings["fuid_template"])

    destino = destination / sheet_filename(
        name, FUID_SUFFIX, directory_length=len(str(destination))
    )
    try:
        escrito = FuidPsd001(plantilla, progress=_reportero(payload or {})).write(
            filas,
            destino,
            cabecera=Cabecera(
                oficina_productora=settings.get("fuid_oficina"),
                entidad_productora=settings.get("fuid_entidad_productora"),
                entidad_remitente=settings.get("fuid_entidad_remitente"),
                unidad_administrativa=settings.get("fuid_unidad_administrativa"),
                objeto=settings.get("fuid_objeto"),
                serie=settings.get("fuid_serie"),
                subserie=settings.get("fuid_subserie"),
                elaborado_por=settings.get("fuid_elaborado_por"),
            ),
        )
        report["fuid"] = escrito.name
    except Exception as error:  # noqa: BLE001 - la lectura sirvió igual
        logger.warning("no se pudo escribir el FUID del archivo", exc_info=True)
        report["fuid_error"] = f"{type(error).__name__}: {error}"


def _escribir_planilla(report: dict, destination: Path, payload: dict) -> None:
    """Deja la planilla del inventario junto a los PDF que describe.

    Se escribe sola, al terminar, sin que nadie la pida. Es lo que el operador
    necesita para entregar la caja: un listado de qué salió, de qué páginas
    salió cada cosa y qué tipo documental resultó ser, en un archivo que se
    abre en Excel. La escriben las cuatro rutas por aquí -- la de resoluciones
    la escribía desde su caso de uso, y por eso se quedó sin la carpeta de
    destino cuando las otras tres empezaron a declararla.

    Que falle no invalida nada: los PDF ya están escritos y el informe también.
    Se anota y se sigue, igual que con el FUID.
    """
    try:
        from ...adapters.excel_inventory import ExcelInventory
    except ImportError:
        # openpyxl no está instalado: el documento se parte igual, sólo que
        # sin su planilla.
        return
    _anunciar(payload, Stage.INVENTORYING, detail="escribiendo la planilla")
    try:
        ExcelInventory().write(
            report,
            destination,
            # A dónde va la entrega, cuando va a alguna parte. En una subida
            # suelta no hay carpeta de destino que declarar y la columna se
            # queda con su raya; en una corrida sobre carpeta local sí la hay,
            # y es justo el caso en que el operador necesita leerla.
            delivered_to=payload.get("destination"),
            operator=payload.get("operator"),
            processed_at=datetime.now(UTC).isoformat(),
        )
    except Exception:  # noqa: BLE001 - la entrega ya está en el disco
        logger.warning("no se pudo escribir la planilla del inventario", exc_info=True)


def _escribir_indice(report: dict, destination: Path, payload: dict) -> None:
    """Deja el Índice Electrónico del cliente junto a los PDF de una caja.

    Es el inventario de toda caja de correspondencia, en el formato que el
    archivo de Afinia hacía a mano -- «00.INDICE ELECTRONICO.xlsx» -- y en lugar
    de la planilla de las otras rutas: una fila por archivo entregado, en el
    orden en que venían las hojas. Cada columna sale de donde se acordó:

    - el nombre es el tipo documental del catálogo, y en un trámite con su
      número RE: «RECLAMO RE3110202138312»;
    - la creación, la fecha que se ve en el documento: la de su sello de
      radicación, la marcada en su guía de envío, o la de su primera hoja
      (S.F. si no trae ninguna);
    - la incorporación al expediente, el día en que el bot lo crea;
    - las observaciones, vacías: son las del negocio, las escribe el archivo;
    - el responsable, quien procesa la caja; la territorial, la que escribió.

    El NIC no se escribe: la celda queda vacía y se llena a mano. El nombre
    del expediente es el de la caja: «UPD2326399».

    Que falle no invalida nada, igual que la planilla: se anota y se sigue.
    """
    try:
        from ...adapters.indice_electronico import FilaDelIndice, escribir_indice
    except ImportError:
        return
    _anunciar(payload, Stage.INVENTORYING, detail="escribiendo el índice electrónico")
    hoy = date.today()
    operador = (payload.get("operator") or "").strip()
    items = ((report.get("inventory") or {}).get("items")) or []
    filas = [
        FilaDelIndice(
            nombre=_nombre_de_la_fila(item, report),
            # Lo dictó el operador: la creación es la fecha que se ve en el
            # documento -- la del sello, la marcada en la guía de envío --;
            # la incorporación al expediente, el día en que el bot lo crea.
            fecha_creacion=_fecha_de_la_fila(item, report),
            fecha_incorporacion=hoy,
            orden=orden,
            paginas=int(item.get("page_count") or 0),
            # Vacía: es la columna de las observaciones del negocio, las que
            # escribe el archivo, no un rastro técnico del bot. El archivo de la
            # fila, el detalle del trámite y la verificación de anexos van al
            # informe y a la revisión, no aquí.
            observaciones="",
            responsable=operador,
        )
        for orden, item in enumerate(items, start=1)
    ]
    try:
        from ...domain.territorial import territorial_de_la_ruta

        escrito = escribir_indice(
            destination,
            filas,
            # El municipio, la carpeta que contiene la caja («…\COMERCIAL\
            # MAGANGUE\210847\UPD….pdf»). Sólo en una corrida de carpeta (con
            # destino): un archivo subido vive en la carpeta de subidas, cuya
            # ruta no dice nada. Si no, lo que escribió el operador.
            territorial=(
                territorial_de_la_ruta(str(payload.get("source") or ""))
                if payload.get("destination")
                else None
            )
            or (payload.get("territorial") or "").strip()
            or None,
            nombre_del_expediente=report.get("expediente") or None,
        )
        report["indice_electronico"] = escrito.name
    except Exception as error:  # noqa: BLE001 - la entrega ya está en el disco
        logger.warning("no se pudo escribir el índice electrónico", exc_info=True)
        report["indice_electronico_error"] = f"{type(error).__name__}: {error}"


def _fecha_iso(valor: object) -> date | None:
    """La fecha del inventario, que viaja en ISO; ``None`` si no hay o no se lee."""
    try:
        return date.fromisoformat(str(valor)[:10]) if valor else None
    except ValueError:
        return None


#: El número de un trámite en el código de su archivo: «01 RE3110202138312
#: 02-09-2021», «02 P43102019110005», «03 SIN-RADICADO-2022-08-18».
_RADICADO_DEL_CODIGO = re.compile(r"\b(RE\d{13}|P\d{14}|SIN-RADICADO)", re.IGNORECASE)


def _piezas_de(item: dict, report: dict) -> list[dict]:
    """Los documentos del corte que caen en el archivo de esta fila, en orden."""
    suyas = set(item.get("page_numbers") or [])
    return [
        pieza for pieza in report.get("piezas") or [] if suyas.intersection(pieza.get("pages") or [])
    ]


def _primera_pieza(item: dict, report: dict) -> dict:
    """El documento con que abre el archivo: el de su primera hoja."""
    return next(iter(_piezas_de(item, report)), {})


def _fecha_de_la_fila(item: dict, report: dict) -> date | None:
    """La fecha del documento con que abre el archivo; si no trae, la del archivo."""
    return _fecha_iso(_primera_pieza(item, report).get("fecha")) or _fecha_iso(item.get("fecha"))


def _radicado_de_la_fila(item: dict, report: dict) -> str | None:
    """El RE del trámite; fuera de un trámite, el del documento si lo trae."""
    if report.get("agrupar") == "tramite":
        hallado = _RADICADO_DEL_CODIGO.search(str(item.get("code") or ""))
        if hallado is not None:
            radicado = hallado.group(1).upper()
            return "SIN RADICADO" if radicado == "SIN-RADICADO" else radicado
    radicado = _primera_pieza(item, report).get("radicado")
    return str(radicado).upper() if radicado else None


def _nombre_de_la_fila(item: dict, report: dict) -> str:
    """Título directo, radicado y fecha: «DERECHO DE PETICION - RE3110202043677 - 02/12/2020».

    Lo pidió el operador mirando la primera imagen de cada documento: el
    título es lo que el documento dice ser en su primera hoja, no una frase de
    su petición. Todo en mayúsculas.
    """
    titulo = _primera_pieza(item, report).get("titulo") or item.get("type") or DOCUMENT_PREFIX
    partes = [str(titulo)]
    radicado = _radicado_de_la_fila(item, report)
    if radicado:
        partes.append(radicado)
    fecha = _fecha_de_la_fila(item, report)
    if fecha:
        partes.append(f"{fecha:%d/%m/%Y}")
    return " - ".join(partes).upper()
