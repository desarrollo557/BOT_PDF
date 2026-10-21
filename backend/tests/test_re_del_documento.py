"""El RE de cada documento, buscado en su sello (el operador, 2026-10-21).

«Búscalo en los sellos, ya sea que estén a mano o digitalizados… necesito que
todo quede bien referenciado y estructurado»: en UPD3102756, de trece archivos
sólo uno llevaba su RE, y ése con la oficina cambiada (RE4310… por RE2310…).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from resolutions.application.ports import Band
from resolutions.application.re_del_documento import CABECERA, PIE, poner_los_re
from resolutions.application.sellos import _sello_de_oficina
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.sello import Sello, radicado_del_texto, radicado_escrito


class TestLaOficina2310:
    def test_el_re_de_bolivar_sur_no_se_vuelve_4310(self):
        assert radicado_del_texto("RE2310202321592") == "RE2310202321592"

    def test_las_otras_oficinas_siguen_igual(self):
        assert radicado_del_texto("NUMERORE3110202139039") == "RE3110202139039"
        # La primera cifra mal leída de la 3110 se sigue corrigiendo.
        assert radicado_del_texto("NUMERORE7110202139039") == "RE3110202139039"


class TestElReEscrito:
    def test_a_mano_encima_del_sello(self):
        assert radicado_escrito("RE2310202321592\nOFICINA BOLIVAR SUR", 2023) == "RE2310202321592"

    def test_con_espacios_y_la_o_por_cero(self):
        assert radicado_escrito("RE 2310 2O23 21592", 2023) == "RE2310202321592"

    def test_de_otro_anio_que_su_carta_no_vale(self):
        """Una lectura mala que da otro año se descarta: no se inventa un RE."""
        assert radicado_escrito("RE2310201921592", 2023) is None

    def test_la_carta_de_diciembre_radicada_en_enero(self):
        assert radicado_escrito("RE2310202400118", 2023) == "RE2310202400118"

    def test_sin_trece_cifras_no_hay_re(self):
        assert radicado_escrito("R23102023 2172", 2023) is None


@dataclass
class _Trozo:
    texto: str
    x0: float
    y0: float
    x1: float
    y1: float


class TestElSelloDeOficina:
    def test_el_rotulo_con_sur_debajo(self):
        trozos = [_Trozo("OPICINA", 420, 650, 460, 660), _Trozo("BOLIVAR", 420, 662, 460, 672), _Trozo("SUR", 465, 662, 480, 672)]
        hallado = _sello_de_oficina(trozos, 612, 792)
        assert hallado is not None
        banda, _ = hallado
        # El recorte sube por encima del rótulo: ahí va el RE a mano.
        assert banda.y0 < 650 / 792 - 0.05

    def test_la_direccion_de_la_carta_no_es_un_sello(self):
        trozos = [_Trozo("Oficina", 60, 100, 100, 110), _Trozo("Magangué", 105, 100, 160, 110), _Trozo("Bolívar", 165, 100, 210, 110)]
        assert _sello_de_oficina(trozos, 612, 792) is None


class _Lector:
    """Un OCR de mentira: lee lo que se le diga de cada imagen y cuenta las lecturas."""

    def __init__(self, textos: dict | None = None, siempre: str = ""):
        self.textos = textos or {}
        self.siempre = siempre
        self.leidas: list = []

    def read(self, imagen):
        self.leidas.append(imagen)
        texto = self.siempre or self.textos.get(imagen, "")

        class _R:
            text = texto

        return _R()


def _grupos(*codigos_y_paginas) -> GroupingResult:
    return GroupingResult(
        groups=[PageGroup(code=ResolutionCode(value=c, raw=c), page_numbers=list(p)) for c, p in codigos_y_paginas]
    )


def _poner(
    grupos,
    *,
    sellos=None,
    local=None,
    ia=None,
    empresa=None,
    conocidos=frozenset(),
    ubicados=None,
    sin_re=frozenset(),
    descartadas=frozenset(),
):
    return poner_los_re(
        grupos,
        sellos=sellos or {},
        copias=frozenset(),
        sin_re=sin_re,
        descartadas=descartadas,
        # La carta del cliente abre en la pág. 1 y la sigue la 2.
        de_la_carta=lambda paginas: [p for p in paginas if p <= 2] if paginas[0] == 1 else [],
        de_la_empresa=lambda paginas: (empresa or {}).get(paginas[0]),
        fecha_de=lambda paginas: date(2023, 11, 8),
        ubicar=lambda p: (ubicados or {}).get(p),
        render=lambda p, banda, ppp: (p, banda),
        # El mosaico, como la tupla de sus recortes: la IA de mentira lee eso.
        mosaico=lambda recortes: tuple(recortes),
        local=local or _Lector(),
        de_pago=ia,
        conocidos=conocidos,
    )


class TestPonerLosRe:
    def test_el_re_a_mano_lo_lee_la_ia_en_una_sola_lectura(self):
        ia = _Lector(siempre="RE2310202321443\nOFICINA BOLIVAR SUR\n10-11-2023")
        hecho = _poner(_grupos(("01", [1, 2, 3, 4])), ia=ia)
        assert hecho.grupos.groups[0].code.value == "01 RE2310202321443"
        assert hecho.renombrados == {"01": "01 RE2310202321443"}
        # Una sola lectura de IA para todo el documento.
        assert len(ia.leidas) == 1 and hecho.lecturas_con_ia == 1

    def test_el_mosaico_mira_todas_las_hojas_del_documento(self):
        """El sello puede ir en cualquier hoja: en UPD3102756 pág. 5, la segunda hoja de la carta."""
        ia = _Lector(siempre="")
        _poner(_grupos(("01", [1, 2, 3, 4])), ia=ia, descartadas={3})
        recortes = ia.leidas[0]
        # Primero el pie de la hoja de firmas, después la carta y la cabecera,
        # y el pie de las demás hojas; la factura (3) no.
        assert recortes[0] == (2, PIE)
        assert {p for p, _ in recortes} == {1, 2, 4}

    def test_el_sello_que_la_capa_ubica_va_primero(self):
        banda = Band(0.6, 0.7, 0.95, 0.95)
        ia = _Lector(siempre="")
        _poner(_grupos(("01", [1, 2, 3])), ia=ia, ubicados={3: banda})
        assert ia.leidas[0][0] == (3, banda)

    def test_el_de_casa_no_vale_para_la_letra_a_mano(self):
        """Un RE que el OCR de casa leyó suelto, sin etiqueta y sin conocerlo, no se pone."""
        banda = Band(0.6, 0.7, 0.95, 0.95)
        local = _Lector({(2, banda): "RE2310202321443"})
        assert _poner(_grupos(("01", [1, 2])), local=local, ubicados={2: banda}).grupos.groups[0].code.value == "01"

    def test_el_de_casa_si_vale_en_la_etiqueta_impresa(self):
        local = _Lector({(1, CABECERA): "AL CONTESTAR CITE ESTE NUMERO RE2310202312304"})
        ia = _Lector(siempre="RE2310202399999")
        hecho = _poner(_grupos(("01", [1, 2])), local=local, ia=ia)
        assert hecho.grupos.groups[0].code.value == "01 RE2310202312304"
        # Y entonces no se gasta IA.
        assert ia.leidas == []

    def test_el_sello_ya_leido_en_cualquier_hoja_manda(self):
        ia = _Lector()
        hecho = _poner(_grupos(("01", [1, 2, 3])), sellos={3: Sello("tinta", "RE2310202321592")}, ia=ia)
        assert hecho.grupos.groups[0].code.value == "01 RE2310202321592"
        assert ia.leidas == []

    def test_la_carta_de_la_empresa_lleva_el_re_que_contesta(self):
        hecho = _poner(_grupos(("01", [5])), empresa={5: "RE2310202321592"})
        assert hecho.grupos.groups[0].code.value == "01 RE2310202321592"

    def test_lo_que_no_se_deja_leer_se_queda_sin_re(self):
        hecho = _poner(_grupos(("01", [1, 2])), ia=_Lector(siempre="R23102023 2172"))
        assert hecho.grupos.groups[0].code.value == "01" and hecho.halladas == {}

    def test_el_que_ya_trae_re_no_se_toca(self):
        ia = _Lector()
        hecho = _poner(_grupos(("01 RE3110202139039", [1])), ia=ia)
        assert hecho.grupos.groups[0].code.value == "01 RE3110202139039" and ia.leidas == []

    def test_el_acuerdo_de_pago_no_lleva_re_ni_gasta_ia(self):
        ia = _Lector(siempre="RE2310202321443")
        hecho = _poner(_grupos(("01", [1, 2])), ia=ia, sin_re={1})
        assert hecho.grupos.groups[0].code.value == "01" and ia.leidas == []

    def test_sin_carta_ni_sello_no_se_gasta_ia(self):
        ia = _Lector(siempre="RE2310202321443")
        hecho = _poner(_grupos(("01", [7, 8])), ia=ia)
        assert hecho.grupos.groups[0].code.value == "01" and ia.leidas == []

class TestLaPrimeraCifraImposible:
    def test_una_x310_imposible_sigue_siendo_4310(self):
        assert radicado_del_texto("NUMERORE9310202207352") == "RE4310202207352"


class TestComoLeeLaIaLaLetraAMano:
    """Las lecturas reales de la IA sobre los sellos de UPD3102756."""

    def test_la_y_es_un_cuatro(self):
        texto = "ublico sino el antiguo decreto. RE23102023214Y3 ON Bolivar OFICINA BOLIVAR SUR FECHA DE RECIBIDO: 10-11-2023"
        assert radicado_escrito(texto) == "RE2310202321443"

    def test_la_barra_es_un_uno_y_los_espacios_no_cuentan(self):
        texto = "| FECHA DE RECIBIDO: | 09-01-2024 | | NO DE FOLIOS: | RE 23/0 2024 003 48 | |"
        assert radicado_escrito(texto) == "RE2310202400348"

    def test_la_cifra_repetida_sin_una_sola_forma_de_quitarla_no_se_adivina(self):
        texto = "FECHA DE RECIBIDO: | 16-07-2024 | | NO DE FOLIOS: | RE23102024114223 | | CIR"
        assert radicado_escrito(texto) is None

    def test_la_cifra_repetida_con_una_sola_forma(self):
        assert radicado_escrito("RE23102023215592 OFICINA", 2023) == "RE2310202321592"

    def test_el_anio_lo_da_la_fecha_de_recibido_del_sello(self):
        texto = "RE2310201921443 FECHA DE RECIBIDO: 10-11-2023"
        assert radicado_escrito(texto) is None

    def test_el_numero_interno_del_sello_no_es_el_re(self):
        assert radicado_escrito("No DE RADICACIÓN: 202360185637 RECIBIDO NO IMPLICA") is None

    def test_la_etiqueta_partida_en_dos(self):
        from resolutions.domain.sello import leer_sello

        sello = leer_sello("Caribemar d 1 SAS ESP 0 CONTES TnR CITE ESTE NUMERORE2310202412304 03 RECLAMO")
        assert sello is not None and sello.clase == "impreso"

    def test_la_d_es_un_cero_y_los_grupos_de_la_letra_a_mano(self):
        texto = "ue Bolívar. .com RE23 10 20 24 07 55D CARIBEMAR DE LA COSTA FECHA DE RECIBIDO: 08-05-2024"
        assert radicado_escrito(texto) == "RE2310202407550"

    def test_la_cifra_que_falta_en_el_anio_con_la_fecha_del_sello(self):
        """Pág. 2: lo de detrás -- el «09» de la dirección -- no es parte del número."""
        texto = "**DE CONTROL** 08-02-2024 202460035753 (03) RE231020202596 09#18-04 Samarkanda FECHA DE RECIBIDO: 08-02-2024"
        assert radicado_escrito(texto) == "RE2310202402596"

    def test_sin_el_anio_no_se_completa_nada(self):
        assert radicado_escrito("RE231020202596 09#18-04") is None

    def test_la_cifra_que_falta_en_el_consecutivo_no_se_adivina(self):
        assert radicado_escrito("RE23102024099 FUNCIONARIO", 2024) is None

    def test_el_numero_no_pasa_de_renglon(self):
        """Pág. 42: «RE23102024003» y debajo «DIR. NOTIFICACIÓN»; no es RE…00301."""
        assert radicado_escrito("RE23102024003\nDIR. NOTIFICACIÓN FECHA DE RECIBIDO: 09-01-2024") is None

    def test_la_barra_en_el_consecutivo_no_se_adivina(self):
        """Pág. 42 en el mosaico: «RE23102024003/8»; la barra es el 4 de RE…00348, no un 1."""
        assert radicado_escrito("RE23102024003/8 FECHA DE RECIBIDO: 09-01-2024") is None

    def test_la_barra_en_el_anio_se_comprueba_con_el_del_sello(self):
        assert radicado_escrito("RE2310202/00348", 2024) == "RE2310202400348"
        assert radicado_escrito("RE2310202/00348") is None
