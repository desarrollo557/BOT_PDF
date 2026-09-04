"""What kind of document a PDF is, decided from what is printed on it.

The splitter used to know one answer: a resolution. A box of scans is not that
tidy -- the same folder carries books of diploma registrations and student
enrolment records, and each of the three is split by a different rule and
inventoried with different columns. Nothing downstream can choose a rule until
this module has named the type.

The decision is made from evidence, never from the file name. A book scanned as
"CAJA 1.pdf" is still a book of diplomas, and a resolution someone renamed
"diplomas 2013.pdf" is still a resolution. Every marker that fired is recorded
with the page it fired on, so the verdict can be audited instead of trusted.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .anchor import normalize
from .extraction import extract_candidates
from .text_distance import damerau_levenshtein


class DocumentType(StrEnum):
    """The kinds of document this system knows how to take apart."""

    RESOLUCION = "resolucion"
    DIPLOMA = "diploma"
    MATRICULA = "matricula"
    DESCONOCIDO = "desconocido"

    @property
    def label(self) -> str:
        """The name an operator reads on screen and on the delivery note."""
        return _LABELS[self]


_LABELS = {
    DocumentType.RESOLUCION: "Resoluciones",
    DocumentType.DIPLOMA: "Registro de diplomas",
    DocumentType.MATRICULA: "Registros de matrícula",
    DocumentType.DESCONOCIDO: "Sin identificar",
}


@dataclass(frozen=True, slots=True)
class Marker:
    """A phrase that, when it appears, argues for one type of document.

    ``weight`` is how much of an argument it is. A phrase that only ever occurs
    on one kind of document -- "NOMBRES Y APELLIDOS DEL GRADUANDO" -- is worth
    several times one that merely leans -- "CONSIDERANDO", which opens every
    administrative act ever written.
    """

    phrase: str
    weight: float

    @property
    def tokens(self) -> tuple[str, ...]:
        return tuple(self.phrase.split())

    @property
    def budget(self) -> int:
        """Edits tolerated before the phrase stops being itself.

        Proportional to length, because OCR damage scales with the number of
        glyphs. One edit per eight characters keeps "REGISTRO DE DIPLOMAS"
        matching through a bad scan without letting a short phrase drift into a
        different one.
        """
        return max(1, len(self.phrase) // 8)


# -----------------------------------------------------------------------------
#  The markers, read off the documents themselves
# -----------------------------------------------------------------------------
#  Every phrase below was taken from a real scanned book, not invented: the
#  printed captions of the diploma registration forms, the headings of the
#  student record cards, and the drafting formulas of the rectory's resolutions.
#  Accents are already stripped and the text uppercased, because that is the
#  shape `normalize` produces and the shape they are compared against.
# -----------------------------------------------------------------------------

_DIPLOMA_MARKERS = (
    # The printed heading of the modern registration books.
    Marker("LIBRO DE REGISTRO DE DIPLOMAS", 6.0),
    Marker("REGISTRO DE DIPLOMAS", 4.0),
    # Captions of the form, one per field. These are what make the page a
    # registration rather than the diploma itself.
    Marker("NOMBRES Y APELLIDOS DEL GRADUANDO", 6.0),
    Marker("FUNCIONARIOS QUE FIRMAN EL DIPLOMA", 5.0),
    Marker("REGISTRADO A FOLIO", 4.0),
    Marker("REGISTRADO AL FOLIO", 4.0),
    Marker("FECHA DE GRADUACION", 3.0),
    Marker("TITULO RECIBIDO", 3.0),
    Marker("RESOLUCION QUE AUTORIZA EL OTORGAMIENTO DEL TITULO", 3.0),
    # The old hand-filled books print the diploma itself and register it at the
    # foot of the same page. Their wording is fixed and unmistakable.
    Marker("LE EXPIDE EL PRESENTE DIPLOMA", 5.0),
    Marker("ESTATUTOS UNIVERSITARIOS", 3.0),
    Marker("PARA CONSTANCIA ES FIRMADO EL PRESENTE REGISTRO DE DIPLOMA", 5.0),
    Marker("DE REGISTRO DE DIPLOMAS DE LA RECTORIA", 4.0),
)

_MATRICULA_MARKERS = (
    Marker("REGISTRO DEL ALUMNO", 6.0),
    Marker("NOMBRE DEL ALUMNO", 5.0),
    # El encabezado impreso de la carátula y la dependencia que la produce. Son
    # las dos cosas que dicen que la hoja es una matrícula y no la portada de
    # cualquier otra cosa, y ninguna de las dos estaba aquí: sin ellas un legajo
    # cuya primera hoja es la carátula se apoyaba sólo en las de asignaturas.
    Marker("MATRICULA ACADEMICA", 6.0),
    Marker("ADMISIONES REGISTRO Y CONTROL ACADEMICO", 5.0),
    Marker("COD ESTUDIANTE", 3.0),
    Marker("FIRMA SECRETARIO ACADEMICO", 3.0),
    Marker("FIRMA ALUMNO", 2.5),
    Marker("REGISTRO DE ESTUDIOS", 4.0),
    Marker("HISTORIA ACADEMICA", 4.0),
    Marker("HISTORIAS ACADEMICAS", 4.0),
    Marker("CEDULA O TARJETA", 3.0),
    Marker("LUGAR DE NACIMIENTO", 2.0),
    Marker("BACHILLER DEL COLEGIO", 2.0),
    Marker("PROMEDIO SEMESTRAL", 2.0),
    Marker("ASIGNATURAS", 1.5),
    Marker("LIBRETA MILITAR", 1.5),
)

_RESOLUCION_MARKERS = (
    Marker("POR MEDIO DE LA CUAL SE", 3.0),
    Marker("POR LA CUAL SE", 2.0),
    Marker("EL RECTOR DE LA UNIVERSIDAD", 2.0),
    Marker("EN USO DE SUS FACULTADES", 2.0),
    Marker("RESUELVE", 1.5),
    Marker("CONSIDERANDO", 1.0),
    Marker("COMUNIQUESE Y CUMPLASE", 2.5),
    Marker("DADA EN CARTAGENA", 1.5),
)

MARKERS: dict[DocumentType, tuple[Marker, ...]] = {
    DocumentType.DIPLOMA: _DIPLOMA_MARKERS,
    DocumentType.MATRICULA: _MATRICULA_MARKERS,
    DocumentType.RESOLUCION: _RESOLUCION_MARKERS,
}

#: An official resolution header -- the anchor word, a numbering token and a
#: zero-padded number -- is the strongest single thing a page can say about
#: being a resolution. It is scored through `extract_candidates` rather than a
#: second regex, so the classifier and the splitter can never disagree about
#: what an official header looks like.
OFFICIAL_HEADER_WEIGHT = 7.0
OFFICIAL_HEADER_MARKER = "encabezado oficial de resolución"

#: Average evidence per page below which nothing has really been recognised.
#: Kept low on purpose: on a scanned book most pages contribute nothing and a
#: handful carry the printed captions, so the average is small even when the
#: identification is certain.
MIN_SCORE = 0.35

#: How far ahead of the runner-up the winner must be to be called decided
#: rather than merely leading.
MIN_MARGIN = 0.60


@dataclass(frozen=True, slots=True)
class TypeEvidence:
    """One marker, on one page. The audit trail behind a verdict."""

    page_number: int
    document_type: DocumentType
    marker: str
    weight: float
    distance: int

    def as_dict(self) -> dict[str, object]:
        return {
            "page": self.page_number,
            "type": str(self.document_type),
            "marker": self.marker,
            "weight": self.weight,
            "distance": self.distance,
        }


@dataclass(frozen=True, slots=True)
class TypeVerdict:
    """What the document turned out to be, and why.

    ``confidence`` is the winner's share of the total evidence, so it answers
    "how much of what we saw pointed here" rather than a number picked to look
    reassuring. A document with no recognised markers comes back as
    ``DESCONOCIDO`` with a confidence of zero rather than as a guess.
    """

    document_type: DocumentType
    confidence: float
    scores: dict[DocumentType, float] = field(default_factory=dict)
    evidence: list[TypeEvidence] = field(default_factory=list)
    pages_sampled: int = 0

    @property
    def is_identified(self) -> bool:
        return self.document_type is not DocumentType.DESCONOCIDO

    def as_dict(self) -> dict[str, object]:
        return {
            "type": str(self.document_type),
            "label": self.document_type.label,
            "confidence": round(self.confidence, 4),
            "scores": {str(key): round(value, 4) for key, value in self.scores.items()},
            "pages_sampled": self.pages_sampled,
            "evidence": [item.as_dict() for item in self.evidence],
        }


def _phrase_distance(tokens: Sequence[str], marker: Marker) -> int | None:
    """Smallest edit distance between ``marker`` and any window of ``tokens``.

    ``None`` when nothing came within the marker's budget. The window is the
    marker's own token count, so a phrase is compared against the same number of
    words wherever it sits on the page.
    """
    width = len(marker.tokens)
    if width == 0 or len(tokens) < width:
        return None

    budget = marker.budget
    best: int | None = None
    for start in range(len(tokens) - width + 1):
        window = " ".join(tokens[start : start + width])
        distance = damerau_levenshtein(window, marker.phrase, ceiling=budget)
        if distance <= budget and (best is None or distance < best):
            best = distance
            if best == 0:
                break
    return best


def markers_on_page(text: str, page_number: int) -> list[TypeEvidence]:
    """Every marker that fires on one page, tolerating OCR damage.

    The cheap exact test runs first: on a clean text layer it answers every
    marker without a single edit-distance computation. The fuzzy window is only
    paid for on the phrases the scan actually damaged.
    """
    normalized = normalize(text)
    if not normalized:
        return []

    tokens = normalized.split()
    found: list[TypeEvidence] = []
    for document_type, markers in MARKERS.items():
        for marker in markers:
            if marker.phrase in normalized:
                distance = 0
            else:
                matched = _phrase_distance(tokens, marker)
                if matched is None:
                    continue
                distance = matched
            found.append(
                TypeEvidence(
                    page_number=page_number,
                    document_type=document_type,
                    marker=marker.phrase,
                    weight=marker.weight,
                    distance=distance,
                )
            )

    if any(candidate.official_form for candidate in extract_candidates(text)):
        found.append(
            TypeEvidence(
                page_number=page_number,
                document_type=DocumentType.RESOLUCION,
                marker=OFFICIAL_HEADER_MARKER,
                weight=OFFICIAL_HEADER_WEIGHT,
                distance=0,
            )
        )
    return found


def classify_pages(pages: Iterable[tuple[int, str]]) -> TypeVerdict:
    """Name the document from the text of the pages that were read.

    Scores are averaged over the pages sampled rather than summed, so reading
    twelve pages of a book and reading four hundred of it produce the same
    verdict instead of a number that grows with the document.
    """
    evidence: list[TypeEvidence] = []
    sampled = 0
    for page_number, text in pages:
        sampled += 1
        evidence.extend(markers_on_page(text, page_number))

    scores = {document_type: 0.0 for document_type in MARKERS}
    for item in evidence:
        scores[item.document_type] += item.weight
    if sampled:
        scores = {key: value / sampled for key, value in scores.items()}

    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    leader, best = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    total = sum(scores.values())

    decided = (
        best >= MIN_SCORE
        # The margin is measured against the runner-up so a page carrying the
        # vocabulary of two types -- a diploma registration that cites the
        # resolution authorising it, which every modern one does -- is not
        # settled by a hair.
        and (runner_up == 0.0 or best >= runner_up * (1.0 + MIN_MARGIN))
    )
    if not decided:
        return TypeVerdict(
            document_type=DocumentType.DESCONOCIDO,
            confidence=0.0,
            scores=scores,
            evidence=evidence,
            pages_sampled=sampled,
        )

    return TypeVerdict(
        document_type=leader,
        confidence=best / total if total else 0.0,
        scores=scores,
        evidence=[item for item in evidence if item.document_type is leader],
        pages_sampled=sampled,
    )
