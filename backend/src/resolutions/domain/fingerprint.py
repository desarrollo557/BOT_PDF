"""What little of a page decides where a document begins.

A box of scans is not one document. It is dozens, shuffled together, one to four
pages each, and the body text of a page argues for none of it: a claim letter and
the invoice it disputes read alike for paragraphs. What actually opens a document
is a letterhead, a city and a date, a serial; what closes one is a farewell
formula; and what settles the middle is the page's own claim to be "3 de 5".

Compressing a page to those few facts is not only cheaper to send to a model --
it is the difference between one request for a whole box and one request per
boundary. On a 125-page expediente the measured difference was 4.616 tokens
against 37.200, and one round trip against 124.

Nothing here imports anything: the layer check forbids it, and the rules have to
stay comprehensible in microseconds because a box is hundreds of pages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: How far down the page a line may sit and still be a letterhead. Measured in
#: fractions so one rule survives A4, Letter and whatever the scanner produced.
LETTERHEAD_BAND = 0.22

#: How near the middle a line must be centred to read as a heading rather than a
#: margin note or a column of an address block.
LETTERHEAD_MARGIN = 0.30

#: A heading is a short line. Past this it is a paragraph that happens to start
#: near the top.
LETTERHEAD_MAX_CHARS = 90

#: Only the end of a page can close a document. "Cordialmente me dirijo a
#: ustedes" opens a claim; the same word at the foot of the page ends a reply.
CLOSING_TAIL_CHARS = 350

_PAGINATION = re.compile(
    r"p[aá]g(?:ina)?\.?\s*(\d{1,3})\s*(?:de|/)\s*(\d{1,3})",
    re.IGNORECASE,
)
_SERIAL = re.compile(r"consecutivo\s*N[o0°]?\.?\s*:?\s*([A-Z]?\d{8,})", re.IGNORECASE)
_PLACE_AND_DATE = re.compile(
    r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ .]{3,28}),?\s*(\d{1,2}[-/ ]\d{1,2}[-/ ]\d{2,4})"
)
_CASE_CODE = re.compile(r"\b(RE\d{10,})", re.IGNORECASE)
_CLOSING = re.compile(
    r"\b(cordialmente|atentamente|para constancia (?:se )?firma)",
    re.IGNORECASE,
)

#: Only the head of a page can carry the place-and-date line. Searching the whole
#: page finds every date the document quotes and names the wrong one.
_PLACE_AND_DATE_HEAD_CHARS = 400


@dataclass(frozen=True, slots=True)
class Heading:
    """One line and where it sits, in 0..1 fractions of the page.

    The same shape as `LineBox` in the ports module, restated here because the
    domain may not import from the application layer. A source that cannot say
    where its lines are passes none of these and the rules fall back to text.
    """

    text: str
    center_x: float
    top: float


@dataclass(frozen=True, slots=True)
class Pagination:
    """A page's own claim about its place in a document: "3 de 5"."""

    index: int
    total: int

    @property
    def is_first(self) -> bool:
        return self.index == 1

    @property
    def is_last(self) -> bool:
        return self.index == self.total


@dataclass(frozen=True, slots=True)
class PageFingerprint:
    """One page, reduced to what argues about its boundaries."""

    page_number: int
    title: str
    letterhead: bool
    place_and_date: str | None
    #: The document's own serial. Unlike `case_code`, this changes per document.
    serial: str | None
    pagination: Pagination | None
    #: The claim number. It identifies the CASE, not the document -- every page
    #: of a 125-page expediente carries the same one. Recorded for the inventory
    #: and deliberately never used to decide continuity.
    case_code: str | None
    closes: bool
    #: The last characters of the page, to see whether a sentence was cut.
    tail: str

    def compact(self) -> dict[str, object]:
        """The smallest shape a model can still judge this page from.

        Keys are two letters and absent facts are omitted rather than sent as
        null, because every field is paid for once per page: on a 125-page box
        the full text is ~68.700 tokens and this is ~4.600.

        `case_code` is deliberately left out. It settles nothing -- every page of
        an expediente carries the same one -- and including it only invites the
        model to read it as continuity, which welds the box into one document.
        """
        compact: dict[str, object] = {"p": self.page_number, "t": self.title}
        if self.letterhead:
            compact["mb"] = 1
        if self.place_and_date:
            compact["cf"] = self.place_and_date
        if self.serial:
            compact["cs"] = self.serial
        if self.pagination:
            compact["pg"] = f"{self.pagination.index}/{self.pagination.total}"
        if self.closes:
            compact["fin"] = 1
        if self.tail:
            compact["z"] = self.tail
        return compact


def read_pagination(text: str) -> Pagination | None:
    """The "página X de Y" a page prints on itself, when it is believable.

    OCR damage is why this can refuse: page 9 of a real expediente prints
    "Página 1 de o" because the six came back as a letter. Returning ``1 de 0``
    would be worse than returning nothing -- a chain with a zero total links
    documents that do not exist -- so an impossible reading is no reading.
    """
    match = _PAGINATION.search(text)
    if not match:
        return None
    index, total = int(match.group(1)), int(match.group(2))
    if total < 1 or index < 1 or index > total:
        return None
    return Pagination(index=index, total=total)


def _has_letterhead(headings: list[Heading]) -> bool:
    return any(
        heading.top <= LETTERHEAD_BAND
        and LETTERHEAD_MARGIN < heading.center_x < (1.0 - LETTERHEAD_MARGIN)
        and 0 < len(heading.text.strip()) <= LETTERHEAD_MAX_CHARS
        for heading in headings
    )


def _title(text: str, headings: list[Heading]) -> str:
    """What the page calls itself: its first heading, or its first words."""
    for heading in headings:
        line = " ".join(heading.text.split())
        if heading.top <= LETTERHEAD_BAND and len(line) > 8:
            return line[:70]
    return " ".join(text.split())[:70]


def fingerprint_page(
    page_number: int,
    text: str,
    headings: list[Heading] | None = None,
) -> PageFingerprint:
    """Reduce one page to the facts that decide its boundaries."""
    headings = headings or []
    flat = " ".join(text.split())

    place_and_date = None
    match = _PLACE_AND_DATE.search(flat[:_PLACE_AND_DATE_HEAD_CHARS])
    if match:
        place_and_date = f"{match.group(1).strip()[:22]} {match.group(2)}"

    serial_match = _SERIAL.search(flat)
    case_match = _CASE_CODE.search(flat)

    return PageFingerprint(
        page_number=page_number,
        title=_title(text, headings),
        letterhead=_has_letterhead(headings),
        place_and_date=place_and_date,
        serial=serial_match.group(1) if serial_match else None,
        pagination=read_pagination(flat),
        case_code=case_match.group(1).upper() if case_match else None,
        closes=bool(_CLOSING.search(flat[-CLOSING_TAIL_CHARS:])),
        tail=flat[-45:],
    )
