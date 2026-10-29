"""Varios documentos a la vez, con topes que reparten la máquina.

Una carpeta de 103 PDF tardó 41 minutos procesándose de uno en uno, con diez
de los once procesos del pool parados. Esto fija la estructura que la
reemplaza: cada carpeta toma varios documentos a la vez, las ranuras son del
servicio y no de la carpeta, los hilos de OCR se reparten entre los que
corren, y las llamadas a la IA tienen un tope común. Nada de esto llama a un
proveedor: la red se simula.
"""

from __future__ import annotations

import asyncio
import io
import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from resolutions.api.folders import FolderRunner, RunState
from resolutions.api.jobs import JobRegistry
from resolutions.api.planificador import HILOS_MINIMOS, Planificador
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
    return settings


def _pdfs(carpeta: Path, cuantos: int) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    for i in range(cuantos):
        (carpeta / f"{i:03d}.pdf").write_bytes(b"%PDF-1.4 fake")


class _Medidor:
    """Un `run_job` que tarda un poco y cuenta cuántos corren a la vez."""

    def __init__(self, registry, ajustes, *, falla_al_entregar=()):
        self.registry = registry
        self.ajustes = ajustes
        self.ahora = 0
        self.pico = 0
        self.hechos: list[str] = []

    async def __call__(self, job):
        self.ahora += 1
        self.pico = max(self.pico, self.ahora)
        try:
            await asyncio.sleep(0.02)
            directorio = self.ajustes.output_dir / job.id
            directorio.mkdir(parents=True, exist_ok=True)
            (directorio / "01_x.pdf").write_bytes(b"%PDF-1.4 out")
            self.registry.mark_done(job, {"groups": [{"code": "01"}], "review_queue": []})
            self.hechos.append(job.filename)
        finally:
            self.ahora -= 1


def _esperar(corridas, tope=600):
    async def ir():
        for _ in range(tope):
            if not any(run.active for run in corridas()):
                return
            await asyncio.sleep(0.01)

    return ir()


