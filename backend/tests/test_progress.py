from pathlib import Path

import pytest
from fakes import (
    BODY,
    FakeAssembler,
    FakeDocumentStore,
    FakeOcr,
    FakePage,
    FakePageSource,
)

from resolutions.application.pipeline import ClassificationPipeline, PipelineConfig
from resolutions.application.process_document import ProcessDocument
from resolutions.application.progress import RecordingProgressReporter, Stage

DOCUMENT = Path("expediente.pdf")
DESTINATION = Path("/out")


def digital(header):
    return FakePage(text=f"{header}\n{BODY}")


class ExplodingOcr:
    """Fails on demand, to prove one bad page does not sink the document."""

    def __init__(self, fail_on: set[int]):
        self.fail_on = fail_on
        self.seen = 0

    def read(self, image_png: bytes):
        self.seen += 1
        raise RuntimeError("tesseract died")


class ExplodingSource(FakePageSource):
    """A source whose render blows up for specific pages."""

    def __init__(self, pages, broken: set[int]):
        super().__init__(pages=pages)
        self.broken = broken

    def render(self, page_number: int, band=None, dpi: int = 200) -> bytes:
        if page_number in self.broken:
            raise OSError(f"page {page_number} is corrupt")
        return super().render(page_number, band, dpi)


def run(pages, *, source=None, ocr=None, progress=None):
    source = source or FakePageSource(pages=pages)
    pipeline = ClassificationPipeline(
        ocr=ocr or FakeOcr(),
        config=PipelineConfig(max_workers=1),
        progress=progress,
    )
    use_case = ProcessDocument(
        store=FakeDocumentStore(source=source),
        pipeline=pipeline,
        assembler=FakeAssembler(),
        progress=progress,
    )
    return use_case.execute(DOCUMENT, DESTINATION)


def _sin_repetir(stages: list[str]) -> list[str]:
    """La secuencia de etapas, sin contar dos veces la que informa de su avance."""
    seen: list[str] = []
    for stage in stages:
        if not seen or seen[-1] != stage:
            seen.append(stage)
    return seen


class TestPageTelemetry:
    def test_it_announces_the_page_count_before_any_work(self):
        recorder = RecordingProgressReporter()
        run([digital("RESOLUCION N° 0412/2024")] * 3, progress=recorder)
        first = recorder.events[0]
        assert first.stage is Stage.OPENED
        assert first.page_count == 3

    def test_it_emits_one_event_per_page_with_the_rung_that_answered(self):
        recorder = RecordingProgressReporter()
        run(
            [digital("RESOLUCION N° 0412/2024"), FakePage(header="RESOLUCION N° 0555/2024")],
            progress=recorder,
        )
        pages = [event for event in recorder.events if event.stage is Stage.PAGE]
        assert [(event.page_number, event.provenance) for event in pages] == [
            (1, "text_layer"),
            (2, "ocr_region"),
        ]

    def test_it_walks_the_stages_in_order(self):
        """El orden de las etapas, no el número de avisos que da cada una.

        Cada etapa larga informa de su avance varias veces -- ése es justamente
        el punto -- así que lo que se fija aquí es la secuencia por la que pasa
        el documento, no cuántas líneas produce cada tramo.
        """
        recorder = RecordingProgressReporter()
        run([digital("RESOLUCION N° 0412/2024")], progress=recorder)
        assert _sin_repetir(recorder.stages()) == [
            "opened",
            "page",
            # Reconocer el documento y contrastar lo declarado tardan, y hasta
            # ahora ocurrían en silencio entre la última página y la agrupación.
            "identifying",
            "verifying",
            "grouping",
            "assembling",
            # Escribir el inventario y la planilla del documento. Estuvo mucho
            # tiempo en silencio -- la etapa existía en el enum y en la
            # pantalla, y nadie la emitía -- así que el trabajo parecía
            # terminado y quieto mientras openpyxl guardaba el libro.
            "delivering",
            "done",
        ]

    def test_la_entrega_se_anuncia_antes_de_escribir_la_planilla(self):
        """Que el aviso llegue antes del trabajo que describe, no después.

        Una etapa anunciada al terminar no informa de nada: el tramo que tenía
        que explicar ya pasó. Se comprueba por la posición del aviso respecto
        del final, que es lo único que la pantalla puede aprovechar.
        """
        recorder = RecordingProgressReporter()
        run([digital("RESOLUCION N° 0412/2024")], progress=recorder)
        etapas = recorder.stages()
        assert etapas.index("delivering") < etapas.index("done")

    def test_a_broken_reporter_never_breaks_the_document(self):
        class Hostile:
            def emit(self, event):
                raise RuntimeError("telemetry is down")

        report = run([digital("RESOLUCION N° 0412/2024")], progress=Hostile())
        assert report.grouping.groups[0].code.value == "0412/2024"


