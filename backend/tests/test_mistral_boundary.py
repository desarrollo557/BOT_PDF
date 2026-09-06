"""Mistral contestando la misma pregunta de bordes, sobre HTTP pelado.

El tercer proveedor no trae una pregunta propia: las instrucciones y la lectura
de la respuesta son las de `boundary_prompt`, compartidas con Claude y con
Gemini, así que una diferencia entre los tres tiene que venir del modelo y no de
que alguien reescribió el prompt en un archivo suelto. Lo que se fija acá es el
transporte -- a dónde va la petición, cómo viaja la llave, y qué pasa cuando el
otro lado no contesta.

Y sobre todo lo que NO pasa: una caída de Mistral degrada la corrida a "estas
costuras las mira un humano" y nunca se lleva puesta la caja. Todo lo que la
estructura resolvió gratis sigue siendo un corte válido.
"""

from __future__ import annotations

import io
import json
import logging
import urllib.error

import pytest

from resolutions.adapters.mistral_boundary import (
    ENDPOINT,
    MistralBoundaryOracle,
    MistralConfig,
)
from resolutions.application.ports import BoundaryOracle

HUELLAS = [
    {"p": 12, "t": "Factura de energía", "mb": True},
    {"p": 13, "t": "...continúa el detalle", "mb": False},
    {"p": 14, "t": "Recurso de reposición", "mb": True},
]
COSTURAS = [(12, 13), (13, 14)]


class _Respuesta:
    """Lo mínimo que `json.load` y el `with` necesitan de una respuesta HTTP."""

    def __init__(self, payload: object) -> None:
        self._cuerpo = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self) -> io.BytesIO:
        return self._cuerpo

    def __exit__(self, *_: object) -> None:
        return None


class _CuerpoQueNoEsJson:
    def __enter__(self) -> io.BytesIO:
        return io.BytesIO(b"<html>502 Bad Gateway</html>")

    def __exit__(self, *_: object) -> None:
        return None


def contestando(texto: str, registro: list | None = None):
    """Un `urlopen` de mentira que contesta `texto` como lo haría Mistral."""

    def falso_urlopen(request, timeout=None):
        if registro is not None:
            registro.append((request, timeout))
        return _Respuesta({"choices": [{"message": {"content": texto}}]})

    return falso_urlopen


def reventando(error: BaseException):
    def falso_urlopen(request, timeout=None):
        raise error

    return falso_urlopen


def veredicto(*entradas: dict) -> str:
    return json.dumps({"cortes": list(entradas)}, ensure_ascii=False)


@pytest.fixture
def registro() -> list:
    return []


@pytest.fixture
def oraculo() -> MistralBoundaryOracle:
    return MistralBoundaryOracle(api_key="llave-de-prueba")


class TestLoQueNoLlegaAPreguntarse:
    """Una petición que no hace falta es una petición que no se paga."""

    def test_sin_costuras_no_se_toca_la_red(self, monkeypatch, oraculo):
        monkeypatch.setattr("urllib.request.urlopen", reventando(AssertionError("no preguntar")))
        assert oraculo.judge(HUELLAS, []) == {}

    def test_sin_llave_no_se_toca_la_red(self, monkeypatch):
        monkeypatch.setattr("urllib.request.urlopen", reventando(AssertionError("no preguntar")))
        assert MistralBoundaryOracle(api_key="").judge(HUELLAS, COSTURAS) == {}


