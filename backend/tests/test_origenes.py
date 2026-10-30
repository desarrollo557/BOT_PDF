"""De qué carpeta o lote salió cada documento, y su inventario general.

Una corrida por carpeta local procesa cada PDF como un trabajo propio. Sin el
origen, el Archivo dibujaba una «carpeta» por PDF con el nombre del archivo
donde el operador esperaba el de la carpeta raíz.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from resolutions.adapters.ledger import InventoryLedger
from resolutions.api.jobs import JobRegistry

ORIGEN = {
    "id": "run1",
    "nombre": "UPD3859771",
    "tipo": "carpeta",
    "inventario": r"C:\DESTINO\ACTAS UPD3859771__inventario.xlsx",
}


def _informe(**extra) -> dict:
    return {
        "document": "1N°22-17 DE DICIEMBRE DE 2012.pdf",
        "page_count": 4,
        "inventory": {
            "source_document": "1N°22-17 DE DICIEMBRE DE 2012.pdf",
            "items": [
                {
                    "code": "022",
                    "file_name": "acta.xlsx",
                    "page_count": 4,
                    "first_page": 1,
                    "last_page": 4,
                    "type": "ACTA DE CONSEJO",
                }
            ],
        },
        **extra,
    }


class TestElInventarioRecuerdaElOrigen:
    def test_cada_fila_lleva_la_carpeta_raiz(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")

        ledger.record("j1", _informe(origen=ORIGEN))

        fila = ledger.rows()[0]
        assert fila["origen_id"] == "run1"
        assert fila["origen"] == "UPD3859771"
        assert fila["origen_tipo"] == "carpeta"
        assert fila["origen_inventario"].endswith("ACTAS UPD3859771__inventario.xlsx")

    def test_el_documento_lo_expone_para_reunirlos_en_una_tarjeta(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")

        ledger.record("j1", _informe(origen=ORIGEN))

        documento = ledger.documents()[0]
        assert documento["source_document"] == "1N°22-17 DE DICIEMBRE DE 2012.pdf"
        assert (documento["origen_id"], documento["origen"]) == ("run1", "UPD3859771")

    def test_lo_cargado_suelto_no_llena_el_archivo_de_nulos(self, tmp_path):
        ledger = InventoryLedger(tmp_path / "inventory.jsonl")

        ledger.record("j1", _informe())

        assert "origen_id" not in ledger.rows()[0]
        assert ledger.documents()[0]["origen_id"] is None


class TestElTrabajoLlevaSuOrigen:
    def test_viaja_en_lo_que_ve_la_pantalla(self):
        job = JobRegistry().create(filename="a.pdf", source=Path("a.pdf"), origen=ORIGEN)

        assert job.as_dict()["origen"]["nombre"] == "UPD3859771"

    def test_suelto_no_tiene(self):
        job = JobRegistry().create(filename="a.pdf", source=Path("a.pdf"))

        assert job.as_dict()["origen"] is None

    def test_la_corrida_por_carpeta_nombra_la_carpeta_raiz_y_no_el_pdf(self, tmp_path):
        import asyncio

        from resolutions.api.folders import FolderRun, FolderRunner
        from resolutions.api.settings import Settings

        fuente = tmp_path / "UPD3859771"
        fuente.mkdir()
        pdf = fuente / "1N°22-17 DE DICIEMBRE DE 2012.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        destino = tmp_path / "DESTINO"
        destino.mkdir()

        registry = JobRegistry()
        vistos = []

        async def run_job(job):
            vistos.append(job)
            job.state = "failed"

        settings = replace(Settings(), output_dir=tmp_path / "outputs")
        runner = FolderRunner(registry, settings, run_job=run_job)
        run = FolderRun(id="r1", source=fuente, destination=destino)

        asyncio.run(runner._consume(run, pdf))

        origen = vistos[0].origen
        assert vistos[0].filename == "1N°22-17 DE DICIEMBRE DE 2012.pdf"
        assert (origen["id"], origen["nombre"], origen["tipo"]) == ("r1", "UPD3859771", "carpeta")
        # El inventario general es el FUID de toda la corrida, en la raíz del
        # destino, con las filas de todas las habilidades (2026-10-29); antes
        # era el Excel de las actas de consejo de la carpeta raíz.
        assert origen["inventario"] == str(destino / "UPD3859771" / "00.FUID GENERAL.xlsx")


class TestElInventarioGeneralDesdeElArchivo:
    def test_con_la_corrida_ya_olvidada_se_baja_por_la_ruta_anotada(self, client, tmp_path):
        from resolutions.api import main

        hoja = tmp_path / "ACTAS UPD3859771__inventario.xlsx"
        hoja.write_bytes(b"planilla")
        main.contexto.ledger.record("j1", _informe(origen={**ORIGEN, "inventario": str(hoja)}))

        respuesta = client.get("/api/origenes/run1/inventario.xlsx")

        assert respuesta.status_code == 200
        assert respuesta.content == b"planilla"

    def test_si_la_corrida_sigue_en_memoria_manda_la_suya(self, client, tmp_path):
        from resolutions.api import main
        from resolutions.api.folders import FolderRun, RunState

        hoja = tmp_path / "ACTAS UPD3859771 (2)__inventario.xlsx"
        hoja.write_bytes(b"la que se escribio al estar abierta la otra")
        run = FolderRun(id="run1", source=tmp_path, destination=tmp_path, state=RunState.DONE)
        run.inventario = str(hoja)
        main.contexto.folders._runs[run.id] = run

        respuesta = client.get("/api/origenes/run1/inventario.xlsx")

        assert respuesta.content == b"la que se escribio al estar abierta la otra"

    def test_si_se_movio_del_destino_dice_donde_se_esperaba(self, client, tmp_path):
        from resolutions.api import main

        perdida = tmp_path / "no-esta.xlsx"
        main.contexto.ledger.record("j1", _informe(origen={**ORIGEN, "inventario": str(perdida)}))

        respuesta = client.get("/api/origenes/run1/inventario.xlsx")

        assert respuesta.status_code == 404
        assert str(perdida) in respuesta.json()["detail"]

    def test_un_origen_desconocido(self, client):
        assert client.get("/api/origenes/nada/inventario.xlsx").status_code == 404

    def test_el_buscador_encuentra_los_pdf_por_el_nombre_de_la_carpeta(self, client):
        from resolutions.api import main

        main.contexto.ledger.record("j1", _informe(origen=ORIGEN))
        main.contexto.ledger.record("j2", _informe())

        documentos = client.get("/api/documents", params={"q": "UPD3859771"}).json()["documents"]

        assert [d["job_id"] for d in documentos] == ["j1"]


def test_un_lote_cargado_lleva_su_nombre(client):
    lote = client.post("/api/batches", json={"name": "Lote de prueba"}).json()

    respuesta = client.post(
        f"/api/jobs?batch_id={lote['id']}",
        files={"file": ("a.pdf", b"%PDF-1.4 not really a pdf", "application/pdf")},
    )

    assert respuesta.status_code == 202, respuesta.text
    from resolutions.api import main

    job = main.contexto.registry.get(respuesta.json()["id"])
    assert job.origen == {"id": lote["id"], "nombre": "Lote de prueba", "tipo": "lote"}
