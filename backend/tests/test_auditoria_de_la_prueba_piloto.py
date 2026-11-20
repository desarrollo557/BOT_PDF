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
