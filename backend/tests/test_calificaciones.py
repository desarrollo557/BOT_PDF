"""Los libros de calificaciones de Odontología: cada lista y cada alumno, un PDF y una fila (2026-11-27).

Lo pidió el operador sobre «8. ACTA 9 FACULTAD DE ODONTOLOGIA CALIFICACIONES
3194 - 3198». Los textos tienen la forma de la capa de texto real de los seis
libros -- con sus errores: «CONLINUACION», «11.9010017», «129210134», el nombre
pegado de la lista, la constancia de cabeza -- y nombres y cédulas inventados.
"""

from __future__ import annotations

import pytest

from resolutions.adapters.fuid_de_la_entrega import CONVERSORES
from resolutions.adapters.fuid_de_la_entrega import fila_del_fuid as fila_de_la_entrega
from resolutions.adapters.fuid_historias import fila_del_fuid
from resolutions.domain.calificaciones import (
    ASIGNATURAS,
    CALIFICACIONES,
    CONSTANCIA,
    CONTINUACION,
    LISTA,
    LISTA_DE_ALUMNOS,
    LISTA_SIGUE,
    RECORD,
    AlumnoDeLaLista,
    alumnos_de_la_lista,
    anio_del_codigo,
    anios_de_las_notas,
    asunto_de_calificaciones,
    cuadre_con_la_lista,
    de_cabeza,
    emparejar_con_la_lista,
    es_libro_de_calificaciones,
    evidencia_de_calificaciones,
    mismo_alumno,
    nombre_completo,
    nombre_de_la_hoja,
    plantilla_de_calificaciones,
    titulo_de_la_lista,
    unidades_del_libro,
)

# -- las hojas, con la forma de su capa de texto ------------------------------------------

LISTA_1995 = (
    "-- ALUMNOS X SEMESTRE DE ODONTOLOGIA 2O. PERIODO 1995 3, 9 1. 9010072 PEREZMORALESANDREAC. ^ "
    "2. 9110106 QUINTERO SALAS BRUNO E. ^ 3^ 3. 9110128 RINCON TOVAR CAMILA S. / 4. 9110010 "
    "SOTO URIBE DIANA P.^ ALO 3,FZ"
)
#: La pág. 2 de la lista: las últimas filas, sin encabezado y con el orden seguido.
LISTA_1995_SIGUE = "5. 9110029 TAPIAS VERA ELENA V ' 6.9110035 ULLOA ZAPATA FABIO. > T ( F. * IM0C/OYF 3,^9"


def constancia(nombre: str = "", anio: int = 1990) -> str:
    """La hoja A de 1995-1997: «HACE CONSTAR Que, NOMBRE, cursó y aprobó…». Sin nombre, la raya en blanco."""
    renglon = f"QUE, {nombre}, CURSO Y APROBO" if nombre else "QUE________________________ ____________ , CURSO Y APROBO"
    return (
        "AL CONTESTAR CITESE ESTE NUMERO DEPENDENCIA UNIVERSIDAD DE CARTAGENA FUNDADA EN 1 827 EL SECRETARIO "
        "ACADEMICO DE LA FACULTAD DE ODONTOLOGIA DE LA UNIVERSIDAD DE CARTAGENA HACE CONSTAR "
        f"{renglon} EN ESTA FACULTAD, EL 1O., 2O., 3O., 4O., 5O., 6O., 7O 8O.,9O. Y 10O. SEMESTRE DE "
        f"ODONTOLOGIA, CON LAS SIGUIENTES CALIFICACIONES: 1ER. SEMESTRE {anio} - BIOQUIMICA - BIOLOGIA "
        "3.10 TRES-UNO-CERO 4.10 CUATRO-UNO-CERO II SEMESTRE - MORFOLOGIA 3.40 TRES-CUATRO-CERO"
    )


