"""El revisor de fechas en resoluciones, diplomas, matrículas, correspondencia y Kingspan (2026-11-10).

Lo pidió el operador: «estar muy seguro de cada fecha en cada documento, sin
importar la habilidad», corrigiendo sólo con prueba y con un margen de error.
Aquí se fija cómo lo usa cada ruta que parte -- con la regla de su perfil,
sobre lo ya leído, con el formato de su fila -- y que un fallo del revisor no
tumba el trabajo.
"""

from __future__ import annotations

from datetime import date

import pytest

from resolutions.api.worker import fechas_aseguradas
from resolutions.api.worker.correspondencia import (
    _asegurar_las_fechas as asegurar_la_caja,
)
from resolutions.api.worker.fechas_aseguradas import (
    asegurar_las_filas_del_fuid,
    con_lo_que_leyeron,
    escrita_en_el_fuid,
    pasar_al_informe,
    regla_de,
    revisar_y_anotar,
)
from resolutions.api.worker.kingspan import _asegurar_las_fechas as asegurar_la_upd
from resolutions.application.control import Cancelled
from resolutions.application.fuid import FuidRow
from resolutions.application.ports import VeredictoDeDato
from resolutions.application.revisor_de_fechas import CLAVE_DEL_INFORME
from resolutions.domain.fechas_extremas import (
    ANIO,
    ANIOS,
    DIA,
    EXPEDICION,
    EXTREMOS,
    fechas_de_un_par,
)
from resolutions.domain.grouping import PageGroup
from resolutions.domain.kingspan import Documento, FilaKingspan
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.sello import Sello

DADA = (
    "RESOLUCION No 030 DE 2025\nPOR MEDIO DE LA CUAL SE CONFORMA EL COMITE\nRESUELVE: ARTICULO PRIMERO...\n"
    "Dada en Cartagena de Indias, a los dieciséis (16) días del mes de enero del año 2025\nEL RECTOR"
)


#: El anexo de la resolución: una hoja con su capa entera, como la que la
#: lectura toma sin pasarla por OCR (desde 80 caracteres).
ANEXO = (
    "ANEXO No. 1\nLISTADO DE LOS MIEMBROS DEL COMITE CONFORMADO POR LA PRESENTE RESOLUCION, "
    "CON SUS CARGOS Y DEPENDENCIAS"
)


class _Taller:
    """Lo único del taller que usa el revisor: su IA, o ninguna."""

    def __init__(self, juez=None):
        self._juez = juez

    def juez_de_datos(self):
        return self._juez


class _Juez:
    """Una IA de prueba: contesta lo que se le diga y cuenta las preguntas."""

    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.preguntas = 0

    def verificar(self, texto, datos):
        self.preguntas += 1
        return self.respuesta


def _grupo(codigo: str, paginas: list[int]) -> PageGroup:
    return PageGroup(code=ResolutionCode(value=codigo, raw=codigo), page_numbers=paginas)


def _fila(fecha: str, pagina: int = 1, folios: int = 1, final: str | None = None) -> FuidRow:
    return FuidRow(
        orden=1,
        asunto="RESOLUCION 030-2025",
        fecha_inicial=fecha,
        fecha_final=final or fecha,
        folios=folios,
        pagina_inicial=pagina,
    )


# -- lo que comparten todas las rutas ----------------------------------------------------------


