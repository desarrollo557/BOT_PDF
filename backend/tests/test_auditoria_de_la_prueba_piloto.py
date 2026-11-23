"""Los falsos avisos de la auditoría de cierre en la prueba piloto de Magangué (2026-11-20).

El operador pegó el informe de la auditoría de su corrida: «¿qué está pasando?».
Ninguno era un corte mal hecho; cada uno, una regla que la auditoría o el
revisor no conocían, o un dato que el bot leía mal:

- 4132539: «folio 11» en ocho constancias sin folio -- el número del formulario --.
- 1000265: la cédula detrás de una constancia pasa al documento siguiente
  saltando otra constancia: es la regla, no un error.
- 4132537: el reconocimiento con «02 de 02 de 22»; 4132571: la fecha que vio la IA.
- 4132569: «N° PQR: JRE2310202104692».
- 920933: la notificación por aviso que no cita ningún RE.

Los nombres y los NIC son inventados.
"""

from __future__ import annotations

from datetime import date

from resolutions.domain.foliacion_del_escrito import (
    foliacion_del_escrito,
    folios_creibles,
)
from resolutions.domain.nombre_oficial import le_falta_su_re
from resolutions.domain.tramites import radicado_de

CONSTANCIA = (
    "PARA LA EMPRESA\nRecibí constancia del contenido de la reclamación presentada ante CARIBEMAR\n"
    "N° PQR: RE2310202100001\nFECHA: 08/09/2021\nCAUSA:\nFacilidades de pago"
)
CEDULA = "REPUBLICA DE COLOMBIA\nIDENTIFICACION PERSONAL\nCEDULA DE CIUDADANIA\n1.000.000.001\nPEREZ\nAPELLIDOS"


class TestElFolioQueSeRepite:
    def test_el_mismo_numero_en_muchas_hojas_no_es_foliacion(self):
        assert folios_creibles({1: 11, 2: 11, 4: 11, 5: 11, 6: 11, 8: 11}) == {}

    def test_la_numeracion_de_verdad_queda(self):
        assert folios_creibles({1: 1, 2: 2, 3: 3, 4: 1, 5: 2}) == {1: 1, 2: 2, 3: 3, 4: 1, 5: 2}
        # Las dos caras de una hoja llevan el mismo folio.
        assert folios_creibles({1: 5, 2: 5, 3: 6}) == {1: 5, 2: 5, 3: 6}

    def test_y_no_une_las_constancias(self):
        foliacion = foliacion_del_escrito({p: 11 for p in (1, 2, 4, 5, 6, 8, 9, 10)}, range(1, 11))
        assert not foliacion.continua


class TestLaCedulaTrasLaConstancia:
    def test_es_un_cruce_que_explica_la_regla(self):
        from resolutions.application.perfiles_de_revision import perfil_de

        textos = {1: CONSTANCIA, 2: CONSTANCIA, 3: CEDULA, 4: CONSTANCIA, 5: "Ref.: Reconocimiento de deuda"}
        assert 3 in perfil_de("Caja de correspondencia").patrones(textos).cruces


class TestLaFechaQueLaAuditoriaNoVeia:
    def test_el_anio_en_dos_cifras_en_la_correspondencia(self):
        from resolutions.domain.fechas_extremas import (
            ESTRUCTURA,
            PAPEL,
            FechasDeLaFila,
            contrastar_las_fechas,
        )

        fila = FechasDeLaFila(inicial=date(2022, 2, 2), final=date(2022, 2, 2), origen=PAPEL)
        revision = contrastar_las_fechas(fila, ["Magangue, 02 de 02 de 22\nRef.: Reconocimiento de deuda"], regla=ESTRUCTURA)
        assert not revision.preguntas

    def test_lo_que_vio_la_ia_va_a_la_constancia(self):
        from resolutions.api.worker.correspondencia import lo_leido_fuera_de_la_capa

        pieza = {"fecha": "2020-10-21", "fecha_pagina": 6, "fecha_via": "visión"}
        leido = lo_leido_fuera_de_la_capa([pieza], releidas={6: ["Recibido: 21/10/2020"]}, leidas_por_ocr={})
        assert leido == [{"paginas": [6], "texto": "Recibido: 21/10/2020"}]


class TestElPqrConUnaLetraDelante:
    def test_la_letra_suelta_del_campo_no_rompe_el_re(self):
        assert radicado_de("PARA LA EMPRESA\nN“ PQR: JRE2310202104692 FECHA: 12/05/2021") == "RE2310202104692"

    def test_fuera_del_campo_no(self):
        assert radicado_de("vea el radicado XRE2310202104692") is None


