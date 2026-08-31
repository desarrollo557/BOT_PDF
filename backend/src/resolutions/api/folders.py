from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from .jobs import Job, JobRegistry, JobState
from .settings import Settings

logger = logging.getLogger(__name__)

#: Deliveries kept for the live view. It is a window on a running job, not a
#: record -- the inventory is the record -- so it never grows without bound.
DELIVERY_WINDOW = 60

#: How often a watching run looks for new files. Long enough that an idle folder
#: costs one directory listing a few times a minute.
WATCH_INTERVAL = 5.0


class RunState(StrEnum):
    SCANNING = "scanning"
    PROCESSING = "processing"
    #: Nothing left to do, still watching the folder for new arrivals.
    WATCHING = "watching"
    DONE = "done"
    STOPPED = "stopped"
    FAILED = "failed"


class SourceDisposition(StrEnum):
    """What happens to the original once its resolutions have been delivered."""

    LEAVE = "leave"
    MOVE = "move"
    DELETE = "delete"


#: Where originals go under ``MOVE``. Inside the source folder, so the operator
#: finds them exactly where they left them.
CONSUMED_DIR = "_procesados"


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FolderError(ValueError):
    """A source or destination that cannot be used, explained in Spanish."""


@dataclass(frozen=True, slots=True)
class Delivery:
    """One generated PDF copied into the destination folder."""

    file_name: str
    source_document: str
    destination: str
    at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, object]:
        return {
            "file_name": self.file_name,
            "source_document": self.source_document,
            "destination": self.destination,
            "at": self.at,
        }


@dataclass(slots=True)
class FolderRun:
    """One local source folder being drained into one destination folder."""

    id: str
    source: Path
    destination: Path
    disposition: SourceDisposition = SourceDisposition.LEAVE
    watch: bool = False
    #: Who started it. Attribution, never authorisation.
    operator: str | None = None
    state: RunState = RunState.SCANNING
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    error: str | None = None

    #: Files already taken. Without this a watching run would re-consume every
    #: document on its next pass whenever the originals are left in place.
    seen: set[str] = field(default_factory=set)
    queue: list[str] = field(default_factory=list)
    current: str | None = None
    current_job_id: str | None = None
    #: Every document this run created, in the order it took them. The screen
    #: needs it to report on the run as a whole once it settles.
    job_ids: list[str] = field(default_factory=list)
    #: One entry per delivered resolution, for the spreadsheet that is left in
    #: the destination folder. Kept whole -- unlike `deliveries`, which is a
    #: window for the live view -- because the sheet has to list every file.
    manifest: list[dict] = field(default_factory=list)

    discovered: int = 0
    processed: int = 0
    #: Net weight of everything taken from the folder so far.
    bytes_total: int = 0
    #: Pages read across the run. Carried here because the report is read long
    #: after the jobs have left the registry, and a report that falls back to
    #: zero is worse than no report: it states something untrue.
    pages_total: int = 0
    failed: int = 0
    delivered: int = 0
    resolutions: int = 0
    deliveries: list[Delivery] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.state in (RunState.SCANNING, RunState.PROCESSING, RunState.WATCHING)

    def record(self, delivery: Delivery) -> None:
        self.deliveries.append(delivery)
        if len(self.deliveries) > DELIVERY_WINDOW:
            del self.deliveries[: len(self.deliveries) - DELIVERY_WINDOW]
        self.delivered += 1

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "folder_run",
            "id": self.id,
            "source": str(self.source),
            "destination": str(self.destination),
            "disposition": str(self.disposition),
            "watch": self.watch,
            "operator": self.operator,
            "state": str(self.state),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "queue": list(self.queue),
            "current": self.current,
            "current_job_id": self.current_job_id,
            "job_ids": list(self.job_ids),
            "discovered": self.discovered,
            "processed": self.processed,
            "bytes_total": self.bytes_total,
            "pages_total": self.pages_total,
            "failed": self.failed,
            "delivered": self.delivered,
            "resolutions": self.resolutions,
            # Newest first: the live view reads from the top.
            "deliveries": [item.as_dict() for item in reversed(self.deliveries)],
        }


