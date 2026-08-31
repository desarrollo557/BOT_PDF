from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .errors import InvalidResolutionCode
from .text_distance import damerau_levenshtein

# Numbering noise that precedes the actual number: "N° 0412", "NRO. 0412", "# 0412".
_NUMBERING_PREFIX = re.compile(r"^(?:NRO\.?|NUM\.?|NUMERO|N[º°]|NO\.?|N\.|#|:)\s*")
_TRAILING_PUNCTUATION = re.compile(r"[.,;:)\]]+$")
_DIGIT = re.compile(r"\d")


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@dataclass(frozen=True, slots=True)
class ResolutionCode:
    """The identity of a group.

    Two pages belong together when their codes are equal, so equality and hashing
    run on the normalized ``value`` alone. ``raw`` is carried untouched purely so
    an operator reviewing a decision can see what the OCR actually produced.
    """

    value: str
    raw: str = field(default="", compare=False)

    @classmethod
    def parse(cls, raw: str) -> ResolutionCode:
        original = (raw or "").strip()
        candidate = _strip_accents(original).upper()
        candidate = _NUMBERING_PREFIX.sub("", candidate).strip()
        candidate = _TRAILING_PUNCTUATION.sub("", candidate)
        candidate = re.sub(r"\s+", "", candidate)

        if not _DIGIT.search(candidate):
            raise InvalidResolutionCode(
                f"{original!r} carries no digits, so it cannot be a resolution number"
            )
        return cls(value=candidate, raw=original)

    @classmethod
    def try_parse(cls, raw: str) -> ResolutionCode | None:
        try:
            return cls.parse(raw)
        except InvalidResolutionCode:
            return None

    def distance_to(self, other: ResolutionCode) -> int:
        return damerau_levenshtein(self.value, other.value)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value
