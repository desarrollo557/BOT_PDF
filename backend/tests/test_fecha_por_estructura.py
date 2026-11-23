"""La fecha de un documento de Afinia, leída donde su estructura la pone.

Fija :mod:`resolutions.domain.fecha_por_estructura` (el operador, 2026-11-10:
«la fecha la tomarás del documento principal… cuando exista un sello, la fecha
que esté dentro del sello»; «la hoja principal no siempre es la primera»). Los
textos imitan la capa de texto de los escaneos reales -- con su desorden y
sus erratas -- sin los datos personales del corpus. Cada caso nombra el
expediente donde se midió la trampa.
"""

from __future__ import annotations

from datetime import date

from resolutions.domain.fecha_por_estructura import (
    fecha_de_la_hoja,
    fecha_entre_lectores,
    fecha_por_estructura,
    hoja_principal,
    pieza_de,
    sin_trampas,
)

HOY = date(2026, 11, 10)

PAGARE = (
    "CARIBEMAR DE LA COSTA S.A.S E.S.P. Territorial: PAGARE No. FECHA DE VENCIMIENTO: VALOR $ "
    "CIUDAD Y DIRECCION DONDE SE EFECTUARA EL PAGO: declaro que por virtud de este documento pagaré "
    "incondicionalmente a la orden de CARIBEMAR DE LA COSTA S.A.S ESP"
)
CARTA_TABLA = (
    "CARTA DE INSTRUCCIONES ANEXA AL PAGARE No. 1000186-7 CON ESPACIOS ABIERTOS identificado(s) como "
    "aparece al pie de mi firma… detalle: Tipo de servicio Energía regulada Símbolo Variable NIR "
    "Fecha Vto, Importe $255.766,00 13/04/2021 1000186007 1.107261-06/04/2021"
)
CARTA_FIRMA = (
    "6. La fecha del pagaré será aquella en que se llenen los espacios dejados en blanco. Dejo constancia "
    "que en mi poder ha quedado una copia del presente documento. del 2021 MAGANGUE a los 6 días del mes "
    "de Abril Firmado en la ciudad de FIRMA: NOMBRE: C.C: RAZON SOCIAL: NIT:"
)
RECONOCIMIENTO_A_MANO = (
    "ÜD _ , ^ de de Grupo*epnp Señores: CARIBEMAR DE LA COSTA S.A.S E.S.P. La Ciudad Ref.: Reconocimiento "
    "de deuda y propuesta de acuerdo de pago Yo, identificado como aparece al pie de mi firma… reconozco "
    "como deuda clara, expresa y actualmente exigible"
)
RECONOCIMIENTO = (
    "El Banco, 23 de diciembre de 2020 Grupo-epm Señores: CARIBEMAR DE LA COSTA S.A.S E.S.P. La Ciudad "
    "Ref.: Reconocimiento de deuda y propuesta de acuerdo de pago Yo, identificado como aparece al pie "
    "de mi firma, reconozco como deuda clara, expresa y actualmente exigible"
)
CAMARA = (
    "CAMARA DE COMERCIO SANTA MARTA CERTIFICADO DE MATRICULA MERCANTIL Número de operación:04C690417046 "
    "Fecha: 20120417 MATRICULA NO: 00139299 DEL 16 DE ABRIL DE 2012 RENOVO EL AÑO 2012, EL 16 DE ABRIL DE 2012"
)
CEDULA = "REPUBLICA DE COLOMBIA IDENTIFICACION PERSONAL CEDULA DE CIUDADANIA FECHA DE NACIMIENTO 08-ABR-1958 ESTATURA 1.62 G.S. RH O+"


def _paginas(*textos: str) -> dict[int, str]:
    return {i: t for i, t in enumerate(textos, start=1)}


