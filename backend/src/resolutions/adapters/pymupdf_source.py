from __future__ import annotations

from pathlib import Path

import pymupdf

from ..application.ports import Band, LineBox
from ..domain.diploma import TextLine
from .mupdf_messages import drenar

#: PDF user space is 72 dpi. Every render scales from there.
_PDF_DPI = 72.0


class PyMuPDFPageSource:
    """A PDF opened once, read page by page.

    Pixmaps are produced on demand and dropped immediately. Rendering a 400-page
    scan eagerly would cost hundreds of megabytes per document, and multiplying
    that by the worker count is how a machine falls over under load.
    """

    def __init__(self, path: Path, nombre: str | None = None) -> None:
        self._path = path
        #: Cómo llamó el operador al archivo. Las subidas se guardan en disco
        #: con un nombre generado, y un aviso que dice "6ea93142663d.pdf" no le
        #: sirve a nadie para saber qué documento venía defectuoso.
        self._nombre = nombre or path.name
        self._document = pymupdf.open(path)

    @property
    def page_count(self) -> int:
        return self._document.page_count

    def text_of(self, page_number: int) -> str:
        return self._document[page_number - 1].get_text("text")

    def sheet_of(self, page_number: int) -> tuple[int, int]:
        """El tamaño físico de la hoja, en puntos enteros.

        Redondeado porque lo que interesa es de qué lote de escaneo salió, no su
        medida exacta: un alimentador no entrega dos veces el mismo decimal.
        """
        rect = self._document[page_number - 1].rect
        return (round(rect.width), round(rect.height))

    def boxes_of(self, page_number: int) -> list[LineBox]:
        """Dónde está cada renglón de la página, en el orden de :meth:`text_of`.

        Es lo que permite distinguir un encabezado de una frase que empieza por
        la palabra "Resolución". Un encabezado va centrado y arriba; en el acta
        de comité del folio 245 del libro 00960-00979, la frase "La Dra. Rosaura
        Arrieta Flórez realiza la respectiva sustentación de la…" parte a mitad
        de página y su segundo renglón empieza justamente por "Resolución No.
        00520 de 202.". En texto plano ese renglón es indistinguible de un
        encabezado; en la página está a media altura y pegado al margen
        izquierdo, y ahí no hay ninguna duda.

        El orden tiene que ser el de ``text_of`` porque las candidatas se
        localizan por número de renglón. MuPDF construye los dos de la misma
        estructura interna, así que coinciden; aun así el llamador comprueba el
        texto antes de fiarse de la caja, porque una geometría mal alineada
        descartaría encabezados de verdad y perder una resolución en silencio es
        exactamente lo que esto viene a evitar.
        """
        page = self._document[page_number - 1]
        rect = page.rect
        if not rect.width or not rect.height:
            return []
        cajas: list[LineBox] = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", ()):
                texto = "".join(span["text"] for span in line["spans"])
                x0, y0, x1, _ = line["bbox"]
                cajas.append(
                    LineBox(
                        text=texto,
                        center_x=((x0 + x1) / 2 - rect.x0) / rect.width,
                        top=(y0 - rect.y0) / rect.height,
                    )
                )
        return cajas

    def lines_of(self, page_number: int) -> list[TextLine]:
        """The page's lines with enough geometry to know what sits above what.

        ``text_of`` is not enough for a form. These books hand back their lines
        in an order that puts the registration date before the graduate's name,
        so a reader that trusts reading order picks the wrong line off the page.
        The position does not lie.
        """
        page = self._document[page_number - 1]
        lines: list[TextLine] = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", ()):
                text = "".join(span["text"] for span in line["spans"]).strip()
                if text:
                    x0, y0, _, _ = line["bbox"]
                    lines.append(TextLine(text=text, y=y0, x=x0))
        lines.sort(key=lambda item: (item.y, item.x))
        return lines

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
        # Lo que MuPDF fue anotando mientras se leía el documento -- un perfil
        # de color roto, un objeto que no está donde dice -- traducido y con el
        # nombre del archivo delante. Aquí y no en cada página: las páginas se
        # leen en varios hilos sobre este mismo PDF y el almacén de MuPDF es uno
        # solo para todo el proceso, así que decir de qué página vino cada aviso
        # sería adjudicarlo al azar.
        drenar(self._nombre)

    def __enter__(self) -> PyMuPDFPageSource:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class PyMuPDFDocumentStore:
    def __init__(self, nombre: str | None = None) -> None:
        #: El nombre con que se informa de lo que traiga el documento. Lo pone
        #: quien monta el trabajo, que es el único que sabe cómo se llamaba el
        #: archivo antes de subirlo.
        self._nombre = nombre

    def open(self, document: Path) -> PyMuPDFPageSource:
        return PyMuPDFPageSource(document, self._nombre)
