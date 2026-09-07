from __future__ import annotations

import csv
import io
import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LEDGER_COLUMNS = (
    "recorded_at",
    "source_document",
    "code",
    "title",
    "file_name",
    "page_count",
    "first_page",
    "last_page",
    "pages",
    "job_id",
    "operator",
    "source_pages",
)


def _compact(page_numbers: list[int]) -> str:
    """Page numbers as ranges: forty integers read as "12-51"."""
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


class InventoryReads:
    """Lo que se deduce de las filas, sin importar dónde estén guardadas.

    Un almacén de inventario sólo tiene que saber devolver ``rows()``; contar
    documentos, códigos y páginas se hace igual sobre un archivo que sobre una
    base de datos. Tenerlo escrito una sola vez es lo que impide que el archivo
    y la base respondan cosas distintas a la misma pregunta.
    """

    def rows(self) -> list[dict]:  # pragma: no cover - lo implementa cada almacén
        raise NotImplementedError

    def documents(self) -> list[dict]:
        """One entry per source document ever processed, newest first.

        The ledger records resolutions; this folds them back into the documents
        they came from, which is the unit an operator looks for afterwards. It
        is derived rather than stored because the rows are the truth and a
        second copy of the same facts is a second thing to keep in step.
        """
        by_job: dict[str, dict] = {}
        for row in self.rows():
            job_id = row.get("job_id") or ""
            entry = by_job.get(job_id)
            if entry is None:
                entry = by_job[job_id] = {
                    "job_id": job_id,
                    "source_document": row.get("source_document") or "",
                    "processed_at": row.get("recorded_at") or "",
                    "resolutions": 0,
                    "pages": 0,
                    "codes": [],
                    "operator": row.get("operator"),
                    # Per-document facts, identical on every row of the
                    # document, so the first one seen is the answer.
                    "source_pages": int(row.get("source_pages") or 0),
                    "bytes": int(row.get("source_bytes") or 0),
                    "review": int(row.get("review") or 0),
                }
            entry["resolutions"] += 1
            entry["pages"] += int(row.get("page_count") or 0)
            # Enough codes to recognise the document, not enough to be a list.
            if len(entry["codes"]) < 8:
                entry["codes"].append(row.get("code"))
            recorded = row.get("recorded_at") or ""
            if recorded and recorded < entry["processed_at"]:
                entry["processed_at"] = recorded
        return list(by_job.values())

    def job_ids(self) -> set[str]:
        """Jobs the ledger still refers to, so their output is never swept."""
        return {row["job_id"] for row in self.rows() if row.get("job_id")}

    def summary(self) -> dict[str, object]:
        rows = self.rows()
        return {
            "resolutions": len(rows),
            "documents": len({row.get("source_document") for row in rows}),
            "codes": len({row.get("code") for row in rows}),
            "pages": sum(int(row.get("page_count") or 0) for row in rows),
        }

    def as_csv(self, rows: list[dict] | None = None) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=LEDGER_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows if rows is not None else self.rows():
            writer.writerow({column: row.get(column, "") for column in LEDGER_COLUMNS})
        return buffer.getvalue()


