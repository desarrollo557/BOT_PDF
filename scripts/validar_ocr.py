"""Mide cuánto se lee bien, por tipo de documento.

    python scripts/validar_ocr.py DOCUMENTO.pdf [OTRO.pdf ...]

No genera ningún entregable: ejecuta el mismo caso de uso que corre el servicio
-- `InventoryDocument` -- sobre los documentos que se le den, y publica lo que
la comprobación encontró. Sirve para responder con números la única pregunta que
importa antes de confiar en un inventario: en qué páginas la lectura no se
sostiene, y por qué.

Se apoya en el software, no lo sustituye. Si estos números son buenos es porque
el sistema lee bien, no porque el script sea listo.
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
from resolutions.application.inventory_document import InventoryDocument  # noqa: E402
from resolutions.application.pipeline import ClassificationPipeline  # noqa: E402
from resolutions.domain.validation import Severity  # noqa: E402


def validar(pdf: Path) -> dict:
    ocr = HeaderAndPageOcr(language="spa")
    caso = InventoryDocument(ocr=ocr, pipeline=ClassificationPipeline(ocr=ocr))

    fuente = PyMuPDFPageSource(pdf)
    try:
        resultado = caso.execute(fuente, document_name=pdf.name)
    finally:
        fuente.close()

    errores = [i for i in resultado.issues if i.severity is Severity.ERROR]
    paginas_con_error = {i.page_number for i in errores if i.page_number}
    lectura = resultado.reading

    return {
        "documento": pdf.name,
        "tipo": str(resultado.document_type),
        "tipo_legible": resultado.document_type.label,
        "confianza": round(resultado.verdict.confidence, 4),
        "paginas": resultado.page_count,
        "registros": len(resultado.rows),
        "errores": len(errores),
        "avisos": len(resultado.issues) - len(errores),
        "paginas_con_error": sorted(paginas_con_error),
        "paginas_limpias": resultado.page_count - len(paginas_con_error),
        "por_campo": dict(Counter(i.field for i in resultado.issues)),
        "lectura": lectura.as_dict() if lectura else None,
        "hallazgos": [i.describe() for i in resultado.issues],
    }


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("pdfs", nargs="+", type=Path)
    analizador.add_argument("--json", type=Path, default=None)
    analizador.add_argument(
        "--detalle", action="store_true", help="listar cada hallazgo, no sólo el recuento"
    )
    opciones = analizador.parse_args()

    informes = []
    for pdf in opciones.pdfs:
        print(f"» {pdf.name}", flush=True)
        informe = validar(pdf)
        informes.append(informe)

        limpio = 100 * informe["paginas_limpias"] / informe["paginas"] if informe["paginas"] else 0
        print(f"   tipo: {informe['tipo_legible']} (confianza {informe['confianza']})")
        print(f"   páginas: {informe['paginas']} · registros: {informe['registros']}")
        if informe["lectura"]:
            lectura = informe["lectura"]
            print(
                f"   leídas por capa de texto: {lectura['from_text_layer']} · "
                f"al OCR: {lectura['escalated']} · resueltas por el OCR: "
                f"{lectura['recovered_by_ocr']}"
            )
        print(
            f"   páginas sin ningún error: {informe['paginas_limpias']}/{informe['paginas']} "
            f"({limpio:.1f} %)"
        )
        print(f"   errores: {informe['errores']} · avisos: {informe['avisos']}")
        if informe["por_campo"]:
            print(f"   por campo: {informe['por_campo']}")
        if opciones.detalle:
            for hallazgo in informe["hallazgos"]:
                print(f"      - {hallazgo}")
        print(flush=True)

    total_paginas = sum(i["paginas"] for i in informes)
    total_limpias = sum(i["paginas_limpias"] for i in informes)
    print("=" * 60)
    print(f"{len(informes)} documentos · {total_paginas} páginas")
    if total_paginas:
        print(
            f"páginas sin ningún error: {total_limpias}/{total_paginas} "
            f"({100 * total_limpias / total_paginas:.1f} %)"
        )
    por_tipo = Counter(i["tipo_legible"] for i in informes)
    print("tipos reconocidos:", dict(por_tipo))

    if opciones.json:
        opciones.json.write_text(
            json.dumps(informes, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"detalle en {opciones.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
