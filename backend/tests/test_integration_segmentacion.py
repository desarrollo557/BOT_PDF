"""De una caja revuelta a los PDF en disco, con los adaptadores de verdad.

Sin modelo y sin OCR: las páginas de esta caja declaran su propia paginación,
que es el caso que la segmentación resuelve gratis. Lo que se fija aquí es la
cadena entera -- leer, cortar, nombrar y escribir -- porque cada pieza ya estaba
probada por separado y ninguna escribía todavía un archivo que alguien pudiera
abrir.
"""

from __future__ import annotations

import pytest

pymupdf = pytest.importorskip("pymupdf")

from resolutions.adapters.pymupdf_assembler import PyMuPDFAssembler  # noqa: E402
from resolutions.adapters.pymupdf_source import PyMuPDFDocumentStore  # noqa: E402
from resolutions.application.segment_document import SegmentDocument  # noqa: E402
from resolutions.application.segment_split import group_by_segment  # noqa: E402
from resolutions.domain.naming import DOCUMENT_PREFIX  # noqa: E402

CUERPO = (
    "Por medio de la presente me permito dar respuesta a la solicitud "
    "radicada en el asunto de la referencia, en los terminos que se exponen "
    "a continuacion y con base en la normatividad vigente."
)

#: Tres documentos barajados en una sola caja: dos hojas, tres hojas y una.
#: El papel se cuenta a si mismo, asi que ningun corte necesita modelo.
PAGINAS = [
    ("RESPUESTA A RECLAMACION", "Página 1 de 2"),
    ("", "Página 2 de 2"),
    ("RECURSO DE REPOSICION", "Página 1 de 3"),
    ("", "Página 2 de 3"),
    ("", "Página 3 de 3"),
    ("CONSTANCIA DE ENTREGA", "Página 1 de 1"),
]


@pytest.fixture
def caja(tmp_path):
    """Una caja como sale del escáner: documentos distintos, un solo PDF."""
    document = pymupdf.open()
    for encabezado, paginacion in PAGINAS:
        page = document.new_page()
        if encabezado:
            page.insert_textbox(
                pymupdf.Rect(56, 64, 540, 96),
                encabezado,
                fontsize=12,
                align=pymupdf.TEXT_ALIGN_CENTER,
            )
        page.insert_textbox(pymupdf.Rect(56, 110, 540, 700), CUERPO, fontsize=11)
        page.insert_textbox(pymupdf.Rect(56, 720, 540, 760), paginacion, fontsize=9)
    path = tmp_path / "caja.pdf"
    document.save(path)
    document.close()
    return path


def _segmentar(caja):
    store = PyMuPDFDocumentStore()
    source = store.open(caja)
    try:
        return SegmentDocument().run(source)
    finally:
        source.close()


class TestLaCadenaCompleta:
    def test_la_paginacion_impresa_corta_la_caja_sin_pagar_modelo(self, caja):
        resultado = _segmentar(caja)
        assert [segment.page_numbers for segment in resultado.segments] == [
            [1, 2],
            [3, 4, 5],
            [6],
        ]
        assert resultado.undecided == []
        assert all(boundary.deterministic for boundary in resultado.boundaries)

    def test_cada_documento_sale_como_su_propio_pdf(self, caja, tmp_path):
        segmentacion = _segmentar(caja)
        grupos = group_by_segment(segmentacion.segments)
        grupos.verify_integrity(total_pages=len(PAGINAS))

        destino = tmp_path / "salida"
        entrega = PyMuPDFAssembler(naming_prefix=DOCUMENT_PREFIX).write(
            caja, grupos, destino
        )

        assert sorted(path.name for path in entrega.outputs) == [
            "DOCUMENTO_01.pdf",
            "DOCUMENTO_02.pdf",
            "DOCUMENTO_03.pdf",
        ]
        assert entrega.unwritable_pages == {}

    def test_los_archivos_llevan_las_hojas_que_les_tocan(self, caja, tmp_path):
        """Nada de cuadres en memoria: se abren los PDF escritos y se cuentan."""
        destino = tmp_path / "salida"
        grupos = group_by_segment(_segmentar(caja).segments)
        PyMuPDFAssembler(naming_prefix=DOCUMENT_PREFIX).write(caja, grupos, destino)

        hojas = {}
        for archivo in sorted(destino.glob("*.pdf")):
            with pymupdf.open(archivo) as escrito:
                hojas[archivo.name] = escrito.page_count

        assert hojas == {
            "DOCUMENTO_01.pdf": 2,
            "DOCUMENTO_02.pdf": 3,
            "DOCUMENTO_03.pdf": 1,
        }

    def test_ninguna_hoja_de_la_caja_se_pierde_por_el_camino(self, caja, tmp_path):
        destino = tmp_path / "salida"
        grupos = group_by_segment(_segmentar(caja).segments)
        PyMuPDFAssembler(naming_prefix=DOCUMENT_PREFIX).write(caja, grupos, destino)

        escritas = 0
        for archivo in destino.glob("*.pdf"):
            with pymupdf.open(archivo) as escrito:
                escritas += escrito.page_count
        assert escritas == len(PAGINAS)
