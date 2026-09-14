from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from itertools import count
from pathlib import Path
from uuid import uuid4

#: Creation order, monotonic and collision-free. Wall-clock timestamps tie when
#: fifty files are queued in the same millisecond, and a tie makes the list order
#: arbitrary — which reads as a bug to whoever is watching the screen.
_sequence = count()


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    #: Detenido entre una página y la siguiente, esperando que lo reanuden. El
    #: worker sigue vivo y con el documento abierto: por eso reanudar continúa
    #: en vez de empezar de nuevo.
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    #: El operador decidió no terminarlo. No es un fallo, y por eso se distingue
    #: de uno: un lote con documentos cancelados no está roto.
    CANCELLED = "cancelled"


#: Estados en los que el trabajo todavía ocupa un sitio en la cola.
IN_FLIGHT = (JobState.QUEUED, JobState.RUNNING, JobState.PAUSED)


#: One character per page, so a 400-page ribbon travels as a 400-byte string
#: instead of an array of objects. At 50 concurrent documents that difference is
#: the whole reason the live view stays cheap.
PENDING_MARK = "."
PROVENANCE_MARKS = {
    "text_layer": "t",
    "ocr_region": "h",
    "ocr_full_page": "f",
    "vision_model": "v",
    "none": "x",
}
FAILED_MARK = "x"

#: Cuántos motivos de revisión se conservan por documento. Un libro de
#: cuatrocientos folios levanta unas decenas; el tope está para que un documento
#: roto no convierta el estado del trabajo en un volcado de texto que viaja
#: entero en cada sondeo de la pantalla.
MAX_REVIEW_REASONS = 500