class TestLoQueComparten:
    def test_la_regla_es_la_del_perfil_de_cada_habilidad(self):
        assert regla_de("resoluciones", EXTREMOS) == EXPEDICION
        assert regla_de("matriculas", EXTREMOS) == ANIOS
        assert regla_de("diplomas", ANIOS) == EXTREMOS
        assert regla_de("kingspan", ANIOS) == EXTREMOS
        assert regla_de("correspondencia", ANIOS) == EXTREMOS

    def test_una_fecha_al_reves_se_dice_como_la_entiende_el_contraste(self):
        # Kingspan fecha «2023/10/14»: la misma fecha del mismo papel, escrita
        # entera, para que no vaya a Revisión sólo por cómo está escrita.
        assert "14/10/2023" in con_lo_que_leyeron("Número DSS 1064\nFecha 2023/10/14")

    def test_las_casillas_de_un_formulario_tambien(self):
        assert "03/05/2021" in con_lo_que_leyeron("COMPROBANTE\nDIA MES AÑO\n3 5 2021\nVALOR")

    def test_una_hoja_sin_fechas_queda_igual(self):
        assert con_lo_que_leyeron("ANEXO SIN FECHA") == "ANEXO SIN FECHA"
        assert con_lo_que_leyeron("") == ""

    def test_la_celda_del_fuid_lleva_su_formato(self):
        assert escrita_en_el_fuid(date(2025, 1, 16), DIA) == "16-01-2025"
        assert escrita_en_el_fuid(date(1950, 1, 1), ANIO) == "1950"

    def test_un_fallo_del_revisor_no_tumba_el_trabajo(self, monkeypatch):
        def roto(*_a, **_k):
            raise RuntimeError("el revisor se cayó")

        monkeypatch.setattr("resolutions.application.revisor_de_fechas.revisar_las_fechas", roto)
        informe: dict = {}
        assert revisar_y_anotar(informe, "doc", 1, fechas_de_un_par("16/01/2025", "16/01/2025"), [DADA], regla=EXPEDICION) is None
        assert informe == {}

    def test_la_cancelacion_si_sube(self, monkeypatch):
        def cancelado(*_a, **_k):
            raise Cancelled()

        monkeypatch.setattr("resolutions.application.revisor_de_fechas.revisar_las_fechas", cancelado)
        with pytest.raises(Cancelled):
            revisar_y_anotar({}, "doc", 1, fechas_de_un_par("16/01/2025", "16/01/2025"), [DADA], regla=EXPEDICION)

    def test_sin_ia_el_juez_es_nadie_y_un_taller_roto_tambien(self):
        class Roto:
            def juez_de_datos(self):
                raise RuntimeError("sin llave")

        assert fechas_aseguradas.juez_del_trabajo(_Taller()) is None
        assert fechas_aseguradas.juez_del_trabajo(Roto()) is None

    def test_la_ia_del_trabajo_tiene_plazo(self, monkeypatch):
        """Pasado el plazo no pide ni reintenta: lo dudoso va a Revisión y el trabajo termina."""

        class ConPlazo:
            agotado = None

            def hasta(self, agotado):
                self.agotado = agotado

        juez = ConPlazo()
        assert fechas_aseguradas.juez_del_trabajo(_Taller(juez), plazo=60) is juez
        assert juez.agotado() is False
        assert fechas_aseguradas.juez_del_trabajo(_Taller(juez), plazo=-1) is juez
        assert juez.agotado() is True

    def test_el_plazo_se_cambia_por_el_entorno(self, monkeypatch):
        monkeypatch.setenv("BOTPDF_TIEMPO_DEL_REVISOR_DE_FECHAS", "45")
        assert fechas_aseguradas.tiempo_del_revisor() == 45
        monkeypatch.setenv("BOTPDF_TIEMPO_DEL_REVISOR_DE_FECHAS", "no")
        assert fechas_aseguradas.tiempo_del_revisor() == fechas_aseguradas.TIEMPO_DEL_REVISOR_DE_FECHAS

    def test_la_cancelacion_al_preparar_la_ia_sube(self):
        class Cancelado:
            def juez_de_datos(self):
                raise Cancelled()

        with pytest.raises(Cancelled):
            fechas_aseguradas.juez_del_trabajo(Cancelado())

    def test_cada_hoja_una_vez(self):
        assert fechas_aseguradas.sin_repetir(["A", "", "A", " ", "B"]) == ["A", "B"]

    @pytest.mark.parametrize(
        ("texto", "ventana", "escrita"),
        [
            ("NOMINA 3.07.84 PAG. 1", None, "03/07/1984"),
            ("910125 T O T A L 45.000", None, "25/01/1991"),
            ("AÑO 90 PRIMER SEMESTRE", None, "1990"),
            ("ACUMULACION 75", None, "1975"),
            ("IPA/05", (2000, 2008), "2005"),
            ("PERIODO 1977-83", None, "1983"),
        ],
    )
    def test_las_fechas_cortas_del_mismo_texto_van_enteras(self, texto, ventana, escrita):
        assert con_lo_que_leyeron(texto, ventana).endswith(f"LEIDO EN LA HOJA: {escrita}")

    @pytest.mark.parametrize(
        "texto",
        [
            "AÑO 05",  # 1905 o 2005: sin ventana, duda
            "26-10-0001 GOMEZ PEREZ",  # el renglón de un listado
            "VALOR 12.500,00 1.234.567",
            "31.02.84",  # no existe
        ],
    )
    def test_lo_que_no_es_una_fecha_segura_no_se_escribe(self, texto):
        assert con_lo_que_leyeron(texto) == texto

    def test_lo_anotado_aparte_pasa_al_informe(self):
        aparte: dict = {}
        revisar_y_anotar(aparte, "doc", 3, fechas_de_un_par("01/02/2003", "01/02/2003"), ["NADA"], regla=EXTREMOS)
        informe = {"notices": ["ya estaba"], "review_queue": []}
        pasar_al_informe(informe, aparte)
        assert informe[CLAVE_DEL_INFORME]["a revisión"] == 1
        assert informe["notices"] == ["ya estaba"]
        assert informe["review_queue"][0]["page"] == 3


