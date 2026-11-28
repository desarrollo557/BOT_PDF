from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date

from ..domain.anchor import normalized_lines
from ..domain.doctype import DocumentType, TypeVerdict, classify_pages
from ..domain.extraction import (
    RENGLONES_DE_LA_CABECERA,
    RENGLONES_DE_LA_HOJA,
    RawCandidate,
    abre_sin_numero,
    encabezado_sin_numero,
    extract_candidates,
    hoja_de,
    siguiente_en_la_cabecera,
)
from ..domain.fechas import fecha_de_expedicion
from ..domain.legibility import garble_score, is_garbled
from ..domain.page import PageClassification, Provenance
from ..domain.plantilla_de_pagina import (
    CARACTERES_LEGIBLES,
    Evidencia,
    Plantilla,
    plantilla_de,
)
from ..domain.resolution_code import ResolutionCode
from ..domain.scoring import Selection, opens_a_resolution, select_best
from ..domain.serie_del_legajo import (
    PREVIAS,
    anio_de_su_papel,
    anios_del_legajo,
    copias_fuera_de_la_serie,
    numeros_por_la_serie,
)
from ..domain.title import extract_title
from ..domain.titulo_impreso import titulo_impreso
from .control import Cancelled, NullRunControl, RunControl, hilos, mapear
from .diagnostico import explicar
from .ports import HEADER_BAND, Band, Crop, OcrEngine, PageSource, VisionOracle
from .progress import NullProgressReporter, ProgressEvent, ProgressReporter, Stage

#: El número de una resolución de rectoría: cinco o seis cifras («00086»).
_DE_RECTORIA = re.compile(r"^\d{5,6}$")
#: El de una de facultad con su año, en la forma única de ``extraction``: «026-2014».
_CON_SU_ANIO = re.compile(r"^(\d{3})-(\d{4})$")
#: El de una de facultad sin su año: «016».
_SIN_SU_ANIO = re.compile(r"^\d{3}$")
#: Lo que puede ser el número de una resolución leído en la banda.
_FORMA_DE_UN_NUMERO = re.compile(r"^(?:\d{3}(?:-\d{4})?|\d{5,6})$")
#: El consecutivo de una de facultad, con su año o sin él.
_CONSECUTIVO = re.compile(r"^(\d{3})(?:-\d{4})?$")
#: Los puntos de la plantilla de rectoría cuando debajo del encabezado firma el
#: rector (``plantilla_de``): sólo con él es la respuesta de rectoría.
_CON_EL_RECTOR = 3


def _legajo_de_facultad(analyses: list[PageAnalysis]) -> bool:
    """Si el legajo es de resoluciones internas: sus encabezados son, de largo, de facultad.

    La caja 00C003303 trae un PDF por año de resoluciones internas, con alguna
    copia de rectoría dentro («00139», «00238»). Al revés que en un legajo de
    rectoría, aquí la copia es la que va dentro.
    """
    de_facultad, de_rectoria = set(), set()
    for analysis in analyses:
        for candidate in analysis.candidates:
            if opens_a_resolution(candidate):
                (de_rectoria if _DE_RECTORIA.match(candidate.code.value) else de_facultad).add(candidate.code.value)
    return len(de_facultad) >= 3 and len(de_facultad) > 2 * len(de_rectoria)


def _un_numero_por_resolucion(classifications: list[PageClassification]) -> list[PageClassification]:
    """«026» y «026-2014» son la misma resolución si el legajo sólo trae ese año para ella.

    Unas hojas repiten el número con su año y otras sin él (caja 00C003303,
    2014: «026» en una página y «026-2014» en la siguiente), y la resolución se
    partía en dos archivos. El número sin año toma el del gemelo, si hay uno solo.

    Sólo en un legajo de un solo año (2026-11-27): en un tomo de varios, donde
    la numeración vuelve a empezar cada año, la «017» de 2009 no es la
    «017-2002». Ahí el año de cada una lo pone ``_con_su_anio``.
    """
    anios: dict[str, set[str]] = {}
    for clasificacion in classifications:
        if clasificacion.code is not None and (hallado := _CON_SU_ANIO.match(clasificacion.code.value)):
            anios.setdefault(hallado.group(1), set()).add(clasificacion.code.value)
    del_legajo = {codigo[-4:] for con_anio in anios.values() for codigo in con_anio}
    gemelos = {numero: next(iter(con_anio)) for numero, con_anio in anios.items() if len(con_anio) == 1}
    if not gemelos or len(del_legajo) > 1:
        return classifications
    return [
        replace(clasificacion, code=ResolutionCode(value=gemelos[clasificacion.code.value], raw=clasificacion.code.raw))
        if clasificacion.code is not None and clasificacion.code.value in gemelos
        else clasificacion
        for clasificacion in classifications
    ]

def _corridas(
    classifications: list[PageClassification], cortes: frozenset[int] = frozenset()
) -> list[tuple[ResolutionCode, list[int]]]:
    """Cada resolución como la deja la lectura: su código y los índices de sus páginas, en orden.

    Una corrida empieza en la página que declara un código distinto del
    abierto y sigue por las que no traen ninguno o repiten el mismo, como las
    hereda el agrupador. Las páginas de antes del primer código no son de
    ninguna. ``cortes`` son índices que empiezan corrida aunque repitan el
    código abierto (``_abre_otra_vez``).
    """
    corridas: list[tuple[ResolutionCode, list[int]]] = []
    abierto: ResolutionCode | None = None
    for indice, clasificacion in enumerate(classifications):
        if clasificacion.code is not None and (clasificacion.code != abierto or indice in cortes):
            abierto = clasificacion.code
            corridas.append((abierto, [indice]))
        elif abierto is not None:
            corridas[-1][1].append(indice)
    return corridas


def _abre_otra_vez(classifications: list[PageClassification], analyses: list[PageAnalysis]) -> frozenset[int]:
    """Las páginas que abren de nuevo, con su encabezado y su emisor, el número de la resolución abierta.

    Una resolución tiene una sola primera hoja. Otra con el mismo número justo
    detrás es otra resolución que la capa leyó con ese número: la 043 de 1998
    lleva el 3 escrito encima del 2 de «042», y la capa dice 042 (07-115 TOMO 1,
    pág. 68; 2026-11-27). Se marca aquí y ``numeros_por_la_serie`` decide si
    la serie le da otro; si no, sigue junta: ante la duda se une.
    """
    del_analisis = {a.page_number: a for a in analyses}
    cortes: set[int] = set()
    abierto: ResolutionCode | None = None
    for indice, clasificacion in enumerate(classifications):
        if clasificacion.code is None:
            continue
        analisis = del_analisis.get(clasificacion.page_number)
        # Primera hoja entera: el encabezado, quien la expide y su asunto
        # («Por la cual…»), que una hoja siguiente nunca repite.
        if (
            clasificacion.code == abierto
            and analisis is not None
            and analisis.plantilla is not None
            and analisis.plantilla.plantilla is Plantilla.RESOLUCION_DE_FACULTAD
            and _ASUNTO_DE_UNA_PRIMERA_HOJA.match(analisis.title or "")
        ):
            cortes.add(indice)
        abierto = clasificacion.code
    return frozenset(cortes)


