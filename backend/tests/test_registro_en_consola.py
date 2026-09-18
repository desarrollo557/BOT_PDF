"""Todo lo que hace el servicio, en la consola y según ocurre.

Se fija que cada petición deje una línea con su duración y su query -- que es
donde viajan la acción, el tipo y el motor, o sea a qué habilidad fue cada
documento --, que el registro se configure una sola vez aunque se le pida dos,
y que los procesos del pool también lo configuren: en Windows nacen sin
manejadores, y es en ellos donde ocurre lo que interesa ver.
"""

from __future__ import annotations

import logging

import pytest

from resolutions.api.registro_en_consola import _Inmediato, configurar, configurar_worker

pytest.importorskip("httpx")


class TestCadaPeticionQuedaEnElRegistro:
    def test_con_ruta_codigo_y_duracion(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="resolutions.api.main"):
            client.get("/api/health")
        lineas = [r.getMessage() for r in caplog.records if r.name == "resolutions.api.main"]
        assert any(
            linea.startswith("GET /api/health -> 200 en ") and linea.endswith(" ms")
            for linea in lineas
        )

    def test_la_query_tambien(self, client, caplog):
        """La query es donde viaja a qué habilidad va el documento."""
        with caplog.at_level(logging.INFO, logger="resolutions.api.main"):
            client.get("/api/jobs?tipo=diploma")
        assert any("GET /api/jobs?tipo=diploma -> " in r.getMessage() for r in caplog.records)


class TestLaConfiguracion:
    def test_configurar_dos_veces_no_duplica_manejadores(self):
        configurar()
        cuantos = sum(isinstance(h, _Inmediato) for h in logging.getLogger().handlers)
        configurar()
        assert sum(isinstance(h, _Inmediato) for h in logging.getLogger().handlers) == cuantos == 1

    def test_lo_propio_se_ensena_entero_y_lo_ajeno_solo_si_avisa(self):
        configurar()
        assert logging.getLogger("resolutions").isEnabledFor(logging.INFO)
        assert not logging.getLogger("alguna.biblioteca").isEnabledFor(logging.INFO)

    def test_el_worker_se_presenta_al_nacer(self, caplog):
        with caplog.at_level(logging.INFO, logger="resolutions.worker"):
            configurar_worker()
        assert any("listo" in r.getMessage() for r in caplog.records if r.name == "resolutions.worker")
