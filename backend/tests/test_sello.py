"""El sello de radicación: cada sello nuevo abre un documento, y su RE lo agrupa.

Los recortes son los de la caja «afinar afinia» leídos a 400 ppp con el OCR de
casa, tal como salieron. Las reglas, como las dictó el operador: «cada vez que
encuentres un sello nuevo es un nuevo documento», y «cuando no logres leer el
número en el sello, no dividas allí por radicado: divide hasta que encuentres
una página con un nuevo sello o un nuevo número de radicado».
"""

from __future__ import annotations

from datetime import date

from resolutions.application.agrupacion import PaginasLeidas, agrupar_por_tramite
from resolutions.application.sellos import cortar_por_sellos
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.sello import Sello, con_los_conocidos, leer_sello

ETIQUETA_6 = (
    "Curibemar de la Custa $.A S. ESP 202160104519 AT CONTESTAR CITF. ESTF "
    "NUMERORF31 10202140544 Asunto: 03 KICLAMO — lolios:2 lamos Oficina: CAT "
    "valledupar-Cosar Il OLN LN AUN ÓO ON MEO ENB ENO Fecha: 17/09/2021 12:32:59.0"
)
ETIQUETA_8 = (
    "Curíbemar de lu Custa $.A.S. ESP . 202100120389 lejas y Reclamos AT.CONTESTAR "
    "CITF. ESTF NUMFRORE3 110202145449 Asuato: 03 KICLAMO — Trolios: 2 Oficina: "
    "CAT ValledupairC onar TE EOOOO Feeha: 21/10/2021 16:59:51.0"
)
ETIQUETA_SIN_NUMERO = (
    "Caríbemar de lu Custa $,A.S. SP AT.CONTRSTAR CÍTFZg%?FFGO%O&3R ORF31102 "
    "Asunto: 03 KICLAMO — trolios:3"
)
TINTA = (
    "CARIBEMAR ZE LACCSTASASESP OFICINA VALLEDUPAR CESAR , RECIBIDO NO IMPLICA "
    "ACEPTACIÓN Grupo-ep9 eA De cano: 022 pt-2024 No DE RA:-CAC!ON:?E&_"
)
CARTA_DE_LA_EMPRESA = "Consecutivo No. 210902090614861 VALLEDUPAR, 02 de septiembre de 2021"


class TestElSello:
    def test_la_etiqueta_impresa_da_radicado_fecha_y_folios(self):
        sello = leer_sello(ETIQUETA_6)
        assert sello == Sello("impreso", "RE3110202140544", date(2021, 9, 17), 2)

    def test_el_radicado_que_la_pagina_entera_no_veia(self):
        """UPD2320043 p8: la página entera lo dejaba ilegible."""
        assert leer_sello(ETIQUETA_8).radicado == "RE3110202145449"
        assert leer_sello(ETIQUETA_8).fecha == date(2021, 10, 21)

    def test_la_etiqueta_con_el_numero_ilegible_sigue_siendo_un_sello(self):
        sello = leer_sello(ETIQUETA_SIN_NUMERO)
        assert sello is not None and sello.clase == "impreso"
        assert not sello.legible

    def test_el_sello_de_tinta_se_reconoce_sin_numero(self):
        assert leer_sello(TINTA) == Sello("tinta")

    def test_la_carta_de_la_empresa_no_es_un_sello(self):
        assert leer_sello(CARTA_DE_LA_EMPRESA) is None

    def test_la_cifra_mal_leida_se_corrige_con_el_radicado_de_la_caja(self):
        """UPD2320047 p1: el sello dio …202487 y la citación trae …202887."""
        assert con_los_conocidos("RE3110202202487", {"RE3110202202887"}) == "RE3110202202887"
        assert con_los_conocidos("RE3110202145449", {"RE3110202202887"}) == "RE3110202145449"


def _grupos(*documentos: list[int]) -> GroupingResult:
    return GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=f"{n:02d}", raw=f"{n:02d}"), page_numbers=p)
            for n, p in enumerate(documentos, start=1)
        ],
        quarantine=[],
        repairs=[],
    )