#: El asunto con que empieza la primera hoja de una resolución.
_ASUNTO_DE_UNA_PRIMERA_HOJA = re.compile(r"^\W*(?:POR|MEDIANTE)\b", re.IGNORECASE)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    header_band: Band = HEADER_BAND
    ocr_dpi: int = 200
    crop_dpi: int = 150

    #: Below this, the embedded text layer is treated as absent rather than poor.
    min_text_layer_chars: int = 80

    #: A page with no anchor but plenty of text is a continuation page and costs
    #: nothing. Below this threshold we cannot tell "continuation" from "the OCR
    #: failed", and only then is escalation justified.
    degraded_text_chars: int = 200

    #: Cuántas páginas se guardan para reconocer de qué documento se trata.
    #: Doce repartidas de punta a punta ven la mezcla de una caja mal ordenada,
    #: y en un libro homogéneo todas dicen lo mismo.
    sample_pages: int = 12

    #: Cuánto texto se conserva de cada página para ese reconocimiento. Lo justo
    #: para que quepan las leyendas impresas del encabezado y del pie; guardar
    #: la página entera de cuatrocientas páginas sería medio megabyte por
    #: documento a cambio de nada.
    sample_chars: int = 1500

    #: Crops per request to the vision model. Header bands are small, so tiling
    #: them amortises the prompt across a dozen pages.
    mosaic_size: int = 12

    max_workers: int = 8

    #: Volver a leer con OCR la banda del encabezado en las páginas que declaran
    #: un número nuevo, y comparar con lo que dijo la capa de texto.
    #:
    #: Es una página por resolución, no una por página: sólo se verifica lo que
    #: decide algo. Y es justamente donde importa -- un número mal leído en una
    #: página de continuación no cambia nada, porque hereda; mal leído en la
    #: página que lo declara, abre un archivo con el nombre equivocado y se lleva
    #: dentro las páginas de otra resolución.
    verify_declarations: bool = True


@dataclass(frozen=True, slots=True)
class PageAnalysis:
    """Everything learned about a page locally, before sequence context."""

    page_number: int
    candidates: list[RawCandidate]
    provenance: Provenance
    text_length: int
    #: Lo que se leyó de la página, recortado. Sirve para reconocer el tipo de
    #: documento sin volver a leer nada: sea cual sea el peldaño que respondió
    #: -- capa de texto, OCR de banda u OCR de página entera -- lo que llegó
    #: aquí es lo que el sistema vio.
    text: str = ""
    title: str | None = None
    failed: bool = False
    error: str | None = None
    #: La capa de texto de esta página venía mal decodificada y hubo que mirar
    #: la imagen. Se guarda para poder contarlo: es una propiedad del documento
    #: de origen, no un incidente del proceso, y quien vuelva a este material
    #: tiene que saber que llegó así.
    mis_decoded: bool = False
    #: Qué plantilla muestra la página, por lo que trae impreso. Decide qué
    #: componente la atiende: una resolución de facultad o un oficio detrás de
    #: una resolución abierta son su soporte y no abren nada.
    plantilla: Evidencia | None = None
    #: El número de su encabezado se leyó con OCR en la banda, porque la capa
    #: de texto traía «Resolución No.» en blanco.
    por_la_banda: bool = False
    #: Abre una resolución -- encabezado y, debajo, su asunto o quien la
    #: expide -- y su número no se dejó leer ni en la capa ni en la banda.
    sin_numero: bool = False

    def is_degraded(self, config: PipelineConfig) -> bool:
        """Whether "no code found" might mean "we could not read the page".

        Only OCR can be silent by failing. If the embedded text layer was
        accepted -- it cleared ``min_text_layer_chars`` -- then it was read, and
        a page with no anchor is simply a continuation page. Escalating those
        would send most of a digital document to a model to be told nothing.
        """
        if self.failed:
            return True
        if self.provenance is Provenance.TEXT_LAYER:
            return False
        return self.text_length < config.degraded_text_chars


