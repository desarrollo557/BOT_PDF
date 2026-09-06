"""Leer lo que contestó un modelo sin creerle más de lo que dijo.

Es la única pieza de la separación que procesa texto que no escribimos nosotros,
y la que decide qué se convierte en un corte del PDF. Todo lo que no se entienda
tiene que costar una revisión y nunca un corte equivocado, así que lo que se fija
acá es sobre todo lo que NO pasa: una respuesta rota no revienta el trabajo, una
costura que nadie preguntó no se cuela, y un "nuevo" que no es booleano no cuenta
como decisión.
"""

from __future__ import annotations

import json
import urllib.error

from resolutions.adapters.boundary_prompt import (
    INSTRUCTIONS,
    NullBoundaryOracle,
    build_question,
    describe_failure,
    describe_unusable,
    parse_answer,
)

COSTURAS = [(12, 13), (13, 14)]


def respuesta(*entradas: dict) -> str:
    return json.dumps({"cortes": list(entradas)}, ensure_ascii=False)


class TestLaPregunta:
    def test_lleva_las_huellas_y_las_costuras(self):
        texto = build_question([{"p": 1, "t": "FACTURA"}], [(1, 2)])
        assert '"p":1' in texto
        assert "1|2" in texto

    def test_las_huellas_van_apretadas(self):
        """Cada espacio se paga una vez por página, y una caja son cientos."""
        texto = build_question([{"p": 1, "t": "FACTURA"}], [(1, 2)])
        assert '{"p":1,"t":"FACTURA"}' in texto

    def test_los_acentos_no_se_escapan(self):
        """`\u00f3` gasta seis caracteres para decir lo que la ó dice en uno."""
        texto = build_question([{"p": 1, "t": "RECLAMACIÓN"}], [(1, 2)])
        assert "RECLAMACIÓN" in texto

    def test_una_huella_por_renglon(self):
        texto = build_question([{"p": 1}, {"p": 2}], [(1, 2)])
        assert '{"p":1}\n{"p":2}' in texto

    def test_las_instrucciones_prohiben_decidir_por_el_expediente(self):
        # Es el error que hizo falta medir sobre 125 páginas para encontrar.
        assert "No uses el número de reclamación" in INSTRUCTIONS


class TestLoQueSeEntiende:
    def test_una_respuesta_limpia_se_lee(self):
        texto = respuesta(
            {"costura": "12|13", "nuevo": True, "razon": "membrete nuevo"},
            {"costura": "13|14", "nuevo": False, "razon": "sigue la frase"},
        )
        assert parse_answer(texto, COSTURAS) == {(12, 13): True, (13, 14): False}

    def test_el_cerco_de_markdown_no_estorba(self):
        """Los modelos envuelven el JSON en un bloque de código a menudo."""
        texto = "```json\n" + respuesta({"costura": "12|13", "nuevo": True}) + "\n```"
        assert parse_answer(texto, COSTURAS) == {(12, 13): True}

    def test_un_cerco_sin_cerrar_tampoco(self):
        texto = "```\n" + respuesta({"costura": "12|13", "nuevo": True})
        assert parse_answer(texto, COSTURAS) == {(12, 13): True}

    def test_los_espacios_dentro_de_la_costura_no_estorban(self):
        texto = respuesta({"costura": " 12 | 13 ", "nuevo": True})
        assert parse_answer(texto, COSTURAS) == {(12, 13): True}

    def test_contestar_solo_algunas_es_valido(self):
        """El silencio sobre una costura la deja sin decidir, que es correcto."""
        texto = respuesta({"costura": "12|13", "nuevo": True})
        assert parse_answer(texto, COSTURAS) == {(12, 13): True}


class TestLoQueSeDescarta:
    def test_una_costura_que_nadie_pregunto_no_se_cuela(self):
        """Un modelo que inventa una costura no puede cortar el PDF por ahí."""
        texto = respuesta({"costura": "40|41", "nuevo": True})
        assert parse_answer(texto, COSTURAS) == {}

    def test_un_nuevo_que_no_es_booleano_no_es_una_decision(self):
        texto = respuesta(
            {"costura": "12|13", "nuevo": "si"},
            {"costura": "13|14", "nuevo": 1},
        )
        assert parse_answer(texto, COSTURAS) == {}

    def test_una_entrada_sin_costura_se_ignora(self):
        assert parse_answer(respuesta({"nuevo": True}), COSTURAS) == {}

    def test_una_costura_ilegible_se_ignora(self):
        texto = respuesta(
            {"costura": "doce|trece", "nuevo": True},
            {"costura": "12-13", "nuevo": True},
            {"costura": "12|13|14", "nuevo": True},
        )
        assert parse_answer(texto, COSTURAS) == {}

    def test_una_entrada_que_no_es_un_objeto_se_ignora(self):
        texto = json.dumps({"cortes": ["12|13", 7, None]})
        assert parse_answer(texto, COSTURAS) == {}

    def test_la_ultima_palabra_del_modelo_es_la_que_vale(self):
        texto = respuesta(
            {"costura": "12|13", "nuevo": True},
            {"costura": "12|13", "nuevo": False},
        )
        assert parse_answer(texto, COSTURAS) == {(12, 13): False}


