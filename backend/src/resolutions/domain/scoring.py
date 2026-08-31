from __future__ import annotations

from dataclasses import dataclass, field

from .extraction import RawCandidate
from .resolution_code import ResolutionCode

# A page's own resolution announces itself: near the top, set in capitals, on a
# short line, in the official form, with no citation verb in front of it. Every
# weight below encodes one of those five observations.
POSITION_WEIGHT = 0.35
CAPITALS_WEIGHT = 0.45
ISOLATION_WEIGHT = 0.20
OFFICIAL_FORM_WEIGHT = 0.30
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


def _official_form(candidate: RawCandidate) -> float:
    """Whether the candidate is written the way a real header writes it.

    "RESOLUCION No. 00086" is the house format, and it stays the house format
    when the page is typeset in title case. Recognising the structure is what
    keeps ``Resolución No. 00072 de 2023`` off the escalation path, where the
    capitals signal alone would have left it one hundredth above the floor.

    A citation is written in exactly the same form, so the signal is withheld
    there: the shape says "this is a resolution number", never "this page is it".
    """
    if not candidate.official_form or _is_citation(candidate):
        return 0.0
    return 1.0


def signals_for(candidate: RawCandidate) -> dict[str, float]:
    return {
        "position": _position(candidate),
        "capitals": _capitals(candidate),
        "isolation": _isolation(candidate),
        "official_form": _official_form(candidate),
        "citation": 1.0 if _is_citation(candidate) else 0.0,
    }


def score(candidate: RawCandidate) -> float:
    signals = signals_for(candidate)
    total = (
        POSITION_WEIGHT * signals["position"]
        + CAPITALS_WEIGHT * signals["capitals"]
        + ISOLATION_WEIGHT * signals["isolation"]
        + OFFICIAL_FORM_WEIGHT * signals["official_form"]
        - CITATION_PENALTY * signals["citation"]
    )
    return min(1.0, max(0.0, total))


def opens_a_resolution(candidate: RawCandidate) -> bool:
    """Si esta candidata puede abrir una resolución nueva (RF-01).

    Sólo un encabezado oficial abre una resolución: el ancla, el token de
    numeración y el número, tal como están escritos en los documentos reales
    (``RESOLUCIÓN No. 00072 de 2023``). Un número suelto en medio del texto no
    abre nada, por muy número que parezca.

    Antes esto sólo sumaba puntos, y no alcanzaba: en un expediente de 222
    páginas se abrían 34 resoluciones donde había unas 20, porque números
    citados en el cuerpo superaban el umbral por su cuenta. Puntuar no basta
    cuando el error parte un documento por la mitad; la forma oficial tiene que
    ser una condición.

    Un encabezado además **abre su renglón**. Lo que lo obligó fue el membrete
    de la Universidad, que dice "Acreditación en Alta Calidad Resolución No,
    1968 dei 12 de febrero de 2018, MEN." y va impreso en decenas de páginas:
    trae ancla, token de numeración y número, así que pasaba por encabezado y
    se llevó 68 páginas que eran de otras resoluciones. La diferencia no está
    en cómo se escribe el número sino en dónde está: en las 222 páginas del
    expediente, las 22 resoluciones reales empiezan el renglón con el ancla las
    22 veces, y el membrete no lo hace ni una -- aparece en la columna 29, 30 o
    49, detrás de otras palabras. Los tres formatos de la casa cumplen esto:
    ``RESOLUCION NO. 00086``, ``Resolución No. 00072 de 2023`` y
    ``RESOLUCIÓN No. 00083 de 2023`` empiezan por el ancla.
    """
    return (
        candidate.official_form
        and candidate.anchor.start == 0
        and not _is_citation(candidate)
    )


def select_best(
    candidates: list[RawCandidate],
    previous_code: ResolutionCode | None = None,
) -> Selection | None:
    """Pick the resolution that owns the page, or ``None`` if there is none."""
    if not candidates:
        return None

    # Stable sort: equal scores keep reading order, so the earliest wins ties.
    ranked = sorted(((score(c), c) for c in candidates), key=lambda pair: -pair[0])

    if previous_code is not None:
        # RF-01: la página continúa la resolución anterior salvo que traiga un
        # encabezado oficial propio. Seguir con el mismo código también vale:
        # eso no abre nada, sólo confirma dónde sigue estando.
        admitidas = [
            pair
            for pair in ranked
            if pair[1].code == previous_code or opens_a_resolution(pair[1])
        ]
        if not admitidas:
            return _continues(previous_code, ranked[0])
        ranked = admitidas
    else:
        # Nada que continuar todavía: el documento tiene que empezar en algún
        # lado, así que aquí la forma oficial ordena en vez de excluir.
        oficiales = [pair for pair in ranked if opens_a_resolution(pair[1])]
        if oficiales:
            ranked = oficiales

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


def _continues(previous_code: ResolutionCode, suppressed: tuple[float, RawCandidate]) -> Selection:
    """La página pertenece a la resolución anterior, y por qué.

    Se marca ambigua sólo cuando el rechazo es discutible: la candidata abría su
    renglón, no venía detrás de un verbo de cita, y aun así se descartó por no
    traer el token de numeración -- que es exactamente lo que pasa cuando el OCR
    se come el "No." de un encabezado verdadero. Eso tiene que verlo una persona.

    Un rechazo estructural no es discutible y no ensucia la cola. El membrete de
    la Universidad aparece en decenas de páginas y se rechaza por la misma razón
    todas las veces; marcarlo mandaba 39 páginas a revisión donde había 8 dudas
    reales, y una cola llena de ruido es una cola que nadie mira.

    La confianza es la del enunciado que se está afirmando -- "esto continúa lo
    anterior" -- y por eso baja a medida que la candidata rechazada se parecía
    más a un encabezado.
    """
    rejected_score, rejected = suppressed
    debatable = (
        rejected_score >= CONFIDENT_FLOOR
        and rejected.anchor.start == 0
        and not _is_citation(rejected)
    )
    return Selection(
        code=previous_code,
        confidence=round(max(0.0, 1.0 - rejected_score), 4),
        ambiguous=debatable,
        runner_up=rejected.code,
        signals=signals_for(rejected),
    )