# -- resoluciones: la fórmula «Dada en…» ----------------------------------------------------------


class TestResoluciones:
    def _revisar(self, fila, juez=None):
        informe: dict = {}
        filas = asegurar_las_filas_del_fuid(
            informe, [fila], [_grupo("030-2025", [1, 2])], {1: DADA, 2: ANEXO}.get, regla=EXPEDICION, juez=juez,
            archivos={1: "01_RESOLUCION-030-2025.pdf"},
        )
        return filas[0], informe

    def test_la_de_su_formula_se_confirma(self):
        fila, informe = self._revisar(_fila("16-01-2025"))
        assert fila.fecha_inicial == fila.fecha_final == "16-01-2025"
        assert informe[CLAVE_DEL_INFORME]["confirmada"] == 1

    def test_con_dos_pruebas_se_corrige_con_el_formato_de_la_fila(self):
        # La de la serie, que no está en su papel, y su fórmula dice otra.
        fila, informe = self._revisar(_fila("03-05-2019"))
        assert (fila.fecha_inicial, fila.fecha_final) == ("16-01-2025", "16-01-2025")
        assert "corregida" in fila.notas
        assert any("Fecha corregida en 01_RESOLUCION-030-2025.pdf" in n for n in informe["notices"])

    def test_un_digito_del_ocr_es_duda_y_va_a_revision(self):
        fila, informe = self._revisar(_fila("17-01-2025"))
        assert fila.fecha_inicial == "17-01-2025"
        assert informe[CLAVE_DEL_INFORME]["a revisión"] == 1
        assert informe["review_queue"][0]["page"] == 1
        assert "fechas:" in fila.notas

    def test_la_ia_decide_lo_dudoso_citando_el_papel(self):
        juez = _Juez({
            "fecha_inicial": VeredictoDeDato("no_esta", "a los dieciséis (16) días del mes de enero del año 2025"),
            "fecha_final": VeredictoDeDato("no_esta", "a los dieciséis (16) días del mes de enero del año 2025"),
        })
        fila, informe = self._revisar(_fila("17-01-2025"), juez=juez)
        # Una pregunta por documento, con todo lo dudoso. 16 y 17 se apartan
        # como el OCR: ni la IA citando corrige dentro del margen, va a Revisión.
        assert juez.preguntas == 1
        assert fila.fecha_inicial == "17-01-2025"
        assert informe[CLAVE_DEL_INFORME]["a revisión"] == 1
        assert informe[CLAVE_DEL_INFORME]["preguntadas_a_la_ia"] >= 1


# -- diplomas y matrículas -------------------------------------------------------------------------