class TestElAcuerdoDePago:
    def test_lo_fecha_el_reconocimiento_aunque_no_sea_la_primera_hoja(self) -> None:
        textos = _paginas(
            PAGARE, CARTA_TABLA, CARTA_FIRMA, RECONOCIMIENTO, CEDULA, CAMARA
        )
        r = fecha_por_estructura(list(textos), textos, hoy=HOY)
        assert r.principal == 4
        assert (r.fecha, r.pagina, r.fuente) == (
            date(2020, 12, 23),
            4,
            "reconocimiento de deuda",
        )

    def test_nunca_el_certificado_de_camara_de_comercio_anexo(self) -> None:
        # UPD2984936 (3807860): salía el 16/04/2012 del certificado de las págs. 6-7.
        textos = _paginas(PAGARE, CARTA_TABLA, RECONOCIMIENTO_A_MANO, CEDULA, CAMARA)
        r = fecha_por_estructura(list(textos), textos, hoy=HOY)
        assert r.fecha is None
        # Sin fecha en la capa, se relee la principal: nunca un anexo.
        assert r.donde_buscar[0] == 3
        assert not {4, 5} & set(r.donde_buscar)

    def test_sin_el_reconocimiento_legible_lo_respalda_la_firma_de_la_carta(self) -> None:
        # Coincidió con el reconocimiento en 14 de 14 acuerdos medidos.
        textos = _paginas(PAGARE, CARTA_TABLA, CARTA_FIRMA, RECONOCIMIENTO_A_MANO, CEDULA)
        r = fecha_por_estructura(list(textos), textos, hoy=HOY)
        assert (r.fecha, r.pagina) == (date(2021, 4, 6), 3)
        assert r.donde_buscar == (4, 3)

    def test_la_tabla_fecha_vto_de_la_carta_no_fecha_nada(self) -> None:
        # UPD2437815, UPD3102728, DOCUMENTO_24: los vencimientos de las facturas financiadas.
        textos = _paginas(PAGARE, CARTA_TABLA, RECONOCIMIENTO_A_MANO)
        assert fecha_por_estructura(list(textos), textos, hoy=HOY).fecha is None

    def test_la_habeas_data_respalda_con_sus_casillas(self) -> None:
        habeas = (
            "Día 25 Mes 03 Año 2022 Grupo-epm Señores CARIBEMAR DE LA COSTA S.A.S E.S.P La Ciudad ASUNTO: "
            "Ley Habeas Data - NIC 3803971 autorizo… Ley 1581 de 2012 Fecha:"
        )
        textos = _paginas(PAGARE, RECONOCIMIENTO_A_MANO, habeas)
        r = fecha_por_estructura(list(textos), textos, hoy=HOY)
        assert (r.fecha, r.fuente) == (date(2022, 3, 25), "Ley Habeas Data")

    def test_el_comprobante_de_la_cuota_inicial_no_le_gana_al_reconocimiento(
        self,
    ) -> None:
        cupon = "COMPROBANTE CUPON MANUAL Nro. 301420220211000013378 FECHA DIA MES ANIO 2 5 MAR 2022"
        textos = _paginas(PAGARE, RECONOCIMIENTO, cupon)
        r = fecha_por_estructura(list(textos), textos, hoy=HOY)
        assert (r.principal, r.fecha) == (2, date(2020, 12, 23))


class TestLasConstancias:
    def test_la_fecha_tras_el_pqr_y_no_el_plazo(self) -> None:
        # UPD2437816: salía el 25/05/2021, «a más tardar el…».
        constancia = (
            "PARA LA EMPRESA Recibí constancia del contenido de la reclamación presentada ante CARIBEMAR DE LA "
            "COSTA S.A.S. ESP MESES POR LO QUE RECLAMA: N»PQR: RE2320202101914 FECHA: 03/05/2021 CAUSA: "
            "Facturación SERVICIO: 10812 NOTIFICACIÓN: La decisión de este requerimiento, le será notificada a "
            "más tardar el 25/05/2021 11:59:59 PM"
        )
        textos = _paginas(constancia)
        assert fecha_por_estructura([1], textos, hoy=HOY).fecha == date(2021, 5, 3)

    def test_la_de_recepcion_y_no_la_de_atencion_vence(self) -> None:
        # UPD2437815 p3: salía el 01/12/2020.
        constancia = (
            'CONSTANCIA DE RECEPCIÓN DE PETICIONES. QUEJAS Y RECLAMOS (POR) N" POR: RE2310202007709 FECHA DE '
            "RECEPCIÓN: 09/11/2020 . FECHA DE ATENCION VENCE: 01/12/2020 CODIGO (NIC): 1000186"
        )
        assert fecha_por_estructura([1], _paginas(constancia), hoy=HOY).fecha == date(
            2020, 11, 9
        )


class TestLasCartasDeLaEmpresa:
    def test_la_publicacion_por_su_dia_y_no_por_el_aviso_de_la_misma_imagen(self) -> None:
        # UPD2437824 p4: el aviso y su publicación escaneados en una imagen.
        hoja = (
            "Consecutivo No. PA 202170170241 Cartagena, 16-06-2021 Consecutivo NO.A202170156706 PUBLICACIÓN "
            "DEL AVISO Señor(a) … El presente aviso se publica el día 28/06/2021 06:01:45.0 y hasta por cinco días"
        )
        r = fecha_por_estructura([1], _paginas(hoja), hoy=HOY)
        assert (r.fecha, r.fuente) == (date(2021, 6, 28), "publicación del aviso")

    def test_la_notificacion_personal_por_el_dia_en_que_comparecio(self) -> None:
        hoja = (
            "NOTIFICACIÓN PERSONAL RECLAMOS En la fecha 10 de agosto de 2023 compareció a las oficinas de "
            "CARIBEMAR DE LA COSTA S.A.S. E.S.P. … Fecha de la factura 02/07/2023"
        )
        assert fecha_por_estructura([1], _paginas(hoja), hoy=HOY).fecha == date(
            2023, 8, 10
        )

    def test_la_respuesta_por_la_linea_bajo_el_consecutivo_y_no_por_lo_que_cita(
        self,
    ) -> None:
        hoja = (
            "aPinia Grupo-epm Consecutivo No. 230810124036573 MAGANGUE, 10 de agosto de 2023 Señor(a) … ASUNTO: "
            "Reclamación No. RE2310202306254 En atención a su escrito recibido el día 19/07/2023"
        )
        assert fecha_por_estructura([1], _paginas(hoja), hoy=HOY).fecha == date(
            2023, 8, 10
        )

    def test_la_respuesta_con_la_barra_del_anio_comida(self) -> None:
        # 18_RECURSO: «22/02 2022»; caía en «recibido el día 21 de febrero».
        hoja = "Consecutivo No. 202270057923 AGUSTIN CODAZZI, 22/02 2022 Señor … presentado el día 21 de febrero de 2022"
        assert fecha_por_estructura([1], _paginas(hoja), hoy=HOY).fecha == date(
            2022, 2, 22
        )

    def test_la_guia_de_lecta_que_acompania_a_la_citacion_no_la_fecha(self) -> None:
        # 01-RE3110202201758: las casillas de la guía (día 18) le ganaban a la citación del 14.
        citacion = "Consecutivo No. C202270010 Cartagena, 14/01/2022 Asunto: Citación para notificación personal"
        guia = "LECTA Nit 806.003.042-7 GUIA No. 700012345 FECHA DE ENTREGA Ó INTENTO DE ENTREGA"
        r = fecha_por_estructura(
            [1, 2], _paginas(citacion, guia), guias={2: date(2022, 1, 18)}, hoy=HOY
        )
        assert r.fecha == date(2022, 1, 14)

    def test_la_guia_sola_se_fecha_con_lo_que_marco_el_mensajero(self) -> None:
        guia = "LECTA Nit 806.003.042-7 GUIA No. 700012345 FECHA DE ENTREGA Ó INTENTO DE ENTREGA"
        r = fecha_por_estructura(
            [1], _paginas(guia), guias={1: date(2022, 1, 18)}, hoy=HOY
        )
        assert (r.fecha, r.fuente) == (date(2022, 1, 18), "fecha marcada en la guía")


