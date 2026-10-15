"""Quién reparte la máquina entre los documentos que corren a la vez.

Hay tres recursos y cada uno tiene su tope:

* **Documentos de carpeta a la vez** (`folder_documents`). Una ranura por
  documento, compartidas por todas las carpetas en marcha: dos carpetas a la
  vez no doblan la carga, se reparten las mismas ranuras por orden de llegada.
* **Hilos de OCR por documento**. Un documento solo usa los que tenga
  configurados (`page_workers`); con varios a la vez se reparten los hilos de
  la máquina, porque tres documentos con ocho Tesseract cada uno en doce hilos
  no leen más rápido, se estorban.
* **Llamadas a la IA a la vez** (`ia_a_la_vez`). Un semáforo del Manager, que
  ven todos los procesos del pool: cada documento pide sus resúmenes y sus
  folios, y sin un tope común el proveedor contesta 429 a todos.

Escala cambiando números, no código: más núcleos, más ranuras
(``RESOLUTIONS_FOLDER_DOCUMENTS``); más cuota con el proveedor, más llamadas
(``RESOLUTIONS_IA_A_LA_VEZ``).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from contextlib import contextmanager

#: Por debajo de esto un documento lee demasiado despacio: dos hilos mantienen
#: ocupado un núcleo mientras el otro rasteriza.
HILOS_MINIMOS = 2


class Planificador:
    def __init__(
        self,
        *,
        documentos_de_carpeta: int,
        hilos_por_documento: int,
        procesos: int,
        hilos_de_la_maquina: int | None = None,
    ) -> None:
        self.documentos_de_carpeta = max(1, documentos_de_carpeta)
        self._hilos_por_documento = max(1, hilos_por_documento)
        self._procesos = max(1, procesos)
        self._hilos_de_la_maquina = max(1, hilos_de_la_maquina or os.cpu_count() or 4)
        self._ranuras: asyncio.Semaphore | None = None
        self.en_curso = 0

    @property
    def ranuras(self) -> asyncio.Semaphore:
        """Las ranuras de las carpetas. Se crean al primer uso, dentro del bucle."""
        if self._ranuras is None:
            self._ranuras = asyncio.Semaphore(self.documentos_de_carpeta)
        return self._ranuras

    def hilos_para(self, documentos: int) -> int:
        """Cuántos hilos de OCR le tocan a cada uno con ``documentos`` corriendo.

        Sólo cuentan los que caben en el pool: los que esperan turno en él no
        están leyendo, y contarlos dejaba a los que sí con dos hilos.
        """
        activos = max(1, min(documentos, self._procesos))
        reparto = self._hilos_de_la_maquina // activos
        return max(HILOS_MINIMOS, min(self._hilos_por_documento, reparto))

    @contextmanager
    def documento(self) -> Iterator[int]:
        """Un documento que entra a procesarse; da los hilos que le tocan."""
        self.en_curso += 1
        try:
            yield self.hilos_para(self.en_curso)
        finally:
            self.en_curso -= 1
