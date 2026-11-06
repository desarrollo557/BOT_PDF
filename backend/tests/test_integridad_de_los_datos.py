"""Los dos agentes también en los datos de cada documento: empezando por las historias académicas.

El operador, 2026-11-06, antes de procesar Enfermería por segunda vez: que los
agentes «se aseguren de que lo que esperemos sea íntegro» -- el nombre, la
cédula o la tarjeta o la libreta militar, el código, y «muy bien las fechas
extremas, inicial y final de cada historia académica» --, «y que los documentos
cumplan su margen de error». Esto fija:

- la regla de una historia (``domain/datos_esperados.py``): qué es error y qué
  es duda en cada campo;
- el agente al procesar (``revisar_los_datos``): las cuentas por documento y
  por campo, y que la portada y las hojas sueltas no se juzgan como historias;
- la auditoría (``auditar_los_datos``): cada PDF entregado contra su fila del
  FUID entregado, encontrada por su identificación o por su nombre;
- que el agente de la corrida lo suma en vivo.
"""

from __future__ import annotations

import pytest

from resolutions.application.auditoria_de_la_entrega import auditar_un_pdf
from resolutions.application.fuid import FuidRow
from resolutions.application.integridad_de_los_datos import (
    DE_UNA_HISTORIA,
    auditar_los_datos,
    historia_de_la_fila,
    historia_del_fuid,
    revisar_los_datos,
)
from resolutions.application.revisor_de_cortes import (
    AgenteDeLaCorrida,
    anotar_en_el_informe,
)
from resolutions.domain.auditoria import BIEN, DUDOSO, ERROR
from resolutions.domain.conciliacion import Huella
from resolutions.domain.datos_esperados import (
    DUDA,
    DatosDeUnaHistoria,
    anio_del_codigo,
    revisar_una_historia,
)
from resolutions.domain.datos_esperados import ERROR as ES_ERROR


def _historia(**cambios) -> DatosDeUnaHistoria:
    datos = {
        "nombre": "AGUAS GARRIDO CLARENA LUCIA",
        "identificacion": "45755189",
        "tipo_de_identificacion": "cédula",
        "codigo": "549310044",
        "anio_inicial": 1993,
        "anio_final": 1996,
    }
    return DatosDeUnaHistoria(**{**datos, **cambios})


def _que(datos: DatosDeUnaHistoria) -> list[tuple[str, str]]:
    return [(h.campo, h.gravedad) for h in revisar_una_historia(datos, este_anio=2026)]