class TestLaPeticion:
    def test_va_al_endpoint_de_mistral(self, monkeypatch, oraculo, registro):
        monkeypatch.setattr("urllib.request.urlopen", contestando(veredicto(), registro))
        oraculo.judge(HUELLAS, COSTURAS)
        assert registro[0][0].full_url == ENDPOINT

    def test_la_llave_viaja_como_portador_y_no_en_la_url(self, monkeypatch, oraculo, registro):
        """En la URL se filtraría a los logs de cualquier proxy del camino."""
        monkeypatch.setattr("urllib.request.urlopen", contestando(veredicto(), registro))
        oraculo.judge(HUELLAS, COSTURAS)
        request = registro[0][0]
        assert request.get_header("Authorization") == "Bearer llave-de-prueba"
        assert "llave-de-prueba" not in request.full_url

    def test_lleva_las_instrucciones_compartidas_como_sistema(self, monkeypatch, oraculo, registro):
        from resolutions.adapters.boundary_prompt import INSTRUCTIONS

        monkeypatch.setattr("urllib.request.urlopen", contestando(veredicto(), registro))
        oraculo.judge(HUELLAS, COSTURAS)
        cuerpo = json.loads(registro[0][0].data)
        sistema = [m for m in cuerpo["messages"] if m["role"] == "system"]
        assert sistema[0]["content"] == INSTRUCTIONS

    def test_lleva_la_caja_y_las_costuras_como_usuario(self, monkeypatch, oraculo, registro):
        monkeypatch.setattr("urllib.request.urlopen", contestando(veredicto(), registro))
        oraculo.judge(HUELLAS, COSTURAS)
        cuerpo = json.loads(registro[0][0].data)
        usuario = [m for m in cuerpo["messages"] if m["role"] == "user"]
        assert "12|13" in usuario[0]["content"]
        assert "Recurso de reposición" in usuario[0]["content"]

    def test_se_pide_json_explicito(self, monkeypatch, oraculo, registro):
        """Sin esto el modelo contesta prosa y `parse_answer` la descarta entera."""
        monkeypatch.setattr("urllib.request.urlopen", contestando(veredicto(), registro))
        oraculo.judge(HUELLAS, COSTURAS)
        cuerpo = json.loads(registro[0][0].data)
        assert cuerpo["response_format"] == {"type": "json_object"}

    def test_una_sola_peticion_por_caja(self, monkeypatch, oraculo, registro):
        """No una por costura: 124 llamadas seguidas es como se llega al 429."""
        monkeypatch.setattr("urllib.request.urlopen", contestando(veredicto(), registro))
        oraculo.judge(HUELLAS, COSTURAS)
        assert len(registro) == 1

    def test_el_plazo_de_espera_es_el_configurado(self, monkeypatch, registro):
        oraculo = MistralBoundaryOracle(api_key="k", config=MistralConfig(timeout_seconds=7))
        monkeypatch.setattr("urllib.request.urlopen", contestando(veredicto(), registro))
        oraculo.judge(HUELLAS, COSTURAS)
        assert registro[0][1] == 7


class TestLaRespuesta:
    def test_los_veredictos_se_leen(self, monkeypatch, oraculo):
        texto = veredicto(
            {"costura": "12|13", "nuevo": False},
            {"costura": "13|14", "nuevo": True},
        )
        monkeypatch.setattr("urllib.request.urlopen", contestando(texto))
        assert oraculo.judge(HUELLAS, COSTURAS) == {(12, 13): False, (13, 14): True}

    def test_contestar_solo_algunas_deja_la_otra_en_duda(self, monkeypatch, oraculo):
        texto = veredicto({"costura": "13|14", "nuevo": True})
        monkeypatch.setattr("urllib.request.urlopen", contestando(texto))
        assert oraculo.judge(HUELLAS, COSTURAS) == {(13, 14): True}

    def test_una_costura_que_nadie_pregunto_no_se_cuela(self, monkeypatch, oraculo):
        texto = veredicto({"costura": "99|100", "nuevo": True})
        monkeypatch.setattr("urllib.request.urlopen", contestando(texto))
        assert oraculo.judge(HUELLAS, COSTURAS) == {}

    def test_el_cerco_de_markdown_no_estorba(self, monkeypatch, oraculo):
        texto = "```json\n" + veredicto({"costura": "12|13", "nuevo": True}) + "\n```"
        monkeypatch.setattr("urllib.request.urlopen", contestando(texto))
        assert oraculo.judge(HUELLAS, COSTURAS) == {(12, 13): True}


