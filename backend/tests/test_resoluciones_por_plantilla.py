"""Resoluciones de rectoría: cada página por su plantilla, y lo que se leía mal.

Medido el 2026-10-16 sobre la carpeta RESOLUCIONES DE RECTORIA 3220 - 3259
(40 cajas, 247 PDF). Todos los textos son de páginas reales, con sus defectos.
"""

from datetime import date

from fakes import FakeOcr, FakePage, FakePageSource

from resolutions.application.clasificacion import fechar
from resolutions.application.fuid import caja_de_la_ruta, upd_del_archivo
from resolutions.application.pipeline import ClassificationPipeline, PipelineConfig
from resolutions.application.resolution_fuid import filas_de_resoluciones
from resolutions.domain.extraction import extract_candidates
from resolutions.domain.fechas import fecha_de_expedicion
from resolutions.domain.grouping import GroupingEngine, GroupingResult, PageGroup
from resolutions.domain.plantilla_de_pagina import Plantilla, plantilla_de
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.scoring import opens_a_resolution, select_best
from resolutions.domain.title import extract_title

RECTORIA_00316 = (
    "Universidad\nde Cartagena\nRESOLUCIÓN No. 00316 DE 2025\n"
    "“Por medio de la cual se autorizan ceremonia de grado”\n"
    "EL RECTOR DE LA UNIVERSIDAD DE CARTAGENA\nen uso de sus facultades legales y,\nCONSIDERANDO\n"
    "A. Que el decano de la FACULTAD DE CIENCIAS SOCIALES Y EDUCACION mediante resolución \n"
    "N° 006 del 21 del mes de febrero del año 2025 solicitó a este despacho autorización de grado"
)
FACULTAD_006 = (
    "Universidad\nde Cartagena\nUNIVERSIDAD DE CARTAGENA\nRESOLUCIÓN No. 006\n"
    "EL DECANO DE LA FACULTAD DE CIENCIAS SOCIALES Y EDUCACION\nEn uso de sus atribuciones legales y,\n"
    "CONSIDERANDO\nEN SESIÓN del consejo de facultad se aprobó la relación de graduandos del programa"
)
FACULTAD_006_HOJA_2 = (
    "UNIVERSIDAD DE CARTAGENA\nRESOLUCIÓN No. 006\n15. CC 1121845760\n16. CC 1050963013\n"
    "17. CC 1047436363 relación de graduandos que continúa en la hoja siguiente del documento"
)
OFICIO = (
    "Facultad de Enfermería\nAcreditación en Alta Calidad Resolución\nNo. 1968 del 12 de febrero de 2018, MEN.\n"
    "Cartagena, 11 de febrero de 2025\nDoctora\nKATIA JOLY VILLAREAL\nCordial saludo,\n"
    "Realizamos entrega de Resolución de Decanatura 006, paz y salvo académico y soportes"
)
RECTORIA_00317 = (
    "Universidad\nde Cartagena\nRESOLUCIÓN No. 00317 DE 2025\n"
    "“Por medio de la cual se acepta una renuncia”\nEL RECTOR DE LA UNIVERSIDAD DE CARTAGENA\n"
    "en uso de sus facultades legales y estatutarias y en especial las que le confiere el estatuto"
)


