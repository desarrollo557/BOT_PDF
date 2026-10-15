"""Las reglas que salieron de revisar la caja 108C000033, hoja por hoja.

Cada prueba lleva el caso real que la motivó: lo que la OCR dejó del sello, la
guía de LECTA que caía entre dos cartas, el certificado partido por el corte.
"""

from __future__ import annotations

from datetime import date

import pytest

from resolutions.application.anexos_declarados import _renumerar, clase_de_soporte
from resolutions.application.sellos import retener_los_folios, unir_lo_que_no_abre
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.sello import Sello, leer_sello, numero_de_guia


def _grupos(*tramos: list[int]) -> GroupingResult:
    return GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=f"{i:02d}", raw=f"{i:02d}"), page_numbers=list(t))
            for i, t in enumerate(tramos, start=1)
        ]
    )


class TestElRadicadoDelSello:
    @pytest.mark.parametrize(
        ("texto", "radicado"),
        [
            # La «l» por el «1»: UPD2326302 p1, con el año del número interno.
            ("Caribernar de la Costa S.A.S. ESP\n202260026584\nAL CONTESTAR CITE ESTE NUMLRORE3i 10202212114", "RE3110202212114"),
            # La primera cifra perdida: la oficina se deduce de «110».
            ("202260031342\nAL CONTESTAR CITE ESTE NUMERORE2| 10202210696\nFecha: 16/03,2022 15:17:44.0", "RE3110202210696"),
            ("s 202100014084\nE AT. CONTESTAR CITE ESTE NUVFRORFI1 10202106861 L", "RE3110202106861"),
            # La Q por el 0 y todo pegado: UPD2326323 p1.
            ("ALCONTESTARCITE!StT¿UMERORE31102Q2144505\nfechi 14/10/2021 10:33.37 0", "RE3110202144505"),
            # Las trece cifras limpias con una oficina imposible: 4110 es 3110.
            ("AL CONTESTAR CITE ESTE NUMERORE4110202206907", "RE3110202206907"),
        ],
    )
    def test_se_recupera(self, texto, radicado):
        assert leer_sello(texto).radicado == radicado

    def test_con_demasiadas_letras_no_se_inventa(self):
        # «RE J 11020212SOI3» (UPD2326310 p1) daba un radicado que no existe.
        sello = leer_sello("AL CONTESTAR CITE ESTE NUMmoREJ 11020212SOI3\nFecha: 02/07/2021 17:05:49.0")
        assert sello.radicado is None

    def test_sin_anio_no_se_aproxima(self):
        assert leer_sello("AL CONTESTAR CITE ESTE NUMERORE31l0202212114").radicado is None

    @pytest.mark.parametrize(
        ("texto", "fecha", "folios"),
        [
            ("AL CONTESTAR CITE\nTolios: 4 ==\nFecha: 09/12/2020) 14:54:26.0", date(2020, 12, 9), 4),
            ("AL CONTESTAR CITE\nTiolios: 9\nFecha: 002/07 2021 17:05:49.0)", date(2021, 7, 2), 9),
            ("AL CONTESTAR CITE\nAcunto: 07 RECURSO Volios: 2", None, 2),
        ],
    )
    def test_fecha_y_folios_como_los_deja_la_ocr(self, texto, fecha, folios):
        sello = leer_sello(texto)
        assert (sello.fecha, sello.folios) == (fecha, folios)

    def test_una_palabra_suelta_no_es_un_sello_de_tinta(self):
        # «le implica otras» en el cuerpo de un recurso (UPD2326324 p9).
        assert leer_sello("ción consecuentemente le implica otras, cuales son") is None
        assert leer_sello("RECIBIDO NO IMPLICA ACEPTACIÓN Grupo-epm").clase == "tinta"


class TestLaGuiaDeLecta:
    def test_el_numero_se_lee_aunque_la_ocr_lo_ensucie(self):
        carta = "J.V.CTA\nNit 806 003 042-7\nNo Guia\n•7e725339023*\nOrden de Servicio"
        guia = "UiCTA\n*78725339023*\nFECHA DE ENTREGA O INTENTO DE ENTREGA"
        assert numero_de_guia(carta) == numero_de_guia(guia) == "25339023"