#: Etapas que llevan su propio contador y su propio reloj. Todas tardan lo
#: bastante como para que callarse durante ellas parezca un cuelgue.
STAGES_WITH_PROGRESS = frozenset(
    {"identifying", "verifying", "grouping", "assembling", "inventorying", "delivering"}
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class JobProgress:
    """Live state of one document, rebuilt from the worker's event stream."""

    stage: str = "queued"
    page_count: int = 0
    pages_done: int = 0
    failed_pages: int = 0
    by_provenance: dict[str, int] = field(default_factory=dict)
    #: Por qué hay que mirar cada página marcada, por número de página. Sin
    #: esto la pantalla sólo puede decir que algo pasa, y el operador tiene que
    #: abrir el documento para averiguar qué.
    review: dict[int, str] = field(default_factory=dict)
    marks: list[str] = field(default_factory=list)
    started_monotonic: float | None = None
    #: Cuándo dejó de correr. Mientras es None el reloj sigue andando; en cuanto
    #: se fija, el tiempo transcurrido queda congelado en su valor final.
    finished_monotonic: float | None = None

    #: Qué está haciendo ahora mismo, en palabras, y cuánto lleva de ello. Sin
    #: esto la pantalla sólo puede nombrar la etapa, y "Escribiendo los PDF"
    #: dice exactamente lo mismo en el archivo 1 que en el 287.
    detail: str | None = None
    stage_done: int = 0
    stage_total: int = 0
    stage_started_monotonic: float | None = None
    #: Cuándo llegó la última noticia. Es lo que permite decir "sin novedades
    #: desde hace 8 s" en vez de callar, que es la diferencia entre un sistema
    #: que tarda y uno que parece colgado.
    last_event_monotonic: float | None = None

    @property
    def elapsed_seconds(self) -> float:
        """Cuánto lleva el trabajo, ahora mismo.

        Se calcula al preguntar y no al recibir un evento. Antes se actualizaba
        dentro de ``_tick``, así que durante cualquier fase que no emitiera
        eventos -- escribir 287 PDF, por ejemplo -- el reloj de la pantalla se
        quedaba clavado en la misma cifra. El trabajo seguía; lo que se había
        parado era el cronómetro.
        """
        if self.started_monotonic is None:
            return 0.0
        final = self.finished_monotonic
        return (final if final is not None else time.monotonic()) - self.started_monotonic

    @property
    def stage_elapsed_seconds(self) -> float:
        """Cuánto lleva en la etapa actual. Es la cifra que explica una espera."""
        if self.stage_started_monotonic is None:
            return 0.0
        final = self.finished_monotonic
        return (final if final is not None else time.monotonic()) - self.stage_started_monotonic

    @property
    def silent_seconds(self) -> float:
        """Cuánto hace que no llega una noticia del worker."""
        if self.last_event_monotonic is None or self.finished_monotonic is not None:
            return 0.0
        return time.monotonic() - self.last_event_monotonic

    @property
    def pages_per_second(self) -> float:
        elapsed = self.elapsed_seconds
        if not elapsed or not self.pages_done:
            return 0.0
        return self.pages_done / elapsed

    @property
    def percent(self) -> float:
        if not self.page_count:
            return 0.0
        return min(100.0, 100.0 * self.pages_done / self.page_count)

    def apply(self, event: dict) -> None:
        stage = str(event.get("stage") or "")
        self.last_event_monotonic = time.monotonic()

        if stage == "opened":
            self.page_count = int(event.get("page_count") or 0)
            self.marks = [PENDING_MARK] * self.page_count
            self.started_monotonic = time.monotonic()
            self._enter("analysing", detail=None, total=self.page_count)
            return

        if stage == "page":
            page_number = int(event.get("page_number") or 0)
            failed = bool(event.get("failed"))
            provenance = str(event.get("provenance") or "none")
            mark = FAILED_MARK if failed else PROVENANCE_MARKS.get(provenance, PENDING_MARK)
            self._note_review(page_number, failed, event.get("detail"))

            if 1 <= page_number <= len(self.marks):
                previous = self.marks[page_number - 1]
                self.marks[page_number - 1] = mark
                # The vision rung revisits a page already counted during
                # analysis, so it repaints the mark without double counting.
                if previous != PENDING_MARK:
                    self._recount(previous, mark, failed)
                    return

            self.pages_done += 1
            self.by_provenance[provenance] = self.by_provenance.get(provenance, 0) + 1
            if failed:
                self.failed_pages += 1
            if self.stage != "analysing":
                # Una página después de una etapa posterior: el trabajo volvió a
                # leer -- lo hace el peldaño del modelo -- y la pantalla tiene
                # que decir eso, no seguir anunciando la etapa que ya pasó.
                self._enter("analysing", detail=None, total=self.page_count)
            self.stage_done = self.pages_done
            self.stage_total = self.page_count
            return

        if stage in STAGES_WITH_PROGRESS:
            hecho = event.get("done")
            total = event.get("total")
            detalle = event.get("detail")
            if stage == self.stage:
                # Avance dentro de la etapa en curso: su reloj no se reinicia.
                if hecho is not None:
                    self.stage_done = int(hecho)
                if total is not None:
                    self.stage_total = int(total)
                if detalle is not None:
                    self.detail = str(detalle)
                return
            self._enter(
                stage,
                detail=str(detalle) if detalle else None,
                done=int(hecho) if hecho is not None else 0,
                total=int(total) if total is not None else int(event.get("page_count") or 0),
            )
            return

        if stage in {"done", "failed"}:
            self.finished_monotonic = time.monotonic()
            self.stage = stage
            self.detail = None

    def _recount(self, previous_mark: str, mark: str, failed: bool) -> None:
        for name, char in PROVENANCE_MARKS.items():
            if char == previous_mark:
                self.by_provenance[name] = max(0, self.by_provenance.get(name, 0) - 1)
                break
        for name, char in PROVENANCE_MARKS.items():
            if char == mark:
                self.by_provenance[name] = self.by_provenance.get(name, 0) + 1
                break
        if failed:
            self.failed_pages += 1

    def _note_review(self, page_number: int, failed: bool, detail: object) -> None:
        """Guarda el motivo de una página marcada, y lo retira si deja de estarlo.

        Retirarlo importa tanto como guardarlo: una página que el modelo vuelve
        a leer y resuelve dejaría si no un motivo colgado, y la pantalla seguiría
        pidiendo que se revise algo que ya está bien.
        """
        if not page_number:
            return
        if not failed:
            self.review.pop(page_number, None)
            return
        if detail and len(self.review) < MAX_REVIEW_REASONS:
            self.review[page_number] = str(detail)

    def _enter(self, stage: str, *, detail: str | None, done: int = 0, total: int = 0) -> None:
        """Empezar una etapa: su nombre, su reloj propio y su contador a cero."""
        self.stage = stage
        self.detail = detail
        self.stage_done = done
        self.stage_total = total
        self.stage_started_monotonic = time.monotonic()

    def as_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "page_count": self.page_count,
            "pages_done": self.pages_done,
            "failed_pages": self.failed_pages,
            "by_provenance": dict(self.by_provenance),
            "review": {str(page): motivo for page, motivo in sorted(self.review.items())},
            "ribbon": "".join(self.marks),
            "percent": round(self.percent, 2),
            "pages_per_second": round(self.pages_per_second, 2),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "detail": self.detail,
            "stage_done": self.stage_done,
            "stage_total": self.stage_total,
            "stage_elapsed_seconds": round(self.stage_elapsed_seconds, 2),
            "silent_seconds": round(self.silent_seconds, 2),
        }


