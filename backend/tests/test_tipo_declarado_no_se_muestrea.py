"""Lo que el operador declaró estar cargando no se vuelve a reconocer.

Reconocer cuesta una muestra de doce páginas -- doce pasadas de OCR en un
escaneo -- y, peor, puede equivocarse: una muestra que dice «resolución» sobre
un libro de diplomas manda el libro entero a la ruta que no sabe cortarlo.
Quien tiene el libro delante sabe lo que es; si lo dijo, se le cree.
"""

from resolutions.application.inventory_document import InventoryDocument
from resolutions.domain.doctype import DocumentType
from tests.fakes import FakeOcr, FakePage, FakePageSource

#: Páginas que, muestreadas, parecen resoluciones y no diplomas.
PARECE_RESOLUCION = FakePage(
    text=(
        "RESOLUCION No. 00412 DE 2019\n"
        "Por la cual se reconoce un derecho\n"
        "EL RECTOR DE LA UNIVERSIDAD en uso de sus facultades resuelve\n"
    )
)


class TestElTipoDeclaradoManda:
    def test_sin_declaracion_la_muestra_decide(self):
        """El control: estas páginas, muestreadas, no son un libro de diplomas."""
        fuente = FakePageSource([PARECE_RESOLUCION] * 6)
        veredicto = InventoryDocument(ocr=FakeOcr()).identify(fuente)
        assert veredicto.document_type is not DocumentType.DIPLOMA
        assert veredicto.pages_sampled > 0

    def test_declarado_diploma_no_se_muestrea_y_va_por_diplomas(self):
        fuente = FakePageSource([PARECE_RESOLUCION] * 6)
        outcome = InventoryDocument(ocr=FakeOcr()).execute(
            fuente, document_name="x.pdf", declarado=DocumentType.DIPLOMA
        )
        assert outcome.document_type is DocumentType.DIPLOMA
        assert outcome.verdict.pages_sampled == 0
        assert outcome.verdict.confidence == 1.0
        assert len(outcome.rows) == 6, "una fila por cara, como manda el criterio"
