"""El folio manuscrito de un acta, leído de dos esquinas en una sola página facturada.

Las actas de consejo se folian a mano en la esquina superior derecha de cada
hoja, al lado del escudo del membrete. Lo que el inventario necesita es el
primer folio y el último, y para eso no hace falta leer las veinte esquinas:
basta la de la primera hoja foliada y la de la última.

El folio va escrito a mano y Tesseract no lo lee -- sobre el acta de Odontología
del 17 de diciembre de 2012 devolvió pedazos del membrete en las cinco esquinas
probadas y ningún número --, así que lo lee el OCR de pago. Y ése cobra por
**página procesada**: las dos esquinas, apiladas una encima de la otra en una
sola imagen, son una página facturada por acta y no dos.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from io import BytesIO

from PIL import Image

from ..application.ports import Band
from ..domain.acta_consejo import BANDA_DEL_FOLIO

logger = logging.getLogger(__name__)

#: A cuánto se rasteriza cada esquina. Lo mismo que una página entera: lo que se
#: recorta es pequeño y la letra manuscrita necesita toda la resolución.
DPI = 300

#: Cuánto blanco separa una esquina de la otra, en píxeles. El proveedor lee el
#: mosaico de arriba abajo, y con aire en medio no junta los dos números en uno.
_SEPARACION = 60


class LectorDeFolios:
    """Lee las esquinas del folio de varias hojas en una imagen. Satisface `LectorDeEsquinas`.

    Recibe la función de lectura y no el motor -- `leer(bytes) -> str` --,
    porque lo único que necesita del proveedor es que transcriba una imagen.
    Así se prueba con un doble y no sabe qué proveedor le tocó.
    """

    def __init__(self, leer: Callable[[bytes], str], dpi: int = DPI) -> None:
        self._leer = leer
        self._dpi = dpi

    def leer_esquinas(self, source, paginas: Sequence[int]) -> str:
        """Lo que el proveedor lee en esas esquinas, de arriba abajo y en ese orden."""
        imagen = self.armar_mosaico(source, paginas)
        return self.leer_mosaico(imagen) if imagen else ""

    def leer_mosaico(self, imagen: bytes) -> str:
        """Lee un mosaico ya armado. Puede ir en otro hilo: no toca el PDF."""
        return self._leer(imagen)

    def armar_mosaico(self, source, paginas: Sequence[int]) -> bytes | None:
        """Las esquinas de esas hojas apiladas en una imagen, o ``None`` si falta alguna.

        Va en el hilo que tiene el PDF abierto -- MuPDF no admite más de uno --,
        y la lectura, que es esperar al proveedor, puede ir aparte.
        """
        banda = Band(*BANDA_DEL_FOLIO)
        recortes = []
        for pagina in paginas:
            try:
                recortes.append(
                    Image.open(BytesIO(source.render(pagina, banda, self._dpi))).convert("L")
                )
            except Exception:  # noqa: BLE001 - una esquina que no se recorta no se lee
                logger.warning("no se pudo recortar la esquina de la página %s", pagina)
        if not recortes or len(recortes) != len(paginas):
            # Leer menos esquinas de las pedidas descuadraría el orden, que es lo
            # único que dice de qué hoja salió cada número.
            return None

        ancho = max(recorte.width for recorte in recortes)
        alto = sum(recorte.height for recorte in recortes) + _SEPARACION * (len(recortes) - 1)
        lienzo = Image.new("L", (ancho, alto), 255)
        y = 0
        for recorte in recortes:
            lienzo.paste(recorte, (0, y))
            y += recorte.height + _SEPARACION
        salida = BytesIO()
        lienzo.save(salida, "PNG")
        return salida.getvalue()
