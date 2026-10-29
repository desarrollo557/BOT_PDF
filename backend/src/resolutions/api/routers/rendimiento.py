"""El rendimiento del equipo y del bot, en vivo, para la pantalla.

Lo pidió el operador el 2026-10-29: «en el espacio en blanco, el rendimiento del
programa y del PC en tiempo real, para tener todo muy bien controlado». Ese
mismo día el otro equipo se ahogó con diez PDF de 200 MB a la vez y sólo se
supo por los registros: con esto se ve en la pantalla, mientras pasa.

En Docker el equipo es lo que ve el contenedor -- la máquina virtual de Docker
Desktop, que reparte los núcleos y la memoria del PC --. Se lee de ``/proc``,
sin dependencias; donde no hay ``/proc`` (el servicio en Windows sin Docker),
lo que no se puede medir va como ``None`` y la pantalla dice «—».
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import APIRouter

from ..contexto import Ctx
from ..jobs import JobState

router = APIRouter()

#: Cuántos segundos se miran para el ritmo de páginas y documentos.
VENTANA = 60.0

_cerrojo = threading.Lock()
#: (instante, páginas leídas, documentos terminados) de cada consulta reciente.
_muestras: deque[tuple[float, int, int]] = deque(maxlen=240)
#: Los contadores de CPU de la consulta anterior: (total, ocioso).
_cpu_antes: tuple[int, int] | None = None


def _cpu() -> float | None:
    """El uso de CPU del equipo desde la consulta anterior, en %."""
    global _cpu_antes
    try:
        campos = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()[1:]
    except (OSError, IndexError):
        return None
    valores = [int(v) for v in campos]
    ocioso = valores[3] + (valores[4] if len(valores) > 4 else 0)
    total = sum(valores)
    with _cerrojo:
        antes, _cpu_antes = _cpu_antes, (total, ocioso)
    if antes is None or total <= antes[0]:
        return None
    return round(100 * (1 - (ocioso - antes[1]) / (total - antes[0])), 1)


def _memoria() -> tuple[int, int] | None:
    """(usada, total) en bytes, de ``/proc/meminfo``."""
    try:
        lineas = Path("/proc/meminfo").read_text(encoding="ascii").splitlines()
    except OSError:
        return None
    datos = {}
    for linea in lineas:
        nombre, _, resto = linea.partition(":")
        partes = resto.split()
        if partes:
            datos[nombre] = int(partes[0]) * 1024
    if "MemTotal" not in datos or "MemAvailable" not in datos:
        return None
    return datos["MemTotal"] - datos["MemAvailable"], datos["MemTotal"]


def _memoria_del_bot() -> int | None:
    """Lo que ocupan en memoria los procesos del servicio y sus lectores, en bytes.

    La parte proporcional de cada uno (``Pss``): los once lectores comparten
    librerías, y sumando la memoria residente de cada uno se contaban once
    veces -- 4,4 GB con 5 GB usados en todo el equipo --.
    """
    raiz = Path("/proc")
    if not raiz.is_dir():
        return None
    total = 0
    for proceso in raiz.iterdir():
        if not proceso.name.isdigit():
            continue
        try:
            total += _proporcional(proceso)
        except OSError:
            continue  # el proceso terminó mientras se miraba
    return total


def _proporcional(proceso: Path) -> int:
    """``Pss`` de ``smaps_rollup``; si el núcleo no lo da, ``VmRSS`` de ``status``."""
    for archivo, campo in (("smaps_rollup", "Pss:"), ("status", "VmRSS:")):
        try:
            texto = (proceso / archivo).read_text(encoding="ascii", errors="replace")
        except FileNotFoundError:
            continue
        for linea in texto.splitlines():
            if linea.startswith(campo):
                return int(linea.split()[1]) * 1024
    return 0


def _carga() -> float | None:
    try:
        return round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        return None


def _ritmo(paginas: int, terminados: int) -> tuple[float | None, float | None]:
    """Páginas y documentos por minuto en la última ``VENTANA``."""
    ahora = time.monotonic()
    with _cerrojo:
        if _muestras and (paginas < _muestras[-1][1] or terminados < _muestras[-1][2]):
            # Se limpió la pantalla y los contadores bajaron: se empieza de nuevo.
            _muestras.clear()
        _muestras.append((ahora, paginas, terminados))
        while _muestras and ahora - _muestras[0][0] > VENTANA:
            _muestras.popleft()
        primero = _muestras[0]
    lapso = ahora - primero[0]
    if lapso < 5:
        return None, None
    return (
        round((paginas - primero[1]) * 60 / lapso, 1),
        round((terminados - primero[2]) * 60 / lapso, 2),
    )


@router.get("/api/rendimiento")
async def rendimiento(ctx: Ctx) -> dict[str, object]:
    trabajos = ctx.registry.list()
    paginas = sum(trabajo.progress.pages_done for trabajo in trabajos)
    terminados = sum(1 for trabajo in trabajos if trabajo.state is JobState.DONE)
    por_minuto, documentos_por_minuto = _ritmo(paginas, terminados)
    memoria = _memoria()
    return {
        "equipo": {
            "cpu": _cpu(),
            "nucleos": os.cpu_count(),
            "carga": _carga(),
            "memoria_usada": memoria[0] if memoria else None,
            "memoria_total": memoria[1] if memoria else None,
        },
        "bot": {
            "memoria": _memoria_del_bot(),
            "procesos": ctx.settings.document_workers,
            "documentos_en_curso": ctx.planificador.en_curso if ctx.planificador else 0,
            "en_cola": ctx.registry.pending,
            "paginas_por_minuto": por_minuto,
            "documentos_por_minuto": documentos_por_minuto,
        },
    }