class TestLosFoliosDelSello:
    def test_lo_que_cae_dentro_de_los_folios_es_del_escrito(self):
        # «Folios: 4» en la hoja 1: el contrato de las hojas 3 y 4 no abre nada.
        grupos, _, unidas = retener_los_folios(
            _grupos([1, 2], [3, 4], [5]), {1: Sello("impreso", folios=4)}, abren={1}
        )
        assert [g.page_numbers for g in grupos.groups] == [[1, 2, 3, 4], [5]]
        assert unidas == [3]

    def test_otro_sello_dentro_de_los_folios_abre_lo_suyo(self):
        grupos, _, _ = retener_los_folios(
            _grupos([1, 2], [3, 4]),
            {1: Sello("impreso", folios=4), 3: Sello("impreso")},
            abren={1, 3},
        )
        assert [g.page_numbers for g in grupos.groups] == [[1, 2], [3, 4]]


class TestLoQueNoAbre:
    def test_va_con_el_anterior_y_se_renumera(self):
        grupos, _, unidas = unir_lo_que_no_abre(_grupos([1, 2], [3], [4]), {3})
        assert [g.page_numbers for g in grupos.groups] == [[1, 2, 3], [4]]
        assert [g.code.value for g in grupos.groups] == ["01", "02"]
        assert unidas == [3]


class TestLosSoportes:
    def test_el_certificado_se_reconoce_en_su_cabecera(self):
        certificado = (
            "OFICINA DE REGISTRO DE INSTRUMENTOS PUBLICOS DE VALLEDUPAR\n"
            "CERTIFICADO DE TRADICION\nMATRICULA INMOBILIARIA\nCertificado generado con el Pin No: 2011"
        )
        assert clase_de_soporte(certificado) == "certificado de tradición"

    def test_el_escrito_que_cita_la_matricula_no_es_un_certificado(self):
        escrito = (
            "Valledupar, 18-08-2022\nDoctora:\nGerente de AFINIA\n" + "texto del escrito " * 60
            + "\nMATRICULA INMOBILIARIA 190-185946 acciono derecho de petición"
        )
        assert clase_de_soporte(escrito) is None


class TestLaNumeracion:
    def test_por_tramite_se_renumera_y_se_conserva_el_radicado(self):
        # UPD2326321 saltaba del 02 al 04.
        grupos = [
            PageGroup(code=ResolutionCode(value="01 RE3110202030638", raw="RE3110202030638"), page_numbers=[1]),
            PageGroup(code=ResolutionCode(value="04 RE3110202118192", raw="RE3110202118192"), page_numbers=[2]),
        ]
        nuevos, _ = _renumerar(grupos, {})
        assert [g.code.value for g in nuevos] == ["01 RE3110202030638", "02 RE3110202118192"]
        assert nuevos[1].code.raw == "RE3110202118192"


class TestLasActasDeSuspension:
    """«Ese tipo de documentos en específico van separados» (el operador)."""

    def test_el_numero_se_lee_con_o_sin_espacios(self):
        from resolutions.domain.sello import numero_del_acta_de_suspension

        assert numero_del_acta_de_suspension("ACTA DE SUSPENSION\nNo. S-21 927720") == "S-21927720"
        assert numero_del_acta_de_suspension("\\CTA DE SUSPENSION\nNo.S-221222941") == "S-221222941"
        # El acta de inspección no es de este tipo.
        assert numero_del_acta_de_suspension("ACTA DE INSPECCION\nNo. 1-21 086674") is None

    def test_cada_numero_abre_su_acta(self):
        from resolutions.application.sellos import separar_las_actas

        grupos, _, abiertas = separar_las_actas(
            _grupos([1, 2, 3, 4]), {1: "S-21927720", 2: "S-221222941", 3: None, 4: "S-221223000"}
        )
        # La 3 no trae número: es el reverso de la 2.
        assert [g.page_numbers for g in grupos.groups] == [[1], [2, 3], [4]]
        assert [g.code.value for g in grupos.groups] == ["01", "02", "03"]
        assert abiertas == [2, 4]


