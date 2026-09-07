"""Cutting a shuffled box into the documents it is made of.

The shipped splitter groups pages by a code every page carries. A box of utility
correspondence has no such code: an invoice, the claim disputing it and the reply
to the claim are three documents that share every identifier the archive knows.
So this decides by continuity instead -- page by page, does the next sheet carry
on or start something new.

Every boundary is decided by evidence and says which. What the evidence cannot
settle comes back as UNDECIDED rather than as a guess, because those are exactly
the boundaries worth paying a model to judge, and a guess dressed as a decision
is indistinguishable from an answer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .errors import IntegrityError
from .fingerprint import PageFingerprint


class Verdict(StrEnum):
    """What happens between one page and the next."""

    #: The right-hand page opens a new document.
    STARTS = "starts"
    #: The right-hand page carries on the left-hand one.
    CONTINUES = "continues"
    #: Nothing on either page settles it. Escalate.
    UNDECIDED = "undecided"


@dataclass(frozen=True, slots=True)
class Boundary:
    """The seam between two adjacent pages, and why it was called that way."""

    left: int
    right: int
    verdict: Verdict
    reason: str
    #: False once a model has overruled or filled in the deterministic verdict,
    #: so a run's cost and its confidence stay measurable after the fact.
    deterministic: bool = True


@dataclass(slots=True)
class Segment:
    """Contiguous pages that form one document."""

    page_numbers: list[int]
    reason: str = ""

    @property
    def size(self) -> int:
        return len(self.page_numbers)


@dataclass(slots=True)
class SegmentationResult:
    segments: list[Segment] = field(default_factory=list)
    boundaries: list[Boundary] = field(default_factory=list)

    @property
    def undecided(self) -> list[Boundary]:
        """The seams a model still has to judge."""
        return [b for b in self.boundaries if b.verdict is Verdict.UNDECIDED]

    def verify_integrity(self, page_numbers: Sequence[int]) -> None:
        """Fail loudly unless every page landed in exactly one segment.

        Called before a single output file is written. A split that silently
        drops or duplicates a page looks identical to a correct one at a glance,
        which is why it has to be impossible rather than unlikely.
        """
        seen: set[int] = set()
        duplicated: set[int] = set()
        for segment in self.segments:
            for page_number in segment.page_numbers:
                if page_number in seen:
                    duplicated.add(page_number)
                seen.add(page_number)

        expected = set(page_numbers)
        missing = expected - seen
        stray = seen - expected
        if duplicated or missing or stray:
            raise IntegrityError(
                "la segmentación no cubre el documento: "
                f"repetidas={sorted(duplicated)} "
                f"faltantes={sorted(missing)} "
                f"ajenas={sorted(stray)}"
            )


def _decide(left: PageFingerprint, right: PageFingerprint) -> tuple[Verdict, str]:
    left_pages, right_pages = left.pagination, right.pagination

    # The strongest evidence there is: the paper counting itself. A sheet that
    # says "1 de 5" is a first page whatever else is printed on it.
    if right_pages and right_pages.is_first:
        return Verdict.STARTS, "la siguiente se declara página 1"

    if left_pages and right_pages:
        if left_pages.total == right_pages.total and right_pages.index == left_pages.index + 1:
            return Verdict.CONTINUES, f"cadena {left_pages.index}->{right_pages.index}"
        return Verdict.STARTS, "la cadena de paginación se rompe"

    # A completed count ends its document even when the next page says nothing.
    if left_pages and left_pages.is_last:
        return Verdict.STARTS, f"la anterior cerró en {left_pages.total} de {left_pages.total}"

    # The serial is per document, unlike the case code.
    if left.serial and right.serial:
        if left.serial == right.serial:
            return Verdict.CONTINUES, "mismo consecutivo"
        return Verdict.STARTS, "cambia el consecutivo"

    # La oración partida por el escáner. Es la evidencia más fuerte que quedaba
    # gratis y no se usaba: `tail` y `title` ya se calculaban -- se le mandaban al
    # modelo en la huella -- así que se pagaba una llamada por costuras que la
    # tipografía del texto ya resolvía.
    if _sentence_runs_on(left, right):
        return Verdict.CONTINUES, "la oración sigue cortada en la hoja siguiente"

    # Un documento que se despidió y otro que abre son dos. `closes` también se
    # calculaba y también se ignoraba. Esta regla empuja a cortar, que es el lado
    # seguro del error: partir un documento en dos se repara en segundos, soldar
    # dos en uno esconde el segundo donde nadie lo va a buscar.
    if left.closes and (right.letterhead or right.place_and_date):
        return Verdict.STARTS, "la anterior se despide y la siguiente abre"

    # Deliberately no rule on `case_code`. Every page of an expediente shares it,
    # so reading it as continuity welds the whole box into one document -- an
    # error measured on a real 125-page file before this module existed.
    return Verdict.UNDECIDED, "sin evidencia estructural"


#: Cuántas palabras necesita el final de una hoja para leerse como prosa cortada
#: y no como un rótulo. Un anexo cuya página entera dice "anexo uno" también
#: termina en letra, y soldarlo con "anexo dos" es el error exacto que esta cuenta
#: evita -- lo detectó la prueba de tres anexos sueltos antes que un operador.
RUNON_TAIL_WORDS = 5

#: Y cuántas necesita el arranque de la siguiente. Una frase retomada es una
#: frase; "anexo dos" son dos palabras y una etiqueta.
RUNON_HEAD_WORDS = 3


def _sentence_runs_on(left: PageFingerprint, right: PageFingerprint) -> bool:
    """Si la oración de la izquierda sigue, sin terminar, en la derecha.

    Estricta a propósito, y la asimetría del error es la razón. Un falso
    CONTINUES suelda dos documentos y el segundo desaparece del inventario sin
    que nadie lo note; un falso STARTS deja dos archivos que el operador junta de
    un vistazo. De modo que cualquier señal de apertura en la hoja derecha
    -- membrete, ciudad y fecha, un consecutivo -- calla esta regla, y ante un
    dato ausente se abstiene en vez de suponer.

    Tres condiciones, y las tres hacen falta:

    * el final de la izquierda es una letra o una coma -- cualquier signo de
      cierre significa que la frase terminó, y con ella pudo terminar el papel;
    * ese final es prosa y no un rótulo, medido en palabras. Una hoja cuyo texto
      completo es "anexo uno" también termina en letra;
    * el arranque de la derecha es una frase en minúscula, no una etiqueta.
    """
    if right.letterhead or right.place_and_date or right.serial:
        return False

    tail = (left.tail or "").rstrip()
    if not tail or not (tail[-1].isalpha() or tail[-1] == ","):
        return False
    if len(tail.split()) < RUNON_TAIL_WORDS:
        return False

    head = (right.title or "").strip()
    if len(head.split()) < RUNON_HEAD_WORDS:
        return False

    first_letter = next((char for char in head if char.isalpha()), None)
    return first_letter is not None and first_letter.islower()


def decide_boundaries(fingerprints: Sequence[PageFingerprint]) -> list[Boundary]:
    """Judge every seam on structure alone, free of charge."""
    boundaries: list[Boundary] = []
    for left, right in zip(fingerprints, fingerprints[1:], strict=False):
        verdict, reason = _decide(left, right)
        boundaries.append(
            Boundary(
                left=left.page_number,
                right=right.page_number,
                verdict=verdict,
                reason=reason,
            )
        )
    return boundaries


def assemble(
    fingerprints: Sequence[PageFingerprint],
    boundaries: Sequence[Boundary],
) -> SegmentationResult:
    """Fold page-by-page verdicts into whole documents.

    An UNDECIDED seam is treated as a cut. Splitting one document in two is a
    mistake an operator can see and repair in seconds; welding two into one hides
    the second where nobody will look for it.
    """
    if not fingerprints:
        return SegmentationResult()

    by_seam = {(b.left, b.right): b for b in boundaries}
    segments = [Segment(page_numbers=[fingerprints[0].page_number], reason="inicio")]

    for left, right in zip(fingerprints, fingerprints[1:], strict=False):
        boundary = by_seam.get((left.page_number, right.page_number))
        continues = boundary is not None and boundary.verdict is Verdict.CONTINUES
        if continues:
            segments[-1].page_numbers.append(right.page_number)
        else:
            reason = boundary.reason if boundary else "sin evidencia estructural"
            segments.append(Segment(page_numbers=[right.page_number], reason=reason))

    return SegmentationResult(segments=segments, boundaries=list(boundaries))
