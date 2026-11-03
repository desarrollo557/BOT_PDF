"""Las historias de Medicina: un expediente por estudiante, unido por su nombre.

Lo pidió el operador el 2026-11-03 para «17. FACULTAD DE MEDICINA 3261- 3268 P».
Los renglones son los que devolvió la IA sobre «INTERNADOS ROTATORIO 1978-1984»
(caja 00C003263) y los de la capa de texto real de las muestras
(``Desktop\\pruebas_medicina``).
"""

from __future__ import annotations

from resolutions.domain.historia_academica import plano
from resolutions.domain.historia_medicina import (
    CERTIFICADO_DE_MATRICULA,
    CERTIFICADO_DE_NOTAS,
    FICHA_DE_MEDICINA,
    HISTORIAS_DE_FICHA,
    HISTORIAS_DE_MEDICINA,
    HOJAS_DE_MATRICULA,
    MATRICULA_ACADEMICA,
    NOMBRE_DE_HISTORIAS,
    NOTAS_DE_MEDICINA,
    RECIBO_DE_CAJA,
    Hoja,
    al_reves,
    anios_del_legajo,
    aproximacion_de_la_ia,
    cedula_de_la_ficha,
    cedula_del_expediente,
    clase_de_pagina,
    corregir_con_la_ia,
    es_de_hojas_sueltas,
    es_de_medicina,
    expedientes_de_medicina,
    familia_de_historias,
    hojas_sueltas,
    leer_hoja,
    mismo_estudiante,
    nombre_del_renglon,
    nombre_por_consenso,
    tipo_de_hoja,
    ventana_del_legajo,
)

F, N = FICHA_DE_MEDICINA, NOTAS_DE_MEDICINA

#: La ficha de 1948-1960 (UPD 3859597, pág. 3), con el nombre delante del rótulo.
FICHA_1957 = (
    "UNIVERSIDAD DE CARTAGENA - Facultad de Medicina / V REGISTRO DE MATRICULA ARMANDO RAFAEL "
    "CASTILLO CASTILLO Nombre del alumno ENRIQUE CASTILLO JIMEN?g4,3¡¿„ ABOGADO Nombre del padre "
    "LUISA CASTILLO DE CASTILLO Nombre de la madre Lugar de naci"
)
#: La ficha con la capa rota: «Nombre drl alumno» (pág. 5).
FICHA_ROTA = (
    "UNIVERSIDAD DE CARTAGENA = Facultad de Medicina REGISTRO DE MATRICULA Nombre drl alumno Uia'EL A, "
    "CABREIlí\\ UTIÍIA.- Profesión Ingeni >>r O.- Nombre del padre JUAH CABRIERA,- Nombre de la madre"
)
#: Su hoja de notas, con el nombre al pie (pág. 2).
NOTAS_1960 = (
    "REGISTRO DE ESTUDIOS Habilitación Calificación Nota de Calificación N. de Examen ASIGNATURAS o "
    "Supletorio Definitiva Examen Final de Prácticas Trimestral SEXTO AÑO 1.960 Medicina Legal 4,00 "
    "Matrícula No. Nombre CASTILLC CASTILLA ARMANAC RAFAEL.="
)
#: Una hoja de notas de los 90 cuya capa perdió el título.
NOTAS_SIN_TITULO = "ASIGNATURAS CALIFICACION DEFINITIVA HABILITACION REVALIDACION PRIMER AÑO - 1.995 Biofísica 3.70"
#: Una carta del estudiante archivada en su expediente (internados, pág. 9).
CARTA = "Cartagena, Julio 15/81 Doctor Oscar Guardo Nuñez Decano Facultad Medicina Estimado doctor"
#: La ficha de Enfermería: no es de Medicina.
FICHA_ENFERMERIA = (
    "UNIVERSIDAD DE CARTAGENA ENFERMERIA Nombre del estudiante Dirección Actual Lugar de Nacimiento "
    "Estado Civil Nombre de los Padres Cédula No."
)


def test_cada_pagina_por_lo_que_es():
    assert clase_de_pagina(FICHA_1957) == F
    assert clase_de_pagina(FICHA_ROTA) == F
    assert clase_de_pagina(NOTAS_1960) == N
    assert clase_de_pagina(NOTAS_SIN_TITULO) == N
    assert clase_de_pagina(CARTA) is None
    assert clase_de_pagina(FICHA_ENFERMERIA) is None


def test_la_hoja_escaneada_al_reves():
    # «REGISTRO DE ESTUDIOS» cabeza abajo, como lo deja la capa (internados, págs. 30, 59 y 96).
    assert al_reves("V JSTO I S V VAIlINlilO NOI3if3IJIlll3 N0I3VÍI1I8VH Nonvonvns V soianxsa aa oaxsioaa .'")
    assert al_reves("VRIÍIHIJ30 R0I3V3IÍÍ1V3 RonviniRiiH ROI3VOIiyil]R soiaaisa m oaxsioaH")
    assert al_reves("“•TOM vimf Siiim VAiiiNiJiQ NoiavaiJiiva xoniiiiifliiH Honvanvüii soianisa aa onisioaa")
    # La ficha al revés: su «Registro de actividades» se lee derecho (UPD 3859597, pág. 7).
    assert al_reves(
        "Bupipapv ap pBíin^M = VNaOVXHVJ 30 avaiSaSAINQ REGISTRO DE ACTIVIDADES rAUFIGACION EXAMENES "
        "PREPARATORIOS 3er. EXAMEN Grado: Doctor en Nombre de la tesis: Conducta que ha observado:"
    )
    # La ficha derecha trae al revés su «Registro de actividades»: no está al revés.
    assert not al_reves(FICHA_1957 + " saavaiAixov aa oHxsioaa")
    assert not al_reves(NOTAS_1960)


