"""El inventario de un documento que ya se procesó, y la acción de una carpeta.

Dos huecos que dejaban a un documento sin inventario sin que nadie hubiera hecho
nada mal:

  * una carpeta local sólo sabía dividir, así que un libro de diplomas tomado de
    una carpeta no tenía forma de dejar su FUID;
  * y un documento partido no podía inventariarse después, porque el FUID sólo se
    escribía si la acción se había acertado antes de empezar.

Lo que se prueba aquí es que la segunda salida usa exactamente el mismo camino
que la acción «Solo inventariar» de la pantalla de carga -- el mismo worker, y la
plantilla elegida por el tipo de documento que se reconozca al leerlo -- y que
cuando no se puede, se dice por qué en vez de dejar el botón girando.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resolutions.api.folders import FolderRun
from resolutions.application.task import TaskKind

pytest.importorskip("httpx")

FUID_SUFFIX = "__FUID.xlsx"


class TestLaAccionDeUnaCarpeta:
    """Una carpeta puede pedir lo mismo que una subida."""

    def test_por_omision_una_carpeta_divide(self):
        # No cambia lo que el sistema ya hacía para quien no elija nada.
        assert FolderRun(id="r", source=Path("o"), destination=Path("d")).task == "split"

    def test_la_accion_elegida_viaja_con_la_corrida(self):
        run = FolderRun(
            id="r",
            source=Path("o"),
            destination=Path("d"),
            task=str(TaskKind.INVENTORY),
        )
        assert run.as_dict()["task"] == "inventory"

    def test_la_corrida_la_declara_en_su_estado(self):
        run = FolderRun(id="r", source=Path("o"), destination=Path("d"))
        assert "task" in run.as_dict()

    def test_una_accion_desconocida_no_se_adivina(self, client):
        respuesta = client.post(
            "/api/folder-runs",
            json={"source": ".", "destination": ".", "task": "haz-lo-que-quieras"},
        )
        assert respuesta.status_code == 422
        assert "acción desconocida" in respuesta.json()["detail"]


class TestLevantarElFuidDespues:
    def test_un_documento_sin_fuid_lo_dice(self, client):
        estado = client.get("/api/jobs/inexistente/fuid").json()
        assert estado["ready"] is False
        assert estado["name"] is None

    def test_un_fuid_ya_escrito_se_reconoce_sin_volver_a_leer_nada(self, client, tmp_path):
        # Quien pidió «Solo inventariar» al cargar ya tiene su planilla. Volver a
        # leer el documento para producir exactamente lo mismo sería tirar
        # minutos de OCR por nada.
        from resolutions.api import main

        carpeta = main.settings.output_dir / "job1"
        carpeta.mkdir(parents=True)
        (carpeta / f"libro{FUID_SUFFIX}").write_bytes(b"planilla")

        respuesta = client.post("/api/jobs/job1/fuid")

        assert respuesta.status_code == 202
        assert respuesta.json()["ready"] is True
        assert respuesta.json()["name"] == f"libro{FUID_SUFFIX}"

    def test_el_estado_lo_confirma(self, client):
        from resolutions.api import main

        carpeta = main.settings.output_dir / "job1"
        carpeta.mkdir(parents=True)
        (carpeta / f"libro{FUID_SUFFIX}").write_bytes(b"planilla")

        estado = client.get("/api/jobs/job1/fuid").json()

        assert estado["ready"] is True
        assert estado["working"] is False
        assert estado["error"] is None

    def test_sin_el_documento_de_origen_se_explica_en_vez_de_intentarlo(self, client):
        # Una subida se borra al terminar su trabajo, y un original de carpeta
        # puede haberse apartado o borrado. Sin el papel no hay nada que leer, y
        # decirlo es mejor que dejar el botón girando para siempre.
        respuesta = client.post("/api/jobs/desconocido/fuid")

        assert respuesta.status_code == 409
        assert "ya no está disponible" in respuesta.json()["detail"]

    def test_el_documento_se_descarga_por_donde_siempre(self, client):
        # El botón nuevo no inventa un sitio de descarga: usa el endpoint que ya
        # servía el FUID de un documento inventariado.
        from resolutions.api import main

        carpeta = main.settings.output_dir / "job1"
        carpeta.mkdir(parents=True)
        (carpeta / f"libro{FUID_SUFFIX}").write_bytes(b"planilla")

        respuesta = client.get("/api/jobs/job1/fuid.xlsx")

        assert respuesta.status_code == 200
        assert respuesta.content == b"planilla"

    def test_el_servicio_declara_lo_que_sabe_hacer(self, client):
        # La pantalla compara esto con lo que fue construida para pedir, y así un
        # servicio sin reiniciar se reconoce como viejo y no como roto.
        salud = client.get("/api/health").json()
        assert salud["api_revision"] >= 14
        assert "job-fuid-make" in salud["features"]
        assert "folder-task" in salud["features"]
