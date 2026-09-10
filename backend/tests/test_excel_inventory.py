"""La planilla de entrega.

Un listado de lo que salió es la mitad de lo que un archivista necesita. La otra
mitad es la prueba de que no se perdió nada: el documento traía 222 páginas, las
resoluciones dan cuenta de 222 páginas, luego ninguna se perdió. Ese cuadre es
lo que convierte esto de una lista en evidencia, y es lo primero de la hoja.
"""

from __future__ import annotations

import pytest

openpyxl = pytest.importorskip("openpyxl")

from resolutions.adapters.excel_inventory import (  # noqa: E402
    SUFFIX,
    ExcelInventory,
    ExcelRunInventory,
)


def report(pages=7, quarantine=None, review=None, items=None):
    items = (
        items
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
            },
            {
                "file_name": "00072__otra.pdf",
                "code": "00072",
                "title": None,
                "page_count": 4,
                "first_page": 4,
                "last_page": 7,
                "page_numbers": [4, 5, 6, 7],
            },
        ]
    )
    return {
        "document": "RESOLUCIONES 00072-00094.pdf",
        "page_count": pages,
        "groups": [],
        "quarantine": quarantine or [],
        "repairs": [],
        "review_queue": review or [],
        "outputs": [item["file_name"] for item in items],
        "stats": {"by_provenance": {"text_layer": pages}, "escalated": 0},
        "inventory": {"source_document": "RESOLUCIONES 00072-00094.pdf",
                      "source_pages": pages, "items": items},
    }


def open_sheet(path, name):
    return openpyxl.load_workbook(path)[name]


def header_row(sheet) -> int:
    """Dónde empieza la tabla.

    Se busca en vez de darla por fija: la maqueta tiene una portada arriba y
    puede crecer, y un test atado a la fila 1 se rompe con cada ajuste visual
    sin que nada esté realmente mal.
    """
    for index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        if row and row[0] == "#":
            return index
    raise AssertionError("la tabla no tiene cabecera")


def col(sheet, titulo: str) -> int:
    """El indice de una columna dentro de las filas que devuelve `body`.

    Por su titulo y no por su numero, por lo mismo que `header_row` busca la
    fila en vez de darla por fija: anadir una columna a la planilla no puede
    obligar a renumerar a mano media docena de pruebas que no tienen nada que
    ver con ella. Paso al entrar "Tipo documental" y por eso existe esto.
    """
    fila = header_row(sheet)
    cabecera = list(sheet.iter_rows(min_row=fila, max_row=fila, values_only=True))[0]
    for indice, valor in enumerate(cabecera):
        if valor and str(valor).strip().upper() == titulo.upper():
            return indice
    raise AssertionError("la planilla no tiene una columna " + titulo)


def body(sheet):
    """Las filas de datos, sin portada, cabecera ni totales."""
    start = header_row(sheet) + 1
    rows = []
    for row in sheet.iter_rows(min_row=start, values_only=True):
        if not any(row):
            continue
        if row[0] is None:  # la fila de totales no lleva número de orden
            continue
        rows.append(row)
    return rows


def find(sheet, label):
    """The value beside a label in the summary sheet."""
    for row in sheet.iter_rows(min_col=1, max_col=2, values_only=True):
        if row[0] == label:
            return row[1]
    return None


class TestPerDocumentSheet:
    def test_it_is_named_after_the_document(self, tmp_path):
        path = ExcelInventory().write(report(), tmp_path)
        assert path.name == f"RESOLUCIONES 00072-00094{SUFFIX}"
        assert path.is_file()

    def test_the_summary_names_the_document_and_the_operator(self, tmp_path):
        path = ExcelInventory().write(
            report(), tmp_path, operator="Ana Martínez", processed_at="2026-08-31T12:00:00"
        )
        sheet = open_sheet(path, "Resumen")
        assert find(sheet, "Documento de origen") == "RESOLUCIONES 00072-00094.pdf"
        assert find(sheet, "Operador") == "Ana Martínez"
        assert "31/08/2026" in find(sheet, "Procesado el")

    def test_it_records_where_the_pdfs_went(self, tmp_path):
        path = ExcelInventory().write(report(), tmp_path, delivered_to=r"C:\Destino")
        assert find(open_sheet(path, "Resumen"), "Carpeta de destino") == r"C:\Destino"

    def test_without_a_destination_it_says_so_rather_than_leaving_it_blank(self, tmp_path):
        path = ExcelInventory().write(report(), tmp_path)
        assert "no se entregó" in find(open_sheet(path, "Resumen"), "Carpeta de destino")