def test_un_pdf_de_medicina_y_uno_de_enfermeria():
    assert es_de_medicina([FICHA_1957, NOTAS_1960, CARTA, NOTAS_1960])
    assert not es_de_medicina([FICHA_ENFERMERIA, CARTA, CARTA])
    # Sin una sola ficha no es una historia de Medicina: unas notas sueltas.
    assert not es_de_medicina([NOTAS_1960, NOTAS_1960])


def test_el_nombre_del_renglon_que_lee_la_ia():
    assert nombre_del_renglon("REGISTRO DE MATRICULA\nNombre del alumno CAROLINA GONIMA NIMMLER.-") == (
        "CAROLINA GONIMA NIMMLER"
    )
    assert nombre_del_renglon("NOMBRE FLOREZ DE LA HOZ GUILLERMO.-\n\nMATRICULA No") == "FLOREZ DE LA HOZ GUILLERMO"
    # En tabla, con la etiqueta de la franja.
    assert nombre_del_renglon("NOMBRE CENTANARO ARRIETA EDER ANTONIO.- 840946 MATRICULA No") == (
        "CENTANARO ARRIETA EDER ANTONIO"
    )
    # El rótulo solo y el nombre debajo, con «Matrícula No.» en medio (págs. de los 80).
    assert nombre_del_renglon("NOMBRE\n\nMATRICULA No\n\nESCUDERO BENAVIDES PABLO ANTONIO.-") == (
        "ESCUDERO BENAVIDES PABLO ANTONIO"
    )
    assert nombre_del_renglon("Nombre del alumno\n\nPABLO ANTONIO ESCUDERO BENAVIDES.-") == (
        "PABLO ANTONIO ESCUDERO BENAVIDES"
    )


def test_el_apellido_con_particula():
    """Internados, pág. 30: «NOMBRE / DEL PORTILLO RONCALLO LUIS ADOLFO» conserva su «DEL»."""
    assert nombre_del_renglon("NOMBRE]\nMATRICULA No\n[30]\nDEL PORTILLO RONCALLO LUIS ADOLFO.-") == (
        "DEL PORTILLO RONCALLO LUIS ADOLFO"
    )


def test_un_trozo_con_dos_nombres_no_es_de_nadie():
    """Si el proveedor devolvió los nombres juntos, lejos de sus rótulos, el trozo no dice cuál es."""
    trozo = "NOMBRE   MATRICULA No\nDURAN RIZO PEDRO.-\nCENTANARO ARRIETA EDER ANTONIO.-"
    assert nombre_del_renglon(trozo) is None
    # El mismo nombre dos veces sí (internados, pág. 40).
    assert nombre_del_renglon("NOMBRE\nCHAMS CHAMS GENOVEVA.-\nMATRICULA No 1.361.-\n[42]\nCHAMS CHAMS GENOVEVA.-") == (
        "CHAMS CHAMS GENOVEVA"
    )
    # El del padre, de dos palabras, que se cuela en la franja de la ficha (pág. 13), tampoco.
    assert nombre_del_renglon("Nombre del alumno RICHARD ELJADNE MARTINEZ.-\n\nAlejandro Elijardo -\n\nComercio -") == (
        "RICHARD ELJADNE MARTINEZ"
    )


def test_la_ficha_en_blanco_no_tiene_nombre():
    assert nombre_del_renglon("Nombre del alumno") is None
    # El renglón de abajo es el del padre: no es el estudiante.
    assert nombre_del_renglon("Nombre del alumno\nNombre del padre Enrique Gonima D.") is None
    assert nombre_del_renglon("NOMBRE\nMATRICULA No 1.273.-") is None


