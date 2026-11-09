"""Las historias académicas de una facultad: un expediente por estudiante.

Lo pidió el operador el 2026-10-29 para «14. ENFERMERIA 3277-3283 P»: 48 PDF de
historias académicas de Enfermería -- egresados, retirados e inactivos de 1968
a 2009 --, divididos por estudiante e inventariados en el FUID FO-GD-008 «como
las actas de grado», una fila por estudiante.

Cada expediente abre con una página que identifica al estudiante, y sigue con
sus hojas de notas y lo que se le archivó detrás (el flujograma del plan, la
carta que pidió el reingreso, el oficio que lo aprobó). Las formas de abrir que
trae la carpeta, medidas sobre sus 48 PDF (2026-10-30):

* La ficha de ingreso de 1968 a 1999: «UNIVERSIDAD DE CARTAGENA · ENFERMERIA ·
  Registro del estudiante · Nombre del estudiante · Cédula No. · Código · Fecha
  de Grado», con diez rótulos de datos personales -- dirección actual, lugar y
  fecha de nacimiento, estado civil, nombre de los padres, colegio, libreta
  militar, pruebas del ICFES… -- que ninguna hoja de notas trae. La capa de
  texto rompe «Nombre del estudiante» («NPMBRE», «NOINLIRE», «ESTUDIAJJTE») en
  una de cada diez fichas de los 70 y 80: por eso basta con dos de esos rótulos.
  Con sólo «Nombre del estudiante» la regla perdía estudiantes: 43 de 60 en
  «2001», 67 de 91 en «2002», 21 de 39 en «2002-2».
* La de 2003 en adelante: «FICHA HISTORIA ACADEMICA DE ESTUDIANTE · APELLIDOS ·
  NOMBRES».
* La de alrededor del 2000: «ESTUDIANTE · SEXO · TELÉFONO · DIRECCIÓN».
* El «CERTIFICADO DE MATRÍCULA ACADÉMICA» con el nombre del estudiante.

Dos páginas seguidas que abren son el mismo expediente sólo si son de
plantillas distintas -- la ficha y, detrás, su certificado de matrícula -- y
dicen el mismo código o la misma cédula, que son cifras: el nombre leído de la
capa de texto unía estudiantes distintos («REGISTRO DEL», el rótulo tomado por
un nombre). Lo que va antes de la primera ficha no es de nadie: sale en su
propio PDF y sin fila, como las hojas de la ceremonia en las actas de grado.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field

from .doble_lectura import Franja
from .rotulo_de_cedula import tiene_rotulo

#: La clase de las filas de esta habilidad en el inventario, y la de las páginas
#: que no son de ningún estudiante (las de antes de la primera ficha).
HISTORIA_ACADEMICA = "HISTORIA ACADEMICA"
SIN_ESTUDIANTE = "SIN ESTUDIANTE"
CLASES = frozenset({HISTORIA_ACADEMICA, SIN_ESTUDIANTE})

#: Con qué se identifica un estudiante, en este orden: lo que va en el nombre
#: del PDF y en el consecutivo inicial del FUID.
CEDULA = "cédula"
TARJETA = "tarjeta de identidad"
LIBRETA = "libreta militar"


def plano(texto: str) -> str:
    """Mayúsculas sin tildes y con un solo espacio: así se comparan las leyendas."""
    sin_tildes = unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.upper().split())


# -- qué página abre un expediente -----------------------------------------------

#: Las plantillas de la página que abre el expediente de un estudiante.
FICHA = "FICHA"
FICHA_NUEVA = "FICHA HISTORIA ACADEMICA"
FICHA_CON_SEXO = "FICHA CON SEXO"
CERTIFICADO = "CERTIFICADO DE MATRICULA"

#: Las leyendas que dicen por sí solas que la página abre el expediente.
_ABRE = (
    "NOMBRE DEL ESTUDIANTE",
    "FICHA HISTORIA ACADEMICA",
    "CERTIFICADO DE MATRICULA ACADEMICA",
)
#: La ficha de alrededor del 2000: «ESTUDIANTE · SEXO · TELÉFONO · DIRECCIÓN»,
#: dentro de su cabecera. La hoja de notas también dice «ESTUDIANTE:», pero no
#: trae ni el sexo ni el teléfono.
_FICHA_CON_SEXO = re.compile(r"\bESTUDIANTE\b.{0,60}\bSEXO\b.{0,80}\bTELEFONO\b")
#: Cuánto del principio de una página se mira para la ficha con sexo.
_CABEZA = 600

#: Los rótulos de datos personales que sólo trae la ficha de ingreso (plantillas
#: de 1968 a 1999). Ninguna hoja de notas ni anexo de los 48 PDF trae dos.
LEYENDAS_DE_LA_FICHA = (
    "REGISTRO DEL ESTUDIANTE",
    "DIRECCION ACTUAL",
    "LUGAR DE NACIMIENTO",
    "FECHA DE NACIMIENTO",
    "ESTADO CIVIL",
    "NOMBRE DE LOS PADRES",
    "BACHILLER DEL COLEGIO",
    "DIPLOMA DE BACHILLER",
    "LIBRETA MILITAR",
    "NOMBRE DEL ACUDIENTE",
    "PRUEBAS DE ADMISION",
    "PRUEBAS DEL ICFES",
    "REGISTRO DE ACTIVIDADES",
    "EXPERIENCIAS PROFESIONALES",
)
MINIMO_DE_LEYENDAS = 2

#: Lo que trae la hoja de notas y nunca la ficha: una página así no abre nada y
#: no hace falta releerla. «PROMEDIO» no: la ficha lo trae tres veces («Promedio:»
#: de las pruebas de admisión, «Promedio aritmético de calificaciones»), y con él
#: una ficha de capa rota no se releía nunca.
DE_NOTAS = ("ASIGNATURA", "REGISTRO ACADEMICO", "FLUJOGRAMA", "HAB. SUPL", "SUPL. CRE")


def leyendas_de_la_ficha(texto: str) -> int:
    """Cuántos rótulos de datos personales de la ficha de ingreso trae la página."""
    p = plano(texto)
    return sum(1 for leyenda in LEYENDAS_DE_LA_FICHA if leyenda in p)


#: El cuerpo del certificado de matrícula cuando la capa de texto perdió su
#: título: «SEMEST. AÑO NOMBRE DEL ESTUDIANTE … CÓDIGO … FECHA EXPEDICIÓN …
#: PERIODO». Por «Nombre del estudiante» pasaba por una ficha y partía al
#: estudiante en dos (IPA 2004, págs. 8 y 31).
_CUERPO_DEL_CERTIFICADO = ("FECHA EXPEDICION", "SEMEST", "PERIODO")
#: Un recibo de pago -- el de la matrícula, el de la División Financiera --
#: trae también «Nombre del estudiante», y no abre nada: es un anexo.
_DE_UN_RECIBO = (
    "COMPROBANTE DE PAGO", "DERECHO DE MATRICULA", "DIVISION FINANCIERA",
    "RECIBO N", "RECIBO DE CAJA", "RECIBO DE PAGO",
)


def plantilla_de_apertura(texto: str) -> str | None:
    """Qué página es: una ficha, que abre, o un certificado, que sigue; ``None`` si no es ninguna.

    Medido sobre los 48 PDF de Enfermería: una página con «Nombre del
    estudiante» y ninguna leyenda de datos personales es un certificado de
    matrícula con el título roto, o un recibo, nunca una ficha.
    """
    p = plano(texto)
    leyendas = leyendas_de_la_ficha(texto)
    if leyendas == 0 and any(marca in p for marca in _DE_UN_RECIBO):
        return None
    if "CERTIFICADO DE MATRICULA" in p:
        return CERTIFICADO
    if "FICHA HISTORIA ACADEMICA" in p:
        return FICHA_NUEVA
    if _FICHA_CON_SEXO.search(p[:_CABEZA]):
        return FICHA_CON_SEXO
    if leyendas >= MINIMO_DE_LEYENDAS or ("NOMBRE DEL ESTUDIANTE" in p and leyendas >= 1):
        return FICHA
    if "NOMBRE DEL ESTUDIANTE" in p and any(marca in p for marca in _CUERPO_DEL_CERTIFICADO):
        return CERTIFICADO
    if "NOMBRE DEL ESTUDIANTE" in p:
        return FICHA
    return None


def es_ficha(plantilla: str | None) -> bool:
    """Si la plantilla es una ficha: las fichas abren, los certificados siguen."""
    return plantilla is not None and plantilla != CERTIFICADO


def abre_expediente(texto: str) -> bool:
    """Si la página abre -- o puede abrir -- un expediente: una ficha o un certificado."""
    return plantilla_de_apertura(texto) is not None


def es_de_notas(texto: str) -> bool:
    """Si la página es una hoja de notas: no abre nada y no hace falta releerla."""
    p = plano(texto)
    return any(marca in p for marca in DE_NOTAS)


# -- lo que dice la ficha ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ficha:
    """Lo que la página de apertura dice del estudiante. Lo que no se leyó, ``None``."""

    nombre: str | None = None
    cedula: str | None = None
    codigo: str | None = None
    #: El año de grado, si la ficha lo trae: «Fecha de Grado 1996».
    anio_de_grado: int | None = None
    #: La tarjeta de identidad, «650609-03314», que no es la cédula.
    tarjeta: str | None = None
    #: El número de la libreta militar: identifica al estudiante sólo si la
    #: ficha no trae ni cédula ni tarjeta (el operador, 2026-11-06: «siempre y
    #: cuando tenga cédula, o TI, o libreta militar»).
    libreta: str | None = None

    @property
    def identificacion(self) -> tuple[str, str] | None:
        """Con qué se identifica al estudiante y sus cifras: la cédula, la tarjeta o la libreta, en ese orden."""
        for tipo, numero in ((CEDULA, self.cedula), (TARJETA, self.tarjeta), (LIBRETA, self.libreta)):
            if cifras := re.sub(r"\D", "", numero or ""):
                return tipo, cifras
        return None

    @property
    def clave(self) -> str | None:
        """Con qué se reconoce al mismo estudiante en dos páginas seguidas."""
        if self.codigo:
            return f"COD:{self.codigo}"
        if self.cedula:
            return f"CC:{self.cedula}"
        if self.nombre:
            return f"NOM:{self.nombre}"
        return None


#: Un nombre: tres palabras o más en mayúsculas, sin cifras.
_NOMBRE = r"([A-Z][A-Z]+(?:\s+[A-Z][A-Z.]*){2,6})"
_NOMBRE_DESPUES = re.compile(r"NOMBRE DEL ESTUDIANTE\W{0,6}" + _NOMBRE)
_NOMBRE_ANTES = re.compile(_NOMBRE + r"\W{0,8}NOMBRE DEL ESTUDIANTE")
#: «ESTUDIANTE Matos Agudelo Johana Margarita SEXO M F»: el nombre hasta «SEXO».
_ESTUDIANTE_Y_SEXO = re.compile(r"\bESTUDIANTE\W{0,6}([A-Z][A-Z]+(?:\s+[A-Z][A-Z.]*){1,6}?)\W{0,6}SEXO\b")
_APELLIDOS_Y_NOMBRES = re.compile(
    r"APELLIDOS\W{0,3}" + r"([A-Z][A-Z ]{3,60}?)" + r"\W{0,3}NOMBRES\W{0,3}" + r"([A-Z][A-Z ]{2,60}?)(?=\s+[A-Z]+\s*[:;]|$)"
)
#: «Cédula No. 45.755.189», «Cédula o tarjeta No. CC 9'132.107», «C.C. 1047382991».
_CEDULA = re.compile(
    r"(?:CEDULA(?:\s+O\s+TARJETA)?|C\.\s*C\.)\s*(?:DE\s+CIUDADANIA\s*)?(?:N[O0]?\.?)?\W{0,3}"
    # Entre el rótulo y el número, la sigla escrita a mano -- «CC 9'132.107» --,
    # que el OCR lee «CC», «Ce» o «ee»: con ella delante la cédula se perdía.
    r"(?:[CEQ]{1,2}\.?\s?){0,2}#?\s?(\d{1,3}(?:[.,'\s\-]{1,2}\d{3}|\d{3}){1,3})\b"
)
#: Cuántas cifras tiene una cédula: de 6 (las de los 60) a 8, o 10 las que
#: empiezan por 1 (desde 2003). No hay cédulas de 9 cifras: un número así junto
#: al rótulo es el código del estudiante («549310006», «5420020056»).
_CIFRAS_DE_CEDULA = range(6, 9)


def _parece_cedula(cifras: str) -> bool:
    return len(cifras) in _CIFRAS_DE_CEDULA or (len(cifras) == 10 and cifras.startswith("1"))


#: «Cédula o tarjeta No. 650609-03314»: la tarjeta de identidad empieza por la
#: fecha de nacimiento (AAMMDD), un guion y su serial. No es la cédula: el bot
#: tomaba sus seis primeras cifras por una en 22 de las 312 historias de la caja
#: 00C003277 (2026-10-30).
_TARJETA = re.compile(r"(?<!\d)(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))\s?[-–]\s?(\d{3,5})(?!\d)")
#: «C.C 45.474.260», la cédula con su sigla en cualquier casilla: la ficha de
#: los 80 la escribe a veces en la de la libreta militar.
_CC = re.compile(r"\b[CE]\s?\.?\s?[CEQOG]\b\.?\s*(?:N[O0]?\.?\s*|#\s*)?(\d{1,3}(?:[.,'\s\-]{1,2}\d{3}|\d{3}){1,3})\b")
#: «TI 66263 en trámite»: la tarjeta rotulada, aunque sea corta (UPD3859718, pág. 37).
_TI = re.compile(r"\bT\s?\.?\s?I\b\.?\s*(?:N[O0]?\.?\s*|#\s*)?(\d[\d.\-]{3,13}\d)")
#: «Libreta Militar No. 7.341.226», «Libreta Militar: 1047382»: el número justo
#: detrás de su rótulo, de 5 a 10 cifras con o sin puntos de miles.
_LIBRETA = re.compile(
    r"\bLIBRETA\s*MILITAR\W{0,4}(?:N[O0]?\.?\s*|#\s*)?(\d{1,3}(?:[.,'\s\-]{1,2}\d{3}){1,3}|\d{5,10})(?![\d.,]?\d)"
)


_MESES = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8,
          "SEP": 9, "SET": 9, "OCT": 10, "NOV": 11, "DIC": 12, "DEC": 12}
_ROMANOS = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12}
_NACIMIENTO = re.compile(r"FECHA DE NACIMIENTO\W{0,4}([^|]{0,40})")


def _nacimiento(p: str) -> str | None:
    """La fecha de nacimiento de la ficha como AAMMDD: «Dic 8 1.961», «20 Junio /57», «26-I/44»."""
    if not (hallada := _NACIMIENTO.search(p)):
        return None
    texto = _ANIO_CON_PUNTO.sub(lambda m: m.group(1) + m.group(2), hallada.group(1))
    numeros = re.findall(r"\d+", texto)
    mes = next(
        (_MESES.get(palabra[:3]) or _ROMANOS.get(palabra) for palabra in re.findall(r"[A-Z]+", texto)
         if palabra[:3] in _MESES or palabra in _ROMANOS),
        None,
    )
    if mes is None and len(numeros) >= 3:
        mes = int(numeros[1])
        numeros = [numeros[0], numeros[2]]
    if mes is None or len(numeros) < 2 or not 1 <= mes <= 12 or not 1 <= int(numeros[0]) <= 31:
        return None
    return f"{numeros[-1][-2:]}{mes:02d}{int(numeros[0]):02d}"


def _puede_ser_tarjeta(cifras: str, nacimiento: str | None) -> bool:
    """Si once cifras pueden ser la tarjeta de identidad de quien nació ese día.

    La tarjeta empieza por la fecha de nacimiento (AAMMDD). Si sus seis primeras
    cifras ni siquiera son una fecha y la ficha dice otra -- ni con un dígito
    mal leído --, no es su tarjeta: «45466499000» no lo es de Tovar Orozco,
    nacida el «Marzo 23 1964» (UPD3859727, pág. 89, 2026-11-09). Una que sí
    empieza por una fecha posible se queda: ``_nacimiento`` a veces toma el año
    de la casilla de al lado -- el teléfono, la edad -- y no puede borrar una
    tarjeta bien leída (revisión, 2026-11-09). Sin fecha que lo desmienta, sí.
    """
    if _parece_fecha(cifras[:6]) or not nacimiento:
        return True
    return sum(a != b for a, b in zip(cifras[:6], nacimiento, strict=False)) <= 1


#: La cédula con sus puntos de miles y, tras un espacio, un grupo de tres cifras
#: de más: «45.466.499 000», «45 466.499 000», «9'132.107 000».
_CEDULA_Y_GRUPO_DE_MAS = re.compile(r"(\d{1,3}(?:[.,'’\s]{1,2}\d{3}){1,2})\s+\d{3}")


def _sin_el_lugar_de_expedicion(numero: str) -> str | None:
    """La cédula de un número con puntos de miles al que la lectura le pegó cifras de más.

    Detrás de la cédula va el lugar donde se expidió -- «45.466.499 de C/gena»,
    de Cartagena -- escrito a mano: la «d», la «e» y la «C» cursivas se leen
    ceros, y sale «45.466.499 000», once cifras que pasaban por tarjeta de
    identidad (Tovar Orozco, UPD3859727, pág. 89, y Nuñez Jezama, UPD3859745,
    pág. 38, 2026-11-09: el FUID llevó 45466499000). Una tarjeta nunca se
    escribe con puntos de miles.

    Sólo si el grupo de más va separado por un espacio, la cédula lleva algún
    punto y el número no empieza por una fecha: «7.047.382.991», con puntos
    hasta el final, no se trunca a 7047382, y «65.060.903 314» puede ser la
    tarjeta 650609-03314 (revisión, 2026-11-09). Mejor N/A que truncada.
    """
    hallado = _CEDULA_Y_GRUPO_DE_MAS.fullmatch(numero.strip())
    if not hallado or not re.search(r"[.,'’]", hallado.group(1)):
        return None
    cifras = re.sub(r"\D", "", hallado.group(1))
    todas = re.sub(r"\D", "", numero)
    if _parece_fecha(todas[:6]) or not _parece_cedula(cifras):
        return None
    return cifras


def _con_la_fecha_de_nacimiento(tarjeta: str, nacimiento: str | None) -> str:
    """La tarjeta empieza por la fecha de nacimiento: un dígito que el OCR leyó mal se corrige con ella.

    «61720803173» en la ficha de Cabarcas Pardo, nacida el «Dic 8 1.961»: es
    611208-03173 (UPD3859718, pág. 17). Sólo un dígito: más ya no es la misma.
    """
    if nacimiento and sum(a != b for a, b in zip(tarjeta[:6], nacimiento, strict=False)) == 1:
        return nacimiento + tarjeta[6:]
    return tarjeta


#: Una cédula con sus puntos: «45.467.824», «57,446,637». En el primer grupo el
#: OCR lee a veces una letra por la cifra manuscrita: «A5.467.824» (Pájaro
#: Martínez, 2026-10-30).
_CEDULA_CON_PUNTOS = re.compile(r"(?<![\w.,])([0-9AOILSBZG]{1,3})[.,]\s?(\d{3})[.,]\s?(\d{3})(?![\d.,]?\d)")
_LETRA_POR_CIFRA = str.maketrans("AOILSBZG", "40115826")


def _parece_fecha(cifras: str) -> bool:
    """Seis cifras que son una fecha AAMMDD: las de la tarjeta de identidad, no una cédula."""
    return bool(re.fullmatch(r"\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])", cifras))


def _sin_puntuacion(p: str) -> str:
    """«CASTILLO, SOLORZANO», «BARBOZA-LUEY», «CELMIRA. FLOREZ»: la puntuación que el OCR deja dentro del nombre."""
    return re.sub(r"(?<=[A-Z])[,;\-.]+(?=\s*[A-Z])", " ", p)
#: «Código. 549310019», «Cód. Estudiante 5420011003», «# 549310044».
#: Con el rótulo, también de seis cifras: «Código. 800642» (1980).
#: El código del estudiante tras su rótulo. También con el programa separado
#: por un guion -- «Código. 54-9010033», como se escribe a mano en las fichas de
#: Enfermería de 1990: COTA ZAMBRANO salía sin código (2026-11-06) -- y con el
#: rótulo de la ficha de 2003, «Carné Estudiantil N°: 5420030020».
_CODIGO = re.compile(
    r"(?:\bCODIGO\b|\bCOD\b|\bCARNET?\s+(?:ESTUDIANTIL\s+)?N\b)\W{0,4}(?:ESTUDIANTE\W{0,3})?"
    r"(\d{2}[\s\-.]?\d{4,10})(?![\d\-])|#\s*(\d{8,12})\b"
)
_FECHA_DE_GRADO = re.compile(r"FECHA DE GRADO\W{0,4}.{0,30}?\b(19[2-9]\d|20[0-3]\d)\b")
#: La ficha de 2003: «Documento de Identificación: C. C. ( ) T.I. ( ) Cédula
#: Extranjería ( ) Pasaporte ( ) N° ____». El número va detrás de «N°» (CONDE
#: DIAZ, Retirados 2003, 2026-11-06: la casilla estaba en blanco).
_DOCUMENTO_N = re.compile(
    r"DOCUMENTO DE IDENTIFICACION.{0,110}?\bN\b\W{0,4}(\d{1,3}(?:[.,'\s\-]{1,2}\d{3}){1,3}|\d{5,11})(?![\d.,]?\d)"
)
#: La casilla de la tarjeta de identidad marcada: «T.I. (X)».
_TI_MARCADA = re.compile(r"\bT\s?\.?\s?I\b\.?\s*\(\s*X\s*\)")


def es_del_bachillerato(texto: str, desde: int) -> bool:
    """Si la «Fecha de Grado» que empieza en ``desde`` es la del bachillerato y no la de la Universidad.

    En la ficha de Enfermería de los 90 va en el renglón del colegio --
    «Bachiller del colegio: … Ciudad: … Fecha de Grado. Dic 7 de 1989» -- y es
    cuando el estudiante salió del colegio: tomada por el grado de la carrera,
    COTA ZAMBRANO salía «1989-1993» con notas de 1990 a 1993 (2026-11-06). El
    grado de la carrera va en su recuadro, «Grado en el mes de: Diciembre 10/93».
    """
    antes = texto[max(0, desde - 160) : desde]
    return "BACHILLER" in antes or "COLEGIO" in antes
#: Palabras de la propia ficha que se cuelan en un nombre leído de la capa de
#: texto o por OCR, y lo que el OCR hace con ellas.
_NO_SON_NOMBRE = {
    "UNIVERSIDAD", "CARTAGENA", "ENFERMERIA", "ENFERMERAS", "FACULTAD", "DIRECCION", "ACTUAL",
    "TEL", "LUGAR", "NACIMIENTO", "NOMBRE", "ESTUDIANTE", "CEDULA", "CODIGO", "FICHA",
    "HISTORIA", "ACADEMICA", "APELLIDOS", "NOMBRES", "SEXO", "TELEFONO", "CARRERA", "PERIODO",
    "NO", "REGISTRO", "PECHA", "OBSERVACIONES", "ESTADO", "CIVIL", "PADRES", "BACHILLER",
    "COLEGIO", "LIBRETA", "MILITAR", "ACUDIENTE", "CERTIFICADO", "MATRICULA", "SEMESTRE",
    "SEMEST", "EXPEDICION", "FECHA", "PROGRAMA", "ACADEMICO", "OFICINA", "ADMISIONES",
}
#: Lo que abre una dirección, que va en el renglón de al lado del nombre: lo
#: que la sigue -- «AV PEDRO DE HEREDIA ESCALLON» -- es la dirección, no un nombre.
_DE_DIRECCION = frozenset({
    "AV", "AVENIDA", "CALLE", "CL", "CRA", "KRA", "BARRIO", "BRR", "URB", "URBANIZACION",
    "MZ", "MANZANA", "LOTE", "LT", "APTO", "EDIF", "SECTOR",
})
#: Las partículas de un nombre: «DE LEZO», «DE LA HOZ», «VDA DE».
_CONECTORES = frozenset({"DE", "DEL", "LA", "LAS", "LOS", "Y", "SAN", "SANTA", "VDA", "VIUDA"})


def _parece_palabra_de_nombre(palabra: str) -> bool:
    """Con vocales, sin tres letras iguales seguidas ni cuatro consonantes juntas."""
    if palabra in _CONECTORES:
        return True
    if len(palabra) < 2 or not re.search(r"[AEIOU]", palabra):
        return False
    return not (re.search(r"(.)\1\1", palabra) or re.search(r"[^AEIOUY]{4,}", palabra))


def _limpio(nombre: str | None, conocidas: Collection[str] = ()) -> str | None:
    """El nombre sin las leyendas del formulario, o ``None`` si no parece un nombre.

    Lo que va **detrás** de una leyenda ya no es el nombre: en «PEREZ GOMEZ ANA
    MARIA CEDULA NO» el nombre acaba en MARIA. Lo que va **delante**
    («UNIVERSIDAD DE CARTAGENA ENFERMERIA AGUAS GARRIDO…») se descarta y se
    empieza de nuevo. Y tiene que parecer un nombre: dos palabras de tres letras
    o más, con vocales; con ``conocidas``, dos de ellas en la lista. Lo demás es
    basura de la capa de texto, y un nombre inventado es peor que un N/A.
    """
    if not nombre:
        return None
    palabras: list[str] = []
    for palabra in (p.strip(".") for p in nombre.split()):
        if not palabra:
            continue
        if palabra in _DE_DIRECCION:
            if len(palabras) >= 2:
                break
            return None
        if palabra in _NO_SON_NOMBRE:
            if len(palabras) >= 2:
                break
            palabras = []
            continue
        if len(palabra) > 1:
            palabras.append(palabra)
    while palabras and palabras[-1] in _CONECTORES:
        palabras.pop()
    while palabras and palabras[0] in _CONECTORES:
        palabras.pop(0)
    plenas = [p for p in palabras if p not in _CONECTORES and len(p) >= 3]
    if len(plenas) < 2 or not all(_parece_palabra_de_nombre(p) for p in palabras):
        return None
    if conocidas and sum(1 for p in plenas if p in conocidas) < 2:
        return None
    return " ".join(palabras)


def leer_ficha(texto: str, conocidas: Collection[str] = ()) -> Ficha:
    """El nombre, la cédula, el código y el año de grado que trae la página que abre."""
    p = plano(texto)
    # La puntuación se quita sólo detrás del rótulo: delante de él, en la capa
    # rota de 1993, «LOI. EJTQ OLO» pasaba por un nombre.
    para_el_nombre = _sin_puntuacion(p)
    nombre = None
    for patron, donde in ((_NOMBRE_DESPUES, para_el_nombre), (_NOMBRE_ANTES, p)):
        if hallado := patron.search(donde):
            nombre = _limpio(hallado.group(1), conocidas)
            if nombre:
                break
    if nombre is None and (hallado := _APELLIDOS_Y_NOMBRES.search(para_el_nombre)):
        nombre = _limpio(f"{hallado.group(1)} {hallado.group(2)}", conocidas)
    if nombre is None and (hallado := _ESTUDIANTE_Y_SEXO.search(para_el_nombre)):
        # La ficha de alrededor del 2000: «ESTUDIANTE Matos Agudelo Johana
        # Margarita SEXO M F» (2026-10-30).
        nombre = _limpio(hallado.group(1), conocidas)
    cedula = tarjeta = codigo = None
    if hallado := _CODIGO.search(p):
        # Sólo sus cifras: «54-9010033» es el 549010033.
        codigo = re.sub(r"\D", "", hallado.group(1) or hallado.group(2))
    # La cédula y la tarjeta se buscan en su casilla y en las de al lado, hasta
    # la del acudiente: la cédula de éste es de otra persona.
    # Desde un poco antes del rótulo: la tarjeta va a veces escrita encima del
    # renglón -- «T.I. 81090409336» sobre «CÉDULA No.» -- y en el texto queda
    # delante (ficha de alrededor del 2000, 2026-10-30).
    desde = p.find("CEDULA")
    desde = max(0, desde - 60) if desde >= 0 else desde
    hasta = p.find("NOMBRE DEL ACUDIENTE", max(desde, 0))
    zona = p[desde : hasta if hasta > desde else desde + 200] if desde >= 0 else p
    nacimiento = _nacimiento(p)
    if hallado := _TARJETA.search(zona):
        tarjeta = f"{hallado.group(1)}-{hallado.group(2)}"
    elif hallado := _TI.search(zona):
        tarjeta = hallado.group(1)
        cifras = re.sub(r"\D", "", tarjeta)
        if len(cifras) == 11 and _parece_fecha(cifras[:6]):
            tarjeta = f"{cifras[:6]}-{cifras[6:]}"
    if (hallado := _CC.search(zona)) and _parece_cedula(cifras := re.sub(r"\D", "", hallado.group(1))):
        cedula = cifras
    elif hallado := _CEDULA.search(zona):
        cifras = re.sub(r"\D", "", hallado.group(1))
        if tarjeta and tarjeta.startswith(cifras):
            pass  # el número del rótulo es la tarjeta de identidad
        elif len(cifras) == 6 and _parece_fecha(cifras):
            tarjeta = tarjeta or cifras
        elif len(cifras) in (10, 11) and not _parece_cedula(cifras) and (
            sin_lugar := _sin_el_lugar_de_expedicion(hallado.group(1))
        ):
            # «45.466.499 000»: la cédula y su lugar de expedición leído como cifras.
            cedula = sin_lugar
        elif (
            len(cifras) == 11
            and _puede_ser_tarjeta(cifras, nacimiento)
            # Con puntos de miles y sin fecha al comienzo no es una tarjeta: «45.466.499.000».
            and (_parece_fecha(cifras[:6]) or not re.search(r"\d[.,'’]\s?\d{3}", hallado.group(1)))
        ) or (
            len(cifras) == 10 and not cifras.startswith("1") and _parece_fecha(cifras[:6])
        ):
            # «61120803173»: la tarjeta de identidad escrita sin su guion. Once
            # cifras no las tiene ninguna cédula.
            tarjeta = tarjeta or f"{cifras[:6]}-{cifras[6:]}"
        elif _parece_cedula(cifras):
            cedula = cifras
        elif len(cifras) in (9, 10) and not codigo:
            # El código del estudiante, escrito junto al rótulo de la cédula:
            # «549310006» no es una cédula (EGRESADOS 1996, 2026-10-30).
            codigo = cifras
    if cedula is None and (hallado := _CEDULA_CON_PUNTOS.search(zona)) and tiene_rotulo(zona[: hallado.start()]):
        # La cédula con sus puntos y su primer grupo con una letra por cifra
        # («A5.467.824»), con su rótulo a la izquierda. Sin él ya no: un número
        # escrito fuera de su sitio -- debajo del renglón, tras «de: Fundación»
        # -- puede ser el del acudiente o un teléfono, y sólo es cédula si a su
        # izquierda dice cédula, C.C. o T.I. (el operador, 2026-11-03).
        cifras = hallado.group(1).translate(_LETRA_POR_CIFRA) + hallado.group(2) + hallado.group(3)
        if cifras.isdigit() and _parece_cedula(cifras) and not (tarjeta and tarjeta.startswith(cifras[:6])):
            cedula = cifras
    if cedula is None and tarjeta is None and (hallado := _DOCUMENTO_N.search(p)):
        # La ficha de 2003: el número tras «N°» del renglón «Documento de
        # Identificación»; es tarjeta si su casilla está marcada o si tiene
        # las once cifras de una.
        cifras = re.sub(r"\D", "", hallado.group(1))
        if not _TI_MARCADA.search(hallado.group(0)) and (sin_lugar := _sin_el_lugar_de_expedicion(hallado.group(1))):
            cedula = sin_lugar
        elif _TI_MARCADA.search(hallado.group(0)) or len(cifras) == 11:
            tarjeta = cifras
        elif _parece_cedula(cifras):
            cedula = cifras
    if tarjeta:
        tarjeta = _con_la_fecha_de_nacimiento(tarjeta, nacimiento)
    if codigo and codigo == cedula:
        # «CC # 78106659»: el «#» es de la cédula, no un código (pág. 13).
        codigo = None
    anio = None
    for hallado in _FECHA_DE_GRADO.finditer(p):
        if not es_del_bachillerato(p, hallado.start()):
            anio = int(hallado.group(1))
            break
    libreta = None
    if hallado := _LIBRETA.search(p):
        cifras = re.sub(r"\D", "", hallado.group(1))
        # La cédula escrita en la casilla de la libreta no es una libreta, ni el código.
        if 5 <= len(cifras) <= 10 and cifras not in (cedula, codigo):
            libreta = cifras
    return Ficha(nombre=nombre, cedula=cedula, codigo=codigo, anio_de_grado=anio, tarjeta=tarjeta, libreta=libreta)


#: Lo que se le pide a la IA cuando ni la capa, ni el OCR de casa, ni el texto
#: del OCR de pago dejaron leer el nombre (2026-10-30: «ningún PDF sin nombre;
#: cuando vaya sin nombre, que sea la IA quien actúe»).
INSTRUCCIONES_DEL_ESTUDIANTE = (
    "Eres archivista de la Universidad de Cartagena. Recibes el texto, leído por OCR, de la ficha de "
    "un estudiante (formulario «Registro del estudiante» o «Ficha historia académica»). El OCR trae "
    "errores y a veces separa el rótulo de su valor. Puede venir también el texto de su hoja de notas.\n\n"
    "Devuelve solo el nombre completo del estudiante, en mayúsculas, con los apellidos primero y luego "
    "los nombres, por ejemplo: ALVAREZ LONDOÑO OLGA.\n"
    "- El nombre aparece varias veces: en «Nombre del estudiante» (o en APELLIDOS y NOMBRES), a veces "
    "repetido en grande en la ficha o al pie de la hoja de notas, y sus apellidos en «Nombre de los padres» "
    "(el primer apellido suele ser el primero del padre, y el segundo, el primero de la madre). El OCR se "
    "equivoca distinto en cada aparición: elige para cada palabra la grafía que confirmen las demás.\n"
    "- Los apellidos de soltera: sin el apellido de casada («López de Zabana», «(Hoy de Arteta)»). "
    "«de Jesús», «del Carmen» o «de la Hoz» son parte del nombre o del apellido y sí van.\n"
    "- No es el nombre de los padres, del acudiente ni del colegio, ni una dirección.\n"
    "- Cada palabra tiene que estar escrita así en alguna parte del texto: no la corrijas por tu cuenta ni inventes.\n"
    "- Si el texto no trae el nombre del estudiante, devuelve solo: NINGUNO"
)


#: Cómo quedó cada casilla que el agente buscó otra vez (2026-11-06, el
#: operador: «haz que los agentes se aseguren cuando en realidad no encuentren
#: algo»).
LEIDO = "leído"
EN_BLANCO = "en blanco"
NO_APARECE = "no aparece"
ILEGIBLE = "ilegible"
#: Sin IA no hay quien mire el papel otra vez: se dice que no se pudo verificar.
SIN_VERIFICAR = "sin verificar"

#: Lo que se le pregunta a la IA de la ficha de un estudiante al que le falta
#: la cédula, el código o los años, sobre el texto que su OCR ya leyó: se paga
#: por tokens, no por página.
INSTRUCCIONES_PARA_VERIFICAR = (
    "Eres archivista de la Universidad de Cartagena. Recibes el texto, leído por OCR, de la ficha académica "
    "de un estudiante (y a veces de su hoja de notas). El OCR trae errores y a veces separa el rótulo de su "
    "valor.\n\n"
    "Responde SOLO un objeto JSON con estas claves:\n"
    '{"cedula": "", "tarjeta": "", "libreta": "", "codigo": "", "anio_ingreso": "", "anio_final": ""}\n'
    "Para cada clave pon UNO de estos valores:\n"
    "- el número tal como está escrito en el texto, sólo sus cifras;\n"
    "- \"VACIO\" si la casilla está en el texto pero no tiene nada escrito;\n"
    "- \"NO_APARECE\" si el texto no trae esa casilla;\n"
    "- \"ILEGIBLE\" si hay algo escrito en la casilla que no se entiende.\n\n"
    "- cedula: la cédula de ciudadanía DEL ESTUDIANTE («Cédula No.», «C.C.», «Documento de Identificación N°»). "
    "Nunca la del acudiente, la de los padres, un teléfono ni la del puesto de ingreso. Si su casilla está en "
    "blanco, responde VACIO aunque haya otros números cerca. Detrás de la cédula suele ir el lugar donde se "
    "expidió («45.466.499 de C/gena», de Cartagena), que el OCR a veces lee como cifras («45.466.499 000»): "
    "esas cifras de más no son de la cédula; la cédula es 45466499.\n"
    "- tarjeta: su tarjeta de identidad (T.I.): empieza por la fecha de nacimiento (AAMMDD) y nunca lleva "
    "puntos de miles.\n"
    "- libreta: su libreta militar.\n"
    "- codigo: su código o carné estudiantil; «54-9010033» es 549010033.\n"
    "- anio_ingreso: el año en que entró a la Universidad (no el del bachillerato ni el de nacimiento). Si la "
    "casilla «Año de ingreso» está en blanco, el primer año de su tabla de períodos académicos («Año 03 Período "
    "II» es 2003) o de sus notas.\n"
    "- anio_final: el año de su grado en la Universidad, o el de su deserción o retiro, o el último año con notas.\n"
    "No inventes ni corrijas: cada número tiene que estar escrito así en el texto."
)


@dataclass(frozen=True, slots=True)
class Verificacion:
    """Lo que dijo la IA de las casillas de una ficha, comprobado contra su texto."""

    #: Campo -> cifras, sólo las que están escritas en el texto: «cedula», «tarjeta», «libreta», «codigo».
    numeros: dict[str, str] = field(default_factory=dict)
    #: Campo -> ``LEIDO``, ``EN_BLANCO``, ``NO_APARECE`` o ``ILEGIBLE``.
    estados: dict[str, str] = field(default_factory=dict)
    anio_ingreso: int | None = None
    anio_final: int | None = None
    #: Campo -> por qué no se tomó el número que dio la IA (sin el número): para el registro.
    motivos: dict[str, str] = field(default_factory=dict)


#: Cuántas cifras puede tener cada número para tomarlo.
_CIFRAS_DE = {"cedula": (5, 10), "tarjeta": (4, 11), "libreta": (5, 10), "codigo": (6, 12)}


def en_el_texto(cifras: str, texto: str) -> bool:
    """Si ese número está escrito en el texto, con o sin separadores de miles («22'809.768»)."""
    junto = re.sub(r"(?<=\d)[\s.,'’\-](?=\d)", "", texto or "")
    return bool(cifras) and re.search(rf"(?<!\d){re.escape(cifras)}(?!\d)", junto) is not None


#: El rótulo que tiene que ir delante de cada número para tomarlo de la IA.
_ROTULOS_DE = {
    "cedula": re.compile(r"CEDULA|\bC\s?\.?\s?C\b|IDENTIFICACION|DOCUMENTO"),
    "tarjeta": re.compile(r"\bT\s?\.?\s?I\b|TARJETA|IDENTIFICACION|DOCUMENTO"),
    "libreta": re.compile(r"LIBRETA|MILITAR"),
    "codigo": re.compile(r"CODIGO|\bCOD\b|CARNE|#"),
}
#: Lo que, entre el rótulo y el número, dice que el número es de otra casilla.
_OTRA_CASILLA = re.compile(r"TELEFONO|\bTEL\b|CELULAR|PUESTO|EDAD|FECHA")
#: Hasta dónde se mira hacia atrás desde el número para encontrar su rótulo.
DISTANCIA_DEL_ROTULO = 70


def junto_a_su_rotulo(cifras: str, texto: str, casilla: str) -> bool:
    """Si el número va escrito detrás del rótulo de su casilla, sin otra casilla en medio.

    Que el número esté en el texto no basta: con la casilla de la cédula en
    blanco, la IA podía tomar el teléfono de al lado (2026-11-06).
    """
    return por_que_no(cifras, texto, casilla) is None


def por_que_no(cifras: str, texto: str, casilla: str) -> str | None:
    """Por qué un número no se puede tomar como el de esa casilla; ``None`` si se puede."""
    junto = plano(re.sub(r"(?<=\d)[\s.,'’\-](?=\d)", "", texto or ""))
    rotulo = _ROTULOS_DE.get(casilla)
    motivo = "un número que el texto no trae"
    for hallado in re.finditer(rf"(?<!\d){re.escape(cifras)}(?!\d)", junto):
        antes = junto[max(0, hallado.start() - DISTANCIA_DEL_ROTULO) : hallado.start()]
        rotulos = list(rotulo.finditer(antes)) if rotulo else []
        if not rotulos:
            motivo = (
                f"un número de otra casilla ({otra.group(0)})"
                if (otra := _OTRA_CASILLA.search(antes))
                else "un número sin su rótulo"
            )
            continue
        if otra := _OTRA_CASILLA.search(antes[rotulos[-1].end() :]):
            motivo = f"un número de otra casilla ({otra.group(0)})"
            continue
        return None
    return motivo


def leer_la_verificacion(respuesta: str, texto: str) -> Verificacion:
    """La respuesta de la IA, con sólo lo que el texto confirma: un número que no está escrito no se toma.

    Si la IA dice un número que el texto no trae, la casilla queda ``ILEGIBLE``:
    alguien tiene que mirarla, pero no se inventa.
    """
    import json

    hallado = re.search(r"\{.*\}", respuesta or "", re.S)
    try:
        datos = json.loads(hallado.group(0)) if hallado else {}
    except ValueError:
        datos = {}
    if not isinstance(datos, dict):
        datos = {}
    numeros: dict[str, str] = {}
    estados: dict[str, str] = {}
    motivos: dict[str, str] = {}
    for campo, (menos, mas) in _CIFRAS_DE.items():
        valor = str(datos.get(campo) or "").strip()
        marca = plano(valor).replace("_", " ")
        cifras = re.sub(r"\D", "", valor)
        if "ILEGIB" in marca:
            estados[campo] = ILEGIBLE
        elif not valor or marca in ("NO APARECE", "NO EXISTE", "NULL", "NONE"):
            estados[campo] = NO_APARECE
        elif not cifras:
            # «VACIO», pero también «N/A», «—», «( )», «no registra»: sin un
            # número, la casilla está en blanco (MONCADA, Retirados 2003, salía
            # «ilegible» con su cédula en blanco; 2026-11-06).
            estados[campo] = EN_BLANCO
        elif len(cifras) <= 3:
            # Un «número» de tres cifras o menos no es una cédula ni un código:
            # la IA tomó el de otra casilla -- «Puesto de Ingreso N° 20» --, y la
            # suya está en blanco (CONDE DIAZ, 2026-11-06).
            estados[campo] = EN_BLANCO
            motivos[campo] = f"la IA dio un número de {len(cifras)} cifras, de otra casilla"
        elif not menos <= len(cifras) <= mas:
            estados[campo] = ILEGIBLE
            motivos[campo] = f"un número de {len(cifras)} cifras"
        elif (motivo := por_que_no(cifras, texto, campo)) is None:
            numeros[campo] = cifras
            estados[campo] = LEIDO
        else:
            # Un número que el texto no trae junto a su rótulo: no se inventa,
            # y alguien tiene que mirar la casilla.
            estados[campo] = ILEGIBLE
            motivos[campo] = motivo

    def anio(clave: str) -> int | None:
        cifras = re.sub(r"\D", "", str(datos.get(clave) or ""))
        if len(cifras) != 4 or not DESDE <= int(cifras) <= 2035:
            return None
        # Escrito entero o abreviado («AÑO 90», «IPA/04») en algún sitio del texto.
        return int(cifras) if en_el_texto(cifras, texto) or re.search(rf"(?<!\d){cifras[2:]}(?!\d)", texto or "") else None

    return Verificacion(numeros, estados, anio("anio_ingreso"), anio("anio_final"), motivos)


def nombre_de_la_ia(respuesta: str, texto: str) -> str | None:
    """El nombre que devolvió la IA, si cada palabra suya está en el texto de la ficha.

    La IA ordena y descarta los rótulos; no puede poner una palabra que el papel
    no diga: un nombre inventado es peor que uno por revisar.
    """
    palabras = re.findall(r"[A-Z]+", plano(respuesta))
    if not palabras or "NINGUNO" in palabras:
        return None
    del_texto = set(re.findall(r"[A-Z]+", plano(texto)))
    if any(palabra not in del_texto for palabra in palabras):
        return None
    return _limpio(" ".join(palabras))


# -- los años de las notas ---------------------------------------------------------

#: Los años que escriben las hojas de notas: «AÑO: 93», «AÑO;93 P.A.», «AÑO
#: 1.993», «1996», «2003-2004». En «plano» la Ñ ya es N. Desde 1920: Medicina
#: archiva historias de los años 40.
_ANIO_CORTO = re.compile(r"\bANO\W{0,3}(\d{2})\b")
_ANIO_LARGO = re.compile(r"\b(19[2-9]\d|20[0-3]\d)\b")
_ANIO_CON_PUNTO = re.compile(r"\b([12])\.(9\d{2}|0[0-3]\d)\b")
DESDE = 1920
#: Cuánto puede separarse un año del siguiente dentro del mismo expediente. Un
#: año suelto más lejos -- el «AÑO 02» que era 92, el «AÑO 28» de la casilla de
#: las horas -- es una mala lectura, no otra matrícula.
HUECO_MAXIMO = 4
#: La ventana de años de un PDF: del percentil 5 al 95 de los años de todas sus
#: hojas de notas, con este margen. Hace falta un mínimo de años para fiarse.
MARGEN_DE_LA_VENTANA = 2
MINIMO_PARA_LA_VENTANA = 8


#: El año del plan de estudios que imprime el flujograma -- «FLUJOGRAMA PLAN DE
#: ESTUDIOS … 1.998» --: es el del plan, no el del estudiante. En los PDF de
#: 2004 era el único año de las notas y daba «1998-1998» a quien entró en 2000.
_PLAN_DE_ESTUDIOS = re.compile(r"PLAN DE ESTUDIOS(?:\W+[A-Z]+){0,8}?\W+[12]\.?\d{3}\b")
#: Lo que la ficha dice de los años del estudiante -- su ingreso y su grado --,
#: lo único de ella que cuenta: el resto son la fecha de nacimiento y la del
#: bachillerato. «AÑO INGRESO 2-000» es 2000 en la capa de texto rota.
_INGRESO = re.compile(r"\bANO\s*(?:DE\s*)?INGRESO\W{0,4}([0-9][0-9\-.\s]{2,6}[0-9])")
_GRADUACION = re.compile(r"FECHA DE GRADU?(?:ACION|O)\W{0,4}.{0,24}?\b(19[2-9]\d|20[0-3]\d)\b")
#: El retiro de la ficha de 2003: «Fecha de Deserción: I PA/2004» es su último
#: año (CONDE DIAZ, Retirados 2003, salía sin fecha final; 2026-11-06).
_DESERCION = re.compile(r"FECHA DE DESERCION\W{0,4}.{0,24}?\b(19[2-9]\d|20[0-3]\d)\b")
#: La tabla «Período Académico» de la ficha de 2003: «Año 03 Período II, Año 04
#: Período I». Cuando «Año de ingreso» va en blanco, sus años son los extremos
#: (QUINTANA JIMENEZ y RAMIREZ RIOS, Retirados 2003, 2026-11-06).
_TABLA_DE_PERIODOS = re.compile(r"PERIODO\W{0,3}ACADEMICO(.{0,400})")
#: Como la escribe la IA: «| Año 03 | Periodo II | Año 04 | Periodo I |», o sin las palabras.
_ANIO_Y_PERIODO = re.compile(r"(?<![\d/])(\d{2})\W{1,4}(?:PERIODO\W{0,3})?(I{1,2})\b")
#: El período de las notas de 2003 en adelante: «IPA/05», «II PA/2004», «IPA-2003»;
#: la IA lee a veces «JPA/04». Es su año (TORRES PARERNINA, 2026-11-06).
_PERIODO_ACADEMICO = re.compile(r"\b(?:I{1,2}|J{1,2})\s?P\s?\.?A\s?[/\-]\s?(\d{4}|\d{2})\b")


#: Los años de estudio que la ficha de 1968 a 1999 anota a mano junto al
#: nombre: «1965-1968», «1.983-86», «1978 - 1981».
_PERIODO = re.compile(r"\b(19[2-9]\d|20[0-3]\d)\s?[-–]\s?(19[2-9]\d|20[0-3]\d|\d{2})\b")
#: La fecha de su recuadro «Grado en / Fecha»: «Fecha Marzo 31 de 1970», «Dic
#: 18/87», «Nov. 25 83». Ninguna de las 312 de la caja 00C003277 se leía.
_RECUADRO_DEL_GRADO = re.compile(r"\bGRADO EN\b(.{0,90}?)(?=PROMEDIO ORAL|OBSERVACION|$)")
_ANIO_DE_LA_FECHA = re.compile(r"\b(19[2-9]\d|20[0-3]\d)\b|\d{1,2}\s?[/\- ]\s?(\d{2})\b")


#: El código del estudiante que la ficha de 1968 a 1990 escribe a mano sin
#: rótulo, arriba o en Observaciones: «840222», «C-800656», «Q=790403».
_CODIGO_SIN_ROTULO = re.compile(r"(?<![\d.,'\-])(?:[CQ]\s?[=\-]\s?)?(\d{6})(?![\d.,'\-]?\d)")


def codigo_sin_rotulo(texto: str, ingreso: int | None) -> str | None:
    """El código de seis cifras sin rótulo, sólo si empieza por los dos dígitos del año de ingreso.

    Medido en UPD3859718 (2026-10-30): los revisores lo vieron en casi todas las
    fichas de 1979 a 1987 -- «840222» de quien entró en 1984 -- y su columna
    salía N/A en 79 de 85. Sin esa coincidencia no se toma: puede ser un
    teléfono, un folio o la tarjeta de identidad.
    """
    if not ingreso:
        return None
    prefijos = {f"{ingreso % 100:02d}", f"{(ingreso - 1) % 100:02d}"}
    for hallado in _CODIGO_SIN_ROTULO.finditer(plano(texto)):
        cifras = hallado.group(1)
        if cifras[:2] in prefijos:
            return cifras
    return None


def anios_de_la_ficha(texto: str) -> tuple[int | None, int | None]:
    """El año de ingreso y el de grado -- o el último de estudio -- que escribe la ficha; ``None`` el que no se lea."""
    p = _ANIO_CON_PUNTO.sub(lambda m: m.group(1) + m.group(2), plano(texto))
    ingreso = grado = None
    if hallado := _INGRESO.search(p):
        cifras = re.sub(r"\D", "", hallado.group(1))
        if len(cifras) == 4 and DESDE <= int(cifras) <= 2030:
            ingreso = int(cifras)
    for hallado in _GRADUACION.finditer(p):
        # La del bachillerato no: es cuando salió del colegio (ver ``es_del_bachillerato``).
        if not es_del_bachillerato(p, hallado.start()):
            grado = int(hallado.group(1))
            break
    if hallado := _DESERCION.search(p):
        grado = max(grado or 0, int(hallado.group(1)))
    if ingreso is None and (tabla := _TABLA_DE_PERIODOS.search(p)):
        anios_de_la_tabla = sorted(
            (2000 if int(corto) < 30 else 1900) + int(corto) for corto, _ in _ANIO_Y_PERIODO.findall(tabla.group(1))
        )
        if anios_de_la_tabla and anios_de_la_tabla[-1] - anios_de_la_tabla[0] <= 15:
            ingreso = anios_de_la_tabla[0]
            grado = max(grado or 0, anios_de_la_tabla[-1])
    if hallado := _PERIODO.search(_PLAN_DE_ESTUDIOS.sub(" ", p)):
        desde, hasta = int(hallado.group(1)), hallado.group(2)
        hasta = int(hasta) if len(hasta) == 4 else desde // 100 * 100 + int(hasta)
        hasta += 100 if hasta < desde else 0
        if hasta - desde <= 15:
            ingreso = ingreso or desde
            grado = max(grado or hasta, hasta)
    if (recuadro := _RECUADRO_DEL_GRADO.search(p)) and (hallado := _ANIO_DE_LA_FECHA.search(recuadro.group(1))):
        corto = hallado.group(2)
        del_recuadro = int(hallado.group(1)) if hallado.group(1) else (1900 if int(corto) >= 30 else 2000) + int(corto)
        if ingreso is None or 0 <= del_recuadro - ingreso <= 15:
            grado = max(grado or del_recuadro, del_recuadro)
    return ingreso, grado


def _candidatos(textos: Sequence[str], ventana: tuple[int, int] | None = None) -> list[tuple[int, bool]]:
    """Cada año visto y si venía con sus cuatro cifras (``True``) o era un «AÑO 93»."""
    vistos: list[tuple[int, bool]] = []
    for texto in textos:
        p = _ANIO_CON_PUNTO.sub(lambda m: m.group(1) + m.group(2), plano(texto))
        p = _PLAN_DE_ESTUDIOS.sub(" ", p)
        for hallado in _ANIO_CORTO.finditer(p):
            corto = int(hallado.group(1))
            anio = 1900 + corto if corto >= 50 else 2000 + corto
            # Con la ventana del PDF se elige el siglo que le toca: el «AÑO 45»
            # de un libro de 1940 es 1945, no 2045.
            if ventana is not None and not ventana[0] <= anio <= ventana[1]:
                otro = anio - 100 if anio >= 2000 else anio + 100
                if ventana[0] <= otro <= ventana[1]:
                    anio = otro
            vistos.append((anio, False))
        vistos.extend((int(h.group(1)), True) for h in _ANIO_LARGO.finditer(p))
        for hallado in _PERIODO_ACADEMICO.finditer(p):
            cifras = hallado.group(1)
            anio = int(cifras) if len(cifras) == 4 else (2000 if int(cifras) < 50 else 1900) + int(cifras)
            # Con su período delante es un año de verdad, aunque vaya con dos cifras.
            vistos.append((anio, True))
    return vistos


def ventana_de_anios(
    textos: Sequence[str], *, nombre: str = "", hasta: int = 2030, margen: int = MARGEN_DE_LA_VENTANA
) -> tuple[int, int] | None:
    """Los años posibles de un PDF, de sus hojas de notas; ``None`` si hay pocos para decirlo.

    Si las notas no traen años bastantes -- la capa de texto de los 70 no los
    deja leer --, la dan los del nombre del PDF: «1974-1977» es una cohorte que
    estudió de unos ocho años antes a dos después. Sin ventana, un «1923» de la
    capa rota pasaba por el primer año de un expediente de 1974.

    ``margen`` ensancha la ventana por los dos lados. Medicina, con los años
    a máquina, usa uno mayor: el «PRIMER AÑO 1989» de Ferrer Triana quedaba
    fuera de la de «INTERNADOS ROTATORIO 1978-1984», que acababa en 1988.
    """
    todos = sorted(anio for anio, _ in _candidatos(textos) if DESDE <= anio <= hasta)
    if len(todos) >= MINIMO_PARA_LA_VENTANA:
        bajo = todos[int(0.05 * (len(todos) - 1))] - margen
        alto = todos[int(0.95 * (len(todos) - 1))] + margen
        return bajo, alto
    del_nombre = [int(anio) for anio in _ANIO_DEL_NOMBRE.findall(nombre or "") if DESDE <= int(anio) <= hasta]
    if del_nombre:
        return min(del_nombre) - ANTES_DEL_NOMBRE, max(del_nombre) + margen
    return None


#: Los años de cuatro cifras del nombre de un PDF: «HISTORIAS ACADEMICAS 1974-1977».
_ANIO_DEL_NOMBRE = re.compile(r"(?<!\d)(19\d{2}|20[0-3]\d)(?!\d)")
#: Cuántos años antes del primero del nombre puede empezar un expediente: el
#: nombre dice el año del grado o del retiro, y la carrera dura de cuatro a cinco.
ANTES_DEL_NOMBRE = 8


def anios(
    textos: Sequence[str],
    *,
    ventana: tuple[int, int] | None = None,
    hasta: int = 2030,
    de_la_ficha: Sequence[int | None] = (),
) -> tuple[int | None, int | None]:
    """El primer y el último año de un expediente, de lo que dicen sus hojas de notas.

    Son las fechas extremas del FUID: el operador las pidió como el primer y el
    último año de las notas (2026-10-29). Se queda el grupo de años mejor
    apoyado -- el que trae más años con sus cuatro cifras, y entre iguales el
    más poblado -- sin los sueltos que se apartan, y dentro de la ``ventana``
    del PDF cuando se conoce. De la ficha sólo cuentan ``de_la_ficha``, su año
    de ingreso y el de grado (ver ``anios_de_la_ficha``): el resto de la ficha
    es la fecha de nacimiento y la del bachillerato, que daban 1952 y 1971 en
    un expediente de 1990.
    """
    bajo, alto = ventana or (DESDE, hasta)
    leidos = [anio for anio in de_la_ficha if anio]
    vistos = sorted(
        (anio, largo)
        for anio, largo in [*_candidatos(textos, ventana), *((anio, True) for anio in leidos)]
        if bajo <= anio <= alto
    )
    if not vistos:
        return None, None
    grupos: list[list[tuple[int, bool]]] = [[vistos[0]]]
    for visto in vistos[1:]:
        if visto[0] - grupos[-1][-1][0] <= HUECO_MAXIMO:
            grupos[-1].append(visto)
        else:
            grupos.append([visto])
    mejor = max(grupos, key=lambda grupo: (sum(1 for _, largo in grupo if largo), len(grupo)))
    if len(mejor) == 1 and not textos_con_anios(textos) and len(leidos) == 1:
        # Un solo año, y sólo de la ficha: el de ingreso es el primero y el de
        # grado el último. Repetirlo daba «2000-2000» a quien se graduó en
        # 2004; el que falta queda N/A, con su nota.
        ingreso = de_la_ficha[0] if de_la_ficha else None
        return (mejor[0][0], None) if ingreso else (None, mejor[0][0])
    return mejor[0][0], mejor[-1][0]


def textos_con_anios(textos: Sequence[str]) -> bool:
    """Si las hojas traen algún año propio, sin contar el del plan de estudios."""
    return bool(_candidatos(textos))


# -- los expedientes ---------------------------------------------------------------


@dataclass
class Expediente:
    """Las páginas de un estudiante, o las de antes de la primera ficha (``ficha`` ``None``)."""

    paginas: list[int] = field(default_factory=list)
    ficha: Ficha | None = None
    #: Con qué plantilla abrió: la ficha, la ficha nueva, el certificado…
    plantilla: str | None = None
    #: Lo que dijeron los certificados que ya entraron en el expediente.
    certificados: list[Ficha] = field(default_factory=list)
    #: La página de su ficha, que es la que lee la IA si hace falta.
    pagina_de_la_ficha: int | None = None
    #: Lo que se unió sin una regla que lo confirme, para quien revise.
    dudas: list[str] = field(default_factory=list)

    @property
    def es_de_un_estudiante(self) -> bool:
        return self.ficha is not None


def _junta(ficha: Ficha, otra: Ficha) -> Ficha:
    """Lo que dicen dos páginas de apertura del mismo estudiante: la primera manda."""
    return Ficha(
        nombre=ficha.nombre or otra.nombre,
        cedula=ficha.cedula or otra.cedula,
        codigo=ficha.codigo or otra.codigo,
        anio_de_grado=ficha.anio_de_grado or otra.anio_de_grado,
        tarjeta=ficha.tarjeta or otra.tarjeta,
        libreta=ficha.libreta or otra.libreta,
    )


def _cifras_distintas(una: Ficha, otra: Ficha) -> bool:
    """Si dos lecturas dicen de seguro estudiantes distintos: códigos distintos o, sin código, cédulas."""
    if una.codigo and otra.codigo:
        return una.codigo != otra.codigo
    if una.cedula and otra.cedula:
        return una.cedula != otra.cedula
    return False


def _mismas_cifras(una: Ficha, otra: Ficha) -> bool:
    """Si dos lecturas dicen de seguro el mismo estudiante: el mismo código o la misma cédula."""
    if una.codigo and otra.codigo:
        return una.codigo == otra.codigo
    if una.cedula and otra.cedula:
        return una.cedula == otra.cedula
    return False


def expedientes(
    textos: Sequence[str],
    fichas: dict[int, Ficha] | None = None,
    *,
    conocidas: Collection[str] = (),
) -> list[Expediente]:
    """Los expedientes de un PDF, por las páginas que abren.

    ``textos`` es el texto de cada página, en orden (la primera es la 1).
    ``fichas`` trae, si se tiene, lo que se leyó mejor de cada página que abre
    -- con la IA --; si no, se lee del mismo texto, validando el nombre con
    ``conocidas`` si se da.

    **Una ficha abre siempre**, salvo la ficha vieja y la nueva del mismo
    estudiante: otra plantilla y las mismas cifras («VEGA CABALLERO MARIA
    EUGENIA», código 549710039, págs. 94 y 97 de «2002-2»).

    **Un certificado de matrícula sigue al expediente en curso**: va detrás de
    las notas de su estudiante, no delante del siguiente. Medido en la imagen:
    el certificado de la pág. 12 de «IPA 2004» es de BALLESTAS CASTRO NORLEY
    ELIANA, la ficha de la pág. 9; la de la 13 es de otra estudiante. Abre uno
    sólo si no hay expediente abierto o si sus cifras contradicen las de la
    ficha o las de otro certificado del mismo expediente («BALSEIRO HERAZO
    XIARA», un certificado suelto en la pág. 52 de «RETIRADOS 2000-2002»).
    Ante la duda, une. Lo que el certificado trae a máquina -- el nombre, el
    código -- completa lo que la ficha escrita a mano no dejó leer.
    """
    fichas = fichas or {}
    resultado: list[Expediente] = []
    for numero, texto in enumerate(textos, start=1):
        cual = plantilla_de_apertura(texto)
        actual = resultado[-1] if resultado else None
        if cual is None:
            if actual is None:
                resultado.append(Expediente(paginas=[numero], ficha=None))
            else:
                actual.paginas.append(numero)
            continue
        ficha = fichas.get(numero) or leer_ficha(texto, conocidas)
        en_curso = actual is not None and actual.ficha is not None
        if es_ficha(cual):
            if (
                en_curso
                and es_ficha(actual.plantilla)
                and cual != actual.plantilla
                and _mismas_cifras(ficha, actual.ficha)
            ):
                actual.paginas.append(numero)
                actual.ficha = _junta(actual.ficha, ficha)
                continue
            if en_curso and es_ficha(actual.plantilla) and actual.paginas == [actual.pagina_de_la_ficha]:
                # Una ficha sin una sola hoja detrás y otra ficha enseguida: en
                # los 48 PDF de Enfermería, las tres veces es un formulario en
                # blanco delante de la ficha de verdad (IPA 2004, págs. 39 y 40).
                # Va con la siguiente, que es la que dice quién es, y se anota.
                anterior = actual.pagina_de_la_ficha
                actual.paginas.append(numero)
                actual.ficha = _junta(ficha, actual.ficha)
                actual.plantilla = cual
                actual.pagina_de_la_ficha = numero
                actual.dudas.append(
                    f"la página {anterior} es una ficha sin hojas detrás, unida a la ficha siguiente"
                )
                continue
            resultado.append(Expediente(paginas=[numero], ficha=ficha, plantilla=cual, pagina_de_la_ficha=numero))
            continue
        if (
            not en_curso
            or _cifras_distintas(ficha, actual.ficha)
            or any(_cifras_distintas(ficha, otro) for otro in actual.certificados)
        ):
            resultado.append(Expediente(paginas=[numero], ficha=ficha, plantilla=cual, certificados=[ficha]))
            continue
        actual.paginas.append(numero)
        actual.certificados.append(ficha)
        actual.ficha = _junta(actual.ficha, ficha)
    return resultado


# -- la segunda lectura de la ficha ---------------------------------------------------


#: Las dos zonas donde la ficha de 1968 a 1990 escribe el nombre: el renglón
#: «Nombre del estudiante» y, debajo de «Observaciones», el mismo nombre en
#: mayúsculas con los apellidos primero. El operador pidió compararlas
#: (2026-10-30): «cuando las 2 áreas tengan el nombre, para tener mejores
#: resultados».
FRANJA_DEL_NOMBRE = Franja(
    campo="el nombre",
    # La primera «NOMBRE» de la ficha, de arriba abajo, es la del estudiante.
    leyendas=("NOMBRE",),
    rotulo=r"N\w{1,4}BRE\W+DEL\W+ESTU\S*",
    alto=0.055,
    margen=0.03,
)
FRANJA_DE_OBSERVACIONES = Franja(
    campo="el nombre en Observaciones",
    leyendas=("OBSERVACIONES",),
    rotulo=r"OBSERVACI\S*",
    alto=0.08,
    margen=0.005,
)

#: El nombre de la zona de Observaciones: las palabras que siguen al rótulo,
#: hasta el primer número («MERIÑO RHENALS CARMEN 1977-80»).
_DE_OBSERVACIONES = re.compile(r"OBSERVACI\w*\W*([A-Z][A-Z\s.,\-]{4,80}?)(?=\d|$)")


def nombre_de_observaciones(texto: str, conocidas: Collection[str] = ()) -> str | None:
    """El nombre que la ficha repite bajo «Observaciones», si dos de sus palabras son nombres conocidos.

    Con la lista: bajo «Observaciones» va también «Obtuvo el grado de
    Enfermera General…», que tiene forma de nombre y no lo es.
    """
    if hallado := _DE_OBSERVACIONES.search(_sin_puntuacion(plano(texto))):
        return _limpio(hallado.group(1), conocidas)
    return None


#: El renglón «Cédula o tarjeta No. … Libreta Militar No. …», entero: la cédula
#: va a veces en la casilla de la libreta militar.
FRANJA_DE_LA_CEDULA = Franja(
    campo="la cédula",
    # Palabras sueltas: Tesseract ubica palabra por palabra.
    leyendas=("CEDULA", "TARJETA"),
    rotulo=r"C[EÉ]DULA\W+O\W+TARJETA",
    # Con margen: la cédula va escrita a mano por encima del renglón. Medido
    # en 8 fichas de UPD3859718 (2026-10-30): así leyó 23229125, 49731465 y la
    # T.I. 66263, que la página entera no leía o leía mal.
    alto=0.055,
    margen=0.028,
)