class TestTheReconciliation:
    """The line somebody signs off on."""

    def test_it_says_so_when_every_page_is_accounted_for(self, tmp_path):
        path = ExcelInventory().write(report(pages=7), tmp_path)
        sheet = open_sheet(path, "Resumen")
        assert find(sheet, "Páginas del documento") == 7
        assert find(sheet, "Páginas en las resoluciones") == 7
        assert "CUADRA" in find(sheet, "Resultado")
        assert "NO CUADRA" not in find(sheet, "Resultado")

    def test_quarantined_pages_count_towards_the_total(self, tmp_path):
        # They are not in a resolution, but they were not lost either.
        path = ExcelInventory().write(report(pages=9, quarantine=[8, 9]), tmp_path)
        sheet = open_sheet(path, "Resumen")
        assert find(sheet, "Páginas en cuarentena") == 2
        assert find(sheet, "Total contabilizado") == 9
        assert "CUADRA" in find(sheet, "Resultado")

    def test_a_missing_page_is_stated_plainly(self, tmp_path):
        # The document had ten pages and only seven came out. The sheet has to
        # say that out loud, not leave it to be noticed.
        path = ExcelInventory().write(report(pages=10), tmp_path)
        result = find(open_sheet(path, "Resumen"), "Resultado")
        assert "NO CUADRA" in result
        assert "3" in result


class TestTheResolutionSheet:
    def test_one_row_per_resolution_with_its_number(self, tmp_path):
        path = ExcelInventory().write(report(), tmp_path)
        numbers = [row[1] for row in body(open_sheet(path, "Resoluciones"))]
        assert numbers == ["00086", "00072"]

    def test_pages_read_as_ranges(self, tmp_path):
        path = ExcelInventory().write(report(), tmp_path)
        sheet = open_sheet(path, "Resoluciones")
        assert body(sheet)[0][col(sheet, "Páginas")] == "1–3"

    def test_each_row_carries_the_generated_file_and_the_destination(self, tmp_path):
        path = ExcelInventory().write(report(), tmp_path, delivered_to=r"C:\Destino")
        sheet = open_sheet(path, "Resoluciones")
        row = body(sheet)[0]
        assert row[col(sheet, "Archivo generado")] == "00086__acta.pdf"
        assert row[col(sheet, "Carpeta de destino")] == r"C:\Destino"

    def test_the_total_is_a_formula_not_a_frozen_number(self, tmp_path):
        # If a resolution is withdrawn and its row deleted, the total follows.
        path = ExcelInventory().write(report(), tmp_path)
        sheet = open_sheet(path, "Resoluciones")
        cantidad = col(sheet, "Cant.") + 1
        totals = [
            row[0]
            for row in sheet.iter_rows(
                min_col=cantidad, max_col=cantidad, values_only=True
            )
        ]
        assert any(isinstance(value, str) and value.startswith("=SUM") for value in totals)

    def test_la_suma_apunta_a_la_columna_de_cantidades(self, tmp_path):
        """Y no a la que estaba ahi antes de anadir una columna.

        La formula llevaba la letra escrita a mano. Con "Tipo documental"
        delante, esa letra paso a senalar el nombre del archivo, y el total
        habria sumado texto: cero, en silencio, en la planilla que se firma.
        """
        path = ExcelInventory().write(report(), tmp_path)
        sheet = open_sheet(path, "Resoluciones")
        # Por el modulo y no por un import propio: openpyxl entra aqui por
        # `importorskip`, asi que un import al principio del archivo correria
        # antes de saber si la libreria esta.
        letra = openpyxl.utils.get_column_letter(col(sheet, "Cant.") + 1)
        formulas = [
            celda.value
            for fila in sheet.iter_rows()
            for celda in fila
            if isinstance(celda.value, str) and celda.value.startswith("=SUM")
        ]
        assert formulas
        assert all("=SUM(" + letra in formula for formula in formulas)

    def test_cada_fila_dice_que_clase_de_papel_es(self, tmp_path):
        """El tipo documental, que estaba en el nombre del archivo y no aqui.

        La planilla viaja con los PDF: es lo que alguien mira para saber que
        hay en la carpeta sin abrir doscientos archivos.
        """
        path = ExcelInventory().write(
            report(
                items=[
                    {
                        "file_name": "01_NOTIFICACION-POR-AVISO.pdf",
                        "code": "01",
                        "title": "paginas 1-3",
                        "type": "NOTIFICACION POR AVISO",
                        "page_count": 3,
                        "first_page": 1,
                        "last_page": 3,
                        "page_numbers": [1, 2, 3],
                    }
                ]
            ),
            tmp_path,
        )
        sheet = open_sheet(path, "Resoluciones")
        assert body(sheet)[0][col(sheet, "Tipo documental")] == "NOTIFICACION POR AVISO"

    def test_lo_que_nadie_reconocio_se_dice_con_una_raya(self, tmp_path):
        """Un tercio de una caja real no lleva rotulo legible, y eso se declara."""
        path = ExcelInventory().write(report(), tmp_path)
        sheet = open_sheet(path, "Resoluciones")
        assert body(sheet)[0][col(sheet, "Tipo documental")] == "—"

    def test_there_is_a_column_to_sign_off_each_row(self, tmp_path):
        path = ExcelInventory().write(report(), tmp_path)
        sheet = open_sheet(path, "Resoluciones")
        headers = list(sheet.iter_rows(min_row=header_row(sheet), max_row=header_row(sheet),
                                       values_only=True))[0]
        assert "VERIFICADO" in [str(h).upper() for h in headers if h]