def test_la_cedula_de_la_ficha():
    # 1941-1965, a máquina (UPD 3859597, pág. 5, leída por la IA).
    assert cedula_de_la_ficha("Cédula - Tarjeta No. 877851\n\nExpedida en Cartagena.-") == "877851"
    # De los 70 en adelante, detrás del rótulo.
    assert cedula_de_la_ficha("C. de C. No. 8'748.124 B/quilla Tde. Identi. No.") == "8748124"
    # Escrita en su casilla pero encima del renglón «C. de C. No.»: en el texto
    # va justo delante del rótulo (internados, pág. 1; y en el servidor,
    # 2026-11-03, HERRERA RODRIGUEZ DANILO y JIMENEZ LAGARES ARMANDO ANTONIO).
    assert cedula_de_la_ficha("Firma\n\n39' 693.597\n\nC. de C. No. de\n\nBogotá") == "39693597"
    assert cedula_de_la_ficha("Firma 73'105.869 C/gena\nC. de C. No. de Tde. Identi. No.") == "73105869"
    assert cedula_de_la_ficha("Firma\n689.282\nC. de C. No. de Montería Tde. Identi. No.") == "689282"
    # Con un espacio por separador de miles (ZOLA HERNANDEZ CARLOS).
    assert cedula_de_la_ficha("Cédula - Tarjeta No. 3082 912 Expedida en Magdalena") == "3082912"
    # Leídas por la IA como tabla, con la barra en medio, «Códula» y el guion
    # de miles: COVO TORRES, DIX SANABRIA y GALVAN CARRASCAL (servidor, 2026-11-03).
    assert cedula_de_la_ficha("|  C. de C. No. | 9.093.493 C/gena.- | die | J. libreta Militar N.o  |") == "9093493"
    assert cedula_de_la_ficha("|  Códula - Tarjeta No. | 2466053 | Expedida en Cartagena  |") == "2466053"
    assert cedula_de_la_ficha("C. de C. No 7'374-983 de S.Pelayo Tde. Identi. No. de") == "7374983"
    # Sin cédula, la libreta militar.
    assert cedula_de_la_ficha("C. de C. No. de Tde. Ident. No. de Libreta Militar N.o 4521876 de 2a.") == "4521876"
    # Un número suelto lejos del rótulo, o con otro número en medio, no.
    assert cedula_de_la_ficha("Tel. 52-676 Libro 58 Folio 218 Firma C. de C. No. de") is None
    assert cedula_de_la_ficha("C.C. 45.474.260 Cartagena") == "45474260"
    assert cedula_de_la_ficha("T.I. 66263544 de Turbaco") == "66263544"
    # Sólo la tarjeta de identidad (pág. 7): no es una cédula.
    assert cedula_de_la_ficha("C. de C. No. de Tde. Identi. No. de 571117-05188 B/quilla.") is None
    assert cedula_de_la_ficha("Cédula - Tarjeta No. Mil.") is None


def test_el_mismo_estudiante_en_cualquier_orden():
    # Las dos imágenes del operador (2026-11-03).
    assert mismo_estudiante("ALVARO ANIBAL YAMHURE MURILLO", "YAMHURE MURILLO ALVARO ANIBAL")
    # El papel escribe distinto un apellido: PALLARES en la ficha, PAYARES al pie.
    assert mismo_estudiante("OSWALDO ENRIQUE CANTILLO PALLARES", "CANTILLO PAYARES OSWALDO")
    # La IA no leyó un apellido de la ficha.
    assert mismo_estudiante("EDER ANTONIO ARRIETA EDER", "CENTANARO ARRIETA EDER ANTONIO")
    # La capa de texto rota, con una letra cambiada en cada palabra.
    assert mismo_estudiante("ARMANDO RAFAEL CASTILLO CASTILLO", "CASTILLC CASTILLA ARMANAC RAFAEL")
    assert mismo_estudiante("GUSTAVO A. AHUMADA PLA", "AHUMADA PLA GUSTAVO A.")


def test_una_palabra_mal_leida():
    """UPD 3859597, págs. 66 y 67: la ficha leída «VELESEUZ» es la de VELASQUEZ CANO."""
    assert mismo_estudiante("RAFAEL VELESEUZ CANO", "RAFAEL VELASQUEZ CANO")
    assert mismo_estudiante("RAFAEL VELESEUZ CANO", "VELASCO REYES FABIO") is False


def test_dos_palabras_que_la_ia_leyo_pegadas():
    """UPD0077293, págs. 48 y 49: el mismo estudiante salía en dos PDF."""
    assert mismo_estudiante("RAMIREZ RAMIREZ FELIX MARTIN", "RAMIREZ RAMIREZ FELIXMARTIN")


def test_la_asignatura_de_encima_no_es_del_nombre():
    """UPD0077293: la última asignatura va justo encima del pie y se pegaba al nombre."""
    assert nombre_del_renglon("NOMBRE OROZCO CABEZA JAIRO Medicina Legal\nMATRICULA No") == "OROZCO CABEZA JAIRO"
    assert nombre_del_renglon("NOMBRE RODELO CEBALLOS KAROLL ALEXANDER Etica Médica") == (
        "RODELO CEBALLOS KAROLL ALEXANDER"
    )
    # UPD 3859597, págs. 148 y 160.
    assert nombre_del_renglon("Nombre BONIFACIO MORALES PALMA Clínica Urológica") == "BONIFACIO MORALES PALMA"
    assert nombre_del_renglon("Nombre MOGOLLON MERLANO CARLOS Deontología Médica") == "MOGOLLON MERLANO CARLOS"


