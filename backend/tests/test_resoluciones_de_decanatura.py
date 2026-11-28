"""Resoluciones de decanatura: tomos de varios años, con sus soportes y su número completo.

Medido el 2026-11-27 sobre los diez tomos de «RESOLUCIONES DECANATURA
1995-2002» de la Facultad de Odontología (carpeta 3194 - 3198). Los textos
tienen la forma de las páginas reales, con sus defectos de OCR; los nombres de
personas son inventados.
"""

from __future__ import annotations

from datetime import date

import pytest
from fakes import FakeOcr, FakePage, FakePageSource

from resolutions.adapters.pymupdf_assembler import nombre_por_su_asunto
from resolutions.application.pipeline import ClassificationPipeline, PipelineConfig
from resolutions.application.resolution_fuid import (
    asunto_del_grupo,
    filas_de_resoluciones,
)
from resolutions.domain.extraction import (
    encabezado_sin_numero,
    extract_candidates,
    hoja_de,
)
from resolutions.domain.grouping import GroupingEngine, PageGroup
from resolutions.domain.plantilla_de_pagina import Plantilla, plantilla_de
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.scoring import opens_a_resolution
from resolutions.domain.serie_del_legajo import (
    anio_de_su_papel,
    anios_de_la_serie,
    anios_del_legajo,
    es_de_las_previas,
    numeros_por_la_serie,
)
from resolutions.domain.title import lo_que_resuelve

MEMBRETE = "DIRECCION: CENTRO CRA. 6\nNo. 36-100\nUNIVERSIDAD DE CARTAGENA\nFUNDADA EN 1.827\nCARTAGENA, COLOMBIA\n"


def decano(numero: str, cierre: str, *, encabezado: str = "RESOLUCIÓN No. {n}", orden: str = "") -> str:
    return (
        MEMBRETE
        + encabezado.format(n=numero)
        + "\nPor la cual se fija fecha para la realización de una evaluación académica.\n"
        + "EL DECANO DE LA FACULTAD DE ODONTOLOGIA DE LA UNIVERSIDAD DE\n"
        + "CARTAGENA, en uso de sus facultades legales, y\nCONSIDERANDO;\n"
        + "A) Que, la doctora Ana Pérez Ruiz, solicitó a este despacho la presentación de examen final;\n"
        + "RESUELVE:\n"
        + (orden or "ARTÍCULO 1o.- Fijar ia fecha del JUEVES 26 DE.MARZO DE 1998, a las 15;00 horas, para el examen.\n")
        + "ARTICULO 2o.- Enviar copia al docente y representante de curso.\n"
        + cierre
        + "\nCESAR PEREZ GOMEZ\nSecretario Académico"
    )


def consejo(numero: str, cierre: str, *, titulo: str = "el Calendario Académico", hoja: str = "Hola No. 1") -> str:
    return (
        "UNIVERSIDAD DE CARTAGENA\nFUNDADA EN 1827\nNIT. 890.480.123-5\n"
        f"Resolución No. {numero}\n{hoja}\n"
        f"Por la cual se fija {titulo}.\n"
        "EL CONSEJO DE LA FACULTAD DE ODONTOLOGÍA DE LA UNIVERSIDAD DE CARTAGENA, en\n"
        "uso de sus facultades legales y\nCONSIDERANDO:\nA. Que es deber de las directivas acogerse al calendario.\n"
        "RESUELVE:\nARTICULO lo.- Fijar las siguientes fechas para el Calendario Académico Interno, así:\n"
        + cierre
    )


SOLICITUD = (
    "UNIVERSIDAD DE CARTAGENA\nFacultad de Odontología\nSOLICITUD DE EXAMEN\nFecha de solicitud\n"
    "Fecha de examen\nTipo de examen\nescrito\noral\nFinal\nparcial\nsupletorio\nhabilitación\nAsignatura\n"
    "Docente\nNOTA: Los examenes deben ser en la hora de la materia y en el horario del semestre"
)
MEJORES = (
    "UNIVERSIDAD DE CARTAGENA\nMejores Estudiantes (Promedio Acumulado)\nPeríodo: 2009/2\n"
    "PUESTO CODIGO NOMBRES Y APELLIDOS PROGRAMA SEM PUNTAJE\n1 5229810001 PEREZ RUIZ ANA ODONTOLOGIA 4 4.50\n"
    "2 5229810002 GOMEZ DIAZ LUIS ODONTOLOGIA 4 4.40"
)
FICHA = (
    "UNIVERSIDAD DE CARTAGENA\nFACULTAD DE ODONTOLOGIA\nNombre del estudiante MARIA JOSE TORRES LUNA\n"
    "Código 5229810003\nSemestre IV\nASIGNATURAS Sem Año Nota"
)