class TestCadaSelloAbreUnDocumento:
    def test_el_sello_a_mitad_de_un_documento_lo_parte(self):
        sellos = {1: Sello("impreso", "RE3110202139039"), 3: Sello("impreso", None)}
        grupos, anexos, cortes = cortar_por_sellos(_grupos([1, 2, 3, 4], [5]), sellos, {"01": [4]})

        assert [g.page_numbers for g in grupos.groups] == [[1, 2], [3, 4], [5]]
        assert [g.code.value for g in grupos.groups] == ["01", "02", "03"]
        assert cortes == [3]
        # El anexo va con el tramo en que quedó.
        assert anexos == {"02": [4]}

    def test_el_sello_en_la_primera_hoja_no_corta_nada(self):
        grupos, _, cortes = cortar_por_sellos(_grupos([1, 2], [3]), {1: Sello("tinta"), 3: Sello("tinta")})
        assert [g.page_numbers for g in grupos.groups] == [[1, 2], [3]]
        assert cortes == []


GUIA_DE_ENTREGA = (
    "l.i:CTA Nil 806 003 042'? Pec«CaToCab30No 17 FECHA OE ENTREGA O INTENTO DE ENTREGA "
    "20201209 11:06:56 598 Skg 2020-12-14 CARIBEMAR DE LA COSTA SAS AFINIA PQR 09122020"
)
CARTA_CON_ETIQUETA = "\n".join(
    [
        "JJÍCTA",
        "Nü: 806.003 042-7",
        "Pie del Cerro Calle 30 No. 17 - 220",
        "www.lacta.com.co",
        "Consecutivo No. 202270023207",
        "Asunto: Citación para notificación personal",
    ]
)


class TestLaGuiaDeEnvio:
    """UPD2321099: la guía de entrega de LECTA (hoja 9) va con la citación que
    lleva la etiqueta (hoja 10), no con la petición de la 1 a la 8."""

    def test_se_reconocen_la_guia_y_la_carta_con_etiqueta(self):
        from resolutions.domain.sello import es_guia_de_envio, lleva_etiqueta_de_envio

        assert es_guia_de_envio(GUIA_DE_ENTREGA)
        assert not lleva_etiqueta_de_envio(GUIA_DE_ENTREGA)
        assert lleva_etiqueta_de_envio(CARTA_CON_ETIQUETA)
        assert not es_guia_de_envio(CARTA_CON_ETIQUETA)
        # La respuesta que menciona una «orden de servicio» no es una etiqueta.
        assert not lleva_etiqueta_de_envio(
            "Consecutivo No. 221018161009828 suspendido mediante orden de servicio No. 69082966"
        )

    def test_la_guia_de_antes_abre_el_documento_de_su_carta(self):
        grupos, _, _ = cortar_por_sellos(
            _grupos([1, 2, 3, 4, 5, 6, 7, 8], [9], [10]), {}, etiquetas={10}, guias={9}
        )
        assert [g.page_numbers for g in grupos.groups] == [[1, 2, 3, 4, 5, 6, 7, 8], [9, 10]]

    def test_la_guia_pegada_al_documento_anterior_tambien_se_va_con_su_carta(self):
        grupos, _, cortes = cortar_por_sellos(
            _grupos([1, 2, 3, 4, 5, 6, 7, 8, 9], [10]), {}, etiquetas={10}, guias={9}
        )
        assert [g.page_numbers for g in grupos.groups] == [[1, 2, 3, 4, 5, 6, 7, 8], [9, 10]]
        assert cortes == [9]

    def test_la_guia_de_despues_se_queda_con_su_carta(self):
        """UPD2320047: citación con etiqueta en la 5, su guía en la 6."""
        grupos, _, _ = cortar_por_sellos(
            _grupos([1, 2, 3, 4], [5], [6], [7]), {}, etiquetas={5}, guias={6}
        )
        assert [g.page_numbers for g in grupos.groups] == [[1, 2, 3, 4], [5, 6], [7]]