class TestRegistros:
    def test_el_diploma_con_su_fecha_en_la_cara_se_confirma(self):
        informe: dict = {}
        filas = asegurar_las_filas_del_fuid(
            informe, [_fila("17-12-2012")], [_grupo("1", [1])], {1: "SE GRADUO EL 17/12/2012"}.get, regla=EXTREMOS,
        )
        assert filas[0].fecha_inicial == "17-12-2012"
        assert informe[CLAVE_DEL_INFORME]["confirmada"] == 1

    def test_lo_que_la_ia_leyo_de_la_cara_es_papel(self):
        # La capa del escáner no trae la fecha; la lectura de la IA, sí.
        informe: dict = {}
        asegurar_las_filas_del_fuid(
            informe, [_fila("17-12-2012")], [_grupo("1", [1])], {1: "ILEGIBLE"}.get, regla=EXTREMOS,
            aparte={1: "Cartagena, 17 de diciembre de 2012"},
        )
        assert informe[CLAVE_DEL_INFORME]["confirmada"] == 1

    def test_los_anios_del_expediente_con_punto(self):
        informe: dict = {}
        filas = asegurar_las_filas_del_fuid(
            informe, [_fila("1950", folios=2, final="1955")], [], {1: "PRIMER AÑO 1.950", 2: "SEXTO AÑO 1.955"}.get,
            regla=ANIOS,
        )
        assert (filas[0].fecha_inicial, filas[0].fecha_final) == ("1950", "1955")
        assert informe[CLAVE_DEL_INFORME]["confirmada"] == 1

    def test_con_la_capa_basura_no_se_pregunta_ni_va_a_revision(self):
        """La capa del escáner es basura y la fecha se leyó con Tesseract, que no se guardó.

        Lo que la capa no trae no prueba nada en contra: ni la IA se paga sobre
        ella ni la fila va a Revisión; queda sin dato con su porqué (la revisión
        adversarial, 2026-11-10: antes, una pregunta a la IA y a Revisión).
        """
        juez = _Juez(None)
        informe: dict = {}
        filas = asegurar_las_filas_del_fuid(
            informe, [_fila("17-12-2012", folios=2)], [_grupo("1", [1, 2])],
            {1: "~ ,. ii UNlVERS| DAD ;; 1|", 2: ""}.get, regla=EXTREMOS, juez=juez,
        )
        assert juez.preguntas == 0
        assert informe[CLAVE_DEL_INFORME]["sin dato"] == 1
        assert "review_queue" not in informe
        assert filas[0].fecha_inicial == "17-12-2012" and filas[0].notas == ""

    def test_con_la_capa_basura_lo_que_el_papel_confirma_vale(self):
        informe: dict = {}
        asegurar_las_filas_del_fuid(
            informe, [_fila("17-12-2012")], [_grupo("1", [1])], {1: "GRADO 17/12/2012"}.get, regla=EXTREMOS,
        )
        assert informe[CLAVE_DEL_INFORME]["confirmada"] == 1

    def test_la_cara_leida_por_la_ia_completa_la_hoja(self):
        """Con lo que la IA leyó de la cara, la hoja está entera: lo dudoso sí se pregunta."""
        juez = _Juez(None)
        informe: dict = {}
        asegurar_las_filas_del_fuid(
            informe, [_fila("17-12-2012")], [_grupo("1", [1])], {1: "ILEGIBLE"}.get, regla=EXTREMOS, juez=juez,
            aparte={1: "Cartagena, 3 de marzo de 2011"},
        )
        assert juez.preguntas == 1
        assert informe[CLAVE_DEL_INFORME]["a revisión"] == 1

    def test_se_puede_detener_entre_una_fila_y_la_siguiente(self):
        class Detenido:
            def check(self):
                raise Cancelled()

        with pytest.raises(Cancelled):
            asegurar_las_filas_del_fuid(
                {}, [_fila("17-12-2012")], [_grupo("1", [1])], {1: DADA}.get, regla=EXTREMOS, control=Detenido()
            )

    def test_sin_texto_en_sus_hojas_es_sin_dato_y_no_revision(self):
        informe: dict = {}
        asegurar_las_filas_del_fuid(informe, [_fila("17-12-2012")], [_grupo("1", [1])], {}.get, regla=EXTREMOS)
        assert informe[CLAVE_DEL_INFORME]["sin dato"] == 1
        assert "review_queue" not in informe

    def test_una_hoja_que_no_se_deja_leer_no_tumba_la_fila(self):
        def roto(_pagina):
            raise OSError("página dañada")

        informe: dict = {}
        filas = asegurar_las_filas_del_fuid(informe, [_fila("17-12-2012")], [_grupo("1", [1])], roto, regla=EXTREMOS)
        assert filas[0].fecha_inicial == "17-12-2012"


