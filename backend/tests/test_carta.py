"""Las cartas de un trámite: dónde empiezan, cómo siguen y cuándo son una copia.

Lo pidió el operador el 2026-10-21 ante UPD3102756: «cada trámite va solo,
obviamente con sus respectivos anexos», y los duplicados «la mayoría de veces
son anexos a trámites diferentes, o sea como pruebas». Los textos son los de
esa caja, como los dejó su capa de texto.
"""

from __future__ import annotations

from datetime import date

from resolutions.application.cartas import Cartas
from resolutions.application.sellos import ajustar_por_cartas
from resolutions.domain.carta import (
    abre_carta,
    cita_el_numero,
    continua_la_carta,
    es_la_misma_carta,
    huella_de_la_carta,
)
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.sello import Sello

COMITE = (
    "COMITE DE DESARROLLO Y CONTROL SOCIAL DE LOS SERVICIOS\n"
    "PUBLICOS DOMICILIARIOS DE MAGANGUE BOLIVAR\n"
)


def _reclamo(dia: str, mes: str) -> str:
    return (
        COMITE + f"Magangue Bolívar {dia} de {mes} del 2024.\n"
        "Señores AFINIA CARIBEMAR S.A.E.S.P.\n"
        "ASUNTO: Reclamo por alto consumo y alto costo en la factura del mes de\n"
        f"{mes} y cobro de monto sin saber de qué se trata. NIC.1004303.\n"
        "En atención al derecho que tenemos los ciudadanos a presentar peticiones de\n"
    )


PETICIONES = (
    "Peticiones.\n"
    "Que la empresa no genere orden de suspensión del servicio mientras este en\n"
    "objeto de reclamo la factura así lo dice el art.155 ley 142.\n"
    "Atentamente\nCesar Augusto Rojas Diaz.\nC.C.91.282.242.\nANEXO: FACTURAS OBJETO DE RECLAMO.\nVo.Bo . VOCAL DE CONTROL\n"
)
SILENCIO = (
    "RV'¿5lD202'ilir92\nOFICINA\nBOLIVAR SUR\n"
    "Magangue Bolívar, Noviembre 14 del 2023.\nSeñores.\nCARIBEMAR S.A. E. S.P. Magangue Bolívar.\n"
    "Cordial Saludo.\n"
    "Asunto; Solicitud de reconocimiento de silencio administrativo positivo por no\n"
    "dar respuesta dentro de los terminos .\nNIC.1004303\n"
)
FACTURA = "aFimá\nOperador de Red: Caribemar de la Costa S.A.S E.S.P\nNIU:21381594\nFactura No.: 1004303042\n"


class TestLaCartaAbre:
    def test_su_primera_hoja_con_saludo_fecha_y_asunto(self):
        assert abre_carta(_reclamo("11", "Marzo"))
        assert abre_carta(SILENCIO)

    def test_el_asunto_del_sello_no_es_una_carta(self):
        assert not abre_carta("Caribemar de la Costa\nAsunto: 03 RECLAMO Folios: 3\nFecha: 08/09/2021\n")

    def test_la_hoja_con_el_encabezado_pero_sin_asunto_no_abre(self):
        """UPD3102756 pág. 15: la primera hoja se imprimió casi en blanco."""
        assert not abre_carta("Magangue Bolivar, Noviembre 14 del 2023.\nSeñores\nCARIBEMAR S.A. E. S.P.\n")


class TestLaHojaQueSigue:
    def test_las_peticiones_la_frase_en_minuscula_y_el_numeral(self):
        assert continua_la_carta(PETICIONES)
        assert continua_la_carta("PETiCfONES\nQue la prestadora corrija el cobro por estimado\n")
        assert continua_la_carta(
            "acompañarme un técnico que me asesorara pero la empresa todo lo realizó sola\n"
        )
        assert continua_la_carta("2) porque al respecto le comunico a la prestadora que soy muy cuidadoso\n")

    def test_el_logo_de_la_factura_no_es_prosa(self):
        assert not continua_la_carta(FACTURA)

    def test_la_carta_nueva_no_sigue_a_la_anterior(self):
        assert not continua_la_carta(_reclamo("11", "Abril"))


