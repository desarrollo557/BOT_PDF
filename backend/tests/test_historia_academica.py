"""Las historias académicas: un expediente por estudiante y su fila en el FUID.

Lo pidió el operador el 2026-10-29 para «14. ENFERMERIA 3277-3283 P». Los textos
son los de la capa de texto real de las muestras (``Desktop\\pruebas_enfermeria``),
recortados: el manuscrito sale como sale, y la regla tiene que vivir con eso.
"""

from __future__ import annotations

import pytest

from resolutions.adapters.fuid_historias import fila_del_fuid, filas_del_fuid
from resolutions.domain.historia_academica import (
    CERTIFICADO,
    FICHA,
    FICHA_CON_SEXO,
    HISTORIA_ACADEMICA,
    SIN_ESTUDIANTE,
    Ficha,
    abre_expediente,
    anios,
    anios_de_la_ficha,
    es_de_notas,
    es_ficha,
    expedientes,
    leer_ficha,
    plantilla_de_apertura,
    ventana_de_anios,
)

#: La ficha de los 90, con el nombre escrito a mano que el escáner no leyó (1993, pág. 1).
FICHA_1993 = (
    "1993 Diciembre 10/^\"^ ‘ 'A m. í UNIVERSIDAD DE CARTAGENA ENFERMERIA m V Cí^LOi. ej’TQ oLo "
    "Nombre del estudiante ^ | voirg a Tel.: 622^29 ^5 s Dirección Actual • 'Boscjue. "
    "Lugar de Nacimiento: ^ £ y¿7 7^ Estado Civil: Fecha de Nacimiento Nombre de los Padres 5 "
    "Dirección; Ciudad: Bachiller del colegio:^ / a,'. g > Cédula No. jk c/p» Fecha de Grado. rj£a "
    "Libreta Militar: Código. S-^'Ho loo 2S DBSFRVACIONES: PRUEBAS DEL ICFES Física A. Mat."
)
#: La misma ficha con el nombre a máquina y el código (1996, pág. 1).
FICHA_1996 = (
    "A ¿I -t UNIVERSIDAD DE CARTAliENA laI jf ENFERMERIA V V AGUAS GAREUIDO CLARENA LUCIA. V "
    "Nombre del estudiante T,|,: Dirección Actual . L f Lugar de Nacimiento: jy (S> ys^é> "
    "Estado Civil; Fecha de Nacimiento Nornbre de los Padres Dirección: Ciudad; Bachiller del "
    "colegio; Cédula No. Fecha de Grado. # 549310044 Libreta Militar; Código. OBSERVACIONES: "
    "PRUEBAS DEL ICFES Ptje. A. Mat. Electiva RECOR ACADEMICO PROMEDIO ARITMETICO"
)
#: La de alrededor del 2000: «ESTUDIANTE · SEXO · TELÉFONO» (retirados 2003, pág. 1).
TEXTO_FICHA_CON_SEXO = (
    "^c.krcxoíos ILFá JlDn3. UNIVERSIDAD DE CARTAGENA FACULTAD DE ENFERMERÍA wm ■» 7\"r "
    "t-lon cc^c, /Oq. rrt i iCs ESTUDIANTE V i SEXO mQ fQ teléfono ♦ —3 1 DIRECaÓN FECHA DE "
    "NACIMIENTO LUGAR 1 'VJ 'f' CÉOUU No. ESTADO CIVIL LIB. MILITAR"
)
#: La de 2003 en adelante (retirados 2003, pág. 11).
FICHA_2003 = (
    "i )¿/<5’/íyrc<e4o . 1PaJ2^ ^ UNIVERSIDAD DE CARTAGENA Facultad de Enfermería Ficha Historia "
    "Académica de Estudiante Q.0nc)<2. Apellidos; Nombres; Sexo; Femenino () Masculino ( ) Fecha "
    "de Nacimiento; Día Mes; Q ¿__Año; Edad;"
)
#: Sus hojas de notas: no abren nada.
NOTAS_1993 = (
    "1 ASIGNATURAS U L AS ASIGNATURAS U L A S -C SEM; I AÑO; 90 P.A.l n SEM: 3,^ fyP A/' A A B C "
    "Total u AÑO: B C Total u I y Humanidades I Química v/ 54 6 60 eo 36 72 18 50 140 AÑO: 93"
)
NOTAS_2003 = (
    "* ESTMPIANTE: Uonccíd^ HoCaíñ PROMEDIO GENERAL S MDICAOORES P E C R REPRE CURSA Ó HABILITA "
    "O M HASUTA 2a .^«Z la. VEZ HABIUTA M E D ? REQUISITOS F p p p p ASIGNATURA"
)