def clasificar(paginas: list[str], *, bandas: dict[int, str] | None = None):
    fuente = FakePageSource(
        pages=[FakePage(text=t, header=(bandas or {}).get(i, "")) for i, t in enumerate(paginas, start=1)]
    )
    pipeline = ClassificationPipeline(ocr=FakeOcr(), config=PipelineConfig(max_workers=1, verify_declarations=False))
    clasificaciones, stats = pipeline.classify(fuente)
    return GroupingEngine().group(clasificaciones), stats


def grupos(agrupacion) -> list[tuple[str, list[int]]]:
    return [(g.code.value, g.page_numbers) for g in agrupacion.groups]


class TestLasAperturas:
    @pytest.mark.parametrize(
        ("encabezado", "esperado"),
        [
            ("RESOLUCION #001", "001"),
            ("RESOLUCIÓN No. 07", "007"),
            ("RESOLUCION 03", "003"),
            ("RESOLUCIÓN o84", "084"),
            ("RESOLUCIÓN lo8", "108"),
        ],
    )
    def test_el_encabezado_del_decano_abre(self, encabezado, esperado):
        texto = decano("", "Dada en Cartagena a los 26 dias de marzo de 1998.", encabezado=encabezado)
        abren = [c.code.value for c in extract_candidates(texto) if opens_a_resolution(c)]
        assert abren == [esperado]
        assert plantilla_de(texto).plantilla is Plantilla.RESOLUCION_DE_FACULTAD

    def test_la_del_consejo_con_su_hoja_1(self):
        texto = consejo("016", "Dada en Cartagena de Indias, a los 06 días del mes de Junio de 2008.")
        candidatos = extract_candidates(texto)
        assert [(c.code.value, c.hoja, opens_a_resolution(c)) for c in candidatos] == [("016", 1, True)]

    def test_sin_particula_y_con_quien_la_expide_abre(self):
        texto = consejo("001", "", hoja="Hola No. 1").replace("Resolución No. 001", "Resolución 001")
        assert [c.code.value for c in extract_candidates(texto) if opens_a_resolution(c)] == ["001"]
        assert plantilla_de(texto).plantilla is Plantilla.RESOLUCION_DE_FACULTAD

    def test_el_numero_escrito_en_su_renglon_debajo(self):
        texto = (
            "UNIVERSIDAD DE CARTAGENA\nCartagena - Colombia\nde 1.9\nResolución No.\n,'-1\n001\n"
            "Por la cual se nombran Coordinadores de asignaturas para el Primer Período de 2003\n"
            "EL CONSEJO DE LA FACULTAD DE ODONTOLOGÍA DE LA UNIVERSIDAD DE\n"
        )
        assert [c.code.value for c in extract_candidates(texto) if opens_a_resolution(c)] == ["001"]

    def test_el_numero_de_una_lista_debajo_no_es_el_de_la_resolucion(self):
        # La hoja siguiente de la 150: «Resolución No.» y la lista de graduandos.
        texto = (
            "UNIVERSIDAD DE CARTAGENA\nCartagena - Colombia\nResolución No.\nde 1.9\n28.\n"
            "IRIARTE PEREZ LUISA DEL C.\nLOCARNO DIAZ ROSA CRISTINA\n"
        )
        assert extract_candidates(texto) == []


class TestLasContinuaciones:
    def test_la_hoja_2_sin_particula_sigue_y_no_abre(self):
        texto = "Resolución 03\n2 de febrero de 1995\nHoja 2.\nen los Considerando de la presente Resolución."
        candidatos = extract_candidates(texto)
        assert hoja_de(texto) == 2
        assert [c.code.value for c in candidatos] == ["003"]
        assert not any(opens_a_resolution(c) for c in candidatos)

    def test_la_hoja_2_con_particula_tampoco_abre(self):
        texto = "UNIVERSIDAD DE CARTAGENA\nResolución No. 001 de 1.9 Hoja 2\nII SEMESTRE\nDra. Ana Pérez, Morfología"
        assert not any(opens_a_resolution(c) for c in extract_candidates(texto))

    def test_la_hoja_2_con_otro_numero_sigue_en_la_abierta(self):
        # La hoja 2 trae el encabezado entero; si el OCR leyó otro número, no abre otra.
        abre = consejo("016", "")
        hoja_2 = "UNIVERSIDAD DE CARTAGENA\nFUNDADA EN 1827\nResolución No. 018\nHola No. 2\nDada en Cartagena de Indias, a los 06 días del mes de Junio de 2008."
        siguientes = [consejo(n, "Dada en Cartagena de Indias, a los 9 días de julio de 2008.") for n in ("024", "026")]
        agrupacion, _ = clasificar([abre, hoja_2, *siguientes])
        assert grupos(agrupacion)[0] == ("016-2008", [1, 2])


