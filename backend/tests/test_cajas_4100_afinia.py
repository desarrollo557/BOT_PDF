"""Las cinco carpetas de Afinia que el operador devolvió el 2026-11-19.

4100875, 4100877, 4100971, 4100975 y 4100976 («procesados afinia»): «quedaron
mal divididas y sin fechas». Cada prueba fija lo que su papel dice, con los
textos tal como los leyeron Tesseract y la IA en la corrida de ese día.
"""

from __future__ import annotations

from datetime import date

from resolutions.application.cartas import Cartas
from resolutions.domain.asunto_del_documento import (
    NOTIFICACION_POR_AVISO,
    PUBLICACION_DEL_AVISO,
    RESPUESTA_DE_LA_EMPRESA,
    consecutivo_de,
    es_contestacion_a_reclamacion,
    formulario_que_abre,
)
from resolutions.domain.fecha_por_estructura import (
    CARTA_RADICADA_DE_LA_EMPRESA,
    fecha_de_la_hoja,
    fecha_de_lo_visto,
    fecha_por_estructura,
    pieza_de,
)
from resolutions.domain.fechas import fecha_de_las_casillas
from resolutions.domain.foliacion_del_escrito import foliacion_del_escrito
from resolutions.domain.nombre_oficial import estandarizar

#: 4100877 (UPD2985231): el cupón como lo transcribió la IA. Las casillas dicen
#: DÍA 10, MES 3, AÑO 22, y el «10» quedó pegado al ID de cobros «…259-23».
CUPON_4100877 = (
    "|  NIC *4100877 Evangelista Católeo 3* |   | FECHA  |   |   |   |\n"
    "|   |   | DIA | MES | ANIO  |   |\n"
    "|  ID DE COBROS: *4100877259-2310* |   | 3 | 22 |   |   |\n"
    "|  FORMA DE PAGO: VALOR CANCELADO: *23,790* |   | EFECTIVO: ☐ |"
)
#: 4100875 pág. 2 (UPD2985229): el día y el mes los tapa el sello; el «6 6» es
#: el final del ID de cobros, no la fecha.
CUPON_4100875_P2 = (
    "|  NIC 4 1 0 0 8 7 5 *Nelson Rojo Cano* |   | FECHA  |   |   |   |\n"
    "|   |   | DIA | MES | ANIO  |   |\n"
    "|  ID DE COBROS: 4 1 0 0 8 7 5 2 5 2 - 6 6 |   | 2021  |   |   |   |"
)

#: 4100976 (UPD2456242): las cartas de la empresa como las dejó Tesseract.
PUBLICACION = (
    "aFinia\ni,v6 •\nGrupo-epfTQ\nConsecutivo No. PA 202270254853\nPUBLICACIÓN DEL AVISO\n"
    "a) El usuario Daniel José Palacio Sampayo reportó como\nTeniendo en cuenta que:\n"
    "radicada bajo el número RE2320202204099, la siguiente dirección; c) Que en atención\n"
    "a lo anterior, Caribe Mar de la Costa S.A.S. E.S.P. declara que\n"
    "El presente aviso se publica el día 05/07/2022 13:07:44.0 y hasta por cinco (5) días"
)


def _notificacion(consecutivo: str, persona: str, radicado: str) -> str:
    return (
        f"aFinia\nGrupo-epm\nCartagena, 21-06-2022\nConsecutivo No.{consecutivo}\nSeñor(a)\n{persona}\n"
        "CARRERA 12, CL 9 - 45, EL LIMON, CICUCO BOLIVAR\nTelefono:3007302208\n"
        f"Asunto: Notificación por aviso\nNIC: 4100976\nRadicado número: {radicado}\n"
        "Caribe Mar de la Costa S.A.S. E.S.P, garantizándole sus derechos como cliente"
    )


def _contestacion(consecutivo: str, lugar_y_fecha: str) -> str:
    return (
        f"armia\nGrupo-epm\nConsecutivo No.{consecutivo}\n{lugar_y_fecha}\nSeñor:\n"
        "EMILSE DE JESÚS MARTÍNEZ ALFARO\nNIC: 6830611\n"
        "ASUNTO: Petición No. RE8673202201958\nEstimado Señor Martínez:\n"
        "En atención a su solicitud presentada con fecha 14 de mayo de 2022, mediante el cual"
    )


class TestElComprobante:
    def test_el_cupon_manual_es_el_comprobante_de_pago_del_catalogo(self):
        """4100875 salía «COMPROBANTE-CUPON-MANUAL» y 4100877 «COMPROBANTE-DE-PAGO»."""
        assert estandarizar("COMPROBANTE CUPON MANUAL") == "COMPROBANTE DE PAGO"

    def test_el_dia_pegado_al_id_de_cobros_es_el_de_las_casillas(self):
        assert fecha_de_las_casillas(CUPON_4100877) == date(2022, 3, 10)

    def test_el_final_del_id_sigue_sin_ser_la_fecha(self):
        assert fecha_de_las_casillas(CUPON_4100875_P2) is None

    def test_la_vision_que_se_contradice_entre_sello_y_casillas_no_fecha(self):
        """Copió «09-03-22» del sello borroso y «23-2-2022» de las casillas; el papel dice 10-03-2022."""
        assert fecha_de_lo_visto("SELLO: 09-03-22\nCASILLAS: 23 - 2 - 2022\nDOCUMENTO: no hay") is None

    def test_el_sello_y_las_casillas_del_mismo_dia_si(self):
        visto = "SELLO: 17 JUL 2021\nCASILLAS: 17 - 07 - 2021\nDOCUMENTO: no hay"
        assert fecha_de_lo_visto(visto) == (date(2021, 7, 17), "sello")


