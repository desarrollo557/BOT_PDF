"""Lo que el operador pidió para Afinia el 2026-11-18, sobre la caja de Magangué (NIC 1005117 y 1005648).

- Los RE de las oficinas 9233 y 9234 (Magangué, Bolívar Sur) se leen en la
  etiqueta impresa y a mano; antes los reclamos salían sin su RE.
- El RE a mano del sello puede ser del año anterior al del sello: el recurso se
  radica con el RE de la reclamación que recurre.
- «EN ATENCIÓN A…» en una carta de la empresa es CONTESTACIÓN A LA RECLAMACIÓN.
- Las notificaciones personales llevan su RE en el nombre.
- Lo que debe llevar RE y no lo trae va a Revisión, también con «Solo OCR».
- Los folios del sello se contrastan con las hojas de cada documento.
- El formulario «Interposición de recurso(s)» de Afinia abre su documento.
"""

from __future__ import annotations

from datetime import date

from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.sello import (
    Sello,
    folios_que_no_cuadran,
    leer_sello,
    radicado_escrito,
    sello_sin_transcribir,
    validar_el_re_a_mano,
)

#: La etiqueta impresa de 1005117 (UPD2437857 p1), como la deja la capa.
ETIQUETA = (
    "Caribemar de la Costa S.A.S ESP 202260149897\nAL CONTESTAR CITE ESTE NUMERORE9233202202774\n"
    "Asunto: 02 QUEJA Folios: 1\nOficina: Magangue-Bolivar Sur\nFecha: 06/10/2022 15:16:48.0"
)


class TestLasOficinasDeMagangue:
    def test_la_etiqueta_impresa_de_la_9233_da_su_re(self):
        sello = leer_sello(ETIQUETA)
        assert (sello.clase, sello.radicado, sello.fecha, sello.folios) == (
            "impreso", "RE9233202202774", date(2022, 10, 6), 1,
        )

    def test_el_re_a_mano_con_una_cifra_mal_leida_se_lee_y_lo_corrige_el_agente_con_la_caja(self):
        # La IA leyó «RE92382022035-77»: un 3 a mano por un 8. Se lee tal cual…
        leido = radicado_escrito("25.01.2023. RE92382022035-77. 2023600116-90 1. FOLIOS")
        assert leido == "RE9238202203577"
        # …y el agente lo da por la 9233 si la caja es de la 9233; entre la 9233 y la 9234, sin caja, no adivina.
        assert validar_el_re_a_mano(leido, date(2023, 1, 25), {"9233"})[0] == "RE9233202203577"
        assert validar_el_re_a_mano(leido, date(2023, 1, 25))[0] is None

    def test_el_re_a_mano_del_ano_anterior_vale_y_dos_antes_no(self):
        assert validar_el_re_a_mano("RE9233202203621", date(2023, 1, 25)) == ("RE9233202203621", "")
        assert validar_el_re_a_mano("RE9233202103621", date(2023, 1, 25))[0] is None


