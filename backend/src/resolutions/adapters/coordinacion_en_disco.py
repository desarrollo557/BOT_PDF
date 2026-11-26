"""Varios equipos sobre la misma carpeta de destino, coordinados por archivos.

El operador, 2026-11-25: «correr 4 PC al mismo tiempo sin que ninguno se pise
los procesos, consumiendo de la misma fuente y llevando al mismo destino», por
carpetas compartidas de red. No hay servidor central: la verdad está en el
destino compartido, en el área ``.botpdf-coordinacion``::

    corrida.json                       la corrida en marcha: opciones y versión
    equipos/<id>.json                  el latido de cada equipo, cada 10 s
    corridas/<corrida>/reclamos/       un archivo por PDF tomado o hecho
    corridas/<corrida>/fallidos/       el PDF que falló en un equipo
    corridas/<corrida>/roles/          quién cierra la corrida
    cerrojos/<clave>.lock              el turno de cada carpeta NIC del destino
    diario/<id>.jsonl                  lo que hizo cada equipo, para revisarlo
    ordenes/<id>.json                  la orden de parar que un equipo deja para otro

**El reclamo** es un archivo creado en exclusiva (``O_CREAT | O_EXCL``), que
el servidor SMB resuelve de forma atómica: de dos equipos que lo intentan a la
vez, gana uno. **El latido** dice que el equipo sigue vivo; si su contador deja
de cambiar 90 s -- medidos por quien lo mira, nunca con la hora de otro PC --,
lo que tenía reclamado se puede tomar. **La ficha** de cada reclamo es la
barrera contra el equipo que vuelve después de darlo por caído: antes de
entregar se relee el reclamo, y si ya no lleva su ficha, no entrega.

Ver ``application.coordinacion`` para la parte que no toca el disco.
"""

from __future__ import annotations

import contextlib
import errno
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from ..application.coordinacion import (
    MODOS_DE_PARAR,
    SEGUNDOS_DEL_LATIDO,
    SEGUNDOS_PARA_DARLO_POR_CAIDO,
    SEGUNDOS_SIN_LATIDO_PROPIO,
    UNIENDOSE,
    OrdenNoPermitida,
    Vida,
    carpeta_de,
    clave_de,
    equipo_preferido,
    la_orden_que_manda,
    opciones_distintas,
)

logger = logging.getLogger(__name__)

#: El área de coordinación, dentro de la raíz del destino. Empieza por punto:
#: los recorridos del destino la saltan (``es_del_bot``).
AREA = ".botpdf-coordinacion"

#: Cuánto se espera, como mucho, el turno de una carpeta NIC que tiene otro
#: equipo vivo: una entrega grande por la red tarda minutos, no horas.
ESPERA_MAXIMA_DEL_CERROJO = 30 * 60.0
#: Cuántos latidos espera la barrera (``confirmar``) a que vuelva a escribirse
#: el propio cuando lleva demasiado sin poder: un servidor lento un momento no
#: tira el OCR ya pagado (2026-11-25: «este equipo lleva demasiado sin poder
#: escribir…», con PDF ya leídos).
LATIDOS_DE_ESPERA_DEL_PROPIO = 6
#: Cada cuántos latidos se vuelca el diario al disco: una línea por PDF a la
#: red eran dos idas y vueltas más por entrega.
LATIDOS_ENTRE_VOLCADOS = 3
#: Hasta cuántas líneas del diario se guardan si el destino no las deja escribir.
LINEAS_DEL_DIARIO_EN_MEMORIA = 50_000

_EXCLUSIVO = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)


class CoordinacionRechazada(RuntimeError):
    """Este equipo no puede unirse a la corrida del destino; el motivo va en palabras."""


class DestinoNoCompartible(CoordinacionRechazada):
    """La carpeta de destino no garantiza lo que la coordinación necesita (crear en exclusiva)."""


class ReclamoPerdido(RuntimeError):
    """Otro equipo tomó este PDF (este se dio por caído): no se entrega."""


class CerrojoOcupado(RuntimeError):
    """La carpeta del destino sigue en manos de otro equipo vivo tras la espera máxima."""


@dataclass(frozen=True)
class Reclamo:
    clave: str
    relativa: str
    ficha: str


@dataclass(frozen=True)
class Ajeno:
    """El PDF lo tiene otro equipo, o ya lo hizo."""

    equipo: str
    estado: str  # «en curso» | «hecho» | «falló» | «aquí»
    error: str = ""


#: El estado de un PDF que ya está en curso en este mismo equipo.
AQUI = "aquí"


def es_del_bot(nombre: str) -> bool:
    """Lo que el bot deja en el destino para coordinarse: ningún recorrido lo cuenta."""
    return nombre == AREA or nombre.startswith(".botpdf-")


def nombre_del_equipo() -> str:
    """El nombre de este PC: ``BOTPDF_EQUIPO`` (el instalador pone el del equipo), o el del sistema."""
    import socket

    nombre = os.environ.get("BOTPDF_EQUIPO") or os.environ.get("COMPUTERNAME") or socket.gethostname()
    limpio = "".join(c if c.isalnum() or c in "-_" else "-" for c in nombre.strip())
    return limpio[:40] or "equipo"


def _ahora_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _leer(ruta: Path) -> dict | None:
    """El JSON de un archivo de coordinación; ``None`` si no está o está a medio escribir."""
    for intento in range(3):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            return datos if isinstance(datos, dict) else None
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            # Recién creado y todavía vacío: el que lo creó lo está escribiendo.
            if intento < 2:
                time.sleep(0.05)
    return None


def _crear_en_exclusiva(ruta: Path, datos: Mapping[str, object]) -> bool:
    """Crea el archivo sólo si no existe. ``False`` si otro ya lo tenía.

    Sin ``fsync``: la exclusividad la da ``O_CREAT | O_EXCL`` en el servidor, y
    lo escrito le llega al cerrar. El ``fsync`` sólo le pedía al Windows del
    destino que lo asentara en su disco: 9 763 esperas de 1,06 s de media en
    una corrida de 9 h 45 min (2026-11-25), unas 2,9 h por equipo. Un lector
    que lo encuentra vacío ya lo trata como ilegible (``_leer``).
    """
    try:
        fd = os.open(ruta, _EXCLUSIVO)
    except FileExistsError:
        return False
    try:
        os.write(fd, json.dumps(dict(datos), ensure_ascii=False).encode("utf-8"))
    finally:
        os.close(fd)
    return True


#: Las esperas cuando el archivo está en uso: en Windows y en un recurso SMB no
#: se puede reemplazar ni borrar un archivo mientras otro equipo lo está
#: leyendo, y con varios equipos mirándose cada diez segundos pasa. Sin
#: reintentar, el latido de un equipo retirado se quedaba en el disco diciendo
#: «procesando» y el que cierra lo esperaba para siempre (2026-11-25).
ESPERAS_SI_ESTA_EN_USO = (0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 1.6)

#: Lo que el cliente SMB de Linux devuelve, en vez de «en uso», cuando el
#: servidor retiene un archivo un momento: «Resource temporarily unavailable»
#: (EAGAIN) y «Device or resource busy» (EBUSY). Cortaba el orden de la
#: carpeta del NIC a la mitad (2026-11-25, «.ordenando-0-…»).
ERRORES_PASAJEROS = frozenset(
    numero for numero in (errno.EAGAIN, errno.EBUSY, getattr(errno, "ETXTBSY", None)) if numero is not None
)


