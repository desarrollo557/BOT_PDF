from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.grouping import GroupingResult
from ..domain.naming import output_filename


@dataclass(frozen=True, slots=True)
class InventoryItem:
    """One generated PDF, traced back to the pages it came from."""

    file_name: str
    code: str
    title: str | None
    page_count: int
    page_numbers: list[int]

    @property
    def first_page(self) -> int:
        return self.page_numbers[0]

    @property
    def last_page(self) -> int:
        return self.page_numbers[-1]

    def as_dict(self) -> dict[str, object]:
        return {
            "file_name": self.file_name,
            "code": self.code,
            "title": self.title,
            "page_count": self.page_count,
            "first_page": self.first_page,
            "last_page": self.last_page,
            "page_numbers": self.page_numbers,
        }


@dataclass(frozen=True, slots=True)
class Inventory:
    """What came out of one source document, and where every page went.

    This is the audit trail: given a generated file you can name the pages it
    came from, and given a source page you can name the file it ended up in.
    """

    source_document: str
    source_pages: int
    items: list[InventoryItem] = field(default_factory=list)
    quarantine_pages: list[int] = field(default_factory=list)
    review_pages: list[int] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)

    @property
    def pages_accounted_for(self) -> int:
        return sum(item.page_count for item in self.items) + len(self.quarantine_pages)

    def as_dict(self) -> dict[str, object]:
        return {
            "source_document": self.source_document,
            "source_pages": self.source_pages,
            "generated_files": len(self.items),
            "pages_accounted_for": self.pages_accounted_for,
            "items": [item.as_dict() for item in self.items],
            "quarantine_pages": self.quarantine_pages,
            "review_pages": self.review_pages,
            "stats": self.stats,
        }


def build_inventory(
    source_document: str,
    source_pages: int,
    result: GroupingResult,
    review_pages: list[int],
    stats: dict[str, object],
) -> Inventory:
    return Inventory(
        source_document=source_document,
        source_pages=source_pages,
        items=[
            InventoryItem(
                file_name=output_filename(group.code, group.title),
                code=group.code.value,
                title=group.title,
                page_count=group.size,
                page_numbers=group.page_numbers,
            )
            for group in result.groups
        ],
        quarantine_pages=list(result.quarantine),
        review_pages=review_pages,
        stats=stats,
    )
