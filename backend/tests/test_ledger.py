"""The durable inventory.

A per-document ``inventory.json`` answers "what came out of this file". After a
few hundred documents the question becomes "which document did 00086 come
from", and that needs one index across every run. It has to outlive the job
registry, because clearing the screen must never erase the record that the work
happened.
"""

from __future__ import annotations

import json

from resolutions.adapters.ledger import InventoryLedger


def report(document="expediente.pdf", items=None):
    return {
        "document": document,
        "inventory": {
            "source_document": document,
            "source_pages": 7,
            "items": items
            if items is not None
            else [
                {
                    "file_name": "00086__acta.pdf",
                    "code": "00086",
                    "title": "Por la cual se adopta el manual",
                    "page_count": 3,
                    "first_page": 1,
                    "last_page": 3,
                    "page_numbers": [1, 2, 3],
                }
            ],
        },
    }


class TestRecording:
    def test_a_finished_document_adds_one_row_per_generated_file(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")
        assert ledger.record("job-1", report()) == 1
        assert [row["code"] for row in ledger.rows()] == ["00086"]

    def test_the_source_document_travels_with_every_row(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")
        ledger.record("job-1", report(document="lote-marzo.pdf"))
        assert ledger.rows()[0]["source_document"] == "lote-marzo.pdf"

    def test_pages_are_recorded_as_ranges_not_as_every_number(self, tmp_path):
        # A forty-page block reads as "12-51" instead of forty integers.
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")
        ledger.record(
            "job-1",
            report(
                items=[
                    {
                        "file_name": "a.pdf",
                        "code": "00086",
                        "title": None,
                        "page_count": 5,
                        "first_page": 1,
                        "last_page": 9,
                        "page_numbers": [1, 2, 3, 8, 9],
                    }
                ]
            ),
        )
        assert ledger.rows()[0]["pages"] == "1-3,8-9"

    def test_a_document_that_produced_nothing_records_nothing(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")
        assert ledger.record("job-1", report(items=[])) == 0
        assert ledger.rows() == []

    def test_a_split_diploma_without_inventory_items_is_still_recorded(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")
        report_payload = {
            "document": "libro-diplomas.pdf",
            "page_count": 2,
            "groups": [
                {"code": "22793650", "title": "ALIX JOSEFINA MARIN", "pages": [1], "size": 1},
                {"code": "22793651", "title": "LUIS PEREZ", "pages": [2], "size": 1},
            ],
            "outputs": ["22793650__alix-josefina-marin.pdf", "22793651__luis-perez.pdf"],
        }
        assert ledger.record("job-diploma", report_payload) == 2
        assert [row["source_document"] for row in ledger.rows()] == [
            "libro-diplomas.pdf",
            "libro-diplomas.pdf",
        ]
        assert [row["file_name"] for row in ledger.rows()] == [
            "22793651__luis-perez.pdf",
            "22793650__alix-josefina-marin.pdf",
        ]

    def test_rows_come_back_newest_first(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")
        ledger.record("job-1", report(document="primero.pdf"))
        ledger.record("job-2", report(document="segundo.pdf"))
        assert [row["source_document"] for row in ledger.rows()] == [
            "segundo.pdf",
            "primero.pdf",
        ]

    def test_recording_appends_rather_than_rewriting(self, tmp_path):
        # 50,000 rows in, a rewrite per document would dominate the run.
        path = tmp_path / "inventory.jsonl"
        ledger = InventoryLedger(path)
        ledger.record("job-1", report())
        first_size = path.stat().st_size
        ledger.record("job-2", report())
        assert path.stat().st_size > first_size
        assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2


class TestResilience:
    def test_a_missing_ledger_reads_as_empty(self, tmp_path):
        assert InventoryLedger(tmp_path / "nope.jsonl").rows() == []

    def test_a_torn_line_costs_one_row_not_the_ledger(self, tmp_path):
        # What a hard kill mid-append actually leaves behind.
        path = tmp_path / "inventory.jsonl"
        ledger = InventoryLedger(path)
        ledger.record("job-1", report())
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"code": "0009')
        assert len(ledger.rows()) == 1

    def test_the_parse_is_cached_until_the_file_changes(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")
        ledger.record("job-1", report())
        assert ledger.rows() is ledger.rows()

    def test_the_cache_is_dropped_when_a_row_is_added(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")
        ledger.record("job-1", report())
        ledger.rows()
        ledger.record("job-2", report())
        assert len(ledger.rows()) == 2


class TestQuerying:
    def build(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")
        ledger.record("job-1", report(document="marzo.pdf"))
        ledger.record(
            "job-2",
            report(
                document="abril.pdf",
                items=[
                    {
                        "file_name": "00072__designacion.pdf",
                        "code": "00072",
                        "title": "Por la cual se designa personal",
                        "page_count": 2,
                        "first_page": 4,
                        "last_page": 5,
                        "page_numbers": [4, 5],
                    }
                ],
            ),
        )
        return ledger

    def test_the_summary_counts_documents_and_resolutions(self, tmp_path):
        summary = self.build(tmp_path).summary()
        assert summary["resolutions"] == 2
        assert summary["documents"] == 2
        assert summary["codes"] == 2
        assert summary["pages"] == 5

    def test_job_ids_are_reported_so_their_output_is_never_swept(self, tmp_path):
        assert self.build(tmp_path).job_ids() == {"job-1", "job-2"}

    def test_the_csv_carries_a_header_and_every_row(self, tmp_path):
        csv = self.build(tmp_path).as_csv()
        lines = csv.strip().splitlines()
        assert lines[0].startswith("recorded_at,source_document,code")
        assert len(lines) == 3


class TestInventoryEndpoint:
    def test_the_inventory_survives_clearing_the_screen(self, client):
        from pathlib import Path

        from resolutions.api import main

        job = main.registry.create("expediente.pdf", Path("expediente.pdf"))
        main.registry.mark_done(job, report())
        main.ledger.record(job.id, report())

        client.request("DELETE", "/api/jobs")
        assert client.get("/api/jobs").json() == {"jobs": []}

        payload = client.get("/api/inventory").json()
        assert payload["total"] == 1
        assert payload["rows"][0]["code"] == "00086"

    def test_the_inventory_can_be_searched(self, client):
        from resolutions.api import main

        main.ledger.record("job-1", report(document="marzo.pdf"))
        assert client.get("/api/inventory?q=00086").json()["total"] == 1
        assert client.get("/api/inventory?q=nada").json()["total"] == 0

    def test_the_inventory_exports_as_csv_excel_can_open(self, client):
        from resolutions.api import main

        main.ledger.record("job-1", report())
        response = client.get("/api/inventory.csv")
        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        # The BOM is what stops Excel mangling the accents in a title.
        assert response.text.startswith("﻿")

    def test_an_empty_inventory_is_not_an_error(self, client):
        payload = client.get("/api/inventory").json()
        assert payload == {
            "rows": [],
            "total": 0,
            "offset": 0,
            "limit": 500,
            "summary": {"resolutions": 0, "documents": 0, "codes": 0, "pages": 0},
        }


class TestSourceNaming:
    """The inventory records the operator's filename, never the stored one."""

    def build(self, tmp_path, source_name=None):
        from fakes import (
            FakeAssembler,
            FakeDocumentStore,
            FakeOcr,
            FakePage,
            FakePageSource,
        )

        from resolutions.adapters.file_inventory import FileInventoryStore
        from resolutions.application.pipeline import ClassificationPipeline
        from resolutions.application.process_document import ProcessDocument

        pages = [FakePage(text="RESOLUCION NO. 00086\n" + "x" * 200), FakePage(text="y" * 300)]
        use_case = ProcessDocument(
            store=FakeDocumentStore(FakePageSource(pages)),
            pipeline=ClassificationPipeline(ocr=FakeOcr()),
            assembler=FakeAssembler(),
            inventory=FileInventoryStore(),
        )
        # What an upload actually looks like on disk: a generated hex name.
        stored = tmp_path / "9f2c4be71a084e5d8c0b1f3a5d7e9c11.pdf"
        return use_case.execute(stored, tmp_path / "out", source_name=source_name)

    def test_the_operators_filename_reaches_the_inventory(self, tmp_path):
        report = self.build(tmp_path, source_name="RESOLUCIONES 00960.pdf")
        assert report.as_dict()["inventory"]["source_document"] == "RESOLUCIONES 00960.pdf"
        assert report.as_dict()["document"] == "RESOLUCIONES 00960.pdf"

    def test_without_one_it_falls_back_to_the_path(self, tmp_path):
        report = self.build(tmp_path)
        assert report.as_dict()["document"].endswith(".pdf")

    def test_the_ledger_row_carries_it_too(self, tmp_path):
        report = self.build(tmp_path, source_name="RESOLUCIONES 00960.pdf")
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")
        ledger.record("job-1", report.as_dict())
        assert ledger.rows()[0]["source_document"] == "RESOLUCIONES 00960.pdf"


class TestDocumentHistory:
    """The ledger folded back into the documents the resolutions came from.

    This is what the processed screen reads, so it has to survive a screen
    clear and a restart -- the two moments the registry forgets everything.
    """

    def build(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")
        ledger.record("job-1", report(document="marzo.pdf"))
        ledger.record(
            "job-2",
            report(
                document="abril.pdf",
                items=[
                    {
                        "file_name": "00072__a.pdf",
                        "code": "00072",
                        "title": "Una",
                        "page_count": 2,
                        "first_page": 1,
                        "last_page": 2,
                        "page_numbers": [1, 2],
                    },
                    {
                        "file_name": "00073__b.pdf",
                        "code": "00073",
                        "title": "Otra",
                        "page_count": 4,
                        "first_page": 3,
                        "last_page": 6,
                        "page_numbers": [3, 4, 5, 6],
                    },
                ],
            ),
        )
        return ledger

    def test_each_source_document_appears_once(self, tmp_path):
        documents = self.build(tmp_path).documents()
        assert [d["source_document"] for d in documents] == ["abril.pdf", "marzo.pdf"]

    def test_its_resolutions_and_pages_are_totalled(self, tmp_path):
        latest = self.build(tmp_path).documents()[0]
        assert latest["resolutions"] == 2
        assert latest["pages"] == 6

    def test_it_carries_the_date_it_was_processed(self, tmp_path):
        latest = self.build(tmp_path).documents()[0]
        assert latest["processed_at"]

    def test_a_few_codes_travel_along_to_recognise_it_by(self, tmp_path):
        latest = self.build(tmp_path).documents()[0]
        assert sorted(latest["codes"]) == ["00072", "00073"]

    def test_an_empty_ledger_has_no_documents(self, tmp_path):
        assert InventoryLedger(tmp_path / "nope.jsonl").documents() == []


class TestDocumentsEndpoint:
    def test_the_history_survives_clearing_the_screen(self, client):
        from pathlib import Path

        from resolutions.api import main

        job = main.registry.create("expediente.pdf", Path("expediente.pdf"))
        main.registry.mark_done(job, report())
        main.ledger.record(job.id, report())

        client.request("DELETE", "/api/jobs")

        payload = client.get("/api/documents").json()
        assert payload["total"] == 1
        assert payload["documents"][0]["source_document"] == "expediente.pdf"

    def test_it_can_be_searched_by_document_or_by_code(self, client):
        from resolutions.api import main

        main.ledger.record("job-1", report(document="marzo.pdf"))
        assert client.get("/api/documents?q=marzo").json()["total"] == 1
        assert client.get("/api/documents?q=00086").json()["total"] == 1
        assert client.get("/api/documents?q=nada").json()["total"] == 0

    def test_an_empty_history_is_not_an_error(self, client):
        payload = client.get("/api/documents").json()
        assert payload["documents"] == [] and payload["total"] == 0


class TestDocumentSearch:
    """Searching the history has to reach every resolution, not just a sample."""

    def build(self, client, codes):
        from resolutions.api import main

        items = [
            {
                "file_name": f"{code}__x.pdf",
                "code": code,
                "title": f"Titulo {code}",
                "page_count": 1,
                "first_page": 1,
                "last_page": 1,
                "page_numbers": [1],
            }
            for code in codes
        ]
        main.ledger.record("job-1", report(document="expediente.pdf", items=items))

    def test_a_code_past_the_sample_is_still_found(self, client):
        # The document carries eight codes for recognition; the twentieth is
        # just as real, and a search that misses it is a search that lies.
        self.build(client, [f"{index:05d}" for index in range(20)])
        assert client.get("/api/documents?q=00019").json()["total"] == 1

    def test_a_title_is_searchable_too(self, client):
        self.build(client, ["00086"])
        assert client.get("/api/documents?q=titulo 00086").json()["total"] == 1

    def test_something_absent_still_returns_nothing(self, client):
        self.build(client, ["00086"])
        assert client.get("/api/documents?q=99999").json()["total"] == 0


class TestDocumentFacts:
    """The archive shows a card per document, so the row carries what it needs.

    Without these the card had blanks exactly where the size and the review
    count belong, and a blank reads as zero rather than as "not recorded".
    """

    def test_the_size_and_review_count_are_recorded(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")
        payload = report()
        payload["page_count"] = 7
        payload["review_queue"] = [{"page": 1, "reason": "x"}, {"page": 2, "reason": "y"}]
        ledger.record("job-1", payload, operator="Ana", source_bytes=4096)

        document = ledger.documents()[0]
        assert document["bytes"] == 4096
        assert document["review"] == 2
        assert document["source_pages"] == 7

    def test_a_document_with_nothing_pending_records_zero(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")
        ledger.record("job-1", report(), source_bytes=100)
        assert ledger.documents()[0]["review"] == 0

    def test_older_rows_without_these_fields_still_read(self, tmp_path):
        # A ledger written before the fields existed must not break the archive.
        path = tmp_path / "inventory.jsonl"
        path.write_text(
            json.dumps(
                {
                    "recorded_at": "2026-01-01T00:00:00+00:00",
                    "source_document": "viejo.pdf",
                    "code": "00086",
                    "file_name": "a.pdf",
                    "page_count": 3,
                    "job_id": "job-viejo",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        document = InventoryLedger(path).documents()[0]
        assert document["bytes"] == 0
        assert document["review"] == 0
        assert document["source_document"] == "viejo.pdf"
