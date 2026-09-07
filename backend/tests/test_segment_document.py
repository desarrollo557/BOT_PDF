"""El caso de uso completo, sin gastar un token.

El oráculo se reemplaza por un doble porque lo que hay que probar no es si el
modelo acierta: es que solo se le pregunte lo que hace falta, que su respuesta se
respete, y que cuando no conteste el documento salga igual de partido con lo que
la estructura ya sabía.
"""

import pytest

from resolutions.application.control import Cancelled
from resolutions.application.ports import BoundaryOracle
from resolutions.application.segment_document import SegmentDocument
from resolutions.domain.errors import IntegrityError
from resolutions.domain.segmentation import Verdict


class Caja:
    """Una fuente de páginas de mentira, con el texto que se le pase."""

    def __init__(self, textos: list[str]):
        self._textos = textos

    @property
    def page_count(self) -> int:
        return len(self._textos)

    def text_of(self, page_number: int) -> str:
        return self._textos[page_number - 1]

    def boxes_of(self, page_number: int) -> list:
        return []

    def render(self, page_number, band=None, dpi=200) -> bytes:
        return b""

    def close(self) -> None:
        return None


class CajaSinGeometria(Caja):
    """Una fuente que no sabe dónde están sus renglones y lo dice fallando."""

    def boxes_of(self, page_number: int) -> list:
        raise NotImplementedError("esta fuente no tiene geometría")


class OraculoQueCuenta:
    def __init__(self, respuestas=None):
        self.respuestas = respuestas or {}
        self.llamadas = 0
        self.costuras_vistas = None
        self.paginas_vistas = None

    def judge(self, pages, seams):
        self.llamadas += 1
        self.costuras_vistas = list(seams)
        self.paginas_vistas = pages
        return self.respuestas


class OraculoCaido:
    def judge(self, pages, seams):
        raise RuntimeError("503 del proveedor")


#: Las páginas 3 a 7 del expediente real: el papel se cuenta solo.
CON_PAGINACION = [
    "aFinia Consecutivo No.202170183712 AGUSTIN CODAZZI, 08/07/2021 Página 1 de 5",
    "continuación del análisis Página 2 de 5",
    "más análisis Página 3 de 5",
    "todavía más Página 4 de 5",
    "Cordialmente, YUDIS PAREDES Página 5 de 5",
]

#: Tres hojas genuinamente ambiguas: prosa corrida, sin membrete, sin fecha, sin
#: paginación, sin rótulo y sin anuncio de anexos. Tienen que ser largas o la
#: regla de legibilidad las une por no haber dicho nada, que es otro caso
#: distinto y tiene sus propias pruebas.
SIN_MARCAS = [
    "El usuario manifiesta que no está de acuerdo con la lectura registrada "
    "por el operador de red durante el periodo objeto de revisión.",
    "Sobre el particular se precisa que la empresa adelantó las verificaciones "
    "técnicas previstas en el contrato de condiciones uniformes.",
    "Por lo expuesto se concluye que la actuación se ajustó a lo previsto en "
    "la normatividad vigente y al contrato suscrito con el suscriptor.",
]


class TestElContratoDelPuerto:
    def test_los_adaptadores_cumplen_el_protocolo(self):
        from resolutions.adapters.boundary_prompt import NullBoundaryOracle

        assert isinstance(NullBoundaryOracle(), BoundaryOracle)
        assert isinstance(OraculoQueCuenta(), BoundaryOracle)


class TestLoQueSeResuelveGratisNoSePregunta:
    def test_una_caja_con_paginacion_no_llama_al_modelo(self):
        oraculo = OraculoQueCuenta()
        resultado = SegmentDocument(oraculo).run(Caja(CON_PAGINACION))

        assert oraculo.llamadas == 0
        assert [s.page_numbers for s in resultado.segments] == [[1, 2, 3, 4, 5]]

    def test_solo_las_costuras_dudosas_viajan(self):
        oraculo = OraculoQueCuenta()
        SegmentDocument(oraculo).run(Caja(CON_PAGINACION + SIN_MARCAS))

        assert oraculo.llamadas == 1
        # Las cuatro costuras internas del documento paginado se resolvieron
        # gratis; solo viajan las que quedaron sin evidencia.
        assert (1, 2) not in oraculo.costuras_vistas
        assert (6, 7) in oraculo.costuras_vistas

    def test_se_pregunta_una_sola_vez_por_caja(self):
        oraculo = OraculoQueCuenta()
        SegmentDocument(oraculo).run(Caja(SIN_MARCAS * 4))
        assert oraculo.llamadas == 1

    def test_el_modelo_ve_la_caja_entera_no_solo_las_dudas(self):
        """Ver todo es lo que le permite saber que 12 a 15 son la misma acta."""
        oraculo = OraculoQueCuenta()
        SegmentDocument(oraculo).run(Caja(CON_PAGINACION + SIN_MARCAS))
        assert len(oraculo.paginas_vistas) == 8


