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
from resolutions.application.pipeline import ClassificationPipeline, PipelineConfig  # noqa: E402
from resolutions.application.process_document import ProcessDocument  # noqa: E402

PAGES = [
    "RESOLUCION N° 0412/2024\nASUNTO: Compra de insumos informaticos\n" + BODY,
    BODY,
    BODY,
    "RESOLUCION N° 0555/2024\nASUNTO: Designacion de personal\n" + BODY,
    BODY,
    # The code comes back after another resolution: same file, per the rules.
    "RESOLUCION N° 0412/2024\nVISTO la Resolucion N° 0555/2024\n" + BODY,
]


@pytest.fixture
def source_pdf(tmp_path):
    document = pymupdf.open()
    for text in PAGES:
        page = document.new_page()
        # A text box wraps; insert_text would run the body off the page edge and
        # the extracted layer would come back truncated.
        page.insert_textbox(pymupdf.Rect(56, 64, 540, 780), text, fontsize=11)
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
        "0412/2024": [1, 2, 3, 6],
        "0555/2024": [4, 5],
    }


def test_the_cited_resolution_never_steals_the_page(report):
    # Page 6 names 0555 under VISTO and 0412 as its heading. It belongs to 0412.
    assert report.classifications[5].code.value == "0412/2024"


def test_the_files_are_named_after_code_and_subject(report):
    assert sorted(path.name for path in report.outputs) == [
        "0412-2024__compra-de-insumos-informaticos.pdf",
        "0555-2024__designacion-de-personal.pdf",
    ]


def test_the_written_pdfs_hold_the_expected_pages(report):
    sizes = {}
    for path in report.outputs:
        with pymupdf.open(path) as document:
            sizes[path.name] = document.page_count
    assert sizes == {
        "0412-2024__compra-de-insumos-informaticos.pdf": 4,
        "0555-2024__designacion-de-personal.pdf": 2,
    }


def test_no_page_is_lost_or_duplicated(report):
    report.grouping.verify_integrity(total_pages=len(PAGES))
    assert report.inventory.pages_accounted_for == len(PAGES)


def test_the_inventory_lands_next_to_the_files(report, tmp_path):
    payload = json.loads((tmp_path / "out" / "inventory.json").read_text(encoding="utf-8"))
    assert payload["source_document"] == "expediente.pdf"
    assert payload["generated_files"] == 2
    assert [item["file_name"] for item in payload["items"]] == [
        "0412-2024__compra-de-insumos-informaticos.pdf",
        "0555-2024__designacion-de-personal.pdf",
    ]

    csv_text = (tmp_path / "out" / "inventory.csv").read_text(encoding="utf-8-sig")
    assert "1-3,6" in csv_text  # page ranges stay readable in a spreadsheet


def test_the_document_never_reached_the_ocr_engine(report):
    assert report.stats["by_provenance"] == {"text_layer": len(PAGES)}
    assert report.stats["escalated"] == 0