def continuacion(nombre: str = "") -> str:
    """La hoja B: «Continuación calificaciones de NOMBRE»; sin nombre, el formulario en blanco de 1995."""
    if not nombre:
        return (
            "AL CONTESTAR CITESE ESTE NUMERO DEPENDENCIA UNIVERSIDAD DE CARTAGENA (I CONTINUACION CALIFICACIONES "
            "DE VI SEMESTRE - ODONTOPEDIATRIA __ - RESTAURADORA II __ - CLINICA INTEGRADAS 1 VIL SEMESTRE - "
            "PRINCIPIOS DE INVESTIGACION ____ ADMINISTRACION GENERAL"
        )
    return (
        "H AL CCMSITESTAR CITESE ESTE NUMERO EPENOENCIA UNIVERSIDAD DE CARTAGENA CONLINUACION CALIFICACIONES "
        f"DE {nombre} 2 V SEMESTRE - RESTAURADORA I Y MATERIALES DENTALES - INFORMATICA 3.40 TRES-CUATRO-CERO "
        "VI SEMESTRE - ODONTOPEDIATRIA - RESTAURADORA II - CLINICA INTEGRADAS 1 3.70 TRES-SIETE-CERO"
    )


#: El formulario en blanco que la capa sólo lee «VI SEMESTRE - Odontopediatría…» (1995).
FORMULARIO_EN_BLANCO = (
    "AL CONTESTAR CITESE ESTE NUMERO OEPENOENCIA UNIVERSIDAD DE CARTAGENA 'HI>TM^ 2 VI SEMESTRE - "
    "ODONFOPEDBTFIA __ - RESTAURADORA II __ - CLINICA INTEGRADAS 1 3 3I ^> VIL SEMESTRE - PRINCIPIOS "
    "DE INVESTIGACION ____ ADMINISTRACION G"
)


def record(nombre: str, cedula: str = "73.000.111", codigo: str = "529010099") -> str:
    """La hoja A de 1998 en adelante: la ficha de ingreso con su record académico."""
    return (
        f"I UNIVERSIDAD DE CARTAGENA FACULTAD DE ODONTOLOGIA {nombre} NOMBRE DEL ESTUDIANTE DIRECCION ACTUAL "
        "BARRIO MANGA CALLE 5 TELEFONO 6600000 CARTAGENA, 12 DE SEPTIEMBRE LUGAR Y FECHA DE NACIMIENTO "
        "ESTADO CIVIL SOLTERO NOMBRE DE LOS PADRES ANA RUEDA - JOSE CASTRO BACHILLER DEL COLEGIO INEM "
        f"C.C. # {cedula} CODIGO {codigo} LIBRETA MILITAR PRUEBA DEL ICFES RECORD ACADEMICO PROMEDIO "
        "ARITMETICO DE CALIFICACIONES FECHA DE GRADO 17 DICIEMBRE DE 1998 ACTA NO 01 DIPLOMA NO 13242 "
        "ASIGNATURAS SEM 1ER AÑO 1990"
    )


def asignaturas(nombre: str) -> str:
    """La hoja B del record: el nombre arriba y la tabla de notas."""
    return (
        f"{nombre} ASIGNATURAS ASIGNATURAS HABIL. CALIF. SEM V HABIL. SEM VI AÑO 1993 CALIF. ANESTESIA Y "
        "CIRUGIA 3.40 4,10 ENDODONCIA 2.80 NOTA: NOTA:"
    )


CARTA = (
    "CARTAGENA DE INDIAS D. T. Y C. 9 DE DICIEMBRE DE 1998 DOCTOR CESAR HERRERA ZARATE SECRETARIO ACADEMICO "
    "FACULTAD DE ODONTOLOGIA CIUDAD ESTIMADO DOCTOR: CON LA PRESENTE HAGO CONSTAR QUE MI NOMBRE SE ESCRIBE "
    "COMO APARECE EN MI CEDULA DE CIUDADANIA"
)
COPIA_DE_CEDULA = (
    "REPUBLICA DE COLOMBIA IDENTIFICACION PERSONAL CEDULA DE CIUDADANIA 52.000.477 FECHA DE NACIMIENTO "
    "17-FEB-1979 CARTAGENA LUGAR DE NACIMIENTO 1.59 ESTATURA"
)
#: La constancia de cabeza: así deja la capa «UNIVERSIDAD DE CARTAGENA … HACE CONSTAR» (1995, pág. 81).
DE_CABEZA = (
    "BOIJFUIY JNS - BQUIO)03 - BUBEBUBO 561 IBJSOJ TI DVLSNOO 30VH VN3OVIDVO 3A AVAISD3AINN VN 30 "
    "VIOOIOINOAO 3A AVIINOVJ"
)


