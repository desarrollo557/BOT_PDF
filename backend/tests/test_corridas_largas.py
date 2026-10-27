"""Corridas largas y desatendidas: reintentar, no repetir lo entregado y no quemar la carpeta.

Lo pidió el operador el 2026-10-19: preparar el bot para procesar seguidas más
de un millón de páginas, con manejo de excepciones, reintento de lo fallido y
sin volver a procesar lo que ya está entregado. Esto fija:

* qué fallo se reintenta y cuál no (``reintentos.py``), y que el reintento
  ocurre de verdad, con el pool rehecho si se rompió;
* que un documento que no avanza se da por atascado en vez de colgar la
  carpeta;
* la constancia de entrega: lo entregado entero se salta sin abrir nada, lo
  cortado o con el origen cambiado se rehace sin dejar «(2)», y los
  inventarios generales siguen contando lo saltado;
* que una copia que no termina no cuenta como entregada;
* que diez fallos seguidos detienen la carpeta;
* que los documentos viejos salen del registro sin que el panel encoja.

Nada llama a un proveedor ni abre un PDF de verdad.
"""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import pickle
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from resolutions.api import constancia as constancias
from resolutions.api import ejecucion, folders
from resolutions.api.constancia import Constancia, EstadoDeEntrega, Vigencia
from resolutions.api.ejecucion import TrabajoSinAvance, _run
from resolutions.api.folders import (
    JOB_IDS_EN_PANTALLA,
    REEMPLAZADOS_DIR,
    FolderRun,
    FolderRunner,
    RunState,
)
from resolutions.api.jobs import Job, JobRegistry, JobState
from resolutions.api.reintentos import (
    es_transitorio,
    espera_antes_del_intento,
    merece_otra_vuelta,
    pide_otro_pool,
)
from resolutions.api.retomar import Retomar
from resolutions.api.settings import Settings


@pytest.fixture
def ajustes(tmp_path):
    settings = replace(
        Settings(),
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "outputs",
        ledger_path=tmp_path / "inventory.jsonl",
        # Las pausas y vueltas de reintento, en centésimas y no en minutos.
        pausa_tras_fallos=0.01,
    )
    settings.ensure_directories()
    (tmp_path / "origen").mkdir()
    (tmp_path / "destino").mkdir()
    return settings


def _pon(carpeta: Path, *nombres: str) -> None:
    for nombre in nombres:
        (carpeta / nombre).write_bytes(b"%PDF-1.4 fake")


def _motor(ajustes, registry, *, produce=("01_X.pdf",), fallan=(), hechos=None):
    hechos = hechos if hechos is not None else []

    async def run_job(job):
        hechos.append(job.filename)
        if job.filename in fallan:
            registry.mark_failed(job, "boom")
            return
        salida = ajustes.output_dir / job.id
        salida.mkdir(parents=True, exist_ok=True)
        for nombre in produce:
            (salida / nombre).write_bytes(b"%PDF-1.4 out " + job.filename.encode())
        registry.mark_done(
            job,
            {
                "groups": [{"code": "01"}],
                "review_queue": [],
                "inventory": {"items": [{"file_name": produce[0], "first_page": 1}]},
            },
        )

    return FolderRunner(registry, ajustes, run_job, watch_interval=0.01), hechos


def _vaciar(motor, origen, destino, **opciones):
    async def ir():
        run = motor.start(str(origen), str(destino), **opciones)
        for _ in range(800):
            if not run.active:
                break
            await asyncio.sleep(0.01)
        # Lo que la corrida deja de fondo -- los generales -- ya terminó.
        if run.escritor is not None and not run.escritor.done():
            await run.escritor
        return run

    return asyncio.run(ir())


# -- qué se reintenta -------------------------------------------------------------


class TestQueSeReintenta:
    def test_la_red_que_se_cae_se_reintenta(self):
        caida = OSError(errno.EINVAL, "El nombre de red ya no está disponible")
        caida.winerror = 64
        assert es_transitorio(caida)
        assert es_transitorio(ConnectionResetError())
        assert es_transitorio(TimeoutError())
        assert es_transitorio(OSError(errno.ETIMEDOUT, "timed out"))

    def test_el_pool_roto_se_reintenta_con_otro_pool(self):
        from concurrent.futures.process import BrokenProcessPool

        error = BrokenProcessPool("un proceso murió")
        assert es_transitorio(error)
        assert pide_otro_pool(error)

    def test_lo_que_dice_algo_del_papel_no(self):
        class PdfQueNoSeAbre(ValueError):
            pass

        assert not es_transitorio(PdfQueNoSeAbre("está dañado"))
        assert not es_transitorio(FileNotFoundError(2, "no está"))
        assert not es_transitorio(PermissionError(13, "abierto en Excel"))
        assert not es_transitorio(ValueError("otra cosa"))
        assert not es_transitorio(TrabajoSinAvance("atascado"))

    def test_la_causa_cuenta(self):
        try:
            try:
                raise ConnectionError("se cortó")
            except ConnectionError as causa:
                raise RuntimeError("al leer la página") from causa
        except RuntimeError as error:
            assert es_transitorio(error)

    def test_la_espera_crece_y_se_puede_apagar(self):
        assert espera_antes_del_intento(2, 0) == 0
        segunda = espera_antes_del_intento(2, 10)
        tercera = espera_antes_del_intento(3, 10)
        assert 8 <= segunda <= 12
        assert 24 <= tercera <= 36