class TestLasActasTecnicas:
    def test_el_acta_por_su_frase_y_no_por_las_lecturas(self) -> None:
        # Acta 28975271: salía el 12/09/2021 (la lectura actual, mes/día) o el 22/11/2021 (la anterior).
        acta = (
            "Acta de Irregularidad ACTA DE REVISIÓN NÚMERO: 28975271 Grupo-epm A los 9 días del mes 12 del 2021 "
            "se hace presente en el inmueble… Lecturas Fecha última lectura: 22/11/2021 -05:00 Fecha lectura "
            "actual : 12/9/2021"
        )
        assert fecha_por_estructura([1], _paginas(acta), hoy=HOY).fecha == date(
            2021, 12, 9
        )

    def test_la_liquidacion_va_mes_dia_anio(self) -> None:
        liquidacion = (
            "Liquidación del Consumo No registrado Pendiente Por Facturar: C.N.R.P.F Grupo-epm 12/10/2021 "
            "5825181 Nro. Consecutivo Nro. Acta: 28975271 Fecha; CONSUMOS 20211122"
        )
        assert fecha_por_estructura([1], _paginas(liquidacion), hoy=HOY).fecha == date(
            2021, 12, 10
        )


class TestElComprobanteYLaFactura:
    def test_el_sello_de_la_caja_partido_por_la_capa(self) -> None:
        # UPD2984939 (3807972): «2 5 ABR 2022» salía 05/04/2022.
        cupon = (
            "COMPROBANTE CUPON MANUAL Nro. 3014202203100000134903 NIT. 901.380.949 FECHA NIC ANIO DIA MES "
            "VALOR CANCELADO: 2 5 ABR 2022 ESTE ABONO"
        )
        r = fecha_por_estructura([1], _paginas(cupon), hoy=HOY)
        assert (r.fecha, r.fuente) == (date(2022, 4, 25), "comprobante de pago")

    def test_el_numero_del_cupon_no_es_una_fecha(self) -> None:
        cupon = "COMPROBANTE CUPON MANUAL Nro. 3014202104290000122013 FECHA DIA MES ANIO"
        assert fecha_por_estructura([1], _paginas(cupon), hoy=HOY).fecha is None

    def test_las_casillas_con_el_anio_en_dos_cifras(self) -> None:
        """4100929 (UPD3138049, 2026-11-18): «FECHA DIA MES AÑO 01 09 22», el sello de la caja sin leer."""
        cupon = (
            "| COMPROBANTE CUPON MANUAL N- 136329 | Nro-3014202203100000 | ID DE COBROS: | 4 | 1 | 0 | 0 | 9 | 2 |\n"
            "| FORMA DE PAGO: | VALOR CANCELADO: | 24.570 | EFECTIVO ☑ | FECHA DIA MES AÑO 01 09 22 |"
        )
        assert fecha_por_estructura([1], _paginas(cupon), hoy=HOY).fecha == date(2022, 9, 1)

    def test_el_sello_manda_sobre_las_casillas(self) -> None:
        # El operador, 2026-11-18: «principalmente la del sello, y cuando no se vea, la otra».
        cupon = "COMPROBANTE CUPON MANUAL Nro. 30142022 FECHA DIA MES AÑO 07 04 2022 CAM 08 ABR 2022 PAGADO"
        assert fecha_por_estructura([1], _paginas(cupon), hoy=HOY).fecha == date(2022, 4, 8)

    def test_las_casillas_con_los_rotulos_tapados_por_la_etiqueta(self) -> None:
        """1000883 (UPD3102731, 2026-11-18): la etiqueta de la caja tapa «DÍA MES AÑO»."""
        cupon = (
            "| COMPROBANTE CUPON MANUAL N-137575 | Nro-3014202203100000 |\n"
            "| ID DE COBROS: 1 0 0 0 8 8 3 0 2 2 - 0 7 | | | | 30 08 2022 |"
        )
        assert fecha_por_estructura([1], _paginas(cupon), hoy=HOY).fecha == date(2022, 8, 30)

    def test_el_dia_pegado_al_id_de_cobros(self) -> None:
        # 4100877: la IA pegó el día al ID de cobros y dejó «3 | 22». El ID
        # lleva dos casillas tras la raya («-2 3»); el «10» es la casilla DÍA,
        # y el sello dice 10 MAR 2022 (2026-11-19: antes se dejaba sin fecha y
        # la visión copiaba un sello borroso, «09-03-22»).
        cupon = "COMPROBANTE CUPON MANUAL FECHA DIA | MES | ANIO ID DE COBROS: *4100877259-2310* | | 3 | 22 |"
        assert fecha_por_estructura([1], _paginas(cupon), hoy=HOY).fecha == date(2022, 3, 10)

    def test_sin_el_dia_no_se_inventa(self) -> None:
        # 4100875 pág. 2: el sello tapa el día y el mes; el «6 6» es el ID.
        cupon = "COMPROBANTE CUPON MANUAL FECHA DIA | MES | ANIO ID DE COBROS: 4 1 0 0 8 7 5 2 5 2 - 6 6 | | 2021 |"
        assert fecha_por_estructura([1], _paginas(cupon), hoy=HOY).fecha is None

    def test_la_factura_anexa_no_fecha_el_escrito(self) -> None:
        # UPD3138018 (4100325): salía el 16/11/2023 de la factura de la pág. 2.
        escrito = "Talaigua nuevo Bolívar Señores Afinia Grupo EPM Cordial saludo La Presente es para solicitar…"
        factura = (
            "OPERADOR DE RED Caribe Mar USE ESTE NÚMERO PARA CONSULTAS NIC 4100325 ID DE COBROS PAGO OPORTUNO "
            "HASTA 16/11/2023 Suspensión a partir de: 27/09/2023 Fecha emisión: 17/08/2023 Factura No."
        )
        r = fecha_por_estructura([1, 2], _paginas(escrito, factura), hoy=HOY)
        assert r.principal == 1
        assert r.fecha is None
        assert r.donde_buscar == (1,)