# -- qué es cada hoja ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "esperada"),
    [
        (LISTA_1995, LISTA),
        ("UNIVERSIDAD DE CARTAGENA PROMOCIÓN 20 DE DICIEMBRE DE 1996 Promedio Puesto 1. PEREZ ANA LUCIA", LISTA),
        ("FACULTAD DE ODONTOLOGIA ALUMNOS A SEMESTRE 2O. PERIODO 2002 CODIGO NOMBRE I S. II S. PROM.", LISTA),
        ("'IAZ FACULTAD DE ODONTOLOGIA ALU M N O S X SE ME EI T R E 1 E R. P E RL O D O 2003", LISTA),
        (constancia("ANDREA C. PEREZ MORALES"), CONSTANCIA),
        (constancia(), CONSTANCIA),
        (continuacion("ANDREA C. PEREZ MORALES"), CONTINUACION),
        (continuacion(), CONTINUACION),
        (FORMULARIO_EN_BLANCO, CONTINUACION),
        (record("LUIS ALBERTO RUEDA CASTANO"), RECORD),
        (asignaturas("LUIS A. RUEDA CASTANO"), ASIGNATURAS),
        (DE_CABEZA, CONSTANCIA),
        (CARTA, None),
        (COPIA_DE_CEDULA, None),
    ],
)
def test_la_plantilla_de_cada_hoja(texto, esperada):
    assert plantilla_de_calificaciones(texto) == esperada


def test_la_lista_sin_encabezado_por_sus_filas_y_no_por_las_notas():
    """Cinco filas con su código son lista; «1 Y MATERIALES DENTALES» en una continuación, no (1995, pág. 43)."""
    filas = " ".join(f"{n}. 91100{n:02d} APELLIDO{chr(64 + n)} SEGUNDO NOMBRE" for n in range(41, 47))
    assert plantilla_de_calificaciones(filas) == LISTA_SIGUE
    nota = continuacion("ARLETH S. HERRERA A.") + " NOTA: HABILITO LA ASIGNATURA DE RESTAURADORA 1 Y MATERIALES DENTALES"
    assert plantilla_de_calificaciones(nota) == CONTINUACION


def test_la_hoja_de_cabeza_se_reconoce():
    assert de_cabeza(DE_CABEZA)
    assert not de_cabeza(constancia("ANDREA C. PEREZ MORALES"))


# -- la lista --------------------------------------------------------------------------------


def test_la_lista_tolera_el_ruido_de_la_capa():
    """«11.9010017», «1 9210360», «129210134» (el 12 pegado), el nombre pegado y la pág. 2 con las últimas filas."""
    texto = (
        "ALUMNOS X SEMESTRE DE ODONTOLOGIA 2O. PERIODO 1997 1 9210360 BENITEZ ROA JUAN E. / 3.67 "
        "2 9310093 CASTRO DIAZ INES Y 3.79 11.9010017 DE LA VALLE ARCHILA MONICA 129210134 DIAZ ARANA GLORIA "
        "PATRICIA ^ 3.68"
    )
    filas = alumnos_de_la_lista([texto])
    assert [(f.orden, f.codigo, f.nombre) for f in filas] == [
        (1, "9210360", "BENITEZ ROA JUAN E"),
        (2, "9310093", "CASTRO DIAZ INES"),
        # «11.» después del 2 no es el 11: es la fila que sigue.
        (3, "9010017", "DE LA VALLE ARCHILA MONICA"),
        (4, "9210134", "DIAZ ARANA GLORIA PATRICIA"),
    ]
    dos_paginas = alumnos_de_la_lista([LISTA_1995, LISTA_1995_SIGUE])
    assert [f.orden for f in dos_paginas] == [1, 2, 3, 4, 5, 6]
    assert dos_paginas[0].nombre == "PEREZMORALESANDREAC"
    assert dos_paginas[-1].codigo == "9110035"


