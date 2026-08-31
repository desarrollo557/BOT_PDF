from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass

from anthropic import Anthropic

from ..application.ports import Crop

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You read resolution numbers off scanned administrative documents.\n"
    "Each image is the top band of one page, labelled with an index.\n"
    "For every index, return the resolution number that belongs to THAT page: the "
    "one printed as the page's own heading.\n"
    "Never return a number that appears after VISTO, CONSIDERANDO, or any phrase "
    "citing another resolution.\n"
    "If no heading number is legible, return null for that index. Guessing is worse "
    "than admitting the page is unreadable.\n"
    'Reply with JSON only: {"1": "0412/2024", "2": null}'
)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True, slots=True)
class ClaudeVisionConfig:
    model: str = "claude-sonnet-5"
    max_tokens: int = 1024
    temperature: float = 0.0


class ClaudeVisionOracle:
    """The last rung. Sees header crops only, a batch at a time.

    Two deliberate economies: the images are cropped bands rather than full
    pages, and one request answers a dozen of them, so the system prompt is paid
    once per batch instead of once per page. The prompt is also cached, which
    removes it from the bill entirely on every request after the first.
    """

    def __init__(self, client: Anthropic | None = None, config: ClaudeVisionConfig | None = None):
        self._client = client or Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self._config = config or ClaudeVisionConfig()

    def read_codes(self, crops: list[Crop]) -> dict[int, str | None]:
        if not crops:
            return {}

        labels = {str(index): crop.page_number for index, crop in enumerate(crops, start=1)}
        content: list[dict] = []
        for label, crop in zip(labels, crops, strict=True):
            content.append({"type": "text", "text": f"Index {label}:"})
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(crop.image_png).decode(),
                    },
                }
            )

        try:
            message = self._client.messages.create(
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": content}],
            )
        except Exception:
            # A model outage degrades the run to "these pages need a human", it
            # does not fail the document and it never invents an answer.
            logger.exception("vision batch failed for pages %s", [c.page_number for c in crops])
            return {crop.page_number: None for crop in crops}

        return self._parse(message, labels)

    @staticmethod
    def _parse(message, labels: dict[str, int]) -> dict[int, str | None]:
        text = "".join(block.text for block in message.content if block.type == "text")
        match = _JSON_BLOCK.search(text)
        if not match:
            logger.warning("vision reply carried no JSON object: %r", text[:200])
            return {page: None for page in labels.values()}

        try:
            answers = json.loads(match.group())
        except json.JSONDecodeError:
            logger.warning("vision reply was not valid JSON: %r", match.group()[:200])
            return {page: None for page in labels.values()}

        resolved: dict[int, str | None] = {}
        for label, page_number in labels.items():
            value = answers.get(label)
            resolved[page_number] = value if isinstance(value, str) and value.strip() else None
        return resolved


class NullVisionOracle:
    """Stands in when no API key is configured.

    Escalated pages go to human review instead of to a model. The system stays
    correct, it just stops being clever.
    """

    def read_codes(self, crops: list[Crop]) -> dict[int, str | None]:
        return {crop.page_number: None for crop in crops}