class TestLaRevisionSoloDiceLoQueHayQueMirar:
    """De treinta avisos en la caja quedaron cinco, todos con algo que hacer."""

    def test_fotocopia_no_es_fotografia(self):
        from resolutions.domain.anexos_declarados import clase_del_renglon

        assert clase_del_renglon("Fotocopia de documento de identificación") == "documento de identidad"
        assert clase_del_renglon("Registro fotográfico del predio") == "fotografías"
        assert clase_del_renglon("Fotocopia de acto administrativo") == "copia de reclamo o respuesta"

    def test_el_titulo_de_la_cabecera_manda_sobre_el_cuerpo(self):
        from resolutions.domain.anexos_declarados import clase_de_la_hoja

        contrato = (
            "RIM\nW- 08389406\nI\nWI\nCONTRATO DE ARRENDAMIENTO DE VIVIENDA URBANA\n"
            + "cláusula del contrato " * 40
            + "\nubicado según CERTIFICACION DEL IGAC nomenclatura catastral"
        )
        assert clase_de_la_hoja(contrato) == "contrato de arrendamiento"

    def test_dos_facturas_a_dos_caras_son_dos(self):
        from resolutions.application.anexos_declarados import (
            AnexosDelEscrito,
            verificar_en_el_documento,
        )
        from resolutions.domain.anexos_declarados import leer_lista_de_anexos

        factura = "OPERADOR DE RED: Caribe Mar\nUSE ESTE NUMERO PARA PAGAR\nTOTAL A PAGAR " + "x " * 40
        textos = {1: "ANEXO:\n- dos (2) facturas", 2: factura, 3: factura, 4: factura, 5: factura}
        lista = leer_lista_de_anexos(textos[1])
        escrito = AnexosDelEscrito(pagina=1, lista=lista, faltan=list(lista.anexos))

        [verificado] = verificar_en_el_documento([escrito], _grupos([1, 2, 3, 4, 5]), textos)

        assert verificado.faltan == []

    def test_una_hoja_ilegible_puede_ser_lo_que_falta(self):
        from resolutions.application.anexos_declarados import (
            AnexosDelEscrito,
            verificar_en_el_documento,
        )
        from resolutions.domain.anexos_declarados import leer_lista_de_anexos

        textos = {1: "ANEXOS:\n- Certificado de defunción", 2: "@ # ~"}
        lista = leer_lista_de_anexos(textos[1])
        escrito = AnexosDelEscrito(pagina=1, lista=lista)

        [verificado] = verificar_en_el_documento([escrito], _grupos([1, 2]), textos)

        assert verificado.motivo_de_revision() is None


class TestElAnexoQueNoSeAporto:
    """«No aporta documento», escrito a mano al lado del anexo al radicar."""

    def test_la_nota_se_reconoce_legible_o_como_rastro_de_letra_a_mano(self):
        from resolutions.domain.anexos_declarados import sin_la_anotacion

        assert sin_la_anotacion("Copia de contrato de arrendamiento fJO O") == (
            "Copia de contrato de arrendamiento",
            True,
        )
        assert sin_la_anotacion("Copia de contrato de arrendamiento NO APORTA DOCUMENTO")[1]
        # Un renglón impreso no lleva rastro: ni las cifras ni las siglas cuentan.
        assert not sin_la_anotacion("Factura NIC")[1]
        assert not sin_la_anotacion("Contrato de arrendamiento número 083 89406")[1]

    def test_se_omite_ese_anexo_y_los_demas_se_verifican(self):
        from resolutions.application.anexos_declarados import (
            AnexosDelEscrito,
            verificar_en_el_documento,
        )
        from resolutions.domain.anexos_declarados import leer_lista_de_anexos

        certificado = (
            "OFICINA DE REGISTRO DE INSTRUMENTOS PUBLICOS\nCERTIFICADO DE TRADICION\n"
            "MATRICULA INMOBILIARIA 190-1"
        )
        textos = {
            1: "ANEXOS\nCopia Certificado de Tradición y Libertad.\nCopia de contrato de arrendamiento fJO O-\nAtentamente,",
            2: certificado,
        }
        lista = leer_lista_de_anexos(textos[1])
        escrito = AnexosDelEscrito(pagina=1, lista=lista)

        [verificado] = verificar_en_el_documento([escrito], _grupos([1, 2]), textos)

        assert verificado.motivo_de_revision() is None
        assert [a.texto for a in verificado.no_aportados] == ["Copia de contrato de arrendamiento"]
        assert "no aportados" in verificado.observacion()