def test_la_lista_de_2003_con_codigos_de_once_cifras_y_la_de_1996_sin_codigo():
    tesseract = (
        "FACULTAD DE ODONTOLOGIA ALUMNOS X SEMESTRE 20, FERIODO 2002 [No]CODIGO NOMBRE 1S. "
        "[1 |52199810009 [ARANDA BELTRAN MILENA 4.36 250 [2 |52199810051 [ARBOLEDA SALAS SILVIA S. 365 "
        "3 |52199910164 [BARRIOS SANTANA ELAYNE E | 4 52199610008 |BARBOSA DE ORO LUIS GERARDO 345"
    )
    filas = alumnos_de_la_lista([tesseract])
    assert [f.codigo for f in filas] == ["52199810009", "52199810051", "52199910164", "52199610008"]
    assert filas[0].nombre == "ARANDA BELTRAN MILENA"
    sin_codigo = (
        "PROMOCION 20 DE DICIEMBRE DE 1996 PROMEDIO PUESTO 1. AGUAS POLO TANIA CECILIA / 2. ALVARO CUETO MARTA "
        "LUCIA 3. ANAYA VELEZ XIMENA DEL C. / 4. ANGULO SALAS JANNIA M ^ 5. ARNEDO AMOR MARTA LUZ / 6. ARTUZ "
        "POSADA GUSTAVO ADOLFO < I. BARROS BERMEO GUSTAVO A. I 8. BEDOYA MONTOYA VERONICA C."
    )
    filas = alumnos_de_la_lista([sin_codigo])
    assert [f.orden for f in filas] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert filas[6].nombre.startswith("BARROS BERMEO GUSTAVO")
    assert all(f.codigo is None for f in filas)


@pytest.mark.parametrize(
    ("texto", "titulo", "anio", "fecha"),
    [
        (LISTA_1995, "LISTA DE ALUMNOS X SEMESTRE DE ODONTOLOGIA - 2 PERIODO 1995", 1995, None),
        ("PROMOCIÓN 20 DE DICIEMBRE DE 1996 Promedio Puesto", "PROMOCION 20-12-1996", 1996, "20/12/1996"),
        (
            "FACULTAD DE ODONTOLOGIA ALUMNOS A SEMESTRE 2O. PERIODO 2002 CODIGO",
            "LISTA DE ALUMNOS X SEMESTRE DE ODONTOLOGIA - 2 PERIODO 2002", 2002, None,
        ),
        (
            "ALU M N O S X SE ME EI T R E 1 E R. P E RL O D O 2003",
            "LISTA DE ALUMNOS X SEMESTRE DE ODONTOLOGIA - 1 PERIODO 2003", 2003, None,
        ),
    ],
)
def test_el_titulo_impreso_de_la_lista(texto, titulo, anio, fecha):
    hallado = titulo_de_la_lista(texto)
    assert (hallado.titulo, hallado.anio, hallado.fecha) == (titulo, anio, fecha)


# -- el nombre ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "nombre"),
    [
        (constancia("ANDREA C. PEREZ MORALES"), "ANDREA C PEREZ MORALES"),
        (constancia(), None),
        (continuacion("RUBEN O. MERCADO N."), "RUBEN O MERCADO N"),
        (record("LUIS ALBERTO RUEDA CASTANO"), "LUIS ALBERTO RUEDA CASTANO"),
        (asignaturas("R { ; .IHONNY RAFAEL ANAYA MARIN"), "IHONNY RAFAEL ANAYA MARIN"),
    ],
)
def test_el_nombre_que_trae_cada_hoja(texto, nombre):
    assert nombre_de_la_hoja(texto) == nombre


@pytest.mark.parametrize(
    ("lista", "hoja", "otras", "esperado"),
    [
        # La inicial de la lista, completada con la hoja; los apellidos primero, como la lista.
        ("RUEDA CASTANO LUIS A.", "LUIS ALBERTO RUEDA CASTANO", (), "RUEDA CASTANO LUIS ALBERTO"),
        # El nombre pegado por la capa, partido por la hoja.
        ("PEREZMORALESANDREAC", "ANDREA C. PEREZ MORALES", (), "PEREZ MORALES ANDREA C"),
        # El segundo nombre que la lista calla va al final; la dirección pegada al renglón, no.
        ("ANAYA MARIN JHONY", "JHONNY RAFAEL ANAYA MARIN", (), "ANAYA MARIN JHONY RAFAEL"),
        ("VECINO RANGEL LILIANA", "LILIANA VECINO RANGEL BUENOS AIRES DIAGONAL", (), "VECINO RANGEL LILIANA"),
        # «LI» leído «U» en la hoja: es la misma palabra, y la lista y la otra hoja votan.
        ("VALIENTE PEREZ ELSA DEL C.", "ELSA DEL CARMEN VAUENTE PEREZ", ("ELSA DEL C. VALIENTE PEREZ",),
         "VALIENTE PEREZ ELSA DEL CARMEN"),
        # Sin hoja, la lista tal cual; sin lista, la hoja con los apellidos primero.
        ("OLIER PIMIENTA VILMA MARIA", None, (), "OLIER PIMIENTA VILMA MARIA"),
        (None, "LUCY MARGARITA OTERO FRANCO", (), "OTERO FRANCO LUCY MARGARITA"),
    ],
)
def test_el_nombre_completo(lista, hoja, otras, esperado):
    assert nombre_completo(lista, hoja, otras) == esperado