class TestLaContestacionYLasNotificaciones:
    def test_en_atencion_al_recurso_es_contestacion_a_la_reclamacion(self):
        from resolutions.domain.asunto_del_documento import (
            CONTESTACION_A_RECLAMACION,
            es_contestacion_a_reclamacion,
        )

        respuesta = (
            "AFINIA GRUPO EPM\nConsecutivo No. 202370167866\nMAGANGUE, 14/04/2023\nSeñora:\n"
            "LUZ ESTHELLA MEDRANO RANGEL\nASUNTO: Recurso de reposición en subsidio el de apelación No.RE9233202300708\n"
            "Estimado señor(a): En atención al recurso interpuesto el 24 de marzo de 2023, frente a la"
        )
        assert CONTESTACION_A_RECLAMACION == "CONTESTACION A LA RECLAMACION"
        assert es_contestacion_a_reclamacion(respuesta)

    def test_las_notificaciones_personales_llevan_su_re(self):
        from resolutions.domain.nombre_oficial import lleva_re_en_el_nombre

        assert lleva_re_en_el_nombre("NOTIFICACION PERSONAL")
        assert lleva_re_en_el_nombre("CONTESTACION A LA RECLAMACION")
        assert not lleva_re_en_el_nombre("CONTESTACION A RECLAMACION")

    def test_el_formulario_de_recurso_de_afinia_abre_su_documento(self):
        from resolutions.application.cartas import _es_escrito_del_tramite
        from resolutions.domain.asunto_del_documento import titulo_del_documento

        formulario = (
            "Magangué Bolívar, 24 de Marzo de 2023\nSeñores\nCARIBEMAR DE LA COSTA S.A.S. E.S.P.\n"
            "OFICINA DE PETICIONES, QUEJAS Y RECLAMOS\nCIUDAD.\n"
            "Asunto: Interposición de recurso(s) de L' Re^sición\nReposición y subsidiariamente apeiación ante la SSPD\n"
        )
        assert titulo_del_documento(formulario) == "RECURSO DE REPOSICION EN SUBSIDIO DE APELACION"
        assert _es_escrito_del_tramite(formulario)


def _grupos(*grupos) -> GroupingResult:
    return GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=valor, raw=valor.split()[-1]), page_numbers=paginas, kind=kind)
            for valor, paginas, kind in grupos
        ],
        quarantine=[],
        repairs=[],
    )


class TestLasValidaciones:
    def test_lo_que_debe_llevar_re_y_no_lo_trae_va_a_revision(self):
        from resolutions.api.worker.correspondencia import documentos_sin_su_re

        grupos = _grupos(
            ("01 RE9233202202774", [1], "RECLAMO"),
            ("02", [2, 3], "RECLAMO"),
            ("03", [4], "NOTIFICACION PERSONAL"),
            ("04", [5], "DERECHO DE PETICION"),
            ("05", [6], "RECLAMO"),
        )
        avisos = documentos_sin_su_re(grupos, ya_avisadas={6})
        assert [aviso["page"] for aviso in avisos] == [2, 4]
        assert avisos[0]["reason"].startswith("RECLAMO sin RE")

    def test_los_folios_del_sello_contra_las_hojas(self):
        from resolutions.api.worker.correspondencia import folios_contra_hojas

        assert folios_que_no_cuadran(10, 10) is None
        assert folios_que_no_cuadran(13, 10) is None  # facturas a dos caras
        assert "faltarle" in folios_que_no_cuadran(3, 10)
        assert "de otro" in folios_que_no_cuadran(5, 2)
        assert folios_que_no_cuadran(80, None) is None and folios_que_no_cuadran(5, 99) is None
        sellos = {6: Sello("tinta", "RE9233202300708", date(2023, 3, 24), 10), 16: Sello("impreso", None, None, 3)}
        piezas = [{"pages": list(range(6, 16))}, {"pages": [16]}, {"pages": [17]}]
        assert [(a["page"], "faltarle" in a["reason"]) for a in folios_contra_hojas(piezas, sellos)] == [(16, True)]

    def test_el_sello_que_el_ocr_no_transcribio(self):
        # Como imagen, o sólo la fecha de la carta: no hay sello reconocible.
        assert sello_sin_transcribir("afinia\n24 de Marzo de 2023\n![img-0.jpeg](img-0.jpeg)\nSeñores")
        assert sello_sin_transcribir("| Bolivar | 24 de Marzo | de 2023 |")
        assert not sello_sin_transcribir(ETIQUETA)
        assert not sello_sin_transcribir("FECHA DE RECIBIDO: 24-03-2023 No. DE RADICACION: RE9233202300708")


