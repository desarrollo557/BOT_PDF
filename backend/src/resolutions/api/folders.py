from __future__ import annotations

import asyncio
import errno
import logging
import os
import shutil
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from itertools import islice
from pathlib import Path
from uuid import uuid4

from ..adapters.excel_inventory import NOMBRE_DEL_INVENTARIO_DE_PROCESOS
from . import constancia as constancias
from .constancia import Constancia, EstadoDeEntrega, Vigencia
from .errores import explicar_fallo
from .jobs import Job, JobRegistry, JobState
from .planificador import Planificador
from .reintentos import merece_otra_vuelta
from .retomar import ControlDeUnLibro, HuellasDelOrigen, Retomar
from .rutas_del_equipo import al_operador, al_servicio
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
    #: En pausa tras una racha de fallos, o esperando a que vuelva el origen:
    #: sigue viva y retoma sola.
    RECOVERING = "recovering"
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

#: Cuántos documentos de la corrida viajan, por su identificador, en cada aviso
#: a la pantalla: los últimos. Con veinte mil PDF mandar todos eran 700 KB por
#: aviso; el total va aparte, en ``job_count``.
JOB_IDS_EN_PANTALLA = 200
#: Y cuántos avisos de la corrida (una subcarpeta que no se deja leer…).
AVISOS_EN_PANTALLA = 50

#: Dónde se aparta, dentro de la carpeta de un PDF en el destino, lo que se
#: entregó antes cuando hay que rehacerlo: una copia cortada o un origen que
#: cambió. Apartar y no borrar: es trabajo entregado, y lo decide el operador.
REEMPLAZADOS_DIR = "_reemplazados"


#: Cuántas veces se reanuda una corrida tras un fallo que no es de ningún
#: documento antes de darla por fallida.
TROPIEZOS_DE_LA_CORRIDA = 3