class TestLaPlantillaDeCadaPagina:
    def test_la_resolucion_de_rectoria(self):
        assert plantilla_de(RECTORIA_00316).plantilla is Plantilla.RESOLUCION_DE_RECTORIA

    def test_la_del_decano_es_de_facultad(self):
        assert plantilla_de(FACULTAD_006).plantilla is Plantilla.RESOLUCION_DE_FACULTAD

    def test_la_decana_tambien(self):
        texto = "UNIVERSIDAD DE CARTAGENA\nRESOLUCIÓN No. 005\nLA DECANA DE LA FACULTAD DE ENFERMERIA\nEn uso de sus atribuciones legales y, CONSIDERANDO"
        assert plantilla_de(texto).plantilla is Plantilla.RESOLUCION_DE_FACULTAD

    def test_el_considerando_que_nombra_al_decano_no_la_vuelve_de_facultad(self):
        """«Que el decano de la FACULTAD…» es una frase del rector, no su emisor."""
        assert plantilla_de(RECTORIA_00316).plantilla is not Plantilla.RESOLUCION_DE_FACULTAD

    def test_el_oficio(self):
        assert plantilla_de(OFICIO).plantilla is Plantilla.OFICIO

    def test_el_formulario_con_un_campo_que_cita_una_resolucion(self):
        """El de apertura de un posgrado: «Resolución No.002086 de 1984» se llevaba 70 páginas."""
        texto = "\n".join(
            [
                "CÓDIGO: FO-DO/PC-012", "DOCENCIA", "Universidad", "de Cartagena", "VERSIÓN: 02",
                "SOLICITUD DE APERTURA DE PROGRAMAS DE", "POSTGRADO", "FECHA: 13-07-2018",
                "1-DATOS DEL PROGRAMA:", "NOMBRE DEL PROGRAMA ACADEMICO:", "30",
                "NUMERO DE PROMOCIÓN:", "CUPO MAxIMO:", "UBICACIÓN DEL PROGRAMA:",
                "Resolución No.002086 de 1984", "NORMA INTERNA DE CREACIÓN;",
            ]
        )
        assert plantilla_de(texto).plantilla is Plantilla.FORMULARIO

    def test_una_resolucion_impresa_sobre_un_formato_sigue_siendo_resolucion(self):
        """La copia de la 02852 de 2024 lleva «CÓDIGO: FO-TH/SE-021»."""
        texto = "\n".join(
            [
                "Cartagena - Colombia", "Resolución No. 02852 de 2024", "Hoja No 5",
                "CÓDIGO: FO-TH/SE-021", "VERSIÓN: 01", "ARTÍCULO QUINTO: Comuníquese",
            ]
        )
        assert plantilla_de(texto).plantilla is Plantilla.RESOLUCION_DE_RECTORIA

    def test_la_tabla(self):
        tabla = "\n".join(["2.1.1.01.03.001.01.03.2001 2087 62.500.000 0 0"] * 20)
        assert plantilla_de(tabla).plantilla is Plantilla.TABLA

    def test_la_pagina_sin_texto(self):
        assert plantilla_de("■ ^ i").plantilla is Plantilla.ILEGIBLE

    def test_el_cuerpo_sin_senal(self):
        texto = "ARTÍCULO 13° El responsable del manejo de la Caja Menor presentará dentro de los siete días"
        assert plantilla_de(texto).plantilla is Plantilla.CUERPO


def clasificar(paginas):
    fuente = FakePageSource(pages=[FakePage(text=t) for t in paginas])
    pipeline = ClassificationPipeline(
        ocr=FakeOcr(), config=PipelineConfig(max_workers=1, verify_declarations=False)
    )
    clasificaciones, stats = pipeline.classify(fuente)
    return GroupingEngine().group(clasificaciones), stats


class TestElSoporteNoAbre:
    def test_la_resolucion_del_decano_va_dentro_de_la_de_rectoria(self):
        """00316: la 006 se quedaba con 192 de las 200 páginas del PDF."""
        agrupacion, stats = clasificar([RECTORIA_00316, FACULTAD_006, FACULTAD_006_HOJA_2, RECTORIA_00317])
        assert [(g.code.value, g.page_numbers) for g in agrupacion.groups] == [
            ("00316", [1, 2, 3]),
            ("00317", [4]),
        ]
        assert stats.soportes == {2: str(Plantilla.RESOLUCION_DE_FACULTAD), 3: "hoja de un soporte"}

    def test_el_oficio_con_el_membrete_tampoco_abre(self):
        agrupacion, _ = clasificar([RECTORIA_00316, OFICIO])
        assert [g.code.value for g in agrupacion.groups] == ["00316"]

    def test_al_principio_la_de_facultad_abre_porque_no_hay_a_quien_soportar(self):
        agrupacion, _ = clasificar([FACULTAD_006])
        assert [g.code.value for g in agrupacion.groups] == ["006"]

    def test_el_informe_cuenta_las_plantillas(self):
        _, stats = clasificar([RECTORIA_00316, FACULTAD_006, OFICIO])
        assert stats.plantillas[str(Plantilla.RESOLUCION_DE_RECTORIA)] == 1
        assert stats.plantillas[str(Plantilla.OFICIO)] == 1


