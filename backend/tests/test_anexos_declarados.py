"""La lista de «ANEXOS» de un escrito: se lee con cuidado, retiene y verifica.

Los textos salen de la caja «afinar afinia» tal como los deja la OCR, con sus
erratas: UPD2321099 (la lista con encabezado), UPD2320047 («PRUEBA YANEXOS»),
UPD2326399 (la frase «Anexo la factura…» y la que remite a las pruebas). Y las
menciones que NO son lista, que son las que más cuidado piden.
"""

from __future__ import annotations

from datetime import date

import pytest

from resolutions.application.agrupacion import PaginasLeidas, agrupar_por_tramite
from resolutions.application.anexos_declarados import (
    nombrar_sin_soporte,
    retener_anexos,
    unir_soportes,
)
from resolutions.domain.anexos_declarados import (
    HOJA_MUDA,
    clase_de_la_hoja,
    clase_del_renglon,
    leer_lista_de_anexos,
)
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode

ENCABEZADO = (
    "se abstengan de suspender el servicio hasta tanto no sea \n"
    "resuelta la petición.\n"
    "ANEXOS\n"
    "Contrato de arrendamiento. \n"
    "Factura de cobro.\n"
    "Cédula de ciudadanía.\n"
    "NOTIFICACIONES\n"
    "Las recibiré en la Carrera 14 No. 9 - 77 Barrio San Joaquín de esta ciudad, \n"
    "Atentamente,\n"
)
PRUEBAS_Y_ANEXOS = (
    "los servicios públicos domiciliarlo (Ley 142 de 1994\n"
    "PRUEBA YANEXOS\n"
    "Téngase como tales las que a continuación se relacionan: \n"
    "Documentales:\n"
    "Contrato de arrendamiento.\n"
    "CERTIFICADO DE LIBERTAD Y TRADICCION \n"
    "CERTIFICADO DE NOMENCLATURA EXPEDIDDO POR EL IGAC.\n"
    "NOTIFICACIONES\n"
)
FRASE = (
    "te y se que no puedo pagar esos servicios de tal costo por eso ahorro \n"
    "energía.\n"
    "Anexo la factura de! mes el cual está en reclamo o debido derecho de petición \n"
    "Y la cédula de ciudadanía\n"
    "Espero que me solucionen este problema lo más pronto posible\n"
    "ATT JOSE LORENZO GOMEZ ARIZA\n"
)
REMITE = (
    "recurso.\n"
    "Anexo Los documentos que reLacioné en Las pruebas documentarias, punto \n"
    "1,2.\n"
    "NOTIFICACIONES:\n"
)


class TestLaLista:
    def test_el_encabezado_con_sus_renglones(self):
        lista = leer_lista_de_anexos(ENCABEZADO)
        assert [(a.texto, a.clase) for a in lista.anexos] == [
            ("Contrato de arrendamiento", "contrato de arrendamiento"),
            ("Factura de cobro", "factura"),
            ("Cédula de ciudadanía", "documento de identidad"),
        ]
        assert lista.cantidad == 3

    def test_pruebas_y_anexos_salta_los_renglones_que_la_presentan(self):
        lista = leer_lista_de_anexos(PRUEBAS_Y_ANEXOS)
        assert [a.clase for a in lista.anexos] == [
            "contrato de arrendamiento",
            "certificado de tradición",
            "certificado catastral",
        ]

    def test_la_frase_y_su_continuacion(self):
        """«la factura del mes en reclamo por derecho de petición» es una
        factura: manda la clase que aparece primero."""
        lista = leer_lista_de_anexos(FRASE)
        assert [a.clase for a in lista.anexos] == ["factura", "documento de identidad"]

    def test_la_que_remite_a_las_pruebas_queda_sin_detalle(self):
        lista = leer_lista_de_anexos(REMITE)
        assert lista.sin_detalle
        assert lista.anexos == []

    def test_la_cantidad(self):
        lista = leer_lista_de_anexos("ANEXOS:\nDos (2) facturas de energía.\nCédula.\nATENTAMENTE")
        assert [(a.clase, a.cantidad) for a in lista.anexos] == [
            ("factura", 2),
            ("documento de identidad", 1),
        ]

    def test_detras_de_los_dos_puntos(self):
        lista = leer_lista_de_anexos("ANEXOS: copia de la cédula; factura de octubre\nCordialmente")
        assert [a.clase for a in lista.anexos] == ["documento de identidad", "factura"]


