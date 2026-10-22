"""Inventario Kingspan: una fila por bloque de documentos consecutivos.

La caja de correspondencia puede inventariarse con dos plantillas. La de
siempre es el Índice Electrónico, que reparte la caja en trámites. La de
Kingspan es otra cosa: cada documento lleva impreso un número ``OOl-NI-NNNNN``
y lo que se entrega es una tabla con el número -- o el rango de números
consecutivos --, el PDF del que salió y su orden.

Este módulo no reutiliza el inventario de libros de registro porque la unidad
documental no es la misma: allí una fila es un graduado leído del papel, aquí
una fila es un tramo de numeración que se extrae del texto impreso. Tampoco
necesita un Excel de entrada: la plantilla se escribe desde cero.

Lo que sí comparte con las demás habilidades es el taller -- de dónde viene el
PDF, dónde se entrega, por dónde avisa y cómo se lee --, que es lo que hace que
un trabajo de esta ruta se comporte como cualquier otro.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ...application.progress import ProgressEvent, Stage
from .taller import Taller

logger = logging.getLogger(__name__)

#: El número impreso del documento. Se acepta cualquier lectura de las letras
#: que el escáner suele confundir: ``O``/``0`` y ``l``/``1``/``I``. El segmento
#: ``-NI-`` es lo bastante distintivo como para que la tolerancia no arrastre
#: números de factura que no son documentos.
_DOCUMENT_NUMBER = re.compile(r"[O0]{2}\s*[l1I]\s*-\s*NI\s*-\s*(\d+)", re.IGNORECASE)

#: Cómo se llama el libro que se deja junto a los PDF.
INVENTORY_SUFFIX = "_INVENTARIO_KINGSPAN.xlsx"


@dataclass(frozen=True, slots=True)
class DocumentRange:
    """Un tramo de numeración consecutiva, que es una fila del inventario."""

    start: int
    end: int

    @property
    def label(self) -> str:
        """El número, o el rango, como se escribe en «No. DOCUMENTO»."""
        return str(self.start) if self.start == self.end else f"{self.start}-{self.end}"


def find_document_numbers(text: str) -> list[int]:
    """Los números de documento que aparecen en un texto, en el orden leído."""
    return [int(numero) for numero in _DOCUMENT_NUMBER.findall(text)]


def ranges_of(numbers: list[int]) -> list[DocumentRange]:
    """Agrupa números en tramos consecutivos.

    El inventario de referencia no tiene una fila por número: tiene una fila por
    bloque -- ``3348-3408``, ``3735-3790`` --, y el corte entre bloques es un
    hueco en la numeración. Eso es exactamente lo que se reconstruye aquí a
    partir de lo que trae el PDF.

    Se ordenan y se deduplican primero porque el mismo número puede aparecer en
    más de una hoja de su documento (la nota interna y su factura, por ejemplo)
    y la fila es una sola.
    """
    ordered = sorted(set(numbers))
    if not ordered:
        return []
    ranges: list[DocumentRange] = []
    start = previous = ordered[0]
    for number in ordered[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append(DocumentRange(start, previous))
        start = previous = number
    ranges.append(DocumentRange(start, previous))
    return ranges


def _read_pages(taller: Taller, source) -> tuple[list[list[int]], int]:
    """Los números de cada página, con OCR sólo donde no hay capa de texto.

    Se pide OCR únicamente cuando la página no trae ni un carácter: un escaneo
    sin capa de texto es justo el caso en que hay que leer la imagen, y una
    factura que sí trae texto no necesita pagar una lectura para que se confirme
    que no lleva número de documento.

    Devuelve los números página a página y cuántas páginas pasaron por OCR.
    """
    per_page: list[list[int]] = []
    ocr_pages = 0
    total = source.page_count
    ocr = taller.ocr()

    for page_number in range(1, total + 1):
        taller.control.check()
        taller.progress.emit(
            ProgressEvent(
                stage=Stage.IDENTIFYING,
                done=page_number - 1,
                total=total,
                detail=f"leyendo página {page_number} de {total}",
            )
        )
        try:
            text = source.text_of(page_number)
        except Exception as error:  # noqa: BLE001 - una hoja ilegible no tumba el trabajo
            logger.debug("no se pudo leer la página %s: %s", page_number, error)
            text = ""

        numbers = find_document_numbers(text)
        if not numbers and not text.strip():
            # Sin capa de texto: es una imagen. Se lee, y si tampoco así aparece
            # un número, la página queda sin documento y se une a la anterior.
            try:
                text = ocr.read(source.render(page_number, dpi=200)).text
                ocr_pages += 1
                numbers = find_document_numbers(text)
            except Exception as error:  # noqa: BLE001 - el OCR es una ayuda, no un requisito
                logger.warning("el OCR de la página %s falló: %s", page_number, error)

        per_page.append(numbers)

    return per_page, ocr_pages


def _write_inventory(
    taller: Taller,
    ranges: list[DocumentRange],
    pages_by_number: dict[int, list[int]],
) -> Path:
    """Escribe el Excel de la plantilla Kingspan y devuelve su ruta."""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Inventario_KINGSPAN"
    sheet.append(["No. DOCUMENTO", "DESDE", "HASTA", "PDF_ORIGEN", "ORDEN"])

    for orden, tramo in enumerate(ranges, start=1):
        # El PDF de origen del tramo: el del primer número que lo compone.
        origen = ""
        for number in range(tramo.start, tramo.end + 1):
            if number in pages_by_number:
                origen = taller.name
                break
        sheet.append([tramo.label, tramo.start, tramo.end, origen or taller.name, orden])

    destination = taller.destination
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{Path(taller.name).stem}{INVENTORY_SUFFIX}"
    workbook.save(target)
    return target


def _pages_by_number(per_page: list[list[int]]) -> dict[int, list[int]]:
    """Qué páginas pertenecen a cada número de documento.

    La nota interna abre el documento y las facturas que la siguen no repiten el
    número: se quedan con el último leído. Una página suelta antes del primer
    documento no se le asigna a nadie; no se inventa a quién pertenece.
    """
    by_number: dict[int, list[int]] = {}
    current: int | None = None
    for page_number, numbers in enumerate(per_page, start=1):
        if numbers:
            current = numbers[0]
        if current is not None:
            by_number.setdefault(current, []).append(page_number)
    return by_number


def _split_by_document(
    taller: Taller,
    per_page: list[list[int]],
) -> list[Path]:
    """Un PDF por documento, para «Dividir e inventariar».

    Se corta por el número impreso, no por continuidad: en esta caja cada nota
    interna abre un documento y sus facturas van detrás. La continuidad cortaría
    donde el escáner dejó de parecer el mismo formulario, que no es lo mismo.
    """
    import pymupdf

    by_number = _pages_by_number(per_page)
    if not by_number:
        return []

    taller.destination.mkdir(parents=True, exist_ok=True)
    stem = Path(taller.name).stem
    written: list[Path] = []
    total = len(by_number)

    with pymupdf.open(taller.source) as origin:
        for done, (number, pages) in enumerate(by_number.items(), start=1):
            taller.control.check()
            taller.progress.emit(
                ProgressEvent(
                    stage=Stage.ASSEMBLING,
                    done=done - 1,
                    total=total,
                    detail=f"escribiendo el documento {number} ({done}/{total})",
                )
            )
            target = taller.destination / f"{number:05d}_{stem}.pdf"
            with pymupdf.open() as output:
                first = previous = pages[0]
                for page in pages[1:]:
                    if page == previous + 1:
                        previous = page
                        continue
                    output.insert_pdf(origin, from_page=first - 1, to_page=previous - 1)
                    first = previous = page
                output.insert_pdf(origin, from_page=first - 1, to_page=previous - 1)
                output.save(target, garbage=3, deflate=True)
            written.append(target)

    return written


def _kingspan_job(payload: dict, task, *, avisos: list[str] = ()) -> dict:
    """Inventaría una caja Kingspan y, si se pidió, la divide por documento."""
    from ...application.task import TaskKind

    taller = Taller.desde(payload)
    notices = list(avisos)

    taller.progress.emit(
        ProgressEvent(
            stage=Stage.IDENTIFYING, done=0, total=1, detail="leyendo números de documento"
        )
    )
    source = _open_source(taller)
    try:
        per_page, ocr_pages = _read_pages(taller, source)
    finally:
        source.close()

    numbers = [number for page_numbers in per_page for number in page_numbers]
    ranges = ranges_of(numbers)
    pages_by_number = _pages_by_number(per_page)

    if not ranges:
        notices.append(
            "no se encontró ningún número de documento (OOl-NI-NNNNN) en el PDF; "
            "el inventario queda vacío. Revise que el archivo sea una caja Kingspan "
            "y que su texto se deje leer."
        )
        logger.warning("%s: sin números de documento Kingspan", taller.name)

    taller.progress.emit(
        ProgressEvent(
            stage=Stage.ASSEMBLING,
            done=0,
            total=1,
            detail=f"escribiendo el inventario ({len(ranges)} fila(s))",
        )
    )
    inventory_path = _write_inventory(taller, ranges, pages_by_number)

    outputs: list[str] = [str(inventory_path)]
    if task is TaskKind.BOTH:
        outputs.extend(str(path) for path in _split_by_document(taller, per_page))

    if ocr_pages:
        notices.append(
            f"{ocr_pages} página(s) se leyeron por OCR por no traer capa de texto."
        )

    taller.progress.emit(ProgressEvent(stage=Stage.DONE, done=1, total=1))

    return {
        "document": taller.name,
        "page_count": sum(1 for _ in per_page),
        "groups": [],
        "quarantine": [],
        "repairs": [],
        "review_queue": [],
        "outputs": outputs,
        "unwritable_pages": [],
        "inventory": {
            "source_document": taller.name,
            "source_pages": len(per_page),
            "generated_files": len(outputs) - 1,
            "pages_accounted_for": len(per_page),
            "items": [],
            "quarantine_pages": [],
            "review_pages": [],
            "stats": {
                "kingspan_inventory": True,
                "rows": len(ranges),
                "documents": len(set(numbers)),
                "first_document": numbers[0] if numbers else None,
                "last_document": numbers[-1] if numbers else None,
                "ocr_pages": ocr_pages,
            },
        },
        "stats": {
            "escalated": 0,
            "no_leidas": [],
            "kingspan_rows": len(ranges),
            "kingspan_documents": len(set(numbers)),
            "outputs": len(outputs),
        },
        "task": str(task),
        "notices": notices,
    }


def _open_source(taller: Taller):
    from ...adapters.pymupdf_source import PyMuPDFPageSource

    return PyMuPDFPageSource(taller.source, taller.name)
