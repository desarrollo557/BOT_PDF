from pathlib import Path

import pytest
from fakes import (
    BODY,
    FakeAssembler,
    FakeDocumentStore,
    FakeInventoryStore,
    FakeOcr,
    FakePage,
    FakePageSource,
    FakeVision,
)

from resolutions.application.pipeline import ClassificationPipeline, PipelineConfig
from resolutions.application.process_document import ProcessDocument
from resolutions.domain.errors import IntegrityError

DOCUMENT = Path("expediente.pdf")
DESTINATION = Path("/out")


def digital(header):
    return FakePage(text=f"{header}\n{BODY}")


def build(pages, *, vision=None, assembler=None, inventory=None):
    source = FakePageSource(pages=pages)
    use_case = ProcessDocument(
        store=FakeDocumentStore(source=source),
        pipeline=ClassificationPipeline(
            ocr=FakeOcr(), vision=vision, config=PipelineConfig(max_workers=1)
        ),
        assembler=assembler or FakeAssembler(),
        inventory=inventory,
    )
    return use_case, source


class TestHappyPath:
    def test_it_writes_one_file_per_resolution(self):
        assembler = FakeAssembler()
        use_case, _ = build(
            [
                digital("RESOLUCION No. 00412"),
                digital(""),
                digital("RESOLUCION No. 00555"),
                digital("RESOLUCION No. 00412"),
            ],
            assembler=assembler,
        )
        report = use_case.execute(DOCUMENT, DESTINATION)

        assert assembler.written == [("00412", [1, 2, 4]), ("00555", [3])]
        assert [path.name for path in report.outputs] == ["00412.pdf", "00555.pdf"]

    def test_it_always_closes_the_document(self):
        use_case, source = build([digital("RESOLUCION No. 00412")])
        use_case.execute(DOCUMENT, DESTINATION)
        assert source.closed is True

    def test_it_reports_where_the_work_went(self):
        use_case, _ = build([digital("RESOLUCION No. 00412"), digital("")])
        report = use_case.execute(DOCUMENT, DESTINATION)
        assert report.stats["by_provenance"] == {"text_layer": 2}
        assert report.stats["vision_page_ratio"] == 0.0


class TestNaming:
    def test_files_are_named_after_the_code_and_the_subject(self):
        pages = [
            FakePage(text=f"RESOLUCION No. 00412\nASUNTO: Compra de insumos informáticos\n{BODY}"),
            FakePage(text=f"RESOLUCION No. 00555\nDesignación de personal transitorio\n{BODY}"),
        ]
        report = build(pages)[0].execute(DOCUMENT, DESTINATION)
        assert [path.name for path in report.outputs] == [
            "00412__compra-de-insumos-informaticos.pdf",
            "00555__designacion-de-personal-transitorio.pdf",
        ]

    def test_an_unnamed_resolution_still_gets_a_file(self):
        report = build([digital("RESOLUCION No. 00412")])[0].execute(DOCUMENT, DESTINATION)
        assert [path.name for path in report.outputs] == ["00412.pdf"]


class TestInventory:
    def test_it_records_every_file_produced_from_the_source(self):
        store = FakeInventoryStore()
        pages = [
            FakePage(text=f"RESOLUCION No. 00412\nASUNTO: Compra de insumos\n{BODY}"),
            digital(""),
            FakePage(text=f"RESOLUCION No. 00555\nASUNTO: Designación de personal\n{BODY}"),
        ]
        build(pages, inventory=store)[0].execute(DOCUMENT, DESTINATION)

        assert store.recorded is not None
        assert store.recorded.source_document == "expediente.pdf"
        assert store.recorded.source_pages == 3
        assert [(item.code, item.title, item.page_numbers) for item in store.recorded.items] == [
            ("00412", "Compra de insumos", [1, 2]),
            ("00555", "Designación de personal", [3]),
        ]

    def test_the_inventory_accounts_for_every_source_page(self):
        store = FakeInventoryStore()
        pages = [digital(""), digital("RESOLUCION No. 00412"), digital("")]
        build(pages, inventory=store)[0].execute(DOCUMENT, DESTINATION)
        assert store.recorded.quarantine_pages == [1]
        assert store.recorded.pages_accounted_for == 3

    def test_the_inventory_names_match_the_files_on_disk(self):
        store = FakeInventoryStore()
        pages = [FakePage(text=f"RESOLUCION No. 00412\nASUNTO: Compra de insumos\n{BODY}")]
        report = build(pages, inventory=store)[0].execute(DOCUMENT, DESTINATION)
        assert [item.file_name for item in store.recorded.items] == [
            path.name for path in report.outputs
        ]

    def test_the_report_carries_the_inventory_for_the_front_end(self):
        store = FakeInventoryStore()
        report = build([digital("RESOLUCION No. 00412")], inventory=store)[0].execute(
            DOCUMENT, DESTINATION
        )
        payload = report.as_dict()["inventory"]
        assert payload["source_pages"] == 1
        assert payload["generated_files"] == 1
        assert report.inventory_path.name == "inventory.json"

    def test_it_is_optional(self):
        report = build([digital("RESOLUCION No. 00412")])[0].execute(DOCUMENT, DESTINATION)
        assert report.inventory_path is None
        assert report.inventory is not None


class TestReviewQueue:
    def test_head_pages_without_a_code_are_queued_not_guessed(self):
        use_case, _ = build([digital(""), digital("RESOLUCION No. 00412")])
        report = use_case.execute(DOCUMENT, DESTINATION)
        assert [item.page_number for item in report.review_queue] == [1]
        assert report.grouping.quarantine == [1]

    def test_pages_the_model_could_not_read_are_queued(self):
        use_case, _ = build(
            [FakePage(header="RESOLUCION No. 00412", body=BODY), FakePage(header="", body="")],
            vision=FakeVision(answers={2: None}),
        )
        report = use_case.execute(DOCUMENT, DESTINATION)
        assert [item.page_number for item in report.review_queue] == [2]

    def test_a_clean_document_has_an_empty_queue(self):
        use_case, _ = build([digital("RESOLUCION No. 00412"), digital("")])
        assert use_case.execute(DOCUMENT, DESTINATION).review_queue == []


class LosesAPage:
    """A pipeline that drops its last page, the way a crashed worker would."""

    def __init__(self, inner):
        self._inner = inner

    def classify(self, source):
        classifications, stats = self._inner.classify(source)
        return classifications[:-1], stats


class TestFailureContainment:
    def test_nothing_is_written_when_page_accounting_does_not_balance(self):
        assembler = FakeAssembler()
        source = FakePageSource(pages=[digital("RESOLUCION No. 00412"), digital("")])
        use_case = ProcessDocument(
            store=FakeDocumentStore(source=source),
            pipeline=LosesAPage(
                ClassificationPipeline(ocr=FakeOcr(), config=PipelineConfig(max_workers=1))
            ),
            assembler=assembler,
        )

        with pytest.raises(IntegrityError):
            use_case.execute(DOCUMENT, DESTINATION)
        assert assembler.written == []
        assert source.closed is True


class TestSerialisation:
    def test_the_report_is_json_ready_for_the_front_end(self):
        use_case, _ = build([digital("RESOLUCION No. 00412"), digital("")])
        payload = use_case.execute(DOCUMENT, DESTINATION).as_dict()
        assert payload["document"] == "expediente.pdf"
        assert payload["page_count"] == 2
        assert payload["groups"] == [
            {"code": "00412", "title": None, "pages": [1, 2], "size": 2}
        ]
        assert payload["quarantine"] == []