class TestPageFailureIsolation:
    def test_one_unreadable_page_does_not_lose_the_document(self):
        pages = [digital("RESOLUCION N° 0412/2024"), FakePage(header="", body=""), digital("")]
        report = run(pages, source=ExplodingSource(pages, broken={2}))

        # Page 2 blew up; pages 1 and 3 still landed in their group.
        assert report.grouping.groups[0].page_numbers == [1, 2, 3]
        report.grouping.verify_integrity(total_pages=3)

    def test_the_failure_is_recorded_against_its_page(self):
        pages = [digital("RESOLUCION N° 0412/2024"), FakePage(header="", body="")]
        report = run(pages, source=ExplodingSource(pages, broken={2}))
        assert "2" in report.stats["failed_pages"]
        assert "corrupt" in report.stats["failed_pages"]["2"]

    def test_a_failed_page_is_sent_to_review_not_guessed(self):
        pages = [digital("RESOLUCION N° 0412/2024"), FakePage(header="", body="")]
        report = run(pages, source=ExplodingSource(pages, broken={2}))
        assert [(item.page_number, "no pudo procesarse" in item.reason) for item in report.review_queue] == [
            (2, True)
        ]

    def test_the_progress_stream_marks_the_failed_page(self):
        recorder = RecordingProgressReporter()
        pages = [digital("RESOLUCION N° 0412/2024"), FakePage(header="", body="")]
        run(pages, source=ExplodingSource(pages, broken={2}), progress=recorder)
        failed = [event for event in recorder.events if event.failed]
        assert [event.page_number for event in failed] == [2]

    def test_every_page_failing_still_produces_an_honest_result(self):
        pages = [FakePage(header="", body="") for _ in range(4)]
        report = run(pages, source=ExplodingSource(pages, broken={1, 2, 3, 4}))
        assert report.grouping.groups == []
        assert report.grouping.quarantine == [1, 2, 3, 4]
        assert len(report.review_queue) == 4


class TestDocumentFailure:
    def test_a_fatal_error_is_announced_before_it_propagates(self):
        recorder = RecordingProgressReporter()

        class Broken:
            def write(self, source, result, destination):
                raise OSError("disk full")

        use_case = ProcessDocument(
            store=FakeDocumentStore(source=FakePageSource(pages=[digital("RESOLUCION N° 1/2024")])),
            pipeline=ClassificationPipeline(ocr=FakeOcr(), config=PipelineConfig(max_workers=1)),
            assembler=Broken(),
            progress=recorder,
        )
        with pytest.raises(OSError):
            use_case.execute(DOCUMENT, DESTINATION)

        assert recorder.events[-1].stage is Stage.FAILED
        assert "disk full" in recorder.events[-1].detail


# -----------------------------------------------------------------------------
#  La procedencia de cada página de un libro de folios
# -----------------------------------------------------------------------------
#  La cinta de progreso pinta con el mismo carácter la página fallida y la que
#  no declara de dónde salió -- las dos son "x" en api/jobs.py -- así que un
#  lector que calle la procedencia hace que la pantalla anuncie como ilegible un
#  libro que se está leyendo perfectamente. Pasó con los 287 folios del libro
#  3858079: 85 páginas leídas, 3 con algo que revisar, y las 85 en rojo.
# -----------------------------------------------------------------------------

from resolutions.api.jobs import FAILED_MARK, PENDING_MARK, PROVENANCE_MARKS  # noqa: E402
from resolutions.application.read_diploma_book import ReadDiplomaBook  # noqa: E402
from resolutions.domain.diploma import TextLine  # noqa: E402
from resolutions.domain.page import Provenance  # noqa: E402

FOLIO_COMPLETO = (
    "UNIVERSIDAD DE CARTAGENA",
    "Folio 336",
    "ALIX JOSEFINA MARIN RODRIGUEZ",
    "Nombres y apellidos del graduando",
    "Titulo recibido: ESPECIALISTA EN GESTION DE LA CALIDAD",
    "Fecha de graduación: 29/03/2012",
    "Registrado a folio No. 336",
    "libro No. 8",
)


class FuenteDeFolios:
    """Un libro de folios, con las líneas que se le den por página."""

    def __init__(self, paginas):
        self._paginas = paginas

    @property
    def page_count(self):
        return len(self._paginas)

    def lines_of(self, page_number):
        return [
            TextLine(text=texto, y=float(indice))
            for indice, texto in enumerate(self._paginas[page_number - 1])
        ]

    def render(self, page_number, band=None, dpi=200):
        return b""


