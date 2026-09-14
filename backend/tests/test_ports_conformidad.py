"""Que lo que el sistema llama sea lo que el protocolo promete.

`ports.PageSource` es el contrato entre la aplicación y quien lee un PDF. Vale
justo lo que valga su exactitud: un método que se usa y no está declarado
convierte el protocolo en documentación de otra cosa, y quien escriba una
fuente nueva leyéndolo entero se encuentra el fallo en tiempo de ejecución y en
una sola de las rutas.

Pasó de verdad con `lines_of` -- la llaman la ruta de diplomas y la de
matrículas, y no estaba en el protocolo. Estas pruebas lo fijan por los dos
lados: que el contrato declara lo que se usa, y que quien lo implementa lo
cumple entero.
"""

from __future__ import annotations

import inspect

import pytest

from resolutions.application import read_diploma_book, read_student_records
from resolutions.application.ports import PageSource
from tests.fakes import FakePage, FakePageSource


class TestElContratoDeclaraLoQueSeUsa:
    def test_lines_of_esta_en_el_protocolo(self):
        assert hasattr(PageSource, "lines_of")

    def test_y_tambien_sheet_of(self):
        # La usa el segmentador para leer el tamaño de la hoja, que es la única
        # señal que sobrevive a una página sin texto.
        assert hasattr(PageSource, "sheet_of")

    @pytest.mark.parametrize(
        "modulo", [read_diploma_book, read_student_records], ids=["diplomas", "matriculas"]
    )
    def test_ningun_lector_llama_a_algo_que_el_protocolo_no_tenga(self, modulo):
        """Los métodos que estos lectores piden de `source`, contra el contrato.

        Se lee el código fuente en vez de ejecutarlo porque lo que se comprueba
        es el contrato, no un camino concreto: un método que sólo se llama
        cuando el OCR entra no se ejercitaría nunca en una prueba corriente y
        rompería igual el día que entre.
        """
        fuente = inspect.getsource(modulo)
        pedidos = {
            linea.split("source.", 1)[1].split("(", 1)[0]
            for linea in fuente.splitlines()
            if "source." in linea and "(" in linea.split("source.", 1)[1]
        }
        faltan = {nombre for nombre in pedidos if not hasattr(PageSource, nombre)}
        assert not faltan, f"se usan y no están en el protocolo: {sorted(faltan)}"


class TestElAdaptadorRealCumpleElContrato:
    def test_la_fuente_de_pymupdf_los_trae_todos(self):
        pymupdf_source = pytest.importorskip(
            "resolutions.adapters.pymupdf_source",
            reason="PyMuPDF no está instalado",
        )
        faltan = [
            nombre
            for nombre in ("page_count", "text_of", "boxes_of", "lines_of", "sheet_of",
                           "render", "close")
            if not hasattr(pymupdf_source.PyMuPDFPageSource, nombre)
        ]
        assert not faltan


class TestElDobleTambien:
    def test_una_fuente_minima_contesta_a_todo_el_contrato(self):
        """Sin geometría, pero sin reventar.

        Es el caso que el protocolo mal declarado escondía: una fuente que sólo
        sabe dar texto plano tiene que poder atravesar cualquier ruta -- leyendo
        cero registros si hace falta -- en vez de tumbarla con un
        `AttributeError` que el operador lee como "la página no pudo
        procesarse".
        """
        source = FakePageSource(pages=[FakePage(text="una hoja")])
        assert source.lines_of(1) == []
        assert source.boxes_of(1) == []
        assert source.sheet_of(1) is None
