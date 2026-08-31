from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Sequence

from .errors import IntegrityError
from .page import PageClassification
from .resolution_code import ResolutionCode

DEFAULT_PHANTOM_DISTANCE = 2


@dataclass(frozen=True, slots=True)
class PageGroup:
    """All pages that belong to one resolution, in original document order."""

    code: ResolutionCode
    page_numbers: list[int]
    #: Read from the first page that declared this code, so a resolution split
    #: across a document is named once and consistently.
    title: str | None = None

    @property
    def size(self) -> int:
        return len(self.page_numbers)


@dataclass(frozen=True, slots=True)
class PhantomRepair:
    """A one-page reading overruled because both neighbours disagreed with it."""

    page_number: int
    observed: ResolutionCode
    applied: ResolutionCode
    distance: int


@dataclass(frozen=True, slots=True)
class GroupingResult:
    groups: list[PageGroup] = field(default_factory=list)
    quarantine: list[int] = field(default_factory=list)
    repairs: list[PhantomRepair] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return sum(group.size for group in self.groups) + len(self.quarantine)

    def verify_integrity(self, total_pages: int) -> None:
        """Fail loudly unless every input page landed in exactly one bucket.

        Called before a single output file is written. A split that silently
        drops or duplicates pages is indistinguishable from a correct one at a
        glance, which is exactly why it has to be impossible.
        """
        seen: set[int] = set()
        duplicated: set[int] = set()
        for group in self.groups:
            for page_number in group.page_numbers:
                if page_number in seen:
                    duplicated.add(page_number)
                seen.add(page_number)
        for page_number in self.quarantine:
            if page_number in seen:
                duplicated.add(page_number)
            seen.add(page_number)

        if duplicated:
            raise IntegrityError(f"pages assigned more than once: {sorted(duplicated)}")

        expected = set(range(1, total_pages + 1))
        if seen != expected:
            missing = sorted(expected - seen)
            unexpected = sorted(seen - expected)
            raise IntegrityError(
                f"page accounting failed: missing={missing} unexpected={unexpected}"
            )


class GroupingEngine:
    """Turns a page-by-page reading into the files that will be written.

    One linear pass, no lookahead beyond the phantom repair, no allocation per
    page beyond the bucket it lands in. A 400-page document groups in
    microseconds, which keeps the whole cost of a job in the OCR stage where it
    belongs.
    """

    def __init__(self, *, max_phantom_distance: int = DEFAULT_PHANTOM_DISTANCE) -> None:
        self._max_phantom_distance = max_phantom_distance

    def group(self, pages: Sequence[PageClassification]) -> GroupingResult:
        repaired, repairs = self._repair_ocr_phantoms(pages)

        buckets: dict[ResolutionCode, list[int]] = {}
        titles: dict[ResolutionCode, str] = {}
        quarantine: list[int] = []
        active: ResolutionCode | None = None

        for page in repaired:
            if page.code is not None:
                active = page.code
                # Only a page that declares the code gets to name it. A
                # continuation page's first line is prose, not a title.
                if page.title and page.code not in titles:
                    titles[page.code] = page.title
            if active is None:
                # Nothing has been read yet, so there is no honest owner. Guessing
                # here would inject foreign pages into a real resolution and no
                # one would ever notice.
                quarantine.append(page.page_number)
            else:
                # Inheritance follows the previous page; the bucket it lands in
                # follows the code. That is what makes a reappearing code rejoin
                # its original group instead of opening a new one.
                buckets.setdefault(active, []).append(page.page_number)

        groups = [
            PageGroup(code=code, page_numbers=numbers, title=titles.get(code))
            for code, numbers in buckets.items()
        ]
        return GroupingResult(groups=groups, quarantine=quarantine, repairs=repairs)

    def _repair_ocr_phantoms(
        self, pages: Sequence[PageClassification]
    ) -> tuple[list[PageClassification], list[PhantomRepair]]:
        """Absorb a lone misread wedged between two identical readings.

        Without this, flipping a single glyph on one page of a 40-page
        resolution shatters it into three output files.
        """
        working = list(pages)
        coded = [index for index, page in enumerate(working) if page.code is not None]
        repairs: list[PhantomRepair] = []

        for position in range(1, len(coded) - 1):
            before = working[coded[position - 1]].code
            current_page = working[coded[position]]
            after = working[coded[position + 1]].code
            current = current_page.code

            assert before is not None and after is not None and current is not None
            if before != after or current == before:
                continue

            distance = current.distance_to(before)
            if distance > self._max_phantom_distance:
                continue

            working[coded[position]] = replace(current_page, code=before)
            repairs.append(
                PhantomRepair(
                    page_number=current_page.page_number,
                    observed=current,
                    applied=before,
                    distance=distance,
                )
            )

        return working, repairs