class InventoryLedger(InventoryReads):
    """Every resolution PDF the system has ever produced, one line each.

    A per-document ``inventory.json`` answers "what came out of this file". It
    cannot answer "which document did resolution 00086 come from", which is the
    question actually asked once a few hundred documents have gone through. This
    is that index: append-only JSONL, so recording a finished job is one write at
    the end of a file and never a rewrite of the whole thing.

    It outlives the job registry on purpose. Clearing the screen forgets jobs;
    the ledger is the record that the work happened.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        #: Cached parse, invalidated by the file's own size and mtime. A screen
        #: that polls the inventory must not re-read a 50,000-line file each time.
        self._cache: list[dict] | None = None
        self._signature: tuple[int, int] | None = None

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        job_id: str,
        report: dict,
        operator: str | None = None,
        source_bytes: int = 0,
    ) -> int:
        """Append one line per generated file. Returns how many were written."""
        inventory = report.get("inventory") or {}
        items = inventory.get("items") or []
        if not items:
            groups = report.get("groups") or []
            outputs = report.get("outputs") or []
            if not groups and not outputs:
                return 0
            items = []
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

        recorded_at = datetime.now(UTC).isoformat()
        source = inventory.get("source_document") or report.get("document") or ""
        # Facts about the document, repeated on each of its rows. The archive
        # shows a card per document and would otherwise have blanks where the
        # size and the review count should be.
        source_pages = int(inventory.get("source_pages") or report.get("page_count") or 0)
        review = len(report.get("review_queue") or [])
        lines = [
            json.dumps(
                {
                    "recorded_at": recorded_at,
                    "source_document": source,
                    "code": item["code"],
                    "title": item.get("title"),
                    "file_name": item["file_name"],
                    "page_count": item["page_count"],
                    "first_page": item["first_page"],
                    "last_page": item["last_page"],
                    "pages": _compact(item.get("page_numbers") or []),
                    "job_id": job_id,
                    "operator": operator,
                    "source_pages": source_pages,
                    "source_bytes": source_bytes,
                    "review": review,
                },
                ensure_ascii=False,
            )
            for item in items
        ]

        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
            self._cache = None
        return len(lines)

    def update(self, job_id: str, file_name: str, changes: dict) -> dict | None:
        """Edit one recorded row in place. Returns the row as it now stands.

        Appending is the hot path and stays an append; editing is rare enough
        that rewriting the file is the honest implementation rather than a
        tombstone scheme nobody would remember to compact.
        """
        return self._rewrite(job_id, file_name, changes)

    def remove(self, job_id: str, file_name: str) -> dict | None:
        """Drop one recorded row. Returns what was removed, or ``None``."""
        return self._rewrite(job_id, file_name, None)

    def remove_document(self, job_id: str) -> int:
        """Drop every row of one document. Returns how many rows went.

        A document is not a row here -- it is however many resolutions came out
        of it -- so forgetting one means forgetting all of them at once. Doing it
        row by row would leave a half-erased document on screen if the second
        call failed.
        """
        return self._rewrite_document(job_id, None)

    def rename_document(self, job_id: str, source_document: str) -> int:
        """Rename a processed document. Returns how many rows were touched.

        The name lives on every row of the document, so the correction has to
        reach all of them: a document whose rows disagree about their own origin
        shows up twice in the archive.
        """
        return self._rewrite_document(job_id, {"source_document": source_document})

    def _rewrite_document(self, job_id: str, changes: dict | None) -> int:
        with self._lock:
            try:
                lines = self._path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return 0

            kept: list[str] = []
            touched = 0
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    row = json.loads(stripped)
                except json.JSONDecodeError:
                    kept.append(stripped)
                    continue

                if row.get("job_id") != job_id:
                    kept.append(stripped)
                    continue

                touched += 1
                if changes is None:
                    continue
                kept.append(json.dumps({**row, **changes}, ensure_ascii=False))

            if not touched:
                return 0

            scratch = self._path.with_suffix(".jsonl.tmp")
            body = "\n".join(kept)
            scratch.write_text(f"{body}\n" if kept else "", encoding="utf-8")
            scratch.replace(self._path)
            self._cache = None
            return touched

    def _rewrite(self, job_id: str, file_name: str, changes: dict | None) -> dict | None:
        with self._lock:
            try:
                lines = self._path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return None

            kept: list[str] = []
            touched: dict | None = None
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    row = json.loads(stripped)
                except json.JSONDecodeError:
                    kept.append(stripped)
                    continue

                if touched is None and row.get("job_id") == job_id and row.get("file_name") == file_name:
                    if changes is None:
                        touched = row
                        continue
                    row = {**row, **{k: v for k, v in changes.items() if v is not None}}
                    touched = row
                    kept.append(json.dumps(row, ensure_ascii=False))
                    continue
                kept.append(stripped)

            if touched is None:
                return None

            # Written beside the ledger and moved into place, so a crash halfway
            # through leaves the previous file intact rather than a half ledger.
            scratch = self._path.with_suffix(".jsonl.tmp")
            body = "\n".join(kept)
            scratch.write_text(f"{body}\n" if kept else "", encoding="utf-8")
            scratch.replace(self._path)
            self._cache = None
            return touched

    def rows(self) -> list[dict]:
        """Every recorded file, newest first. Cached until the file changes."""
        with self._lock:
            try:
                stat = self._path.stat()
            except OSError:
                self._cache, self._signature = [], None
                return []

            signature = (stat.st_size, stat.st_mtime_ns)
            if self._cache is not None and self._signature == signature:
                return self._cache

            rows: list[dict] = []
            with self._path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        # A torn last line from a hard kill loses one row, never
                        # the ledger.
                        logger.warning("skipping malformed ledger line")

            rows.reverse()
            self._cache, self._signature = rows, signature
            return rows