class TestElSelloEnElTramite:
    @staticmethod
    def _tramites(textos, fechas, sellos):
        grupos = _grupos(*[[p] for p in textos])
        leidas = PaginasLeidas(
            fechas=fechas,
            tipos={p: None for p in textos},
            asuntos={p: None for p in textos},
            con_ocr=0,
            textos=textos,
        )
        return agrupar_por_tramite(grupos, leidas, sellos=sellos)

    def test_el_re_del_sello_manda_sobre_la_pagina(self):
        textos = {1: "escrito sin número legible " * 5, 2: "hechos " * 20, 3: "Reclamación No. RE3110202140544"}
        tramites = self._tramites(
            textos,
            {1: None, 2: None, 3: None},
            {1: Sello("impreso", "RE3110202139039")},
        )
        assert [g.code.raw for g in tramites.grupos.groups] == ["RE3110202139039", "RE3110202140544"]

    def test_un_sello_ilegible_corta_hasta_el_proximo_sello_o_re(self):
        """Lo que sigue al sello ilegible es de ese escrito, aunque su fecha
        encaje en otro trámite: la fecha no parte donde manda un sello."""
        textos = {
            1: "Recibí constancia N* PQR: RE3110202138312 FECHA: 02/09/2021",
            2: "escrito radicado " * 10,
            3: "hechos " * 20,
            4: "Reclamación No. RE3110202138312",
        }
        fechas = {1: date(2021, 9, 2), 2: date(2021, 9, 8), 3: date(2021, 9, 2), 4: None}
        tramites = self._tramites(textos, fechas, {2: Sello("impreso", None)})

        assert [g.page_numbers for g in tramites.grupos.groups] == [[1, 4], [2, 3]]
        [hoja] = [h for h in tramites.en_revision if h.page == 2]
        assert "próximo sello o RE" in hoja.motivo


class TestLaUltimaHojaConSello:
    """«Si la página con el sello es la última y la anterior ya pertenece a un
    grupo de páginas, agrupar la página con el sello sola.»"""

    def test_va_sola(self):
        from resolutions.application.sellos import la_ultima_hoja_sola

        grupos, _, sola = la_ultima_hoja_sola(_grupos([1, 2, 3], [4, 5]), {5})
        assert [g.page_numbers for g in grupos.groups] == [[1, 2, 3], [4], [5]]
        assert sola == 5

    def test_con_la_guia_que_la_precede(self):
        """UPD2321099: la citación de la 10 con su guía de LECTA de la 9."""
        from resolutions.application.sellos import la_ultima_hoja_sola

        grupos, _, _ = la_ultima_hoja_sola(_grupos(list(range(1, 11))), {10}, guias={9})
        assert [g.page_numbers for g in grupos.groups] == [list(range(1, 9)), [9, 10]]

    def test_si_ya_va_sola_no_cambia_nada(self):
        from resolutions.application.sellos import la_ultima_hoja_sola

        grupos = _grupos([1, 2], [3])
        assert la_ultima_hoja_sola(grupos, {3})[0] is grupos

    def test_sin_sello_en_la_ultima_no_cambia_nada(self):
        from resolutions.application.sellos import la_ultima_hoja_sola

        grupos = _grupos([1, 2, 3])
        assert la_ultima_hoja_sola(grupos, {1})[0] is grupos


class TestElAnclaDelSello:
    def test_la_contestacion_de_un_recurso_no_es_un_sello(self):
        """UPD2326399 p2: «…anexo a la contestación de la petición»."""
        from resolutions.application.sellos import _ANCLA

        assert _ANCLA.search("se puede evidenciar el cuadro comparativo anexo a la contestación de la petición") is None
        assert _ANCLA.search("AL CONTESTAR CITE ESTE NUMERORE3110202118047")
        assert _ANCLA.search("NUMF.nORK3110202139039")


class _Fuente:
    """Una caja de mentira: cada hoja es su texto, y el recorte es el texto."""

    def __init__(self, textos):
        self.textos = textos

    def text_of(self, pagina):
        return ""

    def render(self, pagina, banda=None, dpi=200, formato="png"):
        return self.textos[pagina].encode("utf-8")