class TestElAcuerdoSinAnioEntero:
    def test_la_firma_de_la_carta_de_instrucciones_fecha_el_acuerdo(self):
        """4100971 (UPD2985239): el reconocimiento dice «18 de 09 de 20» y la carta, el año entero."""
        reconocimiento = (
            "Electricaribe\nSomos Todos\n\nMiguel, 18 de 09 de 20\n\nSeñores:\nELECTRICARIBE S.A. E.S.P.\n"
            "Ref.: Reconocimiento de deuda y propuesta de acuerdo de pago.\nYo, Naldy"
        )
        carta = (
            "Dejo constancia que en mi poder ha quedado una copia del pagaré y de la presente carta de "
            "instrucciones.\nFirmado en Cicuco a los 18 días del mes Septiembre del año 2020\nFIRMA: Naldy"
        )
        estructura = fecha_por_estructura([4, 3, 7], {4: reconocimiento, 3: carta, 7: carta})
        assert estructura.principal == 4
        assert estructura.donde_buscar == (4, 3, 7)
        assert estructura.fecha == date(2020, 9, 18)


class TestLasNotificacionesPorAviso:
    def test_la_publicacion_y_la_notificacion_por_aviso_son_formularios(self):
        assert formulario_que_abre(PUBLICACION) == PUBLICACION_DEL_AVISO
        assert formulario_que_abre(_notificacion("A202270231268", "Daniel", "RE2320202204099")) == (
            NOTIFICACION_POR_AVISO
        )

    def test_la_publicacion_no_es_una_contestacion_aunque_diga_en_atencion_a(self):
        """La pág. 21 salía «CONTESTACION A LA RECLAMACION» por su «c) Que en atención a lo anterior»."""
        assert not es_contestacion_a_reclamacion(PUBLICACION)

    def test_la_respuesta_en_atencion_a_sigue_siendo_contestacion(self):
        texto = _contestacion("202270208732", "EMAIL, 07/06/2022")
        assert formulario_que_abre(texto) == RESPUESTA_DE_LA_EMPRESA
        assert es_contestacion_a_reclamacion(texto)

    def test_el_consecutivo_del_encabezado(self):
        assert consecutivo_de(PUBLICACION) == "PA202270254853"
        assert consecutivo_de(_contestacion("202270211539", "SANTA ANA, 08/06/2022")) == "202270211539"
        recurso = "Magangué, 20 de julio de 2022\nSeñores\nCARIBEMAR\nLa ciudad\nREF: recurso\nCordial saludo\n"
        assert consecutivo_de(recurso + "Interpongo recurso contra el CONSECUTIVO No 202270274611") is None

    def test_dos_avisos_del_mismo_dia_a_dos_personas_no_son_copia(self):
        """Págs. 22 y 40: el mismo asunto y la misma fecha, otro consecutivo y otro RE."""
        textos = {
            22: _notificacion("A202270231268", "Daniel José Palacio Sampayo", "RE2320202204099"),
            40: _notificacion("A202270230147", "EMILSE DE JESÚS MARTÍNEZ ALFARO", "RE8673202201958"),
        }
        assert 40 not in Cartas.de(textos, {}).copias

    def test_la_misma_carta_dos_veces_sigue_siendo_copia(self):
        texto = _notificacion("A202270231268", "Daniel José Palacio Sampayo", "RE2320202204099")
        assert 40 in Cartas.de({22: texto, 40: texto}, {}).copias


class TestLosDocumentosDeUnActaDeIrregularidad:
    def test_la_constancia_de_visita_por_su_titulo(self):
        """Pág. 26: la fotocopia trae sólo el título que imprime la empresa encima."""
        assert pieza_de("ahnia\nGrupo-epnj\nCONSTANCIA DE VISITA\n■ n ' l.\ntliDESCRIPCIONOELA.").nombre == (
            "constancia de visita"
        )

    def test_la_carta_que_la_cita_entre_sus_soportes_no_es_la_constancia(self):
        """Pág. 29: «4. Constancia de Visita asociada al Acta de Revisión…»."""
        texto = "afinia\n4. Constancia de Visita asociada al Acta de Revisión con Orden de Servicio: Dentro del"
        assert pieza_de(texto).nombre != "constancia de visita"

    def test_la_carta_con_su_radicacion_y_su_fecha(self):
        """Pág. 28: «Radicación # :287379504100976 / MAGANGUE, JUEVES, 29 DE JULIO DE 2021»."""
        texto = (
            "al-mia\nGrupo-epí^\nRadicación # :287379504100976\nlyiAGANGUE, JUEVES, 29 DE JULiO DE 2021\n"
            "*287379504100976*\nSeñor(a):\nCiiente, suscriptor y/o usuario\nDIRECCIÓN:"
        )
        assert pieza_de(texto).nombre == CARTA_RADICADA_DE_LA_EMPRESA
        assert fecha_de_la_hoja(texto) == date(2021, 7, 29)


class TestElFolioImposible:
    def test_un_folio_de_cuatro_cifras_no_une_dos_constancias(self):
        """4100976 págs. 1-2: la IA leyó «1000» en las dos esquinas en blanco."""
        assert foliacion_del_escrito({1: 1000, 2: 1000, 3: 10}, range(1, 43)).continua == frozenset()

    def test_el_folio_repetido_de_verdad_sigue_contando(self):
        assert {56, 57} <= foliacion_del_escrito({55: 4, 56: 6, 57: 6, 58: 7}, range(55, 59)).continua