class TestLaNotificacionSinRadicado:
    def test_si_no_cita_ninguno_no_le_falta(self):
        aviso = "Electricaribe MESUC 2818\npor intermedio de este AVISO nos permitimos notificarlo del acto administrativo"
        assert not le_falta_su_re("NOTIFICACION POR AVISO", [aviso])

    def test_si_lo_cita_si(self):
        assert le_falta_su_re("NOTIFICACION POR AVISO", ["Radicado número: RE2310202103443"])

    def test_la_constancia_siempre(self):
        assert le_falta_su_re("CONSTANCIA DEL CONTENIDO DE LA RECLAMACION", ["sin nada"])


class TestElDiaRotoEnElRevisor:
    """4132553: la fila 29/10/2020 del reconocimiento «290 de Oct de 2020» frente a la carta leída «2010»."""

    def test_manda_la_escrita_en_la_hoja_principal(self):
        from resolutions.domain.fechas_extremas import (
            ESTRUCTURA,
            PAPEL,
            FechasDeLaFila,
            _escrita_a_mano,
            contrastar_las_fechas,
        )

        assert _escrita_a_mano("Magangue, 290 de Oct de 2020", date(2020, 10, 29))
        assert not _escrita_a_mano("Magangue, 290 de Oct de 2020", date(2020, 10, 28))
        fila = FechasDeLaFila(inicial=date(2020, 10, 29), final=date(2020, 10, 29), origen=PAPEL)
        textos = [
            "Magangue, 290 de Oct de 2020\nRef.: Reconocimiento de deuda y propuesta de acuerdo de pago",
            "Firmado en Magangue a los 29 días del mes Octubre del año 2010",
        ]
        assert not contrastar_las_fechas(fila, textos, regla=ESTRUCTURA).preguntas


#: Una hoja escrita de verdad: con menos de 25 palabras el bot la toma por muda.
ESCRITO = (
    "DECLARACION JURAMENTADA DE IDENTIDAD\nSeñores Afinia, mediante la presente declaro bajo la gravedad "
    "de juramento que soy la persona titular del servicio de energía del predio ubicado en la dirección "
    "indicada y que los datos que suministro en este documento son ciertos y verificables por la empresa"
)


class TestLaCedulaNuncaAbreUnPdf:
    """4132540: la constancia va sola y su cédula pasa a la declaración juramentada, pero detrás de ella."""

    def _grupos(self, *tramos):
        from resolutions.domain.grouping import GroupingResult, PageGroup
        from resolutions.domain.resolution_code import ResolutionCode

        return GroupingResult(
            groups=[
                PageGroup(code=ResolutionCode(value=f"{n:02d}", raw=f"{n:02d}"), page_numbers=list(t))
                for n, t in enumerate(tramos, start=1)
            ],
        )

    def test_la_cedula_va_detras_del_documento(self):
        from resolutions.application.anexos_declarados import la_cedula_detras

        textos = {4: CONSTANCIA, 5: CEDULA, 6: ESCRITO}
        [constancia, declaracion] = la_cedula_detras(self._grupos([4], [5, 6]), textos).groups
        assert constancia.en_el_pdf == [4]
        assert declaracion.en_el_pdf == [6, 5] and declaracion.page_numbers == [5, 6]

    def test_tambien_con_el_ocr_roto(self):
        from resolutions.application.anexos_declarados import la_cedula_detras

        rota = "REPUBLICA DE COLOMIA\nIDENTIFICACION PERSONAL\nCEBULABE ClUDi^DANiA\n1.000.000.001\nPEREZ"
        textos = {5: rota, 6: ESCRITO}
        [grupo] = la_cedula_detras(self._grupos([5, 6]), textos).groups
        assert grupo.en_el_pdf == [6, 5]

    def test_con_su_reverso_mudo(self):
        from resolutions.application.anexos_declarados import la_cedula_detras

        textos = {1: CEDULA, 2: "", 3: ESCRITO, 4: ESCRITO}
        [grupo] = la_cedula_detras(self._grupos([1, 2, 3, 4]), textos).groups
        assert grupo.en_el_pdf == [3, 4, 1, 2]

    def test_sola_o_ya_detras_no_se_toca(self):
        from resolutions.application.anexos_declarados import la_cedula_detras

        textos = {1: CEDULA, 2: ESCRITO, 3: CEDULA}
        grupos = self._grupos([1], [2, 3])
        assert la_cedula_detras(grupos, textos) is grupos
