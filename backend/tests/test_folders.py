"""Consuming a local folder and delivering into another one.

No upload: the service reads and writes the machine it runs on. One document at
a time, on purpose -- a watched folder is a background service, and taking one
at a time is what makes "which file is it on" a question with one answer.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from resolutions.api.folders import (
    CONSUMED_DIR,
    DELIVERY_WINDOW,
    QUEUE_PREVIEW,
    Delivery,
    FolderError,
    FolderRun,
    FolderRunner,
    RunState,
    SourceDisposition,
    unique_path,
    validate_folders,
)
from resolutions.api.jobs import JobRegistry
from resolutions.api.settings import Settings


@pytest.fixture
def workspace(tmp_path):
    settings = replace(
        Settings(),
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "outputs",
        ledger_path=tmp_path / "inventory.jsonl",
    )
    settings.ensure_directories()
    (tmp_path / "origen").mkdir()
    (tmp_path / "destino").mkdir()
    return settings


def put(directory: Path, *names: str) -> None:
    for name in names:
        (directory / name).write_bytes(b"%PDF-1.4 fake")


def runner(workspace, registry, *, produces=("00086__acta.pdf",), fail=()):
    """A runner whose "processing" writes the outputs a real job would write."""
    processed: list[str] = []

    async def run_job(job):
        processed.append(job.filename)
        if job.filename in fail:
            registry.mark_failed(job, "boom")
            return
        directory = workspace.output_dir / job.id
        directory.mkdir(parents=True, exist_ok=True)
        for name in produces:
            (directory / name).write_bytes(b"%PDF-1.4 out")
        registry.mark_done(job, {"groups": [{"code": "00086"}], "review_queue": []})

    engine = FolderRunner(registry, workspace, run_job, watch_interval=0.01)
    return engine, processed


def drain(engine, source, destination, **kwargs):
    """Start a run and wait for it to settle."""

    async def go():
        run = engine.start(str(source), str(destination), **kwargs)
        for _ in range(400):
            if not run.active:
                return run
            await asyncio.sleep(0.01)
        return run

    return asyncio.run(go())


class TestValidation:
    def test_a_missing_source_is_refused_before_anything_is_touched(self, tmp_path):
        with pytest.raises(FolderError, match="origen no existe"):
            validate_folders(str(tmp_path / "nope"), str(tmp_path / "out"))

    def test_the_destination_is_created_if_it_does_not_exist(self, tmp_path):
        source = tmp_path / "in"
        source.mkdir()
        _, target = validate_folders(str(source), str(tmp_path / "made"))
        assert target.is_dir()

    def test_the_destination_may_not_be_the_source(self, tmp_path):
        source = tmp_path / "in"
        source.mkdir()
        with pytest.raises(FolderError, match="misma carpeta"):
            validate_folders(str(source), str(source))

    def test_the_destination_may_not_sit_inside_the_source(self, tmp_path):
        # Otherwise every delivered resolution is a new PDF in the folder being
        # watched, and the run feeds on its own output forever.
        source = tmp_path / "in"
        source.mkdir()
        with pytest.raises(FolderError, match="dentro del origen"):
            validate_folders(str(source), str(source / "salida"))

    def test_a_file_is_not_a_folder(self, tmp_path):
        document = tmp_path / "a.pdf"
        document.write_bytes(b"x")
        with pytest.raises(FolderError, match="no es una carpeta"):
            validate_folders(str(document), str(tmp_path / "out"))


class TestConsuming:
    def test_every_pdf_in_the_folder_is_processed(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf", "b.pdf", "c.pdf")
        engine, processed = runner(workspace, JobRegistry())

        run = drain(engine, tmp_path / "origen", tmp_path / "destino")

        assert sorted(processed) == ["a.pdf", "b.pdf", "c.pdf"]
        assert run.processed == 3
        assert run.state is RunState.DONE

    def test_files_are_taken_in_name_order_one_at_a_time(self, workspace, tmp_path):
        put(tmp_path / "origen", "c.pdf", "a.pdf", "b.pdf")
        engine, processed = runner(workspace, JobRegistry())
        drain(engine, tmp_path / "origen", tmp_path / "destino")
        assert processed == ["a.pdf", "b.pdf", "c.pdf"]

    def test_anything_that_is_not_a_pdf_is_left_alone(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf")
        (tmp_path / "origen" / "notas.txt").write_text("hola")
        engine, processed = runner(workspace, JobRegistry())
        drain(engine, tmp_path / "origen", tmp_path / "destino")
        assert processed == ["a.pdf"]
        assert (tmp_path / "origen" / "notas.txt").exists()

    def test_an_empty_folder_finishes_without_complaint(self, workspace, tmp_path):
        engine, processed = runner(workspace, JobRegistry())
        run = drain(engine, tmp_path / "origen", tmp_path / "destino")
        assert processed == []
        assert run.state is RunState.DONE

    def test_a_document_that_fails_does_not_stop_the_folder(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf", "roto.pdf", "z.pdf")
        engine, processed = runner(workspace, JobRegistry(), fail=("roto.pdf",))

        run = drain(engine, tmp_path / "origen", tmp_path / "destino")

        assert sorted(processed) == ["a.pdf", "roto.pdf", "z.pdf"]
        assert run.processed == 2
        assert run.failed == 1

    def test_the_same_folder_cannot_be_drained_twice_at_once(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf")

        async def go():
            engine, _ = runner(workspace, JobRegistry())
            engine.start(str(tmp_path / "origen"), str(tmp_path / "destino"), watch=True)
            with pytest.raises(FolderError, match="ya se está procesando"):
                engine.start(str(tmp_path / "origen"), str(tmp_path / "destino"))

        asyncio.run(go())


class TestDelivering:
    def test_the_generated_pdfs_land_in_the_destination(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf")
        engine, _ = runner(
            workspace, JobRegistry(), produces=("00086__acta.pdf", "00072__otra.pdf")
        )

        run = drain(engine, tmp_path / "origen", tmp_path / "destino")

        # Bajo la carpeta del documento del que salieron: en una caja de archivo
        # hay doscientos PDF y todos producen los mismos nombres de salida.
        delivered = sorted(path.name for path in (tmp_path / "destino").rglob("*.pdf"))
        assert delivered == ["00072__otra.pdf", "00086__acta.pdf"]
        assert (tmp_path / "destino" / "a" / "00086__acta.pdf").is_file()
        assert run.delivered == 2

    def test_each_delivery_is_reported_with_the_document_it_came_from(
        self, workspace, tmp_path
    ):
        put(tmp_path / "origen", "expediente.pdf")
        engine, _ = runner(workspace, JobRegistry())

        run = drain(engine, tmp_path / "origen", tmp_path / "destino")

        assert run.deliveries[0].file_name == "00086__acta.pdf"
        assert run.deliveries[0].source_document == "expediente.pdf"

    def test_two_documents_producing_the_same_number_do_not_overwrite(
        self, workspace, tmp_path
    ):
        # The same resolution number can legitimately come out of two documents,
        # and losing one to the other is losing a file nobody asked to lose.
        # Ahora ni siquiera hace falta renombrar: cada documento tiene su carpeta.
        put(tmp_path / "origen", "a.pdf", "b.pdf")
        engine, _ = runner(workspace, JobRegistry())

        drain(engine, tmp_path / "origen", tmp_path / "destino")

        assert (tmp_path / "destino" / "a" / "00086__acta.pdf").is_file()
        assert (tmp_path / "destino" / "b" / "00086__acta.pdf").is_file()
        assert not list((tmp_path / "destino").rglob("*(2)*"))

    def test_quarantine_travels_under_the_name_of_its_document(self, workspace, tmp_path):
        put(tmp_path / "origen", "expediente.pdf")
        engine, _ = runner(workspace, JobRegistry(), produces=("_quarantine.pdf",))

        drain(engine, tmp_path / "origen", tmp_path / "destino")

        assert (tmp_path / "destino" / "expediente" / "expediente_quarantine.pdf").is_file()

    def test_a_failed_document_delivers_nothing(self, workspace, tmp_path):
        put(tmp_path / "origen", "roto.pdf")
        engine, _ = runner(workspace, JobRegistry(), fail=("roto.pdf",))

        drain(engine, tmp_path / "origen", tmp_path / "destino")

        assert list((tmp_path / "destino").glob("*.pdf")) == []


class TestSourceDisposition:
    def test_by_default_the_original_is_left_where_it_was(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf")
        engine, _ = runner(workspace, JobRegistry())
        drain(engine, tmp_path / "origen", tmp_path / "destino")
        assert (tmp_path / "origen" / "a.pdf").is_file()

    def test_it_can_be_moved_aside_once_it_has_been_consumed(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf")
        engine, _ = runner(workspace, JobRegistry())

        drain(
            engine,
            tmp_path / "origen",
            tmp_path / "destino",
            disposition=SourceDisposition.MOVE,
        )

        assert not (tmp_path / "origen" / "a.pdf").exists()
        assert (tmp_path / "origen" / CONSUMED_DIR / "a.pdf").is_file()

    def test_it_can_be_deleted(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf")
        engine, _ = runner(workspace, JobRegistry())
        drain(
            engine,
            tmp_path / "origen",
            tmp_path / "destino",
            disposition=SourceDisposition.DELETE,
        )
        assert not (tmp_path / "origen" / "a.pdf").exists()

    def test_a_document_that_failed_keeps_its_original(self, workspace, tmp_path):
        # Moving it aside would hide the one file the operator has to look at.
        put(tmp_path / "origen", "roto.pdf")
        engine, _ = runner(workspace, JobRegistry(), fail=("roto.pdf",))
        drain(
            engine,
            tmp_path / "origen",
            tmp_path / "destino",
            disposition=SourceDisposition.DELETE,
        )
        assert (tmp_path / "origen" / "roto.pdf").is_file()

    def test_the_originals_that_were_left_are_not_consumed_twice(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf")
        registry = JobRegistry()
        engine, processed = runner(workspace, registry)

        async def go():
            run = engine.start(
                str(tmp_path / "origen"), str(tmp_path / "destino"), watch=True
            )
            for _ in range(60):
                await asyncio.sleep(0.01)
                if run.processed >= 1:
                    break
            await asyncio.sleep(0.15)
            engine.stop(run.id)
            return run

        asyncio.run(go())
        assert processed == ["a.pdf"]


class TestWatching:
    def test_a_watching_run_picks_up_a_file_that_arrives_later(self, workspace, tmp_path):
        registry = JobRegistry()
        engine, processed = runner(workspace, registry)

        async def go():
            run = engine.start(
                str(tmp_path / "origen"), str(tmp_path / "destino"), watch=True
            )
            await asyncio.sleep(0.05)
            assert run.state is RunState.WATCHING
            put(tmp_path / "origen", "tarde.pdf")
            for _ in range(200):
                await asyncio.sleep(0.01)
                if processed:
                    break
            engine.stop(run.id)
            return run

        run = asyncio.run(go())
        assert processed == ["tarde.pdf"]
        assert run.state is RunState.STOPPED

    def test_stopping_a_run_that_already_ended_reports_nothing_to_stop(
        self, workspace, tmp_path
    ):
        engine, _ = runner(workspace, JobRegistry())
        run = drain(engine, tmp_path / "origen", tmp_path / "destino")
        assert engine.stop(run.id) is None


class TestUniqueNames:
    def test_a_free_name_is_returned_untouched(self, tmp_path):
        assert unique_path(tmp_path, "a.pdf").name == "a.pdf"

    def test_a_taken_name_is_numbered(self, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"x")
        assert unique_path(tmp_path, "a.pdf").name == "a (2).pdf"

    def test_numbering_keeps_climbing(self, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"x")
        (tmp_path / "a (2).pdf").write_bytes(b"x")
        assert unique_path(tmp_path, "a.pdf").name == "a (3).pdf"


class TestFolderEndpoints:
    def test_a_run_can_be_started_and_read_back(self, client, tmp_path):
        source = tmp_path / "entrada"
        source.mkdir()
        created = client.post(
            "/api/folder-runs",
            json={"source": str(source), "destination": str(tmp_path / "salida")},
        )
        assert created.status_code == 201
        run_id = created.json()["id"]
        assert client.get(f"/api/folder-runs/{run_id}").json()["source"] == str(source.resolve())

    def test_bad_folders_are_refused_with_an_explanation(self, client, tmp_path):
        response = client.post(
            "/api/folder-runs",
            json={"source": str(tmp_path / "nope"), "destination": str(tmp_path / "out")},
        )
        assert response.status_code == 422
        assert "no existe" in response.json()["detail"]

    def test_an_unknown_disposition_is_refused(self, client, tmp_path):
        source = tmp_path / "entrada"
        source.mkdir()
        response = client.post(
            "/api/folder-runs",
            json={
                "source": str(source),
                "destination": str(tmp_path / "salida"),
                "disposition": "incinerar",
            },
        )
        assert response.status_code == 422

    def test_stopping_an_unknown_run_is_not_found(self, client):
        assert client.post("/api/folder-runs/ghost/stop").status_code == 404


class TestRunReporting:
    """A settled run has to be able to say what it did, document by document."""

    def test_the_run_remembers_every_document_it_created(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf", "b.pdf")
        registry = JobRegistry()
        engine, _ = runner(workspace, registry)

        run = drain(engine, tmp_path / "origen", tmp_path / "destino")

        assert len(run.job_ids) == 2
        assert [registry.get(job_id).filename for job_id in run.job_ids] == ["a.pdf", "b.pdf"]

    def test_the_ids_travel_in_the_payload(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf")
        engine, _ = runner(workspace, JobRegistry())
        run = drain(engine, tmp_path / "origen", tmp_path / "destino")
        assert run.as_dict()["job_ids"] == run.job_ids

    def test_the_net_weight_of_what_it_consumed_is_reported(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf", "b.pdf")
        engine, _ = runner(workspace, JobRegistry())
        run = drain(engine, tmp_path / "origen", tmp_path / "destino")
        assert run.bytes_total == len(b"%PDF-1.4 fake") * 2


class TestPastedPaths:
    """A path arrives the way a person supplies one, not the way code wants it.

    Windows Explorer's "Copy as path" -- the normal way anybody gets a path onto
    the clipboard -- wraps it in double quotes. Pasted straight in, the quotes
    became part of the folder name and the operator was told the folder they
    were looking at did not exist.
    """

    def test_a_path_copied_from_explorer_works(self, tmp_path):
        from resolutions.api.folders import clean_path

        source = tmp_path / "entrada"
        source.mkdir()
        quoted = f'"{source}"'
        assert clean_path(quoted) == str(source)
        origin, _ = validate_folders(quoted, str(tmp_path / "salida"))
        assert origin == source.resolve()

    def test_surrounding_whitespace_comes_off(self, tmp_path):
        source = tmp_path / "entrada"
        source.mkdir()
        origin, _ = validate_folders(f"   {source}  ", str(tmp_path / "salida"))
        assert origin == source.resolve()

    def test_the_destination_is_cleaned_the_same_way(self, tmp_path):
        source = tmp_path / "entrada"
        source.mkdir()
        target = tmp_path / "salida"
        _, cleaned = validate_folders(str(source), f'"{target}"')
        assert cleaned == target.resolve()

    def test_curly_quotes_from_a_chat_window_come_off_too(self, tmp_path):
        from resolutions.api.folders import clean_path

        source = tmp_path / "entrada"
        source.mkdir()
        assert clean_path(f"\u201c{source}\u201d") == str(source)

    def test_single_quotes_come_off(self, tmp_path):
        from resolutions.api.folders import clean_path

        assert clean_path(r"'C:\raiz'") == r"C:\raiz"

    def test_a_bare_path_is_left_exactly_as_it_was(self, tmp_path):
        from resolutions.api.folders import clean_path

        assert clean_path(r"C:\Users\ana\PRUEBA") == r"C:\Users\ana\PRUEBA"

    def test_nothing_is_still_nothing(self):
        from resolutions.api.folders import clean_path

        assert clean_path('   ""   ') == ""
        assert clean_path(None) == ""

    def test_an_empty_field_says_what_is_missing(self, tmp_path):
        with pytest.raises(FolderError, match="Indique la carpeta"):
            validate_folders('""', str(tmp_path / "salida"))

    def test_a_quoted_path_that_really_is_missing_still_fails(self, tmp_path):
        # Cleaning must not turn a genuine mistake into a silent success.
        with pytest.raises(FolderError, match="no existe"):
            validate_folders(f'"{tmp_path / "fantasma"}"', str(tmp_path / "salida"))


class TestPastedPathsThroughTheApi:
    def test_a_quoted_path_is_accepted_by_the_endpoint(self, client, tmp_path):
        source = tmp_path / "entrada"
        source.mkdir()
        response = client.post(
            "/api/folder-runs",
            json={"source": f'"{source}"', "destination": f'"{tmp_path / "salida"}"'},
        )
        assert response.status_code == 201
        assert response.json()["source"] == str(source.resolve())


class TestRunTotalsSurviveTheJobs:
    """A run has to be able to report itself after its jobs are gone.

    The completion report is read long after the registry has been cleared. If
    the run cannot answer from its own totals, the report falls back to zeros --
    and a report that states something untrue is worse than no report at all.
    """

    def test_the_run_totals_its_own_pages(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf", "b.pdf")
        registry = JobRegistry()

        async def run_job(job):
            registry.apply_progress({"job_id": job.id, "stage": "opened", "page_count": 7})
            directory = workspace.output_dir / job.id
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "00086__acta.pdf").write_bytes(b"%PDF")
            registry.mark_done(job, {"groups": [{"code": "00086"}], "review_queue": []})

        engine = FolderRunner(registry, workspace, run_job, watch_interval=0.01)
        run = drain(engine, tmp_path / "origen", tmp_path / "destino")

        assert run.pages_total == 14
        assert run.as_dict()["pages_total"] == 14

    def test_the_totals_travel_in_the_payload(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf")
        engine, _ = runner(workspace, JobRegistry())
        payload = drain(engine, tmp_path / "origen", tmp_path / "destino").as_dict()
        for field in ("processed", "failed", "delivered", "resolutions", "bytes_total", "pages_total"):
            assert field in payload


class TestFolderBrowser:
    """El explorador que alimenta el selector de carpetas.

    El navegador no puede entregar una ruta absoluta -- ni el selector de
    carpetas ni `webkitdirectory` la exponen, por seguridad. El servicio corre
    en la misma máquina que las carpetas, así que el explorador lo pone él.
    """

    def test_sin_ruta_ofrece_puntos_de_partida(self, client):
        payload = client.get("/api/folders").json()
        assert payload["path"] is None
        assert payload["drives"]
        assert all("path" in drive and "name" in drive for drive in payload["drives"])

    def test_lista_las_subcarpetas_de_una_ruta(self, client, tmp_path):
        # Una raíz propia: el servicio crea sus directorios dentro de tmp_path.
        raiz = tmp_path / "arbol"
        (raiz / "entrada").mkdir(parents=True)
        (raiz / "salida").mkdir()
        (raiz / "un-archivo.pdf").write_bytes(b"%PDF")

        payload = client.get(f"/api/folders?path={raiz}").json()

        assert [folder["name"] for folder in payload["folders"]] == ["entrada", "salida"]

    def test_no_lista_archivos(self, client, tmp_path):
        # Es un selector de carpetas. Un archivo ahí sólo sería ruido, y el
        # endpoint no debe insinuar que puede leer contenidos.
        raiz = tmp_path / "arbol"
        raiz.mkdir()
        (raiz / "documento.pdf").write_bytes(b"%PDF")
        payload = client.get(f"/api/folders?path={raiz}").json()
        assert payload["folders"] == []

    def test_omite_las_ocultas_y_las_del_sistema(self, client, tmp_path):
        raiz = tmp_path / "arbol"
        (raiz / ".git").mkdir(parents=True)
        (raiz / "$RECYCLE.BIN").mkdir()
        (raiz / "normal").mkdir()
        payload = client.get(f"/api/folders?path={raiz}").json()
        assert [folder["name"] for folder in payload["folders"]] == ["normal"]

    def test_devuelve_la_carpeta_padre_para_poder_subir(self, client, tmp_path):
        hija = tmp_path / "entrada"
        hija.mkdir()
        payload = client.get(f"/api/folders?path={hija}").json()
        assert payload["parent"] == str(tmp_path)

    def test_cada_carpeta_trae_su_ruta_completa(self, client, tmp_path):
        (tmp_path / "entrada").mkdir()
        folder = client.get(f"/api/folders?path={tmp_path}").json()["folders"][0]
        assert folder["path"] == str(tmp_path / "entrada")

    def test_una_ruta_entrecomillada_tambien_funciona(self, client, tmp_path):
        # La misma tolerancia que el resto: la ruta pegada trae comillas.
        (tmp_path / "entrada").mkdir()
        response = client.get('/api/folders', params={"path": f'"{tmp_path}"'})
        assert response.status_code == 200

    def test_una_ruta_inexistente_se_dice_en_castellano(self, client, tmp_path):
        response = client.get(f"/api/folders?path={tmp_path / 'fantasma'}")
        assert response.status_code == 404
        assert "no existe" in response.json()["detail"]

    def test_un_archivo_no_es_una_carpeta(self, client, tmp_path):
        documento = tmp_path / "a.pdf"
        documento.write_bytes(b"%PDF")
        assert client.get(f"/api/folders?path={documento}").status_code in (404, 422)


class TestLaAccionDeLaCarpeta:
    """Una carpeta puede pedir lo mismo que una subida.

    Hasta ahora sólo sabía dividir, así que un libro de diplomas tomado de una
    carpeta no tenía forma de dejar su inventario: había que volver a subirlo a
    mano, uno por uno, con la acción correcta.
    """

    def test_por_omision_sigue_dividiendo(self, workspace, tmp_path):
        registry = JobRegistry()
        engine, _ = runner(workspace, registry)
        put(tmp_path / "origen", "expediente.pdf")

        run = drain(engine, tmp_path / "origen", tmp_path / "destino")

        assert run.task == "split"
        assert [job.task for job in registry.list()] == ["split"]

    def test_cada_documento_hereda_la_accion_de_su_carpeta(self, workspace, tmp_path):
        # Es lo que hace que el FUID exista sin que nadie tenga que pedirlo dos
        # veces: la carpeta se pidió inventariando, y sus documentos también.
        registry = JobRegistry()
        engine, _ = runner(workspace, registry)
        put(tmp_path / "origen", "libro.pdf", "otro.pdf")

        run = drain(engine, tmp_path / "origen", tmp_path / "destino", task="both")

        assert run.task == "both"
        assert {job.task for job in registry.list()} == {"both"}

    def test_la_accion_viaja_en_el_estado_que_ve_la_pantalla(self, workspace, tmp_path):
        registry = JobRegistry()
        engine, _ = runner(workspace, registry)
        put(tmp_path / "origen", "expediente.pdf")

        run = drain(engine, tmp_path / "origen", tmp_path / "destino", task="inventory")

        assert run.as_dict()["task"] == "inventory"


class TestQuitarUnaCarpetaDeLaPantalla:
    """Una carpeta terminada tiene que poder irse de la pantalla.

    Sin esto se acumulaban para siempre. Al cabo de una mañana la pantalla
    principal enseñaba media docena de tarjetas de carpetas ya cerradas, con sus
    contadores y sus colas, mezcladas con la que sí estaba trabajando, y no
    había forma de distinguir de un vistazo cuál seguía viva.

    Quitar no es parar. Una carpeta en marcha no se olvida por descuido: hay que
    detenerla primero, que es una decisión distinta y del operador.
    """

    def test_a_finished_run_can_be_forgotten(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf")
        engine, _ = runner(workspace, JobRegistry())
        run = drain(engine, tmp_path / "origen", tmp_path / "destino")

        assert engine.forget(run.id) is not None
        assert engine.get(run.id) is None
        assert engine.list() == []

    def test_a_running_one_is_never_forgotten_by_accident(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf")
        engine, _ = runner(workspace, JobRegistry())

        async def go():
            run = engine.start(str(tmp_path / "origen"), str(tmp_path / "destino"), watch=True)
            for _ in range(400):
                if run.state is RunState.WATCHING:
                    break
                await asyncio.sleep(0.01)
            assert run.active
            # Vigilando es estar viva: quitarla dejaría el trabajo corriendo sin
            # nadie que informara de él.
            assert engine.forget(run.id) is None
            assert engine.get(run.id) is not None
            engine.stop(run.id)
            assert engine.forget(run.id) is not None

        asyncio.run(go())

    def test_forgetting_them_all_spares_the_ones_still_alive(self, workspace, tmp_path):
        put(tmp_path / "origen", "a.pdf")
        (tmp_path / "otra").mkdir()
        put(tmp_path / "otra", "b.pdf")
        engine, _ = runner(workspace, JobRegistry())

        async def go():
            terminada = engine.start(str(tmp_path / "origen"), str(tmp_path / "destino"))
            for _ in range(400):
                if not terminada.active:
                    break
                await asyncio.sleep(0.01)
            viva = engine.start(str(tmp_path / "otra"), str(tmp_path / "destino"), watch=True)
            for _ in range(400):
                if viva.state is RunState.WATCHING:
                    break
                await asyncio.sleep(0.01)

            quitadas = engine.forget_finished()
            assert [run.id for run in quitadas] == [terminada.id]
            assert [run.id for run in engine.list()] == [viva.id]
            engine.stop(viva.id)

        asyncio.run(go())

    def test_forgetting_something_that_is_not_there_says_so(self, workspace):
        engine, _ = runner(workspace, JobRegistry())
        assert engine.forget("no-existe") is None


class TestElEndpointQueVaciaLaPantalla:
    """La misma decisión, por HTTP: quitar lo terminado sin tocar lo vivo."""

    def crear(self, client, tmp_path):
        origen = tmp_path / "origen-http"
        destino = tmp_path / "destino-http"
        origen.mkdir()
        destino.mkdir()
        respuesta = client.post(
            "/api/folder-runs",
            json={"source": str(origen), "destination": str(destino)},
        )
        assert respuesta.status_code == 201, respuesta.text
        return respuesta.json()["id"]

    def esperar_a_que_termine(self, client, run_id):
        for _ in range(400):
            estado = client.get(f"/api/folder-runs/{run_id}").json()
            if estado["state"] in ("done", "stopped", "failed"):
                return estado
            import time

            time.sleep(0.01)
        raise AssertionError("la corrida no terminó")

    def test_it_forgets_one_finished_run(self, client, tmp_path):
        run_id = self.crear(client, tmp_path)
        self.esperar_a_que_termine(client, run_id)

        borrado = client.delete(f"/api/folder-runs/{run_id}")
        assert borrado.status_code == 200
        assert borrado.json() == {"removed": 1, "ids": [run_id]}
        assert client.get(f"/api/folder-runs/{run_id}").status_code == 404

    def test_forgetting_one_that_never_existed_is_a_404(self, client):
        assert client.delete("/api/folder-runs/no-existe").status_code == 404

    def test_it_clears_every_finished_run_at_once(self, client, tmp_path):
        primero = self.crear(client, tmp_path)
        self.esperar_a_que_termine(client, primero)

        vaciado = client.delete("/api/folder-runs")
        assert vaciado.status_code == 200
        assert vaciado.json()["removed"] == 1
        assert client.get("/api/folder-runs").json()["runs"] == []

    def test_the_screen_announces_that_it_can_do_this(self, client):
        # La pantalla compara sus capacidades con las del servicio para poder
        # decir "este servicio está viejo" en vez de dar un 405 por roto.
        salud = client.get("/api/health").json()
        assert salud["api_revision"] >= 15
        assert "folder-run-clear" in salud["features"]


def put_deep(root: Path, *relatives: str) -> None:
    """PDFs de mentira en las rutas dadas, creando las carpetas que hagan falta."""
    for relative in relatives:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.4 fake")


class TestElArbolEntero:
    """El archivo se entrega en cajas: una carpeta por expediente, cien en la ruta.

    Pedirle al operador que apunte cien veces, una por carpeta, es pedirle que
    haga a mano lo que la máquina sabe hacer.
    """

    def test_entra_en_las_subcarpetas(self, workspace, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        put_deep(
            origen,
            "EXPEDIENTE_045/documento.pdf",
            "EXPEDIENTE_046/documento.pdf",
            "EXPEDIENTE_047/anexos/documento.pdf",
            "suelto.pdf",
        )
        registry = JobRegistry()
        engine, processed = runner(workspace, registry)
        drain(engine, origen, destino)
        assert len(processed) == 4

    def test_cada_documento_se_nombra_por_su_ruta(self, workspace, tmp_path):
        """Con cien carpetas hay cien "documento.pdf": el nombre solo no distingue."""
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        put_deep(origen, "EXPEDIENTE_045/documento.pdf", "EXPEDIENTE_046/documento.pdf")
        registry = JobRegistry()
        engine, processed = runner(workspace, registry)
        drain(engine, origen, destino)
        assert sorted(processed) == [
            str(Path("EXPEDIENTE_045/documento.pdf")),
            str(Path("EXPEDIENTE_046/documento.pdf")),
        ]

    def test_lo_ya_procesado_no_se_vuelve_a_tomar(self, workspace, tmp_path):
        """`_procesados` a cualquier profundidad: bajo MOVE los originales van ahí."""
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        put_deep(
            origen,
            "EXPEDIENTE_045/documento.pdf",
            f"EXPEDIENTE_045/{CONSUMED_DIR}/viejo.pdf",
            f"{CONSUMED_DIR}/otro.pdf",
        )
        registry = JobRegistry()
        engine, processed = runner(workspace, registry)
        drain(engine, origen, destino)
        assert processed == [str(Path("EXPEDIENTE_045/documento.pdf"))]


class TestElDestinoRefleja:
    """Cien expedientes que producen el mismo nombre de archivo caben sin chocar.

    Aplanados serían noventa y nueve "(2)", "(3)", "(4)" y ni una pista de cuál
    vino de dónde: los archivos estarían y el trabajo no serviría.
    """

    def test_cada_carpeta_de_origen_tiene_la_suya_en_el_destino(self, workspace, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        put_deep(origen, "EXPEDIENTE_045/documento.pdf", "EXPEDIENTE_046/documento.pdf")
        registry = JobRegistry()
        engine, _ = runner(workspace, registry)
        drain(engine, origen, destino)
        assert (destino / "EXPEDIENTE_045" / "documento" / "00086__acta.pdf").exists()
        assert (destino / "EXPEDIENTE_046" / "documento" / "00086__acta.pdf").exists()

    def test_y_ninguno_se_renombra_con_un_numero(self, workspace, tmp_path):
        """Que es lo que pasaba aplanando: el mismo nombre cien veces."""
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        put_deep(origen, "A/documento.pdf", "B/documento.pdf", "C/documento.pdf")
        registry = JobRegistry()
        engine, _ = runner(workspace, registry)
        drain(engine, origen, destino)
        assert sorted(p.name for p in destino.rglob("*.pdf")) == ["00086__acta.pdf"] * 3

    def test_un_pdf_de_la_raiz_sigue_cayendo_en_la_raiz(self, workspace, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        put_deep(origen, "suelto.pdf")
        registry = JobRegistry()
        engine, _ = runner(workspace, registry)
        drain(engine, origen, destino)
        assert (destino / "suelto" / "00086__acta.pdf").exists()


class TestLosOriginalesApartadosConservanSuSitio:
    def test_se_mueven_bajo_procesados_con_su_estructura(self, workspace, tmp_path):
        """Aplanarlo mezclaría cien expedientes y haría irreversible el traslado."""
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        put_deep(origen, "EXPEDIENTE_045/documento.pdf", "EXPEDIENTE_046/documento.pdf")
        registry = JobRegistry()
        engine, _ = runner(workspace, registry)
        drain(engine, origen, destino, disposition=SourceDisposition.MOVE)
        assert (origen / CONSUMED_DIR / "EXPEDIENTE_045" / "documento.pdf").exists()
        assert (origen / CONSUMED_DIR / "EXPEDIENTE_046" / "documento.pdf").exists()
        assert not (origen / "EXPEDIENTE_045" / "documento.pdf").exists()


class TestLoQueViajaALaPantalla:
    """Una carpeta de archivo real trae catorce mil PDF y setenta y ocho gigas.

    Mandar la cola entera en cada aviso son 423 KB por documento consumido -- casi
    seis gigas de tráfico en la corrida -- para que la vista enseñe cuarenta
    nombres y tire el resto.
    """

    @staticmethod
    def corrida(tmp_path) -> FolderRun:
        return FolderRun(id="r1", source=tmp_path / "origen", destination=tmp_path / "destino")

    def test_la_cola_viaja_acotada(self, tmp_path):
        run = self.corrida(tmp_path)
        run.queue = [f"CAJA_{i:05d}/documento.pdf" for i in range(QUEUE_PREVIEW + 25)]
        assert len(run.as_dict()["queue"]) == QUEUE_PREVIEW

    def test_pero_el_total_viaja_entero(self, tmp_path):
        """Es lo único que la vista necesita de los que no enseña."""
        run = self.corrida(tmp_path)
        run.queue = ["x.pdf"] * (QUEUE_PREVIEW + 25)
        assert run.as_dict()["queued"] == QUEUE_PREVIEW + 25

    def test_una_cola_corta_viaja_entera(self, tmp_path):
        run = self.corrida(tmp_path)
        run.queue = ["a.pdf", "b.pdf"]
        publicado = run.as_dict()
        assert publicado["queue"] == ["a.pdf", "b.pdf"]
        assert publicado["queued"] == 2

    def test_las_entregas_ya_estaban_acotadas(self, tmp_path):
        """`record` recorta su propia ventana y `delivered` lleva el total.

        Se comprueba aquí para que nadie vuelva a añadir un tope encima del que
        ya hay -- fue lo primero que se intentó, y sobraba.
        """
        run = self.corrida(tmp_path)
        for index in range(DELIVERY_WINDOW + 40):
            run.record(
                Delivery(file_name=f"{index}.pdf", source_document="x.pdf", destination="d")
            )
        publicado = run.as_dict()
        assert len(publicado["deliveries"]) == DELIVERY_WINDOW
        assert publicado["delivered"] == DELIVERY_WINDOW + 40
        # La vista lee de arriba abajo: lo último entregado es lo que interesa.
        assert publicado["deliveries"][0]["file_name"] == f"{DELIVERY_WINDOW + 39}.pdf"
