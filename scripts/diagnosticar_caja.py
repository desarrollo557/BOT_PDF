"""Dice, antes de gastar un céntimo, qué libros de una caja se leen solos.

    python scripts/diagnosticar_caja.py "Z:\\...\\00C003269"
    python scripts/diagnosticar_caja.py LIBRO.pdf OTRO.pdf

Existe porque en el archivo de la Universidad conviven dos clases de libro de
registro de diplomas que se parecen por fuera y no se parecen en nada por
dentro:

* Los **mecanografiados** -- 2011 en adelante -- traen el formulario impreso y
  el PDF ya viene con capa de texto. Se cortan y se nombran enteros sin pedirle
  una sola página al motor de pago.
* Los **manuscritos** -- los libros antiguos y los de posgrados de los setenta
  -- traen el formulario impreso y **todo lo que identifica al graduado escrito
  a mano encima**. El OCR local lee el formulario y no lee ni un nombre, así que
  la carpeta sale con los archivos llamados `001`, `002`, `003` y el inventario
  en N/A.

La diferencia no se ve abriendo el PDF por encima -- las dos clases enseñan un
formulario lleno -- y cuesta descubrirla del modo caro: procesando la caja
entera y mirando el resultado. Medido sobre la caja `00C003269`, tres de sus
seis libros se leen solos y tres necesitan ayuda de pago.

Esto lo contesta en unos segundos y **sin pedirle nada a ningún proveedor**: se
limita a mirar la capa de texto de una muestra de caras y a preguntarle al mismo
extractor que usa la habilidad qué saca de ellas.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend" / "src"))

import pymupdf
from resolutions.domain.diploma import TextLine, extract_diploma

#: Cuántas caras se miran de cada libro. Doce: es la misma muestra con que el
#: reconocedor decide de qué tipo es un documento, y basta de sobra para
#: distinguir un libro que se lee solo de uno que no suelta un dato.
MUESTRA = 12

#: Qué proporción de la muestra tiene que traer el dato para dar el libro por
#: legible. Cuatro de cada cinco, no todas: en un empaste de cuatrocientas caras
#: siempre hay alguna torcida, velada o repetida, y exigir el pleno mandaría a
#: pagar libros que se leen perfectamente.
SUFICIENTE = 0.8


class Veredicto:
    SOLO_OCR = "se lee solo -- basta «Solo OCR»"
    SIN_CEDULA = "nombres sí, cédulas no -- mirar si el papel las trae"
    NECESITA_IA = "NECESITA «OCR + IA»"


def mirar(pdf: Path, muestra: int) -> tuple[int, int, int, str]:
    """Cuántas caras de la muestra sueltan cédula y nombre, y qué significa."""
    documento = pymupdf.open(pdf)
    try:
        caras = min(muestra, documento.page_count)
        con_cedula = con_nombre = 0
        for numero in range(1, caras + 1):
            crudo = documento[numero - 1].get_text()
            lineas = [
                TextLine(text=texto.strip(), y=float(indice), x=0.0)
                for indice, texto in enumerate(crudo.splitlines())
                if texto.strip()
            ]
            registro = extract_diploma(lineas, numero)
            con_cedula += bool(registro.identity_creible)
            con_nombre += bool(registro.name)
        paginas = documento.page_count
    finally:
        documento.close()

    if con_cedula >= caras * SUFICIENTE:
        return paginas, con_cedula, con_nombre, Veredicto.SOLO_OCR
    if con_nombre >= caras * SUFICIENTE:
        return paginas, con_cedula, con_nombre, Veredicto.SIN_CEDULA
    return paginas, con_cedula, con_nombre, Veredicto.NECESITA_IA


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "rutas",
        nargs="+",
        type=Path,
        help="carpetas de una caja, o archivos PDF sueltos",
    )
    parser.add_argument(
        "--muestra",
        type=int,
        default=MUESTRA,
        help=f"cuántas caras mirar de cada libro (por omisión {MUESTRA})",
    )
    args = parser.parse_args()

    pdfs: list[Path] = []
    for ruta in args.rutas:
        if ruta.is_dir():
            pdfs.extend(sorted(ruta.glob("*.pdf")))
        elif ruta.suffix.lower() == ".pdf":
            pdfs.append(ruta)
        else:
            print(f"se ignora {ruta}: no es un PDF ni una carpeta", file=sys.stderr)

    if not pdfs:
        print("no se encontró ningún PDF", file=sys.stderr)
        return 1

    print(f"{'archivo':<46} {'págs':>5} {'cédula':>7} {'nombre':>7}  veredicto")
    print("-" * 100)
    necesitan_ia: list[Path] = []
    for pdf in pdfs:
        try:
            paginas, cedulas, nombres, veredicto = mirar(pdf, args.muestra)
        except Exception as error:  # noqa: BLE001 - un libro roto no para la caja
            print(f"{pdf.name[:44]:<46} no se pudo abrir: {error}")
            continue
        caras = min(args.muestra, paginas)
        print(
            f"{pdf.name[:44]:<46} {paginas:>5} "
            f"{cedulas:>3}/{caras:<3} {nombres:>3}/{caras:<3}  {veredicto}"
        )
        if veredicto is Veredicto.NECESITA_IA:
            necesitan_ia.append(pdf)

    if necesitan_ia:
        print(
            f"\n{len(necesitan_ia)} de {len(pdfs)} libros están escritos a mano. "
            "Procesarlos con «Solo OCR» deja la carpeta con los archivos llamados\n"
            "001, 002, 003 y el inventario en N/A, porque no hay nada legible con "
            "que nombrarlos:"
        )
        for pdf in necesitan_ia:
            print(f"  · {pdf.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
