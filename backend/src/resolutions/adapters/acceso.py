"""Si una carpeta está en la red o en este equipo, y a qué velocidad se lee y se escribe.

Lo pidió el operador el 2026-11-05 («que si es por red el bot me diga y estime
en realidad cuánto es la velocidad de la red y cuánto podría demorar»). La
cuenta -- la velocidad de lo reciente, lo que falta -- está en
``domain/ritmo.py``; aquí sólo lo que toca el sistema:

* ``es_de_red``: una ruta «\\\\servidor\\recurso», una unidad de red de Windows
  (``W:``), o en Docker una carpeta montada por la red (CIFS, NFS). Las
  unidades del equipo que Docker comparte con el contenedor (``C:`` en
  ``/equipo/c``) son locales aunque pasen por la máquina virtual.
* ``medir_lectura``: lee una muestra de un PDF del origen y cronometra.
* ``medir_escritura``: escribe una muestra en el destino, la fuerza al disco
  (``fsync``, que en una carpeta de red es esperar al servidor) y la borra.

Las dos pruebas mueven ``MUESTRA`` bytes como mucho: unos segundos en una red
lenta, nada en un disco local.
"""

from __future__ import annotations

import os
import re
import sys
import time
import uuid
from pathlib import Path

from . import red_smb

#: Cuánto se lee o se escribe en una prueba: 8 MB.
MUESTRA = 8 * 1024 * 1024
#: De a cuánto.
BLOQUE = 1024 * 1024
#: Los sistemas de archivos que son de red cuando la carpeta está montada.
TIPOS_DE_RED = frozenset({"cifs", "smb3", "smbfs", "nfs", "nfs4", "fuse.sshfs", "afs", "ncpfs"})
#: Lo que Windows dice de una unidad de red (``GetDriveTypeW``).
_UNIDAD_REMOTA = 4
#: El prefijo del nombre del archivo de prueba: si una prueba se corta, se
#: reconoce y se puede borrar.
PREFIJO_DE_LA_PRUEBA = ".botpdf-prueba-de-velocidad-"


def es_de_red(ruta: str | Path) -> bool:
    """Si ``ruta`` está en otro equipo: «\\\\servidor\\…», una unidad de red o un montaje de red."""
    texto = str(ruta)
    if red_smb.es_de_red(texto):
        return True
    if sys.platform == "win32":
        return _unidad_de_red_en_windows(texto)
    try:
        montajes = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return montada_por_la_red(texto, montajes)


def _unidad_de_red_en_windows(texto: str) -> bool:
    unidad = re.match(r"^([A-Za-z]):", texto)
    if unidad is None:
        return False
    import ctypes

    return int(ctypes.windll.kernel32.GetDriveTypeW(f"{unidad.group(1)}:\\")) == _UNIDAD_REMOTA


def _sin_escapes(texto: str) -> str:
    """«/equipo/mi\\040carpeta» de ``/proc/mounts`` es «/equipo/mi carpeta»."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), texto)


def montada_por_la_red(ruta: str, montajes: str) -> bool:
    """Si ``ruta`` cae en un montaje de red según el texto de ``/proc/mounts``.

    Manda el montaje más largo que la contiene: ``/equipo/w`` (cifs) gana a
    ``/`` (overlay) para «/equipo/w/FOLIA-BOT».
    """
    destino = "/" + ruta.replace("\\", "/").strip("/")
    mejor, de_red = -1, False
    for linea in montajes.splitlines():
        campos = linea.split()
        if len(campos) < 3:
            continue
        punto = "/" + _sin_escapes(campos[1]).strip("/")
        dentro = destino == punto or destino.startswith(punto.rstrip("/") + "/") or punto == "/"
        if dentro and len(punto) > mejor:
            mejor, de_red = len(punto), campos[2].lower() in TIPOS_DE_RED
    return de_red


def medir_lectura(ruta: str | Path, tope: int = MUESTRA) -> tuple[int, float]:
    """Lee hasta ``tope`` bytes de ``ruta``: cuántos y en cuántos segundos."""
    if red_smb.por_smb(ruta):
        return red_smb.leer_muestra(str(ruta), tope)
    leidos = 0
    with open(ruta, "rb", buffering=0) as archivo:
        inicio = time.monotonic()
        while leidos < tope and (bloque := archivo.read(min(BLOQUE, tope - leidos))):
            leidos += len(bloque)
        return leidos, time.monotonic() - inicio


def medir_escritura(carpeta: str | Path, cuanto: int = MUESTRA) -> tuple[int, float]:
    """Escribe ``cuanto`` bytes en ``carpeta``, los fuerza al disco y los borra: cuántos y en cuánto.

    Datos al azar, para que ningún disco ni ningún enlace los comprima, y un
    nombre que empieza por un punto y dice qué es, por si la prueba se corta.
    La carpeta tiene que existir: la prueba no crea carpetas que nadie eligió.
    """
    prueba = Path(carpeta) / f"{PREFIJO_DE_LA_PRUEBA}{uuid.uuid4().hex[:8]}.tmp"
    datos = os.urandom(BLOQUE)
    escritos = 0
    try:
        with open(prueba, "wb", buffering=0) as archivo:
            inicio = time.monotonic()
            while escritos < cuanto:
                escritos += archivo.write(datos[: min(BLOQUE, cuanto - escritos)])
            os.fsync(archivo.fileno())
            segundos = time.monotonic() - inicio
    finally:
        prueba.unlink(missing_ok=True)
    return escritos, segundos
