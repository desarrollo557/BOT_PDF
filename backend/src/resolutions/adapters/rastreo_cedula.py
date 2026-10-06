"""Una segunda mirada local a la cédula, antes de pagar por ella.

La lectura normal de una página entera falla con una cédula por dos motivos que
no tienen que ver entre sí. Uno es el papel: en los libros antiguos el número
está escrito a mano y con letra corrida, y contra eso no hay OCR local que
valga. El otro es de método, y **sí** tiene arreglo: leyendo la hoja completa,
Tesseract busca columnas y párrafos, reparte la página en bloques y trata ese
renglón como una línea más de un cuerpo de texto en español -- donde espera
palabras. Entonces propone letras donde hay números: el 7 vuelve como «?», el 0
como «O», el 1 como «l».

Lo que hace este rastreo es quitarle a Tesseract las dos cosas que le estorban:

* **el contexto** -- se le pasa sólo la banda donde vive el número, no la hoja;
* **la libertad** -- se le ata a un renglón único y a un juego de caracteres de
  dígitos y puntos, de modo que ya no puede contestar una letra.

Y de paso se le amplía el recorte, porque una banda estrecha a 400 dpi todavía
tiene dígitos de pocos píxeles de alto y Tesseract acierta bastante más cuando
la letra pasa de treinta.

Nada de esto lee manuscrito de corrido, y conviene no prometerlo: eso sigue
siendo trabajo del motor de pago. Lo que esto recupera es lo que ya estaba
legible en el papel y se perdió por leerlo mal, que en un libro mecanografiado
es la mayoría de lo que faltaba. El orden acaba siendo el que pidió el
operador: la OCR primero, este rastreo después, y la IA sólo para lo que
ninguno de los dos consiguió.
"""

from __future__ import annotations

import logging

from ..domain.diploma import buscar_cedula
from .tesseract_ocr import PSM_UNA_LINEA, TesseractConfig, TesseractOcr

logger = logging.getLogger(__name__)

#: A cuánto se rasteriza la banda. Más que la página entera -- que va a 300 --
#: porque aquí se lee un número de ocho dígitos dentro de tres centímetros de
#: papel, y cada dígito tiene que llegar con píxeles suficientes para distinguir
#: un 3 de un 8.
DPI_DEL_RASTREO = 400

#: Cuánto se amplía el recorte antes de leerlo. Dos: con tres se gana poco y el
#: tiempo por banda se duplica.
ESCALA = 2

#: Lo único que puede contestar Tesseract al leer una cédula. Los puntos y las
#: comas entran porque el papel las escribe -- "7.882.907" -- y porque agrupan
#: el número de tres en tres, que es una comprobación gratis de que está entero.
DIGITOS = "0123456789.,"

#: Las leyendas impresas que anuncian el número. Cuando alguna aparece en la
#: capa de texto de la página, se sabe **en qué renglón** está la cédula y no
#: hay que barrer nada: se recorta esa franja y se lee.
ANCLAS = ("C.C", "CC.", "CEDULA", "IDENTIFICADO CON", "IDENTIFICADA CON")

#: Cuánto papel se recorta alrededor del renglón anclado, en fracción de la
#: altura de la página. Generoso a propósito: la caja del renglón la da la capa
#: de texto de lo impreso, y el número está escrito **a mano encima o al lado**,
#: de modo que puede sobresalir por arriba y por abajo.
MARGEN = 0.05

#: **No hay barrido a ciegas, y esto costó una medición entenderlo.**
#:
#: La primera versión de este rastreo, a falta de rótulo, barría el cuerpo de la
#: hoja en seis bandas. Sobre el libro 7 de 1982 -- manuscrito y con letra
#: corrida -- "recuperó" una cédula en las cuatro caras que se le probaron:
#: 22212251, 515232, 6211552 y 213353. Las cuatro **inventadas**: las de verdad
#: eran 780064, 7882907, 30761 y 9091482.
#:
#: No es un fallo de afinado: es lo que hace un whitelist por definición. Atar
#: Tesseract a dígitos no le enseña a leer números, le **prohíbe** contestar otra
#: cosa. Puesto delante de un trazo de pluma contesta dígitos igual, y como
#: salen seis u ocho, pasan la prueba de credibilidad y entran en el nombre del
#: archivo. Peor todavía: al dar la cédula por encontrada, esa página dejaba de
#: escalar a la IA, que era la única que sabía leerla.
#:
#: De modo que este rastreo sólo mira **donde el papel impreso dice que hay un
#: número**. Sin rótulo no hay banda, y la página sigue su camino a la IA, que
#: es donde tenía que ir.


