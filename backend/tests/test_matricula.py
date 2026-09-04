"""Lectura de un legajo de expedientes académicos.

Los textos son los de las páginas reales que envió el operador: la carátula de
MATRÍCULA ACADÉMICA de RAFAEL NICOLAS AREVALO POSADA y dos hojas de REGISTRO DE
ESTUDIOS con sus años de curso. Se prueban las dos formas en que llegan, porque
son distintas y las dos ocurren: la capa de texto de un PDF entrega una celda
por línea con sus coordenadas, y el OCR entrega la fila entera de corrido.
"""

from resolutions.application.matricula_fuid import filas_de_expedientes
from resolutions.application.matricula_split import group_by_student
from resolutions.domain.diploma import TextLine, lines_from_text
from resolutions.domain.matricula import (
    StudentPage,
    extract_student_page,
    group_students,
    merge_pages,
)
from resolutions.domain.validation import Severity, validate_matriculas


def columnas(*filas: tuple[float, tuple[tuple[float, str], ...]]) -> list[TextLine]:
    """Líneas con coordenadas, como las devuelve la capa de texto de un PDF."""
    return [
        TextLine(text=texto, y=y, x=x)
        for y, celdas in filas
        for x, texto in celdas
    ]


# La carátula tal como la entrega la capa de texto: la fila de leyendas y, justo
# debajo, la fila de valores, cada celda en su columna.
CARATULA = columnas(
    (0.0, ((120.0, "UNIVERSIDAD DE CARTAGENA"), (600.0, "MATRICULA ACADEMICA"),)),
    (14.0, ((120.0, "Admisiones Registro y Control Académico"),)),
    (
        40.0,
        (
            (30.0, "Cód. Estudiante"),
            (150.0, "Apellidos:"),
            (330.0, "Nombres:"),
            (520.0, "Carrera"),
            (620.0, "Año"),
            (700.0, "Periodo"),
        ),
    ),
    (
        62.0,
        (
            (30.0, "51-8710099"),
            (150.0, "AREVALO POSADA"),
            (330.0, "RAFAEL NICOLAS"),
            (520.0, "MEDICINA"),
            (620.0, "6o."),
            (700.0, "1o/93"),
        ),
    ),
    (100.0, ((30.0, "Cód. Materia"), (150.0, "ASIGNATURAS"))),
    (120.0, ((30.0, "9191"), (150.0, "ORTOPEDIA"))),
    (140.0, ((30.0, "9192"), (150.0, "OTORRINOLARINGOLOGIA"))),
)

#: La misma carátula leída por OCR, que no tiene coordenadas y devuelve la fila
#: entera en una línea, con los huecos de la máquina de escribir conservados.
CARATULA_OCR = lines_from_text(
    "UNIVERSIDAD DE CARTAGENA          MATRICULA ACADEMICA\n"
    "Admisiones Registro y Control Académico\n"
    "Cód. Estudiante   Apellidos:        Nombres:         Carrera    Año   Periodo\n"
    "51-8710099        AREVALO POSADA    RAFAEL NICOLAS   MEDICINA   6o.   1o/93\n"
    "Cód. Materia      ASIGNATURAS\n"
    "9191              ORTOPEDIA\n"
)

#: La primera hoja de asignaturas: cuatro cursos, de 1950 a 1953.
ESTUDIOS_PRIMERA = lines_from_text(
    "REGISTRO DE ESTUDIOS\n"
    "ASIGNATURAS  Nota de Examen Trimestral  Calificación de Prácticas\n"
    "PRIMER AÑO 1.950\n"
    "Anatomia 1a.        3\n"
    "Fisica Medica       3\n"
    "SEGUNDO AÑO 1.951\n"
    "Quimica Biologica   3\n"
    "TERCER AÑO 1.952\n"
    "Fisiologia Humana   3.05\n"
    "CUARTO AÑO 1.953\n"
    "Clinica Semiologica 4\n"
)

#: La última, que es la que fija la fecha final.
ESTUDIOS_ULTIMA = lines_from_text(
    "REGISTRO DE ESTUDIOS\n"
    "ASIGNATURAS  Nota de Examen Trimestral  Calificación Definitiva\n"
    "SEXTO AÑO 1.955\n"
    "Clinica Ginecologica   4.\n"
    "Higiene y Salud Publica 3.13\n"
    "Bio-estadistica        3.\n"
)


