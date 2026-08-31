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

    #: Hard cap on documents in flight. Sized for batches of hundreds, since a
    #: 50-file drop is the normal case; past it the API pushes back instead of
    #: quietly accumulating a backlog it cannot serve.
    queue_limit: int = 500

    ocr_language: str = "spa"
    mosaic_size: int = 12
    anthropic_api_key: str | None = None
    vision_model: str = "claude-sonnet-5"
    max_upload_bytes: int = 512 * 1024 * 1024

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            upload_dir=Path(os.environ.get("RESOLUTIONS_UPLOAD_DIR", DEFAULT_ROOT / "uploads")),
            output_dir=Path(os.environ.get("RESOLUTIONS_OUTPUT_DIR", DEFAULT_ROOT / "outputs")),
            document_workers=_int("RESOLUTIONS_DOCUMENT_WORKERS", max(1, (os.cpu_count() or 4) - 1)),
            page_workers=_int("RESOLUTIONS_PAGE_WORKERS", 8),
            queue_limit=_int("RESOLUTIONS_QUEUE_LIMIT", 500),
            ocr_language=os.environ.get("RESOLUTIONS_OCR_LANG", "spa"),
            mosaic_size=_int("RESOLUTIONS_MOSAIC_SIZE", 12),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            vision_model=os.environ.get("RESOLUTIONS_VISION_MODEL", "claude-sonnet-5"),
            max_upload_bytes=_int("RESOLUTIONS_MAX_UPLOAD_BYTES", 512 * 1024 * 1024),
        )

    def ensure_directories(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

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
