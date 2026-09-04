"""End to end over a real PDF, with the real MuPDF adapters.

Only the OCR and vision rungs are faked: every page here carries a text layer,
which is exactly the path the cascade is supposed to take.
"""

from __future__ import annotations

import json

import pytest
from fakes import BODY, FakeOcr

pymupdf = pytest.importorskip("pymupdf")

from resolutions.adapters.file_inventory import FileInventoryStore  # noqa: E402
from resolutions.adapters.pymupdf_assembler import PyMuPDFAssembler  # noqa: E402
from resolutions.adapters.pymupdf_source import PyMuPDFDocumentStore  # noqa: E402
from resolutions.application.pipeline import (  # noqa: E402
    ClassificationPipeline,
    PipelineConfig,
)
from resolutions.application.process_document import ProcessDocument  # noqa: E402

#: Cada página, como se imprime: el encabezado por un lado y el cuerpo por otro.
#:
#: Van separados porque en el papel están separados -- el encabezado centrado en
#: la cabecera de la hoja, el cuerpo debajo -- y porque el separador se fija en
#: dónde está el encabezado, no sólo en lo que dice. Una página sin encabezado
#: lleva ``None`` y hereda la resolución anterior, que es la regla del archivo.
PAGES = [
    ("RESOLUCION No. 00412", "ASUNTO: Compra de insumos informaticos\n" + BODY),
    (None, BODY),
    (None, BODY),
    ("RESOLUCION No. 00555", "ASUNTO: Designacion de personal\n" + BODY),
    (None, BODY),
    # The code comes back after another resolution: same file, per the rules.
    ("RESOLUCION No. 00412", "VISTO la Resolucion No. 00555\n" + BODY),
]


@pytest.fixture
def source_pdf(tmp_path):
    """Un expediente con la forma que tienen los de verdad.

    El encabezado va **centrado y en la cabecera de la hoja**, que es como se
    imprimen las resoluciones de la Universidad y lo que el separador exige para
    abrir una unidad documental. Antes se metía todo en una caja pegada al
    margen izquierdo: el texto era el mismo pero la página no se parecía a
    ninguna real, y una regla que mira dónde está el encabezado no tenía forma
    de pasar aquí.
    """
    document = pymupdf.open()
    for encabezado, cuerpo in PAGES:
        page = document.new_page()
        if encabezado:
            # Centrado y arriba, como en el papel.
            page.insert_textbox(
                pymupdf.Rect(56, 64, 540, 96),
                encabezado,
                fontsize=12,
                align=pymupdf.TEXT_ALIGN_CENTER,
            )
        # Y el cuerpo debajo. Una caja porque envuelve: `insert_text` sacaría el
        # texto por el borde y la capa extraída saldría truncada.
        page.insert_textbox(pymupdf.Rect(56, 110, 540, 780), cuerpo, fontsize=11)
    path = tmp_path / "expediente.pdf"
    document.save(path)
    document.close()
    return path


@pytest.fixture
def report(source_pdf, tmp_path):
    use_case = ProcessDocument(
        store=PyMuPDFDocumentStore(),
        pipeline=ClassificationPipeline(ocr=FakeOcr(), config=PipelineConfig(max_workers=2)),
        assembler=PyMuPDFAssembler(),
        inventory=FileInventoryStore(),
    )
    return use_case.execute(source_pdf, tmp_path / "out")


def test_it_splits_the_document_by_resolution(report):
    assert {group.code.value: group.page_numbers for group in report.grouping.groups} == {
        "00412": [1, 2, 3, 6],
        "00555": [4, 5],
    }


def test_the_cited_resolution_never_steals_the_page(report):
    # Page 6 names 0555 under VISTO and 0412 as its heading. It belongs to 0412.
    assert report.classifications[5].code.value == "00412"


def test_the_files_are_named_after_what_they_are_and_their_number(report):
    """El nombre que pidió el operador: la palabra, un guion bajo y el número."""
    assert sorted(path.name for path in report.outputs) == [
        "RESOLUCION_00412.pdf",
        "RESOLUCION_00555.pdf",
    ]


def test_the_written_pdfs_hold_the_expected_pages(report):
    sizes = {}
    for path in report.outputs:
        with pymupdf.open(path) as document:
            sizes[path.name] = document.page_count
    assert sizes == {
        "RESOLUCION_00412.pdf": 4,
        "RESOLUCION_00555.pdf": 2,
    }


def test_no_page_is_lost_or_duplicated(report):
    report.grouping.verify_integrity(total_pages=len(PAGES))
    assert report.inventory.pages_accounted_for == len(PAGES)


def test_the_inventory_lands_next_to_the_files(report, tmp_path):
    payload = json.loads((tmp_path / "out" / "inventory.json").read_text(encoding="utf-8"))
    assert payload["source_document"] == "expediente.pdf"
    assert payload["generated_files"] == 2
    assert [item["file_name"] for item in payload["items"]] == [
        "RESOLUCION_00412.pdf",
        "RESOLUCION_00555.pdf",
    ]

    csv_text = (tmp_path / "out" / "inventory.csv").read_text(encoding="utf-8-sig")
    assert "1-3,6" in csv_text  # page ranges stay readable in a spreadsheet


def test_every_page_was_answered_by_the_text_layer(report):
    """El OCR sí interviene, pero sólo para contrastar lo que ya se leyó.

    Ninguna página necesitó que se la leyera de otra forma -- eso es lo que
    dice `by_provenance` -- y ninguna quedó sin resolver. La relectura de los
    encabezados con OCR es una comprobación, no un peldaño: no cambia de dónde
    salió la respuesta.
    """
    assert report.stats["by_provenance"] == {"text_layer": len(PAGES)}
    assert report.stats["escalated"] == 0


def test_the_declarations_were_contrasted_against_the_ocr(report):
    """Y las dos lecturas coincidieron, que es lo que hace fiable el resultado."""
    assert report.stats["verified"] >= 1
    assert report.stats["disagreements"] == {}


def test_the_document_was_recognised_as_resolutions(report):
    """El tipo se decide por lo que está impreso, y viaja en el informe."""
    assert report.stats["document_type"] == "resolucion"
    assert report.stats["type_confidence"] > 0.5
