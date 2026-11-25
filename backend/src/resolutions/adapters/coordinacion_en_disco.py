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
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from ..application.coordinacion import (
    SEGUNDOS_DEL_LATIDO,
    SEGUNDOS_PARA_DARLO_POR_CAIDO,
    SEGUNDOS_SIN_LATIDO_PROPIO,
    Vida,
    carpeta_de,
    clave_de,
    equipo_preferido,
    opciones_distintas,
)

logger = logging.getLogger(__name__)

#: El área de coordinación, dentro de la raíz del destino. Empieza por punto:
#: los recorridos del destino la saltan (``es_del_bot``).
AREA = ".botpdf-coordinacion"

#: Cuánto se espera, como mucho, el turno de una carpeta NIC que tiene otro
#: equipo vivo: una entrega grande por la red tarda minutos, no horas.
ESPERA_MAXIMA_DEL_CERROJO = 30 * 60.0

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
    estado: str  # «en curso» | «hecho» | «falló»
    error: str = ""


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
    """Crea el archivo sólo si no existe. ``False`` si otro ya lo tenía."""
    try:
        fd = os.open(ruta, _EXCLUSIVO)
    except FileExistsError:
        return False
    try:
        os.write(fd, json.dumps(dict(datos), ensure_ascii=False).encode("utf-8"))
        with contextlib.suppress(OSError):
            os.fsync(fd)
    finally:
        os.close(fd)
    return True


#: Las esperas cuando el archivo está en uso: en Windows y en un recurso SMB no
#: se puede reemplazar ni borrar un archivo mientras otro equipo lo está
#: leyendo, y con varios equipos mirándose cada diez segundos pasa. Sin
#: reintentar, el latido de un equipo retirado se quedaba en el disco diciendo
#: «procesando» y el que cierra lo esperaba para siempre (2026-11-25).
ESPERAS_SI_ESTA_EN_USO = (0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 1.6)