def test_las_lecturas_del_mismo_estudiante_votan_cada_palabra():
    """El operador (2026-11-03): el nombre mal escrito, corregido a lo más cercano y correcto."""
    # Dos lecturas iguales confirman, en cualquier orden.
    votado = nombre_por_consenso(["GONIMA NIMMLER CAROLINA", "CAROLINA GONIMA NIMMLER"])
    assert (votado.nombre, votado.sin_confirmar, votado.corregido) == ("GONIMA NIMMLER CAROLINA", (), False)
    # Dos contra una: gana la mayoría, y la fila sabrá qué se leyó.
    votado = nombre_por_consenso(["GONIMA NIMMEER CAROLINA", "CAROLINA GONIMA NIMMLER", "CAROLINA GONIMA NIMMLER"])
    assert (votado.nombre, votado.leido, votado.corregido) == (
        "GONIMA NIMMLER CAROLINA", "GONIMA NIMMEER CAROLINA", True
    )
    # Uno a uno -- o dos a dos -- no se sabe: queda la primera, y la palabra para la IA.
    votado = nombre_por_consenso(["GONIMA NIMMEER CAROLINA", "CAROLINA GONIMA NIMMLER"])
    assert (votado.nombre, votado.sin_confirmar) == ("GONIMA NIMMEER CAROLINA", ("NIMMEER",))
    lecturas = ["GONIMA NIMMEER CAROLINA", "GONIMA NIMMEER CAROLINA", "CAROLINA GONIMA NIMMLER", "CAROLINA GONIMA NIMMLER"]
    votado = nombre_por_consenso(lecturas)
    assert votado.sin_confirmar == ("NIMMEER",)
    assert corregir_con_la_ia(votado, "GONIMA NIMMLER CAROLINA", lecturas) == "GONIMA NIMMLER CAROLINA"
    # La palabra que otra lectura parte en dos (UPD0077293, pág. 49).
    assert nombre_por_consenso(["RAMIREZ RAMIREZ FELIXMARTIN", "RAMIREZ RAMIREZ FELIX MARTIN"]).nombre == (
        "RAMIREZ RAMIREZ FELIX MARTIN"
    )


def test_la_lista_solo_desempata():
    """Internados, págs. 54 y 63, contra el papel (2026-11-03)."""
    conocidas = {"LEIDY", "ISABEL", "CABALLERO", "FUENTES", "ANGELINA", "PEREZ", "GOMEZ", "ANA"}
    # La ficha dice LEIDY y el pie se leyó LEYDY: el empate lo decide la lista, y el papel dice LEIDY.
    votado = nombre_por_consenso(["CABALLERO TOVIO LEYDY ISABEL", "LEIDY ISABEL CABALLERO TOVIO"], conocidas)
    assert (votado.nombre, votado.corregido) == ("CABALLERO TOVIO LEIDY ISABEL", True)
    # Una sola lectura, y el renglón dice CIFUENTES ARGELINA: la lista no la vuelve FUENTES ANGELINA.
    votado = nombre_por_consenso(["BARCENAS CIFUENTES ARGELINA"], conocidas)
    assert (votado.nombre, votado.sin_confirmar) == ("BARCENAS CIFUENTES ARGELINA", ("BARCENAS", "CIFUENTES", "ARGELINA"))
    # Lo que dos lecturas confirman no se toca, aunque haya una conocida cerca.
    assert nombre_por_consenso(["PERES GOMEZ ANA", "ANA PERES GOMEZ"], conocidas).nombre == "PERES GOMEZ ANA"


def test_la_ia_solo_toca_lo_que_nada_confirma():
    lecturas = ["VELESEUZ CANO RAFAEL", "RAFAEL VELESEUZ CANO", "CANO RAFAEL"]
    votado = nombre_por_consenso(lecturas)
    assert votado.sin_confirmar == ()
    # Confirmado por dos lecturas: la IA no lo cambia.
    assert corregir_con_la_ia(votado, "VELASQUEZ CANO RAFAEL", lecturas) is None
    # Una sola lectura: la IA corrige la palabra, a una muy cercana.
    votado = nombre_por_consenso(["VELESEUZ CANO RAFAEL", "CANO RAFAEL"])
    assert votado.sin_confirmar == ("VELESEUZ",)
    assert corregir_con_la_ia(votado, "VELASQUEZ CANO RAFAEL", ["VELESEUZ CANO RAFAEL", "CANO RAFAEL"]) == (
        "VELASQUEZ CANO RAFAEL"
    )
    # Quitar dos letras ya es otro apellido: CIFUENTES no es FUENTES.
    votado = nombre_por_consenso(["BARCENAS CIFUENTES ARGELINA"])
    assert corregir_con_la_ia(votado, "BARCENAS FUENTES ARGELINA", ["BARCENAS CIFUENTES ARGELINA"]) is None


