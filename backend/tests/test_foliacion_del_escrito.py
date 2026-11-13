"""El folio a mano de la esquina manda: 11 → 12 es el mismo escrito, el 1 abre otro.

Lo dictó el operador el 2026-11-12 sobre 7975593 («asegúrate de que cuando
exista el folio… el bot lo tenga en cuenta para dividir e inventariar») y eligió
que el folio mande sobre el sello «Recibido» de una copia anexa. Los folios de
estas pruebas son los que leyó la IA de las esquinas de UPD2460819.
"""

from __future__ import annotations

from resolutions.api.worker.correspondencia import marcas_de_las_hojas
from resolutions.application.foliacion import aplicar_la_foliacion
from resolutions.application.ports import VeredictoDeCostura
from resolutions.application.revisor_de_cortes import Patrones, revisar_los_cortes
from resolutions.domain.foliacion_del_escrito import foliacion_del_escrito
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.revision_de_cortes import (
    Decision,
    huella_para_la_ia,
    revisar_costuras,
)
from resolutions.domain.sello import Sello

#: Hojas 55-64 y 92-101 de UPD2460819, como las leyó la IA: la 55 salió «4»
#: por «5», y la 95 vuelve a 1 con el recurso siguiente.
LEIDOS = {
    55: 4, 56: 6, 57: 6, 58: 7, 59: 8, 60: 9, 61: 10, 62: 11, 63: 12, 64: 13,
    92: 42, 93: 43, 94: 44, 95: 1, 96: 2, 97: 3, 98: 4, 99: 5, 100: 6, 101: 7,
}


def _grupos(*documentos) -> GroupingResult:
    return GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=f"{i:02d}", raw=f"{i:02d}"), page_numbers=list(p))
            for i, p in enumerate(documentos, start=1)
        ]
    )


class TestLoQueDiceElFolio:
    def test_el_que_sigue_continua_y_el_uno_abre(self):
        foliacion = foliacion_del_escrito(LEIDOS, range(55, 102))
        assert 63 in foliacion.continua  # 11 → 12: el recurso de 52-94 no se parte
        assert foliacion.abre == frozenset({95})
        assert 95 not in foliacion.continua

    def test_el_folio_mal_leido_o_que_falta_no_rompe_la_numeracion(self):
        foliacion = foliacion_del_escrito(LEIDOS, range(55, 102))
        assert {56, 57, 58} <= foliacion.continua

    def test_el_reverso_sin_folio_sigue_con_su_escrito(self):
        """El 03 de 7975593: facturas por las dos caras, una sola foliada."""
        foliacion = foliacion_del_escrito({16: 6, 18: 7}, range(15, 20))
        assert {17, 18} <= foliacion.continua

    def test_un_uno_mal_leido_en_medio_no_abre(self):
        foliacion = foliacion_del_escrito({10: 11, 11: 1, 12: 13}, range(10, 13))
        assert foliacion.abre == frozenset()

    def test_un_folio_mal_leido_no_rompe_la_numeracion(self):
        """UPD2460819: la 134 se leyó «47» por «41»; la 135 (43) encaja con la 132 (39)."""
        foliacion = foliacion_del_escrito({130: 37, 131: 38, 132: 39, 134: 47, 135: 43}, range(130, 136))
        assert {133, 134, 135} <= foliacion.continua

    def test_el_uno_leido_como_siete(self):
        """UPD2460819 110-115: 16, «77», «78», «79», 20, «27» son 16, 17, 18, 19, 20, 21."""
        foliacion = foliacion_del_escrito({110: 16, 111: 77, 112: 78, 113: 79, 114: 20, 115: 27}, range(110, 116))
        assert set(range(111, 116)) <= foliacion.continua

    def test_la_foliacion_vieja_de_una_copia_no_abre(self):
        """UPD2460819 207-210: la copia anexa trae 1, 2, 3, 4; la 211 sigue en el 18 detrás de la 205 en el 12."""
        folios = {203: 9, 204: 10, 205: 12, 207: 1, 208: 2, 209: 3, 210: 4, 211: 18, 212: 19}
        foliacion = foliacion_del_escrito(folios, range(203, 213))
        assert foliacion.abre == frozenset()
        assert set(range(206, 213)) <= foliacion.continua

    def test_al_acabarse_la_numeracion_abre_la_carta(self):
        """UPD2460819: la solicitud de la 175 detrás del folio 26 de la queja (su esquina se leyó «6100»)."""
        folios = {173: 25, 174: 26, 175: 6100}
        foliacion = foliacion_del_escrito(folios, range(172, 177), abren_solas={175})
        assert 175 in foliacion.abre

    def test_el_reverso_del_recibo_no_abre(self):
        """El operador: «la primera página tiene su folio pero la segunda no… son un folio»."""
        foliacion = foliacion_del_escrito({22: 9, 23: 10}, range(22, 26), abren_solas={25})
        assert 24 not in foliacion.abre
        assert foliacion.abre == frozenset()

    def test_sin_folios_no_dice_nada(self):
        foliacion = foliacion_del_escrito({}, range(1, 10))
        assert not foliacion.continua and not foliacion.abre

    def test_lejos_no_cuenta(self):
        assert foliacion_del_escrito({10: 3, 20: 4}, range(10, 21)).continua == frozenset()


