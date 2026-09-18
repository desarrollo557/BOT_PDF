"""El tipo que declara el operador, y qué habilidad llama.

Lo que se fija aquí es que declarar el tipo mande el trabajo a la habilidad que
sabe atenderlo sin gastar la muestra de reconocimiento, y que no declarar nada
siga haciendo exactamente lo de antes.

La razón de que esta elección exista se midió sobre un libro real: el
reconocedor decide sobre doce páginas, y cuando se equivoca el archivo entero
va a la habilidad que no sabe cortarlo. Ese libro acabó en la ruta de
continuidad -- que no lee el papel, así que no puede saber de quién es cada hoja
-- y volvió en 144 documentos desiguales con 240 páginas en revisión.
"""

import pytest

from resolutions.application.tipo_pedido import TipoPedido, tipos_declarables
from resolutions.domain.doctype import DocumentType


class TestLaDeclaracion:
    def test_por_omision_lo_averigua_el_sistema(self):
        """Quien no declare nada trabaja igual que antes de existir el select."""
        assert TipoPedido.parse(None) is TipoPedido.AUTO
        assert TipoPedido.parse("") is TipoPedido.AUTO
        assert TipoPedido.AUTO.document_type is None

    def test_declarar_diplomas_nombra_el_tipo_del_dominio(self):
        assert TipoPedido.parse("diploma").document_type is DocumentType.DIPLOMA

    def test_no_distingue_mayusculas_ni_espacios(self):
        """Lo que llega por una query string llega como llega."""
        assert TipoPedido.parse("  Diploma  ") is TipoPedido.DIPLOMA

    def test_un_tipo_inventado_no_pasa_por_automatico(self):
        """Tragárselo sería peor que rechazarlo: el operador creería haber elegido."""
        with pytest.raises(ValueError):
            TipoPedido.parse("libro-de-actas")

    def test_la_pantalla_recibe_los_tipos_con_su_etiqueta(self):
        ofrecidos = tipos_declarables()
        assert {"id": "auto", "label": "Detectar automáticamente"} in ofrecidos
        assert {"id": "diploma", "label": "Diplomas"} in ofrecidos


class TestAQuienLlama:
    """El despachador, sin abrir ningún PDF: sólo a dónde manda el trabajo."""

    def payload(self, tipo=None, task="split"):
        return {
            "job_id": "x",
            "source": "no-se-abre.pdf",
            "filename": "no-se-abre.pdf",
            "task": task,
            "tipo": tipo,
            "settings": {"output_dir": ".", "ocr_language": "spa"},
        }

    def test_declarar_diplomas_va_derecho_a_los_registros(self, monkeypatch):
        """Y no pasa por el reconocedor: la muestra no se llega a leer."""
        import resolutions.api.worker as worker

        llamadas = []
        monkeypatch.setattr(worker, "_record_split_job", lambda p, t: llamadas.append("registros"))
        monkeypatch.setattr(
            worker, "_recognise", lambda p: pytest.fail("no debía reconocer nada")
        )
        monkeypatch.setattr(worker, "_anunciar", lambda *a, **k: None)

        worker.process_document_job(self.payload(tipo="diploma"))

        assert llamadas == ["registros"]

    def test_sin_declarar_se_reconoce_como_siempre(self, monkeypatch):
        import resolutions.api.worker as worker

        reconocidos = []
        monkeypatch.setattr(worker, "_record_split_job", lambda p, t: "registros")
        monkeypatch.setattr(worker, "_anunciar", lambda *a, **k: None)

        def reconocer(payload):
            reconocidos.append(payload["filename"])
            return DocumentType.DIPLOMA

        monkeypatch.setattr(worker, "_recognise", reconocer)

        assert worker.process_document_job(self.payload()) == "registros"
        assert reconocidos == ["no-se-abre.pdf"]

    def test_declarar_diplomas_manda_sobre_separar_por_continuidad(self, monkeypatch):
        """Dos instrucciones incompatibles, y gana la que dice qué es el papel.

        Separar por continuidad no lee el documento, así que no puede saber de
        quién es cada hoja ni nombrar el archivo con su cédula. Medido sobre el
        libro 7: por esa ruta salieron 199 documentos numerados 001, 002, 003 y
        con el tipo equivocado, tres corridas seguidas.
        """
        import resolutions.api.worker as worker

        llamadas = []
        avisos = []
        monkeypatch.setattr(worker, "_record_split_job", lambda p, t: llamadas.append(t))
        monkeypatch.setattr(
            worker, "_segment_job", lambda *a, **k: pytest.fail("no debía segmentar")
        )
        monkeypatch.setattr(
            worker, "_anunciar", lambda p, stage, **k: avisos.append(k.get("detail"))
        )

        worker.process_document_job(self.payload(tipo="diploma", task="segment"))

        assert [str(t) for t in llamadas] == ["split"]
        # Y se dice: una elección que se cambia sin avisar es la forma más
        # rápida de que alguien deje de fiarse de la pantalla.
        assert any("no por continuidad" in (aviso or "") for aviso in avisos)

    def test_sin_declarar_nada_se_separa_por_continuidad_como_siempre(self, monkeypatch):
        import resolutions.api.worker as worker

        monkeypatch.setattr(worker, "_segment_job", lambda *a, **k: "continuidad")
        monkeypatch.setattr(worker, "_aviso_de_ruta", lambda *a, **k: [])
        monkeypatch.setattr(worker, "_anunciar", lambda *a, **k: None)

        assert worker.process_document_job(self.payload(task="segment")) == "continuidad"
