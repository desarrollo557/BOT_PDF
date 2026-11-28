"""El latido de un trabajo (2026-11-27): lo que trabaja dice que sigue vivo, y el vigilante lo cree.

El operador vio «Sin novedades desde hace 10 min» en libros de actas de grado
con «OCR + IA» que estaban trabajando: la etapa «asegurando el nombre de 124
graduado(s)» hacía una petición a la IA por graduado sin anunciar nada más, y a
los 20 minutos el vigilante los daba por atascados y los reintentaba al final.
"""

from __future__ import annotations

import time

import pytest

from resolutions.api.jobs import JobProgress
from resolutions.application import latido
from resolutions.application.consumo import Consumo
from resolutions.application.progress import Stage


@pytest.fixture(autouse=True)
def _sin_latido_de_otra_prueba():
    latido.desactivar()
    yield
    latido.desactivar()


class TestElLatido:
    def test_sin_trabajo_no_hace_nada(self):
        latido.pulso()

    def test_avisa_como_mucho_una_vez_cada_intervalo(self, monkeypatch):
        reloj = [1000.0]
        monkeypatch.setattr(latido.time, "monotonic", lambda: reloj[0])
        avisos: list[int] = []
        latido.activar(lambda: avisos.append(1))
        latido.pulso()
        latido.pulso()
        assert len(avisos) == 1
        reloj[0] += latido.INTERVALO
        latido.pulso()
        assert len(avisos) == 2

    def test_un_aviso_que_falla_no_rompe_la_lectura(self):
        def roto() -> None:
            raise RuntimeError("la cola de avance se cerró")

        latido.activar(roto)
        latido.pulso()

    def test_apagado_no_avisa(self):
        avisos: list[int] = []
        latido.activar(lambda: avisos.append(1))
        latido.desactivar()
        latido.pulso()
        assert avisos == []


class TestCadaPeticionLate:
    @pytest.mark.parametrize("anotar", ["peticion", "rechazo", "fallo"])
    def test_lo_que_anota_el_contador_de_la_ia(self, anotar):
        avisos: list[int] = []
        latido.activar(lambda: avisos.append(1))
        getattr(Consumo(), anotar)("mistral-ocr")
        assert avisos == [1]


class TestElVigilanteLoCree:
    def test_refresca_el_silencio_sin_cambiar_la_etapa(self):
        progreso = JobProgress()
        progreso.apply({"stage": "verifying", "detail": "asegurando el nombre de 124 graduado(s)", "total": 124})
        progreso.last_event_monotonic = time.monotonic() - 600
        assert progreso.silent_seconds >= 600

        progreso.apply({"stage": str(Stage.LATIDO)})

        assert progreso.silent_seconds < 5
        assert progreso.stage == "verifying"
        assert progreso.detail == "asegurando el nombre de 124 graduado(s)"
        assert progreso.stage_total == 124
