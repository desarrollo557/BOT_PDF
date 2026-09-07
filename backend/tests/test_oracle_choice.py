"""Quién juzga los bordes deja de ser una consecuencia de qué llave hay puesta.

Hasta acá el proveedor lo decidía la cascada: Claude si estaba su llave, después
Gemini, después Mistral. Sirve para que el sistema arranque solo, y no sirve
cuando el operador quiere comparar dos modelos sobre la misma caja, que es
exactamente lo que hace falta para saber en cuál confiar.

Lo que se fija acá es sobre todo que una elección no se degrade en silencio. Si
alguien pide Mistral y el sistema contesta con Gemini, el informe miente sobre
quién decidió los cortes, y un corte cuya autoría no se puede rastrear no sirve
para decidir si el criterio funciona.
"""

from __future__ import annotations

import pytest

from resolutions.application.oracle import OracleChoice, available_oracles

LLAVE_CLAUDE = {"anthropic_api_key": "abc"}
LLAVE_GEMINI = {"gemini_api_key": "xyz"}
LLAVE_MISTRAL = {"mistral_api_key": "mmm"}
LAS_TRES = {**LLAVE_CLAUDE, **LLAVE_GEMINI, **LLAVE_MISTRAL}


class TestLoQueSeLee:
    def test_lo_vacio_es_la_cascada(self):
        """Nadie que ya estuviera usando el sistema tiene que elegir nada."""
        assert OracleChoice.parse(None) is OracleChoice.AUTO
        assert OracleChoice.parse("") is OracleChoice.AUTO

    def test_los_tres_proveedores_se_reconocen(self):
        assert OracleChoice.parse("claude") is OracleChoice.CLAUDE
        assert OracleChoice.parse("gemini") is OracleChoice.GEMINI
        assert OracleChoice.parse("mistral") is OracleChoice.MISTRAL

    def test_no_distingue_mayusculas_ni_espacios(self):
        assert OracleChoice.parse("  MISTRAL ") is OracleChoice.MISTRAL

    def test_lo_desconocido_no_se_adivina(self):
        with pytest.raises(ValueError) as error:
            OracleChoice.parse("gpt")
        assert "gpt" in str(error.value)

    def test_el_error_dice_cuales_valen(self):
        """Un 422 que no nombra las opciones obliga a leer el código fuente."""
        with pytest.raises(ValueError) as error:
            OracleChoice.parse("gpt")
        for opcion in ("auto", "claude", "gemini", "mistral"):
            assert opcion in str(error.value)

    def test_todos_tienen_nombre_para_la_pantalla(self):
        for eleccion in OracleChoice:
            assert eleccion.label


class TestQueLlaveNecesitaCadaUno:
    @pytest.mark.parametrize(
        ("eleccion", "ajuste", "variable"),
        [
            (OracleChoice.CLAUDE, "anthropic_api_key", "ANTHROPIC_API_KEY"),
            (OracleChoice.GEMINI, "gemini_api_key", "GEMINI_API_KEY"),
            (OracleChoice.MISTRAL, "mistral_api_key", "MISTRAL_API_KEY"),
        ],
    )
    def test_cada_proveedor_sabe_su_llave(self, eleccion, ajuste, variable):
        assert eleccion.key_setting == ajuste
        assert eleccion.env_var == variable

    def test_la_cascada_no_depende_de_una_llave_en_particular(self):
        assert OracleChoice.AUTO.key_setting is None
        assert OracleChoice.AUTO.env_var is None


class TestSiSePuedePedir:
    def test_un_proveedor_con_su_llave_esta_disponible(self):
        assert OracleChoice.MISTRAL.is_available(LLAVE_MISTRAL)

    def test_un_proveedor_sin_su_llave_no_lo_esta(self):
        assert not OracleChoice.MISTRAL.is_available(LLAVE_GEMINI)

    def test_una_llave_vacia_no_cuenta_como_llave(self):
        """`GEMINI_API_KEY=` en el entorno es una llave que no existe."""
        assert not OracleChoice.GEMINI.is_available({"gemini_api_key": ""})
        assert not OracleChoice.GEMINI.is_available({"gemini_api_key": None})

    def test_la_cascada_esta_disponible_con_cualquiera_de_las_tres(self):
        assert OracleChoice.AUTO.is_available(LLAVE_MISTRAL)
        assert OracleChoice.AUTO.is_available(LLAVE_CLAUDE)

    def test_la_cascada_sigue_disponible_sin_ninguna_llave(self):
        """Sin llaves la caja se separa igual por lo que decide la estructura."""
        assert OracleChoice.AUTO.is_available({})


class TestLoQueLaPantallaPuedeOfrecer:
    def test_dice_de_cada_proveedor_si_esta_configurado(self):
        assert available_oracles(LLAVE_GEMINI) == {
            "auto": True,
            "claude": False,
            "gemini": True,
            "mistral": False,
        }

    def test_con_las_tres_llaves_estan_las_tres(self):
        assert available_oracles(LAS_TRES) == {
            "auto": True,
            "claude": True,
            "gemini": True,
            "mistral": True,
        }

    def test_sin_llaves_solo_queda_la_cascada(self):
        assert available_oracles({}) == {
            "auto": True,
            "claude": False,
            "gemini": False,
            "mistral": False,
        }

    def test_nombra_a_todos_los_proveedores_que_existen(self):
        """Un proveedor nuevo que no aparezca acá es invisible para el front."""
        assert set(available_oracles({})) == {eleccion.value for eleccion in OracleChoice}