class RastreoDeCedula:
    """Busca la cédula de una página mirando sólo donde puede estar.

    No satisface ``OcrEngine`` y no pretende hacerlo: no devuelve el texto de
    una imagen, devuelve **un dato concreto de una página**. Es un instrumento
    de un campo, no un motor de lectura, y mezclarlos haría que alguien lo
    enchufara donde se espera una transcripción.
    """

    def __init__(self, language: str = "spa", command: str | None = None) -> None:
        #: Atado a dígitos y a un renglón: es la lectura que de verdad aporta.
        self._numerico = TesseractOcr(
            TesseractConfig(
                language=language,
                psm=PSM_UNA_LINEA,
                whitelist=DIGITOS,
                escala=ESCALA,
                # Un recorte de un renglón no tiene palabras con que promediar
                # una confianza, y la que sale de tres dígitos no dice nada. Lo
                # que decide si la lectura sirve es si el número resultante se
                # sostiene como cédula, y de eso se encarga el dominio.
                min_word_confidence=0.0,
            ),
            command=command,
        )
        #: Y una segunda pasada sin atar, para las fichas donde el número llega
        #: pegado a su rótulo -- "CC. No. 1047375454" -- y la forma de la
        #: fórmula es justamente lo que lo identifica.
        self._libre = TesseractOcr(
            TesseractConfig(
                language=language,
                psm=PSM_UNA_LINEA,
                escala=ESCALA,
                min_word_confidence=0.0,
            ),
            command=command,
        )

    def buscar(self, source, page_number: int) -> str | None:
        """La cédula de esta página, si alguna banda la suelta.

        Devuelve siempre un número **creíble**, porque quien lo pide lo va a
        usar para nombrar un archivo y para decidir un corte. Lo que no se
        sostiene no se entrega: entregarlo sólo servirá para que alguien lo use
        sin comprobarlo.

        Nunca levanta. Un rastreo que falla deja la página como estaba -- sin
        cédula y camino de la IA --, que es exactamente donde estaba antes de
        intentarlo.
        """
        imagenes = self.imagenes(source, page_number)
        return self.buscar_imagenes(imagenes, page_number)

    def imagenes(self, source, page_number: int) -> list[bytes]:
        """Renderiza las bandas de cédula sin ejecutar OCR todavía."""
        if not self._tiene_rotulo(source, page_number):
            # Ni se mira. Una pagina sin el rotulo impreso no tiene donde
            # apuntar, y averiguarlo con las cajas de renglon cuesta un segundo
            # por cara: sobre un libro de cuatrocientas, tres minutos de reloj
            # para no hacer nada. El texto de la pagina ya esta en memoria.
            return []
        imagenes: list[bytes] = []
        for banda in self._bandas(source, page_number):
            try:
                imagenes.append(source.render(page_number, banda, DPI_DEL_RASTREO))
            except Exception:  # noqa: BLE001 - una banda, no la página
                logger.debug("no se pudo recortar una banda de la página %s", page_number)
                continue
        return imagenes

    def buscar_imagenes(self, imagenes: list[bytes], page_number: int) -> str | None:
        """Lee bandas ya renderizadas; es seguro ejecutarlo en paralelo."""
        for imagen in imagenes:
            cedula = self._de_la_banda(imagen, page_number)
            if cedula:
                logger.info(
                    "rastreo local: cédula %s recuperada en la página %s sin pagar",
                    cedula,
                    page_number,
                )
                return cedula
        return None

    def _de_la_banda(self, imagen: bytes, page_number: int) -> str | None:
        """El número de esta franja, con verificación sólo si hay candidato.

        La corroboración es lo que separa un número leído de uno fabricado. La
        lectura atada a dígitos contesta dígitos siempre, los haya o no; la
        libre contesta lo que ve, y ante un trazo de pluma devuelve letras y
        signos. Que las dos coincidan en el mismo número sólo ocurre cuando ese
        número está de verdad escrito ahí y es legible.

        Cuesta una segunda llamada a Tesseract por banda y nada más, porque la
        banda ya está rasterizada. A cambio es lo que permite que este rastreo
        se equivoque **callando** -- devolviendo ``None`` y dejando la página
        para la IA -- en vez de equivocarse hablando.
        """
        try:
            atada = buscar_cedula(self._numerico.read(imagen).text)
        except Exception:  # noqa: BLE001 - un intento, no el libro
            logger.debug("falló el rastreo de la página %s", page_number, exc_info=True)
            return None
        # La mayoría de las franjas no contienen una cédula legible. No se
        # paga el coste de una segunda pasada para confirmar una ausencia.
        if not atada:
            return None
        try:
            libre = buscar_cedula(self._libre.read(imagen).text)
        except Exception:  # noqa: BLE001 - un intento, no el libro
            logger.debug("falló la verificación de la página %s", page_number, exc_info=True)
            return None
        return atada if atada == libre else None

    def _bandas(self, source, page_number: int):
        """Dónde mirar: sólo las franjas que el papel impreso señala.

        El rótulo -- "identificado con C.C. No." -- viene impreso en el
        formulario, así que la capa de texto lo trae aunque el número de al lado
        esté escrito a mano. Eso es lo que convierte esto en una segunda mirada
        al sitio correcto y no en una búsqueda a ciegas.

        Una página sin rótulo no produce ninguna banda, y entonces no se lee
        nada: no hay evidencia de que ahí haya un número, y fabricar una es
        justo lo que esta clase existe para no hacer.
        """
        from ..application.ports import Band

        for arriba in self._ancladas(source, page_number):
            yield Band(0.0, max(0.0, arriba - MARGEN), 1.0, min(1.0, arriba + MARGEN))

    @staticmethod
    def _tiene_rotulo(source, page_number: int) -> bool:
        """Si el texto de la pagina menciona siquiera el rotulo de la cedula.

        Es una criba previa y barata: el texto de la pagina ya se leyo y esta
        guardado, mientras que pedir las cajas de cada renglon obliga a
        reconstruir la pagina entera. En un libro escaneado sin capa de texto
        esto contesta que no al instante y el rastreo ni empieza.
        """
        leer = getattr(source, "text_of", None)
        if leer is None:
            return True
        try:
            texto = (leer(page_number) or "").upper()
        except Exception:  # noqa: BLE001 - sin texto se intenta igual
            return True
        return any(ancla in texto for ancla in ANCLAS)

    @staticmethod
    def _ancladas(source, page_number: int) -> list[float]:
        """La altura de los renglones que anuncian una cédula, si los hay."""
        leer = getattr(source, "boxes_of", None)
        if leer is None:
            return []
        try:
            cajas = leer(page_number)
        except Exception:  # noqa: BLE001 - sin cajas se barre, que es el plan B
            return []
        return [
            caja.top
            for caja in cajas
            if any(ancla in (caja.text or "").upper() for ancla in ANCLAS)
        ]