def test_la_ia_aproxima_pero_no_cambia_a_la_persona():
    """El operador (2026-11-03): «los nombres, lo más parecidos a lo que se pueda leer en el renglón»."""
    assert aproximacion_de_la_ia("VELASQUEZ CANO RAFAEL", ["VELESEUZ CANO RAFAEL"]) == "VELASQUEZ CANO RAFAEL"
    assert aproximacion_de_la_ia("SALINAS LÓPES KAROL", ["SALINAS LOPES KARL"]) == "SALINAS LOPES KAROL"
    # «SIPOZ» por LOPEZ son tres letras de cinco: eso ya no es lo que dice el
    # renglón (RECIBOS DE CAJA, pág. 6). Si el papel dice LOPEZ, lo trae la
    # relectura del renglón con zoom, no la IA.
    assert aproximacion_de_la_ia("SALINAS LOPEZ KAROL", ["SALINAS SIPOZ KARL"]) is None
    assert aproximacion_de_la_ia("SALINAS LOPEZ KAROL", ["SALINAS SIPOZ KARL", "SALINAS LOPEZ KAROL"]) == (
        "SALINAS LOPEZ KAROL"
    )
    # Entre dos lecturas, la que es un apellido de verdad.
    assert aproximacion_de_la_ia(
        "GONIMA NIMMLER CAROLINA", ["GONIMA NIMMEER CAROLINA", "CAROLINA GONIMA NIMMLER"]
    ) == "GONIMA NIMMLER CAROLINA"
    # Otra persona, una palabra de más o una de menos: no.
    assert aproximacion_de_la_ia("PEREZ GOMEZ JUAN", ["SALINAS LOPES KARL"]) is None
    assert aproximacion_de_la_ia("SALINAS LOPEZ KAROL ANDREA", ["SALINAS LOPES KARL"]) is None
    assert aproximacion_de_la_ia("SALINAS KAROL", ["SALINAS LOPES KARL"]) is None
    assert aproximacion_de_la_ia("NINGUNO", ["SALINAS LOPES KARL"]) is None


def test_estudiantes_distintos():
    assert mismo_estudiante("GONIMA NIMMLER CAROLINA", "FERRER TRIANA ALCIDES HERNANDO") is False
    # Dos hermanos: los mismos apellidos, otro nombre de pila.
    assert mismo_estudiante("CASTILLO CASTILLO LUIS", "CASTILLO CASTILLO ARMANDO RAFAEL") is False
    assert mismo_estudiante("CANTILLO FERRANS GREGORIO FRANCISCO", "CANTILLO PAYARES OSWALDO") is False


def test_sin_nombre_no_se_sabe():
    assert mismo_estudiante(None, "FERRER TRIANA ALCIDES") is None
    assert mismo_estudiante("FERRER", "FERRER TRIANA ALCIDES") is None


# -- las hojas sueltas: lo que leyó la IA de las cajas 00C003267 y 00C003268 ---------

#: «PRIMER AÑO 1992», pág. 2.
CERTIFICADO_1992 = """# UNIVERSIDAD DE CARTAGENA
OFICINA DE ADMISIONES Y CONTABILIDAD ACADEMICA
CERTIFICADO DE MATRICULA ACADEMICA
|  CODIGO | NOMBRE DEL ESTUDIANTE |   | SEMEST. AÑO  |
| --- | --- | --- | --- |
|  7210007 | ALVAREZ | OROZCO HAROLD ANTONIO | 01  |
|  CARRERA | CODIGO | PERIODO | AÑO | FECHA EXPEDICION  |   |   |
| --- | --- | --- | --- | --- | --- | --- |
|  DICINA | 51 | 1 | 92 | DIA 26 | MES 03 | AÑO 92  |
|  MATERIAS | CODIGO | GRUPO | ULAS | INTENSIDAD T P | OBSERVACIONES  |"""
#: «EXONERADOS 1991», pág. 3.
MATRICULA_1991 = """UNIVERSIDAD DE CARTAGENA
Admisiones Registro y Control Académico
MATRICULA ACADEMICA
|  COD. ESTUDIANTE 51-8810043 | APELLIDOS: ARRIETA VALENCIA | NOMBRES: LEONARDO ANTONIO | CARRERA MEDICINA | Sem. 6° | Período 10-91  |
| --- | --- | --- | --- | --- | --- |
|  Cód. Materia | ASIGNATURAS | Ulas | Grupo | Asig. que Cursa | Asig. que Repite  |"""
#: «RECIBOS DE CAJA», págs. 3 y 5: el año de la primera, mal leído.
RECIBO_MAL_FECHADO = """# RECIBO DE CAJA
forma minerva
|  CIUDAD Y FECHA Cartagena, Nov. 18 de 1.476 |   |   |   | No.  |   |
| --- | --- | --- | --- | --- | --- |
|  RECIBIDO DE Beleno González Edinson Medicina  |   |   |   |   |   |
|  DIRECCION  |   |   |   |   |   |"""
RECIBO = """# RECIBO DE CAJA
|  CIUDAD Y FECHA Cartagena, julio 30 de 1.996 |   |   | No. 457  |   |
|  RECIBO DE Salinas López Karol Medicina  |   |   |   |   |"""
#: La portada de un legajo, escrita a mano.
PORTADA = "Recibos De Caja 05-09-1995 18-11-1996 UPD0077175"


def test_que_hoja_suelta_es():
    assert tipo_de_hoja(CERTIFICADO_1992) == CERTIFICADO_DE_MATRICULA
    assert tipo_de_hoja(MATRICULA_1991) == MATRICULA_ACADEMICA
    assert tipo_de_hoja(RECIBO) == RECIBO_DE_CAJA
    # La capa de texto de las matrículas: «MA’l RICURA ACADEMICA», «Registro 7 Control».
    assert tipo_de_hoja("UNIVERSIDAD DE CARTAGENA MA’l RICURA ACADEMICA i Admisiones") == MATRICULA_ACADEMICA
    assert tipo_de_hoja("UNIVERSIDAD DE CARTAGENA Admisiones Registro 7 Control Académico Período") == MATRICULA_ACADEMICA
    assert tipo_de_hoja("OFíClHA Ot ADMISIONES Y COMASíUDAD ACADtMiCA CERTIFICADO DE NOTAS cod") == CERTIFICADO_DE_NOTAS
    assert tipo_de_hoja(PORTADA) is None
    assert tipo_de_hoja(NOTAS_1960) is None


