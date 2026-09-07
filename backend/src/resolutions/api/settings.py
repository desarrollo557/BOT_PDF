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

    #: La otra llave que puede juzgar las costuras de una caja revuelta. Se usa
    #: sólo cuando no hay llave de Anthropic: Claude puede cachear el prompt, que
    #: en una caja se paga una vez por página, y Gemini no. Sin ninguna de las
    #: dos el sistema sigue separando todo lo que la estructura decida sola.
    gemini_api_key: str | None = None

    #: La tercera, y la última en preferencia. No cachea el prompt como Claude ni
    #: trae la capa gratuita de Gemini, así que se usa cuando es la llave que
    #: hay. Sin ninguna de las tres el sistema sigue separando todo lo que la
    #: estructura decida sola.
    mistral_api_key: str | None = None

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

    #: La plantilla oficial del FUID. Vacío significa la que viaja con el
    #: programa; se pone una ruta cuando la Universidad publique otra versión
    #: del formato y no se quiera esperar a un despliegue.
    fuid_template: str | None = None

    #: Datos de ubicación física que el PDF no puede saber y que se repiten en
    #: todas las filas de un lote. Lo que no se conoce va como N/A, que es lo
    #: que manda el instructivo del formato.
    #:
    #: La caja es la excepción: la lleva la caja física que se está procesando
    #: ahora mismo, y se cambia con RESOLUTIONS_FUID_CAJA cuando se pase a otra.
    fuid_caja: str = "3269"
    fuid_otro: str = "N/A"
    fuid_codigo_trd: str = "N/A"
    fuid_oficina: str | None = None

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
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
            mistral_api_key=os.environ.get("MISTRAL_API_KEY") or None,
            max_upload_bytes=_int("RESOLUTIONS_MAX_UPLOAD_BYTES", 4 * 1024 * 1024 * 1024),
            ledger_path=Path(
                os.environ.get("RESOLUTIONS_LEDGER", DEFAULT_ROOT / "inventory.jsonl")
            ),
            sweep_seconds=_float("RESOLUTIONS_SWEEP_SECONDS", 30.0),
            fuid_template=os.environ.get("RESOLUTIONS_FUID_TEMPLATE") or None,
            fuid_caja=os.environ.get("RESOLUTIONS_FUID_CAJA", "3269"),
            fuid_otro=os.environ.get("RESOLUTIONS_FUID_OTRO", "N/A"),
            fuid_codigo_trd=os.environ.get("RESOLUTIONS_FUID_TRD", "N/A"),
            fuid_oficina=os.environ.get("RESOLUTIONS_FUID_OFICINA") or None,
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
            "gemini_api_key": self.gemini_api_key,
            "mistral_api_key": self.mistral_api_key,
            "fuid_template": self.fuid_template,
            "fuid_caja": self.fuid_caja,
            "fuid_otro": self.fuid_otro,
            "fuid_codigo_trd": self.fuid_codigo_trd,
            "fuid_oficina": self.fuid_oficina,
        }
