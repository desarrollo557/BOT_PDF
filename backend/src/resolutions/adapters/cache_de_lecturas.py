"""La caché de las lecturas de pago: cada imagen se paga una vez (2026-11-18).

El operador va a procesar otra vez la caja de Magangué entera, y la volverá a
procesar o reprocesará partes: sin caché, cada vuelta pagaba de nuevo a Mistral
las mismas páginas y los mismos sellos. Aquí queda lo que contestó, con la
huella de lo que se le preguntó -- el SHA-256 de la imagen, el modelo y el
pedido --: la misma pregunta, la misma respuesta, sin volver a pagar. Las
lecturas, además, quedan reproducibles.

Un SQLite en la carpeta de datos (``/data`` en Docker), compartido por los
procesos del worker: modo WAL y transacciones cortas. Si algo falla, se lee
como si no hubiera caché: nunca tumba una lectura. ``BOTPDF_CACHE_DE_LECTURAS=0``
la apaga (las pruebas lo hacen).
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

NOMBRE = "cache_de_lecturas.sqlite3"
#: Cuánto espera una escritura a que otro proceso suelte la base.
ESPERA_SEGUNDOS = 10

_cerrojo = threading.Lock()
_conexiones: dict[int, sqlite3.Connection] = {}


def activa() -> bool:
    return os.environ.get("BOTPDF_CACHE_DE_LECTURAS", "1") != "0"


def _ruta() -> Path:
    raiz = Path(os.environ.get("RESOLUTIONS_DATA_DIR", "./data")).resolve()
    return raiz / NOMBRE


def _conexion() -> sqlite3.Connection | None:
    """La conexión de este proceso, creada la primera vez."""
    pid = os.getpid()
    with _cerrojo:
        conexion = _conexiones.get(pid)
        if conexion is not None:
            return conexion
        try:
            ruta = _ruta()
            ruta.parent.mkdir(parents=True, exist_ok=True)
            conexion = sqlite3.connect(ruta, timeout=ESPERA_SEGUNDOS, check_same_thread=False)
            conexion.execute("PRAGMA journal_mode=WAL")
            conexion.execute("CREATE TABLE IF NOT EXISTS lecturas (clave TEXT PRIMARY KEY, texto TEXT NOT NULL)")
            conexion.commit()
        except (OSError, sqlite3.Error):
            logger.warning("no se pudo abrir la caché de lecturas; se lee sin ella", exc_info=True)
            return None
        _conexiones[pid] = conexion
        return conexion


def clave(*partes: bytes | str | None) -> str:
    """La huella de lo que se pregunta: cada parte, en orden."""
    huella = hashlib.sha256()
    for parte in partes:
        dato = parte if isinstance(parte, bytes) else str(parte or "").encode("utf-8")
        huella.update(len(dato).to_bytes(8, "big"))
        huella.update(dato)
    return huella.hexdigest()


def leer(llave: str) -> str | None:
    """Lo que se contestó a esa pregunta, o ``None``."""
    if not activa() or (conexion := _conexion()) is None:
        return None
    try:
        with _cerrojo:
            fila = conexion.execute("SELECT texto FROM lecturas WHERE clave = ?", (llave,)).fetchone()
    except sqlite3.Error:
        logger.debug("la caché de lecturas no respondió", exc_info=True)
        return None
    return fila[0] if fila else None


def guardar(llave: str, texto: str) -> None:
    """Guarda la respuesta. Una vacía no: puede ser un fallo que la próxima vez no lo sea."""
    if not texto or not activa() or (conexion := _conexion()) is None:
        return
    try:
        with _cerrojo:
            conexion.execute("INSERT OR REPLACE INTO lecturas (clave, texto) VALUES (?, ?)", (llave, texto))
            conexion.commit()
    except sqlite3.Error:
        logger.debug("no se pudo guardar en la caché de lecturas", exc_info=True)