#: Every quote character a pasted path realistically arrives wrapped in. The
#: curly ones come from paths that passed through Word, Outlook or a chat app,
#: which substitute them silently.
_QUOTES = "\"'“”‘’«»"


def clean_path(raw: str) -> str:
    """Take a path the way a person actually supplies one.

    Windows Explorer's "Copy as path" -- the normal way anybody gets a path onto
    the clipboard -- wraps it in double quotes. Pasted straight in, those quotes
    become part of the folder name and the folder "does not exist", which is a
    baffling thing to be told about a folder you are looking at.

    So the quotes come off, and so does surrounding whitespace, and so do the
    curly quotes a path picks up passing through a chat window. This is not
    leniency for its own sake: it is refusing to make somebody debug a clipboard.
    """
    value = (raw or "").strip()
    while len(value) >= 2 and value[0] in _QUOTES and value[-1] in _QUOTES:
        value = value[1:-1].strip()
    return value


def validate_folders(source: str, destination: str) -> tuple[Path, Path]:
    """Resolve and check both folders before a single file is touched.

    The containment check is the important one. If the destination sits inside
    the source, every delivered resolution is a new PDF in the folder being
    watched, and the run feeds on its own output forever.
    """
    source = clean_path(source)
    destination = clean_path(destination)
    if not source or not destination:
        raise FolderError("Indique la carpeta de origen y la de destino")

    origin = Path(source).expanduser()
    target = Path(destination).expanduser()

    try:
        origin = origin.resolve(strict=True)
    except (OSError, FileNotFoundError):
        raise FolderError(f"La carpeta de origen no existe: {source}") from None
    if not origin.is_dir():
        raise FolderError(f"El origen no es una carpeta: {origin}")

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise FolderError(f"No se pudo crear la carpeta de destino: {error}") from None
    target = target.resolve()

    if target == origin:
        raise FolderError("El destino no puede ser la misma carpeta que el origen")
    if origin in target.parents:
        raise FolderError(
            "El destino no puede estar dentro del origen: los PDF generados se "
            "volverían a procesar"
        )
    return origin, target


def unique_path(directory: Path, name: str) -> Path:
    """A free path in ``directory``, never overwriting what is already there.

    Two source documents can legitimately produce the same resolution number,
    and silently overwriting one with the other loses a file nobody asked to
    lose.
    """
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(2, 1000):
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem} ({uuid4().hex[:8]}){suffix}"