def candidato(texto):
    return extract_candidates(texto)[0]


class TestElEncabezadoMalLeido:
    def test_la_particula_con_punto(self):
        """00191: «RESOLUCIÓN N°. 00191» no daba ni un candidato."""
        c = candidato("RESOLUCIÓN N°. 00191 DE 2025")
        assert c.code.value == "00191" and c.official_form

    def test_el_numero_que_el_ocr_partio(self):
        """00185: «No. 001 85» se leía «001» y se llevaba otra resolución."""
        assert candidato("RESOLUCIÓN No. 001 85 de 2025").code.value == "00185"

    def test_un_numero_y_un_anio_no_se_juntan(self):
        assert candidato("RESOLUCIÓN No. 006 2025").code.value == "006"

    def test_el_numero_pegado_a_su_particula_abre(self):
        """00204: «RESOLUCIÓN No.00204 de 2025» se archivaba dentro de la 00203."""
        assert opens_a_resolution(candidato("RESOLUCIÓN No.00204 de 2025"))

    def test_una_cita_sigue_sin_abrir(self):
        assert not opens_a_resolution(candidato("RESOLUCION NO.02809 DE 2022, SE EXCLUYE AL SENOR"))

    def test_la_de_facultad_anunciada_es_soporte(self):
        anterior = ResolutionCode(value="00316", raw="00316")
        seleccion = select_best(
            [candidato("RESOLUCIÓN No. 006")], previous_code=anterior, announced_by_open_unit={"006"}
        )
        assert seleccion.code.value == "00316"

    def test_la_de_rectoria_anunciada_sigue_abriendo(self):
        """Decisión vigente: la 02234 citada por la 00080 es su propio archivo."""
        anterior = ResolutionCode(value="00080", raw="00080")
        seleccion = select_best(
            [candidato("RESOLUCIÓN No. 02234 de 2024")], previous_code=anterior, announced_by_open_unit={"02234"}
        )
        assert seleccion.code.value == "02234"