class TestLosFormulariosDelCliente:
    """4100993 y 4100918 (2026-11-18): la fecha a mano de la solicitud y de la declaración."""

    def test_la_solicitud_de_servicio_no_es_una_habeas_data(self) -> None:
        # Sus consentimientos nombran «el tratamiento de datos personales».
        solicitud = (
            "Quiero Activar mi Energía con CaribeMar Solicitud de Servicio Eléctrico en Baja Tensión\n"
            "Señores: Ciudad CÉCULO 07 de Enero de 2022\nCaribeMar de la Costa S.A. E.S.P.\n"
            "REFERENCIA: SOLICITUD DE SERVICIO ELÉCTRICO EN BAJA TENSIÓN\n"
            "Consentimientos: … el consentimiento otorgado para el tratamiento de datos personales."
        )
        r = fecha_por_estructura([1], _paginas(solicitud), hoy=HOY)
        assert (r.fecha, r.fuente) == (date(2022, 1, 7), "solicitud de servicio")

    def test_la_declaracion_con_el_mes_delante(self) -> None:
        declaracion = (
            "afinia Grupo·epm Lugar: CICUCO Fecha: Enero 5 del 2022\n"
            "# REFERENCIA: DECLARACION BAJO GRAVEDAD DE JURAMENTO NIC 4100993"
        )
        r = fecha_por_estructura([1], _paginas(declaracion), hoy=HOY)
        assert (r.fecha, r.fuente) == (date(2022, 1, 5), "declaración bajo juramento")

    def test_la_declaracion_con_el_anio_en_dos_cifras(self) -> None:
        declaracion = "Lugar: Santa Rosa\nFecha: 09/06/21\nREFERENCIA: DECLARACION BAJO GRAVEDAD DE JURAMENTO\nNIC 4100918"
        assert fecha_por_estructura([1], _paginas(declaracion), hoy=HOY).fecha == date(2021, 6, 9)

    def test_la_declaracion_con_el_mes_en_letras_entre_guiones(self) -> None:
        # 4100924 «27-MARZO-2022» y 4100975 «Agosto-11-2021».
        for escrita, fecha in (("27-MARZO-2022", date(2022, 3, 27)), ("Agosto-11-2021", date(2021, 8, 11))):
            declaracion = f"Lugar: MAGANGUE Fecha: {escrita} REFERENCIA: DECLARACION BAJO GRAVEDAD DE JURAMENTO"
            assert fecha_por_estructura([1], _paginas(declaracion), hoy=HOY).fecha == fecha

    def test_la_solicitud_con_el_anio_partido_entre_lo_impreso_y_lo_escrito(self) -> None:
        # 4100975: «de 20» impreso y «21» a mano, y lo escrito sobre la raya.
        for escrita in ("Magangue 11 de Agosto de 20 21", "Magangue __11__ de __Agosto__ de 20_21"):
            solicitud = (
                f"Solicitud de Servicio Eléctrico en Baja Tensión Señores: Ciudad {escrita} "
                "REFERENCIA: SOLICITUD DE SERVICIO ELÉCTRICO EN BAJA TENSIÓN"
            )
            assert fecha_por_estructura([1], _paginas(solicitud), hoy=HOY).fecha == date(2021, 8, 11)

    def test_el_encabezado_con_el_anio_partido(self) -> None:
        # 1005117 pág. 4: «de 20» impreso en el formato del recurso y «23» a mano.
        recurso = (
            "afinia Grupo·epm Maganque Bolívar, 25 de enero de 20 23. (Municipio) (día) (mes) (año) Señores "
            "CARIBEMAR DE LA COSTA S.A.S. E.S.P. Asunto: Interposición de recurso(s) de Reposición"
        )
        assert fecha_por_estructura([1], _paginas(recurso), hoy=HOY).fecha == date(2023, 1, 25)

    def test_el_correo_reenviado_con_su_enviado_el_mas_abajo(self) -> None:
        from resolutions.domain.fecha_por_estructura import _del_correo

        # 4100977: la tabla del banco delante y «Enviado el:» más abajo.
        correo = (
            "Merly Mejia Vega Asunto: Datos adjuntos: RV: Confirmar y aplicar " + "| 23-07-2019 | 3.049.890 | " * 12
            + "De: Jaiver Antonio Rada Suarez Enviado el: martes 30 de julio de 2019 07:49 AM Para: Nicolas"
        )
        assert _del_correo(correo, HOY) == date(2019, 7, 30)

    def test_el_expediente_de_la_solicitud(self) -> None:
        # 4100975 pág. 2: la oficina lo abre con la solicitud.
        expediente = (
            "Grupo EPM CARIBEMAR DE LA COSTA S.A.S. ESP EXPEDIENTE No. Expediente: P23202021080008 "
            "Fecha de solicitud del Servicio: 11/08/2021 # DATOS CLIENTE"
        )
        r = fecha_por_estructura([1], _paginas(expediente), hoy=HOY)
        assert (r.fecha, r.fuente) == (date(2021, 8, 11), "expediente de la solicitud")

    def test_el_retie_respalda_la_declaracion_que_no_deja_leer_su_fecha(self) -> None:
        # 4100975 págs. 6-7: la declaración sin fecha legible, el RETIE firmado ese día.
        declaracion = "Lugar: MAGNOLIA Fecha: 16/05/10-11-2021 REFERENCIA: DECLARACION BAJO GRAVEDAD DE JURAMENTO"
        retie = (
            "DECLARACIÓN DE CUMPLIMIENTO DEL RETIE (REGLAMENTO TÉCNICO DE INSTALACIONES ELÉCTRICAS) … "
            "En constancia se firma en la ciudad de MAGAUGOS el 11 de Agosto del 2021 Firma"
        )
        assert fecha_por_estructura([1, 2], _paginas(declaracion, retie), hoy=HOY).fecha == date(2021, 8, 11)
        # Sin el día no hay fecha (4100993 pág. 8).
        sin_dia = retie.replace("el 11 de Agosto del 2021", "el __ de 01 del 2022")
        assert fecha_por_estructura([1], _paginas(sin_dia), hoy=HOY).fecha is None

    def test_la_declaracion_sin_fecha_no_se_inventa(self) -> None:
        declaracion = "Lugar: Fecha: REFERENCIA: DECLARACION BAJO GRAVEDAD DE JURAMENTO NIC 4100975"
        assert fecha_por_estructura([1], _paginas(declaracion), hoy=HOY).fecha is None