class TestUnaHistoria:
    def test_completa_no_tiene_hallazgos(self):
        assert _que(_historia()) == []

    @pytest.mark.parametrize(
        ("cambios", "esperado"),
        [
            ({"nombre": None}, [("nombre", ES_ERROR)]),
            ({"nombre": "PEREZ 45755189 LUIS"}, [("nombre", ES_ERROR)]),
            ({"nombre": "NOMBRE DEL ESTUDIANTE PEREZ"}, [("nombre", ES_ERROR)]),
            ({"nombre": "PEREZ"}, [("nombre", DUDA)]),
        ],
    )
    def test_el_nombre(self, cambios, esperado):
        assert _que(_historia(**cambios)) == esperado

    def test_sin_identificacion_es_para_mirar_y_no_un_error(self):
        """Los posgrados y las fichas viejas pueden no traerla: se mira en el papel."""
        assert _que(_historia(identificacion=None, tipo_de_identificacion=None)) == [("identificacion", DUDA)]

    @pytest.mark.parametrize(
        ("numero", "tipo", "esperado"),
        [
            ("549310006", "cédula", [("identificacion", ES_ERROR)]),  # nueve cifras: el código, no una cédula
            ("1047382991", "cédula", []),
            ("61120803173", "tarjeta de identidad", []),
            ("66263", "tarjeta de identidad", []),  # «TI 66263 en trámite»
            ("7341226", "libreta militar", []),
            ("123", None, [("identificacion", ES_ERROR)]),
        ],
    )
    def test_la_cedula_la_tarjeta_o_la_libreta(self, numero, tipo, esperado):
        assert _que(_historia(identificacion=numero, tipo_de_identificacion=tipo)) == esperado

    def test_el_codigo(self):
        assert _que(_historia(codigo=None)) == [("codigo", DUDA)]
        assert _que(_historia(codigo="1234")) == [("codigo", ES_ERROR)]
        assert _que(_historia(codigo="45755189")) == [("codigo", ES_ERROR)]  # el mismo número que la cédula
        # «549110044» dice ingreso en 1991, y la fecha inicial es 1993: lo que
        # se mira es la fecha, que sale de las notas (Enfermería, 2026-11-06).
        assert _que(_historia(codigo="549110044")) == [("fechas", DUDA)]
        assert _que(_historia(codigo="549210044")) == []  # un año de diferencia vale

    @pytest.mark.parametrize(
        "nombre",
        ["ALMANZA AVILA VIANJT SOFIA", "ESPRIELLA MELENDEZ LILIANA RDSA II", "MIER SAYAS ANGELA MARIA EM", "BALLESTAS LAGARE Z DANY LUZ"],
    )
    def test_las_palabras_que_no_son_de_un_nombre(self, nombre):
        """Las que dejó la OCR en Enfermería con «Solo OCR»: para mirar, no error."""
        assert _que(_historia(nombre=nombre)) == [("nombre", DUDA)]

    @pytest.mark.parametrize(
        "nombre",
        ["JHON JAIRO PEREZ", "CONDE DIAZ ALIX STELLA", "MA DEL CARMEN DE LA ROSA", "ESPRIELLA MAESTRE BENEDETTI"],
    )
    def test_los_nombres_de_verdad_no_se_tocan(self, nombre):
        assert _que(_historia(nombre=nombre)) == []

    def test_el_anio_del_codigo(self):
        assert anio_del_codigo("549310044") == 1993
        assert anio_del_codigo("5420020056") == 2002
        assert anio_del_codigo("840222") == 1984
        assert anio_del_codigo("12345678") is None

    def test_las_fechas_extremas(self):
        """Ninguna fila sin fecha, y en su orden."""
        assert _que(_historia(anio_inicial=None)) == [("fechas", ES_ERROR)]
        assert _que(_historia(anio_inicial=None, anio_final=None)) == [("fechas", ES_ERROR)]
        assert _que(_historia(anio_inicial=1997, anio_final=1996, codigo="549710044")) == [("fechas", ES_ERROR)]
        assert _que(_historia(anio_final=2031)) == [("fechas", ES_ERROR)]
        assert _que(_historia(anio_inicial=1980, anio_final=1996, codigo="548010044")) == [("fechas", DUDA)]

    def test_el_pdf_se_llama_como_su_fila(self):
        assert _que(_historia(archivo="04_AGUAS-GARRIDO-CLARENA-LUCIA-45755189.pdf")) == []
        # Recortado para caber en la ruta: vale si empieza como la fila.
        assert _que(_historia(archivo="04_AGUAS-GARRIDO-CLAR-45755189.pdf")) == []
        assert _que(_historia(archivo="04_AGUAS-GARRIDO-CLARENA-LUCIA.pdf")) == [("archivo", ES_ERROR)]
        assert _que(_historia(archivo="04_PEREZ-GOMEZ-LUIS-45755189.pdf")) == [("archivo", ES_ERROR)]

    def test_una_hoja_suelta_no_trae_cedula_ni_codigo(self):
        hoja = _historia(identificacion=None, codigo=None, hoja_suelta=True, anio_inicial=1992, anio_final=1992)
        assert _que(hoja) == []


def _fila(**cambios) -> dict:
    datos = {
        "tipo": "HISTORIA ACADEMICA",
        "nombre": "AGUAS GARRIDO CLARENA LUCIA",
        "cedula": "45755189",
        "tarjeta": None,
        "libreta": None,
        "codigo": "549310044",
        "anio_inicial": 1993,
        "anio_final": 1996,
        "pagina_inicial": 3,
        "pagina_final": 6,
        "archivo": "UPD3859753.pdf",
        "archivo_generado": "02_AGUAS-GARRIDO-CLARENA-LUCIA-45755189.pdf",
    }
    return {**datos, **cambios}


