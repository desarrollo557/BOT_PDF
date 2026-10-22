"""La caja de correspondencia se entrega directo en la carpeta de su NIC.

Lo pidió el operador el 2026-10-21: «DESTINO\\210847» con los archivos de su UPD
dentro, no «DESTINO\\210847\\UPD2998726\\…». Y el 2026-10-22, al ver dos UPD en
un mismo NIC: «no hay necesidad de que crees otro índice electrónico, o que en
el nombre le coloques primero la UPD; la idea es que por NIC estén sus archivos
en la raíz, con la estructura número-título». Así: los PDF de todos sus UPD
numerados seguidos y un solo índice. Las demás habilidades siguen con su
carpeta por PDF.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from resolutions.adapters.indice_electronico import (
    FilaDelIndice,
    escribir_indice,
    leer_indice,
)
from resolutions.api import constancia as constancias
from resolutions.api.folders import REEMPLAZADOS_DIR, FolderRunner, RunState
from resolutions.api.jobs import JobRegistry
from resolutions.api.settings import Settings

INDICE = "00.INDICE ELECTRONICO.xlsx"


@pytest.fixture
def ajustes(tmp_path):
    settings = replace(
        Settings(),
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "outputs",
        ledger_path=tmp_path / "inventory.jsonl",
        pausa_tras_fallos=0.01,
    )
    settings.ensure_directories()
    return settings


def _caja(origen: Path, caja: str, *upds: str) -> None:
    (origen / caja).mkdir(parents=True, exist_ok=True)
    for upd in upds:
        (origen / caja / f"{upd}.pdf").write_bytes(b"%PDF-1.4 " + upd.encode())


def _indice(carpeta: Path, upd: str, *nombres: str) -> Path:
    """Un Índice Electrónico de verdad, como el que deja el worker."""
    filas = [
        FilaDelIndice(
            nombre=nombre,
            fecha_creacion=date(2024, 2, 8),
            fecha_incorporacion=date(2026, 10, 22),
            orden=orden,
            paginas=3,
        )
        for orden, nombre in enumerate(nombres, start=1)
    ]
    return escribir_indice(carpeta, filas, nic="1000265", territorial="MAGANGUE", nombre_del_expediente=upd)


def _motor(ajustes, registro, hechos):
    async def run_job(job):
        hechos.append(job.filename)
        # Como el worker: dentro de su carpeta de trabajo, en una subcarpeta.
        upd = Path(job.filename).stem
        salida = ajustes.output_dir / job.id / upd
        salida.mkdir(parents=True, exist_ok=True)
        (salida / "01_RECLAMO.pdf").write_bytes(b"%PDF-1.4 " + job.filename.encode())
        _indice(salida, upd, f"RECLAMO DE {upd}")
        registro.mark_done(
            job,
            {"groups": [{"code": "01"}], "review_queue": [], "indice_electronico": INDICE},
        )

    return FolderRunner(registro, ajustes, run_job, watch_interval=0.01)


def _correr(motor, origen, destino, **opciones):
    async def ir():
        run = motor.start(str(origen), str(destino), **opciones)
        for _ in range(800):
            if not run.active:
                return run
            await asyncio.sleep(0.01)
        return run

    return asyncio.run(ir())


def _nombres(carpeta: Path) -> list[str]:
    return sorted(p.name for p in carpeta.iterdir() if p.name != REEMPLAZADOS_DIR)


class TestLaEntregaPlana:
    def test_un_nic_con_dos_upd_numerado_seguido_y_un_solo_indice(self, ajustes, tmp_path):
        _caja(tmp_path / "origen", "1000265", "UPD1", "UPD2")
        _caja(tmp_path / "origen", "210847", "UPD3")
        hechos: list[str] = []
        run = _correr(_motor(ajustes, JobRegistry(), hechos), tmp_path / "origen", tmp_path / "destino", task="segment")

        assert run.state is RunState.DONE and run.processed == 3
        caja = tmp_path / "destino" / "1000265"
        assert _nombres(caja) == [
            ".bot-entrega-UPD1.json",
            ".bot-entrega-UPD2.json",
            INDICE,
            "01_RECLAMO.pdf",
            "02_RECLAMO.pdf",
        ]
        # Por el orden de sus UPD, cada uno con lo suyo.
        assert (caja / "01_RECLAMO.pdf").read_bytes().endswith(b"UPD1.pdf")
        assert (caja / "02_RECLAMO.pdf").read_bytes().endswith(b"UPD2.pdf")
        # Un solo índice, con las filas de los dos en ese mismo orden.
        indice = leer_indice(caja / INDICE)
        assert [(f.orden, f.nombre) for f in indice.filas] == [(1, "RECLAMO DE UPD1"), (2, "RECLAMO DE UPD2")]
        assert indice.nombre_del_expediente == "UPD1, UPD2"
        assert indice.nic == "1000265"
        assert _nombres(tmp_path / "destino" / "210847") == [".bot-entrega-UPD3.json", INDICE, "01_RECLAMO.pdf"]

    def test_relanzarla_no_repite_nada(self, ajustes, tmp_path):
        _caja(tmp_path / "origen", "1000265", "UPD1", "UPD2")
        registro = JobRegistry()
        _correr(_motor(ajustes, registro, []), tmp_path / "origen", tmp_path / "destino", task="segment")
        hechos: list[str] = []
        otra = _correr(_motor(ajustes, registro, hechos), tmp_path / "origen", tmp_path / "destino", task="segment")
        assert hechos == [] and otra.ya_entregados == 2
        assert _nombres(tmp_path / "destino" / "1000265")[-2:] == ["01_RECLAMO.pdf", "02_RECLAMO.pdf"]

    def test_rehacer_uno_no_toca_al_otro_upd_de_la_caja(self, ajustes, tmp_path):
        _caja(tmp_path / "origen", "1000265", "UPD1", "UPD2")
        registro = JobRegistry()
        _correr(_motor(ajustes, registro, []), tmp_path / "origen", tmp_path / "destino", task="segment")
        # UPD1 se escaneó otra vez: sólo él se rehace.
        (tmp_path / "origen" / "1000265" / "UPD1.pdf").write_bytes(b"%PDF-1.4 escaneado de nuevo")
        hechos: list[str] = []
        _correr(_motor(ajustes, registro, hechos), tmp_path / "origen", tmp_path / "destino", task="segment")
        assert hechos == [str(Path("1000265") / "UPD1.pdf")]
        caja = tmp_path / "destino" / "1000265"
        assert (caja / "02_RECLAMO.pdf").read_bytes().endswith(b"UPD2.pdf")
        apartados = [p for p in (caja / REEMPLAZADOS_DIR).rglob("*") if p.is_file()]
        assert apartados and not any(p.read_bytes().endswith(b"UPD2.pdf") for p in apartados)

    def test_las_otras_habilidades_siguen_con_su_carpeta_por_pdf(self, ajustes, tmp_path):
        _caja(tmp_path / "origen", "1000265", "UPD1")
        _correr(_motor(ajustes, JobRegistry(), []), tmp_path / "origen", tmp_path / "destino", task="both")
        assert (tmp_path / "destino" / "1000265" / "UPD1" / "01_RECLAMO.pdf").exists()


class TestLaEntregaDeAntes:
    """Lo entregado antes, en su subcarpeta UPD o con el UPD delante, no se vuelve a pagar."""

    def _de_antes(self, ajustes, tmp_path):
        _caja(tmp_path / "origen", "1000265", "UPD1")
        registro = JobRegistry()
        # La forma de antes es la de las otras habilidades: una carpeta por PDF.
        _correr(_motor(ajustes, registro, []), tmp_path / "origen", tmp_path / "destino", task="both")
        assert (tmp_path / "destino" / "1000265" / "UPD1" / "01_RECLAMO.pdf").exists()
        return registro

    def test_saltar_lo_entregado_la_reconoce(self, ajustes, tmp_path):
        registro = self._de_antes(ajustes, tmp_path)
        hechos: list[str] = []
        run = _correr(_motor(ajustes, registro, hechos), tmp_path / "origen", tmp_path / "destino", task="segment")
        assert hechos == [] and run.ya_entregados == 1

    def test_procesar_todo_otra_vez_aparta_la_subcarpeta_y_deja_la_caja_plana(self, ajustes, tmp_path):
        registro = self._de_antes(ajustes, tmp_path)
        hechos: list[str] = []
        _correr(
            _motor(ajustes, registro, hechos),
            tmp_path / "origen",
            tmp_path / "destino",
            task="segment",
            retomar="todo",
        )
        caja = tmp_path / "destino" / "1000265"
        assert hechos == [str(Path("1000265") / "UPD1.pdf")]
        assert not (caja / "UPD1").exists()
        assert (caja / "01_RECLAMO.pdf").exists()
        assert any((caja / REEMPLAZADOS_DIR).rglob("UPD1/01_RECLAMO.pdf"))

    def test_la_caja_con_el_upd_delante_se_ordena_sin_volver_a_procesarla(self, ajustes, tmp_path):
        """Como se entregaba el 2026-10-21: «UPD1_01_…», «00.INDICE ELECTRONICO UPD1.xlsx»."""
        _caja(tmp_path / "origen", "1000265", "UPD1", "UPD2")
        caja = tmp_path / "destino" / "1000265"
        caja.mkdir(parents=True)
        for upd, documentos in (("UPD1", ["CONSTANCIA", "RECONOCIMIENTO"]), ("UPD2", ["RECLAMO"])):
            archivos = []
            for orden, documento in enumerate(documentos, start=1):
                pdf = caja / f"{upd}_{orden:02d}_{documento}.pdf"
                pdf.write_bytes(b"%PDF-1.4 " + f"{upd} {documento}".encode())
                archivos.append(pdf)
            hoja = _indice(caja, upd, *documentos)
            suelto = caja / f"00.INDICE ELECTRONICO {upd}.xlsx"
            hoja.rename(suelto)
            archivos.append(suelto)
            origen = tmp_path / "origen" / "1000265" / f"{upd}.pdf"
            tamano, modificado = constancias.huella_del_origen(origen)
            constancias.escribir(
                caja / f".bot-entrega-{upd}.json",
                constancias.Constancia(
                    origen=f"1000265/{upd}.pdf",
                    tamano=tamano,
                    modificado_ns=modificado,
                    estado=constancias.EstadoDeEntrega.COMPLETA,
                    archivos=constancias.archivos_de(caja, archivos),
                    habilidad="Caja de correspondencia",
                ),
            )
        hechos: list[str] = []
        run = _correr(_motor(ajustes, JobRegistry(), hechos), tmp_path / "origen", tmp_path / "destino", task="segment")

        assert hechos == [] and run.ya_entregados == 2
        assert _nombres(caja) == [
            ".bot-entrega-UPD1.json",
            ".bot-entrega-UPD2.json",
            INDICE,
            "01_CONSTANCIA.pdf",
            "02_RECONOCIMIENTO.pdf",
            "03_RECLAMO.pdf",
        ]
        assert (caja / "03_RECLAMO.pdf").read_bytes().endswith(b"UPD2 RECLAMO")
        indice = leer_indice(caja / INDICE)
        assert [f.nombre for f in indice.filas] == ["CONSTANCIA", "RECONOCIMIENTO", "RECLAMO"]
        assert [f.orden for f in indice.filas] == [1, 2, 3]
        # Los índices sueltos de cada UPD, apartados, no borrados.
        assert sorted(p.name for p in (caja / REEMPLAZADOS_DIR).rglob("*.xlsx")) == [
            "00.INDICE ELECTRONICO UPD1.xlsx",
            "00.INDICE ELECTRONICO UPD2.xlsx",
        ]
        # Y la próxima vez sigue saltándolos: sus constancias dicen los nombres nuevos.
        otra = _correr(_motor(ajustes, JobRegistry(), hechos), tmp_path / "origen", tmp_path / "destino", task="segment")
        assert hechos == [] and otra.ya_entregados == 2
