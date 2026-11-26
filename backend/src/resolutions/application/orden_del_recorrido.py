"""Por dónde se empieza a recorrer el origen: primero lo que no está en el destino.

El operador, 2026-11-26: «que no se demore mucho buscando los ya procesados
para comenzar a procesar». Esa mañana cada equipo tardó de 3 a 28 min desde que
se unió a la corrida hasta tomar su primer PDF: el origen de Magangué (~32.000
carpetas NIC) se recorría en orden de ruta, y lo pendiente -- los NIC 8xxxxxxx
y 9xxxxxxx -- quedaba al final, detrás de unos 35.000 PDF ya entregados. La raíz
del origen se lista entera en 7,8 s y la del destino (29.480 carpetas) en 2,9 s:
con esos dos listados se sabe qué carpetas no están en el destino, y se empieza
por ellas.

Aquí sólo la decisión, sin leer nada: la red y el disco los pone quien llama.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable


def nombre_de_la_carpeta(ruta: object) -> str:
    """El último tramo de una ruta, con barras de uno u otro lado.

    «//200.100.20.97/afinia/…/MAGANGUE/1000265» → «1000265»; igual con
    «\\\\» o con un ``Path`` del equipo.
    """
    return str(ruta).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def lo_pendiente_primero[T](
    subcarpetas: Iterable[T],
    en_el_destino: Iterable[str],
    *,
    nombre: Callable[[T], str] = nombre_de_la_carpeta,
) -> tuple[list[T], list[T]]:
    """Las subcarpetas del origen que no están en el destino, y las que sí, cada grupo en su orden.

    ``subcarpetas`` llega en orden de ruta y así sigue dentro de cada grupo: lo
    de una misma caja se procesa junto. ``en_el_destino`` son los nombres de
    las carpetas de la raíz del destino; ``nombre`` saca el de cada subcarpeta.
    Sin distinguir mayúsculas: ni Windows ni SMB las distinguen, y «Ab» y «AB»
    son la misma carpeta.

    Que una carpeta ya esté en el destino no quiere decir que esté completa:
    eso lo sigue diciendo la constancia de cada PDF. Esto sólo dice por dónde
    empezar.
    """
    ya_estan = {nombre_en_el_destino.lower() for nombre_en_el_destino in en_el_destino}
    faltan: list[T] = []
    estan: list[T] = []
    for carpeta in subcarpetas:
        (estan if nombre(carpeta).lower() in ya_estan else faltan).append(carpeta)
    return faltan, estan
