from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator

import pymupdf

from ..domain.grouping import GroupingResult
from ..domain.naming import output_filename

QUARANTINE_FILE = "_quarantine.pdf"


def _runs(page_numbers: list[int]) -> Iterator[tuple[int, int]]:
    """Collapse page numbers into consecutive ranges.

    Copying a 40-page block as one range instead of 40 single-page inserts is
    roughly an order of magnitude fewer object rewrites in the output PDF.
    """
    if not page_numbers:
        return
    start = previous = page_numbers[0]
    for number in page_numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        yield start, previous
        start = previous = number
    yield start, previous


class PyMuPDFAssembler:
    """Writes one PDF per resolution, plus a file holding whatever was quarantined."""

    def write(
        self,
        source: Path,
        result: GroupingResult,
        destination: Path,
    ) -> Iterable[Path]:
        destination.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []

        with pymupdf.open(source) as origin:
            for group in result.groups:
                target = destination / output_filename(group.code, group.title)
                self._write_pages(origin, group.page_numbers, target)
                written.append(target)

            if result.quarantine:
                # Never dropped, never guessed at: quarantined pages ship as their
                # own file so the operator can see exactly what was set aside.
                target = destination / QUARANTINE_FILE
                self._write_pages(origin, result.quarantine, target)
                written.append(target)

        return written

    @staticmethod
    def _write_pages(origin: pymupdf.Document, page_numbers: list[int], target: Path) -> None:
        with pymupdf.open() as output:
            for first, last in _runs(page_numbers):
                output.insert_pdf(origin, from_page=first - 1, to_page=last - 1)
            output.save(target, garbage=3, deflate=True)
