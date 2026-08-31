from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from ..application.inventory import Inventory

INVENTORY_JSON = "inventory.json"
INVENTORY_CSV = "inventory.csv"

_CSV_COLUMNS = (
    "source_document",
    "file_name",
    "code",
    "title",
    "page_count",
    "first_page",
    "last_page",
    "page_numbers",
)


class FileInventoryStore:
    """Writes the inventory next to the files it describes.

    JSON for the API and the front end, CSV because the person who has to check
    this work opens it in a spreadsheet, not in a browser dev tools panel.
    """

    def write(self, inventory: Inventory, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=True)

        payload = inventory.as_dict()
        payload["generated_at"] = datetime.now(UTC).isoformat()

        json_path = destination / INVENTORY_JSON
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with (destination / INVENTORY_CSV).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=_CSV_COLUMNS)
            writer.writeheader()
            for item in inventory.items:
                writer.writerow(
                    {
                        "source_document": inventory.source_document,
                        "file_name": item.file_name,
                        "code": item.code,
                        "title": item.title or "",
                        "page_count": item.page_count,
                        "first_page": item.first_page,
                        "last_page": item.last_page,
                        # Ranges rather than every number: a 40-page block reads
                        # as "12-51" instead of forty comma-separated integers.
                        "page_numbers": _compact(item.page_numbers),
                    }
                )

        return json_path


def _compact(page_numbers: list[int]) -> str:
    if not page_numbers:
        return ""
    parts: list[str] = []
    start = previous = page_numbers[0]
    for number in page_numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = number
    parts.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(parts)
