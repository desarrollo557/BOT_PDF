"""Guardar un Excel entero o nada.

``book.save(ruta)`` escribe directamente sobre el archivo final: un corte a
mitad -- la red, la luz, el servicio que se detiene -- dejaba un .xlsx dañado
con su nombre definitivo, y quien lo leía después para sumarle filas lo
descartaba en silencio (2026-10-27). Aquí se escribe a un temporal oculto junto
al destino y sólo entero pasa a su nombre, como ya hacían el Índice Electrónico
y el análisis de la entrega.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Protocol


class _Libro(Protocol):
    def save(self, filename: str | os.PathLike[str]) -> object: ...


def guardar_libro(libro: _Libro, ruta: str | os.PathLike[str]) -> Path:
    """Guarda ``libro`` en ``ruta`` pasando por un temporal; devuelve la ruta.

    Si el destino está abierto en Excel, ``os.replace`` falla como fallaba el
    guardado directo -- con ``PermissionError`` -- y quien llama decide igual
    que antes. El temporal no queda nunca en la carpeta.
    """
    ruta = Path(ruta)
    temporal = ruta.with_name(f".{ruta.name}.tmp")
    try:
        libro.save(temporal)
        os.replace(temporal, ruta)
    finally:
        with contextlib.suppress(OSError):
            temporal.unlink(missing_ok=True)
    return ruta