@dataclass(slots=True)
class PipelineStats:
    """Where the work actually went. The token bill is auditable, not assumed."""

    by_provenance: Counter[str] = field(default_factory=Counter)
    escalated: int = 0
    vision_requests: int = 0
    resolved_by_context: int = 0
    #: Qué resultó ser el documento, decidido sobre lo que se leyó de él y nunca
    #: sobre el nombre del archivo.
    document_type: str = str(DocumentType.DESCONOCIDO)
    type_confidence: float = 0.0
    #: Páginas cuya capa de texto venía mal decodificada por la fuente y hubo
    #: que leer de la imagen. Es una propiedad del PDF de origen y se cuenta
    #: aparte: si son muchas, el documento hay que volver a generarlo, no
    #: volver a procesarlo.
    #:
    #: Se guardan los números y no sólo el total porque un recuento no se puede
    #: revisar. "19 páginas venían mal codificadas" no le dice al operador
    #: cuáles abrir, y son justamente las páginas donde una lectura equivocada
    #: pudo escribir en el disco un número que no es.
    mis_decoded_pages: list[int] = field(default_factory=list)
    #: Páginas que declaran un número y se releyeron con OCR para contrastarlas.
    verified: int = 0
    #: Página -> las dos lecturas que no coincidieron. Es la cuenta honesta de
    #: cuánto se equivoca la capa de texto en este material.
    disagreements: dict[int, str] = field(default_factory=dict)
    #: page number -> what went wrong. A page that blows up is isolated, never
    #: allowed to take the other 399 with it.
    failures: dict[int, str] = field(default_factory=dict)
    #: Cuántas páginas mostró cada plantilla.
    plantillas: Counter[str] = field(default_factory=Counter)
    #: Página -> la plantilla por la que se archivó como soporte de la
    #: resolución abierta en vez de abrir una propia.
    soportes: dict[int, str] = field(default_factory=dict)
    #: Páginas que abrieron la resolución siguiente de la serie por su número,
    #: con la palabra «resolución» destrozada por el OCR.
    por_secuencia: list[int] = field(default_factory=list)
    #: Páginas con «Resolución No.» y el número en blanco en la capa de texto,
    #: cuyo número se leyó con OCR en la banda del encabezado (2026-11-27).
    por_la_banda: list[int] = field(default_factory=list)
    #: Primera página de cada resolución de facultad cuyo año no lo dice su
    #: papel y se sacó de la serie, y de las que no se pudo saber ni así.
    anio_por_la_serie: list[int] = field(default_factory=list)
    sin_anio: list[int] = field(default_factory=list)
    #: Página -> el número que se leyó en la banda y el que dice la serie,
    #: cuando el leído era el de otra resolución del mismo año.
    numero_por_la_serie: dict[int, str] = field(default_factory=dict)
    #: Las hojas antes de la primera resolución, y qué se hizo con ellas.
    previas: dict[int, str] = field(default_factory=dict)
    #: Páginas que abren una resolución sin número legible, y el que les dio
    #: la serie si el hueco lo decía (``_los_sin_numero``); si no, van con la
    #: anterior, ante la duda se une.
    sin_numero: dict[int, str] = field(default_factory=dict)

    @property
    def mis_decoded(self) -> int:
        """Cuántas fueron. Se conserva porque el informe la venía publicando."""
        return len(self.mis_decoded_pages)

    @property
    def total_pages(self) -> int:
        return sum(self.by_provenance.values())

    @property
    def vision_page_ratio(self) -> float:
        return self.escalated / self.total_pages if self.total_pages else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "by_provenance": dict(self.by_provenance),
            "escalated": self.escalated,
            "vision_requests": self.vision_requests,
            "resolved_by_context": self.resolved_by_context,
            "mis_decoded": self.mis_decoded,
            "mis_decoded_pages": sorted(self.mis_decoded_pages),
            "document_type": self.document_type,
            "type_confidence": round(self.type_confidence, 4),
            "verified": self.verified,
            "disagreements": {
                str(page): value for page, value in sorted(self.disagreements.items())
            },
            "vision_page_ratio": round(self.vision_page_ratio, 4),
            "failed_pages": {str(page): error for page, error in sorted(self.failures.items())},
            "plantillas": dict(self.plantillas),
            "soportes": {str(page): cual for page, cual in sorted(self.soportes.items())},
            "por_secuencia": sorted(self.por_secuencia),
            "por_la_banda": sorted(self.por_la_banda),
            "anio_por_la_serie": sorted(self.anio_por_la_serie),
            "sin_anio": sorted(self.sin_anio),
            "numero_por_la_serie": {str(page): que for page, que in sorted(self.numero_por_la_serie.items())},
            "previas": {str(page): que for page, que in sorted(self.previas.items())},
            "sin_numero": {str(page): que for page, que in sorted(self.sin_numero.items())},
        }


def _geometry_of(
    source: PageSource, page_number: int, text: str
) -> list[tuple[float, float]] | None:
    """Dónde está cada renglón de la página, si la fuente sabe decirlo.

    Las candidatas se localizan por número de renglón, así que la geometría sólo
    sirve si va en el mismo orden que el texto. Se comprueba antes de usarla en
    vez de darlo por hecho: una lista desalineada le negaría el encabezado a
    páginas que sí lo tienen, y perder una resolución en silencio es peor que
    decidir sin geometría, que es lo que se hacía hasta ahora.

    Una fuente que no sepa dónde están sus renglones -- un doble de prueba, o el
    día que se lea de otra biblioteca -- devuelve una lista vacía y aquí se
    responde ``None``, sin que nada más se entere.
    """
    boxes = getattr(source, "boxes_of", None)
    if boxes is None:
        return None
    try:
        cajas = boxes(page_number)
    except Exception:  # noqa: BLE001 - saber dónde está un renglón no vale una página
        logger.debug("no se pudo leer la geometría de la página %s", page_number, exc_info=True)
        return None

    renglones = text.splitlines()
    if len(cajas) != len(renglones):
        logger.debug(
            "la geometría de la página %s no cuadra con su texto (%s cajas, %s renglones)",
            page_number,
            len(cajas),
            len(renglones),
        )
        return None
    if any(caja.text.strip() != renglon.strip() for caja, renglon in zip(cajas, renglones, strict=True)):
        logger.debug("la geometría de la página %s no corresponde a su texto", page_number)
        return None
    return [(caja.center_x, caja.top) for caja in cajas]