class TestElAsunto:
    def test_un_asunto_con_fechas_no_es_un_fechado(self):
        texto = (
            "RESOLUCIÓN No 00005 DE 2025\n“Por medio de la cual se cierra la vigencia fiscal comprendida "
            "entre 1° de enero y el 31 diciembre de 2024”\nEL RECTOR DE LA UNIVERSIDAD DE CARTAGENA"
        )
        assert extract_title(texto).startswith("Por medio de la cual se cierra la vigencia fiscal")

    def test_el_asunto_de_varios_renglones_va_entero(self):
        texto = (
            "RESOLUCIÓN No 00001 de 2025\n“Por medio del cual se realiza el cierre presupuestal y se\n"
            "incorporan los saldos no ejecutados\nGeneral de Regalías del bienio 2025-2026”\n"
            "EL SEÑOR RECTOR DE LA UNIVERSIDAD DE CARTAGENA"
        )
        assert extract_title(texto).endswith("General de Regalías del bienio 2025-2026")

    def test_la_cual_que_el_ocr_leyo_eual(self):
        texto = "RESOLUCIÓN No. 00008 DE 2025\ni\nPor medio de la eual se designan los docentes de cátedra\nHoja No. 1"
        assert extract_title(texto) == "Por medio de la cual se designan los docentes de cátedra"

    def test_la_l_que_el_ocr_leyo_como_exclamacion(self):
        """La 00667 de 2025: «¡a cual … e! procedimiento … Centra!» en cinco renglones."""
        texto = (
            "RESOLUCIÓN No. 00667 DE 2025\n\"\"Por medio de ¡a cual se establece e! procedimiento para la\n"
            "elección de los Representantes ante ei Consejo Superior, Comité Centra! de\n"
            "Admisiones, Consejo de Bienestar\nUniversitario, periodo 2025-2027 y se establecen\n"
            "otras estrategias de divulgación\"\nEL RECTOR DE U UNIVERSIDAD DE CARTAGENA"
        )
        titulo = extract_title(texto)
        assert titulo.startswith("Por medio de la cual se establece el procedimiento")
        assert "ante el Consejo Superior, Comité Central de" in titulo
        assert titulo.endswith("otras estrategias de divulgación")

    def test_quien_firma_mal_leido_no_entra_en_el_asunto(self):
        """La 00678 de 2025: «El Rector» leído «K1 Rector»."""
        texto = (
            "RESOLUCIÓN No 00678 DE 2025\nPor medio de la cual se cubren los gastos de desplazamiento.\n"
            "K1 Rector de la Universidad de Cartagena\nen uso de sus facultades legales y,"
        )
        assert extract_title(texto) == "Por medio de la cual se cubren los gastos de desplazamiento"

    def test_nada_del_considerando_es_un_titulo(self):
        """La 00668 de 2025: sin asunto, el respaldo tomaba «No,40 de 1996, Estatuto General»."""
        texto = (
            "COMISION Y OTORGAMIENTO DE VIATICOS ^3\nPARA TRABAJADORES Y DOCENTES DE\nPLANTA\n"
            "UNIVERSIDAD DE CARTAGENA\nFUNDADA EN 1827\nRESOLUCIÓN No. 00668 De 2025\n"
            "EL RECTOR DE LA UNIVERSIDAD DE CARTAGENA EN USO DE SUS FACULTADES LEGALES,\n"
            "ESTATUTARIAS Y\nCONSIDERANDO:\nQue el Rector es el ordenador del gasto, conforme al artículo 35\n"
            "No,40 de 1996, Estatuto General y artículo 62 y 66 Ley 30 de 1992."
        )
        assert extract_title(texto) is None
        assert (
            extract_title(texto, titulo_encima=True)
            == "COMISION Y OTORGAMIENTO DE VIATICOS PARA TRABAJADORES Y DOCENTES DE PLANTA"
        )

    def test_el_membrete_encima_no_es_un_titulo(self):
        texto = "UNIVERSIDAD DE CARTAGENA\nFUNDADA EN 1827\nRESOLUCIÓN No. 00700 DE 2025\nCONSIDERANDO:\nQue el Rector"
        assert extract_title(texto, titulo_encima=True) is None


