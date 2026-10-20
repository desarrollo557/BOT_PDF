"""Qué fallo de un documento merece otro intento, y cuánto esperar antes.

Una corrida sobre la caja de red Z: de un millón de páginas pasa días sola, y
en días la red se corta, el escáner compartido deja un PDF bloqueado un
minuto y un proceso del pool muere por memoria. Ninguna de esas cosas dice
nada del papel: el mismo PDF, un rato después, sale bien. Hasta ahora salían
como «Falló» y había que relanzarlos a mano, uno por uno.

Lo que sí dice algo del papel -- un PDF dañado, con contraseña, vacío -- no
se reintenta: volverá a fallar igual y sólo gasta tiempo. Tampoco lo que el
operador pidió (cancelar) ni un documento que se quedó sin avanzar, que suele
ser una página que el lector nativo no suelta y que volvería a atascarlo.
"""

from __future__ import annotations

import errno
import random

#: Los errores de Windows de una ruta de red que se cayó un momento:
#: 53 ruta de red no encontrada, 59 error de red inesperado, 64 el nombre de
#: red ya no está disponible, 67 nombre de red no encontrado, 121 se agotó el
#: tiempo del semáforo, 1231/1232 red o host inalcanzable, 1236 la conexión la
#: cortó el sistema local, 1240 la cuenta no tiene permiso desde esta estación
#: (aparece cuando el servidor de archivos se reinicia).
ERRORES_DE_RED_DE_WINDOWS = frozenset({53, 59, 64, 67, 121, 1231, 1232, 1236, 1240})

_ERRNO_DE_RED = frozenset(
    {
        errno.ETIMEDOUT,
        errno.ECONNRESET,
        errno.ECONNABORTED,
        errno.ECONNREFUSED,
        errno.EHOSTUNREACH,
        errno.ENETUNREACH,
        errno.ENETDOWN,
        errno.EIO,
    }
)

#: Por el nombre de su clase, para no importar a quien los lanza: el pool roto
#: es de `concurrent.futures` y llega a esta capa ya como excepción.
_TRANSITORIOS_POR_NOMBRE = frozenset({"BrokenProcessPool", "OrigenNoDisponible"})

#: Lo que se sabe que no cambia con otro intento, aunque herede de una clase
#: que sí: un PDF que no se abre es un ValueError que a veces trae debajo un
#: OSError, y lo que manda es lo que dice del papel.
_DEFINITIVOS_POR_NOMBRE = frozenset(
    {"PdfQueNoSeAbre", "TrabajoSinAvance", "LecturaAtascada", "Cancelled"}
)


def es_transitorio(error: BaseException) -> bool:
    """Si otro intento del mismo documento, un rato después, puede salir bien."""
    nombre = type(error).__name__
    if nombre in _DEFINITIVOS_POR_NOMBRE:
        return False
    if nombre in _TRANSITORIOS_POR_NOMBRE:
        return True
    if isinstance(error, (FileNotFoundError, PermissionError, IsADirectoryError, NotADirectoryError)):
        # Que el archivo no esté o esté bloqueado no se arregla esperando
        # segundos; el operador lo verá y lo resolverá.
        return False
    if isinstance(error, (TimeoutError, ConnectionError, EOFError, MemoryError)):
        return True
    if isinstance(error, OSError):
        if getattr(error, "winerror", None) in ERRORES_DE_RED_DE_WINDOWS:
            return True
        return error.errno in _ERRNO_DE_RED
    causa = error.__cause__
    if causa is not None and causa is not error:
        return es_transitorio(causa)
    return False


def pide_otro_pool(error: BaseException) -> bool:
    """Si el fallo deja inservible el pool de procesos y hay que levantar otro."""
    return type(error).__name__ == "BrokenProcessPool"


def espera_antes_del_intento(intento: int, base: float) -> float:
    """Segundos antes del intento ``intento`` (el segundo es el 2): base, ×3, ×9…

    Con un poco de azar, para que veinte documentos que fallaron a la vez por
    la misma caída de red no vuelvan todos en el mismo segundo.
    """
    if base <= 0:
        return 0.0
    return base * 3 ** max(0, intento - 2) * random.uniform(0.8, 1.2)


#: Lo que no se arregla con otra vuelta: el papel dañado o protegido, lo que
#: el operador canceló y el PDF que ya no está.
_SIN_OTRA_VUELTA = frozenset({"PdfQueNoSeAbre", "Cancelled"})


def merece_otra_vuelta(error: BaseException) -> bool:
    """Si un documento que falló se vuelve a intentar al final de la carpeta.

    Más amplio que ``es_transitorio``: aquí entra también lo que no se sabe
    clasificar, un documento que se atascó y un Excel que estaba abierto. La
    segunda vuelta llega minutos después, con la carpeta ya más tranquila, y
    muchas de esas cosas para entonces se han arreglado solas. Lo que dice
    algo del papel o lo que pidió el operador no vuelve.
    """
    if type(error).__name__ in _SIN_OTRA_VUELTA:
        return False
    return not isinstance(error, (FileNotFoundError, IsADirectoryError, NotADirectoryError))
