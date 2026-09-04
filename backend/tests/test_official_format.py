"""The house header format, taken from real documents.

Every header in the corpus is written one of these three ways::

    RESOLUCION NO. 00086
    Resolución No. 00072 de 2023
    RESOLUCIÓN No. 00083 de 2023

Accents, casing and the trailing year vary; the anchor, the numbering token and
the zero-padded number do not. These tests pin that structure, because it is
what decides where one output PDF ends and the next begins.
"""

from resolutions.domain.extraction import extract_candidates
from resolutions.domain.grouping import GroupingEngine
from resolutions.domain.page import PageClassification
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.scoring import CONFIDENT_FLOOR, opens_a_resolution, select_best

REAL_HEADERS = [
    ("RESOLUCION NO. 00086", "00086"),
    ("Resolución No. 00072 de 2023", "00072"),
    ("RESOLUCIÓN No. 00083 de 2023", "00083"),
]


class TestRealHeaders:
    def test_every_real_header_yields_its_number(self):
        for text, expected in REAL_HEADERS:
            assert [c.code.value for c in extract_candidates(text)] == [expected], text

    def test_the_trailing_year_is_not_mistaken_for_the_number(self):
        # "de 2023" follows the number and must never replace it.
        assert [c.code.value for c in extract_candidates("Resolución No. 00072 de 2023")] == [
            "00072"
        ]

    def test_a_header_split_across_two_lines_still_reads(self):
        assert [c.code.value for c in extract_candidates("RESOLUCIÓN\nNo. 00083 de 2023")] == [
            "00083"
        ]

    def test_the_numbering_token_glued_to_the_number_still_reads(self):
        assert [c.code.value for c in extract_candidates("RESOLUCION No.00086")] == ["00086"]


class TestOfficialFormSignal:
    def test_the_official_form_is_recognised_in_any_casing(self):
        for text, _ in REAL_HEADERS:
            assert extract_candidates(text)[0].official_form is True, text

    def test_a_title_cased_header_is_confident_without_capitals_to_lean_on(self):
        # Before the structure was scored, this page sat a hundredth above the
        # floor and any competing reading pushed it to the vision model.
        selection = select_best(extract_candidates("Resolución No. 00072 de 2023"))
        assert selection.confidence > CONFIDENT_FLOOR + 0.2
        assert selection.ambiguous is False

    def test_the_header_still_wins_over_a_citation_in_the_same_form(self):
        page = (
            "RESOLUCIÓN No. 00083 de 2023\n"
            "Por la cual se adopta el manual de contratación\n"
            "CONSIDERANDO que la Resolución No. 00072 de 2023 dispuso lo contrario"
        )
        selection = select_best(extract_candidates(page))
        assert selection.code.value == "00083"
        assert selection.ambiguous is False

    def test_a_citation_alone_is_not_promoted_by_its_shape(self):
        # The form says "this is a resolution number", never "this page is it".
        page = "CONSIDERANDO que la Resolución No. 00072 de 2023 dispuso lo contrario"
        assert extract_candidates(page)[0].official_form is True
        assert select_best(extract_candidates(page)).confidence < CONFIDENT_FLOOR

    def test_a_bare_number_with_no_numbering_token_is_not_the_official_form(self):
        assert extract_candidates("RESOLUCION 00086")[0].official_form is False


def as_pages(*headers):
    """Turn a run of page headers into classifications, ``None`` for no header."""
    from resolutions.domain.resolution_code import ResolutionCode

    return [
        PageClassification(
            page_number=index + 1,
            code=ResolutionCode.parse(str(select_best(extract_candidates(text)).code))
            if text
            else None,
        )
        for index, text in enumerate(headers)
    ]


