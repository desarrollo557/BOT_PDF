"""Que todo lo que sale de un PDF quede registrado, y con lo que se sabe de ello.

El inventario es la única respuesta a dos preguntas que se hacen meses después:
de qué páginas salió este archivo, y en qué archivo acabó esta página. Vale lo
que valga su exactitud, y tenía dos formas de estar mal a la vez.

La primera era silenciosa y grave. Las rutas que no son la de resoluciones
dejaban dos listas paralelas -- `groups` y `outputs` -- que el libro mayor
emparejaba por posición. Van en el mismo orden mientras se escriban todos los
archivos, y dejan de ir en cuanto uno falla: la unidad que no se pudo escribir
no aparece en `outputs`, corre la lista, y a partir de ahí cada fila afirma que
un archivo contiene las páginas de otro. El inventario no se quejaba -- tenía
tantas filas como siempre -- y mentía en todas.

La segunda era una pérdida: el tipo documental y los anexos se calculaban, se
enseñaban en la pantalla del trabajo, y no llegaban al libro mayor. El informe
del trabajo se borra al limpiar la pantalla; el libro mayor es lo que queda.
"""

from __future__ import annotations

import json

import pytest

from resolutions.adapters.ledger import LEDGER_COLUMNS, InventoryLedger
from resolutions.application.inventory import build_inventory, rows_of
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode


def grupo(code: str, pages: list[int], title: str | None = None, kind: str | None = None):
    return PageGroup(
        code=ResolutionCode(value=code, raw=code),
        page_numbers=list(pages),
        title=title,
        kind=kind,
    )


class TestUnArchivoQueNoSeEscribioNoSeInventa:
    """Una unidad sin PDF no produce fila. Sus páginas van a revisión.

    Antes se le calculaba el nombre que le habría tocado, así que el inventario
    listaba un archivo inexistente y la pantalla enlazaba a una descarga que
    contesta 404.
    """

    def test_solo_se_inventaria_lo_que_esta_en_el_disco(self):
        resultado = GroupingResult(
            groups=[grupo("01", [1, 2]), grupo("02", [3]), grupo("03", [4, 5])]
        )
        inventario = build_inventory(
            source_document="caja.pdf",
            source_pages=5,
            result=resultado,
            review_pages=[3],
            stats={},
            # El 02 no se pudo escribir: el escritor no lo puso en el mapa.
            file_names={"01": "01_FACTURA.pdf", "03": "03_PAGARE.pdf"},
        )
        assert [item.code for item in inventario.items] == ["01", "03"]

    def test_y_cada_fila_nombra_su_propio_archivo(self):
        resultado = GroupingResult(groups=[grupo("01", [1, 2]), grupo("03", [4, 5])])
        inventario = build_inventory(
            source_document="caja.pdf",
            source_pages=5,
            result=resultado,
            review_pages=[],
            stats={},
            file_names={"01": "01_FACTURA.pdf", "03": "03_PAGARE.pdf"},
        )
        emparejado = {
            item.code: (item.file_name, item.page_numbers) for item in inventario.items
        }
        assert emparejado == {
            "01": ("01_FACTURA.pdf", [1, 2]),
            "03": ("03_PAGARE.pdf", [4, 5]),
        }


class TestLaCarpetaVaEnElNombre:
    """Los documentos de una caja se entregan bajo el nombre de su origen.

    Lo que la descarga recibe es la ruta dentro del trabajo, así que el
    inventario tiene que traerla: sin la carpeta delante, el enlace no
    encuentra el archivo.
    """

    def test_el_nombre_registrado_es_la_ruta_dentro_del_trabajo(self):
        inventario = build_inventory(
            source_document="UPD2366126.pdf",
            source_pages=1,
            result=GroupingResult(groups=[grupo("01", [1])]),
            review_pages=[],
            stats={},
            file_names={"01": "01_FACTURA.pdf"},
            folder="UPD2366126",
        )
        assert inventario.items[0].file_name == "UPD2366126/01_FACTURA.pdf"

    def test_sin_carpeta_el_nombre_va_suelto(self):
        inventario = build_inventory(
            source_document="x.pdf",
            source_pages=1,
            result=GroupingResult(groups=[grupo("00072", [1])]),
            review_pages=[],
            stats={},
            file_names={"00072": "RESOLUCION_00072.pdf"},
        )
        assert inventario.items[0].file_name == "RESOLUCION_00072.pdf"