class TestLaFechaVistaPorLaIa:
    """El último recurso del agente de fechas (2026-11-18): lo que la IA con visión copia de la hoja."""

    def test_el_sello_manda_despues_las_casillas_y_al_final_el_documento(self) -> None:
        from resolutions.domain.fecha_por_estructura import fecha_de_lo_visto

        assert fecha_de_lo_visto("SELLO: 01 SEP 2022\nCASILLAS: 01 09 22\nDOCUMENTO: no hay") == (
            date(2022, 9, 1),
            "sello",
        )
        assert fecha_de_lo_visto("SELLO: no hay\nCASILLAS: 10 3 22\nDOCUMENTO: no hay") == (date(2022, 3, 10), "casillas")
        assert fecha_de_lo_visto("SELLO: ilegible\nCASILLAS: no hay\nDOCUMENTO: Agosto-11-2021") == (
            date(2021, 8, 11),
            "documento",
        )
        assert fecha_de_lo_visto("DOCUMENTO: Cicuco 07 de Enero de 20 22") == (date(2022, 1, 7), "documento")

    def test_el_sello_con_blancos_manda_sobre_la_fecha_que_el_recurso_cita(self) -> None:
        """1005117 (UPD2437857 pág. 4): el sello «25 01 2023»; el «21 de Diciembre» es el del acto que recurre."""
        from resolutions.domain.fecha_por_estructura import fecha_de_lo_visto

        visto = "SELLO: 25 01 2023\nCASILLAS: 25 de junio de 20 23\nDOCUMENTO: 21 de Diciembre de 20 22"
        assert fecha_de_lo_visto(visto, leido="Maganque Bolívar, 25 de enero de 20 23.") == (date(2023, 1, 25), "sello")

    def test_lo_que_se_contradice_o_nadie_mas_leyo_no_es_una_fecha(self) -> None:
        """4100877 (2026-11-18): las casillas dicen 10-03-22; la IA copió «09-2-2022» y un sello «09-02-23»."""
        from resolutions.domain.fecha_por_estructura import fecha_de_lo_visto

        leido = "| DIA | MES | ANIO | ID DE COBROS: *4100877259-2310* | | 3 | 22 |"
        assert fecha_de_lo_visto("SELLO: 09-02-23\nCASILLAS: 09 - 2 - 2022\nDOCUMENTO: no hay", leido=leido) is None
        assert fecha_de_lo_visto("SELLO: 09-02-23\nCASILLAS: no hay\nDOCUMENTO: no hay", leido=leido) is None

    def test_lo_ilegible_o_a_medias_no_es_una_fecha(self) -> None:
        from resolutions.domain.fecha_por_estructura import fecha_de_lo_visto

        assert fecha_de_lo_visto("SELLO: ilegible\nCASILLAS: ilegible\nDOCUMENTO: no hay") is None
        assert fecha_de_lo_visto("DOCUMENTO: el __ de 01 del 2022") is None
        assert fecha_de_lo_visto("CASILLAS: 3 22") is None
        assert fecha_de_lo_visto("sin sello") is None