def test_un_legajo_de_hojas_sueltas():
    assert es_de_hojas_sueltas([PORTADA, CERTIFICADO_1992, CERTIFICADO_1992, MATRICULA_1991])
    assert not es_de_hojas_sueltas([FICHA_1957, NOTAS_1960, CERTIFICADO_1992])


def test_un_pdf_por_hoja():
    """La portada no es de nadie; la certificación archivada con una matrícula va con ella."""
    unidades = hojas_sueltas([None, MATRICULA_ACADEMICA, None, MATRICULA_ACADEMICA, RECIBO_DE_CAJA])
    assert [(u.paginas, u.plantilla) for u in unidades] == [
        ([1], None),
        ([2, 3], MATRICULA_ACADEMICA),
        ([4], MATRICULA_ACADEMICA),
        ([5], RECIBO_DE_CAJA),
    ]
    assert not unidades[0].es_de_un_estudiante


def test_lo_que_dice_cada_hoja():
    assert leer_hoja(CERTIFICADO_1992, CERTIFICADO_DE_MATRICULA) == Hoja(
        nombre="ALVAREZ OROZCO HAROLD ANTONIO", codigo=None, fecha=(26, 3, 1992), anio=1992
    )
    assert leer_hoja(MATRICULA_1991, MATRICULA_ACADEMICA) == Hoja(
        nombre="ARRIETA VALENCIA LEONARDO ANTONIO", codigo="51-8810043", fecha=None, anio=1991
    )
    # La inicial con su punto (EXONERADOS 1991, pág. 7).
    assert leer_hoja(
        "| COD. ESTUDIANTE 51-0810034 | APELLIDOS: DE LA CARRERA ALVARADO | NOMBRES: CESAR J. | CARRERA MEDICINA |",
        MATRICULA_ACADEMICA,
    ).nombre == "DE LA CARRERA ALVARADO CESAR J"
    assert leer_hoja(RECIBO, RECIBO_DE_CAJA, ventana=(1990, 1998)) == Hoja(
        nombre="SALINAS LOPEZ KAROL", fecha=(30, 7, 1996), anio=1996
    )
    # «1.476» no es un año del legajo: no se da, y el nombre sin «Medicina».
    mal_fechado = leer_hoja(RECIBO_MAL_FECHADO, RECIBO_DE_CAJA, ventana=(1990, 1998))
    assert (mal_fechado.nombre, mal_fechado.fecha, mal_fechado.anio) == ("BELENO GONZALEZ EDINSON", None, None)
    # La fecha en cifras, y la carrera mal leída detrás del nombre (págs. 9 y 11).
    en_cifras = leer_hoja(
        "|  CIUDAD Y FECHA: Cartagena 08-08-96. |   | No. 1051 |\n|  RECIBO DE Martinez RuP2 Alvaro. Medicina.  |   |",
        RECIBO_DE_CAJA, ventana=(1992, 1999),
    )
    assert (en_cifras.nombre, en_cifras.fecha) == ("MARTINEZ RUP ALVARO", (8, 8, 1996))
    assert leer_hoja("RECIBIDO DE Bacna Nieto Marlene Beatriz Medicine |", RECIBO_DE_CAJA).nombre == (
        "BACNA NIETO MARLENE BEATRIZ"
    )
    # Sin fecha legible, los años del legajo: de su nombre o de su portada.
    assert anios_del_legajo("UPD0077175 - RECIBOS DE CAJA.pdf", PORTADA) == (1995, 1996)


def test_los_anios_del_legajo():
    assert anios_del_legajo("UPD0077180 - CUARTO AÑO 1996 - 1997.pdf") == (1996, 1997)
    assert anios_del_legajo("UPD0077175 - RECIBOS DE CAJA.pdf") == (None, None)
    assert ventana_del_legajo("UPD0077193 - PRIMER AÑO 1992.pdf") == (1989, 1995)
    # Sin años en el nombre, los de la portada escrita a mano.
    assert ventana_del_legajo("UPD0077175 - RECIBOS DE CAJA.pdf", PORTADA) == (1992, 1999)
    assert ventana_del_legajo("UPD0077175 - RECIBOS DE CAJA.pdf") == (1950, 2030)


