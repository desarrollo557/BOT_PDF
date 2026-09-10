"""Buscar un documento por cualquier dato que lo describa.

Lo pidió el operador con esas palabras: «un filtro para buscar documento por
cualquier parámetro relacionado». Antes se buscaba por cinco campos -- número,
título, documento de origen, nombre de archivo y operador -- y quedaban fuera
justamente los que se añadieron después y por los que uno busca de verdad: el
tipo documental, la fecha y el NIC del expediente.
"""

from __future__ import annotations

import pytest

pytest.importorskip("httpx")

from resolutions.api.main import CAMPOS_BUSCABLES, _matches  # noqa: E402

FILA = {
    "recorded_at": "2026-09-10T12:00:00",
    "source_document": "UPD2365925.pdf",
    "code": "01",
    "title": "páginas 1-8",
    "type": "DERECHO DE PETICION",
    "nic": "5825181",
    "fecha": "2021-12-10",
    "file_name": "UPD2365925/01_DERECHO-DE-PETICION.pdf",
    "pages": "1-8",
    "job_id": "9f3c2ab14d7e4c0fa1b28e6d5c04a731",
    "operator": "Eduver Andrés Gutiérrez",
}


class TestSeBuscaPorCualquierDato:
    @pytest.mark.parametrize(
        "termino",
        [
            "01",
            "derecho de peticion",
            "5825181",
            "2021-12-10",
            "upd2365925",
            "eduver",
            "paginas 1-8",
        ],
        ids=["numero", "tipo", "nic", "fecha", "origen", "operador", "procedencia"],
    )
    def test_cada_uno_encuentra_la_fila(self, termino):
        assert _matches(FILA, termino)

    def test_lo_que_no_esta_no_la_encuentra(self):
        assert not _matches(FILA, "pagare")

    def test_el_identificador_del_trabajo_no_se_busca(self):
        """Es un hexadecimal de 32 letras que nadie teclea, y buscar tres
        cifras cualesquiera devolvería media base por su culpa."""
        assert "job_id" not in CAMPOS_BUSCABLES
        assert not _matches(FILA, "9f3c2ab1")


class TestVariasPalabras:
    def test_se_exigen_todas(self):
        assert _matches(FILA, "derecho 5825181")

    def test_y_pueden_estar_en_campos_distintos(self):
        """Es lo que permite acotar con una sola caja de texto: el tipo está en
        una columna, el operador en otra y la fecha en una tercera."""
        assert _matches(FILA, "peticion eduver 2021")

    def test_si_una_falta_no_hay_coincidencia(self):
        assert not _matches(FILA, "derecho de peticion pagare")


class TestLasTildesNoHacenFalta:
    """El OCR las pone y las quita, y quien busca no las escribe dos veces."""

    def test_sin_tildes_encuentra_lo_acentuado(self):
        assert _matches(FILA, "eduver andres gutierrez")

    def test_y_con_tildes_tambien(self):
        assert _matches(FILA, "Eduver Andrés Gutiérrez")

    def test_ni_las_mayusculas(self):
        assert _matches(FILA, "DERECHO DE PETICION")


class TestLaBusquedaAtraviesaElEndpoint:
    def test_se_encuentra_por_tipo_documental(self, client):
        from resolutions.api import main

        job = main.registry.create("UPD2365925.pdf", __import__("pathlib").Path("x.pdf"))
        main.ledger.record(
            job.id,
            {
                "document": "UPD2365925.pdf",
                "nic": "5825181",
                "inventory": {
                    "source_document": "UPD2365925.pdf",
                    "source_pages": 8,
                    "items": [
                        {
                            "code": "01",
                            "title": "páginas 1-8",
                            "type": "DERECHO DE PETICION",
                            "fecha": "2021-12-10",
                            "file_name": "UPD2365925/01_DERECHO-DE-PETICION.pdf",
                            "page_count": 8,
                            "first_page": 1,
                            "last_page": 8,
                            "page_numbers": list(range(1, 9)),
                        }
                    ],
                },
            },
        )

        assert client.get("/api/inventory?q=derecho").json()["total"] == 1
        assert client.get("/api/inventory?q=5825181").json()["total"] == 1
        assert client.get("/api/inventory?q=2021-12-10").json()["total"] == 1
        assert client.get("/api/inventory?q=pagare").json()["total"] == 0