class TestLoQueNoPuedeReventar:
    """Una respuesta rota cuesta una revisión, nunca la caja entera.

    `judge` llama a esto fuera de su propio `try`, así que lo que se escape de
    acá se lleva puesto el trabajo completo -- incluidos los cortes que la
    estructura ya había resuelto gratis.
    """

    def test_texto_que_no_es_json(self):
        assert parse_answer("no tengo idea, perdón", COSTURAS) == {}

    def test_texto_vacio(self):
        assert parse_answer("", COSTURAS) == {}

    def test_ninguna_respuesta(self):
        assert parse_answer(None, COSTURAS) == {}

    def test_json_que_no_es_un_objeto(self):
        assert parse_answer("[1, 2, 3]", COSTURAS) == {}
        assert parse_answer('"listo"', COSTURAS) == {}

    def test_un_objeto_sin_la_clave_que_se_pidio(self):
        assert parse_answer('{"respuesta": "ok"}', COSTURAS) == {}

    def test_cortes_en_nulo(self):
        """`{"cortes": null}` es JSON válido y un modelo lo puede contestar."""
        assert parse_answer('{"cortes": null}', COSTURAS) == {}

    def test_cortes_que_no_es_una_lista(self):
        assert parse_answer('{"cortes": 5}', COSTURAS) == {}
        assert parse_answer('{"cortes": {"12|13": true}}', COSTURAS) == {}
        assert parse_answer('{"cortes": "12|13"}', COSTURAS) == {}

    def test_sin_costuras_que_decidir(self):
        texto = respuesta({"costura": "12|13", "nuevo": True})
        assert parse_answer(texto, []) == {}


class TestElOraculoNulo:
    def test_no_decide_nada(self):
        """Sin proveedor toda duda sigue siendo una duda y va a una persona."""
        assert NullBoundaryOracle().judge([{"p": 1}], COSTURAS) == {}

    def test_cumple_el_protocolo(self):
        from resolutions.application.ports import BoundaryOracle

        assert isinstance(NullBoundaryOracle(), BoundaryOracle)


class TestLoQueSeDiceCuandoUnProveedorFalla:
    """El aviso tiene que permitir elegir el arreglo, no sólo constatar la caída."""

    def test_un_error_http_se_nombra_por_su_codigo(self):
        error = urllib.error.HTTPError("https://x", 429, "Too Many Requests", {}, None)
        dicho = describe_failure(error)
        assert "429" in dicho
        assert "Too Many Requests" in dicho

    def test_una_llave_rechazada_no_se_confunde_con_un_limite(self):
        uno = describe_failure(urllib.error.HTTPError("https://x", 401, "Unauthorized", {}, None))
        otro = describe_failure(
            urllib.error.HTTPError("https://x", 429, "Too Many Requests", {}, None)
        )
        assert uno != otro

    def test_un_fallo_sin_codigo_se_nombra_por_su_tipo(self):
        assert "TimeoutError" in describe_failure(TimeoutError("tardó demasiado"))

    def test_un_fallo_de_red_conserva_lo_que_dijo(self):
        assert "sin red" in describe_failure(urllib.error.URLError("sin red"))

    def test_nunca_devuelve_algo_vacio(self):
        """Un aviso con un paréntesis vacío es peor que no tener paréntesis."""
        for error in (Exception(), TimeoutError(), urllib.error.URLError("")):
            assert describe_failure(error).strip()


class TestCuandoContestaYNoSeEntiendeNada:
    """Un 200 que no produce ni un veredicto tiene que decirlo, y con qué.

    Medido contra la API real de Gemini: la llamada volvió 200, `parse_answer`
    descartó la respuesta entera y el log no dijo nada. Desde afuera se veía
    igual que un proveedor sin llave -- `model_decided: 0` -- y averiguar la
    diferencia costó contar líneas de log contra cajas procesadas.
    """

    def test_ningun_veredicto_se_reporta(self):
        dicho = describe_unusable("Claro, con gusto te ayudo.", COSTURAS, {})
        assert dicho is not None
        assert "0 de 2" in dicho

    def test_se_incluye_un_pedazo_de_lo_que_contesto(self):
        """Sin la respuesta delante no se puede saber si es prosa o otro formato."""
        dicho = describe_unusable('{"boundaries": []}', COSTURAS, {})
        assert "boundaries" in dicho

    def test_una_respuesta_vacia_tambien_se_nombra(self):
        dicho = describe_unusable("", COSTURAS, {})
        assert dicho is not None
        assert "vacía" in dicho or "vacia" in dicho

    def test_contestar_todo_no_genera_ruido(self):
        answers = {(12, 13): True, (13, 14): False}
        assert describe_unusable("{}", COSTURAS, answers) is None

    def test_contestar_algunas_tampoco(self):
        """La cobertura parcial ya se ve en `model_decided`; no hace falta avisar."""
        assert describe_unusable("{}", COSTURAS, {(12, 13): True}) is None

    def test_sin_costuras_no_hay_nada_que_reportar(self):
        assert describe_unusable("", [], {}) is None

    def test_el_pedazo_no_inunda_el_log(self):
        dicho = describe_unusable("x" * 5000, COSTURAS, {})
        assert dicho is not None
        assert len(dicho) < 500
