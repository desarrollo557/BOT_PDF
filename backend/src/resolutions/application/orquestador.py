"""Quién decide qué habilidad atiende un documento que nadie reconoció.

El despachador elegía ruta con una sola pregunta: ¿qué vocabulario impreso
traen doce páginas repartidas? Si la respuesta era clara, bien; si no lo era, el
documento se daba por desconocido y se partía por continuidad -- la ruta que no
lee el papel -- aunque cada hoja trajera un encabezado de resolución, una cédula
de graduado o el número de un acta. El operador lo pidió con estas palabras:
«cuando el bot no reconozca un documento, que llame a todas las habilidades, y
que el orquestador tome la decisión dependiendo de lo que la OCR alimente al
flujo».

Así que el orquestador hace hasta tres preguntas, y se detiene en la primera
que tenga respuesta:

1. **Los marcadores.** La muestra de siempre y `doctype.classify_pages`. Si
   deciden, se respeta y no se gasta nada más: es exactamente lo que se hacía
   antes, y lo que se hace en la inmensa mayoría de los documentos.
2. **Todas las habilidades.** Si los marcadores no decidieron, cada habilidad
   lee la misma muestra con su propio lector -- los mismos que después parten
   el documento -- y dice qué comprobó (`domain.validacion`). Gana la única que
   encontró evidencia positiva en suficientes páginas y con ventaja clara sobre
   la segunda. Ninguna gana por descarte.
3. **La página entera.** Si nadie validó, puede ser que la banda superior no
   bastara: un escaneo sin capa de texto sólo se leyó por su encabezado. Se
   leen enteras unas pocas de esas páginas con el **mismo OCR local** y se
   repiten las dos preguntas anteriores con lo que salga.

Si después de eso nadie validó, el documento queda como desconocido y sigue el
camino conservador, con el motivo escrito.

Sólo OCR local. El orquestador recibe el motor con que se muestrea -- Tesseract
en el servicio -- y no sabe que existen proveedores de pago: reconocer de qué
documento se trata nunca puede costar dinero. La lectura paga, cuando el
operador la permite, es cosa de la habilidad elegida y no de quien la elige.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from ..domain.doctype import DocumentType, TypeVerdict, classify_pages
from ..domain.validacion import Validacion, ganadora, validar_todas
from .ports import HEADER_BAND, Band, OcrEngine, OcrResult, PageSource

logger = logging.getLogger(__name__)

#: Cuántas páginas se miran para decidir de qué documento se trata. Doce bastan
#: y cuestan nada: en un libro de cuatrocientas páginas todas dicen lo mismo, y
#: en una caja mal ordenada doce repartidas de punta a punta ven la mezcla.
SAMPLE_PAGES = 12

#: Por debajo de esto la capa de texto de la página no sirve para reconocer nada
#: y hay que mirar la imagen.
MIN_SAMPLE_CHARS = 80

#: Con qué resolución se rasteriza lo que se muestrea. La misma para la banda
#: del encabezado y para la página entera de la segunda mirada, que es la que
#: usa el inventario de archivo entero para leer una hoja con Tesseract.
DPI_DE_MUESTRA = 200

#: Cuántas páginas se leen enteras cuando la banda superior no bastó. Cuatro:
#: bastan para ver el cuerpo de un documento cuyo encabezado no dijo nada, y
#: leer una página entera cuesta varias veces lo que su banda. Es un precio que
#: sólo pagan los documentos que nadie supo reconocer.
PAGINAS_SEGUNDA_MIRADA = 4


def paginas_de_muestra(total: int, cuantas: int = SAMPLE_PAGES) -> list[int]:
    """Qué páginas se miran: ``cuantas`` repartidas de punta a punta."""
    if total <= 0:
        return []
    paso = max(1, total // cuantas)
    return list(range(1, total + 1, paso))[:cuantas]


def muestrear(
    source: PageSource,
    ocr: OcrEngine | None,
    *,
    paginas: int = SAMPLE_PAGES,
    banda: Band | None = HEADER_BAND,
    numeros: Sequence[int] | None = None,
    dpi: int = DPI_DE_MUESTRA,
) -> list[tuple[int, str]]:
    """El texto de una muestra de páginas, con OCR sólo donde hace falta.

    Cada página se lee por su capa de texto. Si la capa no da para reconocer
    nada -- un escaneo -- y hay motor de OCR, se lee la imagen: por omisión sólo
    la banda superior, que basta para reconocer el encabezado impreso y cuesta
    la décima parte que la página entera; con ``banda=None``, la página entera.

    ``numeros`` elige las páginas a mano; sin él se reparten ``paginas`` de
    punta a punta. Una página que no se deja leer se omite: una hoja ilegible
    no decide nada, y no debe impedir que decidan las demás.
    """
    if numeros is None:
        numeros = paginas_de_muestra(source.page_count, paginas)

    muestra: list[tuple[int, str]] = []
    for numero in numeros:
        try:
            texto = source.text_of(numero)
            if len(texto) < MIN_SAMPLE_CHARS and ocr is not None:
                texto = ocr.read(source.render(numero, banda, dpi)).text
        except Exception:  # noqa: BLE001 - una página ilegible no decide nada
            logger.debug("no se pudo muestrear la página %s", numero, exc_info=True)
            continue
        muestra.append((numero, texto))
    return muestra


def repartidas(numeros: Sequence[int], cuantas: int) -> list[int]:
    """``cuantas`` de ``numeros``, repartidas de punta a punta y en su orden."""
    if cuantas <= 0:
        return []
    if len(numeros) <= cuantas:
        return list(numeros)
    return [numeros[(indice * len(numeros)) // cuantas] for indice in range(cuantas)]


class DecididoPor(StrEnum):
    """Cuál de las tres preguntas tuvo respuesta."""

    MARCADORES = "marcadores"
    HABILIDAD = "habilidad"
    NADIE = "nadie"


@dataclass(frozen=True, slots=True)
class Eleccion:
    """Qué habilidad atiende el documento, y por qué.

    ``veredicto`` es el de los marcadores en la última muestra que se miró --
    la de los encabezados o, si hubo segunda mirada, la que lleva las páginas
    leídas enteras --. ``validaciones`` está vacío cuando los marcadores
    decidieron, porque entonces no se consultó a nadie más.
    """

    tipo: DocumentType
    veredicto: TypeVerdict
    validaciones: dict[DocumentType, Validacion] = field(default_factory=dict)
    motivo: str = ""
    decidido_por: DecididoPor = DecididoPor.MARCADORES
    #: Qué páginas se leyeron enteras porque la banda superior no bastó.
    segunda_mirada: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "tipo": str(self.tipo),
            "etiqueta": self.tipo.label,
            "decidido_por": str(self.decidido_por),
            "motivo": self.motivo,
            "marcadores": self.veredicto.as_dict(),
            "validaciones": [
                validacion.as_dict() for validacion in self.validaciones.values()
            ],
            "segunda_mirada": list(self.segunda_mirada),
        }


#: La primera pregunta, cuando quien llama quiere hacerla por su propio camino:
#: recibe el documento y el motor de OCR con que muestrear, y devuelve el
#: veredicto de los marcadores.
PrimeraMirada = Callable[[PageSource, OcrEngine | None], TypeVerdict]


class Orquestador:
    """Elige la habilidad que atiende un documento, con OCR local y nada más."""

    def __init__(
        self,
        ocr: OcrEngine | None,
        *,
        segunda_mirada: bool = True,
        paginas_segunda: int = PAGINAS_SEGUNDA_MIRADA,
        primera_mirada: PrimeraMirada | None = None,
    ) -> None:
        self._ocr = ocr
        self._segunda_mirada = segunda_mirada
        self._paginas_segunda = max(0, paginas_segunda)
        #: Quién hace la primera pregunta. Por omisión, la muestra y los
        #: marcadores aquí mismo; el despachador la hace a través del
        #: inventario, que es por donde se reconoció siempre.
        self._primera_mirada = primera_mirada

    def elegir(self, source: PageSource) -> Eleccion:
        # Una sola lectura por imagen durante toda la elección. La primera
        # pregunta y la segunda miran la misma muestra, y si la primera se hizo
        # por otro camino no hay forma de pasarle el texto a la segunda; lo que
        # sí se puede es que el OCR no cobre -- en tiempo -- dos veces la misma
        # banda.
        motor = _LecturasRecordadas(self._ocr) if self._ocr is not None else None

        # 1. Los marcadores, como siempre.
        muestra: list[tuple[int, str]] | None = None
        if self._primera_mirada is None:
            muestra = muestrear(source, motor)
            veredicto = classify_pages(muestra)
        else:
            veredicto = self._primera_mirada(source, motor)
        if veredicto.is_identified:
            return Eleccion(
                tipo=veredicto.document_type,
                veredicto=veredicto,
                motivo="lo decidieron los marcadores impresos de la muestra",
            )

        # 2. Todas las habilidades, sobre la misma muestra.
        if muestra is None:
            muestra = muestrear(source, motor)
        validaciones = validar_todas(muestra)
        tipo, motivo = ganadora(validaciones)
        if tipo is not None:
            logger.info("el orquestador eligió %s: %s", tipo.label, motivo)
            return Eleccion(
                tipo=tipo,
                veredicto=veredicto,
                validaciones=validaciones,
                motivo=motivo,
                decidido_por=DecididoPor.HABILIDAD,
            )

        # 3. La página entera de lo que sólo se leyó por su encabezado.
        enteras = self._leer_enteras(source, motor, muestra)
        if not enteras:
            return self._nadie(veredicto, validaciones, motivo, ())

        completa = [(numero, enteras.get(numero, texto)) for numero, texto in muestra]
        leidas = tuple(sorted(enteras))
        veredicto = classify_pages(completa)
        if veredicto.is_identified:
            return Eleccion(
                tipo=veredicto.document_type,
                veredicto=veredicto,
                validaciones=validaciones,
                motivo=(
                    "lo decidieron los marcadores impresos al leer enteras las "
                    f"páginas {_lista(leidas)}"
                ),
                decidido_por=DecididoPor.MARCADORES,
                segunda_mirada=leidas,
            )

        validaciones = validar_todas(completa)
        tipo, motivo = ganadora(validaciones)
        if tipo is not None:
            logger.info(
                "el orquestador eligió %s al leer páginas enteras: %s", tipo.label, motivo
            )
            return Eleccion(
                tipo=tipo,
                veredicto=veredicto,
                validaciones=validaciones,
                motivo=f"{motivo}; leídas enteras las páginas {_lista(leidas)}",
                decidido_por=DecididoPor.HABILIDAD,
                segunda_mirada=leidas,
            )
        return self._nadie(veredicto, validaciones, motivo, leidas)

    # -- la segunda mirada ---------------------------------------------------

    def _leer_enteras(
        self,
        source: PageSource,
        motor: OcrEngine | None,
        muestra: Sequence[tuple[int, str]],
    ) -> dict[int, str]:
        """El texto de página entera de las hojas que sólo se leyeron por arriba.

        Sólo las que no tienen capa de texto suficiente: las que sí la tienen ya
        se leyeron enteras, y volver a leerlas con OCR sería pagar por un texto
        peor que el que hay.
        """
        if not self._segunda_mirada or motor is None or self._paginas_segunda == 0:
            return {}
        sin_capa = [numero for numero, _ in muestra if not _tiene_capa(source, numero)]
        elegidas = repartidas(sin_capa, self._paginas_segunda)
        if not elegidas:
            return {}
        return dict(muestrear(source, motor, banda=None, numeros=elegidas))

    @staticmethod
    def _nadie(
        veredicto: TypeVerdict,
        validaciones: dict[DocumentType, Validacion],
        motivo: str,
        leidas: tuple[int, ...],
    ) -> Eleccion:
        if leidas:
            motivo = f"{motivo}, ni leyendo enteras las páginas {_lista(leidas)}"
        return Eleccion(
            tipo=DocumentType.DESCONOCIDO,
            veredicto=veredicto,
            validaciones=validaciones,
            motivo=f"nadie validó: {motivo}",
            decidido_por=DecididoPor.NADIE,
            segunda_mirada=leidas,
        )


def _tiene_capa(source: PageSource, numero: int) -> bool:
    try:
        return len(source.text_of(numero)) >= MIN_SAMPLE_CHARS
    except Exception:  # noqa: BLE001 - sin capa legible es lo mismo que sin capa
        return False


def _lista(numeros: Sequence[int]) -> str:
    return ", ".join(str(numero) for numero in numeros)


class _LecturasRecordadas:
    """El mismo motor de OCR, sin leer dos veces la misma imagen.

    La clave es la imagen misma: rasterizar una página con la misma banda y la
    misma resolución da los mismos bytes, así que lo que la primera pregunta ya
    leyó la segunda lo encuentra hecho. Vive lo que dura una elección.
    """

    def __init__(self, ocr: OcrEngine) -> None:
        self._ocr = ocr
        self._leidas: dict[bytes, OcrResult] = {}

    def read(self, image_png: bytes) -> OcrResult:
        clave = hashlib.blake2b(image_png, digest_size=16).digest()
        leida = self._leidas.get(clave)
        if leida is None:
            leida = self._ocr.read(image_png)
            self._leidas[clave] = leida
        return leida

    def __getattr__(self, nombre: str):
        # Lo que no sea leer una imagen -- `read_codes`, la telemetría del
        # motor -- es del motor de verdad. Los nombres privados no se delegan:
        # preguntar por `_ocr` antes de que exista sería una recursión sin fin.
        if nombre.startswith("_"):
            raise AttributeError(nombre)
        return getattr(self._ocr, nombre)