@dataclass(slots=True)
class Job:
    id: str
    filename: str
    source: Path
    batch_id: str | None = None
    #: Whether the API owns the file at ``source`` and may delete it when the
    #: job ends. True for uploads, which live in the upload directory. False for
    #: a document taken from a folder the operator gave us: that file is theirs.
    owns_source: bool = True
    #: Size of the source PDF. Recorded at intake because the file is deleted
    #: when the job ends, and "how much did this batch weigh" is a question the
    #: operator asks afterwards.
    bytes: int = 0
    #: Who was at the console. There is no password behind this name, so it is
    #: attribution and never authorisation -- useful for "who ran this", worth
    #: nothing as a control, and the screens say so.
    operator: str | None = None
    #: Qué se le pidió hacer con el documento: partirlo o sólo inventariarlo.
    #: Se decide al cargarlo y viaja con el trabajo hasta el worker.
    task: str = "split"
    #: A qué modelo se le pidió juzgar los bordes dudosos. "auto" es la
    #: cascada de siempre. Se guarda en el trabajo y no sólo en los ajustes
    #: porque dos cajas de la misma corrida pueden haberse decidido con
    #: modelos distintos, y el informe tiene que poder decir con cuál.
    oracle: str = "auto"
    #: La carpeta a la que se entregará lo que produzca, cuando el trabajo
    #: viene de una corrida sobre carpeta local. Se guarda al crearlo porque la
    #: planilla del inventario se escribe dentro del worker, que no conoce la
    #: corrida: sin esto, su columna "Carpeta de destino" salía vacía justo en
    #: el único caso en que hay un destino que declarar.
    destination: str | None = None
    state: JobState = JobState.QUEUED
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    report: dict | None = None
    progress: JobProgress = field(default_factory=JobProgress)
    sequence: int = field(default_factory=lambda: next(_sequence))

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "job",
            "id": self.id,
            "batch_id": self.batch_id,
            "filename": self.filename,
            "bytes": self.bytes,
            "operator": self.operator,
            "task": self.task,
            "oracle": self.oracle,
            "state": str(self.state),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "report": self.report,
            "progress": self.progress.as_dict(),
        }


@dataclass(slots=True)
class Batch:
    id: str
    name: str
    created_at: str = field(default_factory=_now)
    job_ids: list[str] = field(default_factory=list)
    sequence: int = field(default_factory=lambda: next(_sequence))


