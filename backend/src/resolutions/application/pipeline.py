from __future__ import annotations

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

from ..domain.doctype import DocumentType, TypeVerdict, classify_pages
from ..domain.extraction import RawCandidate, extract_candidates
from ..domain.legibility import garble_score, is_garbled
from ..domain.page import PageClassification, Provenance
from ..domain.resolution_code import ResolutionCode
from ..domain.scoring import Selection, select_best
from ..domain.title import extract_title
from .control import NullRunControl, RunControl
from .diagnostico import explicar
from .ports import HEADER_BAND, Band, Crop, OcrEngine, PageSource, VisionOracle
from .progress import NullProgressReporter, ProgressEvent, ProgressReporter, Stage

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
            return PageAnalysis(
                page_number=page_number,
                candidates=extract_candidates(text, _geometry_of(source, page_number, text)),
                provenance=Provenance.TEXT_LAYER,
                text_length=len(text),
                text=text[: config.sample_chars],
                title=extract_title(text),
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
                title=extract_title(band.text),
                mis_decoded=mal_decodificada,
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
            title=extract_title(full.text),
            mis_decoded=mal_decodificada,
        )


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
        return classifications, stats

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
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(lambda n: self._analyse_one(source, n), pages))

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

        for analysis in analyses:
            stats.by_provenance[str(analysis.provenance)] += 1
            if analysis.mis_decoded:
                stats.mis_decoded_pages.append(analysis.page_number)
            if analysis.failed:
                stats.failures[analysis.page_number] = analysis.error or "unknown error"
            selection = select_best(
                analysis.candidates,
                previous_code=previous,
                announced_by_open_unit=anunciados,
            )

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
                )
            )
            if selection.code != previous:
                # Unidad nueva: lo que anunciaba la anterior deja de contar.
                anunciados = set()
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

            stats.verified += 1
            self._report(
                ProgressEvent(
                    stage=Stage.VERIFYING,
                    done=stats.verified,
                    total=por_verificar,
                    detail=f"página {page.page_number}",
                )
            )
            second = self._read_header(source, page.page_number)
            if second is None or second == page.code:
                continue

            stats.disagreements[page.page_number] = f"{page.code.value} / {second.value}"
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
