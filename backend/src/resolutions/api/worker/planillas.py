"""Lo que queda escrito junto a los PDF: la planilla del documento y el FUID.

Las escribe el worker y no el caso de uso, porque las dos son Excel y quien
habla con openpyxl es un adaptador; el caso de uso entrega la agrupación y el
informe, y aquí se convierten en el papel que acompaña la carpeta.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from ...application.progress import Stage
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
