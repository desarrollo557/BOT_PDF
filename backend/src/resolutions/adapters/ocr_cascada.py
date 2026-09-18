"""Tesseract primero, el OCR de pago sólo donde el local no alcanzó.

El orden es de costo, y el costo aquí no es teórico: una caja son cientos de
páginas y el motor remoto se paga por cada una. Tesseract lee gratis y lee bien
lo impreso, que es la mayor parte de cualquier expediente. Lo que no lee es lo
escrito a mano, y ahí -- y sólo ahí -- vale la pena preguntar fuera.

De modo que la escalada no se decide por tipo de documento ni por habilidad, sino
por el resultado: si de la imagen no salió nada que se parezca a texto, se
pregunta al de pago. Una banda de encabezado que Tesseract leyó entera no se
vuelve a leer, y una esquina de la que devolvió `', "'` sí.

Esto es lo que hace que la llave de Mistral sirva a las cuatro habilidades sin
que ninguna de las cuatro sepa que existe: todas piden su OCR al taller, y el
taller les da éste cuando el operador lo activó.
"""

from __future__ import annotations

import logging

from ..application.ports import OcrResult

logger = logging.getLogger(__name__)

#: Cuántos caracteres con contenido -- letras o dígitos, sin contar el ruido de
#: puntuación que deja un escaneo malo -- hacen que una lectura local se dé por
#: buena. Por debajo de esto no hay nada que un extractor pueda usar: no es una
#: lectura pobre, es una lectura vacía con adornos.
MINIMO_UTIL = 12


class OcrEnCascada:
    """Dos motores, uno detrás del otro, con el mismo contrato que cada uno.

    Satisface `OcrEngine`, así que entra donde ya entraba Tesseract y nadie más
    se entera. La lectura que devuelve es la del peldaño que de verdad leyó
    algo; si el remoto tampoco lee, vuelve la local, porque quedarse con la peor
    de las dos sería empeorar el resultado por haber gastado más.
    """

    def __init__(self, local, remoto, minimo_util: int = MINIMO_UTIL) -> None:
        self._local = local
        self._remoto = remoto
        self._minimo = minimo_util

    def read(self, image_png: bytes) -> OcrResult:
        try:
            local = self._local.read(image_png)
        except Exception:  # noqa: BLE001 - que falle el local no impide preguntar
            logger.debug("el OCR local falló; se escala", exc_info=True)
            local = OcrResult(text="", mean_confidence=0.0)

        if _utiles(local.text) >= self._minimo:
            return local

        try:
            remoto = self._remoto.read(image_png)
        except Exception:  # noqa: BLE001 - y que falle el remoto no rompe nada
            logger.warning("el OCR remoto falló; se conserva la lectura local", exc_info=True)
            return local

        if _utiles(remoto.text) > _utiles(local.text):
            return remoto
        return local


    @property
    def consumo(self):
        """El contador del motor de pago, que es el único que cuesta."""
        return getattr(self._remoto, "consumo", None)

    def read_remote(self, image_png: bytes) -> OcrResult:
        """El motor de pago directamente, sin pasar por el local.

        Existe porque "¿sirvió la lectura local?" no tiene la misma respuesta
        para todos los que preguntan. La cascada mide si salió *texto*, y en un
        diploma de 1982 Tesseract saca un párrafo entero de texto impreso --
        "en atención a que el Señor", "le expide el presente Diploma" -- sin
        haber leído ni una de las cinco cosas que identifican al documento,
        porque esas cinco están escritas a mano. Medido por caracteres, esa
        lectura parece buena y la cascada no escalaría nunca.

        Así que quien sabe qué está buscando puede saltarse el peldaño gratis.
        Lo usa la ruta de los libros de registro, que busca la cédula y el
        nombre del graduado; las demás siguen con la cascada, que es lo barato.
        """
        try:
            return self._remoto.read(image_png)
        except Exception:  # noqa: BLE001 - se cae al local, nunca al suelo
            logger.warning("el OCR remoto falló; se lee con el local", exc_info=True)
            return self._local.read(image_png)


def _utiles(texto: str) -> int:
    """Cuántos caracteres del texto son letra o dígito.

    Contar la longitud a secas haría pasar por lectura las comillas y las barras
    con que Tesseract rellena una esquina en blanco, que es justo el caso que
    esta cascada existe para escalar.
    """
    return sum(1 for caracter in texto if caracter.isalnum())