class _Ocr:
    def __init__(self, respuestas=None):
        self.respuestas = respuestas or {}

    def read(self, imagen):
        from resolutions.application.ports import OcrResult

        texto = imagen.decode("utf-8")
        return OcrResult(text=self.respuestas.get(texto, texto))


class TestLeerLosSellos:
    def test_el_de_pago_manda_sobre_el_de_casa(self):
        """El de casa leyó …145449; el de pago, la etiqueta entera: …145459."""
        from resolutions.application.sellos import leer_sellos

        casa = "AT CONTESTAR CITF. ESTF NUMFRORE3 110202145449 Asunto: 03 KICLAMO Trolios: 2"
        pago = "\n".join(
            [
                "AL CONTESTAR CITE ESTE NUMERORE3110202145459",
                "Asunto: 03 RECLAMO Folios: 2",
                "Fecha: 21/10/2021 16:59:51.0",
            ]
        )
        fuente = _Fuente({1: casa, 2: "hechos " * 40})
        sellos = leer_sellos(fuente, _Ocr(), [1, 2], de_pago=_Ocr({casa: pago}))

        assert sellos == {1: Sello("impreso", "RE3110202145459", date(2021, 10, 21), 2)}

    def test_sin_el_de_pago_queda_la_lectura_de_casa(self):
        from resolutions.application.sellos import leer_sellos

        casa = "AT CONTESTAR CITF. ESTF NUMERORF31 10202140544 Asunto: 03 KICLAMO lolios:2 Fecha: 17/09/2021 12:32:59.0"
        sellos = leer_sellos(_Fuente({1: casa}), _Ocr(), [1])
        assert sellos[1].radicado == "RE3110202140544"


class TestPorTramiteMandaElSello:
    """«Cuando varias hojas tienen el mismo RE pero aparece un sello nuevo o una
    carta con etiqueta de LECTA, manda el sello.»"""

    def test_upd2320047_son_cuatro(self):
        from resolutions.application.sellos import dividir_por_tramite

        documentos = _grupos([1, 2, 3, 4], [5, 6], [7], list(range(8, 20)))
        propios = {1: "RE3110202202887", 5: "RE3110202202887", 8: "RE3110202250357"}
        del_tramite = {p: "RE3110202202887" for p in range(1, 7)} | {p: "RE3110202250357" for p in range(8, 20)}
        grupos, _ = dividir_por_tramite(documentos, propios, del_tramite, abren={1, 5, 8})

        assert [g.page_numbers for g in grupos.groups] == [[1, 2, 3, 4], [5, 6], [7], list(range(8, 20))]
        # El acta no trae RE ni quedó en un trámite con evidencia: no se le pone el de otro.
        assert [g.code.raw for g in grupos.groups][2] == "03"

    def test_la_respuesta_que_cita_el_re_se_une_a_su_escrito(self):
        """UPD2326399: recurso con sello, su notificación y su respuesta."""
        from resolutions.application.sellos import dividir_por_tramite

        re_ = "RE3110202138312"
        documentos = _grupos([1, 2, 3], [4], [5, 6], [7, 8, 9], [10], [11, 12])
        propios = {1: re_, 4: re_, 5: re_, 10: re_, 11: re_}
        del_tramite = {p: re_ for p in range(1, 13)}
        grupos, _ = dividir_por_tramite(documentos, propios, del_tramite, abren={1, 7})

        assert [g.page_numbers for g in grupos.groups] == [[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]]
        assert {g.code.raw for g in grupos.groups} == {re_}

    def test_un_re_nuevo_corta_a_mitad_de_un_documento(self):
        """UPD2555083: dos constancias que el corte unió, de dos radicados."""
        from resolutions.application.sellos import dividir_por_tramite

        propios = {1: "RE4310202103559", 2: "RE4310202207571"}
        grupos, _ = dividir_por_tramite(_grupos([1, 2]), propios, {}, abren=set())
        assert [g.page_numbers for g in grupos.groups] == [[1], [2]]