class TestLoQueSeCorrigeEnLaCaja:
    def test_la_oficina_del_re_a_mano_se_corrige_con_la_de_la_caja_antes_del_tramite(self):
        from resolutions.api.worker.correspondencia import _con_lo_impreso

        sellos = {
            1: Sello("impreso", "RE9233202202774", date(2022, 10, 6), 1),
            5: Sello("tinta", "RE9238202203577", date(2023, 1, 25), 1),
        }
        corregidos_sellos, _, corregidos = _con_lo_impreso(sellos, {}, {1: "", 5: ""})
        assert corregidos_sellos[5].radicado == "RE9233202203577"
        assert "9238 leída por 9233" in corregidos[5]

    def test_renumerar_por_fecha_conserva_que_lleva_el_re_de_su_sello(self):
        from dataclasses import replace

        from resolutions.application.anexos_declarados import _renumerar

        grupo = replace(
            PageGroup(code=ResolutionCode(value="04 RE9233202203577", raw="RE9233202203577"), page_numbers=[5]),
            kind="RECURSO DE REPOSICION EN SUBSIDIO DE APELACION",
            re_en_el_nombre=True,
        )
        (nuevo,), _ = _renumerar([grupo], {})
        assert nuevo.code.value == "1 RE9233202203577" or nuevo.code.value.endswith(" RE9233202203577")
        assert nuevo.re_en_el_nombre and nuevo.kind == grupo.kind


# -- los huecos que quedaban (2026-11-18) ---------------------------------------------------


class TestElReAjeno:
    @staticmethod
    def _poner(grupos, textos, sellos=None, sin_re=()):
        from resolutions.api.worker.correspondencia import _poner_el_re_en_el_nombre

        return _poner_el_re_en_el_nombre(grupos, {}, textos=textos, sellos=sellos or {}, sin_re=set(sin_re), abren=set())

    def test_el_reclamo_no_toma_el_re_que_cita_su_carta(self):
        carta = "Señores AFINIA\nREF. QUEJA Y RECLAMO\nya había presentado la reclamación RE9233202202774 y no me responden"
        grupos, _, hallados = self._poner(_grupos(("01", [1], "RECLAMO")), {1: carta})
        assert grupos.groups[0].code.value == "01" and hallados == {}

    def test_si_la_etiqueta_de_su_hoja_si(self):
        grupos, _, _ = self._poner(_grupos(("01", [1], "RECLAMO")), {1: ETIQUETA})
        assert grupos.groups[0].code.value == "01 RE9233202202774"

    def test_la_notificacion_toma_el_re_que_cita(self):
        notificacion = "NOTIFICACION PERSONAL\nRadicado: RE9233202300708\nEn la fecha 23 de marzo de 2023 comparecio"
        grupos, _, _ = self._poner(_grupos(("01", [1], "NOTIFICACION PERSONAL")), {1: notificacion})
        assert grupos.groups[0].code.value == "01 RE9233202300708"

    def test_la_copia_dentro_de_los_folios_no_da_su_re(self):
        sellos = {2: Sello("impreso", "RE9233202202774", date(2022, 10, 6), 1)}
        grupos, _, _ = self._poner(_grupos(("01", [1, 2], "RECLAMO")), {1: "", 2: ""}, sellos, sin_re={2})
        assert grupos.groups[0].code.value == "01"


class TestElSelloDeLado:
    def test_la_imagen_se_gira_un_cuarto_de_vuelta(self):
        import io

        from PIL import Image

        from resolutions.api.worker.correspondencia import _girada

        imagen = io.BytesIO()
        Image.new("RGB", (40, 10), "white").save(imagen, format="JPEG")
        with Image.open(io.BytesIO(_girada(imagen.getvalue()))) as girada:
            assert girada.size == (10, 40)
        assert _girada(b"no es una imagen") is None


class TestConSoloOcr:
    def test_el_escrito_o_el_sello_de_tinta_sin_re_van_a_revision(self):
        from resolutions.api.worker.correspondencia import documentos_con_sello_sin_re

        grupos = _grupos(
            ("01 RE9233202202774", [1], "RECLAMO"),
            ("02", [2, 3], "RECLAMO"),
            ("03", [4], "RECURSO DE REPOSICION"),
            ("04", [5], "DERECHO DE PETICION"),
            ("05", [6], "CONTESTACION A LA RECLAMACION"),
        )
        sellos = {1: Sello("impreso", "RE9233202202774"), 2: Sello("tinta"), 6: Sello("tinta")}
        # 2: sello de tinta sin RE; 4: escrito del usuario; 6: la copia de una prueba no cuenta.
        assert documentos_con_sello_sin_re(grupos, sellos, no_cuentan={6}, escritos={4}) == [2, 4]


