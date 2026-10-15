"""La fecha que el mensajero marca con una X en la guía de LECTA.

La guía se dibuja aquí con la geometría medida en las reales (UPD2320047 y
UPD2321099, a 300 ppp): paso entre columnas de 52 píxeles, la segunda fila de
días -- 16 a 31 -- empieza una columna antes que la primera, y la de MES va
alineada con la primera. Las palabras son las que el OCR leería: algunos de
los números impresos bajo la segunda fila, con alguno mal leído.
"""

from __future__ import annotations

import io
from datetime import date

import pytest

from resolutions.adapters.casillas_de_la_guia import casillas_marcadas, fecha_de_la_guia

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

A, B = 104, 52  # x de la columna 0 y paso
Y_NUMEROS_2 = 160  # altura de los números de la segunda fila
PASO = round(B * 0.885)


def _guia(dia: int, mes: int, con_el_anio_pegado: bool = False) -> bytes:
    imagen = Image.new("L", (960, 280), 255)
    dibujo = ImageDraw.Draw(imagen)
    filas = {"bajo": Y_NUMEROS_2 - PASO, "alto": Y_NUMEROS_2, "mes": Y_NUMEROS_2 + PASO}
    # Las casillas, con un borde gris claro que no llega a tinta.
    for fila, columnas in (("bajo", range(1, 16)), ("alto", range(0, 16)), ("mes", range(1, 13))):
        for k in columnas:
            x = A + B * k
            y = filas[fila] - PASO * 0.55
            dibujo.rectangle((x - 16, y - 16, x + 16, y + 16), outline=200)

    def equis(k: int, fila: str, ancho_extra: int = 0) -> None:
        x = A + B * k
        y = filas[fila] - PASO * 0.55
        dibujo.line((x - 18, y - 18, x + 18 + ancho_extra, y + 18), fill=0, width=5)
        dibujo.line((x - 18, y + 18, x + 18, y - 18), fill=0, width=5)

    if dia <= 15:
        equis(dia, "bajo")
    else:
        equis(dia - 16, "alto")
    # El mes, con el año manuscrito pegado a la derecha si se pide.
    equis(mes, "mes", ancho_extra=120 if con_el_anio_pegado else 0)
    salida = io.BytesIO()
    imagen.save(salida, "PNG")
    return salida.getvalue()


#: Lo que el OCR lee bajo la segunda fila: no todos, y alguno mal («2» por «21»).
PALABRAS = [
    (str(n), A + B * (n - 16) - 8, Y_NUMEROS_2, 16, 12) for n in (16, 18, 19, 20, 27, 28, 29, 30)
] + [("2", A + B * 5 - 8, Y_NUMEROS_2, 8, 12), ("20220125", 200, 247, 74, 14)]


class TestLasCasillas:
    @pytest.mark.parametrize(("dia", "mes"), [(26, 1), (10, 12), (1, 6), (31, 2), (15, 11)])
    def test_lee_el_dia_y_el_mes_marcados(self, dia, mes):
        assert casillas_marcadas(_guia(dia, mes), PALABRAS) == (dia, mes)

    def test_la_x_del_mes_pegada_al_anio_manuscrito(self):
        """UPD2321099: la X del mes 12 sigue en el «2020» escrito a mano."""
        assert casillas_marcadas(_guia(10, 12, con_el_anio_pegado=True), PALABRAS) == (10, 12)

    def test_sin_numeros_legibles_no_adivina(self):
        assert casillas_marcadas(_guia(10, 12), []) == (None, None)


class TestElAnio:
    def test_el_de_la_fecha_impresa(self):
        assert fecha_de_la_guia(_guia(26, 1), PALABRAS, "") == date(2022, 1, 26)

    def test_un_mes_anterior_a_la_admision_es_del_anio_siguiente(self):
        palabras = [p for p in PALABRAS if p[0] != "20220125"] + [("20211228", 200, 247, 74, 14)]
        assert fecha_de_la_guia(_guia(4, 1), palabras, "") == date(2022, 1, 4)
