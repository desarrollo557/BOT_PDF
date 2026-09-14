"""Abandonar el inventario que se está levantando para un documento ya procesado.

Levantar un FUID a petición vuelve a leer el documento entero, y en un libro de
cuatrocientos folios eso son minutos. La carga útil de ese trabajo viajaba sin
canal de control -- sin `controls` -- así que el worker caía en el control nulo
y la única salida era esperar a que terminara.

Lo que se prueba aquí son las dos mitades del arreglo: que la carga útil lleve
el canal, y que la orden de abandonar tenga por dónde entrar. Tiene que ser una
clave propia y un endpoint propio, porque el trabajo original ya terminó: el
endpoint que detiene trabajos exige que el trabajo esté en vuelo, y contesta que
no hay nada que detener.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from resolutions.application.control import Cancelled, RunState

pytest.importorskip("httpx")


def _documento_terminado(main, nombre="libro.pdf"):
    """Un trabajo que ya se procesó, que es el único al que se le pide FUID."""
    job = main.contexto.registry.create(nombre, Path(nombre))
    main.contexto.registry.mark_done(job, {"document": nombre})
    return job


async def _levantar(main, job_id, monkeypatch):
    # En hilos y no en procesos, igual que las demás pruebas de esta ruta: un
    # doble definido dentro de una prueba no se puede enviar a otro proceso.
    from resolutions.api.routers import fuid

    with ThreadPoolExecutor(1) as pool:
        monkeypatch.setattr(main.contexto, "pool", pool)
        await fuid._levantar_fuid(main.contexto, job_id)


class TestLaCargaUtilLlevaPorDondeParar:
    @pytest.mark.asyncio
    async def test_lleva_el_canal_de_control(self, client, monkeypatch):
        from resolutions.api import main

        job = _documento_terminado(main)
        visto = {}
        monkeypatch.setattr(main.contexto, "procesar", lambda payload: visto.update(payload) or {})

        await _levantar(main, job.id, monkeypatch)

        assert visto.get("controls") is not None, (
            "sin `controls` el worker cae en el control nulo y no hay forma de pararlo"
        )

    @pytest.mark.asyncio
    async def test_bajo_una_clave_que_no_es_la_del_trabajo(self, client, monkeypatch):
        # La del trabajo la reutiliza el registro para decir en qué estado
        # quedó la separación que ya ocurrió. Compartirla haría que abandonar
        # el inventario y abandonar el corte fueran la misma orden.
        from resolutions.api import main

        job = _documento_terminado(main)
        visto = {}
        monkeypatch.setattr(main.contexto, "procesar", lambda payload: visto.update(payload) or {})

        await _levantar(main, job.id, monkeypatch)

        assert visto["control_key"] != job.id
        assert job.id in visto["control_key"], "la clave tiene que decir de qué documento es"

    @pytest.mark.asyncio
    async def test_y_declara_a_donde_se_entrego(self, client, monkeypatch):
        # Es una columna de la planilla. Sin esto, el FUID que se pide después
        # declaraba destino vacío para un documento entregado en una carpeta.
        from resolutions.api import main

        job = _documento_terminado(main)
        job.destination = "D:/archivo/2026"
        visto = {}
        monkeypatch.setattr(main.contexto, "procesar", lambda payload: visto.update(payload) or {})

        await _levantar(main, job.id, monkeypatch)

        assert visto["destination"] == "D:/archivo/2026"


class TestElTallerLeeEsaClave:
    """El control se arma con `control_key` cuando viene, y con el trabajo si no."""

    def test_sin_clave_propia_manda_el_trabajo(self):
        from resolutions.api.worker.taller import _control

        control = _control({"job_id": "j1", "controls": {"j1": str(RunState.CANCELLED)}})
        with pytest.raises(Cancelled):
            control.check()

    def test_con_clave_propia_manda_la_clave(self):
        from resolutions.api.worker.taller import _control

        controls = {"j1": str(RunState.CANCELLED), "fuid:j1": str(RunState.RUNNING)}
        control = _control({"job_id": "j1", "controls": controls, "control_key": "fuid:j1"})
        # La orden de cancelar es para el trabajo, no para este inventario.
        control.check()

    def test_y_la_orden_llega_por_ella(self):
        from resolutions.api.worker.taller import _control

        controls = {"fuid:j1": str(RunState.CANCELLED)}
        control = _control({"job_id": "j1", "controls": controls, "control_key": "fuid:j1"})
        with pytest.raises(Cancelled):
            control.check()


class TestAbandonarElInventario:
    def test_sin_nada_levantandose_no_hay_nada_que_abandonar(self, client):
        respuesta = client.delete("/api/jobs/inexistente/fuid")

        assert respuesta.status_code == 409
        assert "No se está levantando" in respuesta.json()["detail"]

    def test_un_fuid_en_curso_se_abandona(self, client):
        from resolutions.api import main

        job = _documento_terminado(main)
        # Así lo deja el endpoint que lo pide: la clave existe y vale None
        # mientras el worker trabaja.
        main.contexto.fuid_jobs[job.id] = None

        respuesta = client.delete(f"/api/jobs/{job.id}/fuid")

        assert respuesta.status_code == 200
        assert respuesta.json()["cancelling"] is True
        assert main.contexto.controls[f"fuid:{job.id}"] == str(RunState.CANCELLED)

    def test_uno_que_ya_fallo_no_se_abandona_otra_vez(self, client):
        from resolutions.api import main

        job = _documento_terminado(main)
        main.contexto.fuid_jobs[job.id] = "algo se rompió"

        assert client.delete(f"/api/jobs/{job.id}/fuid").status_code == 409

    @pytest.mark.asyncio
    async def test_abandonar_no_se_cuenta_como_error_del_documento(self, client, monkeypatch):
        # Un documento abandonado no está roto, y la pantalla no debe pintarlo
        # como si lo estuviera.
        from resolutions.api import main
        from resolutions.api.routers import fuid

        job = _documento_terminado(main)

        def abandona(payload):
            raise Cancelled("el operador canceló el trabajo")

        monkeypatch.setattr(main.contexto, "procesar", abandona)

        await _levantar(main, job.id, monkeypatch)
        estado = await fuid.job_fuid_status(main.contexto, job.id)

        assert estado["ready"] is False
        assert estado["error"] == "Se abandonó el inventario de este documento"
        assert "Cancelled" not in str(estado["error"]), "no se le enseña el nombre de la excepción"

    @pytest.mark.asyncio
    async def test_la_clave_de_control_no_queda_tirada(self, client, monkeypatch):
        # Una clave que sobrevive al trabajo cancela el siguiente intento antes
        # de que empiece, que es como un botón deja de funcionar para siempre.
        from resolutions.api import main

        job = _documento_terminado(main)
        monkeypatch.setattr(main.contexto, "procesar", lambda payload: {})

        await _levantar(main, job.id, monkeypatch)

        assert f"fuid:{job.id}" not in main.contexto.controls