class TestArchivoEnUso:
    def test_espera_y_vuelve_a_abrir_el_pdf_bloqueado(self, monkeypatch, tmp_path):
        ruta = tmp_path / "abierto.pdf"
        ruta.write_bytes(b"%PDF")
        abrir = Path.open
        intentos = 0

        def abrir_con_bloqueo(path, *args, **kwargs):
            nonlocal intentos
            if path == ruta and intentos == 0:
                intentos += 1
                error = PermissionError(13, "The process cannot access the file because it is being used by another process", str(path))
                error.winerror = 32
                raise error
            intentos += 1
            return abrir(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", abrir_con_bloqueo)
        monkeypatch.setattr(folders.time, "sleep", lambda _: None)

        folders._esperar_a_que_se_libere(ruta)

        assert intentos == 2

    def test_si_sigue_bloqueado_el_fallo_conserva_la_causa_de_windows(self, monkeypatch, tmp_path):
        ruta = tmp_path / "abierto.pdf"

        def abrir_bloqueado(path, *args, **kwargs):
            error = PermissionError(13, "The process cannot access the file because it is being used by another process", str(path))
            error.winerror = 32
            raise error

        monkeypatch.setattr(Path, "open", abrir_bloqueado)
        monkeypatch.setattr(folders.time, "sleep", lambda _: None)

        with pytest.raises(PermissionError) as capturada:
            folders._esperar_a_que_se_libere(ruta)

        from resolutions.api.errores import archivo_en_uso, explicar_fallo

        assert archivo_en_uso(capturada.value)
        assert merece_otra_vuelta(capturada.value)
        assert "se vuelve a intentar al final" in explicar_fallo(capturada.value)


    def test_reemplazar_un_excel_abierto_espera_y_reintenta(self, monkeypatch, tmp_path):
        """Windows no dice «en uso» al reemplazar un archivo abierto: dice «acceso denegado» (5)."""
        monkeypatch.setattr(folders.time, "sleep", lambda _: None)
        intentos = {"n": 0}

        def guardar():
            intentos["n"] += 1
            if intentos["n"] == 1:
                error = PermissionError(13, "Access is denied", "00.FUID GENERAL.xlsx")
                error.winerror = 5
                raise error

        folders._reintentar_si_esta_en_uso(guardar)

        assert intentos["n"] == 2

    def test_mover_un_pdf_abierto_en_un_visor_espera(self, monkeypatch, tmp_path):
        monkeypatch.setattr(folders.time, "sleep", lambda _: None)
        desde, hasta = tmp_path / "a.pdf", tmp_path / "b.pdf"
        desde.write_bytes(b"%PDF")
        reemplazar = folders.os.replace
        intentos = {"n": 0}

        def denegado_una_vez(a, b):
            intentos["n"] += 1
            if intentos["n"] == 1:
                raise PermissionError(13, "Permission denied", str(b))
            return reemplazar(a, b)

        monkeypatch.setattr(folders.os, "replace", denegado_una_vez)
        folders._mover(desde, hasta)

        assert hasta.exists() and not desde.exists()

    def test_leer_un_pdf_sin_permiso_no_se_espera(self, monkeypatch, tmp_path):
        """Esperar sólo vale si alguien lo tiene abierto; sin permiso no se arregla esperando."""
        esperas: list[float] = []
        monkeypatch.setattr(folders.time, "sleep", esperas.append)

        def sin_permiso(path, *args, **kwargs):
            raise PermissionError(13, "Permission denied", str(path))

        monkeypatch.setattr(Path, "open", sin_permiso)
        folders._esperar_a_que_se_libere(tmp_path / "x.pdf")

        assert esperas == []


class _Registro:
    """Lo mínimo del registro que usa `_correr`."""

    def __init__(self):
        self.publicados = 0

    def mark_running(self, job):
        job.state = JobState.RUNNING

    def mark_done(self, job, report):
        job.state = JobState.DONE
        job.report = report

    def mark_failed(self, job, error):
        job.state = JobState.FAILED
        job.error = error

    def mark_cancelled(self, job):
        job.state = JobState.CANCELLED

    def publish(self, job):
        self.publicados += 1

    def get_batch(self, batch_id):
        return None


def _contexto(procesar, **ajustes):
    return SimpleNamespace(
        controls={},
        registry=_Registro(),
        pool=ThreadPoolExecutor(1),
        procesar=procesar,
        settings=SimpleNamespace(
            as_worker_payload=lambda: {},
            reintentos=ajustes.get("reintentos", 2),
            espera_de_reintento=0,
            minutos_sin_avance=ajustes.get("minutos_sin_avance", 0),
        ),
        progress_queue=None,
        ledger=SimpleNamespace(record=lambda *a, **k: None),
    )


def _trabajo(tmp_path):
    return Job(id="j1", filename="libro.pdf", source=tmp_path / "libro.pdf", owns_source=False)


class TestElReintento:
    def test_un_fallo_de_red_se_reintenta_y_sale_bien(self, tmp_path):
        intentos = []

        def procesar(payload):
            intentos.append(1)
            if len(intentos) == 1:
                raise ConnectionResetError("la red se cortó")
            return {"groups": []}

        ctx = _contexto(procesar)
        job = _trabajo(tmp_path)
        asyncio.run(_run(ctx, job))
        ctx.pool.shutdown()

        assert job.state is JobState.DONE
        assert job.intentos == 2
        assert len(intentos) == 2

    def test_un_pdf_danado_no_se_reintenta(self, tmp_path):
        intentos = []

        def procesar(payload):
            intentos.append(1)
            raise ValueError("está dañado")

        ctx = _contexto(procesar)
        job = _trabajo(tmp_path)
        asyncio.run(_run(ctx, job))
        ctx.pool.shutdown()

        assert job.state is JobState.FAILED
        assert len(intentos) == 1

    def test_se_rinde_tras_los_intentos_configurados(self, tmp_path):
        intentos = []

        def procesar(payload):
            intentos.append(1)
            raise TimeoutError("no contesta")

        ctx = _contexto(procesar, reintentos=2)
        job = _trabajo(tmp_path)
        asyncio.run(_run(ctx, job))
        ctx.pool.shutdown()

        assert job.state is JobState.FAILED
        assert len(intentos) == 3
        assert "tardó demasiado" in job.error

    def test_el_pool_roto_se_rehace_antes_de_reintentar(self, tmp_path):
        from concurrent.futures.process import BrokenProcessPool

        intentos = []
        rehechos = []

        def procesar(payload):
            intentos.append(1)
            if len(intentos) == 1:
                raise BrokenProcessPool("un proceso murió")
            return {"groups": []}

        ctx = _contexto(procesar)
        ctx.rehacer_pool = lambda roto: rehechos.append(roto)
        job = _trabajo(tmp_path)
        asyncio.run(_run(ctx, job))
        ctx.pool.shutdown()

        assert job.state is JobState.DONE
        assert rehechos == [ctx.pool]

    def test_mandar_al_pool_roto_tampoco_deja_el_trabajo_en_curso(self, tmp_path):
        """Antes, mandar el trabajo fallaba fuera del `try` y quedaba «en curso» para siempre."""

        class PoolRoto:
            def submit(self, *args, **kwargs):
                raise RuntimeError("cannot schedule new futures after shutdown")

        ctx = _contexto(lambda payload: {})
        ctx.pool = PoolRoto()
        job = _trabajo(tmp_path)
        asyncio.run(_run(ctx, job))

        assert job.state is JobState.FAILED


class TestElDocumentoAtascado:
    def test_sin_avanzar_se_da_por_atascado_y_la_espera_se_abandona(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ejecucion, "_VIGILANCIA", 0.02)
        suelta = threading.Event()

        def procesar(payload):
            suelta.wait(5)
            return {"groups": []}

        ctx = _contexto(procesar, minutos_sin_avance=0.001)
        job = _trabajo(tmp_path)
        asyncio.run(_run(ctx, job))
        suelta.set()
        ctx.pool.shutdown()

        assert job.state is JobState.FAILED
        assert "sin avanzar" in job.error
        # Y se le ordenó parar al worker, que lo soltará al atenderla.
        assert ctx.controls.get("j1") in (None, "cancelled")


class TestElErrorDelWorkerViajaLegible:
    def test_una_excepcion_que_no_se_serializa_llega_con_su_nombre(self, monkeypatch):
        from resolutions.api import worker

        class Nativa(Exception):
            def __reduce__(self):
                raise TypeError("cannot pickle 'SwigPyObject'")

        def revienta(payload):
            raise Nativa("cannot find startxref")

        monkeypatch.setattr(worker, "_process_document_job", revienta)
        with pytest.raises(worker.ErrorDelWorker) as capturado:
            worker.process_document_job({})
        assert "Nativa" in str(capturado.value)
        assert "startxref" in str(capturado.value)
        pickle.loads(pickle.dumps(capturado.value))

    def test_las_que_viajan_salen_tal_cual(self, monkeypatch):
        from resolutions.api import worker

        def revienta(payload):
            raise ValueError("está dañado")

        monkeypatch.setattr(worker, "_process_document_job", revienta)
        with pytest.raises(ValueError, match="dañado"):
            worker.process_document_job({})


class TestElTurnoDeLaIA:
    def test_un_turno_que_nadie_devuelve_no_para_la_lectura(self):
        from resolutions.adapters.turnos import turno

        semaforo = threading.BoundedSemaphore(1)
        semaforo.acquire()  # el proceso que murió con él
        with turno(semaforo, espera=0.05) as tomado:
            assert tomado is False
        # Y no se devolvió uno que no se tomó.
        assert semaforo.acquire(blocking=False) is False

    def test_el_turno_tomado_se_devuelve(self):
        from resolutions.adapters.turnos import turno

        semaforo = threading.BoundedSemaphore(1)
        with turno(semaforo) as tomado:
            assert tomado is True
        assert semaforo.acquire(blocking=False) is True


# -- la constancia de entrega -------------------------------------------------------


class TestLaConstancia:
    def _entregada(self, tmp_path):
        origen = tmp_path / "libro.pdf"
        origen.write_bytes(b"%PDF original")
        carpeta = tmp_path / "LIBRO"
        carpeta.mkdir()
        (carpeta / "1_A.pdf").write_bytes(b"uno")
        tamano, fecha = constancias.huella_del_origen(origen)
        constancia = Constancia(
            origen="libro.pdf",
            tamano=tamano,
            modificado_ns=fecha,
            estado=EstadoDeEntrega.COMPLETA,
            archivos=constancias.archivos_de(carpeta, [carpeta / "1_A.pdf"]),
        )
        constancias.escribir(carpeta / constancias.NOMBRE, constancia)
        return origen, carpeta

    def test_completa_y_con_el_mismo_origen_esta_vigente(self, tmp_path):
        origen, carpeta = self._entregada(tmp_path)
        leida = constancias.leer(carpeta / constancias.NOMBRE)
        assert constancias.vigencia(leida, origen, carpeta) is Vigencia.VIGENTE

    def test_un_archivo_que_falta_la_deja_incompleta(self, tmp_path):
        origen, carpeta = self._entregada(tmp_path)
        (carpeta / "1_A.pdf").unlink()
        leida = constancias.leer(carpeta / constancias.NOMBRE)
        assert constancias.vigencia(leida, origen, carpeta) is Vigencia.INCOMPLETA

    def test_un_archivo_cortado_tambien(self, tmp_path):
        origen, carpeta = self._entregada(tmp_path)
        (carpeta / "1_A.pdf").write_bytes(b"u")
        leida = constancias.leer(carpeta / constancias.NOMBRE)
        assert constancias.vigencia(leida, origen, carpeta) is Vigencia.INCOMPLETA

    def test_un_origen_reescaneado_con_el_mismo_nombre_se_nota(self, tmp_path):
        origen, carpeta = self._entregada(tmp_path)
        origen.write_bytes(b"%PDF otro escaneo, mas largo")
        leida = constancias.leer(carpeta / constancias.NOMBRE)
        assert constancias.vigencia(leida, origen, carpeta) is Vigencia.ORIGEN_CAMBIADO

    def test_un_cambio_en_el_centro_del_pdf_no_se_confunde_con_una_copia(self, tmp_path):
        origen, carpeta = self._entregada(tmp_path)
        origen.write_bytes(b"A" * 150_000)
        tamano, modificado = constancias.huella_del_origen(origen)
        constancia = Constancia(
            origen="libro.pdf",
            tamano=tamano,
            modificado_ns=modificado,
            estado=EstadoDeEntrega.COMPLETA,
            archivos=constancias.archivos_de(carpeta, [carpeta / "1_A.pdf"]),
            firma=constancias.firma_del_origen(origen),
        )
        origen.write_bytes(b"A" * 75_000 + b"B" + b"A" * 74_999)

        verificacion = constancias.verificar(
            constancia, origen, carpeta, huella=(tamano, modificado + 1)
        )

        assert origen.stat().st_size == tamano
        assert verificacion.vigencia is Vigencia.ORIGEN_CAMBIADO

    def test_una_entrega_completa_sin_archivos_sigue_vigente(self, tmp_path):
        # El inventario de actas sin dividir no copia ningún PDF: rehacerlo en
        # cada corrida volvería a pagar su lectura.
        origen, carpeta = self._entregada(tmp_path)
        constancia = Constancia(
            origen="libro.pdf",
            tamano=origen.stat().st_size,
            modificado_ns=origen.stat().st_mtime_ns,
            estado=EstadoDeEntrega.COMPLETA,
        )

        verificacion = constancias.verificar(constancia, origen, carpeta)

        assert verificacion.vigencia is Vigencia.VIGENTE

    def test_la_fecha_de_la_entrega_se_dice_en_hora_local(self, tmp_path):
        from datetime import UTC, datetime

        origen, carpeta = self._entregada(tmp_path)
        leida = constancias.leer(carpeta / constancias.NOMBRE)
        leida.fecha = "2026-10-22T18:46:00+00:00"

        verificacion = constancias.verificar(leida, origen, carpeta)

        local = datetime(2026, 10, 22, 18, 46, tzinfo=UTC).astimezone().strftime("%Y-%m-%d %H:%M")
        assert verificacion.vigencia is Vigencia.VIGENTE
        assert f"entregado completo el {local}" in verificacion.motivo

    def test_una_ruta_de_constancia_no_puede_salir_del_destino(self, tmp_path):
        origen, carpeta = self._entregada(tmp_path)
        constancia = Constancia(
            origen="libro.pdf",
            tamano=origen.stat().st_size,
            modificado_ns=origen.stat().st_mtime_ns,
            estado=EstadoDeEntrega.COMPLETA,
            archivos=[{"ruta": "..\\otro.pdf", "bytes": 1}],
        )

        verificacion = constancias.verificar(constancia, origen, carpeta)

        assert verificacion.vigencia is Vigencia.INCOMPLETA
        assert "ruta de archivo inválida" in verificacion.motivo

    def test_la_que_se_quedo_entregando_es_una_entrega_cortada(self, tmp_path):
        origen, carpeta = self._entregada(tmp_path)
        leida = constancias.leer(carpeta / constancias.NOMBRE)
        leida.estado = EstadoDeEntrega.ENTREGANDO
        assert constancias.vigencia(leida, origen, carpeta) is Vigencia.INCOMPLETA

    def test_una_constancia_rota_es_como_no_tenerla(self, tmp_path):
        ruta = tmp_path / constancias.NOMBRE
        ruta.write_text("{roto", encoding="utf-8")
        assert constancias.leer(ruta) is None


class TestNoSeRepiteLoEntregado:
    def test_la_segunda_corrida_salta_lo_entregado_sin_procesarlo(self, ajustes, tmp_path):
        _pon(tmp_path / "origen", "a.pdf", "b.pdf")
        motor, hechos = _motor(ajustes, JobRegistry())
        primera = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")
        assert primera.processed == 2
        constancia = constancias.leer(tmp_path / "destino" / "a" / constancias.NOMBRE)
        assert constancia.estado == EstadoDeEntrega.COMPLETA
        assert [a["ruta"] for a in constancia.archivos if a["ruta"].endswith(".pdf")] == ["01_X.pdf"]

        _pon(tmp_path / "origen", "c.pdf")
        motor, hechos = _motor(ajustes, JobRegistry())
        segunda = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        assert hechos == ["c.pdf"]
        assert segunda.ya_entregados == 2
        assert segunda.sin_constancia == 0
        from openpyxl import load_workbook

        libro = load_workbook(segunda.analisis, read_only=True, data_only=True)
        filas = list(libro["Por PDF"].iter_rows(values_only=True))
        assert {fila[1] for fila in filas[1:]} == {"a.pdf", "b.pdf", "c.pdf"}
        assert {fila[4] for fila in filas[1:]} == {"Ya estaba entregado", "Procesado"}
        assert "Aviso de la corrida" in list(libro["Incidencias"].values)[0]
        libro.close()

    def test_una_constancia_danada_no_se_toma_por_entrega_anterior(self, ajustes, tmp_path):
        _pon(tmp_path / "origen", "a.pdf")
        salida = tmp_path / "destino" / "a"
        salida.mkdir()
        (salida / "01_X.pdf").write_bytes(b"%PDF-1.4 entregado")
        (salida / constancias.NOMBRE).write_text("{roto", encoding="utf-8")
        motor, hechos = _motor(ajustes, JobRegistry())

        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        assert hechos == ["a.pdf"]
        assert run.processed == 1
        assert "constancia de entrega está dañada" in run.verificaciones["a.pdf"][1]

    def test_los_generales_siguen_contando_lo_saltado(self, ajustes, tmp_path):
        from openpyxl import load_workbook

        from resolutions.adapters.excel_inventory import NOMBRE_DEL_INVENTARIO_DE_PROCESOS

        _pon(tmp_path / "origen", "a.pdf", "b.pdf")
        motor, _ = _motor(ajustes, JobRegistry())
        _vaciar(motor, tmp_path / "origen", tmp_path / "destino")
        _pon(tmp_path / "origen", "c.pdf")
        motor, _ = _motor(ajustes, JobRegistry())
        _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        libro = load_workbook(tmp_path / "destino" / NOMBRE_DEL_INVENTARIO_DE_PROCESOS)
        celdas = [str(c.value) for hoja in libro.worksheets for fila in hoja.iter_rows() for c in fila if c.value]
        for pdf in ("a.pdf", "b.pdf", "c.pdf"):
            assert pdf in celdas
        assert "Ya entregado" in celdas

    def test_una_entrega_cortada_se_rehace_sin_dejar_dobles(self, ajustes, tmp_path):
        _pon(tmp_path / "origen", "a.pdf")
        motor, _ = _motor(ajustes, JobRegistry())
        _vaciar(motor, tmp_path / "origen", tmp_path / "destino")
        carpeta = tmp_path / "destino" / "a"
        # Como si la luz se hubiera ido a media copia.
        constancia = constancias.leer(carpeta / constancias.NOMBRE)
        constancia.estado = EstadoDeEntrega.ENTREGANDO
        constancias.escribir(carpeta / constancias.NOMBRE, constancia)

        motor, hechos = _motor(ajustes, JobRegistry())
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        assert hechos == ["a.pdf"]
        assert run.rehechos == 1
        assert sorted(p.name for p in carpeta.glob("*.pdf")) == ["01_X.pdf"]
        assert any((carpeta / REEMPLAZADOS_DIR).rglob("01_X.pdf"))
        assert constancias.leer(carpeta / constancias.NOMBRE).estado == EstadoDeEntrega.COMPLETA

    def test_rehacer_sin_constancia_no_toca_lo_que_no_es_del_bot(self, ajustes, tmp_path):
        # «Que actúe estrictamente según lo seleccionado» (2026-10-20): de una
        # entrega de antes de las constancias sólo se aparta lo que el bot
        # produce; una nota que el operador dejó ahí se queda donde está.
        _pon(tmp_path / "origen", "a.pdf")
        carpeta = tmp_path / "destino" / "a"
        carpeta.mkdir(parents=True)
        (carpeta / "01_VIEJO.pdf").write_bytes(b"%PDF-1.4 de antes")
        (carpeta / "MIS NOTAS.docx").write_bytes(b"del operador")

        motor, hechos = _motor(ajustes, JobRegistry())
        _vaciar(motor, tmp_path / "origen", tmp_path / "destino", retomar="todo")

        assert hechos == ["a.pdf"]
        assert (carpeta / "MIS NOTAS.docx").read_bytes() == b"del operador"
        assert not (carpeta / "01_VIEJO.pdf").exists()
        assert any((carpeta / REEMPLAZADOS_DIR).rglob("01_VIEJO.pdf"))
        assert not any((carpeta / REEMPLAZADOS_DIR).rglob("MIS NOTAS.docx"))

    def test_un_origen_que_cambio_se_vuelve_a_procesar(self, ajustes, tmp_path):
        _pon(tmp_path / "origen", "a.pdf")
        motor, _ = _motor(ajustes, JobRegistry())
        _vaciar(motor, tmp_path / "origen", tmp_path / "destino")
        (tmp_path / "origen" / "a.pdf").write_bytes(b"%PDF-1.4 escaneado de nuevo, distinto")

        motor, hechos = _motor(ajustes, JobRegistry())
        _vaciar(motor, tmp_path / "origen", tmp_path / "destino")
        assert hechos == ["a.pdf"]

    def test_una_entrega_de_antes_sin_constancia_se_da_por_buena(self, ajustes, tmp_path):
        _pon(tmp_path / "origen", "a.pdf")
        (tmp_path / "destino" / "a").mkdir()
        (tmp_path / "destino" / "a" / "01_X.pdf").write_bytes(b"%PDF de antes")

        motor, hechos = _motor(ajustes, JobRegistry())
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        assert hechos == []
        assert run.sin_constancia == 1

    def test_procesar_todo_otra_vez_aparta_lo_anterior(self, ajustes, tmp_path):
        _pon(tmp_path / "origen", "a.pdf")
        motor, _ = _motor(ajustes, JobRegistry())
        _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        motor, hechos = _motor(ajustes, JobRegistry())
        _vaciar(motor, tmp_path / "origen", tmp_path / "destino", retomar=str(Retomar.TODO))

        carpeta = tmp_path / "destino" / "a"
        assert hechos == ["a.pdf"]
        assert sorted(p.name for p in carpeta.glob("*.pdf")) == ["01_X.pdf"]

    def test_todo_vale_para_cualquier_tipo_y_faltantes_solo_para_diplomas(self, ajustes, tmp_path):
        from resolutions.api.folders import FolderError

        motor, _ = _motor(ajustes, JobRegistry())

        async def lanzar(modo):
            return motor.start(str(tmp_path / "origen"), str(tmp_path / "destino"), retomar=modo)

        with pytest.raises(FolderError, match="diplomas"):
            asyncio.run(lanzar("faltantes"))
        assert asyncio.run(lanzar("todo")).retomar == "todo"


class TestLaEntregaIncompleta:
    def test_una_copia_que_falla_no_cuenta_como_entregada(self, ajustes, tmp_path, monkeypatch):
        from resolutions.api import folders

        _pon(tmp_path / "origen", "a.pdf")
        original = folders._copiar

        def copiar(desde, hasta):
            if hasta.suffix == ".pdf":
                raise OSError(errno.ENOSPC, "No space left on device", str(hasta))
            return original(desde, hasta)

        monkeypatch.setattr(folders, "_copiar", copiar)
        registry = JobRegistry()
        motor, _ = _motor(ajustes, registry)
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino", disposition=folders.SourceDisposition.DELETE)

        assert run.failed == 1
        assert run.processed == 0
        assert run.entregas_incompletas == 1
        # El original no se tocó: no se entregó.
        assert (tmp_path / "origen" / "a.pdf").exists()
        job = registry.get(run.job_ids[0])
        assert "incompleta" in job.error
        # Y la constancia dice «entregando»: la próxima corrida lo rehará.
        constancia = constancias.leer(tmp_path / "destino" / "a" / constancias.NOMBRE)
        assert constancia.estado == EstadoDeEntrega.ENTREGANDO

    def test_la_copia_no_deja_archivos_a_medias(self, tmp_path, monkeypatch):
        from resolutions.api import folders

        desde = tmp_path / "x.pdf"
        desde.write_bytes(b"0123456789")
        hasta = tmp_path / "dest" / "x.pdf"
        hasta.parent.mkdir()

        def copia_cortada(origen, destino, **_):
            Path(destino).write_bytes(b"01234")

        monkeypatch.setattr(folders.shutil, "copy2", copia_cortada)
        with pytest.raises(OSError):
            folders._copiar(desde, hasta)
        assert not hasta.exists()
        assert not list(hasta.parent.iterdir())


class TestElOriginalSoloSeTocaSiEsElQueSeLeyo:
    """«Borrarlo» o «Moverlo» se hacen sobre el PDF que se procesó, no sobre otro.

    Un PDF que alguien seguía copiando a la carpeta, o que se sobrescribió
    mientras se leía, se entregaba con lo que había al leerlo y después se
    borraba el original -- ya completo -- (2026-10-27).
    """

    def test_si_el_original_cambio_mientras_se_procesaba_no_se_borra(self, ajustes, tmp_path):
        origen = tmp_path / "origen"
        _pon(origen, "a.pdf")
        registry = JobRegistry()
        motor, _ = _motor(ajustes, registry)
        procesar = motor._run_job

        async def run_job(job):
            # La copia que seguía llegando: el PDF crece a mitad del proceso.
            with (origen / "a.pdf").open("ab") as archivo:
                archivo.write(b" y el resto de las paginas")
            await procesar(job)

        motor._run_job = run_job
        run = _vaciar(motor, origen, tmp_path / "destino", disposition=folders.SourceDisposition.DELETE)

        assert (origen / "a.pdf").exists()
        assert any("cambió mientras se procesaba" in aviso for aviso in run.avisos)

    def test_si_el_original_sigue_igual_se_borra_como_siempre(self, ajustes, tmp_path):
        origen = tmp_path / "origen"
        _pon(origen, "a.pdf")
        motor, _ = _motor(ajustes, JobRegistry())
        run = _vaciar(motor, origen, tmp_path / "destino", disposition=folders.SourceDisposition.DELETE)

        assert run.processed == 1
        assert not (origen / "a.pdf").exists()

    def test_un_original_abierto_que_no_se_puede_mover_se_avisa(self, ajustes, tmp_path, monkeypatch):
        origen = tmp_path / "origen"
        _pon(origen, "a.pdf")

        def tomado(desde, hasta):
            raise PermissionError(errno.EACCES, "el archivo está abierto en otro programa", str(desde))

        monkeypatch.setattr(folders, "_mover", tomado)
        motor, _ = _motor(ajustes, JobRegistry())
        run = _vaciar(motor, origen, tmp_path / "destino", disposition=folders.SourceDisposition.MOVE)

        # Lo entregado sigue entregado; sólo el original se quedó donde estaba.
        assert run.processed == 1
        assert (origen / "a.pdf").exists()
        assert any("a.pdf" in aviso and "no se pudo mover" in aviso for aviso in run.avisos)

    def test_un_libro_que_no_se_pudo_dividir_conserva_su_original(self, ajustes, tmp_path):
        """El Excel de actas sale aunque dividir falle; el original es lo único que tiene las páginas."""
        origen = tmp_path / "origen"
        _pon(origen, "libro.pdf")
        registry = JobRegistry()

        async def run_job(job):
            salida = ajustes.output_dir / job.id
            salida.mkdir(parents=True, exist_ok=True)
            registry.mark_done(
                job,
                {
                    "groups": [],
                    "review_queue": [],
                    "inventory": {"items": []},
                    "division_error": "PermissionError: no hay permiso",
                },
            )

        motor = FolderRunner(registry, ajustes, run_job, watch_interval=0.01)
        run = _vaciar(motor, origen, tmp_path / "destino", disposition=folders.SourceDisposition.DELETE)

        assert (origen / "libro.pdf").exists()
        assert any("no se pudo dividir" in aviso for aviso in run.avisos)

    def test_un_pdf_que_se_sigue_copiando_se_espera_hasta_que_deja_de_crecer(self, tmp_path):
        ruta = tmp_path / "llegando.pdf"
        ruta.write_bytes(b"%PDF-1.4 primera mitad")

        def el_resto():
            with ruta.open("ab") as archivo:
                archivo.write(b" y la segunda mitad")

        temporizador = threading.Timer(0.03, el_resto)
        temporizador.start()
        try:
            huella = folders._esperar_a_que_termine_de_copiarse(ruta, calma=0.15)
        finally:
            temporizador.join()

        assert huella == constancias.huella_del_origen(ruta)
        assert huella[0] == len(b"%PDF-1.4 primera mitad y la segunda mitad")

    def test_un_pdf_viejo_no_se_espera(self, tmp_path):
        import os
        import time

        ruta = tmp_path / "viejo.pdf"
        ruta.write_bytes(b"%PDF-1.4")
        hace_una_hora = time.time() - 3600
        os.utime(ruta, (hace_una_hora, hace_una_hora))

        inicio = time.monotonic()
        huella = folders._esperar_a_que_termine_de_copiarse(ruta, calma=5.0)
        assert time.monotonic() - inicio < 1.0
        assert huella == constancias.huella_del_origen(ruta)


class TestUnExcelAbiertoEnLaRaiz:
    """Los generales de la raíz son justo los que el operador abre mientras la carpeta corre.

    Iban en un solo ``try``: el primero bloqueado -- abierto en Excel -- se
    llevaba por delante a los demás, y todo quedaba sólo en el registro del
    servicio, donde el operador no mira (2026-10-27).
    """

    def test_uno_abierto_no_impide_escribir_los_demas_y_se_avisa(self, ajustes, tmp_path, monkeypatch):
        from resolutions.api import indices

        def abierto(*_, **__):
            raise PermissionError(errno.EACCES, "Permission denied", "00.INVENTARIO GENERAL DE PROCESOS.xlsx")

        escritos: list[str] = []
        monkeypatch.setattr(indices, "inventario_de_procesos_de", abierto)
        monkeypatch.setattr(indices, "fuid_general_de", lambda *a, **k: escritos.append("fuid"))

        _pon(tmp_path / "origen", "a.pdf")
        motor, _ = _motor(ajustes, JobRegistry())
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        assert run.processed == 1
        assert "fuid" in escritos
        assert any("INVENTARIO GENERAL DE PROCESOS" in aviso for aviso in run.avisos)

    def test_la_planilla_del_documento_abierta_no_da_la_entrega_por_completa(
        self, ajustes, tmp_path, monkeypatch
    ):
        """Con la constancia «completa», la corrida siguiente saltaba el PDF y la planilla no se corregía nunca."""
        from resolutions.adapters.excel_inventory import ExcelInventory

        def abierta(self, *_, **__):
            raise PermissionError(errno.EACCES, "Permission denied", "a__inventario.xlsx")

        monkeypatch.setattr(ExcelInventory, "write", abierta)
        monkeypatch.setattr(folders, "ESPERAS_SI_ESTA_EN_USO", (0.0,))
        _pon(tmp_path / "origen", "a.pdf")
        motor, _ = _motor(ajustes, JobRegistry())
        run = _vaciar(
            motor, tmp_path / "origen", tmp_path / "destino", disposition=folders.SourceDisposition.DELETE
        )

        assert run.entregas_incompletas == 1
        assert (tmp_path / "origen" / "a.pdf").exists()
        constancia = constancias.leer(tmp_path / "destino" / "a" / constancias.NOMBRE)
        assert constancia.estado == EstadoDeEntrega.ENTREGANDO

    def test_la_planilla_que_se_libera_enseguida_se_escribe(self, ajustes, tmp_path, monkeypatch):
        from resolutions.adapters.excel_inventory import ExcelInventory

        original = ExcelInventory.write
        intentos = {"n": 0}

        def un_momento(self, *args, **kwargs):
            intentos["n"] += 1
            if intentos["n"] == 1:
                raise PermissionError(13, "The process cannot access the file because it is being used by another process")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(ExcelInventory, "write", un_momento)
        monkeypatch.setattr(folders, "ESPERAS_SI_ESTA_EN_USO", (0.0, 0.0))
        _pon(tmp_path / "origen", "a.pdf")
        motor, _ = _motor(ajustes, JobRegistry())
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        assert run.processed == 1
        assert run.entregas_incompletas == 0

    def test_el_control_de_entrega_abierto_se_avisa(self, ajustes, tmp_path, monkeypatch):
        from resolutions.api import retomar

        def abierto(*_, **__):
            raise PermissionError(errno.EACCES, "Permission denied", "00.CONTROL DE ENTREGA.xlsx")

        monkeypatch.setattr(retomar, "escribir_control", abierto)
        run = FolderRun(id="r", source=tmp_path / "origen", destination=tmp_path / "destino")
        run.retomar = Retomar.FALTANTES
        run.controles = {"x": object()}
        motor, _ = _motor(ajustes, JobRegistry())

        motor._escribir_control(run)

        assert any("CONTROL DE ENTREGA" in aviso for aviso in run.avisos)


class TestUnFalloNoTumbaLaCarpeta:
    """Lo pidió el operador: que si algo falla, lo pare, lo anote, se acomode y lo reintente."""

    def test_una_racha_de_fallos_pausa_y_no_detiene(self, ajustes, tmp_path):
        nombres = [f"{i:03d}.pdf" for i in range(12)]
        _pon(tmp_path / "origen", *nombres)
        ajustes = replace(ajustes, fallos_seguidos=3, pausa_tras_fallos=0.05, folder_documents=2)
        # Los cinco primeros fallan, como si la red se hubiera caído un rato.
        motor, hechos = _motor(ajustes, JobRegistry(), fallan=set(nombres[:5]))
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        assert run.state is RunState.DONE
        assert run.pausas >= 1 or run.a_la_vez is None
        assert sorted(set(hechos)) == nombres
        assert any("se pausa" in aviso for aviso in run.avisos)

    def test_tras_la_pausa_va_de_uno_en_uno_hasta_que_uno_sale_bien(self, ajustes, tmp_path):
        run = FolderRun(id="r", source=tmp_path, destination=tmp_path)
        ajustes = replace(ajustes, fallos_seguidos=2, pausa_tras_fallos=60)
        motor, _ = _motor(ajustes, JobRegistry())
        fallido = Job(id="f", filename="x.pdf", source=Path("x.pdf"), state=JobState.FAILED, error="red")
        bueno = Job(id="b", filename="y.pdf", source=Path("y.pdf"), state=JobState.DONE)
        motor._pausar_si_fallan_seguidos(run, fallido)
        motor._pausar_si_fallan_seguidos(run, fallido)
        assert run.a_la_vez == 1
        assert run.pausa_hasta > 0
        motor._pausar_si_fallan_seguidos(run, bueno)
        assert run.a_la_vez is None

    def test_lo_que_fallo_por_algo_pasajero_vuelve_al_final(self, ajustes, tmp_path):
        _pon(tmp_path / "origen", "a.pdf", "b.pdf")
        ajustes = replace(ajustes, pausa_tras_fallos=0.01)
        registry = JobRegistry()
        intentos: list[str] = []

        async def run_job(job):
            intentos.append(job.filename)
            if job.filename == "a.pdf" and intentos.count("a.pdf") == 1:
                job.reintentable = True
                registry.mark_failed(job, "Se perdió la conexión")
                return
            salida = ajustes.output_dir / job.id
            salida.mkdir(parents=True, exist_ok=True)
            (salida / "01_X.pdf").write_bytes(b"%PDF out")
            registry.mark_done(job, {"groups": [{"code": "01"}], "review_queue": []})

        motor = FolderRunner(registry, ajustes, run_job, watch_interval=0.01)
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        assert intentos.count("a.pdf") == 2
        assert run.failed == 0
        assert run.recuperados == 1
        assert run.processed == 2

    def test_lo_que_dice_algo_del_papel_no_vuelve(self, ajustes, tmp_path):
        _pon(tmp_path / "origen", "a.pdf")
        ajustes = replace(ajustes, pausa_tras_fallos=0.01)
        motor, hechos = _motor(ajustes, JobRegistry(), fallan={"a.pdf"})
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")
        assert hechos == ["a.pdf"]
        assert run.failed == 1

    def test_el_origen_que_se_desconecta_se_espera(self, ajustes, tmp_path, monkeypatch):
        from resolutions.api import folders

        _pon(tmp_path / "origen", "a.pdf")
        monkeypatch.setattr(folders.asyncio, "sleep", _sueno_corto(folders.asyncio.sleep))
        motor, hechos = _motor(ajustes, JobRegistry())
        # El recorrido va por lotes (2026-10-20): la red se cae al pedir el primero.
        original = motor._lotes_del_origen
        caidas = [1]

        def lotes(run):
            if caidas:
                caidas.pop()
                raise OSError(errno.ENETDOWN, "la red no está")
            yield from original(run)

        monkeypatch.setattr(motor, "_lotes_del_origen", lotes)
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        assert run.state is RunState.DONE
        assert hechos == ["a.pdf"]
        assert any("recorrer el origen" in aviso for aviso in run.avisos)


def _sueno_corto(dormir):
    async def corto(segundos, *args, **kwargs):
        return await dormir(min(segundos, 0.01), *args, **kwargs)

    return corto


class TestLaMemoriaNoCrece:
    def test_los_documentos_viejos_salen_del_registro(self, ajustes, tmp_path):
        nombres = [f"{i:03d}.pdf" for i in range(8)]
        _pon(tmp_path / "origen", *nombres)
        ajustes = replace(ajustes, trabajos_en_memoria=3)
        registry = JobRegistry()
        motor, _ = _motor(ajustes, registry)
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        assert run.processed == 8
        assert len(registry.list()) == 3
        aviso = run.as_dict()
        assert aviso["job_count"] == 8
        # Y su fila sigue en el inventario de procesos, que la guarda la corrida.
        assert len(run.procesos) == 8

    def test_el_aviso_lleva_solo_los_ultimos(self, tmp_path):
        run = FolderRun(id="r", source=tmp_path, destination=tmp_path)
        run.job_ids = [f"j{i}" for i in range(JOB_IDS_EN_PANTALLA + 50)]
        aviso = run.as_dict()
        assert len(aviso["job_ids"]) == JOB_IDS_EN_PANTALLA
        assert aviso["job_ids"][-1] == f"j{JOB_IDS_EN_PANTALLA + 49}"
        assert aviso["job_count"] == JOB_IDS_EN_PANTALLA + 50

    def test_lo_que_sumaban_los_retirados_no_se_pierde(self):
        from resolutions.api.folders import _acumular

        retirados = {"procedencias": {}, "revision": 0, "fallidas": 0, "consumo": None}
        for _ in range(2):
            job = Job(id="x", filename="a.pdf", source=Path("a.pdf"))
            job.progress.by_provenance = {"text_layer": 3}
            job.progress.marks = ["x", ".", "x"]
            job.progress.failed_pages = 1
            job.progress.consumo = {"peticiones": 2, "paginas_facturadas": 5, "coste_estimado": 0.5}
            _acumular(retirados, job)

        assert retirados["procedencias"] == {"text_layer": 6}
        assert retirados["revision"] == 4
        assert retirados["fallidas"] == 2
        assert retirados["consumo"]["paginas_facturadas"] == 10
        assert retirados["consumo"]["coste_estimado"] == 1.0


class TestElDescubrimiento:
    def test_una_subcarpeta_que_no_se_deja_leer_queda_en_los_avisos(self, ajustes, tmp_path, monkeypatch):
        from resolutions.api import folders

        _pon(tmp_path / "origen", "a.pdf")
        caminar = folders.os.walk

        def walk(raiz, onerror=None):
            onerror(PermissionError(13, "Acceso denegado", str(Path(raiz) / "CAJA 7")))
            yield from caminar(raiz, onerror=onerror)

        monkeypatch.setattr(folders.os, "walk", walk)
        motor, hechos = _motor(ajustes, JobRegistry())
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")

        assert hechos == ["a.pdf"]
        assert any("CAJA 7" in aviso for aviso in run.avisos)

    def test_el_orden_de_la_carpeta_se_conserva(self, ajustes, tmp_path):
        (tmp_path / "origen" / "b").mkdir()
        _pon(tmp_path / "origen" / "b", "1.pdf")
        _pon(tmp_path / "origen", "c.pdf", "a.pdf")
        registro = JobRegistry()
        motor, _ = _motor(ajustes, registro)
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino")
        # El orden en que se toman, no en el que empiezan a leerse: con varios
        # a la vez, cada uno espera en un hilo a que su PDF se libere y el que
        # vuelve primero es cuestión de suerte.
        tomados = [registro.get(job_id).filename for job_id in run.job_ids]
        assert tomados == ["a.pdf", str(Path("b") / "1.pdf"), "c.pdf"]

    def test_se_procesa_sin_esperar_a_recorrer_toda_la_carpeta(self, ajustes, tmp_path, monkeypatch):
        # «La idea no es que hasta que no termine de explorar la carpeta no
        # continúe» (2026-10-20): con lotes de dos, el primer PDF empieza con
        # la carpeta todavía a medio recorrer, y todos salen en orden.
        nombres = [f"{n:02d}.pdf" for n in range(1, 8)]
        _pon(tmp_path / "origen", *nombres)
        registro = JobRegistry()
        motor, hechos = _motor(ajustes, registro)
        monkeypatch.setattr(motor, "LOTE_DEL_ORIGEN", 2)
        vistos_al_empezar: list[int] = []
        procesar = motor._run_job

        async def run_job(job):
            corrida = next(iter(motor._runs.values()))
            vistos_al_empezar.append(corrida.discovered)
            await procesar(job)

        motor._run_job = run_job
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino", paralelo=1)

        assert run.state is RunState.DONE and run.processed == 7
        assert hechos == nombres
        assert vistos_al_empezar[0] < len(nombres)
        assert run.discovered == len(nombres)


class TestElRegistroEnDisco:
    def test_cada_dia_su_archivo(self, tmp_path):
        from resolutions.api.registro_en_consola import FORMATO_EN_DISCO, _ArchivoDelDia

        manejador = _ArchivoDelDia(tmp_path)
        manejador.setFormatter(logging.Formatter(FORMATO_EN_DISCO))
        registro = logging.getLogger("resolutions.prueba.disco")
        registro.addHandler(manejador)
        registro.setLevel(logging.INFO)
        try:
            registro.info("una línea con tilde")
        finally:
            registro.removeHandler(manejador)
            manejador.close()

        archivos = list(tmp_path.glob("bot-*.log"))
        assert len(archivos) == 1
        assert "una línea con tilde" in archivos[0].read_text(encoding="utf-8")


def test_la_constancia_es_json_legible(tmp_path):
    ruta = tmp_path / constancias.NOMBRE
    constancias.escribir(ruta, Constancia(origen="a.pdf", tamano=1, modificado_ns=2))
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["estado"] == "entregando"
    assert not list(tmp_path.glob("*.tmp"))


class TestArchivosEnParalelo:
    """Lo pidió el operador: elegir antes de procesar cuántos archivos van a la vez."""

    def test_la_cifra_se_valida_contra_los_procesos_del_servicio(self):
        from fastapi import HTTPException

        from resolutions.api.routers.trabajos import _paralelo

        ctx = SimpleNamespace(settings=SimpleNamespace(document_workers=4))
        assert _paralelo(ctx, None) is None
        assert _paralelo(ctx, "auto") is None
        assert _paralelo(ctx, "0") is None
        assert _paralelo(ctx, "3") == 3
        for imposible in ("5", "-1", "tres"):
            with pytest.raises(HTTPException) as capturado:
                _paralelo(ctx, imposible)
            assert "entre 1 y 4" in capturado.value.detail

    def test_un_lote_no_pasa_de_los_que_se_eligieron(self, tmp_path):
        a_la_vez = {"ahora": 0, "pico": 0}
        cerrojo = threading.Lock()

        def procesar(payload):
            with cerrojo:
                a_la_vez["ahora"] += 1
                a_la_vez["pico"] = max(a_la_vez["pico"], a_la_vez["ahora"])
            threading.Event().wait(0.05)
            with cerrojo:
                a_la_vez["ahora"] -= 1
            return {"groups": []}

        ctx = _contexto(procesar)
        ctx.pool = ThreadPoolExecutor(6)
        trabajos = [
            Job(id=f"j{i}", filename=f"{i}.pdf", source=tmp_path / f"{i}.pdf", owns_source=False,
                batch_id="lote-paralelo", paralelo=2)
            for i in range(6)
        ]

        async def todos():
            await asyncio.gather(*(_run(ctx, job) for job in trabajos))

        asyncio.run(todos())
        ctx.pool.shutdown()
        assert all(job.state is JobState.DONE for job in trabajos)
        assert a_la_vez["pico"] == 2

    def test_una_carpeta_va_con_los_que_eligio(self, ajustes, tmp_path):
        nombres = [f"{i:03d}.pdf" for i in range(8)]
        _pon(tmp_path / "origen", *nombres)
        registry = JobRegistry()
        a_la_vez = {"ahora": 0, "pico": 0}

        async def run_job(job):
            a_la_vez["ahora"] += 1
            a_la_vez["pico"] = max(a_la_vez["pico"], a_la_vez["ahora"])
            await asyncio.sleep(0.03)
            a_la_vez["ahora"] -= 1
            (ajustes.output_dir / job.id).mkdir(parents=True, exist_ok=True)
            (ajustes.output_dir / job.id / "01_X.pdf").write_bytes(b"%PDF out")
            registry.mark_done(job, {"groups": [{"code": "01"}], "review_queue": []})

        ajustes = replace(ajustes, folder_documents=1, document_workers=6)
        motor = FolderRunner(registry, ajustes, run_job, watch_interval=0.01)
        run = _vaciar(motor, tmp_path / "origen", tmp_path / "destino", paralelo=4)

        assert run.processed == 8
        assert run.paralelo == 4
        # Pidió cuatro con una sola ranura configurada: se abrieron más.
        assert a_la_vez["pico"] == 4

    def test_el_planificador_amplia_sin_tocar_el_automatico(self):
        from resolutions.api.planificador import Planificador

        planificador = Planificador(documentos_de_carpeta=2, hilos_por_documento=4, procesos=8)

        async def ir():
            ranuras = planificador.ranuras
            planificador.ampliar(5)
            tomadas = 0
            while not ranuras.locked():
                await ranuras.acquire()
                tomadas += 1
            return tomadas

        assert asyncio.run(ir()) == 5
        assert planificador.por_omision == 2


class TestLaUnidadQueNoEntrega:
    """Z: es Zoho WorkDrive: sin nube, el PDF dice su tamaño pero no se deja leer."""

    def test_no_se_llama_danado_a_lo_que_la_unidad_no_entrega(self, tmp_path, monkeypatch):
        from resolutions.adapters import pymupdf_source

        pdf = tmp_path / "RESOLUCION 03587-03595.pdf"
        pdf.write_bytes(b"%PDF-1.4 intacto")

        def no_abre(*args, **kwargs):
            raise RuntimeError("Failed to open file")

        def no_lee(*args, **kwargs):
            raise OSError(errno.EINVAL, "Invalid argument")

        monkeypatch.setattr(pymupdf_source.pymupdf, "open", no_abre)
        monkeypatch.setattr("builtins.open", no_lee)
        with pytest.raises(pymupdf_source.OrigenNoDisponible) as capturado:
            pymupdf_source._abrir(pdf, pdf.name)
        assert es_transitorio(capturado.value)
        assert "no se pudo leer de la unidad" in str(capturado.value)
        pickle.loads(pickle.dumps(capturado.value))

    def test_lo_que_se_lee_y_no_es_pdf_sigue_siendo_danado(self, tmp_path):
        from resolutions.adapters.pymupdf_source import PdfQueNoSeAbre, _abrir

        roto = tmp_path / "roto.pdf"
        roto.write_bytes(b"esto no es un pdf" * 20)
        with pytest.raises(PdfQueNoSeAbre, match="dañado"):
            _abrir(roto, roto.name)


class TestNingunaEsperaSinTope:
    """El 2026-10-19 cinco libros de actas se quedaron quietos con todas sus páginas leídas."""

    def _colgado(self):
        from concurrent.futures import ThreadPoolExecutor

        suelta = threading.Event()
        pool = ThreadPoolExecutor(1)
        return pool, pool.submit(suelta.wait, 5), suelta

    def test_aguardar_no_espera_para_siempre(self):
        from resolutions.application.control import (
            LecturaAtascada,
            NullRunControl,
            aguardar,
        )

        pool, futuro, suelta = self._colgado()
        with pytest.raises(LecturaAtascada, match="minutos sin volver"):
            aguardar(futuro, NullRunControl(), tope=0.3)
        suelta.set()
        pool.shutdown()

    def test_completados_y_alguno_listo_tampoco(self):
        from resolutions.application.control import (
            LecturaAtascada,
            NullRunControl,
            alguno_listo,
            completados,
        )

        pool, futuro, suelta = self._colgado()
        with pytest.raises(LecturaAtascada):
            list(completados([futuro], NullRunControl(), tope=0.3))
        with pytest.raises(LecturaAtascada):
            alguno_listo([futuro], NullRunControl(), tope=0.3)
        suelta.set()
        pool.shutdown()

    def test_lo_que_vuelve_a_tiempo_no_se_toca(self):
        from concurrent.futures import ThreadPoolExecutor

        from resolutions.application.control import NullRunControl, completados

        with ThreadPoolExecutor(2) as pool:
            futuros = [pool.submit(lambda n=n: n * 2) for n in range(5)]
            assert sorted(f.result() for f in completados(futuros, NullRunControl(), tope=5)) == [0, 2, 4, 6, 8]

    def test_viaja_entre_procesos_y_vuelve_al_final_no_en_el_acto(self):
        from resolutions.api.reintentos import merece_otra_vuelta
        from resolutions.application.control import LecturaAtascada

        error = pickle.loads(pickle.dumps(LecturaAtascada(900)))
        assert isinstance(error, LecturaAtascada)
        assert "15 minutos" in str(error)
        assert not es_transitorio(error)
        assert merece_otra_vuelta(error)


class TestElPoolCongelado:
    def _job(self, id_, silencio):
        import time

        job = Job(id=id_, filename=f"{id_}.pdf", source=Path(f"{id_}.pdf"), state=JobState.RUNNING)
        job.progress.last_event_monotonic = time.monotonic() - silencio
        return job

    def test_si_ninguno_avanza_es_el_pool(self):
        from resolutions.api.ejecucion import _pool_congelado

        este = self._job("a", 1300)
        ctx = SimpleNamespace(registry=SimpleNamespace(snapshot=lambda: [este, self._job("b", 900), self._job("c", 1250)]))
        assert _pool_congelado(ctx, este, 1200)

    def test_si_otro_avanza_es_el_pdf(self):
        from resolutions.api.ejecucion import _pool_congelado

        este = self._job("a", 1300)
        ctx = SimpleNamespace(registry=SimpleNamespace(snapshot=lambda: [este, self._job("b", 30)]))
        assert not _pool_congelado(ctx, este, 1200)

    def test_solo_no_se_sabe(self):
        from resolutions.api.ejecucion import _pool_congelado

        este = self._job("a", 1300)
        ctx = SimpleNamespace(registry=SimpleNamespace(snapshot=lambda: [este]))
        assert not _pool_congelado(ctx, este, 1200)