@pytest.mark.parametrize("ficha", [FICHA_1993, FICHA_1996, TEXTO_FICHA_CON_SEXO, FICHA_2003])
def test_cada_formato_de_ficha_abre_el_expediente(ficha):
    assert abre_expediente(ficha)


@pytest.mark.parametrize("notas", [NOTAS_1993, NOTAS_2003, ""])
def test_las_hojas_de_notas_no_abren_nada(notas):
    """La hoja de notas de 2003 dice «ESTUDIANTE:», pero sin el sexo ni el teléfono."""
    assert not abre_expediente(notas)


def test_de_la_ficha_se_lee_el_nombre_y_el_codigo():
    ficha = leer_ficha(FICHA_1996)
    assert ficha.nombre == "AGUAS GAREUIDO CLARENA LUCIA"
    assert ficha.codigo == "549310044"
    assert ficha.clave == "COD:549310044"


def test_lo_escrito_a_mano_no_se_inventa():
    ficha = leer_ficha(FICHA_1993)
    assert (ficha.nombre, ficha.cedula, ficha.codigo) == (None, None, None)
    assert ficha.clave is None


def test_la_cedula_con_puntos_sale_sin_ellos():
    ficha = leer_ficha("NOMBRE DEL ESTUDIANTE PEREZ GOMEZ ANA MARIA Cédula No. 45.755.189 Código. 5420011003")
    assert (ficha.nombre, ficha.cedula, ficha.codigo) == ("PEREZ GOMEZ ANA MARIA", "45755189", "5420011003")


def test_los_anios_de_las_notas_son_las_fechas_extremas():
    assert anios([NOTAS_1993]) == (1990, 1993)
    assert anios(["AÑO 1.993", "AÑO: 94", "1995-1996"]) == (1993, 1996)
    assert anios([NOTAS_2003]) == (None, None)


def test_un_anio_suelto_mal_leido_no_alarga_el_expediente():
    """El «AÑO 02» que era 92: se queda el grupo de años mejor apoyado."""
    assert anios(["AÑO: 90", "AÑO: 91", "AÑO: 92", "AÑO: 02"]) == (1990, 1992)


def test_con_la_ventana_del_pdf_el_siglo_es_el_que_toca():
    """El «AÑO 45» de un libro de los 40 es 1945, no 2045."""
    assert anios(["AÑO: 45", "AÑO: 46"], ventana=(1938, 1952)) == (1945, 1946)
    assert anios(["1923", "AÑO: 74", "AÑO: 75"], ventana=(1966, 1979)) == (1974, 1975)


def test_de_la_ficha_solo_cuentan_el_ingreso_y_el_grado():
    """IPA 2004: la capa dice «AÑO INGRESO 2-000»; la fecha de nacimiento no cuenta."""
    texto = "FECHA DE NACIMIENTO 12/05/1981 ANO INGRESO 2-000 PERIODO FECHA DE GRADUACION 24-VII-2004"
    assert anios_de_la_ficha(texto) == (2000, 2004)
    assert anios([], de_la_ficha=(2000, 2004)) == (2000, 2004)


def test_con_un_solo_anio_de_la_ficha_el_otro_extremo_queda_sin_fecha():
    """Sin notas con años, el ingreso es el primer año y el grado el último; no se repiten."""
    assert anios([], de_la_ficha=(2000, None)) == (2000, None)
    assert anios([], de_la_ficha=(None, 2004)) == (None, 2004)


def test_el_anio_del_plan_de_estudios_no_es_del_estudiante():
    flujograma = "FLUJOGRAMA PLAN DE ESTUDIOS FACULTAD DE ENFERMERIA UNIVERSIDAD DE CARTAGENA 1.998"
    assert anios([flujograma]) == (None, None)


def test_un_numero_de_nueve_cifras_junto_a_la_cedula_es_el_codigo():
    ficha = leer_ficha("NOMBRE DEL ESTUDIANTE Cédula No. 549310006 Libreta Militar")
    assert (ficha.cedula, ficha.codigo) == (None, "549310006")
    assert leer_ficha("Cédula No. 1.047.382.991").cedula == "1047382991"


def test_sin_anios_en_las_notas_la_ventana_la_da_el_nombre_del_pdf():
    assert ventana_de_anios([], nombre="UPD3859721-1HISTORIAS ACADEMICAS 1974-1977.pdf") == (1966, 1979)
    assert ventana_de_anios([], nombre="HISTORIAS SIN FECHA.pdf") is None


