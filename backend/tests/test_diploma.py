"""Lectura de un registro de diplomas.

Todos los textos de estas pruebas están copiados de los libros reales de la
Universidad de Cartagena -- los seis empastes N°08 digitalizados -- incluidos
sus defectos de OCR. Un caso inventado no habría descubierto que la leyenda
sale como "de! graduando" en 48 de 397 páginas, ni que un apellido puede ser
"CARTAGENA".
"""

from resolutions.domain.diploma import (
    DiplomaRecord,
    TextLine,
    extract_diploma,
    fecha_en_letras,
    lines_from_text,
    merge,
)


def lines(*textos: str) -> list[TextLine]:
    """Líneas en el orden en que se pasan, que es el orden vertical."""
    return [TextLine(text=t, y=float(i)) for i, t in enumerate(textos)]


# Página 1 del libro 6, tal como la devuelve la capa de texto.
PAGINA_COMPLETA = lines(
    "UNIVERSIDAD DE CARTAGENA",
    "Fundada en 1827",
    "LIBRO DE REGISTRO DE DIPLOMAS DE POSTGRADOS",
    "LA REPUBLICA DE COLOMBIA, Ministerio de Educación Nacional",
    "por intermedio de la UNIVERSIDAD DE CARTAGENA",
    "Folio 336BIS",
    "ALIX JOSEFINA MARIN RODRIGUEZ",
    "Nombres y apellidos del graduando",
    "Identificado con C.C. No. 22793650",
    "Titulo recibido: ESPECIALISTA EN GESTION DE LA CALIDAD Y AUDITORIA EN SALUD",
    "Fecha de graduación: 29/03/2012",
    "Registrado a folio No. 336BIS",
    "libro No. 8",
)


class TestPaginaCompleta:
    def test_lee_los_siete_campos(self):
        registro = extract_diploma(PAGINA_COMPLETA, page_number=1)
        assert registro.folio == "336BIS"
        assert registro.registered_folio == "336BIS"
        assert registro.book == "8"
        assert registro.name == "ALIX JOSEFINA MARIN RODRIGUEZ"
        assert registro.identity_number == "22793650"
        assert registro.graduation_date == "29/03/2012"
        assert registro.degree.startswith("ESPECIALISTA EN GESTION DE LA CALIDAD")

    def test_una_pagina_completa_no_necesita_revision(self):
        assert extract_diploma(PAGINA_COMPLETA, page_number=1).needs_review is False


class TestDanoDelOcr:
    def test_reconoce_la_leyenda_aunque_diga_de_en_vez_de_del(self):
        # Página 159 del libro 6: "Nombres y apellidos de! graduando".
        registro = extract_diploma(
            lines(
                "Folio 487",
                "FREDDY OMAR GRANADOS LLAMAS",
                "Nombres y apellidos de! graduando",
            ),
            page_number=159,
        )
        assert registro.name == "FREDDY OMAR GRANADOS LLAMAS"

    def test_no_confunde_un_apellido_con_el_nombre_de_la_ciudad(self):
        # Página 131: la graduanda se apellida CARTAGENA.
        registro = extract_diploma(
            lines(
                "por intermedio de la UNIVERSIDAD DE CARTAGENA",
                "Folio 459",
                "MIRLEY ESTHER CARTAGENA VIZCAINO",
                "Nombres y apellidos del graduando",
            ),
            page_number=131,
        )
        assert registro.name == "MIRLEY ESTHER CARTAGENA VIZCAINO"

    def test_nunca_toma_la_leyenda_impresa_como_nombre(self):
        registro = extract_diploma(
            lines(
                "por intermedio de ia UNiVERSiDAD DE CARTAGENA",
                "Folio 599",
                "Nombres y apellidos de! graduando",
            ),
            page_number=269,
        )
        assert registro.name is None
        assert "no se pudo leer el nombre" in registro.warnings[0]

    def test_avisa_cuando_el_nombre_trae_un_digito(self):
        # Página 269: el OCR escribe 2ABALETA donde el papel dice ZABALETA.
        registro = extract_diploma(
            lines(
                "Folio 599",
                "JOSE RAFAEL 2ABALETA ESCRUCERIA",
                "Nombres y apellidos de! graduando",
            ),
            page_number=269,
        )
        assert registro.name == "JOSE RAFAEL 2ABALETA ESCRUCERIA"
        assert any("no es una letra" in aviso for aviso in registro.warnings)


