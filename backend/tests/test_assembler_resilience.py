"""The writer's behaviour on damaged PDFs.

A document that reaches assembly has already been read, grouped and balanced.
Losing it to one broken object would throw all of that away, so the writer
degrades in steps instead of failing: repair the source, fall back from block
copies to single pages, and finally report the pages that cannot be copied at
all rather than dropping them silently.

The failures here are injected at ``insert_pdf`` because that is exactly where
MuPDF raises ``code=4: source object number out of range`` on a real file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from resolutions.adapters.pymupdf_assembler import (  # noqa: E402
    REPAIRED_FILE,
    PyMuPDFAssembler,
    objeto_que_no_resuelve,
)
from resolutions.application.control import Cancelled  # noqa: E402
from resolutions.domain.grouping import GroupingResult, PageGroup  # noqa: E402
from resolutions.domain.resolution_code import ResolutionCode  # noqa: E402

GRAFT_ERROR = "code=4: source object number out of range"


@pytest.fixture
def source(tmp_path):
    document = pymupdf.open()
    for number in range(6):
        page = document.new_page()
        page.insert_text((72, 100), f"pagina {number + 1}")
    path = tmp_path / "expediente.pdf"
    document.save(path)
    document.close()
    return path


@pytest.fixture
def dangling(source, tmp_path):
    """Un PDF cuya página 4 remite a un objeto que no está en la tabla.

    Es la avería real del material de la Universidad, en pequeño: la tabla de
    referencias cruzadas se lee sin una queja y remite a un objeto que no
    existe. Vive a nivel de módulo porque la usan las dos clases que describen
    qué hace el escritor con ella.
    """
    document = pymupdf.open(source)
    document.xref_set_key(document[3].xref, "Resources", "9999 0 R")
    path = tmp_path / "colgante.pdf"
    document.save(path)
    document.close()
    with pymupdf.open(path) as check:
        assert not check.is_repaired, "el daño tiene que ser invisible al abrir"
    return path


def one_group(pages):
    return GroupingResult(
        groups=[PageGroup(code=ResolutionCode.parse("00086"), page_numbers=pages, title="Acta")]
    )


def break_insert(monkeypatch, fails):
    """Make ``insert_pdf`` raise whenever ``fails(from_page, to_page)`` says so."""
    original = pymupdf.Document.insert_pdf

    def flaky(self, docsrc, from_page=-1, to_page=-1, **kwargs):
        if fails(from_page, to_page):
            raise RuntimeError(GRAFT_ERROR)
        return original(self, docsrc, from_page=from_page, to_page=to_page, **kwargs)

    monkeypatch.setattr(pymupdf.Document, "insert_pdf", flaky)


class TestBlockFallback:
    def test_a_block_copy_that_fails_is_retried_page_by_page(self, source, tmp_path, monkeypatch):
        # A six-page run copies as one block; when that raises, every page still
        # has to arrive.
        break_insert(monkeypatch, lambda first, last: last > first)

        assembly = PyMuPDFAssembler().write(source, one_group([1, 2, 3, 4, 5, 6]), tmp_path / "out")

        assert assembly.unwritable_pages == {}
        assert len(assembly.outputs) == 1
        with pymupdf.open(assembly.outputs[0]) as written:
            assert written.page_count == 6

    def test_one_broken_page_does_not_cost_the_other_five(self, source, tmp_path, monkeypatch):
        # Page 3 is unreadable at any granularity.
        break_insert(monkeypatch, lambda first, last: first <= 2 <= last)

        assembly = PyMuPDFAssembler().write(source, one_group([1, 2, 3, 4, 5, 6]), tmp_path / "out")

        assert list(assembly.unwritable_pages) == [3]
        assert GRAFT_ERROR in assembly.unwritable_pages[3]
        with pymupdf.open(assembly.outputs[0]) as written:
            assert written.page_count == 5

    def test_a_group_whose_every_page_fails_writes_no_file(self, source, tmp_path, monkeypatch):
        # An empty PDF on disk would read as a resolution that legitimately has
        # no pages, which is worse than no file at all.
        break_insert(monkeypatch, lambda first, last: True)

        assembly = PyMuPDFAssembler().write(source, one_group([1, 2]), tmp_path / "out")

        assert assembly.outputs == []
        assert sorted(assembly.unwritable_pages) == [1, 2]
        assert not list((tmp_path / "out").glob("00086*.pdf"))

    def test_a_healthy_document_writes_without_any_fallback(self, source, tmp_path):
        assembly = PyMuPDFAssembler().write(source, one_group([1, 2, 3]), tmp_path / "out")
        assert assembly.unwritable_pages == {}
        with pymupdf.open(assembly.outputs[0]) as written:
            assert written.page_count == 3


def break_save(monkeypatch, times=1):
    """Make the first ``times`` saves *of an output file* raise, as a lazy graft does.

    Dos cosas quedan fuera a propósito. ``tobytes`` pasa por ``save`` con un
    búfer en vez de una ruta, y la copia normalizada que el escritor saca del
    origen tampoco es un archivo de salida: romper cualquiera de las dos sería
    describir un fallo distinto del que se está probando.
    """
    original = pymupdf.Document.save
    calls = {"n": 0}

    def flaky(self, filename, **kwargs):
        if isinstance(filename, (str, Path)) and Path(filename).name != REPAIRED_FILE:
            calls["n"] += 1
            if calls["n"] <= times:
                raise RuntimeError(GRAFT_ERROR)
        return original(self, filename, **kwargs)

    monkeypatch.setattr(pymupdf.Document, "save", flaky)
    return calls


class TestSaveTimeFailure:
    """The real shape of the bug: it surfaces at the end, not at the insert.

    MuPDF resolves grafted objects lazily, so a damaged source copies without
    complaint and then raises "source object number out of range" when the
    output is written. Catching only the insert leaves that path uncovered, and
    the whole document is lost after every page has already been read.

    Se rompen dos guardados y no uno porque el escritor tiene dos intentos por
    el camino rápido: el primero sobre el origen tal como llegó y el segundo
    sobre el origen ya normalizado. Romper sólo el primero probaría la
    normalización, que tiene sus propias pruebas, y no el rescate página a
    página que es lo que aquí se describe.
    """

    def test_a_save_that_fails_rebuilds_the_file_page_by_page(
        self, source, tmp_path, monkeypatch
    ):
        break_save(monkeypatch, times=2)

        assembly = PyMuPDFAssembler().write(source, one_group([1, 2, 3, 4, 5, 6]), tmp_path / "out")

        assert assembly.unwritable_pages == {}
        assert len(assembly.outputs) == 1
        with pymupdf.open(assembly.outputs[0]) as written:
            assert written.page_count == 6

    def test_the_half_written_file_is_not_left_behind(self, source, tmp_path, monkeypatch):
        # A file the failed save may have already touched must not survive as a
        # truncated PDF that looks like a finished resolution.
        break_save(monkeypatch, times=2)
        destination = tmp_path / "out"
        assembly = PyMuPDFAssembler().write(source, one_group([1, 2]), destination)
        assert assembly.outputs[0].is_file()
        with pymupdf.open(assembly.outputs[0]) as written:
            assert written.page_count == 2

    def test_a_page_that_fails_to_serialise_alone_is_named(
        self, source, tmp_path, monkeypatch
    ):
        # Isolating each page is what turns "the file cannot be written" into
        # "page 3 cannot be written", which is the difference between losing a
        # document and losing a page.
        break_save(monkeypatch, times=2)
        original = pymupdf.Document.tobytes

        def flaky(self, **kwargs):
            if self.page_count == 1 and "pagina 3" in self[0].get_text():
                raise RuntimeError(GRAFT_ERROR)
            return original(self, **kwargs)

        monkeypatch.setattr(pymupdf.Document, "tobytes", flaky)

        assembly = PyMuPDFAssembler().write(source, one_group([1, 2, 3, 4]), tmp_path / "out")

        assert list(assembly.unwritable_pages) == [3]
        with pymupdf.open(assembly.outputs[0]) as written:
            assert written.page_count == 3

    def test_the_quarantine_file_gets_the_same_treatment(self, source, tmp_path, monkeypatch):
        break_save(monkeypatch, times=2)
        result = GroupingResult(
            groups=[PageGroup(code=ResolutionCode.parse("00086"), page_numbers=[3, 4])],
            quarantine=[1, 2],
        )
        assembly = PyMuPDFAssembler().write(source, result, tmp_path / "out")
        assert [path.name for path in assembly.outputs][-1] == "_quarantine.pdf"
        assert assembly.unwritable_pages == {}


class TestDamagedSource:
    @pytest.fixture
    def damaged(self, source, tmp_path):
        """A source whose cross-reference table MuPDF has to rebuild."""
        raw = source.read_bytes()
        path = tmp_path / "damaged.pdf"
        path.write_bytes(raw[: int(len(raw) * 0.82)])
        with pymupdf.open(path) as document:
            assert document.is_repaired, "fixture no longer produces a damaged file"
        return path

    def test_a_damaged_source_is_still_split(self, damaged, tmp_path):
        assembly = PyMuPDFAssembler().write(damaged, one_group([1, 2, 3]), tmp_path / "out")
        assert len(assembly.outputs) == 1
        with pymupdf.open(assembly.outputs[0]) as written:
            assert written.page_count == 3

    def test_the_repair_scratch_file_does_not_survive_the_run(self, damaged, tmp_path):
        # It is scratch, and an operator opening the output folder should see
        # resolutions, not a copy of the input.
        destination = tmp_path / "out"
        PyMuPDFAssembler().write(damaged, one_group([1, 2]), destination)
        assert not (destination / REPAIRED_FILE).exists()


class TestDanoQueNoSeVeAlAbrir:
    """El daño real que perdía páginas: una referencia colgante que MuPDF no marca.

    Un escaneo puede traer una tabla de referencias cruzadas que se lee sin una
    queja y que, dentro, remite a un objeto que no existe. ``is_repaired`` sale
    en falso porque hasta que alguien no pide ese objeto no hay nada que falle,
    así que el escritor no tenía motivo para normalizar el origen. El daño
    aparecía al injertar, y el rescate página a página injertaba desde el mismo
    documento roto y fallaba igual: la página se daba por perdida sin haber
    probado lo único que la salvaba.

    Aquí no se simula nada. El PDF de la prueba está roto de verdad, con la
    misma avería que produjo ``code=4: source object number out of range`` sobre
    el material de la Universidad.
    """

    def test_the_damage_is_real_and_would_lose_the_page(self, dangling):
        # Sin la reparación no hay forma de copiar esas páginas: ni el bloque
        # entero ni la página sola. Si esto dejara de fallar, el resto de la
        # clase no estaría probando nada.
        with (
            pymupdf.open(dangling) as origin,
            pymupdf.open() as output,
            pytest.raises(Exception, match="out of range"),
        ):
            output.insert_pdf(origin, from_page=0, to_page=5)

    def test_every_page_is_still_written(self, dangling, tmp_path):
        assembly = PyMuPDFAssembler().write(
            dangling, one_group([1, 2, 3, 4, 5, 6]), tmp_path / "out"
        )

        assert assembly.unwritable_pages == {}
        with pymupdf.open(assembly.outputs[0]) as written:
            assert written.page_count == 6

    def test_the_damaged_page_arrives_with_its_content(self, dangling, tmp_path):
        # Que el archivo tenga seis páginas no basta: la que estaba rota tiene
        # que traer lo que traía, no una hoja en blanco que cuadre la cuenta.
        assembly = PyMuPDFAssembler().write(
            dangling, one_group([1, 2, 3, 4, 5, 6]), tmp_path / "out"
        )
        with pymupdf.open(assembly.outputs[0]) as written:
            assert "pagina 4" in written[3].get_text()

    def test_the_source_is_repaired_once_for_the_whole_document(self, dangling, tmp_path):
        # Reparar es reescribir el archivo entero. Pagarlo una vez por
        # resolución convertiría un documento de trescientas en trescientas
        # pasadas sobre el disco.
        saves = []
        original = pymupdf.Document.save

        def contar(self, filename, **kwargs):
            if isinstance(filename, (str, Path)) and Path(filename).name == REPAIRED_FILE:
                saves.append(filename)
            return original(self, filename, **kwargs)

        result = GroupingResult(
            groups=[
                PageGroup(code=ResolutionCode.parse("00086"), page_numbers=[1, 2]),
                PageGroup(code=ResolutionCode.parse("00072"), page_numbers=[3, 4]),
                PageGroup(code=ResolutionCode.parse("00083"), page_numbers=[5, 6]),
            ]
        )
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(pymupdf.Document, "save", contar)
            assembly = PyMuPDFAssembler().write(dangling, result, tmp_path / "out")

        assert len(saves) == 1
        assert len(assembly.outputs) == 3
        assert assembly.unwritable_pages == {}

    def test_the_repair_scratch_file_does_not_survive(self, dangling, tmp_path):
        destination = tmp_path / "out"
        PyMuPDFAssembler().write(dangling, one_group([1, 2, 3, 4]), destination)
        assert not (destination / REPAIRED_FILE).exists()


class TestSeMiraAntesDeEscribir:
    """La avería se busca al empezar, no se descubre a mitad de la entrega.

    Esperar a que una escritura falle tenía tres costes que no hacía falta
    pagar. El operador veía un aviso de fallo -- ``la copia por bloques de
    RESOLUCION_00965.pdf falló`` -- por una avería que el sistema sí sabía
    arreglar. Las resoluciones anteriores ya habían salido de un documento del
    que MuPDF no podía copiarlo todo. Y el archivo a medio escribir había que
    borrarlo y rehacerlo.

    Recorrer la tabla de objetos cuesta menos de un segundo incluso en el libro
    de 192 MB que levantó la avería, así que se paga siempre.
    """

    def test_the_probe_names_the_object_that_is_not_there(self, dangling, source):
        assert objeto_que_no_resuelve(pymupdf.open(dangling)) == 9999
        assert objeto_que_no_resuelve(pymupdf.open(source)) is None

    def test_the_source_is_repaired_before_the_first_output_is_written(
        self, dangling, tmp_path
    ):
        orden = []
        original = pymupdf.Document.save

        def anotar(self, filename, **kwargs):
            if isinstance(filename, (str, Path)):
                orden.append(Path(filename).name)
            return original(self, filename, **kwargs)

        result = GroupingResult(
            groups=[
                PageGroup(code=ResolutionCode.parse("00086"), page_numbers=[1, 2]),
                PageGroup(code=ResolutionCode.parse("00072"), page_numbers=[3, 4]),
            ]
        )
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(pymupdf.Document, "save", anotar)
            assembly = PyMuPDFAssembler().write(dangling, result, tmp_path / "out")

        assert orden[0] == REPAIRED_FILE
        assert REPAIRED_FILE not in orden[1:]
        assert len(assembly.outputs) == 2
        assert assembly.unwritable_pages == {}

    def test_nothing_is_reported_as_a_failure(self, dangling, tmp_path, caplog):
        # Un documento que el sistema arregla y entrega entero no puede dejar en
        # la consola del operador la palabra "falló": lo que se avisa como
        # pérdida tiene que ser lo que se perdió.
        with caplog.at_level("WARNING", logger="resolutions.adapters.pymupdf_assembler"):
            PyMuPDFAssembler().write(dangling, one_group([1, 2, 3, 4, 5, 6]), tmp_path / "out")
        assert not [record for record in caplog.records if "falló" in record.getMessage()]

    def test_the_repair_is_announced_so_the_screen_does_not_look_frozen(
        self, dangling, tmp_path
    ):
        # Reescribir un libro de cientos de megas tarda, y durante ese rato la
        # barra no se mueve. Si además no dice nada, el trabajo parece colgado.
        class Anotador:
            def __init__(self):
                self.detalles = []

            def emit(self, event):
                self.detalles.append(event.detail)

        progress = Anotador()
        PyMuPDFAssembler(progress=progress).write(
            dangling, one_group([1, 2]), tmp_path / "out"
        )
        assert any("reparando" in (detalle or "") for detalle in progress.detalles)

    def test_a_cancellation_is_honoured_before_the_repair_starts(self, dangling, tmp_path):
        # Reparar es el tramo más largo de la escritura. Empezarlo después de que
        # el operador haya pulsado parar es hacerle esperar minutos por un
        # trabajo que ya nadie quiere.
        saves = []
        original = pymupdf.Document.save

        def contar(self, filename, **kwargs):
            if isinstance(filename, (str, Path)) and Path(filename).name == REPAIRED_FILE:
                saves.append(filename)
            return original(self, filename, **kwargs)

        class Cancela:
            def check(self):
                raise Cancelled("el operador canceló el trabajo")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(pymupdf.Document, "save", contar)
            with pytest.raises(Cancelled):
                PyMuPDFAssembler(control=Cancela()).write(
                    dangling, one_group([1, 2]), tmp_path / "out"
                )

        assert saves == []
        assert not (tmp_path / "out" / REPAIRED_FILE).exists()


class TestQuarantineStillShips:
    def test_quarantined_pages_are_written_as_their_own_file(self, source, tmp_path):
        result = GroupingResult(
            groups=[PageGroup(code=ResolutionCode.parse("00086"), page_numbers=[3, 4])],
            quarantine=[1, 2],
        )
        assembly = PyMuPDFAssembler().write(source, result, tmp_path / "out")
        assert [path.name for path in assembly.outputs][-1] == "_quarantine.pdf"


class TestContainment:
    """One resolution failing must never cost the other resolutions."""

    def test_a_file_that_cannot_be_written_at_all_leaves_the_others_alone(
        self, source, tmp_path, monkeypatch
    ):
        original = pymupdf.Document.save

        def flaky(self, filename, **kwargs):
            # Every attempt at the second file fails, at every fallback level.
            if isinstance(filename, (str, Path)) and "00072" in str(filename):
                raise RuntimeError(GRAFT_ERROR)
            return original(self, filename, **kwargs)

        monkeypatch.setattr(pymupdf.Document, "save", flaky)

        result = GroupingResult(
            groups=[
                PageGroup(code=ResolutionCode.parse("00086"), page_numbers=[1, 2]),
                PageGroup(code=ResolutionCode.parse("00072"), page_numbers=[3, 4]),
                PageGroup(code=ResolutionCode.parse("00083"), page_numbers=[5, 6]),
            ]
        )
        assembly = PyMuPDFAssembler().write(source, result, tmp_path / "out")

        # Two of three resolutions still ship, and the lost one is named by page.
        assert len(assembly.outputs) == 2
        assert sorted(assembly.unwritable_pages) == [3, 4]
        assert not (tmp_path / "out" / "00072.pdf").exists()

    def test_the_pages_of_a_lost_file_reach_the_review_queue(self, source, tmp_path, monkeypatch):
        from resolutions.application.process_document import ProcessDocument

        original = pymupdf.Document.save

        def flaky(self, filename, **kwargs):
            if isinstance(filename, (str, Path)) and "00086" in str(filename):
                raise RuntimeError(GRAFT_ERROR)
            return original(self, filename, **kwargs)

        monkeypatch.setattr(pymupdf.Document, "save", flaky)

        assembly = PyMuPDFAssembler().write(source, one_group([1, 2]), tmp_path / "out")
        queue = ProcessDocument._build_review_queue(
            [], GroupingResult(), _NoFailures(), assembly.unwritable_pages
        )
        assert [item.page_number for item in queue] == [1, 2]
        assert "no pudo copiarse" in queue[0].reason


class _NoFailures:
    failures: dict[int, str] = {}
    mis_decoded_pages: list[int] = []


class TestPathLength:
    """Windows refuses a path over 260 characters, and refuses it at save time.

    By then every page has been read, grouped and copied, so the refusal costs
    the whole resolution. A long title is never a good enough reason to lose a
    file, so the name gives way instead.
    """

    def test_a_deep_destination_shortens_the_name_rather_than_failing(
        self, source, tmp_path
    ):
        from resolutions.domain.grouping import GroupingResult, PageGroup
        from resolutions.domain.resolution_code import ResolutionCode

        deep = tmp_path
        for part in ("un-nivel-bastante-largo-de-carpeta", "y-otro-igual-de-largo", "y-uno-mas"):
            deep = deep / part
        title = (
            "Por medio de la cual se hace un nombramiento en provisionalidad en la "
            "planta global de personal administrativo de la universidad"
        )
        result = GroupingResult(
            groups=[
                PageGroup(code=ResolutionCode.parse("00072"), page_numbers=[1, 2], title=title)
            ]
        )

        assembly = PyMuPDFAssembler().write(source, result, deep)

        assert assembly.unwritable_pages == {}
        assert len(assembly.outputs) == 1
        assert assembly.outputs[0].is_file()
        assert len(str(assembly.outputs[0])) < 260

    def test_the_inventory_records_the_name_that_was_written(self, source, tmp_path):
        # The one invariant that matters here: an inventory naming a file nobody
        # can open is worse than no inventory.
        from resolutions.domain.grouping import GroupingResult, PageGroup
        from resolutions.domain.resolution_code import ResolutionCode

        result = GroupingResult(
            groups=[
                PageGroup(
                    code=ResolutionCode.parse("00072"),
                    page_numbers=[1],
                    title="Por medio de la cual se hace un nombramiento en provisionalidad",
                )
            ]
        )
        assembly = PyMuPDFAssembler().write(source, result, tmp_path / "out")

        assert assembly.written["00072"] == assembly.outputs[0].name

    def test_the_code_survives_even_when_the_title_cannot(self, tmp_path):
        # A file named after its number alone is still findable; one that was
        # never written is not.
        from resolutions.adapters.pymupdf_assembler import name_budget
        from resolutions.domain.naming import output_filename
        from resolutions.domain.resolution_code import ResolutionCode

        # El nombre corto de hoy -- "RESOLUCION_00072.pdf" -- cabe siempre; la
        # regla que se fija aquí es la del nombre largo, que es el que puede
        # pasarse y el que se sigue usando en los libros de folios.
        absurd = tmp_path / ("x" * 200)
        name = output_filename(
            ResolutionCode.parse("00072"),
            "un titulo cualquiera",
            budget=name_budget(absurd),
            prefix=None,
        )
        assert name.startswith("00072")
