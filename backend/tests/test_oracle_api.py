"""La elección de modelo viaja desde la pantalla, o falla antes de costar algo.

Lo que se fija acá es el contrato entre la pantalla y el servicio, y tiene dos
mitades que se sostienen la una a la otra.

La primera: `/api/health` dice de cada proveedor si hay llave para pedirlo, así
que la pantalla puede deshabilitar lo que no se puede pedir en vez de ofrecerlo y
cosechar un 422 después de que el operador ya eligió.

La segunda: si igual llega una elección imposible -- una pantalla vieja, un
`curl` a mano, una llave que alguien sacó del entorno entre una subida y la otra
-- se contesta 422 **antes** de escribir el archivo en disco. Pedir Mistral sin
llave de Mistral no se resuelve con Gemini: el informe mentiría sobre quién
decidió los cortes, y un corte cuya autoría no se puede rastrear no sirve para
decidir si el criterio funciona.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("httpx")

CAJA = {"file": ("caja.pdf", b"%PDF-1.4 ...", "application/pdf")}


def con_llaves(monkeypatch, **llaves):
    """Pone llaves sobre los ajustes que ya montó la fixture `client`."""
    from resolutions.api import main

    monkeypatch.setattr(main, "settings", replace(main.settings, **llaves))


class TestLoQueLaPantallaPuedeOfrecer:
    def test_health_dice_que_proveedores_hay(self, client, monkeypatch):
        con_llaves(monkeypatch, gemini_api_key="xyz", mistral_api_key=None)
        cuerpo = client.get("/api/health").json()
        assert cuerpo["oracles"] == {
            "auto": True,
            "claude": False,
            "gemini": True,
            "mistral": False,
        }

    def test_el_automatico_se_ofrece_siempre(self, client, monkeypatch):
        """Sin llaves la caja se separa por lo que decide la estructura sola."""
        con_llaves(
            monkeypatch, anthropic_api_key=None, gemini_api_key=None, mistral_api_key=None
        )
        assert client.get("/api/health").json()["oracles"]["auto"] is True

    def test_la_capacidad_se_anuncia(self, client):
        """Sin bandera, una pantalla nueva no puede saber si el servicio la trae."""
        cuerpo = client.get("/api/health").json()
        assert "oracle-choice" in cuerpo["features"]

    def test_separar_una_caja_tambien_se_anuncia(self, client):
        """La acción existía en la API desde antes y nadie la podía descubrir."""
        assert "segment-task" in client.get("/api/health").json()["features"]

    def test_la_revision_sube_cuando_el_contrato_cambia(self, client):
        """La pantalla compara esto con aquello para lo que fue construida."""
        assert client.get("/api/health").json()["api_revision"] >= 17


class TestLaEleccionQueViaja:
    def test_sin_elegir_nada_es_automatico(self, client):
        respuesta = client.post("/api/jobs", files=CAJA)
        assert respuesta.status_code == 202
        assert respuesta.json()["oracle"] == "auto"

    def test_el_proveedor_elegido_se_acepta_y_se_recuerda(self, client, monkeypatch):
        con_llaves(monkeypatch, mistral_api_key="mmm")
        respuesta = client.post("/api/jobs?task=segment&oracle=mistral", files=CAJA)
        assert respuesta.status_code == 202
        assert respuesta.json()["oracle"] == "mistral"

    def test_el_trabajo_dice_a_quien_se_le_pregunto(self, client, monkeypatch):
        """La pantalla tiene que poder mostrar quién decidió los cortes."""
        con_llaves(monkeypatch, gemini_api_key="xyz")
        creado = client.post("/api/jobs?task=segment&oracle=gemini", files=CAJA).json()
        assert client.get(f"/api/jobs/{creado['id']}").json()["oracle"] == "gemini"


class TestLoQueSeRechazaTemprano:
    def test_un_proveedor_desconocido_es_422(self, client):
        respuesta = client.post("/api/jobs?oracle=gpt", files=CAJA)
        assert respuesta.status_code == 422

    def test_el_error_nombra_las_opciones_que_valen(self, client):
        detalle = client.post("/api/jobs?oracle=gpt", files=CAJA).json()["detail"]
        for opcion in ("auto", "claude", "gemini", "mistral"):
            assert opcion in detalle

    def test_pedir_un_proveedor_sin_llave_es_422(self, client, monkeypatch):
        con_llaves(monkeypatch, mistral_api_key=None)
        respuesta = client.post("/api/jobs?oracle=mistral", files=CAJA)
        assert respuesta.status_code == 422

    def test_el_error_nombra_la_variable_de_entorno_que_falta(self, client, monkeypatch):
        """Decir "no configurado" manda al operador a leer el código fuente."""
        con_llaves(monkeypatch, mistral_api_key=None)
        detalle = client.post("/api/jobs?oracle=mistral", files=CAJA).json()["detail"]
        assert "MISTRAL_API_KEY" in detalle

    def test_no_se_sustituye_por_el_proveedor_que_si_tiene_llave(self, client, monkeypatch):
        """Es la regla entera de este feature: elegir no puede degradar callado."""
        con_llaves(monkeypatch, anthropic_api_key="abc", mistral_api_key=None)
        assert client.post("/api/jobs?oracle=mistral", files=CAJA).status_code == 422

    def test_una_eleccion_imposible_no_deja_nada_en_disco(self, client, monkeypatch):
        """El 422 llega antes de escribir: el cuerpo de la petición es el archivo."""
        from resolutions.api import main

        con_llaves(monkeypatch, mistral_api_key=None)
        client.post("/api/jobs?oracle=mistral", files=CAJA)
        subidas = list(main.settings.upload_dir.glob("*.pdf"))
        assert subidas == []

    def test_una_eleccion_imposible_no_encola_nada(self, client, monkeypatch):
        con_llaves(monkeypatch, mistral_api_key=None)
        client.post("/api/jobs?oracle=mistral", files=CAJA)
        assert client.get("/api/jobs").json()["jobs"] == []


class TestUnaCarpetaPideLoMismo:
    def test_un_proveedor_desconocido_es_422(self, client):
        respuesta = client.post(
            "/api/folder-runs",
            json={"source": ".", "destination": ".", "oracle": "gpt"},
        )
        assert respuesta.status_code == 422
        assert "gpt" in respuesta.json()["detail"]

    def test_un_proveedor_sin_llave_es_422(self, client, monkeypatch):
        con_llaves(monkeypatch, mistral_api_key=None)
        respuesta = client.post(
            "/api/folder-runs",
            json={"source": ".", "destination": ".", "oracle": "mistral"},
        )
        assert respuesta.status_code == 422
        assert "MISTRAL_API_KEY" in respuesta.json()["detail"]

    def test_la_eleccion_queda_en_la_corrida(self, client, monkeypatch, tmp_path):
        """El camino de carpeta no tiene otra prueba que lo fije.

        La elección pasa por cuatro manos antes de llegar al worker: el endpoint,
        `FolderRunner.start`, el `FolderRun` y el trabajo que se crea por cada
        archivo. Un rebase que pierda uno de esos cuatro pasos deja la corrida
        decidiendo con el modelo de la cascada sin que nadie se entere, que es
        exactamente lo que este feature existe para que no pase.
        """
        con_llaves(monkeypatch, gemini_api_key="xyz")
        origen = tmp_path / "origen"
        destino = tmp_path / "destino"
        origen.mkdir()
        destino.mkdir()

        respuesta = client.post(
            "/api/folder-runs",
            json={
                "source": str(origen),
                "destination": str(destino),
                "task": "segment",
                "oracle": "gemini",
            },
        )
        assert respuesta.status_code == 201
        assert respuesta.json()["oracle"] == "gemini"
