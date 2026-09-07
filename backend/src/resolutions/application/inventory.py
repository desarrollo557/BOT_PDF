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
    file_names: dict[str, str] | None = None,
) -> Inventory:
    """Describe what one document produced.

    ``file_names`` is what the writer actually put on disk. It is preferred over
    recomputing the name, because the writer is allowed to shorten one to fit
    the filesystem and an inventory that names a file nobody can open is worse
    than no inventory.
    """
    names = file_names or {}
    return Inventory(
        source_document=source_document,
        source_pages=source_pages,
        items=[
            InventoryItem(
                file_name=names.get(group.code.value)
                or output_filename(group.code, group.title),
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


def rows_of(report: dict) -> list[dict[str, object]]:
    """Las filas que un informe terminado aporta al inventario.

    Existe porque hay dos formas de terminar y los dos almacenes tienen que
    entender las dos. La ruta de resoluciones deja un `inventory.items` ya
    armado; la de segmentación deja `groups` y `outputs` y ningún inventario,
    porque separar por continuidad no levanta FUID -- el formulario pide asunto
    y tipo documental, que son preguntas sobre un documento que ya tiene bordes.

    Tenerlo dos veces salió caro: el archivo JSONL sabía leer las dos formas y
    el de MySQL sólo la primera, así que una caja separada por documento
    escribía sus PDF y no aparecía en la pantalla de Archivo. Sin excepción, sin
    aviso y sin nada en el registro: `record` devolvía cero y nadie mira ese
    número.
    """
    inventory = report.get("inventory") or {}
    items = list(inventory.get("items") or [])
    if items:
        return items

    groups = report.get("groups") or []
    outputs = report.get("outputs") or []
    if not groups and not outputs:
        return []

    for index, group in enumerate(groups):
        pages = list(group.get("pages") or [])
        file_name = outputs[index] if index < len(outputs) else ""
        if not file_name:
            continue
        items.append(
            {
                "code": group.get("code") or "",
                "title": group.get("title"),
                "file_name": file_name,
                "page_count": int(group.get("size") or len(pages) or 0),
                "first_page": pages[0] if pages else 0,
                "last_page": pages[-1] if pages else 0,
                "page_numbers": pages,
            }
        )

    # Un trabajo que escribió archivos sin dejar grupos sigue siendo trabajo
    # hecho, y el operador tiene que poder encontrarlo.
    if not items and outputs:
        items = [
            {
                "code": "",
                "title": None,
                "file_name": file_name,
                "page_count": 1,
                "first_page": 0,
                "last_page": 0,
                "page_numbers": [],
            }
            for file_name in outputs
        ]
    return items
