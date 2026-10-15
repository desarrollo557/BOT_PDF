"""Pausar, reanudar y cancelar un trabajo que ya está corriendo.

Lo que se fija aquí es lo que hace segura esta función: que la orden se atienda
entre una página y la siguiente y nunca a mitad de una escritura, que reanudar
continúe en vez de empezar de nuevo, y que perder el canal de control no pare un
documento —sería perderlo por un fallo de la telemetría—.
"""

from __future__ import annotations

import threading
import time

import pytest
from fakes import BODY, FakeOcr, FakePage, FakePageSource

from resolutions.application.control import (
    Cancelled,
    FlagRunControl,
    NullRunControl,
    RunState,
)
from resolutions.application.pipeline import ClassificationPipeline, PipelineConfig

pytest.importorskip("httpx")


def digital(header: str) -> FakePage:
    return FakePage(text=f"{header}\n{BODY}")


class TestElControlQueNoPara:
    def test_no_hace_nada(self):
        assert NullRunControl().check() is None


class TestSeguirYAbandonar:
    def test_corriendo_devuelve_de_inmediato(self):
        control = FlagRunControl(lambda: str(RunState.RUNNING))
        assert control.check() is None

    def test_cancelado_levanta(self):
        control = FlagRunControl(lambda: str(RunState.CANCELLED))
        with pytest.raises(Cancelled):
            control.check()

    def test_un_estado_que_no_existe_no_para_el_trabajo(self):
        """Un valor corrupto no es motivo para abandonar un documento."""
        assert FlagRunControl(lambda: "vete-a-saber").check() is None

    def test_perder_el_canal_tampoco_lo_para(self):
        def se_rompe():
            raise ConnectionError("el manager se cayó")

        assert FlagRunControl(se_rompe).check() is None


class TestPausa:
    def test_bloquea_mientras_esta_en_pausa_y_sigue_al_reanudar(self):
        estado = [str(RunState.PAUSED)]
        control = FlagRunControl(lambda: estado[0], poll_seconds=0.01)

        siguio = threading.Event()

        def trabajar():
            control.check()
            siguio.set()

        hilo = threading.Thread(target=trabajar, daemon=True)
        hilo.start()

        # Sigue parado mientras nadie lo reanude.
        assert not siguio.wait(timeout=0.15)

        estado[0] = str(RunState.RUNNING)
        assert siguio.wait(timeout=2.0), "reanudar tiene que dejarlo continuar"
        hilo.join(timeout=1.0)

    def test_se_puede_cancelar_estando_en_pausa(self):
        estado = [str(RunState.PAUSED)]
        control = FlagRunControl(lambda: estado[0], poll_seconds=0.01)

        fallo: list[BaseException] = []

        def trabajar():
            try:
                control.check()
            except BaseException as error:  # noqa: BLE001 - se comprueba fuera
                fallo.append(error)

        hilo = threading.Thread(target=trabajar, daemon=True)
        hilo.start()
        time.sleep(0.05)
        estado[0] = str(RunState.CANCELLED)
        hilo.join(timeout=2.0)

        assert fallo and isinstance(fallo[0], Cancelled)


class TestLaCascadaObedece:
    def test_cancelar_abandona_el_documento(self):
        """Y lo hace desde donde esté, sin terminar las páginas que faltan."""
        leidas: list[int] = []

        class CancelaTrasLaTercera:
            def check(self):
                leidas.append(len(leidas) + 1)
                if len(leidas) > 3:
                    raise Cancelled("basta")

        source = FakePageSource(pages=[digital("RESOLUCION No. 00412") for _ in range(20)])
        pipeline = ClassificationPipeline(
            ocr=FakeOcr(),
            config=PipelineConfig(max_workers=1, verify_declarations=False),
            control=CancelaTrasLaTercera(),
        )
        with pytest.raises(Cancelled):
            pipeline.classify(source)
        assert len(leidas) < 20, "no debería haber leído el documento entero"

    def test_sin_control_se_procesa_todo(self):
        source = FakePageSource(pages=[digital("RESOLUCION No. 00412") for _ in range(5)])
        pipeline = ClassificationPipeline(
            ocr=FakeOcr(), config=PipelineConfig(max_workers=1, verify_declarations=False)
        )
        classifications, _ = pipeline.classify(source)
        assert len(classifications) == 5