class TestLaFechaEntreLectores:
    """6833660 (2026-11-23): «Fecha: 19-02-2021» a mano; cada lector erró una cifra y salía la de la IA."""

    #: Lo que leyeron de la hoja el OCR de pago y Tesseract.
    LECTURAS = ("Lugar: Santa Rosa Fecha: 19-02-2027 REFERENCIA: DECLARACION", "Fecha: NA-OT7- 2021 REFERENCIA")
    VISTA = date(2021, 7, 19)

    def test_se_arma_con_lo_de_cada_lector_y_la_caja_desempata(self) -> None:
        armada = fecha_entre_lectores(self.VISTA, self.LECTURAS, [date(2021, 2, 19)], hoy=HOY)
        assert armada == date(2021, 2, 19)

    def test_sin_la_caja_no_se_toca(self) -> None:
        # Nada desempata entre el 19-07 de la IA y el 19-02 del OCR: queda la vista.
        assert fecha_entre_lectores(self.VISTA, self.LECTURAS, [], hoy=HOY) is None
        assert fecha_entre_lectores(self.VISTA, self.LECTURAS, [date(2021, 3, 4)], hoy=HOY) is None

    def test_la_vista_que_trae_la_caja_o_que_nadie_contradice_se_queda(self) -> None:
        assert fecha_entre_lectores(self.VISTA, self.LECTURAS, [self.VISTA, date(2021, 2, 19)], hoy=HOY) is None
        assert fecha_entre_lectores(self.VISTA, ["Fecha: 19-07-2021"], [date(2021, 2, 19)], hoy=HOY) is None

    def test_otra_fecha_de_la_hoja_no_es_la_misma_mal_leida(self) -> None:
        # La factura citada, a más de dos cifras: no arma nada aunque la caja la traiga.
        citada = ["según la factura del 05/11/2019, Fecha: ilegible"]
        assert fecha_entre_lectores(self.VISTA, citada, [date(2019, 11, 5)], hoy=HOY) is None

    def test_nunca_una_fecha_que_ningun_lector_leyo(self) -> None:
        # La caja trae el 20-02-2021, pero el día 20 no lo leyó nadie en esta hoja.
        assert fecha_entre_lectores(self.VISTA, self.LECTURAS, [date(2021, 2, 20)], hoy=HOY) is None

    def test_si_la_caja_confirma_dos_armadas_no_se_elige(self) -> None:
        lecturas = ["Fecha: 19-02-2027", "Fecha: 18-07-2021"]
        caja = [date(2021, 2, 19), date(2021, 7, 18)]
        assert fecha_entre_lectores(self.VISTA, lecturas, caja, hoy=HOY) is None


