"""Lo que va en la casilla «Territorial» del Índice Electrónico, leído de la ruta.

El repositorio de Afinia guarda cada caja así:

    \\\\200.100.20.97\\afinia\\REPOSITORIO\\AFINIA\\BOLIVAR SUR\\COMERCIAL\\MAGANGUE\\210847\\UPD2998726.pdf
                                                                      municipio caja   PDF

El 2026-10-20 el operador pidió que la casilla «Territorial» de cada caja diga
el **municipio** -- «MAGANGUE» --, sin escribirlo a mano: la carpeta que
contiene la caja, es decir, la abuela del PDF. Vale igual si se procesa la
carpeta del municipio, la del área o la territorial entera, y en una copia
local que conserve «MUNICIPIO\\CAJA\\UPD….pdf».

Una caja que cuelga directamente de la raíz («…\\AFINIA\\108C003007\\») o de un
área («…\\COMERCIAL\\108C000001\\») no tiene municipio en la ruta: entonces vale
lo que escribió el operador.

Nada aquí importa nada de fuera del dominio.
"""

from __future__ import annotations

import re

#: La raíz del repositorio de Afinia.
RAIZ = "AFINIA"
#: Las áreas que cuelgan de cada territorial.
AREAS = frozenset({"COMERCIAL", "OTRAS OFICINAS"})


def _carpetas(ruta: str) -> list[str]:
    """Las carpetas de la ruta, sin el archivo del final."""
    partes = [parte.strip() for parte in re.split(r"[\\/]+", ruta or "") if parte.strip()]
    if partes and re.search(r"\.[A-Za-z0-9]{2,4}$", partes[-1]):
        partes = partes[:-1]
    return partes


#: Un NIC es un número; una caja llamada «108C000534» es un número de caja, no un NIC.
_NIC = re.compile(r"^\d{4,12}$")


def nic_de_la_ruta(ruta: str) -> str | None:
    """El NIC de la caja: la carpeta que contiene el PDF, si es un número.

    Lo fijó el operador con su planilla el 2026-10-20: de
    «…\\MAGANGUE\\210847\\UPD2998726.pdf» la «Identificación / Nic» es 210847.
    """
    carpetas = _carpetas(ruta)
    if not carpetas:
        return None
    caja = carpetas[-1].strip()
    return caja if _NIC.match(caja) else None


def nombre_del_expediente(ruta: str) -> str:
    """El expediente es el PDF de la caja, sin la carpeta: «UPD2998266».

    En una corrida de carpeta el nombre del trabajo trae la subcarpeta --
    «910349/UPD2998266.pdf» -- y el índice salía con «910349 UPD2998266».
    """
    archivo = [parte for parte in re.split(r"[\\/]+", ruta or "") if parte.strip()]
    if not archivo:
        return ""
    return re.sub(r"\.[A-Za-z0-9]{1,5}$", "", archivo[-1]).strip()


def territorial_de_la_ruta(ruta: str) -> str | None:
    """El municipio de la caja -- la carpeta que la contiene --; ``None`` si la ruta no lo dice."""
    carpetas = _carpetas(ruta)
    # Hacen falta dos: la de la caja y, encima, la del municipio.
    if len(carpetas) < 2:
        return None
    municipio = carpetas[-2].upper()
    if municipio == RAIZ or municipio in AREAS or municipio.endswith(":"):
        return None
    return municipio