# -- las páginas de los PDF de 2002 en adelante (capa de texto real, IPA 2004) --

#: Su ficha: «ESTUDIANTE · SEXO · TELÉFONO…», con el nombre escrito a mano.
FICHA_2004 = (
    "% ¡J m UNIVERSIDAD DE CARTAOENA FACULTAD DE ENFERMERÍA VCq^I^ £ütcoc ] fCE3 teléfono o o ^ "
    "ESTUDIANTE SEXO M DlRECaÓN OCiCy^QS V-l. - L S - FECHA DE NACIMIENTO C^O^lo ¡Qt\\ LUGAR "
    "C(¿jí2nc, SD\\Wg> CÉDULA No. •S^'^ ACODENTE: NOMBRE '3CiUg>\\T^ ESTADO CIVIL LIB. MILITAR "
    "BACHILLER DEL COLEGIO JX3TÓU CkXC-^óu^^Lr^^ - P CÓDIGO ^4aO0D2.OO5G AÑO INGRESO 2-000"
)
#: Su certificado de matrícula, que va DETRÁS de sus notas (pág. 12).
CERTIFICADO_2004 = (
    "% í '-3 -- «!• UNIVERSIDAD DE CARTAGENA , / OFICINA DE ADMISIONES Y CONTABILIDAD ACADEMICA "
    "CERTIFICADO DE MATRICULA ACADEMICA . V,-' 1 SEM^ST. NOMBRE DEL ESTUDIANTE CODIGO ANO "
    "AÑO FECHA EXPEDICION PERIODO CODIGO CARRERA AÑO OIA MES INTENS, HORARIA OBSERVACIONES"
)
#: Un certificado cuya capa perdió el título (pág. 8): pasaba por una ficha.
CUERPO_DEL_CERTIFICADO = (
    "5 UNIVERSIDAD D£ CARTAÓENA '.lüfifi- “1 SEMEST. ANO NOMBRE DEL ESTUDIANTE J - - , CODIGO + V' "
    "FECHA EXPEDICION AÑO PERIODO CODIGO CARRERA -i'' AÑO h -• DIA MES INTENS. HORARIA OBSERVACIONES"
)
#: El recibo de pago de la matrícula (pág. 45): dice «Nombre del estudiante» y no abre nada.
RECIBO_2004 = (
    "UNIVERSIDAD DE CARTAGENA VICERECTORIA ADMINISTRATIVA DIVISION FINANCIERA RECIBO N° A 0011346 "
    "COMPROBANTE DE PAGO DERECHO DE MATRICULA PROGRAMA: ENFERMERIA FECHA EXPEDICION CODIGO "
    "ESTUDIANTE NOMBRE DEL ESTUDIANTE CORBACHO BUELUAS FARIÑA DEL C VALOR A PAGAR"
)
NOTAS_2004 = (
    "ESTUDIANTE: C)aíl63-ki OoS-Iyd ¿íiofic- PROlUEDíO GENERAL tNDICAOORES s p R E C REPITE CURSA "
    "REQUISITOS ASIGNATURA BIOLOGÍA 411 3.3 BIOQUÍMICA 412"
)
#: La ficha de «EGRESADOS 1996», pág. 29: «Nombre del estu'diante», con un
#: apóstrofo en medio. Con sólo esa leyenda no abría y juntaba a dos estudiantes.
FICHA_CON_APOSTROFO = (
    "UNIVERSIDAD DE CARTAGENA % V ENFERMERIA /“X Nombre del estu'diante GAIARCIO MORENO NEPKT.RYDA.- "
    "Dirección Actual . Daniel Lennaitre Cl.71 # 17-45 Tel.: 666903 Lugar de Nacimiento: Fecha de "
    "Nacimiento Estado Civil: Nombre de los Padres « Dirección; Bachiller del colegio; Ciudad; Cédula "
    "No. 4/^ de: Fecha de Grado. 7} Código. 549310019 Libreta Militar; OBSERVACIONES: PRUEBAS DEL ICFES "
    "RECOR ACADEMICO PROMEDIO ARITMETICO DE CALIFICACIONES"
)


def test_la_ficha_se_reconoce_por_sus_rotulos_aunque_se_rompa_el_suyo():
    assert plantilla_de_apertura(FICHA_CON_APOSTROFO) == FICHA
    assert leer_ficha(FICHA_CON_APOSTROFO).codigo == "549310019"
    assert plantilla_de_apertura(FICHA_2004) in (FICHA, FICHA_CON_SEXO)


