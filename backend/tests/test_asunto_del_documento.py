"""El título de cada documento, leído de su propio papel.

Los textos son los de la caja «afinar afinia» tal como los deja la OCR. Cada
caso es uno de los cuatro sitios donde está el asunto, y los últimos son lo que
parece un asunto y no lo es.
"""

from __future__ import annotations

import pytest

from resolutions.domain.asunto_del_documento import (
    asunto_del_documento,
    legible,
    titulo_del_documento,
)


class TestDondeEstaElTitulo:
    def test_el_ref_con_su_continuacion(self):
        texto = (
            "Señor: GERENTE EMPRESA AFINIA S.A.S E.S.P.\n"
            "REF.: DERECHO DE PETICION EN CONTRA DE LA EDFC DE FECHA DE agosto\n"
            "DE 2021 POR VALOR DE $ 1.972.040\n"
            "GUSTAVO MANUEL PUMAREJO VEGA ciudadano en ejercicio, domiciliado y residente en\n"
        )
        assert asunto_del_documento([texto], "DERECHO DE PETICION") == (
            "EN CONTRA DE LA EDFC DE FECHA DE AGOSTO DE 2021 POR VALOR DE $ 1.972.040"
        )

    def test_el_ref_que_quedo_a_medias_toma_lo_que_sigue_en_mayusculas(self):
        texto = (
            ".REF! DERECHO DE PETICIÓN ART. 23 DE C.N. PROCESO DE RUPTURA DE SOLIDARIDAD POR\n"
            "DEUDA para que la empresa AFINIA E.S.P CARIBE MAR SA. FILIAL. DEL GRUPO EPM Me expida una\n"
        )
        assert asunto_del_documento([texto], "DERECHO DE PETICION") == (
            "PROCESO DE RUPTURA DE SOLIDARIDAD POR DEUDA"
        )

    def test_el_ref_completo_no_se_come_el_nombre_de_quien_escribe(self):
        texto = (
            "REF: ERROR EN LECTURA\n"
            "GERMAN EMILIO MARRONQUIN persona mayor de edad, con domicilio permanente en esta\n"
        )
        assert asunto_del_documento([texto], "DERECHO DE PETICION") == "ERROR EN LECTURA"

    def test_la_respuesta_de_la_empresa_dice_que_contesta(self):
        texto = (
            "ASUNTO: Redamación No. RE3110202138312\n"
            "Estimado Señor(a) JOSE LORENZO GOMEZ ARIZA ;\n"
            "En atención a su petición presentada en nuestras instalaciones el 02 de septiembre de 2021, medíante el\n"
            "cual reclama por exceso de consumo facturado en 09/08/2021, al respecto le informamos lo\n"
        )
        assert asunto_del_documento([texto], "NOTIFICACION PERSONAL RECLAMOS") == (
            "EXCESO DE CONSUMO FACTURADO EN 09/08/2021"
        )

    def test_la_peticion_cuando_el_ref_solo_repite_el_tipo(self):
        portada = "REF: DERECHO DE PETICION (ART 23 CM)\nACCIONANTE: WILMAN ROMO CABRERA.\nNIC.: 5302932.\n"
        peticion = (
            "PETICION\n"
            "Solicito de manera respetuosa a la empresa ELECTRICARIBE S.A. se sirva\n"
            "descargar del sistema los valores adeudados por el arrendatario en el\n"
            "inmueble de mi propiedad, debido a que la empresa no actuó conforme a la\n"
        )
        assert asunto_del_documento([portada, peticion], "DERECHO DE PETICION") == (
            "DESCARGAR DEL SISTEMA LOS VALORES ADEUDADOS POR EL ARRENDATARIO EN EL INMUEBLE DE MI PROPIEDAD"
        )

    def test_la_constancia_por_su_causa(self):
        texto = "N* PQR: RE4310202103559\nFECHA: 11/08/2021\nCAUSA:\nDaño Medidor y/o Acometida\nSERVICIO: 4415218\n"
        assert asunto_del_documento([texto], "RECLAMO") == "DAÑO MEDIDOR Y/O ACOMETIDA"

    def test_la_carta_sencilla(self):
        texto = (
            "Asunto: derecho de petición\n"
            "Cordial saludo:\n"
            "Es para informar mi inconformidad del aumento del monto de la factura del mes de agosto 2021\n"
            "NK: 534Q280 en la dirección TRVS: 24\n"
        )
        assert asunto_del_documento([texto], "DERECHO DE PETICION") == (
            "INCONFORMIDAD DEL AUMENTO DEL MONTO DE LA FACTURA DEL MES DE AGOSTO 2021"
        )

    def test_las_peticiones_en_vinetas(self):
        texto = "PETICIONES:\n• \nSEA RELIQUIDADO DICHOS MONTOS.\n•\n"
        assert asunto_del_documento([texto], "DERECHO DE PETICION") == "SEA RELIQUIDADO DICHOS MONTOS"