class TestLasCarpetasVanEnParalelo:
    def test_el_escaneo_no_bloquea_el_bucle_de_eventos(self, ajustes, tmp_path, monkeypatch):
        (tmp_path / "origen").mkdir()
        registry = JobRegistry()
        medidor = _Medidor(registry, ajustes)
        motor = FolderRunner(registry, ajustes, medidor)
        hilo_del_bucle = threading.get_ident()
        hilos_de_escaneo: list[int] = []
        # Por lotes (2026-10-20): cada lote se lee en el hilo que pide el siguiente.
        descubrir = motor._lotes_del_origen

        def registrar_hilo(run):
            hilos_de_escaneo.append(threading.get_ident())
            yield from descubrir(run)

        monkeypatch.setattr(motor, "_lotes_del_origen", registrar_hilo)

        async def ir():
            run = motor.start(str(tmp_path / "origen"), str(tmp_path / "destino"))
            await _esperar(lambda: [run])

        asyncio.run(ir())

        assert hilos_de_escaneo
        assert hilos_de_escaneo[0] != hilo_del_bucle

    def test_una_carpeta_procesa_varios_a_la_vez_sin_pasar_del_tope(self, ajustes, tmp_path):
        _pdfs(tmp_path / "origen", 9)
        registry = JobRegistry()
        medidor = _Medidor(registry, ajustes)
        planificador = Planificador(documentos_de_carpeta=3, hilos_por_documento=8, procesos=11)
        motor = FolderRunner(registry, ajustes, medidor, planificador=planificador)

        async def ir():
            run = motor.start(str(tmp_path / "origen"), str(tmp_path / "destino"))
            await _esperar(lambda: [run])
            return run

        run = asyncio.run(ir())

        assert run.state is RunState.DONE
        assert run.processed == 9
        assert medidor.pico == 3
        assert run.en_curso == {}

    def test_dos_carpetas_se_reparten_las_mismas_ranuras(self, ajustes, tmp_path):
        _pdfs(tmp_path / "a", 4)
        _pdfs(tmp_path / "b", 4)
        registry = JobRegistry()
        medidor = _Medidor(registry, ajustes)
        planificador = Planificador(documentos_de_carpeta=2, hilos_por_documento=8, procesos=11)
        motor = FolderRunner(registry, ajustes, medidor, planificador=planificador)

        async def ir():
            uno = motor.start(str(tmp_path / "a"), str(tmp_path / "salida_a"))
            otro = motor.start(str(tmp_path / "b"), str(tmp_path / "salida_b"))
            await _esperar(lambda: [uno, otro])
            return uno, otro

        uno, otro = asyncio.run(ir())

        assert uno.processed == otro.processed == 4
        # Dos carpetas no doblan la carga: el tope es del servicio.
        assert medidor.pico == 2

    def test_se_toman_en_el_orden_de_la_carpeta(self, ajustes, tmp_path):
        _pdfs(tmp_path / "origen", 6)
        registry = JobRegistry()
        motor = FolderRunner(
            registry,
            ajustes,
            _Medidor(registry, ajustes),
            planificador=Planificador(documentos_de_carpeta=3, hilos_por_documento=8, procesos=11),
        )

        async def ir():
            run = motor.start(str(tmp_path / "origen"), str(tmp_path / "destino"))
            await _esperar(lambda: [run])
            return run

        run = asyncio.run(ir())
        nombres = [registry.get(job_id).filename for job_id in run.job_ids]
        assert nombres == [f"{i:03d}.pdf" for i in range(6)]

    def test_un_fallo_al_entregar_no_tumba_a_los_demas(self, ajustes, tmp_path, monkeypatch):
        _pdfs(tmp_path / "origen", 4)
        registry = JobRegistry()
        motor = FolderRunner(
            registry,
            ajustes,
            _Medidor(registry, ajustes),
            planificador=Planificador(documentos_de_carpeta=2, hilos_por_documento=8, procesos=11),
        )
        original = motor._deliver

        def entrega(run, job, origen, *resto):
            if origen.name == "001.pdf":
                raise PermissionError(13, "Permission denied", str(origen))
            return original(run, job, origen, *resto)

        monkeypatch.setattr(motor, "_deliver", entrega)

        async def ir():
            run = motor.start(str(tmp_path / "origen"), str(tmp_path / "destino"))
            await _esperar(lambda: [run])
            return run

        run = asyncio.run(ir())

        assert run.state is RunState.DONE
        assert run.failed == 1
        assert run.delivered == 3
        fallido = next(registry.get(i) for i in run.job_ids if registry.get(i).filename == "001.pdf")
        assert "No hay permiso" in fallido.error

    def test_detener_corta_a_todos_los_que_corren(self, ajustes, tmp_path):
        _pdfs(tmp_path / "origen", 6)
        registry = JobRegistry()
        cancelados: list[str] = []
        empezados: list[str] = []

        async def lento(job):
            empezados.append(job.filename)
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelados.append(job.filename)
                raise

        motor = FolderRunner(
            registry,
            ajustes,
            lento,
            planificador=Planificador(documentos_de_carpeta=3, hilos_por_documento=8, procesos=11),
        )

        async def ir():
            run = motor.start(str(tmp_path / "origen"), str(tmp_path / "destino"))
            # Se espera a que los tres estén leyendo, no a que figuren en
            # curso: entre una cosa y otra el PDF espera en un hilo a que el
            # archivo se libere, y detener ahí no deja nada que cancelar.
            for _ in range(500):
                if len(empezados) == 3:
                    break
                await asyncio.sleep(0.01)
            motor.stop(run.id)
            await asyncio.sleep(0.05)
            return run

        run = asyncio.run(ir())

        assert run.state is RunState.STOPPED
        assert sorted(cancelados) == ["000.pdf", "001.pdf", "002.pdf"]
        # Ninguno de los que esperaban turno llegó a empezar.
        assert len(run.job_ids) == 3

    def test_detener_no_deja_en_cola_a_los_que_esperaban_turno(self, ajustes, tmp_path):
        """2026-10-29: detenida la corrida, cuatro documentos siguieron «En cola ·
        esperando turno» para siempre: la cancelación les llegaba esperando su
        turno y nadie les cambiaba el estado."""
        from resolutions.api.jobs import IN_FLIGHT, JobState

        _pdfs(tmp_path / "origen", 4)
        registry = JobRegistry()
        un_turno = asyncio.Semaphore(1)
        leyendo: list[str] = []

        async def con_turno(job):
            # Como `ejecucion._run`: el trabajo espera su cupo antes de leer.
            async with un_turno:
                registry.mark_running(job)
                leyendo.append(job.filename)
                await asyncio.sleep(10)

        motor = FolderRunner(
            registry,
            ajustes,
            con_turno,
            planificador=Planificador(documentos_de_carpeta=3, hilos_por_documento=8, procesos=11),
        )

        async def ir():
            run = motor.start(str(tmp_path / "origen"), str(tmp_path / "destino"))
            for _ in range(500):
                if leyendo and len(run.job_ids) == 3:
                    break
                await asyncio.sleep(0.01)
            motor.stop(run.id)
            await asyncio.sleep(0.05)
            return run

        run = asyncio.run(ir())

        trabajos = [registry.get(job_id) for job_id in run.job_ids]
        assert len(trabajos) == 3
        assert [t.state for t in trabajos if t.state in IN_FLIGHT] == []
        assert {t.state for t in trabajos} == {JobState.CANCELLED}

    def test_la_pantalla_recibe_todos_los_que_estan_en_curso(self, ajustes, tmp_path):
        _pdfs(tmp_path / "origen", 3)
        registry = JobRegistry()
        vistos: list[int] = []

        async def mira(job):
            await asyncio.sleep(0.02)
            vistos.append(len(motor.get(next(iter(motor._runs))).as_dict()["en_curso"]))
            registry.mark_failed(job, "x")

        motor = FolderRunner(
            registry,
            ajustes,
            mira,
            planificador=Planificador(documentos_de_carpeta=3, hilos_por_documento=8, procesos=11),
        )

        async def ir():
            run = motor.start(str(tmp_path / "origen"), str(tmp_path / "destino"))
            await _esperar(lambda: [run])

        asyncio.run(ir())
        assert max(vistos) == 3