class TestLasCitasNoAbren:
    def test_la_que_cita_otra_resolucion(self):
        texto = decano("076", "Dada en Cartagena a los 3 días de febrero de 1997.") + (
            "\nQue, la Resolución 2166 de diciembre de 1996, emanada de la Rectoría, fija el calendario"
        )
        assert [c.code.value for c in extract_candidates(texto) if opens_a_resolution(c)] == ["076"]

    def test_el_acta_que_cita_la_resolucion_que_autorizo_el_acto(self):
        texto = (
            "LA UNIVERSIDAD DE CARTAGENA\nACTA DE GRADO No. 01\nEn la ciudad de Cartagena, se realizó la graduación\n"
            "a solicitud del Decano de la Facultad DE ODONTOLOGIA a la Rectoría, quien autorizó el acto mediante\n"
            "Resolución No. 1847 de fecha 16 de diciembre de 1.993 por medio de la cual, otorga el título"
        )
        assert not any(opens_a_resolution(c) for c in extract_candidates(texto))


class TestQuienLaExpide:
    @pytest.mark.parametrize(
        "emisor",
        [
            "EL DECANO DE LA FACULTAD DE ODONTOLOGIA DE LA UNIVERSIDAD DE",
            "LA DECANA DE LA FACULTAD DE ODONTOLOGIA DE LA UNIVERSIDAD DE",
            "EL CONSEJO DE LA FACULTAD DE ODONTOLOGIA DE LA UNIVERSIDAD DE CARTAGENA",
            "EL DECANO, LAS DIRECTIVAS, LOS DOCENTES Y EL PERSONAL",
        ],
    )
    def test_la_resolucion_es_de_facultad(self, emisor):
        texto = f"UNIVERSIDAD DE CARTAGENA\nRESOLUCIÓN 130\n{emisor}\nlamentan el fallecimiento del doctor"
        assert plantilla_de(texto).plantilla is Plantilla.RESOLUCION_DE_FACULTAD
        assert [c.code.value for c in extract_candidates(texto) if opens_a_resolution(c)] == ["130"]

    def test_la_firma_decano_sola_no_expide(self):
        texto = "UNIVERSIDAD DE CARTAGENA\nResolución 03\nHoja 4\nFRANKLIN PEREZ DIAZ\nDecano"
        assert not any(c.official_form for c in extract_candidates(texto))


