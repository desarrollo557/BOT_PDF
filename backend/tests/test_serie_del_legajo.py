"""La copia de otra resolución de rectoría va dentro de la que la trae.

Medido el 2026-10-29 contra el INVENTARIO DOCUMENTAL de «RESOLUCIONES DE
RECTORIA 3220 - 3259»: una fila por resolución del rango, con sus folios; las
copias encuadernadas detrás cuentan dentro de la resolución que las trae. Las
secuencias de abajo son las de las páginas reales de la muestra.
"""

from __future__ import annotations

from datetime import date

from resolutions.domain.serie_del_legajo import (
    completar_por_la_serie,
    copias_fuera_de_la_serie,
    serie_del_legajo,
)


def paginas(*tramos: tuple[str | None, int]) -> list[str | None]:
    """Las páginas de un legajo: (número, cuántas páginas lo repiten)."""
    return [codigo for codigo, veces in tramos for _ in range(veces)]


class TestLasCopias:
    def test_la_copia_hacia_atras_va_dentro(self):
        # 02991-02998: la 02991 trae detrás la 00121 y la 01206 que la modifica.
        legajo = paginas(("02991", 3), ("00121", 5), ("01206", 2), ("02992", 34), ("02993", 33))
        assert copias_fuera_de_la_serie(legajo) == {"00121", "01206"}

    def test_la_copia_de_otro_ano_que_salta_miles_va_dentro(self):
        # 00073-00082: la 02852 de 2024 detrás de la 00075.
        legajo = paginas(("00074", 22), ("00075", 3), ("02852", 7), ("00076", 12))
        assert copias_fuera_de_la_serie(legajo) == {"02852"}

    def test_varias_copias_entre_las_del_rango(self):
        # 03522-03529: cuatro programas de otros números encuadernados detrás.
        legajo = paginas(
            ("03522", 99), ("03523", 43), ("03524", 10), ("00958", 36), ("03525", 7),
            ("01925", 34), ("03526", 24), ("01776", 39), ("03527", 8), ("03300", 35),
            ("03528", 5), ("03529", 30),
        )
        assert copias_fuera_de_la_serie(legajo) == {"00958", "01925", "01776", "03300"}

    def test_un_legajo_que_empieza_por_una_copia_no_la_toma_por_la_serie(self):
        legajo = paginas(("00958", 30), ("03522", 10), ("03523", 10), ("03524", 10))
        assert serie_del_legajo(legajo) == {"03522", "03523", "03524"}


class TestLaSerieNoSePierde:
    def test_los_saltos_del_inventario_siguen_en_la_serie(self):
        # El inventario salta de 2 a 4 entre resoluciones, y hasta 120 (02284 -> 02404).
        legajo = paginas(("02280", 5), ("02284", 5), ("02404", 5), ("02407", 5))
        assert copias_fuera_de_la_serie(legajo) == set()

    def test_una_sola_resolucion_con_su_copia_gana_la_de_mas_paginas(self):
        # 00317: 190 páginas suyas y una copia corta de la 00290.
        legajo = paginas(("00317", 190), ("00290", 5))
        assert serie_del_legajo(legajo) == {"00317"}

    def test_las_paginas_sin_numero_y_las_de_facultad_no_cuentan(self):
        legajo = paginas(("00384", 2), (None, 3), ("006-2025", 4), ("00385", 4))
        assert copias_fuera_de_la_serie(legajo) == set()
        assert serie_del_legajo(legajo) == {"00384", "00385"}

    def test_un_legajo_sin_numeros(self):
        assert serie_del_legajo([None, None]) == set()
        assert copias_fuera_de_la_serie([]) == set()


class TestLasFechasPorLaSerie:
    def test_entre_dos_iguales_es_esa(self):
        # 03523: fórmula ilegible entre la 03522 y la 03524, las dos del 19 de diciembre.
        dic19 = date(2025, 12, 19)
        assert completar_por_la_serie([dic19, None, dic19]) == [dic19, dic19, dic19]

    def test_entre_dos_distintas_la_de_antes(self):
        assert completar_por_la_serie([date(2025, 2, 24), None, date(2025, 2, 28)])[1] == date(2025, 2, 24)

    def test_en_los_extremos_la_vecina_que_haya(self):
        enero = date(2025, 1, 30)
        assert completar_por_la_serie([None, enero, None]) == [enero, enero, enero]
        assert completar_por_la_serie([None, None]) == [None, None]
