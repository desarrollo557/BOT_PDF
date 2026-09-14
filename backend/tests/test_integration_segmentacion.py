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
        entrega = PyMuPDFAssembler(naming_prefix=None).write(
            caja, grupos, destino
        )

        # El puesto en la caja y el tipo. "DOCUMENTO" es el tipo de lo que
        # nadie reconoció -- estas páginas de prueba no llevan rótulo -- y no
        # una palabra antepuesta.
        assert sorted(path.name for path in entrega.outputs) == [
            "01_DOCUMENTO.pdf",
            "02_DOCUMENTO.pdf",
            "03_DOCUMENTO.pdf",
        ]
        assert entrega.unwritable_pages == {}

    def test_los_archivos_llevan_las_hojas_que_les_tocan(self, caja, tmp_path):
        """Nada de cuadres en memoria: se abren los PDF escritos y se cuentan."""
        destino = tmp_path / "salida"
        grupos = group_by_segment(_segmentar(caja).segments)
        PyMuPDFAssembler(naming_prefix=None).write(caja, grupos, destino)

        hojas = {}
        for archivo in sorted(destino.glob("*.pdf")):
            with pymupdf.open(archivo) as escrito:
                hojas[archivo.name] = escrito.page_count

        assert hojas == {
            "01_DOCUMENTO.pdf": 2,
            "02_DOCUMENTO.pdf": 3,
            "03_DOCUMENTO.pdf": 1,
        }

    def test_ninguna_hoja_de_la_caja_se_pierde_por_el_camino(self, caja, tmp_path):
        destino = tmp_path / "salida"
        grupos = group_by_segment(_segmentar(caja).segments)
        PyMuPDFAssembler(naming_prefix=None).write(caja, grupos, destino)

        escritas = 0
        for archivo in destino.glob("*.pdf"):
            with pymupdf.open(archivo) as escrito:
                escritas += escrito.page_count
        assert escritas == len(PAGINAS)


class TestElInventarioDeLaCaja:
    """Del PDF de origen a las filas del libro mayor, sin saltarse nada.

    Es la comprobación que ninguna prueba de unidad puede dar: que el nombre
    escrito en el inventario es el de un archivo que existe de verdad en el
    disco, y que las páginas que la fila dice son las que ese archivo tiene
    dentro. Todo lo demás -- el emparejamiento, el tipo, la carpeta -- se
    comprueba por separado; esto comprueba que las piezas encajan.
    """

    @staticmethod
    def _entregar(caja, destino, carpeta="caja"):
        from resolutions.application.inventory import build_inventory

        segmentacion = _segmentar(caja)
        grupos = group_by_segment(segmentacion.segments, None)
        grupos.verify_integrity(total_pages=len(PAGINAS))
        entrega = PyMuPDFAssembler(naming_prefix=None).write(
            caja, grupos, destino / carpeta
        )
        inventario = build_inventory(
            source_document="caja.pdf",
            source_pages=len(PAGINAS),
            result=grupos,
            review_pages=[b.right for b in segmentacion.undecided],
            stats={"documents": len(grupos.groups)},
            file_names=entrega.written,
            folder=carpeta,
        )
        return inventario, entrega

    def test_hay_una_fila_por_pdf_escrito(self, caja, tmp_path):
        inventario, entrega = self._entregar(caja, tmp_path)
        assert len(inventario.items) == len(entrega.outputs) == 3

    def test_cada_fila_nombra_un_archivo_que_existe(self, caja, tmp_path):
        inventario, _ = self._entregar(caja, tmp_path)
        for item in inventario.items:
            assert (tmp_path / item.file_name).is_file(), item.file_name

    def test_y_ese_archivo_tiene_las_paginas_que_la_fila_dice(self, caja, tmp_path):
        """Se abren los PDF y se cuentan. Un inventario que no cuadra con el
        disco es exactamente el error que no se ve mirando la carpeta."""
        inventario, _ = self._entregar(caja, tmp_path)
        for item in inventario.items:
            with pymupdf.open(tmp_path / item.file_name) as escrito:
                assert escrito.page_count == item.page_count == len(item.page_numbers)

    def test_las_paginas_del_origen_estan_todas_y_una_sola_vez(self, caja, tmp_path):
        inventario, _ = self._entregar(caja, tmp_path)
        cubiertas = [n for item in inventario.items for n in item.page_numbers]
        assert sorted(cubiertas) == list(range(1, len(PAGINAS) + 1))

    def test_el_libro_mayor_guarda_lo_mismo_que_el_inventario(self, caja, tmp_path):
        from resolutions.adapters.ledger import InventoryLedger

        inventario, _ = self._entregar(caja, tmp_path)
        libro = InventoryLedger(tmp_path / "inventory.jsonl")
        escritas = libro.record(
            "job-1",
            {"document": "caja.pdf", "inventory": inventario.as_dict()},
            operator="quien sea",
        )

        assert escritas == len(inventario.items)
        registrado = {(f["code"], f["file_name"]) for f in libro.rows()}
        esperado = {(item.code, item.file_name) for item in inventario.items}
        assert registrado == esperado