@pytest.mark.parametrize(
    ("texto", "cedula"),
    [
        ("FECHA DE GRADO 3 DE DIC./87 C.C 4 73.141.230 DE CARTAGENA CODIGO 529010027", "73141230"),
        ("FECHA DE GRADO 27 DE NOV,/92 C.C. * _45,766,044 DE _ CARTAGENA", "45766044"),
        ("TELEFONO C.C. # 46.766 044 DE CARTAGENA", "46766044"),
        ("C.C. 45.766.044 DE CARTAGENA", "45766044"),
        ("C.C. # 73.141.^30 J3G", None),
    ],
)
def test_la_cedula_de_la_casilla_del_record(texto, cedula):
    """El «#» leído «4», «*» o «_» y los miles con punto, coma o espacio (1998, págs. 3 y 7)."""
    from resolutions.domain.calificaciones import cedula_del_record

    assert cedula_del_record(texto) == cedula


def test_hermanas_no_son_el_mismo_alumno():
    """GOMEZ DIAZ MARTHA PATRICIA y GOMEZ DIAZ PAOLA MILENA comparten los apellidos y no son la misma (1996)."""
    assert not mismo_alumno("MARTHA PATRICIA GOMEZ DIAZ", "PAOLA MILENA GOMEZ DIAZ")
    assert mismo_alumno("LUCY MARGARITA OTERO FRANCO", "LUCY M. OTERO FRANCO")


def test_el_asunto_es_el_nombre_y_la_especialidad():
    assert asunto_de_calificaciones("PEREZ MORALES ANDREA C") == "PEREZ MORALES ANDREA C - ODONTOLOGIA"


# -- los años --------------------------------------------------------------------------------------


def test_los_anios_de_sus_notas_y_el_periodo_de_la_lista():
    """La constancia sólo escribe el año del primer semestre: el último es el del periodo de la lista."""
    assert anios_de_las_notas([constancia("ANDREA C. PEREZ MORALES", 1990)], 1995) == (1990, 1995)
    assert anios_de_las_notas([asignaturas("LUIS A. RUEDA CASTANO")], 1998) == (1993, 1998)
    assert anios_de_las_notas(["sin años"], 1995) == (None, 1995)
    assert (anio_del_codigo("9010072"), anio_del_codigo("52199810009"), anio_del_codigo("529010027")) == (
        1990, 1998, 1990,
    )


# -- el emparejamiento con la lista -------------------------------------------------------------------


def test_el_emparejamiento_por_orden_y_por_nombre():
    """Una fila que la capa no leyó no corre a las demás; un alumno sin nombre va por su orden."""
    filas = [
        AlumnoDeLaLista(1, None, "ARANA BELLO ANA"),
        AlumnoDeLaLista(2, None, "BARRIOS CANO LUIS"),
        # la 3, CARDENAS DIAZ PEDRO, no se leyó
        AlumnoDeLaLista(4, None, "DURAN ESPINOSA MARIA"),
        AlumnoDeLaLista(5, None, "ESCOBAR FUENTES JOSE"),
    ]
    lecturas = [["ANA ARANA BELLO"], [], ["PEDRO CARDENAS DIAZ"], ["MARIA DURAN ESPINOSA"], []]
    assert emparejar_con_la_lista(lecturas, filas) == [0, 1, None, 2, 3]


# -- el reparto del libro -------------------------------------------------------------------------------