class TestApi:
    def test_un_documento_que_no_existe_no_se_puede_pausar(self, client):
        assert client.post("/api/jobs/no-existe/pause").status_code == 404
        assert client.post("/api/jobs/no-existe/resume").status_code == 404
        assert client.post("/api/jobs/no-existe/cancel").status_code == 404

    def test_un_lote_que_no_existe_tampoco(self, client):
        assert client.post("/api/batches/no-existe/pause").status_code == 404

    def test_una_accion_que_no_existe_se_rechaza(self, client):
        batch = client.post("/api/batches", json={"name": "Lote"}).json()
        assert client.post(f"/api/batches/{batch['id']}/volar").status_code == 404

    def test_la_salud_anuncia_la_capacidad(self, client):
        assert "job-control" in client.get("/api/health").json()["features"]


class TestEsperarSinDejarDeEscuchar:
    """La orden se atiende también mientras se espera a otro hilo: una lectura de la IA."""

    @staticmethod
    def _cancelar_en(estado: dict, segundos: float) -> None:
        threading.Timer(segundos, lambda: estado.update(s=str(RunState.CANCELLED))).start()

    def test_aguardar_atiende_la_cancelacion_con_el_futuro_pendiente(self):
        from concurrent.futures import Future

        from resolutions.application.control import aguardar

        estado = {"s": str(RunState.RUNNING)}
        control = FlagRunControl(lambda: estado["s"])
        self._cancelar_en(estado, 0.2)
        inicio = time.monotonic()
        with pytest.raises(Cancelled):
            aguardar(Future(), control)  # un futuro que nunca termina
        assert time.monotonic() - inicio < 1.5

    def test_hilos_no_espera_la_cola_al_cancelar(self):
        from resolutions.application.control import hilos, mapear

        estado = {"s": str(RunState.RUNNING)}
        control = FlagRunControl(lambda: estado["s"])
        soltar = threading.Event()
        hechas: list[int] = []

        def tarea(n: int) -> int:
            if n == 0:
                soltar.wait(5)  # la que está en vuelo: una lectura lenta
            hechas.append(n)
            return n

        self._cancelar_en(estado, 0.2)
        inicio = time.monotonic()
        with pytest.raises(Cancelled), hilos(1) as pool:
            mapear(pool, tarea, range(20), control)
        assert time.monotonic() - inicio < 1.5
        soltar.set()
        time.sleep(0.1)
        # Las diecinueve encoladas no se leyeron: se descartaron.
        assert hechas == [0]


class TestDetenerUnaCarpetaParaElDocumentoEnCurso:
    def test_la_orden_llega_al_worker_y_se_limpia_al_soltarlo(self, tmp_path):
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        from types import SimpleNamespace

        from resolutions.api.ejecucion import _run
        from resolutions.api.jobs import Job, JobState

        soltado = threading.Event()

        def worker(payload):
            # Un worker que pregunta como los de verdad, hasta que le digan.
            while payload["controls"].get(payload["job_id"]) != str(RunState.CANCELLED):
                time.sleep(0.02)
            soltado.set()
            raise Cancelled("cancelado")

        class Registro:
            def mark_running(self, job):
                job.state = JobState.RUNNING

            def mark_cancelled(self, job):
                job.state = JobState.CANCELLED

            def mark_done(self, job, report):  # pragma: no cover - no debe pasar
                job.state = JobState.DONE

            mark_failed = mark_done

        ctx = SimpleNamespace(
            controls={},
            registry=Registro(),
            pool=ThreadPoolExecutor(1),
            procesar=worker,
            settings=SimpleNamespace(as_worker_payload=lambda: {}),
            progress_queue=None,
        )
        job = Job(id="j1", filename="libro.pdf", source=tmp_path / "libro.pdf", owns_source=False)

        async def escena():
            tarea = asyncio.create_task(_run(ctx, job))
            await asyncio.sleep(0.1)
            tarea.cancel()  # lo que hace detener la carpeta
            with pytest.raises(asyncio.CancelledError):
                await tarea
            # En el acto: cancelado en pantalla y la orden puesta para el worker.
            assert job.state is JobState.CANCELLED
            assert ctx.controls["j1"] == str(RunState.CANCELLED)
            for _ in range(50):
                if "j1" not in ctx.controls:
                    break
                await asyncio.sleep(0.02)

        asyncio.run(escena())
        ctx.pool.shutdown()
        assert soltado.is_set()
        # La orden se quitó sólo cuando el worker soltó el documento.
        assert "j1" not in ctx.controls