class TestCaratula:
    def test_lee_las_seis_casillas_de_la_capa_de_texto(self):
        hoja = extract_student_page(CARATULA, page_number=1)
        assert hoja.codigo == "51-8710099"
        assert hoja.apellidos == "AREVALO POSADA"
        assert hoja.nombres == "RAFAEL NICOLAS"
        assert hoja.carrera == "MEDICINA"
        assert hoja.anio_en_curso == "6"
        assert hoja.periodo == "1/93"

    def test_lee_lo_mismo_cuando_el_ocr_devuelve_la_fila_de_corrido(self):
        hoja = extract_student_page(CARATULA_OCR, page_number=1)
        assert hoja.codigo == "51-8710099"
        assert hoja.apellidos == "AREVALO POSADA"
        assert hoja.nombres == "RAFAEL NICOLAS"
        assert hoja.carrera == "MEDICINA"

    def test_el_nombre_va_en_el_orden_del_formulario(self):
        hoja = extract_student_page(CARATULA, page_number=1)
        assert hoja.nombre == "AREVALO POSADA RAFAEL NICOLAS"

    def test_una_caratula_abre_expediente(self):
        assert extract_student_page(CARATULA, page_number=1).abre_expediente is True

    def test_devuelve_a_su_casilla_el_ano_que_vino_pegado_a_la_carrera(self):
        # Las dos columnas van seguidas y sus valores son cortos: cuando el
        # hueco entre "ODONTOLOGIA" y "3o." es estrecho, el lector las entrega
        # unidas. Están escritas las dos, así que se despegan.
        pegado = columnas(
            (
                0.0,
                (
                    (30.0, "Cód. Estudiante"),
                    (150.0, "Apellidos:"),
                    (330.0, "Nombres:"),
                    (520.0, "Carrera"),
                    (620.0, "Año"),
                    (700.0, "Periodo"),
                ),
            ),
            (
                20.0,
                (
                    (30.0, "51-8810200"),
                    (150.0, "MARTINEZ ROA"),
                    (330.0, "ANA LUCIA"),
                    (520.0, "ODONTOLOGIA 3o."),
                    (700.0, "2o/94"),
                ),
            ),
        )
        hoja = extract_student_page(pegado, page_number=1)
        assert hoja.carrera == "ODONTOLOGIA"
        assert hoja.anio_en_curso == "3"

    def test_el_periodo_de_dos_cifras_no_se_convierte_en_un_ano(self):
        # "1o/93" es 1993 por costumbre y 1893 por aritmética. El cartón no lo
        # dice, así que aquí no hay fecha.
        assert extract_student_page(CARATULA, page_number=1).anios == ()


class TestRegistroDeEstudios:
    def test_lee_un_ano_por_curso(self):
        hoja = extract_student_page(ESTUDIOS_PRIMERA, page_number=2)
        assert hoja.anios == ("1950", "1951", "1952", "1953")

    def test_quita_el_punto_de_los_millares(self):
        hoja = extract_student_page(ESTUDIOS_ULTIMA, page_number=3)
        assert hoja.anios == ("1955",)

    def test_una_hoja_de_asignaturas_no_abre_expediente(self):
        assert extract_student_page(ESTUDIOS_PRIMERA, page_number=2).abre_expediente is False

    def test_no_inventa_un_nombre_donde_no_lo_hay(self):
        hoja = extract_student_page(ESTUDIOS_PRIMERA, page_number=2)
        assert hoja.nombre is None
        assert hoja.codigo is None

    def test_no_pide_revision_por_no_llevar_nombre(self):
        # El nombre está en su carátula, que es otra hoja. Escalar esta página a
        # OCR sería gastar el presupuesto buscando algo que no está impreso.
        assert extract_student_page(ESTUDIOS_PRIMERA, page_number=2).needs_review is False


class TestExpediente:
    def _legajo(self):
        return group_students(
            [
                extract_student_page(CARATULA, page_number=1),
                extract_student_page(ESTUDIOS_PRIMERA, page_number=2),
                extract_student_page(ESTUDIOS_ULTIMA, page_number=3),
            ]
        )

    def test_las_hojas_sin_nombre_se_juntan_con_su_caratula(self):
        expedientes = self._legajo()
        assert len(expedientes) == 1
        assert expedientes[0].page_numbers == [1, 2, 3]

    def test_las_fechas_extremas_son_el_primer_y_el_ultimo_ano(self):
        expediente = self._legajo()[0]
        assert expediente.fecha_inicial == "1950"
        assert expediente.fecha_final == "1955"

    def test_los_folios_son_las_hojas_del_expediente(self):
        assert self._legajo()[0].folios == 3

    def test_una_caratula_nueva_abre_otro_expediente(self):
        otra = StudentPage(
            page_number=4, codigo="51-8710100", apellidos="MARTINEZ", nombres="ANA"
        )
        expedientes = group_students(
            [
                extract_student_page(CARATULA, page_number=1),
                extract_student_page(ESTUDIOS_PRIMERA, page_number=2),
                otra,
            ]
        )
        assert [expediente.page_numbers for expediente in expedientes] == [[1, 2], [4]]

    def test_dos_caratulas_del_mismo_codigo_son_un_solo_expediente(self):
        # Un estudiante con dos matrículas tiene dos carátulas y un expediente.
        segunda = StudentPage(
            page_number=4,
            codigo="51-8710099",
            apellidos="AREVALO POSADA",
            nombres="RAFAEL NICOLAS",
        )
        expedientes = group_students(
            [extract_student_page(CARATULA, page_number=1), segunda]
        )
        assert len(expedientes) == 1
        assert expedientes[0].page_numbers == [1, 4]

    def test_las_hojas_previas_a_la_primera_caratula_no_se_pierden(self):
        expedientes = group_students(
            [
                extract_student_page(ESTUDIOS_PRIMERA, page_number=1),
                extract_student_page(CARATULA, page_number=2),
            ]
        )
        assert [expediente.page_numbers for expediente in expedientes] == [[1], [2]]
        assert expedientes[0].nombre is None


