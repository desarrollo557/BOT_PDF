from __future__ import annotations

import asyncio
import logging
import shutil
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from ..adapters.excel_inventory import NOMBRE_DEL_INVENTARIO_DE_PROCESOS
from .errores import explicar_fallo
from .jobs import Job, JobRegistry, JobState
from .planificador import Planificador
from .settings import Settings

logger = logging.getLogger(__name__)

#: Deliveries kept for the live view. It is a window on a running job, not a
#: record -- the inventory is the record -- so it never grows without bound.
DELIVERY_WINDOW = 60

#: How often a watching run looks for new files. Long enough that an idle folder
#: costs one directory listing a few times a minute.
WATCH_INTERVAL = 5.0

#: Cada cuánto, como mucho, se reescribe el Excel general mientras la carpeta
#: corre. Con 2.600 filas cuesta doce segundos, y reescribirlo tras cada PDF
#: sumaba seis minutos a una corrida de 41. El de la subcarpeta del PDF que
#: acaba de terminar sí se escribe siempre, y al terminar, detener o vaciarse
#: una carpeta vigilada se escriben todos.
INVENTARIO_GENERAL_CADA = 45.0


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


#: Cuánta cola viaja a la pantalla en cada aviso. La pantalla enseña cuarenta
#: nombres y un "y N más", así que mandar los catorce mil de una carpeta real es
#: pagar 423 KB por aviso -- y hay un aviso por documento consumido -- para que
#: el navegador tire 14.263 de ellos. El total va aparte, en `queued`, que es lo
#: único que la vista necesita de los que no enseña.
QUEUE_PREVIEW = 40

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
    #: Qué hacer con cada documento de la carpeta. Es la misma decisión que se
    #: toma al subir un archivo a mano, y viaja igual: hasta ahora una carpeta
    #: sólo sabía dividir, así que un libro de diplomas tomado de una carpeta
    #: nunca podía dejar su inventario.
    task: str = "split"
    oracle: str = "auto"
    #: Con qué leer el papel de esta carpeta. Una corrida entera comparte motor
    #: porque una carpeta suele ser un mismo tipo de material: la caja de libros
    #: manuscritos se lee con ayuda y la de expedientes mecanografiados no la
    #: necesita.
    lectura: str = "local"
    #: Con qué señal se parte cada libro de diplomas de esta carpeta. Una
    #: estantería suele ser homogénea, así que declararlo una vez vale para
    #: todos sus archivos.
    corte: str = "pagina"
    #: Qué se entrega como un archivo en una caja de correspondencia. Se fija
    #: para la corrida entera y se copia a cada archivo que entre, igual que el
    #: corte.
    agrupar: str = "documento"
    #: La territorial de las cajas de correspondencia de esta carpeta, para el
    #: encabezado de su Índice Electrónico. Se copia a cada archivo que entre.
    territorial: str | None = None
    #: Y qué clase de documento trae esta carpeta, cuando el operador lo sabe.
    #: Una carpeta suele ser homogénea -- una estantería de libros de diplomas
    #: --, así que declararlo una vez vale para todos sus archivos.
    tipo: str = "auto"
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
    #: Los que se están procesando ahora, por su trabajo y su ruta. Varios a la
    #: vez: la carpeta toma tantos como ranuras le deje el planificador.
    en_curso: dict[str, str] = field(default_factory=dict)
    #: Every document this run created, in the order it took them. The screen
    #: needs it to report on the run as a whole once it settles.
    job_ids: list[str] = field(default_factory=list)
    #: One entry per delivered resolution, for the spreadsheet that is left in
    #: the destination folder. Kept whole -- unlike `deliveries`, which is a
    #: window for the live view -- because the sheet has to list every file.
    manifest: list[dict] = field(default_factory=list)
    #: La fila de cada acta de consejo inventariada, en el orden en que se
    #: tomaron. Con ellas se escribe **un** Excel para la carpeta entera, que
    #: es lo que se entrega: una carpeta de cien actas son cien filas de una
    #: planilla, no cien planillas de una fila.
    inventario_filas: list[dict] = field(default_factory=list)
    #: Dónde quedó ese Excel, cuando ya se escribió.
    inventario: str | None = None
    #: El Excel general de cada clase de acta -- consejo, grado --, para que
    #: cada una vuelva a escribir el suyo y nunca el de la otra.
    inventarios_generales: dict[str, str] = field(default_factory=dict)
    #: Por qué no se pudo escribir, si falló.
    inventario_error: str | None = None
    #: El control de calidad del último inventario escrito: filas completas,
    #: completadas razonando y con algún dato que el papel no deja leer.
    inventario_validacion: dict | None = None
    #: Cuántas filas llevaba la última vez que se escribió, para no reescribirlo
    #: mientras una carpeta vigilada espera sin novedades.
    inventario_escritas: int = 0

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
    #: Cuándo se escribió por última vez el Excel general (reloj monótono).
    inventario_general_en: float = 0.0
    #: Cuándo se escribió por última vez el Índice Electrónico general de la
    #: carpeta, que lee el de cada caja y no se rehace con cada PDF.
    generales_en: float = 0.0
    #: Entregar y escribir los Excel, de uno en uno. Con varios documentos a la
    #: vez, dos entregas simultáneas se pisarían el nombre libre de un archivo
    #: (`unique_path`) y las filas del inventario. Es de hilos y no de asyncio
    #: porque la entrega corre en un hilo, y uno que ya arrancó no se detiene
    #: aunque se cancele quien lo esperaba.
    cerrojo: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def current(self) -> str | None:
        """El primero de los que están en curso, para quien sólo enseña uno."""
        return next(iter(self.en_curso.values()), None)

    @property
    def current_job_id(self) -> str | None:
        return next(iter(self.en_curso), None)

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
            "task": self.task,
            "oracle": self.oracle,
            "lectura": self.lectura,
            "corte": self.corte,
            "agrupar": self.agrupar,
            "territorial": self.territorial,
            "tipo": self.tipo,
            "operator": self.operator,
            "state": str(self.state),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "queue": list(self.queue[:QUEUE_PREVIEW]),
            # Cuántos esperan de verdad, que es lo que la pantalla cuenta.
            "queued": len(self.queue),
            "current": self.current,
            "current_job_id": self.current_job_id,
            # Todos los que corren ahora, en el orden en que se tomaron.
            "en_curso": [
                {"job_id": job_id, "nombre": nombre} for job_id, nombre in self.en_curso.items()
            ],
            "job_ids": list(self.job_ids),
            "discovered": self.discovered,
            "processed": self.processed,
            "bytes_total": self.bytes_total,
            "pages_total": self.pages_total,
            "failed": self.failed,
            "delivered": self.delivered,
            "resolutions": self.resolutions,
            # El Excel de las actas de la carpeta, por su nombre: la ruta
            # completa es del disco del servicio y la pantalla sólo la enseña.
            "inventario": Path(self.inventario).name if self.inventario else None,
            "inventario_ruta": self.inventario,
            "inventario_filas": len(self.inventario_filas),
            "inventario_error": self.inventario_error,
            "inventario_validacion": self.inventario_validacion,
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
    """Drains a local folder, several documents at a time.

    Iba de uno en uno, y una carpeta de 103 PDF tardó 41 minutos con diez de
    los once procesos del pool sin nada que hacer y la red esperando a la IA
    con la CPU ociosa. Ahora cada carpeta pone tantos trabajadores como
    ranuras tiene el planificador, y todos sacan de la misma cola en el orden
    de la carpeta. Las ranuras son del servicio y no de la carpeta: dos
    carpetas en marcha se las reparten por orden de llegada, en vez de doblar
    la carga de la máquina.

    Lo que tiene que ir en fila sigue en fila: la entrega al destino y los
    Excel se hacen de uno en uno bajo el cerrojo de la corrida.
    """

    def __init__(
        self,
        registry: JobRegistry,
        settings: Settings,
        run_job: Callable[[Job], Awaitable[None]],
        *,
        watch_interval: float = WATCH_INTERVAL,
        planificador: Planificador | None = None,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._run_job = run_job
        self._watch_interval = watch_interval
        self._planificador = planificador or Planificador(
            documentos_de_carpeta=settings.folder_documents,
            hilos_por_documento=settings.page_workers,
            procesos=settings.document_workers,
        )
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
        task: str = "split",
        oracle: str = "auto",
        lectura: str = "local",
        corte: str = "pagina",
        tipo: str = "auto",
        agrupar: str = "documento",
        territorial: str | None = None,
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
            task=task,
            oracle=oracle,
            lectura=lectura,
            corte=corte,
            agrupar=agrupar,
            territorial=territorial,
            tipo=tipo,
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
        # Detener es detener ya: cancelar la tarea le llega al documento en
        # curso, que recibe la orden de cancelar y la atiende en décimas (ver
        # `_run`). Antes se lo dejaba terminar, y en un libro de doscientas
        # páginas eso eran minutos leyendo -- y pagando -- para nadie. Lo ya
        # inventariado de la carpeta se escribe igual al salir.
        run.state = RunState.STOPPED
        run.finished_at = _now()
        run.en_curso.clear()
        self._write_manifest(run)
        self._publish(run)
        return run

    def get(self, run_id: str) -> FolderRun | None:
        return self._runs.get(run_id)

    def forget(self, run_id: str) -> FolderRun | None:
        """Quitar de la pantalla una corrida que ya terminó.

        Una corrida en marcha no se olvida: pararla y quitarla son dos
        decisiones distintas, y confundirlas dejaría un trabajo corriendo sin
        nadie que informara de él. Devuelve ``None`` si no existe o si sigue
        activa, y quien llama distingue los dos casos por :meth:`get`.

        Esto vacía una pantalla, no deshace un trabajo: los PDF entregados
        siguen en la carpeta de destino y el archivo conserva sus filas.
        """
        run = self._runs.get(run_id)
        if run is None or run.active:
            return None
        self._tasks.pop(run_id, None)
        return self._runs.pop(run_id, None)

    def forget_finished(self) -> list[FolderRun]:
        """Quitar todas las que ya terminaron, dejando las que siguen vivas."""
        terminadas = [run for run in self._runs.values() if not run.active]
        for run in terminadas:
            self._tasks.pop(run.id, None)
            del self._runs[run.id]
        return terminadas

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
                    run.queue = [str(self._relative(run, path)) for path in pending]
                    self._publish(run)
                    await self._consumir_en_paralelo(run, pending)
                elif run.watch:
                    # A watching run never "finishes", so the sheet is refreshed
                    # each time the folder empties: otherwise the destination
                    # would hold PDFs with no inventory until somebody stopped it.
                    self._write_manifest(run)
                    await asyncio.to_thread(self._escribir_inventario_de_actas, run)
                    run.state = RunState.WATCHING
                    run.queue = []
                    run.en_curso.clear()
                    self._publish(run)
                    await asyncio.sleep(self._watch_interval)
                    continue
                else:
                    break

                if not run.watch:
                    break

            # El Excel antes de dar la carpeta por terminada: la pantalla enseña
            # el botón de descarga en cuanto la ve terminada, y un botón que
            # aparece antes que el archivo es un botón que falla.
            await asyncio.to_thread(self._escribir_inventario_de_actas, run)
            await asyncio.to_thread(self._escribir_generales, run)
            run.state = RunState.DONE
            run.finished_at = _now()
            run.en_curso.clear()
            run.queue = []
            self._write_manifest(run)
            self._publish(run)
        except asyncio.CancelledError:
            # stop() already recorded the state; do not overwrite it. Pero lo
            # inventariado hasta aquí se deja escrito: detener una carpeta de
            # cien actas a la mitad no tiene por qué perder las cincuenta leídas.
            self._escribir_inventario_de_actas(run)
            self._escribir_generales(run)
            self._publish(run)
            raise
        except Exception as error:  # noqa: BLE001 - surfaced to the operator
            logger.exception("folder run %s failed", run.id)
            run.state = RunState.FAILED
            run.error = explicar_fallo(error)
            run.finished_at = _now()
            self._publish(run)

    def _discover(self, run: FolderRun) -> list[Path]:
        """Los PDF del árbol de origen que nadie ha tomado todavía.

        Por todo el árbol y no sólo por la carpeta que se indicó: el archivo se
        entrega en cajas -- una carpeta por expediente, y cien expedientes en la
        ruta que el operador señala -- y pedirle que apunte cien veces, una por
        carpeta, es pedirle que haga a mano lo que la máquina sabe hacer.

        En orden de ruta, no de nombre, que es lo que mantiene juntos los
        documentos de una misma carpeta mientras se procesan.
        """
        try:
            entries = sorted(
                run.source.rglob("*.[pP][dD][fF]"),
                key=lambda path: str(path).lower(),
            )
        except OSError as error:
            raise FolderError(f"No se pudo leer la carpeta de origen: {error}") from None

        pending: list[Path] = []
        for path in entries:
            # `_procesados` a cualquier profundidad: bajo MOVE los originales se
            # apartan ahí, y volver a tomarlos sería procesar dos veces lo mismo.
            if CONSUMED_DIR in path.parts:
                continue
            if not path.is_file():
                continue
            key = str(path)
            if key in run.seen:
                continue
            pending.append(path)

        run.discovered += len(pending)
        return pending

    @staticmethod
    def _relative(run: FolderRun, path: Path) -> Path:
        """La ruta del PDF vista desde la carpeta de origen.

        Es lo que se enseña y lo que se replica en el destino: con cien carpetas
        hay cien archivos que se llaman igual, y "documento.pdf" a secas no dice
        de cuál de ellas salió.
        """
        try:
            return path.relative_to(run.source)
        except ValueError:
            return Path(path.name)

    async def _consumir_en_paralelo(self, run: FolderRun, pendientes: list[Path]) -> None:
        """Los PDF pendientes, repartidos entre varios trabajadores.

        Cada trabajador saca el siguiente de la cola -- en el orden de la
        carpeta -- y espera una ranura libre del planificador antes de
        empezarlo. Cancelar la corrida cancela a los trabajadores, y cada uno
        le pasa la orden a su documento (ver `ejecucion._run`).
        """
        cola = deque(pendientes)
        ranuras = self._planificador.ranuras

        async def trabajador() -> None:
            while cola:
                path = cola.popleft()
                async with ranuras:
                    if not run.active:
                        return
                    await self._consume(run, path)

        cuantos = min(len(cola), self._planificador.documentos_de_carpeta)
        await asyncio.gather(*(trabajador() for _ in range(cuantos)))

    async def _consume(self, run: FolderRun, path: Path) -> None:
        """Un PDF de la carpeta: procesarlo, entregarlo y contarlo.

        Lo que falle aquí -- la entrega, el disco -- cuenta como un documento
        fallido y la carpeta sigue: con varios a la vez, dejar que el error
        subiera tumbaba también a los que estaban leyéndose al lado.
        """
        run.seen.add(str(path))
        relativa = str(self._relative(run, path))
        run.queue = [name for name in run.queue if name != relativa]

        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        job = self._registry.create(
            filename=relativa,
            source=path,
            owns_source=False,
            size=size,
            operator=run.operator,
            task=run.task,
            oracle=run.oracle,
            lectura=run.lectura,
            corte=run.corte,
            agrupar=run.agrupar,
            territorial=run.territorial,
            tipo=run.tipo,
            # Adónde irá lo que produzca. Se calcula antes de procesarlo, con
            # el nombre del origen, y la entrega lo recalcula después con el
            # NIC si el expediente lo trae: lo que va en la planilla es dónde
            # quedará, que es lo que el operador necesita saber.
            destination=str(self._output_dir(run, path)),
            # La carpeta raíz, que es como el operador la reconoce en el
            # Archivo: sin esto cada PDF salía como una carpeta con su propio
            # nombre de archivo.
            origen={
                "id": run.id,
                "nombre": run.source.name or str(run.source),
                "tipo": "carpeta",
                "inventario": str(self._ruta_del_inventario(run)),
                # Y el general del bot, en la raíz del destino: con esta ruta
                # se descarga desde el Archivo aunque la corrida ya no esté.
                "procesos": str(run.destination / NOMBRE_DEL_INVENTARIO_DE_PROCESOS),
            },
        )
        run.en_curso[job.id] = relativa
        run.job_ids.append(job.id)
        self._registry.publish(job)
        self._publish(run)

        try:
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
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - un documento no tumba la carpeta
            logger.exception("no se pudo terminar %s", relativa)
            run.failed += 1
            if job.state is not JobState.FAILED:
                self._registry.mark_failed(job, explicar_fallo(error))
        finally:
            run.en_curso.pop(job.id, None)
            # Los dos inventarios generales de la carpeta, con este PDF ya
            # contado -- también si falló --. El de procesos cada vez, que es
            # barato; el índice de la habilidad cada tanto, que lee el de cada
            # caja, y siempre al terminar.
            ahora = time.monotonic()
            self._escribir_generales(run, con_indice=ahora - run.generales_en >= INVENTARIO_GENERAL_CADA)
            self._publish(run)

    def _escribir_generales(self, run: FolderRun, *, con_indice: bool = True) -> None:
        """Los dos inventarios generales en la raíz del destino.

        Lo pidió el operador: dentro de la carpeta de cada PDF, el inventario de
        su habilidad; en la raíz, dos generales -- el de la habilidad (el Índice
        Electrónico de las cajas de correspondencia, una hoja por PDF) y el del
        bot, una fila por cada PDF procesado --. Que fallen no deshace nada.
        """
        from .indices import inventario_de_procesos, libro_de_indices

        with run.cerrojo:
            trabajos = [t for job_id in run.job_ids if (t := self._registry.get(job_id)) is not None]
            try:
                inventario_de_procesos(
                    trabajos,
                    run.destination,
                    origen=run.source.name or str(run.source),
                    clase_de_origen="Carpeta",
                    operador=run.operator,
                    destino_de=lambda t: self._destino_relativo(run, t),
                )
                if con_indice:
                    run.generales_en = time.monotonic()
                    con_indice_propio = [
                        t.id
                        for t in trabajos
                        if t.state is JobState.DONE and (t.report or {}).get("indice_electronico")
                    ]
                    if con_indice_propio:
                        libro_de_indices(self._settings.output_dir, con_indice_propio, run.destination)
            except Exception:  # noqa: BLE001 - la entrega de cada PDF ya está hecha
                logger.warning("no se pudieron escribir los generales de %s", run.source, exc_info=True)

    @staticmethod
    def _destino_relativo(run: FolderRun, job: Job) -> str:
        """Dónde quedó lo de un PDF, desde la raíz del destino: «108C000033/UPD2326299»."""
        try:
            return str(FolderRunner._output_dir(run, Path(job.source)).relative_to(run.destination))
        except ValueError:
            return str(job.destination or "")

    @staticmethod
    def _output_dir(run: FolderRun, origin: Path, job: Job | None = None) -> Path:
        """Dónde caen los PDF que salen de un documento de origen.

        Una carpeta por documento, dentro de la carpeta de la que salió:

            DESTINO / 108C000094 / 5825181 / 01_DERECHO-DE-PETICION.pdf

        Los dos niveles hacen falta y por motivos distintos. El de la carpeta,
        porque el archivo se entrega en cajas y cincuenta cajas no caben en un
        montón. El del documento, porque dentro de una caja hay doscientos PDF y
        **todos** producen un "01_...": aplanarlos serían ciento noventa y
        nueve "(2)", "(3)", "(4)" hasta el tope de mil, y a partir de ahí
        archivos que se pierden sin decirlo.

        El segundo nivel se llama **como el PDF de origen** -- «UPD2320047» --,
        siempre. Se llamó con el NIC cuando el expediente lo traía, y el
        operador lo corrigió el 2026-10-13: el destino salía mezclado -- unas
        carpetas «UPD…» y otras «1012408» -- y la caja se busca por su UPD, que
        es también el nombre del expediente en su Índice Electrónico.
        """
        relativa = FolderRunner._relative(run, origin)
        return run.destination / relativa.parent / relativa.stem

    def _deliver(self, run: FolderRun, job: Job, origin: Path) -> None:
        """Copy this document's resolutions into the destination folder.

        Copy, not move: the job's own output directory is what the inventory
        links at, and it is the janitor's business to reclaim, not this one's.
        The document's own spreadsheet travels with its PDFs, because whoever
        receives the folder needs to know what arrived without opening the app.
        """
        # Un acta no entrega PDF ni planilla propia: su fila va al Excel de la
        # carpeta, que es lo que se entrega. La planilla de entrega de un
        # documento cuenta las páginas que acabaron en archivos, y de un acta
        # que no se parte diría que se perdieron todas. Se reescribe en cada
        # acta, que cuesta milisegundos, para que el Excel esté siempre al día
        # aunque la corrida se corte.
        with run.cerrojo:
            self._entregar(run, job, origin)

    def _entregar(self, run: FolderRun, job: Job, origin: Path) -> None:
        filas = (job.report or {}).get("inventario_actas") or []
        if filas:
            # La carpeta de cada fila es su ruta desde la raíz elegida: con
            # subcarpetas, «00C003284\UPD3859772» y no sólo «UPD3859772». Es lo
            # que agrupa el Excel de cada subcarpeta y lo que encadena sus folios.
            carpeta = self._carpeta_de(run, origin)
            run.inventario_filas.extend({**fila, "carpeta": carpeta} for fila in filas)
            # Las actas son sus unidades: un libro cuenta tantas como trae.
            run.resolutions += len(filas)
            self._record(run, job, origin)
            self._entregar_actas(run, job, origin)
            # El de su subcarpeta siempre; el general, cada tanto (ver
            # `INVENTARIO_GENERAL_CADA`). Al terminar se escriben todos.
            self._escribir_inventario_de_actas(run, solo_carpeta=carpeta)
            return

        produced = self._settings.output_dir / job.id
        try:
            # Recursivo: los documentos de una caja se escriben en una carpeta
            # con el nombre de la caja, y con `glob` la entrega salía vacía sin
            # decir por qué -- ni un archivo copiado, ni un error que mirar.
            files = sorted(produced.rglob("*.pdf"))
        except OSError:
            files = []

        carpeta = self._output_dir(run, origin, job)
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            logger.warning("no se pudo crear %s: %s", carpeta, error)
            carpeta = run.destination

        self._record(run, job, origin)
        indice = (job.report or {}).get("indice_electronico")
        if indice:
            # Una caja de correspondencia lleva su Índice Electrónico en lugar
            # de la planilla, y viaja tal cual junto a sus PDF: no declara a
            # dónde se entregó, así que no hay nada que reescribir. Se copia
            # aparte y no se anota como entrega, que cuenta documentos.
            try:
                for hoja in sorted(produced.rglob(indice))[:1]:
                    shutil.copy2(hoja, unique_path(carpeta, hoja.name))
            except OSError as error:
                logger.warning("no se pudo entregar el índice de %s: %s", job.filename, error)
        else:
            self._write_sheet(run, job, carpeta)
            # Y la que quedó junto al trabajo, ahora que se sabe dónde acabaron
            # los PDF: es la que baja el botón de la pantalla.
            self._corregir_planilla_del_trabajo(run, job, carpeta)

        for source_file in files:
            name = source_file.name
            if name.startswith("_"):
                # Quarantine ships under the document it came from, or every
                # source in the folder would deliver a file called the same.
                name = f"{origin.stem}{name}"
            try:
                target = unique_path(carpeta, name)
                shutil.copy2(source_file, target)
            except OSError as error:
                logger.warning("could not deliver %s: %s", source_file.name, error)
                continue
            run.record(
                Delivery(
                    file_name=target.name,
                    source_document=str(self._relative(run, origin)),
                    destination=str(carpeta),
                )
            )
            self._publish(run)

    def _write_sheet(
        self,
        run: FolderRun,
        job: Job,
        carpeta: Path | None = None,
        *,
        en: Path | None = None,
    ) -> None:
        """Write this document's delivery note, saying where it was delivered.

        Written here rather than copied from the output directory, because the
        copy made at processing time cannot know where the PDFs were going -- it
        would arrive in the destination saying the document was never delivered
        to a folder, next to the folder it was delivered to.

        ``en`` separa dónde se escribe de qué destino se declara, y hace falta
        por el mismo motivo: la carpeta definitiva lleva el NIC del expediente,
        que no se conoce hasta haber leído el documento. Así la planilla que
        queda junto al trabajo -- la que baja el botón de la pantalla -- se
        puede reescribir después con la carpeta en la que los PDF acabaron de
        verdad, en vez de con la que se supuso antes de empezar.
        """
        if not job.report:
            return
        try:
            from ..adapters.excel_inventory import ExcelInventory
        except ImportError:
            return
        try:
            destino = carpeta or run.destination
            ExcelInventory().write(
                job.report,
                en or destino,
                delivered_to=str(destino),
                operator=run.operator,
                processed_at=job.finished_at,
            )
        except Exception:  # noqa: BLE001 - the PDFs are already delivered
            logger.warning("could not write the sheet for %s", job.filename, exc_info=True)

    def _corregir_planilla_del_trabajo(self, run: FolderRun, job: Job, carpeta: Path) -> None:
        """Reescribe la planilla que quedó junto al trabajo, con el destino real.

        El worker la escribió al terminar, y en ese momento el destino que
        conocía era el que se calculó al crear el trabajo: con el nombre del PDF
        de origen, porque el NIC del expediente todavía no se había leído. La
        entrega sí lo sabe, y es la que puede dejarla diciendo la verdad.

        Se sobrescribe la que hay, en su sitio, para que no queden dos planillas
        del mismo documento discrepando sobre dónde está.
        """
        try:
            from ..adapters.excel_inventory import SUFFIX
        except ImportError:
            return
        produced = self._settings.output_dir / job.id
        try:
            hojas = sorted(produced.rglob(f"*{SUFFIX}"))
        except OSError:
            return
        if hojas:
            self._write_sheet(run, job, carpeta, en=hojas[0].parent)

    @staticmethod
    def _record(run: FolderRun, job: Job, origin: Path) -> None:
        """Add this document's resolutions to the run's manifest.

        Salvo las cajas de correspondencia: su inventario general es el Índice
        Electrónico del cliente, y la planilla genérica de entrega repetía lo
        mismo en otro formato (lo pidió el operador: sólo la plantilla).
        """
        if (job.report or {}).get("indice_electronico"):
            return
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

    @staticmethod
    def _raiz(run: FolderRun) -> str:
        """El nombre de la carpeta elegida como fuente, que abre el espejo en el destino."""
        return run.source.name or "RAIZ"

    def _carpeta_de(self, run: FolderRun, origin: Path) -> str:
        """La carpeta de un PDF vista desde la raíz: «00C003284\\UPD3859772»."""
        return str(Path(self._raiz(run)) / self._relative(run, origin).parent)

    def _espejo(self, run: FolderRun, origin: Path) -> Path:
        """Dónde va en el destino lo de este PDF: la misma ruta que tiene en la fuente.

        ``FUENTE\\00C003284\\UPD3859772\\libro.pdf`` deja lo suyo en
        ``DESTINO\\00C003284\\UPD3859772\\``: el destino es un espejo de la
        fuente, con la carpeta elegida delante y el trabajo hecho dentro.
        """
        return run.destination / self._carpeta_de(run, origin)

    def _entregar_actas(self, run: FolderRun, job: Job, origin: Path) -> None:
        """Deja en la carpeta espejo del destino el resultado de este PDF de actas.

        * Un libro que se dividió: sus actas, en una carpeta con el nombre del
          libro (``UPD3859772\\2N° 002…\\03_ACTA-EXTRAORDINARIA-NO-017….pdf``).
        * Un PDF que ya era un acta, cuando se pidió dividir: el PDF tal cual,
          para que el destino quede completo como la fuente.
        * Si sólo se pidió inventariar, no se copia ningún PDF: el destino lleva
          la misma estructura de carpetas, cada una con su Excel.

        Volver a procesar **reemplaza** lo que había en vez de dejar al lado un
        «(2)», igual que el Excel: el operador espera la sesión con su nombre,
        no dos copias que discrepan.
        """
        from ..application.task import TaskKind

        report = job.report or {}
        espejo = self._espejo(run, origin)
        producido = self._settings.output_dir / job.id
        salidas = report.get("outputs") or []
        if salidas:
            copias = [(producido / salida, espejo / salida) for salida in salidas]
        elif run.task in (str(TaskKind.SPLIT), str(TaskKind.BOTH)):
            copias = [(origin, espejo / origin.name)]
        else:
            return
        for desde, hasta in copias:
            try:
                hasta.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(desde, hasta)
            except OSError as error:
                logger.warning("no se pudo entregar %s: %s", hasta.name, error)
                continue
            run.record(
                Delivery(
                    file_name=hasta.name,
                    source_document=str(self._relative(run, origin)),
                    destination=str(hasta.parent),
                )
            )
        self._publish(run)

    @classmethod
    def _ruta_del_inventario(cls, run: FolderRun) -> Path:
        """Dónde queda el Excel general: en la carpeta raíz del espejo.

        Se calcula antes de leer nada porque cada trabajo la apunta en el
        inventario al crearse: es lo que deja descargarlo desde el Archivo
        cuando la corrida ya no está en memoria.
        """
        return cls._ruta_de_un_excel(run.destination / cls._raiz(run))

    @staticmethod
    def _ruta_de_un_excel(carpeta: Path, prefijo: str = "ACTAS") -> Path:
        """«ACTAS UPD3859772__inventario.xlsx» dentro de la carpeta que inventaría.

        Con ``prefijo`` «ACTAS DE GRADO» para las actas de grado: una carpeta
        que trae de las dos clases deja un Excel de cada una.
        """
        from ..adapters.excel_actas import SUFIJO
        from ..domain.naming import sheet_filename

        return carpeta / sheet_filename(
            f"{prefijo} {carpeta.name}".strip(),
            SUFIJO,
            directory_length=len(str(carpeta)),
        )

    def _escribir_inventario_de_actas(
        self, run: FolderRun, solo_carpeta: str | None = None
    ) -> None:
        """Deja en el espejo del destino el Excel general y el de cada subcarpeta.

        El general va en la carpeta raíz -- ``DESTINO\\00C003284\\ACTAS
        00C003284__inventario.xlsx`` -- con todas las actas; y cada subcarpeta
        que tenga PDF lleva el suyo, sólo con sus actas: quien abre
        ``UPD3859772`` en el destino encuentra ahí su inventario, como encontraría
        los papeles en la caja. Las filas van en el orden de la carpeta y
        numeradas desde 1, y los folios se encadenan dentro de cada subcarpeta.

        Volver a procesar la misma carpeta al mismo destino **actualiza** esos
        archivos en vez de dejar al lado un «(2)». Sólo si uno está abierto en
        Excel -- que lo bloquea -- se escribe con otro nombre, y la pantalla
        enseña cuál.

        Que falle no deshace nada: las filas siguen en la corrida y cada acta
        conserva su propio Excel junto a su trabajo.

        ``solo_carpeta`` es la escritura de en medio de la corrida: el Excel de
        esa subcarpeta, y el general sólo si hace ``INVENTARIO_GENERAL_CADA``
        que no se escribe. Sin ella se escriben todos, que es lo que se hace al
        terminar y lo que deja los folios deducidos con todas las filas.
        """
        with run.cerrojo:
            self._escribir_inventarios(run, solo_carpeta)

    def _escribir_inventarios(self, run: FolderRun, solo_carpeta: str | None) -> None:
        if not run.inventario_filas:
            return
        if solo_carpeta is None and len(run.inventario_filas) == run.inventario_escritas:
            return
        ahora = time.monotonic()
        con_general = (
            solo_carpeta is None or ahora - run.inventario_general_en >= INVENTARIO_GENERAL_CADA
        )
        try:
            # En el orden de la carpeta y con los folios que la continuidad de
            # la foliación permite deducir de las actas vecinas.
            from ..application.acta_consejo import (
                CONSEJO,
                GRADO,
                TIPO_DE_GRADO,
                inventario_de_la_carpeta,
                validar_inventario,
            )
            from ..domain.acta_grado import ROTULO_DE_CEREMONIA

            filas = inventario_de_la_carpeta(run.inventario_filas)
            run.inventario_validacion = validar_inventario(filas)
            # Un Excel por clase de acta: las de consejo con su resumen, las de
            # grado sin él. El de consejo conserva el nombre de siempre.
            por_clase: dict[str, list[dict]] = {}
            for fila in filas:
                clase = str(fila.get("tipo") or CONSEJO.tipo_documental)
                # Las hojas de una ceremonia de grado van con las actas de
                # grado: el FUID no les da fila, pero son de esa entrega.
                if clase == ROTULO_DE_CEREMONIA:
                    clase = TIPO_DE_GRADO
                por_clase.setdefault(clase, []).append(fila)
            for clase, suyas in por_clase.items():
                grado = clase == TIPO_DE_GRADO
                perfil = GRADO if grado else CONSEJO
                prefijo = "ACTAS DE GRADO" if grado else "ACTAS"
                # El que ya se escribió, por si se escribió con otro nombre
                # porque el suyo estaba abierto; si no, el de su clase.
                ya = run.inventarios_generales.get(clase)
                general = Path(ya) if ya else self._ruta_de_un_excel(
                    run.destination / self._raiz(run), prefijo
                )
                # Una carpeta sin subcarpetas tiene un solo Excel, que es a la
                # vez el general y el suyo: ése va al día siempre.
                es_el_suyo = solo_carpeta is not None and (
                    self._ruta_de_un_excel(run.destination / solo_carpeta, prefijo) == general
                )
                if con_general or es_el_suyo:
                    general = self._escribir_un_excel(run, suyas, general, perfil)
                    run.inventarios_generales[clase] = str(general)

                por_carpeta: dict[str, list[dict]] = {}
                for fila in suyas:
                    por_carpeta.setdefault(str(fila.get("carpeta") or ""), []).append(fila)
                for carpeta, de_la_carpeta in por_carpeta.items():
                    if solo_carpeta is not None and carpeta != solo_carpeta:
                        continue
                    destino = self._ruta_de_un_excel(run.destination / carpeta, prefijo)
                    if carpeta and destino != general:
                        self._escribir_un_excel(run, de_la_carpeta, destino, perfil)

            # El que baja la pantalla: el de consejo si lo hay, si no el de grado.
            run.inventario = run.inventarios_generales.get(
                CONSEJO.tipo_documental
            ) or run.inventarios_generales.get(TIPO_DE_GRADO)
            run.inventario_error = None
            if con_general:
                run.inventario_general_en = ahora
            if solo_carpeta is None:
                run.inventario_escritas = len(run.inventario_filas)
        except Exception as error:  # noqa: BLE001 - lo leído sigue en la corrida
            logger.warning("no se pudo escribir el inventario de actas", exc_info=True)
            run.inventario_error = explicar_fallo(error)

    @staticmethod
    def _escribir_un_excel(
        run: FolderRun, filas: list[dict], destino: Path, perfil=None
    ) -> Path:
        """Escribe un inventario de actas, con otro nombre sólo si el suyo está abierto."""
        from ..adapters.excel_actas import escribir_inventario_de_actas
        from ..application.acta_consejo import CONSEJO, SIN_IA

        perfil = perfil or CONSEJO
        if not perfil.con_resumen and not perfil.lee_folio:
            # Las actas de grado: el FUID oficial, una fila por graduado.
            from ..adapters.fuid_actas_de_grado import escribir_fuid_de_actas_de_grado

            destino.parent.mkdir(parents=True, exist_ok=True)
            try:
                return escribir_fuid_de_actas_de_grado(filas, destino)
            except PermissionError:
                destino = unique_path(destino.parent, destino.name)
                return escribir_fuid_de_actas_de_grado(filas, destino)
        opciones = {
            "carpeta": str(run.source),
            "nota": SIN_IA if run.lectura == "local" else None,
            "titulo": perfil.titulo,
            "con_resumen": perfil.con_resumen,
        }
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            escribir_inventario_de_actas(filas, destino, **opciones)
        except PermissionError:
            destino = unique_path(destino.parent, destino.name)
            escribir_inventario_de_actas(filas, destino, **opciones)
        return destino

    def _dispose(self, run: FolderRun, path: Path) -> None:
        """Leave, move aside, or delete the original, as the operator chose."""
        if run.disposition is SourceDisposition.LEAVE:
            return
        try:
            if run.disposition is SourceDisposition.DELETE:
                path.unlink(missing_ok=True)
                return
            # Bajo `_procesados`, con la misma estructura que tenían. Aplanarlo
            # mezclaría cien expedientes en una carpeta y haría irreversible lo
            # que hasta ahora sólo era moverlos de sitio.
            relativa = self._relative(run, path)
            consumed = run.source / CONSUMED_DIR / relativa.parent
            consumed.mkdir(parents=True, exist_ok=True)
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