class TestAlProcesar:
    def test_las_cuentas_por_documento_y_por_campo(self):
        filas = [
            {"tipo": "SIN ESTUDIANTE", "pagina_inicial": 1, "pagina_final": 2},
            _fila(),
            _fila(
                nombre="PEREZ GOMEZ LUIS", cedula=None, tarjeta="650409-01935", codigo="549310045",
                archivo_generado="03_PEREZ-GOMEZ-LUIS-65040901935.pdf",
            ),
            _fila(nombre="RUIZ DIAZ ANA", cedula=None, codigo=None, archivo_generado="04_RUIZ-DIAZ-ANA.pdf", pagina_inicial=9),
            _fila(
                nombre="LOPEZ MARIA", cedula="45755190", codigo="549310046", anio_final=None,
                archivo_generado="05_LOPEZ-MARIA-45755190.pdf", pagina_inicial=12,
            ),
        ]
        integridad = revisar_los_datos(filas, DE_UNA_HISTORIA)
        assert (integridad.documentos, integridad.completos, integridad.con_dudas, integridad.con_errores) == (4, 2, 1, 1)
        assert integridad.estado == "con errores"
        assert integridad.por_campo["identificacion"] == {"bien": 3, "dudas": 1, "errores": 0, "en_blanco": 0}
        assert integridad.por_campo["fechas"] == {"bien": 3, "dudas": 0, "errores": 1, "en_blanco": 0}
        sin_fecha = next(h for h in integridad.hallazgos if h["campo"] == "fechas")
        assert (sin_fecha["documento"], sin_fecha["pagina"]) == ("05_LOPEZ-MARIA-45755190.pdf", 12)
        assert integridad.as_dict()["margen"]["revisados"] == 4

    def test_la_libreta_identifica_si_no_hay_cedula_ni_tarjeta(self):
        datos = historia_de_la_fila(_fila(cedula=None, libreta="7341226", archivo_generado="02_AGUAS-GARRIDO-CLARENA-LUCIA-7341226.pdf"))
        assert (datos.identificacion, datos.tipo_de_identificacion) == ("7341226", "libreta militar")
        assert revisar_una_historia(datos, este_anio=2026) == []

    def test_va_al_informe_y_a_la_cola_de_revision(self):
        informe: dict = {"review_queue": []}
        integridad = revisar_los_datos([_fila(anio_inicial=None)], DE_UNA_HISTORIA)
        anotar_en_el_informe(informe, None, None, None, integridad=integridad)
        assert informe["integridad_de_los_datos"]["con_errores"] == 1
        assert informe["review_queue"][0]["page"] == 3
        assert "sin fecha inicial" in informe["review_queue"][0]["reason"]
        assert any("Datos de cada documento" in aviso for aviso in informe["notices"])

    def test_el_agente_de_la_corrida_lo_suma(self):
        agente = AgenteDeLaCorrida()
        for filas in ([_fila()], [_fila(), _fila(anio_final=None, archivo_generado="03_X.pdf")]):
            informe: dict = {}
            anotar_en_el_informe(informe, None, None, None, integridad=revisar_los_datos(filas, DE_UNA_HISTORIA))
            agente.sumar("caja/UPD.pdf", informe)
        datos = agente.as_dict()["datos"]
        assert (datos["documentos"], datos["completos"], datos["con_errores"]) == (3, 2, 1)
        assert datos["por_campo"]["fechas"] == {"bien": 2, "dudas": 0, "errores": 1, "en_blanco": 0}
        assert agente.as_dict()["sucesos"][0]["estado"] == "datos"


def _del_fuid(asunto, inicial="45755189", final="549310044", desde="01/01/1993", hasta="31/12/1996") -> FuidRow:
    return FuidRow(
        orden=1, asunto=asunto, consecutivo_inicial=inicial, consecutivo_final=final, fecha_inicial=desde, fecha_final=hasta
    )