class TestElAcuerdoPorMes:
    def test_en_el_mes_solo_se_ordena_el_tramo_del_acuerdo(self):
        from test_orden_del_acuerdo import (
            CARTA,
            HABEAS_DATA,
            PAGARE,
            RECONOCIMIENTO_FECHADO,
        )

        from resolutions.api.worker.correspondencia import _ordenar_los_acuerdos

        otra = "Señores AFINIA\nDERECHO DE PETICION\nSolicito la revision de mi factura."
        textos = {1: otra, 2: PAGARE, 3: CARTA, 4: RECONOCIMIENTO_FECHADO, 5: HABEAS_DATA, 6: otra}
        grupos = _grupos(("01", [1, 2, 3, 4, 5, 6], "MES"))
        piezas = [{"archivo": 0, "pages": [2, 3, 4, 5], "fecha": "2021-03-08", "fecha_pagina": 4}]
        (mes,) = _ordenar_los_acuerdos(grupos, piezas, textos, {2, 3, 4, 5}, por_mes=True).groups
        # La petición de antes y la de después se quedan en su sitio.
        assert mes.orden == [1, 4, 2, 3, 5, 6]


class TestLaAuditoriaDeLosRadicados:
    def test_la_entrega_vieja_de_1005117_y_la_nueva(self):
        from resolutions.application.auditoria_de_la_entrega import auditar_los_radicados
        from resolutions.domain.conciliacion import ArchivoEntregado

        recurso = (
            "Magangué Bolívar, 25 de enero de 2023\nSeñores\nCARIBEMAR DE LA COSTA S.A.S. E.S.P.\n"
            "OFICINA DE PETICIONES, QUEJAS Y RECLAMOS\nCIUDAD.\nAsunto: Interposición de recurso(s) de Reposición\n"
        )
        respuesta = (
            "Consecutivo No. 202370167866\nMAGANGUE, 14/04/2023\nSeñora:\nLUZ ESTHELLA MEDRANO RANGEL\n"
            "En atención al recurso interpuesto el 24 de marzo de 2023"
        )
        textos = {1: ETIQUETA, 2: recurso, 3: respuesta}
        vieja = auditar_los_radicados(
            [
                ArchivoEntregado("01_RECLAMO-RE9233202202774.pdf", (1,)),
                ArchivoEntregado("02_RECURSO-DE-REPOSICION.pdf", (2,)),
                ArchivoEntregado("03_RECURSO-DE-REPOSICION-EN-SUBSIDIO-DE-APELACION.pdf", (3,)),
            ],
            textos,
        )
        assert len(vieja.dudas) == 2
        assert "escrito del usuario sin RE" in vieja.dudas[0] and "abre con una contestación" in vieja.dudas[1]
        nueva = auditar_los_radicados(
            [
                ArchivoEntregado("01_RECLAMO-RE9233202202774.pdf", (1,)),
                ArchivoEntregado("02_RECURSO-DE-REPOSICION-RE9233202203621.pdf", (2,)),
                ArchivoEntregado("03_CONTESTACION-A-LA-RECLAMACION-RE9233202300708.pdf", (3,)),
            ],
            textos,
        )
        assert not nueva.dudas and not nueva.errores
        assert dict(nueva.cuentas) == {"re confirmados": 1, "re a mano": 2}
        # La etiqueta que dice un RE y el nombre que lleva otro.
        otra = auditar_los_radicados([ArchivoEntregado("01_RECLAMO-RE9233202299999.pdf", (1,))], textos)
        assert "su etiqueta de radicación dice RE9233202202774" in otra.dudas[0]

    def test_el_reconocimiento_en_medio_del_acuerdo_es_un_error_y_los_folios_que_faltan_duda(self):
        from test_orden_del_acuerdo import (
            CARTA,
            HABEAS_DATA,
            PAGARE,
            RECONOCIMIENTO_FECHADO,
        )

        from resolutions.application.auditoria_de_la_entrega import auditar_los_radicados
        from resolutions.domain.conciliacion import ArchivoEntregado

        textos = {1: PAGARE, 2: CARTA, 3: RECONOCIMIENTO_FECHADO, 4: HABEAS_DATA}
        nombre = "01_RECONOCIMIENTO-DE-DEUDA-Y-PROPUESTA-DE-ACUERDO-DE-PAGO.pdf"
        en_medio = auditar_los_radicados([ArchivoEntregado(nombre, (1, 2, 3, 4))], textos)
        assert en_medio.errores and "en medio del acuerdo" in en_medio.errores[0]
        assert not auditar_los_radicados([ArchivoEntregado(nombre, (3, 1, 2, 4))], textos).errores
        assert not auditar_los_radicados([ArchivoEntregado(nombre, (1, 2, 4, 3))], textos).errores
        tres_folios = ETIQUETA.replace("Folios: 1", "Folios: 3")
        corta = auditar_los_radicados([ArchivoEntregado("01_RECLAMO-RE9233202202774.pdf", (1,))], {1: tres_folios})
        assert "faltarle" in corta.dudas[0]


