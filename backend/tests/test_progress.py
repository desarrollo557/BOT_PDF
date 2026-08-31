from pathlib import Path

import pytest
from fakes import (
    BODY,
    FakeAssembler,
    FakeDocumentStore,
    FakeOcr,
    FakePage,
    FakePageSource,
)

from resolutions.application.pipeline import ClassificationPipeline, PipelineConfig
from resolutions.application.process_document import ProcessDocument
from resolutions.application.progress import RecordingProgressReporter, Stage

DOCUMENT = Path("expediente.pdf")
DESTINATION = Path("/out")


def digital(header):
    return FakePage(text=f"{header}\n{BODY}")


class ExplodingOcr:
    """Fails on demand, to prove one bad page does not sink the document."""

    def __init__(self, fail_on: set[int]):
        self.fail_on = fail_on
        self.seen = 0

    def read(self, image_png: bytes):
        self.seen += 1
        raise RuntimeError("tesseract died")


class ExplodingSource(FakePageSource):
    """A source whose render blows up for specific pages."""

    def __init__(self, pages, broken: set[int]):
        super().__init__(pages=pages)
        self.broken = broken

    def render(self, page_number: int, band=None, dpi: int = 200) -> bytes:
        if page_number in self.broken:
            raise OSError(f"page {page_number} is corrupt")
        return super().render(page_number, band, dpi)


def run(pages, *, source=None, ocr=None, progress=None):
    source = source or FakePageSource(pages=pages)
    pipeline = ClassificationPipeline(
        ocr=ocr or FakeOcr(),
        config=PipelineConfig(max_workers=1),
        progress=progress,
    )
    use_case = ProcessDocument(
        store=FakeDocumentStore(source=source),
        pipeline=pipeline,
        assembler=FakeAssembler(),
        progress=progress,
    )
    return use_case.execute(DOCUMENT, DESTINATION)


class TestPageTelemetry:
    def test_it_announces_the_page_count_before_any_work(self):
        recorder = RecordingProgressReporter()
        run([digital("RESOLUCION N° 0412/2024")] * 3, progress=recorder)
        first = recorder.events[0]
        assert first.stage is Stage.OPENED
        assert first.page_count == 3

    def test_it_emits_one_event_per_page_with_the_rung_that_answered(self):
        recorder = RecordingProgressReporter()
        run(
            [digital("RESOLUCION N° 0412/2024"), FakePage(header="RESOLUCION N° 0555/2024")],
            progress=recorder,
        )
        pages = [event for event in recorder.events if event.stage is Stage.PAGE]
        assert [(event.page_number, event.provenance) for event in pages] == [
            (1, "text_layer"),
            (2, "ocr_region"),
        ]

    def test_it_walks_the_stages_in_order(self):
        recorder = RecordingProgressReporter()
        run([digital("RESOLUCION N° 0412/2024")], progress=recorder)
        assert recorder.stages() == ["opened", "page", "grouping", "assembling", "done"]

    def test_a_broken_reporter_never_breaks_the_document(self):
        class Hostile:
            def emit(self, event):
                raise RuntimeError("telemetry is down")

        report = run([digital("RESOLUCION N° 0412/2024")], progress=Hostile())
        assert report.grouping.groups[0].code.value == "0412/2024"


class TestPageFailureIsolation:
    def test_one_unreadable_page_does_not_lose_the_document(self):
        pages = [digital("RESOLUCION N° 0412/2024"), FakePage(header="", body=""), digital("")]
        report = run(pages, source=ExplodingSource(pages, broken={2}))

        # Page 2 blew up; pages 1 and 3 still landed in their group.
        assert report.grouping.groups[0].page_numbers == [1, 2, 3]
        report.grouping.verify_integrity(total_pages=3)

    def test_the_failure_is_recorded_against_its_page(self):
        pages = [digital("RESOLUCION N° 0412/2024"), FakePage(header="", body="")]
        report = run(pages, source=ExplodingSource(pages, broken={2}))
        assert "2" in report.stats["failed_pages"]
        assert "corrupt" in report.stats["failed_pages"]["2"]

    def test_a_failed_page_is_sent_to_review_not_guessed(self):
        pages = [digital("RESOLUCION N° 0412/2024"), FakePage(header="", body="")]
        report = run(pages, source=ExplodingSource(pages, broken={2}))
        assert [(item.page_number, "no pudo procesarse" in item.reason) for item in report.review_queue] == [
            (2, True)
        ]

    def test_the_progress_stream_marks_the_failed_page(self):
        recorder = RecordingProgressReporter()
        pages = [digital("RESOLUCION N° 0412/2024"), FakePage(header="", body="")]
        run(pages, source=ExplodingSource(pages, broken={2}), progress=recorder)
        failed = [event for event in recorder.events if event.failed]
        assert [event.page_number for event in failed] == [2]

    def test_every_page_failing_still_produces_an_honest_result(self):
        pages = [FakePage(header="", body="") for _ in range(4)]
        report = run(pages, source=ExplodingSource(pages, broken={1, 2, 3, 4}))
        assert report.grouping.groups == []
        assert report.grouping.quarantine == [1, 2, 3, 4]
        assert len(report.review_queue) == 4


class TestDocumentFailure:
    def test_a_fatal_error_is_announced_before_it_propagates(self):
        recorder = RecordingProgressReporter()

        class Broken:
            def write(self, source, result, destination):
                raise OSError("disk full")

        use_case = ProcessDocument(
            store=FakeDocumentStore(source=FakePageSource(pages=[digital("RESOLUCION N° 1/2024")])),
            pipeline=ClassificationPipeline(ocr=FakeOcr(), config=PipelineConfig(max_workers=1)),
            assembler=Broken(),
            progress=recorder,
        )
        with pytest.raises(OSError):
            use_case.execute(DOCUMENT, DESTINATION)

        assert recorder.events[-1].stage is Stage.FAILED
        assert "disk full" in recorder.events[-1].detail