class TestLaFechaDeExpedicion:
    def test_en_letra_y_en_cifra(self):
        texto = "Dada en Cartagena de Indias, a los dieciséis (16) días del mes de enero del año 2025."
        assert fecha_de_expedicion([texto]) == date(2025, 1, 16)

    def test_con_el_anio_roto_lo_suple_el_encabezado(self):
        paginas = ["RESOLUCIÓN No. 00004 de 2025", "Dada en Cartagena de Indias, a los dieciséis (16) días del mes de enero del añe^lOlS."]
        assert fecha_de_expedicion(paginas) == date(2025, 1, 16)

    def test_la_primera_es_la_suya_y_no_la_del_soporte(self):
        paginas = [
            "Dada en Cartagena de Indias, a los 3 días del mes de marzo del año 2025.",
            "Dada en Cartagena, a los 21 días del mes de febrero de 2025",
        ]
        assert fecha_de_expedicion(paginas) == date(2025, 3, 3)

    def test_dado_en_masculino_tambien_es_la_formula(self):
        """2026-10-29: la 00384 dice «Dado en Cartagena», y sin reconocerlo se
        fechaba con el «28 de Marzo» de la resolución del decano que lleva detrás."""
        paginas = [
            "RESOLUCIÓN No. 00384 DE 2025 COMUNÍQUESE Y CÚMPLASE. "
            "Dado en Cartagena, a los 28 días del mes de febrero del año 2025",
            "ceremonia colectiva de graduación el día Viernes 28 de Marzo de 2025",
        ]
        assert fecha_de_expedicion(paginas) == date(2025, 2, 28)
        assert fecha_de_expedicion(["Expedido en Cartagena, a los 3 días del mes de marzo de 2025"]) == date(2025, 3, 3)

    def test_las_formulas_que_deja_el_ocr(self):
        """Las de la carpeta 3220 - 3259 (2026-10-29), tal como las dejó el OCR."""
        casos = {
            # 03524: el mes destrozado y el año con punto de miles.
            "Dada en Cartagena de Indias a los diecinueve (19) días del mes de diciemtMp de 2.025": date(2025, 12, 19),
            # 03526: el «a los» destrozado y el mes pegado a su «de».
            "Dada en Cartagena de IndiasjJ^/Cftpcinueve (19) días del mes de diciembrpyde 2.025": date(2025, 12, 19),
            # 03527: «ios» por «los» y «diciemb^».
            "Dada en Cartagena de Indias a ios dipcinueve (19) días del mes de diciemb^ de 2.025": date(2025, 12, 19),
            # 03529: sin «los» y sin «del mes».
            "Dada en Cartagena de Iridias, a 19 días de diciembre de 2025": date(2025, 12, 19),
        }
        for texto, esperada in casos.items():
            assert fecha_de_expedicion([texto]) == esperada, texto

    def test_el_anio_roto_lo_pone_el_encabezado(self):
        # 02991: «de 20^.»
        paginas = ["RESOLUCIÓN No. 02991 de 2025 Dada en Cartagena de Indias ^dT)s seis (06) días del mes de Noviembre de 20^."]
        assert fecha_de_expedicion(paginas, numero="02991") == date(2025, 11, 6)

    def test_no_se_fecha_con_la_formula_de_otra_resolucion(self):
        """00390: la suya es ilegible («a Ij i;») y la del decano, detrás, decía 24 de febrero."""
        paginas = [
            "RESOLUCIÓN No. 00390 DE 2025 COMUNÍQUESE Y CÚMPLASE. Dado en Cartagena, a Ij i; KATIA JOLY",
            "UNIVERSIDAD DE CARTAGENA RESOLUCIÓN No. 15 EL DECANO Dado en Cartagena, a los 24 días del mes de Febrero de 2025",
        ]
        assert fecha_de_expedicion(paginas, numero="00390") is None
        # Sin decir de qué resolución es, se comporta como antes.
        assert fecha_de_expedicion(paginas) == date(2025, 2, 24)

    def test_la_misma_resolucion_en_sus_hojas_siguientes_sigue_contando(self):
        paginas = [
            "RESOLUCIÓN No 03523 de 2025 “Por medio de la cual se modifica la Resolución de Rectoría No. 02591”",
            "RESOLUCIÓN No 03523 de 2025 Dada en Cartagena de Indias a los diecinueve (19) días del mes de diciembre de 2025",
        ]
        assert fecha_de_expedicion(paginas, numero="03523") == date(2025, 12, 19)

    def test_fechar_la_prefiere_a_la_mas_reciente(self):
        """La 00005 se fechaba por el listado del sistema que lleva detrás."""
        grupo = PageGroup(code=ResolutionCode(value="00005", raw="00005"), page_numbers=[1, 2])
        textos = {
            1: "Dada en Cartagena de Indias, a los 16 días del mes de enero del año 2025.",
            2: "Fecha: 06/02/2025 listado de registros presupuestales",
        }
        fechado = fechar(GroupingResult(groups=[grupo]), textos.get)
        assert fechado.groups[0].fecha == "2025-01-16"


