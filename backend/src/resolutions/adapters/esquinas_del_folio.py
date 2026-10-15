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

    # -- muchas hojas por página facturada --------------------------------------

    def armar_mosaico_etiquetado(self, source, paginas: Sequence[int]) -> bytes | None:
        """Las esquinas de muchas hojas en una imagen, cada una con su página al lado.

        Para los libros de grados, donde cada graduado es una hoja: leer su
        esquina sola costaría una página facturada por graduado. Con diez por
        imagen cuesta una cada diez, y la etiqueta impresa «P147» al lado de
        cada esquina dice de qué hoja es cada número, aunque el proveedor se
        salte una esquina ilegible -- en el mosaico sin etiquetas eso
        descuadraría todos los números de detrás.
        """
        from PIL import ImageDraw

        banda = Band(*BANDA_DEL_FOLIO)
        fuente = _fuente_de_etiqueta()
        filas = []
        for pagina in paginas:
            try:
                recorte = Image.open(BytesIO(source.render(pagina, banda, self._dpi))).convert("L")
            except Exception:  # noqa: BLE001 - esa hoja se queda sin leer
                logger.warning("no se pudo recortar la esquina de la página %s", pagina)
                continue
            fila = Image.new("L", (_ANCHO_DE_ETIQUETA + recorte.width, recorte.height), 255)
            ImageDraw.Draw(fila).text((10, recorte.height // 3), f"P{pagina}", fill=0, font=fuente)
            fila.paste(recorte, (_ANCHO_DE_ETIQUETA, 0))
            filas.append(fila)
        if not filas:
            return None
        ancho = max(fila.width for fila in filas)
        alto = sum(fila.height for fila in filas) + _SEPARACION * (len(filas) - 1)
        lienzo = Image.new("L", (ancho, alto), 255)
        y = 0
        for fila in filas:
            lienzo.paste(fila, (0, y))
            y += fila.height + _SEPARACION
        salida = BytesIO()
        lienzo.save(salida, "PNG")
        return salida.getvalue()

    def leer_mosaico_etiquetado(self, imagen: bytes, paginas: Sequence[int]) -> dict[int, int]:
        """El folio de cada hoja del mosaico, por su etiqueta. Puede ir en otro hilo."""
        return folios_etiquetados(self._leer(imagen), paginas)

    # -- cualquier franja, no sólo la esquina ------------------------------------

    def armar_mosaico_de_franjas(self, source, franjas: Sequence[tuple[int, Band]]) -> bytes | None:
        """Varias franjas -- la del nombre de cada graduado -- en una imagen, con su página al lado.

        Lo mismo que las esquinas: diez por página facturada, y la etiqueta
        «P147» dice de qué hoja es cada texto aunque el proveedor se salte uno.
        """
        from PIL import ImageDraw

        fuente = _fuente_de_etiqueta()
        filas = []
        for pagina, banda in franjas:
            try:
                recorte = Image.open(BytesIO(source.render(pagina, banda, self._dpi))).convert("L")
            except Exception:  # noqa: BLE001 - esa hoja se queda sin leer
                logger.warning("no se pudo recortar la franja de la página %s", pagina)
                continue
            fila = Image.new("L", (_ANCHO_DE_ETIQUETA + recorte.width, recorte.height), 255)
            ImageDraw.Draw(fila).text((10, recorte.height // 3), f"P{pagina}", fill=0, font=fuente)
            fila.paste(recorte, (_ANCHO_DE_ETIQUETA, 0))
            filas.append(fila)
        if not filas:
            return None
        ancho = max(fila.width for fila in filas)
        alto = sum(fila.height for fila in filas) + _SEPARACION * (len(filas) - 1)
        lienzo = Image.new("L", (ancho, alto), 255)
        y = 0
        for fila in filas:
            lienzo.paste(fila, (0, y))
            y += fila.height + _SEPARACION
        salida = BytesIO()
        lienzo.save(salida, "PNG")
        return salida.getvalue()

    def leer_textos_etiquetados(self, imagen: bytes, paginas: Sequence[int]) -> dict[int, str]:
        """El texto de cada franja del mosaico, por su etiqueta. Puede ir en otro hilo."""
        return textos_etiquetados(self._leer(imagen), paginas)


#: Cuánto ancho lleva la etiqueta de la página a la izquierda de cada esquina.
_ANCHO_DE_ETIQUETA = 260


def _fuente_de_etiqueta():
    """Una letra grande y clara para la etiqueta: el proveedor la lee sin dudar."""
    from PIL import ImageFont

    for nombre in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(nombre, 64)
        except OSError:
            continue
    return ImageFont.load_default()


def textos_etiquetados(texto: str, paginas: Sequence[int]) -> dict[int, str]:
    """De lo que el proveedor leyó en un mosaico, el texto de cada página pedida."""
    import re

    pedidas = set(paginas)
    textos: dict[int, str] = {}
    trozos = re.split(r"\bP\s?(\d{1,4})\b", texto)
    for indice in range(1, len(trozos) - 1, 2):
        pagina = int(trozos[indice])
        if pagina in pedidas and trozos[indice + 1].strip():
            textos[pagina] = trozos[indice + 1].strip()
    return textos


def folios_etiquetados(texto: str, paginas: Sequence[int]) -> dict[int, int]:
    """De lo que el proveedor leyó en el mosaico, el folio de cada página pedida.

    Cada esquina va detrás de su etiqueta «P147»; el número que la sigue, hasta
    la etiqueta siguiente, es el folio de esa hoja: «P147 140/V» es el folio
    140 (la «V» dice que la hoja siguiente es su vuelto). Una etiqueta sin
    número detrás es una esquina que no se leyó.
    """
    import re

    pedidas = set(paginas)
    folios: dict[int, int] = {}
    trozos = re.split(r"\bP\s?(\d{1,4})\b", texto)
    # re.split con un grupo: [antes, pagina, resto, pagina, resto, ...]
    for indice in range(1, len(trozos) - 1, 2):
        pagina = int(trozos[indice])
        numero = re.search(r"(?<![\d.,])(\d{1,4})(?![\d.,])", trozos[indice + 1])
        if pagina in pedidas and numero and int(numero.group(1)) > 0:
            folios[pagina] = int(numero.group(1))
    return folios
