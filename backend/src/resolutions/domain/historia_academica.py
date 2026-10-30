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

#: La clase de las filas de esta habilidad en el inventario, y la de las páginas
#: que no son de ningún estudiante (las de antes de la primera ficha).
HISTORIA_ACADEMICA = "HISTORIA ACADEMICA"
SIN_ESTUDIANTE = "SIN ESTUDIANTE"
CLASES = frozenset({HISTORIA_ACADEMICA, SIN_ESTUDIANTE})


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
_APELLIDOS_Y_NOMBRES = re.compile(
    r"APELLIDOS\W{0,3}" + r"([A-Z][A-Z ]{3,60}?)" + r"\W{0,3}NOMBRES\W{0,3}" + r"([A-Z][A-Z ]{2,60}?)(?=\s+[A-Z]+\s*[:;]|$)"
)
#: «Cédula No. 45.755.189», «Cédula o tarjeta No. CC 9'132.107», «C.C. 1047382991».
_CEDULA = re.compile(
    r"(?:CEDULA(?:\s+O\s+TARJETA)?|C\.\s*C\.)\s*(?:DE\s+CIUDADANIA\s*)?(?:N[O0]?\.?)?\W{0,3}"
    r"(?:C\.?\s?C\.?\s*)?(\d{1,3}(?:[.,'\s]?\d{3}){1,3})\b"
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
_CC = re.compile(r"\bC\s?\.?\s?C\b\.?\s*(?:N[O0]\.?\s*)?(\d{1,3}(?:[.,'\s]?\d{3}){1,3})\b")


def _parece_fecha(cifras: str) -> bool:
    """Seis cifras que son una fecha AAMMDD: las de la tarjeta de identidad, no una cédula."""
    return bool(re.fullmatch(r"\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])", cifras))


def _sin_puntuacion(p: str) -> str:
    """«CASTILLO, SOLORZANO», «BARBOZA-LUEY», «CELMIRA. FLOREZ»: la puntuación que el OCR deja dentro del nombre."""
    return re.sub(r"(?<=[A-Z])[,;\-.]+(?=\s*[A-Z])", " ", p)
#: «Código. 549310019», «Cód. Estudiante 5420011003», «# 549310044».
_CODIGO = re.compile(r"(?:\bCODIGO\b|\bCOD\b)\W{0,4}(?:ESTUDIANTE\W{0,3})?(\d{7,12})\b|#\s*(\d{8,12})\b")
_FECHA_DE_GRADO = re.compile(r"FECHA DE GRADO\W{0,4}.{0,30}?\b(19[2-9]\d|20[0-3]\d)\b")
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
    cedula = tarjeta = codigo = None
    if hallado := _CODIGO.search(p):
        codigo = hallado.group(1) or hallado.group(2)
    if hallado := _TARJETA.search(p):
        tarjeta = f"{hallado.group(1)}-{hallado.group(2)}"
    if (hallado := _CC.search(p)) and _parece_cedula(cifras := re.sub(r"\D", "", hallado.group(1))):
        cedula = cifras
    elif hallado := _CEDULA.search(p):
        cifras = re.sub(r"\D", "", hallado.group(1))
        if tarjeta and tarjeta.startswith(cifras):
            pass  # el número del rótulo es la tarjeta de identidad
        elif len(cifras) == 6 and _parece_fecha(cifras):
            tarjeta = tarjeta or cifras
        elif _parece_cedula(cifras):
            cedula = cifras
        elif len(cifras) in (9, 10) and not codigo:
            # El código del estudiante, escrito junto al rótulo de la cédula:
            # «549310006» no es una cédula (EGRESADOS 1996, 2026-10-30).
            codigo = cifras
    anio = None
    if hallado := _FECHA_DE_GRADO.search(p):
        anio = int(hallado.group(1))
    return Ficha(nombre=nombre, cedula=cedula, codigo=codigo, anio_de_grado=anio, tarjeta=tarjeta)


#: Lo que se le pide a la IA cuando ni la capa, ni el OCR de casa, ni el texto
#: del OCR de pago dejaron leer el nombre (2026-10-30: «ningún PDF sin nombre;
#: cuando vaya sin nombre, que sea la IA quien actúe»).
INSTRUCCIONES_DEL_ESTUDIANTE = (
    "Eres archivista de la Universidad de Cartagena. Recibes el texto, leído por OCR, de la ficha de "
    "un estudiante (formulario «Registro del estudiante» o «Ficha historia académica»). El OCR trae "
    "errores y a veces separa el rótulo de su valor.\n\n"
    "Devuelve solo el nombre completo del estudiante, en mayúsculas, con los apellidos primero y luego "
    "los nombres, por ejemplo: ALVAREZ LONDOÑO OLGA.\n"
    "- Está en «Nombre del estudiante» (o en APELLIDOS y NOMBRES) y a veces repetido en otra parte de la ficha.\n"
    "- No es el nombre de los padres, del acudiente ni del colegio, ni una dirección.\n"
    "- Sin anotaciones como «(Hoy de …)».\n"
    "- Copia cada palabra tal como está en el texto, aunque parezca mal escrita: no la corrijas ni inventes.\n"
    "- Si el texto no trae el nombre del estudiante, devuelve solo: NINGUNO"
)


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


#: Los años de estudio que la ficha de 1968 a 1999 anota a mano junto al
#: nombre: «1965-1968», «1.983-86», «1978 - 1981».
_PERIODO = re.compile(r"\b(19[2-9]\d|20[0-3]\d)\s?[-–]\s?(19[2-9]\d|20[0-3]\d|\d{2})\b")
#: La fecha de su recuadro «Grado en / Fecha»: «Fecha Marzo 31 de 1970», «Dic
#: 18/87», «Nov. 25 83». Ninguna de las 312 de la caja 00C003277 se leía.
_RECUADRO_DEL_GRADO = re.compile(r"\bGRADO EN\b(.{0,90}?)(?=PROMEDIO ORAL|OBSERVACION|$)")
_ANIO_DE_LA_FECHA = re.compile(r"\b(19[2-9]\d|20[0-3]\d)\b|\d{1,2}\s?[/\- ]\s?(\d{2})\b")


def anios_de_la_ficha(texto: str) -> tuple[int | None, int | None]:
    """El año de ingreso y el de grado -- o el último de estudio -- que escribe la ficha; ``None`` el que no se lea."""
    p = _ANIO_CON_PUNTO.sub(lambda m: m.group(1) + m.group(2), plano(texto))
    ingreso = grado = None
    if hallado := _INGRESO.search(p):
        cifras = re.sub(r"\D", "", hallado.group(1))
        if len(cifras) == 4 and DESDE <= int(cifras) <= 2030:
            ingreso = int(cifras)
    if hallado := _GRADUACION.search(p):
        grado = int(hallado.group(1))
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
    return vistos


def ventana_de_anios(
    textos: Sequence[str], *, nombre: str = "", hasta: int = 2030
) -> tuple[int, int] | None:
    """Los años posibles de un PDF, de sus hojas de notas; ``None`` si hay pocos para decirlo.

    Si las notas no traen años bastantes -- la capa de texto de los 70 no los
    deja leer --, la dan los del nombre del PDF: «1974-1977» es una cohorte que
    estudió de unos ocho años antes a dos después. Sin ventana, un «1923» de la
    capa rota pasaba por el primer año de un expediente de 1974.
    """
    todos = sorted(anio for anio, _ in _candidatos(textos) if DESDE <= anio <= hasta)
    if len(todos) >= MINIMO_PARA_LA_VENTANA:
        bajo = todos[int(0.05 * (len(todos) - 1))] - MARGEN_DE_LA_VENTANA
        alto = todos[int(0.95 * (len(todos) - 1))] + MARGEN_DE_LA_VENTANA
        return bajo, alto
    del_nombre = [int(anio) for anio in _ANIO_DEL_NOMBRE.findall(nombre or "") if DESDE <= int(anio) <= hasta]
    if del_nombre:
        return min(del_nombre) - ANTES_DEL_NOMBRE, max(del_nombre) + MARGEN_DE_LA_VENTANA
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
