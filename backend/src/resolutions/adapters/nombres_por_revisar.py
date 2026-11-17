"""Los nombres por confirmar de cada trabajo, en disco: la Revisión de nombres sobrevive a un reinicio.

El operador (2026-11-17), cubriendo lo que quedaba: la Revisión de nombres vivía
en la memoria del servicio. Tras un reinicio sólo quedaba el padrón, y en una
corrida de más de ``trabajos_en_memoria`` PDF los primeros salían de la memoria
antes de que alguien los mirara: sus nombres dudosos se perdían sin decirlo.

Un JSON por trabajo, ``<trabajo>.json``, con lo que la pantalla necesita para
enseñar y corregir a sus personas sin el trabajo en memoria: su documento, su
destino y lo del informe que lleva sus filas. Se escribe al terminar el trabajo
si alguna persona quedó por mirar, se reescribe al corregir cada una y se borra
cuando no queda ninguna. Pasa por un temporal: un corte a mitad de escritura
deja el de antes, nunca medio archivo.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

#: El nombre de un trabajo, tal como sale de ``uuid4().hex``: nada que suba de carpeta.
_TRABAJO = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class NombresPorRevisarEnDisco:
    """Los trabajos con personas por mirar, uno por archivo, en ``carpeta``."""

    def __init__(self, carpeta: Path | str) -> None:
        self._carpeta = Path(carpeta)
        self._lock = threading.Lock()

    @property
    def carpeta(self) -> Path:
        return self._carpeta

    def _ruta(self, trabajo: str) -> Path | None:
        return self._carpeta / f"{trabajo}.json" if _TRABAJO.match(str(trabajo or "")) else None

    def guardar(self, trabajo: str, entrada: dict) -> None:
        """Deja la entrada del trabajo, en lugar de la que hubiera."""
        ruta = self._ruta(trabajo)
        if ruta is None:
            raise ValueError(f"nombre de trabajo no válido: {trabajo!r}")
        with self._lock:
            self._carpeta.mkdir(parents=True, exist_ok=True)
            temporal = ruta.with_name(f".{uuid4().hex[:8]}.tmp")
            try:
                temporal.write_text(json.dumps(entrada, ensure_ascii=False), encoding="utf-8")
                os.replace(temporal, ruta)
            finally:
                temporal.unlink(missing_ok=True)

    def leer(self, trabajo: str) -> dict | None:
        """La entrada del trabajo, o ``None`` si no tiene o no se deja leer."""
        ruta = self._ruta(trabajo)
        if ruta is None:
            return None
        try:
            with self._lock:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            logger.warning("no se pudo leer %s", ruta, exc_info=True)
            return None
        return datos if isinstance(datos, dict) else None

    def todas(self) -> list[dict]:
        """Las entradas de todos los trabajos, las más viejas primero."""
        try:
            rutas = sorted(self._carpeta.glob("*.json"), key=lambda ruta: ruta.stat().st_mtime_ns)
        except OSError:
            return []
        salida = []
        for ruta in rutas:
            if (entrada := self.leer(ruta.stem)) is not None:
                salida.append(entrada)
        return salida

    def quitar(self, trabajo: str) -> None:
        """Quita la entrada del trabajo, si la tiene."""
        ruta = self._ruta(trabajo)
        if ruta is None:
            return
        with self._lock:
            ruta.unlink(missing_ok=True)
