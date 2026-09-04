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
    r"([A-Z]+(?:\s+Y\s+[A-Z]+)?)",
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
    resto = _numero_en_letras(bruto_anio)
    if dia is None or mes is None or resto is None or not (1 <= dia <= 31):
        return None
    return f"{dia:02d}/{mes:02d}/{1900 + resto}"


_IDENTITY = re.compile(
    r"[I¡]DENT[I¡]F[I¡]CAD[OA]\s+CON\s*([A-Z.]{1,6})\s*N[O°º.]*\s*([0-9][0-9.,]{3,14})", re.I
)
_ANNULLED = re.compile(r"\bANULAD[OA]\b", re.I)

#: A name in the small caps these forms use: two or more words. Digits are
#: allowed inside a word on purpose -- the scan renders ZABALETA as "2ABALETA"
#: and ELIZABETH as "ELI2ABETH", and a pattern that rejected those would not
#: skip the damage, it would silently pick the printed caption underneath and
#: file a graduate under "por intermedio de la Universidad de Cartagena".
_NAME = re.compile(r"^[A-ZÑ0-9!|¡][A-ZÑ0-9'.!|¡\-]*(?:\s+[A-ZÑ0-9!|¡][A-ZÑ0-9'.!|¡\-]*){1,7}$")
_MIN_NAME_LENGTH = 7

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
        return heading or foot

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
    def needs_review(self) -> bool:
        return bool(self.warnings) or not self.is_complete

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

        motivos = list(self.warnings)
        faltan = [
            etiqueta
            for valor, etiqueta in (
                (self.folio, "el folio"),
                (self.name, "el nombre del graduando"),
                (self.degree, "el título recibido"),
                (self.graduation_date, "la fecha de graduación"),
                (self.book, "el número de libro"),
            )
            if not valor
        ]
        # El nombre ausente ya lo dice uno de los avisos; no se cuenta dos veces.
        if not self.name:
            faltan = [etiqueta for etiqueta in faltan if etiqueta != "el nombre del graduando"]
        if faltan:
            motivos.append("no se pudo leer " + ", ".join(faltan))
        return "; ".join(motivos) if motivos else "la página quedó incompleta"

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
        found = _first_name_among(below)
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
    name = _graduate_name(lines)

    warnings: list[str] = []
    # The folio is printed twice. Where the two readings disagree, one of them
    # is damaged and neither can be trusted on its own.
    if folio and registered and folio != registered:
        warnings.append(f"el folio del encabezado ({folio}) no coincide con el del pie ({registered})")
    if name and _DAMAGE_IN_NAME.search(name):
        warnings.append(f"el nombre trae un carácter que no es una letra: {name}")
    if not name:
        warnings.append("no se pudo leer el nombre del graduando")

    return DiplomaRecord(
        page_number=page_number,
        folio=folio,
        registered_folio=registered,
        book=_first(_BOOK, flat),
        name=name,
        identity_kind=identity.group(1).strip(".") if identity else None,
        identity_number=identity.group(2).strip(" .,") if identity else None,
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
    if not record.name:
        warnings.append("no se pudo leer el nombre del graduando")
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
        warnings=warnings,
    )