class TestElAnioDeCadaResolucion:
    def test_un_tomo_de_varios_anios_no_junta_la_001_de_cada_anio(self):
        paginas = [
            consejo("001", "Dada en Cartagena, a los 25 días de febrero de 2003"),
            decano("002", "Dada en Cartagena a los 3 días de marzo de 2003."),
            consejo("001", "Dada en Cartagena de Indias, a los 16 días del mes de enero de 2004."),
            decano("002", "Dada^jBRDartagena a los 26 días de marzo de 2004."),
            decano("003", "Dada en (ilegible)"),
        ]
        agrupacion, stats = clasificar(paginas)
        assert grupos(agrupacion) == [
            ("001-2003", [1]),
            ("002-2003", [2]),
            ("001-2004", [3]),
            ("002-2004", [4]),
            ("003-2004", [5]),
        ]
        assert stats.anio_por_la_serie == [5]

    def test_el_anio_que_la_serie_desmiente(self):
        # La 187 de 2006 cierra con la fórmula copiada de una de 2003.
        paginas = [
            decano("184", "Dada en Cartagena a los 2 días de junio de 2006."),
            consejo("187", "Dada en Cartagena de Indias, a los 17 días de Julio de 2003"),
            decano("190", "Dada en Cartagena a los 20 días de julio de 2006."),
            decano("187", "Dada en Cartagena a los 28 días de noviembre de 2003."),
        ]
        agrupacion, _ = clasificar(paginas)
        assert [codigo for codigo, _ in grupos(agrupacion)] == ["184-2006", "187-2006", "190-2006", "187-2003"]

    def test_la_del_calendario_del_anio_siguiente(self):
        # La 001 de noviembre de 2007 fija el primer periodo de 2008 y va con las de 2008.
        paginas = [
            consejo("001", "Dada en Cartagena de Indias, a los 31 días de Enero de 2007"),
            decano("135", "Dada en Cartagena a los 20 días de octubre de 2007."),
            consejo("001", "Dada en Cartagena de Indias, a los 21 días del mes de noviembre de 2007"),
            consejo("003", "Dada en Cartagena de Indias, a los 30 días del mes de enero de 2008"),
        ]
        agrupacion, _ = clasificar(paginas)
        assert [codigo for codigo, _ in grupos(agrupacion)] == ["001-2007", "135-2007", "001-2008", "003-2008"]

    def test_la_misma_resolucion_dos_veces_va_junta(self):
        copia = consejo("007", "Dada en Cartagena de Indias, a los 9 días de mayo de 2003.")
        # Dos distintas en medio: una sola entre dos lecturas iguales es un fantasma del OCR.
        en_medio = [decano(n, "Dada en Cartagena a los 3 días de junio de 2003.") for n in ("008", "009")]
        agrupacion, _ = clasificar([copia, *en_medio, copia])
        assert grupos(agrupacion) == [("007-2003", [1, 4]), ("008-2003", [2]), ("009-2003", [3])]

    def test_el_anio_de_su_papel(self):
        assert anio_de_su_papel(["Dada^jBRDartagena a los 26 días de marzo de 1998."]) == 1998
        assert anio_de_su_papel(["RESOLUCION 03\n2 de febrero de 1995\nEL DECANO DE LA FACULTAD"]) == 1995
        assert anio_de_su_papel(["UNIVERSIDAD DE CARTAGENA\nFUNDADA EN 1.827\nsin fecha"]) is None

    def test_la_serie_rellena_y_no_inventa(self):
        assert anios_de_la_serie([33, 34, 35], [2008, None, 2008]) == [(2008, False), (2008, True), (2008, False)]
        # La numeración vuelve a empezar: la 001 sin fecha es del año de la 002.
        assert anios_de_la_serie([34, 1, 2], [2008, None, 2009])[1] == (2009, True)
        # Nada la sostiene: se queda sin año.
        assert anios_de_la_serie([50, 1], [2008, None])[1] == (None, False)
        # Las de rectoría no son de la serie.
        assert anios_de_la_serie([None, 5], [None, None]) == [(None, False), (None, False)]

    def test_dos_distintas_con_el_mismo_numero_y_anio_se_separan_por_la_serie(self):
        anios = anios_del_legajo(
            [1, 135, 1, 3],
            [2007, 2007, 2007, 2008],
            [date(2007, 1, 31), date(2007, 10, 20), date(2007, 11, 21), date(2008, 1, 30)],
        )
        assert [a for a, _ in anios] == [2007, 2007, 2008, 2008]

    def test_rectoria_no_cambia(self):
        rectoria = "Universidad\nde Cartagena\nRESOLUCIÓN No. 00316 DE 2025\nEL RECTOR DE LA UNIVERSIDAD DE CARTAGENA"
        agrupacion, stats = clasificar([rectoria])
        assert grupos(agrupacion) == [("00316", [1])]
        assert stats.anio_por_la_serie == [] and stats.sin_anio == []


class TestLosSoportes:
    def test_van_con_su_resolucion_y_nunca_abren(self):
        paginas = [
            decano("010", "Dada en Cartagena a los 3 días de abril de 1998."),
            SOLICITUD,
            decano("011", "Dada en Cartagena a los 4 días de abril de 1998."),
            MEJORES,
            FICHA,
            decano("012", "Dada en Cartagena a los 5 días de abril de 1998."),
        ]
        agrupacion, _ = clasificar(paginas)
        assert grupos(agrupacion) == [("010-1998", [1, 2]), ("011-1998", [3, 4, 5]), ("012-1998", [6])]

    def test_la_respuesta_del_rector_va_con_la_del_decano_que_la_pidio(self):
        rector = (
            "UNIVERSIDAD DE CARTAGENA\nFUNDADA EN 1827\nPágina 1\nResolución No. 3073\n"
            "EL RECTOR DE LA UNIVERSIDAD DE CARTAGENA\nQue, el Decano mediante Resolución No.032 de fecha 07 de septiembre"
        )
        paginas = [
            decano("031", "Dada en Cartagena a los 2 días de septiembre de 2009."),
            decano("032", "Dada en Cartagena a los 7 días de septiembre de 2009."),
            rector,
            rector.replace("Página 1", "Página 2"),
            decano("035", "Dada en Cartagena a los 20 días de septiembre de 2009."),
        ]
        agrupacion, stats = clasificar(paginas)
        assert grupos(agrupacion) == [("031-2009", [1]), ("032-2009", [2, 3, 4]), ("035-2009", [5])]
        assert {3, 4} <= set(stats.soportes)