class PageAnalyzer:
    """Rungs 0 to 2 of the cascade: text layer, header OCR, full-page OCR.

    Nothing here depends on neighbouring pages, which is precisely why it can be
    fanned out across workers without any coordination.
    """

    def __init__(self, ocr: OcrEngine, config: PipelineConfig | None = None) -> None:
        self._ocr = ocr
        self._config = config or PipelineConfig()

    def analyse(self, source: PageSource, page_number: int) -> PageAnalysis:
        config = self._config

        text = source.text_of(page_number)
        # Tener texto no es lo mismo que poder leerlo. Una fuente con el mapa de
        # caracteres equivocado devuelve páginas enteras de basura que superan
        # cualquier umbral de longitud: la palabra "RESOLUCIÓN" sale como
        # `<^OLVCIÓ?{%` y la página pasaba por una continuación cualquiera,
        # heredando en silencio el número de la resolución anterior. Cuando el
        # texto no se sostiene, la página baja a los peldaños que miran la
        # imagen, que es donde los glifos dibujados sí dicen lo que dicen.
        mal_decodificada = is_garbled(text)
        if len(text) >= config.min_text_layer_chars and not mal_decodificada:
            # Free rung. On digital PDFs this answers the whole document.
            candidatos = extract_candidates(text, _geometry_of(source, page_number, text))
            # Si la cabecera no dio número, puede que la capa lo traiga en blanco.
            en_la_cabecera = any(c.line_index < RENGLONES_DE_LA_HOJA for c in candidatos)
            de_la_banda = [] if en_la_cabecera else self._numero_en_blanco(source, page_number, text)
            sin_numero = not en_la_cabecera and not de_la_banda and abre_sin_numero(text)
            return PageAnalysis(
                page_number=page_number,
                candidates=candidatos + de_la_banda,
                provenance=Provenance.OCR_REGION if de_la_banda else Provenance.TEXT_LAYER,
                text_length=len(text),
                text=text[: config.sample_chars],
                title=extract_title(text, titulo_encima=True),
                plantilla=plantilla_de(text),
                por_la_banda=bool(de_la_banda),
                sin_numero=sin_numero,
            )

        if mal_decodificada:
            logger.info(
                "la capa de texto de la página %s viene mal decodificada "
                "(%.1f mayúsculas interiores por mil); se lee la imagen",
                page_number,
                garble_score(text),
            )

        band_image = source.render(page_number, config.header_band, config.ocr_dpi)
        band = self._ocr.read(band_image)
        candidates = extract_candidates(band.text)
        if candidates:
            return PageAnalysis(
                page_number=page_number,
                candidates=candidates,
                provenance=Provenance.OCR_REGION,
                text_length=len(band.text),
                text=band.text[: config.sample_chars],
                title=extract_title(band.text, titulo_encima=True),
                mis_decoded=mal_decodificada,
                plantilla=plantilla_de(band.text),
            )

        # The header crop came back empty. Either the number is somewhere else on
        # the page or this is a continuation page; the full render tells us which.
        full_image = source.render(page_number, None, config.ocr_dpi)
        full = self._ocr.read(full_image)
        return PageAnalysis(
            page_number=page_number,
            candidates=extract_candidates(full.text),
            provenance=Provenance.OCR_FULL_PAGE,
            text_length=len(full.text),
            text=full.text[: config.sample_chars],
            title=extract_title(full.text, titulo_encima=True),
            mis_decoded=mal_decodificada,
            plantilla=plantilla_de(full.text),
        )

    def _numero_en_blanco(self, source: PageSource, page_number: int, text: str) -> list[RawCandidate]:
        """El número de un encabezado que la capa de texto trae en blanco, leído con OCR en su banda.

        Los tomos de decanatura de 1999 imprimen «Resolución No. ____ de 1.9__»
        y el número se escribió después a máquina: la capa no lo trae y la
        resolución entera se archivaba dentro de la anterior (01-046 TOMO 3: 15
        resoluciones de 46, 2026-11-27). Una lectura de OCR de la banda por
        página así, y sólo por ésas: Tesseract primero. Si falla, la página
        sigue como antes, sin número: una lectura que no se pudo hacer no tumba
        la página.
        """
        if not encabezado_sin_numero(text):
            return []
        try:
            band = self._ocr.read(source.render(page_number, self._config.header_band, self._config.ocr_dpi))
        except Cancelled:
            raise
        except Exception:  # noqa: BLE001 - una lectura de más no tumba la página
            logger.debug("no se pudo leer la banda de la página %s", page_number, exc_info=True)
            return []
        # La hoja la dice la capa aunque la banda no la recorte entera. Y sólo
        # números con la forma de uno de verdad -- tres cifras, con su año o
        # sin él, o las cinco de rectoría --: la banda de la pág. 39 del tomo
        # 001-061 leyó «7770» y abría una resolución que no existe.
        hoja = hoja_de(text)
        return [
            replace(candidato, hoja=candidato.hoja if candidato.hoja is not None else hoja)
            for candidato in extract_candidates(band.text)
            if _FORMA_DE_UN_NUMERO.match(candidato.code.value)
        ]


