"""Los libros de calificaciones de la Facultad de Odontología: un alumno, un PDF (2026-11-27).

El operador, 2026-11-27, sobre «8. ACTA 9 FACULTAD DE ODONTOLOGIA CALIFICACIONES
3194 - 3198»: «a dividir y a inventariar… implementa los patrones», con el nombre
y la especialidad de cada alumno, y la lista de la promoción «su PDF y su fila».

Cada libro es una promoción. **Abre** con la lista de sus alumnos («ALUMNOS X
SEMESTRE DE ODONTOLOGIA 2o. PERIODO 1995», «PROMOCIÓN 20 DE DICIEMBRE DE 1996»),
con el orden, el código y el nombre de cada uno, y **sigue** con dos hojas por
alumno en el orden de la lista:

* **1995-1997:** la constancia «EL SECRETARIO ACADÉMICO… HACE CONSTAR Que,
  NOMBRE, cursó y aprobó…» (la hoja A) y su «Continuación calificaciones de
  NOMBRE» (la hoja B). En 1995 casi todas las constancias llevan el nombre a
  mano sobre la raya y la continuación es el formulario en blanco que sólo dice
  «VI SEMESTRE - Odontopediatría…».
* **1998, 1999 y la promoción 2003:** el «RECORD ACADÉMICO» -- la ficha de
  ingreso con foto, cédula, código, fecha de grado, acta y diploma, la misma
  que ``historia_academica`` llama FICHA -- (la hoja A) y su hoja de
  ASIGNATURAS con el nombre arriba (la hoja B).

Medido página por página sobre los seis libros (la capa de texto en
``scratchpad/udc-20261127b-textos``): 47, 66, 64, 63, 63 y 54 alumnos, y
dentro de los libros cartas, copias de cédula, certificados de vacunación o de
otra universidad y hojas del sistema de admisiones: los anexos. El de 1997
trae 66 constancias, pero SULAY DIAZ CAPELLA (págs. 27-30) y JHONNY GARZON
PAJARO (págs. 45-48) tienen dos juegos -- la constancia del 9.º semestre y la
del 10.º, con las mismas notas --: son 64 alumnos.

**Las reglas de corte** (``unidades_del_libro``):

1. Cada constancia o record abre un alumno, salvo que diga el mismo nombre (o
   el mismo código) que el alumno en curso: la 2.ª constancia «ha cursado» de
   LUCY OTERO FRANCESCHI (1996, págs. 109-111) es suya.
2. Cada hoja B sigue a su alumno; cada alumno tiene una A y una B. Una B que
   llega cuando el alumno en curso ya tiene la suya, justo antes de una apertura
   cuya B no viene detrás, es de esa apertura: en 1995 la pág. 5 es del alumno
   de la pág. 6. Si la B trae nombre legible, manda el nombre.
3. Los anexos van con el alumno vecino cuyo nombre o cédula traen; si no
   nombran a nadie, con el anterior («los anexos siguen la secuencia»). Nunca
   abren alumno ni quedan sueltos.
4. Cada lista -- también la 2.ª de 2003, pág. 114 -- va en su propio documento.
5. Cada alumno se empareja con su fila de la lista **por orden y por nombre**
   (``emparejar_con_la_lista``): un alineamiento con huecos, para que una fila
   que la capa no dejó leer no corra todos los nombres.

**El nombre** va con los apellidos primero, como la lista, y completado con lo
que dice la propia hoja (``nombre_completo``): lista «ALCALA REVOLLEDO LUIS
A.» + record «LUIS ALBERTO ALCALA REVOLLEDO» = «ALCALA REVOLLEDO LUIS
ALBERTO». Si la hoja no se lee, el de la lista tal cual, y se dice.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from .datos_esperados import palabra_dudosa
from .historia_academica import (
    Expediente,
    Ficha,
    es_ficha,
    leer_ficha,
    plantilla_de_apertura,
)
from .text_distance import damerau_levenshtein

#: El tipo de la fila de un alumno en el inventario y en el FUID.
CALIFICACIONES = "CALIFICACIONES"
#: El tipo de la fila de la lista de la promoción, que lleva su PDF y su fila.
LISTA_DE_ALUMNOS = "LISTA DE ALUMNOS"
#: La familia que reconoce el despachador: un libro de calificaciones.
LIBRO_DE_CALIFICACIONES = "libro de calificaciones"
#: La especialidad de los alumnos, que dicen sus hojas («semestre de Odontología»).
ODONTOLOGIA = "ODONTOLOGIA"

#: Las plantillas de página de un libro de calificaciones.
LISTA = "LISTA"
#: La página que sigue la lista sin su encabezado: «46. 9110029 VILLADIEGO TORRES KATYA V».
LISTA_SIGUE = "LISTA SIGUE"
CONSTANCIA = "CONSTANCIA"
CONTINUACION = "CONTINUACION"
RECORD = "RECORD"
ASIGNATURAS = "ASIGNATURAS"
#: Las hojas que abren un alumno (la A) y las que lo siguen (la B).
HOJAS_QUE_ABREN = frozenset({CONSTANCIA, RECORD})
HOJAS_QUE_SIGUEN = frozenset({CONTINUACION, ASIGNATURAS})


def plano(texto: str) -> str:
    """Mayúsculas sin tildes y con un solo espacio: así se comparan las leyendas."""
    sin_tildes = unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.upper().split())


# -- qué es cada página ---------------------------------------------------------------

#: El encabezado de la lista de la promoción: «ALUMNOS X SEMESTRE DE
#: ODONTOLOGIA 2o. PERIODO 1995» (la «X» sale «A» en la capa de 2003),
#: «PROMOCIÓN 20 DE DICIEMBRE DE 1996 Promedio Puesto».
_LISTA = re.compile(r"\bALUMNOS\s+[XA]?\s*SEMESTRE\b|\bPROMOCION\b.{0,80}\b(?:PROMEDIO|PUESTO)\b")
#: El mismo encabezado con las letras separadas por la capa -- «ALU M N O S X SE
#: ME EI T R E 1 E R. P E RL O D O 2003», la 2.ª lista de 2003, pág. 114 --:
#: se busca sin espacios.
_LISTA_SIN_ESPACIOS = re.compile(r"ALUMNOS[XA]?SEM\w{0,6}\W{0,2}\d?\w{0,3}\.?PER\w{0,4}DO\d{4}")
#: La constancia de calificaciones: «HACE CONSTAR Que, NOMBRE, cursó y aprobó…».
_CONSTANCIA = re.compile(r"\bHACE\s+CONSTAR\b.{0,700}?\b(?:CURSO|HA\s+CURSADO|CALIFICACION|SEMESTRE)")
#: La constancia escaneada cabeza abajo, como la deja la capa: «VN3OVIDVO 3A
#: AVAISD3AINN» es UNIVERSIDAD DE CARTAGENA y «TI DVLSNOO 30VH», HACE CONSTAR,
#: leídos al revés (1995, pág. 81). Con dos de estas firmas, está de cabeza.
_DE_CABEZA = (
    re.compile(r"\bDVLSNOO\b"),
    re.compile(r"\b30VH\b"),
    re.compile(r"VN3OVIDVO|VNHOVIYVD"),
    re.compile(r"AVAIS\S{0,3}AINN"),
    re.compile(r"VIOOIOINOAO|VIOOIOINOOO"),
)
#: Su segunda hoja: «Continuación calificaciones de NOMBRE». La capa de 1995 la
#: lee de veinte maneras -- «CONLINUACION», «CONTIGUACION», «CONIIDUIICIOR
#: CALIFICACIONES», «COITLIFUIACION CAUIICAUIOIIES» --: una palabra que empieza
#: por CO y acaba en CION (o CIOR) seguida de otra que empieza por CA o CC.
_CONTINUACION = re.compile(r"\bCO[A-Z]{3,10}C[I1L]O[NR]\s+C[A-Z]{5,14}\b")
#: El formulario de la continuación, aunque la capa no lea su título: «VI
#: SEMESTRE - Odontopediatría - Restauradora II - Clínica integradas I · VII
#: SEMESTRE - Principios de investigación…». En 1995 muchas son el formulario
#: en blanco, con el nombre a mano.
_SEMESTRE_DEL_FORMULARIO = re.compile(r"\b(?:V|VI|VII|VIL|VIH|VIII|IX|X|VT|VTL|VIT)\s+SEM\w{3,6}\b")
_MATERIAS_DEL_FORMULARIO = re.compile(
    r"\bODON\w{0,3}P\w{0,3}DI\w{1,6}\b|\bPRINCIPIOS\s+D\w\s+INVESTIGACION\b|\bCLINICA\s+INTE\w{1,8}\b"
    r"|\bRESTAURADORA\s+(?:II|11|LI|IL|!1)\b"
)
#: La hoja de ASIGNATURAS del record (y «ASIGNATARAS», «ASIGNATUMS»).
_ASIGNATURAS = re.compile(r"\bA?S\w{0,2}GNA\w{0,3}T\w{0,2}(?:RAS|MS)\b")
_DE_LA_TABLA = re.compile(r"\bSEM\b|\bCALIF\b|\bHABIL\b|\bNOTA\b|\bANO\b")
#: El record académico de 1998 en adelante: la ficha con su promedio aritmético.
_RECORD = re.compile(r"\bRECORD\s+ACADEMICO\b|\bPROMEDIO\s+ARITMETICO\b")
#: La copia de la cédula -- «REPÚBLICA DE COLOMBIA · IDENTIFICACIÓN PERSONAL ·
#: CÉDULA DE CIUDADANÍA», con su «lugar de nacimiento» y su «fecha de
#: nacimiento» -- tiene dos rótulos de la ficha y no es un record: es un anexo
#: (2003, pág. 84, de GILMA DEL CARMEN ROJAS ROSALES).
_COPIA_DE_CEDULA = re.compile(r"\bIDENTIFICACION\s+PERSONAL\b|\bCEDULA\s+DE\s+CIUDADANIA\b.{0,60}\bREPUBLICA\b|\bREPUBLICA\s+DE\s+COLOMBIA\b")
_DE_LA_FICHA = re.compile(r"\bNOMBRE\s+DE\w?\s+ESTUD|\bRECORD\s+ACADEMICO\b|\bNOMBRE\s+DE\s+LOS\s+PADRES\b")

#: Cuántas filas «NN. código nombre» hacen falta para tomar por lista una página sin encabezado.
FILAS_DE_UNA_LISTA = 5


def de_cabeza(texto: str) -> bool:
    """Si la página se escaneó cabeza abajo: su capa trae las firmas de la constancia leídas al revés."""
    p = plano(texto)
    return sum(1 for firma in _DE_CABEZA if firma.search(p)) >= 2


def es_encabezado_de_lista(texto: str) -> bool:
    """Si la página trae el encabezado de una lista de alumnos o de la promoción."""
    p = plano(texto)
    return bool(_LISTA.search(p) or _LISTA_SIN_ESPACIOS.search(p.replace(" ", "")))


def plantilla_de_calificaciones(texto: str) -> str | None:
    """Qué hoja del libro es: lista, constancia, continuación, record o asignaturas; ``None`` si es un anexo.

    En este orden: la constancia de cabeza, la lista con su encabezado, la
    constancia, el record (la ficha de ``historia_academica``), la hoja de
    asignaturas, la lista sin encabezado y la continuación.
    """
    p = plano(texto)
    if de_cabeza(texto):
        return CONSTANCIA
    constancia = bool(_CONSTANCIA.search(p))
    record = (es_ficha(plantilla_de_apertura(texto)) or bool(_RECORD.search(p))) and not (
        _COPIA_DE_CEDULA.search(p) and not _DE_LA_FICHA.search(p)
    )
    if not constancia and not record and es_encabezado_de_lista(texto):
        return LISTA
    if constancia:
        return CONSTANCIA
    if record:
        return RECORD
    if _ASIGNATURAS.search(p) and _DE_LA_TABLA.search(p):
        return ASIGNATURAS
    if _CONTINUACION.search(p):
        return CONTINUACION
    if len(_SEMESTRE_DEL_FORMULARIO.findall(p)) >= 2 and _MATERIAS_DEL_FORMULARIO.search(p):
        return CONTINUACION
    if _parece_lista(_filas(p)):
        return LISTA_SIGUE
    return None


def _parece_lista(filas: Sequence[tuple[int | None, str | None, str, int]]) -> bool:
    """Si las filas leídas son las de una lista: cinco con su código, o cinco con el orden seguido.

    Las notas de la continuación también dejan leer «1 Y MATERIALES DENTALES»
    como una fila: sin código y sin orden seguido no son una lista (1995, págs.
    43 y 64).
    """
    if sum(1 for _, codigo, _, _ in filas if codigo) >= FILAS_DE_UNA_LISTA:
        return True
    ordenes = [orden for orden, _, _, _ in filas if orden is not None]
    seguidos = sum(1 for a, b in zip(ordenes, ordenes[1:], strict=False) if b == a + 1)
    return seguidos >= FILAS_DE_UNA_LISTA - 1


# -- la evidencia, para el despachador --------------------------------------------------

#: Cuántas páginas del comienzo se miran para la lista de la promoción.
PAGINAS_DE_LA_LISTA = 3
#: Cuántos alumnos -- constancias o records -- hacen falta para tomar el PDF
#: por un libro de calificaciones, y qué parte de las páginas tienen que ser
#: suyas (las dos hojas de cada uno). Un libro de actas que trae una constancia
#: suelta (1996-1998-1999 TOMO I) o un tomo de resoluciones con tres fichas no
#: llegan.
MINIMO_DE_ALUMNOS = 5
PARTE_DE_ALUMNOS = 0.3
#: El nombre del PDF o de su carpeta que dice lo que es.
_NOMBRE_DE_LIBRO = re.compile(r"\bCALIFICACIONES\b|\bPROMOCION\b")


def evidencia_de_calificaciones(textos: Sequence[str]) -> dict[str, int]:
    """Cuántas hojas de cada plantilla de un libro de calificaciones trae el PDF.

    ``lista`` cuenta sólo el encabezado en las ``PAGINAS_DE_LA_LISTA``
    primeras; ``notas``, las hojas de asignaturas del record.
    """
    cuenta = {"lista": 0, "constancia": 0, "continuacion": 0, "record": 0, "notas": 0}
    for numero, texto in enumerate(textos):
        cual = plantilla_de_calificaciones(texto)
        if cual == LISTA and numero < PAGINAS_DE_LA_LISTA:
            cuenta["lista"] += 1
        elif cual == CONSTANCIA:
            cuenta["constancia"] += 1
        elif cual == RECORD:
            cuenta["record"] += 1
        elif cual == CONTINUACION:
            cuenta["continuacion"] += 1
        elif cual == ASIGNATURAS:
            cuenta["notas"] += 1
    return cuenta


def es_libro_de_calificaciones(textos: Sequence[str], nombre: str = "") -> bool:
    """Si el PDF es un libro de calificaciones: la lista de su promoción y las hojas de cada alumno.

    Sin la lista al comienzo hace falta que el nombre del PDF o de su carpeta lo
    diga («CALIFICACIONES», «PROMOCION») **y** que sus alumnos abran con la
    constancia de calificaciones, que sólo traen estos libros. El record solo no
    basta: es la misma ficha de ingreso de las historias de Enfermería, con su
    hoja de asignaturas, y «UPD3859754-1HISTORIAS ACADEMICAS PROMOCION 95…»
    (72 págs., 36 fichas y 36 hojas de notas, ninguna lista) se tomaba por un
    libro de calificaciones (2026-11-27).
    """
    if not textos:
        return False
    cuenta = evidencia_de_calificaciones(textos)
    alumnos = cuenta["constancia"] + cuenta["record"]
    suyas = alumnos + cuenta["continuacion"] + cuenta["notas"]
    if alumnos < MINIMO_DE_ALUMNOS or suyas < PARTE_DE_ALUMNOS * len(textos):
        return False
    if cuenta["lista"] > 0:
        return True
    return cuenta["constancia"] >= MINIMO_DE_ALUMNOS and bool(_NOMBRE_DE_LIBRO.search(plano(nombre)))


# -- la lista de la promoción ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlumnoDeLaLista:
    """Una fila de la lista: su orden, su código (si la lista lo trae) y su nombre, apellidos primero."""

    orden: int
    codigo: str | None
    nombre: str


#: Las letras que la capa pone por cifras dentro de un código: «92I0005», «931QQ37».
_CIFRA_LEIDA_LETRA = re.compile(r"(?<=\d)[IOQ]+(?=[IOQ]*\d)")
#: Una fila: «1. 9010072 ALFARO ZOLA LIZELIA M.», «46. 9110029 VILLADIEGO…»,
#: «11.9010017 …», «1 9210360 …», «[1 |52199810009 [ARANDA BETANCOURT MILENA»
#: (Tesseract, 2003) y, sin código, «1. AGUAS POLO TANIA CECILIA» (1996). El
#: orden y el código van a veces pegados: «129210134 DIAZ ARAUJO…» es el 12.
_FILA = re.compile(
    r"(?<![\w.,/])(?:(?P<orden>\d{1,2})(?:\s*[.,]\s*|\s*[|\]\[]\s*|\s+)(?P<codigo>\d{7}|\d{11})?"
    r"|(?P<pegado>\d{8,9}|\d{12,13})|(?P<romano>[IL]{1,2})\.\s)"
    # Sin el apóstrofo: «BRUGES RUIZ MIGUEL ALEJANDRO ' II. CAMARGO…» son dos filas (1996).
    r"\s*[^\w\s]{0,3}\s*(?P<nombre>[A-Z][A-Z.\- ]{3,70})"
)
#: Las palabras que acaban el nombre en la fila: lo que sigue es otra columna.
_FIN_DEL_NOMBRE = frozenset({"PROMEDIO", "PUESTO", "PROMED", "PROM", "MAXIMO", "MINIMO", "SEMESTRE"})
#: Las palabras de la hoja que se cuelan en un nombre y no lo son.
_NO_SON_NOMBRE = frozenset({
    "UNIVERSIDAD", "CARTAGENA", "FACULTAD", "ODONTOLOGIA", "NOMBRE", "ESTUDIANTE", "SEMESTRE", "CODIGO",
    "PROMEDIO", "PUESTO", "ALUMNOS", "PERIODO", "PROMOCION", "CALIFICACIONES", "CONTINUACION", "DIRECCION",
    "ACTUAL", "TELEFONO", "ASIGNATURAS", "NOTA", "CURSO", "APROBO", "CONSTAR", "SECRETARIO", "ACADEMICO",
    "HACE", "QUE", "ESTA", "EN", "CON", "LAS", "SIGUIENTES", "DEPENDENCIA", "CITESE", "NUMERO", "CONTESTAR",
    "HABILITO", "REPITIO", "OBTUVO", "CALIFICACION", "CEDULA", "CIUDADANIA", "REPUBLICA", "COLOMBIA",
    # Los rótulos de la ficha del record y lo que se escribe en ellos: «PRUEBA DEL
    # ICFES», «LUGAR Y FECHA DE NACIMIENTO», la dirección (2003, págs. 29 y 100).
    "LUGAR", "FECHA", "NACIMIENTO", "ESTADO", "CIVIL", "PADRES", "BACHILLER", "COLEGIO", "CIUDAD", "DEPTO",
    "PRUEBA", "ICFES", "GRADO", "LIBRETA", "MILITAR", "EXAMEN", "ADMISION", "ENTREVISTA", "RECORD",
    "DIPLOMA", "ACTA", "OBSERVACIONES", "TEL", "MZA", "LOTE", "MANZANA", "BARRIO", "CALLE", "SECTOR",
    "ETAPA", "URB", "CRA", "AVENIDA", "ASIGNATURA", "SEM", "AFIO", "ANO", "SOLTERO", "SOLTERA",
    "CASADO", "CASADA", "IDENTIFICACION", "PERSONAL", "FIRMA", "ARITMETICO",
    # Las materias, que en la continuación siguen al nombre sin un semestre en medio.
    "PERIODONCIA", "RESTAURADORA", "ODONTOPEDIATRIA", "CLINICA", "ENDODONCIA", "ANESTESIA", "CIRUGIA",
    "ORTODONCIA", "INFORMATICA", "SALUD", "PROTESIS", "ADMINISTRACION", "PRINCIPIOS", "INVESTIGACION",
    "MATERIALES", "DENTALES", "INTEGRADA", "INTEGRADAS", "INTEGRAL", "ETICA", "PROFESIONAL", "URGENCIAS",
})
_CONECTORES = frozenset({"DE", "DEL", "LA", "LAS", "LOS", "Y", "SAN", "SANTA", "VDA", "VIUDA"})


def _parece_palabra(palabra: str) -> bool:
    """Con vocales, sin tres letras iguales seguidas ni cinco consonantes juntas."""
    if palabra in _CONECTORES:
        return True
    if len(palabra) < 3 or not re.search(r"[AEIOUY]", palabra):
        return False
    return not (re.search(r"(.)\1\1", palabra) or re.search(r"[^AEIOUY]{5,}", palabra))


def palabras_del_nombre(texto: str | None) -> list[str]:
    """Las palabras de un nombre tal como se leyeron, con sus iniciales («M.» queda «M»), sin la basura del OCR.

    Se corta en la primera palabra que no es de nombre después de dos que sí:
    «PEREZ GOMEZ ANA CURSO» acaba en ANA. Lo de antes de una palabra de la hoja
    se descarta: «FACULTAD DE ODONTOLOGIA LUIS ALBERTO…» empieza en LUIS.
    """
    return list(_palabras(texto or ""))


@lru_cache(maxsize=16384)
def _palabras(texto: str) -> tuple[str, ...]:
    """``palabras_del_nombre``, una vez por texto: el emparejamiento con la lista compara cada nombre miles de veces."""
    palabras: list[str] = []
    for bruta in re.split(r"[\s,;:]+", plano(texto)):
        for trozo in (t for t in re.split(r"\.", bruta) if t):
            palabra = re.sub(r"[^A-Z\-]", "", trozo).strip("-")
            if not palabra:
                continue
            if palabra in _NO_SON_NOMBRE:
                if sum(1 for p in palabras if len(p) >= 3 and p not in _CONECTORES) >= 2:
                    return tuple(_sin_conectores_sueltos(palabras))
                palabras = []
                continue
            palabras.append(palabra)
    return tuple(_sin_conectores_sueltos(palabras))


def _sin_conectores_sueltos(palabras: list[str]) -> list[str]:
    """Sin partículas sueltas a la cola ni una «Y» delante: «DE LA VALLE ARCHIBOLD» sí empieza por DE."""
    while palabras and palabras[-1] in _CONECTORES:
        palabras = palabras[:-1]
    while palabras and palabras[0] == "Y":
        palabras = palabras[1:]
    return palabras


#: Cuántas iniciales sueltas puede traer un nombre: «MARZAN GENEY LUIS C J».
INICIALES = 2


def _de_nombre(palabra: str) -> bool:
    """Si una palabra puede ser de un nombre: una inicial, una partícula o una palabra con forma de nombre."""
    return len(palabra) == 1 or palabra in _CONECTORES or (_parece_palabra(palabra) and not palabra_dudosa(palabra))


def nombre_limpio(texto: str | None) -> str | None:
    """El nombre leído, sin basura, o ``None`` si no parece un nombre.

    Dos palabras plenas, alguna de cinco letras o más, ninguna con forma
    imposible («MQKII», «UQV») y no más de dos iniciales. Lo de la cola que no
    es de nombre («VAA^^ARI-R» → «VAA» se queda: tiene forma) se suelta; una
    palabra imposible en medio, o letras sueltas de la capa de 2003 («D RL G
    UEZ C ARM O NA»), no son un nombre.
    """
    palabras = [p for p in palabras_del_nombre(texto) if len(p) != 2 or p in _CONECTORES]
    while palabras and not _de_nombre(palabras[-1]):
        palabras = palabras[:-1]
    palabras = _sin_conectores_sueltos(palabras)
    plenas = [p for p in palabras if len(p) >= 3 and p not in _CONECTORES]
    if (
        len(plenas) < 2
        or not any(len(p) >= 5 for p in plenas)
        or sum(1 for p in palabras if len(p) == 1) > INICIALES
        or not all(_de_nombre(p) for p in palabras)
    ):
        return None
    return " ".join(palabras)


#: Desde cuántas letras una sola palabra en la fila es un nombre pegado por la capa.
PEGADO = 12


def _nombre_de_la_fila(crudo: str) -> str | None:
    """El nombre de una fila de la lista: hasta la primera palabra de otra columna.

    Una sola palabra larga es el nombre entero pegado por la capa,
    «ALFAROZOLALIZELIAM.» (1995, fila 1): se queda así, y lo parte la hoja del
    alumno (``nombre_completo``).
    """
    palabras: list[str] = []
    for palabra in crudo.split():
        if palabra.strip(".") in _FIN_DEL_NOMBRE:
            break
        palabras.append(palabra)
    if nombre := nombre_limpio(" ".join(palabras)):
        return nombre
    pegado = palabras_del_nombre(" ".join(palabras[:1]))
    if len(pegado) == 1 and len(pegado[0]) >= PEGADO and _parece_palabra(pegado[0]):
        return pegado[0]
    return None


def _filas(p: str) -> list[tuple[int | None, str | None, str, int]]:
    """Las filas «orden código nombre» de un texto ya plano: (orden, código, nombre, posición)."""
    reparado = _CIFRA_LEIDA_LETRA.sub(lambda m: m.group(0).translate(str.maketrans("IOQ", "100")), p)
    # La marca a mano pegada al nombre y suelta detrás -- «DE LA ESPRIELL^ FERIA
    # JULIO» (1996, fila 19) -- no lo corta; pegada a otra letra («LUIS A^BCDO»), sí.
    reparado = re.sub(r"\^(?=\s)", "", reparado)
    # La coma que la capa mete dentro de una palabra: «13.9210031 DI,AZ CAPELLA
    # SULAY» (1997) es DIAZ; partida, la fila se perdía.
    reparado = re.sub(r"(?<=[A-Z]),(?=[A-Z])", "", reparado)
    filas: list[tuple[int | None, str | None, str, int]] = []
    for hallada in _FILA.finditer(reparado):
        orden_texto, codigo = hallada.group("orden"), hallada.group("codigo")
        if pegado := hallada.group("pegado"):
            # «129210134»: el orden delante del código de siete cifras (o de once en 2003).
            largo = 7 if len(pegado) in (8, 9) else 11
            orden_texto, codigo = pegado[:-largo], pegado[-largo:]
        if not codigo and orden_texto and len(orden_texto) > 2:
            continue
        if (nombre := _nombre_de_la_fila(hallada.group("nombre"))) is None:
            continue
        orden = int(orden_texto) if orden_texto and orden_texto.isdigit() and 0 < int(orden_texto) < 200 else None
        filas.append((orden, codigo, nombre, hallada.start()))
    return filas


def alumnos_de_la_lista(textos: Sequence[str]) -> list[AlumnoDeLaLista]:
    """Las filas de la lista de la promoción, en orden: orden, código y nombre.

    ``textos`` son las páginas de la lista (o el libro entero: sólo se leen las
    que son lista). Tolerante a la capa: «11.9010017», «1 9210360», «129210134»
    (el 12 pegado a su código), códigos de 7 cifras (1995-1999) o de 11 (2003),
    y la lista de 1996, que no trae código. El orden que no se lee -- «I.» por
    7, «II.» por 11 -- es el siguiente al de la fila anterior; uno que se lee
    fuera de su sitio -- «1.» por 7 -- también.
    """
    plantillas = [plantilla_de_calificaciones(texto) for texto in textos]
    de_la_lista = sorted({n for bloque in _bloques_de_lista(plantillas, textos) for n in bloque})
    filas: list[tuple[int | None, str | None, str]] = []
    for numero in de_la_lista:
        filas.extend((orden, codigo, nombre) for orden, codigo, nombre, _ in _filas(plano(textos[numero - 1])))
    if sum(1 for _, codigo, _ in filas if codigo) >= PARTE_CON_CODIGO * len(filas):
        # En una lista con códigos, una «fila» sin el suyo es el texto de otra
        # cosa: «CIRUGIA ENDOC IIA FERIO», las notas que asoman en la pág. 2 de 1995.
        filas = [fila for fila in filas if fila[1]]
    alumnos: list[AlumnoDeLaLista] = []
    anterior = 0
    for orden, codigo, nombre in filas:
        if orden is None or not anterior < orden <= anterior + 3:
            # Fuera de su sitio: la siguiente a la anterior. Pero «19» tras «17»
            # sí se respeta: la fila 18 no se leyó.
            orden = anterior + 1 if orden is None or orden <= anterior or orden > anterior + 3 else orden
        alumnos.append(AlumnoDeLaLista(orden=orden, codigo=codigo, nombre=nombre))
        anterior = orden
    return alumnos


#: Desde qué parte de filas con código la lista es de las que lo traen.
PARTE_CON_CODIGO = 0.8


def filas_legibles(texto: str) -> int:
    """Cuántas filas de la lista se leen con un nombre de verdad: para elegir entre la capa y Tesseract."""
    return sum(1 for _, _, nombre, _ in _filas(plano(texto)) if len(nombre.split()) >= 2)


_ROMANOS = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
_MESES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
    "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}
_PROMOCION = re.compile(r"\bPROMOCION\s+(\d{1,2})\s+DE\s+([A-Z]+)\s+DE\s+((?:19|20)\d{2})\b")
#: «2o. PERIODO 1995», «1er. PERIODO 2003»; Tesseract lee el ordinal «20,» y
#: «FERIODO» («ALUMNOS X SEMESTRE 20, FERIODO 2002», 2003): el periodo es 1 o 2.
_PERIODO = re.compile(r"\b([12])\s?(?:[O0]|ER|ERO|DO)?\W{0,2}\s*[PF]ER\w{0,4}DO\s+(?:DE\s+)?((?:19|20)\d{2})\b")
_SEMESTRE_DE_LA_LISTA = re.compile(r"\bALUMNOS\s+(?:DEL?\s+)?([XA]|[IVX]{1,4})\s*SEMESTRE\b")


@dataclass(frozen=True, slots=True)
class TituloDeLaLista:
    """Lo que dice el encabezado de una lista: su título normalizado y su fecha."""

    titulo: str
    #: El año del periodo o de la promoción.
    anio: int | None = None
    #: La fecha entera de la promoción, «20/12/1996», si la dice.
    fecha: str | None = None


def titulo_de_la_lista(texto: str) -> TituloDeLaLista:
    """El título impreso de la lista, normalizado: «LISTA DE ALUMNOS X SEMESTRE DE ODONTOLOGIA - 2 PERIODO 1995».

    O «PROMOCION 20-12-1996» con su fecha entera. La «X» que la capa de 2003
    lee «A» es la X: no hay un semestre «A». Si el encabezado no se lee,
    «LISTA DE ALUMNOS DE ODONTOLOGIA», sin año.
    """
    p = plano(texto)
    if (hallada := _PROMOCION.search(p)) and (mes := _MESES.get(hallada.group(2))):
        dia, anio = int(hallada.group(1)), int(hallada.group(3))
        return TituloDeLaLista(f"PROMOCION {dia:02d}-{mes:02d}-{anio}", anio, f"{dia:02d}/{mes:02d}/{anio}")
    sin_espacios = p.replace(" ", "")
    semestre = "X"
    if (hallado := _SEMESTRE_DE_LA_LISTA.search(p)) and hallado.group(1) in _ROMANOS:
        semestre = hallado.group(1)
    periodo = _PERIODO.search(p)
    if periodo is None:
        # «1ER.PERLODO2003» sin espacios: el número y el año, juntos.
        if hallado := re.search(r"([12])(?:ER|[O0]|DO)?\.?[PF]ER\w{0,4}DO((?:19|20)\d{2})", sin_espacios):
            return TituloDeLaLista(
                f"LISTA DE ALUMNOS {semestre} SEMESTRE DE ODONTOLOGIA - {hallado.group(1)} PERIODO {hallado.group(2)}",
                int(hallado.group(2)),
            )
        anio = re.search(r"\b((?:19|20)\d{2})\b", p)
        return TituloDeLaLista(
            "LISTA DE ALUMNOS DE ODONTOLOGIA" + (f" {anio.group(1)}" if anio else ""),
            int(anio.group(1)) if anio else None,
        )
    numero, anio = periodo.group(1), int(periodo.group(2))
    return TituloDeLaLista(f"LISTA DE ALUMNOS {semestre} SEMESTRE DE ODONTOLOGIA - {numero} PERIODO {anio}", anio)


# -- el nombre de cada hoja ---------------------------------------------------------------

#: La constancia: «HACE CONSTAR QUE, LIZELIA M. ALFARO ZOLA, CURSO Y APROBO».
_NOMBRE_DE_LA_CONSTANCIA = re.compile(r"\bQUE\W{0,4}([A-Z][A-Z.\- ]{4,80}?)\W{0,4}(?:CURSO|HA\s+CURSADO|NO\s+HA)\b")
#: La continuación: «CONTINUACION CALIFICACIONES DE LUCY M. OTERO FRANCESCHI VIL SEMESTRE».
_NOMBRE_DE_LA_CONTINUACION = re.compile(r"\bCO[A-Z]{3,10}C[I1L]O[NR]\s+C[A-Z]{5,14}\b\W{0,3}(?:DE\b)?\W{0,3}(.{0,90})")
#: El record: «FACULTAD DE ODONTOLOGIA LUIS ALBERTO ALCALA REVOLLEDO NOMBRE DEL
#: ESTUDIANTE», o detrás del rótulo, «NOMBRE DEL ESTUDIANTE TOMAS CASTRO JIMENEZ».
_ROTULO_DEL_RECORD = re.compile(r"\bNO\w{2,4}E\s+DE\w?\s+E\w{3,9}T\w?\b")
#: La hoja de asignaturas: el nombre arriba, «LUIS A. ALCALA REVOLLEDO ASIGNATURAS».
_ANTES_DE_LAS_ASIGNATURAS = re.compile(r"^(.{0,120}?)\bA?S\w{0,2}GNA\w{0,3}T\w{0,2}(?:RAS|MS)\b")


def _hasta_el_semestre(crudo: str) -> str:
    """Lo que va antes del primer semestre, cifra o nota: «LUCY M. OTERO FRANCESCHI VIL SEMESTRE» → el nombre."""
    palabras: list[str] = []
    trozos = crudo.split()
    for indice, palabra in enumerate(trozos):
        siguiente = trozos[indice + 1] if indice + 1 < len(trozos) else ""
        if re.search(r"\d", palabra) or palabra.strip(".:;") in ("NOTA", "SEMESTRE", "REPITIO", "HABILITO"):
            break
        if siguiente.startswith("SEM") and len(palabra) <= 4:
            break
        palabras.append(palabra)
    return " ".join(palabras)


def nombre_de_la_hoja(texto: str, plantilla: str | None = None) -> str | None:
    """El nombre del alumno que trae su propia hoja, como lo imprime; ``None`` si no se lee.

    La constancia y la continuación lo escriben con los nombres primero
    («LIZELIA M. ALFARO ZOLA»); el record, encima de su rótulo («LUIS ALBERTO
    ALCALA REVOLLEDO NOMBRE DEL ESTUDIANTE»); la hoja de asignaturas, arriba
    («LUIS A. ALCALA REVOLLEDO», «BLANCO HEINS JOSE»). Lo escrito a mano sobre la
    raya no lo trae la capa: «QUE______ CURSO» no es un nombre.
    """
    cual = plantilla or plantilla_de_calificaciones(texto)
    p = plano(texto)
    crudo = None
    if cual == CONSTANCIA and (hallado := _NOMBRE_DE_LA_CONSTANCIA.search(p)):
        crudo = hallado.group(1)
    elif cual == CONTINUACION and (hallado := _NOMBRE_DE_LA_CONTINUACION.search(p)):
        crudo = _hasta_el_semestre(hallado.group(1))
    elif cual == RECORD:
        if (rotulo := _ROTULO_DEL_RECORD.search(p)) is not None:
            antes = p[max(0, rotulo.start() - 90) : rotulo.start()]
            if "ODONTOLOGIA" in antes:
                antes = antes.rsplit("ODONTOLOGIA", 1)[1]
            crudo = antes if nombre_limpio(antes) else re.split(r"\bDIRECCION\b", p[rotulo.end() : rotulo.end() + 90])[0]
        if crudo is None or nombre_limpio(crudo) is None:
            crudo = leer_ficha(texto).nombre
    elif cual == ASIGNATURAS and (hallado := _ANTES_DE_LAS_ASIGNATURAS.search(p)):
        crudo = " ".join(hallado.group(1).split()[-6:])
    if not crudo:
        return None
    # Lo de antes de la primera palabra con forma de nombre es basura del borde de la hoja.
    return nombre_limpio(_sin_basura_delante(crudo))


def _sin_basura_delante(crudo: str) -> str:
    """«R { ; .IHONNY RAFAEL ANAYA MARIN» → desde la primera palabra con forma de nombre."""
    trozos = crudo.split()
    for indice, trozo in enumerate(trozos):
        palabra = re.sub(r"[^A-Z]", "", trozo)
        if len(palabra) >= 3 and _parece_palabra(palabra):
            return " ".join(trozos[indice:])
    return crudo


# -- el parecido de dos nombres ------------------------------------------------------------


def _misma_palabra(una: str, otra: str) -> bool:
    """Si dos palabras de nombre son la misma, con los errores de la capa: una letra cada cuatro.

    La capa lee «LI» como «U» -- VAUENTE, MOUNARES, OUVO, UNAN, UUANA por
    VALIENTE, MOLINARES, OLIVO, LINAN, LILIANA (1996 y 1997) --: con esa
    confusión deshecha también son la misma.
    """
    if una == otra:
        return True
    if una.replace("LI", "U") == otra.replace("LI", "U"):
        return True
    corta = min(len(una), len(otra))
    if corta < 3:
        return False
    tope = 1 if corta < 7 else 2
    if abs(len(una) - len(otra)) > tope or (una[0] != otra[0] and una[-1] != otra[-1]):
        # Con una o dos letras cambiadas, el comienzo o el final se conserva.
        return False
    return damerau_levenshtein(una, otra, ceiling=tope) <= tope


def _en_el_texto_seguido(palabra: str, seguido: str, libres: set[int] | None = None) -> int | None:
    """Dónde está la palabra dentro del nombre de la lista sin espacios («ALFAROZOLALIZELIAM»), con una letra de margen.

    ``libres``: las letras de ``seguido`` que aún no casaron con otra palabra;
    si se da, la palabra sólo cae sobre ellas.
    """
    if len(palabra) < 3:
        return None

    def cabe(inicio: int, largo: int) -> bool:
        return libres is None or all(i in libres for i in range(inicio, inicio + largo))

    inicio = seguido.find(palabra)
    while inicio >= 0:
        if cabe(inicio, len(palabra)):
            return inicio
        inicio = seguido.find(palabra, inicio + 1)
    # Con una letra de margen, la palabra trae entero su comienzo o su final:
    # si ninguno de los dos está, no hace falta medir (es lo que hace rápido el
    # emparejamiento de un libro entero con su lista).
    if len(palabra) < 5 or (seguido.find(palabra[:2]) < 0 and seguido.find(palabra[-2:]) < 0):
        return None
    mejor, donde = 2, None
    for largo in (len(palabra) - 1, len(palabra), len(palabra) + 1):
        for inicio in range(0, len(seguido) - largo + 1):
            if seguido[inicio] != palabra[0] and seguido[inicio + largo - 1] != palabra[-1]:
                continue
            if not cabe(inicio, largo):
                continue
            distancia = damerau_levenshtein(palabra, seguido[inicio : inicio + largo], ceiling=1)
            if distancia < mejor:
                mejor, donde = distancia, inicio
    return donde


def _plenas_de(nombre: str | None) -> list[str]:
    return [p for p in palabras_del_nombre(nombre) if len(p) >= 3 and p not in _CONECTORES]


def _comunes(uno: str | None, otro: str | None, *, seguido: bool) -> tuple[float, int]:
    """Cuántas palabras plenas de ``uno`` casan con ``otro``, una a una: (comunes, plenas de ``uno``).

    Con ``seguido``, también dentro de ``otro`` sin espacios -- la capa pega
    palabras en la lista («ALFAROZOLALIZELIAM.») y las separa letra a letra en
    la de 2003 --, sin volver a usar letras ya casadas: «ESPITIA ESPITIA» no
    casa dos veces con el ESPITIA de otro.
    """
    unas, otras = _plenas_de(uno), _plenas_de(otro)
    if not unas or not otras:
        return 0.0, max(len(unas), 1)
    junto = "".join(palabras_del_nombre(otro))
    libres_del_seguido = set(range(len(junto)))
    libres = list(otras)
    comunes = 0.0
    pendientes: list[str] = []
    for palabra in unas:
        indice = next((i for i, o in enumerate(libres) if _misma_palabra(palabra, o)), None)
        if indice is None:
            pendientes.append(palabra)
            continue
        casada = libres.pop(indice)
        if (donde := _en_el_texto_seguido(casada, junto, libres_del_seguido)) is not None:
            libres_del_seguido -= set(range(donde, donde + len(casada)))
        comunes += 1
    for palabra in pendientes:
        if seguido and (donde := _en_el_texto_seguido(palabra, junto, libres_del_seguido)) is not None:
            libres_del_seguido -= set(range(donde, donde + len(palabra)))
            comunes += 1
        elif any(
            o[:1] == palabra[:1] and damerau_levenshtein(palabra, o, ceiling=len(palabra) // 3) <= len(palabra) // 3
            for o in libres
        ):
            comunes += 0.5
    return comunes, len(unas)


@lru_cache(maxsize=65536)
def parecido_de_nombres(uno: str | None, otro: str | None) -> float:
    """Qué parte de las palabras plenas de un nombre está en el otro, en cualquier orden: de 0 a 1.

    En los dos sentidos y el mejor: la palabra pegada de la lista
    («ALFAROZOLALIZELIAM») no está en la hoja, pero cada palabra de la hoja
    («LIZELIA M. ALFARO ZOLA») sí está dentro de ella.
    """
    comunes, plenas = _comunes(uno, otro, seguido=True)
    al_reves, otras = _comunes(otro, uno, seguido=True)
    return max(comunes / plenas, al_reves / otras)


#: Desde qué parte del nombre más corto dos lecturas son del mismo alumno: dos
#: hermanas -- GOMEZ DIAZ MARTHA PATRICIA y GOMEZ DIAZ PAOLA MILENA (1996,
#: págs. 53 y 55) -- comparten la mitad.
MISMO_ALUMNO = 0.75


def mismo_alumno(uno: str | None, otro: str | None) -> bool:
    """Si dos lecturas son del mismo alumno: dos palabras plenas en común y tres cuartas partes del más corto."""
    if not uno or not otro:
        return False
    if len(_plenas_de(uno)) > len(_plenas_de(otro)):
        uno, otro = otro, uno
    comunes, plenas = _comunes(uno, otro, seguido=False)
    return plenas >= 2 and comunes >= 2 and comunes / plenas >= MISMO_ALUMNO


# -- el nombre completo: la lista ordena, la hoja completa ------------------------------------


def _apellidos_primero(hoja: list[str]) -> list[str]:
    """La hoja con los nombres primero, puesta con los apellidos primero: los dos últimos (con sus partículas) delante.

    Sólo cuando no hay lista con qué ordenarla: «LUCY MARGARITA OTERO
    FRANCESCHI» → «OTERO FRANCESCHI LUCY MARGARITA», «LUIS EDUARDO DE LA PENA
    GOMEZ» → «DE LA PENA GOMEZ LUIS EDUARDO».
    """
    plenas = [i for i, p in enumerate(hoja) if p not in _CONECTORES and len(p) >= 2]
    if len(plenas) < 3:
        return hoja
    corte = plenas[-2]
    while corte > 0 and hoja[corte - 1] in _CONECTORES:
        corte -= 1
    return hoja[corte:] + hoja[:corte]


def nombre_completo(
    de_la_lista: str | None, de_la_hoja: str | None, otras: Sequence[str | None] = ()
) -> str | None:
    """El nombre con los apellidos primero como la lista y completado con lo que dice la propia hoja.

    * Cada palabra de la hoja ocupa el sitio de su pareja en la lista; primero
      las que casan palabra a palabra, luego las que caen dentro de lo que la
      capa pegó («ALFAROZOLALIZELIAM.»), sólo sobre lo que aún no casó. Un trozo
      de la hoja dentro de una palabra más larga de la lista es esa palabra
      partida o cortada por la capa de la hoja («OLI VER» por OLIVER, «LENA» por
      MILENA): va la de la lista.
    * La inicial o el comienzo de la lista se completa con la palabra de la hoja
      que empieza así: «ALCALA REVOLLEDO LUIS A.» + «LUIS ALBERTO ALCALA
      REVOLLEDO» = «ALCALA REVOLLEDO LUIS ALBERTO»; «JURADO BARROS MARIT» +
      «MARITZA ELENA…» = MARITZA. Una inicial que la hoja no trae, cuando la
      hoja da el nombre entero, es la marca de la columna de al lado
      («ZAFRA GARRIDO FILADELFO I I»): se suelta.
    * Lo que la hoja trae y la lista no -- el segundo nombre -- va al final,
      sólo si está entre lo que casó: lo de fuera es la dirección o el rótulo
      que la capa pegó al renglón («BUENOS AIRES DIAGNAL», «TOM»). Lo que es
      una palabra de la lista mal leída («YANETY» por AYNETTY) va en su sitio.
    * Lo que la lista trae y la hoja no se queda si va en medio de lo que casó
      o si tiene forma de nombre entero (LEONARDO); una palabra corta a la
      cola (« VAA») es la columna de al lado.
    * Cada palabra se vota entre la lista, la hoja y ``otras`` lecturas de las
      hojas del alumno (``_votado``).

    Sin hoja, la lista tal cual; sin lista, la hoja con los apellidos primero.
    """
    lista = palabras_del_nombre(de_la_lista)
    hoja = palabras_del_nombre(de_la_hoja)
    if not hoja:
        return nombre_limpio(" ".join(lista)) if lista else None
    if not lista:
        return _votado(_apellidos_primero(hoja), [de_la_hoja, *otras])
    inicios: list[int] = []
    posicion = 0
    for palabra in lista:
        inicios.append(posicion)
        posicion += len(palabra)
    seguido = "".join(lista)

    def de_la_lista_en(donde: int, largo: int) -> list[int]:
        return [i for i, inicio in enumerate(inicios) if inicio < donde + largo and inicio + len(lista[i]) > donde]

    usadas: set[int] = set()
    #: (sitio en la lista, palabra, sitio en la hoja)
    ubicadas: list[tuple[float, str, int]] = []
    por_ubicar: list[tuple[int, str]] = []
    # 1. Palabra a palabra, con la grafía de la lista (luego se vota).
    for donde_en_la_hoja, palabra in enumerate(hoja):
        if len(palabra) == 1 or palabra in _CONECTORES:
            continue
        indice = next((i for i, otra in enumerate(lista) if i not in usadas and _misma_palabra(palabra, otra)), None)
        if indice is None:
            por_ubicar.append((donde_en_la_hoja, palabra))
            continue
        usadas.add(indice)
        ubicadas.append((inicios[indice], lista[indice], donde_en_la_hoja))
    # 2. Dentro de lo que la lista pegó, sólo sobre las palabras que aún no casaron.
    libres = {
        letra for indice in range(len(lista)) if indice not in usadas
        for letra in range(inicios[indice], inicios[indice] + len(lista[indice]))
    }
    sin_sitio: list[tuple[int, str]] = []
    for donde_en_la_hoja, palabra in por_ubicar:
        if (donde := _en_el_texto_seguido(palabra, seguido, libres)) is not None:
            libres -= set(range(donde, donde + len(palabra)))
            tocadas = de_la_lista_en(donde, len(palabra))
            if len(tocadas) == 1 and len(palabra) < len(lista[tocadas[0]]) < PEGADO:
                # Un trozo de una palabra de la lista: va la palabra entera, una vez.
                if tocadas[0] not in usadas:
                    ubicadas.append((inicios[tocadas[0]], lista[tocadas[0]], donde_en_la_hoja))
            else:
                ubicadas.append((donde, palabra, donde_en_la_hoja))
            usadas.update(tocadas)
            continue
        indice = next(
            (
                i for i, otra in enumerate(lista)
                if i not in usadas and otra not in _CONECTORES and len(otra) < len(palabra) and palabra.startswith(otra)
            ),
            None,
        )
        if indice is not None:
            usadas.add(indice)
            ubicadas.append((inicios[indice], palabra, donde_en_la_hoja))
            continue
        sin_sitio.append((donde_en_la_hoja, palabra))
    if not ubicadas:
        return None

    def mal_leida(palabra: str, otra: str) -> bool:
        tope = max(2, len(palabra) // 3)
        return len(otra) >= 3 and damerau_levenshtein(palabra, otra, ceiling=tope) <= tope

    quedan: list[tuple[int, str]] = []
    for donde_en_la_hoja, palabra in sin_sitio:
        indice = next((i for i, otra in enumerate(lista) if i not in usadas and mal_leida(palabra, otra)), None)
        if indice is not None:
            usadas.add(indice)
            ubicadas.append((inicios[indice], lista[indice], donde_en_la_hoja))
        elif not any(mal_leida(palabra, otra) for otra in lista):
            quedan.append((donde_en_la_hoja, palabra))
    sin_sitio = quedan
    iniciales_de_la_hoja = {palabra for palabra in hoja if len(palabra) == 1}
    plenas_de_la_hoja = sum(1 for palabra in hoja if len(palabra) >= 3 and palabra not in _CONECTORES)
    ultima = max(usadas, default=-1)
    cola: list[tuple[float, str, int]] = []
    for indice, palabra in enumerate(lista):
        if indice in usadas:
            continue
        if palabra in _CONECTORES:
            ubicadas.append((inicios[indice] - 0.5 + indice * 0.001, palabra, -1))
        elif len(palabra) == 1:
            completa = next(((d, p) for d, p in sin_sitio if p.startswith(palabra)), None)
            if completa:
                sin_sitio.remove(completa)
                ubicadas.append((inicios[indice], completa[1], completa[0]))
            elif palabra in iniciales_de_la_hoja or plenas_de_la_hoja < 3:
                ubicadas.append((inicios[indice], palabra, -1))
        elif indice < ultima:
            ubicadas.append((inicios[indice], palabra, -1))
        else:
            cola.append((inicios[indice], palabra, -1))
    # Lo de la hoja sin pareja va al final, sólo si está entre lo que casó.
    casadas = [donde for _, _, donde in ubicadas if donde >= 0]
    desde, hasta = (min(casadas), max(casadas)) if casadas else (0, -1)
    extra = [palabra for donde, palabra in sin_sitio if desde < donde < hasta and palabra not in [u[1] for u in ubicadas]]
    if not extra:
        # La cola de la lista se queda si la hoja no trae otro nombre en su
        # lugar y tiene forma de nombre entero: LEONARDO en «MARIN CARO
        # LEONARDO» (1999). Si la hoja trae el suyo -- EDUARDO --, la cola es
        # la abreviatura mal leída («ETUF», «AIIO»).
        ubicadas.extend(par for par in cola if len(par[1]) >= 4 and _de_nombre(par[1]))
    # La inicial de la hoja va detrás de la palabra que la precede en la hoja
    # -- «ANDREA C. PEREZ MORALES» --, si la lista no la trae ya suelta: dentro
    # de lo que la lista pegó («PEREZMORALESANDREAC») no tenía sitio propio.
    # Sólo la que va entre dos palabras que casaron: la de la cola es basura del
    # renglón («TANIA CECILIA AGUAS POLO I.. VIL SEMESTRE», 1996, pág. 4).
    sueltas_de_la_lista = {p for _, p, _ in ubicadas if len(p) == 1}
    casadas_de_la_hoja = {donde for _, _, donde in ubicadas if donde >= 0}
    for indice, palabra in enumerate(hoja):
        if (
            len(palabra) != 1
            or palabra in sueltas_de_la_lista
            or indice == 0
            or not any(donde > indice for donde in casadas_de_la_hoja)
        ):
            continue
        anterior = next((sitio for sitio, _, donde in ubicadas if donde == indice - 1), None)
        if anterior is not None:
            ubicadas.append((anterior + 0.5, palabra, indice))
            sueltas_de_la_lista.add(palabra)
    ordenadas = [palabra for _, palabra, _ in sorted(ubicadas, key=lambda par: par[0])]
    # Las repetidas de verdad se quedan: «ESPITIA ESPITIA EUBALDO ESTEBAN».
    return _votado(ordenadas + extra, [de_la_lista, de_la_hoja, *otras])


def _votado(palabras: Sequence[str], lecturas: Sequence[str | None]) -> str | None:
    """Cada palabra con la grafía que más lecturas dicen; nunca una imposible si hay otra; en un empate, la que estaba."""
    leidas = [palabras_del_nombre(lectura) for lectura in lecturas if lectura]
    votado: list[str] = []
    for palabra in palabras:
        if len(palabra) < 3 or palabra in _CONECTORES:
            votado.append(palabra)
            continue
        votos: dict[str, int] = {}
        sin_pareja: list[str] = []
        for leida in leidas:
            pareja = next((p for p in leida if p == palabra), None) or next(
                (p for p in leida if _misma_palabra(palabra, p)), None
            )
            if pareja:
                votos[pareja] = votos.get(pareja, 0) + 1
            else:
                sin_pareja.append("".join(leida))
        # La lectura que la pegó con otras («ARRIETAVERGARAKATHERINE») vota por
        # la grafía que trae dentro: VERGARA y no VERSARA.
        for junta in sin_pareja:
            for grafia in [g for g in votos if len(g) >= 5 and g in junta][:1]:
                votos[grafia] += 1
        if not votos:
            votado.append(palabra)
            continue
        votado.append(max(votos, key=lambda p: (not palabra_dudosa(p), votos[p], p == palabra)))
    return nombre_limpio(" ".join(votado))


#: La casilla de la cédula del record: «C.C. # 73.141.230». La capa y Tesseract
#: leen el «#» como «4», «*» o «_» («C.C 4 73.141.230», «C.C. * _45,766,044»,
#: 1998, págs. 3 y 7), y separan los miles con punto, coma o espacio
#: («46.766 044»). El «4» suelto sólo es el «#» si va separado de la cédula.
_CEDULA_DEL_RECORD = re.compile(
    r"\bC\s?\.?\s?C\b\.?\s*(?:[#*]|4(?=\s))?[\s_]*(\d{1,3}(?:[.,\s]\s?\d{3}){2}|\d{1,3}(?:[.,]\d{3}){3}|\d{6,10})(?![\d.,]?\d)"
)


def cedula_del_record(texto: str) -> str | None:
    """La cédula de la casilla «C.C. #» del record, sólo sus cifras; ``None`` si no se lee una con forma de cédula."""
    if hallada := _CEDULA_DEL_RECORD.search(plano(texto)):
        cifras = re.sub(r"\D", "", hallada.group(1))
        if 6 <= len(cifras) <= 8 or (len(cifras) == 10 and cifras.startswith("1")):
            return cifras
    return None


def asunto_de_calificaciones(nombre: str, especialidad: str = ODONTOLOGIA) -> str:
    """El asunto de la fila de un alumno y el nombre de su PDF: «NOMBRE - ESPECIALIDAD»."""
    return f"{nombre} - {especialidad}"


# -- los años de sus notas -----------------------------------------------------------------

#: Los años que escriben las notas: «1ER. SEMESTRE 1990», «REPITIO … EL 1ER.
#: SEMESTRE DE 1992», «SEM V AÑO 1993» (la capa lee el AÑO «AFIO», «ARTO»,
#: «ANOZ») y «AÑO 96». Nunca la fecha de la carta, ni la de nacimiento, ni la
#: del grado: no son de sus notas.
_ANIO_DE_SEMESTRE = re.compile(r"\bSEMESTRE\s+(?:DE\s+)?((?:19|20)\d{2})\b")
_ANIO_DE_LA_TABLA = re.compile(r"\b(?:ANO|AFIO|ARTO|AFTO|ANOL?)\W{0,3}((?:19|20)\d{2}|\d{2})\b")
#: Cuántos años antes del periodo de la lista puede empezar un alumno: diez
#: semestres, y alguno repite.
ANIOS_DE_CARRERA = 10


def anios_de_las_notas(textos: Sequence[str], periodo: int | None = None) -> tuple[int | None, int | None]:
    """El primer y el último año de las notas de un alumno.

    El último, si las notas no lo dicen -- la constancia sólo escribe el año del
    primer semestre --, es el del periodo de la lista: el del X semestre de toda
    la promoción. Con el periodo, un año que no cabe en la carrera es una mala
    lectura.
    """
    vistos: list[int] = []
    for texto in textos:
        p = plano(texto)
        vistos.extend(int(h.group(1)) for h in _ANIO_DE_SEMESTRE.finditer(p))
        for hallado in _ANIO_DE_LA_TABLA.finditer(p):
            cifras = hallado.group(1)
            vistos.append(int(cifras) if len(cifras) == 4 else 1900 + int(cifras) if int(cifras) >= 50 else 2000 + int(cifras))
    if periodo is not None:
        vistos = [anio for anio in vistos if periodo - ANIOS_DE_CARRERA <= anio <= periodo + 1]
    else:
        vistos = [anio for anio in vistos if 1950 <= anio <= 2030]
    if not vistos:
        return None, periodo
    return min(vistos), max([*vistos, *([periodo] if periodo else [])])


def anio_del_codigo(codigo: str | None) -> int | None:
    """El año de ingreso que dice el código de la lista: «9010072» (1990), «52199810009» (1998), «529010027» (1990)."""
    cifras = re.sub(r"\D", "", codigo or "")
    if len(cifras) == 7:
        return 1900 + int(cifras[:2]) if int(cifras[:2]) >= 50 else None
    if len(cifras) == 9 and cifras.startswith("5"):
        return 1900 + int(cifras[2:4]) if int(cifras[2:4]) >= 50 else None
    if len(cifras) == 11 and (anio := int(cifras[2:6])) and 1950 <= anio <= 2030:
        return anio
    return None


# -- el reparto del libro ---------------------------------------------------------------------


@dataclass
class UnidadDeCalificaciones(Expediente):
    """Un documento del libro: un alumno (``ficha``) o una lista (``ficha`` ``None`` y ``tipo`` LISTA_DE_ALUMNOS).

    Es un ``Expediente`` de ``historia_academica``: el trabajo de las historias
    lo lee, lo revisa y lo escribe igual -- ``paginas``, ``ficha``,
    ``pagina_de_la_ficha`` (su hoja A, la que lee la IA), ``dudas`` --.
    """

    tipo: str = CALIFICACIONES
    #: Las páginas de cada clase: su hoja A, su hoja B y sus anexos.
    hojas_a: list[int] = field(default_factory=list)
    hojas_b: list[int] = field(default_factory=list)
    anexos: list[int] = field(default_factory=list)
    #: Lo que se leyó del nombre en cada hoja suya, como lo imprime.
    lecturas_de_la_hoja: list[str] = field(default_factory=list)
    #: Su fila de la lista, si se emparejó.
    de_la_lista: AlumnoDeLaLista | None = None
    #: Si el nombre es el de la lista tal cual, porque su hoja no se leyó.
    nombre_de_la_lista: bool = False
    #: Si la hoja dice otro nombre que la lista.
    no_cuadra: bool = False
    anio_inicial: int | None = None
    anio_final: int | None = None
    #: Si el año final es el del periodo de la lista y no de sus notas.
    final_de_la_lista: bool = False
    #: Si el año inicial es el que dice su código.
    inicial_del_codigo: bool = False
    #: El año del periodo de su lista: el del X semestre de la promoción.
    periodo: int | None = None
    #: Lo que la fila dice de cómo se leyó un dato, sin ser una duda.
    notas: list[str] = field(default_factory=list)
    #: La lista: su título y su fecha; y sus filas.
    titulo: TituloDeLaLista | None = None
    alumnos: list[AlumnoDeLaLista] = field(default_factory=list)

    @property
    def es_de_un_estudiante(self) -> bool:
        return self.tipo == CALIFICACIONES and self.ficha is not None


def _bloques_de_lista(plantillas: Sequence[str | None], textos: Sequence[str]) -> list[list[int]]:
    """Las páginas de cada lista: la del encabezado y las que la siguen con sus filas.

    Sigue la lista la página con filas sin encabezado, la que repite el mismo
    encabezado (2003, págs. 1 y 2) y la que sólo trae las últimas filas con el
    orden seguido (1995, pág. 2: la 46 y la 47).
    """
    bloques: list[list[int]] = []
    ultimo_orden: int | None = None
    for numero, cual in enumerate(plantillas, start=1):
        pegada = bool(bloques) and bloques[-1][-1] == numero - 1
        filas = _filas(plano(textos[numero - 1])) if cual in (LISTA, LISTA_SIGUE, None) else []
        ordenes = [orden for orden, _, _, _ in filas if orden is not None]
        if cual == LISTA:
            # La que repite el encabezado de la anterior, aunque una de las dos
            # lecturas pierda el periodo: el mismo año, la misma lista.
            mismo_titulo = False
            if pegada:
                este, aquel = titulo_de_la_lista(textos[numero - 1]), titulo_de_la_lista(textos[bloques[-1][0] - 1])
                mismo_titulo = este == aquel or (este.anio is not None and este.anio == aquel.anio)
            if mismo_titulo:
                bloques[-1].append(numero)
            else:
                bloques.append([numero])
        elif cual == LISTA_SIGUE and pegada or cual is None and pegada and ordenes and ultimo_orden is not None and 0 < ordenes[0] - ultimo_orden <= 2:
            bloques[-1].append(numero)
        else:
            continue
        if ordenes:
            ultimo_orden = max(ordenes)
    return bloques


def unidades_del_libro(
    textos: Sequence[str],
    fichas: dict[int, Ficha] | None = None,
) -> list[UnidadDeCalificaciones]:
    """Las unidades del libro, en el orden del papel: cada lista y cada alumno, cada página en una sola.

    ``textos`` es el texto de cada página (la primera es la 1). ``fichas``
    trae, si se tiene, lo que se leyó mejor del record de una página (con la
    IA); si no, se lee del mismo texto. El nombre, el código, la cédula y los
    años quedan puestos; la ``ficha`` de cada alumno lleva el nombre completo
    (lista y hoja), su código y su cédula.
    """
    fichas = fichas or {}
    plantillas = [plantilla_de_calificaciones(texto) for texto in textos]
    bloques = _bloques_de_lista(plantillas, textos)
    de_lista = {numero for bloque in bloques for numero in bloque}
    clases: list[str | None] = []
    for numero, cual in enumerate(plantillas, start=1):
        if cual in (LISTA, LISTA_SIGUE) and numero not in de_lista:
            cual = None  # filas sueltas lejos de su lista: un anexo
        clases.append(LISTA if numero in de_lista else cual)
    nombres = {
        numero: nombre
        for numero, cual in enumerate(clases, start=1)
        if cual in HOJAS_QUE_ABREN | HOJAS_QUE_SIGUEN and (nombre := nombre_de_la_hoja(textos[numero - 1], cual))
    }

    unidades: list[UnidadDeCalificaciones] = []
    #: Las hojas B y los anexos que esperan a la apertura que viene: lo que va
    #: entre la lista y el primer alumno es de ese alumno.
    pendientes_b: list[int] = []
    pendientes_anexos: list[int] = []
    actual: UnidadDeCalificaciones | None = None

    def siguiente_apertura(desde: int) -> int | None:
        for numero in range(desde + 1, len(clases) + 1):
            if clases[numero - 1] in HOJAS_QUE_ABREN or clases[numero - 1] in (LISTA,):
                return numero if clases[numero - 1] in HOJAS_QUE_ABREN else None
            if clases[numero - 1] in HOJAS_QUE_SIGUEN:
                return None
        return None

    def la_siguiente_trae_su_b(apertura: int) -> bool:
        for numero in range(apertura + 1, len(clases) + 1):
            cual = clases[numero - 1]
            if cual in HOJAS_QUE_SIGUEN:
                return True
            if cual is not None:
                return False
        return False

    for numero, cual in enumerate(clases, start=1):
        if numero in de_lista:
            if (bloque := next((b for b in bloques if b[0] == numero), None)) is not None:
                # El encabezado mejor leído de sus páginas: el que dice el periodo o la promoción.
                titulos = [titulo_de_la_lista(textos[n - 1]) for n in bloque]
                titulo = next((t for t in titulos if t.fecha or " PERIODO " in t.titulo), titulos[0])
                unidades.append(
                    UnidadDeCalificaciones(
                        paginas=list(bloque), ficha=None, plantilla=LISTA, tipo=LISTA_DE_ALUMNOS, titulo=titulo,
                        alumnos=alumnos_de_la_lista([textos[n - 1] for n in bloque]),
                    )
                )
                actual = None
            continue
        if cual in HOJAS_QUE_ABREN:
            nombre = nombres.get(numero)
            ficha_del_record = fichas.get(numero) or (leer_ficha(textos[numero - 1]) if cual == RECORD else None)
            codigo = ficha_del_record.codigo if ficha_del_record else None
            mismo = actual is not None and actual.ficha is not None and (
                any(mismo_alumno(nombre, leida) for leida in actual.lecturas_de_la_hoja)
                or (codigo and actual.ficha.codigo and codigo == actual.ficha.codigo)
            )
            if mismo:
                # La 2.ª constancia del mismo alumno («ha cursado»): suya.
                actual.paginas.append(numero)
                actual.hojas_a.append(numero)
                if nombre:
                    actual.lecturas_de_la_hoja.append(nombre)
                actual.dudas.append(f"la página {numero} es otra hoja de apertura del mismo alumno, unida a la suya")
                continue
            actual = UnidadDeCalificaciones(
                paginas=[*pendientes_anexos, *pendientes_b, numero],
                ficha=Ficha(
                    nombre=nombre,
                    cedula=(cedula_del_record(textos[numero - 1]) or ficha_del_record.cedula) if ficha_del_record else None,
                    codigo=codigo,
                    anio_de_grado=ficha_del_record.anio_de_grado if ficha_del_record else None,
                    tarjeta=ficha_del_record.tarjeta if ficha_del_record else None,
                    libreta=ficha_del_record.libreta if ficha_del_record else None,
                ),
                plantilla=cual,
                pagina_de_la_ficha=numero,
                hojas_a=[numero],
                hojas_b=list(pendientes_b),
                anexos=list(pendientes_anexos),
                lecturas_de_la_hoja=[n for n in (nombre, *(nombres.get(b) for b in pendientes_b)) if n],
            )
            if pendientes_b:
                actual.dudas.append(
                    f"la hoja {'continuación' if cual == CONSTANCIA else 'de asignaturas'} de la página "
                    f"{pendientes_b[0]} va antes de su apertura"
                )
            pendientes_b, pendientes_anexos = [], []
            unidades.append(actual)
            continue
        if cual in HOJAS_QUE_SIGUEN:
            nombre = nombres.get(numero)
            proxima = siguiente_apertura(numero)
            if actual is None:
                pendientes_b.append(numero)
                continue
            de_la_proxima = (
                proxima is not None
                and nombre is not None
                and mismo_alumno(nombre, nombres.get(proxima))
                and not any(mismo_alumno(nombre, leida) for leida in actual.lecturas_de_la_hoja)
            )
            del_actual = nombre is not None and any(mismo_alumno(nombre, leida) for leida in actual.lecturas_de_la_hoja)
            if de_la_proxima or (
                not del_actual
                and actual.hojas_b
                and proxima is not None
                and not la_siguiente_trae_su_b(proxima)
            ):
                # La B de la apertura que viene, escaneada antes que ella.
                pendientes_b.append(numero)
                continue
            if actual.hojas_b and not del_actual:
                actual.dudas.append(f"la página {numero} es otra hoja de notas del mismo alumno")
            actual.paginas.append(numero)
            actual.hojas_b.append(numero)
            if nombre:
                actual.lecturas_de_la_hoja.append(nombre)
            continue
        # Un anexo: con el alumno en curso, o con el que viene si aún no hay ninguno.
        if actual is None:
            pendientes_anexos.append(numero)
        else:
            actual.paginas.append(numero)
            actual.anexos.append(numero)
    if pendientes_b or pendientes_anexos:
        # Lo que quedó al final sin apertura detrás: del último alumno.
        ultimo = next((u for u in reversed(unidades) if u.tipo == CALIFICACIONES), None)
        if ultimo is not None:
            for numero in sorted(pendientes_b + pendientes_anexos):
                ultimo.paginas.append(numero)
                (ultimo.hojas_b if numero in pendientes_b else ultimo.anexos).append(numero)
        elif unidades:
            unidades[-1].paginas.extend(sorted(pendientes_b + pendientes_anexos))
    _anexos_con_su_alumno(unidades, textos)
    for unidad in unidades:
        unidad.paginas.sort()
    _con_la_lista(unidades, textos)
    return unidades


def _anexos_con_su_alumno(unidades: list[UnidadDeCalificaciones], textos: Sequence[str]) -> None:
    """Cada anexo con el alumno vecino cuyo nombre o cédula trae; si no nombra a nadie, se queda con el anterior.

    1999, pág. 69: el certificado de LEONARDO LAJIN CARO va con su record, que
    viene detrás.
    """
    alumnos = [u for u in unidades if u.tipo == CALIFICACIONES]
    for indice, unidad in enumerate(alumnos):
        siguiente = alumnos[indice + 1] if indice + 1 < len(alumnos) else None
        if siguiente is None:
            continue
        # Sólo los anexos del final, los que están entre su última hoja y la siguiente apertura.
        cola = [n for n in sorted(unidad.anexos) if n > max(unidad.hojas_a + unidad.hojas_b)]
        for numero in cola:
            texto = plano(textos[numero - 1])
            del_siguiente = _lo_nombra(texto, siguiente)
            suyo = _lo_nombra(texto, unidad)
            if del_siguiente and not suyo:
                unidad.anexos.remove(numero)
                unidad.paginas.remove(numero)
                siguiente.anexos.append(numero)
                siguiente.paginas.append(numero)
                siguiente.dudas.append(f"la página {numero} es un anexo que lo nombra y va antes de su apertura")


def _lo_nombra(texto: str, unidad: UnidadDeCalificaciones) -> bool:
    """Si el texto de un anexo trae el nombre (dos palabras plenas) o la cédula del alumno."""
    if unidad.ficha is not None and unidad.ficha.cedula and unidad.ficha.cedula in re.sub(r"(?<=\d)[.,\s](?=\d)", "", texto):
        return True
    palabras = set(re.findall(r"[A-Z]{3,}", texto))
    for leida in unidad.lecturas_de_la_hoja:
        plenas = [p for p in palabras_del_nombre(leida) if len(p) >= 4 and p not in _CONECTORES]
        if len(plenas) >= 2 and sum(1 for p in plenas if p in palabras) >= 2:
            return True
    return False


# -- el emparejamiento con la lista -----------------------------------------------------------

#: Lo que suma emparejar un alumno sin nombre legible con la fila que le toca:
#: el orden solo. Lo que cuesta saltarse una fila o un alumno.
POR_EL_ORDEN = 0.3
#: Lo que suma además si el número impreso de la fila es el puesto del alumno.
POR_SU_NUMERO = 0.4
HUECO = 0.5


def emparejar_con_la_lista(
    lecturas: Sequence[Sequence[str]], filas: Sequence[AlumnoDeLaLista]
) -> list[int | None]:
    """La fila de la lista de cada alumno, por orden y por nombre: el índice en ``filas`` o ``None``.

    ``lecturas`` son, por alumno y en el orden del libro, los nombres que se
    leyeron en sus hojas (vacío si ninguno). Un alineamiento con huecos
    (programación dinámica): emparejar un alumno con nombre suma su parecido
    con la fila (negativo si no se parecen), uno sin nombre suma un poco por el
    orden, y saltarse una fila o un alumno cuesta. En 1995, el alumno k es la
    fila k (ALFARO = 1, HERNANDEZ ALVAREZ ARLETH = 20, MERCADO NAVAS = 30,
    OLIER PIMIENTA = 32); en 1997 la fila 18 no se lee y no corre a las demás.
    """
    n, m = len(lecturas), len(filas)
    if not n or not m:
        return [None] * n
    # Al revés, para que ante un empate -- alumnos sin nombre y una fila de
    # menos -- el hueco quede al final y no corra a los primeros.
    lecturas, filas = list(lecturas)[::-1], list(filas)[::-1]

    def de_la_pareja(i: int, j: int) -> float:
        suyas = [lectura for lectura in lecturas[i] if lectura]
        if not suyas:
            # Sin nombre, el orden: y mejor la fila cuyo número impreso es el
            # puesto del alumno en el libro -- el k-ésimo es la fila k --, que
            # no se corre cuando la capa no dejó leer una fila de en medio (2003).
            return POR_EL_ORDEN + (POR_SU_NUMERO if filas[j].orden == n - i else 0.0)
        parecido = max(parecido_de_nombres(lectura, filas[j].nombre) for lectura in suyas)
        return 2 * parecido - 0.8

    matriz = [[de_la_pareja(i, j) for j in range(m)] for i in range(n)]

    def puntos(i: int, j: int) -> float:
        return matriz[i][j]

    tabla = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        tabla[i][0] = -HUECO * i
    for j in range(1, m + 1):
        tabla[0][j] = -HUECO * j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            tabla[i][j] = max(
                tabla[i - 1][j - 1] + puntos(i - 1, j - 1),
                tabla[i - 1][j] - HUECO,
                tabla[i][j - 1] - HUECO,
            )
    pareja: list[int | None] = [None] * n
    i, j = n, m
    while i and j:
        if abs(tabla[i][j] - (tabla[i - 1][j - 1] + puntos(i - 1, j - 1))) < 1e-9:
            pareja[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif abs(tabla[i][j] - (tabla[i - 1][j] - HUECO)) < 1e-9:
            i -= 1
        else:
            j -= 1
    return [None if indice is None else m - 1 - indice for indice in pareja[::-1]]


def _con_la_lista(unidades: list[UnidadDeCalificaciones], textos: Sequence[str]) -> None:
    """Cada alumno con su fila de la lista que lo precede, y su nombre, código y años.

    El nombre: los apellidos primero como la lista y completado con la hoja
    (``nombre_completo``); si la hoja no se leyó, el de la lista tal cual
    (``nombre_de_la_lista``); si la hoja dice otro, el de la hoja (``no_cuadra``).
    El código, el del record si se leyó; si no, el de la lista.
    """

    grupos: list[tuple[UnidadDeCalificaciones | None, list[UnidadDeCalificaciones]]] = []
    for unidad in unidades:
        if unidad.tipo == LISTA_DE_ALUMNOS:
            grupos.append((unidad, []))
        else:
            if not grupos:
                grupos.append((None, []))
            grupos[-1][1].append(unidad)
    # Los alumnos que vienen tras una lista de una o dos filas -- la del 1er.
    # periodo de 2003 -- se emparejan con la de la promoción si su lista no
    # los nombra.
    principal = max(
        (lista for lista, _ in grupos if lista is not None), key=lambda lista: len(lista.alumnos), default=None
    )
    usadas: set[int] = set()
    sueltos: list[UnidadDeCalificaciones] = []
    for lista, alumnos in grupos:
        filas = list(lista.alumnos) if lista is not None else []
        periodo = lista.titulo.anio if lista is not None and lista.titulo else None
        if principal is not None and lista is not principal and len(filas) < len(alumnos):
            filas = filas + [fila for fila in principal.alumnos if fila not in filas and id(fila) not in usadas]
            periodo = periodo or (principal.titulo.anio if principal.titulo else None)
        parejas = emparejar_con_la_lista([u.lecturas_de_la_hoja for u in alumnos], filas)
        for unidad, indice in zip(alumnos, parejas, strict=True):
            unidad.de_la_lista = filas[indice] if indice is not None else None
            if unidad.de_la_lista is not None:
                usadas.add(id(unidad.de_la_lista))
            elif lista is not None:
                sueltos.append(unidad)
            unidad.periodo = periodo
    # El alumno que el orden no emparejó -- su record va al final del libro, como
    # BARON OVALLE RICARDO en 1998 --, con la fila libre que más se le parece.
    libres = [fila for lista, _ in grupos if lista is not None for fila in lista.alumnos if id(fila) not in usadas]
    for unidad in sueltos:
        mejor = max(
            libres,
            key=lambda fila: max((parecido_de_nombres(leida, fila.nombre) for leida in unidad.lecturas_de_la_hoja), default=0),
            default=None,
        )
        if mejor is not None and any(mismo_alumno(lectura, mejor.nombre) for lectura in unidad.lecturas_de_la_hoja):
            unidad.de_la_lista = mejor
            libres.remove(mejor)
            unidad.dudas.append(f"emparejado por el nombre con la fila {mejor.orden} de la lista, fuera de su orden")
    for _, alumnos in grupos:
        for unidad in alumnos:
            datos_del_alumno(unidad, textos)


def datos_del_alumno(unidad: UnidadDeCalificaciones, textos: Sequence[str]) -> None:
    """El nombre, el código y los años del alumno, con su fila de la lista.

    El nombre: los apellidos primero como la lista y completado con la hoja
    (``nombre_completo``). Si la hoja no se leyó, o sólo una lectura suya dice
    otro nombre que la lista, el de la lista tal cual (``nombre_de_la_lista``):
    la capa leyó otra cosa («UQV ISI», 1995, pág. 39). Si dos lecturas de la
    hoja dicen otro nombre, el de la hoja (``no_cuadra``). Lo uno y lo otro se
    dicen en la Revisión.

    Se puede llamar otra vez cuando llegan lecturas nuevas -- las de la IA --:
    sus dudas se rehacen, no se repiten.
    """
    from dataclasses import replace

    unidad.dudas[:] = [duda for duda in unidad.dudas if not duda.startswith(_DUDAS_DEL_NOMBRE)]
    fila = unidad.de_la_lista
    periodo = unidad.periodo
    lecturas = unidad.lecturas_de_la_hoja
    unidad.no_cuadra = bool(fila and lecturas) and not any(
        parecido_de_nombres(lectura, fila.nombre) >= 0.5 for lectura in lecturas
    )
    leida = hoja = max(lecturas, key=lambda n: len(palabras_del_nombre(n)), default=None)
    if fila is not None and unidad.no_cuadra and not _la_confirman(hoja, lecturas):
        hoja = None
    otras = [lectura for lectura in lecturas if lectura != hoja]
    if fila is not None and hoja is not None and not unidad.no_cuadra:
        nombre = nombre_completo(fila.nombre, hoja, otras)
    elif hoja is not None:
        nombre = nombre_completo(None, hoja, otras)
    else:
        nombre = nombre_completo(fila.nombre, None) if fila is not None else None
    unidad.nombre_de_la_lista = hoja is None and fila is not None
    codigo = (unidad.ficha.codigo if unidad.ficha else None) or (fila.codigo if fila else None)
    unidad.ficha = replace(unidad.ficha or Ficha(), nombre=nombre, codigo=codigo)
    de_sus_hojas = [textos[n - 1] for n in unidad.paginas if n not in unidad.anexos]
    inicial, final = anios_de_las_notas(de_sus_hojas, periodo)
    unidad.final_de_la_lista = periodo is not None and final == periodo and anios_de_las_notas(de_sus_hojas, None)[1] != periodo
    if inicial is None and (del_codigo := anio_del_codigo(codigo)) is not None:
        inicial, unidad.inicial_del_codigo = del_codigo, True
    unidad.anio_inicial, unidad.anio_final = inicial, final
    if fila is not None and unidad.no_cuadra:
        unidad.dudas.append(
            f"{_DUDAS_DEL_NOMBRE[0]}«{leida}» no cuadra con el de la fila {fila.orden} de la lista «{fila.nombre}»"
        )
    elif fila is None:
        unidad.dudas.append(_DUDAS_DEL_NOMBRE[1])


#: Cómo empiezan las dudas que pone ``datos_del_alumno``: se rehacen cada vez.
_DUDAS_DEL_NOMBRE = ("el nombre de la hoja ", "el alumno no se encontró en la lista de la promoción")


def _la_confirman(nombre: str | None, lecturas: Sequence[str]) -> bool:
    """Si otra lectura de las hojas del alumno dice el mismo nombre."""
    return sum(1 for lectura in lecturas if mismo_alumno(nombre, lectura)) >= 2


def cuadre_con_la_lista(unidades: Sequence[UnidadDeCalificaciones]) -> dict[str, int]:
    """Cuántos alumnos dice la lista y cuántos PDF de alumnos salieron: el cuadre de la Revisión."""
    filas = sum(len(u.alumnos) for u in unidades if u.tipo == LISTA_DE_ALUMNOS)
    alumnos = sum(1 for u in unidades if u.tipo == CALIFICACIONES)
    emparejados = sum(1 for u in unidades if u.tipo == CALIFICACIONES and u.de_la_lista is not None)
    return {"en_la_lista": filas, "alumnos": alumnos, "emparejados": emparejados}
