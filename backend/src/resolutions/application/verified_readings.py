"""Lecturas verificadas por una persona contra la imagen de la página.

Cuando el OCR entrega "ELI2ABETH" no hay forma de saber desde el texto qué
letra perdió el escáner: pudo ser una Z y pudo ser otra cosa. Adivinarla sería
inventar un dato, y esa es justamente la línea que este sistema no cruza. Lo
que sí se puede hacer es que alguien abra la página, lea el papel y deje su
lectura anotada aquí, con el archivo y la página a los que corresponde.

El archivo de verificaciones es la memoria de ese trabajo. Sin él, cada vez que
se regenerara el inventario habría que volver a revisar las mismas páginas, y
el inventario entregado y el regenerado dirían cosas distintas.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from ..domain.diploma import DiplomaRecord, extract_diploma_warnings

#: Los campos que una persona puede corregir. Deliberadamente cortos: si hiciera
#: falta corregir la página entera, lo que está mal es la digitalización.
CAMPOS = ("folio", "registered_folio", "book", "name", "identity_number", "degree",
          "graduation_date")


@dataclass(frozen=True, slots=True)
class VerifiedReading:
    """Lo que una persona leyó en una página concreta de un archivo concreto."""

    document: str
    page_number: int
    values: dict[str, str]
    verified_by: str | None = None
    verified_at: str | None = None

    @property
    def key(self) -> tuple[str, int]:
        return (self.document, self.page_number)


def load(path: Path) -> list[VerifiedReading]:
    """Lee el archivo de verificaciones. Un archivo ausente no es un error."""
    if not Path(path).is_file():
        return []
    crudo = json.loads(Path(path).read_text(encoding="utf-8"))
    lecturas: list[VerifiedReading] = []
    for entrada in crudo:
        valores = {
            campo: str(entrada[campo])
            for campo in CAMPOS
            if entrada.get(campo) not in (None, "")
        }
        if not valores:
            continue
        lecturas.append(
            VerifiedReading(
                document=str(entrada["document"]),
                page_number=int(entrada["page"]),
                values=valores,
                verified_by=entrada.get("verified_by"),
                verified_at=entrada.get("verified_at"),
            )
        )
    return lecturas


def apply(
    records: Sequence[DiplomaRecord],
    readings: Iterable[VerifiedReading],
    *,
    document: str,
) -> tuple[list[DiplomaRecord], list[int]]:
    """Sustituye lo leído por la máquina por lo leído por una persona.

    Devuelve también las páginas tocadas, porque quien firma el inventario tiene
    derecho a saber cuáles de sus filas no vienen del OCR.
    """
    por_pagina = {
        lectura.page_number: lectura
        for lectura in readings
        if lectura.document == document
    }
    if not por_pagina:
        return list(records), []

    corregidas: list[int] = []
    salida: list[DiplomaRecord] = []
    for record in records:
        lectura = por_pagina.get(record.page_number)
        if lectura is None:
            salida.append(record)
            continue
        corregidas.append(record.page_number)
        # Los avisos se recalculan: un nombre verificado deja de estar en duda,
        # y si la persona anotó algo que sigue sin cuadrar, se vuelve a avisar.
        salida.append(extract_diploma_warnings(replace(record, **lectura.values)))
    return salida, corregidas