# -- la caja de correspondencia -------------------------------------------------------------------


class TestCorrespondencia:
    def _piezas(self):
        return [
            {"pages": [1], "archivo": 0, "titulo": "DERECHO DE PETICION", "fecha": "2021-03-12"},
            {"pages": [2], "archivo": 0, "titulo": "DOCUMENTO DE IDENTIDAD", "fecha": "2021-03-12",
             "fecha_por": "la de su trámite: DERECHO DE PETICION (pág. 1)"},
            {"pages": [3], "archivo": 1, "titulo": "RECLAMO", "fecha": "2021-04-02"},
        ]

    def test_la_de_su_texto_y_la_de_su_sello_se_confirman(self):
        piezas = self._piezas()
        aparte = asegurar_la_caja(
            piezas,
            {1: "Cartagena, 12 de marzo de 2021\nSeñores AFINIA", 2: "CEDULA", 3: "RECLAMO POR FACTURA"},
            _Taller(),
            releidas={},
            prestadas={1: 0},
            sellos={3: Sello("tinta", "RE3110202139039", date(2021, 4, 2))},
            fechas_de_guia={},
        )
        resumen = aparte[CLAVE_DEL_INFORME]
        assert resumen["revisados"] == 3
        assert resumen["confirmada"] == 3
        assert "review_queue" not in aparte

    def test_lo_releido_buscando_la_fecha_es_papel(self):
        piezas = self._piezas()[2:]
        aparte = asegurar_la_caja(
            piezas, {3: "RECLAMO"}, _Taller(), releidas={3: ["Magangué, 2 de abril de 2021"]}, prestadas={},
            sellos={}, fechas_de_guia={},
        )
        assert aparte[CLAVE_DEL_INFORME]["confirmada"] == 1

    def test_la_prestada_sigue_a_la_suya_cuando_se_corrige(self):
        # La IA corrige la del derecho de petición citando su papel -- otro mes,
        # no un dígito del OCR --; la cédula, que la tomó prestada, se corrige
        # con ella.
        juez = _Juez({
            "fecha_inicial": VeredictoDeDato("no_esta", "Cartagena, 23 de abril de 2021"),
            "fecha_final": VeredictoDeDato("no_esta", "Cartagena, 23 de abril de 2021"),
        })
        piezas = self._piezas()
        aparte = asegurar_la_caja(
            piezas,
            {1: "Cartagena, 23 de abril de 2021\nSeñores AFINIA", 2: "CEDULA", 3: "RECLAMO 02/04/2021"},
            _Taller(juez),
            releidas={},
            prestadas={1: 0},
            sellos={},
            fechas_de_guia={},
        )
        assert piezas[0]["fecha"] == piezas[1]["fecha"] == "2021-04-23"
        assert piezas[1]["fecha_por"].startswith("corregida por el revisor de fechas")
        assert "la de su trámite (pág. 1)" in piezas[1]["fecha_por"]
        assert aparte[CLAVE_DEL_INFORME]["corregida"] == 2
        assert piezas[2]["fecha"] == "2021-04-02"

    def test_la_ia_no_corrige_lo_que_se_aparta_como_el_ocr(self):
        # 2021 y 2027: un dígito. Es el margen de error: va a Revisión, no se corrige.
        juez = _Juez({"fecha_inicial": VeredictoDeDato("no_esta", "Cartagena, 12 de marzo de 2027")})
        piezas = self._piezas()[:1]
        aparte = asegurar_la_caja(
            piezas, {1: "Cartagena, 12 de marzo de 2027"}, _Taller(juez), releidas={}, prestadas={}, sellos={},
            fechas_de_guia={},
        )
        assert piezas[0]["fecha"] == "2021-03-12"
        assert aparte[CLAVE_DEL_INFORME]["a revisión"] == 1

    def test_el_mes_y_el_anio_escritos_sin_dia_bastan_sin_lector_de_la_regla(self):
        # La regla de la caja (EXTREMOS) no tiene lector fuerte: el mes y el año
        # escritos, sin otro día de ese mes, son apoyo del papel (el OCR deshace
        # el día). Es el margen del contraste del dominio: no se pregunta a la IA.
        juez = _Juez({})
        aparte = asegurar_la_caja(
            self._piezas()[:1], {1: "Cartagena, marzo de 2021"}, _Taller(juez), releidas={}, prestadas={},
            sellos={}, fechas_de_guia={},
        )
        assert aparte[CLAVE_DEL_INFORME]["confirmada"] == 1
        assert juez.preguntas == 0

    def test_otra_fecha_completa_del_mismo_mes_no_confirma(self):
        # «15 de marzo de 2021» con la fila en el 12: el mismo mes y año ya no
        # bastan si el papel trae otro día escrito entero (la revisión,
        # 2026-11-10: la carta del 17 confirmaba la fila del 18).
        juez = _Juez({})
        aparte = asegurar_la_caja(
            self._piezas()[:1], {1: "Cartagena, 15 de marzo de 2021"}, _Taller(juez), releidas={}, prestadas={},
            sellos={}, fechas_de_guia={},
        )
        assert aparte[CLAVE_DEL_INFORME]["confirmada"] == 0
        assert aparte[CLAVE_DEL_INFORME]["a revisión"] == 1

    def test_sin_prueba_va_a_revision_y_la_prestada_con_ella(self):
        piezas = self._piezas()
        aparte = asegurar_la_caja(
            piezas, {1: "Señores AFINIA", 2: "CEDULA", 3: "RECLAMO 02/04/2021"}, _Taller(),
            releidas={}, prestadas={1: 0}, sellos={}, fechas_de_guia={},
        )
        razones = [item["reason"] for item in aparte["review_queue"]]
        assert len(razones) == 2
        assert "la de su trámite (pág. 1)" in razones[1]
        # Nada se cambia sin prueba.
        assert piezas[0]["fecha"] == piezas[1]["fecha"] == "2021-03-12"

    def test_un_fallo_deja_la_caja_como_estaba(self):
        piezas = [{"pages": [], "fecha": "2021-03-12"}]
        assert asegurar_la_caja(
            piezas, {}, _Taller(), releidas={}, prestadas={}, sellos={}, fechas_de_guia={}
        ) == {}
        assert piezas[0]["fecha"] == "2021-03-12"