class TestElSelloManda:
    def test_el_sello_de_la_hoja_principal_manda_sobre_su_encabezado(self) -> None:
        # Formulario de Magangué: encabezado 09/04, sello 12/04/2021.
        escrito = "Magangué, 09 de abril de 2021 Señores CARIBEMAR Ref: Reclamo"
        r = fecha_por_estructura(
            [1], _paginas(escrito), sellos={1: date(2021, 4, 12)}, hoy=HOY
        )
        assert (r.fecha, r.fuente) == (date(2021, 4, 12), "sello de radicación")

    def test_el_derecho_de_peticion_con_sello_lleva_la_fecha_del_sello(self) -> None:
        # 7741429 (2026-11-23), con datos inventados: la carta del 25 de mayo,
        # radicada el 3 de junio. El operador: «siempre y cuando un documento
        # tenga sello, la fecha será tomada del sello, como primera opción».
        carta = "Mompox, Bolívar. 25 de mayo del 2021.\nSeñores AFINIA\nRef. DERECHO DE PETICION"
        r = fecha_por_estructura([1], _paginas(carta), sellos={1: date(2021, 6, 3)}, hoy=HOY)
        assert (r.fecha, r.fuente) == (date(2021, 6, 3), "sello de radicación")
        # Sin sello, la de la carta: lo normal.
        assert fecha_por_estructura([1], _paginas(carta), hoy=HOY).fecha == date(2021, 5, 25)

    def test_el_sello_de_tinta_que_la_capa_deja_leer(self) -> None:
        escrito = "Señores CARIBEMAR REF: recurso contra la factura del 05/10/2021 RECIBIDO NO IMPLICA ACEPTACIÓN FECHA DE RECIBIDO: 21-02-2022"
        assert fecha_por_estructura([1], _paginas(escrito), hoy=HOY).fecha == date(
            2022, 2, 21
        )

    def test_el_ref_del_recurso_no_fecha_el_escrito(self) -> None:
        # La plantilla de Agustín Codazzi: 0 de 11; el sello de tinta, a mano, no está en la capa.
        escrito = (
            "1 Señores CARIBEMAR DE LA COSTA S.A.S. E.S.P. REF: RECURSO DE REPOSICIÓN contra la factura de "
            "fecha 12/10/2021 y el acta de revisión del 09/12/2021, notificado el 18 de febrero de 2022"
        )
        assert fecha_por_estructura([1], _paginas(escrito), hoy=HOY).fecha is None

    def test_la_carta_del_cliente_abre_aunque_detras_venga_una_publicacion(self) -> None:
        # RESOLUCION_010-2020 p50-56: la copia de la publicación que el cliente aporta detrás de
        # su derecho de petición le ganaba como hoja principal y lo fechaba con el 09/11/2022.
        carta = "Agustín Codazzi, 31 de agosto de 2022\nSeñores:\nafinia Grupo EPM\nREF: Derecho de Petición según el Artículo 23"
        publicacion = "Consecutivo No. PA 202270451135 PUBLICACIÓN DEL AVISO … El presente aviso se publica el día 09/11/2022 08:00:00.0"
        r = fecha_por_estructura([1, 2], _paginas(carta, publicacion), hoy=HOY)
        assert (r.principal, r.fecha) == (1, date(2022, 8, 31))
        assert pieza_de(carta).nombre == "carta"
    def test_una_hoja_con_sello_nunca_es_un_anexo(self) -> None:
        # DOCUMENTO_35 p5: el recurso nombra en su cabeza la factura que aporta; su sello, leído
        # por la IA (21/07/2022), no llegaba al documento porque la hoja se tomaba por factura.
        recurso = "OPERADOR DE RED Caribe Mar USE ESTE NÚMERO PARA CONSULTAS Factura No. Fecha emisión: 03/04/2022"
        assert pieza_de(recurso).anexo
        r = fecha_por_estructura([1], _paginas(recurso), sellos={1: date(2022, 7, 21)}, hoy=HOY)
        assert (r.fecha, r.fuente) == (date(2022, 7, 21), "sello de radicación")

    def test_la_hoja_con_sello_es_la_principal(self) -> None:
        factura = "OPERADOR DE RED Caribe Mar USE ESTE NÚMERO PARA CONSULTAS NIC 1 Fecha emisión: 03/04/2022 Factura No."
        escrito = "Señores Afinia Ref: Reclamo"
        piezas = {1: pieza_de(factura), 2: pieza_de(escrito)}
        assert hoja_principal([1, 2], piezas, frozenset({2})) == 2


class TestLasHojasReleidas:
    def test_la_releida_se_fecha_por_su_clase(self) -> None:
        releida = "El Banco, 23 de 12 de 2020 Señores: CARIBEMAR Ref.: Reconocimiento de deuda y propuesta de acuerdo de pago"
        assert fecha_de_la_hoja(releida, hoy=HOY) == date(2020, 12, 23)

    def test_un_anexo_releido_no_da_fecha(self) -> None:
        assert fecha_de_la_hoja(CEDULA, hoy=HOY) is None
        assert fecha_de_la_hoja(CAMARA, hoy=HOY) is None


class TestLaFechaRazonada:
    """La hoja sin estructura conocida: la fecha de su rótulo «FECHA:» en la cabeza (2026-11-11).

    945220 (UPD2998536): «REVISIÓN DE PROCEDIMIENTOS», a mano. La IA leyó
    «FECHA: 03/08/2021» y salió «S.F.»: la hoja no es de ninguna clase y al
    escrito sólo se le cree un «FECHA:» con la hora del rótulo de radicación.
    """

    #: Lo que leyó la IA, recortado.
    LEIDA_POR_LA_IA = (
        "# REVISIÓN DE PROCEDIMIENTOS\n\nFECHA: 03/08/2021\n\nASOCIADO COMERCIAL: Cam Colombia\n\nPUNTO DE PAGO:\n\n"
        "# PROCESOS\n\n1.1 Conocimiento y documentación\n1.2 Censos de carga y modificaciones\n\n# OBSERVACIONES\n\n"
        "Se realiza verificación en terreno por solicitud del Sector Jose de los Peres con Cedula # 945.220"
    )
    #: Su capa: la fecha a mano no está.
    CAPA = "REVISIÓN DE PROCEDIMIENTOS\nFECHA: \n/\nASOCIADO COMERCIAL:\nPUNTO DE PAGO:\nPROCESOS\n1.1 Conocimiento"

    def test_la_leida_por_la_ia_se_fecha_por_su_rotulo(self) -> None:
        assert fecha_de_la_hoja(self.LEIDA_POR_LA_IA, hoy=HOY) == date(2021, 8, 3)
        hallada = fecha_por_estructura([1], {1: self.LEIDA_POR_LA_IA}, hoy=HOY)
        assert hallada.fecha == date(2021, 8, 3) and hallada.pagina == 1

    def test_sin_la_fecha_en_el_papel_no_se_inventa(self) -> None:
        assert fecha_de_la_hoja(self.CAPA, hoy=HOY) is None
        # Tesseract con la fecha a mano: va sin fecha y a Revisión.
        assert fecha_de_la_hoja("REVISIÓN DE PROCEDIMIENTOS\nFECHA: £ 3_/¿¿3 7202|\n", hoy=HOY) is None

    def test_un_rotulo_calificado_es_una_trampa(self) -> None:
        assert fecha_de_la_hoja("FORMATO DE ATENCION\nFECHA DE VENCIMIENTO: 20/09/2021\n", hoy=HOY) is None
        assert fecha_de_la_hoja("FORMATO DE ATENCION\nFECHA VTO: 20/09/2021\n", hoy=HOY) is None

    def test_el_rotulo_que_cita_una_referencia_no_fecha(self) -> None:
        # Lo que el «REF:» de un recurso cita (UPD2365925 p36).
        texto = "Señores AFINIA REF: RECURSO DE REPOSICION contra la factura FECHA: 10/12/2021, FACTURADO SEGUN LA FACTURA"
        assert fecha_de_la_hoja(texto, hoy=HOY) is None

    def test_sólo_en_la_cabeza_de_la_hoja(self) -> None:
        cuerpo = "INFORME DE VISITA " + "se revisó el predio y el medidor " * 20 + "FECHA: 03/08/2021"
        assert fecha_de_la_hoja(cuerpo, hoy=HOY) is None

    def test_un_anexo_no_se_razona(self) -> None:
        assert fecha_de_la_hoja(CEDULA + "\nFECHA: 03/08/2021", hoy=HOY) is None

    def test_la_estructura_manda_sobre_el_rotulo(self) -> None:
        # Una constancia fechada por su estructura no cambia de fecha.
        assert fecha_de_la_hoja(
            "PARA LA EMPRESA Recibí constancia del contenido de la reclamación presentada ante CARIBEMAR "
            "N° PQR: RE2320202101914 FECHA: 03/05/2021 NOTIFICACIÓN: a más tardar el 25/05/2021",
            hoy=HOY,
        ) == date(2021, 5, 3)

    def test_el_agente_la_encuentra_con_la_ia(self) -> None:
        from resolutions.application.agente_de_fechas import AgenteDeFechas

        agente = AgenteDeFechas(leer_con_ia=lambda _p: self.LEIDA_POR_LA_IA, fechar=fecha_de_la_hoja, en_orden=True)
        hallada = agente.buscar([1], {1: self.CAPA})
        assert hallada is not None and hallada.fecha == date(2021, 8, 3) and hallada.via == "ia"