class TestLaRespuestaDelModeloSeRespeta:
    def test_un_corte_del_modelo_parte_el_documento(self):
        oraculo = OraculoQueCuenta({(1, 2): True, (2, 3): False})
        resultado = SegmentDocument(oraculo).run(Caja(SIN_MARCAS))
        assert [s.page_numbers for s in resultado.segments] == [[1], [2, 3]]

    def test_queda_registrado_que_no_lo_decidio_la_estructura(self):
        oraculo = OraculoQueCuenta({(1, 2): False, (2, 3): False})
        resultado = SegmentDocument(oraculo).run(Caja(SIN_MARCAS))
        decididas = [b for b in resultado.boundaries if not b.deterministic]
        assert len(decididas) == 2

    def test_una_costura_que_el_modelo_no_contesta_queda_dudosa(self):
        oraculo = OraculoQueCuenta({(1, 2): False})
        resultado = SegmentDocument(oraculo).run(Caja(SIN_MARCAS))
        pendientes = [(b.left, b.right) for b in resultado.undecided]
        assert pendientes == [(2, 3)]

    def test_el_modelo_no_puede_pisar_lo_que_la_estructura_decidio(self):
        """Si el papel dice "3 de 5", eso no se discute."""
        oraculo = OraculoQueCuenta({(1, 2): True, (2, 3): True})
        resultado = SegmentDocument(oraculo).run(Caja(CON_PAGINACION))
        assert all(b.deterministic for b in resultado.boundaries)


class TestCuandoElProveedorSeCae:
    def test_la_caja_sale_partida_igual(self):
        resultado = SegmentDocument(OraculoCaido()).run(Caja(CON_PAGINACION + SIN_MARCAS))
        resultado.verify_integrity(list(range(1, 9)))
        assert resultado.segments[0].page_numbers == [1, 2, 3, 4, 5]

    def test_las_dudas_quedan_para_revision_no_para_adivinanza(self):
        resultado = SegmentDocument(OraculoCaido()).run(Caja(SIN_MARCAS))
        assert all(b.verdict is Verdict.UNDECIDED for b in resultado.boundaries)

    def test_sin_oraculo_configurado_funciona_igual(self):
        resultado = SegmentDocument().run(Caja(CON_PAGINACION))
        assert [s.page_numbers for s in resultado.segments] == [[1, 2, 3, 4, 5]]


class TestLaGeometriaEsOpcional:
    def test_una_fuente_sin_renglones_no_rompe_nada(self):
        resultado = SegmentDocument().run(CajaSinGeometria(CON_PAGINACION))
        assert [s.page_numbers for s in resultado.segments] == [[1, 2, 3, 4, 5]]


class TestNadaSePierde:
    def test_toda_pagina_cae_en_un_segmento(self):
        resultado = SegmentDocument(OraculoQueCuenta()).run(Caja(CON_PAGINACION + SIN_MARCAS))
        resultado.verify_integrity(list(range(1, 9)))
        repartidas = [p for s in resultado.segments for p in s.page_numbers]
        assert sorted(repartidas) == list(range(1, 9))

    def test_una_caja_vacia_no_produce_segmentos(self):
        assert SegmentDocument().run(Caja([])).segments == []

    def test_una_caja_de_una_pagina_produce_un_segmento(self):
        resultado = SegmentDocument().run(Caja(["hoja suelta"]))
        assert [s.page_numbers for s in resultado.segments] == [[1]]

    def test_la_verificacion_denuncia_una_pagina_ajena(self):
        resultado = SegmentDocument().run(Caja(SIN_MARCAS))
        with pytest.raises(IntegrityError):
            resultado.verify_integrity([1, 2, 3, 4])


class TestSePuedeParar:
    """Una caja de cuatrocientas hojas tarda, y el operador puede arrepentirse.

    Se pregunta entre una página y la siguiente, que es donde no hay nada a
    medio hacer, y una vez más antes de gastar la pregunta al modelo. Ese
    segundo sitio no es simetría: es el único punto del recorrido donde seguir
    cuesta dinero.
    """

    def test_cancelar_abandona_la_caja_donde_este(self):
        class CancelaTrasLaTercera:
            def __init__(self):
                self.consultas = 0

            def check(self):
                self.consultas += 1
                if self.consultas > 3:
                    raise Cancelled("basta")

        control = CancelaTrasLaTercera()
        with pytest.raises(Cancelled):
            SegmentDocument(control=control).run(Caja(["hoja" for _ in range(20)]))
        assert control.consultas < 20, "no debería haber leído la caja entera"

    def test_sin_control_se_lee_la_caja_entera(self):
        """Se cuenta por costuras y no por segmentos: cinco hojas dan cuatro.

        Contar segmentos medía esto sólo mientras la duda cortaba. Ahora une, y
        cinco hojas mudas son un documento -- que es lo correcto y no dice nada
        sobre si se leyeron las cinco.
        """
        resultado = SegmentDocument().run(Caja(["hoja" for _ in range(5)]))
        assert len(resultado.boundaries) == 4

    def test_una_caja_cancelada_no_se_le_pregunta_al_modelo(self):
        """Pagar una consulta por un trabajo que el operador ya abandonó."""

        class CancelaAlTerminarDeLeer:
            def __init__(self, paginas: int):
                self.consultas = 0
                self._paginas = paginas

            def check(self):
                self.consultas += 1
                if self.consultas > self._paginas:
                    raise Cancelled("basta")

        oraculo = OraculoQueCuenta()
        with pytest.raises(Cancelled):
            # Dos hojas genuinamente ambiguas: si no lo fueran, la estructura las
            # resolvería, no habría nada que preguntar y la cancelación no
            # llegaría a probar lo que esta prueba dice probar.
            SegmentDocument(oraculo, control=CancelaAlTerminarDeLeer(2)).run(
                Caja(SIN_MARCAS[:2])
            )
        assert oraculo.llamadas == 0