class TestSplittingOnRealHeaders:
    """The rule end to end: a page with no header belongs to the last one seen."""

    def test_pages_without_a_header_stay_with_the_resolution_above_them(self):
        pages = as_pages(
            "RESOLUCION NO. 00086",
            None,  # page 2: body, no header
            None,  # page 3: body, no header
            "Resolución No. 00072 de 2023",
            None,  # page 5: body, no header
        )
        result = GroupingEngine().group(pages)
        assert {g.code.value: g.page_numbers for g in result.groups} == {
            "00086": [1, 2, 3],
            "00072": [4, 5],
        }
        result.verify_integrity(total_pages=5)

    def test_a_new_header_is_what_opens_the_next_output_pdf(self):
        pages = as_pages("RESOLUCION NO. 00086", None, "RESOLUCIÓN No. 00083 de 2023")
        result = GroupingEngine().group(pages)
        assert [g.code.value for g in result.groups] == ["00086", "00083"]
        assert [g.size for g in result.groups] == [2, 1]


class TestElEncabezadoConRuidoDelante:
    """Un filete delante del encabezado no puede costar una resolución entera.

    La 00964 del libro 00960-00979 está impresa entre dos rayas y su capa de
    texto sale tal cual aparece abajo. La condición anterior -- que el ancla
    estuviera en la columna cero -- la dejaba fuera, así que sus ocho páginas se
    archivaron dentro de la 00963 y la resolución desapareció del entregable sin
    un aviso, sin una página en revisión y sin un hueco visible entre los
    archivos. Las líneas de estas pruebas están copiadas de los documentos.
    """

    #: Capa de texto de la página 31 de "RESOLUCIONES 00960-00979.pdf".
    CON_FILETES = "____________ RESOLUCION NO. 00964 ______________________"
    #: Página 182 de "RESOLUCIONES 00072-00094.pdf": el escáner dejó un punto.
    CON_UN_PUNTO = ". RESOLUCIÓN No. 02461 de 2022"
    #: Página 306 del segundo libro: la fecha salió con una letra cambiada.
    CON_LA_FECHA_ROTA = "RESOLUCION NO 02500 DO 2022"

    def test_a_header_between_two_rules_opens_a_resolution(self):
        candidato = extract_candidates(self.CON_FILETES)[0]
        assert candidato.code.value == "00964"
        assert opens_a_resolution(candidato) is True

    def test_a_stray_dot_before_the_anchor_does_not_block_it(self):
        assert opens_a_resolution(extract_candidates(self.CON_UN_PUNTO)[0]) is True

    def test_one_bad_letter_in_the_date_does_not_cost_the_resolution(self):
        assert opens_a_resolution(extract_candidates(self.CON_LA_FECHA_ROTA)[0]) is True

    def test_the_letterhead_is_still_kept_out(self):
        # Va impreso en decenas de páginas y trae ancla, token y número. Lo que
        # lo delata es que detrás del ancla hay palabras: "Acreditación en Alta
        # Calidad" lo precede en el renglón.
        membrete = (
            "Acreditación en Alta Calidad Resolución No, 1968 dei 12 de febrero "
            "de 2018, MEN."
        )
        assert [c.code.value for c in extract_candidates(membrete)][0] == "1968"
        assert opens_a_resolution(extract_candidates(membrete)[0]) is False

    def test_a_citation_that_carries_on_talking_is_kept_out(self):
        # Página 288 del segundo libro. Delante del ancla el escáner dejó una
        # marca y ninguna palabra, así que sólo la frase que sigue al número la
        # distingue de un encabezado. Sin esto se llevaba doce páginas de la
        # resolución 00979.
        cita = (
            "■ Resolución No.02809 de noviembre 23 de 2022, se excluye al señor "
            "CHRISTIAN DAVID FERNANDEZ AVILA,"
        )
        assert opens_a_resolution(extract_candidates(cita)[0]) is False

    def test_the_three_house_formats_still_open(self):
        for text, _ in REAL_HEADERS:
            assert opens_a_resolution(extract_candidates(text)[0]) is True, text


