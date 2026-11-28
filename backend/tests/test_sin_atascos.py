"""Ningún texto del papel puede dejar al bot pensando sin fin (2026-11-27).

El operador: «que no se trabe… un sistema que cubra todos los escenarios». La
auditoría de atascos midió dos expresiones regulares que retrocedían sin fin con
textos que el OCR sí produce, y que congelaban el proceso entero -- sin latido,
sin atender la orden de parar -- hasta que el vigilante lo daba por atascado:

* los puntos suspensivos de un resumen de la IA con una racha de puntos (las
  líneas de un formulario): 48 puntos, 40 s; 60, cerca de una hora;
* el «Ciudad. 15 de julio de 2021» de la cabeza de una carta con una racha de
  letras pegadas (el OCR de un código de barras): 80 letras, 12 s; 300, más de
  una hora.

Con cuantificadores posesivos, lo mismo de siempre y al instante.
"""

from __future__ import annotations

import time
from datetime import date

import pytest

from resolutions.domain.acta_consejo import sin_cortes
from resolutions.domain.fecha_por_estructura import _del_encabezado_de_la_cabeza

#: Holgado para un equipo cargado: lo que se midió antes tardaba de segundos a horas.
TOPE = 1.0


def _cronometrar(funcion, *args, **kwargs):
    inicio = time.perf_counter()
    resultado = funcion(*args, **kwargs)
    return resultado, time.perf_counter() - inicio


class TestLosSuspensivos:
    @pytest.mark.parametrize("puntos", [48, 200, 5000])
    def test_una_racha_de_puntos_no_atasca(self, puntos):
        texto = "Se aprobó el acta de la sesión anterior " + "." * puntos
        resultado, tardo = _cronometrar(sin_cortes, texto)
        assert tardo < TOPE
        assert resultado == "Se aprobó el acta de la sesión anterior."

    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("Se aprobó el acta…", "Se aprobó el acta."),
            ("Se aprobó el acta...", "Se aprobó el acta."),
            ("Se aprobó el acta . . .", "Se aprobó el acta."),
            ("Se aprobó el acta.", "Se aprobó el acta."),
            ("Se aprobó el acta", "Se aprobó el acta"),
        ],
    )
    def test_dice_lo_mismo_de_siempre(self, texto, esperado):
        assert sin_cortes(texto) == esperado


class TestLaCabezaDeLaCarta:
    @pytest.mark.parametrize("letras", [80, 350])
    def test_una_racha_de_letras_pegadas_no_atasca(self, letras):
        texto = "I" + "Il" * (letras // 2) + " documento sin fecha"
        _, tardo = _cronometrar(_del_encabezado_de_la_cabeza, texto, date(2026, 11, 27))
        assert tardo < TOPE

    def test_la_ciudad_con_punto_y_la_fecha_siguen_valiendo(self):
        texto = "Santa Rosa del Sur – Bolívar. Julio 15 de 2021 Señores ELECTRICARIBE"
        assert _del_encabezado_de_la_cabeza(texto, date(2026, 11, 27)) == date(2021, 7, 15)
