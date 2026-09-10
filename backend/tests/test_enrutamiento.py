"""A qué camino va un PDF según lo que digan sus páginas.

El caso que obliga a que esto exista es real y costoso: una caja de
correspondencia de 125 páginas subida con «Dividir en documentos» salió como un
solo documento de la 37 a la 125, con 37 hojas en revisión. El agrupador por
código había encontrado un número suelto a media caja y lo había hecho mandar
hasta el final, porque es lo único que sabe hacer. Ninguna de sus páginas decía
ser una resolución.
"""

import pytest

from resolutions.api import worker
from resolutions.application.task import TaskKind
from resolutions.domain.doctype import DocumentType


@pytest.fixture
def rutas(monkeypatch):
    """Sustituye los tres destinos por marcadores, para ver a cuál se va."""
    visitados = []
    for nombre in ("_split_job", "_record_split_job", "_segment_job"):
        def marcar(payload, task, _n=nombre, **kwargs):
            visitados.append((_n, task))
            return {"ruta": _n}
        monkeypatch.setattr(worker, nombre, marcar)
    monkeypatch.setattr(worker, "_anunciar", lambda *a, **k: None)
    return visitados


def payload(task: TaskKind) -> dict:
    return {"job_id": "t", "source": "x.pdf", "filename": "x.pdf",
            "task": str(task), "settings": {"ocr_language": "spa"}}


def reconoce(monkeypatch, tipo):
    monkeypatch.setattr(worker, "_recognise", lambda _p: tipo)


class TestLoQueElPapelDiceSerMandaSobreLaAccion:
    def test_una_caja_sin_tipo_reconocible_se_separa_por_continuidad(
        self, rutas, monkeypatch
    ):
        """El desvío. Sin él, esto habría ido al agrupador por código."""
        reconoce(monkeypatch, DocumentType.DESCONOCIDO)
        worker.process_document_job(payload(TaskKind.SPLIT))
        assert rutas == [("_segment_job", TaskKind.SEGMENT)]

    def test_un_legajo_de_resoluciones_sigue_yendo_al_agrupador(
        self, rutas, monkeypatch
    ):
        reconoce(monkeypatch, DocumentType.RESOLUCION)
        worker.process_document_job(payload(TaskKind.SPLIT))
        assert rutas[0][0] == "_split_job"

    def test_un_libro_de_diplomas_sigue_yendo_al_suyo(self, rutas, monkeypatch):
        reconoce(monkeypatch, DocumentType.DIPLOMA)
        worker.process_document_job(payload(TaskKind.SPLIT))
        assert rutas[0][0] == "_record_split_job"

    def test_un_legajo_de_matriculas_se_parte_por_estudiante(self, rutas, monkeypatch):
        """El desvío que faltaba.

        `matricula_split.group_by_student` estaba escrito y probado, y este
        enrutador sólo nombraba a los diplomas: un legajo de matrículas subido
        con «dividir» se iba al agrupador por código de resolución, que busca en
        sus páginas un número que ninguna lleva. Salía un solo documento con el
        legajo entero, o uno por cada número suelto que el OCR creyera ver.
        """
        reconoce(monkeypatch, DocumentType.MATRICULA)
        worker.process_document_job(payload(TaskKind.SPLIT))
        assert rutas[0][0] == "_record_split_job"

    def test_y_tambien_cuando_se_pidio_inventariar_a_la_vez(self, rutas, monkeypatch):
        """Las dos salidas de una sola lectura, igual que en los diplomas."""
        reconoce(monkeypatch, DocumentType.MATRICULA)
        worker.process_document_job(payload(TaskKind.BOTH))
        assert rutas[0] == ("_record_split_job", TaskKind.BOTH)

    def test_separar_por_documento_no_pasa_por_el_reconocedor(
        self, rutas, monkeypatch
    ):
        """Y no debe: reconocer cuesta doce pasadas de OCR que este camino no usa."""
        def explota(_p):
            raise AssertionError("no había que reconocer nada")
        monkeypatch.setattr(worker, "_recognise", explota)
        worker.process_document_job(payload(TaskKind.SEGMENT))
        assert rutas == [("_segment_job", TaskKind.SEGMENT)]