class TestLaCopia:
    def test_la_misma_fecha_y_el_mismo_asunto_es_la_misma_carta(self):
        copia = "^^S¿Í22£232n52\nTOj\n" + SILENCIO.split("OFICINA\nBOLIVAR SUR\n", 1)[1]
        assert es_la_misma_carta(huella_de_la_carta(SILENCIO), huella_de_la_carta(copia))

    def test_los_reclamos_del_mes_con_la_misma_plantilla_son_cartas_distintas(self):
        """El asunto parte justo antes del mes: sin el renglón que sigue, marzo y abril eran una copia."""
        assert not es_la_misma_carta(
            huella_de_la_carta(_reclamo("11", "Marzo")), huella_de_la_carta(_reclamo("11", "Abril"))
        )


class TestLaCita:
    def test_la_carta_cita_el_radicado_de_la_superintendencia_con_una_letra_por_cifra(self):
        """UPD3102756 pág. 23: «Radicado No.202380Ú4468522» por el 20238004468522 de la 24."""
        assert cita_el_numero("fue radicada el 22 de Noviembre del 2023 con Radicado No.202380Ú4468522.", "20238004468522")
        assert not cita_el_numero("Radicado No. 20239999999999", "20238004468522")


def _grupos(*tramos: list[int]) -> GroupingResult:
    return GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=f"{i:02d}", raw=f"{i:02d}"), page_numbers=list(t))
            for i, t in enumerate(tramos, start=1)
        ]
    )


class TestLaCajaDelComite:
    """La forma de UPD3102756, en pequeño: cada carta abre, lo suyo va con ella."""

    TEXTOS = {
        1: _reclamo("11", "Marzo"),
        2: PETICIONES,
        3: FACTURA,
        # El reclamo de abril, pegado por la continuidad a la factura de marzo.
        4: _reclamo("11", "Abril"),
        # Su segunda hoja, con el sello de la ventanilla al pie.
        5: PETICIONES,
        6: FACTURA,
        7: SILENCIO,
        # La misma petición, otra vez: la prueba que trae el aviso de la 7.
        8: "^^S¿Í22£232n52\nTOj\n" + SILENCIO.split("OFICINA\nBOLIVAR SUR\n", 1)[1],
    }
    SELLOS = {5: Sello("tinta"), 7: Sello("tinta"), 8: Sello("tinta", fecha=date(2023, 11, 14))}

    def test_las_senales(self):
        cartas = Cartas.de(self.TEXTOS, self.SELLOS)
        assert cartas.primeras == {1, 4, 7, 8}
        # Sólo el escrito del trámite abre por ser carta: no la «SOLICITUD» a
        # secas, que también titula los formularios (UPD2555087 pág. 4).
        assert cartas.de_tramite == {1, 4}
        assert cartas.siguen == {2, 5}
        assert cartas.copias == {8}
        # El sello al pie de la hoja que sigue y el de la copia no abren.
        assert cartas.no_abren >= {5, 8}
        assert cartas.que_abren({7: Sello("tinta")}) == {1, 4}

    def test_cada_carta_en_su_documento_con_lo_suyo(self):
        cartas = Cartas.de(self.TEXTOS, self.SELLOS)
        # Como lo dejó la continuidad: 1 | 2-4 | 5 | 6 | 7 | 8.
        grupos, anexos, abiertas, unidas = ajustar_por_cartas(
            _grupos([1], [2, 3, 4], [5], [6], [7], [8]),
            abren=cartas.que_abren({7: Sello("tinta")}),
            siguen=cartas.siguen,
            pruebas=cartas.pruebas,
        )
        assert [g.page_numbers for g in grupos.groups] == [[1, 2, 3], [4, 5], [6], [7, 8]]
        assert abiertas == [4] and unidas == [2, 5, 8]
        # La copia es anexo del documento que la trae; la hoja que sigue, la carta.
        assert anexos == {"04": [8]}
        assert [g.code.value for g in grupos.groups] == ["01", "02", "03", "04"]

    def test_la_carta_dentro_de_los_folios_de_un_sello_no_abre(self):
        cartas = Cartas.de(self.TEXTOS, self.SELLOS)
        assert 4 not in cartas.que_abren({1: Sello("impreso", folios=6)})
