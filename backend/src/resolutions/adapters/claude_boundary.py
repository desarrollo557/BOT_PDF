"""Claude answering the same boundary question, through the official SDK.

The instructions live in `boundary_prompt`, shared with the Gemini adapter, so
the two differ in transport and nothing else.

The system half is marked cacheable because it is byte-identical on every box.
Whether it actually caches depends on the prefix clearing the model's minimum,
which is why `usage.cache_read_input_tokens` is logged instead of assumed -- a
prefix below the threshold caches nothing and says nothing about it.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from anthropic import Anthropic

from .boundary_prompt import (
    INSTRUCTIONS,
    build_question,
    describe_failure,
    parse_answer,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClaudeBoundaryConfig:
    #: El chico a propósito. Lo que se le pide es un veredicto binario sobre una
    #: huella de página ya comprimida -- no redactar, no resumir -- y el grande
    #: cuesta bastante más por la misma decisión. Quien quiera el grande lo pasa
    #: por configuración; el valor por omisión responde al modelo de costo, que
    #: es la razón de ser de toda la cascada.
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 8000


class ClaudeBoundaryOracle:
    """Judges undecided seams with Claude. Satisfies `BoundaryOracle`."""

    def __init__(
        self,
        client: Anthropic | None = None,
        config: ClaudeBoundaryConfig | None = None,
    ) -> None:
        self._client = client or Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self._config = config or ClaudeBoundaryConfig()

    def judge(
        self,
        pages: list[dict[str, object]],
        seams: list[tuple[int, int]],
    ) -> dict[tuple[int, int], bool]:
        if not seams:
            return {}

        try:
            message = self._client.messages.create(
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": INSTRUCTIONS,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": build_question(pages, seams)}],
            )
        except Exception as error:  # noqa: BLE001 - an outage degrades, it does not fail the box
            logger.warning(
                "Claude no respondió (%s); las costuras dudosas van a revisión",
                describe_failure(error),
            )
            return {}

        usage = getattr(message, "usage", None)
        if usage is not None:
            logger.info(
                "costuras=%d entrada=%s cache=%s salida=%s",
                len(seams),
                getattr(usage, "input_tokens", "?"),
                getattr(usage, "cache_read_input_tokens", "?"),
                getattr(usage, "output_tokens", "?"),
            )

        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )
        return parse_answer(text, seams)