class TestSegundaLectura:
    def test_el_ocr_llena_lo_que_falta_y_no_pisa_lo_leido(self):
        primera = StudentPage(page_number=1, apellidos="AREVALO POSADA")
        segunda = StudentPage(
            page_number=1,
            codigo="51-8710099",
            apellidos="AREVAL0 P0SADA",
            nombres="RAFAEL NICOLAS",
        )
        fundida = merge_pages(primera, segunda)
        assert fundida.codigo == "51-8710099"
        assert fundida.nombres == "RAFAEL NICOLAS"
        assert fundida.apellidos == "AREVALO POSADA"


class TestFilasDelFuid:
    def _filas(self):
        expedientes = group_students(
            [
                extract_student_page(CARATULA, page_number=1),
                extract_student_page(ESTUDIOS_PRIMERA, page_number=2),
                extract_student_page(ESTUDIOS_ULTIMA, page_number=3),
            ]
        )
        return filas_de_expedientes(
            expedientes, nombre_del_archivo="7. 3858081 MATRICULAS.pdf"
        )

    def test_una_fila_por_estudiante(self):
        assert len(self._filas()) == 1

    def test_el_asunto_lleva_el_nombre_y_la_carrera(self):
        assert self._filas()[0].asunto == "AREVALO POSADA RAFAEL NICOLAS - MEDICINA"

    def test_el_consecutivo_es_el_codigo_del_estudiante(self):
        assert self._filas()[0].consecutivo_inicial == "51-8710099"

    def test_las_fechas_extremas_son_los_anos_leidos(self):
        fila = self._filas()[0]
        assert (fila.fecha_inicial, fila.fecha_final) == ("1950", "1955")

    def test_el_upd_sale_del_nombre_del_archivo(self):
        assert self._filas()[0].carpeta == "3858081"

    def test_los_folios_son_las_hojas(self):
        assert self._filas()[0].folios == 3

    def test_las_notas_situan_el_expediente_en_el_pdf(self):
        notas = self._filas()[0].notas
        assert "Período 1/93" in notas
        assert "Páginas 1 a 3 del documento de origen" in notas

    def test_lo_que_no_se_leyo_sale_como_no_aplica(self):
        filas = filas_de_expedientes(
            group_students([extract_student_page(ESTUDIOS_ULTIMA, page_number=1)]),
            nombre_del_archivo="sin-upd.pdf",
        )
        assert filas[0].asunto == "N/A"
        assert filas[0].consecutivo_inicial == "N/A"
        assert filas[0].carpeta == "N/A"


class TestDivision:
    def test_un_archivo_por_estudiante_con_todas_sus_hojas(self):
        expedientes = group_students(
            [
                extract_student_page(CARATULA, page_number=1),
                extract_student_page(ESTUDIOS_PRIMERA, page_number=2),
                extract_student_page(ESTUDIOS_ULTIMA, page_number=3),
            ]
        )
        resultado = group_by_student(expedientes)
        assert len(resultado.groups) == 1
        assert resultado.groups[0].page_numbers == [1, 2, 3]
        assert resultado.groups[0].code.value == "51-8710099"


class TestComprobaciones:
    def test_señala_el_expediente_sin_dueño(self):
        expedientes = group_students([extract_student_page(ESTUDIOS_PRIMERA, page_number=1)])
        motivos = [issue.reason for issue in validate_matriculas(expedientes)]
        assert any("nombre del estudiante" in motivo for motivo in motivos)

    def test_señala_el_codigo_que_abre_dos_expedientes(self):
        # Dos carátulas seguidas con el mismo código son un estudiante con dos
        # matrículas. Separadas por otro estudiante ya no: o una se leyó con el
        # código de la otra, o el legajo trae las hojas descolocadas.
        uno = StudentPage(page_number=1, codigo="51-8710099", apellidos="AREVALO POSADA")
        otro = StudentPage(page_number=3, codigo="51-8710100", apellidos="MARTINEZ ROA")
        repetido = StudentPage(
            page_number=5, codigo="51-8710099", apellidos="GOMEZ PEREZ"
        )
        issues = validate_matriculas(group_students([uno, otro, repetido]))
        assert any(issue.field == "codigo" for issue in issues)

    def test_señala_los_anos_que_retroceden(self):
        # Las fechas extremas saldrían bien igual -- son el menor y el mayor --
        # y por eso hay que mirar el orden impreso: un curso posterior fechado
        # antes que el anterior sólo puede ser una cifra mal leída.
        hoja = StudentPage(
            page_number=1,
            codigo="51-8710099",
            apellidos="AREVALO POSADA",
            nombres="RAFAEL NICOLAS",
            anios=("1955", "1950"),
        )
        registro = group_students([hoja])[0]
        assert (registro.fecha_inicial, registro.fecha_final) == ("1950", "1955")
        issues = validate_matriculas([registro])
        retroceso = [issue for issue in issues if issue.field == "fecha"]
        assert retroceso and retroceso[0].severity is Severity.ERROR
