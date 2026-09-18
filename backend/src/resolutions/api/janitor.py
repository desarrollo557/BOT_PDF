from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .jobs import JobRegistry, JobState
from .settings import Settings

logger = logging.getLogger(__name__)

def _guarda_un_producto(directorio: Path) -> bool:
    """Si en esta carpeta hay algo que nadie puede volver a generar barriéndola.

    El barrendero decide qué sobra mirando quién referencia cada carpeta: un
    trabajo vivo en memoria, o el libro mayor. Eso vale mientras lo que se
    produce sean PDF, porque los PDF se anotan en el libro mayor y quedan
    referenciados para siempre.

    Un trabajo de inventario no produce PDF: su único producto es el FUID, y el
    FUID no se anota en el libro mayor porque ahí van documentos generados. De
    modo que en cuanto el trabajo salía del registro en memoria -- al reiniciar
    el servicio, sin ir más lejos -- su carpeta quedaba sin nadie que la
    reclamara y se barría con la planilla dentro. El operador procesaba, iba a
    descargar su inventario y se encontraba un 404.

    Esta comprobación es el suelo: cueste lo que cueste el listado, una carpeta
    con un FUID dentro no es espacio que reclamar. El propio barrendero lo dice
    en su descripción -- nada de lo que borra es un producto -- y esto es lo que
    hace que siga siendo verdad.
    """
    # Importado aquí y no arriba porque el paquete del worker arrastra el
    # mundo, y el barrendero arranca con el servicio.
    from .worker import FUID_SUFFIX

    try:
        return any(directorio.glob(f"*{FUID_SUFFIX}"))
    except OSError:  # pragma: no cover - una carpeta ilegible no se toca
        return True


@dataclass(frozen=True, slots=True)
class SweepResult:
    """What one pass reclaimed. Every field is scratch, never a product."""

    uploads: list[Path] = field(default_factory=list)
    outputs: list[Path] = field(default_factory=list)
    ribbons: int = 0

    @property
    def empty(self) -> bool:
        return not self.uploads and not self.outputs and not self.ribbons

    def as_dict(self) -> dict[str, object]:
        return {
            "uploads": len(self.uploads),
            "outputs": len(self.outputs),
            "ribbons": self.ribbons,
        }


class IdleJanitor:
    """Reclaims scratch space, but only while there is nothing to interrupt.

    Three things accumulate during a run and are worthless once it ends: an
    uploaded source whose job is gone, an output directory nothing references any
    more, and the per-page ribbon of a document whose report already says
    everything the ribbon said. None of them is a product. The generated
    resolution PDFs and the inventory ledger are never touched.

    Two guards keep the idle case free. The sweep is skipped unless the queue is
    empty -- reclaiming disk under a running worker is how a half-written output
    directory disappears -- and skipped again unless the registry has changed
    since the last pass. A system at rest therefore costs one integer comparison
    per tick and not a single filesystem call.
    """

    def __init__(
        self,
        registry: JobRegistry,
        settings: Settings,
        referenced: object | None = None,
    ) -> None:
        self._registry = registry
        self._settings = settings
        #: Anything else still pointing at an output directory -- the ledger, in
        #: practice. Kept as a callable so the janitor never caches a stale set.
        self._referenced = referenced
        self._swept_revision: int | None = None
        self.last: SweepResult | None = None

    # -- the loop -------------------------------------------------------------

    async def run(self) -> None:
        """Tick forever. Never lets a sweep failure kill the ticker."""
        while True:
            await asyncio.sleep(self._settings.sweep_seconds)
            try:
                await self.sweep_if_idle()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - housekeeping is never fatal
                logger.debug("idle sweep failed", exc_info=True)

    async def sweep_if_idle(self, force: bool = False) -> SweepResult | None:
        """Sweep, or return ``None`` if now is not the time.

        ``force`` skips the "nothing changed" guard for a sweep somebody asked
        for by hand. It never skips the idle guard: reclaiming disk under a
        running worker is how a half-written output directory disappears.
        """
        if self._registry.pending:
            return None
        if not force and not self.should_sweep():
            return None

        # The plan is computed synchronously, so it is atomic against anything
        # else on the loop: a clear that lands mid-sweep can only add orphans,
        # never take back one already listed. The deletions then go to a thread,
        # because rmtree over a large output directory would stall the stream.
        plan = self.plan()
        self._swept_revision = self._registry.revision
        if plan.empty:
            return plan

        await asyncio.to_thread(self._apply, plan)
        self.last = plan
        logger.info("idle sweep reclaimed %s", plan.as_dict())
        return plan

    def should_sweep(self) -> bool:
        if self._registry.pending:
            # Something is queued or running. Its uploads and outputs are live.
            return False
        return self._swept_revision != self._registry.revision

    # -- the work -------------------------------------------------------------

    def plan(self) -> SweepResult:
        live_jobs = self._registry.snapshot()
        known_ids = {job.id for job in live_jobs}
        known_sources = {job.source.name for job in live_jobs}
        referenced_ids = known_ids | self._referenced_ids()

        return SweepResult(
            uploads=self._orphaned(self._settings.upload_dir, known_sources, files=True),
            outputs=self._orphaned(self._settings.output_dir, referenced_ids, files=False),
            ribbons=self._compact_ribbons(live_jobs),
        )

    def _referenced_ids(self) -> set[str]:
        if self._referenced is None:
            return set()
        try:
            return set(self._referenced())  # type: ignore[operator]
        except Exception:  # noqa: BLE001 - a broken index must not delete output
            logger.warning("could not read the output references; sweeping nothing")
            raise

    @staticmethod
    def _orphaned(directory: Path, keep: set[str], *, files: bool) -> list[Path]:
        try:
            entries = list(directory.iterdir())
        except OSError:
            return []
        sobran = []
        for entry in entries:
            if not (entry.is_file() if files else entry.is_dir()):
                continue
            if entry.name in keep:
                continue
            # Una carpeta de salida con un FUID dentro no es espacio que
            # reclamar aunque nadie la referencie: es el producto de un trabajo
            # de inventario, que no deja rastro en el libro mayor.
            if not files and _guarda_un_producto(entry):
                continue
            sobran.append(entry)
        return sobran

    @staticmethod
    def _compact_ribbons(jobs: list) -> int:
        """Drop the per-page marks of finished documents.

        A 400-page ribbon is a 400-entry list held for the life of the process,
        and once the job is done its report carries everything the ribbon showed.
        The live view only ever draws the ribbon of a running document.
        """
        compacted = 0
        for job in jobs:
            if job.state in (JobState.DONE, JobState.FAILED) and job.progress.marks:
                job.progress.marks = []
                compacted += 1
        return compacted

    def _apply(self, plan: SweepResult) -> None:
        for path in plan.uploads:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.debug("could not remove upload %s", path, exc_info=True)
        for path in plan.outputs:
            shutil.rmtree(path, ignore_errors=True)
