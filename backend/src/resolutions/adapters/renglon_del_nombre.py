"""El renglón del nombre de un estudiante, recortado para enseñarlo en la Revisión.

El operador (2026-11-17): «que los nombres siempre queden exactos». Lo que la
máquina no asegura lo confirma una persona, y para eso tiene que ver el papel
sin abrir el PDF: la parte de arriba de la ficha, donde va «Nombre del
estudiante» en todas sus plantillas, y el pie de la hoja que sigue, donde la
hoja de notas escribe el nombre otra vez.

Se recorta del PDF del estudiante, que empieza por su ficha
(``historias (worker)``, «la ficha principal primero»), o de la página de la
ficha en el original cuando sólo se inventarió. Nada se guarda: se recorta al
pedirlo, en décimas de segundo.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: La parte de la ficha donde va el nombre, en fracción de la hoja: arriba, en
#: todas sus plantillas, de la tarjeta de 1968 a la ficha de 2003.
ARRIBA_DE_LA_FICHA = (0.02, 0.26)
#: El pie de la hoja de notas, donde se repite el nombre a mano.
PIE_DE_LAS_NOTAS = (0.86, 1.0)
#: A cuánto se recorta: se lee la letra a mano y la imagen no pesa.
PPP = 110


def recorte_del_nombre(pdf: Path, ficha: int = 1, notas: int | None = 2) -> bytes | None:
    """La parte de arriba de la página ``ficha`` y el pie de la ``notas``, apiladas en un JPEG; ``None`` si no se puede."""
    try:
        import pymupdf
        from PIL import Image
    except Exception:  # noqa: BLE001 - sin las bibliotecas no hay imagen, y no pasa nada
        return None
    recortes = []
    try:
        with pymupdf.open(pdf) as documento:
            for numero, (arriba, abajo) in ((ficha, ARRIBA_DE_LA_FICHA), (notas, PIE_DE_LAS_NOTAS)):
                if numero is None or not 1 <= numero <= documento.page_count:
                    continue
                pagina = documento[numero - 1]
                caja = pagina.rect
                clip = pymupdf.Rect(caja.x0, caja.y0 + caja.height * arriba, caja.x1, caja.y0 + caja.height * abajo)
                pix = pagina.get_pixmap(dpi=PPP, clip=clip)
                recortes.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
    except Exception:  # noqa: BLE001 - un PDF que no se deja abrir no tumba la pantalla
        logger.warning("no se pudo recortar el nombre de %s", pdf, exc_info=True)
        return None
    if not recortes:
        return None
    ancho = max(recorte.width for recorte in recortes)
    lienzo = Image.new("RGB", (ancho, sum(recorte.height + 12 for recorte in recortes)), "white")
    y = 0
    for recorte in recortes:
        lienzo.paste(recorte, (0, y))
        y += recorte.height + 12
    salida = io.BytesIO()
    lienzo.save(salida, "JPEG", quality=80)
    return salida.getvalue()