class TestLaSegundaPasadaDeLaCaja:
    """Lo que salió de la carpeta entera, 209 PDF: cada aviso, con su porqué."""

    def test_el_radicado_limpio_manda_sobre_el_de_oficina_deducida(self):
        # UPD2326468 p1: «131 0202137028» (un 3110 al que la OCR comió una
        # cifra) daba «4310» aunque la misma lectura trajera el limpio.
        texto = (
            "AL CONTESTAR CITE ESTE NUMERO I?3 131 0202137028\n"
            "AL CONTESTAR CITE ESTE NUMERORE3110202137028\nFecha 24/08/2021 09:17:51.0"
        )
        assert leer_sello(texto).radicado == "RE3110202137028"

    def test_el_radicado_de_la_superintendencia_no_es_un_sello_ilegible(self):
        sspd = leer_sello(
            "Al contestar cite el número de radicado de este documento\n"
            "SSPD Número de Radicado 20215290025562\nFecha: 07/01/2021"
        )
        assert sspd.clase == "sspd" and sspd.radicado is None
        # El formulario de la empresa que nombra la SSPD sigue siendo su etiqueta.
        etiqueta = leer_sello(
            "AL CONTESTAR CITE ESTE NUMERORE3110202201840\n"
            "Reposición y subsidiariamente apelación ante la SSPD"
        )
        assert etiqueta.clase == "impreso"

    def test_la_revocatoria_de_oficio_mantiene_vivo_el_tramite(self):
        from resolutions.application.agrupacion import PaginasLeidas, agrupar_por_tramite

        # UPD2326398: la constancia de 2019 notifica la revocatoria de 2019 de
        # un trámite de 2015; la carta cita el RE.
        textos = {
            1: "CONSTANCIA DE NOTIFICACION PERSONAL a los 26/09/2019 04:08 PM",
            2: "ASUNTO: Revocatoria directa de la respuesta al RE3110201518538 de 12/06/2015",
            3: "recurso de reposición RE3110201518538 de 12/06/2015",
        }
        leidas = PaginasLeidas(
            fechas={1: date(2019, 9, 26), 2: date(2019, 9, 12), 3: date(2015, 6, 12)},
            tipos={p: None for p in textos},
            asuntos={p: None for p in textos},
            con_ocr=0,
            textos=textos,
        )

        por_tramite = agrupar_por_tramite(_grupos([1], [2], [3]), leidas)

        assert [h.page for h in por_tramite.en_revision] == []

    def test_dos_expedientes_seguidos_bien_leidos_no_son_una_mala_lectura(self):
        from resolutions.application.agrupacion import PaginasLeidas, agrupar_por_tramite

        # UPD2326394: P…029 y P…028, de dos personas, cada uno impreso dos veces.
        textos = {
            1: "No. Expediente: P31102021050029\nCAMBIO DE MD P31102021050029",
            2: "No. Expediente: P31102021050028\nCAMBIO DE MD P31102021050028",
        }
        leidas = PaginasLeidas(
            fechas={1: None, 2: None},
            tipos={1: None, 2: None},
            asuntos={1: None, 2: None},
            con_ocr=0,
            textos=textos,
        )

        por_tramite = agrupar_por_tramite(_grupos([1], [2]), leidas)

        assert [h.page for h in por_tramite.en_revision] == []

    def test_la_guia_de_entrega_al_final_va_con_su_carta(self):
        from resolutions.application.sellos import cortar_por_sellos

        # UPD2326502: carta con etiqueta en la 1, hojas 2-3, guía en la 4.
        grupos, _, _ = cortar_por_sellos(_grupos([1, 2, 3], [4]), {}, etiquetas={1}, guias={4})
        assert [g.page_numbers for g in grupos.groups] == [[1, 2, 3, 4]]
        # La que va antes de una carta con etiqueta sigue abriendo la de ella.
        grupos, _, _ = cortar_por_sellos(_grupos([1, 2], [3, 4]), {}, etiquetas={4}, guias={3})
        assert [g.page_numbers for g in grupos.groups] == [[1, 2], [3, 4]]

    def test_la_guia_va_con_la_carta_de_su_envio_aunque_haya_hojas_de_por_medio(self):
        from resolutions.application.sellos import cortar_por_sellos
        from resolutions.domain.sello import claves_del_envio

        # UPD2326502: citación con etiqueta (1) y su guía (2); notificación por
        # aviso con etiqueta (3-6) y su guía (7); una reclamación con sello (8).
        # El número de la guía de hoja entera no se lee; la fecha y la hora de
        # admisión, sí, y son las de la etiqueta de su carta.
        textos = {
            1: "No. Guia\n•79733765652*\nHora.\nFecha.\n12:15:17\n20220117",
            2: "FECHA DE ENTREGA Ó INTENTO DE ENTREGA\n20220117\n12:15:17\nCITACION PENDIENTE DE",
            3: "No. Guia\n*78733908247*\nFecha: 20220125\nHora: 11:40:49",
            7: "FECHA DE ENTREGA Ó INTENTO DE ENTREGA\n20220125 \n11:40:48\nNOTIFICACION POR AVISO",
        }
        envios = {p: claves_del_envio(t) for p, t in textos.items()}
        assert envios[1] & envios[2] and envios[3] & envios[7] and not envios[2] & envios[3]

        grupos, _, _ = cortar_por_sellos(
            _grupos([1], [2, 3, 4, 5, 6], [7], [8]),
            {8: Sello("impreso", "RE3110202272398")},
            etiquetas={1, 3},
            guias={2, 7},
            envios=envios,
        )

        assert [g.page_numbers for g in grupos.groups] == [[1, 2], [3, 4, 5, 6, 7], [8]]


