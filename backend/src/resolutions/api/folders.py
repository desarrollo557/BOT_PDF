from __future__ import annotations

import asyncio
import contextlib
import errno
import json
import logging
import os
import re
import shutil
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from functools import partial
from itertools import islice
from pathlib import Path
from queue import Empty, Full, Queue
from uuid import uuid4

from ..adapters import red_smb
from ..adapters.coordinacion_en_disco import CerrojoOcupado, ReclamoPerdido
from ..adapters.excel_inventory import (
    NOMBRE_DEL_CONTROL_DE_ENTREGA,
    NOMBRE_DEL_INVENTARIO_DE_PROCESOS,
)
from ..application.coordinacion import (
    CORRIDA_TERMINADA,
    MODOS_DE_PARAR,
    NO_ES_COMPARTIDA,
    NO_ESTA_EN_LA_CORRIDA,
    OrdenNoPermitida,
    equipo_en_palabras,
    por_que_no_se_puede_parar,
    resumen_de_la_corrida_sola,
    resumen_de_los_equipos,
)
from ..application.orden_del_recorrido import lo_pendiente_primero, nombre_de_la_carpeta
from ..application.revisor_de_cortes import AgenteDeLaCorrida
from ..domain.ritmo import AvanceDeLaDescarga, Ritmo
from . import constancia as constancias
from .constancia import Constancia, EstadoDeEntrega, Vigencia
from .errores import archivo_en_uso, explicar_fallo
from .jobs import IN_FLIGHT, Job, JobRegistry, JobState
from .planificador import Planificador
from .reintentos import merece_otra_vuelta
from .retomar import ControlDeUnLibro, HuellasDelOrigen, Retomar
from .rutas_del_equipo import al_operador, al_servicio, por_que_no_se_ve
from .settings import Settings

logger = logging.getLogger(__name__)

#: Lo que lleva detrás del nombre de la carpeta elegida la carpeta de la corrida
#: en el destino: «14. ENFERMERIA 3277-3283 P - PROCESADO».
SUFIJO_DE_LA_CORRIDA = " - PROCESADO"


def destino_de_la_corrida(source: str, destination: str) -> str:
    """La carpeta de la corrida dentro del destino elegido en la pantalla.

    Lo pidió el operador el 2026-10-30, para todo el software: en la raíz del
    destino, una carpeta con el nombre de la elegida y «- PROCESADO», y dentro
    sus cajas, sus UPD y todos sus Excel. Si ya eligió esa carpeta, se respeta;
    y también si eligió una entrega anterior de esa misma carpeta
    (``es_entrega_anterior``), aunque se llame de otra manera.
    """
    import ntpath

    # Como en `validate_folders`: una ruta pegada con comillas o espacios.
    source, destination = clean_path(source), clean_path(destination)
    nombre = ntpath.basename(source.rstrip("\\/")) or "RAIZ"
    destino = destination.rstrip("\\/")
    if not source.strip() or not destino or ntpath.basename(destino) == f"{nombre}{SUFIJO_DE_LA_CORRIDA}":
        return destination
    if es_entrega_anterior(source, destination):
        return destination
    separador = "/" if "/" in destino and "\\" not in destino else "\\"
    return f"{destino}{separador}{nombre}{SUFIJO_DE_LA_CORRIDA}"


def _nombre_plano(texto: str) -> str:
    """«Magangüe_procesado» -> «MAGANGUE PROCESADO»: sin tildes, en mayúsculas, con espacios."""
    import unicodedata

    sin_tildes = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", sin_tildes.upper()).split())


def es_entrega_anterior(source: str, destination: str) -> bool:
    """Si el destino elegido ya es una entrega del bot de esa misma carpeta: se sigue en ella.

    Lo pidió el operador el 2026-11-04. MAGANGUE se entregó el 2026-10-28 en
    «MAGANGUE PROCESADO», antes de la regla de «- PROCESADO»; al relanzarla
    para las cajas que faltaban, el bot abría «MAGANGUE PROCESADO\\MAGANGUE -
    PROCESADO», vacía: no veía las constancias de las 29 971 cajas entregadas
    y las habría vuelto a procesar -- y a pagar --. Con el destino tal cual,
    cada PDF encuentra su constancia y se salta lo ya entregado.

    Es una entrega si en su raíz están los Excel generales que deja el bot, y es
    de esa carpeta si su nombre empieza por el de la carpeta elegida
    («MAGANGUE PROCESADO» para «MAGANGUE»): una entrega de otra carpeta no se
    mezcla con ésta. Una carpeta de red que el servicio lee por su cliente SMB
    no se mira: ahí no se puede entregar.
    """
    import ntpath

    from ..adapters.analisis_de_la_entrega import NOMBRE_DEL_ANALISIS
    from ..adapters.excel_inventory import NOMBRE_DEL_INVENTARIO_DE_PROCESOS
    from ..adapters.indice_electronico import NOMBRE_DEL_INDICE

    source, destination = clean_path(source), clean_path(destination)
    nombre = _nombre_plano(ntpath.basename(source.rstrip("\\/")))
    elegido = _nombre_plano(ntpath.basename(destination.rstrip("\\/")))
    if not nombre or not (elegido == nombre or elegido.startswith(f"{nombre} ")):
        return False
    ruta = al_servicio(destination)
    if red_smb.por_smb(ruta):
        return False
    carpeta = Path(ruta).expanduser()
    try:
        return any(
            (carpeta / general).is_file()
            for general in (NOMBRE_DEL_ANALISIS, NOMBRE_DEL_INVENTARIO_DE_PROCESOS, NOMBRE_DEL_INDICE)
        )
    except OSError:
        return False

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
#: Y con varios equipos sobre el mismo destino: los escribe uno solo -- el
#: principal desde el 2026-11-27; antes, el del rol «generales» --, y menos a
#: menudo. Los siete reescribían los mismos Excel cada 45 s, cada reescritura
#: miraba unos 6 000 índices de NIC y tardaba más de 10 min, y los otros seis
#: preguntaban por el turno una vez por segundo: cerca de un millón de idas y
#: vueltas al día contra el destino (2026-11-25). Los definitivos, con todo,
#: los escribe el principal al cerrar.
INVENTARIO_GENERAL_CADA_COMPARTIDA = 15 * 60.0
#: Cuánto espera el turno de los generales quien escribe los de a mitad de
#: corrida: si está ocupado, ya los está escribiendo otro.
ESPERA_DEL_TURNO_A_MITAD = 30.0


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
#: Lo que el bot deja en la carpeta de un PDF entregado: sus PDF y sus Excel.
#: Sin constancia, sólo eso se aparta al rehacer; lo demás no es suyo.
EXTENSIONES_DEL_BOT = frozenset({".pdf", ".xlsx"})


#: Cuántas veces se reanuda una corrida tras un fallo que no es de ningún
#: documento antes de darla por fallida.
TROPIEZOS_DE_LA_CORRIDA = 3
#: Segundos de espera tras el primer tropiezo; el segundo espera el doble, y así.
ESPERA_TRAS_TROPIEZO = 30.0


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


class EquipoNoEncontrado(LookupError):
    """La corrida o el equipo al que se le quiere ordenar parar no está; el motivo va en palabras."""


# ``OrdenNoPermitida`` es la de ``application.coordinacion``, la misma que lanza la
# coordinación al escribir la orden: con una copia aquí, la de un equipo que se
# acababa de retirar salía como un 500 y no como el 409 que es (2026-11-26).


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
    #: El acta de transferencia del inventario de Kingspan, que el operador
    #: eligió para la carpeta. Se copia a cada archivo que entre.
    acta: str | None = None
    #: La oficina productora de la cabecera del FUID («FACULTAD DE MEDICINA»).
    #: La escribe el operador o se averigua al empezar (ver
    #: ``oficina_de_la_carpeta_de_origen``); se copia a cada archivo que entre.
    oficina: str | None = None
    #: Si ya se averiguó: una corrida que se reanuda no la vuelve a buscar.
    oficina_mirada: bool = False
    #: Si la escribió el operador: entonces manda en todos los FUID; si no, la
    #: de cada subcarpeta que nombre su facultad pasa por delante.
    oficina_del_operador: bool = False
    #: Los folios -- las hojas de papel -- que el inventario del cliente anota
    #: de cada UPD, para la fila de un PDF inventariado entero (opción B del
    #: operador, 2026-10-30); la caja de cada UPD, para la fila que no la tiene
    #: en su ruta; y si ya se miraron.
    folios_del_cliente: dict[str, int] = field(default_factory=dict, repr=False)
    cajas_del_cliente: dict[str, str] = field(default_factory=dict, repr=False)
    folios_mirados: bool = False
    #: Y qué clase de documento trae esta carpeta, cuando el operador lo sabe.
    #: Una carpeta suele ser homogénea -- una estantería de libros de diplomas
    #: --, así que declararlo una vez vale para todos sus archivos.
    tipo: str = "auto"
    #: Y qué plantilla de inventario llevar para una caja de correspondencia:
    #: el índice electrónico de siempre (``None``), el inventario Kingspan o
    #: «mixto», que deja decidir al contenido. Vale para toda la corrida, como
    #: el corte, porque una caja suele ser un mismo material.
    tipo_documento: str | None = None
    #: Si esta corrida retoma una entrega anterior: ``faltantes`` procesa sólo
    #: lo que no está en el destino, ``revisar`` sólo lo mira. Sólo para
    #: libros de diplomas (ver ``retomar.py``).
    retomar: str = "no"
    #: Cuántos PDF de esta carpeta a la vez, si el operador lo eligió. ``None``
    #: es el automático del planificador.
    paralelo: int | None = None
    #: Si el destino ya es la carpeta de la corrida aunque no se llame
    #: «<carpeta> - PROCESADO»: una entrega anterior de la misma carpeta
    #: (``es_entrega_anterior``). Dentro no se repite el nombre de la elegida.
    en_su_carpeta: bool = False
    #: A cuántos minutos sin avance el vigilante da un documento por atascado.
    #: La pantalla lo dice tal cual: «si sigue así» no decía cuándo.
    minutos_sin_avance: float = 0.0
    #: Hasta cuántos archivos a la vez se pueden elegir en marcha: los procesos del equipo.
    paralelo_maximo: int = 0
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
    #: Los PDF que se bajan de la red antes de tener trabajo -- al retomar se
    #: baja primero para ver qué falta en el destino --, por su ruta, con cómo
    #: va su descarga. Los que ya tienen trabajo lo llevan en él
    #: (``JobProgress.descarga``). Sólo se toca desde el bucle.
    bajando: dict[str, dict] = field(default_factory=dict)
    #: Cuándo se publicó la corrida por última vez por lo que baja: una vez por segundo.
    bajando_publicado: float = 0.0
    #: Every document this run created, in the order it took them. The screen
    #: needs it to report on the run as a whole once it settles.
    job_ids: list[str] = field(default_factory=list)
    #: One entry per delivered resolution, for the spreadsheet that is left in
    #: the destination folder. Kept whole -- unlike `deliveries`, which is a
    #: window for the live view -- because the sheet has to list every file.
    manifest: list[dict] = field(default_factory=list)
    #: Las filas del inventario de cada PDF -- un acta, un graduado, un
    #: estudiante --, en el orden en que se tomaron. Con ellas se escribe el
    #: FUID de cada subcarpeta y el general de la corrida: una carpeta de cien
    #: actas son cien filas de una planilla, no cien planillas de una fila.
    inventario_filas: list[dict] = field(default_factory=list)
    #: Dónde quedó el FUID general, cuando ya se escribió.
    inventario: str | None = None
    #: El FUID de cada subcarpeta: si se escribió con otro nombre porque el
    #: suyo estaba abierto, los PDF siguientes vuelven a ése en vez de dejar un
    #: «(3)», un «(4)»… por cada uno.
    inventarios_de_carpeta: dict[str, str] = field(default_factory=dict)
    #: Las subcarpetas cuyo FUID hay que reescribir. La entrega sólo las apunta,
    #: bajo el cerrojo, y se escriben fuera de él: escribir un FUID tarda de uno
    #: a cuatro segundos, y dentro del cerrojo las entregas en paralelo hacían
    #: cola detrás (diez actas: 22 s en vez de 3, medido el 2026-10-30).
    fuid_pendientes: set[str] = field(default_factory=set, repr=False)
    #: Cuántas veces cambiaron las filas de cada subcarpeta, y en qué versión se
    #: escribió su FUID: al terminar se reescriben sólo las que cambiaron.
    version_de_carpeta: dict[str, int] = field(default_factory=dict, repr=False)
    version_escrita: dict[str, tuple[int, int]] = field(default_factory=dict, repr=False)
    #: Uno solo escribe los FUID de la corrida a la vez.
    cerrojo_de_escritura: threading.Lock = field(default_factory=threading.Lock, repr=False)
    #: El nombre de cada acta suelta entregada con el de su fila, por carpeta
    #: espejo: {nombre en minúsculas: el origen que lo tiene}. Dos sueltas que
    #: se llamaran igual se pisaban al copiar (la revisión, 2026-11-13).
    nombres_de_sueltas: dict[str, dict[str, str]] = field(default_factory=dict, repr=False)
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

    #: Si el origen y el destino están en la red o en este equipo, y a qué
    #: velocidad se leen y se escriben de verdad. Lo pidió el operador el
    #: 2026-11-05: «que si es por red el bot me diga y estime en realidad cuánto
    #: es la velocidad de la red y cuánto podría demorar». Ver
    #: ``domain/ritmo.py`` y ``adapters/acceso.py``.
    origen_de_red: bool | None = None
    destino_de_red: bool | None = None
    ritmo_de_lectura: Ritmo = field(default_factory=Ritmo, repr=False)
    ritmo_de_escritura: Ritmo = field(default_factory=Ritmo, repr=False)
    #: La prueba del arranque: su estado («midiendo», «hecha») y lo que dio.
    prueba_de_red: dict = field(default_factory=dict)
    #: Si ya hay quien mide: una corrida que se reanuda no arranca otro.
    midiendo: bool = False
    #: Cuándo (reloj monótono) terminó cada PDF de la cola: el ritmo de la corrida.
    terminados_en: deque = field(default_factory=lambda: deque(maxlen=200), repr=False)
    #: Si el recorrido del origen terminó: hasta entonces lo que falta es «al menos».
    recorrido_terminado: bool = False
    #: Lo medido de cada PDF -- su descarga y su entrega, bytes y segundos --,
    #: para su fila del inventario general de procesos.
    medidas_del_pdf: dict[str, dict[str, tuple[int, float]]] = field(default_factory=dict, repr=False)
    #: Lo que hizo el revisor de cortes con cada PDF de la corrida, sumado, y lo
    #: último que corrigió o mandó a revisión (2026-11-05: «que se muestre el
    #: trabajo del agente revisando todo en el front»).
    agente: AgenteDeLaCorrida = field(default_factory=AgenteDeLaCorrida, repr=False)
    #: La auditoría de cierre (2026-11-05): el origen contra el destino
    #: (``comparacion``) y la muestra de 100 PDF revisada otra vez
    #: (``auditoria``), y cómo termina la corrida por ellas (``etapa``).
    comparacion: dict | None = None
    auditoria: dict | None = None
    etapa: str | None = None
    etapa_detalle: str = ""
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
    #: Y de cada Índice Electrónico entregado, para el libro general.
    lecturas_de_indices: dict = field(default_factory=dict, repr=False)
    #: Lo que cada PDF entregado sumó a la corrida -- sus filas de actas, sus
    #: unidades del manifiesto, sus resoluciones --, para retirarlo si el mismo
    #: PDF se rehace en la vuelta final: se sumaba dos veces.
    aportes: dict[str, tuple[list, list, int]] = field(default_factory=dict, repr=False)
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
    #: La memoria de la corrida -- sus filas, sus cuentas, sus entregas --, de
    #: un hilo a la vez. Es de hilos y no de asyncio porque la entrega corre en
    #: un hilo, y uno que ya arrancó no se detiene aunque se cancele quien lo
    #: esperaba.
    #:
    #: En la entrega plana (la caja de correspondencia) **sólo guarda la
    #: memoria**: con él tomado no se escribe en el destino ni se pide otro
    #: cerrojo. Lo que escribe en la carpeta de un NIC va con su turno, y así
    #: varias entregas a NIC distintos van a la vez. Hasta el 2026-11-25 cada
    #: entrega escribía en el destino con él tomado: un PC entregaba de uno en
    #: uno, unos 20 s cada PDF contra un servidor lento, y los ya leídos
    #: esperaban 14-29 min. **El orden de los cerrojos es siempre el mismo**:
    #:
    #: 1. el turno de la carpeta entre equipos (``_turno_de``);
    #: 2. el de la carpeta en este proceso (``cerrojo_de_la_carpeta``);
    #: 3. el turno de entregas del equipo (``FolderRunner._entregas``): sólo lo
    #:    pide quien ya puede escribir, y esperar la carpeta de otro equipo no
    #:    deja sin entregar a las demás;
    #: 4. éste, breve y sin nada dentro.
    #:
    #: Las demás habilidades -- actas, diplomas, Kingspan, que comparten
    #: carpetas espejo y planillas -- siguen entregando de una en una con él.
    cerrojo: threading.RLock = field(default_factory=threading.RLock, repr=False)
    #: Lo que el recorrido ya metió en la cola o dejó para la segunda pasada y
    #: todavía no se tomó. Al volver a recorrer tras una caída del origen se
    #: salta como lo visto: lo encolaba otra vez y se leía y pagaba dos veces.
    encolados: set[str] = field(default_factory=set, repr=False)
    #: La raíz del destino, listada una vez por recorrido (2026-11-26): por dónde
    #: empezar y qué PDF van por el carril rápido. Sólo mientras dura el
    #: recorrido (``_lotes_del_origen``); sin ella, el orden de ruta de siempre.
    destino_listado: DestinoListado | None = field(default=None, repr=False)
    #: Los PDF que este equipo está leyendo o entregando ahora (su ruta).
    tomados: set[str] = field(default_factory=set, repr=False)
    #: Los entregados por otro equipo que se contaron sin leer su constancia
    #: (la segunda pasada, por su reclamo «hecho»): el que cierra la lee.
    contados_sin_constancia: set[str] = field(default_factory=set, repr=False)
    #: Las carpetas de NIC entregadas a la manera de antes -- con el UPD delante
    #: y un índice por UPD -- que hay que ordenar aunque no se procese nada.
    cajas_por_ordenar: set[Path] = field(default_factory=set, repr=False)
    #: Qué se decidió de cada PDF al verificar lo ya entregado, y por qué
    #: (ruta relativa → (decisión, motivo)): lo que lee el análisis de la entrega.
    verificaciones: dict[str, tuple[str, str]] = field(default_factory=dict, repr=False)
    #: El motivo de la última verificación de cada PDF (ruta → motivo).
    motivos: dict[str, str] = field(default_factory=dict, repr=False)
    #: Dónde quedó «00.ANALISIS DE LA ENTREGA.xlsx», cuando ya se escribió.
    analisis: str | None = None
    #: La corrida compartida con otros equipos sobre el mismo destino
    #: (``adapters.coordinacion_en_disco``), o ``None`` si este equipo va solo.
    coordinacion: object | None = field(default=None, repr=False)
    #: Lo que dice la pantalla de la corrida compartida: quién la empezó, cuántos equipos.
    compartida: str = ""
    #: Los PDF que tiene otro equipo en curso (ruta → equipo): se esperan al final.
    ajenos: dict[str, str] = field(default_factory=dict, repr=False)
    #: Los que este equipo dejó para la segunda pasada: su carpeta es de otro.
    diferidos: list[Path] = field(default_factory=list, repr=False)
    #: Los de la segunda pasada, que ya no se vuelven a diferir.
    segunda_pasada: set[str] = field(default_factory=set, repr=False)
    #: Los que se tomaron de un equipo caído: se hacen aquí aunque allí fallaran.
    de_caidos: set[str] = field(default_factory=set, repr=False)
    #: El reclamo de cada PDF que este equipo tiene en curso (ruta → reclamo).
    reclamos: dict[str, object] = field(default_factory=dict, repr=False)
    #: Los reclamos, de uno en uno y en el orden de la carpeta.
    orden_de_toma: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    #: Los que entregó otro equipo de la corrida y ya se contaron aquí.
    contados_de_otro: set[str] = field(default_factory=set, repr=False)
    de_otros_equipos: int = 0
    #: Los que fallaron en otro equipo (ruta relativa → equipo y motivo).
    fallidos_en_otro: dict[str, str] = field(default_factory=dict, repr=False)
    #: Lo repetido en el destino al cerrar (``api.repetidos``), en palabras.
    repetidos: list[str] = field(default_factory=list, repr=False)
    #: Los trabajos con que otros equipos entregaron sus PDF de esta corrida:
    #: la auditoría de la corrida es una sola, con los de todos.
    trabajos_de_otros: list[str] = field(default_factory=list, repr=False)
    #: El monitoreo de equipos (2026-11-26). La orden de «Parar con calma» que
    #: cumple este equipo: termina lo que tiene en curso y no toma nada nuevo.
    parando: dict | None = None
    #: Quién lo detuvo con una orden de parar, en palabras: completa «Detenido por …».
    detenido_por: str | None = None

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
            "acta": self.acta,
            "oficina": self.oficina,
            "tipo": self.tipo,
            "tipo_documento": self.tipo_documento,
            "retomar": self.retomar,
            "paralelo": self.paralelo,
            "paralelo_maximo": self.paralelo_maximo,
            "minutos_sin_avance": self.minutos_sin_avance,
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
            # Lo procesado y lo que no, por carpeta y por PDF, con el porqué.
            "analisis": Path(self.analisis).name if self.analisis else None,
            "analisis_ruta": al_operador(self.analisis) if self.analisis else None,
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
            # Lo que se baja de la red sin trabajo todavía (al retomar).
            "bajando": [{"nombre": nombre, "descarga": dict(datos)} for nombre, datos in self.bajando.items()],
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
            # Red o local, la velocidad medida y lo que falta (2026-11-05).
            "red": self.resumen_de_la_red(),
            # Lo que el revisor de cortes lleva hecho en la corrida (2026-11-05);
            # nada hasta que revisa el primer PDF.
            "agente": self.agente.as_dict() if self.agente.pdf else None,
            # La auditoría de cierre: el cuadre, la muestra y cómo terminó.
            "comparacion": self.comparacion,
            "auditoria": self.auditoria,
            "etapa": self.etapa,
            "etapa_detalle": self.etapa_detalle,
            # Varios equipos sobre el mismo destino (2026-11-25).
            "compartida": self.compartida or None,
            "equipo": getattr(self.coordinacion, "id", None),
            "equipos_vivos": len(self.coordinacion.equipos_vivos()) if self.coordinacion is not None else 0,
            # La orden de parar con calma que cumple, y quién lo detuvo con una (2026-11-26).
            "parando": dict(self.parando) if self.parando else None,
            "detenido_por": self.detenido_por,
            "de_otros_equipos": self.de_otros_equipos,
            "en_otro_equipo": len(self.ajenos),
            "fallidos_en_otro": len(self.fallidos_en_otro),
            "repetidos": self.repetidos[:50],
            # Newest first: the live view reads from the top.
            "deliveries": [item.as_dict() for item in reversed(self.deliveries)],
        }

    def velocidades(self) -> tuple[float | None, float | None]:
        """Lectura del origen y escritura en el destino, en MB/s: lo de en vivo, o si no aún, la prueba."""
        lectura = self.ritmo_de_lectura.mb_por_segundo() or self.prueba_de_red.get("lectura_mb_s")
        escritura = self.ritmo_de_escritura.mb_por_segundo() or self.prueba_de_red.get("escritura_mb_s")
        return lectura, escritura

    def resumen_de_la_red(self) -> dict[str, object]:
        """Lo que la pantalla enseña de la red: el acceso de cada lado, su velocidad y lo que falta."""
        from ..domain.ritmo import duracion_legible, estimar, velocidad_legible

        lectura, escritura = self.velocidades()
        # Una copia de los valores: el recorrido los añade desde su hilo.
        pendientes_en_bytes = sum(tamano for tamano, _fecha in list(self.huellas_del_origen.values()))
        activa = self.active
        estimacion = estimar(
            pendientes=len(self.queue) + len(self.en_curso) if activa else 0,
            terminados_en=tuple(self.terminados_en),
            ahora=time.monotonic(),
            bytes_pendientes=pendientes_en_bytes if activa else 0,
            lectura_mb_s=lectura,
            escritura_mb_s=escritura,
            origen_de_red=bool(self.origen_de_red),
            destino_de_red=bool(self.destino_de_red),
            recorrido_terminado=self.recorrido_terminado or not activa,
        )

        def acceso(de_red: bool | None) -> str | None:
            return None if de_red is None else ("red" if de_red else "local")

        return {
            "origen": {"acceso": acceso(self.origen_de_red), "mb_s": lectura, "velocidad": velocidad_legible(lectura)},
            "destino": {
                "acceso": acceso(self.destino_de_red),
                "mb_s": escritura,
                "velocidad": velocidad_legible(escritura),
            },
            "prueba": dict(self.prueba_de_red),
            "falta_s": estimacion.total,
            "falta": duracion_legible(estimacion.total),
            "red_s": estimacion.red,
            "falta_red": duracion_legible(estimacion.red),
            "al_menos": estimacion.al_menos,
        }


#: Every quote character a pasted path realistically arrives wrapped in. The
#: curly ones come from paths that passed through Word, Outlook or a chat app,
#: which substitute them silently.
_QUOTES = "\"'“”‘’«»"


def en_orden_de_ruta(raiz: Path, al_fallar: Callable[[OSError], None] | None = None):
    """Los PDF de ``raiz`` y sus subcarpetas, a medida que se leen, en orden de ruta.

    Orden de ruta, como el de antes de los lotes: archivos y subcarpetas de una
    carpeta mezclados por nombre -- «a.pdf», «b\\1.pdf», «c.pdf» --, que es lo
    que mantiene juntos los documentos de una caja. Se lee una carpeta cada vez,
    cuando le toca: nunca el árbol entero antes de empezar.

    Cada nivel con ``os.walk`` y no con ``rglob``: ``rglob`` se salta en
    silencio una subcarpeta que no se deja leer -- la red que parpadea, un
    permiso --; ``os.walk`` se la cuenta a ``al_fallar``. ``_procesados`` no se
    recorre: bajo MOVE los originales se apartan ahí.
    """

    def nivel(carpeta: str) -> list[tuple[str, bool]]:
        return _primer_nivel(carpeta, al_fallar)

    pila = [(str(raiz), iter(nivel(str(raiz))))]
    while pila:
        carpeta, entradas = pila[-1]
        siguiente = next(entradas, None)
        if siguiente is None:
            pila.pop()
            continue
        nombre, es_carpeta = siguiente
        ruta = os.path.join(carpeta, nombre)
        if es_carpeta:
            pila.append((ruta, iter(nivel(ruta))))
        else:
            yield Path(ruta)


def _primer_nivel(carpeta: str, al_fallar: Callable[[OSError], None] | None = None) -> list[tuple[str, bool]]:
    """Las subcarpetas y los PDF de ``carpeta``, sin entrar en ellas: cada nivel de ``en_orden_de_ruta``.

    Una sola definición del nivel -- con ``os.walk``, sin ``_procesados``, por
    nombre sin mayúsculas -- para el recorrido que empieza por lo pendiente y
    para ``en_orden_de_ruta``, que usa también la auditoría de cierre: con dos
    copias, cambiar una sola haría que el cuadre contara cosas distintas de lo
    recorrido (2026-11-26).
    """
    for _, subcarpetas, archivos in os.walk(carpeta, onerror=al_fallar):
        entradas = [(nombre, True) for nombre in subcarpetas if nombre != CONSUMED_DIR]
        entradas += [(nombre, False) for nombre in archivos if nombre.lower().endswith(".pdf")]
        return sorted(entradas, key=lambda entrada: entrada[0].lower())
    return []


class DestinoListado:
    """La raíz del destino de una corrida, listada una sola vez por recorrido del origen.

    El operador, 2026-11-26: «que no se demore mucho buscando los ya procesados
    para comenzar a procesar». Esa mañana cada equipo tardó de 3 a 28 min desde
    que se unió hasta su primer PDF, verificando uno a uno lo ya entregado que
    tenía delante. La raíz del destino de Magangué -- 29.480 carpetas NIC -- se
    lista entera en 2,9 s; con ella el recorrido sabe qué carpetas del origen no
    están en el destino y empieza por ellas, y qué PDF no tienen constancia que
    leer porque la carpeta de la raíz donde iría no existe (el carril rápido de
    ``_repartir``).

    Sólo la raíz: una carpeta cuyo padre no existe, no existe; si la de la raíz
    sí está, lo de dentro lo dice la constancia, como siempre. Listar además
    cada carpeta que ya está, una tras otra en el hilo que verifica, salía más
    caro que verificarlas en paralelo: con 2.000 cajas de un PDF y 6 ms por
    listado, el recorrido entero pasaba de 2,1 a 16,2 s (banco del 2026-11-26).
    Sin mayúsculas, como Windows y SMB: así puede salir «está» de más, nunca
    «no está» de más. Lo que no se puede saber es ``None``, y quien pregunta
    verifica como antes.

    Vale mientras dura un recorrido: lo que esta corrida entrega después no
    cambia nada, porque lo que ya tomó se salta (``seen``). Con otros equipos,
    ``_tomar_el_pdf`` reclama cada PDF y vuelve a mirar su constancia antes de
    leerlo; sin ellos, en el destino sólo escribe esta corrida.
    """

    def __init__(self, destino: Path) -> None:
        self.destino = destino
        #: Los PDF que el recorrido mandó por el carril rápido, hasta que ``_repartir`` los decide.
        self.sin_carpeta: set[str] = set()
        self._cerrojo = threading.Lock()
        self._mirada = False
        self._nombres: frozenset[str] | None = None
        self._existe = True

    def nombres_de_la_raiz(self) -> frozenset[str] | None:
        """Los nombres de la raíz del destino, sin mayúsculas: vacío si no existe, ``None`` si no se pudo listar."""
        with self._cerrojo:
            if not self._mirada:
                self._nombres, self._existe = self._listar()
                self._mirada = True
            return self._nombres

    def existe(self, ruta: Path) -> bool | None:
        """Si ``ruta`` está en el destino: ``False`` si seguro que no, ``True`` si es de la raíz y está, ``None`` si no se sabe."""
        try:
            partes = ruta.relative_to(self.destino).parts
        except ValueError:
            return None
        nombres = self.nombres_de_la_raiz()
        if nombres is None:
            return None
        if not partes:
            return self._existe
        if partes[0].lower() not in nombres:
            return False
        return True if len(partes) == 1 else None

    def _listar(self) -> tuple[frozenset[str] | None, bool]:
        try:
            with os.scandir(self.destino) as entradas:
                return frozenset(entrada.name.lower() for entrada in entradas), True
        except (FileNotFoundError, NotADirectoryError):
            return frozenset(), False
        except Exception as error:  # noqa: BLE001 - sin saberlo, se verifica como antes
            logger.warning("no se pudo listar el destino %s para empezar por lo pendiente: %s", self.destino, error)
            return None, True


#: Lo que deja el hilo del listado del origen al acabar, y lo que da
#: ``_ListadoEnSuHilo.siguiente`` si se cumple la espera sin nada nuevo.
_FIN_DEL_LISTADO = object()
_NADA_TODAVIA = object()


@dataclass(frozen=True, slots=True)
class _FalloDelListado:
    """Lo que falló al listar el origen: sale por quien lee, detrás de lo ya listado."""

    error: Exception


class _ListadoEnSuHilo:
    """Los PDF del origen, listados en un hilo propio mientras quien los pide verifica los de antes.

    Recorrer y verificar iban en serie, en el mismo hilo: cada lote de
    constancias paraba el listado del origen, y cada listado -- 21 ms por
    carpeta de Magangué -- paraba la verificación (2026-11-26). Aquí el listado
    llena una cola acotada -- ``tope`` PDF, uno o dos lotes: la memoria no se
    llena de rutas -- y quien verifica la vacía con ``siguiente``. Lo que falle
    al listar sale por ``siguiente`` en su orden, detrás de lo ya listado.
    ``cerrar`` lo detiene: lo que tenía por delante se tira, y el hilo se va en
    cuanto vuelve del listado en que estaba.
    """

    def __init__(self, fuente: Iterator, *, tope: int) -> None:
        self._cola: Queue = Queue(maxsize=max(1, tope))
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._listar, args=(fuente,), name="recorrido-del-origen", daemon=True)
        self._hilo.start()

    def _listar(self, fuente: Iterator) -> None:
        final: object = _FIN_DEL_LISTADO
        try:
            for elemento in fuente:
                if not self._poner(elemento):
                    return
        except Exception as error:  # noqa: BLE001 - sale por quien lee, en su orden
            final = _FalloDelListado(error)
        finally:
            # Lo que listaba, cerrado: los listados de la red pedidos por delante se cancelan.
            cerrar = getattr(fuente, "close", None)
            if cerrar is not None:
                with contextlib.suppress(Exception):
                    cerrar()
        self._poner(final)

    def _poner(self, elemento: object) -> bool:
        while not self._parar.is_set():
            try:
                self._cola.put(elemento, timeout=0.2)
                return True
            except Full:
                continue
        return False

    def siguiente(self, espera: float | None = None) -> object:
        """Lo siguiente: un (ruta, huella), ``_FIN_DEL_LISTADO`` o un ``_FalloDelListado``.

        Con ``espera``, como mucho esos segundos: pasados sin nada, ``_NADA_TODAVIA``.
        """
        limite = None if espera is None else time.monotonic() + espera
        while True:
            paso = 0.5 if limite is None else min(0.5, max(0.0, limite - time.monotonic()))
            try:
                return self._cola.get(timeout=paso)
            except Empty:
                pass
            if limite is not None and time.monotonic() >= limite:
                return _NADA_TODAVIA
            if not self._hilo.is_alive() and self._cola.empty():
                # Se fue sin decir nada (no debería pasar): se recorre otra vez.
                return _FalloDelListado(FolderError("El listado del origen se cortó sin terminar"))

    def cerrar(self) -> None:
        """Detiene el listado y tira lo que tenía por delante."""
        self._parar.set()
        with contextlib.suppress(Empty):
            while True:
                self._cola.get_nowait()


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