def _libro_1995() -> list[str]:
    return [
        LISTA_1995,  # 1
        LISTA_1995_SIGUE,  # 2
        constancia("ANDREA C. PEREZ MORALES", 1990),  # 3 alumno 1
        continuacion("ANDREA C. PEREZ MORALES"),  # 4
        continuacion(),  # 5 la B del alumno 2, escaneada antes de su A
        constancia("", 1991),  # 6 alumno 2, a mano
        constancia("", 1991),  # 7 alumno 3, a mano
        FORMULARIO_EN_BLANCO,  # 8
        constancia("DIANA PATRICIA SOTO URIBE", 1991),  # 9 alumno 4
        continuacion("DIANA P. SOTO URIBE"),  # 10
        constancia("DIANA PATRICIA SOTO URIBE", 1991).replace("CURSO Y APROBO", "HA CURSADO"),  # 11: la 2.ª suya
        CARTA,  # 12 anexo
        DE_CABEZA,  # 13 alumno 5, de cabeza
        continuacion(),  # 14
        constancia("FABIO ULLOA ZAPATA", 1991),  # 15 alumno 6
        continuacion("FABIO ULLOA ZAPATA"),  # 16
    ]


def test_el_libro_se_reparte_en_su_lista_y_sus_alumnos():
    textos = _libro_1995()
    unidades = unidades_del_libro(textos)
    listas = [u for u in unidades if u.tipo == LISTA_DE_ALUMNOS]
    alumnos = [u for u in unidades if u.tipo == CALIFICACIONES]
    assert [u.paginas for u in listas] == [[1, 2]]
    assert [u.paginas for u in alumnos] == [[3, 4], [5, 6], [7, 8], [9, 10, 11, 12], [13, 14], [15, 16]]
    # Cada página en exactamente un documento.
    assert sorted(p for u in unidades for p in u.paginas) == list(range(1, len(textos) + 1))
    # La B escaneada antes de su A va con su A, y lo dice.
    segundo = alumnos[1]
    assert (segundo.hojas_a, segundo.hojas_b) == ([6], [5])
    assert any("va antes de su apertura" in duda for duda in segundo.dudas)


def test_cada_alumno_con_su_fila_y_su_nombre():
    alumnos = [u for u in unidades_del_libro(_libro_1995()) if u.tipo == CALIFICACIONES]
    assert [u.de_la_lista.orden for u in alumnos] == [1, 2, 3, 4, 5, 6]
    # La lista pegó el nombre y la hoja lo parte; la hoja a mano toma el de la lista, y se dice.
    assert alumnos[0].ficha.nombre == "PEREZ MORALES ANDREA C"
    assert alumnos[1].ficha.nombre == "QUINTERO SALAS BRUNO E" and alumnos[1].nombre_de_la_lista
    assert alumnos[3].ficha.nombre == "SOTO URIBE DIANA PATRICIA" and not alumnos[3].nombre_de_la_lista
    assert alumnos[0].ficha.codigo == "9010072"
    assert (alumnos[0].anio_inicial, alumnos[0].anio_final, alumnos[0].final_de_la_lista) == (1990, 1995, True)
    assert cuadre_con_la_lista(unidades_del_libro(_libro_1995())) == {"en_la_lista": 6, "alumnos": 6, "emparejados": 6}


def test_nunca_dos_alumnos_en_un_documento():
    """Dos constancias de nombres distintos abren dos alumnos; la segunda del mismo nombre, no."""
    textos = [
        constancia("MARTHA PATRICIA GOMEZ DIAZ"), continuacion("MARTHA P. GOMEZ DIAZ"),
        constancia("PAOLA MILENA GOMEZ DIAZ"), continuacion("PAOLA MILENA GOMEZ DIAZ"),
        constancia("SULAY DIAZ CAPELLA"), continuacion("SULAY DIAZ CAPELLA"),
        constancia("SULAY DIAZ CAPEELA"), continuacion("SULAY DIAZ CAPELLA"),
    ]
    alumnos = unidades_del_libro(textos)
    assert [u.paginas for u in alumnos] == [[1, 2], [3, 4], [5, 6, 7, 8]]


def test_los_records_y_sus_anexos():
    """El record abre; la carta y la copia de la cédula siguen al alumno, nunca abren ni quedan sueltas."""
    textos = [
        "ALUMNOS X SEMESTRE DE ODONTOLOGIA 2O. PERIODO 1998 PROMEDIO PUESTO 1. 9010027 RUEDA CASTANO LUIS A. "
        "2. 9410047 SALAS MARIN JHONY 3. 9410008 TORRES VEGA KATHERINE",
        record("LUIS ALBERTO RUEDA CASTANO", "73.000.111", "529010027"),
        asignaturas("LUIS A. RUEDA CASTANO"),
        CARTA,
        COPIA_DE_CEDULA,
        asignaturas("JHONNY R. SALAS MARIN"),  # la B antes de su A
        record("JHONNY RAFAEL SALAS MARIN", "1.047.000.222", "529410047"),
        record("KATHERINE TORRES VEGA", "45.000.333", "529410008"),
        asignaturas("KATHERINE TORRES VEGA"),
    ]
    unidades = unidades_del_libro(textos)
    alumnos = [u for u in unidades if u.tipo == CALIFICACIONES]
    assert [u.paginas for u in alumnos] == [[2, 3, 4, 5], [6, 7], [8, 9]]
    luis = alumnos[0]
    assert (luis.ficha.nombre, luis.ficha.cedula, luis.ficha.codigo) == (
        "RUEDA CASTANO LUIS ALBERTO", "73000111", "529010027",
    )
    assert luis.anexos == [4, 5]
    assert alumnos[1].ficha.cedula == "1047000222"


