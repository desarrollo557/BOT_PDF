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
from collections.abc import Sequence
from dataclasses import dataclass, field

from .folio_manuscrito import MarcaDeFolio
from .text_distance import damerau_levenshtein

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
    import unicodedata

    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def has_caption(line: str, caption: str) -> bool:
    """Whether ``line`` carries this printed caption, OCR damage included."""
    budget = max(1, len(caption) // _CAPTION_TOLERANCE)
    words = _fold(line).split()
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
#: MEDICINA Y CIRUGIA" -- así que se captura entero y no sólo lo que sigue.
_DEGREE_DOCTOR = re.compile(r"(D[O0]CT[O0]R\s+EN\s+[^\n]+)", re.I)

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
    r"DE\s+([A-Z]+)\s+DE\s+M[I¡]L\s+N[O0]VEC[I¡]ENT[O0]S\s+"
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
_CEDULA_DEL_DIPLOMA = re.compile(
    r"C\.?\s?C\.?\s*N?[O°º.]*\s*:?\s*(\d{1,3}(?:[.,]\d{3}){1,3}|\d{5,11})",
    re.I,
)


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
    return any(has_caption(line, phrase) for phrase in _FURNITURE)

#: Anything inside a name that cannot be part of one. Its presence does not
#: repair the name -- it marks it unreliable, because "ELI2ABETH" could be
#: ELIZABETH and nothing on the page proves which letter the scanner lost.
_DAMAGE_IN_NAME = re.compile(r"[^A-ZÑÁÉÍÓÚÜ'. \-]", re.I)


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
    identity_kind: str | None = None
    identity_number: str | None = None
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
    def tiene_identidad(self) -> bool:
        """Si este registro se puede nombrar, archivar y volver a encontrar.

        Con la cédula del graduado o con su folio basta: son los dos datos por
        los que alguien busca un diploma. Lo demás -- el título, la fecha, el
        número de libro -- describe el documento, pero no lo identifica.
        """
        return bool(self.identity_number or self.trusted_folio)

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
        """
        return bool(self.warnings)

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

        return "; ".join(self.warnings)

    def as_dict(self) -> dict[str, object]:
        return {
            "page": self.page_number,
            "folio": self.folio,
            "registered_folio": self.registered_folio,
            "book": self.book,
            "name": self.name,
            "identity_kind": self.identity_kind,
            "identity_number": self.identity_number,
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
    name = _graduate_name(lines)

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
        identity_kind=identity.group(1).strip(".") if identity else None,
        identity_number=(
            cedula_normalizada(identity.group(2))
            if identity
            else cedula_normalizada(cedula.group(1))
            if cedula
            else None
        ),
        # El orden es el de las plantillas, de la más explícita a la menos: el
        # libro que rotula "Titulo recibido:" manda sobre el que sólo imprime
        # "DOCTOR EN", que es el antiguo y el que hay que leer al final porque
        # su fórmula también aparece dentro del cuerpo de los modernos.
        degree=(
            _first(_DEGREE, flat)
            or _first(_DEGREE_ALT, flat)
            or _first(_DEGREE_DOCTOR, flat)
        ),
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

    if name is primary.name and folio is primary.folio and registered is primary.registered_folio:
        return primary
    return DiplomaRecord(
        page_number=primary.page_number,
        folio=folio,
        registered_folio=registered,
        book=primary.book,
        name=name,
        identity_kind=primary.identity_kind,
        identity_number=primary.identity_number,
        degree=primary.degree,
        graduation_date=primary.graduation_date,
        annulled=primary.annulled,
        warnings=[],
    )




def pertenece_al_anterior(
    record: DiplomaRecord, padre: DiplomaRecord | None
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
    """
    if padre is None:
        return False
    if record.continua_la_anterior:
        return True
    return _es_la_misma_hoja(record, padre)


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
        identity_kind=pick("identity_kind"),
        identity_number=pick("identity_number"),
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


def extract_diploma_warnings(record: DiplomaRecord) -> DiplomaRecord:
    warnings: list[str] = []
    if record.folio and record.registered_folio and record.folio != record.registered_folio:
        warnings.append(
            f"el folio del encabezado ({record.folio}) no coincide con el del pie "
            f"({record.registered_folio})"
        )
    if record.name and _DAMAGE_IN_NAME.search(record.name):
        warnings.append(f"el nombre trae un carácter que no es una letra: {record.name}")
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
        degree=record.degree,
        graduation_date=record.graduation_date,
        annulled=record.annulled,
        folio_mark=record.folio_mark,
        folio_manuscrito=record.folio_manuscrito,
        warnings=warnings,
    )
