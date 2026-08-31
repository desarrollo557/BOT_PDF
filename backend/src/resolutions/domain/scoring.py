from __future__ import annotations

from dataclasses import dataclass, field

from .extraction import RawCandidate
from .resolution_code import ResolutionCode

# A page's own resolution announces itself: near the top, set in capitals, on a
# short line, with no citation verb in front of it. Every weight below encodes
# one of those four observations.
POSITION_WEIGHT = 0.35
CAPITALS_WEIGHT = 0.45
ISOLATION_WEIGHT = 0.20
CITATION_PENALTY = 0.55

# Sequential context is free evidence, but it only arbitrates between weak
# candidates. A confident header is never overruled by what came before.
NEIGHBOUR_BOOST = 0.30
CONFIDENT_FLOOR = 0.60
TIE_MARGIN = 0.12

_CITATION_MARKERS = (
    "VISTO",
    "CONSIDERANDO",
    "MODIFICA",
    "MODIFICATORIA",
    "DEROGA",
    "RATIFICA",
    "SUSTITUYE",
    "AMPLIA",
    "COMPLEMENTA",
    "MEDIANTE",
    "APROBADA POR",
    "APROBADO POR",
    "CONFORME",
)

_SHORT_LINE_WORDS = 6
_LONG_LINE_WORDS = 12


@dataclass(frozen=True, slots=True)
class Selection:
    """The page's resolution, with enough context to audit or escalate it."""

    code: ResolutionCode
    confidence: float
    ambiguous: bool
    runner_up: ResolutionCode | None = None
    signals: dict[str, float] = field(default_factory=dict)


def _position(candidate: RawCandidate) -> float:
    span = max(candidate.total_lines - 1, 1)
    return max(0.0, 1.0 - candidate.line_index / span)


def _capitals(candidate: RawCandidate) -> float:
    letters = [ch for ch in candidate.line_text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(ch.isupper() for ch in letters) / len(letters)


def _isolation(candidate: RawCandidate) -> float:
    words = len(candidate.line_text.split())
    if words <= _SHORT_LINE_WORDS:
        return 1.0
    return max(0.0, (_LONG_LINE_WORDS - words) / (_LONG_LINE_WORDS - _SHORT_LINE_WORDS))


def _is_citation(candidate: RawCandidate) -> bool:
    return any(marker in candidate.context_before for marker in _CITATION_MARKERS)


def signals_for(candidate: RawCandidate) -> dict[str, float]:
    return {
        "position": _position(candidate),
        "capitals": _capitals(candidate),
        "isolation": _isolation(candidate),
        "citation": 1.0 if _is_citation(candidate) else 0.0,
    }


def score(candidate: RawCandidate) -> float:
    signals = signals_for(candidate)
    total = (
        POSITION_WEIGHT * signals["position"]
        + CAPITALS_WEIGHT * signals["capitals"]
        + ISOLATION_WEIGHT * signals["isolation"]
        - CITATION_PENALTY * signals["citation"]
    )
    return min(1.0, max(0.0, total))


def select_best(
    candidates: list[RawCandidate],
    previous_code: ResolutionCode | None = None,
) -> Selection | None:
    """Pick the resolution that owns the page, or ``None`` if there is none."""
    if not candidates:
        return None

    # Stable sort: equal scores keep reading order, so the earliest wins ties.
    ranked = sorted(((score(c), c) for c in candidates), key=lambda pair: -pair[0])
    top_score, top = ranked[0]

    if previous_code is not None and top_score < CONFIDENT_FLOOR:
        ranked = sorted(
            (
                (value + NEIGHBOUR_BOOST if candidate.code == previous_code else value, candidate)
                for value, candidate in ranked
            ),
            key=lambda pair: -pair[0],
        )
        top_score, top = ranked[0]
        top_score = min(1.0, top_score)

    runner_up_score = ranked[1][0] if len(ranked) > 1 else 0.0
    runner_up = ranked[1][1].code if len(ranked) > 1 else None

    ambiguous = top_score < CONFIDENT_FLOOR or (
        runner_up is not None and runner_up != top.code and top_score - runner_up_score < TIE_MARGIN
    )

    return Selection(
        code=top.code,
        confidence=round(top_score, 4),
        ambiguous=ambiguous,
        runner_up=runner_up,
        signals=signals_for(top),
    )
