"""Comprueba que el sistema distingue una resolución de un libro de diplomas.

    python scripts/clasificacion.py DOCUMENTO.pdf [OTRO.pdf ...] [--via ocr]

No inventaría nada ni escribe entregables: ejecuta el mismo clasificador que
corre el servicio -- `domain.doctype.classify_pages`, alimentado por el mismo
muestreo que usa `InventoryDocument` -- y publica el veredicto con las pruebas
que lo sostienen.

La pregunta que responde es la única que importa antes de confiar en un lote
mezclado: **si el documento se reconoce por lo que está impreso, y si se
reconoce igual cuando el único que lee es el OCR.** Por eso hay tres vías:

  * ``auto``  -- lo que hace el servicio: capa de texto y, si la página viene
                 casi vacía, OCR de la banda del encabezado.
  * ``texto`` -- sólo la capa de texto. Un escaneo sin ella queda sin muestra, y
                 eso es exactamente lo que hay que ver.
  * ``ocr``   -- sólo OCR, ignorando la capa de texto aunque exista. Es la vía
                 que prueba que el reconocimiento no depende de que alguien haya
                 pasado el PDF por un OCR antes de entregarlo.

Se apoya en el software, no lo sustituye: si los números salen bien es porque el
clasificador funciona, no porque el script sea listo.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend" / "src"))

from resolutions.adapters.pymupdf_source import PyMuPDFPageSource  # noqa: E402
from resolutions.adapters.tesseract_ocr import HeaderAndPageOcr  # noqa: E402
from resolutions.application.inventory_document import (  # noqa: E402
    MIN_SAMPLE_CHARS,
    SAMPLE_PAGES,
)
from resolutions.application.ports import HEADER_BAND  # noqa: E402
from resolutions.domain.doctype import classify_pages, markers_on_page  # noqa: E402

VIAS = ("auto", "texto", "ocr")


def _paginas_muestreadas(total: int, cuantas: int) -> list[int]:
    """Las mismas páginas que mira el servicio: repartidas de punta a punta."""
    if total == 0:
        return []
    paso = max(1, total // cuantas)
    return list(range(1, total + 1, paso))[:cuantas]


def _texto_de(fuente, numero: int, via: str, ocr) -> tuple[str, str]:
    """El texto de una página y de dónde salió."""
    if via == "ocr":
        return ocr.read(fuente.render(numero, HEADER_BAND, 200)).text, "ocr"

    texto = fuente.text_of(numero)
    if via == "texto":
        return texto, "capa de texto"
    if len(texto) < MIN_SAMPLE_CHARS:
        return ocr.read(fuente.render(numero, HEADER_BAND, 200)).text, "ocr"
    return texto, "capa de texto"


def clasificar(pdf: Path, *, via: str, cuantas: int, ocr) -> dict:
    fuente = PyMuPDFPageSource(pdf)
    try:
        numeros = _paginas_muestreadas(fuente.page_count, cuantas)
        muestra: list[tuple[int, str]] = []
        procedencia: Counter[str] = Counter()
        caracteres: list[int] = []
        fallos: dict[int, str] = {}

        for numero in numeros:
            try:
                texto, de_donde = _texto_de(fuente, numero, via, ocr)
            except Exception as error:  # noqa: BLE001
                fallos[numero] = f"{type(error).__name__}: {error}"
                continue
            procedencia[de_donde] += 1
            caracteres.append(len(texto))
            muestra.append((numero, texto))

        veredicto = classify_pages(muestra)

        # Las pruebas, agrupadas por la frase que las produjo: qué reconoció el
        # sistema y en cuántas páginas, que es lo que hace auditable el fallo.
        por_marcador: Counter[str] = Counter()
        for prueba in veredicto.evidence:
            por_marcador[prueba.marker] += 1

        # Y lo que argumentó por el tipo perdedor, que es donde vive el riesgo de
        # confusión: una resolución que habla de diplomas, o un registro de
        # diploma que cita la resolución que lo autoriza.
        contrarias: Counter[str] = Counter()
        for numero, texto in muestra:
            for prueba in markers_on_page(texto, numero):
                if prueba.document_type is not veredicto.document_type:
                    contrarias[f"{prueba.document_type}: {prueba.marker}"] += 1

        return {
            "documento": pdf.name,
            "ruta": str(pdf),
            "via": via,
            "paginas": fuente.page_count,
            "muestreadas": len(muestra),
            "procedencia": dict(procedencia),
            "caracteres_medios": round(sum(caracteres) / len(caracteres)) if caracteres else 0,
            "tipo": str(veredicto.document_type),
            "tipo_legible": veredicto.document_type.label,
            "confianza": round(veredicto.confidence, 4),
            "puntajes": {str(k): round(v, 3) for k, v in veredicto.scores.items()},
            "identificado": veredicto.is_identified,
            "marcadores": dict(por_marcador.most_common()),
            "marcadores_del_otro_tipo": dict(contrarias.most_common(10)),
            "paginas_ilegibles": fallos,
        }
    finally:
        fuente.close()


def por_pagina(pdf: Path, *, via: str, desde: int, hasta: int, ocr) -> dict:
    """Clasifica cada página por separado, para ver dónde se filtra el otro tipo.

    Un documento se decide sobre la muestra entera, así que una página suelta
    que puntúa al revés no es un error: es el riesgo, y hay que poder medirlo.
    """
    fuente = PyMuPDFPageSource(pdf)
    try:
        hasta = min(hasta, fuente.page_count)
        resultados = []
        for numero in range(desde, hasta + 1):
            try:
                texto, de_donde = _texto_de(fuente, numero, via, ocr)
            except Exception as error:  # noqa: BLE001
                resultados.append({"pagina": numero, "error": str(error)})
                continue
            veredicto = classify_pages([(numero, texto)])
            resultados.append(
                {
                    "pagina": numero,
                    "de": de_donde,
                    "caracteres": len(texto),
                    "tipo": str(veredicto.document_type),
                    "confianza": round(veredicto.confidence, 3),
                    "puntajes": {str(k): round(v, 2) for k, v in veredicto.scores.items()},
                }
            )
        conteo = Counter(r.get("tipo", "error") for r in resultados)
        return {
            "documento": pdf.name,
            "via": via,
            "rango": [desde, hasta],
            "por_tipo": dict(conteo),
            "paginas": resultados,
        }
    finally:
        fuente.close()


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("pdfs", nargs="+", type=Path)
    analizador.add_argument("--via", choices=VIAS, default="auto")
    analizador.add_argument("--paginas", type=int, default=SAMPLE_PAGES)
    analizador.add_argument("--idioma", default="spa")
    analizador.add_argument("--json", type=Path, default=None)
    analizador.add_argument(
        "--por-pagina",
        nargs=2,
        type=int,
        metavar=("DESDE", "HASTA"),
        default=None,
        help="clasificar cada página del rango por separado",
    )
    opciones = analizador.parse_args()

    ocr = HeaderAndPageOcr(language=opciones.idioma)
    informes = []

    for pdf in opciones.pdfs:
        if not pdf.is_file():
            print(f"!! no existe: {pdf}", flush=True)
            continue
        if opciones.por_pagina:
            desde, hasta = opciones.por_pagina
            informe = por_pagina(pdf, via=opciones.via, desde=desde, hasta=hasta, ocr=ocr)
            print(f"» {informe['documento']} [{informe['via']}] págs {desde}-{hasta}")
            print(f"   por tipo: {informe['por_tipo']}")
            for fila in informe["paginas"]:
                if "error" in fila:
                    print(f"   pág {fila['pagina']}: ERROR {fila['error']}")
                else:
                    print(
                        f"   pág {fila['pagina']:>4} [{fila['de']:>13}] "
                        f"{fila['caracteres']:>5} car -> {fila['tipo']:<12} "
                        f"{fila['puntajes']}"
                    )
        else:
            informe = clasificar(pdf, via=opciones.via, cuantas=opciones.paginas, ocr=ocr)
            print(f"» {informe['documento']} [{informe['via']}]")
            print(
                f"   {informe['paginas']} págs · muestreadas {informe['muestreadas']} "
                f"({informe['procedencia']}) · {informe['caracteres_medios']} car/pág"
            )
            print(
                f"   TIPO: {informe['tipo_legible']} · confianza "
                f"{informe['confianza']} · puntajes {informe['puntajes']}"
            )
            print(f"   marcadores: {informe['marcadores']}")
            if informe["marcadores_del_otro_tipo"]:
                print(f"   del otro tipo: {informe['marcadores_del_otro_tipo']}")
            if informe["paginas_ilegibles"]:
                print(f"   ilegibles: {informe['paginas_ilegibles']}")
        informes.append(informe)
        print(flush=True)

    if not opciones.por_pagina and informes:
        print("=" * 70)
        print("tipos reconocidos:", dict(Counter(i["tipo"] for i in informes)))
        sin_identificar = [i["documento"] for i in informes if not i["identificado"]]
        if sin_identificar:
            print("SIN IDENTIFICAR:", sin_identificar)

    if opciones.json:
        opciones.json.parent.mkdir(parents=True, exist_ok=True)
        opciones.json.write_text(
            json.dumps(informes, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"detalle en {opciones.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
