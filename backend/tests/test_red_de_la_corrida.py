"""La corrida de carpeta dice si va por red o por local, a qué velocidad y cuánto falta.

Lo pidió el operador el 2026-11-05, con estas elecciones: una prueba al empezar
y la medida en vivo; el acceso -- red o local -- del origen y del destino; los
MB/s reales; lo que falta, separado en red y proceso; y lo mismo en el
«00.INVENTARIO GENERAL DE PROCESOS.xlsx».
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from pathlib import Path

import pytest
from openpyxl import load_workbook

from resolutions.adapters.excel_inventory import ExcelInventarioDeProcesos, FilaDeProceso
from resolutions.api.folders import FolderRun, FolderRunner, RunState, _copiar
from resolutions.api.indices import con_la_red
from resolutions.api.jobs import JobRegistry
from resolutions.api.settings import Settings
from resolutions.domain.ritmo import MB


@pytest.fixture
def ajustes(tmp_path):
    settings = replace(
        Settings(),
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "outputs",
        ledger_path=tmp_path / "inventory.jsonl",
    )
    settings.ensure_directories()
    return settings


def _fila(pdf: str = "UPD1.pdf") -> FilaDeProceso:
    return FilaDeProceso(
        pdf=pdf, habilidad="Caja de correspondencia", lectura="Solo OCR", entrega="—", paginas=3,
        documentos=1, en_revision=0, estado="Listo", inicio=None, duracion="0:01", paginas_pagadas=0,
        operador="SIAR", destino="1000265",
    )


class TestLoQueVeLaPantalla:
    def test_red_o_local_la_velocidad_y_lo_que_falta(self, tmp_path):
        run = FolderRun(id="r", source=tmp_path / "MAGANGUE", destination=tmp_path / "MAGANGUE - PROCESADO")
        run.state = RunState.PROCESSING
        run.origen_de_red, run.destino_de_red = True, False
        run.recorrido_terminado = True
        # Cuatro descargas de 8 MB en 2 s cada una: 4 MB/s.
        for inicio in (0.0, 10.0, 20.0, 30.0):
            run.ritmo_de_lectura.sumar(8 * MB, inicio, inicio + 2.0)
        # Un PDF cada 10 s, y 60 en cola de 4 MB cada uno.
        ahora = time.monotonic()
        run.terminados_en.extend([ahora - 40, ahora - 30, ahora - 20, ahora - 10, ahora])
        run.queue = [f"UPD{n}.pdf" for n in range(60)]
        run.huellas_del_origen = {f"/o/UPD{n}.pdf": (4 * MB, 0) for n in range(60)}

        red = run.as_dict()["red"]

        assert red["origen"] == {"acceso": "red", "mb_s": pytest.approx(4.0), "velocidad": "4,0 MB/s"}
        assert red["destino"]["acceso"] == "local"
        assert red["falta_s"] == pytest.approx(600.0, rel=0.05)
        assert red["falta"] == "10 min"
        # 240 MB por traer a 4 MB/s: un minuto de red; el destino es local.
        assert red["red_s"] == pytest.approx(60.0)
        assert red["al_menos"] is False

    def test_mientras_no_se_mide_dice_la_prueba_y_luego_lo_de_en_vivo(self, tmp_path):
        run = FolderRun(id="r", source=tmp_path / "a", destination=tmp_path / "b")
        run.prueba_de_red.update({"estado": "hecha", "escritura_mb_s": 50.0})
        assert run.velocidades() == (None, 50.0)
        run.ritmo_de_escritura.sumar(10 * MB, 0.0, 1.0)
        assert run.velocidades() == (None, pytest.approx(10.0))

    def test_terminada_no_le_falta_nada(self, tmp_path):
        run = FolderRun(id="r", source=tmp_path / "a", destination=tmp_path / "b")
        run.state = RunState.DONE
        run.queue = ["x.pdf"]
        assert run.as_dict()["red"]["falta_s"] == 0.0


class TestLaCopiaSeMide:
    def test_copiar_dice_cuanto_y_en_cuanto(self, tmp_path):
        origen = tmp_path / "a.pdf"
        origen.write_bytes(b"x" * 300_000)
        medidas = []
        _copiar(origen, tmp_path / "b.pdf", lambda b, inicio, fin: medidas.append((b, fin - inicio)))
        assert medidas and medidas[0][0] == 300_000 and medidas[0][1] >= 0
        assert (tmp_path / "b.pdf").read_bytes() == origen.read_bytes()


class TestElInventarioDeProcesos:
    def test_la_fila_lleva_el_acceso_y_la_velocidad_de_su_pdf_o_la_de_la_corrida(self):
        propia = con_la_red(
            _fila(), origen_de_red=True, destino_de_red=False, lectura=(8 * MB, 4.0), escritura=None,
            lectura_de_la_corrida=9.0, escritura_de_la_corrida=120.0,
        )
        assert (propia.acceso, propia.lectura_mb_s, propia.escritura_mb_s) == ("Red → Local", 2.0, 120.0)
        sin_medir = con_la_red(_fila(), origen_de_red=None, destino_de_red=None)
        assert (sin_medir.acceso, sin_medir.lectura_mb_s) == ("— → —", None)

    def test_columnas_y_seccion_de_la_red(self, tmp_path):
        fila = con_la_red(_fila(), origen_de_red=True, destino_de_red=False, lectura=(8 * MB, 4.0))
        red = {
            "origen": {"acceso": "red", "velocidad": "2,0 MB/s"},
            "destino": {"acceso": "local", "velocidad": "—"},
            "prueba": {"estado": "hecha", "lectura_mb_s": 2.5, "escritura_mb_s": 110.0},
        }
        ruta = ExcelInventarioDeProcesos().write([fila], tmp_path, origen="MAGANGUE", red=red)
        libro = load_workbook(ruta)
        procesos = libro["Procesos"]
        titulos = [str(celda.value).upper() for fila_ in procesos.iter_rows(max_row=10) for celda in fila_ if celda.value]
        assert {"ACCESO", "LECTURA (MB/S)", "ESCRITURA (MB/S)"} <= set(titulos)
        valores = [celda.value for fila_ in procesos.iter_rows() for celda in fila_]
        assert "Red → Local" in valores and 2.0 in valores
        resumen = [celda.value for fila_ in libro["Resumen"].iter_rows() for celda in fila_ if celda.value]
        assert "Red · 2,0 MB/s" in resumen and "Local · —" in resumen
        assert "lectura 2,5 MB/s · escritura 110 MB/s" in resumen


def _motor(ajustes, registro):
    async def run_job(job):
        salida = ajustes.output_dir / job.id / Path(job.filename).stem
        salida.mkdir(parents=True, exist_ok=True)
        (salida / "01_RECLAMO.pdf").write_bytes(b"%PDF-1.4 " + b"x" * 200_000)
        registro.mark_done(job, {"groups": [{"code": "01"}], "review_queue": []})

    return FolderRunner(registro, ajustes, run_job, watch_interval=0.01)


def test_una_corrida_local_lo_dice_y_mide_sus_entregas(ajustes, tmp_path):
    origen = tmp_path / "origen" / "1000265"
    origen.mkdir(parents=True)
    for upd in ("UPD1", "UPD2"):
        (origen / f"{upd}.pdf").write_bytes(b"%PDF-1.4 " + b"y" * 500_000)
    motor = _motor(ajustes, JobRegistry())

    async def ir():
        run = motor.start(str(tmp_path / "origen"), str(tmp_path / "destino"), task="segment")
        for _ in range(800):
            if not run.active:
                break
            await asyncio.sleep(0.01)
        return run

    run = asyncio.run(ir())

    assert run.state is RunState.DONE
    red = run.as_dict()["red"]
    assert (red["origen"]["acceso"], red["destino"]["acceso"]) == ("local", "local")
    # Cada PDF entregado se midió, y su fila del inventario de procesos lo dice.
    assert run.ritmo_de_escritura.medidas >= 2
    assert {fila.acceso for fila in run.procesos.values()} == {"Local → Local"}
    assert all(fila.escritura_mb_s for fila in run.procesos.values())
    # La prueba no deja nada suyo en el destino.
    assert not [p for p in run.destination.rglob("*") if p.name.startswith(".botpdf-prueba")]