#: Lo que devuelve el cliente SMB mientras el servidor del destino no contesta
#: un momento: «Host is down» (los 36 fallos del 2026-11-25), la conexión
#: cortada, el tiempo agotado. Al volver la red, lo mismo sale bien.
ERRORES_DE_LA_RED = ERRORES_PASAJEROS | frozenset(
    numero
    for numero in (
        getattr(errno, nombre, None)
        for nombre in (
            "EHOSTDOWN",
            "EHOSTUNREACH",
            "ENETDOWN",
            "ENETUNREACH",
            "ENETRESET",
            "ECONNRESET",
            "ECONNABORTED",
            "ECONNREFUSED",
            "ETIMEDOUT",
            "EIO",
            "ESTALE",
        )
    )
    if numero is not None
)
#: Cuánto se espera a que vuelva el servidor antes de dar por fallido el turno
#: de una carpeta: el PDF ya está leído y pagado, y un corte de unos segundos
#: lo rehacía entero.
ESPERA_DE_LA_RED = 120.0


def es_de_la_red(error: BaseException) -> bool:
    """Si el fallo es de la red o de un archivo retenido: se espera y se reintenta."""
    return isinstance(error, OSError) and not isinstance(error, FileExistsError) and (
        error.errno in ERRORES_DE_LA_RED or isinstance(error, (ConnectionError, TimeoutError))
    )


def es_pasajero(error: BaseException) -> bool:
    """Si el archivo está retenido un momento y vale la pena esperar: en uso, o EAGAIN/EBUSY de SMB."""
    return isinstance(error, PermissionError) or (
        isinstance(error, OSError) and error.errno in ERRORES_PASAJEROS
    )


def reintentar_si_esta_en_uso(hacer: Callable[[], object]) -> object:
    """Hace ``hacer``; si el archivo está en uso o retenido un momento, espera y lo intenta otra vez."""
    for espera in (*ESPERAS_SI_ESTA_EN_USO, None):
        try:
            return hacer()
        except OSError as error:
            if espera is None or not es_pasajero(error):
                raise
            time.sleep(espera)
    return None


def _escribir_entero(ruta: Path, datos: Mapping[str, object]) -> None:
    """Lo escribe entero o nada: a un temporal con nombre único y luego en su sitio."""
    temporal = ruta.with_name(f".{ruta.name}.{uuid4().hex[:8]}.tmp")
    temporal.write_text(json.dumps(dict(datos), ensure_ascii=False), encoding="utf-8")
    try:
        reintentar_si_esta_en_uso(lambda: os.replace(temporal, ruta))
    except OSError:
        with contextlib.suppress(OSError):
            temporal.unlink()
        raise


def _existe(ruta: Path) -> bool:
    """Si el archivo está; ante un fallo de la red, que sí (lo prudente: no quitar un turno a ciegas)."""
    try:
        return ruta.exists()
    except OSError:
        return True


def _borrar(ruta: Path) -> None:
    def borrar() -> None:
        with contextlib.suppress(FileNotFoundError):
            ruta.unlink()

    reintentar_si_esta_en_uso(borrar)


class _CerrojoLocal:
    """El turno de una carpeta dentro de este proceso: reentrante, y el archivo una sola vez."""

    def __init__(self) -> None:
        self.rlock = threading.RLock()
        self.cuenta = 0
        self.ficha = ""