class TestElFolioManda:
    def test_une_lo_que_el_sello_de_una_copia_partio(self):
        """7975593: el sello «Recibido» de la copia partía el recurso 52-94 en 52-62 y 63-94."""
        foliacion = foliacion_del_escrito({p: p - 51 for p in range(52, 95)}, range(52, 95))
        resultado = aplicar_la_foliacion(_grupos(range(52, 63), range(63, 95)), {}, foliacion)
        assert [g.page_numbers for g in resultado.grupos.groups] == [list(range(52, 95))]
        assert resultado.unidas[0] == 63

    def test_lo_que_el_folio_no_ata_se_queda_donde_esta(self):
        """La queja de 149-174 y la solicitud de la 175, sola (su folio se leyó «6100»)."""
        folios = {**{p: p - 148 for p in range(149, 175)}, 176: 1, 177: 2}
        foliacion = foliacion_del_escrito(folios, range(149, 178))
        resultado = aplicar_la_foliacion(_grupos(range(149, 173), [173, 174, 175], [176, 177]), {}, foliacion)
        assert [g.page_numbers for g in resultado.grupos.groups] == [
            list(range(149, 175)),
            [175],
            [176, 177],
        ]

    def test_parte_donde_el_folio_vuelve_a_uno(self):
        """La 95 abre el recurso siguiente aunque el corte la dejara pegada."""
        foliacion = foliacion_del_escrito({93: 43, 94: 44, 95: 1, 96: 2}, range(90, 100))
        resultado = aplicar_la_foliacion(_grupos(range(90, 100)), {}, foliacion)
        assert [g.page_numbers for g in resultado.grupos.groups] == [list(range(90, 95)), list(range(95, 100))]
        assert resultado.partidas == (95,)

    def test_sin_folios_nada_cambia(self):
        grupos = _grupos([1, 2], [3])
        assert aplicar_la_foliacion(grupos, {"02": [3]}, foliacion_del_escrito({}, range(1, 4))).grupos is grupos

    def test_los_anexos_siguen_a_sus_hojas(self):
        foliacion = foliacion_del_escrito({2: 2, 3: 3}, range(1, 5))
        resultado = aplicar_la_foliacion(_grupos([1, 2], [3, 4], [5]), {"02": [4]}, foliacion)
        # Sólo la hoja que el folio ata; la 4 se queda con su anexo.
        assert [g.page_numbers for g in resultado.grupos.groups] == [[1, 2, 3], [4], [5]]
        assert resultado.anexos == {"02": [4]}


