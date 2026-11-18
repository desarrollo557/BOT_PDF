"""Rehace las métricas de la extracción de una entrega y la compara con otra anterior.

Uso:
    python scripts/metricas_de_la_extraccion.py <destino> [--anterior <destino de la primera ejecución>]

Escribe en <destino> «00.METRICAS DE LA EXTRACCION.xlsx» y «00.EVIDENCIA DE LA
EXTRACCION.xlsx». Con --anterior añade la hoja «Comparación», NIC por NIC:
documentos, con RE, sin fecha y los nombres que cambiaron. Sólo lee las
constancias de cada entrega: no abre ningún PDF ni paga nada. La corrida ya
escribe las métricas al cerrar; esto es para la comparación o para rehacerlas.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from resolutions.api.metricas import escribir_las_metricas


def main() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("destino", type=Path)
    argumentos.add_argument("--anterior", type=Path, default=None)
    leidos = argumentos.parse_args()
    if not leidos.destino.is_dir():
        print(f"No existe la carpeta {leidos.destino}")
        return 1
    if leidos.anterior is not None and not leidos.anterior.is_dir():
        print(f"No existe la carpeta anterior {leidos.anterior}")
        return 1
    for ruta in escribir_las_metricas(leidos.destino, leidos.anterior):
        print(f"Escrito: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