class Coordinacion:
    """La parte de este equipo en una corrida compartida sobre ``raiz`` (la raíz del destino)."""

    def __init__(
        self,
        raiz: Path,
        *,
        equipo: str | None = None,
        version: str = "",
        latido: float = SEGUNDOS_DEL_LATIDO,
        caido: float = SEGUNDOS_PARA_DARLO_POR_CAIDO,
        sin_latido_propio: float = SEGUNDOS_SIN_LATIDO_PROPIO,
        reloj: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.raiz = Path(raiz)
        self.area = self.raiz / AREA
        self.equipo = equipo or nombre_del_equipo()
        self.instancia = uuid4().hex
        #: El id de este equipo en esta corrida: el nombre del PC y su arranque.
        #: Dos arranques del mismo PC son dos ids; el viejo se da por caído.
        self.id = f"{self.equipo}-{self.instancia[:6]}"
        self.version = version
        self.latido = latido
        self.sin_latido_propio = sin_latido_propio
        #: Cuánto espera la barrera a que vuelva el latido propio (``confirmar``).
        self.espera_del_latido = latido * LATIDOS_DE_ESPERA_DEL_PROPIO
        self._reloj = reloj
        self._dormir = dormir
        self._vida = Vida(caido=caido)
        #: Los latidos de otras corridas sobre este destino: no reparten nada,
        #: sólo se miran para borrar los que dejó un arranque caído hace rato.
        self._otras = Vida(caido=caido)
        self._mutex = threading.Lock()
        self._cerrojos: dict[str, _CerrojoLocal] = {}
        self._por_borrar: list[Path] = []
        self._contador = 0
        #: Los equipos que dijeron «terminado» en su último latido.
        self._terminados: set[str] = set()
        self._ultimo_latido = reloj()
        self._parar = threading.Event()
        #: El latido propio va solo en su hilo, a ritmo fijo; la mirada a los
        #: demás, en otro. Juntos, una lectura lenta de un latido ajeno -- o un
        #: borrado esperando a la red -- retrasaba el propio, y a los 45 s la
        #: barrera tiraba el trabajo ya hecho (2026-11-25).
        self._hilo: threading.Thread | None = None
        self._hilo_de_la_mirada: threading.Thread | None = None
        #: El diario se escribe por tandas (``_volcar_el_diario``).
        self._diario_pendiente: list[str] = []
        self._cerrojo_del_diario = threading.Lock()
        self._volcando = threading.Lock()
        #: Los reclamos que no se pudieron dejar «hecho» (el destino sin contestar).
        self._hechos_pendientes: list[tuple[Reclamo, str | None]] = []
        self.corrida: dict | None = None
        #: Lo que el latido cuenta a los demás de este equipo.
        self.estado = UNIENDOSE
        self.en_curso: dict[str, str] = {}
        self.hechos = 0
        #: Otro equipo empezó una corrida nueva sobre este destino: esta ya no vale.
        self.desplazado = False
        #: El monitoreo de equipos (2026-11-26). Cuándo se unió a la corrida
        #: (ISO, con su reloj): con ``escrito`` da su ritmo en la pantalla.
        self.unido: str | None = None
        #: La orden de parar que cumple este equipo, o ``None`` (``recibir_orden``).
        self.orden: dict | None = None
        #: Lo que se hace al recibir una orden de parar: la corrida la cumple en su bucle.
        self.al_recibir_orden: Callable[[dict], None] | None = None
        self._cerrojo_de_la_orden = threading.Lock()
        #: Las órdenes que dio este equipo a otros (id → orden): el monitoreo las
        #: enseña en cuanto se dan, sin esperar a que el otro la lea y la lleve
        #: en su latido (hasta tres latidos).
        self._ordenes_dadas: dict[str, dict] = {}
        #: La foto de los latidos para la pantalla (``latidos``): lo que leyó la
        #: última mirada y el último latido propio escrito. Cada pantalla abierta
        #: pregunta cada 5 s: leer el destino en cada pregunta eran idas y
        #: vueltas de más contra un servidor que ya va lento.
        self._cerrojo_de_la_foto = threading.Lock()
        self._foto: dict[str, dict] = {}
        self._corrida_de_la_foto: str | None = None
        self._latido_propio: dict | None = None

    @property
    def retirado(self) -> bool:
        return self._parar.is_set()

    # -- rutas ------------------------------------------------------------------

    @property
    def _equipos(self) -> Path:
        return self.area / "equipos"

    @property
    def _de_la_corrida(self) -> Path:
        if self.corrida is None:
            raise RuntimeError("todavía no hay corrida")
        return self.area / "corridas" / str(self.corrida["id"])

    def _reclamo(self, clave: str) -> Path:
        return self._de_la_corrida / "reclamos" / f"{clave}.json"

    def _fallido(self, clave: str) -> Path:
        return self._de_la_corrida / "fallidos" / f"{clave}.json"

    # -- unirse -----------------------------------------------------------------

    def sondear(self) -> None:
        """Que la carpeta compartida haga lo que la coordinación necesita, o un motivo en palabras.

        Crear en exclusiva tiene que fallar la segunda vez -- es lo que impide
        que dos equipos tomen el mismo PDF --, y reemplazar un archivo tiene que
        dejar el nuevo.
        """
        pruebas = self.area / "pruebas"
        try:
            pruebas.mkdir(parents=True, exist_ok=True)
            ruta = pruebas / f"{self.id}-{uuid4().hex[:8]}.json"
            primero = _crear_en_exclusiva(ruta, {"prueba": 1})
            segundo = _crear_en_exclusiva(ruta, {"prueba": 2})
            _escribir_entero(ruta, {"prueba": 3})
            leido = _leer(ruta)
            _borrar(ruta)
        except OSError as error:
            raise DestinoNoCompartible(
                f"No se pudo escribir en el área de coordinación del destino ({error}): "
                "sin ella, varios equipos se pisarían."
            ) from None
        if not primero or segundo:
            raise DestinoNoCompartible(
                "La carpeta de destino no garantiza la creación exclusiva de archivos: "
                "dos equipos podrían tomar el mismo PDF. No se puede compartir entre equipos."
            )
        if (leido or {}).get("prueba") != 3:
            raise DestinoNoCompartible("La carpeta de destino no deja reemplazar archivos de forma segura.")

    def unirse(self, opciones: Mapping[str, object], origen: str) -> dict:
        """Se une a la corrida en marcha sobre este destino, o empieza una.

        Hay corrida en marcha si algún otro equipo late en ella. Para saberlo se
        miran los latidos dos veces, con un latido y medio entre medias: el que
        no cambió su contador no está vivo. Con un equipo vivo, las opciones y la
        versión del bot tienen que ser las mismas -- si no, se rechaza con la
        diferencia en palabras --. Sin ninguno, la corrida es nueva: lo que
        dejaron las anteriores (reclamos, fallos) queda en su carpeta y no cuenta.
        """
        for carpeta in ("equipos", "cerrojos", "diario", "corridas", "ordenes"):
            (self.area / carpeta).mkdir(parents=True, exist_ok=True)
        self.sondear()
        self._latir()
        self._arrancar_el_latido()
        try:
            with self.cerrojo("corrida", espera_maxima=5 * 60.0):
                corrida = _leer(self.area / "corrida.json")
                # Una corrida cerrada no se reabre: lo que quede latiendo en ella
                # es un equipo que volvió tarde, y ya no entrega (``por_que_no_vale``).
                abierta = bool(corrida) and not corrida.get("cerrada")
                antes = {
                    id_: datos for id_, datos in self._latidos_de_otros().items() if datos.get("estado") != "terminado"
                }
                # Los que deciden si hay corrida en marcha: los latidos de la
                # corrida abierta. Se miran hasta que uno cambie su contador -- está
                # vivo y la corrida sigue --, o hasta el plazo de caído. Mirarlos
                # sólo dos latidos y medio (≈26 s) era menos que lo que tarda un
                # latido con el servidor lento (huecos de más de 45 s el
                # 2026-11-25): el que se unía empezaba una corrida nueva y dejaba
                # fuera a todos los demás, que dejaban de entregar.
                relevantes = {
                    id_ for id_, datos in antes.items() if abierta and datos.get("corrida") == corrida.get("id")
                }
                vivos: dict[str, dict] = {}
                if relevantes:
                    limite = time.monotonic() + self._vida.caido + self.latido
                    while time.monotonic() < limite:
                        self._dormir(min(self.latido, 2.0) * 0.5 + 0.05)
                        for id_, datos in self._latidos_de_otros().items():
                            if id_ in antes and datos.get("contador") != antes[id_].get("contador"):
                                vivos[id_] = datos
                        if relevantes & set(vivos):
                            break
                en_la_corrida = {
                    id_: d for id_, d in vivos.items() if abierta and d.get("corrida") == corrida.get("id")
                }
                if en_la_corrida:
                    self._comprobar_que_encaja(corrida, opciones, origen, en_la_corrida)
                else:
                    # Nadie vivo en una corrida abierta: empieza una nueva. Un
                    # equipo de la anterior que siga vivo -- colgado, o que no se
                    # vio latir -- queda desplazado y no entrega nada más.
                    corrida = {
                        "id": f"{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}",
                        "origen": origen,
                        "opciones": {k: v for k, v in opciones.items() if v not in (None, "")},
                        "version": self.version,
                        "creada_por": self.equipo,
                        "creada": _ahora_iso(),
                    }
                    _escribir_entero(self.area / "corrida.json", corrida)
                self.corrida = corrida
                for carpeta in ("reclamos", "fallidos", "roles"):
                    (self._de_la_corrida / carpeta).mkdir(parents=True, exist_ok=True)
                # Desde aquí cuenta su ritmo en el monitoreo: el de «se unió».
                self.unido = _ahora_iso()
                self.estado = "procesando"
                self._latir()
        except BaseException:
            self.parar()
            raise
        self.anotar("se unió", corrida=self.corrida["id"], version=self.version)
        return self.corrida

    def _comprobar_que_encaja(
        self, corrida: dict, opciones: Mapping[str, object], origen: str, vivos: Mapping[str, dict]
    ) -> None:
        quienes = ", ".join(sorted({str(d.get("equipo") or i) for i, d in vivos.items()}))
        if str(corrida.get("origen") or "").casefold() != str(origen).casefold():
            raise CoordinacionRechazada(
                f"En este destino {quienes} procesa{'n' if len(vivos) > 1 else ''} el origen "
                f"«{corrida.get('origen')}», no «{origen}». Elija otro destino o el mismo origen."
            )
        if corrida.get("version") and self.version and corrida["version"] != self.version:
            raise CoordinacionRechazada(
                f"La versión del bot de este equipo no es la de la corrida ({quienes}): "
                "actualice la imagen en todos los equipos antes de unirlos (una versión distinta "
                "dividiría la mitad de la carpeta con otras reglas)."
            )
        distintas = opciones_distintas(opciones, corrida.get("opciones") or {})
        if distintas:
            raise CoordinacionRechazada(
                f"Las opciones no son las de la corrida que lleva {quienes}: " + "; ".join(distintas)
                + ". Elija las mismas para unirse."
            )

    # -- el latido ------------------------------------------------------------

    def _arrancar_el_latido(self) -> None:
        if self._hilo is not None:
            return
        self._hilo = threading.Thread(target=self._latiendo, name=f"latido-{self.id}", daemon=True)
        self._hilo.start()
        self._hilo_de_la_mirada = threading.Thread(target=self._mirando, name=f"mirada-{self.id}", daemon=True)
        self._hilo_de_la_mirada.start()

    def _latiendo(self) -> None:
        """Sólo el latido propio, a ritmo fijo: lo que tarda uno se descuenta del siguiente."""
        siguiente = time.monotonic() + self.latido
        while not self._parar.wait(max(0.0, siguiente - time.monotonic())):
            self._latir()
            # Si el latido tardó más que su periodo, el siguiente va enseguida,
            # sin amontonar los atrasados.
            siguiente = max(siguiente + self.latido, time.monotonic())

    def _mirando(self) -> None:
        """Lo demás que se hace cada latido: mirar a los otros, las órdenes, borrar lo pendiente, la corrida, el diario."""
        vueltas = 0
        while not self._parar.wait(self.latido):
            vueltas += 1
            self._mirar_a_los_demas()
            self._mirar_las_ordenes()
            self._borrar_lo_pendiente()
            self._marcar_lo_pendiente()
            self._mirar_la_corrida()
            if vueltas % LATIDOS_ENTRE_VOLCADOS == 0:
                self._volcar_el_diario()

    def _latir(self) -> None:
        self._contador += 1
        en_curso = sorted(self.en_curso.values())
        datos = {
            "id": self.id,
            "equipo": self.equipo,
            "version": self.version,
            "corrida": (self.corrida or {}).get("id"),
            "contador": self._contador,
            "estado": self.estado,
            # Los nombres, cortados en veinte; cuántos son, todos: con más de
            # veinte a la vez la pantalla decía veinte (2026-11-26).
            "en_curso": en_curso[:20],
            "en_curso_n": len(en_curso),
            "hechos": self.hechos,
            # El monitoreo (2026-11-26): desde cuándo está y qué orden de parar cumple.
            "unido": self.unido,
            "orden": self.orden,
            "escrito": _ahora_iso(),
        }
        try:
            _escribir_entero(self._equipos / f"{self.id}.json", datos)
            self._ultimo_latido = self._reloj()
            with self._cerrojo_de_la_foto:
                self._latido_propio = datos
        except OSError:
            logger.warning("no se pudo escribir el latido de %s", self.id, exc_info=True)

    def _latidos_de_otros(self) -> dict[str, dict]:
        latidos: dict[str, dict] = {}
        ilegibles: set[str] = set()
        for ruta in self._equipos.glob("*.json"):
            if ruta.stem == self.id:
                continue
            datos = _leer(ruta)
            if datos is not None:
                latidos[ruta.stem] = datos
            else:
                ilegibles.add(ruta.stem)
        #: Los latidos que están en la carpeta y no se dejaron leer en la última
        #: mirada: su equipo no se sabe si terminó (``los_demas_terminaron``).
        self._ilegibles = ilegibles
        return latidos

    def _mirar_a_los_demas(self) -> dict[str, dict] | None:
        """Lee los latidos de los demás; ``None`` si no se pudo mirar (la red).

        Lo visto se fecha al terminar de leer, no al empezar: con el servidor
        lento una lectura tardó 467 s (2026-11-25), y fechada al empezar hacía
        parecer muertos a equipos que acababan de latir. Una mirada que tarda
        más que ``Vida.atrasada`` no cuenta como mirar de seguido: nadie cae
        hasta volver a mirar bien durante el plazo entero.
        """
        empezo = self._reloj()
        try:
            latidos = self._latidos_de_otros()
        except OSError:
            ahora = self._reloj()
            self._vida.mirada(ahora, bien=False)
            self._otras.mirada(ahora, bien=False)
            return None
        ahora = self._reloj()
        bien = ahora - empezo <= self._vida.atrasada
        self._vida.mirada(ahora, bien=bien)
        self._otras.mirada(ahora, bien=bien)
        corrida = (self.corrida or {}).get("id")
        #: Lo que enseña el monitoreo hasta la próxima mirada (``latidos``).
        foto = {id_: dict(datos) for id_, datos in latidos.items()}
        for id_, datos in latidos.items():
            # El que se retiró ya no tiene nada: lo que haya dejado está libre.
            if datos.get("estado") == "terminado":
                self._terminados.add(id_)
                continue
            # Sólo los de esta corrida reparten: el latido que dejó un equipo
            # que se cayó en una corrida anterior no cuenta para nada.
            vida = self._vida if corrida is None or datos.get("corrida") == corrida else self._otras
            vida.observar(id_, datos.get("contador"), ahora)
            muerto = vida.muerto_hace(id_, ahora)
            if muerto is not None and muerto > 2 * vida.caido and self._quitar_el_latido(id_, datos):
                foto.pop(id_, None)
        with self._cerrojo_de_la_foto:
            self._foto = foto
            self._corrida_de_la_foto = corrida
        return latidos

    def _quitar_el_latido(self, id_: str, visto: Mapping[str, object]) -> bool:
        """Borra el latido que dejó un arranque caído hace rato, si sigue igual que cuando se vio. Dice si lo borró.

        Nunca se borraban: cada reinicio de un PC dejaba uno más, y cada equipo
        los releía todos en cada vuelta. Si su dueño vuelve, su siguiente
        latido lo escribe otra vez. Con él se va la orden de parar que ya no
        llegó a leer (2026-11-26).
        """
        ruta = self._equipos / f"{id_}.json"
        try:
            actual = _leer(ruta)
            if actual is not None and actual.get("contador") == visto.get("contador"):
                _borrar(ruta)
                self.anotar("borró el latido de un equipo caído", de=id_)
                with contextlib.suppress(OSError):
                    _borrar(self._orden_de(id_))
                return True
        except OSError:
            logger.debug("no se pudo borrar el latido viejo de %s", id_, exc_info=True)
        return False

    def _mirar_la_corrida(self) -> None:
        if self.corrida is None:
            return
        actual = _leer(self.area / "corrida.json")
        if actual is not None and actual.get("id") != self.corrida.get("id"):
            if not self.desplazado:
                logger.warning("otro equipo empezó la corrida %s sobre %s", actual.get("id"), self.raiz)
            self.desplazado = True

    def vivo(self, id_: str) -> bool:
        if id_ == self.id:
            return not self.retirado
        if id_ in self._terminados:
            return False
        return self._vida.vivo(id_, self._reloj())

    def equipos_vivos(self) -> list[str]:
        """Los ids que laten en esta corrida, este incluido."""
        return sorted({self.id, *(i for i in self._vida.vivos(self._reloj()) if i not in self._terminados)})

    def puede_entregar(self) -> bool:
        """Si este equipo sigue en pie para los demás: su latido reciente y su corrida vigente."""
        return not self.desplazado and self._reloj() - self._ultimo_latido < self.sin_latido_propio

    def latidos(self) -> dict[str, dict]:
        """Los latidos de los equipos del destino, para el monitoreo, con ``vivo`` y ``quieto_hace``.

        Sin leer el disco (2026-11-26): lo que vio la última mirada, que es de
        hace un latido como mucho, y el último latido propio escrito. ``vivo``
        se calcula sin apuntar a nadie en ``Vida`` -- ``Vida.vivo`` cuenta como
        visto al que no conoce, y así preguntar desde la pantalla cambiaba
        ``equipos_vivos`` y el reparto --. ``quieto_hace``: los segundos que
        lleva su contador sin cambiar, medidos por quien mira.

        Retirado este equipo, nadie más está vivo: su mirada ya no corre, la
        foto es la de cuando se retiró, y ``Vida.vivo`` -- con la mirada
        atrasada -- daba vivos a todos horas después (2026-11-26).
        """
        ahora = self._reloj()
        retirado = self.retirado
        with self._cerrojo_de_la_foto:
            foto = {id_: dict(datos) for id_, datos in self._foto.items()}
            corrida = self._corrida_de_la_foto
            propio = dict(self._latido_propio) if self._latido_propio else {}
            dadas = dict(self._ordenes_dadas)
        todos: dict[str, dict] = {}
        for id_, datos in foto.items():
            if id_ == self.id:
                continue
            # Con la misma vida en que lo observó la mirada que hizo la foto.
            vida = self._vida if corrida is None or datos.get("corrida") == corrida else self._otras
            quieto = vida.quieto_hace(id_, ahora)
            if retirado or datos.get("estado") == "terminado" or id_ in self._terminados:
                vivo = False
            else:
                # Nunca observado (no debería pasar: la foto es lo observado): vivo, ante la duda.
                vivo = quieto is None or vida.vivo(id_, ahora)
            # La que dio este equipo se ve en cuanto se da, sin esperar a que el
            # otro la lea y la lleve en su latido.
            orden = la_orden_que_manda(datos.get("orden"), dadas.get(id_))
            todos[id_] = {**datos, "orden": orden, "vivo": vivo, "quieto_hace": quieto}
        # El propio, con lo que ya sabe y aún no escribió: una orden recién
        # recibida se ve en la respuesta de quien la dio.
        en_curso = sorted(self.en_curso.values())
        todos[self.id] = {
            "id": self.id,
            "equipo": self.equipo,
            "version": self.version,
            "contador": self._contador,
            "escrito": None,
            **propio,
            "corrida": (self.corrida or {}).get("id"),
            "estado": self.estado,
            "en_curso": en_curso[:20],
            "en_curso_n": len(en_curso),
            "hechos": self.hechos,
            "unido": self.unido,
            "orden": self.orden,
            "vivo": not retirado,
            "quieto_hace": max(0.0, ahora - self._ultimo_latido),
        }
        return todos

    def parar(self) -> None:
        """Deja de latir y se retira: los demás no lo esperan.

        Primero un último latido «terminado» y después se borra: si el borrado
        no sale -- el archivo en uso por otro equipo --, lo que queda en el
        disco ya dice que terminó, y nadie lo espera.
        """
        if self._parar.is_set():
            return
        self._parar.set()
        for hilo in (self._hilo, self._hilo_de_la_mirada):
            if hilo is not None and hilo is not threading.current_thread():
                hilo.join(timeout=self.latido + 5)
        self.estado = "terminado"
        self._marcar_lo_pendiente()
        self._latir()
        self._borrar_lo_pendiente()
        try:
            _borrar(self._equipos / f"{self.id}.json")
        except OSError:
            logger.warning("no se pudo borrar el latido de %s; queda como «terminado»", self.id)
        # La orden de parar que cumplió, si la había: ya no la va a leer nadie.
        try:
            _borrar(self._orden_de(self.id))
        except OSError:
            logger.warning("no se pudo borrar la orden de parar de %s", self.id)
        self.anotar("se retiró")
        self._volcar_el_diario()

    # -- órdenes de parar (2026-11-26) --------------------------------------------
    #
    # El operador: «un monitoreo para ver los que están conectados y poder
    # desconectarlos». Una orden es un archivo en ``ordenes/<id>.json`` que deja
    # cualquier equipo y lee el destinatario con su mirada, cada latido: sin
    # servidor central, como todo lo demás.

    def _orden_de(self, id_: str) -> Path:
        return self.area / "ordenes" / f"{id_}.json"

    def orden_para(self, id_: str, modo: str, operador: str | None = None) -> dict:
        """La orden de parar que da este equipo a ``id_``, sin escribirla."""
        if modo not in MODOS_DE_PARAR:
            raise ValueError(f"modo de parar desconocido: {modo!r}")
        return {
            "para": id_,
            "modo": modo,
            "por": self.id,
            "equipo_que_ordena": self.equipo,
            "operador": operador,
            "cuando": _ahora_iso(),
        }

    def ordenar_parar(self, id_: str, modo: str, operador: str | None = None) -> dict:
        """Ordena parar a un equipo de la corrida: «calma» o «ya». Devuelve la orden que queda en pie.

        Al propio equipo, directo y sin archivo. A otro, en ``ordenes/<id>.json``,
        que su mirada lee en el siguiente latido: hay E/S, así que se llama desde
        un hilo. «ya» manda sobre «calma», y una orden repetida no hace nada:
        lo que ya estaba escrito se devuelve tal cual.

        Antes se mira su latido en el destino: si se retiró después de la
        última mirada, ``OrdenNoPermitida`` -- la orden no la leería nadie y
        quedaría en ``ordenes/`` para siempre, dada por puesta (2026-11-26) --.
        """
        orden = self.orden_para(id_, modo, operador)
        if id_ == self.id:
            self.anotar("ordenó parar", a=id_, modo=modo, operador=operador or "")
            self.recibir_orden(orden)
            return dict(self.orden or orden)
        if self._se_retiro(id_):
            raise OrdenNoPermitida(f"«{id_}» ya se retiró de la corrida: no queda nada que parar.")
        ruta = self._orden_de(id_)
        anterior = _leer(ruta)
        if anterior is None and modo != "ya" and _existe(ruta):
            # Hay una orden que no se deja leer (la red): una «calma» no pisa a
            # ciegas lo que puede ser un «ya». Quien la pide lo intenta otra vez.
            raise OSError(errno.EAGAIN, "la orden de parar que ya tenía ese equipo no se deja leer")
        if anterior is not None and anterior.get("para") == id_ and anterior.get("modo") in ("ya", modo):
            orden = anterior
        else:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            _escribir_entero(ruta, orden)
            self.anotar("ordenó parar", a=id_, modo=modo, operador=operador or "")
        with self._cerrojo_de_la_foto:
            self._ordenes_dadas[id_] = la_orden_que_manda(self._ordenes_dadas.get(id_), orden) or dict(orden)
        return orden

    def _se_retiro(self, id_: str) -> bool:
        """Si el equipo ``id_`` ya se retiró: su latido no está en el destino, o dice «terminado».

        Un latido que está y no se deja leer -- la red, o lo están
        reemplazando -- no dice nada: ``OSError``, y quien ordena lo intenta
        otra vez, como con la orden anterior que no se deja leer.
        """
        ruta = self._equipos / f"{id_}.json"
        latido = _leer(ruta)
        if latido is None:
            if _existe(ruta):
                raise OSError(errno.EAGAIN, "el latido de ese equipo no se deja leer")
            return True
        return latido.get("estado") == "terminado"

    def _mirar_las_ordenes(self) -> None:
        """La orden de parar que otro equipo dejó para éste, si la hay. Nunca tumba la mirada."""
        if (self.orden or {}).get("modo") == "ya":
            return  # nada manda sobre «ya»: no hay más que leer
        try:
            orden = _leer(self._orden_de(self.id))
            if orden is not None and orden.get("para") == self.id:
                self.recibir_orden(orden)
        except Exception:  # noqa: BLE001 - la mirada sigue aunque una orden no se entienda
            logger.warning("no se pudo leer la orden de parar de %s", self.id, exc_info=True)

    def recibir_orden(self, orden: Mapping[str, object]) -> bool:
        """Este equipo recibe una orden de parar. Dice si es nueva.

        Idempotente: la misma orden otra vez no hace nada, «ya» manda sobre
        «calma» y una «calma» después de «ya» se ignora. Avisa a la corrida
        (``al_recibir_orden``) fuera del cerrojo, y un fallo al avisar no tumba
        la mirada.
        """
        modo = orden.get("modo")
        if modo not in MODOS_DE_PARAR:
            return False
        with self._cerrojo_de_la_orden:
            actual = (self.orden or {}).get("modo")
            if actual in ("ya", modo):
                return False
            self.orden = dict(orden)
        self.anotar("recibió la orden de parar", modo=modo, de=orden.get("por"), operador=orden.get("operador") or "")
        avisar = self.al_recibir_orden
        if avisar is not None:
            try:
                avisar(dict(orden))
            except Exception:  # noqa: BLE001 - la orden queda anotada aunque la corrida no conteste
                logger.warning("no se pudo pasar la orden de parar a la corrida de %s", self.id, exc_info=True)
        return True

    # -- reparto ----------------------------------------------------------------

    def me_toca_primero(self, relativa: str) -> bool:
        """Si la carpeta de este PDF es de este equipo en la primera pasada."""
        return equipo_preferido(carpeta_de(relativa), self.equipos_vivos()) == self.id

    # -- reclamos ---------------------------------------------------------------

    def reclamar(self, relativa: str) -> Reclamo | Ajeno:
        """Toma el PDF para este equipo, o dice quién lo tiene y en qué estado.

        Un reclamo de un equipo caído se toma; uno «hecho» en esta corrida
        dice que el PDF ya está entregado por otro.
        """
        clave = clave_de(relativa)
        if clave in self.en_curso:
            # Ya lo tiene otro hilo de este mismo equipo: un PDF que entró dos
            # veces en la cola (el recorrido que vuelve a empezar tras una caída
            # del origen). Devolverle el mismo reclamo lo hacía leer y pagar dos
            # veces, y el que acababa primero soltaba el del otro (2026-11-25:
            # «la entrega anterior se rehízo» y «ya no tiene…» en el mismo NIC).
            return Ajeno(equipo=self.equipo, estado=AQUI)
        ruta = self._reclamo(clave)
        for _ in range(5):
            ficha = uuid4().hex
            datos = {
                "clave": clave,
                "relativa": relativa,
                "id": self.id,
                "equipo": self.equipo,
                "ficha": ficha,
                "estado": "en curso",
                "desde": _ahora_iso(),
            }
            if _crear_en_exclusiva(ruta, datos):
                self.en_curso[clave] = relativa
                self.anotar("reclamó", pdf=relativa)
                return Reclamo(clave=clave, relativa=relativa, ficha=ficha)
            actual = _leer(ruta)
            if actual is None:
                if not _existe(ruta):
                    continue  # se soltó entretanto: otra vez
                dueno = f"ilegible:{clave}"
                if self.vivo(dueno):
                    return Ajeno(equipo="?", estado="en curso")
                self._quitar_huerfano(ruta, {"ficha": None})
                continue
            if actual.get("estado") == "hecho":
                return Ajeno(equipo=str(actual.get("equipo") or "?"), estado="hecho")
            if actual.get("id") == self.id:
                # Es de este mismo equipo (un intento anterior que no se soltó).
                self.en_curso[clave] = relativa
                return Reclamo(clave=clave, relativa=relativa, ficha=str(actual.get("ficha")))
            if self.vivo(str(actual.get("id"))):
                return Ajeno(equipo=str(actual.get("equipo") or "?"), estado="en curso")
            self.anotar("toma de un equipo caído", pdf=relativa, de=actual.get("id"))
            self._quitar_huerfano(ruta, actual)
        return Ajeno(equipo="?", estado="en curso")

    def estado_de(self, relativa: str) -> Ajeno | None:
        """Quién tiene el PDF ahora, sin tomarlo: ``None`` si está libre (o su dueño cayó)."""
        clave = clave_de(relativa)
        actual = _leer(self._reclamo(clave))
        if actual is None:
            fallo = self.fallo_de(relativa)
            return fallo
        if actual.get("estado") == "hecho":
            return Ajeno(equipo=str(actual.get("equipo") or "?"), estado="hecho")
        if actual.get("id") != self.id and not self.vivo(str(actual.get("id"))):
            return None
        if actual.get("id") == self.id and clave not in self.en_curso:
            # Uno propio que no lleva ningún hilo de este equipo -- no se pudo
            # soltar con el destino caído --: está libre, y lo vuelve a tomar
            # éste. Si no, se esperaba a sí mismo y la corrida no cerraba.
            return None
        return Ajeno(equipo=str(actual.get("equipo") or "?"), estado="en curso")

    def sigue_siendo_mio(self, reclamo: Reclamo) -> bool:
        actual = _leer(self._reclamo(reclamo.clave))
        return actual is not None and actual.get("ficha") == reclamo.ficha

    def por_que_no_vale(self) -> str | None:
        """Si esta corrida ya no vale para este equipo, por qué; ``None`` si sigue valiendo.

        Se lee del disco y no del latido: un equipo colgado no se entera por su
        hilo de latido -- también estaba colgado -- de que los demás empezaron
        otra corrida o cerraron ésta (2026-11-25: el colgado que volvía
        entregaba encima, y salían «(2)»).
        """
        if self.corrida is None:
            return "este equipo no está en ninguna corrida"
        actual = _leer(self.area / "corrida.json")
        if actual is None:
            return None  # ilegible un momento: decide la ficha del reclamo
        if actual.get("id") != self.corrida.get("id"):
            self.desplazado = True
            return "otro equipo empezó una corrida nueva sobre este destino"
        if actual.get("cerrada"):
            self.desplazado = True
            return "la corrida ya se cerró"
        return None

    def vigente(self) -> bool:
        return not self.desplazado and self.por_que_no_vale() is None and self.puede_entregar()

    def cerrar_la_corrida(self) -> None:
        """La deja cerrada en el disco: un equipo que vuelva tarde ya no entrega ni reescribe nada."""
        try:
            actual = _leer(self.area / "corrida.json") or {}
            if actual.get("id") == (self.corrida or {}).get("id"):
                _escribir_entero(self.area / "corrida.json", {**actual, "cerrada": _ahora_iso(), "cerrada_por": self.id})
        except OSError:
            logger.warning("no se pudo marcar cerrada la corrida de %s", self.raiz, exc_info=True)
        self.anotar("cerró la corrida")

    def confirmar(self, reclamo: Reclamo | None) -> None:
        """La barrera antes de lo que no tiene vuelta atrás: entregar, dejar la constancia."""
        if reclamo is None:
            return
        # El último latido escrito antes de cualquier espera: lo que miden los demás.
        antes = self._ultimo_latido
        motivo = self.por_que_no_vale()
        if motivo is not None or self.desplazado:
            raise ReclamoPerdido(motivo or "otro equipo empezó una corrida nueva sobre este destino")
        if not self.puede_entregar() and self.sigue_siendo_mio(reclamo):
            # El latido propio va atrasado -- el servidor lento un momento --,
            # pero el PDF sigue siendo de este equipo: se espera a que vuelva a
            # escribirse en vez de tirar el OCR ya pagado. Después se relee la
            # ficha: si en ese rato otro lo tomó, no se entrega.
            self._esperar_el_latido_propio(antes)
        if not self.puede_entregar() or self._ultimo_latido - antes >= self._hueco_maximo():
            # Un hueco de latido tan largo que los demás pudieron darlo por
            # caído y quitarle el turno de la carpeta -- aunque el reclamo siga
            # siendo suyo --: no escribe nada.
            raise ReclamoPerdido(
                "este equipo lleva demasiado sin poder escribir en el destino; otro puede haberlo tomado"
            )
        if not self.sigue_siendo_mio(reclamo):
            raise ReclamoPerdido(f"otro equipo tomó «{reclamo.relativa}» mientras se procesaba aquí")

    def _hueco_maximo(self) -> float:
        """El hueco de latido propio a partir del cual los demás pueden haberlo dado por caído, con margen."""
        return self._vida.caido - 2 * self.latido

    def _esperar_el_latido_propio(self, antes: float) -> None:
        """Hasta que vuelva el latido propio, sin pasar nunca del plazo en que los demás lo darían por caído."""
        limite = time.monotonic() + self.espera_del_latido
        while (
            not self.puede_entregar()
            and time.monotonic() < limite
            and self._reloj() - antes < self._hueco_maximo()
            and not self._parar.is_set()
        ):
            self._parar.wait(min(0.5, max(0.01, self.latido / 2)))

    def terminar(self, reclamo: Reclamo, *, trabajo: str | None = None) -> None:
        """El PDF quedó entregado con su constancia: su reclamo dice «hecho» para todos.

        Con el trabajo que lo entregó: el equipo que cierra arma con ellos una
        sola auditoría de la corrida, con lo de todos los equipos.
        """
        self.en_curso.pop(reclamo.clave, None)
        self.hechos += 1
        if not self._marcar_hecho(reclamo, trabajo):
            # El destino no contestó: se reintenta con la mirada. Si no, el
            # reclamo seguía «en curso» de un equipo vivo, los demás lo esperaban
            # y la corrida no cerraba.
            with self._mutex:
                self._hechos_pendientes.append((reclamo, trabajo))
        # Con su trabajo: el que cierra arma la auditoría de la corrida con los
        # diarios de todos, sin leer un reclamo por PDF (``lo_hecho_en_la_corrida``).
        self.anotar("entregó", pdf=reclamo.relativa, trabajo=trabajo or "")

    def _marcar_hecho(self, reclamo: Reclamo, trabajo: str | None) -> bool:
        """Deja el reclamo «hecho» si sigue siendo de este equipo. ``False`` si el destino no lo dejó."""
        ruta = self._reclamo(reclamo.clave)
        try:
            # Una lectura y no dos: la ficha y los datos salen de la misma.
            datos = _leer(ruta)
            if datos is None:
                # No está o no se dejó leer: si sigue ahí, se reintenta.
                return not _existe(ruta)
            if datos.get("ficha") != reclamo.ficha:
                return True
            _escribir_entero(ruta, {**datos, "estado": "hecho", "hecho": _ahora_iso(), "trabajo": trabajo})
            _borrar(self._fallido(reclamo.clave))
            return True
        except OSError:
            logger.warning("no se pudo marcar como hecho %s", reclamo.relativa, exc_info=True)
            return False

    def _marcar_lo_pendiente(self) -> None:
        """Los «hecho» que el destino no dejó escribir, otra vez."""
        with self._mutex:
            pendientes, self._hechos_pendientes = self._hechos_pendientes, []
        quedan = [(reclamo, trabajo) for reclamo, trabajo in pendientes if not self._marcar_hecho(reclamo, trabajo)]
        if quedan:
            with self._mutex:
                self._hechos_pendientes[:0] = quedan

    def soltar(self, reclamo: Reclamo, *, error: str | None = None, reintentable: bool = False) -> None:
        """Suelta el PDF sin entregarlo; si falló, deja dicho por qué para los demás."""
        self.en_curso.pop(reclamo.clave, None)
        try:
            if error is not None:
                anterior = _leer(self._fallido(reclamo.clave)) or {}
                _escribir_entero(
                    self._fallido(reclamo.clave),
                    {
                        "relativa": reclamo.relativa,
                        "id": self.id,
                        "equipo": self.equipo,
                        "error": error,
                        "reintentable": reintentable,
                        "intentos": int(anterior.get("intentos") or 0) + 1,
                        "cuando": _ahora_iso(),
                    },
                )
            if self.sigue_siendo_mio(reclamo):
                _borrar(self._reclamo(reclamo.clave))
        except OSError:
            logger.warning("no se pudo soltar %s", reclamo.relativa, exc_info=True)
            self._por_borrar.append(self._reclamo(reclamo.clave))
        self.anotar("soltó", pdf=reclamo.relativa, error=error or "")

    def fallo_de(self, relativa: str) -> Ajeno | None:
        """Si el PDF falló en otro equipo de esta corrida."""
        datos = _leer(self._fallido(clave_de(relativa)))
        if datos is None or datos.get("id") == self.id:
            return None
        return Ajeno(equipo=str(datos.get("equipo") or "?"), estado="falló", error=str(datos.get("error") or ""))

    def _quitar_huerfano(self, ruta: Path, visto: Mapping[str, object]) -> None:
        """Quita el reclamo (o cerrojo) de un equipo caído, sin quitar el de quien lo tomó antes.

        Con una marca exclusiva por ficha: de varios equipos que lo ven caído a
        la vez, sólo uno lo quita, y sólo si sigue siendo el que se vio.
        """
        marca = ruta.with_name(f"{ruta.name}.toma-{visto.get('ficha') or 'ilegible'}")
        if not _crear_en_exclusiva(marca, {"id": self.id, "cuando": _ahora_iso()}):
            return
        try:
            actual = _leer(ruta)
            ilegible_y_sigue = actual is None and visto.get("ficha") is None and _existe(ruta)
            el_mismo = actual is not None and actual.get("ficha") == visto.get("ficha")
            if ilegible_y_sigue or el_mismo:
                _borrar(ruta)
        finally:
            with contextlib.suppress(OSError):
                _borrar(marca)

    # -- roles ------------------------------------------------------------------

    def tomar_rol(self, nombre: str) -> bool:
        """Un papel que sólo hace un equipo por corrida (cerrar, auditar). ``True`` si es de este."""
        if self.por_que_no_vale() is not None:
            return False
        ruta = self._de_la_corrida / "roles" / f"{nombre}.json"
        for _ in range(3):
            if _crear_en_exclusiva(ruta, {"id": self.id, "equipo": self.equipo, "ficha": uuid4().hex}):
                self.anotar("tomó el rol", rol=nombre)
                return True
            actual = _leer(ruta)
            if actual is None:
                continue
            if actual.get("id") == self.id:
                return True
            if self.vivo(str(actual.get("id"))):
                return False
            self._quitar_huerfano(ruta, actual)
        return False

    def lo_hecho_en_la_corrida(self) -> tuple[list[str], dict[str, str]]:
        """Los trabajos de todos los PDF entregados en esta corrida, y los que fallaron (ruta → motivo).

        De los diarios de los equipos -- uno por arranque, unos pocos archivos --
        y no de un reclamo por PDF: con 29 000 reclamos eran unas 116 000 idas y
        vueltas a la red en un solo hilo, una o dos horas al cerrar (2026-11-25).
        El listado de los reclamos (una sola petición) dice cuáles hay; sólo se
        leen, varios a la vez, los que ningún diario cuenta -- un equipo que cayó
        antes de volcar el suyo --.
        """
        self._volcar_el_diario()
        trabajo_de = self._entregados_segun_los_diarios()
        reclamos = self._de_la_corrida / "reclamos"
        try:
            claves = sorted(e.name[: -len(".json")] for e in os.scandir(reclamos) if e.name.endswith(".json"))
        except OSError:
            claves = None
        if claves is not None:
            existen = set(claves)
            trabajo_de = {clave: trabajo for clave, trabajo in trabajo_de.items() if clave in existen}
            faltan = [clave for clave in claves if clave not in trabajo_de]
            if faltan:
                with ThreadPoolExecutor(max_workers=min(8, len(faltan)), thread_name_prefix="lo-hecho") as hilos:
                    leidos = list(hilos.map(lambda clave: _leer(reclamos / f"{clave}.json"), faltan))
                for clave, datos in zip(faltan, leidos, strict=True):
                    if datos and datos.get("estado") == "hecho" and datos.get("trabajo"):
                        trabajo_de[clave] = str(datos["trabajo"])
        trabajos = [trabajo_de[clave] for clave in sorted(trabajo_de)]
        fallidos: dict[str, str] = {}
        for ruta in sorted((self._de_la_corrida / "fallidos").glob("*.json")):
            datos = _leer(ruta)
            if datos and datos.get("relativa"):
                fallidos[str(datos["relativa"])] = f"{datos.get('equipo')}: {datos.get('error')}"
        return trabajos, fallidos

    def los_demas_terminaron(self) -> bool:
        """Si ningún otro equipo vivo de esta corrida sigue procesando."""
        corrida = (self.corrida or {}).get("id")
        latidos = self._mirar_a_los_demas()
        if latidos is None:
            # Sin poder mirar no se sabe: se espera (cerrar con alguien todavía
            # entregando dejaba lo suyo fuera de los generales y la auditoría).
            return False
        for id_, datos in latidos.items():
            if datos.get("estado") == "terminado":
                # El que se retiró y no pudo borrar su latido: se limpia aquí,
                # con la orden de parar que cumplió.
                with contextlib.suppress(OSError):
                    _borrar(self._equipos / f"{id_}.json")
                    _borrar(self._orden_de(id_))
                continue
            if datos.get("corrida") == corrida and datos.get("estado") != "terminado" and self.vivo(id_):
                return False
        # Un equipo de esta corrida cuyo latido está en la carpeta pero no se
        # dejó leer un momento sigue contando. El que se retiró lo borró: ése no.
        ahora = self._reloj()
        for id_ in getattr(self, "_ilegibles", set()):
            if id_ not in self._terminados and self._vida.vivo(id_, ahora):
                return False
        return True

    # -- cerrojos de carpeta ------------------------------------------------------

    @contextlib.contextmanager
    def cerrojo(
        self,
        nombre: str,
        *,
        espera_maxima: float = ESPERA_MAXIMA_DEL_CERROJO,
        cancelado: Callable[[], bool] | None = None,
    ) -> Iterator[None]:
        """El turno de ``nombre`` -- una carpeta del destino -- entre todos los equipos.

        Reentrante en este proceso: quien ya lo tiene lo vuelve a tomar sin
        esperar. El archivo se toma una vez y se suelta al salir del último.
        Si el que lo tiene cayó, se le quita.
        """
        clave = clave_de(nombre)
        with self._mutex:
            local = self._cerrojos.setdefault(clave, _CerrojoLocal())
        local.rlock.acquire()
        try:
            ruta = self.area / "cerrojos" / f"{clave}.lock"
            if local.cuenta == 0:
                local.ficha = self._tomar_el_cerrojo(ruta, nombre, espera_maxima, cancelado)
            local.cuenta += 1
            try:
                yield
            finally:
                local.cuenta -= 1
                if local.cuenta == 0:
                    self._soltar_el_cerrojo(ruta, local.ficha)
        finally:
            local.rlock.release()

    def _tomar_el_cerrojo(
        self, ruta: Path, nombre: str, espera_maxima: float, cancelado: Callable[[], bool] | None
    ) -> str:
        desde = self._reloj()
        pausa = 0.05
        sin_red_desde: float | None = None
        espera_de_la_red = 1.0
        while True:
            ficha = uuid4().hex
            try:
                creado = _crear_en_exclusiva(
                    ruta, {"id": self.id, "equipo": self.equipo, "ficha": ficha, "nombre": nombre}
                )
            except OSError as error:
                # El servidor del destino no contesta un momento: se espera a que
                # vuelva en vez de dar por fallido un PDF ya leído y pagado.
                ahora = time.monotonic()
                sin_red_desde = sin_red_desde if sin_red_desde is not None else ahora
                if not es_de_la_red(error) or ahora - sin_red_desde > ESPERA_DE_LA_RED:
                    raise
                if cancelado is not None and cancelado():
                    raise CerrojoOcupado(f"se canceló esperando el turno de «{nombre}»") from error
                logger.warning("el destino no contesta al tomar el turno de %s: %s; se reintenta", nombre, error)
                self._dormir(espera_de_la_red)
                espera_de_la_red = min(espera_de_la_red * 2, 15.0)
                continue
            sin_red_desde, espera_de_la_red = None, 1.0
            if creado:
                return ficha
            actual = _leer(ruta)
            if actual is not None and actual.get("id") == self.id:
                # Uno propio que no se pudo borrar al soltarlo: vuelve a ser de este.
                return str(actual.get("ficha"))
            dueno = str(actual.get("id")) if actual else f"ilegible:{ruta.name}"
            if (actual is not None or _existe(ruta)) and not self.vivo(dueno):
                self.anotar("quitó el cerrojo de un equipo caído", cerrojo=nombre, de=dueno)
                self._quitar_huerfano(ruta, actual or {"ficha": None})
                continue
            if cancelado is not None and cancelado():
                raise CerrojoOcupado(f"se canceló esperando el turno de «{nombre}»")
            if self._reloj() - desde > espera_maxima:
                quien = (actual or {}).get("equipo") or "otro equipo"
                raise CerrojoOcupado(f"«{nombre}» sigue ocupado por {quien} tras {espera_maxima / 60:.0f} min")
            self._dormir(pausa)
            pausa = min(pausa * 2, 1.0)

    def _soltar_el_cerrojo(self, ruta: Path, ficha: str) -> None:
        try:
            actual = _leer(ruta)
            if actual is not None and actual.get("ficha") == ficha:
                _borrar(ruta)
            elif actual is None and _existe(ruta):
                # No se dejó leer (la red): se reintenta con la mirada, o quedaba
                # a nombre de este equipo vivo y los demás lo esperaban 30 min.
                self._por_borrar.append(ruta)
        except OSError:
            # Se reintenta con el latido: si no, los demás esperarían a un vivo
            # que ya no lo usa.
            logger.warning("no se pudo soltar el cerrojo %s", ruta.name, exc_info=True)
            self._por_borrar.append(ruta)

    def _borrar_lo_pendiente(self) -> None:
        quedan = []
        for ruta in list(self._por_borrar):
            if self._lo_tiene_tomado(ruta):
                # Este equipo lo volvió a tomar entretanto: ya no se borra.
                continue
            try:
                actual = _leer(ruta)
                if actual is None or actual.get("id") == self.id:
                    _borrar(ruta)
            except OSError:
                quedan.append(ruta)
        self._por_borrar = quedan

    def _lo_tiene_tomado(self, ruta: Path) -> bool:
        """Si un cerrojo o un reclamo pendiente de borrar lo tiene ahora este proceso."""
        if ruta.parent.name == "cerrojos":
            local = self._cerrojos.get(ruta.stem)
            return local is not None and local.cuenta > 0
        if ruta.parent.name == "reclamos":
            return ruta.stem in self.en_curso
        return False

    # -- el diario ----------------------------------------------------------------

    def anotar(self, que: str, **datos: object) -> None:
        """Una línea en el diario de este equipo: qué hizo y cuándo. Que falle no para nada.

        Se guarda en memoria y se vuelca por tandas (``_volcar_el_diario``):
        escribirla en la red en el momento eran dos idas y vueltas más por PDF.
        """
        try:
            linea = json.dumps({"cuando": _ahora_iso(), "equipo": self.id, "que": que, **datos}, ensure_ascii=False)
        except (TypeError, ValueError):
            return
        with self._cerrojo_del_diario:
            self._diario_pendiente.append(linea)
            if len(self._diario_pendiente) > LINEAS_DEL_DIARIO_EN_MEMORIA:
                del self._diario_pendiente[: -LINEAS_DEL_DIARIO_EN_MEMORIA]

    def _volcar_el_diario(self) -> None:
        """Lo anotado desde la última vez, al diario del destino de una sola escritura."""
        with self._volcando:
            with self._cerrojo_del_diario:
                lineas, self._diario_pendiente = self._diario_pendiente, []
            if not lineas:
                return
            try:
                with open(self.area / "diario" / f"{self.id}.jsonl", "a", encoding="utf-8") as diario:
                    diario.write("".join(f"{linea}\n" for linea in lineas))
            except OSError:
                # Se intenta en la próxima vuelta, con lo nuevo detrás.
                with self._cerrojo_del_diario:
                    self._diario_pendiente[:0] = lineas
                logger.debug("no se pudo volcar el diario de %s", self.id, exc_info=True)

    def _entregados_segun_los_diarios(self) -> dict[str, str]:
        """La clave y el trabajo de cada PDF que algún equipo dice haber entregado en esta corrida."""
        corrida = (self.corrida or {}).get("id")
        trabajo_de: dict[str, str] = {}
        #: Las que dos líneas dan con trabajos distintos (un PDF rehecho en la
        #: misma corrida): las decide su reclamo, que lleva el último.
        dudosas: set[str] = set()
        try:
            diarios = sorted((self.area / "diario").glob("*.jsonl"))
        except OSError:
            return trabajo_de
        for diario in diarios:
            try:
                texto = diario.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            de_esta = False
            for linea in texto.splitlines():
                try:
                    datos = json.loads(linea)
                except ValueError:
                    continue
                if not isinstance(datos, dict):
                    continue
                if datos.get("que") == "se unió":
                    # Un diario por arranque, y cada arranque es de una corrida.
                    de_esta = datos.get("corrida") == corrida
                elif de_esta and datos.get("que") == "entregó" and datos.get("pdf") and datos.get("trabajo"):
                    clave, trabajo = clave_de(str(datos["pdf"])), str(datos["trabajo"])
                    if trabajo_de.setdefault(clave, trabajo) != trabajo:
                        dudosas.add(clave)
        for clave in dudosas:
            trabajo_de.pop(clave, None)
        return trabajo_de