class TestLasHojasPrevias:
    def test_la_solicitud_antes_de_la_primera_va_en_su_pdf_con_su_titulo(self):
        paginas = [
            SOLICITUD,
            decano("062", "Dada en Cartagena a los 12 días de junio de 1997."),
            decano("063", "Dada en Cartagena a los 12 días de junio de 1997."),
            decano("064", "Dada en Cartagena a los 13 días de junio de 1997."),
        ]
        agrupacion, stats = clasificar(paginas)
        assert agrupacion.quarantine == []
        assert grupos(agrupacion)[0] == ("PREVIAS-1", [1])
        assert es_de_las_previas(agrupacion.groups[0].code.value)
        filas = filas_de_resoluciones(
            agrupacion.groups, nombre_del_archivo="1992-2002- tomo 2.pdf", texto_de=lambda n: paginas[n - 1]
        )
        assert filas[0].asunto == "SOLICITUD DE EXAMEN"
        assert (filas[0].consecutivo_inicial, filas[0].consecutivo_final) == ("N/A", "N/A")
        assert stats.previas == {1: "su propio documento: SOLICITUD DE EXAMEN"}

    def test_la_hoja_en_blanco_va_con_la_primera(self):
        paginas = [
            "",
            decano("001", "Dada en Cartagena a los 12 días de junio de 1997."),
            decano("002", "Dada en Cartagena a los 12 días de junio de 1997."),
            decano("003", "Dada en Cartagena a los 13 días de junio de 1997."),
        ]
        agrupacion, _ = clasificar(paginas)
        assert agrupacion.quarantine == []
        assert grupos(agrupacion)[0] == ("001-1997", [1, 2])


class TestElNumeroEnBlanco:
    PAGINA = (
        "UNIVERSIDAD DE CARTAGENA\nCartagena - Colombia\nResolución No.\nde 1.9\n"
        "Por la cual se fija el Calendario Académico de pregrado para el primero y segundo período de 1999.\n"
        "EL DECANO DE LA FACULTAD DE ODONTOLOGIA DE LA UNIVERSIDAD DE\nCARTAGENA, en uso de sus facultades\n"
        "RESUELVE:\nARTÍCULO 1o.- Fijar el calendario académico de pregrado para el año 1999.\n"
        "Dada en Cartagena a los 15 días de enero de 1999."
    )

    def test_se_reconoce(self):
        assert encabezado_sin_numero(self.PAGINA)
        assert not encabezado_sin_numero(decano("010", ""))

    def test_se_lee_en_la_banda(self):
        paginas = [
            decano("136", "Dada en Cartagena a los 9 días de enero de 1999."),
            decano("137", "Dada en Cartagena a los 10 días de enero de 1999."),
            self.PAGINA,
        ]
        agrupacion, stats = clasificar(paginas, bandas={3: "UNIVERSIDAD DE CARTAGENA\nResolución No. 138 de 1.9"})
        assert grupos(agrupacion) == [("136-1999", [1]), ("137-1999", [2]), ("138-1999", [3])]
        assert stats.por_la_banda == [3]