class TestLaNumeracionDeLasFacultades:
    """Una resolución de decanatura se numera con el año, y también es una.

    Las facultades no numeran como rectoría. Donde rectoría escribe
    ``RESOLUCIÓN No. 00087``, una decanatura escribe ``RESOLUCIÓN No. 002-2023``:
    el consecutivo del año y el año, unidos por un guion. Exigir sólo dígitos
    dejaba esa forma fuera de lo que puede abrir una unidad documental.

    No era una rareza. En el libro 00072-00094 hay dos, y las dos con su
    encabezado, su CONSIDERANDO y su RESUELVE completos: la 002-2023 de la
    Facultad de Ciencias Sociales y Educación en el folio 118, y la 005-2023 de
    la misma facultad en el folio 150. Las dos se archivaban enteras dentro de
    la resolución de rectoría anterior, y la única señal que llegaba a la
    pantalla era un aviso de "códigos en conflicto" en la página.
    """

    #: Los dos encabezados, copiados de los folios 118 y 150 del libro.
    DECANATURA = [
        ("RESOLUCION No. 002-2023", "002-2023"),
        ("RESOLUCIÓN No. 005-2023", "005-2023"),
    ]

    def test_a_faculty_number_is_read_whole(self):
        for texto, esperado in self.DECANATURA:
            assert [c.code.value for c in extract_candidates(texto)] == [esperado], texto

    def test_a_faculty_header_opens_a_resolution(self):
        for texto, _ in self.DECANATURA:
            assert opens_a_resolution(extract_candidates(texto)[0]) is True, texto

    def test_the_year_is_part_of_the_number_and_not_the_number(self):
        # "002-2023" es un número entero: si el año se tomara por el número, dos
        # resoluciones distintas del mismo año acabarían en el mismo archivo.
        assert extract_candidates("RESOLUCION No. 002-2023")[0].code.value == "002-2023"

    def test_a_citation_of_one_still_opens_nothing(self):
        # Es la línea del folio 116, donde la 00087 cita a la que lleva anexa.
        cita = (
            "A. Que el decano de la FACULTAD DE CIENCIAS SOCIALES Y EDUCACION "
            "mediante resolución No. 002-2023 solicitó"
        )
        assert opens_a_resolution(extract_candidates(cita)[0]) is False

    def test_a_form_field_is_not_a_header_either(self):
        # Folios 119 a 122: el número va en una casilla de un formato, no en un
        # encabezado. Lo delata que detrás sigue habiendo formulario.
        campo = "No. Resolución: 002-2023 Fecha: 24/01/23"
        candidatos = extract_candidates(campo)
        assert candidatos and opens_a_resolution(candidatos[0]) is False


class TestDondeVaUnEncabezado:
    """Un encabezado va centrado y arriba, y eso no está en el texto.

    El folio 245 del libro 00960-00979 es un acta de comité. A media página
    contiene la frase "La Dra. Rosaura Arrieta Flórez realiza la respectiva
    sustentación de la…", que envuelve, y su segundo renglón empieza por
    "Resolución No. 00520 de 202.". Ese renglón cumple todo lo que se le pide a
    un encabezado por escrito -- abre su renglón, detrás sólo lleva la fecha,
    tiene la forma oficial -- y abrió un archivo de once páginas que no es
    ninguna resolución. Sobre el papel no había ninguna duda: estaba a media
    altura y pegado al margen izquierdo.

    Los umbrales están medidos sobre los 145 encabezados que abren una
    resolución en los dos libros de la Universidad: el más bajo está a 0,171 de
    altura y los centros caen entre 0,464 y 0,612. Las dos frases que se hacían
    pasar por encabezado están a 0,421 y 0,490 de altura, con centros en 0,217 y
    0,338.
    """

    #: El renglón exacto del folio 245, con su sitio en la página.
    FRASE = "Resolución No. 00520 de 202."
    FRASE_CENTRO, FRASE_ALTURA = 0.217, 0.421

    def con_sitio(self, texto, center_x, top):
        return extract_candidates(texto, [(center_x, top)])[0]

    def test_a_line_halfway_down_the_page_is_not_a_header(self):
        candidato = self.con_sitio(self.FRASE, self.FRASE_CENTRO, self.FRASE_ALTURA)
        assert candidato.code.value == "00520"
        assert opens_a_resolution(candidato) is False

    def test_the_same_line_would_pass_every_other_condition(self):
        # Es lo que la hacía peligrosa: sin geometría no hay nada que la delate.
        assert opens_a_resolution(extract_candidates(self.FRASE)[0]) is True

    def test_a_centred_header_at_the_top_opens_a_resolution(self):
        for texto, _ in REAL_HEADERS:
            assert opens_a_resolution(self.con_sitio(texto, 0.50, 0.11)) is True, texto

    def test_the_measured_extremes_of_the_real_books_still_open(self):
        # El encabezado más bajo (0,171), el más a la izquierda (0,464) y el más
        # a la derecha (0,612) de los dos libros. Si el umbral se apretara hasta
        # dejar fuera a alguno, costaría una resolución entera.
        for centro, altura in ((0.50, 0.171), (0.464, 0.11), (0.612, 0.069)):
            assert opens_a_resolution(self.con_sitio("RESOLUCION NO. 00086", centro, altura))

    def test_a_line_hugging_the_left_margin_is_not_a_header(self):
        assert opens_a_resolution(self.con_sitio("RESOLUCION NO. 00086", 0.12, 0.10)) is False

    def test_without_geometry_nothing_changes(self):
        # El OCR entrega texto sin coordenadas. Negarle el encabezado a una
        # página por no saber dónde estaba sería perder resoluciones justo en
        # las páginas que peor se leen.
        assert opens_a_resolution(extract_candidates("RESOLUCION NO. 00086")[0]) is True