def test_el_certificado_tambien_sin_su_titulo_y_el_recibo_no_abre():
    assert plantilla_de_apertura(CERTIFICADO_2004) == CERTIFICADO
    assert plantilla_de_apertura(CUERPO_DEL_CERTIFICADO) == CERTIFICADO
    assert plantilla_de_apertura(RECIBO_2004) is None
    assert es_de_notas(NOTAS_2004)
    assert not es_ficha(CERTIFICADO) and es_ficha(FICHA)


def test_la_hoja_de_notas_que_dice_promedio_no_se_toma_por_notas_si_es_ficha():
    """«PROMEDIO» lo trae también la ficha: no marca hoja de notas."""
    assert not es_de_notas(FICHA_CON_APOSTROFO)


def test_el_certificado_va_con_el_estudiante_de_antes():
    """Pág. 12 de IPA 2004: el certificado es de la estudiante de la ficha de la pág. 9."""
    paginas = [FICHA_2004, NOTAS_2004, NOTAS_2004, CERTIFICADO_2004, FICHA_2004, NOTAS_2004, RECIBO_2004]
    resultado = expedientes(paginas)
    assert [e.paginas for e in resultado] == [[1, 2, 3, 4], [5, 6, 7]]
    assert [e.pagina_de_la_ficha for e in resultado] == [1, 5]


def test_un_certificado_al_principio_abre_y_sin_ficha_no_se_le_paga_a_la_ia():
    resultado = expedientes([CERTIFICADO_2004, NOTAS_2004, FICHA_2004, NOTAS_2004])
    assert [e.paginas for e in resultado] == [[1, 2], [3, 4]]
    assert resultado[0].es_de_un_estudiante and resultado[0].pagina_de_la_ficha is None


def test_un_certificado_de_otro_codigo_es_otro_estudiante():
    """«BALSEIRO HERAZO XIARA», un certificado suelto tras el de otra estudiante."""
    resultado = expedientes(
        [FICHA_2004, NOTAS_2004, CERTIFICADO_2004],
        fichas={1: Ficha(codigo="5420020056"), 3: Ficha(codigo="5420020099")},
    )
    assert [e.paginas for e in resultado] == [[1, 2], [3]]


def test_el_certificado_trae_a_maquina_lo_que_la_ficha_no_deja_leer():
    resultado = expedientes(
        [FICHA_2004, NOTAS_2004, CERTIFICADO_2004],
        fichas={3: Ficha(nombre="BALLESTAS CASTRO NORLEY ELIANA", codigo="5420020056")},
    )
    assert resultado[0].ficha.nombre == "BALLESTAS CASTRO NORLEY ELIANA"
    assert resultado[0].ficha.codigo == "5420020056"


def test_cada_ficha_con_sus_hojas_es_un_estudiante():
    resultado = expedientes([FICHA_2004, NOTAS_2004, FICHA_CON_APOSTROFO, NOTAS_1993])
    assert [e.paginas for e in resultado] == [[1, 2], [3, 4]]


def test_una_ficha_sin_hojas_detras_va_con_la_siguiente_y_se_anota():
    """IPA 2004, págs. 39 y 40: un formulario en blanco delante de la ficha de verdad."""
    resultado = expedientes([FICHA_2004, NOTAS_2004, FICHA_2004, FICHA_CON_APOSTROFO, NOTAS_1993])
    assert [e.paginas for e in resultado] == [[1, 2], [3, 4, 5]]
    assert resultado[1].pagina_de_la_ficha == 4
    assert resultado[1].ficha.codigo == "549310019"
    assert resultado[1].dudas == ["la página 3 es una ficha sin hojas detrás, unida a la ficha siguiente"]


def test_la_ficha_vieja_y_la_nueva_del_mismo_codigo_son_un_expediente():
    """«VEGA CABALLERO MARIA EUGENIA», código 549710039: págs. 94 y 97 de «2002-2»."""
    resultado = expedientes(
        [FICHA_2004, NOTAS_2004, NOTAS_2004, FICHA_2003, NOTAS_2003],
        fichas={1: Ficha(codigo="549710039"), 4: Ficha(codigo="549710039")},
    )
    assert [e.paginas for e in resultado] == [[1, 2, 3, 4, 5]]