def marca_de(evento):
    """La marca que la cinta pintaría para este evento, tal como lo hace jobs.py."""
    if evento.failed:
        return FAILED_MARK
    return PROVENANCE_MARKS.get(str(evento.provenance or "none"), PENDING_MARK)


class TestProcedenciaDelLibroDeFolios:
    def _eventos(self, paginas, ocr=None):
        reporter = RecordingProgressReporter()
        ReadDiplomaBook(ocr=ocr, progress=reporter).execute(FuenteDeFolios(paginas))
        return [e for e in reporter.events if e.stage is Stage.PAGE]

    def test_toda_pagina_declara_de_donde_salio(self):
        eventos = self._eventos([FOLIO_COMPLETO] * 3)
        assert [e.provenance for e in eventos] == [str(Provenance.TEXT_LAYER)] * 3

    def test_una_pagina_leida_no_se_pinta_como_ilegible(self):
        # Ésta es la regresión: sin procedencia la marca era "x", la misma que
        # la de una página que nadie pudo leer.
        eventos = self._eventos([FOLIO_COMPLETO] * 3)
        assert [marca_de(e) for e in eventos] == ["t", "t", "t"]

    def test_la_pagina_que_necesita_revision_sigue_marcandose(self):
        # Un folio en blanco no tiene nada que leer: ése sí es "x", y tiene que
        # seguir siéndolo para que el operador lo vea.
        eventos = self._eventos([FOLIO_COMPLETO, ("",), FOLIO_COMPLETO])
        assert [marca_de(e) for e in eventos] == ["t", "x", "t"]


class TestMotivoDeLaRevision:
    """Una página marcada tiene que decir por qué, no sólo que sí.

    El operador mira la consola mientras el trabajo corre. "página 83 ilegible"
    lo manda a abrir una página que se leyó entera y bien; el motivo real -- que
    el folio del encabezado no coincide con el del pie -- le dice dónde poner el
    ojo sin abrir nada.
    """

    FOLIO_SIN_FECHA = (
        "Folio 336",
        "ALIX JOSEFINA MARIN RODRIGUEZ",
        "Nombres y apellidos del graduando",
        "Titulo recibido: ESPECIALISTA EN GESTION DE LA CALIDAD",
        "Registrado a folio No. 336",
        "libro No. 8",
    )

    FOLIOS_QUE_NO_COINCIDEN = (
        "Folio 81",
        "BRENDA LOPEZ DIAZ",
        "Nombres y apellidos del graduando",
        "Titulo recibido: ESPECIALISTA EN SALUD OCUPACIONAL",
        "Fecha de graduación: 16/08/2013",
        "Registrado a folio No. 810",
        "libro No. 8",
    )

    def _progreso(self, paginas):
        from resolutions.api.jobs import JobProgress

        progreso = JobProgress()

        class Puente:
            def emit(self, event):
                progreso.apply(event.as_dict())

        ReadDiplomaBook(progress=Puente()).execute(FuenteDeFolios(paginas))
        return progreso

    def test_la_pagina_limpia_no_deja_motivo(self):
        progreso = self._progreso([FOLIO_COMPLETO, FOLIO_COMPLETO])
        assert progreso.as_dict()["review"] == {}
        assert progreso.as_dict()["failed_pages"] == 0

    def test_el_campo_que_falta_se_nombra(self):
        progreso = self._progreso([self.FOLIO_SIN_FECHA])
        assert progreso.as_dict()["review"] == {
            "1": "no se pudo leer la fecha de graduación"
        }

    def test_los_folios_que_discrepan_se_citan_los_dos(self):
        progreso = self._progreso([self.FOLIOS_QUE_NO_COINCIDEN])
        motivo = progreso.as_dict()["review"]["1"]
        assert "81" in motivo and "810" in motivo

    def test_una_pagina_que_deja_de_fallar_pierde_su_motivo(self):
        # El peldaño del modelo repinta una página ya contada. Si el motivo se
        # quedara, la pantalla seguiría pidiendo revisar algo ya resuelto.
        from resolutions.api.jobs import JobProgress

        progreso = JobProgress()
        progreso.apply({"stage": "opened", "page_count": 1})
        progreso.apply(
            {"stage": "page", "page_number": 1, "failed": True, "detail": "algo no cuadra"}
        )
        assert progreso.as_dict()["review"] == {"1": "algo no cuadra"}

        progreso.apply(
            {"stage": "page", "page_number": 1, "failed": False, "provenance": "vision_model"}
        )
        assert progreso.as_dict()["review"] == {}