# -- Kingspan: cada punta, el documento que es --------------------------------------------------------


class TestKingspan:
    def _fila(self):
        desde = Documento(pagina=1, serie="CEE", numero=21045, fecha=date(2024, 3, 21))
        medio = Documento(pagina=2, serie="CEE", numero=21080, fecha=date(2024, 3, 1))
        hasta = Documento(pagina=3, serie="CEE", numero=21111, fecha=date(2024, 3, 18))
        return FilaKingspan(
            asunto="COMPROBANTES",
            desde=desde.codigo,
            hasta=hasta.codigo,
            fecha_inicial=desde.fecha,
            fecha_final=hasta.fecha,
            documentos=(desde, medio, hasta),
        )

    def test_cada_punta_contra_su_hoja_y_la_final_anterior_no_es_error(self):
        # El oficial trae 65 filas con la final anterior a la inicial: cada
        # punta conserva la de su documento.
        textos = ["Número 001-CEE-00021045\nFecha 2024/03/21", "Fecha 01/03/2024", "Fecha 18/03/2024"]
        filas, aparte = asegurar_la_upd([self._fila()], textos, {}, _Taller())
        assert aparte[CLAVE_DEL_INFORME]["revisados"] == 2
        assert aparte[CLAVE_DEL_INFORME]["confirmada"] == 2
        assert (filas[0].fecha_inicial, filas[0].fecha_final) == (date(2024, 3, 21), date(2024, 3, 18))

    def test_la_franja_releida_es_papel(self):
        textos = ["NOTA SIN FECHA EN LA CAPA", "", "Fecha 18/03/2024"]
        _, aparte = asegurar_la_upd([self._fila()], textos, {1: ["Fecha: 21/03/2024"]}, _Taller())
        assert aparte[CLAVE_DEL_INFORME]["confirmada"] == 2

    def test_la_punta_sin_su_fecha_en_el_papel_va_a_revision(self):
        textos = ["NOTA SIN FECHA", "", "Fecha 18/03/2024"]
        filas, aparte = asegurar_la_upd([self._fila()], textos, {}, _Taller())
        informe: dict = {"review_queue": []}
        pasar_al_informe(informe, aparte)
        assert [item["page"] for item in informe["review_queue"]] == [1]
        assert "001-CEE-00021045" in informe["review_queue"][0]["reason"]
        # Sin prueba no se toca, y la nota no se repite en la fila (va a los avisos por el informe).
        assert filas[0].fecha_inicial == date(2024, 3, 21)
        assert filas[0].notas == ""

    def test_la_upd_sin_documentos_numerados_va_de_punta_a_punta(self):
        fila = FilaKingspan(asunto="CONCILIACION", fecha_inicial=date(2024, 1, 5), fecha_final=date(2024, 2, 9))
        _, aparte = asegurar_la_upd([fila], ["Corte al 05/01/2024", "Firmado el 09/02/2024"], {}, _Taller())
        assert aparte[CLAVE_DEL_INFORME]["confirmada"] == 1


