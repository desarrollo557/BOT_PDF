"""Gemini answering the boundary question, over plain HTTP.

No SDK on purpose: this is one POST with a JSON body, and adding a dependency to
the install for it would be paying in setup for something the standard library
already does.

One request per box, not per seam. That is not only cheaper -- it is what keeps
the free tier usable at all. Measured on a real expediente, 124 seam-by-seam
calls hit HTTP 429 after six; the same box asked once goes through.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from .boundary_prompt import (
    INSTRUCTIONS,
    build_question,
    describe_failure,
    parse_answer,
)

logger = logging.getLogger(__name__)

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


@dataclass(frozen=True, slots=True)
class GeminiConfig:
    model: str = "gemini-3.6-flash"
    timeout_seconds: int = 120
    max_output_tokens: int = 8000


class GeminiBoundaryOracle:
    """Judges undecided seams with Gemini. Satisfies `BoundaryOracle`."""

    def __init__(self, api_key: str | None = None, config: GeminiConfig | None = None) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._config = config or GeminiConfig()

    def judge(
        self,
        pages: list[dict[str, object]],
        seams: list[tuple[int, int]],
    ) -> dict[tuple[int, int], bool]:
        if not seams or not self._api_key:
            return {}

        body = json.dumps(
            {
                "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
                "contents": [{"parts": [{"text": build_question(pages, seams)}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "maxOutputTokens": self._config.max_output_tokens,
                },
            }
        ).encode()

        url = ENDPOINT.format(model=self._config.model) + f"?key={self._api_key}"
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            # An outage degrades the run to "these seams need a human". It never
            # fails the box: everything structure settled is still a valid split.
            # The warning names the cause: a 429 waits, a 401 needs another key.
            logger.warning(
                "Gemini no respondió (%s); las costuras dudosas van a revisión",
                describe_failure(error),
            )
            return {}

        return parse_answer(_text_of(payload), seams)


def _text_of(payload: dict) -> str:
    candidates = payload.get("candidates") or [{}]
    parts = candidates[0].get("content", {}).get("parts", [])
    return next((part["text"] for part in parts if isinstance(part, dict) and "text" in part), "")
