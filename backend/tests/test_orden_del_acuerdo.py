"""Las hojas del acuerdo de pago en el orden en que van en su PDF.

Lo dictó el operador el 2026-11-12: «si la página principal, o sea la que dice
reconocimiento de deuda y acuerdo de pago, tiene fecha, agregarla de primero,
luego los pagarés si tiene, luego Ley Habeas Data, y luego los anexos… pero
cuando no tenga fecha, colócalo de último: pagarés, Ley Habeas Data, anexos,
reconocimiento de deuda y acuerdo de pago».
"""

from __future__ import annotations

from dataclasses import replace

from resolutions.api.worker.correspondencia import _ordenar_los_acuerdos
from resolutions.application.anexos_declarados import (
    ANEXOS_DEL_ACUERDO,
    HABEAS,
    PAGARES,
    RECONOCIMIENTO,
    orden_del_acuerdo,
    partes_del_acuerdo,
)
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode

PAGARE = "CARIBEMAR DE LA COSTA S.A.S. ESP\nEMPRESA DE SERVICIOS PUBLICOS DOMICILIARIOS\nPAGARE No. 7975593 -1\n"
CARTA = (
    "CARIBEMAR DE LA COSTA S.A.S. ESP\nCARTA DE INSTRUCCIONES ANEXA A PAGARE No. 7975593 1 CON ESPACIOS ABIERTOS\n"
    "identificado como aparece al pie de mi firma, autorizo irrevocablemente.\n"
)
SIGUE_LA_CARTA = "5. El monto del pagaré será igual al valor que deba el deudor a la fecha de diligenciarlo.\n"
RECONOCIMIENTO_FECHADO = (
    "Magangué 8 de marzo de 2021\nSeñores:\nCARIBEMAR DE LA COSTA S.A.S E.S.P.\n"
    "Ref.: Reconocimiento de deuda y propuesta de acuerdo de pago.\n"
    "Yo, Juan Carrera identificado como aparece al pie de mi firma, en mi calidad de usuario.\n"
)
CEDULA = "REPUBLICA DE COLOMBIA\nIDENTIFICACION PERSONAL\nCEDULA DE CIUDADANIA\n73.242.049\nNUMERO\nCARRERA\nAPELLIDOS\n"
HABEAS_DATA = "Señores\nCARIBEMAR DE LA COSTA S.A.S. E.S.P.\nASUNTO: Ley Habeas Data - NIC 7975593\nAutorizo el tratamiento.\n"

#: Como viene en el papel: el pagaré y su carta, el reconocimiento, la cédula y la Habeas Data.
TEXTOS = {1: PAGARE, 2: CARTA, 3: SIGUE_LA_CARTA, 4: RECONOCIMIENTO_FECHADO, 5: CEDULA, 6: HABEAS_DATA}


class TestLasPartes:
    def test_cada_hoja_en_su_parte(self):
        assert partes_del_acuerdo(range(1, 7), TEXTOS) == [
            (PAGARES, [1]),
            (PAGARES, [2, 3]),
            (RECONOCIMIENTO, [4]),
            (ANEXOS_DEL_ACUERDO, [5]),
            (HABEAS, [6]),
        ]


class TestElOrden:
    def test_con_fecha_el_reconocimiento_va_primero(self):
        assert orden_del_acuerdo(range(1, 7), TEXTOS, reconocimiento_fechado=True) == (4, 1, 2, 3, 6, 5)

    def test_sin_fecha_el_reconocimiento_va_al_final(self):
        assert orden_del_acuerdo(range(1, 7), TEXTOS, reconocimiento_fechado=False) == (1, 2, 3, 6, 5, 4)

    def test_sin_reconocimiento_queda_como_en_el_papel(self):
        assert orden_del_acuerdo([3, 1, 2], TEXTOS, reconocimiento_fechado=True) == (1, 2, 3)