class TestLaPruebaDelOperador:
    """Lo que el operador encontró al probar la versión del 2026-11-18 en su equipo."""

    #: La cabeza del reconocimiento de 1005114 (UPD2973876 pág. 5) como la leyó la IA.
    RECONOCIMIENTO_A_MANO = (
        "Sente fr , 27 de Nov de 2021\n\nafinia\nGrupo·epm\n\nSeñores:\n\nCARIBEMAR DE LA COSTA S.A.S E.S.P.\n\n"
        "La Ciudad\n\n# Ref.: Reconocimiento de deuda y propuesta de acuerdo de pago\n\nYo, Denilo Jimenez"
    )
    #: La Habeas Data de esa misma caja (pág. 1), con el asunto que el escáner rompió.
    HABEAS_ROTA = (
        "aPinia\nDía M Mes\nll\nAño\nGrupo-epr9\nSeñores\nCARIBEMAR DE LA COSTA S.A.S E.S.P\nLa Ciudad\n"
        "ASUNTO: Ley Rabeas Data - NIC\nYo,\nidentificado con. Ja cédula de\n. autorizo a\nexpedida en\n"
        "CARIBEMAR DE LA COSTA S.A.S E.S.P. para enviar de manera física y/oíigital la factura de energía\n"
    )

    def test_el_mes_abreviado_con_su_de_fecha_el_reconocimiento(self):
        from resolutions.domain.fecha_por_estructura import fecha_de_la_hoja
        from resolutions.domain.fechas import _normalizar, fechas_de

        assert fecha_de_la_hoja(self.RECONOCIMIENTO_A_MANO) == date(2021, 11, 27)
        assert fechas_de(_normalizar("Santa Fe, 27 de Nov. de 2021")) == [date(2021, 11, 27)]
        # «mar» no es marzo sin su día y su año.
        assert fechas_de(_normalizar("Caribe mar de la costa 2021")) == []

    def test_la_habeas_data_se_reconoce_con_la_h_rota_y_por_su_cuerpo(self):
        from resolutions.domain.asunto_del_documento import (
            LEY_HABEAS_DATA,
            titulo_del_documento,
        )

        assert titulo_del_documento(self.HABEAS_ROTA) == LEY_HABEAS_DATA
        sin_asunto = self.HABEAS_ROTA.replace("ASUNTO: Ley Rabeas Data - NIC\n", "")
        assert titulo_del_documento(sin_asunto) == LEY_HABEAS_DATA

    def test_la_cedula_detras_del_reconocimiento_va_con_los_anexos(self):
        from test_orden_del_acuerdo import CARTA, PAGARE

        from resolutions.application.anexos_declarados import (
            orden_del_acuerdo,
            partes_del_acuerdo,
        )

        muda = ".-írí-'-'.. ;•.:■* -\n',r'.'^'^-’:v/-:r\ní-\nt r\n*\ns?\n"
        cedula = "FECHA DE NACIMIENTO 21-MAY-1963\nMAGANGUE (BOLIVAR)\nLUGAR DE NACIMIENTO\nESTATURA 1.70 G.S. RH O+\n"
        textos = {1: self.HABEAS_ROTA, 2: PAGARE, 3: CARTA, 4: self.RECONOCIMIENTO_A_MANO, 5: muda, 6: cedula}
        assert partes_del_acuerdo(range(1, 7), textos) == [
            ("habeas", [1]), ("pagares", [2]), ("pagares", [3]), ("reconocimiento", [4]),
            ("anexos", [5]), ("anexos", [6]),
        ]
        assert orden_del_acuerdo(range(1, 7), textos, reconocimiento_fechado=True) == (4, 2, 3, 1, 5, 6)
        assert orden_del_acuerdo(range(1, 7), textos, reconocimiento_fechado=False) == (2, 3, 1, 5, 6, 4)

    def test_el_parrafo_en_mayuscula_sigue_a_la_carta_y_su_sello_al_pie_no_abre(self):
        from resolutions.domain.carta import continua_la_carta

        # 1001389 (UPD3102735 págs. 3 y 4): el reclamo seguía, y el sello al pie
        # de la 4 abría otro documento con la mitad del escrito.
        assert continua_la_carta(
            "Ahora bien, para hacer efectivo el derecho constitucional al debido proceso es necesario que en los\n"
        )
        assert continua_la_carta("En esa medida, se concreta por parte del prestador la garantía del debido proceso en\n")
        # Una cabecera no es prosa: casi todo en mayúscula, o corta.
        assert not continua_la_carta("Operador de Red: Caribemar de la Costa S.A.S E.S.P\nNIU:21381594\n")
        assert not continua_la_carta("Censo de Amplificadores Jigaltel Santa Ana\n")

    def test_el_pqr_roto_de_la_constancia_se_repara_solo_en_lo_que_no_era_cifra(self):
        from resolutions.domain.tramites import pqr_reparado, pqr_roto

        # 1005652 (UPD2437864 pág. 1): sin esto la constancia tomaba por su
        # fecha el RE de la de al lado, RE8673202203514.
        roto = pqr_roto("Recibí constancia del contenido N° PQR: RE86732022b3446 FECHA: 22/08/2022")
        assert roto == "86732022b3446"
        assert pqr_reparado(roto, "N° PQR: RE8673202203446 MESES POR LO") == "RE8673202203446"
        # La relectura que cambia una cifra que la capa sí leyó no vale.
        assert pqr_reparado(roto, "N° PQR: RE8673202203447") is None
        assert pqr_roto("N° PQR: RE8673202203514 FECHA") is None

    def test_el_re_a_mano_de_una_oficina_que_no_existe_no_arma_el_tramite(self):
        from resolutions.api.worker.correspondencia import _con_lo_impreso

        # 1005117: la IA leyó «RE2022202203579» en el reclamo, y su trámite lo
        # ponía en el nombre aunque el agente lo rechazara.
        sellos = {2: Sello("tinta", "RE2022202203579", date(2022, 10, 14), 2)}
        nuevos, _, corregidos = _con_lo_impreso(sellos, {}, {1: ETIQUETA})
        assert nuevos[2].radicado is None
        assert "no se cree" in corregidos[2]
        # El de la oficina a una cifra de la de la caja se sigue corrigiendo.
        cerca = {2: Sello("tinta", "RE9238202203577", date(2023, 1, 25), 1)}
        assert _con_lo_impreso(cerca, {}, {1: ETIQUETA})[0][2].radicado == "RE9233202203577"

    def test_las_oficinas_que_radican_en_bolivar_sur_se_creen_tal_cual(self):
        # Contadas en las entregas de Magangué: la 2320 (1.347 PDF) y la 8673
        # de Santa Ana (2.604) no estaban, y el agente rechazaba su RE o lo
        # «corregía» a otra oficina (1001389: «RE2320…» a mano salía RE2310…).
        assert validar_el_re_a_mano("RE2320202403286", date(2024, 4, 1)) == ("RE2320202403286", "")
        assert validar_el_re_a_mano("RE8673202103319", date(2021, 10, 27)) == ("RE8673202103319", "")
        # Una errata de la letra sigue sin creerse.
        assert validar_el_re_a_mano("RE2022202203579", date(2022, 10, 14))[0] is None