def test_que_habilidad_le_toca_a_cada_pdf():
    """El operador (2026-11-03): «que sepa detectar la habilidad automáticamente»."""
    assert familia_de_historias([PORTADA, FICHA_1957, NOTAS_1960, CARTA]) == HISTORIAS_DE_MEDICINA
    assert familia_de_historias([PORTADA, CERTIFICADO_1992, CERTIFICADO_1992, MATRICULA_1991]) == HOJAS_DE_MATRICULA
    # Los recibos de caja, que no traen membrete en la capa: por el nombre del legajo.
    assert familia_de_historias([PORTADA, RECIBO, RECIBO], "UPD0077175 - RECIBOS DE CAJA.pdf") == HOJAS_DE_MATRICULA
    otro_recibo = "RECIBO DE CAJA No. 88 CIUDAD Y FECHA Barranquilla RECIBIDO DE Ferretería El Tornillo LA SUMA DE"
    assert familia_de_historias([otro_recibo, otro_recibo], "factura_proveedor.pdf") is None
    # Enfermería: dos fichas de ingreso con sus notas.
    ficha = "Nombre del estudiante Dirección Actual Lugar de Nacimiento Estado Civil Cédula No."
    notas = "REGISTRO ACADEMICO ASIGNATURA NOTA DEFINITIVA AÑO: 93"
    assert familia_de_historias([ficha, notas, ficha, notas]) == HISTORIAS_DE_FICHA
    # «Nombre del estudiante» suelto no basta (recibos, certificados de otra cosa).
    assert familia_de_historias(["Nombre del estudiante Pago", CARTA, CARTA, CARTA]) is None
    # Un acta o una resolución no son historias.
    assert familia_de_historias(["RESOLUCION No. 0123 POR LA CUAL SE", "CONSIDERANDO", "RESUELVE"]) is None
    assert familia_de_historias([]) is None


def test_el_nombre_de_un_pdf_de_historias():
    """Lo que se mira de un PDF de red de más de 25 MB, que no se baja para sugerir."""
    for nombre in (
        "UPD 3859597 HISTORIAS ACADEMICAS 1948-1960.pdf",
        "INTERNADOS ROTATORIO 1978-1984.pdf",
        "UPD0077193 - PRIMER AÑO 1992.pdf",
        "UPD0077185 - EXONERADOS 1991.pdf",
        "UPD0077175 - RECIBOS DE CAJA.pdf",
    ):
        assert NOMBRE_DE_HISTORIAS.search(plano(nombre)), nombre
    assert not NOMBRE_DE_HISTORIAS.search(plano("RESOLUCIONES DE RECTORIA 3220.pdf"))


def _rangos(unidades):
    return [(u.paginas[0], u.paginas[-1], u.ficha.nombre if u.ficha else None) for u in unidades]


def test_internados_1978_1984_paginas_1_a_10():
    """Las notas de Ferrer antes de su ficha, y la segunda cartulina de Flórez antes de la primera."""
    clases = [F, N, N, F, F, N, F, N, None, None]
    nombres = {
        1: "CAROLINA GONIMA NIMMLER",
        2: "GONIMA NIMMLER CAROLINA",
        3: "FERRER TRIANA ALCIDES HERNANDO",
        4: "ALCIDES HERNANDO FERRER TRIANA",
        6: "FLOREZ DE LA HOZ GUILLERMO",
        7: "GUILLERMO FLOREZ DE LA HOZ",
        8: "FLOREZ DE LA HOZ GUILLERMO",
    }
    unidades = expedientes_de_medicina(clases, nombres)
    assert _rangos(unidades) == [
        (1, 2, "GONIMA NIMMLER CAROLINA"),
        (3, 4, "FERRER TRIANA ALCIDES HERNANDO"),
        # La ficha en blanco de la pág. 5 va con Flórez por el pie de su reverso,
        # y sus cartas (págs. 9 y 10) con él.
        (5, 10, "FLOREZ DE LA HOZ GUILLERMO"),
    ]
    assert unidades[1].pagina_de_la_ficha == 4
    assert unidades[2].pagina_de_la_ficha == 7


def test_la_segunda_cartulina_va_con_su_estudiante():
    """UPD 3859597, págs. 1 a 4: la ficha en blanco y sus notas, luego la ficha llena."""
    clases = [F, N, F, N, F, N]
    nombres = {
        2: "CASTILLC CASTILLA ARMANAC RAFAEL",
        3: "ARMANDO RAFAEL CASTILLO CASTILLO",
        4: "ARMANDO RAFAEL CASTILLO CASTILLO",
        5: "MIGUEL A CABRERA UTRIA",
        6: "CABRERA UTRIA MIGUEL A",
    }
    assert _rangos(expedientes_de_medicina(clases, nombres)) == [
        (1, 4, "CASTILLC CASTILLA ARMANAC RAFAEL"),
        (5, 6, "CABRERA UTRIA MIGUEL A"),
    ]


def test_el_mismo_estudiante_en_dos_tramos():
    """UPD 3859613, págs. 1 a 6: Baleta, Ballestas y otra vez Baleta. Un solo PDF de Baleta, con su nota.

    El operador (2026-11-03): «no puede existir 2 PDF con el mismo nombre, cada
    estudiante es único».
    """
    clases = [F, N, F, N, F, N]
    nombres = {
        1: "FREDDY DE JESUS BALETA CASTILLA",
        2: "BALETA CASTILLA FREDDY DE JESUS",
        3: "ONOFRE DE JESUS BALLESTAS CAMPO",
        4: "BALLESTAS CAMPO ONOFRE DE JESUS",
        5: "FREDDY DE JESUS BALETA CATILLA",
        6: "BALETA CASTILLA FREDDY DE JESUS",
    }
    unidades = expedientes_de_medicina(clases, nombres)
    assert [u.paginas for u in unidades] == [[1, 2, 5, 6], [3, 4]]
    assert unidades[0].dudas == [
        "se unieron las páginas 5 a 6, del mismo estudiante, que estaban separadas en el escaneo"
    ]
    assert unidades[1].dudas == []


