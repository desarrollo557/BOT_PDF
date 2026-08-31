from __future__ import annotations

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..domain.extraction import RawCandidate, extract_candidates
from ..domain.page import PageClassification, Provenance
from ..domain.resolution_code import ResolutionCode
from ..domain.scoring import Selection, select_best
from ..domain.title import extract_title
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

    #: Crops per request to the vision model. Header bands are small, so tiling
    #: them amortises the prompt across a dozen pages.
    mosaic_size: int = 12

    max_workers: int = 8


@dataclass(frozen=True, slots=True)
class PageAnalysis:
    """Everything learned about a page locally, before sequence context."""

    page_number: int
    candidates: list[RawCandidate]
    provenance: Provenance
    text_length: int
    title: str | None = None
    failed: bool = False
    error: str | None = None

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
    #: page number -> what went wrong. A page that blows up is isolated, never
    #: allowed to take the other 399 with it.
    failures: dict[int, str] = field(default_factory=dict)

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
            "vision_page_ratio": round(self.vision_page_ratio, 4),
            "failed_pages": {str(page): error for page, error in sorted(self.failures.items())},
        }


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
        if len(text) >= config.min_text_layer_chars:
            # Free rung. On digital PDFs this answers the whole document.
            return PageAnalysis(
                page_number=page_number,
                candidates=extract_candidates(text),
                provenance=Provenance.TEXT_LAYER,
                text_length=len(text),
                title=extract_title(text),
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
                title=extract_title(band.text),
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
            title=extract_title(full.text),
        )


class ClassificationPipeline:
    """Drives the full cascade for one document."""

    def __init__(
        self,
        ocr: OcrEngine,
        vision: VisionOracle | None = None,
        config: PipelineConfig | None = None,
        progress: ProgressReporter | None = None,
    ) -> None:
        self._config = config or PipelineConfig()
        self._analyzer = PageAnalyzer(ocr, self._config)
        self._vision = vision
        self._progress = progress or NullProgressReporter()

    def classify(self, source: PageSource) -> tuple[list[PageClassification], PipelineStats]:
        self._report(ProgressEvent(stage=Stage.OPENED, page_count=source.page_count))
        analyses = self._analyse_all(source)
        classifications, stats, unresolved = self._resolve_with_context(analyses)
        if unresolved:
            classifications = self._escalate(source, classifications, unresolved, stats)
        return classifications, stats

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

        A corrupt page, a font MuPDF chokes on, an OCR process that dies: none of
        those are a reason to lose the other 399 pages. The page is marked
        unreadable and routed to review, and the document carries on.
        """
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
                error=f"{type(error).__name__}: {error}",
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

        for analysis in analyses:
            stats.by_provenance[str(analysis.provenance)] += 1
            if analysis.failed:
                stats.failures[analysis.page_number] = analysis.error or "unknown error"
            selection = select_best(analysis.candidates, previous_code=previous)

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
            previous = selection.code

        stats.escalated = len(unresolved)
        return classifications, stats, unresolved

    @staticmethod
    def _used_context(
        analysis: PageAnalysis, selection: Selection, previous: ResolutionCode | None
    ) -> bool:
        blind = select_best(analysis.candidates)
        return blind is not None and blind.code != selection.code and previous is not None

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
            batch = unresolved[start : start + config.mosaic_size]
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