def test_es_libro_de_calificaciones():
    assert es_libro_de_calificaciones(_libro_1995() * 2, "1 CALIFICACIONES ODONTOLOGIA 1995.pdf")
    evidencia = evidencia_de_calificaciones(_libro_1995())
    assert evidencia["lista"] == 1 and evidencia["constancia"] == 7


def test_las_historias_de_enfermeria_no_son_un_libro_de_calificaciones():
    """Fichas y hojas de notas, «PROMOCION» en el nombre y ninguna lista: historias (UPD3859754, 2026-11-27)."""
    from test_historia_academica import FICHA_1996, NOTAS_1993

    textos = [FICHA_1996, NOTAS_1993] * 10
    nombre = "UPD3859754-1HISTORIAS ACADEMICAS PROMOCION 95 EGRESO EN MARZO 1995-1996.pdf"
    assert not es_libro_de_calificaciones(textos, nombre)
    # Ni un libro de actas con una constancia suelta.
    assert not es_libro_de_calificaciones(["ACTA DE GRADO No. 01"] * 30 + [constancia("ANA PEREZ ROJAS")], "ACTAS")


# -- la fila del FUID --------------------------------------------------------------------------------------


def _fila_del_alumno(**cambios) -> dict:
    fila = {
        "tipo": CALIFICACIONES,
        "asunto": "PEREZ MORALES ANDREA C - ODONTOLOGIA",
        "nombre": "PEREZ MORALES ANDREA C",
        "codigo": "9010072",
        "cedula": None,
        "anio_inicial": 1990,
        "anio_final": 1995,
        "folios": 2,
        "pagina_inicial": 3,
        "pagina_final": 4,
        "archivo": "1 CALIFICACIONES ODONTOLOGIA 1995.pdf",
        "carpeta": "FACULTAD DE ODONTOLOGIA CALIFICACIONES 1995",
        "archivo_generado": "02_PEREZ MORALES ANDREA C - ODONTOLOGIA.pdf",
    }
    return {**fila, **cambios}


def test_la_fila_del_alumno_con_el_estandar_de_la_universidad():
    """Asunto «NOMBRE - ODONTOLOGIA», D = código, E = cédula o N/A, del 01/01 del primer año al 31/12 del último."""
    fila = fila_del_fuid(_fila_del_alumno())
    assert (fila.asunto, fila.consecutivo_inicial, fila.consecutivo_final) == (
        "PEREZ MORALES ANDREA C - ODONTOLOGIA", "9010072", "N/A",
    )
    assert (fila.fecha_inicial, fila.fecha_final, fila.folios) == ("01/01/1990", "31/12/1995", 2)
    con_cedula = fila_del_fuid(_fila_del_alumno(cedula="73000111", codigo="529010027"))
    assert (con_cedula.consecutivo_inicial, con_cedula.consecutivo_final) == ("529010027", "73000111")


def test_la_fila_de_la_lista_con_su_titulo_y_su_fecha():
    lista = {
        "tipo": LISTA_DE_ALUMNOS,
        "asunto": "PROMOCION 20-12-1996",
        "anio_inicial": 1996,
        "anio_final": 1996,
        "fecha_exacta": "20/12/1996",
        "folios": 2,
        "pagina_inicial": 1,
        "pagina_final": 2,
        "archivo": "1 CALIFICACIONES ODONTOLOGIA  1996.pdf",
        "carpeta": "FACULTAD DE ODONTOLOGIA CALIFICACIONES 1996",
    }
    fila = fila_del_fuid(lista)
    assert (fila.asunto, fila.consecutivo_inicial, fila.consecutivo_final) == ("PROMOCION 20-12-1996", "N/A", "N/A")
    assert (fila.fecha_inicial, fila.fecha_final) == ("20/12/1996", "20/12/1996")
    periodo = fila_del_fuid({**lista, "asunto": "LISTA DE ALUMNOS X SEMESTRE DE ODONTOLOGIA - 2 PERIODO 1995",
                             "fecha_exacta": None, "anio_inicial": 1995, "anio_final": 1995})
    assert (periodo.fecha_inicial, periodo.fecha_final) == ("01/01/1995", "31/12/1995")