class TestLoQueNoEsUnaLista:
    @pytest.mark.parametrize(
        "texto",
        [
            # Prosa: la palabra suelta en medio de un párrafo.
            "tal como se demuestra en las fotografías anexas y las\nfactura emitidas",
            "reglamento técnico adjunto al contrato de condiciones uniformes",
            # Lo que el cliente pide, no lo que trae.
            "PETICIONES:\n• \nSE ME ANEXE ESTADO DE CUENTA QUE CORROBORE QUE DICHOS",
            # La norma y el contrato que se citan.
            "servicio según lo establecido en el capitulo 11 del anexo \ngeneral de la Resolución CREG",
            "Anexo general de la Resolución CREG 097/2008",
            "que forma parte integrante de este contrato en calidad de Anexo 1.\nQuinta - Reparaciones",
            "Anexo 1.\nQuinta - Reparaciones",
            # El título de una hoja anexa no es una lista.
            "ANEXO A RECLAMO\nSe presenta el registro de lecturas",
        ],
    )
    def test_no_se_lee_como_lista(self, texto):
        assert leer_lista_de_anexos(texto) is None

    def test_la_prosa_entre_dos_anexos_no_es_un_anexo(self):
        # UPD2326300 p13: «ANEXOS», «ANEXOS como prueba», la cita de una
        # sentencia y, por fin, la lista. Se leían once anexos.
        texto = (
            "realizar un nuevo contrato\nademás\nANEXOS\nANEXOS como prueba\n"
            "DE CONFORMIDAD CON LA SENTENCIA DE TUTELA T-636 DE 2006 ,” QUE apropósito\n"
            "del tema argumento sobre la existencia de un contrato de arrendamiento : Así pues con el\n"
            "objetivo de acreditar la existencia y los elementos del arrendamiento nopO es imperativo exigir\n"
            "ANEXOS LO SIGUIENTES;\n• \nCopia del certificado de tradición y libertad\n• \n"
            "CONTRATO DE ARRENDAMIENTO\nNOTIFICACIONES\nPara notificación hacerla llegar a la DG 17A"
        )

        lista = leer_lista_de_anexos(texto)

        assert [anexo.clase for anexo in lista.anexos] == [
            "certificado de tradición",
            "contrato de arrendamiento",
        ]
        assert not lista.sin_detalle


class TestLaHoja:
    def test_el_contrato_por_su_titulo_y_no_por_mencionarlo(self):
        assert clase_de_la_hoja("CONTRATO DE ARRENDAMIENTO DE VIVIENDA Entre los suscritos") == (
            "contrato de arrendamiento"
        )
        assert clase_de_la_hoja(
            "debió denunciar antes; el contrato de arrendamiento goza de toda credibilidad " * 6
        ) is None

    def test_la_factura_por_lo_que_solo_imprime_la_factura(self):
        assert clase_de_la_hoja("OPERADOR DE RED; Caribe Mar USE ESTE NÚMERO PARA CONSULTAS " * 4) == "factura"
        assert clase_de_la_hoja("La empresa permitió facturas vencidas por $1.129.410 " * 8) is None

    def test_la_fotocopia_que_la_ocr_volvio_basura_es_muda(self):
        basura = ": ^i2jmMn TvpíSI s iS? '%■ Si ri i? iX^CZO ■mm - ...... i- WT\\ Ba til ;.(.*'--*Sá!í" * 2
        assert clase_de_la_hoja(basura) == HOJA_MUDA

    def test_la_cedula_casi_muda_que_deja_ver_la_republica(self):
        assert clase_de_la_hoja("V^LLeST . ; (CESAR) REPUBLICA DE COLOMBIA |^ 3 f.ir mi") == (
            "documento de identidad"
        )

    def test_el_renglon(self):
        assert clase_del_renglon("CERTIFICADO DE LIBERTAD Y TRADICCION") == "certificado de tradición"


def _grupos(*documentos: list[int]) -> GroupingResult:
    return GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=f"{n:02d}", raw=f"{n:02d}"), page_numbers=paginas)
            for n, paginas in enumerate(documentos, start=1)
        ],
        quarantine=[],
        repairs=[],
    )


CONTRATO = "CONTRATO DE ARRENDAMIENTO DE VIVIENDA Entre los suscritos " + "cláusula " * 60
CONTRATO_2 = "DECIMA NOVENA: CLAUSULA PENAL; Las partes acuerdan " + "cláusula " * 60
FACTURA = "OPERADOR DE RED; Caribe Mar USE ESTE NUMERO PARA CONSULTAS NIC 5302932 " + "kwh " * 60
CEDULA = "REPUBLICA DE COLOMBIA IDENTIFICACION PERSONAL CEDULA DE CIUDADANIA FECHA DE NACIMIENTO"
GUIA = "Señores WILMAN ROMO GUIA DE ENTREGA PQR RE3110202043677 " + "entrega " * 60
ESCRITO = "Valledupar, diciembre 02 de 2020\nSeñores CARIBEMAR\nREF: DERECHO DE PETICION\n" + "hechos " * 60


