"""Un filtro mal escrito se contesta con una frase, no con un hueco.

Cuatro salidas del archivo -- la lista de resoluciones, la de documentos, el
Excel y el CSV -- reciben lo que el operador teclea. Hasta ahora ninguna
validaba `offset`, un `limit` que no era número volvía como una lista de
pydantic que la pantalla enseñaba como «[object Object]», y la búsqueda de la
pestaña de documentos era otra distinta de la de resoluciones: no encontraba
ni por tipo documental ni por NIC. Esto fija que las cuatro contesten igual,
en español, y que lo inesperado no salga con el traceback puesto.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("httpx")

from resolutions.api.errores import explicar_validacion  # noqa: E402


def _graba(
    main,
    *,
    code: str = "01",
    tipo: str = "DERECHO DE PETICION",
    nic: str = "5825181",
    fecha: str = "2021-12-10",
    documento: str = "UPD2365925.pdf",
):
    """Un documento de una unidad en el libro mayor, con todo lo que se busca."""
    job = main.registry.create(documento, Path("x.pdf"))
    main.ledger.record(
        job.id,
        {
            "document": documento,
            "nic": nic,
            "inventory": {
                "source_document": documento,
                "source_pages": 8,
                "items": [
                    {
                        "code": code,
                        "title": "páginas 1-8",
                        "type": tipo,
                        "fecha": fecha,
                        "file_name": f"{documento[:-4]}/{code}_{tipo.replace(' ', '-')}.pdf",
                        "page_count": 8,
                        "first_page": 1,
                        "last_page": 8,
                        "page_numbers": list(range(1, 9)),
                    }
                ],
            },
        },
    )
    return job


class TestLosParametrosSeValidan:
    @pytest.mark.parametrize(
        "consulta, parametro",
        [("offset=-1", "offset"), ("limit=abc", "limit"), ("limit=0", "limit"), ("limit=99999", "limit")],
    )
    def test_contestan_422_con_una_frase_en_espanol(self, client, consulta, parametro):
        for ruta in ("/api/inventory", "/api/documents"):
            respuesta = client.get(f"{ruta}?{consulta}")
            assert respuesta.status_code == 422, ruta
            detalle = respuesta.json()["detail"]
            assert isinstance(detalle, str), "una lista se enseña como [object Object]"
            assert f"«{parametro}»" in detalle
            assert detalle.startswith("El parámetro")

    def test_dice_que_se_esperaba_y_que_llego(self, client):
        detalle = client.get("/api/inventory?limit=abc").json()["detail"]
        assert "número entero" in detalle
        assert "«abc»" in detalle

    def test_los_topes_se_nombran(self, client):
        assert "mayor o igual que 0" in client.get("/api/inventory?offset=-1").json()["detail"]
        assert "mayor o igual que 1" in client.get("/api/inventory?limit=0").json()["detail"]
        assert "menor o igual que 5000" in client.get("/api/inventory?limit=99999").json()["detail"]

    def test_una_busqueda_desmedida_tambien(self, client):
        for ruta in ("/api/inventory", "/api/documents", "/api/inventory.csv", "/api/inventory.xlsx"):
            respuesta = client.get(ruta, params={"q": "x" * 5000})
            assert respuesta.status_code == 422, ruta
            assert "200 caracteres" in respuesta.json()["detail"]

    def test_un_offset_mas_alla_del_final_no_es_un_error(self, client):
        """Pedir la página once de diez es una página vacía, no un 4xx."""
        from resolutions.api import main

        _graba(main)
        cuerpo = client.get("/api/inventory?offset=50").json()
        assert cuerpo["rows"] == []
        assert cuerpo["total"] == 1

    def test_una_busqueda_en_blanco_es_no_buscar(self, client):
        from resolutions.api import main

        _graba(main)
        assert client.get("/api/inventory", params={"q": "   "}).json()["total"] == 1
        assert client.get("/api/documents", params={"q": "   "}).json()["total"] == 1


class TestElMismoFiltroEnLasCuatroSalidas:
    """Lo que se ve en pantalla es exactamente lo que se descarga."""

    @staticmethod
    def _dos_documentos(main):
        _graba(main, code="01", tipo="DERECHO DE PETICION")
        _graba(main, code="02", tipo="FACTURA", documento="UPD2366126.pdf", nic="7000001")

    def test_la_lista_y_el_csv(self, client):
        from resolutions.api import main

        self._dos_documentos(main)
        assert client.get("/api/inventory?q=factura").json()["total"] == 1
        csv = client.get("/api/inventory.csv?q=factura").text
        filas = [linea for linea in csv.splitlines() if linea.strip()]
        assert len(filas) == 2, "el encabezado y una sola fila"
        assert "FACTURA" in csv
        assert "DERECHO DE PETICION" not in csv

    def test_y_el_excel(self, client):
        openpyxl = pytest.importorskip("openpyxl")
        from io import BytesIO

        from resolutions.api import main

        self._dos_documentos(main)
        libro = openpyxl.load_workbook(BytesIO(client.get("/api/inventory.xlsx?q=factura").content))
        texto = " ".join(
            str(celda.value)
            for hoja in libro.worksheets
            for fila in hoja.iter_rows()
            for celda in fila
            if celda.value is not None
        )
        assert "FACTURA" in texto
        assert "DERECHO DE PETICION" not in texto

    def test_y_la_pestana_de_documentos(self, client):
        from resolutions.api import main

        self._dos_documentos(main)
        documentos = client.get("/api/documents?q=factura").json()
        assert documentos["total"] == 1
        assert documentos["documents"][0]["source_document"] == "UPD2366126.pdf"


class TestLaPestanaDeDocumentosBuscaComoLaDeResoluciones:
    """Antes buscaba sólo por código, título y nombre del PDF, con tildes y todo."""

    def test_por_tipo_documental(self, client):
        from resolutions.api import main

        _graba(main)
        assert client.get("/api/documents?q=derecho").json()["total"] == 1
        assert client.get("/api/documents?q=factura").json()["total"] == 0

    def test_por_nic(self, client):
        from resolutions.api import main

        _graba(main)
        assert client.get("/api/documents?q=5825181").json()["total"] == 1

    def test_por_fecha(self, client):
        from resolutions.api import main

        _graba(main)
        assert client.get("/api/documents?q=2021-12-10").json()["total"] == 1

    def test_sin_tildes_y_con_varias_palabras(self, client):
        from resolutions.api import main

        _graba(main, tipo="NOTIFICACIÓN PERSONAL")
        assert client.get("/api/documents", params={"q": "notificacion 2021"}).json()["total"] == 1
        assert client.get("/api/documents", params={"q": "notificacion 2019"}).json()["total"] == 0


class TestLoInesperadoNoSaleConElTraceback:
    def test_responde_500_con_una_frase_y_sin_interioridades(self, client, monkeypatch):
        from fastapi.testclient import TestClient

        from resolutions.api import main

        def revienta():
            raise RuntimeError("C:/secreto/inventory.jsonl no se pudo abrir")

        monkeypatch.setattr(main.ledger, "rows", revienta)
        # Con `raise_server_exceptions` el cliente de pruebas relanza el error
        # en vez de devolver la respuesta, que es justo lo que hay que mirar.
        respuesta = TestClient(main.app, raise_server_exceptions=False).get("/api/inventory")

        assert respuesta.status_code == 500
        detalle = respuesta.json()["detail"]
        assert "/api/inventory" in detalle
        assert "registro del backend" in detalle
        assert "secreto" not in detalle
        assert "RuntimeError" not in detalle

    def test_el_borrado_en_lote_tampoco_cuenta_interioridades(self, client, monkeypatch):
        from resolutions.api import main

        def revienta(job_id):
            raise OSError("C:/secreto/outputs/abc no se pudo borrar")

        monkeypatch.setattr(main, "_erase_document", revienta)
        cuerpo = client.request("DELETE", "/api/documents", json={"job_ids": ["abc"]}).json()
        motivo = cuerpo["failed"][0]["reason"]
        assert "secreto" not in motivo
        assert "OSError" not in motivo
        assert "registro del backend" in motivo


class TestExplicarValidacion:
    """La traducción, sin levantar el servicio."""

    def test_nombra_el_parametro_lo_esperado_y_lo_recibido(self):
        frase = explicar_validacion(
            [{"type": "int_parsing", "loc": ("query", "limit"), "msg": "x", "input": "abc"}]
        )
        assert frase == "El parámetro «limit» debe ser un número entero; se recibió «abc»."

    def test_los_topes_llevan_su_numero(self):
        frase = explicar_validacion(
            [{"type": "less_than_equal", "loc": ("query", "limit"), "input": 99999, "ctx": {"le": 5000}}]
        )
        assert frase == "El parámetro «limit» debe ser menor o igual que 5000; se recibió «99999»."

    def test_lo_que_falta_no_repite_lo_que_llego(self):
        frase = explicar_validacion(
            [{"type": "missing", "loc": ("body", "job_ids"), "input": {"otro": 1}}]
        )
        assert frase == "El parámetro «job_ids» es obligatorio."

    def test_lo_recibido_se_recorta(self):
        frase = explicar_validacion(
            [{"type": "string_too_long", "loc": ("query", "q"), "input": "x" * 500, "ctx": {"max_length": 200}}]
        )
        assert "no puede pasar de 200 caracteres" in frase
        assert "…" in frase
        assert len(frase) < 120

    def test_varios_errores_van_en_un_parrafo(self):
        frase = explicar_validacion(
            [
                {"type": "greater_than_equal", "loc": ("query", "offset"), "input": -1, "ctx": {"ge": 0}},
                {"type": "int_parsing", "loc": ("query", "limit"), "input": "abc"},
            ]
        )
        assert "«offset» debe ser mayor o igual que 0; se recibió «-1». " in frase
        assert frase.endswith("«limit» debe ser un número entero; se recibió «abc».")

    def test_un_tipo_desconocido_conserva_el_motivo_original(self):
        frase = explicar_validacion(
            [{"type": "algo_nuevo", "loc": ("query", "x"), "msg": "Value error, raro", "input": "1"}]
        )
        assert "no es válido (Value error, raro)" in frase

    def test_sin_errores_sigue_habiendo_frase(self):
        assert explicar_validacion([]) == "La petición no es válida."
