"""Qué filas aporta al inventario un informe terminado.

Dos formas de terminar y dos almacenes que tienen que entender las dos. Que sólo
uno supiera leer la segunda costó una pantalla de Archivo vacía: una caja
separada por documento escribía sus PDF, `record` devolvía cero y nadie mira ese
número.
"""

import json

from resolutions.adapters.ledger import InventoryLedger
from resolutions.application.inventory import rows_of

#: Lo que deja la ruta de resoluciones: un inventario ya armado.
CON_INVENTARIO = {
    "document": "resoluciones.pdf",
    "page_count": 9,
    "inventory": {
        "source_document": "resoluciones.pdf",
        "source_pages": 9,
        "items": [
            {
                "code": "00086",
                "title": "por la cual se nombra",
                "file_name": "RESOLUCION_00086.pdf",
                "page_count": 4,
                "first_page": 1,
                "last_page": 4,
                "page_numbers": [1, 2, 3, 4],
            }
        ],
    },
}

#: Lo que deja la ruta de segmentación: grupos y archivos, y ningún inventario.
#: Separar por continuidad no levanta FUID, así que `inventory` no existe.
SIN_INVENTARIO = {
    "document": "caja revuelta.pdf",
    "page_count": 4,
    "task": "segment",
    "groups": [
        {"code": "01", "title": "páginas 1-2", "pages": [1, 2], "size": 2},
        {"code": "02", "title": "páginas 3-4", "pages": [3, 4], "size": 2},
    ],
    "outputs": ["DOCUMENTO_01.pdf", "DOCUMENTO_02.pdf"],
    "review_queue": [{"page": 3, "reason": "sin evidencia"}],
}


class TestLasDosFormasDeTerminar:
    def test_un_inventario_armado_se_usa_tal_cual(self):
        filas = rows_of(CON_INVENTARIO)
        assert [f["file_name"] for f in filas] == ["RESOLUCION_00086.pdf"]
        assert filas[0]["code"] == "00086"

    def test_una_caja_segmentada_tambien_aporta_filas(self):
        """La regresión: esto devolvía lista vacía en el almacén de MySQL."""
        filas = rows_of(SIN_INVENTARIO)
        assert [f["file_name"] for f in filas] == ["DOCUMENTO_01.pdf", "DOCUMENTO_02.pdf"]
        assert [f["page_count"] for f in filas] == [2, 2]
        assert filas[0]["first_page"] == 1
        assert filas[1]["last_page"] == 4

    def test_un_informe_sin_nada_no_aporta_filas(self):
        assert rows_of({"document": "x.pdf", "page_count": 0}) == []

    def test_archivos_escritos_sin_grupos_siguen_contando(self):
        """Trabajo hecho es trabajo que el operador tiene que poder encontrar."""
        filas = rows_of({"outputs": ["SUELTO.pdf"]})
        assert [f["file_name"] for f in filas] == ["SUELTO.pdf"]

    def test_un_grupo_sin_archivo_no_inventa_una_fila(self):
        filas = rows_of({"groups": [{"code": "01", "pages": [1]}], "outputs": []})
        assert filas == []


class TestElArchivoJsonlEscribeLasDos:
    def test_una_caja_segmentada_llega_al_libro_mayor(self, tmp_path):
        libro = InventoryLedger(tmp_path / "inventory.jsonl")
        escritas = libro.record("trabajo", SIN_INVENTARIO, operator="Ana", source_bytes=1024)
        assert escritas == 2
        lineas = [json.loads(fila) for fila in (tmp_path / "inventory.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [fila["file_name"] for fila in lineas] == ["DOCUMENTO_01.pdf", "DOCUMENTO_02.pdf"]
        assert {fila["source_document"] for fila in lineas} == {"caja revuelta.pdf"}
        assert {fila["operator"] for fila in lineas} == {"Ana"}
        # Lo que la tarjeta del archivo necesita para no salir con huecos.
        assert {fila["source_pages"] for fila in lineas} == {4}
        assert {fila["review"] for fila in lineas} == {1}