def reintentar_si_esta_en_uso(hacer: Callable[[], object]) -> object:
    """Hace ``hacer``; si el archivo está en uso (``PermissionError``), espera y lo intenta otra vez."""
    for espera in (*ESPERAS_SI_ESTA_EN_USO, None):
        try:
            return hacer()
        except PermissionError:
            if espera is None:
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
        self._reloj = reloj
        self._dormir = dormir
        self._vida = Vida(caido=caido)
        self._mutex = threading.Lock()
        self._cerrojos: dict[str, _CerrojoLocal] = {}
        self._por_borrar: list[Path] = []
        self._contador = 0
        #: Los equipos que dijeron «terminado» en su último latido.
        self._terminados: set[str] = set()
        self._ultimo_latido = reloj()
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self.corrida: dict | None = None
        #: Lo que el latido cuenta a los demás de este equipo.
        self.estado = "uniéndose"
        self.en_curso: dict[str, str] = {}
        self.hechos = 0
        #: Otro equipo empezó una corrida nueva sobre este destino: esta ya no vale.
        self.desplazado = False

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
        for carpeta in ("equipos", "cerrojos", "diario", "corridas"):
            (self.area / carpeta).mkdir(parents=True, exist_ok=True)
        self.sondear()
        self._latir()
        self._arrancar_el_latido()
        try:
            with self.cerrojo("corrida", espera_maxima=5 * 60.0):
                corrida = _leer(self.area / "corrida.json")
                antes = {
                    id_: datos for id_, datos in self._latidos_de_otros().items() if datos.get("estado") != "terminado"
                }
                vivos: dict[str, dict] = {}
                # Se miran varias veces durante dos latidos y medio: con que su
                # contador cambie una vez, está vivo. Uno lento por la red no se
                # da por muerto (y no se le quita la corrida) por un latido tarde.
                vueltas = 5
                for _ in range(vueltas if antes else 0):
                    self._dormir(self.latido * 2.5 / vueltas + 0.2)
                    for id_, datos in self._latidos_de_otros().items():
                        if id_ in antes and datos.get("contador") != antes[id_].get("contador"):
                            vivos[id_] = datos
                    if len(vivos) == len(antes):
                        break
                # Una corrida cerrada no se reabre: lo que quede latiendo en ella
                # es un equipo que volvió tarde, y ya no entrega (``por_que_no_vale``).
                abierta = bool(corrida) and not corrida.get("cerrada")
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

    def _latiendo(self) -> None:
        while not self._parar.wait(self.latido):
            self._latir()
            self._mirar_a_los_demas()
            self._borrar_lo_pendiente()
            self._mirar_la_corrida()

    def _latir(self) -> None:
        self._contador += 1
        datos = {
            "id": self.id,
            "equipo": self.equipo,
            "version": self.version,
            "corrida": (self.corrida or {}).get("id"),
            "contador": self._contador,
            "estado": self.estado,
            "en_curso": sorted(self.en_curso.values())[:20],
            "hechos": self.hechos,
            "escrito": _ahora_iso(),
        }
        try:
            _escribir_entero(self._equipos / f"{self.id}.json", datos)
            self._ultimo_latido = self._reloj()
        except OSError:
            logger.warning("no se pudo escribir el latido de %s", self.id, exc_info=True)

    def _latidos_de_otros(self) -> dict[str, dict]:
        latidos: dict[str, dict] = {}
        for ruta in self._equipos.glob("*.json"):
            if ruta.stem == self.id:
                continue
            datos = _leer(ruta)
            if datos is not None:
                latidos[ruta.stem] = datos
        return latidos

    def _mirar_a_los_demas(self) -> dict[str, dict]:
        ahora = self._reloj()
        try:
            latidos = self._latidos_de_otros()
        except OSError:
            self._vida.mirada(ahora, bien=False)
            return {}
        self._vida.mirada(ahora, bien=True)
        corrida = (self.corrida or {}).get("id")
        for id_, datos in latidos.items():
            # El que se retiró ya no tiene nada: lo que haya dejado está libre.
            if datos.get("estado") == "terminado":
                self._terminados.add(id_)
            # Sólo los de esta corrida: el latido que dejó un equipo que se
            # cayó en una corrida anterior no reparte nada.
            if corrida is None or datos.get("corrida") == corrida:
                self._vida.observar(id_, datos.get("contador"), ahora)
        return latidos

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
        """Los latidos de todos los equipos del destino, para la pantalla."""
        todos = self._latidos_de_otros()
        datos = _leer(self._equipos / f"{self.id}.json")
        if datos:
            todos[self.id] = datos
        for id_, latido in todos.items():
            latido["vivo"] = self.vivo(id_)
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
        if self._hilo is not None and self._hilo is not threading.current_thread():
            self._hilo.join(timeout=self.latido + 5)
        self.estado = "terminado"
        self._latir()
        self._borrar_lo_pendiente()
        try:
            _borrar(self._equipos / f"{self.id}.json")
        except OSError:
            logger.warning("no se pudo borrar el latido de %s; queda como «terminado»", self.id)
        self.anotar("se retiró")

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
                if not ruta.exists():
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
        motivo = self.por_que_no_vale()
        if motivo is not None or self.desplazado:
            raise ReclamoPerdido(motivo or "otro equipo empezó una corrida nueva sobre este destino")
        if not self.puede_entregar():
            raise ReclamoPerdido(
                "este equipo lleva demasiado sin poder escribir en el destino; otro puede haberlo tomado"
            )
        if not self.sigue_siendo_mio(reclamo):
            raise ReclamoPerdido(f"otro equipo tomó «{reclamo.relativa}» mientras se procesaba aquí")

    def terminar(self, reclamo: Reclamo, *, trabajo: str | None = None) -> None:
        """El PDF quedó entregado con su constancia: su reclamo dice «hecho» para todos.

        Con el trabajo que lo entregó: el equipo que cierra arma con ellos una
        sola auditoría de la corrida, con lo de todos los equipos.
        """
        self.en_curso.pop(reclamo.clave, None)
        self.hechos += 1
        try:
            if not self.sigue_siendo_mio(reclamo):
                return
            datos = _leer(self._reclamo(reclamo.clave)) or {}
            _escribir_entero(
                self._reclamo(reclamo.clave),
                {**datos, "estado": "hecho", "hecho": _ahora_iso(), "trabajo": trabajo},
            )
            _borrar(self._fallido(reclamo.clave))
        except OSError:
            logger.warning("no se pudo marcar como hecho %s", reclamo.relativa, exc_info=True)
        self.anotar("entregó", pdf=reclamo.relativa)

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
            ilegible_y_sigue = actual is None and visto.get("ficha") is None and ruta.exists()
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
        """Los trabajos de todos los PDF entregados en esta corrida, y los que fallaron (ruta → motivo)."""
        trabajos: list[str] = []
        fallidos: dict[str, str] = {}
        for ruta in sorted((self._de_la_corrida / "reclamos").glob("*.json")):
            datos = _leer(ruta)
            if datos and datos.get("estado") == "hecho" and datos.get("trabajo"):
                trabajos.append(str(datos["trabajo"]))
        for ruta in sorted((self._de_la_corrida / "fallidos").glob("*.json")):
            datos = _leer(ruta)
            if datos and datos.get("relativa"):
                fallidos[str(datos["relativa"])] = f"{datos.get('equipo')}: {datos.get('error')}"
        return trabajos, fallidos

    def los_demas_terminaron(self) -> bool:
        """Si ningún otro equipo vivo de esta corrida sigue procesando."""
        corrida = (self.corrida or {}).get("id")
        for id_, datos in self._mirar_a_los_demas().items():
            if datos.get("estado") == "terminado":
                # El que se retiró y no pudo borrar su latido: se limpia aquí.
                with contextlib.suppress(OSError):
                    _borrar(self._equipos / f"{id_}.json")
                continue
            if datos.get("corrida") == corrida and datos.get("estado") != "terminado" and self.vivo(id_):
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
        while True:
            ficha = uuid4().hex
            if _crear_en_exclusiva(ruta, {"id": self.id, "equipo": self.equipo, "ficha": ficha, "nombre": nombre}):
                return ficha
            actual = _leer(ruta)
            if actual is not None and actual.get("id") == self.id:
                # Uno propio que no se pudo borrar al soltarlo: vuelve a ser de este.
                return str(actual.get("ficha"))
            dueno = str(actual.get("id")) if actual else f"ilegible:{ruta.name}"
            if (actual is not None or ruta.exists()) and not self.vivo(dueno):
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
        except OSError:
            # Se reintenta con el latido: si no, los demás esperarían a un vivo
            # que ya no lo usa.
            logger.warning("no se pudo soltar el cerrojo %s", ruta.name, exc_info=True)
            self._por_borrar.append(ruta)

    def _borrar_lo_pendiente(self) -> None:
        quedan = []
        for ruta in self._por_borrar:
            try:
                actual = _leer(ruta)
                if actual is None or actual.get("id") == self.id:
                    _borrar(ruta)
            except OSError:
                quedan.append(ruta)
        self._por_borrar = quedan

    # -- el diario ----------------------------------------------------------------

    def anotar(self, que: str, **datos: object) -> None:
        """Una línea en el diario de este equipo: qué hizo y cuándo. Que falle no para nada."""
        try:
            linea = json.dumps({"cuando": _ahora_iso(), "equipo": self.id, "que": que, **datos}, ensure_ascii=False)
            with open(self.area / "diario" / f"{self.id}.jsonl", "a", encoding="utf-8") as diario:
                diario.write(linea + "\n")
        except OSError:
            pass