def test_la_portada_no_es_de_nadie():
    unidades = expedientes_de_medicina([None, F, N], {2: "OCHOA NUÑEZ ALBERT MIGUEL", 3: "OCHOA NUÑEZ ALBERT MIGUEL"})
    assert _rangos(unidades) == [(1, 1, None), (2, 3, "OCHOA NUÑEZ ALBERT MIGUEL")]
    assert not unidades[0].es_de_un_estudiante


def test_una_cartulina_sin_nombre_no_se_pega_a_otro_estudiante():
    """UPD 3859597, págs. 58 a 63 (el operador, 2026-11-03: «te fijas que no tiene el mismo nombre?»).

    Villalobos trae sus dos cartulinas; la 62 es la ficha en blanco de Velásquez
    y la 63 sus notas. Si el pie de la 63 no se deja leer, no se sabe de quién
    es: se separa y se anota, en vez de quedar dentro del PDF de Villalobos.
    """
    clases = [F, N, F, N, F, N]
    nombres = {
        1: "RAMON VILLALOBOS LOPEZ",
        2: "VILLALOBOS LOPEZ RAMON",
        3: "RAMON VILLALOBOS LOPEZ",
        4: "VILLALOBOS LOPEZ RAMON",
    }
    unidades = expedientes_de_medicina(clases, nombres)
    assert _rangos(unidades) == [(1, 4, "VILLALOBOS LOPEZ RAMON"), (5, 6, None)]
    assert unidades[1].dudas == [
        "la ficha de la página 5 y su reverso no dejan leer el nombre: se separó de "
        "RAMON VILLALOBOS LOPEZ; revise si es suyo"
    ]
    # Con el pie leído, Velásquez sale con su nombre.
    unidades = expedientes_de_medicina(clases, {**nombres, 6: "VELASQUEZ CANO RAFAEL"})
    assert _rangos(unidades) == [(1, 4, "VILLALOBOS LOPEZ RAMON"), (5, 6, "VELASQUEZ CANO RAFAEL")]


def test_una_cartulina_sin_nombre_no_se_lleva_la_ficha_siguiente():
    """UPD 3859597, págs. 62 a 65, con «Solo OCR»: Velásquez sin nombre se llevaba la ficha de Velasco Reyes."""
    clases = [F, N, F, N, F, N]
    nombres = {1: "RAMON VILLALOBOS LOPEZ", 2: "VILLALOBOS LOPEZ RAMON", 5: "FABIO VELASCO REYES"}
    unidades = expedientes_de_medicina(clases, nombres)
    assert _rangos(unidades) == [(1, 2, "VILLALOBOS LOPEZ RAMON"), (3, 4, None), (5, 6, "FABIO VELASCO REYES")]
    assert unidades[1].dudas[-1] == "no deja leer el nombre; la ficha siguiente es de FABIO VELASCO REYES: revise si es suya"


def test_el_rotulo_mal_leido_no_va_en_el_nombre():
    assert nombre_del_renglon("Nombre DEL ALMO RAJMUN VILLALOBOS LOPNA") == "RAJMUN VILLALOBOS LOPNA"


def test_la_cedula_de_cinco_cifras_detras_de_su_rotulo():
    """Las de los 40 y 50: «Cédula - Tarjeta No. 77975» (Castillo, UPD 3859597, pág. 3, leída por la IA)."""
    assert cedula_de_la_ficha("Cédula - Tarjeta No. 77975 Expedida en Cartagena") == "77975"
    # Suelta, sin rótulo, no.
    assert cedula_de_la_ficha("Firma 77975 Bogotá") is None


def test_la_segunda_cartulina_sin_nombre_sigue_a_la_primera_si_esta_no_esta_completa():
    """Una ficha sin hojas detrás todavía no es una cartulina entera: lo que sigue va con ella."""
    unidades = expedientes_de_medicina([F, F, N], {1: "DURAN RIZO PEDRO"})
    assert _rangos(unidades) == [(1, 3, "DURAN RIZO PEDRO")]


def test_la_cedula_se_busca_en_todo_el_expediente():
    """RAMON VILLALOBOS LOPEZ salía sin cédula: la ficha dice «Cédula - Tarjeta No. 4312325»."""
    ficha = "REGISTRO DE MATRICULA Nombre del alumno RAMON VILLALOBOS LOPEZ Cédula - Tarjeta No. 4312325 Expedida en"
    assert cedula_del_expediente([NOTAS_1960, ficha]) == "4312325"
    # La de una hoja de notas, con su rótulo.
    assert cedula_del_expediente([FICHA_ROTA, "REGISTRO DE ESTUDIOS C.C. 45.474.260 Cartagena"]) == "45474260"
    # Un número suelto no es una cédula.
    assert cedula_del_expediente([NOTAS_1960, "Matrícula No. 271 Tel. 31-21"]) is None