class TestOptionalSheets:
    def test_the_review_sheet_only_exists_when_there_is_something_to_review(self, tmp_path):
        path = ExcelInventory().write(report(), tmp_path)
        assert "Revisión" not in openpyxl.load_workbook(path).sheetnames

    def test_and_it_lists_the_page_and_the_reason(self, tmp_path):
        path = ExcelInventory().write(
            report(review=[{"page": 4, "reason": "códigos en conflicto"}]), tmp_path
        )
        sheet = open_sheet(path, "Revisión")
        start = next(i for i, r in enumerate(sheet.iter_rows(values_only=True), start=1)
                     if r and str(r[0] or "").upper() == "PÁGINA") + 1
        row = list(sheet.iter_rows(min_row=start, max_row=start, values_only=True))[0]
        assert row[0] == 4
        assert "conflicto" in row[1]

    def test_a_document_with_no_resolutions_still_produces_a_sheet(self, tmp_path):
        # A document that yielded nothing is exactly the one somebody will ask
        # about later.
        path = ExcelInventory().write(report(pages=3, items=[], quarantine=[1, 2, 3]), tmp_path)
        assert path.is_file()
        assert "CUADRA" in find(open_sheet(path, "Resumen"), "Resultado")


class TestTheDeliverySheet:
    def rows(self):
        return [
            {
                "code": "00086",
                "title": "Acta",
                "file_name": "00086__acta.pdf",
                "page_count": 3,
                "pages": "1-3",
                "source_document": "marzo.pdf",
            },
            {
                "code": "00072",
                "title": None,
                "file_name": "00072__otra.pdf",
                "page_count": 4,
                "pages": "4-7",
                "source_document": "abril.pdf",
            },
        ]

    def test_it_lands_in_the_destination_folder(self, tmp_path):
        path = ExcelRunInventory().write(self.rows(), tmp_path, source=r"C:\Origen")
        assert path.parent == tmp_path
        assert path.suffix == ".xlsx"

    def test_the_summary_names_both_folders(self, tmp_path):
        path = ExcelRunInventory().write(self.rows(), tmp_path, source=r"C:\Origen")
        sheet = open_sheet(path, "Resumen")
        assert find(sheet, "Carpeta de origen") == r"C:\Origen"
        assert find(sheet, "Carpeta de destino") == str(tmp_path)

    def test_it_counts_documents_and_resolutions(self, tmp_path):
        path = ExcelRunInventory().write(self.rows(), tmp_path)
        sheet = open_sheet(path, "Resumen")
        assert find(sheet, "Documentos procesados") == 2
        assert find(sheet, "Resoluciones entregadas") == 2
        assert find(sheet, "Páginas en total") == 7

    def test_each_row_says_which_document_it_came_from(self, tmp_path):
        path = ExcelRunInventory().write(self.rows(), tmp_path)
        sheet = open_sheet(path, "Resoluciones")
        rows = body(sheet)
        origen = col(sheet, "Documento de origen")
        assert [row[origen] for row in rows] == ["marzo.pdf", "abril.pdf"]

    def test_an_empty_delivery_still_writes_a_sheet(self, tmp_path):
        path = ExcelRunInventory().write([], tmp_path)
        assert path.is_file()
