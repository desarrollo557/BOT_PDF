from fakes import BODY, FakeOcr, FakePage, FakePageSource, FakeVision

from resolutions.application.pipeline import ClassificationPipeline, PipelineConfig
from resolutions.domain.page import Provenance

CONFIG = PipelineConfig(max_workers=1)


def run(pages, *, vision=None, config=CONFIG):
    source = FakePageSource(pages=pages)
    ocr = FakeOcr()
    pipeline = ClassificationPipeline(ocr=ocr, vision=vision, config=config)
    classifications, stats = pipeline.classify(source)
    return classifications, stats, ocr, source


def digital(header, body=BODY):
    return FakePage(text=f"{header}\n{body}")


class TestTextLayerRung:
    def test_a_digital_pdf_never_reaches_the_ocr_engine(self):
        _, stats, ocr, source = run(
            [digital("RESOLUCION No. 00412"), digital(""), digital("RESOLUCION No. 00555")]
        )
        assert ocr.calls == 0
        assert source.renders == []
        assert stats.by_provenance == {"text_layer": 3}

    def test_it_reads_the_code_straight_off_the_text_layer(self):
        classifications, _, _, _ = run([digital("RESOLUCION No. 00412")])
        assert classifications[0].code.value == "00412"
        assert classifications[0].provenance is Provenance.TEXT_LAYER


class TestOcrRungs:
    def test_a_scan_is_read_from_the_header_band_alone(self):
        classifications, _, ocr, source = run(
            [FakePage(header="RESOLUCION No. 00412", body=BODY)]
        )
        assert classifications[0].code.value == "00412"
        assert classifications[0].provenance is Provenance.OCR_REGION
        # One render, one OCR pass, on ~28% of the pixels. The full page is never
        # touched, and that ratio is the whole cost story of the system.
        assert (source.band_renders, source.full_renders) == (1, 0)
        assert ocr.calls == 1

    def test_the_full_page_is_only_rendered_when_the_band_comes_back_empty(self):
        classifications, _, ocr, source = run(
            [FakePage(header="", body=f"Se dispone lo siguiente. RESOLUCION No. 00412. {BODY}")]
        )
        assert classifications[0].code.value == "00412"
        assert classifications[0].provenance is Provenance.OCR_FULL_PAGE
        assert (source.band_renders, source.full_renders) == (1, 1)
        assert ocr.calls == 2


class TestEscalationPolicy:
    def test_a_continuation_page_with_healthy_text_costs_nothing(self):
        # No anchor, but plenty of text: this is page 2 of something, and the
        # grouping engine inherits it for free. Sending it to a model would be
        # burning tokens to be told what we already know.
        vision = FakeVision()
        classifications, stats, _, _ = run(
            [digital("RESOLUCION No. 00412"), digital("")], vision=vision
        )
        assert classifications[1].code is None
        assert classifications[1].ambiguous is False
        assert stats.escalated == 0
        assert vision.batches == []

    def test_a_short_digital_page_is_not_mistaken_for_a_failed_read(self):
        # The text layer was read successfully, so the absence of an anchor is
        # evidence, not silence. Treating a short page as unreadable is how a
        # digital PDF ends up sending most of itself to a model for nothing.
        vision = FakeVision()
        short = (
            "Continúa en la página siguiente conforme lo actuado en el expediente "
            "correspondiente, sin observaciones."
        )
        classifications, stats, _, _ = run(
            [digital("RESOLUCION No. 00412"), FakePage(text=short)], vision=vision
        )
        assert stats.escalated == 0
        assert vision.batches == []
        assert classifications[1].code is None

    def test_a_short_ocr_page_is_still_escalated(self):
        # Same length, but it came off the pixels. A near-empty OCR read really
        # can mean the scan failed, and that is worth a model call.
        vision = FakeVision(answers={2: "00412"})
        _, stats, _, _ = run(
            [digital("RESOLUCION No. 00412"), FakePage(header="", body="ruido ilegible")],
            vision=vision,
        )
        assert stats.escalated == 1

    def test_an_illegible_page_is_escalated_because_silence_is_not_evidence(self):
        vision = FakeVision(answers={2: "00412"})
        classifications, stats, _, _ = run(
            [FakePage(header="RESOLUCION No. 00412", body=BODY), FakePage(header="", body="")],
            vision=vision,
        )
        assert stats.escalated == 1
        assert classifications[1].code.value == "00412"
        assert classifications[1].provenance is Provenance.VISION_MODEL

    def test_a_page_with_competing_codes_is_escalated(self):
        vision = FakeVision(answers={1: "00555"})
        text = "Se remite copia de la Resolucion 00412\ny de la Resolucion 00555"
        classifications, stats, _, _ = run([FakePage(text=text + BODY)], vision=vision)
        assert stats.escalated == 1
        assert classifications[0].code.value == "00555"

    def test_an_unreadable_escalation_stays_unknown_instead_of_being_invented(self):
        vision = FakeVision(answers={2: None})
        classifications, _, _, _ = run(
            [FakePage(header="RESOLUCION No. 00412", body=BODY), FakePage(header="", body="")],
            vision=vision,
        )
        assert classifications[1].code is None
        assert classifications[1].ambiguous is True


class TestBatching:
    def test_escalated_pages_travel_in_mosaics_not_one_request_per_page(self):
        vision = FakeVision()
        pages = [FakePage(header="RESOLUCION No. 00412", body=BODY)]
        pages += [FakePage(header="", body="") for _ in range(15)]
        _, stats, _, _ = run(pages, vision=vision, config=PipelineConfig(max_workers=1, mosaic_size=12))
        assert [len(batch) for batch in vision.batches] == [12, 3]
        assert stats.vision_requests == 2

    def test_the_run_reports_what_fraction_of_pages_needed_a_model(self):
        vision = FakeVision()
        pages = [FakePage(header="RESOLUCION No. 00412", body=BODY)]
        pages += [digital("") for _ in range(9)]
        _, stats, _, _ = run(pages, vision=vision)
        assert stats.total_pages == 10
        assert stats.vision_page_ratio == 0.0


class TestParallelAnalysis:
    def test_fanning_out_preserves_page_order(self):
        pages = [digital(f"RESOLUCION No. {n:05d}") for n in range(1, 33)]
        classifications, _, _, _ = run(pages, config=PipelineConfig(max_workers=8))
        assert [c.page_number for c in classifications] == list(range(1, 33))
        assert [c.code.value for c in classifications] == [f"{n:05d}" for n in range(1, 33)]
