"""La territorial de una caja de correspondencia, leída de su ruta en el repositorio.

El repositorio de Afinia guarda cada caja así:

    \\\\200.100.20.97\\afinia\\REPOSITORIO\\AFINIA\\BOLIVAR SUR\\COMERCIAL\\MOMPOX\\108C000534\\UPD2452915.pdf
                                           territorial  área      municipio caja

El 2026-10-20 el operador pidió que el Índice Electrónico de cada caja diga su
territorial sin escribirla a mano: «BOLIVAR SUR», tal como está en la ruta. Se
lee de dos maneras, en este orden:

1. La carpeta que sigue a la raíz «AFINIA» del repositorio.
2. Si la ruta no pasa por esa raíz -- una copia local que conserva la estructura
   --, la carpeta que está encima del área («COMERCIAL», «OTRAS OFICINAS»).

Una caja que cuelga directamente de la raíz («…\\AFINIA\\108C003007\\») no
tiene territorial en la ruta: entonces vale la que escribió el operador.

Nada aquí importa nada de fuera del dominio.
"""

from __future__ import annotations

import re

#: La raíz del repositorio de Afinia: lo que la sigue es la territorial.
RAIZ = "AFINIA"
#: Las áreas que cuelgan de cada territorial.
AREAS = frozenset({"COMERCIAL", "OTRAS OFICINAS"})


def _carpetas(ruta: str) -> list[str]:
    """Las carpetas de la ruta, sin el archivo del final."""
    partes = [parte.strip() for parte in re.split(r"[\\/]+", ruta or "") if parte.strip()]
    if partes and re.search(r"\.[A-Za-z0-9]{2,4}$", partes[-1]):
        partes = partes[:-1]
    return partes


def territorial_de_la_ruta(ruta: str) -> str | None:
    """La territorial de la caja, si la ruta la dice; ``None`` si no."""
    carpetas = _carpetas(ruta)
    mayusculas = [carpeta.upper() for carpeta in carpetas]
    # Por la raíz del repositorio: la última «AFINIA» (la primera puede ser el
    # nombre del recurso compartido, «\\\\servidor\\afinia\\…»).
    raices = [i for i, carpeta in enumerate(mayusculas) if carpeta == RAIZ]
    if raices:
        siguiente = raices[-1] + 1
        # Tiene que haber algo debajo: si lo que sigue es ya la carpeta de la
        # caja, la caja cuelga de la raíz y no tiene territorial.
        if siguiente < len(carpetas) - 1:
            return mayusculas[siguiente]
    # Por el área: lo que está encima de «COMERCIAL» es la territorial.
    for i in range(len(mayusculas) - 1, 0, -1):
        if mayusculas[i] in AREAS:
            return mayusculas[i - 1]
    return None