class TestEnLaCaja:
    """La caja de correspondencia de verdad, sobre un PDF pequeño (sin IA)."""

    def test_el_acuerdo_se_fecha_por_su_reconocimiento_y_no_por_su_certificado(
        self, tmp_path
    ) -> None:
        import pytest

        pymupdf = pytest.importorskip("pymupdf")
        from resolutions.api import worker
        from resolutions.api.settings import Settings
        from resolutions.application.task import TaskKind

        ruta = tmp_path / "UPD0000001.pdf"
        with pymupdf.open() as documento:
            for texto in (PAGARE, CARTA_TABLA, RECONOCIMIENTO, CEDULA, CAMARA):
                documento.new_page().insert_textbox(
                    pymupdf.Rect(40, 40, 560, 800), texto, fontsize=11
                )
            documento.save(ruta)
        informe = worker._segment_job(
            {
                "job_id": "t",
                "source": str(ruta),
                "filename": "UPD0000001.pdf",
                "task": str(TaskKind.SEGMENT),
                "settings": Settings(output_dir=tmp_path / "salida").as_worker_payload(),
            },
            TaskKind.SEGMENT,
        )
        acuerdo = next(p for p in informe["piezas"] if 3 in p["pages"])
        assert acuerdo["fecha"] == "2020-12-23"
        assert acuerdo["fecha_por"] == "reconocimiento de deuda (pág. 3)"
        # Ninguna pieza de la caja lleva la fecha del certificado (2012).
        assert all(
            not str(p.get("fecha") or "").startswith("2012") for p in informe["piezas"]
        )


def test_sin_trampas_tacha_lo_que_va_tras_el_plazo() -> None:
    plano = sin_trampas("FECHA: 03/05/2021 le será notificada a más tardar el 25/05/2021")
    assert "03/05/2021" in plano
    assert "25/05/2021" not in plano


class TestLaFechaSolaEnLaCabeza:
    """910349 (UPD2998266 pág. 1, 2026-11-20): el formato «____, ____ de 20__» con la ciudad en blanco."""

    def test_el_acta_de_predio_desocupado_se_fecha_por_su_cabeza(self):
        from datetime import date

        from resolutions.domain.fecha_por_estructura import fecha_de_la_hoja

        acta = (
            "afinia\nGrupo-epm\n\n26, Nov de 2022\n\n# ACTA DE VERIFICACIÓN DE PREDIO DESOCUPADO\n"
            "El sr(a) Pedro Pérez identificado con C.C. afirma que el predio se encontraba desocupado al momento de "
            "realizar la visita desde Mayo-21 hasta 06-11-22"
        )
        assert fecha_de_la_hoja(acta) == date(2022, 11, 26)
        assert fecha_de_la_hoja("___26___, ___Nov___ de 2022\nACTA DE VERIFICACION DE PREDIO DESOCUPADO") == date(
            2022, 11, 26
        )

    def test_una_fecha_sola_en_el_cuerpo_no_es_la_del_documento(self):
        from resolutions.domain.fecha_por_estructura import fecha_de_la_hoja

        carta = "Señores AFINIA\nREF: reclamo\nPor medio de la presente\nuno\ndos\ntres\ncuatro\n15 de marzo de 2021\n"
        assert fecha_de_la_hoja(carta) is None
