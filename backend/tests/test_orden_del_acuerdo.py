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
        # La fecha que salió del pagaré no es la del reconocimiento.
        del_pagare = {**fechada, "fecha_pagina": 1}
        assert _ordenar_los_acuerdos(grupos, [del_pagare], TEXTOS, set(range(1, 7))).groups[0].en_el_pdf[-1] == 4
        sin_fecha = {**fechada, "fecha": None}
        assert _ordenar_los_acuerdos(grupos, [sin_fecha], TEXTOS, set(range(1, 7))).groups[0].en_el_pdf[-1] == 4
        # Lo que no es del acuerdo no se toca.
        otro = replace(self._grupo())
        assert _ordenar_los_acuerdos(GroupingResult(groups=[otro]), [fechada], TEXTOS, set()).groups[0].orden is None
