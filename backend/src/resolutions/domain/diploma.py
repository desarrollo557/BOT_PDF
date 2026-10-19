"""Reading one diploma registration off one page.

A book of diploma registrations is not a document that gets split by a number
running down its pages: every page is a finished record, and both faces of a
leaf hold different students -- the recto numbered ``337`` and the verso
``337BIS``. So there is no grouping here and no inheritance. There is one page,
one graduate, and the seven things the archive needs to inventory them.

Everything is read twice where the paper says it twice. The folio is printed in
the heading and again in the registration formula at the foot, and comparing the
two is a free check on the OCR: on the books measured, that comparison is what
caught ``Folio 5^`` on a page whose folio is 543.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .carreras import carrera_normalizada
from .folio_manuscrito import MarcaDeFolio
from .text_distance import damerau_levenshtein

#: Las marcas combinantes que una descomposición NFD separa de su letra: la
#: tilde de "á", la virgulilla de "ñ". Quitarlas con una tabla de traducción es
#: lo que hace que plegar un renglón no cueste una llamada por carácter: medido
#: sobre un libro de cuatrocientas caras, eran millón y medio de llamadas.
_MARCAS_COMBINANTES = dict.fromkeys(
    [
        *range(0x0300, 0x0370),
        *range(0x1AB0, 0x1B00),
        *range(0x1DC0, 0x1E00),
        *range(0x20D0, 0x2100),
        *range(0xFE20, 0xFE30),
    ]
)


class CriterioDeCorte(StrEnum):
    """Qué señal del papel decide dónde termina un documento.

    Son dos maneras distintas de leer el mismo empaste, y cuál corresponde lo
    sabe quien lo tiene delante. Ninguna es más correcta que la otra en
    abstracto: dependen de cómo esté armado el libro.
    """

    #: **El folio escrito a mano en la esquina.** La cara que lo lleva abre
    #: documento; la que llega con la esquina limpia es su vuelta y va en el
    #: mismo archivo. Es la unidad *hoja de papel*.
    #:
    #: Es el valor por omisión y el más barato con diferencia: la marca se
    #: decide **contando tinta**, sin leer una palabra, de modo que sólo hay que
    #: leer las caras que abren -- la mitad del libro -- y sólo para ponerles
    #: nombre.
    FOLIO = "folio"

    #: **El número de cédula.** Mientras la cédula no cambie, las caras son del
    #: mismo documento; cuando aparece otra, empieza uno nuevo. Es la unidad
    #: *persona*, y es lo que corresponde cuando un mismo graduado ocupa varias
    #: caras o cuando la foliación de la esquina no es de fiar.
    #:
    #: Cuesta más, y conviene decirlo: la cédula hay que **leerla**, así que no
    #: se puede saltar ninguna cara. A cambio, lo único que hace falta de cada
    #: una es ese número, de modo que una cara cuya cédula sacó el motor de casa
    #: no llega a pagarse nunca.
    CEDULA = "cedula"

    #: **El nombre y la cédula, los dos.** Abre documento la cara cuyo graduado
    #: no es el que viene abierto, y para decir que no lo es hacen falta **las
    #: dos señales a la vez**: otra cédula y otro nombre.
    #:
    #: Es el criterio prudente de los tres. Exigir que dos lecturas
    #: independientes coincidan es lo que impide que un dígito mal leído parta
    #: un documento: si la cédula sale distinta pero el nombre es el mismo, lo
    #: que cambió fue el OCR y no la persona, y la cara se queda donde estaba.
    #:
    #: El precio es el simétrico: dos graduados cuyo nombre el OCR devuelva
    #: parecido y cuya cédula no se dejó leer se quedan juntos, y esa costura
    #: sale declarada en la cola de revisión en vez de resuelta a la brava.
    NOMBRE_Y_CEDULA = "nombre-cedula"

    #: **El encabezado impreso del formulario.** Abre documento toda cara que
    #: arranque con la leyenda del diploma -- "UNIVERSIDAD DE CARTAGENA", "LIBRO
    #: DE REGISTRO DE DIPLOMAS" --, y también la que traiga otro graduando.
    #:
    #: Es el criterio de los libros **mecanografiados**, los de 2011 en
    #: adelante: ahí cada diploma ocupa su propia cara y el formulario va
    #: impreso encima, de modo que la señal es tipográfica y el OCR la lee sola.
    #: Medido sobre los libros 8 de 2013 y de 2012-2013, las dieciséis primeras
    #: caras de cada uno traen encabezado, nombre, cédula y folio, **todo desde
    #: la capa de texto y sin una sola petición a ningún proveedor**.
    #:
    #: Por eso este criterio **no usa nunca el motor de pago**, y eso es parte de
    #: lo que es: pedir IA aquí sería pagar por leer lo que ya estaba leído.
    ENCABEZADO = "encabezado"

    #: **Cada cara es un diploma.** No hay agrupación que decidir: una página,
    #: un documento, y todo el trabajo está en nombrarlo -- por la cédula si se
    #: leyó bien, si no por el nombre, y si la OCR local no saca ninguno, el
    #: nombre con la IA.
    #:
    #: Es la regla del operador, dada con la salida real de dos libros delante:
    #: «cada página es un diploma diferente, lo que tienes que hacer es buscar la
    #: cédula o el nombre para saber cómo guardarlo». Y es el valor por omisión
    #: porque describe su corpus entero: en el libro 7 de 1982 el «Registrado al
    #: folio No.» avanza de uno en uno por cara, y en los de posgrados cada cara
    #: trae su propio graduado.
    #:
    #: Sustituyó a un criterio que unía caras consecutivas del mismo nombre.
    #: Parecía prudente y era un error esperando a ocurrir: dos homónimos seguidos
    #: -- o un apellido que el OCR devolviera parecido -- acababan en un archivo,
    #: y en un libro donde nunca hay que unir, un criterio que puede unir sólo
    #: sirve para equivocarse sin que nadie lo vea.
    PAGINA = "pagina"

    @property
    def paga_lectura(self) -> bool:
        """Si este criterio puede llegar a pedirle páginas al motor de pago.

        Los tres primeros sí: dependen de datos que en los libros antiguos están
        escritos a mano, y el motor de casa no lee manuscrito. El del encabezado
        no, porque la señal que usa está impresa: si el OCR no la ve, tampoco la
        vería la IA mejor de lo que hace falta, y lo que hay que hacer entonces
        es mirar el papel, no gastar.
        """
        return self is not CriterioDeCorte.ENCABEZADO

    @property
    def label(self) -> str:
        return _ETIQUETAS[self]

    @classmethod
    def parse(cls, value: str | None) -> CriterioDeCorte:
        """Lo que llegó por la API. Lo desconocido no se adivina."""
        if value in (None, ""):
            return cls.PAGINA
        try:
            return cls(str(value).strip().lower())
        except ValueError as error:
            opciones = ", ".join(criterio.value for criterio in cls)
            raise ValueError(
                f"criterio de corte desconocido: {value!r}; se esperaba uno de {opciones}"
            ) from error


_ETIQUETAS = {
    CriterioDeCorte.FOLIO: "Por folio",
    CriterioDeCorte.CEDULA: "Por cédula",
    CriterioDeCorte.NOMBRE_Y_CEDULA: "Por nombre y cédula",
    CriterioDeCorte.ENCABEZADO: "Por encabezado (sólo OCR)",
    CriterioDeCorte.PAGINA: "Cada cara es un diploma",
}

# Glyphs OCR swaps for letters. Applied only when recognising the printed
# captions of the form -- never to a value, where a digit turned into a letter
# is corruption and must be reported rather than quietly repaired.
_CAPTION_FOLD = str.maketrans({"¡": "I", "!": "I", "|": "I", "1": "I", "0": "O", "5": "S"})
_NON_LETTER = re.compile(r"[^A-ZÑ ]+")

#: Edits tolerated per character of a printed caption. A sixth is what it takes
#: to still recognise "Nombres y apellidos del graduando" when the scan renders
#: it "Nombres y apellidos de! graduando", which it does on 48 of 397 pages.
_CAPTION_TOLERANCE = 6


@dataclass(frozen=True, slots=True)
class TextLine:
    """One line of a page, with enough position to know what sits above what.

    ``y`` only ever needs to order lines vertically, so a caller with no
    coordinates -- OCR output, for instance -- can pass the line's index.
    """

    text: str
    y: float
    x: float = 0.0


def _fold(text: str) -> str:
    return _NON_LETTER.sub(" ", _strip(text).upper().translate(_CAPTION_FOLD)).strip()


def _strip(text: str) -> str:
    # La mayoría de los renglones que salen de un OCR son ASCII puro, y ésos no
    # tienen nada que quitar: se contesta sin descomponer.
    if text.isascii():
        return text
    return unicodedata.normalize("NFD", text).translate(_MARCAS_COMBINANTES)


def has_caption(line: str, caption: str) -> bool:
    """Whether ``line`` carries this printed caption, OCR damage included."""
    return _has_caption_folded(_fold(line).split(), caption)


def _has_caption_folded(words: Sequence[str], caption: str) -> bool:
    """La misma pregunta sobre un renglón ya plegado y partido en palabras.

    Existe porque un mismo renglón se compara contra treinta leyendas seguidas
    -- las del formulario --, y plegarlo treinta veces era la mitad del tiempo
    de leer la capa de texto de un libro.
    """
    budget = max(1, len(caption) // _CAPTION_TOLERANCE)
    target = caption.split()
    width = len(target)
    if width == 0 or len(words) < width:
        return False
    for start in range(len(words) - width + 1):
        window = " ".join(words[start : start + width])
        if damerau_levenshtein(window, caption, ceiling=budget) <= budget:
            return True
    return False


CAPTION_GRADUATE = _fold("NOMBRES Y APELLIDOS DEL GRADUANDO")

#: Con qué leyendas arranca el formulario de un diploma.
#:
#: Cualquiera de ellas en lo alto de la cara dice que ahí empieza un formulario
#: nuevo, y por tanto un diploma nuevo. Son varias porque los empastes no usan
#: todos la misma cabecera y porque el escáner se come la primera línea a
#: menudo: en los libros medidos aparecen "UNIVERSIDAD DE CARTAGENA", "LIBRO DE
#: REGISTRO DE DIPLOMAS DE POSTGRADOS" y "LA REPUBLICA DE COLOMBIA", y basta con
#: que se reconozca una.
#:
#: Se comparan con la misma holgura difusa que el resto de leyendas impresas,
#: porque así es como llegan: medido sobre el libro 8 de 2013, la capa de texto
#: devuelve "UMiVERSSDAD DE CARTAGENA" en una cara y "UNiVERSiDAD DE CARTAGEMA"
#: en otra. Exigir la cadena exacta reconocería una de cada tres.
ENCABEZADOS_DEL_FORMULARIO = tuple(
    _fold(leyenda)
    for leyenda in (
        "UNIVERSIDAD DE CARTAGENA",
        "LIBRO DE REGISTRO DE DIPLOMAS",
        "LIBRO DE REGISTRO DE DIPLOMAS DE POSTGRADOS",
        "LA REPUBLICA DE COLOMBIA",
    )
)

#: Cuántos renglones del principio de la cara se miran buscando el encabezado.
#:
#: Ocho. El encabezado va arriba del todo -- es el membrete del formulario -- y
#: mirar la página entera haría que la fórmula del cuerpo ("por intermedio de la
#: UNIVERSIDAD DE CARTAGENA", que va a media hoja) contara como un encabezado
#: nuevo. Entonces toda cara abriría documento y el criterio no diría nada.
_RENGLONES_DEL_ENCABEZADO = 8


def abre_formulario(lines: Sequence[TextLine]) -> bool:
    """Si esta cara arranca con el membrete impreso de un diploma.

    Es la señal tipográfica de que aquí empieza un formulario nuevo, y por tanto
    un diploma nuevo. A diferencia del folio de la esquina -- que se mide
    contando tinta -- ésta hay que leerla, pero está **impresa**, de modo que la
    lee el motor de casa sin ayuda de nadie.
    """
    alto = sorted(lines, key=lambda linea: linea.y)[:_RENGLONES_DEL_ENCABEZADO]
    for linea in alto:
        palabras = _fold(linea.text).split()
        if any(
            _has_caption_folded(palabras, leyenda) for leyenda in ENCABEZADOS_DEL_FORMULARIO
        ):
            return True
    return False

# -- dónde empieza cada diploma, por lo impreso -------------------------------
#
# Lo dictó el operador mirando las tres plantillas de la carpeta REGISTROS DE
# DIPLOMAS 3269 - 3291: «cada vez que veas un [encabezado] también es un pdf
# nuevo, o un diploma dividido». El membrete abre diploma; la cara que no trae
# nada del formulario es la continuación del anterior.
#
# El membrete solo no alcanza: en los libros antiguos va en letra decorativa y
# la capa lo deja como «^.OOIÜEKSIDHO oe CePIRSEOñ» -- se reconoció en 223 de
# las 396 caras del libro 3858080 --. Las leyendas impresas del formulario sí
# salen, y con ellas se reconocen las 4.143 caras de los once libros de la
# carpeta, sin una sola lectura de pago. Van en tres grupos porque no dicen lo
# mismo: las de **apertura** sólo están en la cara que empieza un diploma; las
# del **cuerpo** y las del **cierre** también estarían en la mitad de abajo de
# un diploma partido en dos caras, y por eso solas no abren.

#: Lo que sólo trae la cara donde empieza un diploma, en cualquiera de las tres
#: plantillas: la mecanografiada (2011 en adelante) y las dos manuscritas.
LEYENDAS_DE_APERTURA = tuple(
    _fold(leyenda)
    for leyenda in (
        "Y EN SU NOMBRE LA",
        "EN ATENCION A QUE EL SEÑOR",
        "NOMBRES Y APELLIDOS DEL GRADUANDO",
        "IDENTIFICADO CON",
        "TITULO RECIBIDO",
        "HA COMPLETADO TODOS LOS ESTUDIOS",
    )
)
#: El cuerpo del formulario.
LEYENDAS_DEL_CUERPO = tuple(
    _fold(leyenda)
    for leyenda in (
        "EXIGEN PARA OPTAR EL TITULO",
        "LE EXPIDE EL PRESENTE DIPLOMA",
        "FECHA DE GRADUACION",
        "FUNCIONARIOS QUE FIRMAN",
    )
)
#: El pie: el registro en el libro y las firmas.
LEYENDAS_DE_CIERRE = tuple(
    _fold(leyenda)
    for leyenda in (
        "REGISTRADO AL FOLIO",
        "REGISTRADO A FOLIO",
        "EN TESTIMONIO DE ELLO",
        "PARA CONSTANCIA ES FIRMADO",
        "DE REGISTRO DE DIPLOMA",
    )
)


@dataclass(frozen=True, slots=True)
class FormaDeLaCara:
    """Qué parte del formulario de un diploma trae una cara, leída de lo impreso."""

    #: Si la cara trae capa de texto: sin ella no se sabe nada de su forma.
    con_texto: bool
    #: El membrete o una leyenda de apertura.
    abre: bool
    #: Alguna leyenda del cuerpo.
    cuerpo: bool
    #: Alguna leyenda del pie.
    cierra: bool


def _trae(lines: Sequence[TextLine], leyendas: Sequence[str]) -> bool:
    return any(
        _has_caption_folded(_fold(linea.text).split(), leyenda)
        for linea in lines
        for leyenda in leyendas
    )


def forma_de_la_cara(lines: Sequence[TextLine]) -> FormaDeLaCara:
    """Qué parte del formulario trae esta cara."""
    return FormaDeLaCara(
        con_texto=any(linea.text.strip() for linea in lines),
        abre=abre_formulario(lines) or _trae(lines, LEYENDAS_DE_APERTURA),
        cuerpo=_trae(lines, LEYENDAS_DEL_CUERPO),
        cierra=_trae(lines, LEYENDAS_DE_CIERRE),
    )


def continuaciones(formas: Sequence[FormaDeLaCara]) -> set[int]:
    """Qué caras -- por su posición, desde 0 -- continúan el diploma anterior.

    Abre diploma la cara que:

    1. trae el membrete o una leyenda de apertura;
    2. trae el cuerpo o el pie **y la anterior ya cerró el suyo**: el membrete
       y la apertura se leyeron mal, pero esto no puede ser la mitad de abajo de
       un diploma que ya terminó (UPD3858080 p117, escaneo oscuro);
    3. no trae capa de texto: no hay con qué decir otra cosa, y en estos libros
       cada cara es un diploma;
    4. es la primera.

    Las demás continúan el anterior: la cara con texto que no trae nada del
    formulario -- un anexo, una vuelta escrita -- y la mitad de abajo de un
    diploma partido en dos caras.
    """
    siguen: set[int] = set()
    for i, forma in enumerate(formas):
        if i == 0 or not forma.con_texto or forma.abre:
            continue
        if (forma.cuerpo or forma.cierra) and formas[i - 1].cierra:
            continue
        siguen.add(i)
    return siguen


#: Lo que sólo imprimen las plantillas antiguas -- la de posgrados sin cédula y
#: la manuscrita de 1981-85 --: el diploma redactado en prosa, con los datos
#: escritos a mano en los huecos. La mecanografiada de 2011-13 es un formulario
#: de rótulos («Nombres y apellidos del graduando», «Folio 21») y no trae
#: ninguna de estas frases.
LEYENDAS_DE_LA_PLANTILLA_ANTIGUA = (
    "EN ATENCION A QUE EL",
    "HA COMPLETADO TODOS LOS ESTUDIOS",
    "LE EXPIDE EL PRESENTE DIPLOMA",
    "EN TESTIMONIO DE ELLO",
)


def plantilla_antigua(lines: Sequence[TextLine]) -> bool:
    """Si esta cara es de una plantilla antigua, con los datos escritos a mano.

    Importa por el asiento. En la mecanografiada «Folio 21» está impreso y la
    capa de texto lo lee bien; en las antiguas va escrito a mano en el hueco de
    «Registrado al folio No.», y lo que la capa devuelve ahí es ruido: «2»
    donde dice 1036, «7» donde dice 1082 (UPD3858080). Un asiento así en el
    inventario es peor que un N/A, y el de verdad lo lee quien sepa leer letra
    a mano.
    """
    return _trae(lines, LEYENDAS_DE_LA_PLANTILLA_ANTIGUA)


#: La fórmula con que los libros antiguos presentan al graduando. Ahí el nombre
#: va *debajo* de la leyenda y no encima, porque el impreso es el diploma mismo
#: y no una ficha de registro: la frase corre y el nombre se escribió a mano en
#: el renglón siguiente.
CAPTION_SENOR = _fold("EN ATENCION A QUE EL SEÑOR")

# -----------------------------------------------------------------------------
#  The fields, as the two forms in these books print them
# -----------------------------------------------------------------------------
#  The books carry two templates. The common one says "Titulo recibido:" and
#  "Registrado a folio No."; the doctorate one says "Titulo de:", "Acta de Grado
#  N°:" and "Titulo registrado a folio No.". Both are the same record, so both
#  patterns feed the same field rather than a second kind of document.
# -----------------------------------------------------------------------------

_FOLIO = re.compile(r"F[O0]L\s?[I¡!|1]?\s?[O0]\s*N?[O°º.]*\s*:?\s*([0-9]{1,4})\s*(BIS)?", re.I)
_REGISTERED_FOLIO = re.compile(
    r"REG[I¡]STRAD[O0]\s+A[LI]?\s+F[O0]L[I¡!|1]?[O0]\s*N?[O°º.]*\s*_*\s*([0-9]{1,5})\s*(B[I1]S)?",
    re.I,
)
_REGISTERED_FOLIO_ALT = re.compile(
    r"T[I¡]TUL[O0]\s+REG[I¡]STRAD[O0]\s+A\s+F[O0]L[I¡]?[O0]\s*N?[O°º.]*\s*([0-9]{1,5})\s*(B[I1]S)?",
    re.I,
)
_BOOK = re.compile(r"L[I¡]BR[O0]\s*N?[O°º.]*\s*_*\s*([0-9]{1,3})", re.I)
_DEGREE = re.compile(r"T[I¡]TUL[O0]\s+REC[I¡]B[I¡]D[O0]\s*:?\s*(.+)", re.I)
_DEGREE_ALT = re.compile(r"T[I¡]TUL[O0]\s+DE\s*:\s*(.+)", re.I)

#: Los libros antiguos no rotulan el título: lo escriben a mano detrás de la
#: fórmula impresa "DOCTOR EN". El grado forma parte del título -- "DOCTOR EN
#: MEDICINA Y CIRUGIA" -- así que se conserva entero, pero la especialidad se
#: captura **aparte** para poder comprobarla: la fórmula está impresa y el OCR
#: la lee siempre, mientras que lo que va detrás está manuscrito y muchas veces
#: no lo lee nadie. Sin esa separación, "DOCTOR EN" más dos rayas pasa por
#: título: medido sobre el libro de posgrados 3858080, la mayoría de sus 224
#: unidades se archivó bajo "DOCTOR EN //", "DOCTOR EN )" o "DOCTOR EN ^".
_DEGREE_DOCTOR = re.compile(r"(D[O0]CT[O0]R\s+EN\s+([^\n]+))", re.I)

#: De qué plantilla sale el título, qué grupo trae la especialidad y con qué
#: grupo se escribe el valor final. El orden va de la más explícita a la menos:
#: el libro que rotula "Titulo recibido:" manda sobre el que sólo imprime
#: "DOCTOR EN", que es el antiguo y el que hay que leer al final porque su
#: fórmula también aparece dentro del cuerpo de los modernos.
_PLANTILLAS_DEL_TITULO = (
    (_DEGREE, 1, 1),
    (_DEGREE_ALT, 1, 1),
    (_DEGREE_DOCTOR, 1, 2),
)

#: Lo que tiene que haber en una especialidad para llamarla especialidad: una
#: palabra de cuatro letras seguidas, por lo menos. "MEDICINA" la tiene;
#: "//", ")", "T" y "y7iji\'dc¿y\'zA^" no.
_PALABRA_DEL_TITULO = re.compile(r"[A-ZÁÉÍÓÚÜÑ]{4,}", re.I)

_GRADUATION = re.compile(
    r"GRADUAC[I¡]ON\s*[;:]?\s*(\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4})", re.I
)

# -----------------------------------------------------------------------------
#  La fecha escrita con letras de los libros antiguos
# -----------------------------------------------------------------------------
#  Los empastes anteriores a los formularios mecanografiados fechan el diploma
#  como se fechaba entonces: "a los 10 días del mes de Mayo de mil novecientos
#  setenta y dos". Es una fecha completa y está impresa la mitad, así que se lee
#  igual que cualquier otra en vez de darse por perdida. Lo que no está escrito
#  -- un año que el escaneo dejó ilegible -- sigue sin completarse.
# -----------------------------------------------------------------------------

_MESES = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "SETIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}

_NUMEROS = {
    "UN": 1, "UNO": 1, "DOS": 2, "TRES": 3, "CUATRO": 4, "CINCO": 5, "SEIS": 6,
    "SIETE": 7, "OCHO": 8, "NUEVE": 9, "DIEZ": 10, "ONCE": 11, "DOCE": 12,
    "TRECE": 13, "CATORCE": 14, "QUINCE": 15, "DIECISEIS": 16, "DIECISIETE": 17,
    "DIECIOCHO": 18, "DIECINUEVE": 19, "VEINTE": 20, "VEINTIUNO": 21,
    "VEINTIDOS": 22, "VEINTITRES": 23, "VEINTICUATRO": 24, "VEINTICINCO": 25,
    "VEINTISEIS": 26, "VEINTISIETE": 27, "VEINTIOCHO": 28, "VEINTINUEVE": 29,
    "TREINTA": 30, "CUARENTA": 40, "CINCUENTA": 50, "SESENTA": 60,
    "SETENTA": 70, "OCHENTA": 80, "NOVENTA": 90,
}

_FECHA_EN_LETRAS = re.compile(
    r"A\s+L[O0]S\s+(\d{1,2}|[A-Z]+)\s+D[I¡]?AS?\s+DEL\s+MES\s+"
    r"DE\s+([A-Z]+)\s+DE\s+(?:M[I¡]L\s+)?N[O0]VEC[I¡]ENT[O0]S[\s\S]{0,50}?"
    # El año, en letras o en cifras. Las dos formas están en el mismo libro y
    # muchas veces en la misma página: el impreso dice "de mil novecientos" y
    # deja el hueco, y quien rellenó el diploma escribió a mano "ochenta y uno"
    # o "81" según el día que fuera. Aceptar sólo las letras dejaba el FUID sin
    # fechas extremas -- N/A en las veinte filas de la muestra medida -- teniendo
    # el dato escrito en el papel y leído por el OCR.
    r"([A-Z]+(?:\s+Y\s+[A-Z]+)?|\d{1,2})",
    re.I,
)


def _numero_en_letras(palabras: str) -> int | None:
    """Un número de dos cifras escrito con palabras, o ``None`` si no lo es.

    Sólo las dos formas que estos libros usan: una palabra -- "setenta" -- o una
    decena y una unidad unidas por "y" -- "setenta y dos". Cualquier otra cosa
    se declara ilegible antes que adivinarla.
    """
    partes = [parte for parte in palabras.upper().split() if parte != "Y"]
    if not partes or len(partes) > 2:
        return None
    total = 0
    for parte in partes:
        valor = _NUMEROS.get(parte)
        if valor is None:
            return None
        total += valor
    return total if total <= 99 else None


def fecha_en_letras(texto: str) -> str | None:
    """La fecha escrita con letras, en el DD/MM/AAAA que usa el resto del lector."""
    encontrada = _FECHA_EN_LETRAS.search(_strip(texto).upper())
    if not encontrada:
        return None

    bruto_dia, bruto_mes, bruto_anio = encontrada.groups()
    dia = int(bruto_dia) if bruto_dia.isdigit() else _numero_en_letras(bruto_dia)
    mes = _MESES.get(bruto_mes.upper())
    resto = int(bruto_anio) if bruto_anio.isdigit() else _numero_en_letras(bruto_anio)
    if dia is None or mes is None or resto is None or not (1 <= dia <= 31):
        return None
    return f"{dia:02d}/{mes:02d}/{1900 + resto}"


_IDENTITY = re.compile(
    r"[I¡]DENT[I¡]F[I¡]CAD[OA]\s+CON\s*([A-Z.]{1,6})\s*N[O°º.]*\s*([0-9][0-9.,]{3,14})", re.I
)
#: La cedula tal como la escriben los libros antiguos, que no rotulan
#: "identificado con" sino que ponen la formula del diploma: "C.C. No.
#: 7.882.907 Expedida en Arizona Bolivar". El numero va escrito a mano encima
#: del renglon impreso, asi que solo aparece cuando la pagina se leyo con un
#: OCR que sepa manuscrito -- Tesseract devuelve "C.c. No," y nada mas.
#:
#: Se aceptan las dos formas de escribirlo, con separadores de miles y sin
#: ellos, porque el mismo numero sale de las dos maneras y hay que poder
#: compararlos: es lo que decide si dos hojas seguidas son del mismo graduado.
#: Los separadores de millar son opcionales grupo a grupo, porque así llega el
#: número escrito a mano: "9.081624" y "8673.721" son lecturas reales del libro 7
#: y las dos son la cédula entera con un punto de menos. Lo que no se admite es
#: otra cosa en medio -- "33/23.201", "4V.425.748" --: ahí el OCR confundió un
#: trazo, y de ese número no se sabe qué parte es dato.
#:
#: Y el número agrupado tiene que terminar donde terminan los dígitos: sin ese
#: freno, "1047375454" se leía "104737545" -- nueve dígitos que se sostienen --
#: y perdía el último.
_CEDULA_DEL_DIPLOMA = re.compile(
    r"C\.?\s?C\.?\s*N?[O°º.]*\s*:?\s*(\d{1,3}(?:[., ]?\d{3}){1,3}(?!\d)|\d{5,11})",
    re.I,
)

#: Que el texto lleve el rótulo impreso de la cédula, diga lo que diga el número.
_ROTULO_DE_CEDULA = re.compile(
    r"C\.?\s?C\.?\s*N[O°º.]|[I¡]DENT[I¡]F[I¡]CAD[OA]\s+CON|C[EÉ]DULA", re.I
)


#: Cuántos dígitos tiene que tener un número para poder llamarlo cédula.
#:
#: Seis. Es el suelo de las cédulas de ciudadanía que circulan en estos libros:
#: las series de Bolívar de la generación que se gradúa en 1982 son 9.0xx.xxx y
#: 45.xxx.xxx, y las más antiguas que aparecen son de seis. Lo que baja de ahí
#: no es una cédula corta, es una cédula a la que el OCR le comió dígitos:
#: medido sobre las dieciséis primeras caras del libro 7, "30761", que iba a
#: nombrar un archivo llamado `30761_DIPLOMA.pdf`.
#:
#: Se probó antes subir el suelo a siete y bajarlo a cuatro cuando el número
#: venía escrito con sus puntos de millar, con el argumento de que la propia
#: agrupación de tres en tres lo valida. **No se sostiene**, y conviene dejarlo
#: escrito para que nadie lo reintente: perder el dígito de delante conserva la
#: agrupación intacta -- de "930.761" sale "30.761", que agrupa perfectamente --
#: de modo que los separadores no prueban que el número esté entero. Medido
#: sobre ese mismo libro, con la excepción puesta "30.761" pasaba igual.
CEDULA_DIGITOS_MINIMOS = 6

#: Y el techo. Ninguna cédula de ciudadanía colombiana pasa de diez dígitos -- ni
#: siquiera el NUIP, que los tiene justos --, así que lo que pase de ahí es el
#: número pegado a otra cosa que el OCR arrastró del renglón.
CEDULA_DIGITOS_MAXIMOS = 10


#: Un número suelto que podría ser una cédula, sin la fórmula que la rotula.
#:
#: Hace falta porque el rastreo especializado lee la banda con Tesseract atado a
#: dígitos, y entonces lo que vuelve no es "C.C. No. 7.882.907" sino "7.882.907"
#: a secas. Sin rótulo alrededor, lo único que separa una cédula de un folio o
#: de un año es su forma, y de eso se encarga `cedula_creible`.
_NUMERO_SUELTO = re.compile(r"\d[\d.,]{4,14}\d")


def buscar_cedula(texto: str) -> str | None:
    """La primera cédula que se sostenga dentro de este texto, o nada.

    Mira primero las dos fórmulas que rotulan el número -- "identificado con
    C.C. No." y la del diploma antiguo -- porque un número rotulado dice de sí
    mismo que es una cédula. Sólo si no hay ninguna se conforma con un número
    suelto, y entonces la credibilidad es lo único que lo defiende de ser el
    folio, el año o el número del libro.

    Devuelve siempre un número **creíble**: lo que no se sostiene no sirve para
    nombrar ni para cortar, así que entregarlo sólo serviría para que alguien lo
    usara sin comprobarlo.

    Y un rótulo cuyo número no se sostiene **no da paso a un número suelto**.
    De "C.C. No. 4V.425.748" el número suelto es "425.748", que tiene seis
    dígitos y pasa por cédula, y no lo es: le falta el "45" que el OCR leyó
    como una uve. Un trozo de cédula con aspecto de cédula es peor que ninguna,
    porque nombra el archivo y nadie vuelve a mirarlo.
    """
    rotulada = cedula_tras_el_rotulo(texto)
    if rotulada or _ROTULO_DE_CEDULA.search(texto):
        return rotulada
    for encontrado in _NUMERO_SUELTO.finditer(texto):
        valor = cedula_normalizada(encontrado.group(0))
        if cedula_creible(valor):
            return valor
    return None


def cedula_tras_el_rotulo(texto: str) -> str | None:
    """La cédula que sigue al rótulo impreso -- "C.C. No.", "identificado con"
    -- si se sostiene, y nada en cualquier otro caso. Nunca un número suelto."""
    for patron, grupo in ((_IDENTITY, 2), (_CEDULA_DEL_DIPLOMA, 1)):
        for encontrado in patron.finditer(texto):
            valor = cedula_normalizada(encontrado.group(grupo))
            if cedula_creible(valor):
                return valor
    return None


def cedula_creible(valor: str | None) -> bool:
    """Si este número se puede sostener como cédula por sí solo.

    La pregunta no es si el número es correcto -- eso sólo lo sabe quien tenga
    la hoja delante -- sino si **se puede apoyar una decisión en él**. Una
    cédula creíble nombra el archivo y puede separar dos diplomas; una que no lo
    es no hace ninguna de las dos cosas y se declara en revisión. Usar a medias
    un dato dudoso -- nombrar con él pero no cortar, o al revés -- sería dejar
    el error dentro sin dejar rastro de él.

    La regla la fijó el operador después de ver que la comprobación por cédula
    que se había quitado -- la cédula está manuscrita y el OCR le come dígitos --
    volvía a hacer falta para no empalmar diplomas distintos. Lo que cambió
    respecto de aquella vez es justamente esto: antes se comparó cualquier cosa
    que se pareciera a un número, y ahora sólo lo que se sostiene.
    """
    numero = cedula_normalizada(valor)
    if not numero or not numero.isdigit():
        return False
    # Ninguna cedula empieza por cero. Cuando el OCR devuelve uno delante es que
    # se trajo un caracter del renglon impreso, no un digito del numero.
    if numero.startswith("0"):
        return False
    # Ni es una tirada del mismo digito: "1111111" es lo que contesta un escaner
    # ante una raya del formulario, no la cedula de nadie.
    if len(set(numero)) == 1:
        return False
    return CEDULA_DIGITOS_MINIMOS <= len(numero) <= CEDULA_DIGITOS_MAXIMOS


def cedula_normalizada(valor: str | None) -> str | None:
    """El numero sin puntos ni comas, que es la unica forma comparable.

    El mismo documento se escribe "7.882.907" en una hoja y "7882907" en la de
    al lado, y son la misma persona. Comparar las cadenas tal cual diria que no.
    """
    if not valor:
        return None
    limpio = valor.replace(".", "").replace(",", "").replace(" ", "").strip()
    return limpio or None


_ANNULLED = re.compile(r"\bANULAD[OA]\b", re.I)

#: A name in the small caps these forms use: two or more words. Digits are
#: allowed inside a word on purpose -- the scan renders ZABALETA as "2ABALETA"
#: and ELIZABETH as "ELI2ABETH", and a pattern that rejected those would not
#: skip the damage, it would silently pick the printed caption underneath and
#: file a graduate under "por intermedio de la Universidad de Cartagena".
_NAME = re.compile(r"^[A-ZÑ0-9!|¡][A-ZÑ0-9'.!|¡\-]*(?:\s+[A-ZÑ0-9!|¡][A-ZÑ0-9'.!|¡\-]*){1,7}$")
_MIN_NAME_LENGTH = 7

#: Cuántos renglones por debajo de la leyenda puede estar el nombre. Dos: el
#: suyo, y uno de margen por si el escaneo intercaló una raya del formulario.
_RENGLONES_DEL_NOMBRE = 2

#: Lines that sit where the name sits but are printed on every page. Matched
#: through the same fuzzy comparison as the captions, because on a bad scan they
#: arrive as "por intermedio de ia UNiVERSiDAD DE CARTAGENA".
_FURNITURE = tuple(
    _fold(phrase)
    for phrase in (
        "UNIVERSIDAD DE CARTAGENA",
        "FUNDADA EN",
        "LIBRO DE REGISTRO DE DIPLOMAS DE POSTGRADOS",
        "LIBRO DE REGISTRO DE DIPLOMAS",
        "LA REPUBLICA DE COLOMBIA",
        "MINISTERIO DE EDUCACION NACIONAL",
        "POR INTERMEDIO DE LA UNIVERSIDAD DE CARTAGENA",
        "NOMBRES Y APELLIDOS DEL GRADUANDO",
        "ANULADO",
        # Y las del diploma mismo, que es lo que llevan impreso los libros
        # antiguos: ahí no hay ficha de registro con sus rótulos, hay un diploma
        # con su redacción corrida y los datos escritos a mano encima. Sus
        # renglones caen justo donde cae el nombre y pasan por nombre: medido
        # sobre el libro 7, 371 de sus 398 páginas se archivaban bajo un nombre
        # de graduado que decía "Expedida en", "C.c. No" o "le expide el
        # presente Diploma". Un archivo llamado así no lo encuentra nadie, y lo
        # peor es que no parece roto: parece un nombre mal leído.
        "EN ATENCION A QUE EL SEÑOR",
        "EXPEDIDA EN",
        # El renglón de la cédula, que en estos libros llega partido: el número
        # se escribió a mano y lo que queda impreso en la línea es "C.C. No".
        "C C NO",
        # Y la continuación del renglón de los estudios, que empieza a media
        # frase porque la anterior se cortó por el margen.
        "CLASICOS QUE LOS ESTATUTOS UNIVERSITARIOS",
        "HA COMPLETADO TODOS LOS ESTUDIOS",
        "ESTUDIOS CLASICOS QUE LOS ESTATUTOS UNIVERSITARIOS",
        # El renglon que sigue al de los estudios, y que el recorte del nombre
        # arrastra por abajo. Sin el aqui, cinco archivos del libro de
        # posgrados 3858081 salieron llamados
        # "exigen-para-optar-el-titulo-de_DIPLOMA.pdf": tiene forma de nombre
        # -- palabras en fila, sin digitos -- y es la leyenda impresa.
        "EXIGEN PARA OPTAR EL TITULO DE",
        "EXIGEN PARA OPTAR EL TITULO",
        "OPTAR EL TITULO DE",
        "LE EXPIDE EL PRESENTE DIPLOMA",
        "AL MISMO TIEMPO TESTIFICA Y GARANTIZA",
        "POR MINISTERIO DE LA LEY",
        "PARA DESEMPEÑAR LA PROFESION DE",
        "EN TESTIMONIO DE ELLO FIRMAMOS Y SELLAMOS",
        "EL RECTOR DE LA UNIVERSIDAD",
        "EL DECANO DE LA FACULTAD",
        "EL SECRETARIO DE LA FACULTAD",
        "DIAS DEL MES DE",
        "DE MIL NOVECIENTOS",
        "REGISTRADO AL FOLIO",
        "DE REGISTRO DE DIPLOMA",
        "DE LA RECTORIA DE LA UNIVERSIDAD",
        # Las mismas leyendas del pie, tal como llegan cuando el escaneo se
        # comió el principio del renglón. No son frases distintas: son éstas
        # cortadas por el margen, y hay que nombrarlas aparte porque la
        # comparación difusa mide ediciones, no recortes.
        "ISTRO DE DIPLOMA DE",
        "DEL LIBRO NO",
        "LA RECTORIA",
    )
)


def _is_furniture(line: str) -> bool:
    palabras = _fold(line).split()
    return any(_has_caption_folded(palabras, phrase) for phrase in _FURNITURE)

#: Anything inside a name that cannot be part of one. Its presence does not
#: repair the name -- it marks it unreliable, because "ELI2ABETH" could be
#: ELIZABETH and nothing on the page proves which letter the scanner lost.
#:
#: Cualquier letra latina con su acento cuenta como letra, y no sólo las
#: vocales del español: el motor de pago devuelve "EUGÈNE" con acento grave, y
#: marcarlo como dañado mandaba a revisión un nombre perfectamente legible.
_DAMAGE_IN_NAME = re.compile(r"[^A-Za-zÀ-ÖØ-öø-ÿ'. \-]")


@dataclass(frozen=True, slots=True)
class DiplomaRecord:
    """One graduate's registration, as read from one page.

    Every field is optional and none is ever filled with a plausible stand-in.
    A registration whose date could not be read carries ``None``, and the
    inventory writes what the archival instruction requires for an absent date,
    which is ``N/A`` and not a date that nobody can trace to the paper.
    """

    page_number: int
    folio: str | None = None
    registered_folio: str | None = None
    book: str | None = None
    name: str | None = None
    carrera: str | None = None
    identity_kind: str | None = None
    identity_number: str | None = None
    #: Si esta cara arranca con el membrete impreso del formulario.
    #:
    #: Es la señal tipográfica de que aquí empieza un diploma nuevo, y la
    #: única de las cuatro que se lee del papel **impreso**: el folio está
    #: manuscrito en la esquina y la cédula y el nombre van escritos a mano
    #: sobre el formulario en los libros antiguos. Por eso el criterio que
    #: la usa no necesita pagar ninguna lectura.
    encabezado: bool = False
    #: Si esta cara es la continuación del diploma anterior: trae capa de texto
    #: pero nada que abra un formulario (ver ``continuaciones``). Sólo se marca
    #: con esa evidencia; sin ella la cara abre diploma, que es lo que pasa en
    #: estos libros.
    continuacion: bool = False
    degree: str | None = None
    graduation_date: str | None = None
    annulled: bool = False
    #: Si la esquina alta de la hoja llevaba folio escrito a mano. No se lee
    #: cuál: sólo si lo hay, que es lo que dice si aquí empieza un registro o
    #: si esta cara es la vuelta del anterior. ``None`` mientras nadie haya
    #: mirado la esquina -- una fuente sin píxeles, una lectura de prueba --
    #: y entonces la agrupación decide como decidía antes.
    folio_mark: MarcaDeFolio | None = None
    #: El folio escrito a mano en esa esquina, cuando alguien supo leerlo y el
    #: libro lo confirmó. No es lo mismo que ``folio``, que es el que el
    #: formulario trae impreso, ni que ``registered_folio``, que es el del libro
    #: de registro citado al pie: éste es la foliación del expediente, la que un
    #: archivista escribió hoja por hoja, y en los libros antiguos es lo único
    #: que identifica la hoja porque lo demás está en blanco o manuscrito.
    #: ``None`` cuando no se leyó o cuando lo leído no encajó con la progresión
    #: del libro, y entonces el archivo se nombra por su página.
    folio_manuscrito: str | None = None
    #: Fields whose two readings disagree, or that came back malformed. The
    #: operator sees these; nothing is silently accepted.
    warnings: list[str] = field(default_factory=list)

    @property
    def trusted_folio(self) -> str | None:
        """The folio to believe, given that the page prints it twice.

        Where the two readings differ, the longer one wins: OCR drops digits far
        more often than it invents them. On the four disagreements measured --
        338 against 33, 543 against 5, 668 against 6, 340BIS against 340 -- the
        longer reading was every time the one printed on the paper.
        """
        heading, foot = self.folio, self.registered_folio
        if heading and foot and heading != foot:
            return heading if len(heading) >= len(foot) else foot
        # Y si el formulario no trae ninguno impreso -- los libros antiguos no
        # los traen: ahí el folio es una anotación a mano en la esquina y nada
        # más --, el de la esquina, que para eso se leyó y se comprobó contra la
        # progresión del libro antes de llegar hasta acá.
        return heading or foot or self.folio_manuscrito

    @property
    def is_complete(self) -> bool:
        return all(
            (self.folio, self.name, self.degree, self.graduation_date, self.book)
        )

    @property
    def carries_no_identifier(self) -> bool:
        """Si en esta página no había absolutamente nada con qué identificarla.

        Es distinto de "no se pudo leer bien". Una página ilegible trae algo --
        un folio a medias, un nombre, una fecha -- y es un registro que hay que
        revisar. Ésta no trae nada, y en el archivo de la Universidad eso tiene
        un significado preciso: es la vuelta de la hoja anterior.

        Las hojas se escanean por las dos caras cuando llevan algo escrito
        detrás, y el folio de la cara delantera se anota a mano con una "v" al
        lado. La cara de atrás llega sin folio y sin nada más, porque nunca lo
        tuvo. Lo mismo vale para lo que alguien anexó al expediente: la
        fotografía de una cédula no lleva folio ni encabezado.

        Una página así no es un registro nuevo. Pertenece al registro que venía
        abierto, igual que en un expediente de resoluciones una página sin
        encabezado pertenece a la resolución de más arriba.
        """
        return not any(
            (
                self.trusted_folio,
                self.book,
                self.name,
                self.identity_number,
                self.degree,
                self.graduation_date,
            )
        )

    @property
    def continua_la_anterior(self) -> bool:
        """Si esta cara pertenece al registro que venía abierto.

        Un libro de registro se folia a mano en la esquina alta de la cara de
        delante. La de atrás no lo lleva porque nunca lo tuvo, así que la marca
        contesta la pregunta directamente y sin leer el papel: hay folio, abre
        registro; no hay folio, es la vuelta de la hoja anterior.

        Una esquina que se miró y no dijo nada claro también une: no es
        evidencia de que aquí empiece nada, y la norma de la casa es que ante la
        duda se une y la costura se declara para revisión, nunca que se corta.
        Partir un registro en dos deja dos archivos de media hoja que nadie
        reconoce; unirlos de más deja una hoja señalada por su nombre en la cola
        de revisión.

        Cuando nadie pudo mirar la esquina -- una fuente sin píxeles, una
        página que no se dejó rasterizar -- se cae a la regla de antes, que
        pregunta por los identificadores leídos. Es más débil, porque depende de
        que el OCR haya sabido leer algo, pero es la que había y sigue
        acertando donde la tinta no se puede medir. Y tiene que ser ésa y no la
        de la duda: si se uniera también aquí, un libro entero sin medir se
        soldaría en un solo documento.

        La usan el separador y el FUID, y tiene que ser la misma para los dos:
        si el inventario contara una fila donde la carpeta escribe media, el
        inventario prometería más diplomas de los que hay archivos.
        """
        if self.folio_mark is MarcaDeFolio.PRESENTE:
            return False
        if self.folio_mark in (MarcaDeFolio.AUSENTE, MarcaDeFolio.DUDOSA):
            return True
        return self.carries_no_identifier

    @property
    def identity_creible(self) -> bool:
        """Si la cédula leída se puede sostener como cédula.

        Una cédula creíble hace dos cosas: nombra el archivo y, cuando la de la
        cara anterior es otra, prueba que aquí empieza un registro distinto. Una
        que no lo es no hace ninguna de las dos, y se dice por qué en la cola de
        revisión. Usar a medias un dato dudoso -- nombrar con él pero no cortar,
        o al revés -- sería dejar el error dentro sin dejar rastro de él.
        """
        return cedula_creible(self.identity_number)

    @property
    def nombre_creible(self) -> bool:
        """Si el nombre leído sirve para identificar y guardar el diploma.

        Una palabra sola suele ser un fragmento del renglón, y un dígito o
        símbolo extraño indica que el OCR dañó el nombre. Esas lecturas deben
        dejar paso a la siguiente mirada, incluida la IA.
        """
        nombre = (self.name or "").strip()
        return bool(
            nombre
            and len(nombre.split()) >= 2
            and not _DAMAGE_IN_NAME.search(nombre)
        )


    @property
    def debe_releerse(self) -> bool:
        """Si vale la pena gastar una lectura de OCR en esta página.

        Cualquier hueco la justifica, porque el OCR puede cerrarlo y cuesta lo
        mismo intentarlo. Es una pregunta sobre el gasto, no sobre el resultado.
        """
        return bool(self.warnings) or not self.is_complete

    @property
    def needs_review(self) -> bool:
        """Si una persona tiene que abrir esta página y mirarla.

        Sólo cuando hay un aviso, y un aviso es una **contradicción o una
        costura dudosa**: el folio del encabezado contra el del pie, un nombre
        con un dígito dentro, una esquina que la tinta no resolvió, una hoja sin
        nada con qué situarla. Eso es lo que significa que algo pudo salir mal y
        lo que vale la pena que alguien mire.

        Lo que **no** manda a revisar es que un dato no se haya leído. Se probó
        lo contrario y hacía inútil la cola: exigir la fecha marcaba 354 de las
        398 páginas del libro 7 de 1982, porque está escrita a mano; y exigir la
        cédula o el folio marcaba las 398 en cuanto se leía sin el motor de pago,
        porque en ese libro todo lo que identifica al graduado es manuscrito. La
        pantalla entera en rojo no señala nada, y el operador acaba ignorándola
        -- que es peor que no tenerla.

        Un documento sin cédula leída no está mal cortado: se llama por su orden
        en el libro, que es un dato cierto, y el FUID escribe ``N/A`` donde el
        papel no se dejó leer, que es lo que pide la instrucción archivística.
        Quien quiera saber cuáles quedaron sin nombre tiene la columna del
        inventario, que es donde se busca eso.

        Y tampoco manda a revisar un aviso **informativo** -- una cédula que no
        se sostuvo y no se usó, una que dos lecturas confirmaron contra una
        tercera --: dice algo que pasó, no algo que quedó mal.
        """
        return any(not es_informativo(aviso) for aviso in self.warnings)

    @property
    def review_reason(self) -> str | None:
        """Por qué hay que mirar esta página, en una frase. ``None`` si no hay que.

        Es lo que lee el operador mientras el trabajo corre, así que dice qué
        pasa y no sólo que pasa algo. La diferencia no es de estilo: "página 83
        ilegible" manda a abrir una página que se leyó entera y bien, mientras
        que "el folio del encabezado (81) no coincide con el del pie (810)" dice
        exactamente dónde poner el ojo.
        """
        if not self.needs_review:
            return None

        return "; ".join(aviso for aviso in self.warnings if not es_informativo(aviso))

    def as_dict(self) -> dict[str, object]:
        return {
            "page": self.page_number,
            "folio": self.folio,
            "registered_folio": self.registered_folio,
            "book": self.book,
            "name": self.name,
            "carrera": self.carrera,
            "identity_kind": self.identity_kind,
            "identity_number": self.identity_number,
            # Que la cédula se pudiera sostener o no viaja al informe, porque es
            # lo que explica que un archivo lleve su folio en vez de su cédula.
            "identity_creible": self.identity_creible,
            "encabezado": self.encabezado,
            "continuacion": self.continuacion,
            "degree": self.degree,
            "graduation_date": self.graduation_date,
            "annulled": self.annulled,
            "folio_mark": str(self.folio_mark) if self.folio_mark else None,
            "warnings": list(self.warnings),
        }


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    found = pattern.search(text)
    if not found:
        return None
    value = found.group(1).strip(" _-.:;")
    return value or None


def _folio_value(pattern: re.Pattern[str], text: str) -> str | None:
    """A folio number with its BIS suffix, which is the verso of the leaf."""
    found = pattern.search(text)
    if not found:
        return None
    number = found.group(1).strip(" _-.:")
    if not number:
        return None
    suffix = found.group(2) if found.lastindex and found.lastindex >= 2 else None
    # "340B1S" is "340BIS" with a one where the I is; the suffix is recognised
    # through the fold, then written the one way it is ever written.
    return f"{number}BIS" if suffix else number


def _graduate_name(lines: Sequence[TextLine]) -> str | None:
    """The line sitting directly above "Nombres y apellidos del graduando".

    The form prints the name on the rule and its caption underneath, so the
    caption is what locates the name. When the caption itself is too damaged to
    recognise, the name is the first centred line under the folio instead.
    """
    caption = next((line for line in lines if has_caption(line.text, CAPTION_GRADUATE)), None)
    if caption is not None:
        above = sorted(
            (line for line in lines if line.y < caption.y), key=lambda item: -item.y
        )
        return _first_name_among(above)

    # El libro antiguo: "en atención a que el Señor" y, en el renglón de abajo,
    # el nombre. Se prueba antes que la regla del folio porque es una leyenda
    # impresa y explícita, y la del folio es sólo una posición.
    senor = next((line for line in lines if has_caption(line.text, CAPTION_SENOR)), None)
    if senor is not None:
        below = sorted(
            (line for line in lines if line.y > senor.y), key=lambda item: item.y
        )
        # Sólo los dos renglones de debajo, y no todo lo que venga después. En
        # estos libros el nombre se escribió a mano en la línea siguiente a la
        # leyenda, de manera que si esa línea no está en la capa de texto es que
        # el nombre no se leyó -- y entonces no hay nombre, no hay que buscarlo
        # más abajo. Buscando hasta el final de la página siempre aparece algo
        # con forma de nombre: medido sobre el libro 7, 59 de sus 60 primeras
        # caras se archivaban bajo "exigen para optar el título de", "de la
        # Facultad" o "niayor de la Uni", que son el pie del diploma. Ninguna
        # lista de leyendas cierra ese agujero, porque el formulario entero está
        # impreso debajo del nombre y cualquiera de sus renglones sirve de
        # respuesta equivocada.
        found = _first_name_among(below[:_RENGLONES_DEL_NOMBRE])
        if found:
            return found

    folio = next((line for line in lines if _FOLIO.search(_strip(line.text).upper())), None)
    if folio is None:
        return None
    below = sorted((line for line in lines if line.y > folio.y), key=lambda item: item.y)
    return _first_name_among(below)


def _career(lines: Sequence[TextLine]) -> str | None:
    """La carrera escrita bajo la fórmula de los estudios.

    En estos diplomas queda después de ``C.C. No.`` y antes de ``le expide el
    presente Diploma``. Se limita la búsqueda a esa zona para no confundirla
    con cargos, firmas o texto impreso del pie.
    """
    ordenadas = sorted(lines, key=lambda line: line.y)
    inicio = next(
        (indice for indice, line in enumerate(ordenadas)
         if _CEDULA_DEL_DIPLOMA.search(_strip(line.text).upper())
         or has_caption(line.text, "IDENTIFICADO CON")),
        None,
    )
    if inicio is None:
        return None
    fin = next(
        (indice for indice in range(inicio + 1, len(ordenadas))
         if has_caption(ordenadas[indice].text, "LE EXPIDE EL PRESENTE DIPLOMA")),
        len(ordenadas),
    )
    candidatos = []
    for line in ordenadas[inicio + 1 : fin]:
        texto = line.text.strip(" _-.:;")
        if not texto or has_caption(texto, "EXIGEN PARA OPTAR EL TITULO"):
            continue
        carrera = carrera_normalizada(texto)
        if carrera:
            candidatos.append(carrera)
    return candidatos[0] if len(set(candidatos)) == 1 else None


def _first_name_among(candidates: Sequence[TextLine]) -> str | None:
    """The first line in ``candidates`` that can be a person and not the form."""
    for line in candidates:
        candidate = line.text.strip(" _-.:")
        if len(candidate) < _MIN_NAME_LENGTH:
            continue
        if _FOLIO.search(_strip(candidate).upper()) or _is_furniture(candidate):
            continue
        if _NAME.match(_strip(candidate).upper()):
            return candidate
    return None


#: Hasta dónde puede llegar un título antes de que deje de serlo. Sesenta
#: caracteres sobran para el más largo que dan estos libros -- "DOCTOR EN
#: MEDICINA Y CIRUGIA" son veintidos -- y son pocos para una leyenda del
#: formulario. El límite hace falta porque el renglón del título se rellenaba a
#: mano: cuando el OCR no lee lo manuscrito, devuelve el hueco pegado a la
#: leyenda que viene detrás y "optar el título de:" contesta con media página.
#: Medido sobre las dieciséis primeras caras del libro 7, cuatro asuntos del
#: FUID decían "le expide el presente Diploma, - Al mismo tiempo testifica y
#: garantiza ba­".
_LARGO_MAXIMO_DEL_TITULO = 60

#: Y desde dónde empieza a poder serlo. El título más corto que dan estos libros
#: -- "MEDICO" -- tiene seis letras, y cuatro deja margen para uno que no
#: conozcamos. Por debajo de eso no hay título: lo que hay es lo que el OCR
#: rascó del hueco manuscrito que no supo leer. Medido sobre las dieciséis
#: primeras caras del libro 7, el FUID archivaba graduados con el título "V",
#: "I", ")I" e "i" -- cuatro de dieciséis filas --, y un título de un carácter en
#: un inventario documental no es un dato pobre, es ruido con aspecto de dato.
_LARGO_MINIMO_DEL_TITULO = 4


def _titulo(flat: str) -> str | None:
    """El título que recibe el graduado, o nada cuando lo que salió no lo es.

    El orden de las plantillas va de la más explícita a la menos: el libro que
    rotula "Titulo recibido:" manda sobre el que sólo imprime "DOCTOR EN", que
    es el antiguo y el que hay que leer al final porque su fórmula también
    aparece dentro del cuerpo de los modernos.

    Se descarta por tres cosas, y la tercera es la que más trabajo da: lo
    demasiado largo es la leyenda impresa que sigue al hueco manuscrito; lo
    demasiado corto es lo que el OCR rascó de ese hueco sin saber leerlo; y lo
    que **no nombra ninguna especialidad** es la fórmula impresa sola.

    Ese tercer caso es traicionero porque no parece un hueco: la fórmula está
    impresa y el OCR la lee perfectamente, de modo que "DOCTOR EN //" llega con
    aspecto de dato leído. Lo que falta es justamente lo único que importaba.

    Lo que se descarta se descarta entero y no se recorta: un título cortado por
    la mitad -- "le expide el presente" -- parece un dato leído y no lo es, y en
    el FUID lo leería un archivista como el título del graduado. Un hueco
    declarado se ve; un hueco relleno con la leyenda de al lado, no.
    """
    for patron, entero, especialidad in _PLANTILLAS_DEL_TITULO:
        encontrado = patron.search(flat)
        if not encontrado:
            continue
        # En un solo renglón: la fórmula impresa y lo manuscrito están en
        # renglones distintos del papel, así que el título llega partido --
        # "DOCTOR EN\nMedicina y Cirugia" -- y en una celda del FUID eso rompe
        # la fila en dos.
        valor = " ".join((encontrado.group(entero) or "").split()).strip(" _-.:;")
        # La especialidad es lo que de verdad hay que comprobar. En las
        # plantillas modernas es el valor entero; en la del libro antiguo es lo
        # que sigue a la fórmula impresa, que es la única parte manuscrita y por
        # tanto la única que el OCR puede no haber leído.
        parte = " ".join((encontrado.group(especialidad) or "").split())
        if not valor or not _PALABRA_DEL_TITULO.search(parte):
            continue
        if not _LARGO_MINIMO_DEL_TITULO <= len(valor) <= _LARGO_MAXIMO_DEL_TITULO:
            continue
        if _is_furniture(valor):
            continue
        return valor
    return None


def nombre_suelto(lines: Sequence[TextLine]) -> str | None:
    """El nombre de un graduando dentro de un trozo de papel sin contexto.

    Distinto de lo que hace `extract_diploma`, y por un motivo concreto: ahi el
    nombre se localiza **por su leyenda** -- "Nombres y apellidos del graduando"
    encima, "en atencion a que el Senor" debajo -- porque en una pagina entera
    hay veinte renglones con forma de nombre y la leyenda es lo unico que dice
    cual es el bueno.

    Aqui no hay pagina: hay una franja recortada justo donde vive el nombre, de
    modo que la leyenda ya quedo fuera y lo que sobra es poco. Basta con el
    primer renglon que pueda ser una persona y no el formulario, que es la misma
    comprobacion de siempre: largo suficiente, forma de nombre y ninguna de las
    leyendas impresas que el recorte haya arrastrado por los bordes.
    """
    return _first_name_among(list(lines))


def extract_diploma(lines: Sequence[TextLine], page_number: int) -> DiplomaRecord:
    """Read the registration printed on one page."""
    flat = _strip("\n".join(line.text for line in lines))

    folio = _folio_value(_FOLIO, flat)
    registered = _folio_value(_REGISTERED_FOLIO, flat) or _folio_value(
        _REGISTERED_FOLIO_ALT, flat
    )
    identity = _IDENTITY.search(flat)
    # Y si el papel no usa la fórmula de la ficha, la del diploma. No es un
    # segundo tipo de documento: es el mismo dato escrito como lo escribían los
    # libros antiguos, y va detrás porque la ficha es más específica.
    cedula = _CEDULA_DEL_DIPLOMA.search(flat) if identity is None else None
    # La cédula tal como la escribió el papel, venga de la fórmula de la ficha
    # o de la del diploma. Se normaliza una vez y en un solo sitio.
    cedula_en_bruto = (
        identity.group(2) if identity else cedula.group(1) if cedula else None
    )
    name = _graduate_name(lines)
    if name:
        name = name.upper()
    carrera = _career(lines)

    warnings: list[str] = []
    # The folio is printed twice. Where the two readings disagree, one of them
    # is damaged and neither can be trusted on its own.
    if folio and registered and folio != registered:
        warnings.append(f"el folio del encabezado ({folio}) no coincide con el del pie ({registered})")
    if name and _DAMAGE_IN_NAME.search(name):
        warnings.append(f"el nombre trae un carácter que no es una letra: {name}")
    # Un nombre que no se leyó no es un aviso: es una ausencia, y las
    # ausencias van al FUID como N/A. En el libro 7 de 1982 el nombre está
    # escrito a mano y el motor local no lo lee en ninguna de las 398 páginas;
    # avisarlo ponía la pantalla entera en rojo sin señalar nada.

    return DiplomaRecord(
        page_number=page_number,
        folio=folio,
        registered_folio=registered,
        book=_first(_BOOK, flat),
        name=name,
            carrera=carrera,
        identity_kind=identity.group(1).strip(".") if identity else None,
        identity_number=cedula_normalizada(cedula_en_bruto),
        # El membrete del formulario, que se mira sólo en lo alto de la
        # cara: la fórmula del cuerpo repite el nombre de la Universidad a
        # media hoja, y contarla haría que toda cara abriera documento.
        encabezado=abre_formulario(lines),
        # El orden es el de las plantillas, de la más explícita a la menos: el
        # libro que rotula "Titulo recibido:" manda sobre el que sólo imprime
        # "DOCTOR EN", que es el antiguo y el que hay que leer al final porque
        # su fórmula también aparece dentro del cuerpo de los modernos.
        degree=_titulo(flat),
        # La fecha con cifras es la del formulario mecanografiado; la escrita
        # con letras, la del libro antiguo. Ninguna de las dos se deduce.
        graduation_date=_first(_GRADUATION, flat) or fecha_en_letras(flat),
        annulled=bool(_ANNULLED.search(flat)),
        warnings=warnings,
    )


def lines_from_text(text: str) -> list[TextLine]:
    """Treat plain text as lines, using their order as their position.

    OCR gives back text without coordinates. Its reading order is good enough to
    say which line is above which, which is all the name rule needs.
    """
    return [
        TextLine(text=raw.strip(), y=float(index), x=0.0)
        for index, raw in enumerate(text.splitlines())
        if raw.strip()
    ]


def _resolve_doubts(primary: DiplomaRecord, fallback: DiplomaRecord) -> DiplomaRecord:
    """Deja que la segunda lectura resuelva lo que la primera dejó en duda.

    Sólo en duda: un valor que la primera lectura entregó limpio no se toca,
    porque dos lecturas que discrepan es un hecho que el operador tiene que ver
    y no un empate que gane el último en escribir. Pero cuando la primera
    lectura se contradice a sí misma -- un nombre con un dígito dentro, un folio
    que no coincide con el del pie -- y la segunda no, la segunda gana: no es
    preferirla, es que la primera ya dijo que no se sostiene.
    """
    name = primary.name
    if (
        name
        and _DAMAGE_IN_NAME.search(name)
        and fallback.name
        and not _DAMAGE_IN_NAME.search(fallback.name)
    ):
        name = fallback.name

    folio, registered = primary.folio, primary.registered_folio
    heading_disagrees = bool(folio and registered and folio != registered)
    if heading_disagrees and fallback.folio and fallback.folio == fallback.registered_folio:
        # La segunda lectura leyó las dos veces lo mismo, que es exactamente la
        # prueba que a la primera le faltaba.
        folio = registered = fallback.folio

    # Y lo mismo con la cédula: una que no se sostiene -- cinco dígitos sueltos,
    # un cero delante -- no gana por haber llegado primero. Si la segunda lectura
    # trae una que sí se sostiene, manda esa. No es preferir la segunda: es que
    # la primera ya dijo de sí misma que no sirve para nombrar ni para cortar.
    cedula = primary.identity_number
    if not primary.identity_creible and fallback.identity_creible:
        cedula = fallback.identity_number

    if (
        name is primary.name
        and folio is primary.folio
        and registered is primary.registered_folio
        and cedula is primary.identity_number
    ):
        return primary
    return DiplomaRecord(
        page_number=primary.page_number,
        folio=folio,
        registered_folio=registered,
        book=primary.book,
        name=name,
        carrera=primary.carrera or fallback.carrera,
        identity_kind=primary.identity_kind,
        identity_number=cedula,
        encabezado=primary.encabezado,
        continuacion=primary.continuacion,
        degree=primary.degree,
        graduation_date=primary.graduation_date,
        annulled=primary.annulled,
        # La marca de la esquina y el folio que se leyó en ella no salen de
        # ninguna lectura de texto: los puso quien miró los píxeles antes de que
        # se intentara ninguna. Olvidarlos aquí los borraba justo en las páginas
        # donde la segunda lectura había servido de algo, y esa cara pasaba a
        # repartirse por la regla débil -- los identificadores leídos -- sin que
        # nada lo dijera.
        folio_mark=primary.folio_mark,
        folio_manuscrito=primary.folio_manuscrito,
        warnings=[],
    )


def pertenece_al_anterior(
    record: DiplomaRecord,
    padre: DiplomaRecord | None,
    criterio: CriterioDeCorte = CriterioDeCorte.PAGINA,
) -> bool:
    """Si esta cara va dentro del documento que abrió ``padre``.

    Una sola función porque son dos los que preguntan -- el separador, para
    meter la página en el PDF del registro, y el FUID, para sumarle un folio a
    su fila -- y tienen que contestarse lo mismo. Cuando no se contestaban lo
    mismo, el inventario prometía más diplomas de los que había en la carpeta:
    203 filas contra 199 archivos en el libro medido.

    Son dos los casos en que una cara pertenece a la anterior:

    1. **No abre registro**: no lleva folio escrito en la esquina, o no trae
       ningún identificador propio. Es la vuelta de la hoja, o algo que alguien
       anexó.
    2. **Es la misma hoja otra vez**: repite el folio *y* la cédula del que
       está abierto. Pasa en estos libros -- una hoja fotografiada dos veces
       produce dos registros idénticos -- y no lo hacen dos graduados distintos.
       Sobrevive a la marca del folio a propósito: las dos capturas de la misma
       cara llevan las dos su folio escrito, así que por la marca serían dos
       registros.

    Lo que **no** separa dos caras es lo que traigan escrito. Se propuso cortar
    cuando el folio de registro del pie o la cédula de esta cara no fueran los de
    la anterior, y el operador lo rechazó con el papel delante: en su archivo la
    unidad documental es la **hoja**, y la esquina limpia dice que esta cara es
    la vuelta de la que se está llenando. La condición es el folio y sólo el
    folio.

    Conviene saber que la evidencia del libro 7 apunta al otro lado -- las caras
    de esquina limpia traen nombre, cédula y número de asiento propios, y el pie
    de la última página dice 396 y no 199 --, y que se le enseñó y decidió así
    igualmente. No es un descuido: es su criterio de archivo, y no se cambia sin
    que lo pida.
    """
    if padre is None:
        return False
    if criterio is CriterioDeCorte.CEDULA:
        return _pertenece_por_cedula(record, padre)
    if criterio is CriterioDeCorte.NOMBRE_Y_CEDULA:
        return _pertenece_por_persona(record, padre)
    if criterio is CriterioDeCorte.ENCABEZADO:
        return _pertenece_por_encabezado(record, padre)
    if criterio is CriterioDeCorte.PAGINA:
        # Cada diploma empieza en su encabezado: sólo la cara que no trae nada
        # que abra un formulario -- la mitad de abajo de un diploma partido, un
        # anexo -- va con el anterior. La que repite el folio y la cédula de la
        # anterior -- una hoja fotografiada dos veces -- trae su encabezado y se
        # archiva aparte con su página en el nombre.
        return record.continuacion
    if criterio is CriterioDeCorte.FOLIO:
        # Por folio escrito a mano en la esquina: la cara que lo lleva abre
        # registro; la que llega con la esquina limpia es su vuelta y va en el
        # mismo archivo. Es la unidad *hoja de papel*.
        if record.continua_la_anterior:
            return True
        return _es_la_misma_hoja(record, padre)
    if record.continua_la_anterior:
        return True
    return _es_la_misma_hoja(record, padre)


def _pertenece_por_cedula(record: DiplomaRecord, padre: DiplomaRecord) -> bool:
    """Si esta cara es del mismo graduado que el documento que está abierto.

    Aquí la unidad documental es **la persona** y no la hoja, así que la esquina
    no pinta nada: lo que abre un documento es que aparezca una cédula distinta.

    Tres casos, y los tres siguen la norma de la casa de que sólo la evidencia
    positiva corta:

    1. **Esta cara no trae cédula creíble**: no aporta evidencia de nada, así que
       se queda con el documento abierto. Es lo mismo que hace la regla del
       folio ante una esquina dudosa, y por el mismo motivo: partir deja dos
       archivos de media hoja que nadie reconoce, mientras que unir de más deja
       una hoja señalada por su nombre en la cola de revisión.
    2. **Las dos traen cédula creíble**: mandan ellas. Iguales, se une; distintas,
       son dos personas y se abre.
    3. **Ésta trae cédula y el documento abierto no**: se abre. Podría ser la
       misma persona cuya primera cara no se dejó leer, pero unir aquí
       **escondería a un graduado identificado dentro de un documento sin
       nombre**, y eso no deja rastro: el archivo se llamaría por su orden y esa
       cédula no aparecería en ninguna parte. Abrir, en cambio, deja las dos
       caras visibles y cada una con su fila.
    """
    if not record.identity_creible:
        return True
    if not padre.identity_creible:
        return False
    return record.identity_number == padre.identity_number


def vueltas_por_la_tinta(records: Sequence[DiplomaRecord]) -> set[int]:
    """Caras que **la tinta de la esquina** declara vuelta de la anterior.

    Sirve para no pagar por leerlas: una vuelta no nombra ningún archivo -- el
    nombre sale de la cara que abre -- ni abre ninguna fila del inventario, así
    que leerla es pagar por un dato que nadie va a mirar. En un libro foliado
    hoja a hoja eso es **la mitad del libro**.

    La condición es estrecha a propósito: sólo cuenta la esquina que **se miró**
    y resultó limpia o dudosa. No vale preguntarle a `pertenece_al_anterior`,
    aunque sea la regla buena para repartir, porque en este momento aún no se ha
    leído nada: su rama de respaldo mira los identificadores del registro, y
    antes del OCR un libro escaneado no tiene ninguno en ninguna página. Usarla
    aquí diría que las 398 caras pertenecen a la primera, se leería sólo la
    página 1 y el libro entero saldría vacío.

    Dicho de otro modo: se ahorra la lectura sólo donde hay **evidencia física
    medida** de que esa cara no abre nada. Donde nadie pudo mirar la esquina se
    lee, que es lo que había y lo que no puede equivocarse.
    """
    return {
        record.page_number
        for indice, record in enumerate(records)
        if indice > 0
        and record.folio_mark in (MarcaDeFolio.AUSENTE, MarcaDeFolio.DUDOSA)
    }


#: Cuánta diferencia se le perdona a **una palabra** antes de llamarla otra.
#:
#: Un tercio de su longitud: una letra en un apellido de hasta cinco, dos en uno
#: de hasta ocho. Es la holgura del escáner sobre una palabra concreta --
#: "PADILLA" leído "PADILIA" --, no la de un nombre entero.
_TOLERANCIA_POR_PALABRA = 3

#: Cuántas palabras hacen falta para poder juzgar dos nombres comparando
#: palabras. Con una sola no hay nada que alinear, así que se comparan enteros.
_PALABRAS_PARA_COMPARAR = 2


def mismo_graduado(uno: str | None, otro: str | None) -> bool:
    """Si dos nombres leídos son, con la holgura del OCR, la misma persona.

    No compara cadenas: compara **personas leídas por un escáner**. Y no lo hace
    midiendo la distancia entre los nombres enteros, que es lo primero que se
    intentó y **no funciona**: "JUAN PEREZ GOMEZ" y "JUAN PEREZ LOPEZ" se
    separan por dos ediciones sobre dieciséis caracteres -- menos que muchas
    erratas de OCR -- y son dos graduados distintos. Cualquier tolerancia que
    perdone un apellido mal leído perdona también un apellido **distinto**, y
    entonces dos diplomas acaban en el mismo archivo.

    Lo que sí los separa es mirar **palabra por palabra**: el daño del escáner
    se reparte dentro de las palabras y no las sustituye por otras. De modo que
    dos nombres son la misma persona cuando **cada palabra del más corto
    encuentra la suya en el más largo**, con una holgura proporcional a esa
    palabra. Así "JUAN PEREZ" y "JUAN PEREZ GOMEZ" son el mismo graduado -- el
    segundo apellido no se leyó en una de las dos caras -- mientras que "JUAN
    PEREZ GOMEZ" y "JUAN PEREZ LOPEZ" no lo son, porque GOMEZ no tiene pareja.

    Conviene saber lo que esto **no** resuelve, para no confiarle más de lo que
    puede: un apellido que el OCR sustituya entero -- "PADILLA" devuelto
    "PUCELA" -- se lee aquí como otra persona, y no hay forma barata de
    distinguirlo de un hermano. Por eso este criterio nunca corta solo: hace
    falta además que la cédula sea otra, y son las dos juntas las que deciden.

    Un nombre que falta no es igual ni distinto: es una ausencia, y quien
    pregunta decide qué hace con ella. Aquí se contesta ``False`` -- no consta
    que sean el mismo -- y el llamador se encarga de que eso no baste para
    cortar por sí solo.
    """
    if not uno or not otro:
        return False
    a, b = _fold(uno), _fold(otro)
    if not a or not b:
        return False
    if a == b:
        return True

    cortas, largas = sorted((a.split(), b.split()), key=len)
    if len(cortas) < _PALABRAS_PARA_COMPARAR:
        # Un nombre de una sola palabra no se puede alinear con nada; se compara
        # entero y con la holgura de una palabra, que es lo que es.
        holgura = max(1, max(len(a), len(b)) // _TOLERANCIA_POR_PALABRA)
        return damerau_levenshtein(a, b, ceiling=holgura) <= holgura

    disponibles = list(largas)
    for palabra in cortas:
        pareja = _pareja_de(palabra, disponibles)
        if pareja is None:
            return False
        disponibles.remove(pareja)
    return True


def _pareja_de(palabra: str, candidatas: list[str]) -> str | None:
    """La candidata que puede ser esta misma palabra mal leída, si la hay.

    Se retira de la lista al emparejarla, para que un apellido repetido no
    empareje dos veces con la misma y dé por bueno un nombre que no lo es.
    """
    holgura = max(1, len(palabra) // _TOLERANCIA_POR_PALABRA)
    for candidata in candidatas:
        if damerau_levenshtein(palabra, candidata, ceiling=holgura) <= holgura:
            return candidata
    return None


def _pertenece_por_persona(record: DiplomaRecord, padre: DiplomaRecord) -> bool:
    """Si esta cara es del mismo graduado, exigiendo que dos señales lo digan.

    Corta **sólo cuando la cédula y el nombre son los dos otros**. Que una de
    las dos coincida basta para quedarse: si la cédula cambia pero el nombre es
    el mismo, lo que cambió fue el OCR y no la persona -- y al revés igual.

    Es la versión prudente del corte por cédula, y existe porque la cédula de
    estos libros está manuscrita y el OCR le come dígitos. Pedirle a dos
    lecturas independientes que coincidan antes de partir es la única defensa
    barata contra eso, y no cuesta ninguna petición más: el nombre se lee de la
    misma página y en la misma pasada que la cédula.

    Sin las dos señales de esta cara no hay nada que comparar, así que se une:
    la ausencia de un dato nunca es evidencia, que es la norma de la casa.
    """
    if not record.identity_creible or not record.name:
        return True
    if not padre.identity_creible or not padre.name:
        # Esta cara identifica a un graduado y el documento abierto no. Unir
        # aquí lo escondría dentro de un archivo sin nombre, y esa cédula no
        # aparecería en ninguna parte; abrir deja las dos caras visibles.
        return False
    otra_cedula = record.identity_number != padre.identity_number
    otro_nombre = not mismo_graduado(record.name, padre.name)
    return not (otra_cedula and otro_nombre)


def _pertenece_por_encabezado(record: DiplomaRecord, padre: DiplomaRecord) -> bool:
    """Si esta cara continúa el diploma anterior, mirando lo que hay impreso.

    Dos señales, y basta con una para abrir:

    1. **El membrete del formulario.** Si la cara arranca con "UNIVERSIDAD DE
       CARTAGENA" o con la cabecera del libro de registro, ahí empieza un
       formulario nuevo -- y en estos empastes un formulario es un diploma.
    2. **Otro graduando.** Si el nombre leído no es el del documento abierto, es
       otra persona, aunque el escáner se haya comido el membrete. Es la señal
       que salva las caras mal escaneadas, que es justo para lo que se pidió.

    Las dos son evidencia positiva y están **impresas**, que es lo que permite
    que este criterio no le pida nada al motor de pago.

    Una cara sin membrete y sin nombre propio no aporta ninguna de las dos, así
    que se queda con el documento abierto: es la norma de la casa, y aquí cubre
    el caso real de la hoja anexa -- una fotocopia de cédula, un acta suelta --
    que el archivo intercala entre dos registros.
    """
    if record.encabezado:
        return False
    otro_graduando = bool(
        record.name and padre.name and not mismo_graduado(record.name, padre.name)
    )
    return not otro_graduando


def _es_la_misma_hoja(record: DiplomaRecord, padre: DiplomaRecord) -> bool:
    """Si los dos registros son el mismo folio y la misma persona.

    La excepción sólo aplica cuando el folio vuelve a repetirse y además la
    cédula coincide. Si la cédula cambia, o si el folio cambia, no hay
    agrupación: son dos registros distintos y cada uno sale por su identidad.
    """
    actual_folio = (record.folio or "").strip()
    padre_folio = (padre.folio or "").strip()
    if not actual_folio or not padre_folio or actual_folio != padre_folio:
        return False
    actual_id = (record.identity_number or "").strip()
    padre_id = (padre.identity_number or "").strip()
    if not actual_id or not padre_id:
        return False
    return actual_id == padre_id

def merge(primary: DiplomaRecord, fallback: DiplomaRecord) -> DiplomaRecord:
    """Fill the gaps in ``primary`` from a second, more expensive reading.

    Only absent fields are taken. A value the cheap rung already read is never
    overwritten by the escalation, because two readings that disagree is a fact
    the operator has to see rather than a tie for the last writer to win.
    """
    def pick(name: str):
        return getattr(primary, name) or getattr(fallback, name)

    primary = _resolve_doubts(primary, fallback)
    merged = DiplomaRecord(
        page_number=primary.page_number,
        folio=pick("folio"),
        registered_folio=pick("registered_folio"),
        book=pick("book"),
        name=pick("name"),
        carrera=pick("carrera"),
        identity_kind=pick("identity_kind"),
        identity_number=pick("identity_number"),
        # De cualquiera de las dos lecturas que lo haya visto: el membrete
        # está impreso en el papel, y que una lectura no lo reconociera no
        # lo borra de la hoja.
        encabezado=primary.encabezado or fallback.encabezado,
        continuacion=primary.continuacion,
        degree=pick("degree"),
        graduation_date=pick("graduation_date"),
        annulled=primary.annulled or fallback.annulled,
        # No sale de ninguna de las dos lecturas de texto: la puso quien miró
        # la esquina antes de que ninguna se intentara. Se conserva tal cual,
        # porque una escalada a OCR no cambia lo que hay escrito en el papel.
        folio_mark=primary.folio_mark or fallback.folio_mark,
        # Tampoco sale de las lecturas de texto: lo leyó quien miró la esquina.
        folio_manuscrito=primary.folio_manuscrito or fallback.folio_manuscrito,
        warnings=[],
    )
    # The warnings are recomputed against the merged values: a gap the second
    # reading filled is no longer a gap, and a conflict it introduced is new.
    return extract_diploma_warnings(merged)


#: Con qué se reconoce un aviso que habla de unir esta cara a la anterior.
_HABLA_DE_UNIR = "se unió a la anterior"

#: Con qué empiezan los avisos que **informan sin mandar a revisar**.
#:
#: Un aviso de estos dice algo que pasó y que conviene saber, pero que no
#: deja la hoja mal: una cédula que no se sostuvo y no se usó, o una que dos
#: lecturas confirmaron contra una tercera. La regla del operador es que a
#: revisión vaya sólo un error de verdad, y estos no lo son.
AVISOS_INFORMATIVOS = (
    "la cédula leída no se sostiene",
    "la cédula leída a página entera",
    "la franja leyó una vez otra cédula",
)


def es_informativo(aviso: str) -> bool:
    """Si este aviso informa sin mandar la hoja a revisión."""
    return aviso.startswith(AVISOS_INFORMATIVOS)


def sin_avisos_de_costura(record: DiplomaRecord) -> DiplomaRecord:
    """El mismo registro sin los avisos que hablan de unir caras.

    Cortando cara a cara no se une nada, así que "la hoja se unió a la
    anterior" no describe ninguna decisión que se haya tomado: es un aviso de
    otro criterio, y mandaba a revisión hojas que salieron exactamente como
    tenían que salir. Medido sobre el libro 7: cuatro caras en la cola por una
    costura que no existe.
    """
    limpios = [aviso for aviso in record.warnings if _HABLA_DE_UNIR not in aviso]
    if len(limpios) == len(record.warnings):
        return record
    return DiplomaRecord(
        page_number=record.page_number,
        folio=record.folio,
        registered_folio=record.registered_folio,
        book=record.book,
        name=record.name,
        identity_kind=record.identity_kind,
        identity_number=record.identity_number,
        encabezado=record.encabezado,
        continuacion=record.continuacion,
        degree=record.degree,
        graduation_date=record.graduation_date,
        annulled=record.annulled,
        folio_mark=record.folio_mark,
        folio_manuscrito=record.folio_manuscrito,
        warnings=limpios,
    )


#: Cuántas veces tiene que repetirse un título en el libro para servir de
#: referencia a sus variantes rotas.
VECES_DE_UN_TITULO_DE_REFERENCIA = 3
#: Cuántas letras puede diferir una variante de su título de referencia, sin
#: contar los espacios: «OCUPACIQNAL», «OCUF ACIONAL» frente a «OCUPACIONAL».
ERRATAS_DE_UN_TITULO = 2
#: Qué parte de las caras con libro tiene que decir el mismo número para que
#: ése sea el del libro y llene las que no lo trajeron.
MAYORIA_DEL_LIBRO = 0.8


def con_lo_que_dice_el_libro(records: Sequence[DiplomaRecord]) -> list[DiplomaRecord]:
    """Los registros, con lo que el libro entero confirma y la cara suelta no.

    Se mira al final, con todas las caras leídas, porque lo que se corrige aquí
    sólo se sabe comparando unas con otras:

    - **El número de libro.** Un empaste es un libro: si la gran mayoría de sus
      caras dicen «libro No. 8», la que no lo dejó leer es del 8. Sólo se
      rellena lo que falta, nunca se cambia uno leído (en el libro 3858079,
      cinco caras sin libro dejaban su asiento en «868-N/A»).
    - **El título.** Los títulos de un libro se repiten: cuarenta
      «ESPECIALISTA EN SALUD OCUPACIONAL» y uno «… OCUPACIQNAL». Un título que
      aparece una sola vez y se parece letra por letra a uno frecuente es ese
      mismo título mal leído. Uno raro y distinto -- otra especialidad -- se
      queda como está.

    No se toca el nombre ni la cédula: dos graduados distintos pueden parecerse
    tanto como un nombre y su errata, y ahí el libro no sabe cuál es cuál.

    El asiento no se mira aquí: su progresión sólo vale cortando cara a cara
    (ver ``asientos_en_progresion``).
    """
    from collections import Counter
    from dataclasses import replace

    libros = Counter(r.book for r in records if r.book)
    del_libro = None
    if libros:
        libro, veces = libros.most_common(1)[0]
        if veces / sum(libros.values()) >= MAYORIA_DEL_LIBRO:
            del_libro = libro

    titulos = Counter(r.degree for r in records if r.degree)
    frecuentes = [t for t, n in titulos.items() if n >= VECES_DE_UN_TITULO_DE_REFERENCIA]

    def el_frecuente(titulo: str) -> str | None:
        if titulos[titulo] > 1 or titulo in frecuentes:
            return None
        pegado = titulo.replace(" ", "")
        cercanos = [
            f for f in frecuentes
            if damerau_levenshtein(pegado, f.replace(" ", "")) <= ERRATAS_DE_UN_TITULO
        ]
        return cercanos[0] if len(cercanos) == 1 else None

    salida: list[DiplomaRecord] = []
    for record in records:
        cambios: dict[str, str] = {}
        if not record.book and del_libro:
            cambios["book"] = del_libro
        if record.degree and (corregido := el_frecuente(record.degree)):
            cambios["degree"] = corregido
        salida.append(replace(record, **cambios) if cambios else record)
    return salida


#: Hasta cuántas caras a cada lado se busca una vecina que confirme un asiento.
VECINAS_DE_UN_ASIENTO = 6
#: Cuánto puede apartarse el desfase de un tramo del desfase típico del libro.
#: Más lejos es una lectura que perdió cifras en varias caras seguidas.
DESVIO_DE_UN_TRAMO = 50
#: Desde cuántas caras un tramo con su propio desfase es un salto real de la
#: numeración, y no ruido, aunque se aparte del resto.
TRAMO_LARGO = 10


def _asiento_numerico(record: DiplomaRecord) -> int | None:
    folio = record.trusted_folio
    return int(folio) if folio and folio.isdigit() else None


def _leido_dos_veces(record: DiplomaRecord) -> bool:
    """Si el encabezado y el pie dicen el mismo asiento.

    También cuando una lectura es el comienzo de la otra: el OCR se come
    dígitos y no los inventa, y «Folio 21 o» arriba con «210» al pie es el
    210 leído dos veces (UPD3858083 p207, una hoja fuera de su sitio que la
    recta no sostiene).
    """
    arriba, abajo = record.folio, record.registered_folio
    if not arriba or not abajo:
        return False
    corto, largo = sorted((arriba, abajo), key=len)
    return len(corto) >= 2 and largo.startswith(corto)


def asientos_en_progresion(records: Sequence[DiplomaRecord]) -> list[DiplomaRecord]:
    """Los asientos que la progresión del libro sostiene, y los que deduce.

    En un libro de registro el asiento -- «Registrado al folio No. N» -- sube
    de uno en uno por cara: la página 10 del libro 7 de 1982 es el asiento 10,
    la 11 el 11. Eso da dos cosas sin leer nada más:

    - **Validar.** Un asiento se cree si alguna cara cercana tiene el mismo
      desfase (asiento menos página): dos lecturas independientes que caen en la
      misma recta no son casualidad. El que no encaja con ninguna vecina se
      descarta: en los libros manuscritos la capa de texto devuelve «1», «7» o
      «03» donde va escrito a mano «1036» (UPD3858080, UPD3859768), y un asiento
      equivocado en el inventario es peor que un N/A.
    - **Deducir.** Entre dos asientos validados con el mismo desfase, cada cara
      sin asiento tiene el suyo por la cuenta exacta de páginas. Sólo entre dos
      anclas que coinciden, nunca hacia fuera de ellas: un salto -- un folio
      que falta, una hoja escaneada dos veces, un BIS -- cambia el desfase, y
      ahí no se deduce nada.

    Los asientos con letras («336BIS») no entran en la cuenta y se quedan como
    se leyeron.

    Sólo vale cuando cada cara es un diploma. Un libro foliado hoja a hoja
    sube uno cada dos caras, y ahí esta recta descartaría todos los folios.
    """
    from collections import Counter
    from dataclasses import replace

    numeros = [_asiento_numerico(r) for r in records]
    desfases = [
        n - r.page_number if n is not None else None for n, r in zip(numeros, records, strict=True)
    ]

    def confirmado(i: int) -> bool:
        # Impreso dos veces y las dos lecturas iguales -- «Folio 728» arriba y
        # «Registrado a folio No. 728» al pie, en los libros mecanografiados --
        # ya está confirmado: no necesita vecina. Así no se pierde el asiento
        # de una hoja escaneada dos veces o de un BIS, que rompen la recta.
        if _leido_dos_veces(records[i]):
            return True
        desde = max(0, i - VECINAS_DE_UN_ASIENTO)
        hasta = min(len(records), i + VECINAS_DE_UN_ASIENTO + 1)
        return any(desfases[j] == desfases[i] for j in range(desde, hasta) if j != i)

    validos = [d is not None and confirmado(i) for i, d in enumerate(desfases)]

    # Y un tramo coherente pero lejos de todo lo demás no es el libro: la capa
    # del libro 3859768 leyó «3, 4, 5…» donde va escrito «203, 204, 205…» en
    # seis caras seguidas, que se confirmaban entre sí. Se mide contra el
    # desfase típico del libro, salvo que el tramo sea largo.
    aceptados = sorted(d for d, ok in zip(desfases, validos, strict=True) if ok)
    if aceptados:
        tipico = aceptados[len(aceptados) // 2]
        cuantos = Counter(d for d, ok in zip(desfases, validos, strict=True) if ok)
        for i, d in enumerate(desfases):
            if (
                validos[i]
                and d is not None
                and abs(d - tipico) > DESVIO_DE_UN_TRAMO
                and cuantos[d] < TRAMO_LARGO
                and not _leido_dos_veces(records[i])
            ):
                validos[i] = False
    salida: list[DiplomaRecord] = []
    for i, record in enumerate(records):
        if desfases[i] is not None and not validos[i]:
            salida.append(
                replace(
                    record,
                    folio=None,
                    registered_folio=None,
                    folio_manuscrito=None,
                    warnings=[
                        *record.warnings,
                        f"el asiento leído ({numeros[i]}) no encaja con la progresión del libro: "
                        "se deja sin asiento",
                    ],
                )
            )
            continue
        if record.trusted_folio is None:
            antes = next((j for j in range(i - 1, -1, -1) if validos[j]), None)
            despues = next((j for j in range(i + 1, len(records)) if validos[j]), None)
            if antes is not None and despues is not None and desfases[antes] == desfases[despues]:
                deducido = record.page_number + desfases[antes]
                salida.append(replace(record, registered_folio=str(deducido)))
                continue
        salida.append(record)
    return salida


def extract_diploma_warnings(record: DiplomaRecord) -> DiplomaRecord:
    warnings: list[str] = []
    if record.folio and record.registered_folio and record.folio != record.registered_folio:
        warnings.append(
            f"el folio del encabezado ({record.folio}) no coincide con el del pie "
            f"({record.registered_folio})"
        )
    if record.name and _DAMAGE_IN_NAME.search(record.name):
        warnings.append(f"el nombre trae un carácter que no es una letra: {record.name}")
    # Una cédula que se leyó pero no se sostiene. Es un aviso y no un hueco: el
    # papel sí traía el dato y el OCR sí contestó algo, de modo que hay una hoja
    # concreta que alguien puede abrir y un número concreto que comprobar. No
    # nombra el archivo ni separa dos diplomas, y por eso hay que decirlo: sin
    # este aviso la única señal sería un archivo llamado por su folio en medio
    # de doscientos llamados por su cédula, que nadie mira.
    if record.identity_number and not record.identity_creible:
        warnings.append(
            f"la cédula leída no se sostiene y no se usó para nombrar ni para "
            f"separar: {record.identity_number}"
        )
    # La costura que la tinta no supo resolver. La hoja va con el registro
    # anterior, que es lo que manda ante la duda, y se dice por qué: es la única
    # forma de que alguien pueda comprobar esa unión sin repasar el libro entero.
    if record.folio_mark is MarcaDeFolio.DUDOSA:
        warnings.append(
            "no se pudo ver si la esquina lleva folio, así que la hoja se unió a la anterior"
        )
    # Y la costura que se unió sin ninguna evidencia: nadie pudo medir la
    # esquina y la hoja no trae nada con qué situarla. Es la política de la casa
    # -- ante la duda se une -- pero la política tiene dos mitades, y la segunda
    # es que la costura se declara. Sin este aviso, una hoja en blanco de un
    # escaneo sin píxeles se pegaba a la anterior y nadie llegaba a saberlo.
    if record.folio_mark in (None, MarcaDeFolio.SIN_MEDIR) and record.carries_no_identifier:
        warnings.append(
            "la hoja no trae ningún identificador y no se pudo medir la esquina: "
            "se unió a la anterior"
        )
    return DiplomaRecord(
        page_number=record.page_number,
        folio=record.folio,
        registered_folio=record.registered_folio,
        book=record.book,
        name=record.name,
        identity_kind=record.identity_kind,
        identity_number=record.identity_number,
        encabezado=record.encabezado,
        continuacion=record.continuacion,
        degree=record.degree,
        graduation_date=record.graduation_date,
        annulled=record.annulled,
        folio_mark=record.folio_mark,
        folio_manuscrito=record.folio_manuscrito,
        warnings=warnings,
    )
