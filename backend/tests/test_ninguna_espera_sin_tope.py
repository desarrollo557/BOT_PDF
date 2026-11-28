"""Ninguna espera sin tope: lo que espera a la red, a un proceso o a otro equipo, se corta y se sigue (2026-11-28).

El operador, 2026-11-27: «que no se trabe por falta de petición o algo; un
sistema que cubra todos los escenarios». La auditoría de atascos encontró
esperas sin fin fuera del documento: un proceso del pool que no suelta un
documento cortado, el turno de la IA que se llevó un proceso muerto, las copias
de la red, las esperas de la corrida compartida, reclamar un PDF, el turno de
una carpeta dentro del mismo equipo, el listado del origen, el lector de las
noticias del worker y lo que se lee del origen antes del primer PDF. Cada una
tiene ya su tope; estas pruebas lo fijan con tiempos de décimas.

Nada llama a un proveedor, a la red ni abre un PDF de verdad.
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from resolutions.adapters import copia_vigilada, red_smb
from resolutions.adapters.coordinacion_en_disco import (
    CerrojoOcupado,
    Coordinacion,
    Reclamo,
    es_de_la_red,
)
from resolutions.api import ejecucion, folders
from resolutions.api.folders import FolderRun, FolderRunner, RunState
from resolutions.api.jobs import Job, JobRegistry, JobState
from resolutions.api.reintentos import es_transitorio, merece_otra_vuelta
from resolutions.api.settings import Settings


def _hasta(condicion, segundos: float = 5.0) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.01)
    return condicion()


@pytest.fixture
def ajustes(tmp_path):
    settings = replace(
        Settings(),
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "outputs",
        ledger_path=tmp_path / "inventory.jsonl",
        pausa_tras_fallos=0.01,
        espera_de_reintento=0.01,
    )
    settings.ensure_directories()
    (tmp_path / "origen").mkdir()
    (tmp_path / "destino").mkdir()
    return settings


def _motor(ajustes, registry, hechos: list | None = None, fuentes: list | None = None):
    hechos = hechos if hechos is not None else []

    async def run_job(job):
        hechos.append(job.filename)
        if fuentes is not None:
            fuentes.append((Path(job.source), Path(job.source).exists()))
        salida = ajustes.output_dir / job.id
        salida.mkdir(parents=True, exist_ok=True)
        (salida / "01_X.pdf").write_bytes(b"%PDF-1.4 out " + job.filename.encode())
        registry.mark_done(
            job,
            {
                "groups": [{"code": "01"}],
                "review_queue": [],
                "inventory": {"items": [{"file_name": "01_X.pdf", "first_page": 1}]},
            },
        )

    return FolderRunner(registry, ajustes, run_job, watch_interval=0.01), hechos


def _vaciar(motor, origen, destino, **opciones):
    async def ir():
        run = motor.start(str(origen), str(destino), **opciones)
        for _ in range(1500):
            if not run.active:
                break
            await asyncio.sleep(0.01)
        if run.escritor is not None and not run.escritor.done():
            await run.escritor
        return run

    return asyncio.run(ir())


# -- A4: el proceso que no suelta un documento cortado -------------------------------


class _Registro:
    """Lo mínimo del registro que usa `_correr`, con `snapshot` para mirar a los demás."""

    def __init__(self, otros=()):
        self.otros = list(otros)
        self.trabajos: list[Job] = []

    def mark_running(self, job):
        job.state = JobState.RUNNING
        if job not in self.trabajos:
            self.trabajos.append(job)

    def mark_done(self, job, report):
        job.state = JobState.DONE
        job.report = report

    def mark_failed(self, job, error):
        job.state = JobState.FAILED
        job.error = error

    def mark_cancelled(self, job):
        job.state = JobState.CANCELLED

    def publish(self, job):
        pass

    def get_batch(self, batch_id):
        return None

    def snapshot(self):
        return [*self.trabajos, *self.otros]


def _contexto(procesar, registro, **ajustes):
    return SimpleNamespace(
        controls={},
        registry=registro,
        pool=ThreadPoolExecutor(2),
        procesar=procesar,
        settings=SimpleNamespace(
            as_worker_payload=lambda: {},
            reintentos=ajustes.get("reintentos", 0),
            espera_de_reintento=0,
            minutos_sin_avance=ajustes.get("minutos_sin_avance", 0.001),
        ),
        progress_queue=None,
        ledger=SimpleNamespace(record=lambda *a, **k: None),
    )


def _otro_en_curso(silencio: float) -> Job:
    otro = Job(id="otro", filename="otro.pdf", source=Path("otro.pdf"), state=JobState.RUNNING)
    otro.progress.last_event_monotonic = time.monotonic() - silencio
    return otro


class TestElProcesoQueNoSuelta:
    """«Cortar» no liberaba el proceso: congelado en el lector nativo, quedaba ocupado hasta reiniciar."""

    def _correr(self, ctx, job, suelta, mientras):
        async def ir():
            await ejecucion._run(ctx, job)
            return await asyncio.to_thread(mientras)

        try:
            return asyncio.run(ir())
        finally:
            suelta.set()
            ctx.pool.shutdown()

    def test_si_nada_mas_avanza_se_cambia_el_pool(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ejecucion, "_VIGILANCIA", 0.02)
        monkeypatch.setattr(ejecucion, "ESPERA_AL_SOLTAR", 0.05)
        suelta = threading.Event()
        cambiados = []
        ctx = _contexto(lambda payload: suelta.wait(10) and {}, _Registro())
        ctx.rehacer_pool = lambda roto, matar=False: cambiados.append((roto, matar))
        job = Job(id="j1", filename="congelado.pdf", source=tmp_path / "x.pdf", owns_source=False)

        cambiado = self._correr(ctx, job, suelta, lambda: _hasta(lambda: cambiados))

        assert job.state is JobState.FAILED and "sin avanzar" in job.error
        assert cambiado and cambiados == [(ctx.pool, True)]

    def test_si_otro_avanza_no_se_toca(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ejecucion, "_VIGILANCIA", 0.02)
        monkeypatch.setattr(ejecucion, "ESPERA_AL_SOLTAR", 0.05)
        suelta = threading.Event()
        cambiados = []
        # El otro acaba de dar noticias, y las sigue dando (su última, siempre por delante).
        otro = _otro_en_curso(silencio=-3600)
        ctx = _contexto(lambda payload: suelta.wait(10) and {}, _Registro([otro]))
        ctx.rehacer_pool = lambda roto, matar=False: cambiados.append((roto, matar))
        job = Job(id="j1", filename="congelado.pdf", source=tmp_path / "x.pdf", owns_source=False)

        def mientras():
            time.sleep(0.4)
            # Y la orden de parar sigue puesta mientras el worker no lo suelte.
            return list(cambiados), ctx.controls.get("j1")

        assert self._correr(ctx, job, suelta, mientras) == ([], "cancelled")

    def test_lo_que_el_pool_nuevo_saco_de_su_cola_se_reintenta(self, tmp_path):
        """Cambiar el pool cancela lo que esperaba proceso: no lo canceló nadie, y acababa «cancelado» sin leerse."""
        from concurrent.futures import Future

        intentos = []

        class PoolQueCancela:
            def __init__(self):
                self.veces = 0

            def submit(self, fn, *args):
                self.veces += 1
                futuro: Future = Future()
                if self.veces == 1:
                    futuro.cancel()  # lo que hace ``shutdown(cancel_futures=True)``
                else:
                    intentos.append(1)
                    futuro.set_result({"groups": []})
                return futuro

        ctx = _contexto(lambda payload: {}, _Registro(), reintentos=1, minutos_sin_avance=0)
        ctx.pool = PoolQueCancela()
        ctx.rehacer_pool = lambda roto, matar=False: None
        job = Job(id="j1", filename="en-cola.pdf", source=tmp_path / "x.pdf", owns_source=False)

        asyncio.run(ejecucion._run(ctx, job))

        assert job.state is JobState.DONE
        assert intentos == [1]

    def test_el_reintento_lleva_el_turno_de_ia_de_ahora(self, tmp_path):
        from concurrent.futures.process import BrokenProcessPool

        vistos = []

        def procesar(payload):
            vistos.append(payload["turnos_de_ia"])
            if len(vistos) == 1:
                raise BrokenProcessPool("un proceso murió con un turno")
            return {"groups": []}

        ctx = _contexto(procesar, _Registro(), reintentos=1, minutos_sin_avance=0)
        ctx.turnos_de_ia = "viejo"

        def rehacer(roto, matar=False):
            ctx.turnos_de_ia = "nuevo"

        ctx.rehacer_pool = rehacer
        job = Job(id="j1", filename="libro.pdf", source=tmp_path / "x.pdf", owns_source=False)
        asyncio.run(ejecucion._run(ctx, job))
        ctx.pool.shutdown()

        assert job.state is JobState.DONE
        assert vistos == ["viejo", "nuevo"]


# -- A5: el turno de la IA que se llevó un proceso muerto ----------------------------


class TestElTurnoDeLaIA:
    def test_rehacer_el_pool_estrena_turnos(self):
        from resolutions.api.main import _rehacer_pool

        class Manager:
            def BoundedSemaphore(self, cuantos):  # noqa: N802 - el nombre del Manager
                return threading.BoundedSemaphore(cuantos)

        viejo = threading.BoundedSemaphore(2)
        viejo.acquire()
        viejo.acquire()  # los dos, en procesos que murieron
        roto = ThreadPoolExecutor(1)
        ajustes = replace(Settings(), document_workers=1, ia_a_la_vez=2)
        ctx = SimpleNamespace(pool=roto, settings=ajustes, manager=Manager(), turnos_de_ia=viejo)

        _rehacer_pool(ctx, roto, matar=True)
        try:
            assert ctx.turnos_de_ia is not viejo
            assert ctx.turnos_de_ia.acquire(blocking=False) and ctx.turnos_de_ia.acquire(blocking=False)
            # Quien llega con el pool ya cambiado no cambia nada.
            nuevo = ctx.turnos_de_ia
            _rehacer_pool(ctx, roto)
            assert ctx.turnos_de_ia is nuevo
        finally:
            ctx.pool.shutdown()

    def test_sin_turno_se_espera_un_minuto_y_no_diez(self):
        from resolutions.adapters import turnos

        assert turnos.ESPERA_MAXIMA == 60.0


# -- A6: las copias de la red, vigiladas ---------------------------------------------


class TestLaCopiaVigilada:
    def test_sin_mover_un_byte_se_corta_y_es_de_la_red(self):
        suelta = threading.Event()

        with pytest.raises(copia_vigilada.CopiaSinAvance) as cortada:
            copia_vigilada.vigilado(lambda vigilancia: suelta.wait(5), sin_avance=0.2, que="La copia de prueba")
        suelta.set()
        error = cortada.value
        assert isinstance(error, TimeoutError)
        assert es_transitorio(error) and es_de_la_red(error) and merece_otra_vuelta(error)
        assert str(error).startswith("La copia de prueba lleva 0 s sin mover un byte")

    def test_la_que_late_no_se_corta(self):
        def lenta(vigilancia):
            for _ in range(10):
                time.sleep(0.05)
                vigilancia.latir()
            return "copiada"

        assert copia_vigilada.vigilado(lenta, sin_avance=0.2) == "copiada"

    def test_esperar_el_turno_no_cuenta(self):
        turno = threading.Semaphore(0)

        def con_turno(vigilancia):
            with vigilancia.esperando():
                turno.acquire()
            return "con turno"

        threading.Timer(0.5, turno.release).start()
        assert copia_vigilada.vigilado(con_turno, sin_avance=0.2) == "con turno"

    def test_la_abandonada_no_escribe_nada_mas(self):
        suelta, escritos = threading.Event(), []

        def copia(vigilancia):
            suelta.wait(5)  # colgada en la red
            vigilancia.latir()
            escritos.append(b"bloque")

        with pytest.raises(copia_vigilada.CopiaSinAvance):
            copia_vigilada.vigilado(copia, sin_avance=0.1)
        suelta.set()
        time.sleep(0.2)
        assert escritos == []

    def test_traer_del_sistema_copia_entero_y_dice_cuanto(self, tmp_path):
        origen = tmp_path / "Z" / "UPD.pdf"
        origen.parent.mkdir()
        origen.write_bytes(b"%PDF-1.4 " + b"x" * (3 * red_smb.BLOQUE))
        avisos = []

        copia = red_smb.traer_del_sistema(origen, tmp_path / "local" / "UPD.pdf", al_avanzar=lambda c, t: avisos.append(c))

        assert copia.read_bytes() == origen.read_bytes()
        assert avisos[0] == 0 and avisos[-1] == origen.stat().st_size
        assert not list(tmp_path.rglob("*.part"))

    def test_traer_que_no_avanza_es_red_sin_avance(self, monkeypatch, tmp_path):
        monkeypatch.setattr(copia_vigilada, "SEGUNDOS_SIN_AVANCE", 0.2)
        monkeypatch.setattr(red_smb, "_descargas", {})
        suelta = threading.Event()
        monkeypatch.setattr(red_smb, "_llamar", lambda ruta, copiar: suelta.wait(5))

        try:
            with pytest.raises(red_smb.RedSinAvance) as cortada:
                red_smb.traer(r"\\srv\recurso\UPD.pdf", tmp_path / "UPD.pdf")
        finally:
            suelta.set()
        assert isinstance(cortada.value, red_smb.RedNoDisponible) and es_transitorio(cortada.value)
        assert not (tmp_path / "UPD.pdf").exists()

    def test_el_listado_pedido_por_delante_tiene_tope(self, monkeypatch):
        monkeypatch.setattr(red_smb, "SEGUNDOS_PARA_LISTAR", 0.2)
        monkeypatch.setattr(red_smb, "asegurar", lambda raiz: None)
        suelta = threading.Event()
        monkeypatch.setattr(red_smb, "_listado", lambda p, carpeta: suelta.wait(5) and [])

        try:
            with pytest.raises(red_smb.RedSinAvance, match="no contestó"):
                list(red_smb.iterar_carpetas([r"\\srv\recurso\210847"], al_fallar=lambda c, e: None))
        finally:
            suelta.set()

    def test_el_tiempo_de_recepcion_de_smbprotocol_baja_a_dos_minutos(self):
        import os

        assert os.environ["SMB_EXPERIMENTAL_TRANSPORT_RECEIVE_TIMEOUT"] == red_smb.SEGUNDOS_DE_RECEPCION == "120"

    def test_la_copia_al_destino_colgada_se_corta_sin_dejar_nada(self, monkeypatch, tmp_path):
        monkeypatch.setattr(copia_vigilada, "SEGUNDOS_SIN_AVANCE", 0.2)
        suelta = threading.Event()
        monkeypatch.setattr(folders.shutil, "copyfileobj", lambda origen, destino, *_: suelta.wait(5))
        desde = tmp_path / "x.pdf"
        desde.write_bytes(b"0123456789")
        destino = tmp_path / "dest"
        destino.mkdir()

        with pytest.raises(TimeoutError) as cortada:
            folders._copiar(desde, destino / "x.pdf")
        suelta.set()
        assert es_de_la_red(cortada.value)
        # El «.part» abandonado lo borra su hilo cuando la red le devuelve el control.
        assert _hasta(lambda: not list(destino.iterdir()))

    def test_la_copia_directa_colgada_es_de_la_red(self, monkeypatch, tmp_path):
        monkeypatch.setattr(copia_vigilada, "SEGUNDOS_SIN_AVANCE", 0.2)
        suelta = threading.Event()
        monkeypatch.setattr(folders.shutil, "copyfileobj", lambda origen, destino, *_: suelta.wait(5))
        desde = tmp_path / "x.pdf"
        desde.write_bytes(b"0123456789")
        carpeta = tmp_path / "dest"
        carpeta.mkdir()

        with pytest.raises(TimeoutError) as cortada:
            folders._copiar_directo(desde, carpeta, "x.pdf")
        suelta.set()
        # Con el archivo que se intentó: el reintento escribe encima de ése.
        assert es_de_la_red(cortada.value) and cortada.value.filename == str(carpeta / "x.pdf")
        assert "sin mover un byte" in str(cortada.value)

    def test_lo_que_no_vuelve_suelta_la_ranura(self, ajustes):
        motor = FolderRunner(JobRegistry(), ajustes, lambda job: None)
        motor.TOPE_DE_LA_RED = 0.1
        suelta = threading.Event()

        async def ir():
            try:
                return await motor._con_tope(asyncio.to_thread(suelta.wait, 5), "La descarga de «x.pdf»")
            finally:
                suelta.set()

        with pytest.raises(folders.SinRespuestaDeLaRed, match="La descarga de «x.pdf» lleva 0 min") as cortada:
            asyncio.run(ir())
        assert es_transitorio(cortada.value) and merece_otra_vuelta(cortada.value)


# -- M11: el origen de red que abre el sistema, copiado antes a local ----------------


class TestElOrigenDeRedDelSistema:
    def test_se_procesa_desde_una_copia_local_que_no_queda(self, ajustes, tmp_path, monkeypatch):
        from resolutions.adapters import acceso

        origen = tmp_path / "origen"
        (origen / "210847").mkdir()
        (origen / "210847" / "UPD1.pdf").write_bytes(b"%PDF-1.4 fake")
        monkeypatch.setattr(acceso, "es_de_red", lambda ruta: Path(str(ruta)).name == "origen")
        monkeypatch.setattr(folders, "SEGUNDOS_DE_CALMA", 0)
        registro, fuentes = JobRegistry(), []
        motor, hechos = _motor(ajustes, registro, fuentes=fuentes)

        run = _vaciar(motor, origen, tmp_path / "destino")

        assert run.state is RunState.DONE, run.error
        assert hechos == [str(Path("210847") / "UPD1.pdf")]
        leido, existia = fuentes[0]
        copias = Path(ajustes.upload_dir) / FolderRunner.CARPETA_DE_COPIAS / run.id
        assert existia and copias in leido.parents
        # La ruta del origen se conserva detrás de la carpeta de copias (el NIC, la caja).
        assert leido.parts[-2:] == ("210847", "UPD1.pdf")
        assert not copias.exists()
        assert (origen / "210847" / "UPD1.pdf").exists()
        assert list((tmp_path / "destino").rglob("*.pdf"))

    def test_un_origen_local_se_lee_en_su_sitio(self, ajustes, tmp_path):
        motor = FolderRunner(JobRegistry(), ajustes, lambda job: None)
        run = FolderRun(id="r1", source=tmp_path / "origen", destination=tmp_path / "destino")
        path = tmp_path / "origen" / "a.pdf"
        assert motor._copia_local(run, path) == path

    @pytest.mark.skipif(__import__("os").name != "nt", reason="el límite de 260 es de Windows")
    def test_si_la_copia_no_cabe_en_windows_se_lee_de_la_red(self, ajustes, tmp_path, monkeypatch):
        motor = FolderRunner(JobRegistry(), ajustes, lambda job: None)
        run = FolderRun(id="r1", source=Path(r"Z:\caja"), destination=tmp_path / "destino")
        run.copia_del_sistema = True
        largo = Path("Z:\\caja\\" + "\\".join(["CARPETA LARGA DEL CLIENTE"] * 10) + "\\UPD.pdf")
        assert motor._copia_local(run, largo) == largo
        corto = Path(r"Z:\caja\210847\UPD.pdf")
        assert motor._copia_local(run, corto).parts[-4:] == ("Z", "caja", "210847", "UPD.pdf")


# -- A7: las esperas de la corrida compartida ----------------------------------------


class TestLaEsperaSinAvance:
    def test_vence_si_nada_cambia(self):
        espera = folders._EsperaSinAvance(0.1)
        assert not espera.vencida("igual")
        time.sleep(0.15)
        assert espera.vencida("igual")

    def test_un_cambio_o_un_avance_vuelven_a_empezar(self):
        espera = folders._EsperaSinAvance(0.1)
        espera.vencida("antes")
        time.sleep(0.15)
        assert not espera.vencida("después")
        time.sleep(0.15)
        assert not espera.vencida("después", avanza=True)
        assert not espera.vencida("después")

    def test_el_tope_por_omision_es_dos_veces_el_del_documento_mas_el_del_turno(self, ajustes):
        motor = FolderRunner(JobRegistry(), replace(ajustes, minutos_sin_avance=20), lambda job: None)
        assert motor._tope_de_la_compartida() == 2 * 20 * 60 + 30 * 60


class _OtroEquipo:
    """Una coordinación de mentira: otro equipo vivo con un PDF en curso que nunca termina."""

    def __init__(self, *, sin_avance=None, principal="PC1-aaaaaa"):
        self.id = "PC1-aaaaaa"
        self.sin_avance = sin_avance
        self._principal = principal
        self.estado = "procesando"

    def estado_de(self, relativa):
        from resolutions.adapters.coordinacion_en_disco import Ajeno

        return Ajeno(equipo="PC2", estado="en curso")

    def latidos(self):
        return {
            "PC2-bbbbbb": {
                "vivo": True,
                "hechos": 7,
                "en_curso": ["210847/UPD1.pdf"],
                "en_curso_n": 1,
                "estado": "procesando",
                "sin_avance": self.sin_avance,
            }
        }

    def mirar_ahora(self):
        pass

    def principal(self):
        return self._principal

    def tomar_rol(self, nombre):
        return True

    def los_demas_terminaron(self):
        return False


def _corrida_compartida(tmp_path, coordinacion):
    run = FolderRun(id="r1", source=tmp_path / "origen", destination=tmp_path / "destino")
    run.state = RunState.PROCESSING
    run.coordinacion = coordinacion
    return run


class TestLaCorridaCompartidaNoEsperaParaSiempre:
    def _motor(self, ajustes):
        motor = FolderRunner(JobRegistry(), ajustes, lambda job: None)
        motor.TOPE_DE_LA_COMPARTIDA = 0.2
        motor.ESPERA_DE_LOS_OTROS = 0.01
        return motor

    def test_lo_que_otro_equipo_no_termina_se_deja_con_su_lista(self, ajustes, tmp_path):
        motor = self._motor(ajustes)
        run = _corrida_compartida(tmp_path, _OtroEquipo())
        run.ajenos[str(tmp_path / "origen" / "210847" / "UPD1.pdf")] = "PC2"

        asyncio.run(asyncio.wait_for(motor._esperar_a_los_otros_equipos(run), 5))

        assert not run.ajenos
        relativa = str(Path("210847") / "UPD1.pdf")
        assert run.fallidos_en_otro == {relativa: "PC2: seguía en curso sin avanzar al cerrar"}
        assert any("Se dejó de esperar a otros equipos: 1 PDF" in aviso for aviso in run.avisos)

    def test_mientras_lo_suyo_avance_se_espera(self, ajustes, tmp_path):
        motor = self._motor(ajustes)
        run = _corrida_compartida(tmp_path, _OtroEquipo(sin_avance=3.0))
        run.ajenos[str(tmp_path / "origen" / "UPD1.pdf")] = "PC2"

        async def ir():
            esperando = asyncio.ensure_future(motor._esperar_a_los_otros_equipos(run))
            await asyncio.sleep(0.6)
            sigue = not esperando.done()
            run.state = RunState.DONE  # se detiene
            await asyncio.wait_for(esperando, 5)
            return sigue

        assert asyncio.run(ir())
        assert run.ajenos and not run.fallidos_en_otro

    def test_el_que_cierra_no_espera_para_siempre_a_los_demas(self, ajustes, tmp_path):
        motor = self._motor(ajustes)
        run = _corrida_compartida(tmp_path, _OtroEquipo())

        cierra = asyncio.run(asyncio.wait_for(motor._esperar_el_cierre(run), 5))

        assert cierra is True
        assert any(aviso.startswith("Se cierra la corrida sin esperar más") and "210847/UPD1.pdf" in aviso for aviso in run.avisos)

    def test_si_el_principal_no_avanza_ni_cierra_cierra_este(self, ajustes, tmp_path):
        motor = self._motor(ajustes)
        coordinacion = _OtroEquipo(principal="PC2-bbbbbb")
        run = _corrida_compartida(tmp_path, coordinacion)

        cierra = asyncio.run(asyncio.wait_for(motor._esperar_el_cierre(run), 5))

        assert cierra is True
        assert any("sin avanzar ni empezar a cerrar: cierra la corrida este equipo" in aviso for aviso in run.avisos)

    def test_el_latido_dice_si_lo_suyo_avanza(self, ajustes, tmp_path):
        coordinacion = Coordinacion(tmp_path, equipo="PC1", version="v1")
        coordinacion.medir_el_avance = lambda: 3.21
        assert coordinacion._sin_avance() == 3.2
        coordinacion.medir_el_avance = lambda: 1 / 0
        assert coordinacion._sin_avance() is None

        registro = JobRegistry()
        motor = FolderRunner(registro, ajustes, lambda job: None)
        run = FolderRun(id="r1", source=tmp_path / "origen", destination=tmp_path / "destino")
        assert motor._sin_avance_de_lo_suyo(run) is None
        job = registro.create(filename="a.pdf", source=tmp_path / "a.pdf", owns_source=False)
        registro.mark_running(job)
        job.progress.last_event_monotonic = time.monotonic() - 30
        run.en_curso[job.id] = "a.pdf"
        assert 29 <= motor._sin_avance_de_lo_suyo(run) < 60


# -- M1: reclamar un PDF en un destino colgado ---------------------------------------


class TestReclamarConTope:
    def test_no_retiene_la_fila_y_lo_tomado_tarde_se_suelta(self, ajustes, tmp_path, monkeypatch):
        motor = FolderRunner(JobRegistry(), ajustes, lambda job: None)
        motor.ESPERA_DE_LA_TOMA = 0.1
        suelta, soltados = threading.Event(), []
        coordinacion = SimpleNamespace(soltar=lambda reclamo: soltados.append(reclamo))
        run = _corrida_compartida(tmp_path, coordinacion)
        path = tmp_path / "origen" / "UPD1.pdf"
        reclamo = Reclamo(clave="k", relativa="UPD1.pdf", ficha="f")

        def tomar(run, path, relativa):
            suelta.wait(5)
            run.reclamos[str(path)] = reclamo
            return True, False

        monkeypatch.setattr(motor, "_tomar_el_pdf", tomar)

        async def ir():
            await asyncio.wait_for(motor._consumir_uno(run, path), 5)
            fallado = (run.failed, dict(run.fallidos))
            suelta.set()
            for _ in range(200):
                if soltados:
                    break
                await asyncio.sleep(0.01)
            return fallado

        fallados, fallidos = asyncio.run(ir())
        assert fallados == 1 and "no contestó en 0 s al reclamarlo" in fallidos[str(path)]
        assert soltados == [reclamo] and not run.reclamos


# -- M2: el turno de una carpeta dentro del mismo equipo -----------------------------


class TestElTurnoLocalTieneTope:
    def test_otro_hilo_con_el_turno_no_retiene_para_siempre(self, tmp_path):
        coordinacion = Coordinacion(tmp_path, equipo="PC1", version="v1")
        (coordinacion.area / "cerrojos").mkdir(parents=True)
        dentro, suelta = threading.Event(), threading.Event()

        def retener():
            with coordinacion.cerrojo("carpeta:210847"):
                dentro.set()
                suelta.wait(5)

        hilo = threading.Thread(target=retener)
        hilo.start()
        try:
            assert dentro.wait(5)
            inicio = time.monotonic()
            with (
                pytest.raises(CerrojoOcupado, match="otra entrega de este equipo"),
                coordinacion.cerrojo("carpeta:210847", espera_maxima=0.2),
            ):
                pass
            assert time.monotonic() - inicio < 2
            with pytest.raises(CerrojoOcupado, match="se canceló"), coordinacion.cerrojo(
                "carpeta:210847", cancelado=lambda: True
            ):
                pass
        finally:
            suelta.set()
            hilo.join()
        # Suelto, se toma como siempre.
        with coordinacion.cerrojo("carpeta:210847", espera_maxima=0.2):
            pass


# -- M3: el listado del origen colgado -----------------------------------------------


class TestElListadoDelOrigenColgado:
    def test_da_el_fallo_de_la_red_en_vez_de_esperar_para_siempre(self, monkeypatch):
        monkeypatch.setattr(folders._ListadoEnSuHilo, "SEGUNDOS_SIN_NADA", 0.3)
        suelta = threading.Event()

        def colgado():
            suelta.wait(5)
            yield from ()

        listado = folders._ListadoEnSuHilo(colgado(), tope=10)
        try:
            elemento = listado.siguiente()
        finally:
            listado.cerrar()
            suelta.set()
        assert isinstance(elemento, folders._FalloDelListado)
        # Un ``OSError``: ``_descubrir_por_lotes`` lo espera y recorre otra vez.
        assert isinstance(elemento.error, TimeoutError) and isinstance(elemento.error, OSError)

    def test_lo_que_llega_a_tiempo_sale_igual(self, monkeypatch):
        monkeypatch.setattr(folders._ListadoEnSuHilo, "SEGUNDOS_SIN_NADA", 0.3)
        listado = folders._ListadoEnSuHilo(iter([("a", None), ("b", None)]), tope=10)
        try:
            assert [listado.siguiente(), listado.siguiente(), listado.siguiente()] == [
                ("a", None),
                ("b", None),
                folders._FIN_DEL_LISTADO,
            ]
        finally:
            listado.cerrar()


# -- M10: el turno de la carpeta que no llega al entregar ----------------------------


class TestElTurnoQueNoLlegaAlEntregar:
    def test_se_reintenta_la_entrega_sin_volver_a_leer(self, ajustes, tmp_path, monkeypatch):
        (tmp_path / "origen" / "UPD1.pdf").write_bytes(b"%PDF-1.4 fake")
        registro = JobRegistry()
        motor, hechos = _motor(ajustes, registro)
        entregar = motor._deliver
        intentos = []

        def ocupado_una_vez(*args, **kwargs):
            intentos.append(1)
            if len(intentos) == 1:
                raise CerrojoOcupado("«carpeta:UPD1» sigue ocupado por PC2 tras 30 min")
            return entregar(*args, **kwargs)

        monkeypatch.setattr(motor, "_deliver", ocupado_una_vez)
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        assert run.state is RunState.DONE, run.error
        assert hechos == ["UPD1.pdf"] and len(intentos) == 2
        assert run.failed == 0 and run.processed == 1
        assert any("Se reintenta la entrega" in aviso for aviso in run.avisos)
        assert list((tmp_path / "destino").rglob("*.pdf"))


# -- M12: lo que se lee del origen antes del primer PDF ------------------------------


class TestLosDatosDelOrigenConTope:
    def test_sin_el_dato_se_sigue_y_se_avisa(self, ajustes, tmp_path):
        motor = FolderRunner(JobRegistry(), ajustes, lambda job: None)
        motor.ESPERA_DE_LOS_DATOS_DEL_ORIGEN = 0.1
        run = FolderRun(id="r1", source=tmp_path / "origen", destination=tmp_path / "destino")
        suelta = threading.Event()

        async def ir():
            try:
                return await motor._dato_del_origen(run, lambda: suelta.wait(5), "la oficina productora", None)
            finally:
                suelta.set()

        dato = asyncio.run(ir())
        assert dato is None
        assert any("No se pudo leer la oficina productora del origen" in aviso for aviso in run.avisos)

    @pytest.mark.parametrize("modo", ["auto", "si"])
    def test_la_union_que_no_llega_sigue_sola_o_no_corre(self, ajustes, tmp_path, monkeypatch, modo):
        monkeypatch.setenv("BOTPDF_COORDINACION", modo)
        motor = FolderRunner(JobRegistry(), ajustes, lambda job: None)
        motor.ESPERA_DE_LA_UNION = 0.1
        run = FolderRun(id="r1", source=tmp_path / "origen", destination=tmp_path / "destino")
        suelta, abandonos = threading.Event(), []

        def unirse(run, abandonada=None):
            suelta.wait(5)
            abandonos.append(abandonada.is_set())

        monkeypatch.setattr(motor, "_unirse_a_la_corrida", unirse)

        async def ir():
            try:
                await motor._unirse_con_tope(run)
                return None
            except folders.FolderError as error:
                return str(error)
            finally:
                suelta.set()
                for _ in range(200):
                    if abandonos:
                        break
                    await asyncio.sleep(0.01)

        error = asyncio.run(ir())
        # La unión que llega tarde se entera de que ya no la esperan (y se retira).
        assert abandonos == [True]
        if modo == "si":
            assert error and "no contestó" in error
        else:
            assert error is None and any("Esta corrida sigue sola" in aviso for aviso in run.avisos)
