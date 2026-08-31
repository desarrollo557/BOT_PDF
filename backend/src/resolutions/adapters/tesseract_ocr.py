from __future__ import annotations

import os
from dataclasses import dataclass
from io import BytesIO

import pytesseract
from PIL import Image, ImageOps

from ..application.ports import OcrResult

# Tesseract's Windows installer does not put itself on PATH, and a worker process
# that inherits a stale environment is a confusing way to find that out. This
# override makes the binary's location explicit and configurable.
_TESSERACT_CMD = os.environ.get("RESOLUTIONS_TESSERACT_CMD")
if _TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD

#: Page segmentation modes. A header crop is a single uniform block; a full page
#: needs the layout analyser. Using the right one is free accuracy.
PSM_UNIFORM_BLOCK = 6
PSM_AUTO = 3


@dataclass(frozen=True, slots=True)
class TesseractConfig:
    language: str = "spa"
    psm: int = PSM_UNIFORM_BLOCK
    #: Below this mean word confidence the read is treated as unusable, which
    #: routes the page to the next rung instead of poisoning a group.
    min_word_confidence: float = 40.0
    autocontrast: bool = True


class TesseractOcr:
    """Local OCR. Free, CPU-bound, and released from the GIL while it runs."""

    def __init__(self, config: TesseractConfig | None = None) -> None:
        self._config = config or TesseractConfig()

    def read(self, image_png: bytes) -> OcrResult:
        image = self._prepare(image_png)
        data = pytesseract.image_to_data(
            image,
            lang=self._config.language,
            config=f"--psm {self._config.psm}",
            output_type=pytesseract.Output.DICT,
        )

        words: list[str] = []
        confidences: list[float] = []
        for text, confidence in zip(data["text"], data["conf"], strict=False):
            token = (text or "").strip()
            score = float(confidence)
            if not token or score < 0:
                continue
            words.append(token)
            confidences.append(score)

        if not words:
            return OcrResult(text="", mean_confidence=0.0)

        mean = sum(confidences) / len(confidences)
        if mean < self._config.min_word_confidence:
            # Honest empty beats confident nonsense: an invented code silently
            # moves pages into the wrong file.
            return OcrResult(text="", mean_confidence=mean / 100.0)

        return OcrResult(text=self._reflow(data, words), mean_confidence=mean / 100.0)

    def _prepare(self, image_png: bytes) -> Image.Image:
        image = Image.open(BytesIO(image_png)).convert("L")
        return ImageOps.autocontrast(image) if self._config.autocontrast else image

    @staticmethod
    def _reflow(data: dict, words: list[str]) -> str:
        """Rebuild line breaks, because the scorer reads position off lines."""
        lines: dict[tuple[int, int, int], list[str]] = {}
        for index, text in enumerate(data["text"]):
            token = (text or "").strip()
            if not token or float(data["conf"][index]) < 0:
                continue
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            lines.setdefault(key, []).append(token)
        if not lines:
            return " ".join(words)
        return "\n".join(" ".join(tokens) for _, tokens in sorted(lines.items()))


class HeaderAndPageOcr:
    """Applies the right segmentation mode to each rung of the cascade."""

    def __init__(self, language: str = "spa") -> None:
        self._band = TesseractOcr(TesseractConfig(language=language, psm=PSM_UNIFORM_BLOCK))
        self._page = TesseractOcr(TesseractConfig(language=language, psm=PSM_AUTO))
        self._seen_bytes = 0

    def read(self, image_png: bytes) -> OcrResult:
        # A header crop is a small image; a full page render is not. The size is
        # a reliable enough signal to pick the segmentation mode without
        # threading extra state through the pipeline.
        engine = self._band if len(image_png) < 400_000 else self._page
        return engine.read(image_png)