class ClassificationPipeline:
    """Drives the full cascade for one document."""

    def __init__(
        self,
        ocr: OcrEngine,
        vision: VisionOracle | None = None,
        config: PipelineConfig | None = None,
        progress: ProgressReporter | None = None,
        control: RunControl | None = None,
    ) -> None:
        self._config = config or PipelineConfig()
        self._control = control or NullRunControl()
        self._ocr = ocr
        self._analyzer = PageAnalyzer(ocr, self._config)
        self._vision = vision
        self._progress = progress or NullProgressReporter()

    def classify(self, source: PageSource) -> tuple[list[PageClassification], PipelineStats]:
        self._report(ProgressEvent(stage=Stage.OPENED, page_count=source.page_count))
        analyses = self._analyse_all(source)
        self._report(
            ProgressEvent(
                stage=Stage.IDENTIFYING,
                done=0,
                total=self._config.sample_pages,
                detail="reconociendo de qué documento se trata",
            )
        )
        verdict = self._identify(analyses)
        classifications, stats, unresolved = self._resolve_with_context(analyses)
        stats.document_type = str(verdict.document_type)
        stats.type_confidence = verdict.confidence
        self._report(
            ProgressEvent(
                stage=Stage.IDENTIFYING,
                done=self._config.sample_pages,
                total=self._config.sample_pages,
                detail=verdict.document_type.label,
            )
        )
        if self._config.verify_declarations:
            classifications, unresolved = self._verify_declarations(
                source, analyses, classifications, unresolved, stats
            )
        if unresolved:
            classifications = self._escalate(source, classifications, unresolved, stats)
        classifications = self._copias_dentro(classifications, stats)
        if _legajo_de_facultad(analyses):
            # Un legajo de facultad (2026-11-27): la que abre sin número, con el
            # de la serie si el hueco lo dice; cada resolución con el año de su
            # papel, y las hojas de antes de la primera, con su dueño.
            classifications = self._los_sin_numero(classifications, analyses, stats)
            classifications = self._con_su_anio(classifications, analyses, source, stats)
            classifications = self._las_previas(classifications, analyses, stats)
        return _un_numero_por_resolucion(classifications), stats

    @staticmethod
    def _los_sin_numero(
        classifications: list[PageClassification], analyses: list[PageAnalysis], stats: PipelineStats
    ) -> list[PageClassification]:
        """La resolución que abre sin número legible, con el de la serie cuando el hueco lo dice.

        Su primera hoja trae el encabezado y quien la expide, pero el número va
        a máquina sobre la raya y ni la capa ni el OCR de la banda lo leen: se
        archivaba como soporte de la anterior (07-115 TOMO 1: la del Consejo de
        la pág. 174 dentro de la 097, 2026-11-27). Si entre la resolución que la
        trae y la siguiente faltan justo tantos números como hojas así hay, son
        ésos, en orden: la 097, una sin número y la 099 dan la 098. Va a
        Revisión. Si el hueco no cuadra, sigue con la anterior: ante la duda se
        une, y queda anotada.
        """
        sin_numero = {a.page_number for a in analyses if a.sin_numero}
        if not sin_numero:
            return classifications
        corridas = _corridas(classifications)
        resultado = list(classifications)
        for posicion, (codigo, indices) in enumerate(corridas):
            sueltas = [i for i in indices[1:] if classifications[i].page_number in sin_numero]
            if not sueltas:
                continue
            numero = _CONSECUTIVO.match(codigo.value)
            siguiente = next(
                (m for c, _ in corridas[posicion + 1 :] if (m := _CONSECUTIVO.match(c.value))), None
            )
            hueco = int(siguiente.group(1)) - int(numero.group(1)) - 1 if numero and siguiente else -1
            if hueco != len(sueltas):
                for i in sueltas:
                    stats.sin_numero[classifications[i].page_number] = (
                        f"abre una resolución sin número legible; va con la {codigo.value}"
                    )
                continue
            for desplazamiento, i in enumerate(sueltas, start=1):
                valor = f"{int(numero.group(1)) + desplazamiento:03d}"
                resultado[i] = replace(
                    resultado[i], code=ResolutionCode(value=valor, raw=""), ambiguous=True, title=None
                )
                stats.sin_numero[classifications[i].page_number] = f"sin número legible; la serie dice {valor}"
                # Ya no es el soporte de la anterior: abre la suya.
                stats.soportes.pop(classifications[i].page_number, None)
        return resultado

    @staticmethod
    def _con_su_anio(
        classifications: list[PageClassification],
        analyses: list[PageAnalysis],
        source: PageSource,
        stats: PipelineStats,
    ) -> list[PageClassification]:
        """«016» pasa a «016-2008»: el número completo, con el año de la propia resolución.

        En un tomo de varios años la numeración vuelve a empezar cada año, y el
        agrupador junta por número: la 001 de 2003 se llevaba las hojas de la
        001 de 2004 y de la de 2005 (TOMO 1 2003-2010: la 001 en las págs. 2-6,
        153-157 y 199-200; 2026-11-27). Cada resolución -- la página que la
        abre y las que la siguen sin abrir otra -- toma el año de su papel
        (``anio_de_su_papel``) o, si no lo dice, el de la serie
        (``anios_de_la_serie``), y se anota. Las que ya traían el año
        («017-2002») y las de rectoría no cambian; la que no se puede fechar
        ni así se queda con su número solo.
        """
        texto_leido = {a.page_number: a.text for a in analyses}

        def texto_de(pagina: int) -> str:
            leido = texto_leido.get(pagina, "")
            try:
                capa = source.text_of(pagina)
            except Exception:  # noqa: BLE001 - el año es un dato más, no un requisito
                return leido
            return capa if len(capa.strip()) >= len(leido.strip()) else leido

        otra_vez = _abre_otra_vez(classifications, analyses)
        corridas = _corridas(classifications, otra_vez)
        numeros: list[int | None] = []
        anios: list[int | None] = []
        fechas: list[date | None] = []
        for codigo, indices in corridas:
            fecha = None
            if (con_anio := _CON_SU_ANIO.match(codigo.value)) is not None:
                numeros.append(int(con_anio.group(1)))
                anios.append(int(con_anio.group(2)))
            elif _SIN_SU_ANIO.match(codigo.value):
                textos = [texto_de(classifications[i].page_number) for i in indices]
                fecha = fecha_de_expedicion(textos, numero=codigo.value)
                numeros.append(int(codigo.value))
                anios.append(fecha.year if fecha else anio_de_su_papel(textos, numero=codigo.value))
            else:
                numeros.append(None)
                anios.append(None)
            fechas.append(fecha)
        completos = anios_del_legajo(numeros, anios, fechas)
        # El número leído con OCR en la banda, si choca con otra del mismo año,
        # es el siguiente al de la anterior (``numeros_por_la_serie``).
        de_la_banda = {a.page_number for a in analyses if a.por_la_banda}
        renumerados = numeros_por_la_serie(
            numeros,
            [anio for anio, _ in completos],
            [
                (classifications[indices[0]].page_number in de_la_banda or indices[0] in otra_vez)
                and bool(_SIN_SU_ANIO.match(codigo.value))
                for codigo, indices in corridas
            ],
        )

        resultado = list(classifications)
        for (codigo, indices), (anio, por_la_serie), (numero, renumerado) in zip(
            corridas, completos, renumerados, strict=True
        ):
            if not _SIN_SU_ANIO.match(codigo.value):
                continue
            primera = classifications[indices[0]].page_number
            if anio is None:
                stats.sin_anio.append(primera)
                continue
            if por_la_serie:
                stats.anio_por_la_serie.append(primera)
            completo = ResolutionCode(value=f"{numero or int(codigo.value):03d}-{anio}", raw=codigo.raw)
            for indice in indices:
                if resultado[indice].code == codigo:
                    resultado[indice] = replace(
                        resultado[indice],
                        code=completo,
                        # El número de la serie no es el que se leyó: a Revisión.
                        ambiguous=resultado[indice].ambiguous or (renumerado and indice == indices[0]),
                    )
            if renumerado:
                stats.numero_por_la_serie[primera] = f"se leyó {codigo.value} y la serie dice {numero:03d}"
        return resultado

    @staticmethod
    def _las_previas(
        classifications: list[PageClassification], analyses: list[PageAnalysis], stats: PipelineStats
    ) -> list[PageClassification]:
        """Las hojas antes de la primera resolución, en su PDF y con su fila, nunca en cuarentena.

        La pág. 1 de «1992-2002- tomo 2» es una SOLICITUD DE EXAMEN que viene
        antes de la resolución 062 (la de la 061, que quedó en el tomo
        anterior), y se iba a «_quarantine.pdf» sin fila (2026-11-27). Con
        algo legible, van juntas en su propio documento, con el título que
        imprimen (``titulo_impreso``) para nombrarlo: el código
        «PREVIAS-<página>». Si todas están en blanco -- la hoja de guarda de un
        tomo --, van con la primera resolución: no traen nada que no sea suyo.
        La regla de no adivinar sigue: ninguna hoja con texto entra en una
        resolución que no la nombra.
        """
        primera = next((i for i, c in enumerate(classifications) if c.code is not None), None)
        if not primera:
            return classifications
        texto = {a.page_number: a.text for a in analyses}
        previas = classifications[:primera]
        legibles = [c for c in previas if len(texto.get(c.page_number, "").strip()) >= CARACTERES_LEGIBLES]
        resultado = list(classifications)
        if not legibles:
            codigo = classifications[primera].code
            for indice, clasificacion in enumerate(previas):
                resultado[indice] = replace(clasificacion, code=codigo, title=None, ambiguous=False)
                stats.previas[clasificacion.page_number] = "en blanco: va con la primera resolución"
            return resultado
        titulo = next((t for c in legibles if (t := titulo_impreso(texto.get(c.page_number, "")))), None)
        codigo = ResolutionCode(value=f"{PREVIAS}-{previas[0].page_number}", raw=titulo or "")
        for indice, clasificacion in enumerate(previas):
            # Sin número no hay nada en disputa: no van a Revisión por «códigos en conflicto».
            resultado[indice] = replace(
                clasificacion, code=codigo, title=titulo if indice == 0 else None, ambiguous=False
            )
            stats.previas[clasificacion.page_number] = f"su propio documento: {titulo or 'sin título impreso'}"
        return resultado

    @staticmethod
    def _copias_dentro(
        classifications: list[PageClassification], stats: PipelineStats
    ) -> list[PageClassification]:
        """La copia de otra resolución de rectoría va dentro de la que la trae.

        Al final, después de la IA, para que valga también para lo que ella
        decidió. Ver ``serie_del_legajo``.
        """
        copias = copias_fuera_de_la_serie(
            [c.code.value if c.code is not None else None for c in classifications]
        )
        if not copias:
            return classifications
        dentro = []
        for clasificacion in classifications:
            if clasificacion.code is not None and clasificacion.code.value in copias:
                stats.soportes[clasificacion.page_number] = f"copia de la resolución {clasificacion.code.value}"
                clasificacion = replace(
                    clasificacion, code=None, ambiguous=False, title=None, plantilla="copia de otra resolución"
                )
            dentro.append(clasificacion)
        return dentro

    def _identify(self, analyses: list[PageAnalysis]) -> TypeVerdict:
        """De qué documento se trata, según lo que se leyó de él.

        Se decide después de leer y no antes, porque leer es justamente lo que
        pone el texto sobre la mesa: en un escaneo sin capa de texto, la única
        forma de reconocer el formulario impreso es haberlo pasado por el OCR.
        """
        legibles = [a for a in analyses if a.text]
        if not legibles:
            return classify_pages([])
        paso = max(1, len(legibles) // self._config.sample_pages)
        muestra = legibles[::paso][: self._config.sample_pages]
        return classify_pages([(a.page_number, a.text) for a in muestra])

    def _report(self, event: ProgressEvent) -> None:
        """Telemetry is never allowed to break the work it is describing."""
        try:
            self._progress.emit(event)
        except Exception:  # noqa: BLE001
            logger.debug("progress reporter raised, continuing", exc_info=True)

    # -- rungs 0-2, fanned out ------------------------------------------------

    def _analyse_all(self, source: PageSource) -> list[PageAnalysis]:
        pages = range(1, source.page_count + 1)
        workers = max(1, min(self._config.max_workers, source.page_count))
        if workers == 1:
            return [self._analyse_one(source, n) for n in pages]

        # Threads, not processes: the expensive calls are native (MuPDF render,
        # Tesseract) and release the GIL, so this scales with cores without
        # paying to serialise page images across a process boundary.
        with hilos(workers) as pool:
            return mapear(pool, lambda n: self._analyse_one(source, n), pages, self._control)

    def _analyse_one(self, source: PageSource, page_number: int) -> PageAnalysis:
        """Analyse one page, containing any failure to that page.

        La orden de pausar o cancelar se atiende justo aquí, antes de empezar la
        página: es el punto del recorrido en que no hay nada a medio leer ni a
        medio escribir.

        A corrupt page, a font MuPDF chokes on, an OCR process that dies: none of
        those are a reason to lose the other 399 pages. The page is marked
        unreadable and routed to review, and the document carries on.
        """
        self._control.check()
        try:
            analysis = self._analyzer.analyse(source, page_number)
        except Cancelled:
            # Detener no es que la página esté dañada: se sale, no se anota.
            raise
        except Exception as error:  # noqa: BLE001 - reported, not swallowed
            logger.warning("page %s failed to analyse", page_number, exc_info=True)
            analysis = PageAnalysis(
                page_number=page_number,
                candidates=[],
                provenance=Provenance.NONE,
                text_length=0,
                failed=True,
                error=explicar(error),
            )

        self._report(
            ProgressEvent(
                stage=Stage.PAGE,
                page_number=page_number,
                page_count=source.page_count,
                provenance=str(analysis.provenance),
                failed=analysis.failed,
                detail=analysis.error,
            )
        )
        return analysis

    # -- rung 3: sequence context, free ---------------------------------------

    def _resolve_with_context(
        self, analyses: list[PageAnalysis]
    ) -> tuple[list[PageClassification], PipelineStats, list[int]]:
        stats = PipelineStats()
        classifications: list[PageClassification] = []
        unresolved: list[int] = []
        previous: ResolutionCode | None = None
        #: Los números que la resolución abierta ha nombrado en su propio texto.
        #:
        #: Una resolución de rectoría declara en su CONSIDERANDO de qué se
        #: funda: "Que el decano de la FACULTAD DE CIENCIAS SOCIALES Y EDUCACION
        #: mediante resolución N° 002-2023 del 24 del mes de enero del año 2023
        #: solicitó a este despacho autorización...". Lo que nombra ahí viene
        #: encuadernado detrás, como anexo, y trae su propio encabezado impreso.
        #:
        #: Guardarlo es lo que distingue un anexo de una resolución nueva, que
        #: sobre el papel se ven exactamente igual. Se vacía al abrir una unidad
        #: nueva: lo que anunció la anterior no dice nada de la siguiente.
        anunciados: set[str] = set()
        #: Los números de los soportes que la resolución abierta lleva detrás
        #: -- la 006 del decano en la 00316 --: sus hojas siguientes repiten
        #: su encabezado sin decir ya quién la expide, y tampoco abren nada.
        soportes_del_abierto: set[str] = set()
        de_facultad = _legajo_de_facultad(analyses)

        for analysis in analyses:
            stats.by_provenance[str(analysis.provenance)] += 1
            if analysis.plantilla is not None:
                stats.plantillas[str(analysis.plantilla.plantilla)] += 1
            if analysis.por_la_banda:
                stats.por_la_banda.append(analysis.page_number)
            if previous is not None and self._es_soporte(
                analysis, previous, soportes_del_abierto, de_facultad=de_facultad
            ):
                # Lo que la página trae de «RESOLUCIÓN No.» es la resolución
                # con que un decano pidió algo, o lo que cita un oficio: es el
                # soporte de la resolución abierta y va en su archivo. Ni abre
                # una unidad ni sube a la IA, que no tiene nada que decidir.
                soportes_del_abierto.update(
                    candidate.code.value
                    for candidate in analysis.candidates
                    if candidate.code != previous
                )
                cual = (
                    analysis.plantilla.plantilla
                    if analysis.plantilla is not None and analysis.plantilla.es_soporte
                    else "hoja de un soporte"
                )
                stats.soportes[analysis.page_number] = str(cual)
                classifications.append(
                    PageClassification(
                        page_number=analysis.page_number,
                        code=None,
                        provenance=analysis.provenance,
                        plantilla=str(cual),
                    )
                )
                continue
            if analysis.mis_decoded:
                stats.mis_decoded_pages.append(analysis.page_number)
            if analysis.failed:
                stats.failures[analysis.page_number] = analysis.error or "unknown error"
            if de_facultad:
                # En un legajo de internas, un número de rectoría no abre nada:
                # es la copia con que rectoría respondió, y suele traer también
                # el número de la interna («00139» con «008-2016», 2016, pág. 16).
                analysis = replace(
                    analysis,
                    candidates=[c for c in analysis.candidates if not _DE_RECTORIA.match(c.code.value)],
                )
            selection = select_best(
                analysis.candidates,
                previous_code=previous,
                announced_by_open_unit=anunciados,
            )

            siguiente = self._siguiente_de_la_serie(analysis, selection, previous)
            if siguiente is not None:
                # Peldaño de la secuencia: la cabecera trae el número que sigue
                # al de la abierta junto a lo que fue «resolución», aunque el OCR
                # destrozara esa palabra. Gratis, y sin preguntarle a nadie.
                stats.por_secuencia.append(analysis.page_number)
                classifications.append(
                    PageClassification(
                        page_number=analysis.page_number,
                        code=siguiente,
                        provenance=analysis.provenance,
                        title=analysis.title,
                        plantilla=str(analysis.plantilla.plantilla) if analysis.plantilla else None,
                    )
                )
                anunciados = set()
                soportes_del_abierto = set()
                previous = siguiente
                continue

            if selection is None:
                if analysis.is_degraded(self._config):
                    # We cannot tell a continuation page from a failed read.
                    unresolved.append(analysis.page_number)
                    classifications.append(
                        PageClassification(
                            page_number=analysis.page_number,
                            code=None,
                            provenance=analysis.provenance,
                            ambiguous=True,
                        )
                    )
                else:
                    # Healthy text with no anchor: a continuation page. Grouping
                    # inherits it for free, so it never reaches a model.
                    classifications.append(
                        PageClassification(
                            page_number=analysis.page_number,
                            code=None,
                            provenance=analysis.provenance,
                        )
                    )
                continue

            if selection.ambiguous:
                unresolved.append(analysis.page_number)
            elif self._used_context(analysis, selection, previous):
                stats.resolved_by_context += 1

            classifications.append(
                PageClassification(
                    page_number=analysis.page_number,
                    code=selection.code,
                    confidence=selection.confidence,
                    provenance=analysis.provenance,
                    ambiguous=selection.ambiguous,
                    title=analysis.title,
                    plantilla=str(analysis.plantilla.plantilla) if analysis.plantilla else None,
                )
            )
            if selection.code != previous:
                # Unidad nueva: lo que anunciaba la anterior deja de contar.
                anunciados = set()
                soportes_del_abierto = set()
            previous = selection.code
            # Y lo que esta página nombra queda anotado a cuenta de la unidad
            # abierta. La página que abre una resolución es la que trae su
            # CONSIDERANDO, así que es aquí donde se recogen sus anexos.
            anunciados.update(
                candidate.code.value
                for candidate in analysis.candidates
                if candidate.code != selection.code
            )

        stats.escalated = len(unresolved)
        return classifications, stats, unresolved

    @staticmethod
    def _siguiente_de_la_serie(
        analysis: PageAnalysis, selection: Selection | None, abierta: ResolutionCode | None
    ) -> ResolutionCode | None:
        """La resolución que sigue a la abierta, si esta página la encabeza y nada más la abrió.

        Sólo cuando la página no abrió nada por sí misma -- o continuaba la
        abierta --, no es un soporte y su cabecera no repite el número de la
        abierta, que es lo que llevan sus hojas siguientes.
        """
        if abierta is None or (selection is not None and selection.code != abierta):
            return None
        if analysis.plantilla is not None and analysis.plantilla.es_soporte:
            return None
        cabecera = normalized_lines(analysis.text)[:RENGLONES_DE_LA_CABECERA]
        if any(abierta.value in renglon for renglon in cabecera):
            return None
        return siguiente_en_la_cabecera(analysis.text, abierta)

    @staticmethod
    def _es_soporte(
        analysis: PageAnalysis, abierta: ResolutionCode, soportes: set[str], *, de_facultad: bool = False
    ) -> bool:
        """Si esta página es soporte de la resolución abierta y no puede abrir nada.

        Lo es cuando su plantilla lo dice -- una resolución de facultad, un
        oficio -- o cuando sólo trae el número de un soporte que ya va dentro.
        Una página que repite el número de la abierta nunca es soporte: es la
        resolución misma, que sigue. En un legajo de resoluciones internas
        (``de_facultad``), la copia de una de rectoría es soporte de la interna
        que la trae: «00238» se llevaba 40 páginas de las internas de 2016.
        """
        numeros = {candidate.code.value for candidate in analysis.candidates}
        if (
            de_facultad
            and analysis.plantilla is not None
            and analysis.plantilla.plantilla is Plantilla.RESOLUCION_DE_RECTORIA
            and analysis.plantilla.puntos >= _CON_EL_RECTOR
            and abierta.value not in {c.code.value for c in analysis.candidates if opens_a_resolution(c)}
        ):
            # La respuesta del rector con su número de cuatro cifras -- la
            # 3073 de 2009 que exonera la matrícula que pidió la 032 del
            # decano -- también es soporte de la de facultad que la pidió
            # (2026-11-27, 2003-2010 TOMO 2, pág. 61): abría su propio PDF.
            # Aunque nombre a la abierta, que es justo lo que hace al
            # responderle («mediante Resolución No.032»).
            return True
        if abierta.value in numeros:
            return False
        if de_facultad and numeros and all(_DE_RECTORIA.match(numero) for numero in numeros):
            return True
        if analysis.plantilla is not None and analysis.plantilla.es_soporte:
            # Una resolución de facultad es el soporte de la de rectoría que le
            # responde, no de otra de facultad: en un legajo de resoluciones
            # internas (caja 00C003303) cada una es su propia unidad, y tomarlas
            # por soporte de la anterior juntaba el año entero en un archivo.
            return not (
                analysis.plantilla.plantilla is Plantilla.RESOLUCION_DE_FACULTAD
                and numeros
                and not _DE_RECTORIA.match(abierta.value)
            )
        return bool(numeros) and numeros <= soportes

    @staticmethod
    def _used_context(
        analysis: PageAnalysis, selection: Selection, previous: ResolutionCode | None
    ) -> bool:
        blind = select_best(analysis.candidates)
        return blind is not None and blind.code != selection.code and previous is not None

    # -- verificación: el OCR contrasta lo que leyó la capa de texto ----------

    def _verify_declarations(
        self,
        source: PageSource,
        analyses: list[PageAnalysis],
        classifications: list[PageClassification],
        unresolved: list[int],
        stats: PipelineStats,
    ) -> tuple[list[PageClassification], list[int]]:
        """Segunda opinión del OCR sobre las páginas que declaran un número.

        Una página cuyo número vino de la capa de texto no se comprobó contra
        nada: el texto embebido es una lectura previa que también pudo salir
        mal, y en estos escaneos sale mal más de lo que parece. Aquí se vuelve a
        leer la banda del encabezado con OCR y se comparan las dos.

        Cuando discrepan no se elige: la página queda marcada como ambigua y
        sube al siguiente peldaño, que es el que sabe mirar la imagen. Elegir una
        de dos lecturas que se contradicen sería inventar una certeza.
        """
        provenance = {analysis.page_number: analysis.provenance for analysis in analyses}
        pendientes = set(unresolved)
        previous: ResolutionCode | None = None
        verificadas = list(classifications)

        # Cuántas hay que contrastar, contado antes de empezar: es lo que
        # convierte una espera muda en una barra que avanza. Son treinta
        # renderizados seguidos sin una sola página nueva que enseñar, así que
        # sin esto la pantalla se queda quieta justo después de leerlo todo.
        por_verificar = 0
        anterior: ResolutionCode | None = None
        for page in verificadas:
            if page.code is not None and page.code != anterior:
                anterior = page.code
                if (
                    page.page_number not in pendientes
                    and provenance.get(page.page_number) is Provenance.TEXT_LAYER
                ):
                    por_verificar += 1
        if por_verificar:
            self._report(
                ProgressEvent(
                    stage=Stage.VERIFYING,
                    done=0,
                    total=por_verificar,
                    detail="contrastando con OCR lo que declaró la capa de texto",
                )
            )

        # Cuáles hay que contrastar, decidido antes de leer ninguna: cada
        # lectura es independiente de las demás y se reparte entre hilos, igual
        # que el análisis. Iban una detrás de otra en el hilo principal, y en
        # un legajo de 222 páginas eran 28 lecturas de OCR en fila: 17 de los
        # 40 segundos que costaba el documento entero.
        a_contrastar: list[tuple[int, PageClassification]] = []
        for index, page in enumerate(verificadas):
            declara = page.code is not None and page.code != previous
            if page.code is not None:
                previous = page.code
            if not declara or page.page_number in pendientes:
                continue
            if provenance.get(page.page_number) is not Provenance.TEXT_LAYER:
                # Ya se leyó con OCR o con el modelo; comprobarlo consigo mismo
                # no añadiría nada y costaría un render por resolución.
                continue
            a_contrastar.append((index, page))

        def contrastar(page: PageClassification) -> ResolutionCode | None:
            # La orden de pausar o cancelar se atiende entre una lectura y la
            # siguiente, como en el análisis: es donde no hay nada a medias.
            self._control.check()
            return self._read_header(source, page.page_number)

        if a_contrastar:
            workers = max(1, min(self._config.max_workers, len(a_contrastar)))
            with hilos(workers) as pool:
                segundas = mapear(
                    pool, contrastar, [page for _, page in a_contrastar], self._control
                )
                # `map` entrega en el orden en que se pidió, así que el contador
                # y las discrepancias salen iguales corran en el orden que corran.
                for (index, page), second in zip(a_contrastar, segundas, strict=True):
                    stats.verified += 1
                    self._report(
                        ProgressEvent(
                            stage=Stage.VERIFYING,
                            done=stats.verified,
                            total=por_verificar,
                            detail=f"página {page.page_number}",
                        )
                    )
                    if second is None or second == page.code:
                        continue
                    stats.disagreements[page.page_number] = (
                        f"{page.code.value} / {second.value}"
                    )
                    verificadas[index] = replace(page, ambiguous=True)
                    pendientes.add(page.page_number)

        stats.escalated = len(pendientes)
        return verificadas, sorted(pendientes)

    def _read_header(self, source: PageSource, page_number: int) -> ResolutionCode | None:
        """Lo que el OCR lee en la banda del encabezado, o nada."""
        try:
            image = source.render(page_number, self._config.header_band, self._config.ocr_dpi)
            candidates = extract_candidates(self._ocr.read(image).text)
        except Exception:  # noqa: BLE001 - una verificación no rompe el documento
            logger.debug("no se pudo verificar la página %s", page_number, exc_info=True)
            return None
        selection = select_best(candidates)
        return selection.code if selection is not None else None

    # -- rung 4: the vision model, on crops, in mosaics ------------------------

    def _escalate(
        self,
        source: PageSource,
        classifications: list[PageClassification],
        unresolved: list[int],
        stats: PipelineStats,
    ) -> list[PageClassification]:
        if self._vision is None:
            return classifications

        by_page = {c.page_number: c for c in classifications}
        config = self._config

        for start in range(0, len(unresolved), config.mosaic_size):
            # Entre lotes del modelo: cada uno es una llamada de red que se paga,
            # así que conviene poder no hacer las que faltan.
            self._control.check()
            batch = unresolved[start : start + config.mosaic_size]
            self._report(
                ProgressEvent(
                    stage=Stage.VERIFYING,
                    done=start,
                    total=len(unresolved),
                    detail=f"consultando al modelo por {len(batch)} páginas",
                )
            )
            crops = [
                Crop(
                    page_number=n,
                    image_png=source.render(n, config.header_band, config.crop_dpi),
                )
                for n in batch
            ]
            stats.vision_requests += 1
            answers = self._vision.read_codes(crops)

            for page_number in batch:
                code = ResolutionCode.try_parse(answers.get(page_number) or "")
                if code is None:
                    continue
                by_page[page_number] = PageClassification(
                    page_number=page_number,
                    code=code,
                    confidence=0.9,
                    provenance=Provenance.VISION_MODEL,
                    ambiguous=False,
                    title=by_page[page_number].title,
                )
                self._report(
                    ProgressEvent(
                        stage=Stage.PAGE,
                        page_number=page_number,
                        provenance=str(Provenance.VISION_MODEL),
                        code=code.value,
                    )
                )

        return [by_page[c.page_number] for c in classifications]
