"""El padrón de personas de la Universidad, en un archivo de texto junto al libro mayor.

Un JSON por línea, como el libro mayor y los usuarios: se lee con cualquier
cosa y sobrevive a que el programa se caiga a mitad de una escritura. Sólo se
añade -- una persona corregida otra vez es una línea nueva, y la última del
operador manda (``domain/padron.py``) --, y no se repite una línea igual.

Escribe un solo proceso, el del servicio: al terminar cada trabajo y cuando el
operador corrige un nombre. Los trabajos lo leen, cada uno al empezar.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable
from pathlib import Path

from ..domain.padron import Persona

logger = logging.getLogger(__name__)


class PadronEnArchivo:
    """Las personas del padrón, una por línea."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        #: La lectura cacheada, invalidada por el tamaño y la fecha del archivo.
        self._cache: list[Persona] | None = None
        self._firma: tuple[int, int] | None = None

    @property
    def path(self) -> Path:
        return self._path

    def personas(self) -> list[Persona]:
        with self._lock:
            return list(self._leer())

    def _leer(self) -> list[Persona]:
        try:
            estado = self._path.stat()
        except OSError:
            self._cache, self._firma = [], None
            return []
        firma = (estado.st_size, estado.st_mtime_ns)
        if self._cache is not None and firma == self._firma:
            return self._cache
        personas: list[Persona] = []
        try:
            with self._path.open(encoding="utf-8") as archivo:
                for numero, linea in enumerate(archivo, start=1):
                    if not linea.strip():
                        continue
                    try:
                        persona = Persona.de_dict(json.loads(linea))
                    except ValueError:
                        logger.warning("padrón: la línea %s de %s no es JSON; se salta", numero, self._path)
                        continue
                    if persona is not None:
                        personas.append(persona)
        except OSError:
            logger.warning("no se pudo leer el padrón %s", self._path, exc_info=True)
            return self._cache or []
        self._cache, self._firma = personas, firma
        return personas

    def anotar(self, personas: Iterable[Persona]) -> int:
        """Añade las personas que no estén ya con el mismo nombre, cédula y fuente; devuelve cuántas.

        Lo del operador se anota siempre: la última corrección es la que manda,
        aunque vuelva a un nombre que ya dio antes.
        """
        nuevas = list(personas)
        if not nuevas:
            return 0
        with self._lock:
            ya = {(persona.nombre, persona.cedula, persona.fuente) for persona in self._leer()}
            lineas = []
            for persona in nuevas:
                clave = (persona.nombre, persona.cedula, persona.fuente)
                if clave in ya and not persona.del_operador:
                    continue
                ya.add(clave)
                lineas.append(json.dumps(persona.como_dict(), ensure_ascii=False))
            if not lineas:
                return 0
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as archivo:
                archivo.write("\n".join(lineas) + "\n")
            self._cache, self._firma = None, None
            return len(lineas)