class FolderRunner:
    """Drains a local folder one document at a time.

    Sequential on purpose. The pool exists for a fifty-file drop where the
    operator wants throughput; a watched folder is a background service, and
    taking one document at a time keeps the machine responsive for whatever the
    operator is doing in the foreground -- and makes "which file is it on" a
    question with exactly one answer.
    """

    def __init__(
        self,
        registry: JobRegistry,
        settings: Settings,
        run_job: Callable[[Job], Awaitable[None]],
        *,
        watch_interval: float = WATCH_INTERVAL,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._run_job = run_job
        self._watch_interval = watch_interval
        self._runs: dict[str, FolderRun] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    # -- lifecycle ------------------------------------------------------------

    def start(
        self,
        source: str,
        destination: str,
        *,
        disposition: SourceDisposition = SourceDisposition.LEAVE,
        watch: bool = False,
        operator: str | None = None,
    ) -> FolderRun:
        origin, target = validate_folders(source, destination)

        for existing in self._runs.values():
            if existing.active and existing.source == origin:
                raise FolderError(f"Esa carpeta ya se está procesando: {origin}")

        run = FolderRun(
            id=uuid4().hex,
            source=origin,
            destination=target,
            disposition=disposition,
            watch=watch,
            operator=operator,
        )
        self._runs[run.id] = run
        self._tasks[run.id] = asyncio.create_task(self._drain(run))
        self._publish(run)
        return run

    def stop(self, run_id: str) -> FolderRun | None:
        run = self._runs.get(run_id)
        if run is None or not run.active:
            return None
        task = self._tasks.get(run_id)
        if task is not None:
            task.cancel()
        # The document in flight is not abandoned: cancellation lands between
        # documents, so whatever is open finishes and is delivered.
        run.state = RunState.STOPPED
        run.finished_at = _now()
        run.current = None
        self._write_manifest(run)
        self._publish(run)
        return run

    def get(self, run_id: str) -> FolderRun | None:
        return self._runs.get(run_id)

    def list(self) -> list[FolderRun]:
        return sorted(self._runs.values(), key=lambda run: run.started_at, reverse=True)

    @property
    def busy(self) -> bool:
        return any(run.active for run in self._runs.values())

    # -- the loop -------------------------------------------------------------

    async def _drain(self, run: FolderRun) -> None:
        try:
            while True:
                pending = self._discover(run)
                if pending:
                    run.state = RunState.PROCESSING
                    run.queue = [path.name for path in pending]
                    self._publish(run)
                    for path in pending:
                        await self._consume(run, path)
                elif run.watch:
                    # A watching run never "finishes", so the sheet is refreshed
                    # each time the folder empties: otherwise the destination
                    # would hold PDFs with no inventory until somebody stopped it.
                    self._write_manifest(run)
                    run.state = RunState.WATCHING
                    run.queue = []
                    run.current = None
                    self._publish(run)
                    await asyncio.sleep(self._watch_interval)
                    continue
                else:
                    break

                if not run.watch:
                    break

            run.state = RunState.DONE
            run.finished_at = _now()
            run.current = None
            run.queue = []
            self._write_manifest(run)
            self._publish(run)
        except asyncio.CancelledError:
            # stop() already recorded the state; do not overwrite it.
            raise
        except Exception as error:  # noqa: BLE001 - surfaced to the operator
            logger.exception("folder run %s failed", run.id)
            run.state = RunState.FAILED
            run.error = f"{type(error).__name__}: {error}"
            run.finished_at = _now()
            self._publish(run)

    def _discover(self, run: FolderRun) -> list[Path]:
        """PDFs in the source folder that have not been taken yet, in name order."""
        try:
            entries = sorted(run.source.iterdir(), key=lambda path: path.name.lower())
        except OSError as error:
            raise FolderError(f"No se pudo leer la carpeta de origen: {error}") from None

        pending: list[Path] = []
        for path in entries:
            if path.name == CONSUMED_DIR or not path.is_file():
                continue
            if path.suffix.lower() != ".pdf":
                continue
            key = str(path)
            if key in run.seen:
                continue
            pending.append(path)

        run.discovered += len(pending)
        return pending

    async def _consume(self, run: FolderRun, path: Path) -> None:
        run.seen.add(str(path))
        run.current = path.name
        run.queue = [name for name in run.queue if name != path.name]
        self._publish(run)

        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        job = self._registry.create(
            filename=path.name,
            source=path,
            owns_source=False,
            size=size,
            operator=run.operator,
        )
        run.current_job_id = job.id
        run.job_ids.append(job.id)
        self._registry.publish(job)
        self._publish(run)

        await self._run_job(job)

        run.bytes_total += job.bytes
        run.pages_total += job.progress.page_count
        if job.state is JobState.DONE:
            run.processed += 1
            run.resolutions += len(((job.report or {}).get("groups")) or [])
            await asyncio.to_thread(self._deliver, run, job, path)
            self._dispose(run, path)
        else:
            run.failed += 1

        run.current = None
        run.current_job_id = None
        self._publish(run)

    def _deliver(self, run: FolderRun, job: Job, origin: Path) -> None:
        """Copy this document's resolutions into the destination folder.

        Copy, not move: the job's own output directory is what the inventory
        links at, and it is the janitor's business to reclaim, not this one's.
        The document's own spreadsheet travels with its PDFs, because whoever
        receives the folder needs to know what arrived without opening the app.
        """
        produced = self._settings.output_dir / job.id
        try:
            files = sorted(produced.glob("*.pdf"))
        except OSError:
            files = []

        self._record(run, job, origin)
        self._write_sheet(run, job)

        for source_file in files:
            name = source_file.name
            if name.startswith("_"):
                # Quarantine ships under the document it came from, or every
                # source in the folder would deliver a file called the same.
                name = f"{origin.stem}{name}"
            try:
                target = unique_path(run.destination, name)
                shutil.copy2(source_file, target)
            except OSError as error:
                logger.warning("could not deliver %s: %s", source_file.name, error)
                continue
            run.record(
                Delivery(
                    file_name=target.name,
                    source_document=origin.name,
                    destination=str(run.destination),
                )
            )
            self._publish(run)

    def _write_sheet(self, run: FolderRun, job: Job) -> None:
        """Write this document's delivery note into the destination folder.

        Written here rather than copied from the output directory, because the
        copy made at processing time cannot know where the PDFs were going -- it
        would arrive in the destination saying the document was never delivered
        to a folder, next to the folder it was delivered to.
        """
        if not job.report:
            return
        try:
            from ..adapters.excel_inventory import ExcelInventory
        except ImportError:
            return
        try:
            ExcelInventory().write(
                job.report,
                run.destination,
                delivered_to=str(run.destination),
                operator=run.operator,
                processed_at=job.finished_at,
            )
        except Exception:  # noqa: BLE001 - the PDFs are already delivered
            logger.warning("could not write the sheet for %s", job.filename, exc_info=True)

    @staticmethod
    def _record(run: FolderRun, job: Job, origin: Path) -> None:
        """Add this document's resolutions to the run's manifest."""
        inventory = ((job.report or {}).get("inventory")) or {}
        for item in inventory.get("items") or []:
            run.manifest.append({**item, "source_document": origin.name})

    def _write_manifest(self, run: FolderRun) -> None:
        """Leave one spreadsheet in the destination covering the whole delivery.

        Somebody receiving six hundred PDFs needs one page saying what arrived
        and where each file came from. The per-document sheets answer that
        document by document; this answers it for the delivery.
        """
        if not run.manifest:
            return
        try:
            from ..adapters.excel_inventory import ExcelRunInventory
        except ImportError:
            return
        try:
            ExcelRunInventory().write(
                run.manifest,
                run.destination,
                source=str(run.source),
                operator=run.operator,
                started_at=run.started_at,
                finished_at=run.finished_at or _now(),
            )
        except Exception:  # noqa: BLE001 - the delivery already happened
            logger.warning("could not write the run inventory", exc_info=True)

    def _dispose(self, run: FolderRun, path: Path) -> None:
        """Leave, move aside, or delete the original, as the operator chose."""
        if run.disposition is SourceDisposition.LEAVE:
            return
        try:
            if run.disposition is SourceDisposition.DELETE:
                path.unlink(missing_ok=True)
                return
            consumed = run.source / CONSUMED_DIR
            consumed.mkdir(exist_ok=True)
            shutil.move(str(path), str(unique_path(consumed, path.name)))
        except OSError as error:
            # Failing to tidy up is never a reason to lose the split that
            # already succeeded.
            logger.warning("could not dispose of %s: %s", path.name, error)

    def _publish(self, run: FolderRun) -> None:
        try:
            self._registry.announce(run.as_dict())
        except Exception:  # noqa: BLE001 - telemetry never breaks the work
            logger.debug("could not publish folder run state", exc_info=True)