class TestLoQueNoPuedeReventarLaCaja:
    """Todo lo de acá tiene que costar una revisión, nunca un corte inventado."""

    @pytest.mark.parametrize(
        "error",
        [
            urllib.error.URLError("sin red"),
            urllib.error.HTTPError(ENDPOINT, 429, "Too Many Requests", {}, None),
            urllib.error.HTTPError(ENDPOINT, 401, "Unauthorized", {}, None),
            TimeoutError("tardó demasiado"),
        ],
        ids=["sin-red", "429", "401", "plazo-vencido"],
    )
    def test_una_caida_manda_las_dudas_a_revision(self, monkeypatch, oraculo, error):
        monkeypatch.setattr("urllib.request.urlopen", reventando(error))
        assert oraculo.judge(HUELLAS, COSTURAS) == {}

    def test_un_cuerpo_que_no_es_json_manda_las_dudas_a_revision(self, monkeypatch, oraculo):
        monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=None: _CuerpoQueNoEsJson())
        assert oraculo.judge(HUELLAS, COSTURAS) == {}

    def test_una_respuesta_sin_opciones_manda_las_dudas_a_revision(self, monkeypatch, oraculo):
        monkeypatch.setattr(
            "urllib.request.urlopen", lambda request, timeout=None: _Respuesta({"choices": []})
        )
        assert oraculo.judge(HUELLAS, COSTURAS) == {}

    def test_una_opcion_sin_contenido_manda_las_dudas_a_revision(self, monkeypatch, oraculo):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda request, timeout=None: _Respuesta({"choices": [{"message": {}}]}),
        )
        assert oraculo.judge(HUELLAS, COSTURAS) == {}

    def test_prosa_en_vez_de_json_manda_las_dudas_a_revision(self, monkeypatch, oraculo):
        monkeypatch.setattr("urllib.request.urlopen", contestando("Claro, con gusto te ayudo."))
        assert oraculo.judge(HUELLAS, COSTURAS) == {}

    def test_cortes_en_nulo_no_revienta(self, monkeypatch, oraculo):
        monkeypatch.setattr("urllib.request.urlopen", contestando(json.dumps({"cortes": None})))
        assert oraculo.judge(HUELLAS, COSTURAS) == {}


class TestLoQueElLogTieneQueDecir:
    """Un aviso que no nombra la causa no sirve para arreglar nada.

    Medido contra la API real: la primera petición de una cuenta nueva volvió
    429 "Rate limit exceeded", y el log decía sólo "Mistral no respondió". Un
    429, un 401 y un plazo vencido se leían iguales, y son tres problemas con
    tres arreglos distintos -- esperar, cambiar la llave, subir el plazo.
    """

    def test_el_codigo_http_llega_al_aviso(self, monkeypatch, oraculo, caplog):
        error = urllib.error.HTTPError(ENDPOINT, 429, "Too Many Requests", {}, None)
        monkeypatch.setattr("urllib.request.urlopen", reventando(error))
        with caplog.at_level(logging.WARNING):
            oraculo.judge(HUELLAS, COSTURAS)
        assert "429" in caplog.text

    def test_la_razon_llega_al_aviso(self, monkeypatch, oraculo, caplog):
        error = urllib.error.HTTPError(ENDPOINT, 401, "Unauthorized", {}, None)
        monkeypatch.setattr("urllib.request.urlopen", reventando(error))
        with caplog.at_level(logging.WARNING):
            oraculo.judge(HUELLAS, COSTURAS)
        assert "401" in caplog.text

    def test_un_fallo_sin_codigo_igual_se_explica(self, monkeypatch, oraculo, caplog):
        """Sin red no hay status, y el aviso no puede quedarse mudo."""
        monkeypatch.setattr("urllib.request.urlopen", reventando(urllib.error.URLError("sin red")))
        with caplog.at_level(logging.WARNING):
            oraculo.judge(HUELLAS, COSTURAS)
        assert "sin red" in caplog.text

    def test_el_aviso_sigue_diciendo_que_las_dudas_van_a_revision(self, monkeypatch, oraculo, caplog):
        monkeypatch.setattr("urllib.request.urlopen", reventando(TimeoutError("tardó")))
        with caplog.at_level(logging.WARNING):
            oraculo.judge(HUELLAS, COSTURAS)
        assert "revisión" in caplog.text


class TestElContrato:
    def test_cumple_el_protocolo(self, oraculo):
        assert isinstance(oraculo, BoundaryOracle)

    def test_el_modelo_por_omision_es_uno_de_los_baratos(self):
        """La caja se paga por costura dudosa, no por prestigio del modelo."""
        assert MistralConfig().model == "mistral-small-latest"
