"""El PDF dividido con dos o más sellos de RE distinto: se avisa y lo revisa el agente.

Lo pidió el operador el 2026-11-12: «cuando en la habilidad de Afinia me
dividas un PDF y tenga más de 2 sellos, me avises». Precisó: desde dos sellos,
contando cada RE una vez; el aviso en la auditoría y en el Excel de informe de
procesamiento; y que lo revise el agente. El caso de origen es 1005965: dos
derechos de petición, cada uno con su sello, en un solo PDF.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from resolutions.api.indices import fila_de_proceso
from resolutions.api.worker.correspondencia import (
    VARIOS_SELLOS_CONFIRMADO,
    VARIOS_SELLOS_EN_REVISION,
    _res_de_los_sellos,
    aviso_de_varios_sellos,
    pdf_con_varios_sellos,
)
from resolutions.application.auditoria_de_la_entrega import avisos_de_varios_sellos
from resolutions.application.ports import VeredictoDeCostura
from resolutions.application.revisor_de_cortes import Patrones, revisar_los_cortes
from resolutions.domain.conciliacion import ArchivoEntregado
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.revision_de_cortes import (
    Decision,
    costuras_de_los_sellos,
    revisar_costuras,
)
from resolutions.domain.sello import Sello, re_del_sello, res_del_documento

RE_1 = "RE2311202302499"
RE_2 = "RE2311202302952"
TEXTOS = {p: f"hoja {p} con su texto" for p in range(1, 9)}


def _grupos(*documentos: list[int]) -> GroupingResult:
    return GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=f"{i:02d}", raw=f"{i:02d}"), page_numbers=list(p))
            for i, p in enumerate(documentos, start=1)
        ]
    )


class _Juez:
    def __init__(self, decision: str):
        self.decision = decision
        self.preguntas: list = []

    def decidir(self, hojas, costuras, reglas):
        self.preguntas.append((hojas, costuras, reglas))
        return {c: VeredictoDeCostura(self.decision, "DERECHO DE PETICION Señores AFINIA") for c in costuras}


class TestLosReDeUnPdf:
    def test_el_mismo_re_cuenta_una_vez(self):
        assert res_del_documento([1, 2, 3, 4], {1: RE_1, 3: RE_1}) == [(1, RE_1)]

    def test_dos_re_distintos_en_el_orden_del_papel(self):
        assert res_del_documento([4, 1, 2, 3], {3: RE_2, 1: RE_1, 4: RE_1}) == [(1, RE_1), (3, RE_2)]

    def test_la_hoja_sin_re_no_cuenta(self):
        assert res_del_documento([1, 2], {}) == []

    def test_el_re_que_se_cree_de_cada_sello(self):
        assert re_del_sello(Sello("impreso", "re3110202139039")) == ("RE3110202139039", "")
        assert re_del_sello(Sello("impreso", "RE31102021")) == (None, "")
        assert re_del_sello(Sello("tinta", None)) == (None, "")
        # El de tinta, validado por el agente: la oficina leída a una cifra.
        assert re_del_sello(Sello("tinta", "RE2371202302499", date(2023, 8, 28)))[0] == RE_1
        assert re_del_sello(Sello("tinta", RE_1, date(2022, 1, 3)))[0] is None

    def test_los_del_pie_y_los_de_arriba(self):
        res = _res_de_los_sellos(
            {1: Sello("impreso", RE_1)}, {4: Sello("tinta", RE_2, date(2023, 9, 1)), 1: Sello("tinta", None)}, set()
        )
        assert res == {1: RE_1, 4: RE_2}


class TestLaCosturaQuePonenEnDuda:
    def test_el_sello_de_cabeza_pone_en_duda_la_costura_de_su_hoja(self):
        marcadas = costuras_de_los_sellos([[1, 2, 3, 4]], {1: RE_1, 3: RE_2})
        assert list(marcadas) == [3]
        assert RE_2 in marcadas[3] and RE_1 in marcadas[3]

    def test_el_sello_al_pie_pone_en_duda_las_que_siguen_al_anterior(self):
        """1005965: el sello va junto a la firma, al final de su escrito."""
        marcadas = costuras_de_los_sellos([[1, 2, 3, 4, 5, 6, 7]], {2: RE_1, 7: RE_2}, al_pie={2, 7})
        assert list(marcadas) == [3, 4, 5, 6]

    def test_un_solo_re_no_pone_nada_en_duda(self):
        assert costuras_de_los_sellos([[1, 2, 3]], {1: RE_1, 3: RE_1}) == {}

    def test_la_prueba_es_debil_y_queda_fuera_del_margen(self):
        costuras = revisar_costuras([[1, 2, 3, 4]], TEXTOS, sellos={1: RE_1, 3: RE_2})
        costura = next(c for c in costuras if c.derecha == 3)
        assert costura.decision is Decision.UNION
        assert costura.fuera_del_margen and not costura.error_seguro
        assert costura.propuesta.paginas == (3, 4) and costura.propuesta.hacia is None
        assert all(not c.fuera_del_margen for c in costuras if c.derecha != 3)

    def test_sin_sellos_la_auditoria_revisa_como_siempre(self):
        assert all(not c.fuera_del_margen for c in revisar_costuras([[1, 2, 3, 4]], TEXTOS))


class TestLoRevisaElAgente:
    PATRONES = Patrones(sellos={1: RE_1, 3: RE_2})

    def test_con_la_ia_que_dice_que_abre_se_parte(self):
        juez = _Juez("abre")
        revision = revisar_los_cortes(_grupos([1, 2, 3, 4]), TEXTOS, self.PATRONES, juez=juez)
        assert sorted(g.page_numbers for g in revision.grupos.groups) == [[1, 2], [3, 4]]
        assert revision.movimientos[0].por == "la IA"
        assert len(juez.preguntas) == 1
        # La IA sabe la regla de los dos sellos.
        assert "RE distinto" in juez.preguntas[0][2] or juez.preguntas[0][2] == ""

    def test_con_la_ia_que_dice_que_sigue_queda_confirmado(self):
        revision = revisar_los_cortes(_grupos([1, 2, 3, 4]), TEXTOS, self.PATRONES, juez=_Juez("continua"))
        assert [g.page_numbers for g in revision.grupos.groups] == [[1, 2, 3, 4]]
        assert revision.confirmadas_por_la_ia == 1

    def test_sin_ia_va_a_revision_y_no_se_mueve(self):
        revision = revisar_los_cortes(_grupos([1, 2, 3, 4]), TEXTOS, self.PATRONES)
        assert [g.page_numbers for g in revision.grupos.groups] == [[1, 2, 3, 4]]
        assert [p for p, _ in revision.en_revision] == [3]
        assert "OCR + IA" in revision.en_revision[0][1]


class TestElAviso:
    def test_lo_que_el_agente_no_decidio_va_en_revision(self):
        revision = revisar_los_cortes(_grupos([1, 2, 3, 4]), TEXTOS, Patrones(sellos={1: RE_1, 3: RE_2}))
        varios = pdf_con_varios_sellos(
            [("UPD1/01_DERECHO-DE-PETICION.pdf", [1, 2, 3, 4])],
            {1: RE_1, 3: RE_2},
            explicados={},
            al_pie=frozenset(),
            revision=revision,
        )
        assert len(varios) == 1
        assert varios[0]["estado"] == VARIOS_SELLOS_EN_REVISION
        assert [s["re"] for s in varios[0]["sellos"]] == [RE_1, RE_2]
        assert RE_2 in varios[0]["motivo"]

    def test_lo_que_confirmo_la_ia(self):
        revision = revisar_los_cortes(
            _grupos([1, 2, 3, 4]), TEXTOS, Patrones(sellos={1: RE_1, 3: RE_2}), juez=_Juez("continua")
        )
        varios = pdf_con_varios_sellos(
            [("01_X.pdf", [1, 2, 3, 4])], {1: RE_1, 3: RE_2}, explicados={}, al_pie=frozenset(), revision=revision
        )
        assert varios[0]["estado"] == VARIOS_SELLOS_CONFIRMADO

    def test_lo_partido_ya_no_avisa(self):
        varios = pdf_con_varios_sellos(
            [("01_X.pdf", [1, 2]), ("02_X.pdf", [3, 4])], {1: RE_1, 3: RE_2}, explicados={}, al_pie=frozenset()
        )
        assert varios == []

    def test_la_copia_aportada_como_prueba_se_explica(self):
        varios = pdf_con_varios_sellos(
            [("01_X.pdf", [1, 2, 3])],
            {1: RE_1, 3: RE_2},
            explicados={3: "explicado: copia aportada como prueba"},
            al_pie=frozenset(),
        )
        assert varios[0]["estado"] == "explicado: copia aportada como prueba"

    def test_sin_revisor_va_en_revision(self):
        varios = pdf_con_varios_sellos(
            [("01_X.pdf", [1, 2, 3])], {1: RE_1, 3: RE_2}, explicados={}, al_pie=frozenset()
        )
        assert varios[0]["estado"] == VARIOS_SELLOS_EN_REVISION

    def test_el_resumen(self):
        varios = pdf_con_varios_sellos(
            [("UPD1/01_X.pdf", [1, 2, 3])], {1: RE_1, 3: RE_2}, explicados={}, al_pie=frozenset()
        )
        assert aviso_de_varios_sellos(varios) == f"1 PDF con 2 o más sellos: 01_X.pdf ({RE_1}, {RE_2}; en revisión)"
        assert aviso_de_varios_sellos([]) is None


class TestElExcelDeProcesos:
    def test_la_fila_lo_dice_en_sus_observaciones(self):
        varios = pdf_con_varios_sellos(
            [("UPD1/01_X.pdf", [1, 2, 3])], {1: RE_1, 3: RE_2}, explicados={}, al_pie=frozenset()
        )
        job = SimpleNamespace(
            report={"agrupar": "tramite", "page_count": 3, "groups": [{}], "review_queue": [], "varios_sellos": varios},
            state="done",
            filename="UPD1.pdf",
            agrupar="tramite",
            task="segment",
            tipo=None,
            lectura="ocr",
            progress=SimpleNamespace(page_count=3),
            started_at=None,
            finished_at=None,
            operator="",
            destination="",
            error=None,
        )
        assert "1 PDF con 2 o más sellos: 01_X.pdf" in fila_de_proceso(job).observaciones


class TestLaAuditoria:
    ARCHIVOS = (ArchivoEntregado("UPD1/01_X.pdf", (1, 2, 3)), ArchivoEntregado("UPD1/02_Y.pdf", (4,)))

    def _varios(self, estado: str) -> list[dict]:
        return [
            {
                "archivo": "UPD1/07_X.pdf",
                "paginas": [1, 2, 3],
                "sellos": [{"pagina": 1, "re": RE_1}, {"pagina": 3, "re": RE_2}],
                "estado": estado,
            }
        ]

    def test_lo_que_quedo_en_revision_es_una_duda(self):
        avisos, dudas = avisos_de_varios_sellos(self.ARCHIVOS, self._varios(VARIOS_SELLOS_EN_REVISION))
        assert avisos == []
        assert dudas == [f"«UPD1/01_X.pdf» trae 2 sellos de RE distinto: {RE_1} (pág. 1), {RE_2} (pág. 3); en revisión"]

    def test_lo_confirmado_es_un_aviso(self):
        avisos, dudas = avisos_de_varios_sellos(self.ARCHIVOS, self._varios(VARIOS_SELLOS_CONFIRMADO))
        assert dudas == [] and len(avisos) == 1

    def test_se_casa_por_las_hojas_no_por_el_nombre(self):
        """La carpeta del NIC renumera los PDF: el nombre de la constancia ya no es el del disco."""
        varios = self._varios(VARIOS_SELLOS_EN_REVISION)
        varios[0]["paginas"] = [1, 2]
        assert avisos_de_varios_sellos(self.ARCHIVOS, varios) == ([], [])