class TestElPlanificador:
    def test_uno_solo_usa_todos_sus_hilos(self):
        p = Planificador(documentos_de_carpeta=3, hilos_por_documento=8, procesos=11, hilos_de_la_maquina=12)
        assert p.hilos_para(1) == 8

    def test_varios_se_reparten_la_maquina(self):
        p = Planificador(documentos_de_carpeta=3, hilos_por_documento=8, procesos=11, hilos_de_la_maquina=12)
        assert p.hilos_para(3) == 3

    def test_nunca_baja_del_minimo(self):
        p = Planificador(documentos_de_carpeta=3, hilos_por_documento=8, procesos=11, hilos_de_la_maquina=12)
        assert p.hilos_para(40) == HILOS_MINIMOS == 1

    def test_los_que_esperan_en_el_pool_no_cuentan(self):
        # Con un pool de 3, el cuarto espera turno y no le quita hilos a nadie.
        p = Planificador(documentos_de_carpeta=3, hilos_por_documento=8, procesos=3, hilos_de_la_maquina=12)
        assert p.hilos_para(10) == p.hilos_para(3) == 3

    def test_cuenta_los_que_entran_y_salen(self):
        p = Planificador(documentos_de_carpeta=3, hilos_por_documento=8, procesos=11, hilos_de_la_maquina=12)
        with p.documento() as primero, p.documento() as segundo:
            assert p.en_curso == 2
        assert (primero, segundo) == (8, 5)
        assert p.en_curso == 0


class TestLosAjustes:
    def test_por_defecto_uno_por_cada_cuatro_hilos(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 12)
        assert Settings(document_workers=11).folder_documents == 3

    def test_nunca_mas_que_los_procesos_del_pool(self):
        assert Settings(document_workers=2, folder_documents=8).folder_documents == 2

    def test_se_configura_por_entorno(self, monkeypatch):
        monkeypatch.setenv("RESOLUTIONS_FOLDER_DOCUMENTS", "2")
        monkeypatch.setenv("RESOLUTIONS_IA_A_LA_VEZ", "5")
        ajustes = Settings.from_env()
        assert ajustes.folder_documents == min(2, ajustes.document_workers)
        assert ajustes.ia_a_la_vez == 5


class _Turnos:
    """Un semáforo de prueba que mide cuántas llamadas hay en el aire."""

    def __init__(self):
        self.dentro = 0
        self.pico = 0
        self.tomados = 0
        self._lock = threading.Lock()

    def __enter__(self):
        with self._lock:
            self.dentro += 1
            self.tomados += 1
            self.pico = max(self.pico, self.dentro)

    def __exit__(self, *_):
        with self._lock:
            self.dentro -= 1
        return False


