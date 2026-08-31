"""Bajar el inventario desde la pantalla, en Excel y no en CSV.

El adaptador ya escribía la hoja junto a los PDF generados, pero no había
ninguna ruta por donde pedirla: la pantalla seguía ofreciendo el CSV, así que la
plantilla existía y nadie la veía nunca. Estas pruebas cubren las dos formas de
pedirla -- la de un documento y la del inventario completo -- y que el archivo
que llega sea un libro que Excel abre, no bytes con un nombre bonito.
"""

from __future__ import annotations

import io
from urllib.parse import unquote

import pytest

openpyxl = pytest.importorskip("openpyxl")

from resolutions.adapters import excel_inventory  # noqa: E402
from resolutions.api import main  # noqa: E402

XLSX_MAGIC = b"PK\x03\x04"


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


def test_el_sufijo_que_busca_la_api_es_el_que_escribe_el_adaptador():
    """Los dos nombres viven en módulos distintos y no pueden separarse.

    La API no puede importar el adaptador -- eso exigiría openpyxl para
    arrancar -- así que repite la constante. Si alguien renombra la hoja, esto
    falla antes de que el botón de descarga empiece a dar 404 en silencio.
    """
    assert main.SHEET_SUFFIX == excel_inventory.SUFFIX


class TestInventarioDeUnDocumento:
    def test_entrega_la_hoja_que_quedo_junto_a_los_pdf(self, client):
        carpeta = main.settings.output_dir / "job-1"
        carpeta.mkdir(parents=True)
        hoja = carpeta / f"RESOLUCIONES 00072{excel_inventory.SUFFIX}"
        libro = openpyxl.Workbook()
        libro.active["A1"] = "INVENTARIO DE RESOLUCIONES"
        libro.save(hoja)

        respuesta = client.get("/api/jobs/job-1/inventory.xlsx")

        assert respuesta.status_code == 200
        # El tipo es lo que hace que Windows lo abra con Excel en vez de preguntar.
        assert respuesta.headers["content-type"] == main.XLSX_MEDIA
        # El nombre viaja percent-codificado: la cabecera es ASCII y el archivo
        # lleva espacios. Lo que importa es que llegue con SU nombre y no con
        # el identificador interno del trabajo.
        assert "RESOLUCIONES%2000072" in respuesta.headers["content-disposition"]
        assert unquote(respuesta.headers["content-disposition"]).endswith(hoja.name)
        assert respuesta.content.startswith(XLSX_MAGIC)

    def test_un_documento_sin_hoja_lo_dice_en_vez_de_entregar_nada(self, client):
        (main.settings.output_dir / "job-2").mkdir(parents=True)

        respuesta = client.get("/api/jobs/job-2/inventory.xlsx")

        assert respuesta.status_code == 404
        assert "inventario" in respuesta.json()["detail"].lower()

    def test_un_documento_que_no_existe_no_revienta(self, client):
        assert client.get("/api/jobs/no-existe/inventory.xlsx").status_code == 404


class TestInventarioCompleto:
    def test_llega_un_libro_de_verdad_y_no_un_csv(self, client):
        main.ledger.record("job-1", report())

        respuesta = client.get("/api/inventory.xlsx")

        assert respuesta.status_code == 200
        assert respuesta.headers["content-type"] == main.XLSX_MEDIA
        assert "inventario.xlsx" in respuesta.headers["content-disposition"]

        libro = openpyxl.load_workbook(io.BytesIO(respuesta.content))
        texto = [
            str(cell)
            for sheet in libro.worksheets
            for row in sheet.iter_rows(values_only=True)
            for cell in row
            if cell is not None
        ]
        assert any("00086" in value for value in texto)
        assert any("expediente.pdf" in value for value in texto)

    def test_el_filtro_de_la_pantalla_llega_hasta_el_libro(self, client):
        main.ledger.record("job-1", report(document="marzo.pdf"))
        main.ledger.record("job-2", report(document="abril.pdf"))

        respuesta = client.get("/api/inventory.xlsx", params={"q": "marzo"})

        libro = openpyxl.load_workbook(io.BytesIO(respuesta.content))
        texto = " ".join(
            str(cell)
            for sheet in libro.worksheets
            for row in sheet.iter_rows(values_only=True)
            for cell in row
            if cell is not None
        )
        assert "marzo.pdf" in texto
        assert "abril.pdf" not in texto

    def test_un_inventario_vacio_sigue_dando_un_libro_abrible(self, client):
        respuesta = client.get("/api/inventory.xlsx")

        assert respuesta.status_code == 200
        assert respuesta.content.startswith(XLSX_MAGIC)


def test_la_revision_de_la_api_anuncia_el_inventario_en_excel(client):
    salud = client.get("/api/health").json()

    assert salud["api_revision"] >= 7
    assert "inventory-xlsx" in salud["features"]