class TestElTipoYLosAnexosLleganAlInventario:
    def test_el_tipo_documental_viaja_con_la_unidad(self):
        inventario = build_inventory(
            source_document="caja.pdf",
            source_pages=1,
            result=GroupingResult(
                groups=[grupo("01", [1], kind="NOTIFICACION POR AVISO")]
            ),
            review_pages=[],
            stats={},
            file_names={"01": "01_NOTIFICACION-POR-AVISO.pdf"},
        )
        assert inventario.items[0].as_dict()["type"] == "NOTIFICACION POR AVISO"

    def test_sin_tipo_la_fila_lo_dice_en_vez_de_inventarlo(self):
        inventario = build_inventory(
            source_document="x.pdf",
            source_pages=1,
            result=GroupingResult(groups=[grupo("00072", [1])]),
            review_pages=[],
            stats={},
            file_names={"00072": "RESOLUCION_00072.pdf"},
        )
        assert inventario.items[0].as_dict()["type"] is None

    def test_los_anexos_dicen_de_que_documento_son(self):
        """Un acta con cuatro fotografías, y no un acta de cinco hojas."""
        inventario = build_inventory(
            source_document="caja.pdf",
            source_pages=5,
            result=GroupingResult(groups=[grupo("01", [1, 2, 3, 4, 5])]),
            review_pages=[],
            stats={},
            file_names={"01": "01_ACTA-DE-IRREGULARIDAD.pdf"},
            attachments={"01": [2, 3, 4, 5]},
        )
        item = inventario.items[0]
        assert item.page_numbers == [1, 2, 3, 4, 5]
        assert item.as_dict()["attachments"] == [2, 3, 4, 5]


class TestElLibroMayorEmparejaPorCodigoYNoPorPosicion:
    """La lectura de informes que no traen inventario armado.

    Sigue haciendo falta: en el registro quedan informes de trabajos anteriores
    a este cambio, y un informe viejo no puede dejar de poder leerse.
    """

    @staticmethod
    def _informe_con_una_baja():
        return {
            "document": "UPD2366126.pdf",
            "groups": [
                {
                    "code": "01",
                    "title": "páginas 1-3",
                    "type": "NOTIFICACION POR AVISO",
                    "pages": [1, 2, 3],
                    "size": 3,
                },
                {"code": "02", "title": "página 4", "type": "FACTURA",
                 "pages": [4], "size": 1},
                {"code": "03", "title": "páginas 5-6", "type": "PAGARE",
                 "pages": [5, 6], "size": 2},
            ],
            # El 02 no se escribió.
            "outputs": [
                "UPD2366126/01_NOTIFICACION-POR-AVISO.pdf",
                "UPD2366126/03_PAGARE.pdf",
            ],
        }

    def test_ninguna_fila_se_queda_con_el_archivo_de_otra(self):
        filas = rows_of(self._informe_con_una_baja())
        assert [(f["code"], f["file_name"]) for f in filas] == [
            ("01", "UPD2366126/01_NOTIFICACION-POR-AVISO.pdf"),
            ("03", "UPD2366126/03_PAGARE.pdf"),
        ]

    def test_la_que_no_se_escribio_no_aparece(self):
        codigos = {f["code"] for f in rows_of(self._informe_con_una_baja())}
        assert "02" not in codigos

    def test_las_paginas_siguen_siendo_las_suyas(self):
        filas = {
            f["code"]: f["page_numbers"] for f in rows_of(self._informe_con_una_baja())
        }
        assert filas == {"01": [1, 2, 3], "03": [5, 6]}

    def test_el_tipo_tambien_se_recupera_de_un_informe_viejo(self):
        tipos = {f["code"]: f["type"] for f in rows_of(self._informe_con_una_baja())}
        assert tipos == {"01": "NOTIFICACION POR AVISO", "03": "PAGARE"}

    @pytest.mark.parametrize(
        ("nombre", "code"),
        [
            ("RESOLUCION_00086.pdf", "00086"),
            ("00072__por-medio-de-la-cual.pdf", "00072"),
            ("01_NOTIFICACION-POR-AVISO.pdf", "01"),
            ("728.pdf", "728"),
        ],
        ids=["resolucion", "asunto-largo", "tipo-documental", "solo-el-codigo"],
    )
    def test_reconoce_las_cuatro_formas_de_nombrar_un_archivo(self, nombre, code):
        informe = {
            "groups": [
                {"code": code, "pages": [1], "size": 1},
                {"code": "zzz", "pages": [2], "size": 1},
            ],
            "outputs": [nombre],
        }
        filas = rows_of(informe)
        assert [(f["code"], f["file_name"]) for f in filas] == [(code, nombre)]

    def test_un_informe_ya_inventariado_manda_sobre_todo_lo_demas(self):
        informe = {
            "inventory": {
                "items": [
                    {
                        "code": "X",
                        "file_name": "de-verdad.pdf",
                        "page_count": 1,
                        "first_page": 1,
                        "last_page": 1,
                        "page_numbers": [1],
                    }
                ]
            },
            "groups": [{"code": "otro", "pages": [9], "size": 1}],
            "outputs": ["deducido.pdf"],
        }
        assert [f["file_name"] for f in rows_of(informe)] == ["de-verdad.pdf"]