class TestElAcuerdoDePago:
    """UPD2326302: pagarés, cartas de instrucciones, reconocimiento de deuda y
    simulador son UN documento, sin RE."""

    TEXTOS = {
        1: "AL CONTESTAR CITE ESTE NUMERORE3110202216128 REF: DERECHO DE PETICION " + "hechos " * 30,
        2: "CARIBEMAR DE LA COSTA S.A.S. ESP Sector Cesar Norte PAGARE No. 5339823 -6 FECHA VENCIMIENTO",
        3: "CARTA DE INSTRUCCIONES ANEXA A PAGARE No. 5339823 6 CON ESPACIOS ABIERTOS",
        4: "CARIBEMAR DE LA COSTA S.A.S. ESP PAGARE No. 5339823 -7 FECHA VENCIMIENTO",
        5: "VALLEDUPAR, 25 de Mayo de 2022 Ref.: Reconocimiento de deuda y propuesta de acuerdo de pago",
        6: "aFima Simulador de Negociación y Financiación Delegación Cesar",
    }

    def test_las_piezas_seguidas_son_un_documento(self):
        from resolutions.application.anexos_declarados import unir_el_acuerdo_de_pago

        grupos, _, del_acuerdo = unir_el_acuerdo_de_pago(_grupos([1], [2, 3], [4], [5], [6]), self.TEXTOS)
        assert [g.page_numbers for g in grupos.groups] == [[1], [2, 3, 4, 5, 6]]
        assert grupos.groups[1].kind == "RECONOCIMIENTO DE DEUDA Y ACUERDO DE PAGO"
        assert del_acuerdo == {2, 3, 4, 5, 6}

    def test_un_sello_corta_el_acuerdo(self):
        from resolutions.application.anexos_declarados import unir_el_acuerdo_de_pago

        grupos, _, _ = unir_el_acuerdo_de_pago(_grupos([1], [2, 3], [4], [5], [6]), self.TEXTOS, abren={4})
        # La hoja con sello abre su documento: no es del acuerdo. Y el pagaré que
        # queda antes del sello no va suelto: se une al documento anterior
        # (regla del operador del 2026-10-22, «ningún pagaré puede ir solo»).
        assert [g.page_numbers for g in grupos.groups] == [[1, 2, 3], [4], [5, 6]]


class TestLaHojaDeLaListaCierraSuEscrito:
    def test_vuelve_al_escrito_anterior(self):
        """UPD2326319: la hoja 3 -- notificaciones y la lista de anexos -- salía
        abriendo un documento con los anexos detrás."""
        from resolutions.application.anexos_declarados import retener_anexos

        textos = {
            1: "Señores Caribemar REF: DERECHO DE PETICION " + "hechos " * 40,
            2: "PRETENSIONES " + "pido " * 40,
            3: "\n".join(
                [
                    "NOTIFICACIONES:",
                    "La que suscribe la recibirá en la Transversal 23",
                    "ANEXO:",
                    "Certificado de defunción Nro 70297037-7",
                    "Factura NIC - 4405451",
                    "Denuncia por hurto",
                ]
            ),
            4: "REPUBLICA DE COLOMBIA CERTIFICADO DE DEFUNCION " + "datos " * 40,
            5: "FISCALIA DENUNCIA POR HURTO " + "relato " * 40,
            6: "OPERADOR DE RED; USE ESTE NUMERO PARA CONSULTAS NIC 5339939 " + "kwh " * 40,
        }
        retencion = retener_anexos(_grupos([1, 2], [3, 4, 5, 6]), textos)
        assert [g.page_numbers for g in retencion.grupos.groups] == [[1, 2, 3, 4, 5, 6]]

    def test_una_hoja_con_sello_no_vuelve(self):
        from resolutions.application.anexos_declarados import retener_anexos

        textos = {
            1: "escrito " * 40,
            2: "\n".join(["ANEXO:", "Factura de cobro", "NOTIFICACIONES"]),
            3: "OPERADOR DE RED " * 10,
        }
        retencion = retener_anexos(_grupos([1], [2, 3]), textos, abren={2})
        assert [g.page_numbers for g in retencion.grupos.groups] == [[1], [2, 3]]