class TestLoQueNoEsTitulo:
    def test_el_asunto_del_sello(self):
        assert asunto_del_documento(["Asunto: 03 RCCLAMO\nOficina: CAT\n"], "RECLAMO") is None

    def test_el_numero_de_cuenta(self):
        assert asunto_del_documento(["Referencia: Cuenta Interna No. 1012171\n"], "RECLAMO") is None

    def test_lo_que_solo_repite_el_tipo(self):
        assert asunto_del_documento(["Asunto: Citación para notificación personal\n"], (
            "CITACION PARA NOTIFICACION PERSONAL"
        )) is None

    def test_un_renglon_del_cuerpo_que_empieza_por_referencia(self):
        texto = "referencia, en los terminos que se exponen a continuacion y con base en la normatividad\n"
        assert asunto_del_documento([texto], "NOTIFICACION POR AVISO") is None

    @pytest.mark.parametrize("basura", ["ERENR^^- ''•«ENTA INTERNA", "Nl,MLKOKL3n02n22!l0.137"])
    def test_la_basura_de_la_ocr(self, basura):
        assert not legible(basura)

    def test_el_corte_por_largo_no_deja_una_palabra_colgando(self):
        texto = (
            "PETICIÓN\nSolicito de manera respetuosa a la empresa CARIBEMAR S.A. E.S.P. se sirva\n"
            "descargar del sistema los meses adeudados por el arrendatario por concepto de\n"
            "facturas de energía y fínanciaciones que no autorice o realice ante la empresa\n"
        )
        titulo = asunto_del_documento([texto], "DERECHO DE PETICION")
        assert titulo.startswith("DESCARGAR DEL SISTEMA LOS MESES ADEUDADOS")
        assert not titulo.endswith((" Y", " DE", " POR"))


class TestElTituloDirecto:
    """Lo que el documento dice ser en su primera hoja, mirando su imagen."""

    @pytest.mark.parametrize(
        ("primera_hoja", "titulo"),
        [
            # UPD2321099 p1: el escrito del cliente, por su REF.
            (
                "Valledupar, diciembre 02 de 2020\nSeñores\nCARIBEMAR S.A. E.S.P.\n"
                "REF: DERECHO DE PETICION (ART 23 C.N.)\nACCIONANTE: WILMAN ROMO CABRERA.\n",
                "DERECHO DE PETICION",
            ),
            # UPD2326399 p1: el recurso cita un consecutivo y no es de la empresa.
            (
                "Valledupar 9 de septiembre de 2021.\nSeñores.\nCARIBE MAR DE L COSTA - AFINIA.\n"
                "REF. RECURSO DE REPOSICIÓN EN SUBSIDIO DE\nAPELACION.\n"
                "CONSECUTIVO No 20190209061.\nPETICIÓN N° RE3110202138312.\n",
                "RECURSO DE REPOSICION EN SUBSIDIO DE APELACION",
            ),
            # UPD2326399 p5: la carta de la empresa contesta la reclamación.
            (
                "Consecutivo No. 210902090614861\nVALLEDUPAR, 02 de septiembre de 2021\n"
                "Señor(a)\nJOSE LORENZO GOMEZ ARIZA\nNIC: 5340280\n"
                "ASUNTO: Redamación No. RE3110202138312\nEstimado Señor(a) JOSE LORENZO GOMEZ ARIZA :\n",
                "RESPUESTA A RECLAMACION",
            ),
            # UPD2326399 p18: la empresa contesta el recurso.
            (
                "Consecutivo No. 202170259186\nVALLEDUPAR, 16/09/2021\nSeñor:\n"
                "ASUNTO: Recurso de Reposición en subsidio el de apelación No. RE3110202138312\n",
                "RESPUESTA A RECURSO DE REPOSICION EN SUBSIDIO DE APELACION",
            ),
            # UPD2320047 p5: la citación, por su asunto.
            (
                "Cartagena, 24/01/2022\nConsecutivo No. 202270023207\nSeñor(a)\n"
                "Asunto: Citación para notificación personal\nNIC 1012408\n",
                "CITACION PARA NOTIFICACION PERSONAL",
            ),
            # UPD2326399 p4 y p17: el título centrado de la hoja.
            ("NOTIFICACIÓN PERSONAL RECLAMOS\nEn la fecha 02 de septiembre de 2021\n", "NOTIFICACION PERSONAL RECLAMOS"),
            ("afinia\nNOTIFICACIÓN PERSONAL\nEn la fecha 22/09/2021 compareció\n", "NOTIFICACION PERSONAL"),
            # UPD2555083 p1: la constancia de la reclamación.
            (
                "PARA LA EMPRESA\nRecibí constancia del contenido de la reclamación presentada ante "
                "CARIBEMAR DE LA COSTA S.A.S. ESP\nN* PQR: RE4310202103559\n",
                "CONSTANCIA DE RECLAMACION",
            ),
            # UPD2320047 p7: el acta, aunque la OCR se coma la A.
            ("Una filial del\n^ \\CTA DE SUSPENSION\n{ CORTE Y RECONEXION\nGrupo EPM\n", "ACTA DE SUSPENSION CORTE Y RECONEXION"),
            # UPD2321099 p9: la guía de envío de LECTA.
            ("LECTA\nFECHA DE ENTREGA O INTENTO DE ENTREGA\nCARIBEMAR DE LA COSTA SAS\n", "GUIA DE ENVIO"),
            # UPD2320043 p6: el REF no nombra un tipo; el cuerpo dice qué interpone.
            (
                "Señores:\nAFINIA S.A.S E.S.P.\nReferencia: Cuenta Interna No. 1012171\n"
                "REF: ERROR EN LECTURA\nrespetuosamente me dirijo a ese despacho con el fin de "
                "INTERPONER DERECHO DE PETICION.\n",
                "DERECHO DE PETICION",
            ),
        ],
    )
    def test_el_titulo_de_la_primera_hoja(self, primera_hoja, titulo):
        assert titulo_del_documento(primera_hoja) == titulo

    def test_sin_nada_que_lo_diga_queda_el_tipo_del_catalogo(self):
        assert titulo_del_documento("hoja sin cabecera alguna", "Factura") == "FACTURA"