class EntregaIncompleta(RuntimeError):
    """La copia al destino no terminó: el documento cuenta como fallido."""

    para_el_operador = True


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
            "destination": al_operador(self.destination),
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
    #: Si esta corrida retoma una entrega anterior: ``faltantes`` procesa sólo
    #: lo que no está en el destino, ``revisar`` sólo lo mira. Sólo para
    #: libros de diplomas (ver ``retomar.py``).
    retomar: str = "no"
    #: Cuántos PDF de esta carpeta a la vez, si el operador lo eligió. ``None``
    #: es el automático del planificador.
    paralelo: int | None = None
    #: Lo que había de cada PDF de origen en el destino, qué se hizo y cómo
    #: quedó, en el orden en que se tomaron. Con esto se escribe el control.
    controles: dict[str, ControlDeUnLibro] = field(default_factory=dict)
    #: Los PDF que ya estaban completos en el destino y no se volvieron a leer.
    ya_entregados: int = 0
    #: De ellos, cuántos no traían constancia de entrega: entregas de antes de
    #: que existiera, que se dan por buenas porque su carpeta trae PDF.
    sin_constancia: int = 0
    #: Los que tenían la entrega cortada o el origen cambiado y se rehicieron.
    rehechos: int = 0
    #: Los PDF cuya copia al destino no terminó. Cuentan también como fallidos.
    entregas_incompletas: int = 0
    incompletas: set[str] = field(default_factory=set, repr=False)
    #: Cuántos fallaron seguidos, para pausar la carpeta antes de quemarla.
    fallos_seguidos: int = 0
    #: Hasta cuándo (reloj monótono) está en pausa, y cuántas pausas lleva.
    pausa_hasta: float = 0.0
    pausas: int = 0
    #: Cuántos documentos a la vez mientras se recupera: uno, hasta que uno
    #: salga bien. ``None`` es lo normal, los que deje el planificador.
    a_la_vez: int | None = None
    #: Los que fallaron por algo que merece otra vuelta: ruta -> motivo.
    fallidos: dict[str, str] = field(default_factory=dict)
    #: Los que fallaron y salieron bien en una vuelta posterior.
    recuperados: int = 0
    #: Cuántas veces se reanudó tras un fallo que no era de un documento.
    tropiezos: int = 0
    #: Lo que hay que contar de la corrida y no es el fallo de un documento: una
    #: subcarpeta del origen que no se dejó leer, por ejemplo.
    avisos: list[str] = field(default_factory=list)
    #: Dónde quedó «00.CONTROL DE ENTREGA.xlsx», cuando ya se escribió.
    control: str | None = None
    huellas: HuellasDelOrigen = field(default_factory=HuellasDelOrigen, repr=False)
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

    #: Tamaño y fecha de cada PDF pendiente, tomados al descubrirlo.
    huellas_del_origen: dict[str, tuple[int, int]] = field(default_factory=dict, repr=False)
    #: Los PDF que hay que rehacer y por qué: ruta -> (vigencia, constancia).
    a_rehacer: dict[str, tuple] = field(default_factory=dict, repr=False)
    #: La fila del inventario general de procesos de cada PDF, por su ruta
    #: relativa. La guarda la corrida y no se saca del registro, porque de
    #: allí salen los documentos viejos (ver ``trabajos_en_memoria``).
    procesos: dict[str, object] = field(default_factory=dict, repr=False)
    #: Las carpetas del destino con un libro de diplomas, para el FUID general.
    carpetas_con_fuid: dict[str, Path] = field(default_factory=dict, repr=False)
    #: El Índice Electrónico entregado de cada caja de correspondencia.
    indices: dict[str, Path] = field(default_factory=dict, repr=False)
    #: Lo ya leído de cada FUID del destino, para no releerlos todos cada vez.
    lecturas_de_fuid: dict = field(default_factory=dict, repr=False)
    #: Las filas de actas de cada subcarpeta, para escribir su Excel sin
    #: recorrer las de toda la corrida.
    filas_por_carpeta: dict[str, list[dict]] = field(default_factory=dict, repr=False)
    #: Los documentos terminados, en orden, para sacar del registro los viejos.
    terminados: deque = field(default_factory=deque, repr=False)
    #: Lo que sumaban los documentos que ya salieron del registro, para que el
    #: panel de la carpeta no encoja sus cifras al sacarlos.
    retirados: dict = field(
        default_factory=lambda: {"procedencias": {}, "revision": 0, "fallidas": 0, "consumo": None}
    )
    #: Si hay inventarios generales por escribir, y quién los escribe.
    generales_pendientes: bool = False
    escritor: asyncio.Task | None = field(default=None, repr=False)
    #: Los generales, de uno en uno; aparte de la entrega para no pararla.
    cerrojo_generales: threading.Lock = field(default_factory=threading.Lock, repr=False)
    #: Cuántas unidades llevaba la planilla de la entrega al escribirla.
    manifiesto_escrito: int = 0

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
        return self.state in (
            RunState.SCANNING,
            RunState.PROCESSING,
            RunState.WATCHING,
            RunState.RECOVERING,
        )

    def record(self, delivery: Delivery) -> None:
        self.deliveries.append(delivery)
        if len(self.deliveries) > DELIVERY_WINDOW:
            del self.deliveries[: len(self.deliveries) - DELIVERY_WINDOW]
        self.delivered += 1

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "folder_run",
            "id": self.id,
            # Como las reconoce el operador, también cuando el servicio corre
            # en Docker y las ve montadas en otra ruta.
            "source": al_operador(self.source),
            "destination": al_operador(self.destination),
            "disposition": str(self.disposition),
            "watch": self.watch,
            "task": self.task,
            "oracle": self.oracle,
            "lectura": self.lectura,
            "corte": self.corte,
            "agrupar": self.agrupar,
            "territorial": self.territorial,
            "tipo": self.tipo,
            "retomar": self.retomar,
            "paralelo": self.paralelo,
            "ya_entregados": self.ya_entregados,
            "sin_constancia": self.sin_constancia,
            "rehechos": self.rehechos,
            "entregas_incompletas": self.entregas_incompletas,
            "recuperados": self.recuperados,
            "por_reintentar": len(self.fallidos),
            "pausas": self.pausas,
            "avisos": self.avisos[-AVISOS_EN_PANTALLA:],
            "retirados": self.retirados,
            "control": Path(self.control).name if self.control else None,
            "control_ruta": al_operador(self.control) if self.control else None,
            "controles": [control.as_dict() for control in islice(self.controles.values(), 500)],
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
            # Los últimos: los demás ya salieron del registro o están por salir.
            "job_ids": self.job_ids[-JOB_IDS_EN_PANTALLA:],
            "job_count": len(self.job_ids),
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
            "inventario_ruta": al_operador(self.inventario) if self.inventario else None,
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
    # En Docker, «C:\…» del operador está montada en otra ruta del contenedor
    # (ver `rutas_del_equipo.py`). Fuera de Docker no cambia nada.
    source = al_servicio(source)
    destination = al_servicio(destination)

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
        #: El bucle de la aplicación, para publicar desde los hilos de entrega.
        self._loop: asyncio.AbstractEventLoop | None = None

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
        retomar: str = "no",
        paralelo: int | None = None,
    ) -> FolderRun:
        try:
            modo = Retomar.parse(retomar)
        except ValueError as error:
            raise FolderError(str(error)) from None
        if modo in (Retomar.FALTANTES, Retomar.REVISAR) and tipo != "diploma":
            # Saber qué llegó al destino exige reconocer cada página entregada
            # en el PDF de origen, y eso sólo está medido para los libros de
            # diplomas: un archivo por cara, copiada tal cual.
            raise FolderError("Retomar una entrega sólo está disponible para libros de diplomas")
        if modo in (Retomar.FALTANTES, Retomar.REVISAR) and watch:
            raise FolderError("Una carpeta que se retoma no se puede vigilar a la vez")
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
            retomar=str(modo),
            paralelo=paralelo,
        )
        if paralelo:
            # Si pide más que las ranuras del servicio, se abren más: si no,
            # la cifra elegida se quedaría en papel.
            self._planificador.ampliar(paralelo)
        self._runs[run.id] = run
        self._loop = asyncio.get_running_loop()
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
        # La planilla de la entrega y los inventarios los escribe la propia
        # corrida al recibir la cancelación, en un hilo (ver `_drain`). Aquí
        # escribían en el hilo que atiende la pantalla: con una carpeta grande,
        # «Detener» tardaba en contestar y todo parecía colgado.
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
                pending, entregados = await self._descubrir_con_paciencia(run)
                for path, constancia in entregados:
                    run.seen.add(str(path))
                    self._contar_lo_ya_entregado(run, path, constancia)
                run.ya_entregados += len(entregados)
                run.discovered += len(pending) + len(entregados)
                if entregados:
                    self._pedir_generales(run)
                if pending:
                    run.state = RunState.PROCESSING
                    run.queue = [str(self._relative(run, path)) for path in pending]
                    self._publish(run)
                    await self._consumir_en_paralelo(run, pending)
                    await self._otra_vuelta(run)
                elif run.watch and run.active:
                    # A watching run never "finishes", so the sheet is refreshed
                    # each time the folder empties: otherwise the destination
                    # would hold PDFs with no inventory until somebody stopped it.
                    # Sólo si cambió: una carpeta vigilada sin novedades pasa
                    # por aquí cada cinco segundos.
                    await asyncio.to_thread(self._write_manifest, run, solo_si_cambio=True)
                    await asyncio.to_thread(self._escribir_inventario_de_actas, run)
                    run.state = RunState.WATCHING
                    run.queue = []
                    run.en_curso.clear()
                    self._publish(run)
                    await asyncio.sleep(self._watch_interval)
                    continue
                else:
                    break

                if not run.watch or run.state is RunState.FAILED:
                    break

            # El Excel antes de dar la carpeta por terminada: la pantalla enseña
            # el botón de descarga en cuanto la ve terminada, y un botón que
            # aparece antes que el archivo es un botón que falla.
            await asyncio.to_thread(self._escribir_inventario_de_actas, run)
            await self._cerrar_generales(run)
            if run.state is not RunState.FAILED:
                # Una carpeta detenida por fallos seguidos se queda así, con
                # su motivo: «terminada» diría que salió bien.
                run.state = RunState.DONE
            run.finished_at = run.finished_at or _now()
            run.en_curso.clear()
            run.queue = []
            await asyncio.to_thread(self._write_manifest, run)
            self._publish(run)
        except asyncio.CancelledError:
            # stop() already recorded the state; do not overwrite it. Pero lo
            # inventariado hasta aquí se deja escrito: detener una carpeta de
            # cien actas a la mitad no tiene por qué perder las cincuenta leídas.
            if run.escritor is not None:
                run.escritor.cancel()
            run.generales_pendientes = False
            # En un hilo y protegido: la pantalla sigue atendiendo mientras se
            # escribe, y una segunda pulsación de «Detener» no deja los Excel a
            # medio escribir.
            try:
                await asyncio.shield(asyncio.to_thread(self._dejar_escrito_al_detener, run))
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - detener no falla por un Excel
                logger.warning("no se pudo dejar escrito lo de %s al detener", run.source, exc_info=True)
            self._publish(run)
            raise
        except Exception as error:  # noqa: BLE001 - surfaced to the operator
            logger.exception("folder run %s failed", run.id)
            if run.active and run.tropiezos < TROPIEZOS_DE_LA_CORRIDA:
                # Un fallo que no es de ningún documento -- un error del propio
                # bucle, el disco del destino un momento -- no tira la corrida:
                # se anota, se espera y se sigue. Lo ya tomado no se repite.
                run.tropiezos += 1
                espera = 30.0 * run.tropiezos
                self._avisar(
                    run,
                    f"La corrida tropezó ({explicar_fallo(error)}). Se reanuda en {espera:.0f} s "
                    f"(intento {run.tropiezos} de {TROPIEZOS_DE_LA_CORRIDA}).",
                )
                run.state = RunState.RECOVERING
                self._publish(run)
                await asyncio.sleep(espera)
                if run.active:
                    run.state = RunState.PROCESSING
                    await self._drain(run)
                return
            run.state = RunState.FAILED
            run.error = explicar_fallo(error)
            run.finished_at = _now()
            self._publish(run)

    def _dejar_escrito_al_detener(self, run: FolderRun) -> None:
        """Lo inventariado hasta aquí, escrito: detener a la mitad no pierde lo leído."""
        self._escribir_inventario_de_actas(run)
        self._escribir_todo_lo_general(run)
        self._write_manifest(run)

    async def _descubrir_con_paciencia(
        self, run: FolderRun
    ) -> tuple[list[Path], list[tuple[Path, Constancia | None]]]:
        """Recorre el origen y, si no se deja, espera a que vuelva en vez de rendirse.

        La carpeta de origen suele estar en una unidad de red, y una unidad de
        red se desconecta: la VPN que se cae, el servidor que se reinicia. Eso
        tumbaba la corrida entera. Ahora se espera -- treinta segundos, luego
        el doble, hasta cinco minutos entre intentos -- hasta
        ``minutos_de_espera_del_origen``; sólo entonces la corrida falla.
        """
        limite = time.monotonic() + 60 * float(
            getattr(self._settings, "minutos_de_espera_del_origen", 0) or 0
        )
        espera = 30.0
        while True:
            try:
                resultado = await asyncio.to_thread(self._discover, run)
            except (FolderError, OSError) as error:
                if not run.active or time.monotonic() + espera > limite:
                    raise
                self._avisar(
                    run,
                    f"No se pudo recorrer el origen ({error}). Se vuelve a intentar en "
                    f"{espera:.0f} s; la corrida espera a que vuelva la unidad.",
                )
                run.state = RunState.RECOVERING
                self._publish(run)
                await asyncio.sleep(espera)
                espera = min(espera * 2, 300.0)
                continue
            if run.state is RunState.RECOVERING:
                run.state = RunState.PROCESSING
            return resultado

    def _discover(self, run: FolderRun) -> tuple[list[Path], list[tuple[Path, Constancia | None]]]:
        """Los PDF del árbol de origen que nadie ha tomado todavía, y los ya entregados.

        Por todo el árbol y no sólo por la carpeta que se indicó: el archivo se
        entrega en cajas -- una carpeta por expediente, y cien expedientes en la
        ruta que el operador señala -- y pedirle que apunte cien veces, una por
        carpeta, es pedirle que haga a mano lo que la máquina sabe hacer.

        En orden de ruta, no de nombre, que es lo que mantiene juntos los
        documentos de una misma carpeta mientras se procesan.

        Con ``os.walk`` y no con ``rglob``: ``rglob`` se salta en silencio una
        subcarpeta que no se deja leer -- la red que parpadea, un permiso --, y
        sus PDF desaparecían de la corrida sin un error que mirar. Ahora cada
        una queda en los avisos de la corrida. ``_procesados`` no se recorre.

        Lo ya entregado se sabe por su constancia (ver ``constancia.py``), sin
        abrir ni el origen ni lo entregado. Sin constancia, una carpeta del
        destino con algún PDF es una entrega de antes de que existiera, y se da
        por buena como hasta ahora.
        """

        def no_se_pudo(error: OSError) -> None:
            if Path(str(error.filename or "")) == run.source:
                raise FolderError(f"No se pudo leer la carpeta de origen: {error}")
            self._avisar(
                run,
                f"No se pudo leer la carpeta «{self._relative(run, Path(str(error.filename)))}»: "
                f"{error.strerror or error}. Sus PDF no entraron en esta corrida.",
            )

        encontrados: list[Path] = []
        try:
            for carpeta, subcarpetas, archivos in os.walk(run.source, onerror=no_se_pudo):
                # `_procesados` a cualquier profundidad: bajo MOVE los originales
                # se apartan ahí, y volver a tomarlos sería procesar dos veces.
                subcarpetas[:] = [nombre for nombre in subcarpetas if nombre != CONSUMED_DIR]
                encontrados.extend(
                    Path(carpeta) / nombre for nombre in archivos if nombre.lower().endswith(".pdf")
                )
        except FolderError:
            raise
        except OSError as error:
            raise FolderError(f"No se pudo leer la carpeta de origen: {error}") from None
        encontrados.sort(key=lambda path: str(path).lower())

        pending: list[Path] = []
        entregados: list[tuple[Path, Constancia | None]] = []
        for path in encontrados:
            key = str(path)
            if key in run.seen:
                continue
            if run.retomar == Retomar.NO:
                vigencia, constancia = self._vigencia(run, path)
                if vigencia is Vigencia.VIGENTE:
                    entregados.append((path, constancia))
                    continue
                if vigencia is Vigencia.SIN_CONSTANCIA and self._tiene_pdf_entregado(run, path):
                    run.sin_constancia += 1
                    entregados.append((path, None))
                    continue
                if vigencia in (Vigencia.INCOMPLETA, Vigencia.ORIGEN_CAMBIADO):
                    run.a_rehacer[key] = (vigencia, constancia)
            elif run.retomar == Retomar.TODO:
                # Todo otra vez, y lo entregado antes se aparta para no dejar
                # cada archivo con su «(2)» al lado.
                vigencia, constancia = self._vigencia(run, path)
                if constancia is not None or self._tiene_pdf_entregado(run, path):
                    run.a_rehacer[key] = (vigencia, constancia)
            try:
                run.huellas_del_origen[key] = constancias.huella_del_origen(path)
            except OSError:
                run.huellas_del_origen[key] = (0, 0)
            pending.append(path)

        return pending, entregados

    def _avisar(self, run: FolderRun, aviso: str) -> None:
        logger.warning("%s: %s", run.source, aviso)
        if aviso not in run.avisos:
            run.avisos.append(aviso)
            del run.avisos[:-AVISOS_EN_PANTALLA]

    def _ruta_de_la_constancia(self, run: FolderRun, path: Path, *, actas: bool) -> Path:
        """Dónde va la constancia de un PDF: en su carpeta, o la de sus actas en el espejo."""
        if actas:
            return self._espejo(run, path) / constancias.CARPETA_DE_ACTAS / f"{path.name}.json"
        return self._output_dir(run, path) / constancias.NOMBRE

    def _vigencia(self, run: FolderRun, path: Path) -> tuple[Vigencia, Constancia | None]:
        """Qué dice la constancia de un PDF -- la suya o, si es de actas, la del espejo --."""
        for actas in (False, True):
            ruta = self._ruta_de_la_constancia(run, path, actas=actas)
            constancia = constancias.leer(ruta)
            if constancia is not None:
                base = ruta.parent.parent if actas else ruta.parent
                return constancias.vigencia(constancia, path, base), constancia
        return Vigencia.SIN_CONSTANCIA, None

    def _tiene_pdf_entregado(self, run: FolderRun, path: Path) -> bool:
        carpeta = self._output_dir(run, path)
        try:
            return carpeta.is_dir() and any(carpeta.glob("*.[pP][dD][fF]"))
        except OSError:
            return False

    def _contar_lo_ya_entregado(
        self, run: FolderRun, path: Path, constancia: Constancia | None
    ) -> None:
        """Lo que un PDF ya entregado aporta a los inventarios generales, sin procesarlo.

        Sin esto, relanzar una carpeta para tomar diez PDF nuevos reescribía
        los generales con esos diez y nada más.
        """
        from ..adapters.excel_inventory import FilaDeProceso
        from ..adapters.indice_electronico import NOMBRE_DEL_INDICE

        relativa = str(self._relative(run, path))
        carpeta = self._output_dir(run, path)
        nota = (
            "ya estaba entregado: no se volvió a procesar"
            if constancia
            else "entregado por una corrida anterior, sin constancia de entrega"
        )
        fila = None
        if constancia and constancia.proceso:
            try:
                fila = FilaDeProceso(**{**constancia.proceso, "estado": "Ya entregado", "observaciones": nota})
            except TypeError:
                fila = None
        run.procesos[relativa] = fila or FilaDeProceso(
            pdf=path.name,
            habilidad=(constancia.habilidad if constancia else "") or "—",
            lectura="—",
            entrega="—",
            paginas=0,
            documentos=0,
            en_revision=0,
            estado="Ya entregado",
            inicio=None,
            duracion="—",
            paginas_pagadas=0,
            operador=run.operator or "",
            destino=self._relativa_al_destino(run, carpeta),
            observaciones=nota,
        )
        if constancia is None:
            if run.tipo == "diploma":
                run.carpetas_con_fuid[self._relativa_al_destino(run, carpeta)] = carpeta
            return
        if constancia.habilidad == "Libro de diplomas":
            run.carpetas_con_fuid[self._relativa_al_destino(run, carpeta)] = carpeta
        if constancia.actas:
            self._sumar_filas_de_actas(run, constancia.actas)
        if constancia.unidades:
            run.manifest.extend(constancia.unidades)
        if any(str(archivo.get("ruta")) == NOMBRE_DEL_INDICE for archivo in constancia.archivos):
            run.indices[carpeta.name] = carpeta / NOMBRE_DEL_INDICE

    @staticmethod
    def _sumar_filas_de_actas(run: FolderRun, filas: list[dict]) -> None:
        run.inventario_filas.extend(filas)
        for fila in filas:
            run.filas_por_carpeta.setdefault(str(fila.get("carpeta") or ""), []).append(fila)

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

        async def trabajador(indice: int) -> None:
            while cola:
                # En pausa, o sobrando mientras la carpeta va de uno en uno:
                # se espera sin tomar nada.
                await self._esperar_turno(run, indice, cola)
                if not run.active or not cola:
                    return
                path = cola.popleft()
                async with ranuras:
                    if not run.active:
                        return
                    await self._consume(run, path)

        cuantos = min(len(cola), run.paralelo or self._planificador.por_omision)
        await asyncio.gather(*(trabajador(indice) for indice in range(cuantos)))

    async def _esperar_turno(self, run: FolderRun, indice: int, cola: deque) -> None:
        """Lo que espera un trabajador antes de tomar el siguiente PDF.

        Tras una racha de fallos la carpeta se pausa un rato y luego sigue con
        un solo documento a la vez, hasta que uno salga bien: si la red volvió,
        el primero lo dice y vuelven todos; si no, se gasta un intento y no
        diez.
        """
        while run.active and cola:
            espera = run.pausa_hasta - time.monotonic()
            if espera > 0:
                if run.state is not RunState.RECOVERING:
                    run.state = RunState.RECOVERING
                    self._publish(run)
                await asyncio.sleep(min(espera, 1.0))
                continue
            if run.state is RunState.RECOVERING:
                run.state = RunState.PROCESSING
                self._publish(run)
            if run.a_la_vez is not None and indice >= run.a_la_vez:
                await asyncio.sleep(0.2)
                continue
            return

    async def _consume(self, run: FolderRun, path: Path) -> None:
        """Un PDF de la carpeta: procesarlo, entregarlo y contarlo.

        Lo que falle aquí -- la entrega, el disco -- cuenta como un documento
        fallido y la carpeta sigue: con varios a la vez, dejar que el error
        subiera tumbaba también a los que estaban leyéndose al lado.
        """
        run.seen.add(str(path))
        relativa = str(self._relative(run, path))
        # Casi siempre es el primero de la cola: sacarlo así no recorre la
        # cola entera, que con veinte mil PDF sumaba minutos.
        if run.queue and run.queue[0] == relativa:
            del run.queue[0]
        elif relativa in run.queue:
            run.queue.remove(relativa)

        # Al retomar, antes de nada se mira qué hay de este PDF en el destino.
        # Lo completo no se vuelve a leer, y de lo que está a medias se leen
        # sólo las páginas que faltan.
        paginas: list[int] | None = None
        control: ControlDeUnLibro | None = None
        if run.retomar in (Retomar.FALTANTES, Retomar.REVISAR):
            control, paginas, seguir = await self._mirar_el_destino(run, path, relativa)
            if not seguir:
                self._pedir_generales(run)
                self._publish(run)
                return

        # Tamaño y fecha del origen tal como se descubrió: es lo que la
        # constancia guarda para saber, la próxima vez, si es el mismo. Se
        # tomaron en el hilo que recorre la carpeta: aquí un `stat` a la red
        # pararía el servicio si la red no contesta, y un `await` dejaría que
        # otro trabajador se adelantara y perdiera el orden de la carpeta.
        huella = run.huellas_del_origen.pop(str(path), (0, 0))
        job = self._registry.create(
            filename=relativa,
            source=path,
            owns_source=False,
            size=huella[0],
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
            destination=al_operador(self._output_dir(run, path)),
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
            paginas=paginas,
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
                entrega = await asyncio.to_thread(self._deliver, run, job, path, huella)
                if entrega.fallos:
                    # Lo copiado a medias no es una entrega: el PDF cuenta
                    # como fallido, el original se queda donde estaba y la
                    # constancia sigue diciendo «entregando», así que la
                    # próxima corrida lo rehace entero.
                    run.processed -= 1
                    run.incompletas.add(str(path))
                    run.entregas_incompletas = len(run.incompletas)
                    raise EntregaIncompleta(
                        f"La entrega quedó incompleta: {len(entrega.fallos)} archivo(s) no se "
                        f"copiaron al destino ({'; '.join(entrega.fallos[:3])}). Vuelva a lanzar "
                        "la carpeta: este PDF se rehará."
                    )
                await asyncio.to_thread(self._dejar_constancia, run, job, path, huella, entrega)
                if str(path) in run.incompletas:
                    # Una vuelta posterior sí la terminó.
                    run.incompletas.discard(str(path))
                    run.entregas_incompletas = len(run.incompletas)
                await asyncio.to_thread(self._dispose, run, path)
                if control is not None:
                    await self._comprobar_el_destino(run, path, control)
            elif job.state is JobState.CANCELLED:
                # Lo canceló el operador: no es un fallo y no se cuenta como tal.
                if control is not None:
                    control.accion = "cancelado"
            else:
                run.failed += 1
                if control is not None:
                    control.accion = "falló"
                    control.error = job.error or "el procesamiento no terminó"
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - un documento no tumba la carpeta
            if not isinstance(error, EntregaIncompleta):
                logger.exception("no se pudo terminar %s", relativa)
            run.failed += 1
            job.reintentable = merece_otra_vuelta(error)
            if job.state is not JobState.FAILED:
                self._registry.mark_failed(job, explicar_fallo(error))
            if control is not None:
                control.accion = "falló"
                control.error = job.error
        finally:
            run.en_curso.pop(job.id, None)
            self._anotar_el_proceso(run, job, relativa)
            if job.state is JobState.FAILED and job.reintentable:
                run.fallidos[str(path)] = job.error or "sin detalle"
            self._pausar_si_fallan_seguidos(run, job)
            self._retirar_los_viejos(run, job)
            # Los inventarios generales de la carpeta, con este PDF ya contado
            # -- también si falló --, cuando le toque al escritor de fondo.
            self._pedir_generales(run)
            self._publish(run)

    def _anotar_el_proceso(self, run: FolderRun, job: Job, relativa: str) -> None:
        from .indices import fila_de_proceso

        if str(job.state) in ("done", "failed", "cancelled"):
            run.procesos[relativa] = fila_de_proceso(job, self._destino_relativo(run, job))

    def _pausar_si_fallan_seguidos(self, run: FolderRun, job: Job) -> None:
        """Pausa la carpeta cuando fallan demasiados documentos seguidos.

        Diez PDF seguidos que fallan casi nunca son diez papeles malos: es la
        red, el disco de destino lleno o el proveedor sin crédito. Detener la
        carpeta obligaba a relanzarla a mano; seguir igual quemaba en minutos
        los veinte mil que quedan. Ahora se pausa -- un minuto la primera vez,
        el doble cada vez seguida, hasta quince --, sigue de uno en uno hasta
        que uno salga bien, y los que fallaron vuelven al final de la cola.
        """
        if job.state is JobState.DONE:
            run.fallos_seguidos = 0
            if run.a_la_vez is not None:
                run.a_la_vez = None
                run.pausas = 0
                logger.info("%s: un documento salió bien; la carpeta vuelve a su ritmo", run.source)
            return
        if job.state is not JobState.FAILED:
            return
        run.fallos_seguidos += 1
        limite = int(getattr(self._settings, "fallos_seguidos", 0) or 0)
        if not limite or run.fallos_seguidos < limite or not run.active:
            return
        run.pausas += 1
        base = float(getattr(self._settings, "pausa_tras_fallos", 60.0) or 0)
        espera = min(base * 2 ** (run.pausas - 1), 900.0)
        run.pausa_hasta = time.monotonic() + espera
        run.a_la_vez = 1
        self._avisar(
            run,
            f"{run.fallos_seguidos} documentos seguidos fallaron (el último: "
            f"{job.error or 'sin detalle'}). La carpeta se pausa {espera / 60:.0f} min, sigue de "
            "uno en uno y vuelve a intentar al final los que fallaron.",
        )
        run.fallos_seguidos = 0

    async def _otra_vuelta(self, run: FolderRun) -> None:
        """Vuelve a intentar, al final de la cola, los que fallaron por algo pasajero.

        Tras una pausa: los que fallaron por la red o por un Excel abierto
        suelen salir bien minutos después. Los que salen bien dejan de contar
        como fallidos y se cuentan como recuperados.
        """
        vueltas = int(getattr(self._settings, "vueltas_de_reintento", 0) or 0)
        for vuelta in range(1, vueltas + 1):
            if not run.fallidos or not run.active:
                return
            rutas = [Path(ruta) for ruta in run.fallidos]
            run.fallidos.clear()
            espera = float(getattr(self._settings, "pausa_tras_fallos", 60.0) or 0)
            self._avisar(
                run,
                f"Vuelta {vuelta} de reintento: {len(rutas)} "
                f"{'documento que falló vuelve' if len(rutas) == 1 else 'documentos que fallaron vuelven'} "
                f"a intentarse en {espera:.0f} s.",
            )
            run.pausa_hasta = max(run.pausa_hasta, time.monotonic() + espera)
            for ruta in rutas:
                run.seen.discard(str(ruta))
            await asyncio.to_thread(self._preparar_otra_vuelta, run, rutas)
            antes = run.failed
            run.failed -= len(rutas)
            run.queue = [str(self._relative(run, ruta)) for ruta in rutas]
            await self._consumir_en_paralelo(run, rutas)
            # Los que no volvieron a fallar.
            run.recuperados += max(0, len(rutas) - (run.failed - (antes - len(rutas))))

    def _preparar_otra_vuelta(self, run: FolderRun, rutas: list[Path]) -> None:
        """Huella del origen y, si quedó algo a medias en el destino, que se aparte."""
        for ruta in rutas:
            clave = str(ruta)
            try:
                run.huellas_del_origen[clave] = constancias.huella_del_origen(ruta)
            except OSError:
                run.huellas_del_origen[clave] = (0, 0)
            vigencia, constancia = self._vigencia(run, ruta)
            if constancia is not None and vigencia is not Vigencia.VIGENTE:
                run.a_rehacer[clave] = (vigencia, constancia)

    def _retirar_los_viejos(self, run: FolderRun, job: Job) -> None:
        """Saca del registro los documentos más viejos de la carpeta, ya terminados.

        Cada uno guardaba su informe entero -- grupos, páginas, revisión --, y
        con veinte mil PDF eran gigas de memoria y de lo que se le manda a la
        pantalla al conectarse. Su fila queda en los inventarios (la guarda la
        corrida) y en el Archivo; lo que sumaban para el panel, en
        ``retirados``.
        """
        run.terminados.append(job.id)
        limite = int(getattr(self._settings, "trabajos_en_memoria", 0) or 0)
        while limite and len(run.terminados) > limite:
            viejo = self._registry.get(run.terminados.popleft())
            if viejo is None or viejo.state in (JobState.QUEUED, JobState.RUNNING, JobState.PAUSED):
                continue
            _acumular(run.retirados, viejo)
            self._registry.remove(viejo.id)

    # -- los inventarios generales, de fondo ----------------------------------

    def _pedir_generales(self, run: FolderRun) -> None:
        """Pide que se escriban los generales, sin esperarlos.

        Se escribían tras cada PDF y en el hilo que atiende la pantalla: con
        veinte mil PDF eso son veinte mil reescrituras de una planilla que
        crece, horas con el servicio sin contestar. Ahora los escribe una sola
        tarea de fondo, como mucho cada ``INVENTARIO_GENERAL_CADA`` segundos
        contados desde que terminó la escritura anterior, y una vez más al
        final con todo.
        """
        run.generales_pendientes = True
        if run.escritor is None or run.escritor.done():
            try:
                run.escritor = asyncio.get_running_loop().create_task(self._escribir_generales_luego(run))
            except RuntimeError:
                # Sin bucle -- desde un hilo, en una prueba --, al momento.
                self._escribir_todo_lo_general(run)

    async def _escribir_generales_luego(self, run: FolderRun) -> None:
        while run.generales_pendientes:
            espera = INVENTARIO_GENERAL_CADA - (time.monotonic() - run.generales_en)
            if run.generales_en and espera > 0:
                await asyncio.sleep(espera)
            run.generales_pendientes = False
            await asyncio.to_thread(self._escribir_todo_lo_general, run)

    async def _cerrar_generales(self, run: FolderRun) -> None:
        """La escritura final de los generales, con todo, al terminar la carpeta."""
        run.generales_pendientes = False
        escritor = run.escritor
        if escritor is not None and not escritor.done():
            escritor.cancel()
            try:
                await escritor
            except asyncio.CancelledError:
                pass
        await asyncio.to_thread(self._escribir_todo_lo_general, run)

    def _escribir_todo_lo_general(self, run: FolderRun) -> None:
        with run.cerrojo_generales:
            self._escribir_control(run)
            self._escribir_generales(run)
            run.generales_en = time.monotonic()

    async def _mirar_el_destino(
        self, run: FolderRun, path: Path, relativa: str
    ) -> tuple[ControlDeUnLibro, list[int] | None, bool]:
        """Qué hay de este PDF en el destino, y qué hacer: (control, páginas, seguir).

        ``páginas`` es ``None`` para procesarlo entero. ``seguir`` es falso
        cuando no hay nada que procesar: ya estaba completo, sólo se revisa, o
        no se pudo mirar.
        """
        from .retomar import conciliar_libro, que_hacer

        carpeta = self._output_dir(run, path)
        control = ControlDeUnLibro(pdf=relativa, carpeta=self._relativa_al_destino(run, carpeta))
        run.controles[relativa] = control
        if run.retomar == Retomar.FALTANTES:
            # Con la constancia de una entrega completa no hace falta leer el
            # libro página a página -- veinte segundos por libro desde la red --:
            # ya se sabe que está entero.
            vigencia, constancia = await asyncio.to_thread(self._vigencia, run, path)
            if vigencia is Vigencia.VIGENTE:
                control.accion = "ya estaba completo (constancia de entrega): no se volvió a leer"
                run.ya_entregados += 1
                self._contar_lo_ya_entregado(run, path, constancia)
                return control, None, False
        try:
            control.antes, control.ilegibles = await asyncio.to_thread(
                conciliar_libro, path, carpeta, run.huellas
            )
        except Exception as error:  # noqa: BLE001 - un PDF que no se deja mirar no tumba la carpeta
            logger.warning("no se pudo mirar el destino de %s", relativa, exc_info=True)
            control.error = f"no se pudo comparar con el destino: {explicar_fallo(error)}"
            run.failed += 1
            return control, None, False
        if run.retomar == Retomar.REVISAR:
            control.accion = "sólo se revisó"
            return control, None, False
        paginas, control.accion = que_hacer(control.antes)
        if paginas == []:
            run.ya_entregados += 1
            return control, None, False
        return control, paginas, True

    async def _comprobar_el_destino(
        self, run: FolderRun, path: Path, control: ControlDeUnLibro
    ) -> None:
        """Vuelve a mirar el destino tras entregar: lo que dice el control es lo que hay."""
        from .retomar import conciliar_libro

        try:
            control.despues, control.ilegibles = await asyncio.to_thread(
                conciliar_libro, path, self._output_dir(run, path), run.huellas
            )
        except Exception as error:  # noqa: BLE001 - la entrega ya está hecha
            logger.warning("no se pudo comprobar el destino de %s", control.pdf, exc_info=True)
            control.error = f"no se pudo comprobar la entrega: {explicar_fallo(error)}"

    @staticmethod
    def _relativa_al_destino(run: FolderRun, carpeta: Path) -> str:
        try:
            return str(carpeta.relative_to(run.destination))
        except ValueError:
            return str(carpeta)

    def _escribir_control(self, run: FolderRun) -> None:
        """«00.CONTROL DE ENTREGA.xlsx» en la raíz del destino, al día. Que falle no deshace nada."""
        from .retomar import escribir_control

        if run.retomar == Retomar.NO or not run.controles:
            return
        try:
            with run.cerrojo:
                ruta = escribir_control(
                    list(run.controles.values()),
                    run.destination,
                    origen=run.source.name or str(run.source),
                    operador=run.operator,
                )
            if ruta is not None:
                run.control = str(ruta)
        except Exception:  # noqa: BLE001 - lo entregado ya está en el disco
            logger.warning("no se pudo escribir el control de %s", run.source, exc_info=True)

    def _escribir_generales(self, run: FolderRun, *, con_indice: bool = True) -> None:
        """Los dos inventarios generales en la raíz del destino.

        Lo pidió el operador: dentro de la carpeta de cada PDF, el inventario de
        su habilidad; en la raíz, dos generales -- el de la habilidad (el Índice
        Electrónico de las cajas de correspondencia, una hoja por PDF; el FUID
        general de los libros de diplomas, una fila por diploma) y el del
        bot, una fila por cada PDF procesado --. Que fallen no deshace nada.

        De lo que guarda la corrida y no de los trabajos del registro: los
        viejos salen de él, y los ya entregados en otra corrida nunca entraron.
        Lo que se copia bajo el cerrojo es poco; la escritura va fuera, para no
        parar las entregas mientras se escribe.
        """
        from .indices import (
            fuid_general_de,
            inventario_de_procesos_de,
            libro_de_indices_de,
        )

        with run.cerrojo:
            filas = list(run.procesos.values())
            indices = sorted(run.indices.items())
            fuids = self._fuids_del_destino(run)
        try:
            inventario_de_procesos_de(
                filas,
                run.destination,
                origen=run.source.name or str(run.source),
                clase_de_origen="Carpeta",
                operador=run.operator,
            )
            if con_indice:
                if indices:
                    libro_de_indices_de(indices, run.destination)
                fuid_general_de(fuids, run.destination, lecturas=run.lecturas_de_fuid)
        except Exception:  # noqa: BLE001 - la entrega de cada PDF ya está hecha
            logger.warning("no se pudieron escribir los generales de %s", run.source, exc_info=True)

    def _fuids_del_destino(self, run: FolderRun) -> list[tuple[Path, str]]:
        """Los FUID de los libros de diplomas de esta corrida, tal como están en el destino.

        Del destino y no de los trabajos: al retomar, los libros que ya estaban
        completos no se procesan y su FUID sólo está ahí, y uno retomado a
        medias tiene ahí el suyo ya sumado a lo anterior.
        """
        from .retomar import fuid_del_libro

        carpetas: dict[str, Path] = dict(run.carpetas_con_fuid)
        for control in run.controles.values():
            carpetas.setdefault(control.carpeta, run.destination / control.carpeta)
        planillas = []
        for relativa in sorted(carpetas, key=str.lower):
            fuid = fuid_del_libro(carpetas[relativa])
            if fuid is not None:
                planillas.append((fuid, relativa))
        return planillas

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

    def _deliver(
        self, run: FolderRun, job: Job, origin: Path, huella: tuple[int, int] = (0, 0)
    ) -> Entrega:
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
            return self._entregar(run, job, origin, huella)

    def _entregar(
        self, run: FolderRun, job: Job, origin: Path, huella: tuple[int, int] = (0, 0)
    ) -> Entrega:
        filas = (job.report or {}).get("inventario_actas") or []
        if filas:
            # La carpeta de cada fila es su ruta desde la raíz elegida: con
            # subcarpetas, «00C003284\UPD3859772» y no sólo «UPD3859772». Es lo
            # que agrupa el Excel de cada subcarpeta y lo que encadena sus folios.
            carpeta = self._carpeta_de(run, origin)
            self._sumar_filas_de_actas(run, [{**fila, "carpeta": carpeta} for fila in filas])
            # Las actas son sus unidades: un libro cuenta tantas como trae.
            run.resolutions += len(filas)
            self._record(run, job, origin)
            entrega = self._entregar_actas(run, job, origin, huella)
            # El de su subcarpeta siempre; el general, cada tanto (ver
            # `INVENTARIO_GENERAL_CADA`). Al terminar se escriben todos.
            self._escribir_inventario_de_actas(run, solo_carpeta=carpeta)
            return entrega

        produced = self._settings.output_dir / job.id
        try:
            # Recursivo: los documentos de una caja se escriben en una carpeta
            # con el nombre de la caja, y con `glob` la entrega salía vacía sin
            # decir por qué -- ni un archivo copiado, ni un error que mirar.
            files = sorted(produced.rglob("*.pdf"))
        except OSError:
            files = []

        carpeta = self._output_dir(run, origin, job)
        ruta_de_la_constancia = carpeta / constancias.NOMBRE
        entrega = Entrega(base=carpeta, constancia=ruta_de_la_constancia)
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            # Ya no se entrega en la raíz del destino: lo que se dejaba ahí no
            # lo encontraba nadie, ni la corrida siguiente.
            logger.warning("no se pudo crear %s: %s", carpeta, error)
            entrega.fallos.append(f"no se pudo crear la carpeta «{carpeta.name}»: {explicar_fallo(error)}")
            return entrega

        rehacer = run.a_rehacer.pop(str(origin), None)
        if rehacer is not None:
            self._apartar_lo_anterior(run, carpeta, None, rehacer[0])
            run.rehechos += 1
        # «Entregando» antes de copiar nada: si la corrida se corta a media
        # copia, la próxima ve una entrega cortada y la rehace entera.
        self._escribir_constancia(
            ruta_de_la_constancia,
            Constancia(origen=str(self._relative(run, origin)), tamano=huella[0], modificado_ns=huella[1], job_id=job.id),
            entrega,
        )

        self._record(run, job, origin)
        indice = (job.report or {}).get("indice_electronico")
        if indice:
            # Una caja de correspondencia lleva su Índice Electrónico en lugar
            # de la planilla, y viaja tal cual junto a sus PDF: no declara a
            # dónde se entregó, así que no hay nada que reescribir. Se copia
            # aparte y no se anota como entrega, que cuenta documentos.
            try:
                for hoja in sorted(produced.rglob(indice))[:1]:
                    destino_del_indice = unique_path(carpeta, hoja.name)
                    _copiar(hoja, destino_del_indice)
                    run.indices[carpeta.name] = destino_del_indice
            except OSError as error:
                logger.warning("no se pudo entregar el índice de %s: %s", job.filename, error)
                entrega.fallos.append(f"el índice: {explicar_fallo(error)}")
        else:
            self._write_sheet(run, job, carpeta)
            # Y la que quedó junto al trabajo, ahora que se sabe dónde acabaron
            # los PDF: es la que baja el botón de la pantalla.
            self._corregir_planilla_del_trabajo(run, job, carpeta)

        renombres: dict[str, str] = {}
        for source_file in files:
            name = source_file.name
            if name.startswith("_"):
                # Quarantine ships under the document it came from, or every
                # source in the folder would deliver a file called the same.
                name = f"{origin.stem}{name}"
            try:
                target = unique_path(carpeta, name)
                _copiar(source_file, target)
            except OSError as error:
                logger.warning("could not deliver %s: %s", source_file.name, error)
                entrega.fallos.append(f"«{source_file.name}»: {explicar_fallo(error)}")
                continue
            if target.name != source_file.name:
                renombres[source_file.name] = target.name
            run.record(
                Delivery(
                    file_name=target.name,
                    source_document=str(self._relative(run, origin)),
                    destination=str(carpeta),
                )
            )

        self._entregar_fuid(run, job, origin, carpeta, renombres)
        return entrega

    def _entregar_fuid(
        self, run: FolderRun, job: Job, origin: Path, carpeta: Path, renombres: dict[str, str]
    ) -> None:
        """El FUID de un libro de diplomas, junto a sus PDF.

        Es el inventario de su habilidad, y va en la carpeta del libro (ver
        «Dos inventarios generales»). Si el libro se retomó a medias, se suma
        a las filas que ya estaban: lo entregado es **un** FUID por libro.
        """
        from .indices import habilidad_del_proceso
        from .retomar import entregar_fuid

        informe = job.report or {}
        if habilidad_del_proceso(job) != "Libro de diplomas":
            return
        # Para el FUID general: ésta es una carpeta con un libro de diplomas.
        run.carpetas_con_fuid[self._relativa_al_destino(run, carpeta)] = carpeta
        if not informe.get("fuid"):
            return
        try:
            ruta = next(
                iter(sorted((self._settings.output_dir / job.id).rglob(informe["fuid"]))), None
            )
        except OSError:
            ruta = None
        if ruta is None:
            return
        control = run.controles.get(str(self._relative(run, origin)))
        paginas_nuevas = {
            Path(str(item["file_name"])).name: int(item["first_page"])
            for item in (informe.get("inventory") or {}).get("items") or []
            if item.get("file_name") and item.get("first_page")
        }
        try:
            entregar_fuid(
                ruta,
                carpeta,
                previo=control.antes if control else None,
                paginas_nuevas=paginas_nuevas,
                renombres=renombres,
            )
        except Exception:  # noqa: BLE001 - los PDF ya están entregados
            logger.warning("no se pudo entregar el FUID de %s", job.filename, exc_info=True)

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
                delivered_to=al_operador(destino),
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

    def _write_manifest(self, run: FolderRun, *, solo_si_cambio: bool = False) -> None:
        """Leave one spreadsheet in the destination covering the whole delivery.

        Somebody receiving six hundred PDFs needs one page saying what arrived
        and where each file came from. The per-document sheets answer that
        document by document; this answers it for the delivery.
        """
        if not run.manifest:
            return
        if solo_si_cambio and len(run.manifest) == run.manifiesto_escrito:
            return
        try:
            from ..adapters.excel_inventory import ExcelRunInventory
        except ImportError:
            return
        try:
            ExcelRunInventory().write(
                run.manifest,
                run.destination,
                source=al_operador(run.source),
                operator=run.operator,
                started_at=run.started_at,
                finished_at=run.finished_at or _now(),
            )
            run.manifiesto_escrito = len(run.manifest)
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

    def _entregar_actas(
        self, run: FolderRun, job: Job, origin: Path, huella: tuple[int, int] = (0, 0)
    ) -> Entrega:
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
            copias = []
        ruta_de_la_constancia = self._ruta_de_la_constancia(run, origin, actas=True)
        entrega = Entrega(base=espejo, constancia=ruta_de_la_constancia, archivos=[hasta for _, hasta in copias])
        rehacer = run.a_rehacer.pop(str(origin), None)
        if rehacer is not None and rehacer[1] is not None:
            # Sólo con constancia: el espejo lo comparten varios PDF y, sin la
            # lista de lo suyo, se reemplaza al copiar, como siempre.
            self._apartar_lo_anterior(run, espejo, rehacer[1], rehacer[0])
            run.rehechos += 1
        # La espejo la comparten todos los PDF de la subcarpeta: la constancia
        # «entregando» ya lista lo que se va a copiar, para poder apartarlo si
        # la copia se corta.
        self._escribir_constancia(
            ruta_de_la_constancia,
            Constancia(
                origen=str(self._relative(run, origin)),
                tamano=huella[0],
                modificado_ns=huella[1],
                job_id=job.id,
                archivos=[{"ruta": hasta.relative_to(espejo).as_posix(), "bytes": -1} for _, hasta in copias],
            ),
            entrega,
        )
        for desde, hasta in copias:
            try:
                hasta.parent.mkdir(parents=True, exist_ok=True)
                _copiar(desde, hasta)
            except OSError as error:
                logger.warning("no se pudo entregar %s: %s", hasta.name, error)
                entrega.fallos.append(f"«{hasta.name}»: {explicar_fallo(error)}")
                continue
            run.record(
                Delivery(
                    file_name=hasta.name,
                    source_document=str(self._relative(run, origin)),
                    destination=str(hasta.parent),
                )
            )
        return entrega

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
        con_general = (
            solo_carpeta is None
            or time.monotonic() - run.inventario_general_en >= INVENTARIO_GENERAL_CADA
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

            if con_general or solo_carpeta == self._raiz(run):
                filas = inventario_de_la_carpeta(run.inventario_filas)
                run.inventario_validacion = validar_inventario(filas)
            else:
                # Sólo la subcarpeta del acta que llegó: sus folios se deducen
                # dentro de ella y nunca de una a otra, así que basta con sus
                # filas. Con todas, cada acta reordenaba la corrida entera.
                filas = inventario_de_la_carpeta(run.filas_por_carpeta.get(solo_carpeta, []))
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
                # Desde que terminó de escribirse: medido desde antes, una
                # escritura más larga que el intervalo se encadenaba sin pausa.
                run.inventario_general_en = time.monotonic()
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
            "carpeta": al_operador(run.source),
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
        """Avisa a la pantalla. Desde un hilo de entrega, a través del bucle.

        Las colas de quienes miran son de asyncio y no se pueden tocar desde
        otro hilo: el aviso se perdía o despertaba tarde a quien esperaba.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            if self._loop is not None and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._publicar_ya, run)
                return
        self._publicar_ya(run)

    def _publicar_ya(self, run: FolderRun) -> None:
        try:
            self._registry.announce(run.as_dict())
        except Exception:  # noqa: BLE001 - telemetry never breaks the work
            logger.debug("could not publish folder run state", exc_info=True)

    # -- la constancia de entrega ---------------------------------------------

    @staticmethod
    def _escribir_constancia(ruta: Path, constancia: Constancia, entrega: Entrega) -> None:
        try:
            constancias.escribir(ruta, constancia)
        except OSError as error:
            logger.warning("no se pudo escribir la constancia %s: %s", ruta, error)
            entrega.fallos.append(f"la constancia de entrega: {explicar_fallo(error)}")

    def _dejar_constancia(
        self, run: FolderRun, job: Job, origin: Path, huella: tuple[int, int], entrega: Entrega
    ) -> None:
        """La constancia «completa» de un PDF entregado entero: la próxima corrida lo salta.

        Lleva lo que los generales necesitan de él -- su fila de procesos, sus
        actas, sus unidades --, para que la corrida que lo salte lo siga
        contando sin abrir nada.
        """
        from .indices import fila_de_proceso, habilidad_del_proceso

        if entrega.archivos is None:
            try:
                rutas = [
                    ruta
                    for ruta in entrega.base.iterdir()
                    if ruta.is_file()
                    and ruta.name != constancias.NOMBRE
                    and not ruta.name.endswith((".part", ".tmp"))
                ]
            except OSError:
                rutas = []
        else:
            rutas = entrega.archivos
        informe = job.report or {}
        carpeta = self._carpeta_de(run, origin)
        constancia = Constancia(
            origen=str(self._relative(run, origin)),
            tamano=huella[0],
            modificado_ns=huella[1],
            estado=EstadoDeEntrega.COMPLETA,
            archivos=constancias.archivos_de(entrega.base, sorted(rutas)),
            habilidad=habilidad_del_proceso(job),
            job_id=job.id,
            proceso=asdict(fila_de_proceso(job, self._destino_relativo(run, job))),
            actas=[{**fila, "carpeta": carpeta} for fila in informe.get("inventario_actas") or []],
            unidades=[
                {**item, "source_document": origin.name}
                for item in ((informe.get("inventory") or {}).get("items") or [])
            ]
            if not informe.get("indice_electronico")
            else [],
        )
        try:
            constancias.escribir(entrega.constancia, constancia)
        except OSError as error:
            # Sin ella la próxima corrida lo tomará por una entrega de antes y
            # lo saltará igual si su carpeta trae PDF: no se pierde nada.
            logger.warning("no se pudo cerrar la constancia de %s: %s", origin.name, error)
        if getattr(self._settings, "liberar_salidas", False):
            self._liberar_salidas(job)

    def _liberar_salidas(self, job: Job) -> None:
        """Borra de salidas los PDF que ya están en el destino (ver ``liberar_salidas``)."""
        producido = self._settings.output_dir / job.id
        try:
            for pdf in producido.rglob("*.[pP][dD][fF]"):
                pdf.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("no se pudieron liberar las salidas de %s: %s", job.filename, error)

    def _apartar_lo_anterior(
        self, run: FolderRun, base: Path, constancia: Constancia | None, vigencia: Vigencia
    ) -> None:
        """Aparta lo que se entregó antes de rehacer un PDF, para no dejar «(2)».

        En la carpeta propia del PDF, todo lo que hay en ella; en el espejo de
        las actas, que comparten varios PDF, sólo lo que su constancia lista.
        Se mueve a ``_reemplazados/<fecha>``, no se borra: es trabajo entregado,
        y si sobra lo decide el operador.
        """
        sello = datetime.now().strftime("%Y%m%d-%H%M%S")
        apartado = base / REEMPLAZADOS_DIR / sello
        if constancia is None:
            try:
                rutas = [ruta for ruta in base.iterdir() if ruta.is_file()]
            except OSError:
                rutas = []
        else:
            rutas = [base / str(archivo.get("ruta")) for archivo in constancia.archivos]
        movidos = 0
        for ruta in rutas:
            if ruta.name == constancias.NOMBRE or not ruta.exists():
                continue
            try:
                relativa = ruta.relative_to(base)
                (apartado / relativa).parent.mkdir(parents=True, exist_ok=True)
                os.replace(ruta, apartado / relativa)
                movidos += 1
            except (OSError, ValueError) as error:
                logger.warning("no se pudo apartar %s: %s", ruta, error)
        if movidos:
            self._avisar(
                run,
                f"«{base.name}»: la entrega anterior ({vigencia}) se rehízo; lo que había "
                f"quedó en {REEMPLAZADOS_DIR}\\{sello}.",
            )


@dataclass(slots=True)
class Entrega:
    """Lo que dejó la copia de un PDF en el destino, y lo que no se pudo copiar."""

    #: La carpeta respecto de la que se listan los archivos de la constancia.
    base: Path
    #: Dónde va la constancia.
    constancia: Path
    #: Lo copiado, o ``None`` para tomar todo lo que hay en ``base``.
    archivos: list[Path] | None = None
    fallos: list[str] = field(default_factory=list)


def _copiar(desde: Path, hasta: Path) -> None:
    """Copia entera o nada: primero a «.part» y luego, comprobada, a su nombre.

    Una copia que se cortaba -- la red, el disco lleno -- dejaba un PDF a medias
    con su nombre definitivo, y la corrida siguiente lo daba por entregado.
    """
    parcial = hasta.with_name(hasta.name + ".part")
    try:
        shutil.copy2(desde, parcial)
        if parcial.stat().st_size != desde.stat().st_size:
            raise OSError(errno.EIO, "la copia quedó incompleta", str(hasta))
        os.replace(parcial, hasta)
    except BaseException:
        try:
            parcial.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _acumular(retirados: dict, job: Job) -> None:
    """Suma a ``retirados`` lo que un documento aportaba al panel de la carpeta."""
    from .jobs import FAILED_MARK

    progreso = job.progress
    procedencias = retirados["procedencias"]
    for clave, cuantas in (progreso.by_provenance or {}).items():
        procedencias[clave] = procedencias.get(clave, 0) + int(cuantas or 0)
    retirados["revision"] += sum(1 for marca in progreso.marks if marca == FAILED_MARK)
    retirados["fallidas"] += int(progreso.failed_pages or 0)
    consumo = progreso.consumo or (job.report or {}).get("consumo")
    if isinstance(consumo, dict) and consumo.get("peticiones"):
        retirados["consumo"] = _sumar_consumo(retirados["consumo"], consumo)


_CAMPOS_DEL_CONSUMO = (
    "peticiones",
    "paginas_facturadas",
    "tokens_entrada",
    "tokens_salida",
    "tokens_cache",
    "tokens",
    "rechazos",
    "fallos",
)


def _sumar_consumo(total: dict | None, otro: dict) -> dict:
    """Dos consumos en uno, como ``sumarConsumos`` en la pantalla."""
    if total is None:
        return {
            "proveedores": {},
            **{campo: int(otro.get(campo) or 0) for campo in _CAMPOS_DEL_CONSUMO},
            "coste_estimado": otro.get("coste_estimado"),
            "moneda": otro.get("moneda"),
        }
    suma = {campo: int(total.get(campo) or 0) + int(otro.get(campo) or 0) for campo in _CAMPOS_DEL_CONSUMO}
    coste = (
        None
        if total.get("coste_estimado") is None or otro.get("coste_estimado") is None
        else float(total["coste_estimado"]) + float(otro["coste_estimado"])
    )
    return {"proveedores": {}, **suma, "coste_estimado": coste, "moneda": total.get("moneda") or otro.get("moneda")}
