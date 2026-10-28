"""Lo que corre de fondo no se muere en silencio.

Las tareas que el servicio deja corriendo -- la que pasa los eventos del worker
al registro, la que lanza cada trabajo subido -- morían sin dejar más que una
línea en DEBUG, que con el nivel por omisión no se ve. Una cola de progreso
muerta deja a todos los trabajos sin noticias: el vigilante los da por
atascados a los veinte minutos y tumba el pool creyéndolo congelado. Un trabajo
cuya tarea murió antes de empezar se queda «en cola» para siempre (2026-10-27).
"""

from __future__ import annotations

import asyncio
import queue
from types import SimpleNamespace

from resolutions.api.main import _drain_progress


class _Registro:
    def __init__(self, revienta_con: object):
        self.revienta_con = revienta_con
        self.aplicados: list[object] = []

    def apply_progress(self, evento):
        if evento is self.revienta_con:
            raise KeyError("un evento sin el campo que se esperaba")
        self.aplicados.append(evento)


def test_un_evento_malformado_no_mata_la_cola_de_progreso():
    malo, bueno = object(), object()
    cola: queue.Queue = queue.Queue()
    for evento in (malo, bueno, None):
        cola.put(evento)
    registro = _Registro(revienta_con=malo)

    asyncio.run(_drain_progress(SimpleNamespace(progress_queue=cola, registry=registro)))

    assert registro.aplicados == [bueno]


def test_si_la_cola_se_cae_queda_en_el_registro_a_la_vista(caplog):
    class _Caida:
        def get(self):
            raise EOFError("el Manager se fue")

    with caplog.at_level("WARNING", logger="resolutions.api.main"):
        asyncio.run(_drain_progress(SimpleNamespace(progress_queue=_Caida(), registry=_Registro(None))))

    assert any("cola de progreso" in registro.message for registro in caplog.records)


def test_un_trabajo_que_falla_antes_de_empezar_no_se_queda_en_cola(tmp_path):
    """Lo que fallaba antes de llegar al pool -- leer el canal de control -- mataba la tarea en silencio."""
    from resolutions.api.ejecucion import _run
    from resolutions.api.jobs import JobRegistry, JobState

    class _CanalCaido:
        def get(self, *_):
            raise BrokenPipeError(32, "El canal de control se cerró")

    registro = JobRegistry()
    trabajo = registro.create(filename="a.pdf", source=tmp_path / "a.pdf", owns_source=False, size=1)
    ctx = SimpleNamespace(controls=_CanalCaido(), registry=registro, settings=SimpleNamespace())

    asyncio.run(_run(ctx, trabajo))

    assert trabajo.state is JobState.FAILED
    assert trabajo.error


def test_el_fuid_a_peticion_que_falla_antes_del_pool_lo_dice(tmp_path):
    """Sin esto la pantalla se quedaba diciendo «levantando…» para siempre."""
    from resolutions.api.routers.fuid import _levantar_fuid_sin_colgarse

    class _RegistroCaido:
        def get(self, _):
            raise PermissionError(13, "Permission denied", "a.pdf")

    ctx = SimpleNamespace(registry=_RegistroCaido(), fuid_jobs={"x": None})

    asyncio.run(_levantar_fuid_sin_colgarse(ctx, "x"))

    assert ctx.fuid_jobs["x"]
    assert "PermissionError" not in ctx.fuid_jobs["x"]


def test_reanudar_no_cuenta_la_pausa_como_silencio(tmp_path):
    """Pausado media hora, al reanudar el vigilante lo daba por atascado en el acto."""
    import time

    from resolutions.api.jobs import JobRegistry

    registro = JobRegistry()
    trabajo = registro.create(filename="a.pdf", source=tmp_path / "a.pdf", owns_source=False, size=1)
    registro.mark_running(trabajo)
    trabajo.progress.last_event_monotonic = time.monotonic() - 30 * 60
    registro.mark_paused(trabajo)

    registro.mark_resumed(trabajo)

    assert trabajo.progress.silent_seconds < 5


def test_tropiezos_sueltos_en_una_corrida_larga_no_la_tumban(tmp_path, monkeypatch):
    """Tres errores del bucle en días de vigilancia la dejaban en FAILED: el contador no volvía a cero."""
    from dataclasses import replace

    from resolutions.api import folders
    from resolutions.api.folders import FolderRunner, RunState
    from resolutions.api.jobs import JobRegistry
    from resolutions.api.settings import Settings

    ajustes = replace(
        Settings(), upload_dir=tmp_path / "u", output_dir=tmp_path / "o", ledger_path=tmp_path / "i.jsonl"
    )
    ajustes.ensure_directories()
    (tmp_path / "origen").mkdir()
    (tmp_path / "destino").mkdir()
    monkeypatch.setattr(folders, "ESPERA_TRAS_TROPIEZO", 0.0)

    async def no_corre(job):
        raise AssertionError("no hay PDF que procesar")

    motor = FolderRunner(JobRegistry(), ajustes, no_corre, watch_interval=0.0)
    llamadas = {"n": 0}

    async def por_lotes(run):
        llamadas["n"] += 1
        if llamadas["n"] >= 10:
            run.watch = False
        elif llamadas["n"] % 2:
            raise RuntimeError("el disco del destino un momento")
        return False

    monkeypatch.setattr(motor, "_procesar_por_lotes", por_lotes)

    async def ir():
        run = motor.start(str(tmp_path / "origen"), str(tmp_path / "destino"), watch=True)
        for _ in range(500):
            if not run.active:
                break
            await asyncio.sleep(0.01)
        return run

    run = asyncio.run(ir())

    assert llamadas["n"] >= 10
    assert run.state is RunState.DONE, run.error


def test_las_noticias_llegan_aunque_los_hilos_del_servicio_esten_ocupados():
    """Con el pool de hilos lleno -- descargas de la red esperando turno, entregas
    esperando el cerrojo --, la cola de progreso compartía ese pool y no se leía:
    todos los documentos salían «Sin novedades» y a los veinte minutos el
    vigilante mataba documentos sanos y los mandaba a reprocesar (2026-10-28)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    evento = object()
    cola: queue.Queue = queue.Queue()
    registro = _Registro(None)
    soltar = threading.Event()

    async def ir():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=2))
        # Los dos hilos del pool, ocupados como los tendría una descarga lenta.
        ocupados = [loop.run_in_executor(None, soltar.wait) for _ in range(2)]
        drenaje = asyncio.create_task(_drain_progress(SimpleNamespace(progress_queue=cola, registry=registro)))
        cola.put(evento)
        try:
            for _ in range(100):
                if registro.aplicados:
                    break
                await asyncio.sleep(0.01)
            return list(registro.aplicados)
        finally:
            soltar.set()
            cola.put(None)
            await drenaje
            await asyncio.gather(*ocupados)

    assert asyncio.run(ir()) == [evento]