class JobRegistry:
    """Jobs, batches, live progress, and a fan-out channel for the UI.

    In memory on purpose for the demo. The surface is small enough that moving it
    to Postgres or Redis touches this file and nothing else.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._batches: dict[str, Batch] = {}
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self._dirty: set[str] = set()
        #: Bumped whenever a job appears, finishes or is removed. The idle
        #: janitor compares this against what it last swept, so a system at rest
        #: costs one integer comparison instead of a directory listing.
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    def snapshot(self) -> list[Job]:
        """Every job as it stands right now, in no particular order."""
        return list(self._jobs.values())

    # -- batches --------------------------------------------------------------

    def create_batch(self, name: str) -> Batch:
        batch = Batch(id=uuid4().hex, name=name or "Lote sin nombre")
        self._batches[batch.id] = batch
        return batch

    def get_batch(self, batch_id: str) -> Batch | None:
        return self._batches.get(batch_id)

    def list_batches(self) -> list[Batch]:
        return sorted(self._batches.values(), key=lambda batch: batch.sequence, reverse=True)

    def batch_summary(self, batch: Batch) -> dict[str, object]:
        jobs = [self._jobs[job_id] for job_id in batch.job_ids if job_id in self._jobs]
        states = [job.state for job in jobs]
        pages_total = sum(job.progress.page_count for job in jobs)
        pages_done = sum(job.progress.pages_done for job in jobs)
        bytes_total = sum(job.bytes for job in jobs)
        resolutions = sum(
            len(job.report["groups"]) for job in jobs if job.report and "groups" in job.report
        )
        review = sum(
            len(job.report["review_queue"]) for job in jobs if job.report and "review_queue" in job.report
        )
        return {
            "id": batch.id,
            "name": batch.name,
            "created_at": batch.created_at,
            "documents": len(jobs),
            "done": states.count(JobState.DONE),
            "failed": states.count(JobState.FAILED),
            "running": states.count(JobState.RUNNING),
            "paused": states.count(JobState.PAUSED),
            "cancelled": states.count(JobState.CANCELLED),
            "queued": states.count(JobState.QUEUED),
            "pages_total": pages_total,
            "pages_done": pages_done,
            "bytes_total": bytes_total,
            "percent": round(100.0 * pages_done / pages_total, 2) if pages_total else 0.0,
            "resolutions": resolutions,
            "review_items": review,
            "job_ids": list(batch.job_ids),
        }

    # -- jobs -----------------------------------------------------------------

    def create(
        self,
        filename: str,
        source: Path,
        batch_id: str | None = None,
        owns_source: bool = True,
        size: int = 0,
        operator: str | None = None,
        task: str = "split",
        oracle: str = "auto",
        destination: str | None = None,
    ) -> Job:
        job = Job(
            id=uuid4().hex,
            filename=filename,
            source=source,
            batch_id=batch_id,
            owns_source=owns_source,
            bytes=size,
            operator=operator,
            task=task,
            oracle=oracle,
            destination=destination,
        )
        self._jobs[job.id] = job
        self._revision += 1
        if batch_id and batch_id in self._batches:
            self._batches[batch_id].job_ids.append(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda job: job.sequence, reverse=True)

    @property
    def pending(self) -> int:
        return sum(1 for job in self._jobs.values() if job.state in IN_FLIGHT)

    def mark_running(self, job: Job) -> None:
        job.state = JobState.RUNNING
        self._revision += 1
        job.started_at = _now()
        self.publish(job)

    def mark_done(self, job: Job, report: dict) -> None:
        job.state = JobState.DONE
        self._revision += 1
        job.report = report
        job.finished_at = _now()
        job.progress.stage = "done"
        self.publish(job)

    def mark_failed(self, job: Job, error: str) -> None:
        job.state = JobState.FAILED
        self._revision += 1
        job.error = error
        job.finished_at = _now()
        job.progress.stage = "failed"
        self.publish(job)

    def mark_cancelled(self, job: Job) -> None:
        """El operador lo paró. Se conserva por dónde iba, que es lo útil."""
        job.state = JobState.CANCELLED
        self._revision += 1
        job.finished_at = _now()
        job.progress.stage = "cancelled"
        self.publish(job)

    def mark_paused(self, job: Job) -> None:
        job.state = JobState.PAUSED
        self._revision += 1
        job.progress.stage = "paused"
        self.publish(job)

    def mark_resumed(self, job: Job) -> None:
        job.state = JobState.RUNNING
        self._revision += 1
        job.progress.stage = "analysing" if job.progress.page_count else "queued"
        self.publish(job)

    # -- clearing -------------------------------------------------------------

    def remove(self, job_id: str) -> Job | None:
        """Forget one finished job. A job still in flight is never removed.

        Dropping a running job would leave its worker emitting progress for an
        id nobody owns, and its output directory half written.
        """
        job = self._jobs.get(job_id)
        if job is None or job.state in IN_FLIGHT:
            return None

        del self._jobs[job_id]
        self._dirty.discard(job_id)
        self._revision += 1
        for batch in list(self._batches.values()):
            if job_id in batch.job_ids:
                batch.job_ids.remove(job_id)
            # A batch with nothing left in it is a label with no referent.
            if not batch.job_ids:
                del self._batches[batch.id]

        self.publish_removal(job)
        return job

    def remove_finished(self) -> list[Job]:
        """Forget every job that is done or failed, leaving the queue untouched."""
        finished = [
            job.id
            for job in self._jobs.values()
            if job.state not in IN_FLIGHT
        ]
        return [removed for job_id in finished if (removed := self.remove(job_id))]

    # -- live progress --------------------------------------------------------

    def apply_progress(self, event: dict) -> None:
        """Fold one worker event into its job, and mark the job for the next tick.

        Events are not published one by one: a 400-page document would push 400
        frames at a browser that can only usefully render a handful per second.
        """
        job = self._jobs.get(str(event.get("job_id") or ""))
        if job is None:
            return
        job.progress.apply(event)
        self._dirty.add(job.id)

    def flush(self) -> list[Job]:
        """Return the jobs that changed since the last tick, and clear the flags."""
        changed = [self._jobs[job_id] for job_id in self._dirty if job_id in self._jobs]
        self._dirty.clear()
        for job in changed:
            self.publish(job)
        return changed

    def heartbeat(self) -> list[Job]:
        """Volver a publicar los trabajos en curso aunque nada haya cambiado.

        Publicar sólo lo que cambia es lo correcto mientras hay páginas que
        contar. Deja de serlo en cuanto el trabajo entra en una fase que tarda
        sin producir eventos -- escribir doscientos ochenta y siete PDF, guardar
        una planilla de mil filas -- porque entonces el navegador no recibe
        nada: ni el reloj, que ahora corre solo, ni el "sin novedades desde
        hace tanto". Un latido cuesta una trama por trabajo vivo y es la
        diferencia entre un sistema que tarda y uno que parece colgado.
        """
        alive = [job for job in self._jobs.values() if job.state in IN_FLIGHT]
        for job in alive:
            self.publish(job)
        return alive

    # -- fan-out --------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[dict]:
        # Bounded: a tab that stops reading gets frames dropped rather than
        # growing the server's memory on its behalf.
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(queue)

    def publish(self, job: Job) -> None:
        self._fan_out(job.as_dict())

    def publish_removal(self, job: Job) -> None:
        """Tell every open tab the job is gone, so a second one does not keep it."""
        self._fan_out({**job.as_dict(), "deleted": True})

    def announce(self, payload: dict) -> None:
        """Fan out something that is not a job -- a folder run, for instance.

        Every frame carries a ``kind`` so a client can tell them apart, and the
        stream stays one connection rather than one per kind of thing to watch.
        """
        self._fan_out(payload)

    def _fan_out(self, payload: dict) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass
