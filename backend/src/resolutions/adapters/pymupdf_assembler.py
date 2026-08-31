from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pymupdf

from ..application.ports import AssemblyResult
from ..domain.grouping import GroupingResult
from ..domain.naming import output_filename

logger = logging.getLogger(__name__)

QUARANTINE_FILE = "_quarantine.pdf"

#: Scratch copy of a damaged source, renumbered so its objects can be grafted.
#: Deleted once the outputs are written.
REPAIRED_FILE = "_repaired.pdf"

#: Windows refuses to open a path longer than this, and the refusal arrives at
#: save time -- after every page has been read, grouped and copied. A resolution
#: lost to a long title is a resolution lost for no reason at all.
MAX_PATH = 260

#: Slack for the numbering a destination folder may add on collision, e.g.
#: " (2)" in a delivery folder that already holds the same number.
PATH_MARGIN = 10


def name_budget(destination: Path) -> int:
    """How many characters a file name may use inside ``destination``."""
    try:
        room = MAX_PATH - len(str(destination.resolve())) - 1 - PATH_MARGIN
    except OSError:
        room = MAX_PATH - len(str(destination)) - 1 - PATH_MARGIN
    # Never below what a bare code plus extension needs; a directory that deep
    # is a problem the operator has to solve, not one to silently mangle names
    # over.
    return max(room, 24)


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
    """Writes one PDF per resolution, plus a file holding whatever was quarantined.

    Damage is expected, not exceptional. Scanners, mail gateways and decades-old
    archives all produce PDFs whose object tables do not survive a strict read,
    and a document that arrives at this stage has already been read, grouped and
    balanced -- losing it here would throw away all of that work. So the writer
    degrades in three steps: repair the source, fall back from block copies to
    single pages, and finally set aside the individual pages that cannot be
    copied at all, reporting them instead of failing the document.
    """

    def write(
        self,
        source: Path,
        result: GroupingResult,
        destination: Path,
    ) -> AssemblyResult:
        destination.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        names: dict[str, str] = {}
        unwritable: dict[int, str] = {}
        budget = name_budget(destination)

        origin, scratch = self._open_graftable(source, destination)
        try:
            for group in result.groups:
                name = output_filename(group.code, group.title, budget=budget)
                target = destination / name
                if self._write_guarded(origin, group.page_numbers, target, unwritable):
                    written.append(target)
                    names[group.code.value] = name

            if result.quarantine:
                # Never dropped, never guessed at: quarantined pages ship as their
                # own file so the operator can see exactly what was set aside.
                target = destination / QUARANTINE_FILE
                if self._write_guarded(origin, result.quarantine, target, unwritable):
                    written.append(target)
        finally:
            origin.close()
            if scratch is not None:
                scratch.unlink(missing_ok=True)

        return AssemblyResult(outputs=written, unwritable_pages=unwritable, written=names)

    @staticmethod
    def _open_graftable(source: Path, destination: Path) -> tuple[pymupdf.Document, Path | None]:
        """Open the source in a state its objects can actually be copied out of.

        When MuPDF has to rebuild a broken cross-reference table it does so in
        memory, and the object numbers the page tree cites are then not the ones
        the rebuilt table holds. Reading such a document works; grafting pages out
        of it is what raises "source object number out of range". Writing the
        rebuild out and reopening it renumbers everything consistently, which
        costs one pass over the file and only for documents that are damaged.
        """
        document = pymupdf.open(source)
        if not document.is_repaired:
            return document, None

        logger.warning("%s arrived damaged; normalising before assembly", source.name)
        scratch = destination / REPAIRED_FILE
        try:
            document.save(scratch, garbage=4, clean=True, deflate=True)
        except Exception:  # noqa: BLE001 - the unrepaired document is still usable
            logger.warning("could not normalise %s, assembling from the original", source.name)
            return document, None

        document.close()
        return pymupdf.open(scratch), scratch

    def _write_guarded(
        self,
        origin: pymupdf.Document,
        page_numbers: list[int],
        target: Path,
        unwritable: dict[int, str],
    ) -> bool:
        """Write one file, containing any failure to that file.

        The last line of defence. Whatever goes wrong with one resolution, the
        other resolutions of the same document still get written, and the pages
        of the one that failed are named rather than quietly missing.
        """
        try:
            return self._write_pages(origin, page_numbers, target, unwritable)
        except Exception as error:  # noqa: BLE001 - contained to this file
            logger.warning("could not write %s: %s", target.name, error)
            target.unlink(missing_ok=True)
            for page_number in page_numbers:
                unwritable.setdefault(page_number, f"{type(error).__name__}: {error}")
            return False

    def _write_pages(
        self,
        origin: pymupdf.Document,
        page_numbers: list[int],
        target: Path,
        unwritable: dict[int, str],
    ) -> bool:
        """Write one output file. Returns whether anything was actually written.

        Two attempts. The fast one copies whole ranges and saves once, which is
        what every healthy document takes. If anything in it raises -- including
        the save, because MuPDF resolves grafted objects lazily and a damaged
        one surfaces there rather than at the insert -- the whole group is
        rebuilt a page at a time.
        """
        try:
            if self._write_in_blocks(origin, page_numbers, target):
                return True
        except Exception as error:  # noqa: BLE001 - retried page by page
            logger.warning(
                "block assembly of %s failed (%s); rebuilding page by page",
                target.name,
                error,
            )
            target.unlink(missing_ok=True)

        return self._write_page_by_page(origin, page_numbers, target, unwritable)

    @staticmethod
    def _write_in_blocks(
        origin: pymupdf.Document, page_numbers: list[int], target: Path
    ) -> bool:
        """The fast path: one insert per consecutive range, one save."""
        if not page_numbers:
            return False
        with pymupdf.open() as output:
            for first, last in _runs(page_numbers):
                output.insert_pdf(origin, from_page=first - 1, to_page=last - 1)
            output.save(target, garbage=3, deflate=True)
        return True

    def _write_page_by_page(
        self,
        origin: pymupdf.Document,
        page_numbers: list[int],
        target: Path,
        unwritable: dict[int, str],
    ) -> bool:
        """The salvage path: every page is proved on its own before it goes in.

        Each page is serialised by itself first. That forces MuPDF to resolve
        exactly one page's objects, so a page that cannot be copied fails here,
        by number, instead of poisoning the save of the whole file. It costs a
        serialise per page and runs only after the fast path has already failed.
        """
        with pymupdf.open() as output:
            copied = 0
            for page_number in page_numbers:
                try:
                    isolated = self._isolate(origin, page_number)
                except Exception as error:  # noqa: BLE001 - reported, not swallowed
                    # The page is lost, the document is not. It goes to review
                    # named, so nobody has to diff page counts to find it.
                    logger.warning("page %s could not be copied: %s", page_number, error)
                    unwritable[page_number] = f"{type(error).__name__}: {error}"
                    continue

                with pymupdf.open("pdf", isolated) as clean:
                    output.insert_pdf(clean)
                copied += 1

            if not copied:
                # Every page failed. An empty PDF on disk would look like a
                # resolution that legitimately has no pages.
                return False
            self._save_defensively(output, target)
        return True

    @staticmethod
    def _save_defensively(output: pymupdf.Document, target: Path) -> None:
        """Save, and if compaction is what objects to the file, save without it.

        Garbage collection and compression both walk every object. When one of
        them is what raises, writing the file plainly still produces a PDF a
        reader can open, which is the thing that actually matters.
        """
        try:
            output.save(target, garbage=3, deflate=True)
        except Exception as error:  # noqa: BLE001 - retried without compaction
            logger.warning("compacted save of %s failed (%s); saving plainly", target.name, error)
            target.unlink(missing_ok=True)
            output.save(target)

    @staticmethod
    def _isolate(origin: pymupdf.Document, page_number: int) -> bytes:
        """Serialise one page on its own, so its damage cannot spread."""
        single = pymupdf.open()
        try:
            single.insert_pdf(origin, from_page=page_number - 1, to_page=page_number - 1)
            return single.tobytes(garbage=3, deflate=True)
        finally:
            single.close()
