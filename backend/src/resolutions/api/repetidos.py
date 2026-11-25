"""Ningún archivo repetido en el destino: el control del cierre.

El operador, 2026-11-25: «no quiero en la carpeta ningún archivo repetido,
absolutamente ninguno». Con varios equipos sobre el mismo destino, lo que lo
impide es el reclamo de cada PDF y el turno de cada carpeta NIC
(``adapters.coordinacion_en_disco``); esto lo comprueba al cerrar, sobre el
disco, y dice dónde si algo se coló:

- un nombre con «(2)», «(3)»… -- ``unique_path`` lo pone cuando el nombre ya
  estaba --, y
- dos PDF de una misma carpeta con el mismo contenido, byte a byte. Sólo se
  leen los de igual tamaño, que son pocos: no se vuelve a bajar la entrega.

Lo apartado al rehacer (``_reemplazados``) y lo del bot (el área de
coordinación, las constancias) no cuenta.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..adapters.coordinacion_en_disco import es_del_bot

#: «01_RECLAMO (2).pdf»: el nombre que ``unique_path`` da al segundo.
_CON_NUMERO = re.compile(r"\s\(\d+\)\.[^.]+$")
#: «4133182 - copia», «4133182 - Copia (2)», «4133182 (2)»: una carpeta
#: repetida. El operador, 2026-11-25: «ni siquiera con NIC repetido-copia,
#: nada de eso, todos los archivos deben ser únicos, como están en la fuente».
_CARPETA_REPETIDA = re.compile(r"(?:\s*-\s*copia(?:\s*\(\d+\))?|\s\(\d+\))$", re.IGNORECASE)
_APARTADOS = "_reemplazados"
_EXTENSIONES = (".pdf", ".xlsx")


@dataclass(frozen=True)
class Repetido:
    carpeta: str
    archivos: tuple[str, ...]
    motivo: str

    def en_palabras(self) -> str:
        return f"«{self.carpeta}»: {', '.join(self.archivos)} — {self.motivo}"


def _huella(ruta: Path) -> str:
    resumen = hashlib.sha1()
    with open(ruta, "rb") as archivo:
        for trozo in iter(lambda: archivo.read(1 << 20), b""):
            resumen.update(trozo)
    return resumen.hexdigest()


def buscar_repetidos(
    destino: Path,
    *,
    detener: Callable[[], bool] = lambda: False,
    en_la_fuente: Callable[[str], bool] = lambda relativa: False,
) -> list[Repetido]:
    """Los archivos y carpetas repetidos del destino, con su motivo.

    ``en_la_fuente`` dice si una carpeta con nombre de copia existe así en el
    origen: entonces es del cliente y se replica tal cual.
    """
    repetidos: list[Repetido] = []
    for carpeta, subcarpetas, archivos in os.walk(destino):
        if detener():
            break
        subcarpetas[:] = [s for s in subcarpetas if s != _APARTADOS and not es_del_bot(s)]
        relativa = os.path.relpath(carpeta, destino)
        relativa = "." if relativa == "." else relativa.replace("\\", "/")
        hermanas = {s.casefold() for s in subcarpetas}
        for subcarpeta in subcarpetas:
            if not _CARPETA_REPETIDA.search(subcarpeta):
                continue
            original = _CARPETA_REPETIDA.sub("", subcarpeta)
            ruta = subcarpeta if relativa == "." else f"{relativa}/{subcarpeta}"
            if en_la_fuente(ruta):
                continue
            repetidos.append(
                Repetido(
                    relativa,
                    (f"{subcarpeta}/",),
                    f"carpeta repetida{' de «' + original + '»' if original.casefold() in hermanas else ''}",
                )
            )
        propios = [a for a in archivos if a.lower().endswith(_EXTENSIONES) and not a.startswith((".", "~$"))]
        for nombre in propios:
            if _CON_NUMERO.search(nombre):
                original = _CON_NUMERO.sub(Path(nombre).suffix, nombre)
                repetidos.append(
                    Repetido(relativa, (nombre,), f"nombre repetido (ya había «{original}»)")
                )
        por_tamano: dict[int, list[str]] = defaultdict(list)
        for nombre in propios:
            if not nombre.lower().endswith(".pdf"):
                continue
            try:
                por_tamano[os.path.getsize(os.path.join(carpeta, nombre))].append(nombre)
            except OSError:
                continue
        for nombres in por_tamano.values():
            if len(nombres) < 2:
                continue
            por_huella: dict[str, list[str]] = defaultdict(list)
            for nombre in nombres:
                try:
                    por_huella[_huella(Path(carpeta) / nombre)].append(nombre)
                except OSError:
                    continue
            for iguales in por_huella.values():
                if len(iguales) > 1:
                    repetidos.append(Repetido(relativa, tuple(sorted(iguales)), "mismo contenido, byte a byte"))
    return repetidos