def test_los_dos_tipos_estan_en_los_conversores_del_fuid():
    assert CONVERSORES[CALIFICACIONES] is fila_del_fuid
    assert CONVERSORES[LISTA_DE_ALUMNOS] is fila_del_fuid
    convertida = fila_de_la_entrega(_fila_del_alumno())
    assert convertida.asunto == "PEREZ MORALES ANDREA C - ODONTOLOGIA"
    assert "Archivo: 02_PEREZ MORALES ANDREA C - ODONTOLOGIA.pdf" in convertida.notas


# -- el trabajo de punta a punta, «Solo OCR» ---------------------------------------------------------------


def _pdf(ruta, textos) -> None:
    import fitz

    with fitz.open() as doc:
        for texto in textos:
            doc.new_page().insert_textbox(fitz.Rect(30, 30, 560, 800), texto, fontsize=9)
        doc.save(ruta)


def test_el_trabajo_divide_e_inventaria_el_libro(tmp_path):
    from resolutions.api.worker.historias import historias_academicas_job

    origen = tmp_path / "1 CALIFICACIONES ODONTOLOGIA 1995.pdf"
    textos = [t for t in _libro_1995() if t is not DE_CABEZA]
    _pdf(origen, textos)
    informe = historias_academicas_job(
        {
            "job_id": "cal", "source": str(origen), "filename": origen.name, "task": "both", "lectura": "local",
            "settings": {"ocr_language": "spa", "output_dir": str(tmp_path / "salida")},
        }
    )
    assert informe["habilidad"] == "Calificaciones"
    filas = informe["inventario_actas"]
    assert [f["tipo"] for f in filas] == [LISTA_DE_ALUMNOS] + [CALIFICACIONES] * 5
    assert filas[0]["asunto"] == "LISTA DE ALUMNOS X SEMESTRE DE ODONTOLOGIA - 2 PERIODO 1995"
    assert filas[1]["asunto"] == "PEREZ MORALES ANDREA C - ODONTOLOGIA"
    # «NN_<asunto>.pdf», con espacios, y la hoja A primero aunque la B se escaneara antes.
    assert [f["archivo_generado"] for f in filas[:2]] == [
        "01_LISTA DE ALUMNOS X SEMESTRE DE ODONTOLOGIA - 2 PERIODO 1995.pdf",
        "02_PEREZ MORALES ANDREA C - ODONTOLOGIA.pdf",
    ]
    comprobacion = informe["comprobacion_de_la_entrega"]
    assert comprobacion["comprobada"] and comprobacion["problemas"] == [], comprobacion
    assert comprobacion["hojas"] == len(textos)
    assert informe["calificaciones"]["cuadre_de_la_lista"]["alumnos"] == 5
    # El nombre tomado de la lista va a Revisión.
    assert filas[2]["nombre_de_la_lista"]
    assert any("tomado de la fila 2 de la lista" in item["reason"] for item in informe["review_queue"])
    assert informe["inventario"]


def test_lo_que_no_es_libro_de_calificaciones_sigue_como_historia(tmp_path):
    from test_historia_academica import FICHA_1996, FICHA_2003, NOTAS_1993, NOTAS_2003

    from resolutions.api.worker.historias import historias_academicas_job

    origen = tmp_path / "historias.pdf"
    _pdf(origen, [FICHA_1996, NOTAS_1993, FICHA_2003, NOTAS_2003])
    informe = historias_academicas_job(
        {
            "job_id": "h", "source": str(origen), "filename": origen.name, "task": "inventory",
            "settings": {"ocr_language": "spa", "output_dir": str(tmp_path / "salida")},
        }
    )
    assert "habilidad" not in informe
    assert {f["tipo"] for f in informe["inventario_actas"]} == {"HISTORIA ACADEMICA"}
