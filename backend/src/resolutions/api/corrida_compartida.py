"""La corrida compartida: varios equipos procesando la misma carpeta hacia el mismo destino.

El operador, 2026-11-25: «correr 4 PC al mismo tiempo sin que ninguno se pise
los procesos, consumiendo de la misma fuente y llevando al mismo destino». Lo
que coordina está en ``adapters.coordinacion_en_disco``; aquí, lo que decide la
API: si se coordina, con qué versión del bot y con qué opciones.

``BOTPDF_COORDINACION``:

- ``auto`` (por omisión): se coordina siempre que el destino lo permita. Si la
  carpeta de destino no garantiza la creación exclusiva, la corrida sigue sola
  y lo avisa.
- ``si``: se coordina o no se corre.
- ``no``: como antes, un equipo solo.
"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path

MODOS = ("auto", "si", "no")


def modo() -> str:
    valor = (os.environ.get("BOTPDF_COORDINACION") or "auto").strip().lower()
    return {"sí": "si", "yes": "si", "1": "si", "0": "no", "off": "no"}.get(valor, valor if valor in MODOS else "auto")


@lru_cache(maxsize=1)
def version_del_bot() -> str:
    """La huella del código del bot: la misma imagen en todos los equipos da la misma.

    Del código y no de una etiqueta: un equipo con un arreglo de más dividiría
    su parte de la carpeta con otras reglas, y eso es lo que se impide.
    """
    raiz = Path(__file__).resolve().parent.parent
    huella = hashlib.sha1()
    for ruta in sorted(raiz.rglob("*.py")):
        if "__pycache__" in ruta.parts or "tests" in ruta.parts:
            continue
        try:
            huella.update(ruta.relative_to(raiz).as_posix().encode("utf-8"))
            huella.update(ruta.read_bytes().replace(b"\r\n", b"\n"))
        except OSError:
            continue
    return huella.hexdigest()[:12]


def opciones_de(run) -> dict[str, object]:
    """Las opciones de la corrida que tienen que ser las mismas en todos los equipos."""
    return {
        "task": run.task,
        "tipo": run.tipo,
        "tipo_documento": run.tipo_documento,
        "lectura": run.lectura,
        "corte": run.corte,
        "agrupar": run.agrupar,
        "oracle": run.oracle,
        "retomar": str(run.retomar),
        "territorial": run.territorial,
        "acta": run.acta,
        "oficina": run.oficina if run.oficina_del_operador else None,
    }
