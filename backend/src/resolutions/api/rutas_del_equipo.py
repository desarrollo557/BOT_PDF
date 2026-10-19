"""Las rutas del equipo vistas desde el contenedor, y al revés.

En Docker el servicio corre en Linux y no ve los discos de Windows: cada unidad
se monta dentro del contenedor («C:\\» en ``/equipo/c``, «Z:\\» en
``/equipo/z``). Sin esta traducción el operador tendría que escribir
``/equipo/c/Users/…`` en lugar de la ruta que copia del Explorador, y el
explorador de la pantalla le enseñaría carpetas que no reconoce.

Las unidades montadas se declaran en ``BOTPDF_UNIDADES`` -- «C:=/equipo/c;Z:=/equipo/z»
--, que escribe el instalador según las unidades que encuentra. Sin ella (el
servicio corriendo directamente en Windows) todo es la identidad: nada cambia.
"""

from __future__ import annotations

import os
import re

VARIABLE = "BOTPDF_UNIDADES"

#: «C:», «C:\», «C:\Users\ana» o «c:/Users/ana».
_RUTA_DE_WINDOWS = re.compile(r"^([A-Za-z]):(?:[\\/](.*))?$")
#: Dónde puede estar montada una unidad: una ruta absoluta del contenedor
#: («/equipo/c») o, en las pruebas sobre Windows, una carpeta con su letra.
_MONTAJE = re.compile(r"^(/|[A-Za-z]:/)")


def _barras(ruta: str) -> str:
    return ruta.replace("\\", "/")


def unidades() -> dict[str, str]:
    """Las unidades montadas: letra en mayúscula -> carpeta en el contenedor."""
    valor = os.environ.get(VARIABLE, "")
    montadas: dict[str, str] = {}
    for par in valor.split(";"):
        letra, _, montaje = par.partition("=")
        letra = letra.strip().rstrip(":").upper()
        montaje = _barras(montaje.strip()).rstrip("/")
        if len(letra) == 1 and letra.isalpha() and _MONTAJE.match(montaje + "/"):
            montadas[letra] = montaje
    return montadas


def al_servicio(ruta: str) -> str:
    """La ruta que escribió el operador, donde el servicio la encuentra.

    «C:\\Users\\ana\\ENTRADA» -> «/equipo/c/Users/ana/ENTRADA». Una ruta de una
    unidad que no está montada, o una que ya es del contenedor, pasa tal cual.
    """
    montadas = unidades()
    coincide = _RUTA_DE_WINDOWS.match(ruta.strip()) if montadas else None
    if not coincide:
        return ruta
    montaje = montadas.get(coincide.group(1).upper())
    if montaje is None:
        return ruta
    resto = _barras(coincide.group(2) or "").strip("/")
    return f"{montaje}/{resto}" if resto else montaje


def al_operador(ruta: object) -> str:
    """La ruta del contenedor como la reconoce el operador: «C:\\Users\\ana\\ENTRADA»."""
    texto = str(ruta)
    comparable = _barras(texto)
    for letra, montaje in unidades().items():
        if comparable == montaje or comparable.startswith(montaje + "/"):
            resto = comparable[len(montaje) :].strip("/")
            return f"{letra}:\\" + resto.replace("/", "\\")
    return texto


def raices() -> list[dict[str, str]]:
    """Las unidades montadas como puntos de partida del explorador de la pantalla."""
    return [{"name": f"Disco {letra}:", "path": f"{letra}:\\"} for letra in sorted(unidades())]