class TestElAsuntoYElNombreDelPdf:
    def test_resolucion_numero_completo_y_lo_que_resuelve(self):
        texto = decano("007", "Dada en Cartagena a los 26 dias de marzo de 1998.")
        grupo = PageGroup(code=ResolutionCode.parse("007-1998"), page_numbers=[1], fecha="1998-03-26")
        [fila] = filas_de_resoluciones([grupo], nombre_del_archivo="07-115 TOMO 1.pdf", texto_de=lambda _n: texto)
        assert fila.asunto == (
            "RESOLUCION 007-1998 - FIJAR LA FECHA DEL JUEVES 26 DE MARZO DE 1998, A LAS 15:00 HORAS, PARA EL EXAMEN"
        )
        assert (fila.consecutivo_inicial, fila.consecutivo_final) == ("007-1998", "007-1998")
        assert (fila.fecha_inicial, fila.fecha_final) == ("26-03-1998", "26-03-1998")
        assert asunto_del_grupo(grupo, lambda _n: texto) == fila.asunto

    def test_el_pdf_se_llama_como_su_fila(self):
        asunto = "RESOLUCION 007-1998 - FIJAR LA FECHA DEL JUEVES 26 DE MARZO DE 1998, A LAS 15:00 HORAS"
        assert nombre_por_su_asunto(1, asunto, budget=200) == (
            "01_RESOLUCION 007-1998 - FIJAR LA FECHA DEL JUEVES 26 DE MARZO DE 1998, A LAS 15-00 HORAS.pdf"
        )

    def test_el_nombre_largo_se_recorta_por_una_palabra(self):
        asunto = "RESOLUCION 001-2003 - " + "NOMBRAR COORDINADORES " * 20
        nombre = nombre_por_su_asunto(12, asunto, budget=200)
        assert nombre.startswith("12_RESOLUCION 001-2003 - NOMBRAR")
        # Por una palabra entera: lo que queda es el principio del asunto.
        assert asunto.startswith(nombre[3:-4] + " ")
        assert len(nombre) <= 3 + 120 + 4
        # Y lo que no cabe en la ruta tampoco entra.
        assert len(nombre_por_su_asunto(12, asunto, budget=60)) <= 60

    def test_lo_que_resuelve_sin_lo_que_rompio_el_ocr(self):
        orden = lo_que_resuelve(["RESUELVE:\nARTÍCULO 1o.- Fijar ia fecha del 26 DE.MARZO DE 1998, a las 15;00 horas, para el examen."])
        assert orden == "Fijar la fecha del 26 DE MARZO DE 1998, a las 15:00 horas, para el examen"

    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("RESUELVE:\nARTICULO lo.-\nFijar las siguientes fechas para el Calendario Académico, así:",
             "Fijar las siguientes fechas para el Calendario Académico, así"),
            ("RESUELVE;\nHT’ICULO 1-.- Fíjese la fecha del 3 de marzo de 1995 para el examen. ARTICULO 2o.",
             "Fíjese la fecha del 3 de marzo de 1995 para el examen"),
            # Sin RESUELVE legible: el artículo primero que abre su renglón.
            ("Por la cual se nombran Coordinadores\nARTICULO 1o.-\nNombrar coordinadores de las diferentes asignaturas.",
             "Nombrar coordinadores de las diferentes asignaturas"),
        ],
    )
    def test_el_rotulo_del_articulo_como_lo_deja_la_capa(self, texto, esperado):
        assert lo_que_resuelve([texto]) == esperado

    def test_sin_resuelve_el_titulo_sin_quien_la_expide(self):
        texto = (
            "RESOLUCIÓN No. 016\nPor la cual se nombra coordinador de la unidad estomatológica.\n"
            "EL DECANO DE LA FACULTAD DE ODONTOLOGIA DE LA UNIVERSIDAD DE\nCARTAGENA, en uso de sus facultades"
        )
        grupo = PageGroup(code=ResolutionCode.parse("016-1995"), page_numbers=[1], title=None)
        from resolutions.domain.title import extract_title

        grupo = PageGroup(code=grupo.code, page_numbers=[1], title=extract_title(texto, titulo_encima=True))
        assert asunto_del_grupo(grupo, lambda _n: texto) == (
            "RESOLUCION 016-1995 - POR LA CUAL SE NOMBRA COORDINADOR DE LA UNIDAD ESTOMATOLÓGICA"
        )

    def test_la_fecha_con_el_mes_roto_no_es_el_titulo(self):
        from resolutions.domain.title import extract_title

        assert extract_title("RESOLlíCION No. 004\n2 de lebrero de 1995\nt", titulo_encima=True) is None


class TestElNumeroQueEngañaAlOcr:
    def test_el_que_choca_con_otra_toma_el_de_la_serie(self):
        # 07-115 TOMO 1: la 088 leída «049»; 088-173 TOMO 2: la 173 leída «075».
        numeros = [49, 87, 49, 89]
        assert numeros_por_la_serie(numeros, [1998] * 4, [False, False, True, False]) == [
            (49, False), (87, False), (88, True), (89, False),
        ]
        assert numeros_por_la_serie([75, 172, 75, 2], [1997] * 4, [False, False, True, False])[2] == (173, True)

    def test_el_que_no_choca_se_respeta_aunque_salte(self):
        # 01-046 TOMO 3: la 138 de 1998 va detrás de la 001, y es la 138.
        assert numeros_por_la_serie([1, 138, 6], [1998, 1998, 1998], [False, True, False])[1] == (138, False)

    def test_sin_hueco_en_la_serie_no_se_inventa(self):
        assert numeros_por_la_serie([49, 87, 49, 88], [1998] * 4, [False, False, True, False])[2] == (49, False)


class TestElLegajoDeUnAnioSigueIgual:
    """Las internas de la 3303: un PDF por año, con «026» y «026-2014» en dos hojas."""

    def test_con_y_sin_anio_son_la_misma(self):
        sin_anio = "UNIVERSIDAD DE CARTAGENA\nRESOLUCIÓN No. 026\nPor la cual se aprueba el plan de estudios del programa"
        con_anio = "UNIVERSIDAD DE CARTAGENA\nRESOLUCIÓN No. 026-2014\nARTÍCULO SEGUNDO: continúa el plan de estudios"
        siguiente = "UNIVERSIDAD DE CARTAGENA\nRESOLUCIÓN No. 027-2014\nPor la cual se conforma el comité de bienestar"
        agrupacion, _ = clasificar([sin_anio, con_anio, siguiente])
        assert grupos(agrupacion) == [("026-2014", [1, 2]), ("027-2014", [3])]