class TestDondeEstaElPapel:
    def test_la_caja_y_la_carpeta_salen_de_la_ruta(self):
        ruta = "3220\\UPD3859348\\1 RESOLUCIONES DE RECTORIAN 00001 A 00011.pdf"
        assert caja_de_la_ruta(ruta) == "3220"
        assert upd_del_archivo(ruta) == "3859348"

    def test_un_pdf_suelto_no_inventa_caja(self):
        assert caja_de_la_ruta("suelto.pdf") == "N/A"


class TestLaFilaDelFuid:
    def test_numero_asunto_y_fecha(self):
        grupo = PageGroup(
            code=ResolutionCode(value="00002", raw="00002"),
            page_numbers=[17, 18, 19, 20],
            title="Por medio de la cual se fija cronograma de ceremonia de grado para Cartagena",
            fecha="2025-01-16",
        )
        fila = filas_de_resoluciones(
            [grupo], nombre_del_archivo="3220\\UPD3859348\\1 RESOLUCIONES 00001 A 00011.pdf"
        )[0]
        assert fila.asunto == (
            "RESOLUCION 00002 POR MEDIO DE LA CUAL SE FIJA CRONOGRAMA DE CEREMONIA DE GRADO PARA CARTAGENA"
        )
        assert (fila.consecutivo_inicial, fila.consecutivo_final) == ("00002", "00002")
        assert (fila.fecha_inicial, fila.fecha_final) == ("16-01-2025", "16-01-2025")
        assert (fila.caja, fila.carpeta, fila.folios) == ("3220", "3859348", 4)


class TestLaSecuencia:
    """Encabezados con la palabra «resolución» destrozada por el OCR."""

    def test_la_siguiente_de_la_serie_abre_aunque_el_ancla_no_se_lea(self):
        """00676: «RHSOIAJCIÓN No 00676 DE 2025» se archivaba dentro de la 00675."""
        siguiente = "Universidad\nde Cartagena\n9\nRHSOIAJCIÓN No 00676 DE 2025\nPor medio de la cual se cubren los gastos"
        agrupacion, stats = clasificar(
            ["Universidad\nRESOLUCIÓN No 00675 DE 2025\nPor medio de la cual se cubren los gastos\nEL RECTOR DE LA UNIVERSIDAD", siguiente]
        )
        assert [g.code.value for g in agrupacion.groups] == ["00675", "00676"]
        assert stats.por_secuencia == [2]

    def test_la_letra_decorativa_de_una_condolencia(self):
        """00592: «^oLVcióa^í^ 00592 <u lois»."""
        agrupacion, _ = clasificar(
            [
                "Universidad\nRESOLUCIÓN No 00591 de 2025\nPor medio de la cual se aprueba un Programa de Posgrado\nEl Rector",
                "UNICARTAGENA\nBICENTENARIA\n^oLVcióa^í^ 00592 <u lois\n'En uso de sus facultades legales, CONSIDERANDO que el 24 de marzo",
            ]
        )
        assert [g.code.value for g in agrupacion.groups] == ["00591", "00592"]

    def test_un_numero_cualquiera_en_la_cabecera_no_abre(self):
        agrupacion, _ = clasificar(
            [
                "Universidad\nRESOLUCIÓN No 00591 de 2025\nPor medio de la cual se crea una Caja Menor\nEl Rector",
                "CAJA MENOR 00592 pesos\ncuadro de gastos de la vigencia con sus rubros presupuestales y valores",
            ]
        )
        assert [g.code.value for g in agrupacion.groups] == ["00591"]

    def test_la_hoja_siguiente_de_la_abierta_no_abre_la_que_sigue(self):
        """La cabecera repite el número de la abierta: es su hoja, aunque cite la siguiente."""
        agrupacion, _ = clasificar(
            [
                "Universidad\nRESOLUCIÓN No 00591 de 2025\nPor medio de la cual se aprueba\nEl Rector",
                "RESOLUCIÓN No 00591 de 2025\nResolución 00592 que se expide en la misma fecha y continúa el texto",
            ]
        )
        assert [g.code.value for g in agrupacion.groups] == ["00591"]
