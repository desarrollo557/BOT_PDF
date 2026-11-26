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
import shutil
import tempfile
from pathlib import Path
from typing import Protocol
from uuid import uuid4


class _Libro(Protocol):
    def save(self, filename: str | os.PathLike[str]) -> object: ...


def guardar_libro(libro: _Libro, ruta: str | os.PathLike[str], *, armado_en_local: bool = False) -> Path:
    """Guarda ``libro`` en ``ruta`` pasando por un temporal; devuelve la ruta.

    Si el destino está abierto en Excel, ``os.replace`` falla como fallaba el
    guardado directo -- con ``PermissionError`` -- y quien llama decide igual
    que antes. El temporal no queda nunca en la carpeta.

    ``armado_en_local``: el libro se arma en un temporal de este equipo y al
    destino va de una sola copia seguida. Guardado directo en una carpeta de
    red, openpyxl lo escribe a trozos -- decenas de idas y vueltas por libro --,
    y es lo que se hace en cada entrega de la carpeta de un NIC (2026-11-26).
    """
    ruta = Path(ruta)
    # Corto y único: «.{nombre}.tmp» sumaba cinco caracteres a un nombre que
    # `sheet_filename` ya recortó al límite de Windows, y el guardado fallaba.
    temporal = ruta.with_name(f".{uuid4().hex[:8]}.tmp")
    local: Path | None = None
    try:
        if armado_en_local:
            descriptor, nombre = tempfile.mkstemp(suffix=".xlsx", prefix="botpdf-libro-")
            os.close(descriptor)
            local = Path(nombre)
            libro.save(local)
            with local.open("rb") as origen, temporal.open("wb") as copia:
                shutil.copyfileobj(origen, copia, 1024 * 1024)
        else:
            libro.save(temporal)
        os.replace(temporal, ruta)
    finally:
        with contextlib.suppress(OSError):
            temporal.unlink(missing_ok=True)
        if local is not None:
            with contextlib.suppress(OSError):
                local.unlink(missing_ok=True)
    return ruta