class TestUnaResolucionDeRectoriaNoSeAbsorbe:
    """Que otra la cite no la convierte en un anexo.

    La 00080 dice en su título "se modifica la Resolución de Rectoría No. 02234".
    Con eso bastaba para absorberla, y el PDF de la 00080 salió con siete
    folios: cuatro suyos y tres de la 02234, que es una resolución de rectoría
    entera, con su escudo y su encabezado centrado. Dos resoluciones en un solo
    archivo.

    La diferencia está en la serie, y los propios documentos la dicen. Rectoría
    numera sólo con dígitos y sus resoluciones son unidades documentales del
    libro. Una facultad numera con el año detrás de un guion, y su resolución es
    el soporte de la que le responde: la 00087 dice "el decano de la FACULTAD…
    mediante resolución N° 002-2023 solicitó a este despacho".
    """

    def anunciada(self, texto, code):
        candidato = extract_candidates(texto, [(0.50, 0.11)])[0]
        return select_best([candidato], previous_code=ResolutionCode.parse("00080"),
                           announced_by_open_unit={code})

    def test_a_rectory_resolution_opens_even_when_it_was_cited(self):
        eleccion = self.anunciada("RESOLUCIÓN No 02234 de 2022", "02234")
        assert eleccion.code.value == "02234"

    def test_a_faculty_resolution_that_was_cited_is_absorbed(self):
        eleccion = self.anunciada("RESOLUCIÓN No. 002-2023", "002-2023")
        assert eleccion.code.value == "00080"
        # Y sin marcarla para revisión: se sabe exactamente qué es.
        assert eleccion.ambiguous is False

    def test_a_faculty_resolution_nobody_cited_still_opens(self):
        candidato = extract_candidates("RESOLUCIÓN No. 002-2023", [(0.50, 0.11)])[0]
        eleccion = select_best([candidato], previous_code=ResolutionCode.parse("00080"))
        assert eleccion.code.value == "002-2023"