class TestRetenerYVerificar:
    """UPD2321099: el corte dejaba el contrato con el escrito y la factura y la
    cédula aparte; la lista las une, y la guía de entrega se queda donde está."""

    textos = {1: ESCRITO, 2: ENCABEZADO + "palabra " * 40, 3: CONTRATO, 4: CONTRATO_2, 5: FACTURA, 6: CEDULA, 7: GUIA}

    def test_une_lo_que_la_lista_nombra_y_para_en_lo_que_abre(self):
        retencion = retener_anexos(_grupos([1, 2, 3, 4], [5, 6], [7]), self.textos)

        assert [g.page_numbers for g in retencion.grupos.groups] == [[1, 2, 3, 4, 5, 6], [7]]
        [escrito] = retencion.escritos
        assert escrito.retenidas == [5, 6]
        assert escrito.faltan == []
        assert [h.clase for h in escrito.hallados] == [
            "contrato de arrendamiento",
            "factura",
            "documento de identidad",
        ]
        assert escrito.observacion() == "Anexos declarados: 3 (pág. 2); hallados: 3"

    def test_renumera_los_documentos(self):
        retencion = retener_anexos(_grupos([1, 2, 3, 4], [5, 6], [7]), self.textos)
        assert [g.code.value for g in retencion.grupos.groups] == ["01", "02"]

    def test_lo_que_falta_se_declara(self):
        textos = {**self.textos, 5: GUIA, 6: GUIA}
        retencion = retener_anexos(_grupos([1, 2, 3, 4], [5, 6], [7]), textos)

        [escrito] = retencion.escritos
        assert [a.texto for a in escrito.faltan] == ["Factura de cobro", "Cédula de ciudadanía"]
        assert "no aparece" in escrito.motivo_de_revision()
        # Y no se une nada que no sea de la lista.
        assert [g.page_numbers for g in retencion.grupos.groups] == [[1, 2, 3, 4], [5, 6], [7]]

    def test_una_cedula_suelta_entre_anexos_no_corta_la_cadena(self):
        """UPD2320047: entre el contrato y el certificado de tradición hay una
        cédula que la lista no nombra."""
        textos = {
            1: PRUEBAS_Y_ANEXOS + "palabra " * 40,
            2: CONTRATO,
            3: CEDULA,
            4: "CERTIFICADO DE TRADICION MATRICULA INMOBILIARIA " + "folio " * 60,
            5: "INSTITUTO GEOGRAFICO AGUSTIN CODAZZI CERTIFICADO DE NOMENCLATURA " + "predio " * 60,
        }
        retencion = retener_anexos(_grupos([1, 2], [3], [4], [5]), textos)

        assert [g.page_numbers for g in retencion.grupos.groups] == [[1, 2, 3, 4, 5]]
        [escrito] = retencion.escritos
        assert escrito.faltan == []
        assert [h.clase for h in escrito.no_declarados] == ["documento de identidad"]

    def test_la_cedula_suelta_al_final_no_se_retiene_si_no_vuelve_la_lista(self):
        textos = {1: ENCABEZADO + "palabra " * 40, 2: CONTRATO, 3: CEDULA, 4: ESCRITO}
        retencion = retener_anexos(_grupos([1, 2], [3], [4]), textos)
        # La cédula SÍ es de la lista: se retiene. Lo que no se retiene es lo
        # que viene detrás y abre un escrito.
        assert [g.page_numbers for g in retencion.grupos.groups] == [[1, 2, 3], [4]]

    def test_otro_escrito_con_su_lista_no_se_lo_traga_el_anterior(self):
        textos = {1: FRASE + "palabra " * 40, 2: FRASE + "palabra " * 40, 3: FACTURA}
        retencion = retener_anexos(_grupos([1], [2], [3]), textos)
        assert [g.page_numbers for g in retencion.grupos.groups] == [[1], [2, 3]]

    def test_sin_lista_no_cambia_nada(self):
        grupos = _grupos([1], [2])
        retencion = retener_anexos(grupos, {1: ESCRITO, 2: FACTURA})
        assert retencion.grupos.groups == grupos.groups
        assert retencion.escritos == []