def validate_folders(
    source: str, destination: str, *, internas: Iterable[Path] = ()
) -> tuple[Path, Path]:
    """Resolve and check both folders before a single file is touched.

    The containment check is the important one. If the destination sits inside
    the source, every delivered resolution is a new PDF in the folder being
    watched, and the run feeds on its own output forever.

    ``internas`` son las carpetas del propio servicio -- sus datos, subidas y
    salidas --: ni el origen ni el destino pueden caer dentro, y el origen
    tampoco puede contenerlas. El servicio está en la red sin contraseña, y
    con «Borrarlo» sobre una carpeta que las contiene se borraban las subidas
    de los demás (2026-10-27).
    """
    source = clean_path(source)
    destination = clean_path(destination)
    if not source or not destination:
        raise FolderError("Indique la carpeta de origen y la de destino")
    # En Docker, «C:\…» del operador está montada en otra ruta del contenedor,
    # y «Y:\…» o «Z:\…» pueden ser unidades que se leen por la red (ver
    # `rutas_del_equipo.py`). Fuera de Docker no cambia nada. Se traduce antes
    # de nada: lo de abajo pregunta si cada carpeta es de red.
    escrito = destination
    # Una unidad que el contenedor no tiene: el origen «no existía» y el
    # destino se creaba dentro del contenedor, donde nadie lo ve.
    for ruta in (source, destination):
        if motivo := por_que_no_se_ve(ruta):
            raise FolderError(motivo)
    source = al_servicio(source)
    destination = al_servicio(destination)
    # Una carpeta de red se comprueba antes de nada: si el servidor pide usuario
    # y clave, `CredencialesDeRed` sube y la pantalla los pide.
    if red_smb.es_de_red(source):
        red_smb.asegurar(source)
    if red_smb.por_smb(destination):
        # Una carpeta de red como destino (el operador, 2026-11-25: «la idea es
        # colocar como ruta destino rutas en red»): se escribe por donde está
        # montada en el contenedor. El cliente SMB propio sólo lee.
        from ..adapters.acceso import montaje_de_la_red

        montada = montaje_de_la_red(destination)
        if montada is None:
            partes = red_smb.partes(destination)
            raiz = partes.raiz if partes else escrito
            raise FolderError(
                f"Para entregar en la carpeta de red {escrito}, el bot tiene que tenerla montada "
                "en este equipo (una sola vez). En CMD, dentro de la carpeta BOT_PDF: "
                f"«net use W: {raiz} /persistent:yes» y después «powershell -NoProfile "
                "-ExecutionPolicy Bypass -File scripts\\montar-unidad-de-red.ps1 W». Luego vuelva "
                "a pegar la ruta de red. Revise también que la ruta esté bien escrita (por ejemplo "
                "«Users» y no «User»)."
            )
        destination = montada

    target = Path(destination).expanduser()
    if red_smb.por_smb(source):
        origin = Path(source)
        try:
            existe = red_smb.es_carpeta(source)
        except red_smb.RedNoDisponible as error:
            raise FolderError(str(error)) from None
        except OSError as error:
            raise FolderError(f"No se pudo leer la carpeta de red: {error}") from None
        if not existe:
            raise FolderError(f"La carpeta de origen no existe: {al_operador(source)}")
    else:
        origin = Path(source).expanduser()
        try:
            origin = origin.resolve(strict=True)
        except (OSError, FileNotFoundError):
            raise FolderError(f"La carpeta de origen no existe: {source}") from None
        if not origin.is_dir():
            raise FolderError(f"El origen no es una carpeta: {origin}")

    propias = [Path(carpeta).resolve() for carpeta in internas]

    def es_propia(ruta: Path, *, o_las_contiene: bool = False) -> bool:
        # Dentro de una propia, o -- para el origen -- conteniéndola.
        return any(
            ruta == propia or propia in ruta.parents or (o_las_contiene and ruta in propia.parents)
            for propia in propias
        )

    if not red_smb.por_smb(origin) and es_propia(origin, o_las_contiene=True):
        raise FolderError("El origen no puede ser ni contener las carpetas de trabajo del servicio")
    if any(propia == target.resolve() or propia in target.resolve().parents for propia in propias):
        raise FolderError("El destino no puede estar dentro de las carpetas de trabajo del servicio")

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise FolderError(f"No se pudo crear la carpeta de destino: {explicar_fallo(error)}") from None
    target = target.resolve()

    if target == origin:
        raise FolderError("El destino no puede ser la misma carpeta que el origen")
    if origin in target.parents:
        raise FolderError(
            "El destino no puede estar dentro del origen: los PDF generados se "
            "volverían a procesar"
        )
    if not red_smb.por_smb(origin) and target in origin.parents:
        # Al revés tampoco: con el origen dentro del destino, la carpeta de un
        # PDF entregado podía caer sobre el propio origen, y el bot sólo
        # escribe y aparta dentro del destino lo que él produjo.
        raise FolderError(
            "El origen no puede estar dentro del destino: elija una carpeta de destino "
            "aparte (por ejemplo, junto al origen y no por encima de él)"
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


#: Cuántos Excel sueltos de una carpeta de red se bajan buscando la oficina.
EXCELS_DE_LA_RED = 5


def _leer_del_cliente(carpeta: str, leer: Callable[[Path], object]) -> object:
    """Lo que ``leer`` saca del primer Excel del cliente suelto en la carpeta que lo diga; ``None`` si ninguno.

    Por la red se bajan como mucho ``EXCELS_DE_LA_RED``. Nunca falla: uno que
    no se abre o no baja se salta.
    """
    import tempfile

    from ..adapters.inventario_del_cliente import es_del_bot

    try:
        if red_smb.por_smb(carpeta):
            remotos = [r for r in red_smb.archivos(carpeta, ".xlsx") if not es_del_bot(Path(r).name)]
            with tempfile.TemporaryDirectory(prefix="cliente-") as temporal:
                for indice, remoto in enumerate(remotos[:EXCELS_DE_LA_RED]):
                    try:
                        copia = red_smb.traer(remoto, Path(temporal) / f"{indice}.xlsx")
                    except Exception:  # noqa: BLE001 - uno que no baja no tapa a los demás
                        logger.debug("no se pudo bajar %s", remoto, exc_info=True)
                        continue
                    if hallado := leer(copia):
                        return hallado
            return None
        excels = sorted(
            (r for r in Path(carpeta).glob("*.xlsx") if r.is_file() and not es_del_bot(r.name)),
            key=lambda r: r.name.lower(),
        )
        for excel in excels:
            if hallado := leer(excel):
                return hallado
    except Exception:  # noqa: BLE001 - sin el Excel del cliente se sigue sin él
        logger.debug("no se pudo mirar el Excel del cliente en %s", carpeta, exc_info=True)
    return None


def _padre_de(ruta: str) -> str:
    """La carpeta de arriba de una ruta del servicio o de red; vacío si no tiene."""
    limpia = ruta.rstrip("/\\")
    separador = "/" if "/" in limpia else "\\"
    return limpia.rsplit(separador, 1)[0] if separador in limpia else ""


def por_upd_de_la_carpeta_de_origen(ruta: str) -> tuple[dict[str, int], dict[str, str]]:
    """Los folios y la caja que el inventario del cliente anota de cada UPD: el de la carpeta o el de la de arriba.

    De una vez: por la red, cada Excel que se mira se baja una sola vez.
    """
    from ..adapters.inventario_del_cliente import cajas_por_upd, folios_por_upd

    def leer(excel: Path) -> tuple[dict[str, int], dict[str, str]] | None:
        folios, cajas = folios_por_upd(excel), cajas_por_upd(excel)
        return (folios, cajas) if folios or cajas else None

    padre = _padre_de(ruta)
    hallados = _leer_del_cliente(ruta, leer) or (_leer_del_cliente(padre, leer) if padre and padre != ruta else None)
    return hallados if isinstance(hallados, tuple) else ({}, {})


def oficina_de_la_carpeta_de_origen(ruta: str) -> str | None:
    """La oficina productora de una carpeta: su inventario del cliente o, si no, su nombre.

    La cabecera de su FUID (ver ``domain/oficina_productora.py``). Nunca
    falla: una carpeta que no se deja mirar se queda con la de la plantilla.
    """
    import tempfile

    from ..adapters.inventario_del_cliente import (
        es_del_bot,
        oficina_de_la_carpeta,
        oficina_del_excel,
    )
    from ..domain.oficina_productora import oficina_de_la_ruta

    def del_excel(carpeta: str) -> str | None:
        try:
            if red_smb.por_smb(carpeta):
                remotos = [r for r in red_smb.archivos(carpeta, ".xlsx") if not es_del_bot(Path(r).name)]
                with tempfile.TemporaryDirectory(prefix="oficina-") as temporal:
                    for indice, remoto in enumerate(remotos[:EXCELS_DE_LA_RED]):
                        try:
                            copia = red_smb.traer(remoto, Path(temporal) / f"{indice}.xlsx")
                        except Exception:  # noqa: BLE001 - uno que no baja no tapa a los demás
                            logger.debug("no se pudo bajar %s", remoto, exc_info=True)
                            continue
                        if hallada := oficina_del_excel(copia):
                            return hallada
                return None
            return oficina_de_la_carpeta(Path(carpeta))
        except Exception:  # noqa: BLE001 - sin el Excel del cliente queda el nombre de la carpeta
            logger.debug("no se pudo mirar la oficina de %s", carpeta, exc_info=True)
            return None

    # La carpeta elegida y, si no lo trae, la de arriba: una caja lanzada
    # suelta -- «18-RESOLUCIONES INTERNAS Y ACTAS 3303\00C003303» -- tiene el
    # Excel del cliente un nivel más arriba (2026-10-30).
    separador = "/" if "/" in ruta else "\\"
    padre = ruta.rstrip("/\\").rsplit(separador, 1)[0] if separador in ruta.rstrip("/\\") else ""
    oficina = del_excel(ruta) or (del_excel(padre) if padre and padre != ruta else None)
    return oficina or oficina_de_la_ruta(al_operador(ruta)) or oficina_de_la_ruta(ruta)


class FolderRunner:
    """Drains a local folder, several documents at a time.

    Iba de uno en uno, y una carpeta de 103 PDF tardó 41 minutos con diez de
    los once procesos del pool sin nada que hacer y la red esperando a la IA
    con la CPU ociosa. Ahora cada carpeta pone tantos trabajadores como
    ranuras tiene el planificador, y todos sacan de la misma cola en el orden
    de la carpeta. Las ranuras son del servicio y no de la carpeta: dos
    carpetas en marcha se las reparten por orden de llegada, en vez de doblar
    la carga de la máquina.

    Lo que tiene que ir en fila sigue en fila: los Excel se escriben de uno en
    uno, y la entrega a una misma carpeta también. En la caja de
    correspondencia, las entregas a carpetas de NIC distintas van a la vez
    (hasta ``entregas_a_la_vez``); ver el orden de los cerrojos en
    ``FolderRun.cerrojo``.
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
        #: Cuántas entregas planas escriben a la vez en el destino, entre todas
        #: las carpetas de este equipo: varias, para no hacer fila detrás de un
        #: servidor lento, y no todas, para no ahogarlo (``entregas_a_la_vez``).
        #: Se pide después del turno de la carpeta (ver ``FolderRun.cerrojo``).
        self._entregas = threading.BoundedSemaphore(max(1, int(getattr(settings, "entregas_a_la_vez", 4) or 4)))
        #: Los hilos del recorrido, aparte del pool común: con una carpeta de
        #: red ese pool se llena de descargas, y el recorrido esperaba detrás
        #: de ellas sin descubrir nada nuevo (2026-10-28).
        self._hilos_del_recorrido = ThreadPoolExecutor(max_workers=4, thread_name_prefix="recorrido")
        #: El bucle de la aplicación, para publicar desde los hilos de entrega.
        self._loop: asyncio.AbstractEventLoop | None = None
        #: Las tareas que miden la red de cada corrida: con su referencia aquí,
        #: el recolector no se las lleva a medio medir.
        self._medidores: set[asyncio.Task] = set()
        #: Las que esperan a que se vacíe una corrida con la orden de «Parar con
        #: calma» (``_parar_al_vaciarse``), por lo mismo.
        self._paradas: set[asyncio.Task] = set()

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
        tipo_documento: str | None = None,
        retomar: str = "no",
        paralelo: int | None = None,
        acta: str | None = None,
        oficina: str | None = None,
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
        if red_smb.es_de_red(al_servicio(clean_path(source))) and disposition is not SourceDisposition.LEAVE:
            # El original de una carpeta de red no se toca: es el repositorio.
            raise FolderError(
                "En una carpeta de red el original se deja como está: elija «Dejarlo»"
            )
        origin, target = validate_folders(
            source,
            destination,
            internas=(self._settings.upload_dir, self._settings.output_dir),
        )

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
            acta=acta,
            oficina=oficina,
            oficina_mirada=bool(oficina),
            oficina_del_operador=bool(oficina),
            tipo=tipo,
            tipo_documento=tipo_documento,
            retomar=str(modo),
            paralelo=paralelo,
            en_su_carpeta=es_entrega_anterior(source, destination),
            minutos_sin_avance=float(getattr(self._settings, "minutos_sin_avance", 0) or 0),
            paralelo_maximo=self._paralelo_maximo(),
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
            await self._drenar(run)
        finally:
            if not run.active and run.coordinacion is not None:
                # Se retira de la corrida compartida: los demás dejan de esperarlo.
                await asyncio.shield(asyncio.to_thread(self._retirarse, run))

    def _retirarse(self, run: FolderRun) -> None:
        coordinacion = run.coordinacion
        if coordinacion is None or coordinacion.retirado:
            return
        try:
            coordinacion.estado = "terminado"
            for reclamo in list(run.reclamos.values()):
                coordinacion.soltar(reclamo)
            run.reclamos.clear()
            coordinacion.parar()
        except Exception:  # noqa: BLE001 - retirarse nunca tumba la corrida
            logger.warning("no se pudo retirar de la corrida compartida de %s", run.destination, exc_info=True)

    def _unirse_a_la_corrida(self, run: FolderRun) -> None:
        """Se une a la corrida de los demás equipos sobre este destino, o la empieza.

        Las opciones y la versión del bot tienen que ser las de la corrida: si
        no, se rechaza con la diferencia en palabras, porque la mitad de la
        carpeta saldría con otras reglas. Si el destino no deja coordinarse
        -- no garantiza la creación exclusiva --, con ``auto`` sigue sola y lo
        avisa; con ``si``, no corre.
        """
        from ..adapters import recursos_del_equipo
        from ..adapters.coordinacion_en_disco import (
            Coordinacion,
            CoordinacionRechazada,
            DestinoNoCompartible,
        )
        from .corrida_compartida import modo, opciones_de, version_del_bot

        if modo() == "no" or run.retomar in (Retomar.FALTANTES, Retomar.REVISAR):
            return
        ritmo = {
            clave: valor
            for clave, valor in (
                ("latido", self.SEGUNDOS_DEL_LATIDO),
                ("caido", self.SEGUNDOS_PARA_DARLO_POR_CAIDO),
            )
            if valor is not None
        }
        # Los recursos de este PC en su latido (2026-11-27), con su propio
        # medidor de CPU. El disco: el C: del equipo en Docker, o si no, el de
        # la carpeta de datos del bot (la de sus «outputs»).
        medir_recursos = partial(
            recursos_del_equipo.medir,
            self._settings.output_dir.parent,
            cpu=recursos_del_equipo.MedidorDeCpu(),
        )
        coordinacion = Coordinacion(
            run.destination, version=version_del_bot(), medir_recursos=medir_recursos, **ritmo
        )
        try:
            corrida = coordinacion.unirse(opciones_de(run), origen=run.source.name or str(run.source))
        except DestinoNoCompartible as error:
            if modo() == "si":
                raise FolderError(str(error)) from None
            self._avisar(run, f"{error} Esta corrida sigue sola, sin repartir con otros equipos.")
            return
        except CoordinacionRechazada as error:
            raise FolderError(str(error)) from None
        if not run.active:
            # Se detuvo mientras se unía («Detener», o una orden recibida en la
            # unión): unirse tarda de segundos a minutos. Se retira ya; si no,
            # quedaba latiendo «procesando» sin nadie que la parara, y el que
            # cierra la esperaba para siempre (2026-11-26).
            coordinacion.parar()
            return
        run.coordinacion = coordinacion
        # La orden de parar que otro equipo deja para éste desde el monitoreo
        # (2026-11-26): llega al hilo de la mirada y se cumple en el bucle. Se
        # conecta ya unida, y la que llegó durante la unión -- la mirada ya
        # corría y la guardó en ``orden`` -- se cumple ahora: no se avisa dos
        # veces, y ``_obedecer`` es idempotente si coincide con la del aviso.
        recibir = self._al_recibir_orden(run.id)
        coordinacion.al_recibir_orden = recibir
        if coordinacion.orden is not None:
            recibir(dict(coordinacion.orden))
        otros = len(coordinacion.equipos_vivos()) - 1
        run.compartida = (
            f"Corrida compartida {corrida['id']} (la empezó {corrida.get('creada_por')}); "
            f"este equipo es {coordinacion.id}"
            + (f", con {otros} equipo(s) más" if otros > 0 else "")
        )
        self._avisar(run, run.compartida)

    async def _drenar(self, run: FolderRun) -> None:
        try:
            if run.coordinacion is None and run.state is not RunState.FAILED:
                try:
                    await asyncio.to_thread(self._unirse_a_la_corrida, run)
                except FolderError as error:
                    # No se reintenta: con otras opciones u otra versión, otra
                    # vuelta daría lo mismo. Se dice por qué y se para.
                    run.state = RunState.FAILED
                    run.error = str(error)
                    run.finished_at = _now()
                    self._publish(run)
                    return
            if not run.folios_mirados:
                # Los folios del inventario del cliente, para las filas de los
                # PDF inventariados enteros (opción B, 2026-10-30), y la caja de
                # cada UPD, para la fila cuya ruta no la dice.
                run.folios_del_cliente, run.cajas_del_cliente = await asyncio.to_thread(
                    por_upd_de_la_carpeta_de_origen, str(run.source)
                )
                run.folios_mirados = True
            if not run.oficina_mirada:
                # Antes del primer PDF: cada trabajo la lleva a la cabecera de
                # su FUID. Puede ir por la red, así que en un hilo.
                run.oficina = await asyncio.to_thread(oficina_de_la_carpeta_de_origen, str(run.source))
                run.oficina_mirada = True
                self._publish(run)
            if not run.midiendo:
                # Red o local y la velocidad real de cada lado (2026-11-05), en
                # paralelo: medir no retrasa el primer PDF.
                run.midiendo = True
                medidor = asyncio.create_task(self._medir_la_red(run))
                self._medidores.add(medidor)
                medidor.add_done_callback(self._medidores.discard)
            while True:
                # En paralelo y por lotes: el recorrido llena la cola lote a
                # lote mientras los trabajadores la vacían.
                hubo = await self._procesar_por_lotes(run)
                if run.coordinacion is not None:
                    # Lo que otros equipos tenían en curso: se espera a que lo
                    # entreguen (y se cuenta), o se toma si su equipo cayó.
                    hubo = await self._esperar_a_los_otros_equipos(run) or hubo
                # Una pasada entera sin tropezar: los tropiezos cuentan seguidos,
                # no en toda la vida de la corrida. En una vigilancia de días,
                # tres sueltos la dejaban en FAILED (2026-10-27).
                run.tropiezos = 0
                if hubo:
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

            # La auditoría de cierre (2026-11-05): el origen contra el destino y
            # una muestra de 100 PDF entregados revisada otra vez. Antes de los
            # Excel generales, que la llevan en el análisis de la entrega. Una
            # carpeta vigilada no termina: no se audita.
            # Con varios equipos, cierra uno solo -- la auditoría y los Excel
            # generales finales --, y cuando los demás ya terminaron: así lo
            # tiene todo contado (lo suyo y lo de ellos) y nadie lo pisa después.
            # Desde el 2026-11-27 es el principal (``_esperar_el_cierre``).
            cierra = True
            if run.coordinacion is not None and run.active:
                cierra = await self._esperar_el_cierre(run)
            if cierra and not run.watch and run.state is not RunState.FAILED and run.active:
                # Los FUID de cada subcarpeta, al día antes de auditar: la
                # auditoría compara cada PDF con su fila del FUID entregado
                # (2026-11-06). Sólo escribe los que cambiaron.
                await asyncio.to_thread(self._escribir_inventario_de_actas, run)
                await self._auditar_al_cerrar(run)
                # Ningún archivo ni carpeta repetidos en el destino (el
                # operador, 2026-11-25): se comprueba en el disco, con todo
                # lo entregado por todos los equipos.
                await asyncio.to_thread(self._buscar_repetidos, run)
            # El Excel antes de dar la carpeta por terminada: la pantalla enseña
            # el botón de descarga en cuanto la ve terminada, y un botón que
            # aparece antes que el archivo es un botón que falla.
            await asyncio.to_thread(self._escribir_inventario_de_actas, run)
            if cierra:
                await self._cerrar_generales(run)
            else:
                await self._dejar_los_generales_al_que_cierra(run)
            if run.state is not RunState.FAILED:
                # Una carpeta detenida por fallos seguidos se queda así, con
                # su motivo: «terminada» diría que salió bien.
                run.state = RunState.DONE
            run.finished_at = run.finished_at or _now()
            run.en_curso.clear()
            run.queue = []
            if cierra:
                await asyncio.to_thread(self._write_manifest, run)
                if run.coordinacion is not None and not run.watch:
                    # Cerrada en el disco: un equipo que vuelva tarde ya no
                    # entrega ni reescribe los generales que este dejó con todo.
                    await asyncio.to_thread(run.coordinacion.cerrar_la_corrida)
            await asyncio.to_thread(self._limpiar_las_copias, run)
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
                espera = ESPERA_TRAS_TROPIEZO * run.tropiezos
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
        """Lo inventariado hasta aquí, escrito: detener a la mitad no pierde lo leído.

        Con otros equipos, como a mitad de corrida: los generales los escribe
        sólo el principal (2026-11-27) -- uno que no lo es y se detiene no los
        toca --, y los definitivos el principal que cierre.
        """
        self._escribir_inventario_de_actas(run)
        self._escribir_todo_lo_general(run, a_mitad=run.coordinacion is not None)
        self._write_manifest(run)
        self._limpiar_las_copias(run)

    # -- varios equipos sobre el mismo destino (2026-11-25) -------------------

    #: Cada cuánto se mira lo que tienen en curso los otros equipos.
    ESPERA_DE_LOS_OTROS = 5.0
    #: El latido de este equipo y cuánto sin él para darlo por caído (las
    #: pruebas los acortan; ver ``application.coordinacion``).
    SEGUNDOS_DEL_LATIDO: float | None = None
    SEGUNDOS_PARA_DARLO_POR_CAIDO: float | None = None

    def _turno_de(self, run: FolderRun, carpeta: Path):
        """El turno de una carpeta del destino entre todos los equipos (o nada, si va solo).

        Entregar, dejar la constancia y ordenar la carpeta del NIC se hacen con
        él: dos equipos con UPD del mismo NIC no renumeran a la vez.
        """
        coordinacion = run.coordinacion
        if coordinacion is None:
            return contextlib.nullcontext()
        try:
            nombre = carpeta.relative_to(run.destination).as_posix()
        except ValueError:
            nombre = str(carpeta)
        return coordinacion.cerrojo(f"carpeta:{nombre}", cancelado=lambda: not run.active)

    @staticmethod
    def _confirmar(run: FolderRun, origin: Path) -> None:
        """La barrera antes de entregar: el PDF sigue siendo de este equipo.

        Sin su reclamo en memoria -- ya se soltó, o la corrida se detuvo -- no
        se entrega: una entrega en un hilo que siguió tras «Detener» esperaba
        el turno de la carpeta y, al tenerlo, pisaba la que otro equipo ya
        había dejado completa (2026-11-25, cuatro equipos con uno detenido).
        """
        if run.coordinacion is None:
            return
        reclamo = run.reclamos.get(str(origin))
        if reclamo is None or not run.active:
            raise ReclamoPerdido(f"este equipo ya no tiene «{origin.name}»: no lo entrega")
        run.coordinacion.confirmar(reclamo)

    def _tomar_el_pdf(self, run: FolderRun, path: Path, relativa: str) -> tuple[bool, bool]:
        """Reclama el PDF para este equipo. Devuelve (procesarlo, hay_que_pedir_generales).

        Si lo tiene otro equipo vivo, se espera al final; si otro ya lo entregó
        en esta corrida, se cuenta como entregado; si falló en otro, se anota y
        no se paga otra vez aquí (lo reintenta el suyo). Tomado, se vuelve a
        mirar su constancia: entretanto pudo entregarlo otro.
        """
        from ..adapters.coordinacion_en_disco import AQUI, Ajeno

        coordinacion = run.coordinacion
        motivo = coordinacion.por_que_no_vale()
        if motivo is not None:
            # Este equipo volvió tarde (colgado, o la red caída): otros empezaron
            # otra corrida o cerraron ésta. No toma nada más: se para con el
            # motivo, y relanzarlo lo une a la corrida en marcha.
            if run.active:
                run.state = RunState.FAILED
                run.error = f"Este equipo ya no está en la corrida compartida: {motivo}. Vuelva a lanzar la carpeta."
                run.finished_at = _now()
            return False, False
        resultado = coordinacion.reclamar(relativa)
        if isinstance(resultado, Ajeno):
            if resultado.estado == AQUI:
                # Ya lo tiene otro trabajador de este mismo equipo: él lo entrega.
                return False, False
            if resultado.estado == "hecho":
                return False, self._entregado_por_otro(run, path, resultado.equipo)
            run.ajenos[str(path)] = resultado.equipo
            return False, False
        fallo = coordinacion.fallo_de(relativa)
        if fallo is not None and str(path) not in run.de_caidos:
            coordinacion.soltar(resultado)
            run.fallidos_en_otro[relativa] = f"{fallo.equipo}: {fallo.error}"
            return False, False
        run.reclamos[str(path)] = resultado
        if run.retomar == Retomar.NO:
            vigencia, constancia = self._vigencia(run, path)
            if vigencia is Vigencia.VIGENTE:
                # Lo entregó otro equipo (o una corrida de antes) mientras éste lo
                # tenía en la cola: se cuenta y se marca hecho para los demás.
                coordinacion.terminar(resultado)
                run.reclamos.pop(str(path), None)
                return False, self._entregado_por_otro(run, path, "otro equipo", constancia=constancia)
            if constancia is not None and vigencia in (Vigencia.INCOMPLETA, Vigencia.ORIGEN_CAMBIADO):
                run.a_rehacer[str(path)] = (vigencia, constancia)
        return True, False

    def _entregado_por_otro(
        self, run: FolderRun, path: Path, equipo: str, *, constancia: Constancia | None = None
    ) -> bool:
        """Lo que entregó otro equipo, contado aquí como ya entregado. Dice si cambió algo."""
        clave = str(path)
        if clave in run.contados_de_otro:
            return False
        if constancia is None:
            # Lo que lee el destino, fuera del cerrojo de la corrida.
            vigencia, constancia = self._vigencia(run, path)
            if vigencia is not Vigencia.VIGENTE:
                # Su reclamo dice «hecho» pero la constancia todavía no: un
                # destino lento. Se vuelve a mirar en la espera.
                run.ajenos[clave] = equipo
                return False
        # Su memoria, con el cerrojo de la corrida (se llama desde hilos, y el
        # escritor de los generales la copia desde otro).
        with run.cerrojo:
            return self._contar_entregado_por_otro(run, path, equipo, constancia)

    def _contar_entregado_por_otro(self, run: FolderRun, path: Path, equipo: str, constancia: Constancia | None) -> bool:
        clave = str(path)
        if clave in run.contados_de_otro:
            return False
        run.contados_de_otro.add(clave)
        run.seen.add(clave)
        run.ajenos.pop(clave, None)
        run.ya_entregados += 1
        run.de_otros_equipos += 1
        if constancia is not None and constancia.job_id:
            run.trabajos_de_otros.append(constancia.job_id)
        self._anotar_la_verificacion(
            run, str(self._relative(run, path)), DECISION_YA_ENTREGADO, f"lo entregó el equipo {equipo} en esta corrida"
        )
        self._contar_lo_ya_entregado(run, path, constancia)
        return True

    def _mirar_los_ajenos(self, run: FolderRun) -> tuple[list[Path], bool]:
        """Cómo van los PDF que tenían otros equipos: los libres se rehacen aquí."""
        coordinacion = run.coordinacion
        libres: list[Path] = []
        contados = False
        for clave in list(run.ajenos):
            path = Path(clave)
            relativa = str(self._relative(run, path))
            estado = coordinacion.estado_de(relativa)
            if estado is None:
                # Libre: su equipo cayó o lo soltó sin entregarlo. Lo hace éste.
                run.ajenos.pop(clave, None)
                libres.append(path)
            elif estado.estado == "hecho":
                contados = self._entregado_por_otro(run, path, estado.equipo) or contados
            elif estado.estado == "falló":
                run.ajenos.pop(clave, None)
                run.fallidos_en_otro[relativa] = f"{estado.equipo}: {estado.error}"
        if libres:
            for path in libres:
                run.seen.discard(str(path))
                run.segunda_pasada.add(str(path))
                run.de_caidos.add(str(path))
            self._preparar_otra_vuelta(run, libres)
        return libres, contados

    def _para_la_segunda_pasada(self, run: FolderRun, path: Path) -> bool:
        """Si el PDF es de una carpeta que en la primera pasada le toca a otro equipo vivo.

        Cada carpeta NIC tiene un equipo preferido (``equipo_preferido``): así
        los UPD de un NIC caen en el mismo equipo, y dos equipos no se disputan
        cada PDF de la cola. Sólo ordena: el reclamo es lo que garantiza que
        cada PDF lo haga uno.
        """
        coordinacion = run.coordinacion
        if coordinacion is None or str(path) in run.segunda_pasada:
            return False
        return not coordinacion.me_toca_primero(str(self._relative(run, path)))

    async def _esperar_a_los_otros_equipos(self, run: FolderRun) -> bool:
        """Espera lo que otros equipos tienen en curso; toma lo de los caídos. Dice si procesó algo."""
        hubo = False
        while run.active and run.ajenos:
            libres, contados = await asyncio.to_thread(self._mirar_los_ajenos, run)
            if contados:
                self._pedir_generales(run)
            if libres:
                hubo = True
                run.queue = [str(self._relative(run, path)) for path in libres]
                await self._consumir_en_paralelo(run, libres)
                continue
            if run.ajenos:
                run.etapa = "Esperando a otros equipos"
                run.etapa_detalle = f"{len(run.ajenos)} PDF en curso en otros equipos"
                self._publish(run)
                await asyncio.sleep(self.ESPERA_DE_LOS_OTROS)
        if run.etapa == "Esperando a otros equipos":
            run.etapa, run.etapa_detalle = "", ""
        return hubo

    #: Cuántos reclamos o constancias de otros equipos se miran a la vez.
    MIRAR_A_LA_VEZ = 8

    def _clasificar_la_segunda_pasada(self, run: FolderRun, segunda: list[Path]) -> list[Path]:
        """De los PDF de la segunda pasada, los que de verdad hay que procesar aquí.

        Se mira el reclamo de cada uno, varios a la vez y sin la fila de los
        reclamos: lo entregado por otro equipo se cuenta (su constancia la lee
        sólo el que cierra, ``_completar_lo_de_los_otros``), lo que otro tiene en
        curso se espera al final, lo que falló en otro no se paga otra vez aquí,
        y lo libre o de un caído vuelve a la cola.
        """
        coordinacion = run.coordinacion

        def mirar(path: Path):
            try:
                return coordinacion.estado_de(str(self._relative(run, path)))
            except Exception:  # noqa: BLE001 - sin poder mirarlo, lo decide su reclamo al tomarlo
                return _SIN_MIRAR

        with ThreadPoolExecutor(max_workers=self.MIRAR_A_LA_VEZ, thread_name_prefix="segunda-pasada") as hilos:
            estados = list(hilos.map(mirar, segunda))
        quedan: list[Path] = []
        contados = 0
        # La memoria de la corrida, con su cerrojo: el escritor de los generales
        # la copia desde otro hilo.
        with run.cerrojo:
            for path, estado in zip(segunda, estados, strict=True):
                relativa = str(self._relative(run, path))
                if estado is _SIN_MIRAR or estado is None:
                    quedan.append(path)
                elif estado.estado == "hecho":
                    if self._contar_como_de_otro(run, path, estado.equipo):
                        contados += 1
                elif estado.estado == "falló":
                    run.seen.add(str(path))
                    run.fallidos_en_otro[relativa] = f"{estado.equipo}: {estado.error}"
                else:
                    run.seen.add(str(path))
                    run.ajenos[str(path)] = estado.equipo
        if contados:
            logger.info("segunda pasada: %d PDF ya entregados por otros equipos", contados)
        return quedan

    def _contar_como_de_otro(self, run: FolderRun, path: Path, equipo: str) -> bool:
        """Lo que entregó otro equipo, contado por su reclamo «hecho» y sin leer su constancia todavía."""
        clave = str(path)
        if clave in run.contados_de_otro:
            return False
        run.contados_de_otro.add(clave)
        run.contados_sin_constancia.add(clave)
        run.seen.add(clave)
        run.ajenos.pop(clave, None)
        run.ya_entregados += 1
        run.de_otros_equipos += 1
        self._anotar_la_verificacion(
            run, str(self._relative(run, path)), DECISION_YA_ENTREGADO, f"lo entregó el equipo {equipo} en esta corrida"
        )
        return True

    def _completar_lo_de_los_otros(self, run: FolderRun) -> bool:
        """El que cierra lee la constancia de lo que los demás entregaron y se contó sin ella.

        Una sola vez, en un solo equipo y varias a la vez: así los Excel
        generales finales llevan la fila de cada PDF de la corrida, y la
        auditoría su trabajo. Dice si sumó algo.
        """
        pendientes = sorted(run.contados_sin_constancia)
        if not pendientes:
            return False

        def leer(clave: str):
            # Donde la busca la verificación (``_vigencia``): la suya, la de sus
            # actas en el espejo y, en la entrega plana, la de su subcarpeta de antes.
            path = Path(clave)
            rutas = [
                self._ruta_de_la_constancia(run, path, actas=False),
                self._ruta_de_la_constancia(run, path, actas=True),
            ]
            if self._plana(run):
                rutas.append(self._entrega_de_antes(run, path) / constancias.NOMBRE)
            for ruta in rutas:
                try:
                    constancia = constancias.leer(ruta)
                except Exception:  # noqa: BLE001 - sin su constancia, su fila sale sin detalle
                    constancia = None
                if constancia is not None:
                    return constancia
            return None

        with ThreadPoolExecutor(max_workers=self.MIRAR_A_LA_VEZ, thread_name_prefix="lo-de-los-otros") as hilos:
            leidas = list(hilos.map(leer, pendientes))
        with run.cerrojo:
            for clave, constancia in zip(pendientes, leidas, strict=True):
                run.contados_sin_constancia.discard(clave)
                if constancia is not None and constancia.job_id:
                    run.trabajos_de_otros.append(constancia.job_id)
                self._contar_lo_ya_entregado(run, Path(clave), constancia)
        return True

    async def _esperar_el_cierre(self, run: FolderRun) -> bool:
        """Si este equipo cierra la corrida compartida: el principal, y espera a los demás.

        El operador, 2026-11-27: el principal -- el primero en lanzar, que
        «deberá tener más capacidad de recursos» -- hace las tareas pesadas.
        Hasta entonces cerraba el primero que acababa. Uno que no es el
        principal termina su parte, lo dice y se retira, como hacía el que no
        tomaba el rol. Si el principal se cae o se retira sin cerrar, el
        siguiente de la sucesión (``principal_de``) que llega aquí cierra: el
        rol de un caído o de un retirado se hereda (``tomar_rol``). Si ya no
        queda nadie para cerrar, relanzar la carpeta empieza una corrida nueva
        que cierra.
        """
        coordinacion = run.coordinacion
        if run.parando is not None:
            # Con la orden de «Parar con calma» no cierra (2026-11-26): la
            # auditoría y los generales finales los hace otro equipo. Lo suyo
            # ya se vació, así que se detiene aquí, y la cancelación de
            # «Detener» llega en la espera, no a mitad de escribir un Excel.
            while run.active and not self._parar_si_se_vacio(run):
                await asyncio.sleep(self.ESPERA_AL_VACIARSE)
            await asyncio.sleep(0)
            return False
        try:
            # Una mirada ahora y no la foto de hace un latido: un principal que
            # se acaba de retirar seguiría vivo en ella, y éste se iría
            # dejándole el cierre a nadie.
            await asyncio.to_thread(coordinacion.mirar_ahora)
        except Exception:  # noqa: BLE001 - sin poder mirar, decide la última foto
            logger.warning("no se pudo mirar a los demás equipos antes del cierre", exc_info=True)
        # Uno que no es el principal no se retira hasta que el principal empiece
        # a cerrar: si se fueran todos y el principal se cayera o se detuviera
        # en su última vuelta, nadie cerraría (lo encontró la revisión,
        # 2026-11-27). Mientras espera no trabaja; si el principal desaparece, la
        # sucesión lo nombra a él y cierra él.
        while True:
            principal = coordinacion.principal()
            if principal is None or principal == coordinacion.id:
                break
            if (coordinacion.latidos().get(principal) or {}).get("estado") == "cerrando":
                # Antes de decir «cerrando»: éste no cierra, y en la lista de
                # equipos no tiene que salir como el que cierra.
                self._avisar(
                    run,
                    f"Este equipo terminó su parte. La corrida la cierra el principal "
                    f"{equipo_en_palabras(principal)}: la auditoría y los Excel generales finales.",
                )
                return False
            if not run.active or run.parando is not None:
                return False
            run.etapa = "Esperando al principal"
            run.etapa_detalle = (
                f"el principal {equipo_en_palabras(principal)} cierra la corrida; "
                "este equipo espera por si no pudiera"
            )
            self._publish(run)
            await asyncio.sleep(self.ESPERA_DE_LOS_OTROS)
            try:
                await asyncio.to_thread(coordinacion.mirar_ahora)
            except Exception:  # noqa: BLE001 - sin poder mirar, decide la última foto
                logger.debug("no se pudo mirar a los demás equipos esperando al principal", exc_info=True)
        if run.etapa == "Esperando al principal":
            run.etapa, run.etapa_detalle = "", ""
        coordinacion.estado = "cerrando"
        if not await asyncio.to_thread(coordinacion.tomar_rol, "cierre"):
            self._avisar(run, "Este equipo terminó su parte; la auditoría y los Excel generales los cierra otro equipo.")
            return False
        while run.active and not await asyncio.to_thread(coordinacion.los_demas_terminaron):
            run.etapa = "Esperando a otros equipos"
            run.etapa_detalle = "este equipo cierra la corrida cuando los demás terminen"
            self._publish(run)
            await asyncio.sleep(self.ESPERA_DE_LOS_OTROS)
        # Lo que falló en otro equipo y su reintento sí entregó.
        contados = await asyncio.to_thread(self._recontar_lo_de_los_otros, run)
        # Y la constancia de lo que los demás entregaron, para los generales finales.
        contados = await asyncio.to_thread(self._completar_lo_de_los_otros, run) or contados
        if contados:
            self._pedir_generales(run)
        if run.etapa == "Esperando a otros equipos":
            run.etapa, run.etapa_detalle = "", ""
        return True

    def _recontar_lo_de_los_otros(self, run: FolderRun) -> bool:
        contados = False
        for relativa in list(run.fallidos_en_otro):
            path = run.source / relativa
            vigencia, constancia = self._vigencia(run, path)
            if vigencia is Vigencia.VIGENTE:
                run.fallidos_en_otro.pop(relativa, None)
                contados = self._entregado_por_otro(run, path, "otro equipo", constancia=constancia) or contados
        for relativa, motivo in run.fallidos_en_otro.items():
            self._avisar(run, f"«{relativa}» falló en el equipo {motivo}")
        return contados

    def _buscar_repetidos(self, run: FolderRun) -> None:
        """Los archivos y carpetas repetidos del destino, como avisos de la corrida."""
        from .repetidos import buscar_repetidos

        def en_la_fuente(relativa: str) -> bool:
            ruta = run.source / relativa
            try:
                if red_smb.por_smb(run.source):
                    return Path(relativa).name in set(red_smb.carpetas(str(ruta.parent)))
                return ruta.is_dir()
            except Exception:  # noqa: BLE001 - sin poder mirarlo, se avisa
                return False

        try:
            repetidos = buscar_repetidos(run.destination, detener=lambda: not run.active, en_la_fuente=en_la_fuente)
        except Exception as error:  # noqa: BLE001 - el control no tumba la corrida
            self._avisar(run, f"No se pudo buscar archivos repetidos en el destino: {explicar_fallo(error)}")
            return
        run.repetidos = [repetido.en_palabras() for repetido in repetidos]
        if not repetidos:
            self._avisar(run, "Control de repetidos: ningún archivo ni carpeta repetidos en el destino.")
            return
        self._avisar(run, f"Control de repetidos: {len(repetidos)} repetido(s) en el destino. Revíselos:")
        for repetido in repetidos[:20]:
            self._avisar(run, f"Repetido — {repetido.en_palabras()}")

    async def _dejar_los_generales_al_que_cierra(self, run: FolderRun) -> None:
        """El equipo que no cierra no reescribe los generales al final: los escribe el que cierra, con todo."""
        run.generales_pendientes = False
        escritor = run.escritor
        if escritor is not None and not escritor.done():
            escritor.cancel()
            try:
                await escritor
            except asyncio.CancelledError:
                pass

    #: Cuántos PDF del origen se reparten y se ponen a procesar de una vez. Con
    #: un millón en el árbol, juntar la lista entera antes de empezar el primero
    #: eran minutos de recorrido y cientos de megas de memoria (lo pidió el
    #: operador el 2026-10-20: «hagámoslo por conteo por lotes»).
    LOTE_DEL_ORIGEN = 1000
    #: El primero, más corto: el primer PDF nuevo no espera a que se verifiquen
    #: mil ya entregados. Relanzando una caja de mil, empezaba a los 14 s
    #: (2026-10-28).
    PRIMER_LOTE = 50
    #: Y ninguno espera más que esto a llenarse: en una carpeta de red cada
    #: listado es una ida y vuelta, y un PDF nuevo hallado tras el primer lote
    #: esperaba a que se listaran otros mil antes de empezar (2026-10-28).
    #: Cortado antes, el contador de la pantalla avanza a la vez que el recorrido.
    SEGUNDOS_POR_LOTE = 1.0

    async def _descubrir_por_lotes(self, run: FolderRun):
        """Los lotes del origen, uno tras otro; si el origen no se deja, espera a que vuelva.

        El recorrido avanza un lote cada vez que se pide el siguiente: mientras
        se procesa el primero, el resto del árbol todavía no se ha leído. El
        listado va como mucho dos lotes por delante, en su propio hilo
        (``_ListadoEnSuHilo``, 2026-11-26), y lo que falla en él sale por aquí.

        La carpeta de origen suele estar en una unidad de red, y una unidad de
        red se desconecta: la VPN que se cae, el servidor que se reinicia. Eso
        tumbaba la corrida entera. Ahora se espera -- treinta segundos, luego
        el doble, hasta cinco minutos entre intentos -- hasta
        ``minutos_de_espera_del_origen``; sólo entonces la corrida falla. Al
        volver, el recorrido empieza otra vez y salta lo ya tomado.
        """

        def plazo() -> float:
            return time.monotonic() + 60 * float(
                getattr(self._settings, "minutos_de_espera_del_origen", 0) or 0
            )

        limite, espera = plazo(), 30.0
        lotes = None
        while True:
            try:
                if lotes is None:
                    lotes = self._lotes_del_origen(run)
                lote = await asyncio.get_running_loop().run_in_executor(
                    self._hilos_del_recorrido, next, lotes, None
                )
            except (FolderError, OSError) as error:
                lotes = None
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
            if lote is None:
                return
            limite, espera = plazo(), 30.0
            yield lote

    def _discover(self, run: FolderRun) -> tuple[list[Path], list[tuple[Path, Constancia | None]]]:
        """Todo el origen de una vez: los lotes juntos (lo usa quien no procesa)."""
        pendientes: list[Path] = []
        entregados: list[tuple[Path, Constancia | None]] = []
        for lote, ya in self._lotes_del_origen(run):
            pendientes.extend(lote)
            entregados.extend(ya)
        return pendientes, entregados

    def _lotes_del_origen(self, run: FolderRun):
        """Los PDF del árbol de origen que nadie ha tomado todavía, y los ya entregados, por lotes.

        Por todo el árbol y no sólo por la carpeta que se indicó: el archivo se
        entrega en cajas -- una carpeta por expediente, y cien expedientes en la
        ruta que el operador señala -- y pedirle que apunte cien veces, una por
        carpeta, es pedirle que haga a mano lo que la máquina sabe hacer.

        En orden de ruta: carpeta por carpeta, por nombre, que es lo que mantiene
        juntos los documentos de una misma caja mientras se procesan. Pero lo
        pendiente primero (2026-11-26): las carpetas de la raíz que ya están en
        el destino van al final (``_pdfs_locales``, ``_pdfs_en_la_red``). Cada
        equipo tardaba de 3 a 28 min en tomar su primer PDF: lo pendiente de
        Magangué quedaba detrás de unos 35.000 PDF ya entregados, y recorrer y
        verificar iban en serie. Ahora el listado va en su propio hilo
        (``_ListadoEnSuHilo``) y aquí se verifica mientras tanto.

        Lo ya entregado se sabe por su constancia (ver ``constancia.py``), sin
        abrir ni el origen ni lo entregado. Sin constancia, una carpeta del
        destino con algún PDF es una entrega de antes de que existiera, y se da
        por buena como hasta ahora. Un PDF cuya carpeta no está en el destino no
        tiene constancia que leer: va por el carril rápido
        (``_sin_carpeta_en_el_destino``), en lotes aparte, para que no espere a
        que se verifiquen los ya entregados que vienen detrás de él.
        """
        destino = DestinoListado(run.destination)
        # Sólo cuando se verifica al recorrer: al retomar lo que falta o al
        # revisar, cada PDF se compara con el destino al procesarlo.
        rapido = run.retomar in (Retomar.NO, Retomar.TODO)
        listado: _ListadoEnSuHilo | None = None
        lote: list[Path] = []
        huellas: dict[str, tuple[int, int]] = {}
        sin_carpeta = False
        tope = min(self.PRIMER_LOTE, self.LOTE_DEL_ORIGEN)
        desde = time.monotonic()

        def cortar() -> tuple[list[Path], list[tuple[Path, Constancia | None]]]:
            nonlocal lote, huellas, tope, desde
            repartido = self._repartir(run, lote, huellas)
            lote, huellas = [], {}
            tope, desde = self.LOTE_DEL_ORIGEN, time.monotonic()
            return repartido

        try:
            run.destino_listado = destino
            fuente = self._pdfs_en_la_red(run) if red_smb.por_smb(run.source) else self._pdfs_locales(run)
            # Uno o dos lotes por delante, no más: la memoria no se llena de rutas.
            listado = _ListadoEnSuHilo(fuente, tope=2 * max(1, self.LOTE_DEL_ORIGEN))
            # La raíz del destino aquí, mientras el hilo del listado lee la del origen.
            destino.nombres_de_la_raiz()
            while True:
                espera = max(0.0, desde + self.SEGUNDOS_POR_LOTE - time.monotonic()) if lote else None
                elemento = listado.siguiente(espera)
                if elemento is _NADA_TODAVIA:
                    # Ningún lote espera más de ``SEGUNDOS_POR_LOTE`` a llenarse.
                    yield cortar()
                    continue
                if elemento is _FIN_DEL_LISTADO:
                    break
                if isinstance(elemento, _FalloDelListado):
                    # Lo listado antes del fallo sale primero; el fallo, después.
                    if lote:
                        yield cortar()
                    raise elemento.error
                path, huella = elemento
                # Lo ya tomado y lo que ya está en la cola o en la segunda pasada:
                # al recorrer otra vez tras una caída del origen, se encolaba de
                # nuevo y se leía (y pagaba) dos veces (2026-11-25).
                if str(path) in run.seen or str(path) in run.encolados:
                    continue
                nuevo = rapido and self._sin_carpeta_en_el_destino(run, path, destino)
                if lote and nuevo != sin_carpeta:
                    # Cada lote, de un solo carril y en orden de ruta.
                    yield cortar()
                sin_carpeta = nuevo
                if nuevo:
                    destino.sin_carpeta.add(str(path))
                lote.append(path)
                if huella is not None:
                    huellas[str(path)] = huella
                if len(lote) >= tope or time.monotonic() - desde >= self.SEGUNDOS_POR_LOTE:
                    yield cortar()
            if lote:
                yield cortar()
        finally:
            # Cerrar el recorrido -- relanzarlo, detener la corrida -- detiene el listado.
            if listado is not None:
                listado.cerrar()
            if run.destino_listado is destino:
                run.destino_listado = None

    def _sin_carpeta_en_el_destino(self, run: FolderRun, path: Path, destino: DestinoListado) -> bool:
        """Si un PDF va por el carril rápido: no están en el destino ni su carpeta ni la de su constancia.

        Son las carpetas donde ``_vigencia`` busca su constancia -- la suya (la
        de ``_output_dir``), la de sus actas en el espejo y, en la entrega
        plana, la de su subcarpeta de antes -- y donde ``_tiene_pdf_entregado``
        busca lo entregado sin constancia. Si de ninguna está en el destino su
        carpeta de la raíz (``DestinoListado.existe``), no hay nada que leer: es
        nuevo. Ante la duda -- la carpeta de la raíz sí está, la raíz no se dejó
        listar, una ruta que no se puede calcular --, el carril normal, que lo
        verifica como siempre.
        """
        try:
            # La suya primero: en un relanzamiento casi todo está, y basta con ella.
            if destino.existe(self._output_dir(run, path)) is not False:
                return False
            otras = [self._ruta_de_la_constancia(run, path, actas=True).parent]
            if self._plana(run):
                otras.append(self._entrega_de_antes(run, path))
            return all(destino.existe(carpeta) is False for carpeta in otras)
        except Exception:  # noqa: BLE001 - sin poder saberlo, se verifica como siempre
            logger.debug("no se pudo saber si «%s» tiene su carpeta en el destino", path, exc_info=True)
            return False

    def _avisar_por_donde_empieza(self, run: FolderRun, faltan: int, estan: int) -> None:
        """Lo que dice la pantalla al empezar por lo pendiente: sólo si hay carpetas de los dos lados."""
        if not faltan or not estan:
            return
        delante = "1 carpeta que no está" if faltan == 1 else f"{faltan} carpetas que no están"
        detras = "la otra se verifica" if estan == 1 else f"las otras {estan} se verifican"
        self._avisar(run, f"Se empieza por {delante} en el destino; {detras} mientras tanto.")

    def _pdfs_locales(self, run: FolderRun):
        """Los PDF de una carpeta del equipo, a medida que se leen.

        Con ``os.walk`` y no con ``rglob``: ``rglob`` se salta en silencio una
        subcarpeta que no se deja leer -- la red que parpadea, un permiso --, y
        sus PDF desaparecían de la corrida sin un error que mirar. Ahora cada
        una queda en los avisos de la corrida. ``_procesados`` no se recorre.

        Con el destino listado del recorrido (``run.destino_listado``), lo
        pendiente primero (``_lo_pendiente_primero_en_el_equipo``); sin él -- la
        auditoría de cierre --, en orden de ruta, como siempre.
        """

        def no_se_pudo(error: OSError) -> None:
            if Path(str(error.filename or "")) == run.source:
                raise FolderError(f"No se pudo leer la carpeta de origen: {error}")
            self._avisar(
                run,
                f"No se pudo leer la carpeta «{self._relative(run, Path(str(error.filename)))}»: "
                f"{error.strerror or error}. Sus PDF no entraron en esta corrida.",
            )

        destino = run.destino_listado
        try:
            if destino is None:
                rutas = en_orden_de_ruta(run.source, no_se_pudo)
            else:
                rutas = self._lo_pendiente_primero_en_el_equipo(run, destino, no_se_pudo)
            for path in rutas:
                yield path, None
        except FolderError:
            raise
        except OSError as error:
            raise FolderError(f"No se pudo leer la carpeta de origen: {error}") from None

    def _lo_pendiente_primero_en_el_equipo(
        self, run: FolderRun, destino: DestinoListado, no_se_pudo: Callable[[OSError], None]
    ) -> Iterator[Path]:
        """Los PDF de una carpeta del equipo, lo pendiente primero (2026-11-26).

        La raíz se lista una vez (``_primer_nivel``); sus subcarpetas que ya
        están en el destino (``lo_pendiente_primero``) van al final, y lo demás
        -- las que faltan y los PDF sueltos de la raíz -- delante, en su orden de
        ruta de siempre: sin nada en el destino, el orden de antes. Dentro de
        cada subcarpeta, ``en_orden_de_ruta`` con el mismo ``no_se_pudo``: la
        raíz que no se deja leer es un error; una subcarpeta, un aviso.
        """
        raiz = str(run.source)
        entradas = _primer_nivel(raiz, no_se_pudo)
        faltan, estan = lo_pendiente_primero(
            [nombre for nombre, es_carpeta in entradas if es_carpeta], destino.nombres_de_la_raiz() or ()
        )
        self._avisar_por_donde_empieza(run, len(faltan), len(estan))
        al_final = set(estan)
        delante = [(nombre, es_carpeta) for nombre, es_carpeta in entradas if not (es_carpeta and nombre in al_final)]
        for nombre, es_carpeta in [*delante, *((nombre, True) for nombre in estan)]:
            ruta = os.path.join(raiz, nombre)
            if es_carpeta:
                yield from en_orden_de_ruta(Path(ruta), no_se_pudo)
            else:
                yield Path(ruta)

    def _pdfs_en_la_red(self, run: FolderRun):
        """Lo mismo, para una carpeta de red leída con SMB, con la huella de cada PDF.

        Un listado por carpeta con el tamaño y la fecha de cada PDF: la huella
        sale de ahí, sin otra pregunta al servidor por archivo. Con el destino
        listado del recorrido, lo pendiente primero
        (``_lo_pendiente_primero_en_la_red``); sin él, ``red_smb.iterar``.
        """

        def no_se_pudo(carpeta: str, error: OSError) -> None:
            self._avisar(
                run,
                f"No se pudo leer la carpeta «{self._relative(run, Path(carpeta))}»: "
                f"{error.strerror or error}. Sus PDF no entraron en esta corrida.",
            )

        destino = run.destino_listado
        try:
            if destino is None:
                archivos = red_smb.iterar(str(run.source), saltar=frozenset({CONSUMED_DIR}), al_fallar=no_se_pudo)
            else:
                archivos = self._lo_pendiente_primero_en_la_red(run, destino, no_se_pudo)
            # Cerrado al cerrar éste: los listados pedidos por delante se cancelan.
            with contextlib.closing(archivos):
                for archivo in archivos:
                    yield Path(archivo.ruta), (archivo.tamano, archivo.modificado_ns)
        except red_smb.CredencialesDeRed as error:
            # A mitad de una corrida no hay a quién preguntar: se espera a que
            # el operador vuelva a entrar, como con una unidad que se cayó.
            raise FolderError(
                f"{error.motivo}: {error.recurso}. Vuelva a conectar la carpeta de red."
            ) from None
        except OSError as error:
            raise FolderError(f"No se pudo leer la carpeta de red: {error}") from None

    def _lo_pendiente_primero_en_la_red(
        self, run: FolderRun, destino: DestinoListado, no_se_pudo: Callable[[str, OSError], None]
    ) -> Iterator[red_smb.ArchivoDeRed]:
        """Lo de ``_lo_pendiente_primero_en_el_equipo``, para una carpeta de red leída con SMB.

        La raíz, con un solo listado (``red_smb.listar_nivel``: 7,8 s la de
        Magangué, ~32.000 carpetas). Las subcarpetas, con
        ``red_smb.iterar_carpetas``, que pide por delante el listado de las
        siguientes: una tras otra, a 21 ms cada una, eran unos 10 min antes de
        llegar a lo pendiente (2026-11-26). Los PDF sueltos de la raíz, en su
        sitio entre lo que falta; cada tramo de carpetas seguidas va de una vez.
        """
        saltar = frozenset({CONSUMED_DIR})
        sueltos, subcarpetas = red_smb.listar_nivel(str(run.source), saltar=saltar)
        faltan, estan = lo_pendiente_primero(subcarpetas, destino.nombres_de_la_raiz() or ())
        self._avisar_por_donde_empieza(run, len(faltan), len(estan))
        delante = sorted(
            [*((archivo.ruta, archivo) for archivo in sueltos), *((carpeta, None) for carpeta in faltan)],
            key=lambda entrada: nombre_de_la_carpeta(entrada[0]).lower(),
        )
        tramo: list[str] = []
        for ruta, archivo in delante:
            if archivo is None:
                tramo.append(ruta)
                continue
            if tramo:
                yield from red_smb.iterar_carpetas(tramo, saltar=saltar, al_fallar=no_se_pudo)
                tramo = []
            yield archivo
        yield from red_smb.iterar_carpetas([*tramo, *estan], saltar=saltar, al_fallar=no_se_pudo)

    def _repartir(
        self, run: FolderRun, encontrados: list[Path], huellas: dict[str, tuple[int, int]]
    ) -> tuple[list[Path], list[tuple[Path, Constancia | None]]]:
        """Lo pendiente y lo ya entregado, según la constancia de cada PDF.

        Las constancias se miran a la vez (``_mirar_las_constancias``); lo que
        se decide con ellas, en orden y en este hilo. Lo que el recorrido mandó
        por el carril rápido (``DestinoListado.sin_carpeta``: ni su carpeta ni
        la de su constancia están en el destino) es nuevo sin mirar nada, que
        es lo que diría su constancia: no hay ninguna (2026-11-26).
        """
        pending: list[Path] = []
        entregados: list[tuple[Path, Constancia | None]] = []
        por_mirar = [path for path in encontrados if str(path) not in run.seen and str(path) not in run.encolados]
        for path in por_mirar:
            if str(path) in huellas:
                run.huellas_del_origen[str(path)] = huellas[str(path)]
        destino = run.destino_listado
        nuevos = destino.sin_carpeta if destino is not None else set()
        sin_carpeta = [str(path) in nuevos for path in por_mirar]
        miradas = iter(
            self._mirar_las_constancias(
                run, [path for path, nuevo in zip(por_mirar, sin_carpeta, strict=True) if not nuevo]
            )
        )
        for path, nuevo in zip(por_mirar, sin_carpeta, strict=True):
            key = str(path)
            relativa = str(self._relative(run, path))
            if nuevo:
                nuevos.discard(key)
                # Su huella, como la de cualquier otro que se va a procesar.
                self._tomar_la_huella(run, path)
                self._anotar_la_verificacion(run, relativa, DECISION_NUEVO, MOTIVO_SIN_CARPETA)
                pending.append(path)
                continue
            vigencia, constancia, con_pdf_entregado = next(miradas)
            if run.retomar == Retomar.NO:
                motivo = run.motivos.pop(key, "")
                if vigencia is Vigencia.VIGENTE:
                    self._anotar_la_verificacion(run, relativa, DECISION_YA_ENTREGADO, motivo)
                    entregados.append((path, constancia))
                    # Su huella no hace falta: no se va a procesar.
                    run.huellas_del_origen.pop(key, None)
                    continue
                if vigencia is Vigencia.SIN_CONSTANCIA and con_pdf_entregado:
                    run.sin_constancia += 1
                    self._anotar_la_verificacion(
                        run,
                        relativa,
                        DECISION_YA_ENTREGADO,
                        "su carpeta ya trae PDF entregados por una corrida de antes, sin constancia",
                    )
                    entregados.append((path, None))
                    run.huellas_del_origen.pop(key, None)
                    continue
                if vigencia in (Vigencia.INCOMPLETA, Vigencia.ORIGEN_CAMBIADO):
                    run.a_rehacer[key] = (vigencia, constancia)
                    self._anotar_la_verificacion(run, relativa, DECISION_SE_REHACE, motivo)
                else:
                    self._anotar_la_verificacion(run, relativa, DECISION_NUEVO, motivo)
            elif run.retomar == Retomar.TODO:
                # Todo otra vez, y lo entregado antes se aparta para no dejar
                # cada archivo con su «(2)» al lado.
                motivo = run.motivos.pop(key, "")
                if constancia is not None or con_pdf_entregado:
                    run.a_rehacer[key] = (vigencia, constancia)
                    self._anotar_la_verificacion(
                        run, relativa, DECISION_OTRA_VEZ, f"se eligió procesar todo otra vez ({motivo})"
                    )
                else:
                    self._anotar_la_verificacion(run, relativa, DECISION_NUEVO, motivo)
            else:
                self._anotar_la_verificacion(
                    run,
                    relativa,
                    DECISION_SE_COMPARA,
                    "se eligió sólo revisar: se compara con el destino sin procesar nada"
                    if run.retomar == Retomar.REVISAR
                    else "se eligió retomar: se compara con el destino y se procesa sólo lo que falte",
                )
            pending.append(path)

        return pending, entregados

    def _mirar_las_constancias(
        self, run: FolderRun, paths: list[Path]
    ) -> list[tuple[Vigencia | None, Constancia | None, bool]]:
        """Por cada PDF: qué dice su constancia, y si su carpeta ya trae PDF entregados.

        Varios a la vez (``verificar_a_la_vez``): cada uno son unas cuantas
        lecturas del destino -- la constancia, el listado de su carpeta, el
        tamaño de lo entregado -- y del origen, y en el disco que Docker monta
        cada lectura es un milisegundo de espera. Una tras otra, relanzar mil
        PDF ya entregados eran 16 s (2026-10-28). El orden de la respuesta es
        el de ``paths``. Cada hilo sólo escribe las entradas de su PDF.

        La huella del origen se toma aquí, una vez: la verificación la usa y
        la constancia la guarda al entregar.
        """
        if run.retomar not in (Retomar.NO, Retomar.TODO):
            # Retomar o revisar: se compara con el destino al procesar cada uno.
            for path in paths:
                self._tomar_la_huella(run, path)
            return [(None, None, False)] * len(paths)

        def mirar(path: Path) -> tuple[Vigencia | None, Constancia | None, bool]:
            self._tomar_la_huella(run, path)
            vigencia, constancia = self._vigencia(run, path)
            sin_constancia = constancia is None if run.retomar == Retomar.TODO else vigencia is Vigencia.SIN_CONSTANCIA
            return vigencia, constancia, sin_constancia and self._tiene_pdf_entregado(run, path)

        a_la_vez = max(1, int(getattr(self._settings, "verificar_a_la_vez", 1) or 1))
        if a_la_vez == 1 or len(paths) < 2:
            return [mirar(path) for path in paths]
        with ThreadPoolExecutor(max_workers=min(a_la_vez, len(paths)), thread_name_prefix="verificar") as hilos:
            return list(hilos.map(mirar, paths))

    @staticmethod
    def _tomar_la_huella(run: FolderRun, path: Path) -> None:
        """Tamaño y fecha del origen, si el listado no los trajo (una carpeta del equipo)."""
        if str(path) in run.huellas_del_origen:
            return
        try:
            run.huellas_del_origen[str(path)] = constancias.huella_del_origen(path)
        except OSError:
            run.huellas_del_origen[str(path)] = (0, 0)

    @staticmethod
    def _anotar_la_verificacion(run: FolderRun, relativa: str, decision: str, motivo: str) -> None:
        """Lo que se decidió de un PDF al verificarlo, para el análisis y para el registro del servicio."""
        run.verificaciones[relativa] = (decision, motivo)
        logger.info("verificación «%s»: %s — %s", relativa, decision, motivo or "sin detalle")

    def _avisar(self, run: FolderRun, aviso: str) -> None:
        logger.warning("%s: %s", run.source, aviso)
        if aviso not in run.avisos:
            run.avisos.append(aviso)
            del run.avisos[:-AVISOS_EN_PANTALLA]

    def _ruta_de_la_constancia(self, run: FolderRun, path: Path, *, actas: bool) -> Path:
        """Dónde va la constancia de un PDF: en su carpeta, o la de sus actas en el espejo."""
        if actas:
            return self._espejo(run, path) / constancias.CARPETA_DE_ACTAS / f"{path.name}.json"
        return self._output_dir(run, path) / self._nombre_de_la_constancia(run, path)

    def _vigencia(self, run: FolderRun, path: Path) -> tuple[Vigencia, Constancia | None]:
        """Qué dice la constancia de un PDF -- la suya o, si es de actas, la del espejo --."""
        rutas = [
            self._ruta_de_la_constancia(run, path, actas=False),
            self._ruta_de_la_constancia(run, path, actas=True),
        ]
        if self._plana(run):
            # Una entrega de antes del 2026-10-21, en su subcarpeta UPD: también
            # vale, para que «Saltar lo ya entregado» no repita lo ya pagado.
            rutas.append(self._entrega_de_antes(run, path) / constancias.NOMBRE)
        danada = None
        for indice, ruta in enumerate(rutas):
            actas = indice == 1
            constancia, esta = constancias.leer_si_hay(ruta)
            if constancia is not None:
                base = ruta.parent.parent if actas else ruta.parent
                # La huella que ya trajo el listado, si la hay: en una carpeta
                # de red, preguntarla otra vez es una ida y vuelta por PDF.
                huella = run.huellas_del_origen.get(str(path))
                verificacion = constancias.verificar(constancia, path, base, huella=huella)
                run.motivos[str(path)] = verificacion.motivo
                if verificacion.a_medio_ordenar:
                    run.cajas_por_ordenar.add(base)
                if verificacion.fecha_nueva is not None:
                    self._recordar_la_fecha(run, ruta, constancia, verificacion.fecha_nueva)
                return verificacion.vigencia, constancia
            if esta and danada is None:
                danada = ruta
        if danada is not None:
            run.motivos[str(path)] = f"la constancia de entrega está dañada y no se pudo leer («{danada.name}»)"
            return Vigencia.INCOMPLETA, None
        run.motivos[str(path)] = (
            "no tiene constancia de entrega: no se había entregado"
        )
        return Vigencia.SIN_CONSTANCIA, None

    def _recordar_la_fecha(self, run: FolderRun, ruta: Path, constancia: Constancia, fecha: int) -> None:
        """El origen se copió o se movió y su SHA-256 dice que es el mismo: se guarda su fecha nueva.

        Sin esto cada vuelta volvía a leer el PDF entero -- por la red, si es
        de la red -- para llegar a la misma conclusión. Es el archivo del bot
        en el destino; si no se deja escribir, la próxima vez se vuelve a
        comparar, que es lo de antes.

        La constancia se relee del disco dentro del cerrojo y del turno de su
        carpeta: la que se leyó al verificar pudo quedar vieja -- otro equipo, o
        el orden de la carpeta del NIC, la renumeró entretanto --, y escribirla
        tal cual deshacía esa renumeración (2026-11-25).
        """
        from .correccion_del_re import cerrojo_de_la_carpeta

        constancia.modificado_ns = fecha
        # En la entrega plana, el cerrojo de su carpeta (el que toma el orden
        # del NIC) y no el de la corrida (``FolderRun.cerrojo``).
        cerrojo = cerrojo_de_la_carpeta(ruta.parent) if self._plana(run) else run.cerrojo
        try:
            with self._turno_de(run, ruta.parent), cerrojo:
                actual = constancias.leer(ruta) or constancia
                actual.modificado_ns = fecha
                constancias.escribir(ruta, actual)
        except OSError:
            logger.warning("no se pudo guardar la fecha nueva del origen en %s", ruta, exc_info=True)
        except Exception:  # noqa: BLE001 - el turno ocupado: se vuelve a comparar la próxima vez
            logger.warning("no se pudo guardar la fecha nueva del origen en %s", ruta, exc_info=True)

    def _tiene_pdf_entregado(self, run: FolderRun, path: Path) -> bool:
        carpeta = self._output_dir(run, path)
        try:
            if carpeta.is_dir() and any(carpeta.glob(f"{self._prefijo(run, path)}*.[pP][dD][fF]")):
                return True
            # Y la de antes, en su subcarpeta UPD.
            antes = self._entrega_de_antes(run, path)
            return self._plana(run) and antes.is_dir() and any(antes.glob("*.[pP][dD][fF]"))
        except OSError:
            return False

    def _entrega_de_antes(self, run: FolderRun, origin: Path) -> Path:
        """Dónde quedaba lo de un PDF antes de la entrega plana: «DESTINO\\caja\\UPD…»."""
        relativa = self._relative(run, origin)
        return run.destination / relativa.parent / relativa.stem

    def _apartar_la_entrega_de_antes(
        self, run: FolderRun, origin: Path, carpeta: Path, *, listado: Mapping[str, os.DirEntry] | None = None
    ) -> bool:
        """La subcarpeta UPD de una entrega de antes, apartada entera al rehacer el PDF.

        A `_reemplazados` de su caja, no a la basura: es trabajo entregado. Así la
        caja queda sólo con la forma nueva, sin el mismo documento dos veces.
        """
        antes = self._entrega_de_antes(run, origin)
        if antes == carpeta:
            return False
        if listado is not None and antes.parent == carpeta:
            # Del listado que ya se tiene de la carpeta del NIC: sin otra pregunta al destino.
            entrada = listado.get(antes.name)
            if entrada is None or not entrada.is_dir():
                return False
        elif not antes.is_dir():
            return False
        sello = datetime.now().strftime("%Y%m%d-%H%M%S")
        apartado = carpeta / REEMPLAZADOS_DIR / sello / antes.name
        try:
            apartado.parent.mkdir(parents=True, exist_ok=True)
            _mover(antes, apartado)
        except OSError as error:
            logger.warning("no se pudo apartar la entrega de antes %s: %s", antes, error)
            return False
        self._avisar(
            run,
            f"«{antes.name}»: la entrega de antes, en su subcarpeta, quedó en "
            f"{REEMPLAZADOS_DIR}\\{sello}; ahora sus archivos van en la carpeta de la caja.",
        )
        return True

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
        nombre_del_indice = self._nombre_del_indice(run, path, NOMBRE_DEL_INDICE)
        entregados = {str(archivo.get("ruta")) for archivo in constancia.archivos}
        prefijo = f"{path.stem}_"
        if self._plana(run) and (
            nombre_del_indice in entregados
            # `_sin_el_prefijo` y no `startswith`: de «01.pdf», «01_RECLAMO.pdf»
            # ya está en su puesto y no se ordena en cada relanzamiento.
            or any(_sin_el_prefijo(r, prefijo) != r for r in entregados)
        ):
            # Entregado a la manera de antes -- su UPD delante y su propio
            # índice --, o mal numerado con el nombre de su origen dentro
            # («01_NIC 5940155-11_01_DOCUMENTO.pdf», 2026-11-10): se ordena la
            # carpeta del NIC sin volver a procesarlo.
            run.cajas_por_ordenar.add(carpeta)
        elif self._plana(run) and constancia.indice is not None:
            run.indices[carpeta.name] = carpeta / NOMBRE_DEL_INDICE
        elif nombre_del_indice in entregados:
            run.indices[self._clave_del_indice(run, path, carpeta)] = carpeta / nombre_del_indice
        elif self._plana(run) and NOMBRE_DEL_INDICE in entregados:
            # Una entrega de antes, en su subcarpeta UPD: su índice está ahí.
            run.indices[path.stem] = self._entrega_de_antes(run, path) / NOMBRE_DEL_INDICE

    @staticmethod
    def _clave_del_indice(run: FolderRun, origin: Path, carpeta: Path) -> str:
        """El nombre de la hoja de su índice en el libro general: el UPD."""
        return origin.stem if FolderRunner._plana(run) else carpeta.name

    @staticmethod
    def _con_los_folios_del_cliente(run: FolderRun, fila: dict, origin: Path) -> dict:
        """Le pone a la fila la caja que el cliente anota de su UPD y, si es de un PDF entero, sus hojas."""
        from ..adapters.fuid_actas_de_grado import ubicacion
        from ..adapters.fuid_de_la_entrega import PDF_ENTERO

        _caja, upd = ubicacion(str(fila.get("carpeta") or ""), origin.name)
        if upd in run.cajas_del_cliente:
            fila["caja_del_cliente"] = run.cajas_del_cliente[upd]
        if not run.folios_del_cliente or not (fila.get("entero") or fila.get("tipo") == PDF_ENTERO):
            return fila
        if upd in run.folios_del_cliente:
            fila["folios_del_cliente"] = run.folios_del_cliente[upd]
        return fila

    @staticmethod
    def _sumar_filas_de_actas(run: FolderRun, filas: list[dict]) -> None:
        run.inventario_filas.extend(filas)
        for fila in filas:
            # Con la clave única de su carpeta en el destino: también las de
            # una constancia de antes, anotadas con la otra.
            carpeta = FolderRunner._carpeta_canonica(run, str(fila.get("carpeta") or ""))
            if carpeta:
                fila["carpeta"] = carpeta
            run.filas_por_carpeta.setdefault(carpeta, []).append(fila)
            run.version_de_carpeta[carpeta] = run.version_de_carpeta.get(carpeta, 0) + 1

    @staticmethod
    def _retirar_lo_que_sumo(run: FolderRun, origin: Path) -> None:
        """Quita lo que este PDF sumó en un intento anterior de la misma corrida.

        Una entrega que quedó incompleta vuelve en la vuelta final y se suma
        otra vez: sin esto, sus actas salían dos veces en el Excel y sus
        unidades dos veces en el manifiesto (2026-10-27). Se quita por
        identidad, no por contenido: dos actas iguales de dos libros son dos.
        """
        antes = run.aportes.pop(str(origin), None)
        if antes is None:
            return
        filas, unidades, resoluciones = antes
        if filas:
            fuera = {id(fila) for fila in filas}
            run.inventario_filas[:] = [f for f in run.inventario_filas if id(f) not in fuera]
            for suyas in run.filas_por_carpeta.values():
                suyas[:] = [f for f in suyas if id(f) not in fuera]
            for fila in filas:
                carpeta = str(fila.get("carpeta") or "")
                run.version_de_carpeta[carpeta] = run.version_de_carpeta.get(carpeta, 0) + 1
            # Mismo número de filas, otro contenido: que se vuelva a escribir.
            run.inventario_escritas = -1
        if unidades:
            fuera = {id(unidad) for unidad in unidades}
            run.manifest[:] = [u for u in run.manifest if id(u) not in fuera]
            run.manifiesto_escrito = -1
        run.resolutions -= resoluciones

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

    async def _procesar_por_lotes(self, run: FolderRun) -> bool:
        """Recorre el origen por lotes y procesa en paralelo a la vez. Dice si hubo algo que hacer.

        Una cadena (lo pidió el operador el 2026-10-20: «utilicemos el
        procesamiento en paralelo por lotes»): el recorrido llena una cola lote a
        lote, y los trabajadores -- tantos como «Archivos en paralelo» -- la
        vacían sin esperar a que se termine un lote para empezar el siguiente.
        Antes, al final de cada lote los que ya habían acabado se quedaban
        quietos esperando al último. El recorrido no se adelanta más de un lote:
        con un millón de PDF, la cola no se llena de rutas que tardarán horas.
        """
        cola: deque[Path] = deque()
        hay_novedad = asyncio.Event()
        estado = {"terminado": False, "hubo": False, "clasificando": False}
        ranuras = self._planificador.ranuras

        async def recorrer() -> None:
            run.recorrido_terminado = False
            try:
                async for pending, entregados in self._descubrir_por_lotes(run):
                    for path, constancia in entregados:
                        run.seen.add(str(path))
                        self._contar_lo_ya_entregado(run, path, constancia)
                    # Las carpetas de NIC entregadas a la manera de antes, ya
                    # numeradas seguidas y con un solo índice.
                    while run.cajas_por_ordenar:
                        await asyncio.to_thread(self._ordenar_la_caja, run, run.cajas_por_ordenar.pop())
                    run.ya_entregados += len(entregados)
                    run.discovered += len(pending) + len(entregados)
                    if entregados:
                        self._pedir_generales(run)
                    if pending:
                        estado["hubo"] = True
                        cola.extend(pending)
                        run.encolados.update(str(path) for path in pending)
                        run.queue.extend(str(self._relative(run, path)) for path in pending)
                        if run.state is not RunState.RECOVERING:
                            run.state = RunState.PROCESSING
                        hay_novedad.set()
                        # Los trabajadores toman lo nuevo antes de que se pida el
                        # lote siguiente: verificar lo ya entregado que viene
                        # detrás no se adelanta al primer PDF nuevo (2026-11-26).
                        await asyncio.sleep(0)
                    self._publish(run)
                    # Un lote por delante, no más.
                    while run.active and len(cola) >= self.LOTE_DEL_ORIGEN:
                        await asyncio.sleep(0.05)
                    if not run.active:
                        return
            finally:
                estado["terminado"] = True
                run.recorrido_terminado = True
                hay_novedad.set()

        async def trabajador(indice: int) -> None:
            while run.active:
                if not cola:
                    if estado["terminado"]:
                        # Con la orden de «Parar con calma», la segunda pasada
                        # no empieza: lo de los demás lo hacen ellos (2026-11-26).
                        if run.diferidos and not estado["clasificando"] and run.parando is None:
                            # La segunda pasada: las carpetas de los otros
                            # equipos, al revés -- ellos van al derecho --, para
                            # ayudar a los lentos o tomar lo de los caídos. Lo ya
                            # entregado se salta con su reclamo «hecho», mirado
                            # antes de encolar y varios a la vez: de uno en uno
                            # y con su constancia eran 7-14 h por equipo con
                            # 25 000 PDF de los demás (2026-11-25).
                            segunda = list(reversed(run.diferidos))
                            run.diferidos.clear()
                            run.segunda_pasada.update(str(path) for path in segunda)
                            if run.coordinacion is not None:
                                estado["clasificando"] = True
                                try:
                                    segunda = await asyncio.to_thread(self._clasificar_la_segunda_pasada, run, segunda)
                                finally:
                                    estado["clasificando"] = False
                                # Lo contado de los demás, a los generales en su plazo.
                                self._pedir_generales(run)
                            cola.extend(segunda)
                            hay_novedad.set()
                            continue
                        if not estado["clasificando"]:
                            return
                    # Sin `await` entre mirar y limpiar: en asyncio nadie puede
                    # meter algo en la cola en medio.
                    hay_novedad.clear()
                    await hay_novedad.wait()
                    continue
                # En pausa, o sobrando mientras la carpeta va de uno en uno:
                # se espera sin tomar nada.
                await self._esperar_turno(run, indice, cola)
                if not run.active or not cola:
                    continue
                path = cola.popleft()
                if self._para_la_segunda_pasada(run, path):
                    run.diferidos.append(path)
                    continue
                async with ranuras:
                    if not run.active:
                        return
                    if run.parando is not None:
                        # La orden de parar llegó mientras esperaba la ranura:
                        # el PDF vuelve a la cola sin tomarse.
                        cola.appendleft(path)
                        continue
                    await self._consume(run, path)
                    # El ritmo de la corrida, para estimar lo que falta.
                    run.terminados_en.append(time.monotonic())

        recorrido = asyncio.create_task(recorrer())
        try:
            # Tantos trabajadores como el tope del equipo; toman PDF sólo los
            # que caben en la cifra de ahora (`_en_paralelo`), que el operador
            # puede cambiar en marcha.
            cuantos = self._trabajadores(run)
            await asyncio.gather(*(trabajador(indice) for indice in range(cuantos)))
        finally:
            if not recorrido.done():
                recorrido.cancel()
        # Si el recorrido se rindió -- el origen no volvió --, aquí sube su error.
        await recorrido
        return estado["hubo"]

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
                    if run.parando is not None:
                        # La orden de parar llegó mientras esperaba la ranura.
                        cola.appendleft(path)
                        continue
                    await self._consume(run, path)
                    run.terminados_en.append(time.monotonic())

        cuantos = min(len(cola), self._trabajadores(run))
        await asyncio.gather(*(trabajador(indice) for indice in range(cuantos)))

    async def _esperar_turno(self, run: FolderRun, indice: int, cola: deque) -> None:
        """Lo que espera un trabajador antes de tomar el siguiente PDF.

        Tras una racha de fallos la carpeta se pausa un rato y luego sigue con
        un solo documento a la vez, hasta que uno salga bien: si la red volvió,
        el primero lo dice y vuelven todos; si no, se gasta un intento y no
        diez. Con la orden de «Parar con calma» (2026-11-26) no se toma nada
        nuevo: se espera a que ``_parar_al_vaciarse`` detenga la corrida.
        """
        while run.active and cola:
            if run.parando is not None:
                await asyncio.sleep(0.2)
                continue
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
            if indice >= self._en_paralelo(run):
                await asyncio.sleep(0.2)
                continue
            return

    def _en_paralelo(self, run: FolderRun) -> int:
        """Cuántos PDF de la carpeta pueden leerse ahora: la cifra elegida, o uno tras una racha de fallos."""
        cuantos = run.paralelo or self._planificador.por_omision
        if run.a_la_vez is not None:
            cuantos = min(cuantos, run.a_la_vez)
        return max(1, cuantos)

    def _trabajadores(self, run: FolderRun) -> int:
        """Los trabajadores que se arrancan: los del tope del equipo, para poder subir en marcha."""
        return max(run.paralelo or 0, self._planificador.por_omision, self._paralelo_maximo())

    def _paralelo_maximo(self) -> int:
        return max(1, int(getattr(self._settings, "document_workers", 1) or 1))

    def cambiar_paralelo(self, run_id: str, paralelo: int | None) -> FolderRun | None:
        """Cuántos archivos a la vez, con la carpeta en marcha (lo pidió el operador el 2026-10-28).

        Subir despierta a los trabajadores que esperaban; bajar deja terminar a
        los que están leyendo y no les da otro PDF. ``None`` vuelve al
        automático. Devuelve ``None`` si la corrida no existe o ya terminó.
        """
        run = self._runs.get(run_id)
        if run is None or not run.active:
            return None
        if paralelo:
            self._planificador.ampliar(paralelo)
        run.paralelo = paralelo
        logger.info("%s: %s archivos a la vez", run.source, paralelo or "automático,")
        self._publish(run)
        return run

    # -- el monitoreo de equipos (2026-11-26) ---------------------------------
    #
    # El operador: «un monitoreo para ver los que están conectados y poder
    # desconectarlos». La pantalla sólo sabía cuántos equipos latían, ninguno
    # podía parar a otro, y «Detener» cancelaba en el acto lo que se estaba
    # leyendo, ya pagado. Ahora un equipo puede parar a otro -- o a sí mismo --
    # con calma: termina lo que tiene en curso, lo entrega y se retira.

    #: Cada cuánto mira una corrida con la orden de «Parar con calma» si ya se vació.
    ESPERA_AL_VACIARSE = 1.0

    def equipos(self, run_id: str) -> dict | None:
        """Los equipos de la corrida compartida, para el monitoreo; ``None`` si la corrida no existe.

        Sin E/S: lo que vio la última mirada de la coordinación
        (``Coordinacion.latidos``), que es de hace un latido como mucho. Con el
        principal, la velocidad y el aviso de recursos (2026-11-27), sacados de
        esa misma foto y de quién empezó la corrida (``corrida.json``).
        """
        from .corrida_compartida import version_del_bot

        run = self._runs.get(run_id)
        if run is None:
            return None
        coordinacion = run.coordinacion
        if coordinacion is None:
            return resumen_de_la_corrida_sola(version=version_del_bot(), activa=run.active)
        corrida = coordinacion.corrida or {}
        return resumen_de_los_equipos(
            coordinacion.latidos(),
            este=coordinacion.id,
            corrida=corrida.get("id"),
            version=coordinacion.version,
            activa=run.active,
            creador_id=corrida.get("creada_por_id"),
            creador_nombre=corrida.get("creada_por"),
        )

    def ordenar_parar(self, run_id: str, equipo_id: str, modo: str, operador: str | None = None) -> dict:
        """Ordena parar a un equipo de la corrida compartida; devuelve la lista, como ``equipos``.

        «calma» termina lo que tiene en curso y no toma nada nuevo; «ya» es
        «Detener». Al propio equipo, directo; a otro, con un archivo en el
        destino que su mirada lee en el siguiente latido: hay E/S, así que se
        llama desde un hilo. Lo que no se puede, con ``EquipoNoEncontrado`` u
        ``OrdenNoPermitida`` y el motivo para el operador.

        No hay «quitar» un caído, a propósito: sus PDF los toman los demás a
        los 90 s y su latido se borra solo a los 3 min, y marcarlo «terminado»
        a mano lo dejaba fuera para siempre si en realidad seguía vivo.
        """
        if modo not in MODOS_DE_PARAR:
            raise ValueError(f"modo de parar desconocido: {modo!r}")
        run = self._runs.get(run_id)
        if run is None:
            raise EquipoNoEncontrado("El proceso de carpeta no existe")
        if not run.active:
            raise OrdenNoPermitida(CORRIDA_TERMINADA)
        coordinacion = run.coordinacion
        if coordinacion is None:
            raise OrdenNoPermitida(NO_ES_COMPARTIDA)
        resumen = self.equipos(run_id) or {}
        equipo = next((e for e in resumen.get("equipos", []) if e["id"] == equipo_id), None)
        if equipo is None or not equipo["de_esta_corrida"]:
            raise EquipoNoEncontrado(NO_ESTA_EN_LA_CORRIDA)
        motivo = por_que_no_se_puede_parar(equipo, activa=run.active)
        if motivo is not None:
            raise OrdenNoPermitida(motivo)
        orden = coordinacion.ordenar_parar(equipo_id, modo, operador)
        logger.info("%s: %s ordenó «%s» a %s", run.source, coordinacion.id, orden.get("modo"), equipo_id)
        return self.equipos(run_id) or resumen

    def _al_recibir_orden(self, run_id: str) -> Callable[[dict], None]:
        """Lo que hace la coordinación con una orden de parar: pasarla al bucle, que es donde se cumple."""
        bucle = self._loop

        def recibir(orden: dict) -> None:
            if bucle is not None and not bucle.is_closed():
                bucle.call_soon_threadsafe(self._obedecer, run_id, orden)

        return recibir

    @staticmethod
    def _quien_ordena(orden: Mapping[str, object]) -> str:
        """Quién dio la orden, para completar «Detenido por …»: «el equipo SIAR (operador Juan)»."""
        equipo = orden.get("equipo_que_ordena") or orden.get("por") or "otro"
        operador = str(orden.get("operador") or "").strip()
        return f"el equipo {equipo}" + (f" (operador {operador})" if operador else "")

    def _obedecer(self, run_id: str, orden: dict) -> None:
        """Cumple, en el bucle, la orden de parar que recibió este equipo.

        «ya» es «Detener»: lo que se estaba leyendo se suelta y lo toman los
        demás. «calma» deja terminar lo que tiene en curso y no toma nada
        nuevo: ``_esperar_turno`` retiene a los trabajadores, la segunda pasada
        y el cierre no empiezan, y ``_parar_al_vaciarse`` la detiene cuando ya
        no le queda nada.
        """
        run = self._runs.get(run_id)
        if run is None or not run.active:
            # Una corrida que ya no está activa pero cuya coordinación sigue
            # latiendo (se detuvo en un mal momento): la orden la retira, o los
            # demás la esperarían para siempre (2026-11-26).
            coordinacion = getattr(run, "coordinacion", None)
            if run is not None and coordinacion is not None and not coordinacion.retirado:
                asyncio.get_running_loop().run_in_executor(None, self._retirarse, run)
            return
        quien = self._quien_ordena(orden)
        al_empezar = quien[:1].upper() + quien[1:]
        if orden.get("modo") == "ya":
            run.detenido_por = f"{quien}, con «Parar ya»"
            self._avisar(
                run,
                f"{al_empezar} ordenó «Parar ya»: este equipo se detiene ahora y lo que estaba leyendo "
                "lo retoman los otros equipos.",
            )
            self.stop(run_id)
            return
        if run.parando is not None:
            return
        run.parando = dict(orden)
        en_curso = len(run.tomados)
        lo_suyo = (
            f"termina los {en_curso} PDF que tiene en curso"
            if en_curso > 1
            else "termina el PDF que tiene en curso"
            if en_curso == 1
            else "no tiene nada en curso"
        )
        self._avisar(
            run,
            f"{al_empezar} ordenó «Parar con calma»: este equipo {lo_suyo}, no toma ninguno nuevo y se "
            "detiene; lo demás lo hacen los otros equipos.",
        )
        self._publish(run)
        tarea = asyncio.get_running_loop().create_task(self._parar_al_vaciarse(run))
        self._paradas.add(tarea)
        tarea.add_done_callback(self._paradas.discard)

    async def _parar_al_vaciarse(self, run: FolderRun) -> None:
        """Con la orden de «Parar con calma», detiene la corrida cuando ya no le queda nada en curso.

        Mira cada ``ESPERA_AL_VACIARSE``; si la corrida deja de estar activa por
        otra vía -- «Detener», «Parar ya», o termina --, se acaba sin más.
        """
        while run.active and not self._parar_si_se_vacio(run):
            await asyncio.sleep(self.ESPERA_AL_VACIARSE)

    def _parar_si_se_vacio(self, run: FolderRun) -> bool:
        """Detiene la corrida si ya no lee, entrega ni baja nada. Dice si ya no está activa.

        Si el equipo está cerrando la corrida -- la auditoría, los generales
        finales --, no la interrumpe: termina sola.
        """
        if not run.active:
            return True
        if run.tomados or run.bajando or getattr(run.coordinacion, "estado", None) == "cerrando":
            return False
        run.detenido_por = f"{self._quien_ordena(run.parando or {})}, con «Parar con calma»"
        self._avisar(run, "«Parar con calma»: este equipo terminó lo que tenía en curso y se detiene.")
        self.stop(run.id)
        return True

    async def _consume(self, run: FolderRun, path: Path) -> None:
        """Un PDF de la carpeta: procesarlo, entregarlo y contarlo.

        Lo que falle aquí -- la entrega, el disco -- cuenta como un documento
        fallido y la carpeta sigue: con varios a la vez, dejar que el error
        subiera tumbaba también a los que estaban leyéndose al lado.

        Uno solo a la vez por PDF en este equipo: si ya lo está leyendo otro
        trabajador (entró dos veces en la cola), éste no hace nada. Se leía y
        se pagaba dos veces, y el que acababa primero soltaba el reclamo del
        otro (2026-11-25). Sólo se toca desde el bucle de asyncio.
        """
        clave = str(path)
        run.encolados.discard(clave)
        # Lo ya tomado en esta corrida sólo vuelve si se soltó a propósito (la
        # vuelta de reintento, lo de un equipo caído: lo sacan de lo visto).
        if clave in run.tomados or clave in run.seen:
            relativa = str(self._relative(run, path))
            if relativa in run.queue:
                run.queue.remove(relativa)
            logger.info("«%s» ya se tomó en este equipo: no se toma dos veces", relativa)
            return
        run.tomados.add(clave)
        try:
            await self._consumir_uno(run, path)
        finally:
            run.tomados.discard(clave)

    async def _consumir_uno(self, run: FolderRun, path: Path) -> None:
        run.seen.add(str(path))
        relativa = str(self._relative(run, path))
        # Casi siempre es el primero de la cola: sacarlo así no recorre la
        # cola entera, que con veinte mil PDF sumaba minutos.
        if run.queue and run.queue[0] == relativa:
            del run.queue[0]
        elif relativa in run.queue:
            run.queue.remove(relativa)

        if run.coordinacion is not None:
            # Con otros equipos en el mismo destino, el PDF se reclama antes de
            # bajarlo o leerlo: lo hace uno solo y se paga una vez. En fila (un
            # cerrojo de asyncio es FIFO): de aquí a crear su trabajo no hay
            # otro `await`, así que los trabajos salen en el orden de la carpeta.
            try:
                async with run.orden_de_toma:
                    procesarlo, contado = await asyncio.to_thread(self._tomar_el_pdf, run, path, relativa)
            except Exception as error:  # noqa: BLE001 - el destino que no contesta: se reintenta luego
                self._avisar(run, f"No se pudo reclamar «{relativa}» en el destino: {explicar_fallo(error)}")
                run.failed += 1
                run.fallidos[str(path)] = explicar_fallo(error)
                self._publish(run)
                return
            if contado:
                self._pedir_generales(run)
            if not procesarlo:
                self._publish(run)
                return

        # Al retomar, antes de nada se mira qué hay de este PDF en el destino.
        # Lo completo no se vuelve a leer, y de lo que está a medias se leen
        # sólo las páginas que faltan.
        paginas: list[int] | None = None
        control: ControlDeUnLibro | None = None
        #: Por qué no se entregó un PDF que sigue siendo de este equipo (su
        #: latido no volvió a tiempo): se suelta con el motivo y se reintenta aquí.
        perdido_propio: str | None = None
        #: Lo que este PDF escribe en el destino en su hilo -- la entrega, su
        #: constancia -- mientras lo escribe: cancelar no para el hilo, y su
        #: reclamo no se suelta hasta que acaba (``_esperar_lo_que_escribe``).
        escribiendo: asyncio.Task | None = None
        #: Si al cancelarlo ya había quedado entregado entero, con su constancia completa.
        entregado_al_cancelar = False
        # De una carpeta de red se procesa una copia local, bajada justo antes
        # y borrada al terminar (ver `_copia_local`).
        local = self._copia_local(run, path)
        if run.retomar in (Retomar.FALTANTES, Retomar.REVISAR):
            # La constancia, antes de bajar nada: un libro ya completo no se
            # baja de la red sólo para descubrir que no hacía falta.
            mirada = None
            if run.retomar == Retomar.FALTANTES:
                mirada = await asyncio.to_thread(self._vigencia, run, path)
            if local != path and not (mirada and mirada[0] is Vigencia.VIGENTE):
                try:
                    await self._bajar_sin_trabajo(run, path, relativa, local)
                except Exception as error:  # noqa: BLE001 - un PDF que no baja no tumba la carpeta
                    self._avisar(run, f"No se pudo traer «{relativa}» de la red: {explicar_fallo(error)}")
                    run.failed += 1
                    run.fallidos[str(path)] = explicar_fallo(error)
                    self._publish(run)
                    return
            control, paginas, seguir = await self._mirar_el_destino(run, path, relativa, local, mirada)
            if not seguir:
                self._borrar_la_copia(path, local)
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
            source=local,
            owns_source=False,
            size=huella[0],
            operator=run.operator,
            task=run.task,
            oracle=run.oracle,
            lectura=run.lectura,
            corte=run.corte,
            agrupar=run.agrupar,
            territorial=run.territorial,
            acta=run.acta,
            oficina=run.oficina,
            tipo=run.tipo,
            tipo_documento=run.tipo_documento,
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
            if local != path and not local.exists():
                # Dentro del `try`: una red que se corta a mitad de la copia es
                # un fallo pasajero de este PDF, que vuelve en la vuelta de
                # reintento, y no de la carpeta.
                # La tarjeta lo dice, con cifras: el tamaño mientras espera su
                # turno de descarga, y lo bajado, la velocidad y lo que falta
                # mientras baja (el operador, 2026-11-09). Sin esto enseñaba
                # «En cola 0/?» como si no tuviera relación con la corrida.
                avance = AvanceDeLaDescarga(total=job.bytes)
                self._registry.anotar_descarga(job.id, avance.esperando())
                self._registry.publish(job)
                try:
                    await asyncio.to_thread(
                        red_smb.traer,
                        str(path),
                        local,
                        self._al_bajar(run, path),
                        al_avanzar=self._al_avanzar(avance, partial(self._registry.anotar_descarga, job.id)),
                    )
                finally:
                    self._registry.anotar_descarga(job.id, None)
                self._registry.publish(job)
            # El PDF que tiene abierto otro programa -- el visor de alguien, el
            # antivirus, otra corrida del bot -- se espera un poco antes de darlo
            # por fallido («The process cannot access the file because it is
            # being used by another process», 2026-10-22).
            await asyncio.to_thread(_esperar_a_que_se_libere, local)
            # Y el que todavía se está copiando a la carpeta se espera a que
            # deje de crecer: leído a medias se entregaba incompleto y, con
            # «Borrarlo», se borraba después el original ya completo. La huella
            # que vale es la de ese momento, la del PDF que de verdad se lee.
            if local == path:
                huella = await asyncio.to_thread(_esperar_a_que_termine_de_copiarse, path) or huella
            await self._run_job(job)

            run.bytes_total += job.bytes
            run.pages_total += job.progress.page_count
            if job.state is JobState.DONE:
                run.processed += 1
                run.resolutions += len(((job.report or {}).get("groups")) or [])
                escribiendo = asyncio.create_task(asyncio.to_thread(self._deliver, run, job, path, huella))
                entrega = await asyncio.shield(escribiendo)
                escribiendo = None
                if entrega.ya_estaba is not None:
                    # Otro equipo lo entregó entero mientras éste lo leía (lo
                    # dio por caído un momento): se cuenta como suyo y no se
                    # entrega otra vez. Su reclamo se suelta en el «finally»,
                    # que sólo lo borra si sigue siendo de este equipo.
                    run.processed -= 1
                    run.resolutions -= len(((job.report or {}).get("groups")) or [])
                    await asyncio.to_thread(
                        partial(self._entregado_por_otro, run, path, "otro equipo", constancia=entrega.ya_estaba)
                    )
                    self._avisar(run, f"«{relativa}»: otro equipo ya lo había entregado entero; no se entrega otra vez.")
                    return
                if entrega.fallos and len(entrega.pendientes) == len(entrega.fallos):
                    # Sólo falló copiar -- la red, un momento --: se reintenta
                    # la copia, no el PDF. Rehacerlo entero volvía a leer cada
                    # página y a pagar el OCR (2026-10-27).
                    await self._recopiar(run, entrega, path)
                if entrega.fallos:
                    # Lo copiado a medias no es una entrega: el PDF cuenta
                    # como fallido, el original se queda donde estaba y la
                    # constancia sigue diciendo «entregando», así que la
                    # próxima corrida lo rehace entero.
                    run.processed -= 1
                    run.resolutions -= len(((job.report or {}).get("groups")) or [])
                    run.incompletas.add(str(path))
                    run.entregas_incompletas = len(run.incompletas)
                    raise EntregaIncompleta(
                        f"La entrega quedó incompleta: {len(entrega.fallos)} archivo(s) no se "
                        f"copiaron al destino ({'; '.join(entrega.fallos[:3])}). Vuelva a lanzar "
                        "la carpeta: este PDF se rehará."
                    )
                escribiendo = asyncio.create_task(
                    asyncio.to_thread(self._dejar_constancia, run, job, path, huella, entrega)
                )
                cerrada = await asyncio.shield(escribiendo)
                escribiendo = None
                if cerrada:
                    reclamo = run.reclamos.pop(str(path), None)
                    if reclamo is not None:
                        # «Hecho» para los demás equipos: ninguno lo vuelve a tomar.
                        await asyncio.to_thread(run.coordinacion.terminar, reclamo, trabajo=job.id)
                elif run.coordinacion is not None:
                    # Sin su constancia completa no es una entrega: se suelta con
                    # el motivo y se rehace (lo entregado se aparta al rehacerlo).
                    run.processed -= 1
                    run.resolutions -= len(((job.report or {}).get("groups")) or [])
                    run.incompletas.add(str(path))
                    run.entregas_incompletas = len(run.incompletas)
                    raise EntregaIncompleta(
                        f"No se pudo cerrar la constancia de «{relativa}» en el destino: se rehará."
                    )
                if str(path) in run.incompletas:
                    # Una vuelta posterior sí la terminó.
                    run.incompletas.discard(str(path))
                    run.entregas_incompletas = len(run.incompletas)
                no_se_dividio = (job.report or {}).get("division_error")
                if no_se_dividio:
                    # El Excel salió, pero las páginas siguen sólo en el
                    # original: borrarlo o apartarlo las perdería.
                    self._avisar(
                        run,
                        f"«{relativa}» no se pudo dividir ({no_se_dividio}); el original se dejó en su sitio.",
                    )
                else:
                    await asyncio.to_thread(self._dispose, run, path, huella)
                if control is not None:
                    await self._comprobar_el_destino(run, path, control, local)
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
            # Detener la corrida le llega a cada documento, también al que
            # esperaba turno: sin esto se quedaba «En cola · esperando turno»
            # para siempre en la pantalla, aunque ya nunca fuera a correr
            # (2026-10-29).
            if job.state in IN_FLIGHT:
                self._registry.mark_cancelled(job)
                if control is not None:
                    control.accion = "cancelado"
            if escribiendo is not None and run.coordinacion is not None:
                # «Detener» o «Parar ya» con la entrega escribiendo en el destino
                # en su hilo, que sigue: se espera antes de soltar el reclamo (en
                # el «finally»). Soltado antes, otro equipo lo tomaba sin ver aún
                # su constancia y lo entregaba encima: «01_UPD022 (2).pdf» (2026-11-26).
                entregado_al_cancelar = await self._esperar_lo_que_escribe(escribiendo, relativa)
                if not entregado_al_cancelar:
                    # No es una entrega: lo cuenta quien lo rehaga.
                    run.processed -= 1
                    run.resolutions -= len(((job.report or {}).get("groups")) or [])
            raise
        except ReclamoPerdido as error:
            if job.state is JobState.DONE:
                run.processed -= 1
                run.resolutions -= len(((job.report or {}).get("groups")) or [])
            reclamo = run.reclamos.get(str(path))
            propio = False
            if reclamo is not None and run.coordinacion is not None:
                coordinacion = run.coordinacion

                def sigue_siendo_propio() -> bool:
                    # En una corrida que ya no vale (otro empezó una nueva, o se
                    # cerró) lo hacen los demás, aunque su reclamo viejo siga aquí.
                    return (
                        not coordinacion.desplazado
                        and coordinacion.por_que_no_vale() is None
                        and coordinacion.sigue_siendo_mio(reclamo)
                    )

                try:
                    propio = await asyncio.to_thread(sigue_siendo_propio)
                except Exception:  # noqa: BLE001 - sin poder mirarlo, lo decide su espera
                    propio = False
            if propio:
                # Nadie lo tomó: fue el latido propio, que no volvió a tiempo (el
                # destino sin contestar). Se suelta con su motivo -- los demás no
                # lo pagan otra vez -- y se reintenta aquí, en la vuelta final.
                # Antes se quedaba «en curso» para siempre y la corrida no cerraba.
                perdido_propio = str(error)
                job.reintentable = True
                run.failed += 1
                run.fallidos[str(path)] = f"no se pudo entregar: {error}"
                self._avisar(run, f"«{relativa}»: {error}. Se reintenta al final en este equipo.")
            else:
                # Otro equipo lo dio por caído y lo tomó: lo entrega él. No es un
                # fallo de este PDF, y aquí no se entrega nada más. Su reclamo se
                # suelta igual en el «finally», que sólo lo borra si es de éste.
                run.ajenos[str(path)] = "otro equipo"
                self._avisar(run, f"«{relativa}»: {error}. Lo entrega el otro equipo.")
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
            reclamo = run.reclamos.pop(str(path), None)
            if reclamo is not None and run.coordinacion is not None and entregado_al_cancelar:
                # Quedó entregado entero, con su constancia completa, antes de que
                # llegara «Detener»: «hecho» para los demás, que no lo rehacen.
                try:
                    await asyncio.shield(asyncio.to_thread(run.coordinacion.terminar, reclamo, trabajo=job.id))
                except (asyncio.CancelledError, Exception):  # noqa: BLE001 - quien lo tome verá su constancia
                    logger.warning("no se pudo dejar como hecho el reclamo de %s", relativa, exc_info=True)
            elif reclamo is not None and run.coordinacion is not None:
                # No se entregó: se suelta para los demás, con el motivo si falló
                # (el reintento lo hace este equipo; los otros no lo pagan otra vez).
                fallo = job.error if job.state is JobState.FAILED else perdido_propio
                try:
                    await asyncio.shield(
                        asyncio.to_thread(
                            run.coordinacion.soltar, reclamo, error=fallo, reintentable=bool(job.reintentable)
                        )
                    )
                except (asyncio.CancelledError, Exception):  # noqa: BLE001 - el latido lo dará por libre
                    logger.warning("no se pudo soltar el reclamo de %s", relativa, exc_info=True)
            self._borrar_la_copia(path, local)
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

    #: Cuánto espera, como mucho, «Detener» (o «Parar ya») a que acabe lo que
    #: un PDF ya escribía en el destino en su hilo, antes de soltar su reclamo.
    ESPERA_DE_LA_ENTREGA_AL_DETENER = 120.0

    async def _esperar_lo_que_escribe(self, escribiendo: asyncio.Task, relativa: str) -> bool:
        """Espera, con tope, lo que un PDF cancelado escribía en el destino en su hilo. Dice si quedó entregado entero.

        Cancelar la corrida cancela la espera, no el hilo: la entrega sigue
        copiando. Si su reclamo se soltaba ya, otro equipo lo tomaba, no veía
        todavía su constancia «entregando» -- no se había escrito -- y lo
        entregaba encima: «01_UPD022 (2).pdf», igual al original (2026-11-26).
        Esperada, quien lo tome después ve lo que dejó y lo aparta al
        rehacerlo, o lo encuentra entregado. Con tope: un destino que no
        contesta no deja «Detener» colgado; pasado, se suelta como antes.
        """
        if not escribiendo.done():
            try:
                await asyncio.wait({escribiendo}, timeout=self.ESPERA_DE_LA_ENTREGA_AL_DETENER)
            except asyncio.CancelledError:
                # Otra cancelación encima (el servicio que se apaga): no se espera más.
                pass
        if not escribiendo.done():
            # Su fallo, si acaba fallando, se recoge: nadie más lo va a esperar.
            escribiendo.add_done_callback(lambda tarea: tarea.cancelled() or tarea.exception())
            logger.warning("«%s» seguía escribiendo en el destino al detener: se suelta igual", relativa)
            return False
        if escribiendo.cancelled() or escribiendo.exception() is not None:
            return False
        resultado = escribiendo.result()
        if isinstance(resultado, Entrega):
            # La entrega plana por el camino rápido cierra su constancia en su turno.
            resultado = resultado.cerrada
        return resultado is True

    #: Cuántas veces se reintenta sólo la copia antes de dar la entrega por incompleta.
    VECES_QUE_SE_RECOPIA = 2

    async def _recopiar(self, run: FolderRun, entrega: Entrega, origin: Path) -> None:
        """Reintenta las copias que fallaron, al mismo nombre, con una espera entre medias.

        Fuera del cerrojo mientras se espera; dentro mientras se copia. Lo que
        sale se apunta igual que en la entrega; si algo sigue sin salir, la
        entrega queda incompleta como siempre y el PDF vuelve al final.
        """
        espera = float(getattr(self._settings, "espera_de_reintento", 15.0) or 0)
        for _ in range(self.VECES_QUE_SE_RECOPIA):
            if not entrega.pendientes:
                return
            await asyncio.sleep(espera)
            await asyncio.to_thread(self._copiar_lo_pendiente, run, entrega, origin)

    def _copiar_lo_pendiente(self, run: FolderRun, entrega: Entrega, origin: Path) -> None:
        quedan: list[tuple[Path, Path, bool]] = []
        fallos: list[str] = []
        with contextlib.ExitStack() as cerrojos:
            # En la entrega plana, el orden de cerrojos de ``FolderRun.cerrojo``:
            # el de la corrida sólo para su memoria, nunca con el destino de por medio.
            if self._plana(run):
                from .correccion_del_re import cerrojo_de_la_carpeta

                cerrojos.enter_context(self._turno_de(run, entrega.base))
                cerrojos.enter_context(cerrojo_de_la_carpeta(entrega.base))
                cerrojos.enter_context(self._entregas)
            else:
                cerrojos.enter_context(self._turno_de(run, entrega.base))
                cerrojos.enter_context(run.cerrojo)
            self._confirmar(run, origin)
            for desde, hasta, reemplaza in entrega.pendientes:
                try:
                    if not reemplaza and hasta.exists():
                        # Otro tomó el nombre mientras tanto: no se pisa.
                        raise FileExistsError(errno.EEXIST, "el nombre ya está ocupado", str(hasta))
                    hasta.parent.mkdir(parents=True, exist_ok=True)
                    _copiar(desde, hasta, self._al_entregar(run, origin))
                except OSError as error:
                    quedan.append((desde, hasta, reemplaza))
                    fallos.append(f"«{hasta.name}»: {_explicar_la_entrega(error, hasta)}")
                    continue
                if entrega.archivos is not None and hasta not in entrega.archivos:
                    entrega.archivos.append(hasta)
                with run.cerrojo:
                    run.record(
                        Delivery(
                            file_name=hasta.name,
                            source_document=str(self._relative(run, origin)),
                            destination=str(hasta.parent),
                        )
                    )
        entrega.pendientes = quedan
        entrega.fallos = fallos

    # -- la red: red o local, su velocidad y lo que falta (2026-11-05) ------------

    #: Cada cuánto se vuelve a medir la lectura del origen con la corrida en
    #: marcha, y con cuánto: poco, para no quitarle red a la corrida.
    SEGUNDOS_ENTRE_MEDIDAS = 300.0
    MUESTRA_EN_VIVO = 2 * 1024 * 1024
    #: Cuánto se espera a que el recorrido encuentre un PDF para la prueba de lectura.
    ESPERA_AL_PRIMER_PDF = 600.0

    async def _medir_la_red(self, run: FolderRun) -> None:
        """Si el origen y el destino son de red, la prueba del arranque y la lectura en vivo.

        La prueba (el operador la eligió el 2026-11-05: «prueba al empezar + en
        vivo»): escribe y borra unos MB en el destino y lee unos MB del primer PDF
        que encuentre el recorrido. Después, cada ``SEGUNDOS_ENTRE_MEDIDAS``, una
        muestra pequeña del siguiente de la cola; las descargas y las entregas
        reales también se miden (``_al_bajar``, ``_al_entregar``). Nada de aquí
        toca la corrida: medir es para informar, y un fallo sólo se anota.
        """
        from ..adapters import acceso
        from ..domain.ritmo import mb_por_segundo

        prueba = run.prueba_de_red
        # Un origen que se baja con el cliente SMB ya se mide con cada descarga
        # (``_al_bajar``), y la primera sale en cuanto arranca la corrida: leer
        # además una muestra sería bajar dos veces, y de lo ya entregado, nunca.
        por_descargas = red_smb.por_smb(run.source)
        try:
            run.origen_de_red = await asyncio.to_thread(acceso.es_de_red, run.source)
            run.destino_de_red = await asyncio.to_thread(acceso.es_de_red, run.destination)
            prueba.clear()
            prueba["estado"] = "midiendo"
            self._publish(run)
            # Escribir: una muestra, si la carpeta ya está; si no, la primera
            # entrega, que la crea. La prueba no crea carpetas que no se eligieron.
            if await asyncio.to_thread(run.destination.is_dir):
                try:
                    escritos, segundos = await asyncio.to_thread(acceso.medir_escritura, run.destination)
                    prueba["escritura_mb_s"] = mb_por_segundo(escritos, segundos)
                except Exception as error:  # noqa: BLE001 - se informa, la corrida sigue
                    prueba["escritura_error"] = explicar_fallo(error)
            # Leer: la primera descarga, o una muestra del primer PDF pendiente
            # -- uno que se va a leer de todos modos, nunca uno ya entregado --.
            muestra = None if por_descargas else await self._un_pdf_del_origen(run)
            if muestra is not None:
                try:
                    leidos, segundos = await asyncio.to_thread(acceso.medir_lectura, muestra)
                    prueba["lectura_mb_s"] = mb_por_segundo(leidos, segundos)
                    prueba["muestra"] = re.split(r"[\\/]", muestra)[-1]
                except Exception as error:  # noqa: BLE001 - se informa, la corrida sigue
                    prueba["lectura_error"] = explicar_fallo(error)
            self._publish(run)
            if por_descargas or "escritura_mb_s" not in prueba:
                await self._lo_primero_que_se_mueva(run, leer=por_descargas)
            prueba["estado"] = "hecha"
            self._publish(run)
            while await self._dormir_mientras_siga(run, self.SEGUNDOS_ENTRE_MEDIDAS):
                if por_descargas:
                    continue
                siguiente = next(iter(list(run.huellas_del_origen)), None)
                if siguiente is None:
                    continue
                try:
                    leidos, segundos = await asyncio.to_thread(
                        acceso.medir_lectura, siguiente, self.MUESTRA_EN_VIVO
                    )
                except Exception:  # noqa: BLE001 - la próxima vez
                    logger.debug("no se pudo medir la lectura de %s", siguiente, exc_info=True)
                    continue
                fin = time.monotonic()
                run.ritmo_de_lectura.sumar(leidos, fin - segundos, fin)
                self._publish(run)
        except Exception:  # noqa: BLE001 - medir nunca tumba la corrida
            logger.warning("no se pudo medir la red de %s", run.source, exc_info=True)

    async def _un_pdf_del_origen(self, run: FolderRun) -> str | None:
        """El primer PDF pendiente que encuentre el recorrido; ``None`` si no aparece ninguno.

        Sólo pendientes: uno ya entregado no se vuelve a leer, ni para medir.
        """
        limite = time.monotonic() + self.ESPERA_AL_PRIMER_PDF
        while run.active and time.monotonic() < limite:
            primero = next(iter(list(run.huellas_del_origen)), None)
            if primero:
                return str(primero)
            if run.recorrido_terminado:
                return None
            await asyncio.sleep(0.5)
        return None

    async def _lo_primero_que_se_mueva(self, run: FolderRun, *, leer: bool) -> None:
        """Lo que falta de la prueba, de la primera descarga y la primera entrega reales.

        Se espera como mucho ``ESPERA_AL_PRIMER_PDF``: una corrida que no baja ni
        entrega nada -- todo ya estaba -- no tiene nada que medir, y la pantalla
        lo dice con «—».
        """
        prueba = run.prueba_de_red
        limite = time.monotonic() + self.ESPERA_AL_PRIMER_PDF
        while run.active and time.monotonic() < limite:
            if leer and "lectura_mb_s" not in prueba and run.ritmo_de_lectura.medidas:
                prueba["lectura_mb_s"] = run.ritmo_de_lectura.mb_por_segundo()
                prueba["muestra"] = "la primera descarga"
                self._publish(run)
            if "escritura_mb_s" not in prueba and "escritura_error" not in prueba and run.ritmo_de_escritura.medidas:
                prueba["escritura_mb_s"] = run.ritmo_de_escritura.mb_por_segundo()
                self._publish(run)
            listo_leer = not leer or "lectura_mb_s" in prueba
            listo_escribir = "escritura_mb_s" in prueba or "escritura_error" in prueba
            if listo_leer and listo_escribir:
                return
            await asyncio.sleep(0.5)

    @staticmethod
    async def _dormir_mientras_siga(run: FolderRun, segundos: float) -> bool:
        """Espera ``segundos`` o hasta que la corrida termine; dice si sigue."""
        limite = time.monotonic() + segundos
        while run.active and time.monotonic() < limite:
            await asyncio.sleep(min(1.0, max(0.0, limite - time.monotonic())))
        return run.active

    async def _bajar_sin_trabajo(self, run: FolderRun, path: Path, relativa: str, local: Path) -> None:
        """Baja de la red un PDF que todavía no tiene trabajo -- al retomar --, y dice cómo va.

        Su avance va en la corrida (``FolderRun.bajando``), como mucho una vez
        por segundo: esa trama pesa mucho más que la de un trabajo.
        """
        avance = AvanceDeLaDescarga(total=run.huellas_del_origen.get(str(path), (0, 0))[0], intervalo=1.0)
        run.bajando[relativa] = avance.esperando()
        self._publish(run)

        def anotar(datos: dict) -> None:
            if relativa in run.bajando:
                run.bajando[relativa] = datos
                # Una vez por segundo para toda la corrida, aunque bajen varios.
                ahora = time.monotonic()
                if ahora - run.bajando_publicado >= 1.0:
                    run.bajando_publicado = ahora
                    self._publish(run)

        try:
            await asyncio.to_thread(
                red_smb.traer,
                str(path),
                local,
                self._al_bajar(run, path),
                al_avanzar=self._al_avanzar(avance, anotar),
            )
        finally:
            run.bajando.pop(relativa, None)
            self._publish(run)

    @staticmethod
    def _al_avanzar(avance: AvanceDeLaDescarga, entregar: Callable[[dict], None]) -> Callable[[int, int], None]:
        """Lo que hace el hilo que baja con cada bloque: contarlo y, si toca avisar, pasarlo al bucle.

        Se crea en el bucle y se llama desde el hilo de la descarga: lo que
        cambia en el trabajo o en la corrida se cambia siempre en el bucle,
        como ``_publish``.
        """
        bucle = asyncio.get_running_loop()

        def avanzar(copiados: int, total: int) -> None:
            datos = avance.avanzar(copiados, time.monotonic(), total)
            if datos is not None and not bucle.is_closed():
                bucle.call_soon_threadsafe(entregar, datos)

        return avanzar

    @staticmethod
    def _al_bajar(run: FolderRun, path: Path) -> Callable[[int, float, float], None]:
        """Lo que se anota de cada descarga de la red: la velocidad de la corrida y la de su PDF."""

        clave = str(FolderRunner._relative(run, path))

        def anotar(bytes_: int, inicio: float, fin: float) -> None:
            run.ritmo_de_lectura.sumar(bytes_, inicio, fin)
            run.medidas_del_pdf.setdefault(clave, {})["lectura"] = (bytes_, fin - inicio)

        return anotar

    @staticmethod
    def _al_entregar(run: FolderRun, path: Path) -> Callable[[int, float, float], None]:
        """Lo que se anota de cada PDF que se copia al destino: suma a lo de su PDF de origen."""

        clave = str(FolderRunner._relative(run, path))

        def anotar(bytes_: int, inicio: float, fin: float) -> None:
            run.ritmo_de_escritura.sumar(bytes_, inicio, fin)
            antes = run.medidas_del_pdf.setdefault(clave, {}).get("escritura", (0, 0.0))
            run.medidas_del_pdf[clave]["escritura"] = (antes[0] + bytes_, antes[1] + (fin - inicio))

        return anotar

    #: Dónde se dejan, mientras se procesan, las copias de los PDF de una carpeta de red.
    CARPETA_DE_COPIAS = "red"

    def _copia_local(self, run: FolderRun, path: Path) -> Path:
        """El PDF que se procesa: el mismo, o su copia local si viene de la red.

        La copia conserva la ruta entera del servidor -- «…/200.100.20.97/afinia/
        REPOSITORIO/AFINIA/BOLIVAR SUR/COMERCIAL/MAGANGUE/210847/UPD….pdf» --
        porque el Índice Electrónico lee de ella el municipio y el NIC.
        """
        partes = red_smb.partes(path) if red_smb.por_smb(path) else None
        if partes is None:
            return path
        base = Path(self._settings.upload_dir) / self.CARPETA_DE_COPIAS / run.id
        copia = base.joinpath(partes.servidor, partes.recurso, *partes.resto.split("\\"))
        # Segunda llave: pase lo que pase con la ruta, la copia no sale de aquí.
        if base.resolve() not in copia.resolve().parents:
            raise FolderError(f"La ruta de red no es válida: {path}")
        return copia

    @staticmethod
    def _borrar_la_copia(path: Path, local: Path) -> None:
        """Una copia de la red no se queda ocupando disco cuando su PDF terminó."""
        if local == path:
            return
        try:
            local.unlink(missing_ok=True)
        except OSError:
            logger.warning("no se pudo borrar la copia local %s", local, exc_info=True)

    def _limpiar_las_copias(self, run: FolderRun) -> None:
        """Al terminar o detener una corrida de red, nada suyo queda en la carpeta de copias."""
        if red_smb.por_smb(run.source):
            shutil.rmtree(
                Path(self._settings.upload_dir) / self.CARPETA_DE_COPIAS / run.id, ignore_errors=True
            )

    def _anotar_el_proceso(self, run: FolderRun, job: Job, relativa: str) -> None:
        from .indices import con_la_red, fila_de_proceso

        medidas = run.medidas_del_pdf.pop(relativa, {})
        if str(job.state) == "done":
            # Lo que el revisor de cortes hizo con este PDF, a la cuenta de la
            # corrida. Nunca tumba la anotación: es para la pantalla.
            try:
                run.agente.sumar(Path(relativa).name, job.report or {})
            except Exception:  # noqa: BLE001 - la cuenta del agente no es la entrega
                logger.debug("no se pudo sumar el revisor de %s", relativa, exc_info=True)
        if str(job.state) in ("done", "failed", "cancelled"):
            # Con el acceso de cada lado y la velocidad con que se bajó y se
            # entregó este PDF; si no se movió por la red -- un origen local, o
            # uno de red que el sistema abre directo --, la de la corrida.
            lectura, escritura = run.velocidades()
            run.procesos[relativa] = con_la_red(
                fila_de_proceso(job, self._destino_relativo(run, job)),
                origen_de_red=run.origen_de_red,
                destino_de_red=run.destino_de_red,
                lectura=medidas.get("lectura"),
                escritura=medidas.get("escritura"),
                lectura_de_la_corrida=lectura,
                escritura_de_la_corrida=escritura,
            )

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
                self._escribir_todo_lo_general(run, a_mitad=True)

    async def _auditar_al_cerrar(self, run: FolderRun) -> None:
        """La auditoría de cierre: el cuadre del origen con el destino y la muestra de 100 PDF.

        Lo pidió el operador el 2026-11-05: que el bot, así como vigila cada PDF
        mientras procesa, lo haga también al terminar -- que lo de la fuente
        esté en el destino y que 100 PDF al azar se revisen otra vez con los
        patrones y el margen de error (ver ``api/auditoria.py``). Lo que la
        corrida nunca llegó a tomar -- una carpeta que no se dejó leer -- se
        procesa antes de cerrar. Nunca tumba la corrida: si no se puede hacer,
        se dice y lo entregado queda como está.
        """
        from ..domain.auditoria import TAMANO_DE_LA_MUESTRA
        from .auditoria import (
            UNIDAD_FILAS,
            UNIDAD_PDF,
            auditar_la_muestra,
            auditar_las_filas,
            cuadrar,
            etapa_de,
            filas_candidatas,
        )

        semilla = int(time.time())
        run.auditoria = {"estado": "auditando", "fase": "cuadre", "hechos": 0, "total": 0, "semilla": semilla}
        self._publish(run)

        def avance_del_cuadre(hechos: int, total: int) -> None:
            run.auditoria = {**(run.auditoria or {}), "hechos": hechos, "total": total}
            self._publish(run)

        def avance_de_la_muestra(hechos: int, resultado) -> None:
            actual = run.auditoria or {}
            run.auditoria = {
                **actual,
                "hechos": hechos,
                "total": max(int(actual.get("total") or 0), hechos),
                "ultimo": resultado.as_dict(),
            }
            self._publish(run)

        def detener() -> bool:
            return not run.active

        try:
            comparacion, entregas = await asyncio.to_thread(
                cuadrar, self, run, detener=detener, avance=avance_del_cuadre
            )
            nunca = [falta for falta in comparacion["pdf_sin_entregar"] if not falta["intentado"]]
            if nunca and run.active:
                self._avisar(
                    run,
                    f"Al cerrar, faltaban {len(nunca)} PDF en el destino que la corrida no había tomado "
                    "(una carpeta que no se dejó leer, un listado cortado): se procesan antes de terminar.",
                )
                await self._procesar_por_lotes(run)
                comparacion, entregas = await asyncio.to_thread(cuadrar, self, run, detener=detener)
            run.comparacion = comparacion
            # Sin PDF cortados -- «Solo inventario» -- lo que se entregó son
            # filas, y la muestra es de filas: cada una contra sus páginas del
            # original (el operador, 2026-11-09: salía «muestra: 0 de 0»).
            # Por los PDF **entregados** (``documentos_entregados``), no por los
            # PDF del origen ya entregados (``pdf_entregados``): con éstos, una
            # corrida de «Solo inventario» con todo entregado nunca iba a la
            # muestra de filas -- ni las historias, ni el inventario de
            # Kingspan -- y salía la de PDF, sin ninguno que abrir (2026-11-10).
            filas = filas_candidatas(entregas) if not comparacion["documentos_entregados"] else {}
            de_filas = bool(filas)
            run.auditoria = {
                "estado": "auditando",
                "fase": "muestra",
                "unidad": UNIDAD_FILAS if de_filas else UNIDAD_PDF,
                "hechos": 0,
                "total": min(TAMANO_DE_LA_MUESTRA, len(filas) if de_filas else comparacion["pdf_entregados"]),
                "semilla": semilla,
            }
            self._publish(run)
            from ..application.consumo import Consumo

            # La IA que busca en el papel los datos dudosos -- y, desde el
            # 2026-11-10, las fechas dudosas de las dos muestras --, sólo si
            # la corrida se hizo con ella.
            consumo = Consumo()
            juez = self._juez_de_los_datos(run, consumo)
            if de_filas:
                muestra = await asyncio.to_thread(
                    auditar_las_filas,
                    self,
                    run,
                    entregas,
                    semilla=semilla,
                    juez=juez,
                    detener=detener,
                    avance=avance_de_la_muestra,
                )
            else:
                muestra = await asyncio.to_thread(
                    auditar_la_muestra,
                    self,
                    run,
                    entregas,
                    semilla=semilla,
                    juez=self._juez_de_la_auditoria(run),
                    juez_de_datos=juez,
                    detener=detener,
                    avance=avance_de_la_muestra,
                )
            # Lo que costó la IA de los datos en la auditoría, a la vista: se
            # paga por tokens y no se suma al de la corrida, que ya cerró.
            muestra["con_ia"] = juez is not None
            if juez is not None:
                muestra["consumo_ia"] = consumo.as_dict()
            run.etapa, run.etapa_detalle = etapa_de(comparacion, muestra)
            run.auditoria = {"estado": "hecha", "semilla": semilla, "muestra": muestra, "fecha": _now()}
            if run.etapa != "Terminado":
                self._avisar(run, f"Auditoría de cierre: {run.etapa} — {run.etapa_detalle}")
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - la auditoría nunca tumba la corrida
            logger.exception("la auditoría de cierre de %s falló", run.source)
            run.auditoria = {"estado": "no se pudo", "error": explicar_fallo(error), "semilla": semilla}
            self._avisar(
                run,
                f"La auditoría de cierre no se pudo hacer ({explicar_fallo(error)}). Lo entregado no cambia.",
            )
        self._publish(run)

    def _juez_de_la_auditoria(self, run: FolderRun):
        """La IA que decide las dudas de la muestra, sólo si la corrida se hizo con ella."""
        llave = getattr(self._settings, "mistral_api_key", None)
        if run.lectura not in ("mistral", "mistral-nombres") or not llave:
            return None
        from ..adapters.mistral_revisor import MistralJuezDeCosturas

        return MistralJuezDeCosturas(api_key=llave)

    def _juez_de_los_datos(self, run: FolderRun, consumo=None):
        """La IA que busca en el papel los datos dudosos de la muestra de filas, sólo si la corrida se hizo con ella.

        Con «Detener»: una vez detenida la corrida no se le pide nada más.
        """
        llave = getattr(self._settings, "mistral_api_key", None)
        if run.lectura not in ("mistral", "mistral-nombres") or not llave:
            return None
        from ..adapters.mistral_juez_de_datos import MistralJuezDeDatos
        from ..application.control import Cancelled

        def antes_de_pedir() -> None:
            if not run.active:
                raise Cancelled("la corrida se detuvo")

        return MistralJuezDeDatos(api_key=llave, consumo=consumo, antes_de_pedir=antes_de_pedir)

    async def _escribir_generales_luego(self, run: FolderRun) -> None:
        while run.generales_pendientes:
            cada = INVENTARIO_GENERAL_CADA if run.coordinacion is None else INVENTARIO_GENERAL_CADA_COMPARTIDA
            espera = cada - (time.monotonic() - run.generales_en)
            if run.generales_en and espera > 0:
                await asyncio.sleep(espera)
            run.generales_pendientes = False
            await asyncio.to_thread(self._escribir_todo_lo_general, run, a_mitad=True)

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
        if run.task == "segment":
            # Las métricas y la evidencia de la extracción (2026-11-18), una
            # vez, de las constancias: un fallo aquí no tumba la corrida.
            await asyncio.to_thread(self._escribir_las_metricas, run)

    def _escribir_las_metricas(self, run: FolderRun) -> None:
        from ..application.metricas_de_la_extraccion import LaCorrida
        from .metricas import escribir_la_auditoria, escribir_las_metricas

        try:
            escribir_las_metricas(run.destination)
        except Exception:  # noqa: BLE001 - la entrega ya está; las métricas se rehacen con su script
            logger.warning("no se pudieron escribir las métricas de la extracción", exc_info=True)
        # La auditoría de esta corrida sola (el operador, 2026-11-20: «por
        # proceso ejecutado»): sus PDF, lo que no tomaron y los que fallaron.
        try:
            corrida = LaCorrida(
                inicio=run.started_at,
                fin=run.finished_at or _now(),
                origen=str(run.source),
                destino=str(run.destination),
                encontrados=run.discovered,
                # Con varios equipos, la corrida es una sola: lo que procesaron
                # los demás cuenta aquí como procesado, no como ya entregado.
                procesados=run.processed + run.de_otros_equipos,
                ya_entregados=run.ya_entregados - run.de_otros_equipos,
                fallidos={**dict(run.fallidos), **run.fallidos_en_otro},
                operador=run.operator or "",
                dictamen=f"{run.etapa} — {run.etapa_detalle}".strip(" —") if run.etapa else "",
            )
            # Los trabajos de todos los equipos de la corrida: una sola auditoría.
            trabajos = [*run.job_ids, *run.trabajos_de_otros]
            if run.coordinacion is not None:
                try:
                    de_la_corrida, fallidos = run.coordinacion.lo_hecho_en_la_corrida()
                    trabajos = sorted({*trabajos, *de_la_corrida})
                    corrida = replace(
                        corrida,
                        # Desde que el primer equipo la empezó.
                        inicio=str((run.coordinacion.corrida or {}).get("creada") or corrida.inicio),
                        procesados=max(corrida.procesados, len(de_la_corrida)),
                        ya_entregados=max(0, corrida.ya_entregados),
                        fallidos={**fallidos, **corrida.fallidos},
                    )
                except OSError:
                    logger.warning("no se pudo leer lo hecho en la corrida compartida", exc_info=True)
            escribir_la_auditoria(run.destination, corrida, trabajos)
        except Exception:  # noqa: BLE001 - la entrega ya está
            logger.warning("no se pudo escribir la auditoría de la corrida", exc_info=True)

    def _escribir_todo_lo_general(self, run: FolderRun, *, a_mitad: bool = False) -> None:
        """Los Excel generales de la raíz del destino.

        ``a_mitad``: los que se escriben mientras la carpeta corre. Con otros
        equipos sobre el mismo destino, sólo los escribe el principal
        (2026-11-27; si cae o se retira, quien le sigue), sin el índice
        general -- que mira el índice de cada NIC -- y sin esperar el turno más
        de ``ESPERA_DEL_TURNO_A_MITAD``. Los definitivos, con todo, los escribe
        el principal al cerrar la corrida.

        Antes los escribía el primero que tomaba el rol «generales», que nunca
        se soltaba: podía quedarse en un PC con pocos recursos, o en uno que ya
        no estaba. Ahora no hay rol: el principal escribe con el turno de los
        generales (``cerrojo("generales")``), como antes, y los demás ni lo piden.
        """
        coordinacion = run.coordinacion
        compartida = coordinacion is not None and not coordinacion.retirado
        # Con otros equipos, los Excel de la raíz de uno en uno entre todos:
        # dos reemplazando el mismo archivo a la vez lo dejarían roto.
        if compartida and (coordinacion.desplazado or coordinacion.por_que_no_vale() is not None):
            # Un equipo que volvió tarde no reescribe los generales que ya
            # cerró otro con todo: los dejaría con lo suyo y nada más.
            logger.warning("%s: no se reescriben los generales, la corrida compartida ya no es de este equipo", run.source)
            return
        # Con otros equipos vivos, los de a mitad son de uno solo; si este va solo
        # (el modo «auto» con un solo PC), como siempre: con el índice y el FUID.
        a_mitad = a_mitad and compartida and len(coordinacion.equipos_vivos()) > 1
        if a_mitad and not coordinacion.puede_entregar():
            # Con el latido propio atrasado, los demás pueden haberlo dado por
            # caído y tener ya otro principal.
            run.generales_en = time.monotonic()
            return
        if a_mitad and coordinacion.principal() not in (None, coordinacion.id):
            # Los escribe el principal: éste no pregunta por el turno y los
            # vuelve a pedir en su plazo, por si entretanto le toca serlo. Sin
            # principal -- con «Parar todos con calma», la manera de actualizar,
            # todos tienen orden y nadie lo es -- los escribe cualquiera, de uno
            # en uno con el turno «generales»: si no, nadie los escribía al
            # detenerse (2026-11-27).
            run.generales_en = time.monotonic()
            return
        turno = (
            coordinacion.cerrojo("generales", espera_maxima=ESPERA_DEL_TURNO_A_MITAD if a_mitad else 10 * 60.0)
            if compartida
            else contextlib.nullcontext()
        )
        try:
            with turno, run.cerrojo_generales:
                self._escribir_control(run)
                self._escribir_generales(run, con_indice=not a_mitad)
                run.generales_en = time.monotonic()
        except CerrojoOcupado as error:
            # Se vuelven a pedir en su plazo, no en el acto: reintentarlo enseguida
            # eran otros diez minutos preguntando por el turno.
            run.generales_en = time.monotonic()
            if not a_mitad:
                self._avisar(run, f"Los Excel generales esperan su turno: {error}. Se vuelven a escribir luego.")

    async def _mirar_el_destino(
        self,
        run: FolderRun,
        path: Path,
        relativa: str,
        local: Path | None = None,
        mirada: tuple[Vigencia, Constancia | None] | None = None,
    ) -> tuple[ControlDeUnLibro, list[int] | None, bool]:
        """Qué hay de este PDF en el destino, y qué hacer: (control, páginas, seguir).

        ``páginas`` es ``None`` para procesarlo entero. ``seguir`` es falso
        cuando no hay nada que procesar: ya estaba completo, sólo se revisa, o
        no se pudo mirar. ``mirada`` es lo que ya dijo su constancia, si se
        miró antes de bajarlo de la red.
        """
        from .retomar import conciliar_libro, que_hacer

        carpeta = self._output_dir(run, path)
        control = ControlDeUnLibro(pdf=relativa, carpeta=self._relativa_al_destino(run, carpeta))
        run.controles[relativa] = control
        if run.retomar == Retomar.FALTANTES:
            # Con la constancia de una entrega completa no hace falta leer el
            # libro página a página -- veinte segundos por libro desde la red --:
            # ya se sabe que está entero.
            vigencia, constancia = mirada or await asyncio.to_thread(self._vigencia, run, path)
            if vigencia is Vigencia.VIGENTE:
                relativa = str(self._relative(run, path))
                run.verificaciones[relativa] = (
                    DECISION_YA_ENTREGADO,
                    run.motivos.get(str(path), "la constancia y los archivos entregados siguen vigentes"),
                )
                control.accion = "ya estaba completo (constancia de entrega): no se volvió a leer"
                run.ya_entregados += 1
                self._contar_lo_ya_entregado(run, path, constancia)
                return control, None, False
            motivo = run.motivos.get(str(path))
            if motivo:
                run.verificaciones[str(self._relative(run, path))] = (DECISION_SE_COMPARA, motivo)
        try:
            # El libro se abre de su copia local si viene de la red.
            control.antes, control.ilegibles = await asyncio.to_thread(
                conciliar_libro, local or path, carpeta, run.huellas
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
        self, run: FolderRun, path: Path, control: ControlDeUnLibro, local: Path | None = None
    ) -> None:
        """Vuelve a mirar el destino tras entregar: lo que dice el control es lo que hay."""
        from .retomar import conciliar_libro

        try:
            control.despues, control.ilegibles = await asyncio.to_thread(
                conciliar_libro, local or path, self._output_dir(run, path), run.huellas
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
        def escribir() -> None:
            with run.cerrojo:
                ruta = escribir_control(
                    list(run.controles.values()),
                    run.destination,
                    origen=run.source.name or str(run.source),
                    operador=run.operator,
                )
            if ruta is not None:
                run.control = str(ruta)

        self._escribir_general(run, NOMBRE_DEL_CONTROL_DE_ENTREGA, escribir)

    def _escribir_general(self, run: FolderRun, nombre: str, escribir: Callable[[], object]) -> None:
        """Escribe un Excel de la raíz; si no se deja, lo avisa en pantalla y sigue.

        Cada uno por su cuenta: el primero abierto en Excel se llevaba por
        delante a los demás, y el fallo quedaba sólo en el registro del
        servicio, donde el operador no mira (2026-10-27). Lo entregado de cada
        PDF ya está en el disco; el general se reescribe en la próxima pasada.
        """
        try:
            escribir()
        except Exception as error:  # noqa: BLE001 - lo entregado ya está en el disco
            logger.warning("no se pudo escribir «%s» de %s", nombre, run.source, exc_info=True)
            self._avisar(
                run,
                f"No se pudo actualizar «{nombre}» en el destino: {explicar_fallo(error)} "
                "Se vuelve a escribir solo mientras la carpeta siga; al terminar, si sigue sin "
                "estar al día, vuelva a lanzar la carpeta.",
            )

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
        from ..adapters.fuid_de_la_entrega import ruta_del_fuid
        from ..adapters.indice_electronico import NOMBRE_DEL_INDICE
        from .indices import (
            NOMBRE_DEL_FUID_GENERAL,
            inventario_de_procesos_de,
            libro_de_indices_de,
        )

        with run.cerrojo:
            filas = list(run.procesos.values())
            indices = sorted(run.indices.items())
            carpetas_con_fuid = self._carpetas_con_fuid(run)
            analisis = self._filas_del_analisis(run)
            avisos = list(run.avisos)
            del_inventario = list(run.inventario_filas)
            # Lo medido de la red, para su sección en el inventario de procesos.
            red = run.resumen_de_la_red()
            # También el de una corrida anterior que ésta todavía no reescribió.
            de_las_subcarpetas = {Path(ruta) for ruta in run.inventarios_de_carpeta.values()} | {
                ruta_del_fuid(FolderRunner._en_destino(run, carpeta)) for carpeta in run.filas_por_carpeta if carpeta
            }
        # Buscar cada FUID en el disco va fuera del cerrojo: con cientos de
        # libros, recorrer el destino cada 45 s paraba todas las entregas. Sin
        # el FUID de cada subcarpeta, que ya va en el general por sus filas:
        # leerlo además del disco las contaría dos veces.
        fuids = [(ruta, carpeta) for ruta, carpeta in self._fuids_en(carpetas_con_fuid) if ruta not in de_las_subcarpetas]
        self._escribir_general(
            run,
            NOMBRE_DEL_INVENTARIO_DE_PROCESOS,
            lambda: inventario_de_procesos_de(
                filas,
                run.destination,
                origen=run.source.name or str(run.source),
                clase_de_origen="Carpeta",
                operador=run.operator,
                red=red,
            ),
        )
        if con_indice:
            if indices:
                self._escribir_general(
                    run, NOMBRE_DEL_INDICE, lambda: libro_de_indices_de(indices, run.destination, lecturas=run.lecturas_de_indices)
                )
            self._escribir_general(
                run, NOMBRE_DEL_FUID_GENERAL, lambda: self._escribir_el_fuid_general(run, fuids, del_inventario)
            )
        if run.tipo_documento == "kingspan":
            # El inventario oficial de Kingspan es un solo libro para toda
            # la entrega, no uno por UPD.
            from .worker.kingspan import NOMBRE_DEL_GENERAL, inventario_general

            self._escribir_general(run, NOMBRE_DEL_GENERAL, lambda: inventario_general(run.destination))
        self._escribir_el_analisis(run, analisis, avisos)

    @staticmethod
    def _escribir_el_fuid_general(run: FolderRun, fuids: list[tuple[Path, str]], filas: list[dict]) -> None:
        """«00.FUID GENERAL.xlsx»: todas las filas de la corrida en un solo FUID.

        Las de cada habilidad -- actas, graduados, estudiantes, matrículas --
        en el orden de la carpeta, y detrás las de los libros de diplomas, que
        se leen de su FUID en el destino. Con la oficina de la carpeta en la
        cabecera. Es el inventario general que pidió el operador el 2026-10-29:
        el mismo FUID para cada carpeta.

        Va en la carpeta espejo de la elegida, uno por carpeta (ver
        ``_ruta_del_inventario``). Un estante de sólo libros de diplomas lo
        sigue dejando en la raíz del destino, donde lo dejaba siempre.
        """
        from ..adapters.fuid_de_la_entrega import filas_del_fuid
        from ..application.acta_consejo import inventario_de_la_carpeta
        from .indices import fuid_general_de

        ordenadas = inventario_de_la_carpeta(filas) if filas else []
        ruta = fuid_general_de(
            fuids,
            FolderRunner._en_destino(run, FolderRunner._raiz(run)) if ordenadas else run.destination,
            lecturas=run.lecturas_de_fuid,
            otras=filas_del_fuid(ordenadas),
            # Sólo con filas de las demás habilidades: un estante de libros de
            # diplomas conserva la cabecera de sus FUID (Secretaría General),
            # aunque el nombre de la carpeta nombre una facultad.
            oficina=run.oficina if ordenadas else None,
        )
        if ruta is not None and ordenadas:
            run.inventario = str(ruta)
            # El general de actas de antes del 2026-11-11, en la misma carpeta.
            FolderRunner._retirar_el_de_actas(run, Path(ruta).parent)

    def _escribir_el_analisis(self, run: FolderRun, filas: list, avisos: list[str]) -> None:
        """«00.ANALISIS DE LA ENTREGA.xlsx» en la raíz del destino. Que falle no deshace nada."""
        from ..adapters.analisis_de_la_entrega import escribir_analisis

        try:
            ruta = escribir_analisis(
                run.destination,
                filas,
                origen=al_operador(run.source),
                fecha=datetime.now().strftime("%Y-%m-%d %H:%M"),
                avisos=avisos,
                # La auditoría de cierre, cuando ya se hizo (2026-11-05).
                comparacion=run.comparacion,
                muestra=(run.auditoria or {}).get("muestra"),
            )
            run.analisis = str(ruta)
        except Exception as error:  # noqa: BLE001 - lo entregado ya está en el disco
            logger.warning("no se pudo escribir el análisis de %s", run.source, exc_info=True)
            self._avisar(
                run,
                f"No se pudo escribir «00.ANALISIS DE LA ENTREGA.xlsx» en el destino "
                f"({run.destination}): {explicar_fallo(error)}. Cierre el archivo si está abierto "
                "y vuelva a lanzar la carpeta.",
            )

    def _filas_del_analisis(self, run: FolderRun) -> list:
        """Cada PDF de la corrida: qué se decidió al verificarlo, por qué, y qué pasó después.

        Lo pidió el operador el 2026-10-22: reconocer de un vistazo las carpetas y
        los PDF ya procesados y los que no. Se llama bajo ``run.cerrojo`` y sólo
        lee lo que la corrida ya guarda: ni el origen ni el destino.
        """
        from ..adapters.analisis_de_la_entrega import (
            CANCELADO,
            EN_PROCESO,
            FALLO,
            PENDIENTE,
            PROCESADO,
            REVISADO,
            YA_ENTREGADO,
            FilaDelAnalisis,
        )

        resultados = {
            "Ya entregado": YA_ENTREGADO,
            "Listo": PROCESADO,
            "Falló": FALLO,
            "Cancelado": CANCELADO,
        }
        en_curso = set(run.en_curso.values())
        en_cola = set(run.queue)
        fallidos = {str(self._relative(run, Path(ruta))): motivo for ruta, motivo in run.fallidos.items()}
        relanzar = "Vuelva a lanzar la carpeta: sólo se procesa lo que falte."
        filas = []
        for relativa in set(run.verificaciones) | set(run.procesos) | en_cola | en_curso | set(fallidos):
            decision, motivo = run.verificaciones.get(relativa, ("—", ""))
            proceso = run.procesos.get(relativa)
            control = run.controles.get(relativa)
            documentos = paginas = 0
            if relativa in en_curso:
                resultado, detalle = EN_PROCESO, "se está procesando ahora"
            elif proceso is not None:
                documentos, paginas = int(proceso.documentos or 0), int(proceso.paginas or 0)
                resultado = resultados.get(proceso.estado, PENDIENTE)
                partes = [f"en «{proceso.destino}»" if proceso.destino and resultado != FALLO else ""]
                if resultado == FALLO:
                    partes.append(proceso.observaciones or fallidos.get(relativa) or "sin detalle")
                    if not run.active:
                        partes.append(relanzar)
                elif proceso.estado == "Cancelado":
                    partes.append("lo canceló el operador")
                if getattr(proceso, "en_revision", 0):
                    partes.append(f"{proceso.en_revision} página(s) a revisión")
                detalle = "; ".join(parte for parte in partes if parte)
            elif relativa in fallidos:
                resultado = FALLO
                detalle = fallidos[relativa] + ("" if run.active else f"; {relanzar}")
            elif control is not None:
                if control.error:
                    resultado = FALLO
                elif run.retomar == Retomar.REVISAR:
                    resultado = REVISADO
                else:
                    resultado = YA_ENTREGADO
                detalle = control.error or control.accion or ""
            elif relativa in en_cola:
                resultado, detalle = PENDIENTE, "en la cola"
            else:
                resultado, detalle = PENDIENTE, "no se llegó a procesar en esta corrida"
            carpeta = Path(relativa).parent.as_posix()
            filas.append(
                FilaDelAnalisis(
                    carpeta="(raíz)" if carpeta == "." else carpeta,
                    pdf=Path(relativa).name,
                    verificacion=decision,
                    motivo=motivo,
                    resultado=resultado,
                    detalle=detalle,
                    documentos=documentos,
                    paginas=paginas,
                )
            )
        return filas

    @staticmethod
    def _carpetas_con_fuid(run: FolderRun) -> dict[str, Path]:
        """Las carpetas del destino con un libro de diplomas de esta corrida. Sólo memoria."""
        carpetas: dict[str, Path] = dict(run.carpetas_con_fuid)
        for control in run.controles.values():
            carpetas.setdefault(control.carpeta, FolderRunner._en_destino(run, control.carpeta))
        return carpetas

    @staticmethod
    def _fuids_en(carpetas: dict[str, Path]) -> list[tuple[Path, str]]:
        """Los FUID de esas carpetas, tal como están en el destino.

        Del destino y no de los trabajos: al retomar, los libros que ya estaban
        completos no se procesan y su FUID sólo está ahí, y uno retomado a
        medias tiene ahí el suyo ya sumado a lo anterior. Mira el disco: se
        llama sin el cerrojo de la corrida.
        """
        from .retomar import fuid_del_libro

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
    def _plana(run: FolderRun) -> bool:
        """Si la entrega va directa en la carpeta de la caja, sin subcarpeta por PDF.

        Lo pidió el operador el 2026-10-21 para la caja de correspondencia:
        «DESTINO\\210847» con lo de cada UPD dentro, no «DESTINO\\210847\\UPD…».
        De 30 003 cajas de MAGANGUE, 6 266 traen dos o tres UPD, así que todo lo
        de un PDF lleva su UPD delante (`_prefijo`) y nunca pisa lo de otro.
        Las demás habilidades siguen con su carpeta por PDF.
        """
        return str(run.task) == "segment"

    @staticmethod
    def _prefijo(run: FolderRun, origin: Path) -> str:
        """Lo que va delante de cada archivo de un PDF en una entrega plana: «UPD2998726_»."""
        return f"{origin.stem}_" if FolderRunner._plana(run) else ""

    @staticmethod
    def _nombre_de_la_constancia(run: FolderRun, origin: Path) -> str:
        """La constancia de un PDF: una por PDF también en la carpeta compartida de su caja."""
        if FolderRunner._plana(run):
            return f"{Path(constancias.NOMBRE).stem}-{origin.stem}.json"
        return constancias.NOMBRE

    @staticmethod
    def _nombre_del_indice(run: FolderRun, origin: Path, nombre: str) -> str:
        """«00.INDICE ELECTRONICO UPD2998726.xlsx» en una entrega plana; tal cual si no."""
        if FolderRunner._plana(run):
            hoja = Path(nombre)
            return f"{hoja.stem} {origin.stem}{hoja.suffix}"
        return nombre

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

        Con el destino de la corrida («<elegida> - PROCESADO») es el espejo de
        la fuente con una carpeta por libro, el árbol que eligió el operador el
        2026-11-27 viendo los dos («lo deje como está en la fuente, pero
        dividido»): la misma ruta que ``_espejo`` más el nombre del PDF, igual
        que dejan sus libros las actas y las historias (``document_folder``).
        Lo fija ``test_entrega_espejo_por_libro.py``.
        """
        relativa = FolderRunner._relative(run, origin)
        if FolderRunner._plana(run):
            # La caja de correspondencia, plana: la carpeta de la caja.
            return run.destination / relativa.parent
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
        # Con otros equipos: el turno de su carpeta del destino y, dentro, que
        # el PDF siga siendo de este equipo (la barrera contra el que vuelve
        # después de que lo dieran por caído).
        if self._entrega_en_el_nic(run, job):
            entrega = self._entregar_en_el_nic(run, job, origin, huella)
        else:
            from .correccion_del_re import cerrojo_de_la_carpeta

            carpeta = self._output_dir(run, origin, job)
            # En la entrega plana, también el cerrojo de la carpeta del NIC, en
            # el orden de ``FolderRun.cerrojo``: sin coordinación el turno no es
            # nada, y una entrega por aquí y otra por el camino rápido al mismo
            # NIC se cruzaban.
            del_nic = cerrojo_de_la_carpeta(carpeta) if self._plana(run) else contextlib.nullcontext()
            with self._turno_de(run, carpeta), del_nic:
                self._confirmar(run, origin)
                with run.cerrojo:
                    entrega = self._entregar(run, job, origin, huella)
        # Los FUID de las subcarpetas que cambiaron, fuera del cerrojo: las
        # demás entregas siguen mientras se escriben.
        self._escribir_los_pendientes(run)
        return entrega

    def _entrega_en_el_nic(self, run: FolderRun, job: Job) -> bool:
        """Si el PDF se entrega en la carpeta de su NIC por el camino rápido (``_entregar_en_el_nic``).

        La caja de correspondencia con su Índice Electrónico, que es el caso de
        las corridas grandes. Lo demás -- actas, Kingspan, una caja sin índice
        con su planilla -- sigue por ``_entregar`` con el cerrojo de la corrida.
        """
        informe = job.report or {}
        return (
            self._plana(run)
            # Retomar a medias -- sólo las páginas que faltan -- suma a lo ya
            # entregado en vez de rehacerlo: sigue por su camino de siempre.
            and run.retomar in (Retomar.NO, Retomar.TODO)
            and bool(informe.get("indice_electronico"))
            and not informe.get("inventario_actas")
            and job.tipo_documento != "kingspan"
        )

    def _entregar_en_el_nic(
        self, run: FolderRun, job: Job, origin: Path, huella: tuple[int, int]
    ) -> Entrega:
        """La entrega plana de un PDF en la carpeta de su NIC: de una vez y sin parar a las demás.

        Hasta el 2026-11-25 cada entrega escribía en el destino con el cerrojo de
        la corrida tomado, y un PC entregaba de uno en uno: unos 20 s por PDF
        contra el Escritorio de un Windows compartido por siete PC, con los ya
        leídos esperando 14-29 min. Ahora:

        - lo que se puede hacer en local -- la lista de PDF, el índice del UPD,
          las citas de cada PDF -- se hace antes, sin ningún turno;
        - una sola sección con el turno de la carpeta entre equipos, el de la
          carpeta en este proceso y el turno de entregas del equipo (el orden de
          ``FolderRun.cerrojo``): la barrera (``_confirmar``), la copia, la
          constancia «completa» y el orden de la carpeta, con el turno tomado
          una vez y no dos; entregas a NIC distintos van a la vez;
        - el cerrojo de la corrida, sólo un momento y sólo para su memoria.

        Si una copia falla, la entrega vuelve sin cerrar y sigue como siempre
        (``_recopiar`` y ``_dejar_constancia``).
        """
        from .correccion_del_re import cerrojo_de_la_carpeta

        carpeta = self._output_dir(run, origin, job)
        preparada = self._preparar_la_entrega_plana(job)
        with self._turno_de(run, carpeta), cerrojo_de_la_carpeta(carpeta), self._entregas:
            self._confirmar(run, origin)
            entrega = self._entregar_plano(run, job, origin, huella, preparada)
            if entrega.ya_estaba is not None or entrega.fallos:
                return entrega
            constancia = self._constancia_completa(run, job, origin, huella, entrega)
            # Otra vez la barrera, justo antes de lo que no tiene vuelta atrás.
            self._confirmar(run, origin)
            try:
                constancias.escribir(entrega.constancia, constancia, carpeta_existe=True)
                entrega.cerrada = True
            except OSError as error:
                entrega.cerrada = False
                logger.warning("no se pudo cerrar la constancia de %s: %s", origin.name, error)
                self._avisar(run, f"No se pudo guardar la constancia de «{origin.name}»: {explicar_fallo(error)}")
            # La carpeta del NIC, con este UPD ya dentro: numerada seguida y con
            # un solo índice. Con el mismo turno, que es reentrante.
            self._ordenar_la_caja(run, carpeta)
        return entrega

    def _preparar_la_entrega_plana(self, job: Job) -> _EntregaPreparada:
        """Lo que la entrega plana necesita y está en este equipo: sin turno ni red."""
        from ..adapters.indice_electronico import leer_indice
        from .correccion_del_re import citas_del_pdf

        informe = job.report or {}
        producido = self._settings.output_dir / job.id
        try:
            # Recursivo: los documentos de una caja se escriben en una carpeta
            # con el nombre de la caja (ver ``_entregar``).
            archivos = sorted(producido.rglob("*.pdf"))
        except OSError:
            archivos = []
        indice = None
        nombre = informe.get("indice_electronico")
        if nombre:
            try:
                for hoja in sorted(producido.rglob(str(nombre)))[:1]:
                    indice = _indice_a_dict(leer_indice(hoja))
                    # Sus PDF, numerados en el orden de sus filas (2026-11-11).
                    indice["por_fecha"] = bool(informe.get("numerado_por_fecha"))
            except Exception:  # noqa: BLE001 - sin sus filas, el índice de la carpeta sale sin ellas
                logger.warning("no se pudo leer el índice de %s", job.filename, exc_info=True)
        citas = {}
        for archivo in archivos:
            suyas = citas_del_pdf(archivo)
            if suyas is not None:
                citas[archivo] = suyas
        return _EntregaPreparada(archivos=archivos, indice=indice, citas=citas)

    #: Las esperas antes de reintentar una copia que falló por la red, con el turno
    #: de su carpeta tomado: un corte de unos segundos («Host is down») no rehace
    #: un PDF ya leído y pagado.
    ESPERAS_DE_LA_COPIA = (2.0, 5.0, 15.0)

    def _entregar_plano(
        self, run: FolderRun, job: Job, origin: Path, huella: tuple[int, int], preparada: _EntregaPreparada
    ) -> Entrega:
        """Copia lo de un PDF en la carpeta de su NIC. Con su turno tomado; la memoria, con ``run.cerrojo`` breve.

        Nada queda a medias: si una copia no sale ni reintentándola, se borra lo
        que esta entrega alcanzó a copiar y vuelve con su fallo, para rehacerse
        entera (su constancia sigue «entregando», con lo que iba a copiar).
        """
        carpeta = self._output_dir(run, origin, job)
        ruta_de_la_constancia = carpeta / self._nombre_de_la_constancia(run, origin)
        prefijo = self._prefijo(run, origin)
        relativa = str(self._relative(run, origin))
        entrega = Entrega(base=carpeta, constancia=ruta_de_la_constancia, archivos=[])
        with run.cerrojo:
            self._retirar_lo_que_sumo(run, origin)
            rehacer = run.a_rehacer.pop(str(origin), None)
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
            # Estricto: quien va a escribir no puede creer vacía una carpeta que
            # no se dejó leer (la red un momento).
            listado = _listado(carpeta, estricto=True)
        except OSError as error:
            logger.warning("no se pudo preparar %s: %s", carpeta, error)
            entrega.fallos.append(f"no se pudo leer la carpeta «{carpeta.name}»: {explicar_fallo(error)}")
            return entrega
        # Lo que dice ahora el disco de este PDF, con su turno tomado: no lo que
        # se vio al recorrer o al reclamarlo.
        actual = constancias.leer(ruta_de_la_constancia) if ruta_de_la_constancia.name in listado else None
        conocida = rehacer[1] if rehacer is not None else None
        if (
            actual is not None
            and actual.estado == EstadoDeEntrega.COMPLETA
            and run.retomar == Retomar.NO
            and (conocida is None or (actual.job_id, actual.fecha) != (conocida.job_id, conocida.fecha))
        ):
            # Lo entregó entero otro equipo mientras éste lo leía (lo dio por
            # caído un momento): entregarlo otra vez lo dejaría repetido.
            entrega.ya_estaba = actual
            return entrega
        try:
            movido = False
            if actual is not None or rehacer is not None:
                vigencia = rehacer[0] if rehacer is not None else Vigencia.INCOMPLETA
                # Lo que ya nombra la constancia completa de otro UPD de la carpeta
                # no se aparta nunca: un resto de una entrega cortada pudo quedar
                # con el mismo nombre que hoy es de otro.
                ajenos = self._nombrados_por_otros(carpeta, listado, ruta_de_la_constancia.name)
                movido = self._apartar_lo_anterior(
                    run, carpeta, actual or conocida, vigencia, prefijo=prefijo, listado=listado, proteger=ajenos
                )
                with run.cerrojo:
                    run.rehechos += 1
            movido = self._apartar_la_entrega_de_antes(run, origin, carpeta, listado=listado) or movido
            # Lo que dejó a medias una entrega cortada de este mismo UPD: va con su
            # UPD delante hasta que `_ordenar_la_caja` lo numera.
            movido = (
                self._apartar_lo_anterior(run, carpeta, None, Vigencia.SIN_CONSTANCIA, prefijo=prefijo, listado=listado)
                or movido
            )
            if movido:
                listado = _listado(carpeta, estricto=True)
        except OSError as error:
            entrega.fallos.append(f"no se pudo leer la carpeta «{carpeta.name}»: {explicar_fallo(error)}")
            return entrega
        nombres = self._nombres_en_el_nic(run, origin, preparada, carpeta, listado)
        # «Entregando» antes de copiar nada, con la lista de lo que se va a
        # copiar: si la corrida se corta a media copia, al rehacerla se aparta
        # exactamente eso, también lo que ya llevaba su nombre final.
        planeados = []
        for desde, nombre in nombres:
            try:
                planeados.append({"ruta": nombre, "bytes": desde.stat().st_size})
            except OSError:
                planeados.append({"ruta": nombre, "bytes": 0})
        self._escribir_constancia(
            ruta_de_la_constancia,
            Constancia(
                origen=relativa, tamano=huella[0], modificado_ns=huella[1], job_id=job.id, archivos=planeados
            ),
            entrega,
            carpeta_existe=True,
        )
        if entrega.fallos:
            # Sin su constancia «entregando», nada se copia: un corte dejaría
            # archivos que ninguna constancia nombra.
            return entrega
        with run.cerrojo:
            run.aportes[str(origin)] = ([], self._record(run, job, origin), 0)
        entrega.indice = preparada.indice
        renombres: dict[str, str] = {}
        entregas: list[Delivery] = []
        for desde, nombre in nombres:
            try:
                hasta, copiados = self._copiar_con_reintentos(run, origin, desde, carpeta, nombre)
            except OSError as error:
                logger.warning("could not deliver %s: %s", desde.name, error)
                entrega.fallos.append(f"«{desde.name}»: {explicar_fallo(error)}")
                # Nada a medias en la carpeta del NIC: lo que esta entrega alcanzó
                # a copiar se borra -- es suyo, y su constancia sigue «entregando»
                # --, y el PDF se rehace entero en la vuelta de reintento. Dejarlo
                # con su nombre final chocaba con el del siguiente UPD del NIC.
                for copiado in entrega.archivos:
                    with contextlib.suppress(OSError):
                        copiado.unlink(missing_ok=True)
                entrega.archivos = []
                entrega.tamanos.clear()
                entrega.citas.clear()
                return entrega
            entrega.archivos.append(hasta)
            entrega.tamanos[hasta] = copiados
            if desde in preparada.citas:
                entrega.citas[hasta] = preparada.citas[desde]
            if hasta.name != desde.name:
                renombres[desde.name] = hasta.name
            entregas.append(Delivery(file_name=hasta.name, source_document=relativa, destination=str(carpeta)))
        with run.cerrojo:
            for entregado in entregas:
                run.record(entregado)
        self._sumar_las_filas_hechas(run, job, origin, renombres)
        return entrega

    def _copiar_con_reintentos(
        self, run: FolderRun, origin: Path, desde: Path, carpeta: Path, nombre: str
    ) -> tuple[Path, int]:
        """``_copiar_directo``, esperando a que vuelva la red si se corta un momento."""
        from ..adapters.coordinacion_en_disco import es_de_la_red

        # El primer intento crea el archivo en exclusiva (si el nombre ya está
        # tomado, el siguiente libre). Los reintentos escriben encima del que
        # dejó a medias el intento anterior de esta misma entrega: con el
        # turno de la carpeta tomado, ese nombre es suyo. Pasar a un «(2)»
        # dejaba el PDF truncado con su nombre y un repetido al lado.
        propio: Path | None = None
        for espera in (*self.ESPERAS_DE_LA_COPIA, None):
            try:
                return _copiar_directo(desde, carpeta, nombre, self._al_entregar(run, origin), encima_de=propio)
            except OSError as error:
                if isinstance(error, FileExistsError) or espera is None or not es_de_la_red(error) or not run.active:
                    raise
                propio = Path(getattr(error, "filename", "") or carpeta / nombre)
                if propio.parent != carpeta:
                    propio = carpeta / nombre
                logger.warning("el destino no contesta al copiar %s (%s): se reintenta en %.0f s", nombre, error, espera)
                time.sleep(espera)
        raise OSError(errno.EIO, "la copia no salió", str(carpeta / nombre))

    @staticmethod
    def _nombrados_por_otros(carpeta: Path, listado: Mapping[str, os.DirEntry], propia: str) -> set[str]:
        """Los archivos que nombran las constancias completas de los otros UPD de la carpeta del NIC."""
        sello = f"{Path(constancias.NOMBRE).stem}-"
        nombrados: set[str] = set()
        for nombre in listado:
            if not nombre.startswith(sello) or not nombre.endswith(".json") or nombre == propia:
                continue
            otra, esta = constancias.leer_si_hay(carpeta / nombre)
            if otra is None and esta:
                # Está y no se dejó leer (la red un momento): sin saber qué es de
                # otro no se aparta nada. La entrega vuelve con su fallo y se rehace.
                raise OSError(errno.EIO, "no se pudo leer la constancia de otro UPD de la carpeta", str(carpeta / nombre))
            if otra is not None and otra.estado == EstadoDeEntrega.COMPLETA:
                nombrados.update(str(archivo.get("ruta") or "") for archivo in otra.archivos)
        return nombrados

    def _nombres_en_el_nic(
        self,
        run: FolderRun,
        origin: Path,
        preparada: _EntregaPreparada,
        carpeta: Path,
        listado: Mapping[str, os.DirEntry],
    ) -> list[tuple[Path, str]]:
        """Con qué nombre va cada PDF del UPD a la carpeta de su NIC.

        Con su UPD delante -- «UPD2998726_01_RECLAMO.pdf» -- hasta que
        ``_ordenar_la_caja`` numera la carpeta entera, que es lo de siempre
        cuando el NIC ya trae otros UPD. En una carpeta de NIC nueva (el 79 %
        de MAGANGUE trae un solo UPD) el orden sería el del propio UPD: va ya
        con su nombre final, calculado igual que lo haría el orden
        (``_numeracion_del_nic``), y no hay que renombrar nada después. Eran dos
        renombres por PDF, de casi un segundo cada uno en un destino de red lento.
        """
        prefijo = self._prefijo(run, origin)
        propios = []
        for archivo in preparada.archivos:
            nombre = archivo.name
            if nombre.startswith("_"):
                # La cuarentena va con el PDF del que salió.
                nombre = f"{origin.stem}{nombre}"
            elif prefijo:
                nombre = f"{prefijo}{nombre}"
            propios.append((archivo, nombre))
        constancia_propia = self._nombre_de_la_constancia(run, origin)
        sello_de_las_constancias = f"{Path(constancias.NOMBRE).stem}-"
        nueva = not any(
            (nombre.startswith(sello_de_las_constancias) and nombre != constancia_propia)
            or nombre.lower().endswith(".pdf")
            or nombre.startswith(PREFIJO_DE_PASO)
            for nombre in listado
        )
        finales = {nombre: nombre for _, nombre in propios}
        if nueva and propios:
            en_memoria = Constancia(
                origen=str(self._relative(run, origin)),
                tamano=0,
                modificado_ns=0,
                archivos=[{"ruta": nombre, "bytes": 0} for _, nombre in propios],
                indice=preparada.indice,
            )
            plan, _ = _numeracion_del_nic([en_memoria])
            finales = {str(archivo["ruta"]): nuevo.name for archivo, _, nuevo in plan}
        nombres = []
        tomados = set(listado)
        for desde, nombre in propios:
            final = finales.get(nombre, nombre)
            if final in tomados:
                # Un archivo que no es del bot ocupa el nombre: no se pisa.
                final = unique_path(carpeta, final).name
            tomados.add(final)
            nombres.append((desde, final))
        return nombres

    def _escribir_los_pendientes(self, run: FolderRun) -> None:
        """Escribe el FUID de las subcarpetas que apuntaron las entregas. Sin el cerrojo tomado."""
        with run.cerrojo:
            pendientes = sorted(run.fuid_pendientes)
            run.fuid_pendientes.clear()
        for carpeta in pendientes:
            self._escribir_inventario_de_actas(run, solo_carpeta=carpeta)

    def _entregar(
        self, run: FolderRun, job: Job, origin: Path, huella: tuple[int, int] = (0, 0)
    ) -> Entrega:
        self._retirar_lo_que_sumo(run, origin)
        filas = (job.report or {}).get("inventario_actas") or []
        if filas:
            # El nombre del acta suelta, antes de anotar sus filas: si ya es el
            # de otro PDF de su carpeta, se entrega con el del cliente.
            filas = self._sin_pisar_otra_suelta(run, job, origin, filas)
            # La carpeta de cada fila es su ruta desde la raíz elegida: con
            # subcarpetas, «00C003284\UPD3859772» y no sólo «UPD3859772». Es lo
            # que agrupa el Excel de cada subcarpeta y lo que encadena sus folios.
            carpeta = self._carpeta_de(run, origin)
            suyas = [{**fila, "carpeta": carpeta} for fila in filas]
            for fila in suyas:
                self._con_los_folios_del_cliente(run, fila, origin)
            self._sumar_filas_de_actas(run, suyas)
            # Las actas son sus unidades: un libro cuenta tantas como trae. Las
            # historias académicas ya las contó su informe («groups»): sumarlas
            # aquí otra vez daba el doble de estudiantes en la pantalla.
            unidades = 0 if (job.report or {}).get("groups") else len(filas)
            run.resolutions += unidades
            run.aportes[str(origin)] = (suyas, self._record(run, job, origin), unidades)
            entrega = self._entregar_actas(run, job, origin, huella)
            # El de su subcarpeta, en cuanto se suelte el cerrojo; el general,
            # cada tanto (ver `INVENTARIO_GENERAL_CADA`). Al terminar, todos.
            run.fuid_pendientes.add(carpeta)
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
        ruta_de_la_constancia = carpeta / self._nombre_de_la_constancia(run, origin)
        prefijo = self._prefijo(run, origin)
        # En la carpeta compartida de una caja, la constancia lista lo que se
        # copió de este PDF y nada más: lo demás es de los otros UPD.
        entrega = Entrega(
            base=carpeta, constancia=ruta_de_la_constancia, archivos=[] if prefijo else None
        )
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            # Ya no se entrega en la raíz del destino: lo que se dejaba ahí no
            # lo encontraba nadie, ni la corrida siguiente.
            logger.warning("no se pudo crear %s: %s", carpeta, error)
            entrega.fallos.append(
                f"no se pudo crear la carpeta «{carpeta.name}»: {_explicar_la_entrega(error, carpeta)}"
            )
            return entrega

        rehacer = run.a_rehacer.pop(str(origin), None)
        if rehacer is not None:
            anterior = None
            if prefijo:
                # La constancia del disco y no la de cuando se descubrió el PDF:
                # entretanto `_ordenar_la_caja` pudo renumerar sus PDF y
                # reescribirla. Con los nombres viejos no se apartaba nada, y lo
                # entregado quedaba sin constancia junto a lo nuevo con «(2)»
                # (la revisión, 2026-11-10). Bajo `run.cerrojo`, como el orden.
                anterior = constancias.leer(ruta_de_la_constancia) or rehacer[1]
            self._apartar_lo_anterior(run, carpeta, anterior, rehacer[0], prefijo=prefijo)
            run.rehechos += 1
        if prefijo:
            self._apartar_la_entrega_de_antes(run, origin, carpeta)
            # Lo que dejó a medias una entrega cortada de este mismo UPD: va con
            # su UPD delante hasta que `_ordenar_la_caja` lo numera.
            self._apartar_lo_anterior(run, carpeta, None, Vigencia.SIN_CONSTANCIA, prefijo=prefijo)
        # «Entregando» antes de copiar nada: si la corrida se corta a media
        # copia, la próxima ve una entrega cortada y la rehace entera.
        self._escribir_constancia(
            ruta_de_la_constancia,
            Constancia(origen=str(self._relative(run, origin)), tamano=huella[0], modificado_ns=huella[1], job_id=job.id),
            entrega,
        )

        run.aportes[str(origin)] = ([], self._record(run, job, origin), 0)
        indice = (job.report or {}).get("indice_electronico")
        if indice and prefijo:
            # La carpeta de un NIC lleva un solo Índice Electrónico para todos
            # sus UPD (lo dictó el operador el 2026-10-22): el de este PDF no se
            # copia; sus filas van en su constancia y `_ordenar_la_caja` escribe
            # el de la carpeta.
            from ..adapters.indice_electronico import leer_indice

            try:
                for hoja in sorted(produced.rglob(indice))[:1]:
                    entrega.indice = _indice_a_dict(leer_indice(hoja))
                    # Sus PDF, numerados en el orden de sus filas (2026-11-11):
                    # la carpeta los cruza con los de los otros UPD por fecha.
                    entrega.indice["por_fecha"] = bool((job.report or {}).get("numerado_por_fecha"))
            except Exception:  # noqa: BLE001 - sin sus filas, el índice de la carpeta sale sin ellas
                logger.warning("no se pudo leer el índice de %s", job.filename, exc_info=True)
        elif indice:
            # Una caja de correspondencia lleva su Índice Electrónico en lugar
            # de la planilla, y viaja tal cual junto a sus PDF: no declara a
            # dónde se entregó, así que no hay nada que reescribir. Se copia
            # aparte y no se anota como entrega, que cuenta documentos.
            try:
                for hoja in sorted(produced.rglob(indice))[:1]:
                    destino_del_indice = unique_path(
                        carpeta, self._nombre_del_indice(run, origin, hoja.name)
                    )
                    _copiar(hoja, destino_del_indice)
                    run.indices[self._clave_del_indice(run, origin, carpeta)] = destino_del_indice
                    if entrega.archivos is not None:
                        entrega.archivos.append(destino_del_indice)
            except OSError as error:
                logger.warning("no se pudo entregar el índice de %s: %s", job.filename, error)
                entrega.fallos.append(f"el índice: {explicar_fallo(error)}")
        elif job.tipo_documento == "kingspan":
            # El inventario de Kingspan es el FUID oficial de la UPD y va en
            # lugar de la planilla, como el Índice Electrónico de una caja de
            # correspondencia. Sin esto la corrida sólo copiaba los PDF: el FUID
            # se quedaba en las salidas del servicio y en el destino aparecía
            # una planilla genérica en su lugar.
            from .worker.kingspan import INVENTORY_SUFFIX as INVENTARIO_KINGSPAN

            for hoja in sorted(produced.rglob(f"*{INVENTARIO_KINGSPAN}")):
                try:
                    destino_del_fuid = unique_path(carpeta, hoja.name)
                    _copiar(hoja, destino_del_fuid)
                    if entrega.archivos is not None:
                        entrega.archivos.append(destino_del_fuid)
                except OSError as error:
                    logger.warning("no se pudo entregar el inventario de %s: %s", job.filename, error)
                    entrega.fallos.append(f"el inventario: {explicar_fallo(error)}")
        elif run.oficina and (job.report or {}).get("filas_del_fuid"):
            # Un PDF de la Universidad -- su corrida lleva la oficina de una
            # facultad -- cuyas filas van al FUID de su carpeta
            # (``_sumar_las_filas_hechas``): ninguna planilla suelta al lado. El
            # operador, 2026-11-11: «documentos de Universidad de Cartagena, un
            # único FUID». Dejaba un «INVENTARIO DE RESOLUCIONES … NO CUADRA» en
            # una carpeta con el nombre del PDF, junto a su fila del FUID.
            pass
        else:
            fallo = self._write_sheet(run, job, carpeta)
            if fallo:
                # Sin esto la constancia quedaba «completa» y la corrida
                # siguiente saltaba el PDF: la planilla no se corregía nunca.
                entrega.fallos.append(f"la planilla: {fallo}")
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
            elif prefijo:
                # En la carpeta de la caja, con su UPD delante.
                name = f"{prefijo}{name}"
            target = None
            try:
                target = unique_path(carpeta, name)
                _copiar(source_file, target, self._al_entregar(run, origin))
                if entrega.archivos is not None:
                    entrega.archivos.append(target)
            except OSError as error:
                logger.warning("could not deliver %s: %s", source_file.name, error)
                entrega.fallos.append(
                    f"«{source_file.name}»: {_explicar_la_entrega(error, target or carpeta / name)}"
                )
                # Se puede reintentar tal cual, salvo que el FUID del libro ya
                # se escribió sin conocer el nombre que le tocó.
                if target is not None and (
                    target.name == source_file.name or not (job.report or {}).get("fuid")
                ):
                    entrega.pendientes.append((source_file, target, False))
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

        fallo = self._entregar_fuid(run, job, origin, carpeta, renombres)
        if fallo:
            entrega.fallos.append(f"el FUID: {fallo}")
        self._sumar_las_filas_hechas(run, job, origin, renombres)
        return entrega

    def _sumar_las_filas_hechas(
        self, run: FolderRun, job: Job, origin: Path, renombres: dict[str, str]
    ) -> None:
        """Las filas del FUID que escribió la habilidad del PDF, al FUID de su carpeta y al general.

        Las de un legajo de resoluciones, un legajo de matrículas o un archivo
        inventariado entero: cada una ya trae su asunto, su número y sus
        fechas, y aquí se les pone la caja y la UPD de su ruta. Así una carpeta
        que trae resoluciones y actas -- «18-RESOLUCIONES INTERNAS Y ACTAS
        3303» -- deja un solo FUID con todas (2026-10-29).

        Los libros de diplomas no: su FUID va junto al libro y el general lo
        lee del destino, que es lo que deja retomar un libro a medias.
        """
        from ..adapters.fuid_de_la_entrega import FILA_HECHA
        from .indices import habilidad_del_proceso

        informe = job.report or {}
        hechas = informe.get("filas_del_fuid") or []
        if not hechas or habilidad_del_proceso(job) == "Libro de diplomas":
            return
        # Su FUID va con sus PDF: éstos se entregan en ``_output_dir``, sin la
        # carpeta elegida delante, y agruparlos por el espejo de las actas los
        # dejaba en un árbol aparte que sólo tenía el FUID (2026-10-30).
        try:
            carpeta = str(self._output_dir(run, origin, job).parent.relative_to(run.destination))
        except ValueError:
            carpeta = ""
        if carpeta in ("", "."):
            # Un PDF suelto en la carpeta elegida: su FUID va en el espejo de
            # ella, junto al general, y no en la raíz del destino con su nombre.
            carpeta = self._carpeta_de(run, origin)
        # La misma clave que las actas de esa carpeta: un solo FUID con las dos.
        carpeta = self._carpeta_canonica(run, carpeta)
        # Por lo que hizo el trabajo y no sólo por lo que se pidió: «Solo el
        # inventario» de un PDF sin registros acaba inventariándolo entero.
        entero = job.task == "inventory_file" or informe.get("task") == "inventory_file"
        suyas = []
        for hecha in hechas:
            notas = str(hecha.get("notas") or "")
            # El archivo con el nombre con que quedó en el destino, si se
            # entregó con otro porque el suyo ya estaba.
            for antes, despues in renombres.items():
                notas = notas.replace(f"Archivo: {antes}", f"Archivo: {despues}")
            suyas.append(
                self._con_los_folios_del_cliente(
                    run,
                    {
                        "tipo": FILA_HECHA,
                        "fuid": {**hecha, "notas": notas},
                        "carpeta": carpeta,
                        "archivo": origin.name,
                        "pagina_inicial": hecha.get("pagina_inicial"),
                        "entero": entero,
                    },
                    origin,
                )
            )
        with run.cerrojo:
            self._sumar_filas_de_actas(run, suyas)
            filas, unidades, resoluciones = run.aportes.get(str(origin), ([], [], 0))
            run.aportes[str(origin)] = (list(filas) + suyas, unidades, resoluciones)
            run.fuid_pendientes.add(carpeta)

    def _entregar_fuid(
        self, run: FolderRun, job: Job, origin: Path, carpeta: Path, renombres: dict[str, str]
    ) -> str | None:
        """El FUID de un libro de diplomas, junto a sus PDF.

        Es el inventario de su habilidad, y va en la carpeta del libro (ver
        «Dos inventarios generales»). Si el libro se retomó a medias, se suma
        a las filas que ya estaban: lo entregado es **un** FUID por libro.

        Devuelve por qué no se pudo entregar, o ``None``.
        """
        from .indices import habilidad_del_proceso
        from .retomar import entregar_fuid

        informe = job.report or {}
        if habilidad_del_proceso(job) != "Libro de diplomas":
            return None
        # Para el FUID general: ésta es una carpeta con un libro de diplomas.
        run.carpetas_con_fuid[self._relativa_al_destino(run, carpeta)] = carpeta
        if not informe.get("fuid"):
            return None
        try:
            ruta = next(
                iter(sorted((self._settings.output_dir / job.id).rglob(informe["fuid"]))), None
            )
        except OSError:
            ruta = None
        if ruta is None:
            return None
        control = run.controles.get(str(self._relative(run, origin)))
        paginas_nuevas = {
            Path(str(item["file_name"])).name: int(item["first_page"])
            for item in (informe.get("inventory") or {}).get("items") or []
            if item.get("file_name") and item.get("first_page")
        }
        try:
            _reintentar_si_esta_en_uso(
                lambda: entregar_fuid(
                    ruta,
                    carpeta,
                    previo=control.antes if control else None,
                    paginas_nuevas=paginas_nuevas,
                    renombres=renombres,
                )
            )
        except Exception as error:  # noqa: BLE001 - los PDF ya están entregados
            logger.warning("no se pudo entregar el FUID de %s", job.filename, exc_info=True)
            return explicar_fallo(error)
        return None

    def _write_sheet(
        self,
        run: FolderRun,
        job: Job,
        carpeta: Path | None = None,
        *,
        en: Path | None = None,
    ) -> str | None:
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
            return None
        try:
            from ..adapters.excel_inventory import ExcelInventory
        except ImportError:
            return None
        try:
            destino = carpeta or run.destination
            # Abierta en Excel unos segundos -- alguien mirando la anterior --
            # se espera como un PDF abierto antes de darla por fallida.
            _reintentar_si_esta_en_uso(
                lambda: ExcelInventory().write(
                    job.report,
                    en or destino,
                    delivered_to=al_operador(destino),
                    operator=run.operator,
                    processed_at=job.finished_at,
                )
            )
        except Exception as error:  # noqa: BLE001 - the PDFs are already delivered
            logger.warning("could not write the sheet for %s", job.filename, exc_info=True)
            return explicar_fallo(error)
        return None

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
    def _record(run: FolderRun, job: Job, origin: Path) -> list[dict]:
        """Add this document's resolutions to the run's manifest; returns what it added.

        Salvo las cajas de correspondencia: su inventario general es el Índice
        Electrónico del cliente, y la planilla genérica de entrega repetía lo
        mismo en otro formato (lo pidió el operador: sólo la plantilla).
        """
        if (job.report or {}).get("indice_electronico"):
            return []
        inventory = ((job.report or {}).get("inventory")) or {}
        suyos = [{**item, "source_document": origin.name} for item in inventory.get("items") or []]
        run.manifest.extend(suyos)
        return suyos

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

    @staticmethod
    def _en_destino(run: FolderRun, carpeta: str) -> Path:
        """Dónde está en el disco la carpeta ``carpeta`` -- «14. ENFERMERIA…\\CAJA 00C003277» -- de la corrida.

        Si el destino ya es la carpeta de la corrida, «14. ENFERMERIA 3277-3283 P
        - PROCESADO», el nombre de la elegida no se repite dentro de ella: el
        operador pidió el 2026-10-30, para todo el software, «DESTINO\\<carpeta>
        - PROCESADO\\<caja>\\<UPD>» y nada más (ver ``destino_de_la_corrida``).
        Igual si es una entrega anterior de la misma carpeta con otro nombre,
        «MAGANGUE PROCESADO» (``FolderRun.en_su_carpeta``).
        """
        raiz = FolderRunner._raiz(run)
        partes = FolderRunner._partes(carpeta)
        if FolderRunner._quita_la_raiz(run) and partes and partes[0] == raiz:
            return run.destination.joinpath(*partes[1:])
        return run.destination.joinpath(*partes)

    @staticmethod
    def _partes(carpeta: str) -> tuple[str, ...]:
        """Las carpetas de ``carpeta``, venga con la barra de Windows o con la de Linux.

        Una entrega empezada en Windows y seguida en Docker (Linux) trae sus
        carpetas como «MAGANGUE\\7720382». En Linux la barra invertida no
        separa: salía una carpeta con la barra en el nombre, y la clave de
        ``_carpeta_canonica`` con la elegida dos veces (la suite en Linux,
        como la CI, 2026-11-10). En Windows las dos barras ya separaban.
        """
        return Path(carpeta.replace("\\", "/")).parts

    @staticmethod
    def _quita_la_raiz(run: FolderRun) -> bool:
        """Si el destino ya es la carpeta de la corrida y el nombre de la elegida no se repite dentro."""
        return run.en_su_carpeta or run.destination.name == f"{FolderRunner._raiz(run)}{SUFIJO_DE_LA_CORRIDA}"

    @staticmethod
    def _carpeta_canonica(run: FolderRun, carpeta: str) -> str:
        """La clave de una carpeta del destino, la misma la anote quien la anote.

        Las actas la anotan desde la elegida -- «18-RESOLUCIONES INTERNAS Y ACTAS
        3303\\00C003303» -- y las filas que trae hechas otra habilidad, desde el
        destino -- «00C003303» --. Si el destino es la carpeta de la corrida, las
        dos son la misma carpeta en el disco (``_en_destino``) y, con dos claves,
        se escribían dos FUID en el mismo archivo: el segundo pisaba al primero,
        y a la 3303 le faltaban sus 10 actas de consejo en el suyo (2026-11-05).
        Con la elegida delante, una sola clave y un solo FUID con todas.
        """
        if not carpeta or not FolderRunner._quita_la_raiz(run):
            return carpeta
        raiz = FolderRunner._raiz(run)
        partes = FolderRunner._partes(carpeta)
        if partes and partes[0] == raiz:
            # Con la barra del sistema: «3303\\00C003303» escrita en Windows y
            # «3303/00C003303» calculada en Linux son una sola clave, un solo FUID.
            return str(Path(*partes))
        return str(Path(raiz, *partes))

    def _carpeta_de(self, run: FolderRun, origin: Path) -> str:
        """La carpeta de un PDF vista desde la raíz: «00C003284\\UPD3859772»."""
        return str(Path(self._raiz(run)) / self._relative(run, origin).parent)

    def _espejo(self, run: FolderRun, origin: Path) -> Path:
        """Dónde va en el destino lo de este PDF: la misma ruta que tiene en la fuente.

        ``FUENTE\\00C003284\\UPD3859772\\libro.pdf`` deja lo suyo en
        ``DESTINO\\00C003284\\UPD3859772\\``: el destino es un espejo de la
        fuente, con la carpeta elegida delante y el trabajo hecho dentro.
        """
        return self._en_destino(run, self._carpeta_de(run, origin))

    def _sin_pisar_otra_suelta(
        self, run: FolderRun, job: Job, origin: Path, filas: list[dict]
    ) -> list[dict]:
        """Las filas del acta suelta, con el nombre de su fila sólo si no es ya el de otro PDF de su carpeta.

        El acta que ya era un PDF se entrega con el nombre de su fila --
        «01_ACTA DE CONSEJO DE FACULTAD - ORDINARIA - 022 - 17-12-2012.pdf» --,
        y dos de la misma UPD pueden llamarse igual: la misma acta escaneada dos
        veces. La copia de la segunda pisaba a la primera sin avisar (la
        revisión, 2026-11-13). Si el nombre ya es de otro origen -- en esta
        corrida, en la constancia de otro o un archivo que nadie reclama --, se
        entrega con el del cliente, que en su carpeta es único, y se avisa.
        Se llama con ``run.cerrojo`` tomado: las entregas van de una en una.
        """
        from ..application.acta_consejo import SE_ENTREGA_COMO

        report = job.report or {}
        nombre = Path(str(report.get("nombre_del_pdf") or "")).name.strip()
        if not nombre:
            return filas
        espejo = self._espejo(run, origin)
        propio = str(self._relative(run, origin))
        duenos = run.nombres_de_sueltas.setdefault(str(espejo), {})
        dueno = duenos.get(nombre.lower()) or self._dueno_del_nombre(espejo, nombre, propio)
        if dueno is None or dueno == propio:
            duenos[nombre.lower()] = propio
            return filas
        report.pop("nombre_del_pdf", None)
        sin_el_nombre = [
            {**fila, "resultado": str(fila.get("resultado") or "").split(f"; {SE_ENTREGA_COMO} ")[0]}
            for fila in filas
        ]
        report["inventario_actas"] = sin_el_nombre
        self._avisar(
            run,
            f"«{origin.name}»: «{nombre}» ya es de «{Path(dueno).name}» en la misma carpeta; "
            "se entrega con su nombre de origen para no pisarlo.",
        )
        return sin_el_nombre

    @staticmethod
    def _dueno_del_nombre(espejo: Path, nombre: str, propio: str) -> str | None:
        """Qué otro origen tiene ya ``nombre`` en ``espejo``, por las constancias de sus PDF; ``None`` si nadie.

        Un archivo con ese nombre que no reclama ninguna constancia -- de una
        entrega sin constancia, o puesto a mano -- tampoco se pisa.
        """
        clave = nombre.lower()
        try:
            rutas = sorted((espejo / constancias.CARPETA_DE_ACTAS).glob("*.json"))
        except OSError:
            rutas = []
        reclamado = False
        for ruta in rutas:
            otra = constancias.leer(ruta)
            if otra is None or not any(str(a.get("ruta") or "").lower() == clave for a in otra.archivos):
                continue
            if otra.origen != propio:
                return otra.origen
            reclamado = True
        try:
            existe = (espejo / nombre).exists()
        except OSError:
            existe = False
        return f"{nombre} (ya estaba en la carpeta)" if existe and not reclamado else None

    def _entregar_actas(
        self, run: FolderRun, job: Job, origin: Path, huella: tuple[int, int] = (0, 0)
    ) -> Entrega:
        """Deja en la carpeta espejo del destino el resultado de este PDF de actas.

        * Un libro que se dividió: sus actas, en una carpeta con el nombre del
          libro (``UPD3859772\\2N° 002…\\03_ACTA-EXTRAORDINARIA-NO-017….pdf``).
        * Un PDF que ya era un acta, cuando se pidió dividir: el PDF tal cual,
          para que el destino quede completo como la fuente, con el nombre de
          su fila si el trabajo lo trae (``nombre_del_pdf``, 2026-11-13:
          «01_ACTA DE CONSEJO DE FACULTAD - ORDINARIA - 022 - 17-12-2012.pdf»).
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
            # Desde la copia que se procesó: un origen de la red no es una ruta
            # de este equipo, y copiarlo por su nombre daba «No se encontró…
            # se movió, se renombró o se borró» (Z:, 2026-10-29). Con el
            # nombre de su fila del FUID, no con el del cliente (2026-11-13).
            nombre = Path(str(report.get("nombre_del_pdf") or "")).name.strip() or origin.name
            copias = [(self._copia_local(run, origin), espejo / nombre)]
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
                _copiar(desde, hasta, self._al_entregar(run, origin))
            except OSError as error:
                logger.warning("no se pudo entregar %s: %s", hasta.name, error)
                entrega.fallos.append(f"«{hasta.name}»: {_explicar_la_entrega(error, hasta)}")
                # El espejo se reemplaza al copiar: se reintenta al mismo nombre.
                entrega.pendientes.append((desde, hasta, True))
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
        """Dónde queda el inventario general: «00.FUID GENERAL.xlsx» en la carpeta espejo de la elegida.

        Uno por carpeta elegida, dentro de la suya en el destino --
        ``DESTINO\\14. ENFERMERIA 3277-3283 P\\00.FUID GENERAL.xlsx`` --: en la
        raíz del destino, dos carpetas lanzadas al mismo destino se pisaban el
        general y la primera bajaba el de la segunda (2026-10-30).

        Se calcula antes de leer nada porque cada trabajo la apunta en el
        inventario al crearse: es lo que deja descargarlo desde el Archivo
        cuando la corrida ya no está en memoria.
        """
        from .indices import NOMBRE_DEL_FUID_GENERAL

        return cls._en_destino(run, cls._raiz(run)) / NOMBRE_DEL_FUID_GENERAL

    def _escribir_inventario_de_actas(
        self, run: FolderRun, solo_carpeta: str | None = None
    ) -> None:
        """Deja en el espejo del destino el FUID de cada subcarpeta.

        Cada subcarpeta que tenga PDF lleva el suyo, sólo con sus filas --
        ``DESTINO\\…\\UPD3859772\\UPD3859772__FUID.xlsx`` --: quien abre
        ``UPD3859772`` en el destino encuentra ahí su inventario, como encontraría
        los papeles en la caja. El general, con todas las filas de la corrida,
        lo escribe ``_escribir_generales`` en la carpeta espejo de la elegida
        («00.FUID GENERAL.xlsx»). Las filas van en el orden de la carpeta y
        numeradas desde 1, y los folios de las actas se encadenan dentro de cada
        subcarpeta.

        Es el mismo FUID para todas las habilidades -- actas de consejo, de
        grado, historias académicas, matrículas -- desde el 2026-10-29 (ver
        ``adapters/fuid_de_la_entrega.py``).

        Volver a procesar la misma carpeta al mismo destino **actualiza** esos
        archivos en vez de dejar al lado un «(2)». Sólo si uno está abierto en
        Excel -- que lo bloquea -- se escribe con otro nombre, y la pantalla
        enseña cuál.

        Que falle no deshace nada: las filas siguen en la corrida y cada PDF
        conserva su propio FUID junto a su trabajo.

        ``solo_carpeta`` es la escritura de en medio de la corrida: el FUID de
        esa subcarpeta. Sin ella se escriben los de todas las que cambiaron
        desde su última escritura, que es lo que se hace al terminar.

        En dos tiempos (2026-10-30): bajo ``run.cerrojo`` sólo se copian las
        filas y se decide qué escribir; los Excel se escriben fuera de él, de
        uno en uno, para que las entregas en paralelo no esperen detrás. Se
        llama sin el cerrojo de la corrida tomado.
        """
        with run.cerrojo_de_escritura:
            # Que falle -- una fila con un dato que no se esperaba, un Excel
            # abierto -- no tumba la entrega: se anota y la corrida sigue, como
            # antes de partir la escritura en dos tiempos.
            try:
                with run.cerrojo:
                    plan = self._plan_de_inventarios(run, solo_carpeta)
                if plan is None:
                    return
                escritos = self._escribir_el_plan(run, plan)
                with run.cerrojo:
                    self._aplicar_lo_escrito(run, plan, escritos)
            except Exception as error:  # noqa: BLE001 - lo leído sigue en la corrida
                logger.warning("no se pudo escribir el FUID de la carpeta", exc_info=True)
                with run.cerrojo:
                    run.inventario_error = explicar_fallo(error)

    def _plan_de_inventarios(self, run: FolderRun, solo_carpeta: str | None) -> dict | None:
        """Qué hay que escribir, con las filas ya copiadas. Bajo ``run.cerrojo``."""
        if not run.inventario_filas:
            return None
        # De la lista de todas las filas, que es la de verdad, agrupadas por
        # su subcarpeta.
        de_todas: dict[str, list[dict]] = {}
        for fila in run.inventario_filas:
            de_todas.setdefault(str(fila.get("carpeta") or ""), []).append(fila)
        if solo_carpeta is None and len(run.inventario_filas) == run.inventario_escritas and not any(
            self._cambio(run, carpeta, len(filas)) for carpeta, filas in de_todas.items()
        ):
            return None
        from ..adapters.fuid_de_la_entrega import filas_del_fuid, ruta_del_fuid
        from ..application.acta_consejo import (
            inventario_de_la_carpeta,
            validar_inventario,
        )

        raiz = self._raiz(run)
        con_general = (
            solo_carpeta is None
            or time.monotonic() - run.inventario_general_en >= INVENTARIO_GENERAL_CADA
        )
        if solo_carpeta is None:
            # Al terminar o al detener: las subcarpetas que cambiaron desde su
            # última escritura. Reescribirlas todas costaba minutos en una
            # carpeta de cientos de UPD que ya estaban al día.
            carpetas = [carpeta for carpeta, filas in de_todas.items() if self._cambio(run, carpeta, len(filas))]
        else:
            # Sólo la subcarpeta del PDF que llegó: sus folios se deducen
            # dentro de ella y nunca de una a otra, así que bastan sus filas.
            carpetas = [solo_carpeta]
            de_todas = {solo_carpeta: run.filas_por_carpeta.get(solo_carpeta, [])}
        fuids: list[tuple[str, list, Path, tuple[int, int]]] = []
        for carpeta in carpetas:
            suyas = [dict(fila) for fila in de_todas.get(carpeta, [])]
            ordenadas = inventario_de_la_carpeta(suyas)
            filas = filas_del_fuid(ordenadas)
            version = (run.version_de_carpeta.get(carpeta, 0), len(suyas))
            if carpeta and filas:
                # El que ya se escribió, por si se escribió con otro nombre
                # porque el suyo estaba abierto; si no, el de la subcarpeta.
                # Sin filas -- sólo hojas de una ceremonia, o lo de antes de la
                # primera ficha -- no hay FUID que escribir.
                ya = run.inventarios_de_carpeta.get(carpeta)
                fuids.append((carpeta, filas, Path(ya) if ya else ruta_del_fuid(self._en_destino(run, carpeta)), version))
            else:
                run.version_escrita[carpeta] = version
        # El control de calidad de toda la corrida, cada
        # ``INVENTARIO_GENERAL_CADA`` y al terminar. El FUID general lo escribe
        # ``_escribir_generales``, con todas las habilidades. Ningún otro Excel:
        # el de actas de consejo, con su resumen, lo quitó el operador el
        # 2026-11-11 («todo se unificará en uno solo y es el FUID»).
        validacion = None
        if con_general or solo_carpeta == raiz:
            validacion = validar_inventario(inventario_de_la_carpeta([dict(fila) for fila in run.inventario_filas]))
        return {
            "fuids": fuids,
            "validacion": validacion,
            "con_general": con_general,
            "completa": solo_carpeta is None,
            "filas": len(run.inventario_filas),
        }

    @staticmethod
    def _cambio(run: FolderRun, carpeta: str, filas: int) -> bool:
        """Si las filas de la subcarpeta cambiaron desde que se escribió su FUID; una que no se escribió nunca, sí."""
        return run.version_escrita.get(carpeta) != (run.version_de_carpeta.get(carpeta, 0), filas)

    def _escribir_el_plan(self, run: FolderRun, plan: dict) -> dict:
        """Escribe los FUID del plan, sin el cerrojo de la corrida. Devuelve dónde quedó cada uno."""
        escritos: dict = {"fuids": {}}
        for carpeta, filas, destino, _version in plan["fuids"]:
            escritos["fuids"][carpeta] = str(self._escribir_un_fuid(run, filas, destino, carpeta=carpeta))
        return escritos

    @staticmethod
    def _aplicar_lo_escrito(run: FolderRun, plan: dict, escritos: dict) -> None:
        """Apunta en la corrida lo que se escribió. Bajo ``run.cerrojo``."""
        for carpeta, _filas, _destino, version in plan["fuids"]:
            run.inventarios_de_carpeta[carpeta] = escritos["fuids"][carpeta]
            run.version_escrita[carpeta] = version
        if plan["validacion"] is not None:
            run.inventario_validacion = plan["validacion"]
        if plan["con_general"]:
            # Desde que terminó de escribirse: medido desde antes, una escritura
            # más larga que el intervalo se encadenaba sin pausa.
            run.inventario_general_en = time.monotonic()
        run.inventario_error = None
        if plan["completa"]:
            run.inventario_escritas = plan["filas"]

    @staticmethod
    def _oficina_de(run: FolderRun, carpeta: str | None) -> str | None:
        """La oficina productora del FUID de una subcarpeta.

        La que escribió el operador, si escribió una; si no, la que nombra la
        subcarpeta, de dentro afuera; y si no nombra ninguna, la de la corrida
        (el Excel del cliente o el nombre de la carpeta elegida). Lanzada la
        raíz del repositorio entero, cada facultad lleva la suya en vez de la
        «FACULTAD DE INGENIERIA» de la plantilla (2026-10-30).
        """
        from ..domain.oficina_productora import oficina_de_la_ruta

        if run.oficina_del_operador or not carpeta:
            return run.oficina
        return oficina_de_la_ruta(carpeta) or run.oficina

    @staticmethod
    def _escribir_un_fuid(run: FolderRun, filas: list, destino: Path, *, carpeta: str | None = None) -> Path:
        """Escribe un FUID con la oficina de su carpeta; con otro nombre sólo si el suyo está abierto.

        Y en esa carpeta retira el Excel de actas que el bot dejó en una entrega
        de antes (ver ``FolderRunner._retirar_el_de_actas``).
        """
        from ..adapters.fuid_de_la_entrega import escribir_fuid

        oficina = FolderRunner._oficina_de(run, carpeta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            escrito = escribir_fuid(filas, destino, oficina=oficina)
        except PermissionError:
            escrito = escribir_fuid(filas, unique_path(destino.parent, destino.name), oficina=oficina)
        FolderRunner._retirar_el_de_actas(run, escrito.parent)
        return escrito

    @staticmethod
    def _retirar_el_de_actas(run: FolderRun, carpeta: Path) -> None:
        """Borra de la carpeta el «ACTAS …__inventario.xlsx» que escribió el bot antes del 2026-11-11.

        El operador eligió que, al volver a entregar la carpeta, el FUID quede
        solo (2026-11-11). Sólo el que escribió el bot -- su hoja «Inventario de
        actas» y el bot como autor --: lo que dejó otro no se toca. Que no se
        pueda -- abierto en Excel -- no detiene nada: se avisa y se queda.
        """
        from ..adapters.fuid_de_la_entrega import retirar_el_excel_de_actas

        try:
            no_se_pudo = retirar_el_excel_de_actas(carpeta)
        except OSError:
            logger.debug("no se pudo mirar el Excel de actas de %s", carpeta, exc_info=True)
            return
        for ruta, error in no_se_pudo:
            aviso = f"No se pudo borrar el Excel de actas viejo «{ruta.name}»: {explicar_fallo(error)}"
            logger.warning("%s: %s", run.source, aviso)
            # Fuera del cerrojo de la corrida, que aquí no se tiene: se toma
            # sólo para anotarlo.
            with run.cerrojo:
                if aviso not in run.avisos:
                    run.avisos.append(aviso)
                    del run.avisos[:-AVISOS_EN_PANTALLA]

    def _dispose(self, run: FolderRun, path: Path, huella: tuple[int, int] = (0, 0)) -> None:
        """Leave, move aside, or delete the original, as the operator chose."""
        # El original de una carpeta de red no se toca nunca (`start` ya sólo
        # admite «Dejarlo» ahí; esto es la segunda llave).
        if run.disposition is SourceDisposition.LEAVE or red_smb.por_smb(path):
            return
        relativa = self._relative(run, path)
        # Sólo el PDF que se leyó. Si cambió desde entonces -- una copia que
        # seguía llegando, alguien que lo sobrescribió --, lo entregado no es
        # lo que hay ahora y borrarlo o apartarlo perdería lo que se añadió.
        if huella != (0, 0):
            try:
                cambio = constancias.huella_del_origen(path) != huella
            except OSError:
                cambio = False  # ya no está: no hay nada que tocar
            if cambio:
                self._avisar(
                    run,
                    f"El original «{relativa}» cambió mientras se procesaba: se dejó en su sitio. "
                    "Vuelva a lanzar la carpeta para procesar la versión nueva.",
                )
                return
        verbo = "borrar" if run.disposition is SourceDisposition.DELETE else "mover"
        try:
            if run.disposition is SourceDisposition.DELETE:
                path.unlink(missing_ok=True)
                return
            # Bajo `_procesados`, con la misma estructura que tenían. Aplanarlo
            # mezclaría cien expedientes en una carpeta y haría irreversible lo
            # que hasta ahora sólo era moverlos de sitio.
            consumed = run.source / CONSUMED_DIR / relativa.parent
            consumed.mkdir(parents=True, exist_ok=True)
            # Con la espera de quien lo tenga abierto, como al ordenar.
            _mover(path, unique_path(consumed, path.name))
        except OSError as error:
            # No poder recoger el original nunca deshace lo ya entregado; pero
            # el operador eligió que no quedara ahí, y tiene que saberlo.
            self._avisar(
                run, f"El original «{relativa}» no se pudo {verbo}: {explicar_fallo(error)}"
            )

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
    def _escribir_constancia(
        ruta: Path, constancia: Constancia, entrega: Entrega, *, carpeta_existe: bool = False
    ) -> None:
        try:
            constancias.escribir(ruta, constancia, carpeta_existe=carpeta_existe)
        except OSError as error:
            logger.warning("no se pudo escribir la constancia %s: %s", ruta, error)
            entrega.fallos.append(f"la constancia de entrega: {explicar_fallo(error)}")

    def _constancia_completa(
        self, run: FolderRun, job: Job, origin: Path, huella: tuple[int, int], entrega: Entrega
    ) -> Constancia:
        """La constancia «completa» de un PDF entregado entero, sin escribirla.

        Lleva lo que los generales necesitan de él -- su fila de procesos, sus
        filas del FUID, sus unidades --, para que la corrida que lo salte lo
        siga contando sin abrir nada. Las filas son las que este PDF sumó a la
        corrida, de la habilidad que sea: con sólo las de las actas, relanzar una
        carpeta dejaba sin sus filas a las resoluciones, las matrículas y los
        archivos enteros ya entregados (2026-10-30).

        El tamaño de cada archivo, el que la copia ya comprobó; y con cada PDF,
        sus citas de trece cifras (``Entrega.citas``), para cruzar el RE con el
        expediente sin volver a abrirlo por la red.
        """
        from .indices import fila_de_proceso, habilidad_del_proceso

        if entrega.archivos is None:
            try:
                rutas = [
                    ruta
                    for ruta in entrega.base.iterdir()
                    if ruta.is_file()
                    and not ruta.name.startswith(Path(constancias.NOMBRE).stem)
                    and not ruta.name.endswith((".part", ".tmp"))
                    # Sólo lo que el bot entrega (PDF y Excel), sin el bloqueo
                    # de un Excel abierto: lo demás aparece y desaparece sin
                    # que la entrega cambie, y anotarlo hacía rehacer el PDF.
                    and ruta.suffix.lower() in EXTENSIONES_DEL_BOT
                    and not constancias.es_ajeno(ruta.name)
                ]
            except OSError:
                rutas = []
        else:
            rutas = entrega.archivos
        informe = job.report or {}
        carpeta = self._carpeta_de(run, origin)
        with run.cerrojo:
            aportadas = [dict(fila) for fila in (run.aportes.get(str(origin)) or ([], [], 0))[0]]
        constancia = Constancia(
            origen=str(self._relative(run, origin)),
            tamano=huella[0],
            modificado_ns=huella[1],
            estado=EstadoDeEntrega.COMPLETA,
            archivos=constancias.archivos_de(entrega.base, sorted(rutas), tamanos=entrega.tamanos),
            habilidad=habilidad_del_proceso(job),
            job_id=job.id,
            proceso=asdict(fila_de_proceso(job, self._destino_relativo(run, job))),
            actas=aportadas or [{**fila, "carpeta": carpeta} for fila in informe.get("inventario_actas") or []],
            unidades=[
                {**item, "source_document": origin.name}
                for item in ((informe.get("inventory") or {}).get("items") or [])
            ]
            if not informe.get("indice_electronico")
            else [],
            indice=entrega.indice,
            # Lo que la IA o el sello leyeron para fechar cada documento cuando
            # la capa no lo trae: la auditoría de cierre lo suma a su papel.
            lo_leido=[f for f in informe.get("lo_leido") or [] if isinstance(f, dict)],
            # Los PDF con dos o más sellos de RE distinto: la auditoría los avisa.
            varios_sellos=[v for v in informe.get("varios_sellos") or [] if isinstance(v, dict)],
            # El folio a mano y las marcas de cada hoja: la auditoría razona con ellos.
            folios=dict(informe.get("folios_de_la_esquina") or {}),
            marcas=dict(informe.get("marcas") or {}),
            # La evidencia de cada parámetro y la Revisión con sus motivos
            # (2026-11-18): las métricas y la Revisión las leen después.
            evidencia=dict(informe.get("evidencia") or {}),
            revision=[r for r in informe.get("review_queue") or [] if isinstance(r, dict)],
            decisiones_del_agente=[d for d in informe.get("decisiones_del_agente") or [] if isinstance(d, dict)],
            secuencia_de_anexos=[d for d in informe.get("secuencia_de_anexos") or [] if isinstance(d, dict)],
            # Las hojas de cada documento, para la auditoría (2026-11-20).
            documentos=[
                {"hojas": list(grupo.get("pages") or [])}
                for grupo in informe.get("groups") or []
                if isinstance(grupo, dict)
            ],
            # De la copia que se procesó, que es la del origen: sin otra lectura
            # de la red.
            firma=self._firma_de(job, origin),
        )
        # Dónde quedó, para corregir el RE en la Revisión aunque la corrida ya no
        # esté en memoria (2026-11-23, ``api.correccion_del_re``).
        if isinstance(job.report, dict):
            job.report["donde_se_entrega_el_re"] = {
                "carpeta": str(entrega.base),
                "constancia": str(entrega.constancia),
                # La raíz del destino, por su índice general.
                "raiz": str(run.destination),
            }
        if entrega.citas:
            citas = {}
            for ruta, suyas in entrega.citas.items():
                try:
                    citas[ruta.relative_to(entrega.base).as_posix()] = suyas
                except ValueError:
                    citas[ruta.name] = suyas
            for archivo in constancia.archivos:
                if str(archivo.get("ruta")) in citas:
                    archivo["citas"] = citas[str(archivo.get("ruta"))]
        return constancia

    def _dejar_constancia(
        self, run: FolderRun, job: Job, origin: Path, huella: tuple[int, int], entrega: Entrega
    ) -> bool:
        """La constancia «completa» de un PDF entregado entero: la próxima corrida lo salta.

        La entrega plana por el camino rápido ya la dejó en su turno
        (``Entrega.cerrada``). Si no, aquí: en la entrega plana, con el turno de
        entregas, el de la carpeta y su cerrojo -- nunca el de la corrida con el
        destino de por medio --; en las demás habilidades, como siempre.
        """
        if entrega.cerrada is not None:
            cerrada = entrega.cerrada
        else:
            constancia = self._constancia_completa(run, job, origin, huella, entrega)
            cerrada = True
            if self._plana(run):
                from .correccion_del_re import cerrojo_de_la_carpeta

                with self._turno_de(run, entrega.base), cerrojo_de_la_carpeta(entrega.base), self._entregas:
                    self._confirmar(run, origin)
                    try:
                        constancias.escribir(entrega.constancia, constancia)
                    except OSError as error:
                        cerrada = False
                        logger.warning("no se pudo cerrar la constancia de %s: %s", origin.name, error)
                        self._avisar(
                            run, f"No se pudo guardar la constancia de «{origin.name}»: {explicar_fallo(error)}"
                        )
                    # La carpeta del NIC, con este UPD ya dentro: numerada seguida y con
                    # un solo índice.
                    self._ordenar_la_caja(run, entrega.base)
            else:
                with self._turno_de(run, entrega.base):
                    self._confirmar(run, origin)
                    try:
                        with run.cerrojo:
                            constancias.escribir(entrega.constancia, constancia)
                    except OSError as error:
                        cerrada = False
                        logger.warning("no se pudo cerrar la constancia de %s: %s", origin.name, error)
                        self._avisar(
                            run, f"No se pudo guardar la constancia de «{origin.name}»: {explicar_fallo(error)}"
                        )
        if getattr(self._settings, "liberar_salidas", False):
            self._liberar_salidas(job)
        return cerrada

    def tiene_la_corrida(self, job) -> bool:
        """Si la corrida del trabajo sigue en memoria: sus correcciones van por ella."""
        run = self._runs.get(str((getattr(job, "origen", None) or {}).get("id") or ""))
        return run is not None and job.id in run.job_ids

    def donde_se_entrega(self, job) -> dict[str, str] | None:
        """Dónde deja la corrida lo de este trabajo en el destino; ``None`` fuera de una corrida en memoria.

        Para la Revisión de nombres (2026-11-17): se guarda con los nombres por
        confirmar del trabajo, y con ello se corrige en el destino aunque la
        corrida ya no esté -- tras un reinicio --. Son las rutas que usa la
        entrega, no unas que se le parezcan: el espejo de sus actas, la carpeta
        de sus PDF, sus dos constancias y el FUID general.
        """
        run = self._runs.get(str((getattr(job, "origen", None) or {}).get("id") or ""))
        if run is None or job.id not in run.job_ids:
            return None
        origen = run.source / job.filename
        return {
            "espejo": str(self._espejo(run, origen)),
            "carpeta": str(self._output_dir(run, origen, job)),
            "constancia_de_actas": str(self._ruta_de_la_constancia(run, origen, actas=True)),
            "constancia": str(self._ruta_de_la_constancia(run, origen, actas=False)),
            "general": str(self._ruta_del_inventario(run)),
            # La raíz, por su índice general (la corrección del RE, 2026-11-23).
            "raiz": str(run.destination),
        }

    def corregir_nombre(self, job: Job, pagina: int, viejo: dict, nuevo: dict) -> list[str]:
        """Lleva al destino el nombre que el operador corrigió en la Revisión (2026-11-17).

        Todo junto, porque una corrección que aterriza en uno solo es peor que
        ninguna: el PDF del estudiante en el espejo, la constancia de su PDF de
        origen -- sin ella, la corrida siguiente daría el PDF por faltante y lo
        volvería a procesar y a pagar -- y su fila en la corrida, de donde salen
        el FUID de la subcarpeta y el general, que se reescriben.

        ``viejo`` y ``nuevo`` traen «nombre», «archivo_generado» y «salida» (la
        ruta del PDF dentro del trabajo, que es la misma dentro del espejo).
        Devuelve lo que no se pudo hacer, para decírselo al operador. Fuera de
        una corrida de carpeta, nada.
        """
        avisos: list[str] = []
        run = self._runs.get(str((job.origen or {}).get("id") or ""))
        if run is None or job.id not in run.job_ids:
            return avisos
        origen: Path | None = None
        carpeta = ""
        with run.cerrojo:
            for clave, (suyas, _registro, _unidades) in run.aportes.items():
                for fila in suyas:
                    if (
                        fila.get("pagina_inicial") == pagina
                        and fila.get("archivo_generado") == viejo.get("archivo_generado")
                        and fila.get("nombre") == viejo.get("nombre")
                        and str(fila.get("archivo") or "") == Path(clave).name
                    ):
                        fila["nombre"] = nuevo["nombre"]
                        fila["archivo_generado"] = nuevo.get("archivo_generado")
                        for campo in ("revision_del_nombre", "asunto"):
                            if campo in nuevo:
                                fila[campo] = nuevo[campo]
                        origen, carpeta = Path(clave), str(fila.get("carpeta") or "")
                        break
                if origen is not None:
                    break
            if origen is not None:
                run.version_de_carpeta[carpeta] = run.version_de_carpeta.get(carpeta, 0) + 1
        if origen is None:
            return ["la corrida ya no trae la fila de este estudiante: el FUID de su carpeta no se reescribió"]

        espejo = self._espejo(run, origen)
        if viejo.get("salida") and nuevo.get("salida") and viejo["salida"] != nuevo["salida"]:
            antes, despues = espejo / viejo["salida"], espejo / nuevo["salida"]
            try:
                if despues.exists():
                    avisos.append(f"en el destino ya hay un «{despues.name}»: no se renombró «{antes.name}»")
                elif antes.exists():
                    os.replace(antes, despues)
            except OSError as error:
                avisos.append(f"no se pudo renombrar «{antes.name}» en el destino: {explicar_fallo(error)}")

        ruta = self._ruta_de_la_constancia(run, origen, actas=True)
        constancia = constancias.leer(ruta)
        if constancia is not None:
            for archivo in constancia.archivos:
                if viejo.get("salida") and archivo.get("ruta") == viejo["salida"]:
                    archivo["ruta"] = nuevo.get("salida")
            for fila in constancia.actas:
                if (
                    fila.get("pagina_inicial") == pagina
                    and fila.get("archivo_generado") == viejo.get("archivo_generado")
                    and fila.get("nombre") == viejo.get("nombre")
                ):
                    fila["nombre"] = nuevo["nombre"]
                    fila["archivo_generado"] = nuevo.get("archivo_generado")
                    if "asunto" in nuevo:
                        fila["asunto"] = nuevo["asunto"]
            try:
                with run.cerrojo:
                    constancias.escribir(ruta, constancia)
            except OSError as error:
                avisos.append(f"no se pudo actualizar la constancia de «{origen.name}»: {explicar_fallo(error)}")

        error_de_antes = run.inventario_error
        self._escribir_inventario_de_actas(run, solo_carpeta=carpeta)
        if run.inventario_error and run.inventario_error != error_de_antes:
            avisos.append(f"el FUID de la carpeta: {run.inventario_error}")
        self._pedir_generales(run)
        return avisos

    def corregir_nombre_del_fuid(self, job: Job, pagina: int, viejo: dict, nuevo: dict) -> list[str]:
        """Lleva al destino el nombre corregido de un diploma o una matrícula (2026-11-17).

        Sus filas son ya del formato (``filas_del_fuid``) y se entregan por otro
        camino que las actas: sus PDF en la carpeta del documento
        (``_output_dir``), con su constancia al lado. Todo junto otra vez:

        - el PDF entregado, si su nombre lleva el de la persona;
        - la constancia, para que la corrida siguiente no lo dé por faltante;
        - su fila en la corrida (las matrículas), de donde salen el FUID de la
          subcarpeta y el general;
        - el FUID del libro junto a sus PDF (los diplomas), que es el que lee
          el general.

        ``viejo`` y ``nuevo`` traen «nombre», «asunto» y «archivo»; ``nuevo``,
        además, «notas» y «revision_del_nombre». Devuelve lo que no se pudo
        hacer. Fuera de una corrida de carpeta, nada.
        """
        avisos: list[str] = []
        run = self._runs.get(str((job.origen or {}).get("id") or ""))
        if run is None or job.id not in run.job_ids:
            return avisos
        origen = run.source / job.filename
        carpeta_de_entrega = self._output_dir(run, origen, job)
        antes_de, despues_de = viejo.get("archivo"), nuevo.get("archivo")

        if antes_de and despues_de and antes_de != despues_de:
            antes, despues = carpeta_de_entrega / antes_de, carpeta_de_entrega / despues_de
            try:
                if despues.exists():
                    avisos.append(f"en el destino ya hay un «{despues.name}»: no se renombró «{antes.name}»")
                elif antes.exists():
                    os.replace(antes, despues)
            except OSError as error:
                avisos.append(f"no se pudo renombrar «{antes.name}» en el destino: {explicar_fallo(error)}")
            ruta = self._ruta_de_la_constancia(run, origen, actas=False)
            constancia = constancias.leer(ruta)
            if constancia is not None:
                for archivo in constancia.archivos:
                    entregado = str(archivo.get("ruta") or "")
                    if entregado == antes_de or entregado.endswith(("/" + antes_de, "\\" + antes_de)):
                        archivo["ruta"] = entregado[: len(entregado) - len(antes_de)] + despues_de
                try:
                    with run.cerrojo:
                        constancias.escribir(ruta, constancia)
                except OSError as error:
                    avisos.append(f"no se pudo actualizar la constancia de «{origen.name}»: {explicar_fallo(error)}")

        # Su fila en la corrida: la de una matrícula va al FUID de su subcarpeta.
        carpeta: str | None = None
        with run.cerrojo:
            for clave, aportado in run.aportes.items():
                if Path(clave).name != Path(job.filename).name:
                    continue
                for fila in aportado[0]:
                    datos = fila.get("fuid")
                    if (
                        isinstance(datos, dict)
                        and datos.get("pagina_inicial") == pagina
                        and datos.get("asunto") == viejo.get("asunto")
                    ):
                        datos["nombre"] = nuevo.get("nombre")
                        datos["revision_del_nombre"] = nuevo.get("revision_del_nombre")
                        if nuevo.get("asunto"):
                            datos["asunto"] = nuevo["asunto"]
                        if antes_de and despues_de:
                            datos["notas"] = str(datos.get("notas") or "").replace(
                                f"Archivo: {antes_de}", f"Archivo: {despues_de}"
                            )
                        carpeta = str(fila.get("carpeta") or "")
                        break
                if carpeta is not None:
                    run.version_de_carpeta[carpeta] = run.version_de_carpeta.get(carpeta, 0) + 1
                    break
        if carpeta is not None:
            error_de_antes = run.inventario_error
            self._escribir_inventario_de_actas(run, solo_carpeta=carpeta)
            if run.inventario_error and run.inventario_error != error_de_antes:
                avisos.append(f"el FUID de la carpeta: {run.inventario_error}")

        # El FUID del libro, junto a sus PDF: el general lo lee de ahí.
        from .retomar import corregir_el_asunto, fuid_del_libro

        libro = fuid_del_libro(carpeta_de_entrega)
        if libro is not None and viejo.get("asunto") and nuevo.get("asunto") and viejo["asunto"] != nuevo["asunto"]:
            try:
                with run.cerrojo:
                    corregir_el_asunto(libro, viejo["asunto"], nuevo["asunto"])
            except Exception as error:  # noqa: BLE001 - lo demás ya se corrigió; se dice qué faltó
                avisos.append(f"no se pudo reescribir el FUID de «{libro.name}»: {explicar_fallo(error)}")
        self._pedir_generales(run)
        return avisos

    def corregir_re(self, job: Job, posicion: int, radicado: str, quien: str | None = None) -> list[str]:
        """Lleva al destino el RE que el operador confirmó o escribió en la Revisión (2026-11-18).

        Todo junto, como la Revisión de nombres: el PDF entregado en la carpeta
        del NIC, su constancia -- la ruta del archivo y el nombre de su fila,
        sin las cuales la corrida siguiente lo daría por faltante y lo volvería
        a pagar --, el índice del NIC, que se rehace desde las constancias
        (``_ordenar_la_caja``), y los generales.

        ``posicion`` es el puesto del documento entre los PDF de su UPD, por su
        número: el mismo en la constancia y en sus filas del índice. Devuelve lo
        que no se pudo hacer. Fuera de una corrida de carpeta, nada.
        """
        run = self._runs.get(str((job.origen or {}).get("id") or ""))
        if run is None or job.id not in run.job_ids:
            return []
        origen = run.source / job.filename
        carpeta = self._output_dir(run, origen, job)
        from .correccion_del_re import cerrojo_de_la_carpeta

        # Leer, renombrar, escribir y ordenar, con el turno de la carpeta y su
        # cerrojo: una entrega o un orden del mismo NIC no se cruzan en medio.
        with self._turno_de(run, carpeta), cerrojo_de_la_carpeta(carpeta):
            avisos = self._corregir_re_en_la_carpeta(run, job, origen, carpeta, posicion, radicado, quien)
        self._pedir_generales(run)
        return avisos

    def _corregir_re_en_la_carpeta(
        self, run: FolderRun, job: Job, origen: Path, carpeta: Path, posicion: int, radicado: str, quien: str | None
    ) -> list[str]:
        from ..domain.nombre_oficial import con_su_re_en_la_ruta

        avisos: list[str] = []
        ruta = self._ruta_de_la_constancia(run, origen, actas=False)
        constancia = constancias.leer(ruta)
        if constancia is None:
            return [f"no está la constancia de «{origen.name}» en el destino: el PDF entregado no se renombró"]
        if constancia.job_id and constancia.job_id != job.id:
            # La carpeta se reprocesó: lo entregado es de otro trabajo.
            return [f"la entrega de «{origen.name}» es ahora de otro trabajo (se reprocesó): lo entregado no se tocó"]
        prefijo = _prefijo_de_la_constancia(constancia)
        pdfs = sorted(
            (a for a in constancia.archivos if str(a.get("ruta") or "").lower().endswith(".pdf")),
            key=lambda a: _orden_del_archivo(a, prefijo),
        )
        if posicion >= len(pdfs):
            return [f"la constancia de «{origen.name}» no trae ese documento: el PDF entregado no se renombró"]
        archivo = pdfs[posicion]
        actual = str(archivo.get("ruta") or "")
        renombrado = con_su_re_en_la_ruta(actual, radicado)
        antes = constancias.ruta_de_entrega(carpeta, actual)
        despues = constancias.ruta_de_entrega(carpeta, renombrado)
        if antes is None or despues is None:
            return [f"la ruta de «{Path(actual).name}» no es de la carpeta del NIC: no se renombró"]
        try:
            if despues.exists() and despues != antes:
                return [f"en el destino ya hay un «{despues.name}»: no se renombró «{antes.name}»"]
            if antes.exists():
                os.replace(antes, despues)
        except OSError as error:
            return [f"no se pudo renombrar «{antes.name}» en el destino: {explicar_fallo(error)}"]
        # El archivo, su fila, su evidencia, su Revisión y la decisión del
        # agente, todo junto (2026-11-23).
        from .correccion_del_re import re_en_la_constancia

        avisos += re_en_la_constancia(constancia, posicion, radicado, quien)
        try:
            constancias.escribir(ruta, constancia)
        except OSError as error:
            avisos.append(f"no se pudo actualizar la constancia de «{origen.name}»: {explicar_fallo(error)}")
        self._ordenar_la_caja(run, carpeta)
        return avisos

    def _ordenar_la_caja(self, run: FolderRun, carpeta: Path) -> None:
        """La carpeta de un NIC como un solo expediente: sus PDF seguidos y un índice.

        Lo dictó el operador el 2026-10-22 ante «DESTINO\\1002194» con dos UPD:
        «no hay necesidad de que crees otro índice electrónico, o que en el
        nombre le coloques primero la UPD; la idea es que por NIC estén sus
        archivos en la raíz de la carpeta del NIC con la estructura número-título».

        - Los PDF de todos sus UPD entregados se numeran seguidos: «01_…»,
          «02_…», «03_…» (renombrando en dos pasos, para que ningún nombre pise
          a otro mientras se mueve). Por la fecha de su documento, en el mismo
          orden que el índice (lo dictó el operador el 2026-11-11), si cada UPD
          los trae numerados así (``indice["por_fecha"]``); si no -- una
          entrega de antes --, por el orden de su ruta y de sus hojas.
        - Un solo «00.INDICE ELECTRONICO.xlsx», con las filas de todos por la
          fecha de cada documento, lo antiguo primero, y el NIC también como
          «Nombre del Expediente» (lo dictó el operador el 2026-11-04); las de
          cada UPD están en su constancia, así que también cuenta el que se
          entregó en una corrida anterior.
        - Lo que se entregaba hasta el 2026-10-21 -- el UPD delante del nombre y
          un índice por UPD -- queda así también: el índice suelto de cada UPD se
          aparta a ``_reemplazados``.

        Sólo toca lo que las constancias completas dicen que entregó el bot: lo
        de una entrega en curso o cortada se ordena cuando termine. Un fallo
        aquí no deshace ninguna entrega: se avisa y la carpeta queda como esté.
        """
        from ..adapters.indice_electronico import (
            NOMBRE_DEL_INDICE,
            en_orden_cronologico,
            escribir_indice,
            leer_indice,
        )
        from .correccion_del_re import cerrojo_de_la_carpeta, corregir_con_el_expediente

        # El turno de la carpeta entre equipos y su cerrojo en este proceso: la
        # corrección del RE sin la corrida (``correccion_del_re``) no se cruza
        # con la renumeración, y dos PC con UPD del mismo NIC no renumeran a la
        # vez. Sin el cerrojo de la corrida: con él, cada orden paraba todas las
        # entregas del equipo (2026-11-25). Su memoria, un momento al final.
        with self._turno_de(run, carpeta), cerrojo_de_la_carpeta(carpeta):
            # Un solo listado de la carpeta para todo el orden: qué constancias
            # hay, qué nombres están tomados, qué dejó un orden cortado.
            listado = _listado(carpeta)
            sello_de_las_constancias = f"{Path(constancias.NOMBRE).stem}-"
            rutas = sorted(
                carpeta / nombre
                for nombre in listado
                if nombre.startswith(sello_de_las_constancias) and nombre.endswith(".json")
            )
            todas = []
            for ruta in rutas:
                constancia, esta = constancias.leer_si_hay(ruta)
                if constancia is None and esta:
                    # Una constancia que está y no se dejó leer: sin saber qué es
                    # de quién no se renumera ni se aparta nada. Al relanzar la
                    # carpeta se vuelve a ordenar.
                    logger.warning("no se ordena %s: no se pudo leer %s", carpeta, ruta.name)
                    return
                if constancia is not None:
                    todas.append((ruta, constancia))
            completas = [(ruta, c) for ruta, c in todas if c.estado == EstadoDeEntrega.COMPLETA]
            # Lo que nombran las entregas cortadas («entregando»), que se rehacen:
            # con el turno de la carpeta tomado, ninguna está en marcha.
            de_las_cortadas = {
                str(archivo.get("ruta") or "")
                for _, c in todas
                if c.estado != EstadoDeEntrega.COMPLETA
                for archivo in c.archivos
                if isinstance(archivo, dict)
            }
            # El RE leído a mano que otro documento del NIC cita distinto: aquí
            # están ya todos sus UPD (4251556, 2026-11-24). Antes de renumerar,
            # para que lo numerado lleve el corregido; con las constancias ya
            # leídas, que corrige en su sitio.
            try:
                hechos = corregir_con_el_expediente(carpeta, leidas=completas, en_el_orden=True)
                for hecho in hechos:
                    self._avisar(run, f"RE corregido por el expediente del NIC {carpeta.name}: {hecho}")
                if hechos:
                    listado = _listado(carpeta)
            except Exception:  # noqa: BLE001 - el cruce nunca deja la carpeta sin ordenar
                logger.warning("no se pudo cruzar los RE del NIC %s", carpeta, exc_info=True)
            leidas = [
                (ruta, constancia)
                for ruta, constancia in completas
                if all(
                    isinstance(archivo, dict)
                    and type(archivo.get("bytes")) is int
                    and archivo["bytes"] >= 0
                    and constancias.ruta_de_entrega(carpeta, archivo.get("ruta")) is not None
                    for archivo in constancia.archivos
                )
            ]
            if not leidas:
                return
            # Con la barra de Linux: una constancia escrita en Windows -- «5940155\NIC…» --
            # y otra en Docker -- «5940155/NIC…» -- se ordenan por su nombre y no por la
            # barra, que en el texto pone «/» antes que «\» (la revisión, 2026-11-10).
            leidas.sort(key=lambda par: par[1].origen.replace("\\", "/").casefold())
            # Cómo estaba cada una: al final se escriben sólo las que cambiaron.
            como_estaban = [_huella_de_la_constancia(constancia) for _, constancia in leidas]
            de_las_completas = {
                str(archivo.get("ruta") or "") for _, constancia in leidas for archivo in constancia.archivos
            }
            nombres = set(listado)

            def existe(relativa: Path) -> bool:
                if len(relativa.parts) == 1:
                    return relativa.name in nombres
                return (carpeta / relativa).exists()

            def mover(desde: Path, hasta: Path) -> None:
                _mover(desde, hasta)
                if desde.parent == carpeta:
                    nombres.discard(desde.name)
                if hasta.parent == carpeta:
                    nombres.add(hasta.name)

            sello = datetime.now().strftime("%Y%m%d-%H%M%S")
            try:
                # 0. Lo que un orden cortado a medias dejó con su nombre de paso,
                #    a su nombre: es el que sigue en su constancia.
                for nombre in sorted(n for n in listado if n.startswith(PREFIJO_DE_PASO)):
                    paso = carpeta / nombre
                    original = paso.with_name(nombre.split("-", 2)[2])
                    if original.name not in nombres:
                        mover(paso, original)
                # 1. El índice suelto de cada UPD, como se entregaba antes: sus
                #    filas a la constancia y el archivo, apartado.
                for _, constancia in leidas:
                    sueltos = [a for a in constancia.archivos if _INDICE_POR_UPD.match(str(a.get("ruta") or ""))]
                    for archivo in sueltos:
                        relativa = Path(str(archivo.get("ruta")))
                        hoja = carpeta / relativa
                        if constancia.indice is None and existe(relativa):
                            try:
                                constancia.indice = _indice_a_dict(leer_indice(hoja))
                            except Exception:  # noqa: BLE001 - un índice ilegible no para la carpeta
                                logger.warning("no se pudo leer el índice %s", hoja, exc_info=True)
                        if existe(relativa):
                            apartado = carpeta / REEMPLAZADOS_DIR / sello / hoja.name
                            apartado.parent.mkdir(parents=True, exist_ok=True)
                            mover(hoja, apartado)
                        constancia.archivos.remove(archivo)
                # 2. Los PDF, numerados seguidos por el orden de su UPD (o por la
                #    fecha de cada documento: ``_numeracion_del_nic``).
                plan, filas = _numeracion_del_nic([constancia for _, constancia in leidas])
                cambios = [(archivo, actual, nuevo) for archivo, actual, nuevo in plan if nuevo != actual and existe(actual)]
                # Primero todos a un nombre de paso, después a su número: así el
                # «02» de un UPD no pisa el «02» que otro está dejando libre.
                de_paso = []
                try:
                    for puesto, (archivo, actual, nuevo) in enumerate(cambios):
                        paso = carpeta / actual.with_name(f"{PREFIJO_DE_PASO}{puesto}-{actual.name}")
                        mover(carpeta / actual, paso)
                        de_paso.append((archivo, paso, nuevo))
                    for archivo, paso, nuevo in de_paso:
                        destino = carpeta / nuevo
                        if existe(nuevo):
                            if nuevo.as_posix() in de_las_cortadas and nuevo.as_posix() not in de_las_completas:
                                # El resto de una entrega cortada con su nombre final:
                                # se aparta -- ese PDF se rehace entero -- y no sale «(2)».
                                apartado = carpeta / REEMPLAZADOS_DIR / sello / nuevo.name
                                apartado.parent.mkdir(parents=True, exist_ok=True)
                                mover(destino, apartado)
                            else:
                                # Un archivo que no es del bot ocupa el nombre: no se pisa.
                                destino = unique_path(destino.parent, destino.name)
                        mover(paso, destino)
                        archivo["ruta"] = destino.relative_to(carpeta).as_posix()
                finally:
                    # Cortado a medias -- un PDF que sigue abierto en un visor --:
                    # lo que quedó con su nombre de paso vuelve al suyo, sin pisar
                    # nada, y las constancias dicen dónde quedó cada uno. Sin esto
                    # la corrida siguiente veía «falta … en el destino» y rehacía
                    # un UPD que ya estaba entregado.
                    for archivo, paso, _ in de_paso:
                        try:
                            if paso.exists():
                                vuelta = carpeta / str(archivo["ruta"])
                                if vuelta.exists():
                                    vuelta = unique_path(vuelta.parent, vuelta.name)
                                os.replace(paso, vuelta)
                                archivo["ruta"] = vuelta.relative_to(carpeta).as_posix()
                        except OSError:
                            logger.warning("no se pudo devolver %s a su nombre", paso, exc_info=True)
                    # Sólo las que cambiaron: con cuatro UPD en el NIC, reescribir
                    # las cuatro en cada entrega eran cuatro renombres de casi un
                    # segundo cada uno (2026-11-25).
                    for (ruta, constancia), antes in zip(leidas, como_estaban, strict=True):
                        if _huella_de_la_constancia(constancia) != antes:
                            constancias.escribir(ruta, constancia, carpeta_existe=True)
                # 3. Un solo índice, con las filas de todos sus UPD.
                nic = territorial = None
                for _, constancia in leidas:
                    datos = constancia.indice or {}
                    nic = nic or datos.get("nic")
                    territorial = territorial or datos.get("territorial")
                if any(constancia.indice for _, constancia in leidas):
                    # Por la fecha de cada documento, lo antiguo primero, y
                    # «Nombre del Expediente» = el NIC (lo dictó el operador el
                    # 2026-11-04). Nunca el UPD (2026-10-22). Los PDF llevan el
                    # mismo puesto que su fila (2026-11-11), salvo los de una
                    # entrega de antes, que guardan el orden de sus hojas. Se
                    # arma en este equipo y va de una sola copia (``guardar_libro``).
                    indice = escribir_indice(
                        carpeta,
                        en_orden_cronologico(filas),
                        nic=nic,
                        territorial=territorial,
                        nombre_del_expediente=nic,
                        armado_en_local=True,
                    )
                    with run.cerrojo:
                        # En el libro general, una hoja por NIC y no una por UPD.
                        for _, constancia in leidas:
                            run.indices.pop(Path(constancia.origen).stem, None)
                        run.indices[carpeta.name] = indice
                    if len(filas) != len(plan):
                        self._avisar(
                            run,
                            f"«{carpeta.name}»: el índice lleva {len(filas)} filas y la carpeta "
                            f"{len(plan)} PDF; revise el índice.",
                        )
                elif NOMBRE_DEL_INDICE in nombres:
                    with run.cerrojo:
                        run.indices[carpeta.name] = carpeta / NOMBRE_DEL_INDICE
            except Exception as error:  # noqa: BLE001 - las entregas ya están hechas
                logger.warning("no se pudo ordenar la carpeta %s", carpeta, exc_info=True)
                self._avisar(run, f"«{carpeta.name}»: no se pudo ordenar la carpeta del NIC: {explicar_fallo(error)}")

    @staticmethod
    def _firma_de(job: Job, origin: Path) -> str | None:
        """La firma del PDF que se procesó: de su copia local si la hay, si no del origen."""
        for candidata in (Path(str(job.source)) if job.source else None, origin):
            if candidata is None:
                continue
            try:
                if red_smb.por_smb(candidata) or candidata.exists():
                    return constancias.firma_del_origen(candidata)
            except (OSError, red_smb.CredencialesDeRed):
                continue
        return None

    def _liberar_salidas(self, job: Job) -> None:
        """Borra de salidas los PDF que ya están en el destino (ver ``liberar_salidas``)."""
        producido = self._settings.output_dir / job.id
        try:
            for pdf in producido.rglob("*.[pP][dD][fF]"):
                pdf.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("no se pudieron liberar las salidas de %s: %s", job.filename, error)

    def _apartar_lo_anterior(
        self,
        run: FolderRun,
        base: Path,
        constancia: Constancia | None,
        vigencia: Vigencia,
        *,
        prefijo: str = "",
        listado: Mapping[str, os.DirEntry] | None = None,
        proteger: set[str] | None = None,
    ) -> bool:
        """Aparta lo que se entregó antes de rehacer un PDF, para no dejar «(2)». Dice si apartó algo.

        ``listado``: el de ``base`` que ya tiene quien llama (``_listado``), para
        no volver a listarla ni preguntar por cada archivo al destino.
        ``proteger``: lo que nombra la constancia completa de otro PDF de la
        carpeta (``_nombrados_por_otros``): eso nunca se aparta.

        Con constancia, exactamente lo que ella dice que se entregó. Sin ella
        (una entrega de antes de que existiera), sólo lo que el bot produce --
        los PDF y los Excel de la carpeta del PDF --: un archivo que el operador
        dejó ahí por su cuenta no es del bot y no se toca (lo pidió el operador
        el 2026-10-20: «que actúe estrictamente según lo seleccionado»).
        Se mueve a ``_reemplazados/<fecha>``, no se borra: es trabajo entregado,
        y si sobra lo decide el operador.
        """
        sello = datetime.now().strftime("%Y%m%d-%H%M%S")
        apartado = base / REEMPLAZADOS_DIR / sello
        if constancia is None:
            try:
                # Del listado (``DirEntry.is_file`` sale de él): sin una pregunta
                # al destino por cada archivo de la carpeta del NIC.
                entradas = list(listado.values()) if listado is not None else list(os.scandir(base))
                rutas = [
                    base / entrada.name
                    for entrada in entradas
                    if entrada.is_file()
                    and Path(entrada.name).suffix.lower() in EXTENSIONES_DEL_BOT
                    # El bloqueo de un Excel abierto no es una entrega.
                    and not constancias.es_ajeno(entrada.name)
                    # En la carpeta compartida de una caja, sólo lo de este PDF. Con
                    # `_sin_el_prefijo`: al entregar «02.pdf», el «02_RESPUESTA.pdf»
                    # ya numerado de «01.pdf» no es suyo (la revisión, 2026-11-10).
                    and (
                        not prefijo
                        or _sin_el_prefijo(entrada.name, prefijo) != entrada.name
                        # Su índice suelto de antes, «00.INDICE ELECTRONICO UPD….xlsx».
                        # Sólo el Excel y con el espacio delante: con un origen de
                        # sólo dígitos («1.pdf») atrapaba el PDF de otro UPD cuyo
                        # RE acaba en esa cifra (la revisión, 2026-11-26).
                        or (
                            Path(entrada.name).suffix.lower() == ".xlsx"
                            and Path(entrada.name).stem.endswith(" " + prefijo.rstrip("_"))
                        )
                    )
                ]
            except OSError:
                rutas = []
        else:
            rutas = [
                ruta
                for archivo in constancia.archivos
                if (ruta := constancias.ruta_de_entrega(base, archivo.get("ruta"))) is not None
            ]
        movidos = 0
        for ruta in rutas:
            if ruta.name.startswith(Path(constancias.NOMBRE).stem):
                continue
            if proteger and _relativa_a(ruta, base) in proteger:
                continue
            if listado is not None and ruta.parent == base:
                if ruta.name not in listado:
                    continue
            elif not ruta.exists():
                continue
            if ruta.suffix.lower() not in EXTENSIONES_DEL_BOT or constancias.es_ajeno(ruta.name):
                # Una constancia de antes del 2026-10-27 anotaba todo lo que
                # hubiera en la carpeta, también lo del operador: eso no se aparta.
                continue
            try:
                relativa = ruta.relative_to(base)
                (apartado / relativa).parent.mkdir(parents=True, exist_ok=True)
                _mover(ruta, apartado / relativa)
                movidos += 1
            except (OSError, ValueError) as error:
                logger.warning("no se pudo apartar %s: %s", ruta, error)
        if movidos:
            self._avisar(
                run,
                f"«{base.name}»: la entrega anterior ({vigencia}) se rehízo; lo que había "
                f"quedó en {REEMPLAZADOS_DIR}\\{sello}.",
            )
        return movidos > 0


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
    #: Las copias que fallaron y se pueden reintentar tal cual: (desde, hasta,
    #: si puede reemplazar lo que haya en ``hasta``). Si todos los fallos son
    #: de éstos, se reintenta sólo la copia antes de rehacer el PDF entero.
    pendientes: list[tuple[Path, Path, bool]] = field(default_factory=list)
    #: El Índice Electrónico de este PDF, leído, para su constancia: en la
    #: carpeta de un NIC va uno solo para todos sus UPD (``_ordenar_la_caja``).
    indice: dict | None = None
    #: El tamaño de cada archivo copiado, comprobado al copiarlo: la constancia
    #: no vuelve a preguntárselo al destino.
    tamanos: dict[Path, int] = field(default_factory=dict)
    #: Las citas de trece cifras de cada PDF copiado (``citas_del_pdf``), que
    #: van en su constancia para cruzar el RE con el expediente sin releerlo.
    citas: dict[Path, list] = field(default_factory=dict)
    #: La constancia completa que otro equipo dejó de este PDF mientras éste lo
    #: leía: ya está entregado y no se entrega otra vez.
    ya_estaba: object | None = None
    #: Si la entrega plana ya cerró su constancia en su turno (``True``/``False``);
    #: ``None`` si la cierra después ``_dejar_constancia``.
    cerrada: bool | None = None


#: Lo que se decide de cada PDF al verificar lo ya entregado (el análisis de la entrega).
DECISION_YA_ENTREGADO = "Ya entregado: se salta"
DECISION_SE_REHACE = "Se rehace"
DECISION_NUEVO = "Nuevo: se procesa"
DECISION_OTRA_VEZ = "Se procesa otra vez"
DECISION_SE_COMPARA = "Se compara con el destino"
#: El motivo del carril rápido (2026-11-26): ni su carpeta ni la de su
#: constancia están en el destino, así que no hay constancia que leer.
MOTIVO_SIN_CARPETA = "su carpeta no está en el destino"

PREFIJO_DE_PASO = constancias.PREFIJO_DE_PASO

#: Un reclamo que no se pudo mirar en la segunda pasada: lo decide su toma.
_SIN_MIRAR = object()

#: Un archivo de la caja de correspondencia en la carpeta de su NIC: «03_RECLAMO.pdf»,
#: y como se entregaban hasta el 2026-10-21, con su UPD delante.
_NUMERO_DEL_ARCHIVO = re.compile(r"^(?:UPD\d+_)?(\d+)_(.+)$", re.IGNORECASE)
#: El índice de un UPD como se entregaba hasta el 2026-10-21: «00.INDICE ELECTRONICO UPD….xlsx».
_INDICE_POR_UPD = re.compile(r"^00\.INDICE ELECTRONICO \S+\.xlsx$", re.IGNORECASE)


@dataclass(slots=True)
class _EntregaPreparada:
    """Lo que la entrega plana de un PDF saca en este equipo antes de tomar ningún turno."""

    #: Los PDF que produjo su trabajo, en orden.
    archivos: list[Path]
    #: Su Índice Electrónico, leído, para su constancia.
    indice: dict | None
    #: Las citas de trece cifras de cada PDF (``citas_del_pdf``).
    citas: dict[Path, list]


def _huella_de_la_constancia(constancia) -> str:
    """Todo lo que dice una constancia, para saber si cambió sin escribirla otra vez."""
    return json.dumps(constancia.as_dict(), sort_keys=True, ensure_ascii=False, default=str)


def _numeracion_del_nic(constancias_del_nic: list) -> tuple[list[tuple[dict, Path, Path]], list]:
    """El nombre final de cada PDF de la carpeta de un NIC, con todos sus UPD: (archivo, actual, nuevo), y sus filas.

    Los PDF de todos los UPD -- ya ordenados por su origen -- van seguidos:
    «01_…», «02_…», en el orden de su UPD y de sus hojas. Si cada UPD los trae
    numerados por la fecha de su documento (``indice["por_fecha"]``) y tantas
    filas como PDF, el PDF y su fila van al mismo puesto, por esa fecha y
    cruzando los UPD (el operador, 2026-11-11: «como esté en el Excel, también
    estará en el orden de archivos y numeración»). Las filas salen en ese orden.

    La usan ``_ordenar_la_caja`` y la entrega a una carpeta de NIC nueva
    (``_nombres_en_el_nic``): el nombre con que se copia es el mismo que
    pondría el orden, y no hay que renombrar nada después.
    """
    from ..domain.orden_del_indice import orden_cronologico

    pdfs_de = [
        [
            (archivo, _prefijo_de_la_constancia(constancia))
            for archivo in sorted(
                (a for a in constancia.archivos if str(a.get("ruta") or "").lower().endswith(".pdf")),
                key=lambda a, c=constancia: _orden_del_archivo(a, _prefijo_de_la_constancia(c)),
            )
        ]
        for constancia in constancias_del_nic
    ]
    filas_de = [_filas_de_la_constancia(constancia) for constancia in constancias_del_nic]
    pdfs = [par for suyos in pdfs_de for par in suyos]
    filas = [fila for suyas in filas_de for fila in suyas]
    if all(
        (constancia.indice or {}).get("por_fecha") and len(suyas) == len(suyos)
        for constancia, suyas, suyos in zip(constancias_del_nic, filas_de, pdfs_de, strict=True)
    ):
        puestos = orden_cronologico([fila.fecha_creacion for fila in filas])
        pdfs = [pdfs[puesto] for puesto in puestos]
        filas = [filas[puesto] for puesto in puestos]
    ancho = max(2, len(str(len(pdfs))))
    plan = []
    for numero, (archivo, prefijo) in enumerate(pdfs, start=1):
        actual = Path(str(archivo["ruta"]))
        hallado = _NUMERO_DEL_ARCHIVO.match(_sin_el_prefijo(actual.name, prefijo))
        titulo = hallado.group(2) if hallado else _sin_el_prefijo(actual.name, prefijo)
        plan.append((archivo, actual, actual.with_name(f"{numero:0{ancho}d}_{titulo}")))
    return plan, filas


def _orden_del_archivo(archivo: dict, prefijo: str = "") -> tuple[int, str]:
    """El puesto de un PDF entre los de su UPD: el número con que empieza su nombre, sin su prefijo."""
    ruta = str(archivo.get("ruta") or "")
    hallado = _NUMERO_DEL_ARCHIVO.match(_sin_el_prefijo(Path(ruta).name, prefijo))
    return (int(hallado.group(1)) if hallado else 10**6, ruta)


def _prefijo_de_la_constancia(constancia) -> str:
    """El prefijo con que se entregaron los archivos de un PDF en la carpeta de su NIC: «NIC 5940155-11_»."""
    origen = str(getattr(constancia, "origen", "") or "").replace("\\", "/")
    return f"{Path(origen).stem}_" if origen else ""


def _sin_el_prefijo(nombre: str, prefijo: str) -> str:
    """El nombre sin el prefijo de su PDF de origen, si lo lleva: «01_DOCUMENTO.pdf».

    También como quedó mal numerado hasta el 2026-11-10 -- el número delante
    del prefijo, «01_NIC 5940155-11_01_DOCUMENTO.pdf» --: al relanzar la
    carpeta se arregla sin volver a procesarla.
    """
    if not prefijo:
        return nombre
    # De un origen de sólo dígitos -- «01.pdf» --, el prefijo «01_» es igual al
    # puesto en la caja de «01_RECLAMO.pdf». Sólo es prefijo si detrás viene el
    # número del documento, «01_01_RECLAMO.pdf» (los títulos nunca llevan «_»).
    # Sin esto cada relanzamiento lo quitaba y la caja cambiaba de orden (la
    # revisión, 2026-11-10).
    solo_digitos = prefijo[:-1].isdigit()
    numerado = re.match(r"^\d+_", nombre)
    for candidato in (nombre, nombre[numerado.end():] if numerado else ""):
        if candidato and candidato.casefold().startswith(prefijo.casefold()):
            resto = candidato[len(prefijo):]
            if not solo_digitos or re.match(r"^\d+_", resto):
                return resto
    return nombre


def _filas_de_la_constancia(constancia) -> list:
    """Las filas del índice de un UPD, de su constancia, en su orden («Orden Documento» lo pone el índice)."""
    from ..adapters.indice_electronico import FilaDelIndice

    def fecha(valor: object) -> date | None:
        return date.fromisoformat(str(valor)) if valor else None

    return [
        FilaDelIndice(
            nombre=str(fila.get("nombre") or ""),
            fecha_creacion=fecha(fila.get("fecha_creacion")),
            fecha_incorporacion=fecha(fila.get("fecha_incorporacion")),
            orden=puesto,
            paginas=int(fila.get("paginas") or 0),
            formato=str(fila.get("formato") or "pdf"),
            observaciones=str(fila.get("observaciones") or ""),
            responsable=str(fila.get("responsable") or ""),
        )
        for puesto, fila in enumerate((constancia.indice or {}).get("filas") or [], start=1)
    ]


def _indice_a_dict(indice) -> dict:
    """Un ``IndiceLeido`` como va en la constancia: fechas en ISO."""
    return {
        "nic": indice.nic,
        "territorial": indice.territorial,
        "expediente": indice.nombre_del_expediente,
        "filas": [
            {
                "nombre": fila.nombre,
                "fecha_creacion": fila.fecha_creacion.isoformat() if fila.fecha_creacion else None,
                "fecha_incorporacion": fila.fecha_incorporacion.isoformat() if fila.fecha_incorporacion else None,
                "paginas": fila.paginas,
                "formato": fila.formato,
                "observaciones": fila.observaciones,
                "responsable": fila.responsable,
            }
            for fila in indice.filas
        ],
    }


#: Cuánto se espera, intento tras intento, a que otro programa suelte un PDF.
ESPERAS_SI_ESTA_EN_USO = (1.0, 2.0, 4.0, 8.0)


_en_uso = archivo_en_uso


def _en_uso_al_escribir(error: BaseException) -> bool:
    """Si vale la pena esperar antes de dar por fallida una escritura o un renombrado.

    Reemplazar un archivo que Excel o un visor tiene abierto no siempre da el
    «en uso» de Windows (32): ``os.replace`` contesta «acceso denegado» (5).
    Al escribir se espera también por eso; si de verdad falta el permiso, se
    pierden unos segundos y el error sale igual. Al *leer* no, que ahí un
    permiso que falta no se arregla esperando.

    Y lo que contesta el cliente SMB de Linux cuando el servidor retiene el
    archivo un momento: EAGAIN («Resource temporarily unavailable») o EBUSY.
    Cortaba el orden de la carpeta del NIC a la mitad (2026-11-25).
    """
    from ..adapters.coordinacion_en_disco import es_pasajero

    return _en_uso(error) or es_pasajero(error)


def _esperar_a_que_se_libere(ruta: Path) -> None:
    """Abre el PDF para leerlo, y si otro programa lo tiene tomado espera y reintenta.

    Si sigue tomado, el error lo dice con palabras -- quién puede tenerlo -- y
    el PDF vuelve en la vuelta de reintento del final de la carpeta.
    """
    if red_smb.por_smb(ruta):
        return
    for espera in (*ESPERAS_SI_ESTA_EN_USO, None):
        try:
            with ruta.open("rb") as archivo:
                archivo.read(1)
            return
        except OSError as error:
            if not _en_uso(error):
                return  # otro fallo: lo dirá quien lo procese
            if espera is None:
                # Con el error de Windows debajo: ``explicar_fallo`` lo reconoce
                # y lo cuenta como un archivo abierto en otro programa.
                raise PermissionError(errno.EACCES, "el archivo está abierto en otro programa", str(ruta)) from error
        time.sleep(espera)


#: Cuánto tiene que llevar quieto un PDF recién llegado para darlo por copiado.
#: Uno escaneado hace horas no espera nada: sólo se mira el que se modificó
#: hace menos que esto.
SEGUNDOS_DE_CALMA = 2.0
#: Y hasta cuándo se le espera, para que una copia colgada no pare la carpeta.
TOPE_DE_LA_COPIA = 600.0


def _esperar_a_que_termine_de_copiarse(ruta: Path, calma: float | None = None) -> tuple[int, int] | None:
    """La huella del PDF cuando deja de cambiar, o ``None`` si es de la red.

    Explorer, robocopy o el escáner escriben el PDF poco a poco con su nombre
    definitivo; procesarlo en medio daba un documento al que le faltaban
    páginas -- MuPDF repara el truncado sin quejarse -- (2026-10-27). Se mira
    sólo el que cambió hace menos de ``calma`` segundos, y se espera a que dos
    miradas seguidas coincidan.
    """
    if red_smb.por_smb(ruta):
        return None
    calma = SEGUNDOS_DE_CALMA if calma is None else calma
    try:
        previa = constancias.huella_del_origen(ruta)
    except OSError:
        return None  # que lo diga quien lo abra
    limite = time.monotonic() + TOPE_DE_LA_COPIA
    while calma > 0 and time.time_ns() - previa[1] < calma * 1e9 and time.monotonic() < limite:
        time.sleep(calma)
        try:
            actual = constancias.huella_del_origen(ruta)
        except OSError:
            return previa
        if actual == previa:
            break
        previa = actual
    return previa


def _reintentar_si_esta_en_uso(escribir: Callable[[], object]) -> None:
    """Escribe, y si otro programa tiene el archivo tomado espera y reintenta.

    Las mismas esperas que un PDF abierto. Lo que no sea un archivo en uso
    sube a la primera.
    """
    for espera in (*ESPERAS_SI_ESTA_EN_USO, None):
        try:
            escribir()
            return
        except OSError as error:
            if espera is None or not _en_uso_al_escribir(error):
                raise
        time.sleep(espera)


def _mover(desde: Path, hasta: Path) -> None:
    """``os.replace`` que espera a que otro programa suelte el archivo antes de fallar.

    Ordenar la carpeta de un NIC o apartar una entrega renombra PDF que el
    operador puede tener abiertos en un visor; sin esperar, el orden se cortaba
    a medias («The process cannot access the file because it is being used by
    another process», 2026-10-22).
    """
    for espera in (*ESPERAS_SI_ESTA_EN_USO, None):
        try:
            os.replace(desde, hasta)
            return
        except OSError as error:
            if espera is None or not _en_uso_al_escribir(error):
                raise
        time.sleep(espera)


#: Lo más largo que Windows deja abrir sin las rutas largas activadas
#: (``LongPathsEnabled``, apagado en los equipos del archivo): MAX_PATH son 260
#: con el cero del final, y una carpeta 12 menos, para que quepa dentro un
#: nombre corto 8.3.
LARGO_DE_RUTA_EN_WINDOWS = 259
LARGO_DE_CARPETA_EN_WINDOWS = 247


def _parcial_de(hasta: Path) -> Path:
    """El «.part» de una copia: «<nombre>.<marca>.part», o «.<marca>.part» si con su nombre no cabe en Windows.

    El destino espejo de una carpeta con subcarpetas anidadas y un libro
    dividido por carpeta -- «… - PROCESADO\\RESOLUCIONES\\RESOLUCIONES
    DECANATURA 1995-2002\\RESOLUCIONES DECANATURA 1995-2002 TOMO 2\\1992-2002-
    tomo 2\\01_RESOLUCION….pdf» (Odontología, 2026-11-27) -- deja PDF cuya ruta
    cabe justa en el límite, y los 14 caracteres del «.part» la sacaban de él:
    la copia fallaba sin que el PDF final pasara del límite. Con la marca
    única igual, para que dos equipos no compartan el «.part».
    """
    marca = uuid4().hex[:8]
    parcial = hasta.with_name(f"{hasta.name}.{marca}.part")
    if os.name == "nt" and len(str(parcial)) > LARGO_DE_RUTA_EN_WINDOWS:
        return hasta.with_name(f".{marca}.part")
    return parcial


def _por_lo_largo(error: BaseException, ruta: Path) -> str | None:
    """Si una entrega falló porque su ruta no cabe en Windows, dicho para el operador; si no, ``None``.

    Sin las rutas largas activadas, Windows contesta a una ruta de más de 259
    caracteres «no se encuentra la ruta», y ``explicar_fallo`` decía «se movió,
    se renombró o se borró»: el operador habría buscado un archivo que nadie
    tocó. Con el destino espejo y una carpeta por libro, el árbol real de
    Odontología deja de 28 a 102 caracteres para el nombre de cada PDF en
    ``C:\\Users\\…\\Desktop\\PROCESADOS`` (medido el 2026-11-27). Sólo si lo
    que falló es la ruta larga: un origen que de verdad desapareció sigue con
    su explicación de siempre.
    """
    if os.name != "nt" or not isinstance(error, OSError) or isinstance(error, PermissionError):
        return None
    fallidas = [str(nombre) for nombre in (error.filename, getattr(error, "filename2", None)) if nombre]
    largo = max([len(str(ruta)), *map(len, fallidas)])
    # «El nombre del archivo o la extensión es demasiado largo» (WinError 206):
    # una carpeta de 248 a 259 caracteres, que como archivo cabría (medido).
    if not (getattr(error, "winerror", None) == 206 or error.errno == errno.ENAMETOOLONG):
        if not isinstance(error, FileNotFoundError):
            return None
        if fallidas and all(len(nombre) <= LARGO_DE_RUTA_EN_WINDOWS for nombre in fallidas):
            # Lo que falló cabe: no es el largo (un origen que se borró, por ejemplo).
            return None
        if largo <= LARGO_DE_RUTA_EN_WINDOWS and len(str(ruta.parent)) <= LARGO_DE_CARPETA_EN_WINDOWS:
            return None
    return (
        f"la ruta en el destino tiene {largo} caracteres y Windows no deja pasar de "
        f"{LARGO_DE_RUTA_EN_WINDOWS} sin las rutas largas activadas. Elija un destino más cerca de la "
        "raíz del disco, o active las rutas largas de Windows, y vuelva a lanzar la carpeta: sólo se "
        "procesa lo que falte."
    )


def _explicar_la_entrega(error: BaseException, ruta: Path) -> str:
    """``explicar_fallo``, salvo que lo que falló sea el largo de la ruta en Windows (``_por_lo_largo``)."""
    return _por_lo_largo(error, ruta) or explicar_fallo(error)


def _copiar(desde: Path, hasta: Path, medir: Callable[[int, float, float], None] | None = None) -> None:
    """Copia entera o nada: primero a «.part» y luego, comprobada, a su nombre.

    Una copia que se cortaba -- la red, el disco lleno -- dejaba un PDF a medias
    con su nombre definitivo, y la corrida siguiente lo daba por entregado.

    ``medir`` recibe los bytes y de cuándo a cuándo se copiaron: la velocidad
    de escritura en el destino (2026-11-05).
    """
    # Con nombre único: dos equipos que entregan a la misma carpeta no
    # comparten el «.part» (2026-11-25, varios PC en un destino).
    parcial = _parcial_de(hasta)
    for espera in (*ESPERAS_SI_ESTA_EN_USO, None):
        try:
            inicio = time.monotonic()
            # Sin copiar fechas ni permisos (``copy2``): nadie las mira --la
            # constancia comprueba tamaños-- y en un destino de red eran uno o
            # dos cambios de atributos de casi un segundo por archivo (2026-11-25).
            shutil.copyfile(desde, parcial)
            fin = time.monotonic()
            tamano = parcial.stat().st_size
            if tamano != desde.stat().st_size:
                raise OSError(errno.EIO, "la copia quedó incompleta", str(hasta))
            os.replace(parcial, hasta)
            if medir is not None:
                try:
                    medir(tamano, inicio, fin)
                except Exception:  # noqa: BLE001 - medir nunca tumba una entrega
                    logger.debug("no se pudo anotar la velocidad de %s", hasta, exc_info=True)
            return
        except BaseException as error:
            try:
                parcial.unlink(missing_ok=True)
            except OSError:
                pass
            # El destino abierto en otro programa -- el PDF en un visor --: se
            # espera y se reintenta antes de dar la copia por fallida.
            if espera is None or not isinstance(error, OSError) or not _en_uso_al_escribir(error):
                raise
        time.sleep(espera)


def _copiar_directo(
    desde: Path,
    carpeta: Path,
    nombre: str,
    medir: Callable[[int, float, float], None] | None = None,
    *,
    encima_de: Path | None = None,
) -> tuple[Path, int]:
    """Copia ``desde`` a ``carpeta`` con su nombre final, sin pisar nunca nada; devuelve dónde y cuánto.

    Para la entrega plana, que ya dejó en la constancia «entregando» la lista
    de lo que va a copiar: una copia cortada se aparta entera al rehacer el
    PDF, así que no hace falta pasar por un «.part» y renombrarlo después -- un
    renombre de casi un segundo por archivo en un destino de red lento
    (2026-11-25) --. Se crea en exclusiva: si el nombre ya está tomado, el
    siguiente libre (``unique_path``), igual que antes.

    ``encima_de``: el archivo que dejó a medias un intento anterior de esta
    misma copia (la red se cortó y no se pudo borrar): se reescribe ése.

    Si falla, el error lleva en ``filename`` el archivo que se intentó: quien
    reintenta sabe cuál es suyo.
    """
    esperado = desde.stat().st_size
    hasta = encima_de or carpeta / nombre
    for intento in range(3):
        try:
            # Se cierra abajo, también si la copia falla.
            destino = open(hasta, "wb" if encima_de is not None else "xb")  # noqa: SIM115
        except FileExistsError:
            if intento == 2:
                raise
            hasta = unique_path(carpeta, nombre)
            continue
        except OSError as error:
            error.filename = str(hasta)
            raise
        inicio = time.monotonic()
        try:
            with destino, desde.open("rb") as origen:
                shutil.copyfileobj(origen, destino, 1024 * 1024)
                copiados = destino.tell()
            if copiados != esperado:
                raise OSError(errno.EIO, "la copia quedó incompleta", str(hasta))
        except BaseException as error:
            with contextlib.suppress(OSError):
                hasta.unlink(missing_ok=True)
            if isinstance(error, OSError):
                # Cuál se intentó: si no se pudo borrar, el reintento es suyo.
                error.filename = str(hasta)
            raise
        if medir is not None:
            try:
                medir(copiados, inicio, time.monotonic())
            except Exception:  # noqa: BLE001 - medir nunca tumba una entrega
                logger.debug("no se pudo anotar la velocidad de %s", hasta, exc_info=True)
        return hasta, copiados
    raise FileExistsError(errno.EEXIST, "no quedó un nombre libre", str(carpeta / nombre))


def _relativa_a(ruta: Path, base: Path) -> str:
    """La ruta de un archivo entregado como la guarda su constancia: relativa a su carpeta, con «/»."""
    try:
        return ruta.relative_to(base).as_posix()
    except ValueError:
        return ruta.name


def _listado(carpeta: Path, *, estricto: bool = False) -> dict[str, os.DirEntry]:
    """Lo que hay en una carpeta del destino, de una sola petición: nombre → entrada.

    ``DirEntry.is_file`` y ``is_dir`` salen del propio listado, sin preguntar
    al servidor por cada archivo. Vacío si la carpeta no está o no se deja
    leer; ``estricto``: si no se deja leer, el error sube -- quien va a escribir
    en ella no puede creer que está vacía --.
    """
    try:
        with os.scandir(carpeta) as entradas:
            return {entrada.name: entrada for entrada in entradas}
    except FileNotFoundError:
        return {}
    except OSError:
        if estricto:
            raise
        return {}


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