# -----------------------------------------------------------------------------
#  El estado que ve la pantalla mientras el trabajo tarda
# -----------------------------------------------------------------------------
#  Un documento pasa la mitad del tiempo en fases que no producen páginas:
#  reconocerlo, contrastar lo declarado, escribir doscientos ochenta y siete PDF,
#  guardar una planilla de mil filas. El estado tiene que poder contestar "¿qué
#  está haciendo?" en todas ellas. Antes no podía: el reloj sólo avanzaba cuando
#  llegaba un evento, así que durante esas fases la pantalla mostraba la misma
#  cifra indefinidamente y el sistema parecía colgado mientras trabajaba.
# -----------------------------------------------------------------------------

import time as _time  # noqa: E402

from resolutions.api.jobs import JobProgress  # noqa: E402


def _abierto(paginas: int = 3) -> JobProgress:
    progreso = JobProgress()
    progreso.apply({"stage": "opened", "page_count": paginas})
    return progreso


class TestElRelojNoSePara:
    def test_avanza_aunque_no_llegue_ningun_evento(self):
        progreso = _abierto()
        primero = progreso.as_dict()["elapsed_seconds"]
        _time.sleep(0.05)
        segundo = progreso.as_dict()["elapsed_seconds"]
        assert segundo > primero

    def test_se_congela_cuando_el_trabajo_termina(self):
        progreso = _abierto()
        progreso.apply({"stage": "done"})
        final = progreso.as_dict()["elapsed_seconds"]
        _time.sleep(0.05)
        assert progreso.as_dict()["elapsed_seconds"] == final

    def test_la_velocidad_se_calcula_sobre_el_reloj_vivo(self):
        progreso = _abierto()
        progreso.apply({"stage": "page", "page_number": 1, "provenance": "text_layer"})
        assert progreso.as_dict()["pages_per_second"] > 0


class TestCadaEtapaCuentaLoSuyo:
    def test_una_etapa_larga_guarda_su_detalle_y_su_contador(self):
        progreso = _abierto()
        progreso.apply(
            {"stage": "assembling", "done": 0, "total": 287, "detail": "preparando"}
        )
        progreso.apply({"stage": "assembling", "done": 142, "detail": "00082__acta.pdf"})
        estado = progreso.as_dict()
        assert estado["stage"] == "assembling"
        assert (estado["stage_done"], estado["stage_total"]) == (142, 287)
        assert estado["detail"] == "00082__acta.pdf"

    def test_avanzar_dentro_de_una_etapa_no_reinicia_su_reloj(self):
        progreso = _abierto()
        progreso.apply({"stage": "assembling", "done": 0, "total": 287})
        _time.sleep(0.05)
        antes = progreso.as_dict()["stage_elapsed_seconds"]
        progreso.apply({"stage": "assembling", "done": 40})
        assert progreso.as_dict()["stage_elapsed_seconds"] >= antes

    def test_cambiar_de_etapa_si_reinicia_su_reloj(self):
        progreso = _abierto()
        progreso.apply({"stage": "assembling", "done": 287, "total": 287})
        _time.sleep(0.05)
        progreso.apply({"stage": "inventorying", "done": 0, "total": 1084})
        estado = progreso.as_dict()
        assert estado["stage_elapsed_seconds"] < 0.05
        assert estado["stage_done"] == 0

    def test_las_paginas_siguen_contandose_como_paginas(self):
        progreso = _abierto(paginas=3)
        for numero in (1, 2):
            progreso.apply(
                {"stage": "page", "page_number": numero, "provenance": "text_layer"}
            )
        estado = progreso.as_dict()
        assert (estado["stage_done"], estado["stage_total"]) == (2, 3)

    def test_una_pagina_despues_de_otra_etapa_devuelve_el_estado_a_la_lectura(self):
        # El peldaño del modelo relee páginas cuando el documento ya está
        # agrupado. La pantalla tiene que decir eso y no seguir anunciando una
        # etapa que ya pasó.
        progreso = _abierto()
        progreso.apply({"stage": "grouping"})
        progreso.apply({"stage": "page", "page_number": 1, "provenance": "vision_model"})
        assert progreso.as_dict()["stage"] == "analysing"


class TestElSilencio:
    def test_se_mide_desde_la_ultima_noticia(self):
        progreso = _abierto()
        _time.sleep(0.05)
        assert progreso.as_dict()["silent_seconds"] >= 0.05

    def test_una_noticia_lo_pone_a_cero(self):
        progreso = _abierto()
        _time.sleep(0.05)
        progreso.apply({"stage": "assembling", "done": 1, "total": 10})
        assert progreso.as_dict()["silent_seconds"] < 0.05

    def test_un_trabajo_terminado_no_esta_callado_sino_acabado(self):
        progreso = _abierto()
        progreso.apply({"stage": "done"})
        _time.sleep(0.05)
        assert progreso.as_dict()["silent_seconds"] == 0.0
