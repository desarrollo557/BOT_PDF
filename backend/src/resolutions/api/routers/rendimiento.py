"""El rendimiento del equipo y del bot, en vivo, para la pantalla.

Lo pidió el operador el 2026-10-29: «en el espacio en blanco, el rendimiento del
programa y del PC en tiempo real, para tener todo muy bien controlado». Ese
mismo día el otro equipo se ahogó con diez PDF de 200 MB a la vez y sólo se
supo por los registros: con esto se ve en la pantalla, mientras pasa.

En Docker el equipo es lo que ve el contenedor -- la máquina virtual de Docker
Desktop, que reparte los núcleos y la memoria del PC --. Se lee de ``/proc``,
sin dependencias; donde no hay ``/proc`` (el servicio en Windows sin Docker),
lo que no se puede medir va como ``None`` y la pantalla dice «—».

Lo del equipo -- CPU, memoria, carga y núcleos -- lo mide desde el 2026-11-27
``adapters.recursos_del_equipo``, el mismo que pone los recursos de cada PC en
su latido de la corrida compartida. Con su propio ``MedidorDeCpu``: el latido
tiene el suyo, y ninguno le roba al otro la muestra anterior. Las respuestas
no cambian.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path

from fastapi import APIRouter

from ...adapters import recursos_del_equipo
from ..contexto import Ctx
from ..jobs import JobState

router = APIRouter()

#: Cuántos segundos se miran para el ritmo de páginas y documentos.
VENTANA = 60.0

_cerrojo = threading.Lock()
#: (instante, páginas leídas, documentos terminados) de cada consulta reciente.
_muestras: deque[tuple[float, int, int]] = deque(maxlen=240)
#: La CPU desde la consulta anterior de esta pantalla, con su propia muestra.
_medidor_de_cpu = recursos_del_equipo.MedidorDeCpu()


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
    memoria = recursos_del_equipo.memoria()
    return {
        "equipo": {
            "cpu": _medidor_de_cpu.medir(),
            "nucleos": recursos_del_equipo.nucleos(),
            "carga": recursos_del_equipo.carga(),
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