class TestFolioLeidoDosVeces:
    def test_avisa_cuando_las_dos_lecturas_del_folio_discrepan(self):
        # Página 213: la cabecera salió "Folio 5^" y el pie dice 543.
        registro = extract_diploma(
            lines("Folio 5", "ALGUIEN CON NOMBRE", "Nombres y apellidos del graduando",
                  "Registrado a folio No. 543"),
            page_number=213,
        )
        assert any("no coincide" in aviso for aviso in registro.warnings)

    def test_se_queda_con_la_lectura_mas_larga(self):
        registro = DiplomaRecord(page_number=213, folio="5", registered_folio="543")
        assert registro.trusted_folio == "543"

    def test_conserva_el_sufijo_bis_del_reverso(self):
        registro = DiplomaRecord(page_number=9, folio="340BIS", registered_folio="340")
        assert registro.trusted_folio == "340BIS"

    def test_no_avisa_cuando_las_dos_coinciden(self):
        assert extract_diploma(PAGINA_COMPLETA, page_number=1).warnings == []


class TestSegundoFormulario:
    def test_lee_la_plantilla_de_doctorados(self):
        # Páginas 302 y 303 del libro 6 usan otra plantilla.
        registro = extract_diploma(
            lines(
                "Folio 632",
                "JOSEFINA DEL CARMEN ZAKZUK SIERRA",
                "Nombres y apellidos del graduando",
                "Identificado con CC No. 1128050378",
                "Titulo de: DOCTOR EN CIENCIAS BIOMEDICAS",
                "Fecha de graduación; 28/02/2013",
                "Titulo registrado a folio No. 632",
                "libro No. 8",
            ),
            page_number=302,
        )
        assert registro.degree == "DOCTOR EN CIENCIAS BIOMEDICAS"
        assert registro.graduation_date == "28/02/2013"
        assert registro.registered_folio == "632"


class TestSelloAnulado:
    def test_detecta_el_sello(self):
        registro = extract_diploma(
            lines("ANULADO", "Folio 353", "LEIDYS JUDITH SALAMANCA MARTINEZ",
                  "Nombres y apellidos del graduando"),
            page_number=25,
        )
        assert registro.annulled is True

    def test_el_sello_no_se_toma_por_el_nombre(self):
        registro = extract_diploma(
            lines("ANULADO", "Folio 353", "Nombres y apellidos del graduando"),
            page_number=25,
        )
        assert registro.name is None


class TestIdentificacion:
    def test_admite_cedula_de_extranjeria(self):
        # Página 335 del libro 6.
        registro = extract_diploma(
            lines("Identificado con CE. No. 393598"), page_number=335
        )
        assert registro.identity_kind == "CE"
        assert registro.identity_number == "393598"

    def test_admite_la_cedula_sin_puntos(self):
        registro = extract_diploma(
            lines("identificado con CC. No. 45539417"), page_number=165
        )
        assert registro.identity_number == "45539417"


class TestSinDatos:
    def test_un_folio_en_blanco_no_inventa_nada(self):
        # Página 152 del libro 5: folio en blanco, tachado a mano con una X.
        registro = extract_diploma(lines(), page_number=152)
        assert registro.folio is None
        assert registro.name is None
        assert registro.graduation_date is None
        assert registro.is_complete is False


class TestSegundaLectura:
    def test_completa_solo_lo_que_faltaba(self):
        primera = DiplomaRecord(
            page_number=165,
            folio="493",
            registered_folio="493",
            book="8",
            name="OLGA BEATRIZ ALVAREZ ORTEGA",
            degree="ESPECIALIZACION EN INGENIERIA SANITARIA Y AMBIENTAL",
            graduation_date=None,
        )
        segunda = DiplomaRecord(page_number=165, graduation_date="19/10/2012")

        completo = merge(primera, segunda)
        assert completo.graduation_date == "19/10/2012"
        assert completo.name == "OLGA BEATRIZ ALVAREZ ORTEGA"
        assert completo.is_complete

    def test_no_pisa_un_valor_ya_leido(self):
        primera = DiplomaRecord(page_number=1, folio="338")
        segunda = DiplomaRecord(page_number=1, folio="33")
        assert merge(primera, segunda).folio == "338"


