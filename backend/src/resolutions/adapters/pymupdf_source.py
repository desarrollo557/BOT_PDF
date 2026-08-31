from __future__ import annotations

from pathlib import Path

import pymupdf

from ..application.ports import Band

#: PDF user space is 72 dpi. Every render scales from there.
_PDF_DPI = 72.0


class PyMuPDFPageSource:
    """A PDF opened once, read page by page.

    Pixmaps are produced on demand and dropped immediately. Rendering a 400-page
    scan eagerly would cost hundreds of megabytes per document, and multiplying
    that by the worker count is how a machine falls over under load.
    """

    def __init__(self, path: Path) -> None:
        self._document = pymupdf.open(path)

    @property
    def page_count(self) -> int:
        return self._document.page_count

    def text_of(self, page_number: int) -> str:
        return self._document[page_number - 1].get_text("text")

    def render(self, page_number: int, band: Band | None = None, dpi: int = 200) -> bytes:
        page = self._document[page_number - 1]
        clip = None
        if band is not None:
            rect = page.rect
            clip = pymupdf.Rect(
                rect.x0 + band.x0 * rect.width,
                rect.y0 + band.y0 * rect.height,
                rect.x0 + band.x1 * rect.width,
                rect.y0 + band.y1 * rect.height,
            )

        zoom = dpi / _PDF_DPI
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(zoom, zoom),
            clip=clip,
            # Greyscale: Tesseract binarises anyway, and it is a third of the
            # bytes to move around per page.
            colorspace=pymupdf.csGRAY,
            alpha=False,
        )
        return pixmap.tobytes("png")

    def close(self) -> None:
        self._document.close()

    def __enter__(self) -> PyMuPDFPageSource:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class PyMuPDFDocumentStore:
    def open(self, document: Path) -> PyMuPDFPageSource:
        return PyMuPDFPageSource(document)
