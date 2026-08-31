from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(os.environ.get("RESOLUTIONS_DATA_DIR", "./data")).resolve()


def _int(name: str, fallback: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return fallback


def _float(name: str, fallback: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return fallback


@dataclass(frozen=True, slots=True)
class Settings:
    upload_dir: Path = DEFAULT_ROOT / "uploads"
    output_dir: Path = DEFAULT_ROOT / "outputs"

    #: Documents processed concurrently. One OS process each, because a 400-page
    #: PDF is CPU-bound work and processes are the only way past the GIL.
    document_workers: int = max(1, (os.cpu_count() or 4) - 1)

    #: Threads inside a worker, fanning pages out across the OCR engine. Native
    #: code releases the GIL, so this scales without another process boundary.
    page_workers: int = 8

    #: Documents in flight before the API pushes back. Not a limit on how much
    #: can be processed -- the pool drains it steadily -- only on how much may be
    #: accepted and not yet started, since each waiting job holds its upload on
    #: disk. Raise it freely; the memory per queued job is a few kilobytes.
    queue_limit: int = 10_000

    ocr_language: str = "spa"
    mosaic_size: int = 12
    anthropic_api_key: str | None = None
    vision_model: str = "claude-sonnet-5"

    #: Uploads are streamed to disk in chunks and never held in memory, so this
    #: bounds disk use rather than RAM. Four gigabytes covers a full archive box
    #: scanned at 300 dpi; set it higher when the scanner disagrees.
    max_upload_bytes: int = 4 * 1024 * 1024 * 1024

    #: How often the idle janitor looks for scratch to reclaim. It does nothing
    #: at all unless the queue is empty and something has changed since the last
    #: pass, so this is a poll of one integer comparison in the common case.
    sweep_seconds: float = 30.0

    #: The durable record of every resolution PDF ever produced. It outlives the
    #: job registry, so clearing the screen never erases the history of the work.
    ledger_path: Path = DEFAULT_ROOT / "inventory.jsonl"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            upload_dir=Path(os.environ.get("RESOLUTIONS_UPLOAD_DIR", DEFAULT_ROOT / "uploads")),
            output_dir=Path(os.environ.get("RESOLUTIONS_OUTPUT_DIR", DEFAULT_ROOT / "outputs")),
            document_workers=_int("RESOLUTIONS_DOCUMENT_WORKERS", max(1, (os.cpu_count() or 4) - 1)),
            page_workers=_int("RESOLUTIONS_PAGE_WORKERS", 8),
            queue_limit=_int("RESOLUTIONS_QUEUE_LIMIT", 10_000),
            ocr_language=os.environ.get("RESOLUTIONS_OCR_LANG", "spa"),
            mosaic_size=_int("RESOLUTIONS_MOSAIC_SIZE", 12),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            vision_model=os.environ.get("RESOLUTIONS_VISION_MODEL", "claude-sonnet-5"),
            max_upload_bytes=_int("RESOLUTIONS_MAX_UPLOAD_BYTES", 4 * 1024 * 1024 * 1024),
            ledger_path=Path(
                os.environ.get("RESOLUTIONS_LEDGER", DEFAULT_ROOT / "inventory.jsonl")
            ),
            sweep_seconds=_float("RESOLUTIONS_SWEEP_SECONDS", 30.0),
        )

    def ensure_directories(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def as_worker_payload(self) -> dict[str, object]:
        """Only what a worker process needs, and nothing that cannot be pickled."""
        return {
            "output_dir": str(self.output_dir),
            "page_workers": self.page_workers,
            "ocr_language": self.ocr_language,
            "mosaic_size": self.mosaic_size,
            "anthropic_api_key": self.anthropic_api_key,
            "vision_model": self.vision_model,
        }