class TestAlAuditar:
    FUID = [
        _del_fuid("AGUAS GARRIDO CLARENA LUCIA"),
        _del_fuid("PEREZ GOMEZ LUIS", inicial="N/A", final="N/A"),
        _del_fuid("RUIZ DIAZ ANA", inicial="1047382991", final="5420020056", desde="01/01/2002", hasta="N/A"),
    ]

    def test_cada_pdf_con_su_fila(self):
        errores, dudas = auditar_los_datos(
            [
                "UPD/01_SIN-FICHA-DE-ESTUDIANTE.pdf",
                "UPD/02_AGUAS-GARRIDO-CLARENA-LUCIA-45755189.pdf",
                "UPD/03_PEREZ-GOMEZ-LUIS.pdf",
                "UPD/04_RUIZ-DIAZ-ANA-1047382991.pdf",
            ],
            self.FUID,
            DE_UNA_HISTORIA,
        )
        assert errores == ["«04_RUIZ-DIAZ-ANA-1047382991.pdf»: sin fecha final"]
        assert sorted(dudas) == [
            "«03_PEREZ-GOMEZ-LUIS.pdf»: no se leyó el código del estudiante",
            "«03_PEREZ-GOMEZ-LUIS.pdf»: sin cédula, tarjeta de identidad ni libreta militar: revisar en el papel",
        ]

    def test_el_pdf_sin_nombre_es_la_fila_sin_nombre(self):
        """Enfermería con «Solo OCR» (2026-11-06): «01_PAGINAS-1-6.pdf» salía «sin fila»;
        su fila es la «N/A» del FUID, y lo que hay que decir es que falta el nombre."""
        fuid = [_del_fuid("N/A", inicial="N/A", final="N/A", desde="01/01/2000", hasta="31/12/2001")]
        errores, _ = auditar_los_datos(["UPD/01_PAGINAS-1-6.pdf"], fuid, DE_UNA_HISTORIA)
        assert errores == ["«01_PAGINAS-1-6.pdf»: no se leyó el nombre del estudiante"]
        # Con su cédula, por la cédula.
        fuid = [_del_fuid("N/A", inicial="33217278")]
        errores, _ = auditar_los_datos(["UPD/03_PAGINAS-5-6-33217278.pdf"], fuid, DE_UNA_HISTORIA)
        assert errores == ["«03_PAGINAS-5-6-33217278.pdf»: no se leyó el nombre del estudiante"]

    def test_el_pdf_sin_fila_es_un_error(self):
        errores, _ = auditar_los_datos(["UPD/05_OTRA-PERSONA-99887766.pdf"], self.FUID, DE_UNA_HISTORIA)
        assert errores == ["«05_OTRA-PERSONA-99887766.pdf» no tiene su fila en el FUID (ni por su identificación ni por su nombre)"]

    def test_sin_fuid_no_hay_con_que_comprobar(self):
        errores, _ = auditar_los_datos(["UPD/02_AGUAS-GARRIDO-CLARENA-LUCIA-45755189.pdf"], None, DE_UNA_HISTORIA)
        assert errores == ["su carpeta no tiene FUID con que comprobar los datos"]

    def test_un_fuid_de_antes_con_el_tipo_en_el_asunto_tambien_vale(self):
        datos = historia_del_fuid(_del_fuid("AGUAS GARRIDO CLARENA LUCIA - HISTORIA ACADEMICA"))
        assert (datos.nombre, datos.hoja_suelta) == ("AGUAS GARRIDO CLARENA LUCIA", False)
        hoja = historia_del_fuid(_del_fuid("AGUAS GARRIDO CLARENA LUCIA - RECIBO DE CAJA", inicial="N/A", final="N/A"))
        assert hoja.hoja_suelta is True

    def test_la_muestra_cuenta_los_datos(self):
        """En la auditoría de cierre, un PDF de historias con un dato imposible sale con error."""
        huellas = [Huella(texto=f"hoja {n} de la historia") for n in range(1, 3)]
        entregado = {"UPD/01_RUIZ-DIAZ-ANA-1047382991.pdf": huellas}
        textos = {1: "ficha", 2: "notas"}
        malo = auditar_un_pdf(
            "caja/UPD.pdf", huellas, textos, entregado, habilidad="Historias académicas", filas_del_fuid=self.FUID
        )
        assert malo.estado == ERROR and "sin fecha final" in malo.hallazgos[0]
        bien = auditar_un_pdf(
            "caja/UPD.pdf",
            huellas,
            textos,
            {"UPD/01_AGUAS-GARRIDO-CLARENA-LUCIA-45755189.pdf": huellas},
            habilidad="Historias académicas",
            filas_del_fuid=self.FUID,
        )
        assert bien.estado == BIEN
        # Otra habilidad no revisa datos.
        otra = auditar_un_pdf("caja/UPD.pdf", huellas, textos, entregado, habilidad="Kingspan")
        assert otra.estado == BIEN
        # Sin cédula ni código es para mirar, no un error.
        dudoso = auditar_un_pdf(
            "caja/UPD.pdf", huellas, textos, {"UPD/01_PEREZ-GOMEZ-LUIS.pdf": huellas},
            habilidad="Historias académicas", filas_del_fuid=self.FUID,
        )
        assert dudoso.estado == DUDOSO
