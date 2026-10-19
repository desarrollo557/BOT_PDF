"""Las huellas de las páginas de un PDF, para saber qué llegó al destino.

El escritor copia cada página del origen con su capa de texto y su imagen
escaneada tal cual (``insert_pdf``), así que una página entregada tiene la
misma capa y los mismos bytes de imagen que la de origen. Ver
``domain/conciliacion.py``.

La capa de texto se mira primero porque es lo barato: unos cientos de bytes
por cara. La imagen sólo cuando la capa no basta para distinguir la página --
una cara en blanco, un escaneo sin capa --, porque leerla es leer el escaneo
entero, y desde una unidad de red eso es la mitad del tiempo.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf

from ..domain.conciliacion import Huella
from .mupdf_messages import drenar
from .pymupdf_source import _abrir

#: Cuántos caracteres necesita la capa de texto para distinguir una página. Una
#: cara de diploma trae cientos; menos que esto es una hoja casi en blanco, y
#: dos hojas en blanco tienen la misma capa.
TEXTO_QUE_DISTINGUE = 40


def _resumen(datos: bytes) -> str:
    return hashlib.sha1(datos, usedforsecurity=False).hexdigest()


def huella_de(page: pymupdf.Page) -> Huella:
    texto = " ".join(page.get_text().split())
    if len(texto) >= TEXTO_QUE_DISTINGUE:
        return Huella(texto=_resumen(texto.encode("utf-8")))
    imagenes = page.get_images(full=True)
    if not imagenes:
        return Huella(texto=_resumen(texto.encode("utf-8")) if texto else None)
    # La más grande: la del escaneo, no un sello o un logotipo pegado encima.
    # Sin la compresión de transporte: el escritor guarda con ``deflate`` y
    # puede volver a comprimir una imagen Flate. Un JPEG sale tal cual.
    xref = max(imagenes, key=lambda imagen: imagen[2] * imagen[3])[0]
    return Huella(imagen=_resumen(page.parent.xref_stream(xref) or b""))


def huellas_de(path: Path) -> list[Huella]:
    """La huella de cada página del PDF, en orden."""
    documento = _abrir(Path(path), Path(path).name)
    try:
        return [huella_de(page) for page in documento]
    finally:
        documento.close()
        drenar()


def paginas_de(path: Path) -> int:
    """Cuántas páginas tiene, sin mirar ninguna."""
    documento = _abrir(Path(path), Path(path).name)
    try:
        return documento.page_count
    finally:
        documento.close()
        drenar()
