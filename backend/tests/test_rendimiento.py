"""El rendimiento del equipo y del bot, en vivo (2026-10-29).

El operador lo pidió para «tener todo muy bien controlado»: ese mismo día el
otro equipo se ahogó con diez PDF de 200 MB a la vez y sólo se supo por los
registros del servicio.

Desde el 2026-11-27 lo del equipo lo mide ``adapters.recursos_del_equipo`` (ver
``test_recursos_del_equipo.py``), con un medidor de CPU propio de esta
pantalla: las respuestas no cambian.
"""

from __future__ import annotations

import sys

import pytest

from resolutions.adapters import recursos_del_equipo
from resolutions.api.routers import rendimiento


@pytest.fixture(autouse=True)
def _desde_cero(monkeypatch):
    monkeypatch.setattr(rendimiento, "_medidor_de_cpu", recursos_del_equipo.MedidorDeCpu())
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
        else:
            assert segunda["equipo"]["cpu"] is None and segunda["equipo"]["memoria_total"] is None
        assert segunda["equipo"]["nucleos"] == recursos_del_equipo.nucleos()

    def test_la_cpu_de_la_pantalla_no_le_roba_la_muestra_al_latido(self, client, tmp_path, monkeypatch):
        # Antes la muestra anterior era una variable global: el latido de la
        # corrida compartida, midiendo también, se la habría llevado.
        (tmp_path / "stat").write_text("cpu  100 0 100 800 0 0 0 0 0 0\n", encoding="ascii")
        monkeypatch.setattr(recursos_del_equipo, "PROC", tmp_path)
        del_latido = recursos_del_equipo.MedidorDeCpu()
        assert del_latido.medir() is None
        client.get("/api/rendimiento")
        (tmp_path / "stat").write_text("cpu  150 0 150 900 0 0 0 0 0 0\n", encoding="ascii")
        assert client.get("/api/rendimiento").json()["equipo"]["cpu"] == 50.0
        # El del latido compara con su propia muestra, no con la de la pantalla.
        assert del_latido.medir() == 50.0


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