class TestEnElTramite:
    def test_lo_retenido_no_lo_mueve_ninguna_fecha(self):
        """El contrato de 2018 encajaría por fecha en otro trámite; la lista
        dice que es de este, y manda la lista."""
        textos = {
            1: "Recibí constancia N* PQR: RE3110201811111 FECHA: 20/11/2018",
            2: "Valledupar, diciembre 02 de 2020 PQR: RE3110202043677 " + ENCABEZADO,
            3: CONTRATO,
        }
        fechas = {1: date(2018, 11, 20), 2: date(2020, 12, 2), 3: date(2018, 11, 25)}
        grupos = _grupos([1], [2], [3])
        leidas = PaginasLeidas(
            fechas=fechas,
            tipos={p: None for p in textos},
            asuntos={p: None for p in textos},
            con_ocr=0,
            textos=textos,
        )

        por_tramite = agrupar_por_tramite(grupos, leidas, retenidas={3: 2})

        assert [g.page_numbers for g in por_tramite.grupos.groups] == [[1], [2, 3]]


class TestLaCedulaYLaFacturaNuncaVanSolas:
    """«Una cédula nunca podrá ir sola en el inventario o en la división,
    siempre será acompañada dentro del PDF de la página anterior.» Y la factura
    igual."""

    def test_la_cedula_sola_vuelve_al_documento_anterior(self):
        unidos = unir_soportes(_grupos([1, 2], [3]), {1: ESCRITO, 2: CONTRATO, 3: CEDULA})
        assert [g.page_numbers for g in unidos.grupos.groups] == [[1, 2, 3]]
        assert unidos.movidas == {3: 1}
        assert unidos.anexos == {"01": [3]}

    def test_la_factura_que_abre_un_documento_pasa_al_anterior_y_lo_demas_se_queda(self):
        """UPD2320047: el corte dejaba la factura y su estado de cuenta abriendo
        el documento de la citación."""
        unidos = unir_soportes(
            _grupos([1, 2], [3, 4, 5]),
            {1: ESCRITO, 2: ESCRITO, 3: FACTURA, 4: "Estado de cuenta NIC 1012408 No. Facturas Vencidas: 6", 5: GUIA},
        )
        assert [g.page_numbers for g in unidos.grupos.groups] == [[1, 2, 3, 4], [5]]

    def test_el_reverso_mudo_de_la_cedula_va_con_ella(self):
        unidos = unir_soportes(_grupos([1], [2, 3]), {1: ESCRITO, 2: CEDULA, 3: "^i2j mMn"})
        assert [g.page_numbers for g in unidos.grupos.groups] == [[1, 2, 3]]

    def test_la_cedula_con_que_empieza_la_caja_acompana_al_siguiente(self):
        unidos = unir_soportes(_grupos([1], [2, 3]), {1: CEDULA, 2: ESCRITO, 3: ESCRITO})
        assert [g.page_numbers for g in unidos.grupos.groups] == [[1, 2, 3]]

    def test_renumera(self):
        unidos = unir_soportes(_grupos([1], [2], [3]), {1: ESCRITO, 2: CEDULA, 3: GUIA})
        assert [g.code.value for g in unidos.grupos.groups] == ["01", "02"]

    def test_en_el_tramite_solo_se_mueve_el_que_iria_solo(self):
        textos = {1: ESCRITO, 2: CEDULA, 3: ESCRITO, 4: CEDULA}
        unidos = unir_soportes(_grupos([1], [2, 3], [4]), textos, solo_si_queda_solo=True)
        assert [g.page_numbers for g in unidos.grupos.groups] == [[1], [2, 3, 4]]


class TestUnDocumentoNoSeLlamaComoSuAnexo:
    def test_el_reclamo_con_cedula_no_es_un_documento_de_identidad(self):
        """UPD2320047 p8: la OCR dejó «REF! DERECHO DE PETICIÓN» y el escrito
        dice «identificado con CC No.»; el catálogo contestaba cédula."""
        reclamo = (
            "Valledupar. 18-08-2022 Asunto: 03 RCCLAMO Gerente de AFINIA .REF! DERECHO DE PETICIÓN "
            "identifícado(a) con CC No. 36.516.321 " + "hechos " * 60
        )
        grupos = GroupingResult(
            groups=[
                PageGroup(
                    code=ResolutionCode(value="01", raw="01"),
                    page_numbers=[1, 2],
                    kind="DOCUMENTO DE IDENTIDAD",
                )
            ],
            quarantine=[],
            repairs=[],
        )
        [grupo] = nombrar_sin_soporte(grupos, {1: reclamo, 2: CEDULA}).groups
        assert grupo.kind == "DERECHO DE PETICION"

    def test_la_cedula_que_de_verdad_abre_se_queda_con_su_nombre(self):
        grupos = GroupingResult(
            groups=[
                PageGroup(
                    code=ResolutionCode(value="01", raw="01"), page_numbers=[1], kind="DOCUMENTO DE IDENTIDAD"
                )
            ],
            quarantine=[],
            repairs=[],
        )
        [grupo] = nombrar_sin_soporte(grupos, {1: CEDULA}).groups
        assert grupo.kind == "DOCUMENTO DE IDENTIDAD"