class TestElTituloDeLaHoja:
    def test_el_petitorio_de_un_recurso_no_es_un_derecho_de_peticion(self):
        from resolutions.domain.asunto_del_documento import titulo_del_documento

        # UPD2326418 p3: la hoja «PETICIÓN» de un recurso, que nombra de pasada
        # el derecho de petición en su prosa.
        hoja = (
            "PETICIÓN\nSolicito de manera respetuosa a la Superintendencia de Servicios Públicos "
            "ordenar a la empresa\nCARIBEMAR S.A., se sirva descargar los valores adeudados, los\n"
            "cuales fueron solicitados en el derecho de petición, mientras estuvo ocupando el inmueble"
        )
        assert titulo_del_documento(hoja) == "DOCUMENTO"
        assert titulo_del_documento("Señores\nAFINIA\nDERECHO DE PETICIÓN.\nYo, ...") == "DERECHO DE PETICION"
        assert (
            titulo_del_documento(
                "Señores AFINIA\nacudo a usted con el fin de interponer derecho de petición amparado en"
            )
            == "DERECHO DE PETICION"
        )

    def test_los_rotulos_y_formatos(self):
        from resolutions.domain.asunto_del_documento import titulo_del_documento

        # «REF;» es «REF:» con la OCR encima (UPD2326418 p4).
        assert titulo_del_documento(
            "REF; RECURSO DE REPOSICIÓN ANTE LA EMPRESA Y EN SUBSIDIO EL DE APELACION\n"
            "CONTRA LA RECLAMACIÓN N° RE- 3110202040770"
        ).startswith("RECURSO DE REPOSICION")
        assert titulo_del_documento("aFinia\nCONTRATO DE TRANSACCION\nCARIBEMAR") == "CONTRATO DE TRANSACCION"
        assert (
            titulo_del_documento("Autorización para ia Notificación Electrónica\nAUTORIZO a la empresa")
            == "AUTORIZACION DE NOTIFICACION ELECTRONICA"
        )
        assert titulo_del_documento("ASUNTO:\nLey Habeas Data - NIC\nautorizo") == "LEY HABEAS DATA"

    def test_el_asunto_del_sello_es_el_ultimo_recurso(self):
        from resolutions.domain.asunto_del_documento import titulo_del_documento

        # UPD2326321 p15: ni REF ni título; el sello dice «01 PETICION».
        assert (
            titulo_del_documento(
                "AL CONTESTAR CITE ESTE NUMERORE3110202216743\nAsunto 01 PETICION Fokos 5\n"
                "Señores: AFINIA\nPor medio de la presente les estoy solicitando"
            )
            == "DERECHO DE PETICION"
        )
        # Y el REF manda sobre él.
        assert (
            titulo_del_documento("Asunto: 03 RECLAMO Folios: 4\nREF: DERECHO DE PETICION (ART 23 C. N.)")
            == "DERECHO DE PETICION"
        )