class _Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class TestElTopeComunDeLaIA:
    def test_el_ocr_de_pago_toma_un_turno_por_peticion(self, monkeypatch):
        from resolutions.adapters.mistral_ocr import MistralOcr

        turnos = _Turnos()
        dentro_al_pedir: list[int] = []

        def urlopen(peticion, timeout=None):
            dentro_al_pedir.append(turnos.dentro)
            return _Respuesta(json.dumps({"pages": [{"markdown": "hola"}]}).encode())

        monkeypatch.setattr("urllib.request.urlopen", urlopen)
        MistralOcr(api_key="x", turnos=turnos).read(b"imagen")

        assert turnos.tomados == 1
        # La petición sale con el turno tomado, y al volver se suelta.
        assert dentro_al_pedir == [1]
        assert turnos.dentro == 0

    def test_esperar_un_reintento_no_retiene_el_turno(self, monkeypatch):
        import urllib.error

        from resolutions.adapters.mistral_resumen import MistralResumidor

        turnos = _Turnos()
        dentro_al_esperar: list[int] = []
        respuestas = [
            urllib.error.HTTPError("https://api.mistral.ai", 429, "x", {}, io.BytesIO(b"{}")),
            _Respuesta(
                json.dumps(
                    {"choices": [{"message": {"content": "Listo."}}], "usage": {}}
                ).encode()
            ),
        ]

        def urlopen(request, timeout):
            siguiente = respuestas.pop(0)
            if isinstance(siguiente, Exception):
                raise siguiente
            return siguiente

        monkeypatch.setattr("urllib.request.urlopen", urlopen)
        resumidor = MistralResumidor(
            "llave",
            turnos=turnos,
            esperar=lambda _segundos: dentro_al_esperar.append(turnos.dentro),
        )

        assert resumidor.resumir("texto") == "Listo."
        assert turnos.tomados == 2
        assert dentro_al_esperar == [0]

    def test_sin_tope_se_pide_igual(self, monkeypatch):
        from resolutions.adapters.mistral_ocr import MistralOcr

        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda peticion, timeout=None: _Respuesta(
                json.dumps({"pages": [{"markdown": "hola"}]}).encode()
            ),
        )
        assert MistralOcr(api_key="x").read(b"imagen").text == "hola"


class TestLaLecturaPorLotes:
    """Varias imágenes por arranque de Tesseract, sin perder qué falló en cuál."""

    def test_los_lotes_no_dejan_lectores_parados(self):
        from resolutions.application.acta_consejo import _lotes

        assert [len(lote) for lote in _lotes(list(range(5)), 8, 4)] == [1, 1, 1, 1, 1]
        assert [len(lote) for lote in _lotes(list(range(40)), 4, 4)] == [4] * 10
        assert _lotes([], 4, 4) == []

    def test_un_lote_que_falla_se_lee_de_una_en_una(self):
        from resolutions.application.acta_consejo import _leer_lote

        class Motor:
            def read_varias(self, imagenes):
                raise RuntimeError("el lote no se dejó leer")

            def read(self, imagen):
                if imagen == b"mala":
                    raise RuntimeError("ésta no")
                return imagen.decode()

        salida = _leer_lote(Motor(), [b"una", b"mala", b"otra"])
        assert [leida for leida, _ in salida] == ["una", None, "otra"]
        assert isinstance(salida[1][1], RuntimeError)

    def test_un_motor_sin_lotes_lee_de_una_en_una(self):
        from resolutions.application.acta_consejo import _leer_lote

        class Motor:
            def read(self, imagen):
                return imagen.decode()

        assert _leer_lote(Motor(), [b"a", b"b"]) == [("a", None), ("b", None)]

    def test_el_tsv_de_un_lote_se_reparte_por_imagen(self):
        from resolutions.adapters.tesseract_ocr import _partir_por_imagen, en_columnas

        filas = [
            ["level", "page_num", "block_num", "par_num", "line_num", "word_num",
             "left", "top", "width", "height", "conf", "text"],
            ["5", "1", "1", "1", "1", "1", "0", "0", "1", "1", "95", "ACTA"],
            ["1", "2", "0", "0", "0", "0", "0", "0", "1", "1", "-1", ""],
            ["5", "3", "1", "1", "1", "1", "0", "0", "1", "1", "90", "GRADO"],
        ]
        tsv = "".join(chr(9).join(fila) + chr(10) for fila in filas)
        partes = _partir_por_imagen(en_columnas(tsv), 3)
        assert [parte["text"] for parte in partes] == [["ACTA"], [""], ["GRADO"]]
