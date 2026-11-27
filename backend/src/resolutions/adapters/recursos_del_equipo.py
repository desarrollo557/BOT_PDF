"""Lo que tiene y lo que usa este equipo: núcleos, CPU, carga, memoria y disco (2026-11-27).

El operador, 2026-11-27: «obviamente el principal deberá tener más capacidad de
recursos, RAM, disco», y eligió ver la RAM, el disco y la CPU de cada PC de la
corrida compartida. Cada equipo los mide para su latido
(``adapters.coordinacion_en_disco``), la pantalla de equipos enseña los de
todos y ``api/routers/rendimiento.py`` los de éste.

Antes vivían en ``api/routers/rendimiento.py``, que un adaptador no puede
importar (``scripts/check_layers.py``), y la CPU con su muestra anterior en una
variable global: dos que la midieran -- el latido y la pantalla de
rendimiento -- se habrían robado la muestra uno al otro. Ahora cada uno tiene su
``MedidorDeCpu``. Y no había nada que midiera el disco.

Se lee de ``/proc``, sin dependencias. En Docker es lo que ve el contenedor --
la máquina virtual de Docker Desktop, que reparte los núcleos y la memoria del
PC --: lo que el bot puede usar. Donde no hay ``/proc`` (el servicio en Windows
sin Docker), lo que no se puede medir va como ``None`` y la pantalla dice «—».
Nada de aquí lanza: medir nunca tumba a quien mide.
"""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

#: De dónde se leen la CPU y la memoria. Las pruebas lo cambian por una carpeta
#: con un ``/proc`` simulado.
PROC = Path("/proc")
#: El C: del equipo dentro de Docker (``BOTPDF_UNIDADES``, «C:=/equipo/c»): en
#: ese disco vive también el disco virtual de Docker, así que es el que se llena.
DISCO_DEL_EQUIPO = Path("/equipo/c")


class MedidorDeCpu:
    """El uso de CPU del equipo entre una medida y la anterior, en %.

    Con su propia muestra anterior: el latido tiene el suyo y la pantalla de
    rendimiento el suyo. La primera medida no tiene con qué comparar: ``None``.
    """

    def __init__(self, proc: Path | None = None) -> None:
        self._proc = proc
        self._antes: tuple[int, int] | None = None
        self._cerrojo = threading.Lock()

    def medir(self) -> float | None:
        try:
            primera = ((self._proc or PROC) / "stat").read_text(encoding="ascii").splitlines()[0]
            valores = [int(valor) for valor in primera.split()[1:]]
        except (OSError, IndexError, ValueError):
            return None
        if len(valores) < 4:
            return None
        ocioso = valores[3] + (valores[4] if len(valores) > 4 else 0)
        total = sum(valores)
        with self._cerrojo:
            antes, self._antes = self._antes, (total, ocioso)
        if antes is None or total <= antes[0]:
            return None
        return round(100 * (1 - (ocioso - antes[1]) / (total - antes[0])), 1)


def memoria(proc: Path | None = None) -> tuple[int, int] | None:
    """(usada, total) en bytes, de ``/proc/meminfo``: usada es MemTotal − MemAvailable."""
    try:
        lineas = ((proc or PROC) / "meminfo").read_text(encoding="ascii").splitlines()
    except (OSError, ValueError):
        # ValueError: un byte que no es ASCII (UnicodeDecodeError). Nada de aquí
        # lanza: en /api/rendimiento habría sido un 500.
        return None
    datos: dict[str, int] = {}
    for linea in lineas:
        nombre, _, resto = linea.partition(":")
        partes = resto.split()
        if partes and partes[0].isdigit():
            datos[nombre] = int(partes[0]) * 1024
    if "MemTotal" not in datos or "MemAvailable" not in datos:
        return None
    return datos["MemTotal"] - datos["MemAvailable"], datos["MemTotal"]


def carga() -> float | None:
    """La carga media del último minuto (``os.getloadavg``); en Windows no existe: ``None``."""
    try:
        return round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        return None


def nucleos() -> int | None:
    """Los núcleos que ve el bot: en Docker, los de su máquina virtual."""
    return os.cpu_count()


def disco(ruta: Path | str) -> tuple[int, int] | None:
    """(libre, total) en bytes del disco donde está ``ruta``; ``None`` si no se puede mirar."""
    try:
        uso = shutil.disk_usage(ruta)
    except (OSError, ValueError):
        return None
    return uso.free, uso.total


def disco_a_medir(carpeta_de_datos: Path | str) -> Path:
    """El disco que importa: el C: del equipo si el bot corre en Docker (``/equipo/c``); si no, el de sus datos."""
    try:
        if DISCO_DEL_EQUIPO.is_dir():
            return DISCO_DEL_EQUIPO
    except OSError:
        pass
    return Path(carpeta_de_datos)


def _nombre_del_disco(ruta: Path) -> str:
    """«/equipo/c» en Docker; en Windows, la unidad («C:\\»), que dice más que la carpeta de datos."""
    return ruta.anchor if ruta.drive else ruta.as_posix()


def medir(carpeta_de_datos: Path | str, *, cpu: MedidorDeCpu | None = None) -> dict[str, object]:
    """Los recursos de este equipo, con las claves de ``application.coordinacion.CLAVES_DE_LOS_RECURSOS``.

    ``carpeta_de_datos``: donde el bot guarda lo suyo (``/data`` en Docker), el
    disco que se mide si no hay ``/equipo/c``. ``cpu``: el medidor de quien
    mide; sin él, la CPU va como ``None``. Lo que no se puede medir, ``None``.
    """
    ruta = disco_a_medir(carpeta_de_datos)
    usada_y_total = memoria()
    libre_y_total = disco(ruta)
    return {
        "nucleos": nucleos(),
        "cpu": cpu.medir() if cpu is not None else None,
        "carga": carga(),
        "memoria_usada": usada_y_total[0] if usada_y_total else None,
        "memoria_total": usada_y_total[1] if usada_y_total else None,
        "disco_libre": libre_y_total[0] if libre_y_total else None,
        "disco_total": libre_y_total[1] if libre_y_total else None,
        "disco": _nombre_del_disco(ruta) if libre_y_total else None,
    }