class TestLoQueQuedaEscritoEnElLibroMayor:
    def test_una_fila_por_archivo_con_su_tipo_y_sus_anexos(self, tmp_path):
        libro = InventoryLedger(tmp_path / "inventory.jsonl")
        escritas = libro.record(
            "job-1",
            {
                "document": "UPD2366126.pdf",
                "page_count": 6,
                "inventory": {
                    "source_document": "UPD2366126.pdf",
                    "source_pages": 6,
                    "items": [
                        {
                            "code": "01",
                            "title": "páginas 1-5",
                            "type": "ACTA DE IRREGULARIDAD",
                            "file_name": "UPD2366126/01_ACTA-DE-IRREGULARIDAD.pdf",
                            "page_count": 5,
                            "first_page": 1,
                            "last_page": 5,
                            "page_numbers": [1, 2, 3, 4, 5],
                            "attachments": [2, 3, 4, 5],
                        }
                    ],
                },
            },
            operator="María Martínez",
        )
        assert escritas == 1

        cruda = (tmp_path / "inventory.jsonl").read_text(encoding="utf-8").strip()
        fila = json.loads(cruda)
        assert fila["type"] == "ACTA DE IRREGULARIDAD"
        # En rangos, como las páginas: "2-5" y no cuatro enteros.
        assert fila["attachments"] == "2-5"
        assert fila["pages"] == "1-5"
        assert fila["file_name"] == "UPD2366126/01_ACTA-DE-IRREGULARIDAD.pdf"
        assert fila["operator"] == "María Martínez"

    def test_el_csv_exporta_el_tipo_y_los_anexos(self, tmp_path):
        """El CSV es lo que se abre en Excel: lo que no salga ahí no existe."""
        assert "type" in LEDGER_COLUMNS
        assert "attachments" in LEDGER_COLUMNS

        libro = InventoryLedger(tmp_path / "inventory.jsonl")
        libro.record(
            "job-1",
            {
                "document": "caja.pdf",
                "inventory": {
                    "source_document": "caja.pdf",
                    "source_pages": 1,
                    "items": [
                        {
                            "code": "01",
                            "title": None,
                            "type": "FACTURA",
                            "file_name": "caja/01_FACTURA.pdf",
                            "page_count": 1,
                            "first_page": 1,
                            "last_page": 1,
                            "page_numbers": [1],
                        }
                    ],
                },
            },
        )
        exportado = libro.as_csv()
        assert "FACTURA" in exportado
        assert exportado.splitlines()[0].split(",")[4] == "type"