class TestLosAgentesRazonanConElFolio:
    def test_el_folio_que_sigue_es_prueba_fuerte_contra_un_corte(self):
        costuras = revisar_costuras([[61, 62], [63, 64]], {}, folios={61: 10, 62: 11, 63: 12, 64: 13})
        costura = next(c for c in costuras if c.derecha == 63)
        assert costura.decision is Decision.CORTE
        assert any(p.fuerte and "folio 12" in p.motivo for p in costura.pruebas)
        assert costura.fuera_del_margen

    def test_el_folio_uno_es_prueba_fuerte_contra_una_union(self):
        costuras = revisar_costuras([[93, 94, 95, 96]], {}, folios={93: 43, 94: 44, 95: 1, 96: 2})
        costura = next(c for c in costuras if c.derecha == 95)
        assert costura.decision is Decision.UNION
        assert any(p.fuerte and "folio 1" in p.motivo for p in costura.pruebas)

    def test_la_ia_ve_las_marcas_de_cada_hoja(self):
        assert huella_para_la_ia(63, "texto", marcas="folio a mano 12")["marcas"] == "folio a mano 12"
        assert "marcas" not in huella_para_la_ia(63, "texto")

    def test_las_marcas_dicen_folio_y_sello(self):
        from datetime import date

        marcas = marcas_de_las_hojas(
            {95: 1}, {95: Sello("tinta", "RE2310202103442", date(2021, 5, 20), 43)}, {175: Sello("tinta", None)}
        )
        assert marcas[95] == "folio a mano 1; sello de radicación RE2310202103442 del 20/05/2021, 43 folios"
        assert marcas[175] == "sello de radicación al pie"

    def test_el_revisor_le_pasa_las_marcas_y_guarda_su_razon(self):
        class Juez:
            def __init__(self):
                self.hojas = []

            def decidir(self, hojas, costuras, reglas):
                self.hojas.extend(hojas)
                return {c: VeredictoDeCostura("continua", "12", razon="el folio 12 sigue al 11") for c in costuras}

        juez = Juez()
        revision = revisar_los_cortes(
            _grupos([61, 62], [63, 64]),
            {p: f"hoja {p}" for p in range(61, 65)},
            Patrones(folios={61: 10, 62: 11, 63: 12, 64: 13}, marcas={63: "folio a mano 12"}),
            juez=juez,
        )
        assert [g.page_numbers for g in revision.grupos.groups] == [[61, 62, 63, 64]]
        assert any(h.get("marcas") == "folio a mano 12" for h in juez.hojas)
        assert "el folio 12 sigue al 11" in revision.movimientos[0].motivo


class TestLosFoliosDelSello:
    """El «No. DE FOLIOS» del sello de tinta, como lo transcribió la IA en 7975593."""

    def test_la_cifra_con_su_palabra_delante(self):
        from resolutions.domain.sello import folios_del_sello_de_tinta

        assert folios_del_sello_de_tinta("RECIBIDO NO IMPLICA ACEPTACIÓN\nNo DE FOLIOS: (5) cinco Folios\n") == 5

    def test_la_cifra_sola_y_no_el_numero_interno(self):
        from resolutions.domain.sello import folios_del_sello_de_tinta

        hoja_315 = (
            "RECIBIDO NO IMPLICA ACERTACION\nNo DE RADICACION: RE 2310202215174.\n"
            "No DE FOLIOS: 202260173102.\nD.R. NOTIFICACION: 8 folios.\n"
        )
        assert folios_del_sello_de_tinta(hoja_315) == 8
        assert folios_del_sello_de_tinta("RECIBIDO NO IMPLICA ACEPTACIÓN\nNo DE FOLIOS: 10\n") == 10

    def test_la_palabra_y_la_cifra_que_no_coinciden_no_valen(self):
        from resolutions.domain.sello import folios_del_sello_de_tinta

        assert folios_del_sello_de_tinta("RECIBIDO NO IMPLICA ACEPTACIÓN\nNo DE FOLIOS: DOCE (42)\n") is None


class TestLoQueDevuelveLaIa:
    """Lo que el OCR de pago devolvió de los mosaicos de UPD2460819, tal cual."""

    def test_el_folio_con_su_punto_y_sin_el_importe_ni_el_nic(self):
        from resolutions.adapters.esquinas_del_folio import folios_etiquetados

        texto = (
            "|  P141 | 1.  |\n| --- | --- |\n|  P142 | 2.  |\n|  P144 | 4.  |\n|   | 7975593  |\n"
            "|  P145 | 7975593  |\n|  P146 | 1.  |\n|  P91 | $ 142.890  |"
        )
        assert folios_etiquetados(texto, [91, 141, 142, 144, 145, 146]) == {141: 1, 142: 2, 144: 4, 146: 1}

    def test_la_imagen_que_mete_el_ocr_no_es_un_folio(self):
        from resolutions.adapters.esquinas_del_folio import folios_etiquetados

        texto = "P153\n\n![img-0.jpeg](img-0.jpeg)\n\n5.\n\nP155\n\n![img-1.jpeg](img-1.jpeg)\n\n7."
        assert folios_etiquetados(texto, [153, 155]) == {153: 5, 155: 7}