class TestElEscritorNombraPorElAsunto:
    def test_cada_pdf_con_el_asunto_de_su_fila_y_que_quepa_en_el_destino(self, tmp_path):
        pymupdf = pytest.importorskip("pymupdf")
        from resolutions.adapters.pymupdf_assembler import PyMuPDFAssembler
        from resolutions.domain.grouping import GroupingResult

        origen = tmp_path / "07-115 TOMO 1.pdf"
        documento = pymupdf.open()
        for _ in range(3):
            documento.new_page()
        documento.save(origen)
        documento.close()
        grupos_ = [
            PageGroup(code=ResolutionCode.parse("PREVIAS-1"), page_numbers=[1], title="SOLICITUD DE EXAMEN"),
            PageGroup(code=ResolutionCode.parse("007-1998"), page_numbers=[2, 3]),
        ]
        asuntos = {"PREVIAS-1": "SOLICITUD DE EXAMEN", "007-1998": "RESOLUCION 007-1998 - FIJAR LA FECHA DEL EXAMEN: 15:00"}
        hondo = "C:\\" + "\\".join(["CARPETA DEL ESPEJO"] * 11)
        escritor = PyMuPDFAssembler(asunto_de=lambda g: asuntos[g.code.value], entregado_en=hondo)
        escrito = escritor.write(origen, GroupingResult(groups=grupos_), tmp_path / "salida")
        nombres = [ruta.name for ruta in escrito.outputs]
        assert nombres[0] == "01_SOLICITUD DE EXAMEN.pdf"
        # Sin los dos puntos que Windows no admite, y recortado para caber en el espejo.
        assert nombres[1].startswith("02_RESOLUCION 007-1998") and ":" not in nombres[1]
        assert len(hondo) + 1 + len(nombres[1]) <= 260


class TestLaQueAbreSinNumero:
    """La primera hoja con su encabezado y su emisor, y el número que nadie lee."""

    EN_BLANCO = (
        "UNIVERSIDAD DE CARTAGENA\nCartagena - Colombia\nResolución No.\nde 1.9\n"
        "EL CONSEJO DE LA FACULTAD DE ODONTOLOGÍA DE LA UNIVERSIDAD DE\nCARTAGENA, en uso de sus facultades\n"
        "RESUELVE:\nARTICULO 1o.- Aprobar el calendario de habilitaciones del segundo periodo de 1998.\n"
        "Dada en Cartagena a los 4 días de agosto de 1998."
    )

    def test_toma_el_numero_que_falta_en_la_serie(self):
        paginas = [
            decano("096", "Dada en Cartagena a los 2 días de julio de 1998."),
            decano("097", "Dada en Cartagena a los 3 días de julio de 1998."),
            SOLICITUD,
            self.EN_BLANCO,
            decano("099", "Dada en Cartagena a los 5 días de agosto de 1998."),
        ]
        agrupacion, stats = clasificar(paginas)
        assert grupos(agrupacion) == [
            ("096-1998", [1]), ("097-1998", [2, 3]), ("098-1998", [4]), ("099-1998", [5]),
        ]
        assert stats.sin_numero == {4: "sin número legible; la serie dice 098"}

    def test_si_el_hueco_no_cuadra_va_con_la_anterior(self):
        paginas = [
            decano("096", "Dada en Cartagena a los 2 días de julio de 1998."),
            decano("097", "Dada en Cartagena a los 3 días de julio de 1998."),
            self.EN_BLANCO,
            decano("101", "Dada en Cartagena a los 5 días de agosto de 1998."),
        ]
        agrupacion, stats = clasificar(paginas)
        assert grupos(agrupacion)[1] == ("097-1998", [2, 3])
        assert stats.sin_numero == {3: "abre una resolución sin número legible; va con la 097"}

    def test_la_palabra_sola_con_su_emisor_se_lee_en_la_banda(self):
        sola = self.EN_BLANCO.replace("Resolución No.\nde 1.9", "RESOLUCIÓN")
        paginas = [
            decano("058", "Dada en Cartagena a los 2 días de julio de 1998."),
            decano("059", "Dada en Cartagena a los 3 días de julio de 1998."),
            sola,
            decano("061", "Dada en Cartagena a los 5 días de agosto de 1998."),
        ]
        agrupacion, stats = clasificar(paginas, bandas={3: "RESOLUCIÓN No. 060"})
        assert grupos(agrupacion)[2] == ("060-1998", [3])
        assert stats.por_la_banda == [3]

    def test_loo_y_loi_son_la_100_y_la_101(self):
        condolencia = "UNIVERSIDAD DE CARTAGENA\nRESOLUCIÓN {}\nEL DECANO, LAS DIRECTIVAS, LOS DOCENTES Y EL PERSONAL"
        assert [c.code.value for c in extract_candidates(condolencia.format("loo")) if opens_a_resolution(c)] == ["100"]
        assert [c.code.value for c in extract_candidates(condolencia.format("loi")) if opens_a_resolution(c)] == ["101"]
        # «LOS» no es un número.
        assert extract_candidates("RESOLUCIÓN LOS DOCENTES\nEL DECANO DE LA FACULTAD") == []