def test_un_nombre_leido_gratis_tiene_que_ser_un_nombre():
    conocidas = {"BALLESTAS", "CASTRO", "NORLEY", "ELIANA", "PEDRO", "HEREDIA"}
    assert leer_ficha("NOMBRE DEL ESTUDIANTE BALLESTAS CASTRO NORLEY ELIANA", conocidas).nombre == (
        "BALLESTAS CASTRO NORLEY ELIANA"
    )
    # El rótulo roto y la dirección no son nombres.
    assert leer_ficha("EGISTRO DEL TUDIANTE NOMBRE DEL ESTUDIANTE", conocidas).nombre is None
    assert leer_ficha("NOMBRE DEL ESTUDIANTE AV PEDRO DE HEREDIA ESCALLON", conocidas).nombre is None


def test_un_expediente_por_ficha_con_sus_hojas_detras():
    paginas = [FICHA_1996, NOTAS_1993, FICHA_2003, NOTAS_2003, NOTAS_2003]
    resultado = expedientes(paginas)
    assert [e.paginas for e in resultado] == [[1, 2], [3, 4, 5]]
    assert all(e.es_de_un_estudiante for e in resultado)


def test_lo_de_antes_de_la_primera_ficha_no_es_de_nadie():
    resultado = expedientes([NOTAS_2003, FICHA_1996, NOTAS_1993])
    assert [e.paginas for e in resultado] == [[1], [2, 3]]
    assert [e.es_de_un_estudiante for e in resultado] == [False, True]


def test_dos_paginas_seguidas_del_mismo_estudiante_son_un_expediente():
    """La ficha y, detrás, su certificado de matrícula: el mismo código, el mismo expediente."""
    certificado = "CERTIFICADO DE MATRICULA ACADEMICA AGUAS GARRIDO CLARENA Código 549310044"
    resultado = expedientes([FICHA_1996, certificado, NOTAS_1993])
    assert [e.paginas for e in resultado] == [[1, 2, 3]]


def test_dos_fichas_sin_leer_no_se_unen():
    """Sin nada con que reconocer al estudiante, cada ficha es un expediente."""
    resultado = expedientes([FICHA_1993, NOTAS_1993, FICHA_1993, NOTAS_1993])
    assert [e.paginas for e in resultado] == [[1, 2], [3, 4]]


def test_la_ficha_leida_con_la_ia_manda_sobre_la_del_texto():
    resultado = expedientes([FICHA_1993, NOTAS_1993], fichas={1: Ficha(nombre="ANA PEREZ", cedula="123")})
    assert resultado[0].ficha.nombre == "ANA PEREZ"


def _fila(**cambios):
    datos = {
        "tipo": HISTORIA_ACADEMICA,
        "nombre": "AGUAS GARRIDO CLARENA LUCIA",
        "cedula": "45755189",
        "codigo": "549310044",
        "anio_inicial": 1993,
        "anio_final": 1996,
        "folios": 2,
        "carpeta": "14. ENFERMERIA 3277-3283 P\\CAJA 00C003282",
        "archivo": "UPD3859753-1HISTORIAS ACDEMICAS EGRASADOS 1996.pdf",
        "pagina_inicial": 1,
        "observaciones": "",
    }
    return {**datos, **cambios}


def test_la_fila_del_fuid_de_un_estudiante():
    fila = fila_del_fuid(_fila())
    assert fila.asunto == "HISTORIA ACADEMICA - AGUAS GARRIDO CLARENA LUCIA"
    assert (fila.consecutivo_inicial, fila.consecutivo_final) == ("45755189", "549310044")
    assert (fila.fecha_inicial, fila.fecha_final) == ("01/01/1993", "31/12/1996")
    assert (fila.caja, fila.carpeta) == ("00C003282", "UPD3859753")
    assert (fila.folios, fila.folios_siar) == (2, 2)


def test_lo_que_no_se_leyo_queda_na():
    fila = fila_del_fuid(_fila(nombre=None, cedula=None, codigo=None, anio_inicial=None, anio_final=None, folios=None))
    assert fila.asunto == "HISTORIA ACADEMICA - N/A"
    assert (fila.consecutivo_inicial, fila.consecutivo_final) == ("N/A", "N/A")
    assert (fila.fecha_inicial, fila.fecha_final, fila.folios) == ("N/A", "N/A", "N/A")


def test_las_paginas_sin_estudiante_no_llevan_fila():
    assert fila_del_fuid(_fila(tipo=SIN_ESTUDIANTE)) is None
    filas = filas_del_fuid([_fila(tipo=SIN_ESTUDIANTE), _fila(), _fila(nombre="OTRA PERSONA")])
    assert [f.orden for f in filas] == [1, 2]
