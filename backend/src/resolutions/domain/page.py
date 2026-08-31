from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .resolution_code import ResolutionCode


class Provenance(StrEnum):
    """Which rung of the cascade produced the answer.

    Recorded on every page so the cost profile of a run is measurable rather than
    assumed, and so a regression in one stage is visible without re-processing.
    """

    TEXT_LAYER = "text_layer"
    OCR_REGION = "ocr_region"
    OCR_FULL_PAGE = "ocr_full_page"
    VISION_MODEL = "vision_model"
    HUMAN_REVIEW = "human_review"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class PageClassification:
    """What the pipeline concluded about a single page."""

    page_number: int
    code: ResolutionCode | None
    confidence: float = 0.0
    provenance: Provenance = Provenance.NONE
    ambiguous: bool = False
    #: The document's own name, read from the page that declares the code.
    title: str | None = None

    @property
    def is_classified(self) -> bool:
        return self.code is not None