class TestLoQueElDesvioNoSeLleva:
    def test_dividir_e_inventariar_no_se_desvia(self, rutas, monkeypatch):
        """Separar por continuidad no levanta FUID.

        Desviarlo dejaría al operador sin el inventario que pidió y sin que
        nadie se lo dijera, que es peor que darle un reparto discutible.
        """
        reconoce(monkeypatch, DocumentType.DESCONOCIDO)
        worker.process_document_job(payload(TaskKind.BOTH))
        assert rutas[0][0] == "_split_job"

    def test_una_averia_del_reconocedor_no_cambia_de_ruta_a_nadie(
        self, rutas, monkeypatch, tmp_path
    ):
        """Cae al camino de siempre, que es el comportamiento conservador.

        Cubre la avería de la lectura -- Tesseract ausente, una muestra que no se
        puede sacar. Abrir el PDF queda fuera de esa protección: un archivo que
        PyMuPDF no puede abrir sigue reventando el trabajo, aquí y en las demás
        rutas, y arreglarlo es otra conversación.
        """
        import pymupdf

        from resolutions.application import inventory_document

        vacio = tmp_path / "x.pdf"
        documento = pymupdf.open()
        documento.new_page()
        documento.save(vacio)
        documento.close()

        class Averiado:
            def __init__(self, *_a, **_k):
                pass

            def identify(self, _source):
                raise RuntimeError("tesseract no está")

        monkeypatch.setattr(inventory_document, "InventoryDocument", Averiado)
        datos = payload(TaskKind.SPLIT)
        datos["source"] = str(vacio)
        worker.process_document_job(datos)
        assert rutas[0][0] == "_split_job"


class TestElAvisoDeQueLaAccionNoPega:
    """Avisa y deja seguir. La elección de la acción es del operador.

    Un legajo de resoluciones separado por continuidad devuelve el doble de
    unidades y media caja en revisión, porque lo único que distingue una
    resolución de la siguiente es el número impreso que esa ruta no lee. Medido
    sobre "RESOLUCIONES 00072-00094.pdf": 29 resoluciones y cero revisiones por
    su camino, contra 63 documentos y 112 páginas a revisar por el otro.
    """

    def test_avisa_cuando_el_papel_dice_ser_otra_cosa(self, monkeypatch):
        monkeypatch.setattr(worker, "_recognise", lambda _p: DocumentType.RESOLUCION)
        monkeypatch.setattr(worker, "_anunciar", lambda *a, **k: None)
        avisos = worker._aviso_de_ruta(payload(TaskKind.SEGMENT), worker._SIN_RECONOCER)
        assert len(avisos) == 1
        assert "resoluciones" in avisos[0]
        assert "Dividir en documentos" in avisos[0]

    def test_no_avisa_de_una_caja_revuelta(self, monkeypatch):
        monkeypatch.setattr(worker, "_anunciar", lambda *a, **k: None)
        avisos = worker._aviso_de_ruta(payload(TaskKind.SEGMENT), DocumentType.DESCONOCIDO)
        assert avisos == []

    def test_una_averia_del_reconocedor_no_inventa_un_aviso(self, monkeypatch):
        """`None` es "no pude", y de eso no se avisa a nadie."""
        monkeypatch.setattr(worker, "_anunciar", lambda *a, **k: None)
        assert worker._aviso_de_ruta(payload(TaskKind.SEGMENT), None) == []

    def test_el_desvio_no_vuelve_a_reconocer(self, monkeypatch, rutas):
        """Ya se preguntó una vez; doce pasadas de OCR no se pagan dos veces."""
        llamadas = []
        def contar(_p):
            llamadas.append(1)
            return DocumentType.DESCONOCIDO
        monkeypatch.setattr(worker, "_recognise", contar)
        worker.process_document_job(payload(TaskKind.SPLIT))
        assert len(llamadas) == 1

    def test_el_aviso_llega_al_informe_y_no_solo_al_progreso(self, monkeypatch):
        """El progreso se ve mientras corre; el informe se lee después."""
        import inspect
        fuente = inspect.getsource(worker._segment_job)
        assert '"notices": avisos' in fuente

    def test_un_reconocedor_que_revienta_no_cancela_la_separacion(self, monkeypatch):
        """El aviso es una comodidad; la separación es el trabajo.

        Esta ruta no dependía del reconocedor hasta que llegó el aviso, y un PDF
        que él no pueda abrir no puede impedir que la caja se separe.
        """
        def revienta(_p):
            raise RuntimeError("no such file")
        monkeypatch.setattr(worker, "_recognise", revienta)
        monkeypatch.setattr(worker, "_anunciar", lambda *a, **k: None)
        assert worker._aviso_de_ruta(payload(TaskKind.SEGMENT), worker._SIN_RECONOCER) == []