class TestElMismoNumeroDosVecesSeguidas:
    def test_la_043_que_la_capa_lee_042(self):
        # El 3 escrito encima del 2: dos primeras hojas seguidas con el mismo número.
        paginas = [
            decano("041", "Dada en Cartagena a los 20 dias de mayo de 1998."),
            decano("042", "Dada en Cartagena a los 21 dias de mayo de 1998."),
            SOLICITUD,
            decano("042", "Dada en Cartagena a los 21 días de mayo de 1998."),
            SOLICITUD,
            decano("045", "Dada en Cartagena a los 22 dias de mayo de 1998."),
        ]
        agrupacion, stats = clasificar(paginas)
        assert grupos(agrupacion) == [
            ("041-1998", [1]), ("042-1998", [2, 3]), ("043-1998", [4, 5]), ("045-1998", [6]),
        ]
        assert 4 in stats.numero_por_la_serie

    def test_la_hoja_2_que_repite_el_encabezado_no_es_otra(self):
        hoja_2 = "UNIVERSIDAD DE CARTAGENA\nResolución No. 042\nARTICULO 2o.- Enviar copia al docente.\nDada en Cartagena a los 21 dias de mayo de 1998."
        paginas = [
            decano("041", "Dada en Cartagena a los 20 dias de mayo de 1998."),
            decano("042", ""),
            hoja_2,
            decano("045", "Dada en Cartagena a los 22 dias de mayo de 1998."),
        ]
        agrupacion, _ = clasificar(paginas)
        assert grupos(agrupacion)[1] == ("042-1998", [2, 3])

    def test_lo_que_la_banda_lee_sin_forma_de_numero_no_abre(self):
        # La banda de la pág. 39 del tomo 001-061 leyó «7770»: la serie dice 070.
        sola = TestLaQueAbreSinNumero.EN_BLANCO.replace("Resolución No.\nde 1.9", "RESOLUCIÓN")
        paginas = [
            decano("068", "Dada en Cartagena a los 2 días de julio de 1995."),
            decano("069", "Dada en Cartagena a los 3 días de julio de 1995."),
            sola.replace("1998", "1995"),
            decano("071", "Dada en Cartagena a los 5 días de agosto de 1995."),
        ]
        agrupacion, stats = clasificar(paginas, bandas={3: "RESOLUCIÓN No. 7770"})
        assert grupos(agrupacion)[2] == ("070-1995", [3])
        assert stats.por_la_banda == []


class TestLaFechaDeLaFila:
    def test_la_formula_con_el_en_cartagena_destrozado_da_su_fecha_y_no_la_de_la_serie(self):
        texto = (
            "RESOLUCIÓN No. 018\nRESUELVE:\nARTÍCULO 1o.- Fijar la fecha del JUEVES 16 DE ABRIL DE 1998 para el examen.\n"
            "Dada enjigrtagena a los 14 días de abril de 1998."
        )
        # La fecha de la unidad vino de la serie (la de su vecina): 02-04-1998.
        grupo = PageGroup(code=ResolutionCode.parse("018-1998"), page_numbers=[1], fecha="1998-04-02")
        [fila] = filas_de_resoluciones([grupo], nombre_del_archivo="x.pdf", texto_de=lambda _n: texto)
        assert (fila.fecha_inicial, fila.fecha_final) == ("14-04-1998", "14-04-1998")

    def test_con_la_formula_sana_manda_la_de_la_unidad(self):
        texto = "RESOLUCIÓN No. 018\nDada en Cartagena a los 14 días de abril de 1998."
        grupo = PageGroup(code=ResolutionCode.parse("018-1998"), page_numbers=[1], fecha="1998-04-14")
        [fila] = filas_de_resoluciones([grupo], nombre_del_archivo="x.pdf", texto_de=lambda _n: texto)
        assert fila.fecha_inicial == "14-04-1998"