class TestElReDeTodoDocumento:
    """«Cuando haya RE, ya sea en el sello o en la página, lo coloques, siempre y cuando no sea un anexo» (2026-11-18)."""

    #: Lo que el OCR de pago leyó del sello al pie del reclamo de 1005122
    #: (UPD3102765 pág. 1): el RE en la casilla de la notificación, con un 3 leído
    #: 8 y un 1 de más.
    SELLO_AL_PIE = (
        "OFICINA\nBOLIVAR SUR\nRECIBIDO NO IMPLICA ACEPTACIÓN\nFECHA DE RECIBIDO: 12-02-2024\n"
        "No DE RADICACIÓN: 2024600 38949\nNo DE FOLIOS: (04).\nDIR. NOTIFICACIÓN: RE28102024102908\n"
    )

    def test_el_re_fuera_de_su_casilla_se_casa_solo_con_el_que_la_caja_ya_trae(self):
        from resolutions.domain.sello import radicado_con_una_cifra_de_mas

        caja = {"RE2310202402908", "RE2310202409991"}
        assert (
            radicado_con_una_cifra_de_mas(self.SELLO_AL_PIE, caja, 2024, en_cualquier_casilla=True)
            == "RE2310202402908"
        )
        # Sin la caja que lo confirme, dos arreglos serían adivinar.
        assert radicado_con_una_cifra_de_mas(self.SELLO_AL_PIE, (), 2024, en_cualquier_casilla=True) is None
        assert (
            radicado_con_una_cifra_de_mas(self.SELLO_AL_PIE, {"RE2310202409991"}, 2024, en_cualquier_casilla=True)
            is None
        )
        # Y fuera del sello recortado -- en la lectura de una carta -- no se mira otra casilla.
        assert radicado_con_una_cifra_de_mas(self.SELLO_AL_PIE, caja, 2024) is None

    def test_lo_que_se_leyo_del_re_que_no_se_creyo_va_al_aviso(self):
        from resolutions.domain.sello import lo_que_se_leyo_del_re

        # 1001051: el «1» pegado al «9», que ninguna lectura distingue.
        leido = "No DE RADICACIÓN: RE 86732021033A\nNo. DE RADICACION: RE867320210339\nRE867320210339"
        assert lo_que_se_leyo_del_re(leido) == "RE86732021033A / RE867320210339"
        assert lo_que_se_leyo_del_re("RECIBIDO NO IMPLICA ACEPTACION") is None

    def test_el_derecho_de_peticion_toma_la_etiqueta_de_su_pagina(self):
        poner = TestElReAjeno._poner
        grupos, _, hallados = poner(_grupos(("01", [1], "DERECHO DE PETICION")), {1: ETIQUETA})
        assert grupos.groups[0].code.value == "01 RE9233202202774"
        assert grupos.groups[0].re_en_el_nombre
        # El RE que su cuerpo sólo cita no es el suyo.
        carta = "Señores AFINIA\nREF. DERECHO DE PETICION\nsobre la reclamación RE9233202202774 que no me responden"
        grupos, _, _ = poner(_grupos(("01", [1], "DERECHO DE PETICION")), {1: carta})
        assert grupos.groups[0].code.value == "01"
        # Ni la etiqueta de un anexo.
        grupos, _, _ = poner(_grupos(("01", [1, 2], "DERECHO DE PETICION")), {1: carta, 2: ETIQUETA}, sin_re={2})
        assert grupos.groups[0].code.value == "01"