class TestLosAnexosConElTituloRoto:
    """El anexo de delante se tragaba el siguiente si la OCR rompía su título."""

    @pytest.mark.parametrize(
        "cabecera",
        [
            "JWGRupomo »3»RÍ!r«w/ F !? CONTRATO DEARRENDAMIENTO PARA VIVIENDA URBANA",  # UPD2326409 p6
            "Í^rupcMq <0 m m PCONTRATO DE ARRENDAilENTO PARA VMENDA URBANA",  # UPD2326328 p6
            "M ■> hN f. V-' s.. COITOATO DS ARRÍNDAMrBítOM UNA VIVieNDA",  # UPD2326418 p12
        ],
    )
    def test_el_contrato(self, cabecera):
        from resolutions.domain.anexos_declarados import clase_de_la_hoja

        assert clase_de_la_hoja(cabecera + "\n" + "cláusula " * 40) == "contrato de arrendamiento"

    def test_la_factura_y_la_cedula(self):
        from resolutions.domain.anexos_declarados import clase_de_la_hoja

        # UPD2326402 p12 y UPD2326386 p9.
        assert clase_de_la_hoja("arinia OPERADOR OeRH)-^^ Calle 16 Wo.8 - 37 " + "x " * 40) == "factura"
        cedula = "S2.FUBl!€A DE COLOSIBIA IDENT!’-!.: I.ClOM PERSOiMAL CeDULS, CE CIUDADANIA 5.163.897 NUMERO OfÍATE"
        assert clase_de_la_hoja(cedula) == "documento de identidad"
        # La prosa que nombra la cédula no es una cédula.
        escrito = (
            "Yo, YANETH LEONOR SANCHEZ VILLAR, identificada con la Cédula de Ciudadanía: 49.779.336 "
            "de la Ciudad de Valledupar, me dirijo a su despacho respetuosamente " * 3
        )
        assert clase_de_la_hoja(escrito) != "documento de identidad"

    def test_anexo_a_mitad_de_oracion_no_es_una_lista(self):
        from resolutions.domain.anexos_declarados import leer_lista_de_anexos

        # UPD2326503 p7: la carta de la empresa, partida por el renglón.
        carta = (
            "Después de efectuado el análisis del escrito presentado evidenciamos que al mismo\n"
            "anexo el Certificado de Tradición y Libertad, por tanto, nos debe aportar dicho\n"
            "documento con una fecha de expedición no mayor a 90 días."
        )
        assert leer_lista_de_anexos(carta) is None
        assert leer_lista_de_anexos("Solicito la revisión.\nAnexo copia de la cédula de ciudadanía")


class TestLaRelecturaDelRenglon:
    """El renglón del número, releído solo: vale si las lecturas coinciden."""

    class _Fuente:
        def trozos_of(self, pagina):
            from resolutions.domain.formulario import Trozo

            return [Trozo("AL CONTESTAR CITE ESTE NUMERORE31102022 69554", 300, 100, 560, 110, "x")]

        def size_of(self, pagina):
            return 612, 792

        def render(self, pagina, banda, dpi, *_):
            return b"png"

    class _Lector:
        def __init__(self, texto):
            self.texto = texto

        def read(self, imagen):
            from resolutions.application.ports import OcrResult

            return OcrResult(self.texto)

    def test_vale_si_coinciden_y_no_si_difieren(self):
        from resolutions.application.sellos import releer_el_renglon

        igual = self._Lector("NUMERORE3 110202269554")
        assert releer_el_renglon(self._Fuente(), 1, [igual, igual]) == "RE3110202269554"
        # UPD2326336 p1: «…821» o «…823» según cómo se lea: se deja ilegible.
        otro = self._Lector("NUMERORE3 110202269553")
        assert releer_el_renglon(self._Fuente(), 1, [igual, otro]) is None
        assert releer_el_renglon(self._Fuente(), 1, [igual]) is None
