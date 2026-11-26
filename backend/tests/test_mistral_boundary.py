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

import http.client
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
from resolutions.application.consumo import Consumo
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
    # Sin dormir de verdad entre los reintentos de un corte de red.
    return MistralBoundaryOracle(api_key="llave-de-prueba", esperar=lambda _segundos: None)


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


    def test_una_respuesta_200_inservible_se_avisa(self, monkeypatch, oraculo, caplog):
        """Un 200 que no produce veredictos se veía igual que no tener llave."""
        monkeypatch.setattr("urllib.request.urlopen", contestando("Claro, con gusto."))
        with caplog.at_level(logging.WARNING):
            assert oraculo.judge(HUELLAS, COSTURAS) == {}
        assert "no se entendió" in caplog.text
        assert "Claro" in caplog.text

    def test_una_respuesta_util_no_avisa_nada(self, monkeypatch, oraculo, caplog):
        texto = veredicto({"costura": "12|13", "nuevo": True})
        monkeypatch.setattr("urllib.request.urlopen", contestando(texto))
        with caplog.at_level(logging.WARNING):
            oraculo.judge(HUELLAS, COSTURAS)
        assert "no se entendió" not in caplog.text


class TestUnCorteDeRedSeRepite:
    """2026-11-26: un corte de red no es un «no» del proveedor.

    Lo que no se mandó (``URLError``) se repite dos veces, con 1 y 2 s de
    espera; lo que se cortó con la pregunta ya enviada, que Mistral pudo
    cobrar, una sola vez y con un aviso que lo dice. Sólo entonces van las
    dudas a revisión y cuenta un fallo. Un 401, un 429 o un cuerpo que no es
    JSON son respuestas, y repetir la pregunta no las cambia.
    """

    @staticmethod
    def _contestando(monkeypatch, *respuestas):
        """Un `urlopen` que da cada respuesta en orden y repite la última."""
        pedidas: list = []

        def falso_urlopen(request, timeout=None):
            pedidas.append(request)
            siguiente = respuestas[min(len(pedidas), len(respuestas)) - 1]
            if isinstance(siguiente, BaseException):
                raise siguiente
            return siguiente

        monkeypatch.setattr("urllib.request.urlopen", falso_urlopen)
        return pedidas

    @pytest.mark.parametrize(
        "corte",
        [
            urllib.error.URLError(TimeoutError("timed out")),
            TimeoutError("The read operation timed out"),
            http.client.RemoteDisconnected("Remote end closed connection without response"),
        ],
        ids=["sin-enviar", "plazo-de-lectura", "remote-disconnected"],
    )
    def test_un_corte_y_luego_la_respuesta(self, monkeypatch, corte):
        texto = veredicto({"costura": "12|13", "nuevo": True})
        pedidas = self._contestando(
            monkeypatch, corte, _Respuesta({"choices": [{"message": {"content": texto}}]})
        )
        esperas: list[float] = []
        consumo = Consumo()
        oraculo = MistralBoundaryOracle(api_key="k", consumo=consumo, esperar=esperas.append)

        assert oraculo.judge(HUELLAS, COSTURAS) == {(12, 13): True}
        assert len(pedidas) == 2
        assert esperas == [1.0]
        assert consumo.as_dict()["proveedores"]["mistral-bordes"]["fallos"] == 0

    def test_si_la_red_no_vuelve_las_dudas_van_a_revision_con_un_fallo(self, monkeypatch, caplog):
        corte = urllib.error.URLError(TimeoutError("timed out"))
        pedidas = self._contestando(monkeypatch, corte)
        esperas: list[float] = []
        consumo = Consumo()
        oraculo = MistralBoundaryOracle(api_key="k", consumo=consumo, esperar=esperas.append)

        with caplog.at_level(logging.WARNING, logger="resolutions.adapters.mistral_boundary"):
            assert oraculo.judge(HUELLAS, COSTURAS) == {}
        assert len(pedidas) == 3
        assert esperas == [1.0, 2.0]
        assert consumo.as_dict()["proveedores"]["mistral-bordes"]["fallos"] == 1
        [aviso] = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert "timed out" in aviso
        assert "3 intentos" in aviso
        assert "revisión" in aviso

    @pytest.mark.parametrize(
        "corte",
        [
            TimeoutError("The read operation timed out"),
            http.client.RemoteDisconnected("Remote end closed connection without response"),
            http.client.IncompleteRead(b'{"cort'),
        ],
        ids=["plazo-de-lectura", "remote-disconnected", "incomplete-read"],
    )
    def test_lo_ya_enviado_se_repite_una_sola_vez(self, monkeypatch, caplog, corte):
        """Mistral pudo cobrar la pregunta: dos como mucho, un fallo y un aviso que lo dice."""
        pedidas = self._contestando(monkeypatch, corte)
        esperas: list[float] = []
        consumo = Consumo()
        oraculo = MistralBoundaryOracle(api_key="k", consumo=consumo, esperar=esperas.append)

        with caplog.at_level(logging.WARNING, logger="resolutions.adapters.mistral_boundary"):
            assert oraculo.judge(HUELLAS, COSTURAS) == {}
        assert len(pedidas) == 2
        assert esperas == [1.0]
        assert consumo.as_dict()["proveedores"]["mistral-bordes"]["fallos"] == 1
        cobro, aviso = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert "pudo cobrarse" in cobro
        assert type(corte).__name__ in aviso
        assert "2 intentos" in aviso
        assert "revisión" in aviso

    @pytest.mark.parametrize(
        "respuesta",
        [
            urllib.error.HTTPError(ENDPOINT, 401, "Unauthorized", {}, None),
            urllib.error.HTTPError(ENDPOINT, 429, "Too Many Requests", {}, None),
            _CuerpoQueNoEsJson(),
        ],
        ids=["401", "429", "no-es-json"],
    )
    def test_una_respuesta_no_se_repite(self, monkeypatch, respuesta):
        pedidas = self._contestando(monkeypatch, respuesta)
        esperas: list[float] = []
        consumo = Consumo()
        oraculo = MistralBoundaryOracle(api_key="k", consumo=consumo, esperar=esperas.append)

        assert oraculo.judge(HUELLAS, COSTURAS) == {}
        assert len(pedidas) == 1
        assert esperas == []
        assert consumo.as_dict()["proveedores"]["mistral-bordes"]["fallos"] == 1

    def test_por_omision_dos_reintentos_con_1_y_2_segundos(self):
        assert (MistralConfig().reintentos, MistralConfig().esperas) == (2, (1.0, 2.0))


class TestElContrato:
    def test_cumple_el_protocolo(self, oraculo):
        assert isinstance(oraculo, BoundaryOracle)

    def test_el_modelo_por_omision_es_uno_de_los_baratos(self):
        """La caja se paga por costura dudosa, no por prestigio del modelo."""
        assert MistralConfig().model == "mistral-small-latest"
