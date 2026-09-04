"""Genera el FUID de los libros de registro de diplomas.

    python scripts/inventario_diplomas.py --plantilla PLANTILLA.xlsx \
        --salida INVENTARIO.xlsx  LIBRO1.pdf LIBRO2.pdf ...

Un solo inventario con todos los libros que se le pasen, numerado del 1 en
adelante y en el orden en que están las páginas de cada PDF. Imprime al
terminar lo que no pudo leer y lo que leyó dos veces distinto, porque un
inventario que no dice dónde dudó no se puede revisar.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend" / "src"))

from resolutions.adapters.fuid_inventory import FuidInventory  # noqa: E402
from resolutions.adapters.pymupdf_source import PyMuPDFPageSource  # noqa: E402
from resolutions.adapters.tesseract_ocr import HeaderAndPageOcr  # noqa: E402
from resolutions.application.diploma_fuid import Ubicacion, filas_del_libro  # noqa: E402
from resolutions.application.fuid import Cabecera  # noqa: E402
from resolutions.application.read_diploma_book import ReadDiplomaBook  # noqa: E402
from resolutions.domain.validation import validate_diplomas  # noqa: E402
from resolutions.application import verified_readings  # noqa: E402

#: Quien produce estos libros, según lo que dicen ellos mismos: "Registro de
#: Diplomas de la Rectoría de la Universidad de Cartagena", firmado en cada
#: folio por el Secretario General.
OFICINA = "SECRETARÍA GENERAL - RECTORÍA"

#: La caja en que llegaron los seis empastes de registro de diplomas. Va igual
#: en todas las filas porque es una sola caja; se cambia con --caja cuando el
#: lote venga de otra.
CAJA = "3269"


def procesar(
    pdf: Path, desde: int, ubicacion: Ubicacion, sin_ocr: bool, verificaciones: list
) -> tuple[list, list, dict]:
    ocr = None if sin_ocr else HeaderAndPageOcr(language="spa")
    lector = ReadDiplomaBook(ocr=ocr)

    fuente = PyMuPDFPageSource(pdf)
    try:
        registros, estadisticas = lector.execute(fuente)
    finally:
        fuente.close()

    registros, corregidas = verified_readings.apply(
        registros, verificaciones, document=pdf.name
    )

    filas = filas_del_libro(
        registros, nombre_del_archivo=pdf.name, ubicacion=ubicacion, desde=desde
    )
    return registros, filas, {
        "estadisticas": estadisticas,
        "hallazgos": validate_diplomas(registros),
        "verificadas": corregidas,
    }


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("pdfs", nargs="+", type=Path)
    analizador.add_argument("--plantilla", required=True, type=Path)
    analizador.add_argument("--salida", required=True, type=Path)
    analizador.add_argument("--caja", default=CAJA)
    analizador.add_argument("--otro", default="N/A")
    analizador.add_argument("--codigo-trd", default="N/A")
    analizador.add_argument("--oficina", default=OFICINA)
    analizador.add_argument("--objeto", default=None)
    analizador.add_argument(
        "--verificaciones",
        type=Path,
        default=RAIZ / "scripts" / "verificaciones" / "diplomas.json",
        help="lecturas comprobadas por una persona, que sustituyen a las del OCR",
    )
    analizador.add_argument(
        "--sin-ocr",
        action="store_true",
        help="sólo la capa de texto, sin escalar a Tesseract (más rápido, menos completo)",
    )
    opciones = analizador.parse_args()

    ubicacion = Ubicacion(
        caja=opciones.caja, otro=opciones.otro, codigo_trd=opciones.codigo_trd
    )

    verificaciones = verified_readings.load(opciones.verificaciones)
    if verificaciones:
        print(f"{len(verificaciones)} lecturas verificadas a mano en {opciones.verificaciones}")

    todas: list = []
    incidencias: list[str] = []
    for pdf in opciones.pdfs:
        print(f"» {pdf.name}", flush=True)
        registros, filas, informe = procesar(
            pdf, len(todas) + 1, ubicacion, opciones.sin_ocr, verificaciones
        )
        todas.extend(filas)

        estadisticas = informe["estadisticas"]
        print(
            f"   {estadisticas.pages} páginas · "
            f"{estadisticas.from_text_layer} por capa de texto · "
            f"{estadisticas.escalated} al OCR · "
            f"{estadisticas.recovered_by_ocr} recuperadas · "
            f"{len(estadisticas.incomplete)} incompletas · "
            f"{len(informe['verificadas'])} verificadas a mano"
        )

        incidencias.extend(
            f"{pdf.name} {hallazgo.describe()}" for hallazgo in informe["hallazgos"]
        )

    destino = FuidInventory(opciones.plantilla).write(
        todas,
        opciones.salida,
        cabecera=Cabecera(oficina_productora=opciones.oficina, objeto=opciones.objeto),
    )
    print(f"\nEscrito {destino}  ({len(todas)} registros)")

    if incidencias:
        print(f"\n{len(incidencias)} incidencias que conviene revisar:")
        for linea in incidencias:
            print(f"   - {linea}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