# -- de punta a punta: el trabajo entero deja su revisión en el informe ------------------------------


class TestDePuntaAPunta:
    """Las rutas de verdad sobre PDF pequeños: el revisor corre y su resumen llega al informe."""

    @staticmethod
    def _pdf(tmp_path, nombre: str, paginas: list[str]):
        pymupdf = pytest.importorskip("pymupdf")
        ruta = tmp_path / nombre
        with pymupdf.open() as documento:
            for texto in paginas:
                documento.new_page().insert_textbox(pymupdf.Rect(40, 40, 560, 800), texto, fontsize=11)
            documento.save(ruta)
        return ruta

    def test_kingspan_revisa_cada_punta_de_cada_serie(self, tmp_path):
        from resolutions.api.worker.kingspan import _kingspan_job
        from resolutions.application.task import TaskKind

        def encabezado(serie: str, numero: int, fecha: str) -> str:
            return (
                f"NOTA BANCARIA\nKINGSPAN PANELES AISLADOS S.A.S\nNIT 900447906-1\n"
                f"Número:\n001-{serie}-{numero:08d}\nPRINCIPAL\nFecha:\n{fecha}\n"
            )

        origen = self._pdf(
            tmp_path,
            "UPD0000002.pdf",
            [encabezado("NB", 1300, "05/05/2024"), "Extracto grapado", encabezado("NB", 1301, "09/05/2024")],
        )
        informe = _kingspan_job(
            {
                "job_id": "t",
                "source": str(origen),
                "filename": "100C000999/UPD0000002.pdf",
                "task": "inventory",
                "settings": {"ocr_language": "spa", "output_dir": str(tmp_path / "salida")},
            },
            TaskKind.INVENTORY,
        )
        resumen = informe[CLAVE_DEL_INFORME]
        assert resumen["revisados"] == 2
        assert resumen["confirmada"] == 2

    def test_la_caja_revisa_cada_pieza(self, tmp_path):
        from resolutions.api import worker
        from resolutions.api.settings import Settings
        from resolutions.application.task import TaskKind

        caja = self._pdf(
            tmp_path, "caja.pdf", ["DERECHO DE PETICION\nCartagena, 12 de marzo de 2021\nSeñores AFINIA\nSolicito..."]
        )
        informe = worker._segment_job(
            {
                "job_id": "t",
                "source": str(caja),
                "filename": "caja.pdf",
                "task": str(TaskKind.SEGMENT),
                "settings": Settings(output_dir=tmp_path / "salida").as_worker_payload(),
            },
            TaskKind.SEGMENT,
        )
        resumen = informe[CLAVE_DEL_INFORME]
        assert resumen["revisados"] == 1
        assert resumen["confirmada"] == 1

    def test_el_legajo_revisa_cada_resolucion_por_su_formula(self, tmp_path):
        from resolutions.api.settings import Settings
        from resolutions.api.worker import _split_job
        from resolutions.application.task import TaskKind

        legajo = self._pdf(
            tmp_path,
            "RESOLUCIONES 00412.pdf",
            [
                "RESOLUCION No. 00412\nPor medio de la presente resolucion se resuelve la solicitud. "
                "RESUELVE: ARTICULO PRIMERO. Conceder lo pedido.",
                "Dada en Cartagena de Indias, a los dieciséis (16) días del mes de enero del año 2025\nEL RECTOR",
            ],
        )
        informe = _split_job(
            {
                "job_id": "trabajo",
                "source": str(legajo),
                "filename": "RESOLUCIONES 00412.pdf",
                "task": str(TaskKind.BOTH),
                "settings": Settings(output_dir=tmp_path / "outputs").as_worker_payload(),
            },
            TaskKind.BOTH,
        )
        resumen = informe[CLAVE_DEL_INFORME]
        assert resumen["revisados"] >= 1
        assert resumen["confirmada"] >= 1
        assert resumen["a revisión"] == 0

    def test_la_fecha_corregida_llega_tambien_a_la_planilla_y_al_inventario(self, tmp_path, monkeypatch):
        """El FUID decía 16-01-2025 y la planilla que va junto a los PDF, la constancia y el acta del lote,
        2019-05-03, la de la serie: entregables que se contradecían (la revisión adversarial, 2026-11-10)."""
        from dataclasses import replace

        from openpyxl import load_workbook

        from resolutions.api.settings import Settings
        from resolutions.api.worker import _split_job
        from resolutions.application import process_document
        from resolutions.application.task import TaskKind

        original = process_document.ProcessDocument._describir_el_legajo

        def de_la_serie(result, source):
            # Como `completar_por_la_serie` cuando la fórmula no se dejó leer al procesar.
            hecho = original(result, source)
            return replace(hecho, groups=[replace(grupo, fecha="2019-05-03") for grupo in hecho.groups])

        monkeypatch.setattr(process_document.ProcessDocument, "_describir_el_legajo", staticmethod(de_la_serie))
        legajo = self._pdf(
            tmp_path,
            "RESOLUCIONES 00412.pdf",
            [
                "RESOLUCION No. 00412 DE 2025\nPor medio de la presente resolucion se resuelve la solicitud. "
                "RESUELVE: ARTICULO PRIMERO. Conceder lo pedido.",
                "Dada en Cartagena de Indias, a los dieciséis (16) días del mes de enero del año 2025\nEL RECTOR",
            ],
        )
        informe = _split_job(
            {
                "job_id": "trabajo",
                "source": str(legajo),
                "filename": "RESOLUCIONES 00412.pdf",
                "task": str(TaskKind.BOTH),
                "settings": Settings(output_dir=tmp_path / "outputs").as_worker_payload(),
            },
            TaskKind.BOTH,
        )

        assert informe[CLAVE_DEL_INFORME]["corregida"] == 1
        assert [item.get("fecha") for item in informe["inventory"]["items"]] == ["2025-01-16"]
        salida = tmp_path / "outputs" / "trabajo"
        hoja = load_workbook(next(salida.glob("*__inventario.xlsx")))["Resoluciones"]
        # Las filas de la tabla, las que empiezan por su número de orden.
        documentos = [fila for fila in hoja.iter_rows(values_only=True) if isinstance(fila[0], int)]
        assert [fila[3] for fila in documentos] == ["2025-01-16"]