class TestTextoPlano:
    def test_el_orden_de_las_lineas_sirve_de_posicion(self):
        texto = "Folio 493\nOLGA BEATRIZ ALVAREZ ORTEGA\nNombres y apellidos del graduando"
        registro = extract_diploma(lines_from_text(texto), page_number=165)
        assert registro.name == "OLGA BEATRIZ ALVAREZ ORTEGA"


# -----------------------------------------------------------------------------
#  Los libros antiguos
# -----------------------------------------------------------------------------
#  El empaste manuscrito no es una ficha de registro: es el diploma mismo,
#  registrado al pie de su propia página. No rotula "Titulo recibido:" ni pone
#  la fecha en cifras, así que hay que leer lo que sí imprime -- "DOCTOR EN",
#  "en atención a que el Señor" y la fecha escrita con letras.
# -----------------------------------------------------------------------------

LIBRO_ANTIGUO = lines(
    "LA REPUBLICA DE COLOMBIA",
    "y en su nombre la",
    "UNIVERSIDAD DE CARTAGENA",
    "en atención a que el Señor",
    "MANUEL RUIZ YEPEZ",
    "ha completado todos los Estudios Clásicos que los Estatutos Universitarios",
    "exigen para optar el título de",
    "DOCTOR EN MEDICINA Y CIRUGIA",
    "le expide el presente Diploma.- Al mismo tiempo testifica y garantiza",
    "bajo la fé pública de que se halla investida por ministerio de la ley",
    "que dicho señor es idóneo para desempeñar la profesión de",
    "En testimonio de ello firmamos y sellamos con el sello mayor de la",
    "Facultad de Cartagena a los 10 días del mes de Mayo de mil novecientos",
    "setenta y dos.",
    "Registrado al folio No. 1018 del Libro No. 1 de registro de Diploma",
    "de la Rectoría de la Universidad de Cartagena",
)


class TestLibroAntiguo:
    def test_el_nombre_va_debajo_de_la_formula_y_no_encima(self):
        registro = extract_diploma(LIBRO_ANTIGUO, page_number=1)
        assert registro.name == "MANUEL RUIZ YEPEZ"

    def test_el_titulo_es_la_formula_entera(self):
        registro = extract_diploma(LIBRO_ANTIGUO, page_number=1)
        assert registro.degree == "DOCTOR EN MEDICINA Y CIRUGIA"

    def test_lee_la_fecha_escrita_con_letras(self):
        registro = extract_diploma(LIBRO_ANTIGUO, page_number=1)
        assert registro.graduation_date == "10/05/1972"

    def test_el_folio_y_el_libro_salen_de_la_formula_del_pie(self):
        registro = extract_diploma(LIBRO_ANTIGUO, page_number=1)
        assert registro.folio == "1018"
        assert registro.book == "1"

    def test_una_pagina_asi_esta_completa(self):
        assert extract_diploma(LIBRO_ANTIGUO, page_number=1).is_complete


class TestFechaEnLetras:
    def test_la_decena_sola(self):
        assert fecha_en_letras(
            "a los 5 días del mes de Enero de mil novecientos cincuenta"
        ) == "05/01/1950"

    def test_el_dia_escrito_con_letras(self):
        assert fecha_en_letras(
            "a los veinte días del mes de Agosto de mil novecientos sesenta y tres"
        ) == "20/08/1963"

    def test_un_ano_ilegible_no_se_completa(self):
        assert fecha_en_letras(
            "a los 10 días del mes de Mayo de mil novecientos ??????"
        ) is None

    def test_un_mes_que_no_existe_no_se_adivina(self):
        assert fecha_en_letras(
            "a los 10 días del mes de Maio de mil novecientos setenta"
        ) is None