class TestElPdfEscrito:
    def _grupo(self, orden=None) -> PageGroup:
        return PageGroup(code=ResolutionCode(value="01", raw="01"), page_numbers=[1, 2, 3, 4, 5, 6], orden=orden)

    def test_se_escribe_en_su_orden_y_se_inventaria_en_el_del_papel(self):
        grupo = self._grupo((4, 1, 2, 3, 6, 5))
        assert grupo.en_el_pdf == [4, 1, 2, 3, 6, 5]
        assert grupo.page_numbers == [1, 2, 3, 4, 5, 6]

    def test_un_orden_que_no_trae_las_mismas_hojas_no_vale(self):
        assert self._grupo((4, 1)).en_el_pdf == [1, 2, 3, 4, 5, 6]

    def test_la_fecha_de_su_pieza_decide(self):
        grupos = GroupingResult(groups=[self._grupo()])
        fechada = {"archivo": 0, "pages": [1, 2, 3, 4, 5, 6], "fecha": "2021-03-08", "fecha_pagina": 4}
        assert _ordenar_los_acuerdos(grupos, [fechada], TEXTOS, set(range(1, 7))).groups[0].en_el_pdf[0] == 4
        # La fecha que salió de un respaldo no es la del reconocimiento, pero el reconocimiento
        # que trae su renglón de fecha llenado -- aunque ningún lector lo lea -- está fechado y va
        # primero (el operador, 2026-11-24, 4251530 y 4251531).
        del_pagare = {**fechada, "fecha_pagina": 1}
        assert _ordenar_los_acuerdos(grupos, [del_pagare], TEXTOS, set(range(1, 7))).groups[0].en_el_pdf[0] == 4
        a_mano = {**TEXTOS, 4: RECONOCIMIENTO_FECHADO.replace("Magangué 8 de marzo de 2021", "t'oso-N OZ de 9iWi:vode 2o2-n")}
        assert _ordenar_los_acuerdos(grupos, [del_pagare], a_mano, set(range(1, 7))).groups[0].en_el_pdf[0] == 4
        # Sólo el renglón en blanco del formato es «sin fecha»: al final.
        en_blanco = {**TEXTOS, 4: RECONOCIMIENTO_FECHADO.replace("Magangué 8 de marzo de 2021", "________, ___ de ________ de 20___")}
        assert _ordenar_los_acuerdos(grupos, [del_pagare], en_blanco, set(range(1, 7))).groups[0].en_el_pdf[-1] == 4
        sin_fecha = {**fechada, "fecha": None}
        assert _ordenar_los_acuerdos(grupos, [sin_fecha], TEXTOS, set(range(1, 7))).groups[0].en_el_pdf[-1] == 4
        # Lo que no es del acuerdo no se toca.
        otro = replace(self._grupo())
        assert _ordenar_los_acuerdos(GroupingResult(groups=[otro]), [fechada], TEXTOS, set()).groups[0].orden is None


class TestElOtroDocumentoDentroDelAcuerdo:
    """1000258 (2026-11-23): «reconocimiento, pagaré, Ley Habeas Data, y luego nuevo documento, y luego anexos».

    La autorización para la financiación no tiene título del catálogo: se pegaba
    al reconocimiento de delante. Y la cédula que la OCR casi no leyó seguía al
    pagaré. Los nombres son inventados.
    """

    AUTORIZACION = (
        "Santa Rosa del Sur, 05 de Junio de 2023\nSeñores\nAFINIA\nAUTORIZACION\n"
        "Yo, Juana Carrera, identificada con cédula de ciudadanía, autorizo la financiación de la deuda.\n"
    )
    #: La foto de una cédula de la que la OCR sólo dejó basura y el rótulo roto.
    CEDULA_ROTA = "Si f r V 4 4 V % .<í^5 f CEDUIA P| OfyPADANIA 7 ,f r^. •^5 CARRERA APaUDOS JUANA :.>í4Síí?4"

    def test_va_despues_de_la_habeas_data_y_antes_de_los_anexos(self):
        from resolutions.application.anexos_declarados import OTRO_DOCUMENTO

        textos = {
            1: HABEAS_DATA, 2: CEDULA, 3: PAGARE, 4: self.CEDULA_ROTA, 5: CARTA,
            6: RECONOCIMIENTO_FECHADO, 7: self.AUTORIZACION, 8: CEDULA,
        }  # fmt: skip
        assert (OTRO_DOCUMENTO, [7]) in partes_del_acuerdo(range(1, 9), textos)
        assert (ANEXOS_DEL_ACUERDO, [4]) in partes_del_acuerdo(range(1, 9), textos)
        assert orden_del_acuerdo(range(1, 9), textos, reconocimiento_fechado=True) == (6, 3, 5, 1, 7, 2, 4, 8)
        assert orden_del_acuerdo(range(1, 9), textos, reconocimiento_fechado=False) == (3, 5, 1, 7, 2, 4, 8, 6)

    def test_tras_el_pagare_tambien(self):
        textos = {1: RECONOCIMIENTO_FECHADO, 2: PAGARE, 3: self.AUTORIZACION, 4: CEDULA}
        assert orden_del_acuerdo(range(1, 5), textos, reconocimiento_fechado=True) == (1, 2, 3, 4)

    def test_la_cedula_rota_es_de_identidad(self):
        from resolutions.domain.anexos_declarados import clase_de_la_hoja

        assert clase_de_la_hoja(self.CEDULA_ROTA) == "documento de identidad"
        assert clase_de_la_hoja("CEDUUoiltüDADANtA ; CARRERA APBiKSDS JUANA I® í1í:S^") == "documento de identidad"