class TestLaColaNoLlamaPorNada:
    """Dos falsas alarmas que llenaban la revisión de páginas correctas.

    Las cinco páginas que el libro 00960-00979 dejaba en revisión estaban bien
    archivadas, y llegaban ahí por dos motivos distintos que no eran conflictos.
    """

    def test_a_line_in_the_wrong_place_is_a_structural_rejection(self):
        # Folio 245: "Resolución No. 00520 de 202." a media página y pegada al
        # margen izquierdo. Se rechaza por dónde está, y eso no se discute: se
        # ve de un vistazo que no es un encabezado.
        candidato = extract_candidates("Resolución No. 00520 de 202.", [(0.217, 0.421)])[0]
        eleccion = select_best([candidato], previous_code=ResolutionCode.parse("00977"))
        assert eleccion.code.value == "00977"
        assert eleccion.ambiguous is False

    def test_a_rejection_in_the_right_place_is_still_worth_a_look(self):
        # Lo que _continues existe para marcar: centrada y arriba, sin verbo de
        # cita delante, y descartada sólo por no traer el token de numeración --
        # que es justo lo que pasa cuando el OCR se come el "No." de un
        # encabezado verdadero. Eso sí tiene que verlo una persona.
        candidato = extract_candidates("RESOLUCION 00520", [(0.50, 0.11)])[0]
        assert candidato.official_form is False
        eleccion = select_best([candidato], previous_code=ResolutionCode.parse("00977"))
        assert eleccion.code.value == "00977"
        assert eleccion.ambiguous is True

    def test_repeating_the_open_number_is_not_a_doubt(self):
        # Folios 186, 274 y 317: el cuerpo menciona de pasada la resolución en
        # la que la página ya está. Puntúa bajo, como debe, pero coincide con lo
        # abierto. Una página que no dice nada hereda en silencio; ésta no puede
        # salir peor parada por haber dicho lo mismo.
        mencion = "1. Analizar las hojas de vida de las aspirantes a la Resolución No. 00767"
        candidato = extract_candidates(mencion, [(0.532, 0.525)])[0]
        eleccion = select_best([candidato], previous_code=ResolutionCode.parse("00767"))
        assert eleccion.code.value == "00767"
        assert eleccion.ambiguous is False

    def test_a_genuine_tie_with_another_number_is_still_a_doubt(self):
        # Lo que la cola sí tiene que traer: dos números peleándose la página.
        pagina = "RESOLUCION No. 00412\nRESOLUCION No. 00555"
        candidatos = extract_candidates(pagina, [(0.50, 0.10), (0.50, 0.12)])
        assert len(candidatos) == 2
        eleccion = select_best(candidatos, previous_code=ResolutionCode.parse("00412"))
        assert eleccion.ambiguous is True


class TestLoQueElEscanerLePegaAlNumero:
    """Tres resoluciones que faltaban del libro, y cada una por un carácter.

    Las tres se leen perfectamente -- de la capa de texto o de la imagen -- y se
    perdían porque un solo carácter pegado al número impedía reconocerlo. No
    llegaban a producir ni un candidato, así que sus páginas se archivaban dentro
    de la resolución anterior y desaparecían del entregable sin un aviso.
    """

    #: Folio 47: la 00966 está impresa sobre una raya y el filete sale pegado.
    #: En el folio 31 la misma raya salió separada por un espacio, y por eso la
    #: 00964 sí se leía: la diferencia entre perder una resolución y no perderla
    #: era un espacio.
    CON_FILETE_PEGADO = "RESOLUCIÓN No. 00966_____________________________"
    #: Folios 208 y 209, leídos de la imagen: el OCR pone un asterisco o una
    #: interrogación donde el papel tiene el "°" de "N°".
    CON_ASTERISCO = "RESOLUCIÓN N* 00973"
    CON_INTERROGACION = "RESOLUCIÓN N? 00974"

    def test_the_three_are_read_and_open_a_resolution(self):
        esperado = {
            self.CON_FILETE_PEGADO: "00966",
            self.CON_ASTERISCO: "00973",
            self.CON_INTERROGACION: "00974",
        }
        for linea, codigo in esperado.items():
            candidatos = extract_candidates(linea, [(0.5, 0.09)])
            assert [c.code.value for c in candidatos] == [codigo], linea
            assert opens_a_resolution(candidatos[0]) is True, linea

    def test_the_rule_is_not_swallowed_into_the_number(self):
        # El filete no puede acabar dentro del código: el archivo se llamaría
        # "RESOLUCION_00966_____________.pdf".
        assert extract_candidates(self.CON_FILETE_PEGADO)[0].code.value == "00966"

    def test_a_faculty_number_keeps_its_hyphen(self):
        # Se recortan los bordes, no lo de dentro: "002-2023" es un número entero.
        assert extract_candidates("RESOLUCIÓN No. 002-2023")[0].code.value == "002-2023"
