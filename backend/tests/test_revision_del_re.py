"""La Revisión del RE: el operador confirma un candidato o escribe el RE que la máquina no leyó con certeza.

Lo decidió el operador el 2026-11-18: lo que la máquina sólo sugiere -- un
solo lector, una corrección, el RE de su trámite -- se confirma en la
Revisión. Confirmar mueve todo junto: el PDF y el informe del trabajo, su
índice, y en el destino el PDF del NIC, su constancia y el índice del NIC.
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest

from resolutions.adapters.indice_electronico import leer_indice

RE = "RE8673202103319"
POR_CONFIRMAR = "RE por confirmar, el nombre va sin él hasta que se confirme en la Revisión: RE8673202103319 (…)"


def _pdf(ruta: Path, paginas: int = 2) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as documento:
        for _ in range(paginas):
            documento.new_page().insert_text((72, 90), "No DE RADICACION: RE86732021033A")
        documento.save(ruta)


def _informe() -> dict:
    return {
        "groups": [{"code": "01", "type": "DERECHO DE PETICION", "pages": [1, 2]}],
        "outputs": ["UPD1/01_DERECHO-DE-PETICION.pdf"],
        "inventory": {
            "items": [
                {"file_name": "UPD1/01_DERECHO-DE-PETICION.pdf", "page_numbers": [1, 2], "type": "DERECHO DE PETICION"}
            ]
        },
        "review_queue": [{"page": 1, "reason": POR_CONFIRMAR}, {"page": 2, "reason": "la fecha no se leyó"}],
        "evidencia": {"re": {"1": {"estado": "requiere validación", "candidatos": [{"valor": RE}]}}},
        "indice_electronico": "00.INDICE ELECTRONICO.xlsx",
    }


@pytest.fixture
def trabajo(client, tmp_path):
    from resolutions.adapters.indice_electronico import FilaDelIndice, escribir_indice
    from resolutions.api import main

    job = main.contexto.registry.create("UPD1.pdf", tmp_path / "ya-no-esta.pdf")
    carpeta = main.contexto.settings.output_dir / job.id / "UPD1"
    _pdf(carpeta / "01_DERECHO-DE-PETICION.pdf")
    escribir_indice(
        carpeta,
        [FilaDelIndice(nombre="DERECHO DE PETICION", fecha_creacion=date(2021, 10, 27), fecha_incorporacion=date(2026, 11, 18), orden=1, paginas=2)],
        territorial="MAGANGUE",
    )
    main.contexto.registry.mark_done(job, _informe())
    return job


class TestElHttp:
    def test_sin_identificarse_no(self, client, trabajo):
        assert client.put(f"/api/jobs/{trabajo.id}/re/1", json={"re": RE}).status_code == 401

    def test_un_re_mal_escrito_no(self, client, trabajo, administrador):
        respuesta = client.put(f"/api/jobs/{trabajo.id}/re/1", json={"re": "RE867320210339"}, headers=administrador)
        assert respuesta.status_code == 422 and "trece cifras" in respuesta.json()["detail"]

    def test_la_hoja_del_sello_se_ve_sin_el_original(self, client, trabajo):
        respuesta = client.get(f"/api/jobs/{trabajo.id}/re/1/hoja.jpg")
        assert respuesta.status_code == 200 and respuesta.headers["content-type"] == "image/jpeg"


class TestElTrabajo:
    def test_confirmar_el_candidato_mueve_todo_junto(self, client, trabajo, administrador):
        from resolutions.api import main

        respuesta = client.put(
            f"/api/jobs/{trabajo.id}/re/2", json={"re": "re 8673 2021 03319"}, headers=administrador
        )
        assert respuesta.status_code == 200, respuesta.text
        cuerpo = respuesta.json()
        assert cuerpo["re"] == RE and cuerpo["archivo"] == f"UPD1/01_DERECHO-DE-PETICION-{RE}.pdf"
        carpeta = main.contexto.settings.output_dir / trabajo.id / "UPD1"
        assert (carpeta / f"01_DERECHO-DE-PETICION-{RE}.pdf").is_file()
        assert not (carpeta / "01_DERECHO-DE-PETICION.pdf").exists()
        informe = main.contexto.registry.get(trabajo.id).report
        assert informe["inventory"]["items"][0]["file_name"] == f"UPD1/01_DERECHO-DE-PETICION-{RE}.pdf"
        assert informe["outputs"] == [f"UPD1/01_DERECHO-DE-PETICION-{RE}.pdf"]
        assert informe["groups"][0]["code"] == f"01 {RE}"
        assert informe["evidencia"]["re"]["1"]["estado"] == "verificado"
        assert informe["evidencia"]["re"]["1"]["metodo"] == "confirmado por el operador"
        # Sale de la Revisión lo del RE, y lo demás se queda.
        assert informe["review_queue"] == [{"page": 2, "reason": "la fecha no se leyó"}]
        assert [f.nombre for f in leer_indice(carpeta / "00.INDICE ELECTRONICO.xlsx").filas] == [
            f"DERECHO DE PETICION-{RE}"
        ]

    def test_una_oficina_rara_avisa_y_no_bloquea(self, client, trabajo, administrador):
        respuesta = client.put(f"/api/jobs/{trabajo.id}/re/1", json={"re": "RE7777202103319"}, headers=administrador)
        assert respuesta.status_code == 200 and "oficina 7777" in respuesta.json()["avisos"][0]


class TestElDestino:
    def test_el_re_llega_al_pdf_del_nic_su_constancia_y_su_indice(self, tmp_path):
        from dataclasses import replace

        from test_entrega_plana import _caja, _indice

        from resolutions.api import constancia as constancias
        from resolutions.api.folders import FolderRunner, RunState
        from resolutions.api.jobs import JobRegistry
        from resolutions.api.settings import Settings

        ajustes = replace(
            Settings(),
            upload_dir=tmp_path / "uploads",
            output_dir=tmp_path / "outputs",
            ledger_path=tmp_path / "inventory.jsonl",
            pausa_tras_fallos=0.01,
        )
        ajustes.ensure_directories()
        registro = JobRegistry()

        async def run_job(job):
            salida = ajustes.output_dir / job.id / "UPD1"
            salida.mkdir(parents=True, exist_ok=True)
            (salida / "01_RECLAMO.pdf").write_bytes(b"%PDF-1.4 reclamo")
            _indice(salida, "UPD1", "RECLAMO")
            registro.mark_done(job, {"groups": [{"code": "01"}], "review_queue": [], "indice_electronico": "00.INDICE ELECTRONICO.xlsx"})

        motor = FolderRunner(registro, ajustes, run_job, watch_interval=0.01)
        _caja(tmp_path / "origen", "1001051", "UPD1")

        async def ir():
            run = motor.start(str(tmp_path / "origen"), str(tmp_path / "destino"), task="segment")
            for _ in range(800):
                if not run.active:
                    return run
                await asyncio.sleep(0.01)
            return run

        run = asyncio.run(ir())
        assert run.state is RunState.DONE
        job = next(j for j in registro.list() if j.filename.endswith("UPD1.pdf"))
        assert motor.tiene_la_corrida(job)

        assert motor.corregir_re(job, 0, RE) == []
        caja = tmp_path / "destino" / "1001051"
        assert (caja / f"01_RECLAMO-{RE}.pdf").is_file() and not (caja / "01_RECLAMO.pdf").exists()
        constancia = constancias.leer(caja / ".bot-entrega-UPD1.json")
        assert [a["ruta"] for a in constancia.archivos if a["ruta"].endswith(".pdf")] == [f"01_RECLAMO-{RE}.pdf"]
        assert [f.nombre for f in leer_indice(caja / "00.INDICE ELECTRONICO.xlsx").filas] == [f"RECLAMO-{RE}"]
