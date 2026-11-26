"""Por dónde se empieza a recorrer el origen: primero lo que no está en el destino.

El operador, 2026-11-26: «que no se demore mucho buscando los ya procesados
para comenzar a procesar». Cada equipo tardaba de 3 a 28 min en tomar su primer
PDF porque lo pendiente de Magangué quedaba al final del orden de ruta.
"""

from __future__ import annotations

from pathlib import PureWindowsPath

from resolutions.application.orden_del_recorrido import (
    lo_pendiente_primero,
    nombre_de_la_carpeta,
)

MAGANGUE = "//200.100.20.97/afinia/REPOSITORIO/AFINIA/BOLIVAR SUR/COMERCIAL/MAGANGUE"


def _rutas(*nics: str) -> list[str]:
    return [f"{MAGANGUE}/{nic}" for nic in nics]


class TestLoPendientePrimero:
    def test_lo_que_falta_primero_y_cada_grupo_en_su_orden(self):
        origen = _rutas("1000265", "210847", "3000001", "8000001", "8000002", "910349", "9100001")
        destino = {"1000265", "210847", "3000001", "910349"}

        faltan, estan = lo_pendiente_primero(origen, destino)

        assert faltan == _rutas("8000001", "8000002", "9100001")
        assert estan == _rutas("1000265", "210847", "3000001", "910349")

    def test_sin_distinguir_mayusculas(self):
        # Windows y SMB no las distinguen: «Caja b» del origen es «CAJA B» del destino.
        faltan, estan = lo_pendiente_primero(_rutas("Caja b", "caja C", "Otra"), ["CAJA B", "caja c"])
        assert faltan == _rutas("Otra")
        assert estan == _rutas("Caja b", "caja C")

    def test_un_nombre_solo_coincide_entero(self):
        faltan, estan = lo_pendiente_primero(_rutas("100", "1000", "10"), {"1000"})
        assert faltan == _rutas("100", "10")
        assert estan == _rutas("1000")

    def test_sin_subcarpetas_no_hay_nada_que_repartir(self):
        assert lo_pendiente_primero([], {"1000265"}) == ([], [])
        assert lo_pendiente_primero([], set()) == ([], [])

    def test_todo_ya_en_el_destino(self):
        origen = _rutas("1", "2", "3")
        assert lo_pendiente_primero(origen, {"3", "2", "1"}) == ([], origen)

    def test_nada_en_el_destino(self):
        # Un destino vacío o recién creado: todo es pendiente, en orden de ruta.
        origen = _rutas("1", "2", "3")
        assert lo_pendiente_primero(origen, set()) == (origen, [])
        assert lo_pendiente_primero(origen, {"otra cosa"}) == (origen, [])

    def test_vale_cualquier_iterable_y_no_toca_lo_que_recibe(self):
        destino = {"B"}
        faltan, estan = lo_pendiente_primero(iter(_rutas("a", "b")), (n for n in destino))
        assert (faltan, estan) == (_rutas("a"), _rutas("b"))
        assert destino == {"B"}

    def test_el_nombre_lo_dice_quien_llama(self):
        cajas = [("1000265", 3), ("8000001", 1)]
        faltan, estan = lo_pendiente_primero(cajas, {"1000265"}, nombre=lambda caja: caja[0])
        assert faltan == [("8000001", 1)] and estan == [("1000265", 3)]


class TestElNombreDeLaCarpeta:
    def test_de_una_ruta_de_red_o_del_equipo(self):
        assert nombre_de_la_carpeta(f"{MAGANGUE}/1000265") == "1000265"
        assert nombre_de_la_carpeta(r"\\200.100.20.97\afinia\MAGANGUE\1000265") == "1000265"
        assert nombre_de_la_carpeta(PureWindowsPath(r"C:\origen\1000265")) == "1000265"
        assert nombre_de_la_carpeta("/equipo/c/origen/1000265/") == "1000265"
