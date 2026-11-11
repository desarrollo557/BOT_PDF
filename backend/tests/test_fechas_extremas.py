"""El revisor de fechas: la fecha inicial y la final de cada documento contra su papel (el operador, 2026-11-10).

«Necesito estar muy seguro de cada fecha en cada documento, sin importar la
habilidad», «corregir sólo con prueba» y «saber manejar un margen de errores».
Esta suite fija el núcleo que usan los dos agentes -- el que procesa y la
auditoría de cierre --, en el orden en que trabaja:

1. **Leer la fila** (``leer_fecha``, ``fechas_de_un_par``, ``fechas_de_la_fila``):
   cada forma de fila real -- la del acta de consejo, la de la historia, la del
   FUID ya hecho, la de la nómina -- con sus formatos.
2. **El contraste con el papel** (``contrastar_las_fechas``): cada regla de
   habilidad confirma, corrige con dos pruebas o pregunta; el margen del OCR y
   de la precisión es duda, nunca corrección; la ventana de años del libro.
3. **La IA para lo dudoso** (``revisar_las_fechas``): una pregunta por documento,
   sólo con cita del papel, y una IA caída o rota deja la duda, no el trabajo.
4. **El informe** (``anotar_en_el_informe``): la misma forma en todas las
   habilidades, para la pantalla, la cola de revisión y la auditoría.

Y una matriz que recorre **todas las habilidades** del registro de perfiles con
un documento sintético de su regla: ninguna queda sin cubrir.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from resolutions.application.control import Cancelled
from resolutions.application.perfiles_de_revision import PERFILES, perfil_de
from resolutions.application.ports import VeredictoDeDato
from resolutions.application.revisor_de_fechas import (
    A_REVISION,
    CLAVE_DEL_INFORME,
    CONFIRMADA,
    CORREGIDA,
    SIN_DATO,
    FechasRevisadas,
    anotar_en_el_informe,
    revisar_las_fechas,
)
from resolutions.domain.fechas_extremas import (
    ANIO,
    ANIOS,
    DIA,
    ESTRUCTURA,
    EXPEDICION,
    EXTREMOS,
    FIRMA,
    GRADO,
    REGLAS,
    SESION,
    FechasDeLaFila,
    contrastar_las_fechas,
    difiere_como_el_ocr,
    fechas_de_la_fila,
    fechas_de_un_par,
    leer_fecha,
)

# -- los papeles -----------------------------------------------------------------------------
#
# Uno por regla, con lo que trae el papel de verdad: la fecha que importa y las
# que despistan (la de la plantilla, la de la próxima reunión, la de un acuerdo
# viejo).

ACTA = (
    "UNIVERSIDAD DE CARTAGENA\nCONSEJO DE FACULTAD\nACTA No. 019\n"
    "Fecha: 21 de febrero de 2012\nHora: 8:00 a.m.\nSe verificó el quórum.\n"
    "VERSIÓN 00 FECHA 04-05-2011\nPróxima reunión: 6 de marzo de 2012"
)
#: El lector de la apertura toma la de la próxima reunión: la IA lo rescata.
ACTA_CON_LA_PROXIMA = (
    "ACTA ORDINARIA No. 003\nEn Cartagena, a los 21 días del mes de febrero de 2012, "
    "se reunió el Consejo de Facultad.\nVERSIÓN 00 FECHA 04-05-2011\n"
    "Se citó a la próxima reunión el 6 de marzo de 2012."
)
#: El acta 019 de Odontología: el OCR deshizo el día de la apertura y una fecha
#: de respaldo, más abajo, es otra. La primera versión la corregía al 17/11/2007.
ACTA_I3DF = (
    "ACTA CONSEJO DE FACULTAD\nACTA No. 019\nCartagena, I3DF, DICIEMBRE DE 2007\n"
    "Se verificó el quórum.\nEl 17 de noviembre de 2007 se aprobó."
)
GRADO_TEXTO = (
    "ACTA DE GRADO No. 1234\nEn la ciudad de Cartagena, a los 15 días del mes de junio de 2001, "
    "se reunieron el Rector y el Secretario General."
)
#: Con el número y el año en su encabezado, como van impresos: sin ellos la
#: fórmula no es prueba (2026-11-10).
RESOLUCION = (
    "RESOLUCION No. 00123 DE 2005\nPor la cual se concede una licencia\nRESUELVE:\nARTICULO PRIMERO: ...\n"
    "COMUNIQUESE Y CUMPLASE\nDada en Cartagena de Indias, a los 10 días del mes de marzo de 2005."
)
CERTIFICADO = (
    "CERTIFICADO DE TIEMPO DE SERVICIO No. 45\nse firma el presente en Cartagena a los 20 días "
    "del mes de Enero de 1993"
)
HISTORIA = "HISTORIA ACADEMICA\nALEMAN PORTILLA EVELYN\nINGRESO: 1977\nPRIMER SEMESTRE\nGRADO: 1.983"
CORRESPONDENCIA = (
    "Cartagena, 4 de mayo de 2011\nSeñores ELECTRICARIBE\nAsunto: reclamo\n...\n"
    "Respuesta del 30/08/2016"
)


class _JuezFalso:
    """Un juez que contesta lo que se le dicte, y anota lo que se le preguntó."""

    def __init__(self, respuestas=None, *, error: Exception | None = None):
        self.respuestas = respuestas
        self.error = error
        self.preguntas: list[list[dict[str, str]]] = []

    def verificar(self, texto, datos):
        self.preguntas.append(datos)
        if self.error is not None:
            raise self.error
        return self.respuestas


def _par(inicial, final=None) -> FechasDeLaFila:
    return fechas_de_un_par(inicial, inicial if final is None else final)


# -- 1. leer la fila -------------------------------------------------------------------------


class TestLeerLaFecha:
    @pytest.mark.parametrize(
        ("valor", "esperada", "precision"),
        [
            ("17/12/2012", date(2012, 12, 17), DIA),
            ("17-12-2012", date(2012, 12, 17), DIA),
            ("17.12.2012", date(2012, 12, 17), DIA),
            ("7/2/2012", date(2012, 2, 7), DIA),
            ("2012-12-17", date(2012, 12, 17), DIA),
            ("2012-12-17T00:00:00", date(2012, 12, 17), DIA),
            ("  1986 ", date(1986, 1, 1), ANIO),
            (1986, date(1986, 1, 1), ANIO),
            (date(2001, 6, 15), date(2001, 6, 15), DIA),
        ],
    )
    def test_cada_formato_de_las_filas(self, valor, esperada, precision):
        assert leer_fecha(valor) == (esperada, precision)

    def test_un_datetime_de_una_hoja_de_calculo_es_su_dia(self):
        # openpyxl devuelve ``datetime``: comparado con un ``date`` nunca es igual.
        fecha, precision = leer_fecha(datetime(2012, 12, 17, 0, 0))
        assert (fecha, precision) == (date(2012, 12, 17), DIA)
        assert type(fecha) is date

    @pytest.mark.parametrize(
        "valor",
        [None, "", "N/A", "n/a", "S.F.", "31/02/2012", "dic 2012", True, 99, 3000],
    )
    def test_lo_que_no_es_una_fecha_no_se_inventa(self, valor):
        assert leer_fecha(valor)[0] is None


class TestElParDeFechas:
    def test_el_primero_de_enero_y_el_treinta_y_uno_de_diciembre_son_anios(self):
        par = fechas_de_un_par("01/01/1977", "31/12/1983")
        assert (par.inicial, par.final, par.precision) == (
            date(1977, 1, 1),
            date(1983, 12, 31),
            ANIO,
        )

    def test_un_anio_en_cualquiera_de_las_dos_hace_el_par_de_anios(self):
        assert fechas_de_un_par("1986", "17/12/1986").precision == ANIO

    def test_dos_dias_son_dias(self):
        assert fechas_de_un_par("04-05-2011", "30-08-2016").precision == DIA

    def test_el_mismo_primero_de_enero_es_un_dia(self):
        # Un acta del 1 de enero no es «todo el año».
        assert fechas_de_un_par("01/01/2000", "01/01/2000").precision == DIA

    def test_el_origen_se_conserva(self):
        assert fechas_de_un_par("1986", "1990", origen="del libro").origen == "del libro"


class TestLaFilaDeCadaHabilidad:
    """Las formas de fila de las entregas reales (``.bot-entregas/*.json``)."""

    def test_el_acta_de_consejo_una_sola_fecha(self):
        # 00C003284/UPD3859771, «10N°003-21 DE FEBRERO DE 2012.pdf».
        fila = {
            "archivo": "10N°003-21 DE FEBRERO DE 2012.pdf",
            "acta": "ACTA ORDINARIA No. 003",
            "fecha": "21-02-2012",
            "observaciones": "",
        }
        assert fechas_de_la_fila(fila) == FechasDeLaFila(
            date(2012, 2, 21), date(2012, 2, 21), DIA, "papel"
        )

    def test_la_historia_academica_por_anios(self):
        # CAJA 00C003278, «ALEMAN PORTILLA EVELYN», 1977-1983.
        fila = {
            "tipo": "HISTORIA ACADEMICA",
            "anio_inicial": 1977,
            "anio_final": 1983,
            "fecha_exacta": None,
            "observaciones": "",
        }
        assert fechas_de_la_fila(fila) == FechasDeLaFila(
            date(1977, 1, 1), date(1983, 12, 31), ANIO, "papel"
        )

    def test_la_historia_con_un_anio_con_punto(self):
        fila = {"anio_inicial": "1.977", "anio_final": None}
        fechas = fechas_de_la_fila(fila)
        assert (fechas.inicial, fechas.final, fechas.precision) == (
            date(1977, 1, 1),
            None,
            ANIO,
        )

    def test_la_historia_con_fecha_exacta(self):
        fila = {"anio_inicial": 1986, "anio_final": 1986, "fecha_exacta": "17/12/1986"}
        assert fechas_de_la_fila(fila) == FechasDeLaFila(
            date(1986, 12, 17), date(1986, 12, 17), DIA, "papel"
        )

    def test_la_fila_del_fuid_ya_hecha(self):
        # 00C003285/UPD3859779: la fecha de la plantilla («04-05-2011») en la inicial.
        fila = {
            "tipo": "FILA DEL FUID",
            "fuid": {
                "fecha_inicial": "04-05-2011",
                "fecha_final": "30-08-2016",
                "notas": "",
            },
        }
        assert fechas_de_la_fila(fila) == FechasDeLaFila(
            date(2011, 5, 4), date(2016, 8, 30), DIA, "papel"
        )

    def test_la_nomina_y_el_certificado(self):
        fila = {
            "fecha_inicial": "01/01/1972",
            "fecha_final": "31/12/1972",
            "observaciones": "",
        }
        assert fechas_de_la_fila(fila).precision == ANIO
        fila = {"fecha_inicial": "20/01/1993", "fecha_final": "20/01/1993"}
        assert fechas_de_la_fila(fila).precision == DIA

    @pytest.mark.parametrize(
        ("observaciones", "origen"),
        [
            ("fecha tomada del nombre del archivo", "del nombre del archivo"),
            ("la fecha, de su trámite", "de su tramite"),
            ("año de la serie", "de la serie"),
        ],
    )
    def test_de_donde_salio_la_fecha_lo_dicen_sus_observaciones(
        self, observaciones, origen
    ):
        fila = {"fecha": "21-02-2012", "observaciones": observaciones}
        assert fechas_de_la_fila(fila).origen == origen

    def test_las_notas_del_fuid_tambien_dicen_el_origen(self):
        fila = {
            "fuid": {
                "fecha_inicial": "1986",
                "fecha_final": "1990",
                "notas": "años del libro",
            }
        }
        assert fechas_de_la_fila(fila).origen == "del libro"

    @pytest.mark.parametrize(
        "fila",
        [
            {},
            {"fecha": "N/A"},
            {"fecha_inicial": "S.F.", "fecha_final": None},
            {"fuid": {"fecha_inicial": "N/A", "fecha_final": "N/A"}},
            {"anio_inicial": None, "anio_final": None, "fecha_exacta": None},
        ],
    )
    def test_una_fila_sin_fechas_no_trae(self, fila):
        assert fechas_de_la_fila(fila) is None


# -- 2. el contraste con el papel ------------------------------------------------------------


class TestCadaRegla:
    """Cada regla confirma la suya, y las de lector fuerte corrigen con dos pruebas."""

    @pytest.mark.parametrize(
        ("regla", "texto", "fechas"),
        [
            (SESION, ACTA, _par("21-02-2012")),
            (GRADO, GRADO_TEXTO, _par("15-06-2001")),
            (EXPEDICION, RESOLUCION, _par("10/03/2005")),
            (FIRMA, CERTIFICADO, _par("20/01/1993")),
            (
                ANIOS,
                HISTORIA,
                fechas_de_la_fila({"anio_inicial": 1977, "anio_final": 1983}),
            ),
            (EXTREMOS, CORRESPONDENCIA, _par("04/05/2011", "30/08/2016")),
        ],
    )
    def test_la_de_su_papel_se_confirma(self, regla, texto, fechas):
        revision = contrastar_las_fechas(fechas, [texto], regla=regla)
        assert revision.confirmadas == ("la fecha inicial", "la fecha final")
        assert revision.correcciones == revision.preguntas == ()

    @pytest.mark.parametrize(
        ("regla", "texto", "de_la_fila", "del_papel"),
        [
            (SESION, ACTA, "22-05-2013", date(2012, 2, 21)),
            (GRADO, GRADO_TEXTO, "03-09-1999", date(2001, 6, 15)),
            (EXPEDICION, RESOLUCION, "10/08/2006", date(2005, 3, 10)),
            (FIRMA, CERTIFICADO, "05/07/1990", date(1993, 1, 20)),
        ],
    )
    def test_dos_pruebas_del_papel_corrigen(self, regla, texto, de_la_fila, del_papel):
        revision = contrastar_las_fechas(_par(de_la_fila), [texto], regla=regla)
        assert [c.campo for c in revision.correcciones] == [
            "fecha_inicial",
            "fecha_final",
        ]
        assert all(c.dice_el_papel == del_papel for c in revision.correcciones)
        assert "no está escrita en el documento" in revision.correcciones[0].prueba

    def test_la_fecha_de_la_plantilla_no_engana_a_la_sesion(self):
        # «VERSIÓN 00 FECHA 04-05-2011»: escrita, pero el lector de la apertura dice otra.
        revision = contrastar_las_fechas(_par("04-05-2011"), [ACTA], regla=SESION)
        assert revision.correcciones == ()
        assert [p.dice_el_papel for p in revision.preguntas] == [date(2012, 2, 21)] * 2

    @pytest.mark.parametrize("regla", [ANIOS, EXTREMOS])
    def test_sin_lector_fuerte_nunca_se_corrige(self, regla):
        revision = contrastar_las_fechas(
            _par("09/09/1999"), [CORRESPONDENCIA], regla=regla
        )
        assert revision.correcciones == ()
        assert all("no está escrita" in p.duda for p in revision.preguntas)
        assert len(revision.preguntas) == 2

    def test_la_fila_sin_fecha_la_toma_del_lector(self):
        fechas = FechasDeLaFila(None, date(2005, 3, 10))
        revision = contrastar_las_fechas(fechas, [RESOLUCION], regla=EXPEDICION)
        assert [
            (c.campo, c.dice_la_fila, c.dice_el_papel) for c in revision.correcciones
        ] == [("fecha_inicial", None, date(2005, 3, 10))]

    def test_sin_lector_y_sin_fecha_en_la_fila_es_sin_dato(self):
        fechas = FechasDeLaFila(date(2011, 5, 4), None)
        revision = contrastar_las_fechas(fechas, [CORRESPONDENCIA], regla=EXTREMOS)
        assert revision.confirmadas == ("la fecha inicial",)
        assert revision.sin_dato == ("la fecha final",)

    @pytest.mark.parametrize("textos", [[], [""], ["   \n  "]])
    def test_paginas_sin_texto_son_sin_dato(self, textos):
        revision = contrastar_las_fechas(_par("21-02-2012"), textos, regla=SESION)
        assert revision.sin_dato == (
            "sus páginas no traen texto en que buscar las fechas",
        )
        assert revision.confirmadas == revision.correcciones == revision.preguntas == ()


class TestElMargenDeError:
    """Lo que se aparta como lo aparta el OCR, o sólo por la precisión, es duda: nunca se corrige."""

    @pytest.mark.parametrize(
        ("una", "otra", "precision", "como_el_ocr"),
        [
            (date(2009, 1, 16), date(2000, 1, 16), DIA, True),  # un dígito del año
            (date(2007, 12, 13), date(2007, 12, 18), DIA, True),  # un dígito del día
            (
                date(2007, 12, 13),
                date(2007, 11, 13),
                DIA,
                False,
            ),  # otro mes: no es el OCR
            (date(2007, 12, 13), date(2008, 12, 31), DIA, False),  # tres dígitos
            (date(1983, 1, 1), date(1988, 1, 1), ANIO, True),
            (date(1983, 1, 1), date(1994, 1, 1), ANIO, False),
        ],
    )
    def test_que_es_un_digito_del_ocr(self, una, otra, precision, como_el_ocr):
        assert difiere_como_el_ocr(una, otra, precision) is como_el_ocr

    def test_un_digito_del_anio_es_pregunta_y_no_correccion(self):
        papel = "CONSEJO DE FACULTAD\nACTA No. 5\nFecha: 16 de enero de 2000\nSe verificó el quórum."
        revision = contrastar_las_fechas(_par("16-01-2009"), [papel], regla=SESION)
        assert revision.correcciones == ()
        assert [p.dice_el_papel for p in revision.preguntas] == [date(2000, 1, 16)] * 2
        assert (
            "pero la apertura de la sesión dice 16/01/2000" in revision.preguntas[0].duda
        )

    def test_el_caso_i3df_diciembre_de_2007_no_se_corrige(self):
        # El acta 019: el día lo deshizo el OCR, su mes y su año siguen escritos.
        # El lector cae en una fecha de respaldo (17/11/2007): no basta.
        revision = contrastar_las_fechas(_par("13-12-2007"), [ACTA_I3DF], regla=SESION)
        assert revision.correcciones == ()

    def test_el_caso_i3df_tampoco_lo_corrige_la_ia(self):
        # La IA cita la fecha de respaldo, que está en el papel y coincide con
        # el lector: aun así, el mes y el año de la fila siguen escritos.
        juez = _JuezFalso(
            {
                "fecha_inicial": VeredictoDeDato(
                    "no_esta", "El 17 de noviembre de 2007 se aprobó"
                ),
                "fecha_final": VeredictoDeDato(
                    "no_esta", "El 17 de noviembre de 2007 se aprobó"
                ),
            }
        )
        revisadas = revisar_las_fechas(
            _par("13-12-2007"), [ACTA_I3DF], regla=SESION, juez=juez
        )
        assert revisadas.estado != CORREGIDA
        assert revisadas.inicial == date(2007, 12, 13)

    def test_la_fecha_de_la_fila_escrita_en_otra_forma_se_confirma_por_su_mes_y_anio(
        self,
    ):
        # Sin lector: «DICIEMBRE DE 2007» apoya el 13/12/2007 que el OCR deshizo.
        revision = contrastar_las_fechas(
            _par("13-12-2007"), ["Cartagena, I3DF, DICIEMBRE DE 2007"], regla=EXTREMOS
        )
        assert revision.confirmadas == ("la fecha inicial", "la fecha final")

    def test_la_precision_un_anio_frente_a_un_dia_es_el_mismo(self):
        fechas = fechas_de_un_par("1986", "1986")
        revision = contrastar_las_fechas(fechas, ["expedido el 17/12/1986"], regla=ANIOS)
        assert revision.confirmadas == ("la fecha inicial", "la fecha final")

    def test_el_anio_con_punto_tambien_es_el_anio(self):
        fechas = fechas_de_la_fila({"anio_inicial": 1975, "anio_final": 1975})
        assert contrastar_las_fechas(fechas, ["AÑO 1.975"], regla=ANIOS).confirmadas == (
            "la fecha inicial",
            "la fecha final",
        )


class TestLaVentanaDelLibro:
    def test_un_anio_fuera_de_los_del_libro_es_pregunta_aunque_este_escrito(self):
        # ACOSTA BELLO, 1994-2001 en un libro de 1978-1988 (2026-11-10).
        fechas = fechas_de_la_fila({"anio_inicial": 1994, "anio_final": 2001})
        revision = contrastar_las_fechas(
            fechas, ["ACOSTA BELLO 1994 2001"], regla=ANIOS, ventana=(1978, 1988)
        )
        assert revision.confirmadas == ()
        assert [p.duda for p in revision.preguntas] == [
            "la fecha inicial 1994 cae fuera de los años del libro (1978-1988)",
            "la fecha final 2001 cae fuera de los años del libro (1978-1988)",
        ]

    def test_dentro_de_la_ventana_se_confirma(self):
        fechas = fechas_de_la_fila({"anio_inicial": 1979, "anio_final": 1984})
        revision = contrastar_las_fechas(
            fechas, ["1979 ... 1984"], regla=ANIOS, ventana=(1978, 1988)
        )
        assert revision.confirmadas == ("la fecha inicial", "la fecha final")

    def test_la_ventana_tambien_mira_las_fechas_de_dia(self):
        # 2026-11-10: una fecha de día fuera de los años del libro es duda,
        # aunque esté escrita; va derecho a Revisión, sin pagar la IA.
        revision = contrastar_las_fechas(
            _par("04/05/2011"), [CORRESPONDENCIA], regla=EXTREMOS, ventana=(1978, 1988)
        )
        assert revision.confirmadas == ()
        assert [p.para_la_ia for p in revision.preguntas] == [False, False]
        assert revision.preguntas[0].duda == (
            "la fecha inicial 04/05/2011 cae fuera de los años del libro (1978-1988)"
        )

    def test_fuera_de_la_ventana_no_se_le_pregunta_a_la_ia(self):
        juez = _JuezFalso({})
        revisadas = revisar_las_fechas(
            _par("04/05/2011"), [CORRESPONDENCIA], regla=EXTREMOS, ventana=(1978, 1988), juez=juez
        )
        assert revisadas.estado == A_REVISION
        assert juez.preguntas == []

    def test_los_anios_del_libro_salen_del_nombre_de_su_archivo(self):
        fila = {
            "archivo": "1ACTAS DE CONSEJO DE FACULTAD 2007-2009 DE N°1 AL 439-2.pdf",
            "fecha": "16-01-2009",
        }
        assert fechas_de_la_fila(fila).ventana == (2007, 2009)
        # «N°19-25 Y 30 DE OCTUBRE DE 2012» no es un libro de años.
        fila = {"archivo": "3N°19-25 Y 30 DE OCTUBRE DE 2012.pdf", "fecha": "30-10-2012"}
        assert fechas_de_la_fila(fila).ventana is None

    def test_la_fecha_del_papel_fuera_de_la_ventana_no_es_prueba(self):
        # ACTA EXTRAORDINARIA 001 (libro 2007-2009): el papel dice «16 DE ENERO
        # DE 2000», una errata. Alterada la fila al 17/01/2009, el revisor la
        # corregía al 16/01/2000 (la revisión adversarial del 2026-11-10).
        papel = (
            "ACTA CONSEJO DE FACULTAD EXTRAORDINARIO No. 001\n16 DE ENERO DE 2000\n"
            "FECHA:\nHORA:\nSe verificó el quórum. Calendario académico del año 2009."
        )
        fila = {"archivo": "ACTAS 2007-2009.pdf", "fecha": "17-02-2009"}
        revision = contrastar_las_fechas(fechas_de_la_fila(fila), [papel], regla=SESION)
        assert revision.correcciones == ()
        assert "fuera de los años del libro (2007-2009)" in revision.preguntas[0].duda


# -- 3. el revisor, con la IA para lo dudoso -------------------------------------------------


class TestElRevisor:
    def test_sin_fechas_en_la_fila_es_sin_dato(self):
        revisadas = revisar_las_fechas(None, [ACTA], regla=SESION)
        assert (revisadas.estado, revisadas.motivos) == (
            SIN_DATO,
            ("la fila no trae fechas",),
        )

    def test_paginas_sin_texto_son_sin_dato_con_su_motivo(self):
        revisadas = revisar_las_fechas(_par("21-02-2012"), [""], regla=SESION)
        assert revisadas.estado == SIN_DATO
        assert revisadas.motivos == (
            "sus páginas no traen texto en que buscar las fechas",
        )

    def test_lo_confirmado_no_gasta_ia(self):
        juez = _JuezFalso({})
        revisadas = revisar_las_fechas(
            _par("21-02-2012"), [ACTA], regla=SESION, juez=juez
        )
        assert revisadas.estado == CONFIRMADA
        assert juez.preguntas == []
        assert revisadas.nota == ""

    def test_dos_pruebas_corrigen_sin_ia(self):
        juez = _JuezFalso({})
        revisadas = revisar_las_fechas(
            _par("10/08/2006"), [RESOLUCION], regla=EXPEDICION, juez=juez
        )
        assert (revisadas.estado, revisadas.inicial, revisadas.final) == (
            CORREGIDA,
            date(2005, 3, 10),
            date(2005, 3, 10),
        )
        assert juez.preguntas == []
        assert revisadas.nota.startswith(
            "fecha inicial corregida: 10/08/2006 → 10/03/2005 (la fórmula de expedición"
        )

    def test_sin_ia_lo_dudoso_va_a_revision_con_su_motivo(self):
        revisadas = revisar_las_fechas(
            _par("16/01/2009"), [CORRESPONDENCIA], regla=EXTREMOS
        )
        assert revisadas.estado == A_REVISION
        assert revisadas.inicial == date(2009, 1, 16)  # las de la fila, sin tocar
        assert revisadas.nota == (
            "fechas: la fecha inicial 16/01/2009 no está escrita en el documento; "
            "la fecha final 16/01/2009 no está escrita en el documento"
        )

    def test_una_sola_pregunta_por_documento_con_lo_dudoso(self):
        juez = _JuezFalso(None)
        revisar_las_fechas(
            _par("04/05/2011", "09/09/2019"), [CORRESPONDENCIA], regla=EXTREMOS, juez=juez
        )
        # Una pregunta, y sólo con la final: la inicial ya la confirmó el papel.
        assert juez.preguntas == [[{"campo": "fecha_final", "valor": "09/09/2019"}]]

    def test_la_ia_confirma_citando_el_papel(self):
        # El lector de la apertura toma la próxima reunión; la de la fila está
        # escrita: duda. La IA la confirma con su cita.
        assert contrastar_las_fechas(
            _par("21-02-2012"), [ACTA_CON_LA_PROXIMA], regla=SESION
        ).preguntas
        cita = "a los 21 días del mes de febrero de 2012"
        juez = _JuezFalso(
            {
                "fecha_inicial": VeredictoDeDato("esta", cita),
                "fecha_final": VeredictoDeDato("esta", cita),
            }
        )
        revisadas = revisar_las_fechas(
            _par("21-02-2012"), [ACTA_CON_LA_PROXIMA], regla=SESION, juez=juez
        )
        assert revisadas.estado == CONFIRMADA
        assert revisadas.preguntadas_a_la_ia == 2
        assert revisadas.motivos == ()

    def test_la_ia_corrige_citando_el_papel_y_de_acuerdo_con_el_lector(self):
        # La fila trae la de la próxima reunión; el lector, la apertura: duda,
        # porque la de la fila también está escrita. La IA cita la apertura.
        cita = "Fecha: 21 de febrero de 2012"
        juez = _JuezFalso(
            {
                "fecha_inicial": VeredictoDeDato("no_esta", cita),
                "fecha_final": VeredictoDeDato("no_esta", cita),
            }
        )
        revisadas = revisar_las_fechas(
            _par("06-03-2012"), [ACTA], regla=SESION, juez=juez
        )
        assert (revisadas.estado, revisadas.inicial, revisadas.final) == (
            CORREGIDA,
            date(2012, 2, 21),
            date(2012, 2, 21),
        )
        assert "la IA lo cita del papel: «Fecha: 21 de febrero de 2012»" in revisadas.nota

    def test_la_ia_no_corrige_contra_el_lector(self):
        cita = "Próxima reunión: 6 de marzo de 2012"
        juez = _JuezFalso({"fecha_inicial": VeredictoDeDato("no_esta", cita)})
        revisadas = revisar_las_fechas(
            _par("04-05-2011"), [ACTA], regla=SESION, juez=juez
        )
        assert revisadas.estado == A_REVISION
        assert revisadas.correcciones == ()

    def test_la_ia_no_corrige_lo_que_se_aparta_como_el_ocr(self):
        papel = "Cartagena, 16 de enero de 2000\nAsunto: reclamo"
        juez = _JuezFalso(
            {"fecha_inicial": VeredictoDeDato("no_esta", "16 de enero de 2000")}
        )
        revisadas = revisar_las_fechas(
            _par("16/01/2009"), [papel], regla=EXTREMOS, juez=juez
        )
        assert revisadas.estado == A_REVISION

    def test_una_cita_que_no_esta_en_el_papel_no_vale(self):
        juez = _JuezFalso(
            {
                "fecha_inicial": VeredictoDeDato(
                    "no_esta", "Cartagena, 9 de septiembre de 1999"
                )
            }
        )
        revisadas = revisar_las_fechas(
            _par("09/09/1999"), [CORRESPONDENCIA], regla=EXTREMOS, juez=juez
        )
        assert revisadas.estado == A_REVISION
        assert revisadas.preguntadas_a_la_ia == 0

    def test_una_cita_con_dos_fechas_no_decide(self):
        papel = "Cartagena, 4 de mayo de 2011 y 30/08/2016"
        juez = _JuezFalso({"fecha_inicial": VeredictoDeDato("no_esta", papel)})
        revisadas = revisar_las_fechas(
            _par("09/09/1999"), [papel], regla=EXTREMOS, juez=juez
        )
        assert revisadas.estado == A_REVISION

    def test_la_correccion_de_un_anio_final_es_el_fin_de_su_anio(self):
        # Una nómina «01/01/1972-31/12/1972» que el papel dice de 1965: la final
        # corregida se escribe 31/12/1965, no 01/01/1965. (1972 frente a 1975
        # sería un dígito del OCR: duda, no corrección.)
        papel = "NOMINA DEL PERSONAL DOCENTE\nMES DE MARZO DE 1965"
        cita = "MES DE MARZO DE 1965"
        juez = _JuezFalso(
            {
                "fecha_inicial": VeredictoDeDato("no_esta", cita),
                "fecha_final": VeredictoDeDato("no_esta", cita),
            }
        )
        revisadas = revisar_las_fechas(
            fechas_de_un_par("01/01/1972", "31/12/1972"), [papel], regla=ANIOS, juez=juez
        )
        assert (revisadas.estado, revisadas.inicial, revisadas.final) == (
            CORREGIDA,
            date(1965, 1, 1),
            date(1965, 12, 31),
        )
        assert revisadas.nota.startswith("fecha inicial corregida: 1972 → 1965")

    @pytest.mark.parametrize(
        "juez", [_JuezFalso(None), _JuezFalso(error=RuntimeError("la IA cayó"))]
    )
    def test_una_ia_caida_o_rota_deja_la_duda_y_no_el_trabajo(self, juez):
        revisadas = revisar_las_fechas(
            _par("09/09/1999"), [CORRESPONDENCIA], regla=EXTREMOS, juez=juez
        )
        assert revisadas.estado == A_REVISION
        assert all(m.endswith("(la IA no respondió)") for m in revisadas.motivos)
        assert revisadas.preguntadas_a_la_ia == 0

    def test_cancelar_corta_al_revisor(self):
        juez = _JuezFalso(error=Cancelled())
        with pytest.raises(Cancelled):
            revisar_las_fechas(
                _par("09/09/1999"), [CORRESPONDENCIA], regla=EXTREMOS, juez=juez
            )

    def test_la_fila_a_medias_se_completa_con_el_lector(self):
        # La inicial que falta la dice la fórmula de expedición; la final ya era esa.
        revisadas = revisar_las_fechas(
            FechasDeLaFila(None, date(2005, 3, 10)), [RESOLUCION], regla=EXPEDICION
        )
        assert (revisadas.estado, revisadas.inicial, revisadas.final) == (
            CORREGIDA,
            date(2005, 3, 10),
            date(2005, 3, 10),
        )
        assert revisadas.nota.startswith("fecha inicial corregida: N/A → 10/03/2005")

    def test_la_final_anterior_a_la_inicial_es_motivo(self):
        fechas = FechasDeLaFila(date(2016, 8, 30), date(2011, 5, 4))
        revisadas = revisar_las_fechas(fechas, [CORRESPONDENCIA], regla=EXTREMOS)
        assert revisadas.estado == A_REVISION
        # Las dos puntas, cambiadas, tampoco son las de sus hojas.
        assert revisadas.motivos[-1] == "la fecha final 04/05/2011 es anterior a la inicial"


# -- 3b. la revisión adversarial del 2026-11-10 ----------------------------------------------
#
# Dos revisores alteraron fechas de actas reales y armaron papeles sintéticos:
# 7 correcciones equivocadas en actas reales y 6 en sintéticos. La regla del
# operador es «ninguna corrección equivocada»: cada caso, fijado aquí.

#: La fórmula propia ilegible, y detrás la copia de otra resolución con la suya.
_RESOLUCION_ILEGIBLE = (
    "UNIVERSIDAD DE CARTAGENA\nRESOLUCION No. 00390 DE 2025\nPor la cual ... RESUELVE ...\n"
    "Da¿a en Cart%gena, a ios d*ec#s (1~) d1/s de| m*s de en&ro\n"
)
_COPIA_DETRAS = (
    "UNIVERSIDAD DE CARTAGENA\nRESOLUCION No. 00012 DE 2024\nPor la cual se ...\n"
    "Dada en Cartagena de Indias, a los tres (3) días del mes de marzo de 2024\n"
)
#: Certificado con la firma ilegible: la última fecha es el fin del servicio.
_CERTIFICADO_ILEGIBLE = (
    "CERTIFICADO No. 083\nLA SECCION DE ARCHIVO HACE CONSTAR que el señor JUAN PEREZ C.C. 9.064.394 "
    "prestó sus servicios del 29 de Marzo de 1979 al 30 de Junio de 1985.\n"
    "Se firma en Cartagena a los ##ce (1#) d$as del m3s de jul1o de 1.985\n"
)
_CERTIFICADO_LEGIBLE = _CERTIFICADO_ILEGIBLE.replace(
    "##ce (1#) d$as del m3s de jul1o de 1.985", "doce (12) días del mes de julio de 1985"
)
#: Acta de grado con el OCR revuelto: sólo el respaldo por piezas la lee.
_GRADO_REVUELTO = (
    "ACTA DE GRADO No. 345\nEN LA CIUDAD DE CARTAGENA, 15 ( ) DIAS ... CEREMONIA ... 1987 ...\n"
    "SE CONFIRIO EL TITULO DE ENFERMERA a MARIA PEREZ ... en el mes de JULIO de mil novecientos ochenta y siete"
)
_HISTORIA_CON_NACIMIENTO = (
    "REGISTRO ACADEMICO\nAÑO 1977 ... 1978 ... 1979 ... 1980 ... 1981 ... 1982 ... 1983\nNacimiento 1958"
)
_CARTA = "Cartagena, 17/12/2012\nSeñores AFINIA\nAsunto: reclamo\nEl plazo vence el 01/02/2013.\nAtentamente"


class TestElLectorFuerteEsEstricto:
    def test_la_resolucion_no_se_corrige_con_la_formula_de_la_copia(self):
        # La fila trae la fecha de la serie; la copia de detrás dice el 03/03/2024.
        revision = contrastar_las_fechas(
            _par("20-01-2025"), [_RESOLUCION_ILEGIBLE, _COPIA_DETRAS], regla=EXPEDICION
        )
        assert revision.correcciones == ()
        assert len(revision.preguntas) == 2

    def test_la_formula_sin_el_anio_de_su_encabezado_no_es_prueba(self):
        papel = RESOLUCION.replace("No. 00123 DE 2005", "No. 00123")
        revision = contrastar_las_fechas(_par("10/08/2006"), [papel], regla=EXPEDICION)
        assert revision.correcciones == ()
        assert revision.preguntas[0].dice_el_papel == date(2005, 3, 10)

    def test_la_ia_no_corrige_una_resolucion_fuera_del_anio_de_su_encabezado(self):
        cita = "a los tres (3) días del mes de marzo de 2024"
        juez = _JuezFalso({"fecha_inicial": VeredictoDeDato("no_esta", cita)})
        revisadas = revisar_las_fechas(
            _par("20-01-2025"), [_RESOLUCION_ILEGIBLE, _COPIA_DETRAS], regla=EXPEDICION, juez=juez
        )
        assert revisadas.estado == A_REVISION

    def test_el_certificado_no_se_corrige_con_el_fin_del_servicio(self):
        for ventana in ((1985, 1985), None):
            revision = contrastar_las_fechas(
                _par("12/07/1985"), [_CERTIFICADO_ILEGIBLE], regla=FIRMA, ventana=ventana
            )
            assert revision.correcciones == ()

    def test_el_certificado_con_la_firma_legible_si_se_corrige(self):
        revision = contrastar_las_fechas(
            _par("12/08/1985"), [_CERTIFICADO_LEGIBLE], regla=FIRMA, ventana=(1985, 1985)
        )
        assert {c.dice_el_papel for c in revision.correcciones} == {date(1985, 7, 12)}

    def test_firmas_del_certificado_no_trae_el_respaldo(self):
        from resolutions.domain.nomina import (
            fechas_del_certificado,
            firmas_del_certificado,
        )

        assert firmas_del_certificado([_CERTIFICADO_ILEGIBLE]) == []
        assert fechas_del_certificado([_CERTIFICADO_ILEGIBLE]) == [(30, 6, 1985)]

    def test_el_grado_por_piezas_no_corrige(self):
        from resolutions.domain.acta_grado import (
            POR_PIEZAS,
            fecha_de_grado,
            fecha_de_grado_y_como,
        )

        # El lector dice lo mismo que siempre, y ahora también cómo lo leyó.
        assert fecha_de_grado_y_como(_GRADO_REVUELTO) == (date(1987, 7, 15), POR_PIEZAS)
        assert fecha_de_grado(_GRADO_REVUELTO) == date(1987, 7, 15)
        revision = contrastar_las_fechas(_par("23-01-1987"), [_GRADO_REVUELTO], regla=GRADO)
        assert revision.correcciones == ()
        assert revision.preguntas[0].dice_el_papel == date(1987, 7, 15)


class TestLaFechaTomadaDeOtraParte:
    def test_no_se_busca_ni_se_pregunta_ni_se_corrige(self):
        fechas = fechas_de_un_par("01/01/1985", "31/12/1985", origen="del libro")
        juez = _JuezFalso({})
        revisadas = revisar_las_fechas(
            fechas, [_CERTIFICADO_LEGIBLE], regla=FIRMA, ventana=(1985, 1985), juez=juez
        )
        # La firma dice 1985, el mismo año: se confirma; nada más se hace.
        assert revisadas.estado == CONFIRMADA
        assert juez.preguntas == []
        revisadas = revisar_las_fechas(fechas, [_CERTIFICADO_ILEGIBLE], regla=FIRMA, juez=juez)
        assert revisadas.estado == SIN_DATO
        assert juez.preguntas == []

    def test_fuera_de_la_ventana_va_a_revision_sin_la_ia(self):
        # ACOSTA BELLO: 1994-2001, del código, en un libro de 1978-1988.
        fechas = fechas_de_un_par("1994", "2001", origen="del codigo")
        juez = _JuezFalso({})
        revisadas = revisar_las_fechas(fechas, ["1994 2001"], regla=ANIOS, ventana=(1978, 1988), juez=juez)
        assert revisadas.estado == A_REVISION
        assert juez.preguntas == []

    def test_la_fila_vacia_tomada_del_libro_no_se_rellena(self):
        revision = contrastar_las_fechas(
            FechasDeLaFila(None, None, ANIO, "del libro"), [_CERTIFICADO_LEGIBLE], regla=FIRMA
        )
        assert revision.correcciones == ()

    def test_la_fila_vacia_no_se_rellena_con_el_lector_debil(self):
        revision = contrastar_las_fechas(
            FechasDeLaFila(None, None, DIA), [_CERTIFICADO_ILEGIBLE], regla=FIRMA, ventana=(1985, 1985)
        )
        assert revision.correcciones == ()

    def test_el_origen_lo_dice_la_parte_de_las_observaciones_que_habla_de_la_fecha(self):
        # Acta 019 de Odontología: «del libro» habla del folio, no de la fecha.
        fila = {
            "fecha": "13-12-2007",
            "observaciones": "el folio final no se leyó en su esquina y se dedujo de la foliación "
            "seguida del libro: revíselo en el papel; la fecha: el OCR leyó 17-11-2007 y la IA "
            "13-12-2007; se dejó lo de la IA: revíselo en el papel",
        }
        fechas = fechas_de_la_fila(fila)
        assert fechas.origen == "papel"
        assert fechas.rechazadas == (date(2007, 11, 17), date(2007, 12, 13))


class TestLasLecturasDescartadasYLasSesiones:
    def test_no_se_corrige_hacia_la_lectura_que_la_fila_ya_descarto(self):
        # ACTA No. 02 (libro 2000-2006): el papel dice 2001, la IA leyó 2004.
        papel = (
            "CONSEJO DE FACULTAD\nACTA No. 02\nFECHA: 2 DE FEBRERO DE 2001\nHORA: 07:00 HORAS\n"
            "LUGAR: DECANATURA\nSe verificó el Quórum reglamentario."
        )
        fila = {
            "fecha": "02-03-2004",
            "observaciones": "la fecha: el OCR leyó 02-02-2001 y la IA 02-02-2004; se dejó lo de la IA: revíselo en el papel",
        }
        revision = contrastar_las_fechas(fechas_de_la_fila(fila), [papel], regla=SESION)
        assert revision.correcciones == ()
        assert "sus observaciones ya descartaron" in revision.preguntas[0].duda

    def test_la_ia_tampoco_corrige_hacia_ella(self):
        papel = "Cartagena, 16 de enero de 2000\nAsunto: reclamo de la factura"
        fila = {
            "fecha_inicial": "16/02/2009",
            "fecha_final": "16/02/2009",
            "observaciones": "la fecha: el OCR leyó 16-01-2000 y la IA 16-01-2009",
        }
        cita = "Cartagena, 16 de enero de 2000"
        juez = _JuezFalso({"fecha_inicial": VeredictoDeDato("no_esta", cita)})
        revisadas = revisar_las_fechas(fechas_de_la_fila(fila), [papel], regla=EXTREMOS, juez=juez)
        assert revisadas.estado == A_REVISION

    def test_el_acta_de_dos_sesiones_se_confirma_con_la_ultima(self):
        # La 019 de Odontología: «25 Y 30 DE OCTUBRE DE 2012»; el trabajo escribe el 30.
        hojas = [
            "CONSEJO DE FACULTAD\nSESION ORDINARIA\nACTA No. 019\nFECHA: JUEVES 25 DE OCTUBRE DE 2012\n"
            "LUGAR: DECANATURA\nSe verificó el quórum.",
            "CONSEJO DE FACULTAD\nSESION ORDINARIA\nACTA No. 019\nFECHA: MARTES 30 DE OCTUBRE DE 2012\n"
            "LUGAR: DECANATURA\nContinúa la sesión.",
        ]
        revision = contrastar_las_fechas(_par("30-10-2012"), hojas, regla=SESION)
        assert revision.confirmadas == ("la fecha inicial", "la fecha final")

    def test_la_proxima_reunion_no_es_otra_sesion(self):
        papel = (
            "FACULTAD DE ODONTOLOGIA VERSION 00 FECHA 04-05-2011\nACTA ORDINARIA No. 008\n"
            "FECHA: 7 DE MAYO DE 2012\nLUGAR: DECANATURA\nPróxima reunión 21 de mayo de 2012."
        )
        revision = contrastar_las_fechas(_par("21-05-2012"), [papel], regla=SESION)
        assert revision.confirmadas == ()

    def test_un_digito_del_ocr_de_otra_fecha_escrita_no_se_corrige(self):
        # La 019 alterada al 30/10/2011: es la del 30/10/2012 de la segunda
        # sesión con un dígito del OCR, no la apertura del 25.
        papel = (
            "CONSEJO DE FACULTAD\nACTA No. 019\nFECHA: JUEVES 25 DE OCTUBRE DE 2012\nLUGAR: DECANATURA\n"
            "Se aprobó lo del 30 de octubre de 2012."
        )
        revision = contrastar_las_fechas(_par("30-10-2011"), [papel], regla=SESION)
        assert revision.correcciones == ()


class TestElLectorDebil:
    @pytest.mark.parametrize("fila", ["18/12/2012", "07/12/2012", "01/02/2013"])
    def test_la_carta_solo_con_su_propia_fecha(self, fila):
        # Otro día del mismo mes, o el plazo que cita: ya no se confirman.
        revision = contrastar_las_fechas(_par(fila), [_CARTA], regla=EXTREMOS)
        assert revision.confirmadas == ()
        assert revision.correcciones == ()
        assert revision.preguntas[0].dice_el_papel == date(2012, 12, 17)

    def test_la_carta_con_su_fecha_se_confirma(self):
        revision = contrastar_las_fechas(_par("17/12/2012"), [_CARTA], regla=EXTREMOS)
        assert revision.confirmadas == ("la fecha inicial", "la fecha final")

    def test_el_mes_y_el_anio_no_confirman_si_hay_otra_fecha_entera_de_ese_mes(self):
        papel = "NOMINA\nMES DE MARZO 1991\nFECHA 15/03/1991\nPERIODO 01/03/1991 AL 31/03/1991"
        revision = contrastar_las_fechas(_par("02/03/1991", "31/03/1991"), [papel], regla=ANIOS)
        assert revision.confirmadas == ("la fecha final",)
        assert [p.campo for p in revision.preguntas] == ["fecha_inicial"]

    @pytest.mark.parametrize(("inicial", "final"), [(1978, 1983), (1977, 1982)])
    def test_la_historia_con_ventana_pide_el_primer_y_el_ultimo_anio(self, inicial, final):
        fechas = fechas_de_la_fila({"anio_inicial": inicial, "anio_final": final})
        revision = contrastar_las_fechas(
            fechas, [_HISTORIA_CON_NACIMIENTO], regla=ANIOS, ventana=(1975, 1990)
        )
        assert len(revision.preguntas) == 1
        assert revision.correcciones == ()

    def test_la_historia_bien_con_ventana_se_confirma(self):
        fechas = fechas_de_la_fila({"anio_inicial": 1977, "anio_final": 1983})
        revision = contrastar_las_fechas(
            fechas, [_HISTORIA_CON_NACIMIENTO], regla=ANIOS, ventana=(1975, 1990)
        )
        assert revision.confirmadas == ("la fecha inicial", "la fecha final")


class TestLaIaConCitaYVentana:
    def test_una_cita_de_un_anio_suelto_no_vale(self):
        # La IA citaba «1958», el nacimiento, y corregía la historia de 1977.
        papel = "HISTORIA ACADEMICA\nINGRESO: 1.977\nNacimiento 1958"
        juez = _JuezFalso({"fecha_inicial": VeredictoDeDato("no_esta", "1958")})
        revisadas = revisar_las_fechas(
            fechas_de_la_fila({"anio_inicial": 1976, "anio_final": None}), [papel], regla=ANIOS, juez=juez
        )
        assert revisadas.estado != CORREGIDA
        assert revisadas.preguntadas_a_la_ia == 0

    @pytest.mark.parametrize(("ventana", "corrige"), [((1975, 1990), False), (None, True)])
    def test_la_ia_no_corrige_fuera_de_la_ventana(self, ventana, corrige):
        from resolutions.application.revisor_de_fechas import _con_la_ia
        from resolutions.domain.fechas_extremas import PreguntaDeFecha

        papel = "HISTORIA ACADEMICA\nALUMNO NACIDO EN EL AÑO DE 1958"
        cita = "NACIDO EN EL AÑO DE 1958"
        juez = _JuezFalso({"fecha_inicial": VeredictoDeDato("no_esta", cita)})
        fechas = fechas_de_la_fila({"anio_inicial": 1977, "anio_final": None})
        pregunta = PreguntaDeFecha("fecha_inicial", "1977", "la fecha inicial 1977 no está escrita")
        _, correcciones, _, _ = _con_la_ia(fechas, [pregunta], [papel], juez, ventana=ventana)
        assert bool(correcciones) is corrige


class TestUnaVezPorDocumento:
    def test_las_fechas_del_texto_se_leen_una_vez(self, monkeypatch):
        from resolutions.domain import fechas_extremas

        llamadas: list[int] = []
        original = fechas_extremas.fechas_del_texto

        def contada(texto, **kwargs):
            llamadas.append(1)
            return original(texto, **kwargs)

        monkeypatch.setattr(fechas_extremas, "fechas_del_texto", contada)
        fechas_extremas._escritas.cache_clear()
        fechas_extremas._anios_escritos.cache_clear()
        papel = "Cartagena, 9 de marzo de 2003\nAsunto: carta sin la fecha de la fila"
        for _ in range(3):
            revisar_las_fechas(_par("09/09/1999"), [papel], regla=EXTREMOS)
        assert len(llamadas) == 1
        fechas_extremas._escritas.cache_clear()
        fechas_extremas._anios_escritos.cache_clear()


# -- que el revisor no trabe la corrida (2026-11-10) ------------------------------------------
#
# El operador exige que el flujo nunca se trabe: ya hubo una corrida atascada por
# una regex sin fin. La revisión adversarial del revisor de fechas midió entradas
# cuyo costo crecía al cuadrado -- «dos mil » × 20 000 tardaba 318 s en un solo
# documento --. Se acota lo que les llega, sin cambiar ninguna fecha: se fija lo
# que no depende de la máquina (qué le llega a ``fechas_del_texto``, qué rótulos
# se encuentran) y el tiempo, con un tope holgado.

#: Lo que la revisión midió creciendo al cuadrado, en 200 000 caracteres: de
#: minutos a horas antes; menos de un segundo ahora.
_ADVERSARIAS = {
    "dos mil": "dos mil " * 25_000,
    "y": "y " * 100_000,
    "y con cifras": ("y " * 99 + "1 ") * 1_000,
    "12 y blancos": "12" + " " * 200_000 + "x",
    "lunes y blancos": "lunes" + " " * 200_000 + "x",
    "saltos": "a" + "\n" * 200_000 + "x",
    "siglas": "A." * 100_000,
}
#: Segundos: holgado frente a lo que tarda ahora, corto frente a lo de antes.
_TOPE = 3.0


def _segundos(funcion, *args, **kwargs) -> float:
    import time

    inicio = time.perf_counter()
    funcion(*args, **kwargs)
    return time.perf_counter() - inicio


class TestElRevisorNoTrabaLaCorrida:
    def test_el_rotulo_de_la_sesion_acaba_donde_acababa(self):
        """``^[^\\S\\n]*`` en lugar de ``^\\s*``: los mismos rótulos, sin recorrer los renglones vacíos que siguen."""
        import re

        from resolutions.domain import fechas_extremas

        viejo = re.compile(r"^\s*FECHA(?:\s+DE\s+LA\s+SESI[OÓ]N)?\s*[:;]", re.IGNORECASE | re.MULTILINE)
        papeles = [
            ACTA,
            ACTA_CON_LA_PROXIMA,
            ACTA_I3DF,
            "ACTA No. 019\nFECHA: 25 DE OCTUBRE DE 2012\n\n\n   FECHA DE LA SESIÓN ; 30 de octubre",
            "\n\n \t\n  Fecha:\n21 de febrero de 2012",
            # El \r y el espacio duro son blancos del renglón; el salto de página no abre renglón.
            "\r\nFECHA: lunes\r\n\xa0FECHA: martes\x0cFECHA: no",
            "Próxima reunión, FECHA: 6 de marzo",
        ]
        for papel in papeles:
            nuevo = [m.end() for m in fechas_extremas._ROTULO_DE_LA_SESION.finditer(papel)]
            assert nuevo == [m.end() for m in viejo.finditer(papel)], papel

    def test_los_renglones_vacios_no_traban_la_regla_de_la_sesion(self):
        """«a» + 20 000 saltos tardaba 1,9 s y crecía al cuadrado: 200 000 eran minutos."""
        revision = None

        def contrastar():
            nonlocal revision
            revision = contrastar_las_fechas(_par("17/12/2012"), [_ADVERSARIAS["saltos"]], regla=SESION)

        assert _segundos(contrastar) < _TOPE
        assert not revision.confirmadas and not revision.correcciones

    def test_a_fechas_del_texto_le_llega_el_texto_acotado(self, monkeypatch):
        """De 200 000 caracteres le llega la racha final de 24 palabras de número, o 40 blancos."""
        from resolutions.domain import fechas_extremas

        largos: list[int] = []
        original = fechas_extremas.fechas_del_texto

        def medida(texto, **kwargs):
            largos.append(len(texto))
            return original(texto, **kwargs)

        monkeypatch.setattr(fechas_extremas, "fechas_del_texto", medida)
        for nombre in ("dos mil", "y", "12 y blancos", "lunes y blancos"):
            assert fechas_extremas.fechas_escritas(_ADVERSARIAS[nombre]) == set()
        assert len(largos) == 4 and max(largos) < 200

    @pytest.mark.parametrize(
        "papel",
        [
            # Cruza el salto de renglón: leer por renglones la perdía (157 fechas en 66 de 260 documentos reales).
            "a los diecisiete (17) días del mes de diciembre\nde dos mil doce (2012) se reunió el Consejo",
            # La racha larga sigue juntándose con su cifra: quedan sus últimas palabras.
            "Cartagena, 17 de diciembre de " + "y " * 30 + "dos mil doce (2012)",
            # Los blancos de más, dentro de la fecha.
            "Fecha: 17" + " \n" * 3_000 + "de diciembre de 2012",
            "lunes" + " " * 500 + "17 de diciembre de 2012 y diciembre 18 de 2012, 19/12/2012",
            "VEINTITRÉS (23) DE JUNIO DE DOS MIL CUATRO (2004)",
        ],
    )
    def test_acotar_no_cambia_ninguna_fecha(self, papel):
        from resolutions.domain.acta_consejo import fechas_del_texto
        from resolutions.domain.fechas_extremas import fechas_escritas

        assert fechas_escritas(papel) == fechas_del_texto(papel) != set()

    def test_la_hoja_con_siglas_sin_fin_se_lee_sin_ellas(self, monkeypatch):
        """«A.» × 10 000 tardaba 3,4 s en ``fecha_de_la_pagina``: la racha se lee con sus puntos como espacios."""
        from resolutions.domain import fechas
        from resolutions.domain.fechas_extremas import fecha_propia_de_la_hoja

        # La hoja real llega como está, y dice lo mismo.
        assert fecha_propia_de_la_hoja(CORRESPONDENCIA) == fechas.fecha_de_la_pagina(CORRESPONDENCIA)
        # Con una racha de siglas delante, el encabezado de la carta sigue ahí.
        con_siglas = "A." * 2_000 + "\nCartagena, 21 de diciembre de 2021\nSeñores ELECTRICARIBE"
        assert fecha_propia_de_la_hoja(con_siglas) == fechas.fecha_de_la_pagina(con_siglas) == date(2021, 12, 21)
        leidas: list[str] = []
        original = fechas.fecha_de_la_pagina
        monkeypatch.setattr(fechas, "fecha_de_la_pagina", lambda texto, **k: leidas.append(texto) or original(texto, **k))
        fecha_propia_de_la_hoja(CORRESPONDENCIA)
        fecha_propia_de_la_hoja(_ADVERSARIAS["siglas"])
        assert leidas[0] == CORRESPONDENCIA
        assert "A.A" not in leidas[1] and len(leidas[1]) == len(_ADVERSARIAS["siglas"])

    @pytest.mark.parametrize("nombre", list(_ADVERSARIAS))
    def test_una_entrada_adversaria_de_200_000_caracteres_termina(self, nombre):
        from resolutions.domain import fechas_extremas

        papel = _ADVERSARIAS[nombre]
        assert _segundos(fechas_extremas.fechas_escritas, papel) < _TOPE
        assert _segundos(fechas_extremas.fecha_propia_de_la_hoja, papel) < _TOPE
        fechas_extremas._escritas.cache_clear()
        fechas_extremas._anios_escritos.cache_clear()
        fechas_extremas._fechas_propias.cache_clear()
        assert _segundos(contrastar_las_fechas, _par("17/12/2012", "18/12/2012"), [papel], regla=EXTREMOS) < _TOPE


# -- 4. el informe ---------------------------------------------------------------------------


class TestElInforme:
    def test_la_misma_forma_en_todas_las_habilidades(self):
        report: dict = {}
        anotar_en_el_informe(
            report,
            "01_ACTA.pdf",
            3,
            revisar_las_fechas(_par("21-02-2012"), [ACTA], regla=SESION),
        )
        anotar_en_el_informe(
            report,
            "02_RESOLUCION.pdf",
            7,
            revisar_las_fechas(_par("10/08/2006"), [RESOLUCION], regla=EXPEDICION),
        )
        anotar_en_el_informe(
            report,
            "03_RECLAMO.pdf",
            None,
            revisar_las_fechas(_par("09/09/1999"), [CORRESPONDENCIA], regla=EXTREMOS),
        )
        anotar_en_el_informe(
            report, "04_FOTO.pdf", 9, revisar_las_fechas(None, [], regla=EXTREMOS)
        )
        resumen = report[CLAVE_DEL_INFORME]
        assert {k: v for k, v in resumen.items() if k != "detalle"} == {
            "revisados": 4,
            CONFIRMADA: 1,
            CORREGIDA: 1,
            A_REVISION: 1,
            SIN_DATO: 1,
            "preguntadas_a_la_ia": 0,
        }
        assert [d["documento"] for d in resumen["detalle"]] == [
            "02_RESOLUCION.pdf",
            "03_RECLAMO.pdf",
        ]
        assert report["notices"] == [
            "Fecha corregida en 02_RESOLUCION.pdf: " + resumen["detalle"][0]["nota"]
        ]
        # Lo que va a Revisión, con su página; sin página, la primera.
        assert report["review_queue"] == [
            {
                "page": 1,
                "reason": "revisor de fechas, 03_RECLAMO.pdf: "
                + resumen["detalle"][1]["nota"],
            }
        ]

    def test_suma_lo_que_contesto_la_ia(self):
        report: dict = {}
        revisadas = FechasRevisadas(
            CONFIRMADA, date(2012, 2, 21), date(2012, 2, 21), DIA, preguntadas_a_la_ia=2
        )
        anotar_en_el_informe(report, "a.pdf", 1, revisadas)
        anotar_en_el_informe(report, "b.pdf", 1, revisadas)
        assert report[CLAVE_DEL_INFORME]["preguntadas_a_la_ia"] == 4
        assert "review_queue" not in report and "notices" not in report

    def test_respeta_lo_que_el_informe_ya_traia(self):
        report = {
            "review_queue": [{"page": 2, "reason": "otra cosa"}],
            "notices": ["antes"],
        }
        anotar_en_el_informe(
            report,
            "x.pdf",
            5,
            revisar_las_fechas(_par("09/09/1999"), [CORRESPONDENCIA], regla=EXTREMOS),
        )
        assert report["review_queue"][0] == {"page": 2, "reason": "otra cosa"}
        assert report["review_queue"][1]["page"] == 5
        assert report["notices"] == ["antes"]


# -- todas las habilidades -------------------------------------------------------------------

#: Un documento sintético por regla, con la fila que lo describe bien y una que
#: lo describe mal sin que el papel diga otra cosa.
class TestLaCajaDeCorrespondenciaPorSuEstructura:
    """La caja de correspondencia se contrasta con la fecha de su hoja principal (2026-11-11).

    Con el lector de las puntas, la auditoría de «pruebas afinia» dudó de tres
    fechas bien puestas: la «fecha propia» de cada hoja caía en las trampas que
    el bot ya deja fuera al fechar (``fecha_por_estructura``). Capa real de cada caso.
    """

    #: 1000186, «03_PAGARE.pdf»: la liquidación de la carta de instrucciones
    #: trae la «Fecha Vto.»; la firma, el día del documento.
    LIQUIDACION = (
        "CARIBEMAR DE LA COSTA S.A.S. ESP EMPRESA DE SERVICIOS PUBLICOS DOMICILIARIOS NitSOI .380.949-1 CARTA DE "
        "INSTRUCCIONES ANEXA A PAGARE No. 1000186 1 CON ESPACIOS ABIERTOS , identificado como aparece al ... "
        "Tipo de servicio Energía regulada 255.766,00 Símbolo Variable NIR Fecha Vto, Importe $255.766,00 "
        "13/04/2021 1000186007 1.107261-06/04/2021 $255.766,00 Importe total:"
    )
    FIRMA_DE_LA_CARTA = (
        "f CARIBEMAR DE LA COSTA S.A.S. ESP EMPRESA DE SERVICIOS PUBLICOS DOMICILIARIOS Nit901.380.949-1 í, f H "
        "CARTA DE INSTRUCCIONES ANEXA A PAGARE No. 1000186 1 CON E ... Dejo constancia que en mi poder ha quedado "
        "una copia del presente documento. del 2021 MAGANGUE a los 6 días del mes de Abril Firmado en la ciudad de FIRMA:"
    )
    #: 1000224: «FECHA:» de la constancia y el plazo «a más tardar» de su notificación.
    CONSTANCIA = (
        "PARA LA EMPRESA Recibí constancia del contenido de la reclamación presentada ante CARIBEMAR DE LA COSTA "
        "S.A.S. ESP MESES POR LO QUE RECLAMA: N»PQR: RE2320202101914 FECHA: 03/05/2021 INSTALACIÓN: CR 1 CR26 117 "
        "CAUSA: Facturación no ditribuida SERVICIO: 10812 ^ ^ Apr de 2021 de AMPIM NOTIFICACIÓN: La decisión de estp "
        "requerimiento, le será notificada a más íardar el 25/05/2021 11:59:59 PM"
    )
    #: 1000690, «05_PUBLICACION-DEL-AVISO.pdf»: el día en que se publica, y la
    #: lectura del medidor de la respuesta que va dentro.
    AVISO = (
        "aFinia Grupo-ep«) Consecutivo No. PA 202170188518 Cartagena, 30-06-2021 Consecutivo NO.A202170174520 "
        "PUBLICACIÓN DEL AVISO Señor(a) AZAÚ BELEÑO CARRERA 3 CALLE 19 - 67 APARTAMENTO 01 LA CANDELARIA MAGANGUE "
        "BOLIVAR a) El usuario AZAÚ BELEÑO reportó como dirección de Teniendo en cuenta que: notificación para la "
        "respuesta a la petición presentada el día 16/06/2021 16:40:44, ... El presente aviso se publica el día "
        "13/07/2021 10:32:03.0 y hasta por"
    )
    LECTURA_DEL_MEDIDOR = (
        "Consumo: lectura mes de junio del 2021 (lectura 1226 (01/06/2021) - lectura 01/06/2021 (03/05/2021) = 259 Kws"
    )

    @pytest.mark.parametrize(
        ("hojas", "fecha"),
        [
            ((LIQUIDACION, FIRMA_DE_LA_CARTA), "06/04/2021"),
            ((CONSTANCIA,), "03/05/2021"),
            ((AVISO, LECTURA_DEL_MEDIDOR), "13/07/2021"),
        ],
        ids=["pagare", "constancia", "publicacion"],
    )
    def test_la_fecha_de_su_hoja_principal_se_confirma(self, hojas, fecha):
        assert contrastar_las_fechas(_par(fecha, fecha), list(hojas), regla=ESTRUCTURA).confirmadas
        # Con el lector de las puntas, las tres quedaban en duda.
        assert contrastar_las_fechas(_par(fecha, fecha), list(hojas), regla=EXTREMOS).preguntas

    @pytest.mark.parametrize(
        ("hojas", "trampa"),
        [
            ((LIQUIDACION, FIRMA_DE_LA_CARTA), "13/04/2021"),
            ((CONSTANCIA,), "25/05/2021"),
            ((AVISO, LECTURA_DEL_MEDIDOR), "01/06/2021"),
        ],
        ids=["vencimiento", "a-mas-tardar", "lectura-del-medidor"],
    )
    def test_la_fecha_de_una_trampa_no_se_confirma(self, hojas, trampa):
        revision = contrastar_las_fechas(_par(trampa, trampa), list(hojas), regla=ESTRUCTURA)
        assert not revision.confirmadas and not revision.correcciones
        assert "la fecha de su hoja principal dice" in revision.preguntas[0].duda

    def test_la_fecha_del_sello_que_se_sumo_al_papel_se_confirma(self):
        hojas = [self.CONSTANCIA, "SELLO DE RADICACION: 04/05/2021"]
        assert contrastar_las_fechas(_par("04/05/2021", "04/05/2021"), hojas, regla=ESTRUCTURA).confirmadas

    def test_el_lector_es_debil_nunca_corrige(self):
        revision = contrastar_las_fechas(_par("10/05/2021", "10/05/2021"), [self.CONSTANCIA], regla=ESTRUCTURA)
        assert revision.correcciones == () and revision.preguntas

    def test_la_caja_de_correspondencia_usa_esta_regla(self):
        assert perfil_de("Caja de correspondencia").regla_de_fechas == ESTRUCTURA


_DE_CADA_REGLA = {
    ESTRUCTURA: (
        TestLaCajaDeCorrespondenciaPorSuEstructura.CONSTANCIA,
        {"fecha_inicial": "03/05/2021", "fecha_final": "03/05/2021"},
    ),
    SESION: (ACTA, {"fecha": "21-02-2012"}),
    GRADO: (GRADO_TEXTO, {"fecha": "15-06-2001"}),
    EXPEDICION: (
        RESOLUCION,
        {"fecha_inicial": "10/03/2005", "fecha_final": "10/03/2005"},
    ),
    FIRMA: (CERTIFICADO, {"fecha_inicial": "20/01/1993", "fecha_final": "20/01/1993"}),
    ANIOS: (HISTORIA, {"anio_inicial": 1977, "anio_final": 1983}),
    EXTREMOS: (
        CORRESPONDENCIA,
        {"fuid": {"fecha_inicial": "04-05-2011", "fecha_final": "30-08-2016"}},
    ),
}


class TestTodasLasHabilidades:
    def test_cada_regla_tiene_su_documento_en_esta_suite(self):
        assert set(_DE_CADA_REGLA) == set(REGLAS)

    @pytest.mark.parametrize("perfil", PERFILES, ids=lambda p: p.clave)
    def test_cada_habilidad_declara_una_regla_que_existe(self, perfil):
        assert perfil.regla_de_fechas in REGLAS

    def test_una_habilidad_desconocida_cae_en_los_extremos(self):
        assert perfil_de("algo que no existe").regla_de_fechas == EXTREMOS

    @pytest.mark.parametrize("perfil", PERFILES, ids=lambda p: p.clave)
    def test_cada_habilidad_confirma_su_documento(self, perfil):
        texto, fila = _DE_CADA_REGLA[perfil.regla_de_fechas]
        revisadas = revisar_las_fechas(
            fechas_de_la_fila(fila), [texto], regla=perfil.regla_de_fechas
        )
        assert revisadas.estado == CONFIRMADA, revisadas.motivos

    @pytest.mark.parametrize("regla", REGLAS)
    def test_cada_regla_nunca_confirma_lo_que_el_papel_no_dice(self, regla):
        # Una fecha que no aparece en el papel: la corrige el lector de su regla
        # con dos pruebas, o va a revisión; confirmada, nunca.
        texto, _ = _DE_CADA_REGLA[regla]
        fechas = (
            fechas_de_un_par("1960", "1961")
            if regla == ANIOS
            else _par("05/07/1960", "06/07/1960")
        )
        revisadas = revisar_las_fechas(fechas, [texto], regla=regla)
        assert revisadas.estado == (
            CORREGIDA if regla in (SESION, GRADO, EXPEDICION, FIRMA) else A_REVISION
        )
