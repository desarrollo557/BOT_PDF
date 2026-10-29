"""El rendimiento del equipo y del bot, en vivo (2026-10-29).

El operador lo pidió para «tener todo muy bien controlado»: ese mismo día el
otro equipo se ahogó con diez PDF de 200 MB a la vez y sólo se supo por los
registros del servicio.
"""

from __future__ import annotations

import sys

import pytest

from resolutions.api.routers import rendimiento


@pytest.fixture(autouse=True)
def _desde_cero(monkeypatch):
    monkeypatch.setattr(rendimiento, "_cpu_antes", None)
    rendimiento._muestras.clear()


class TestElEndpoint:
    def test_dice_lo_del_equipo_y_lo_del_bot(self, client):
        assert "rendimiento" in client.get("/api/health").json()["features"]
        primera = client.get("/api/rendimiento").json()
        segunda = client.get("/api/rendimiento").json()
        assert set(primera) == {"equipo", "bot"}
        assert set(segunda["equipo"]) == {"cpu", "nucleos", "carga", "memoria_usada", "memoria_total"}
        assert set(segunda["bot"]) == {
            "memoria", "procesos", "documentos_en_curso", "en_cola",
            "paginas_por_minuto", "documentos_por_minuto",
        }
        assert segunda["bot"]["en_cola"] == 0
        if sys.platform != "win32":
            # En el contenedor se mide todo; en Windows sin Docker, lo que no hay es None.
            assert segunda["equipo"]["memoria_total"] > segunda["equipo"]["memoria_usada"] > 0
            assert segunda["bot"]["memoria"] > 0


class TestElRitmo:
    def test_paginas_y_documentos_por_minuto(self, monkeypatch):
        reloj = iter([100.0, 130.0, 160.0])
        monkeypatch.setattr(rendimiento.time, "monotonic", lambda: next(reloj))
        assert rendimiento._ritmo(0, 0) == (None, None)
        assert rendimiento._ritmo(150, 1) == (300.0, 2.0)
        # Al minuto la primera muestra sale de la ventana: cuenta desde la segunda.
        assert rendimiento._ritmo(300, 2) == (300.0, 2.0)

    def test_si_se_limpia_la_pantalla_empieza_de_nuevo(self, monkeypatch):
        reloj = iter([0.0, 30.0, 40.0])
        monkeypatch.setattr(rendimiento.time, "monotonic", lambda: next(reloj))
        rendimiento._ritmo(500, 10)
        rendimiento._ritmo(600, 11)
        # Los contadores bajaron: no hay un ritmo negativo, hay que volver a medir.
        assert rendimiento._ritmo(20, 0) == (None, None)
