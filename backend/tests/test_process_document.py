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

# La capa de texto de la página 18 del libro 00072-00094, tal como la devolvía
# el PDF: los glifos impresos son correctos y el texto que se puede copiar no.
# Se toma de donde ya estaba descrita en vez de fabricar una imitación.
from test_legibility import PAGINA_18 as GARBLED

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
        assert [path.name for path in report.outputs] == [
            "RESOLUCION_00412.pdf",
            "RESOLUCION_00555.pdf",
        ]

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
    def test_files_are_named_after_what_they_are_and_their_number(self):
        """El asunto ya no entra en el nombre: vive en el inventario.

        Antes el número quedaba enterrado bajo un resumen del asunto y encontrar
        la 00412 entre trescientos archivos obligaba a leer. Ahora el nombre
        ordena y se busca de un vistazo.
        """
        pages = [
            FakePage(text=f"RESOLUCION No. 00412\nASUNTO: Compra de insumos informáticos\n{BODY}"),
            FakePage(text=f"RESOLUCION No. 00555\nDesignación de personal transitorio\n{BODY}"),
        ]
        report = build(pages)[0].execute(DOCUMENT, DESTINATION)
        assert [path.name for path in report.outputs] == [
            "RESOLUCION_00412.pdf",
            "RESOLUCION_00555.pdf",
        ]

    def test_an_unnamed_resolution_still_gets_a_file(self):
        report = build([digital("RESOLUCION No. 00412")])[0].execute(DOCUMENT, DESTINATION)
        assert [path.name for path in report.outputs] == ["RESOLUCION_00412.pdf"]


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

    def test_pages_the_model_could_not_read_join_the_open_resolution(self):
        # Antes iban a revisión. No hay nada que decidir: la página no trae
        # ningún número, así que hereda la resolución abierta -- que es lo que
        # manda el orden de los folios -- y nadie tiene que mirarla.
        use_case, _ = build(
            [FakePage(header="RESOLUCION No. 00412", body=BODY), FakePage(header="", body="")],
            vision=FakeVision(answers={2: None}),
        )
        report = use_case.execute(DOCUMENT, DESTINATION)
        assert report.review_queue == []

    def test_a_clean_document_has_an_empty_queue(self):
        use_case, _ = build([digital("RESOLUCION No. 00412"), digital("")])
        assert use_case.execute(DOCUMENT, DESTINATION).review_queue == []


class TestUnaPaginaIlegibleNoEsUnaPaginaDefectuosa:
    """Una capa de texto que no se deja leer no basta para llamar a nadie.

    En estos expedientes casi nunca es un defecto. Es un anexo escaneado -- un
    correo, un formato, la fotografía de una cédula -- o la vuelta de un folio,
    que el archivo escanea por las dos caras y marca con una "v" junto al número
    escrito a mano en la esquina superior derecha; la cara de atrás llega sin
    ningún identificador porque nunca lo tuvo.

    Se llegaron a mandar a revisión y estaba mal: en el libro 00072-00094 eran
    diecinueve páginas de doscientas veintidós, todas normales, y enterraban a
    las que sí necesitaban que alguien las mirara. La página 5 del libro
    00960-00979 es el ejemplo exacto: una cédula, foliada "4 /v", acusada de
    venir mal codificada en el origen.
    """

    def test_a_book_in_order_still_has_an_empty_queue(self):
        use_case, _ = build(
            [
                digital("RESOLUCION No. 00073"),
                digital("RESOLUCION No. 00074"),
                digital("RESOLUCION No. 00075"),
                digital("RESOLUCION No. 00076"),
            ]
        )
        assert use_case.execute(DOCUMENT, DESTINATION).review_queue == []

    def test_a_mis_decoded_text_layer_is_not_sent_to_review(self):
        rota = FakePage(text=GARBLED, header="RESOLUCION No. 00074", body=BODY)
        use_case, _ = build([digital("RESOLUCION No. 00073"), rota])
        report = use_case.execute(DOCUMENT, DESTINATION)
        assert report.review_queue == []

    def test_a_page_with_no_identifier_joins_the_open_resolution(self):
        # Es la vuelta de un folio, o la cédula que alguien anexó. Va al PDF de
        # la resolución que venía abierta y no se le pregunta a nadie.
        assembler = FakeAssembler()
        anexo = FakePage(text=GARBLED, header="", body=BODY)
        use_case, _ = build(
            [digital("RESOLUCION No. 00073"), anexo, digital("")],
            assembler=assembler,
        )
        report = use_case.execute(DOCUMENT, DESTINATION)
        assert assembler.written == [("00073", [1, 2, 3])]
        assert report.review_queue == []

    def test_the_count_of_mis_decoded_pages_still_matches_their_numbers(self):
        rota = FakePage(text=GARBLED, header="RESOLUCION No. 00074", body=BODY)
        use_case, _ = build([digital("RESOLUCION No. 00073"), rota])
        report = use_case.execute(DOCUMENT, DESTINATION)
        assert report.stats["mis_decoded"] == len(report.stats["mis_decoded_pages"]) == 1


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


class TestSoloSeLlamaCuandoHayAlgoQueDecidir:
    """Una página sin ningún número no es una duda: es un anexo.

    El orden de las páginas es el orden de los folios, así que una página sin
    identificador entre el folio de una resolución y el siguiente pertenece a
    esa resolución. Lo dijo el operador con su ejemplo: "si la página 1 tiene
    resolución y la página 2 es una factura o una imagen sin texto y el folio es
    el 2, ya sabemos que pertenece al pdf de la página 1".

    Las cinco páginas que el libro 00072-00094 dejaba en revisión eran
    exactamente eso -- la fotografía de un recibo de consignación mandado por
    WhatsApp, dos comprobantes de pago del banco -- y la pantalla las acusaba de
    "códigos de resolución en conflicto" sin que trajeran un solo número.
    """

    def test_an_unreadable_page_does_not_call_anyone(self):
        use_case, _ = build(
            [digital("RESOLUCION No. 00412"), FakePage(header="", body="")],
            vision=FakeVision(answers={2: None}),
        )
        report = use_case.execute(DOCUMENT, DESTINATION)
        assert report.review_queue == []

    def test_it_is_filed_with_the_open_resolution(self):
        assembler = FakeAssembler()
        use_case, _ = build(
            [digital("RESOLUCION No. 00412"), FakePage(header="", body="")],
            vision=FakeVision(answers={2: None}),
            assembler=assembler,
        )
        use_case.execute(DOCUMENT, DESTINATION)
        assert assembler.written == [("00412", [1, 2])]

    def test_a_page_before_any_resolution_is_still_quarantined(self):
        # Aquí no hay folio anterior del que colgar: no existe la resolución
        # abierta, así que la página no puede heredar nada y sigue yendo a
        # cuarentena con su aviso.
        use_case, _ = build([digital(""), digital("RESOLUCION No. 00412")])
        report = use_case.execute(DOCUMENT, DESTINATION)
        assert [item.page_number for item in report.review_queue] == [1]
        assert "sin código de resolución" in report.review_queue[0].reason
