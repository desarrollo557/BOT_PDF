"""What little of a page decides where a document begins.

A box of scans is not one document. It is dozens, shuffled together, one to four
pages each, and the body text of a page argues for none of it: a claim letter and
the invoice it disputes read alike for paragraphs. What actually opens a document
is a letterhead, a city and a date, a serial; what closes one is a farewell
formula; and what settles the middle is the page's own claim to be "3 de 5".

Compressing a page to those few facts is not only cheaper to send to a model --
it is the difference between one request for a whole box and one request per
boundary. On a 125-page expediente the measured difference was 4.616 tokens
against 37.200, and one round trip against 124.

Nothing here imports anything: the layer check forbids it, and the rules have to
stay comprehensible in microseconds because a box is hundreds of pages.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .legibility import is_garbled
from .tipo_documental import identificar_rotulo

#: How far down the page a line may sit and still be a letterhead. Measured in
#: fractions so one rule survives A4, Letter and whatever the scanner produced.
LETTERHEAD_BAND = 0.22

#: How near the middle a line must be centred to read as a heading rather than a
#: margin note or a column of an address block.
LETTERHEAD_MARGIN = 0.30

#: A heading is a short line. Past this it is a paragraph that happens to start
#: near the top.
LETTERHEAD_MAX_CHARS = 90

#: Cuántas palabras necesita un encabezado para leerse como el nombre de un
#: documento y no como la marca del papel. Sale de la caja real: el logo llegó
#: siempre como un solo token -- "Grupo*epr9", "GrupO'epo)" -- y los nombres
#: siempre con varias palabras: "Acta de Irregularidad".
TITLE_MIN_WORDS = 2

#: Only the end of a page can close a document. "Cordialmente me dirijo a
#: ustedes" opens a claim; the same word at the foot of the page ends a reply.
CLOSING_TAIL_CHARS = 350

_PAGINATION = re.compile(
    r"p[aá]g(?:ina)?\.?\s*(\d{1,3})\s*(?:de|/)\s*(\d{1,3})",
    re.IGNORECASE,
)
#: El consecutivo lleva prefijo, y no siempre pegado. La notificacion se
#: imprime "Consecutivo No.A202170196624" -- una letra y sin espacio -- pero el
#: aviso de publicacion se imprime "Consecutivo No. PA 202170210656", con dos
#: letras y un espacio. Aceptar solo la primera forma costaba las siete
#: publicaciones de un expediente real: sus siete costuras quedaban sin decidir
#: por falta de un dato que estaba impreso en la hoja.
_SERIAL = re.compile(r"consecutivo\s*N[o0°]?\.?\s*:?\s*([A-Z]{0,3}\s?\d{8,})", re.IGNORECASE)
#: La coma es obligatoria. Sin ella el patrón reconocía como "ciudad y fecha"
#: cualquier palabra en mayúscula seguida de números: "DEL 10/12/2021",
#: "CARRERA 17 12-96", "Transformador 26/08/2021". Medido sobre dos
#: expedientes, dos de cada tres detecciones eran eso, y cada una convertía
#: una hoja de cuerpo en una que parecía abrir algo. Las de verdad la llevan
#: siempre: "Cartagena, 21-07-2021", "AGUSTIN CODAZZI, 08/07/2021".
_PLACE_AND_DATE = re.compile(
    r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ .]{3,28}),\s*(\d{1,2}[-/ ]\d{1,2}[-/ ]\d{2,4})"
)
_CASE_CODE = re.compile(r"\b(RE\d{10,})", re.IGNORECASE)
_CLOSING = re.compile(
    r"\b(cordialmente|atentamente|para constancia (?:se )?firma)",
    re.IGNORECASE,
)

#: Cuántos puntos pueden diferir dos hojas y seguir siendo del mismo lote de
#: escaneo. Un escáner de producción no entrega dos veces la misma medida exacta:
#: en la caja medida, hojas del mismo documento oscilaban entre 614x790 y 616x795,
#: y un legajo distinto entraba con 615x937. Ocho puntos separa una cosa de la
#: otra sin marcar el ruido del alimentador.
SHEET_TOLERANCE = 8

#: Por debajo de esto una hoja no ha dicho nada: es una fotografía, un sello, o
#: una página que el escáner no supo leer. No es evidencia de documento nuevo --
#: es la ausencia de toda evidencia -- y las reglas que la ven se abstienen en vez
#: de partir. Sale de la caja medida: las hojas de continuación más pobres tenían
#: 37 caracteres y la cabecera de apertura más escueta, 168.
LEGIBLE_MIN_CHARS = 120

#: Y por encima de esto la hoja está llena de prosa. Una página así que no trae
#: ninguna marca de abrir un documento es el medio de un escrito largo: en la
#: caja medida, las hojas de continuación de un oficio van de 1.672 a 3.639
#: caracteres y la mediana de la caja entera es 3.075. Una hoja de cuatro líneas
#: sin marcas, en cambio, puede ser cualquier cosa, y por eso no basta con que
#: se haya podido leer.
DENSE_MIN_CHARS = 1200

#: Cuántos renglones de arriba son "la cabecera" cuando se buscan en ella las
#: marcas de apertura. El equivalente en renglones de HEAD_CHARS, y por el
#: mismo motivo: más abajo empieza el cuerpo, y lo que se encuentra ahí son
#: menciones y no encabezados.
CABECERA_RENGLONES = 12

#: Hasta dónde llega "la cabecera" cuando se la mide en texto y no en geometría.
#: Es el equivalente en caracteres de LETTERHEAD_BAND, y existe porque una fuente
#: sin coordenadas -- OCR crudo, texto pegado -- se queda sin la banda geométrica
#: y aun así tiene que poder decir dónde empieza la hoja.
HEAD_CHARS = 300

#: Lo que una hoja imprime arriba cuando abre un documento. Cada patrón lleva una
#: palabra ancla, no sólo dígitos: medido sobre un expediente real, "NIT" y
#: "ciudad y fecha" reconocían números de factura como si fueran cabeceras y
#: partían cinco documentos por la mitad. Un patrón que el OCR puede confundir con
#: el cuerpo no sirve para decidir aperturas.
_OPENING_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("consecutivo", re.compile(r"consecutivo\s*N[o0°]?\.?\s*:?\s*[A-Z]{0,3}\s?\d{8,}", re.IGNORECASE)),
    ("destinatario", re.compile(r"\bse[nñ]or(?:a|es|\(a\))?\s*[:;.]", re.IGNORECASE)),
    ("asunto", re.compile(r"\b(?:asunto|referencia)\s*[:.]", re.IGNORECASE)),
    ("radicado", re.compile(r"\bradicaci[oó]n\s*[#N:]|\bradicado\s*(?:n[uú]mero|no\.?|:)", re.IGNORECASE)),
)

#: Los nombres que un papel se da a sí mismo viven en `tipo_documental`, que
#: es el catálogo del archivo del cliente. Aquí hubo una segunda lista de
#: trece escrita a mano, y se retiró: dos listas para la misma pregunta
#: divergen siempre, y la que se quedaba corta era justamente la que decidía
#: dónde se corta el papel.

#: Lo que un documento dice cuando anuncia que trae cosas pegadas detrás. No es
#: el nombre de un anexo: es la promesa de que vienen. Se busca en la cola de la
#: hoja porque ahí es donde un escrito enumera lo que adjunta.
#:
#: Y se pide la promesa entera, no una palabra suelta. "pruebas", "soportes" y
#: "adjunto" a secas son prosa jurídica corriente -- "valoradas las pruebas
#: obrantes en el expediente" cierra media resolución -- y leerlas como anuncio
#: desactivaba la regla de que un documento que agotó su propia paginación ha
#: terminado, pegándolo al siguiente.
_ANNOUNCES_ATTACHMENTS = re.compile(
    r"\banexos?\b|\bse adjuntan?\b|\bse anexan?\b"
    r"|\b(?:evidencia|registro|anexo|soporte)\s+fotogr[aá]fico?a?\b"
    r"|\bdocumentos?\s+adjuntos?\b|\bsoporte\s+documental\b",
    re.IGNORECASE,
)

#: Y lo que una hoja dice cuando ella misma es uno. El número que puede
#: precederlo es el folio -- se escribe "7 ANEXOS Y PRUEBAS", sin punto -- y
#: no exigirle puntuación es lo que hace que se reconozca en una caja foliada
#: a mano, que son todas.
_IS_ATTACHMENT = re.compile(
    r"^\s*(?:\d{1,3}\s*[.)-]?\s+)?(?:anexos?|anexo fotogr[aá]fico|evidencia fotogr[aá]fica"
    r"|fotograf[ií]as?(?:\s+y/o\s+videos?)?|soportes?\s+documental(?:es)?|pruebas)\b",
    re.IGNORECASE,
)

#: Cuánta cola se mira para ver si un documento anuncia sus anexos. La misma
#: ventana que ya usa la fórmula de despedida, y por la misma razón: sólo el
#: final de una hoja cierra algo.
ATTACHMENT_TAIL_CHARS = 400

#: Un impreso de cobro se reconoce por su estructura, no por la palabra. Un
#: recurso que reclama contra una factura escribe "factura" veinte veces en el
#: cuerpo; lo que ninguna de esas veces trae es un total a pagar en la cabecera.
_INVOICE_HEAD = re.compile(
    r"\bfactura\s*(?:no\.?|n[uú]mero|#)|\btotal a pagar\b|\bvalor a pagar\b"
    r"|\bcuenta de cobro\b|\bestado de cuenta\b",
    re.IGNORECASE,
)

#: Los identificadores con que se mide si dos hojas hablan del mismo asunto. El
#: código de caso queda fuera a propósito -- lo comparte el expediente entero --
#: y estos no: son del suscriptor y del cobro concreto.
#:
#: El importe entra porque es el que de verdad distingue. El NIC identifica al
#: suscriptor, y en un expediente de un solo cliente lo llevan casi todas las
#: hojas; una cantidad de dinero, en cambio, es de un cobro. Dos hojas que
#: comparten "$1.766.840" son el mismo recibo por delante y por detrás, y eso
#: es lo que hace falta saber para no partirlo.
#:
#: Y se le exige que venga anunciado como dinero: un signo de pesos delante, o
#: una de las palabras con que se presenta una cantidad. Pedirle sólo el
#: separador de miles reconocía como importe cualquier número que lo llevara,
#: y medido sobre un expediente real de 97 páginas eso era más de un tercio de
#: las detecciones: "la ley 142,143", "la ley 142 de 1,994", las cifras
#: sueltas de una factura escaneada y -- lo caro -- el número de cédula.
#:
#: La cédula es lo que obligó a arreglarlo. La de la persona del expediente
#: sale en la firma de su escrito, en el acta que la notifica y en la copia de
#: su documento, así que leída como "el mismo importe" soldaba tres documentos
#: distintos en uno. Es el mismo modo de fallo que el código de expediente:
#: identifica al sujeto y no al papel, y por eso no puede decidir nada.

#: Cómo se anuncia una cantidad de dinero en este papel.
_MARCA_DE_DINERO = r"(?:\$|\bvalor(?:es)?\b|\bsuma\b|\btotal\b|\bcuant[ií]a\b|\bpesos\b)"
#: Y cuánto puede mediar entre el anuncio y la cifra: "valor de $526.980" son
#: nueve caracteres, y más allá de veinte ya no se están nombrando.
SEPARACION_DE_LA_CIFRA = 20
_IDENTIFIERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("nic", re.compile(r"\bNIC\s*[:.]?\s*(\d{5,})", re.IGNORECASE)),
    ("factura", re.compile(r"\bfactura\s*(?:no\.?|n[uú]mero|#)\s*[:.]?\s*(\d{6,})", re.IGNORECASE)),
    (
        "importe",
        re.compile(
            _MARCA_DE_DINERO
            + r"[^\d]{0,"
            + str(SEPARACION_DE_LA_CIFRA)
            + r"}([1-9]\d{0,2}(?:[.,]\d{3})+)(?:[.,]\d{2})?(?![\d])",
            re.IGNORECASE,
        ),
    ),
)

#: El número de documento de una persona, con o sin puntos de millar. Se
#: reconoce por lo que lo anuncia -- "C.C.", "cédula", "NUMERO" en la carátula
#: de la propia cédula -- y no por su forma, porque su forma es la de
#: cualquier número de ocho cifras.
#:
#: No entra en `identifiers` y no decide continuidad por sí solo: es de la
#: persona del expediente y sale en casi todas sus hojas, igual que el código
#: de caso. Sirve para otra cosa -- comprobar que la cédula suelta que viene
#: detrás de un escrito es la de quien lo firmó -- y para eso hace falta
#: leerla, no compararla con todo.
_CEDULA = re.compile(
    r"(?:\bc\.?c\.?|\bc[eé]dula|\bn[uú]mero)"
    r"[^0-9]{0,12}(\d{1,3}(?:[.,]\d{3}){1,3}|\d{6,11})",
    re.IGNORECASE,
)

#: Cuánto de la hoja se mira buscando esa cédula. La carátula de una cédula la
#: lleva arriba; un escrito la lleva en la firma, al final. Así que se mira
#: entera: es un dato que se lee, no una marca de posición.

#: Los nombres propios que la hoja imprime en mayúscula. Es el respaldo de la
#: comprobación anterior para cuando el escáner se comió el número: la cédula
#: de "INIRIDA BEATRIZ ZARATE GARIZABAL" llega rota de mil maneras, pero rara
#: vez se rompen los cuatro apellidos a la vez.
_NOMBRE_EN_MAYUSCULAS = re.compile(r"\b([A-ZÁÉÍÓÚÑ]{4,})\b")

#: Cuántas de esas palabras tienen que coincidir para creer que las dos hojas
#: hablan de la misma persona. Dos, porque una sola -- un apellido corriente,
#: o "CESAR", que aquí es un departamento -- la comparten hojas de asuntos
#: distintos del mismo municipio.
NOMBRES_QUE_DEBEN_COINCIDIR = 2

#: El folio: un número corto y solo, escrito arriba del papel. No es la
#: paginación impresa -- ésa dice "3 de 5" y se basta sola -- sino la que pone a
#: mano quien arma el expediente, que sólo dice "3" y únicamente significa algo
#: en cadena con la hoja de al lado. Se busca como renglón entero: un número
#: suelto es folio, un número dentro de una frase es una cifra.
_FOLIO = re.compile(r"^\W{0,3}(\d{1,3})\W{0,3}$")

#: Hasta dónde se le busca. Más abajo que esto ya no es el folio de nadie: es
#: una celda de tabla o el primer renglón del cuerpo.
FOLIO_BAND = 0.12

#: Los mismos identificadores, cuando el escaneo separó el rótulo de su valor.
#: En un impreso de cobro, "Nic:" y "5826232" están en la misma línea impresa y
#: el extractor los devuelve como dos renglones distintos: buscarlos pegados en
#: el texto plano no los encuentra nunca. La geometría sí -- misma altura, el
#: número a la derecha -- y es la única forma de leer un formulario escaneado.
_LABEL_ONLY: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("nic", re.compile(r"\bnic\b\s*[:.]?\s*$", re.IGNORECASE)),
    ("factura", re.compile(r"\bfactura\s*(?:no\.?|n[uú]mero|#)\s*[:.]?\s*$", re.IGNORECASE)),
)

#: Un valor a la derecha del rótulo cuenta como suyo si está en la misma banda
#: horizontal. Medido sobre renglones reales: los de una misma línea impresa caen
#: dentro de ocho milésimas de la altura de la página, y el siguiente renglón ya
#: está a más de veinte.
LABEL_ROW_TOLERANCE = 0.008

#: Y tiene que ser un número de los que sirven para identificar algo, no una
#: cifra de dinero ni un año suelto.
_LABEL_VALUE = re.compile(r"^\d{5,}$")

#: Los ordinales con que un escrito numera sus párrafos. Un documento que va
#: PRIMERO, SEGUNDO, TERCERO se cuenta a sí mismo igual que una paginación, y esa
#: cuenta sobrevive en hojas que no traen ni membrete ni consecutivo.
_ORDINALS: dict[str, int] = {
    "primero": 1, "segundo": 2, "tercero": 3, "cuarto": 4, "quinto": 5,
    "sexto": 6, "septimo": 7, "octavo": 8, "noveno": 9, "decimo": 10,
    "undecimo": 11, "duodecimo": 12,
}
#: Y la misma numeración escrita en cifras: "1.", "2.", "3." al frente de cada
#: párrafo. Una carta de instrucciones enumera sus cláusulas así, y cuando su
#: segunda hoja arranca en el punto 5 eso es lo único que dice que es la segunda
#: hoja. Se pide el punto o el paréntesis y una letra detrás: un número suelto es
#: un folio y una cifra dentro de una frase es una cantidad.
_LIST_NUMERAL = re.compile(r"(?:^|(?<=[.\s]))(\d{1,2})\s*[.)]\s+(?=[A-Za-zÁÉÍÓÚÑáéíóúñ])")

_ORDINAL = re.compile(r"\b(" + "|".join(_ORDINALS) + r")\s*[:.]", re.IGNORECASE)

#: Only the head of a page can carry the place-and-date line. Searching the whole
#: page finds every date the document quotes and names the wrong one.
_PLACE_AND_DATE_HEAD_CHARS = 400


@dataclass(frozen=True, slots=True)
class Heading:
    """One line and where it sits, in 0..1 fractions of the page.

    The same shape as `LineBox` in the ports module, restated here because the
    domain may not import from the application layer. A source that cannot say
    where its lines are passes none of these and the rules fall back to text.
    """

    text: str
    center_x: float
    top: float


@dataclass(frozen=True, slots=True)
class Pagination:
    """A page's own claim about its place in a document: "3 de 5"."""

    index: int
    total: int

    @property
    def is_first(self) -> bool:
        return self.index == 1

    @property
    def is_last(self) -> bool:
        return self.index == self.total


@dataclass(frozen=True, slots=True)
class PageFingerprint:
    """One page, reduced to what argues about its boundaries."""

    page_number: int
    title: str
    letterhead: bool
    place_and_date: str | None
    #: The document's own serial. Unlike `case_code`, this changes per document.
    serial: str | None
    pagination: Pagination | None
    #: The claim number. It identifies the CASE, not the document -- every page
    #: of a 125-page expediente carries the same one. Recorded for the inventory
    #: and deliberately never used to decide continuity.
    case_code: str | None
    closes: bool
    #: The last characters of the page, to see whether a sentence was cut.
    tail: str

    # Lo que sigue son señales de segundo orden: nacieron para la caja de
    # correspondencia heterogénea, donde ni la paginación ni el consecutivo
    # alcanzan. Llevan valor por defecto porque una fuente que no las provee
    # sigue produciendo una huella válida -- las reglas que las usan simplemente
    # se abstienen -- y porque así una hoja construida a mano en una prueba no
    # tiene que enumerarlas para hablar de otra cosa.

    #: Lo que la hoja imprime arriba y sólo se imprime al abrir: un consecutivo,
    #: un destinatario, un asunto, un radicado. Vacío en una hoja de continuación.
    opening: tuple[str, ...] = ()
    #: El nombre que el papel se da a sí mismo, si se reconoce alguno.
    label: str | None = None
    #: Los ordinales con que numera sus párrafos, en orden de aparición.
    ordinals: tuple[int, ...] = ()
    #: Si la cabecera tiene estructura de impreso de cobro.
    invoice: bool = False
    #: Identificadores que sirven para medir si dos hojas hablan del mismo asunto.
    #: El código de expediente NO está entre ellos: lo comparten las 125 páginas
    #: de una caja, así que leerlo como contexto compartido las une todas.
    identifiers: frozenset[tuple[str, str]] = frozenset()
    #: El número escrito arriba del papel, si lo hay. Vale por su cadena con el
    #: vecino, nunca por sí solo: un "4" suelto no dice de qué documento es.
    folio: int | None = None
    #: El tamaño físico de la hoja, en puntos. Cambia cuando cambia el lote de
    #: escaneo, y un lote distinto es casi siempre un documento distinto: papel
    #: de otro tamaño, otra sesión de escáner, otra procedencia. Es la única
    #: señal de esta huella que no sale del texto, así que sobrevive a un OCR
    #: que no leyó nada.
    sheet: tuple[int, int] | None = None
    #: Si la hoja anuncia, al final, que detrás vienen anexos.
    announces_attachments: bool = False
    #: Si la hoja se presenta a sí misma como un anexo.
    is_attachment: bool = False
    #: Si la hoja va llena de prosa. No es lo mismo que `legible`: aquélla dice
    #: que se pudo leer, ésta que hay bastante que leer.
    dense: bool = False
    #: El documento de identidad que la hoja nombra, sin puntos. No decide
    #: continuidad -- es de la persona del expediente y sale en casi todas sus
    #: hojas -- pero permite comprobar que la cédula suelta que viene detrás de
    #: un escrito es la de quien lo firmó, en vez de suponerlo.
    cedula: str | None = None
    #: Los nombres propios en mayúscula, para la misma comprobación cuando el
    #: escáner se comió el número.
    nombres: frozenset[str] = frozenset()
    #: Si la hoja dejó texto suficiente y sano como para que se le crea algo.
    #: Falso en una fotografía, en un sello suelto y en una capa de texto mal
    #: decodificada. Por defecto verdadero: una huella construida a mano en una
    #: prueba habla de otra cosa y no tiene por qué declararlo.
    legible: bool = True

    def compact(self) -> dict[str, object]:
        """The smallest shape a model can still judge this page from.

        Keys are two letters and absent facts are omitted rather than sent as
        null, because every field is paid for once per page: on a 125-page box
        the full text is ~68.700 tokens and this is ~4.600.

        `case_code` is deliberately left out. It settles nothing -- every page of
        an expediente carries the same one -- and including it only invites the
        model to read it as continuity, which welds the box into one document.
        """
        compact: dict[str, object] = {"p": self.page_number, "t": self.title}
        if self.letterhead:
            compact["mb"] = 1
        if self.place_and_date:
            compact["cf"] = self.place_and_date
        if self.serial:
            compact["cs"] = self.serial
        if self.pagination:
            compact["pg"] = f"{self.pagination.index}/{self.pagination.total}"
        if self.closes:
            compact["fin"] = 1
        if self.tail:
            compact["z"] = self.tail
        return compact


#: Cuántas hojas tienen que coincidir para que un NIC sea el de la caja. Dos,
#: porque el ruido del escáner produce números sueltos -- en un expediente real
#: el NIC bueno salía en 27 hojas y la basura en una -- y con una sola aparición
#: no hay forma de distinguir uno del otro.
NIC_MIN_HOJAS = 2


def nic_de_la_caja(fingerprints: Sequence[PageFingerprint]) -> str | None:
    """El número de cuenta que identifica al suscriptor de un expediente entero.

    Es de la caja y no de ningún documento suyo, que es justamente lo que lo
    hace inútil para decidir dónde se corta y útil para nombrar la carpeta en
    que se entrega: todas las hojas hablan del mismo cliente.

    Gana el que más hojas comparten. Medido sobre dos expedientes reales: el
    bueno aparecía en 27 y 35 hojas, y el ruido del OCR -- un dígito de más,
    una lectura rota -- en una sola cada vez.
    """
    cuenta: dict[str, int] = {}
    for huella in fingerprints:
        for clase, valor in huella.identifiers:
            if clase == "nic":
                cuenta[valor] = cuenta.get(valor, 0) + 1
    if not cuenta:
        return None
    valor, hojas = max(cuenta.items(), key=lambda par: (par[1], par[0]))
    return valor if hojas >= NIC_MIN_HOJAS else None


def read_pagination(text: str) -> Pagination | None:
    """The "página X de Y" a page prints on itself, when it is believable.

    OCR damage is why this can refuse: page 9 of a real expediente prints
    "Página 1 de o" because the six came back as a letter. Returning ``1 de 0``
    would be worse than returning nothing -- a chain with a zero total links
    documents that do not exist -- so an impossible reading is no reading.
    """
    match = _PAGINATION.search(text)
    if not match:
        return None
    index, total = int(match.group(1)), int(match.group(2))
    if total < 1 or index < 1 or index > total:
        return None
    return Pagination(index=index, total=total)


def _has_letterhead(headings: list[Heading]) -> bool:
    return any(
        heading.top <= LETTERHEAD_BAND
        and LETTERHEAD_MARGIN < heading.center_x < (1.0 - LETTERHEAD_MARGIN)
        and 0 < len(heading.text.strip()) <= LETTERHEAD_MAX_CHARS
        for heading in headings
    )


def _title(text: str, headings: list[Heading]) -> str:
    """What the page calls itself -- not the brand printed on every sheet.

    On letterheaded paper the topmost line is the company logo, and a scan hands
    it over mangled: measured on the 125-page expediente the same logo arrived as
    'Grupo*epr9', 'Grupo-eprp', 'GrupO\'epo)', never twice the same. It was the
    title of 111 of those 125 pages -- and `title` is the `t` of the fingerprint,
    the only topical signal the model ever receives. Asking a model about thematic
    continuity while feeding it a garbled logo is asking it to guess.

    The discriminator comes from the data rather than from taste: every logo
    observed is a single token and every document name is several words. So a
    multi-word heading wins. A single-token heading is still returned when it is
    all the page offers, because there are documents called "NOTIFICACION".
    """
    band = [" ".join(heading.text.split()) for heading in headings if heading.top <= LETTERHEAD_BAND]
    usable = [line for line in band if len(line) > 8]

    for line in usable:
        if len(line.split()) >= TITLE_MIN_WORDS:
            return line[:70]
    if usable:
        return usable[0][:70]
    return " ".join(text.split())[:70]


def _strip_accents(text: str) -> str:
    """Sin tildes ni eñes, para comparar rótulos que el OCR devuelve de cualquier forma."""
    for accented, plain in zip("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN", strict=True):
        text = text.replace(accented, plain)
    return text


def _opening_signals(head: str, lineas: list[str] | None = None) -> tuple[str, ...]:
    """Las marcas de apertura impresas en la cabecera, si las hay.

    Al principio de un renglón, no en cualquier sitio. Una cabecera se imprime
    en su propia línea -- "Señor(a) INIRIDA...", "ASUNTO: Reclamación No...",
    "Consecutivo No.202270030080" -- y buscarla en el texto corrido reconoce
    también la fórmula de cortesía que abre un párrafo a media página.

    Costó un falso corte medido: la sexta hoja de un derecho de petición de
    ocho empieza diciendo "Respetados señores: Representante Legal o quien haga
    sus veces de la empresa...", y esas dos palabras partían el escrito por la
    mitad. La cabecera de verdad, en la primera hoja del mismo documento, dice
    "Señores:" y nada más en su renglón.

    Una fuente sin saltos de línea -- OCR crudo, texto pegado -- se queda sin
    esa distinción y se le busca en el texto plano, como antes: perder la señal
    entera sería peor que aceptarla de más.
    """
    renglones = [renglon.strip() for renglon in (lineas or []) if renglon.strip()]
    if not renglones:
        return tuple(name for name, pattern in _OPENING_SIGNALS if pattern.search(head))
    return tuple(
        name
        for name, pattern in _OPENING_SIGNALS
        if any(pattern.match(renglon) for renglon in renglones)
    )


def _document_label(lineas: list[str]) -> str | None:
    """El rótulo que la hoja se da a sí misma, si se reconoce alguno.

    Se pregunta al catálogo de tipos documentales del archivo, que es el mismo
    que nombra los archivos de salida. Antes había aquí una segunda lista de
    trece rótulos escrita a mano, y esa duplicación era un error de diseño con
    consecuencias medibles: el catálogo conoce "NOTIFICACION PERSONAL" y esta
    lista no, así que en un expediente real la hoja que la anuncia -- con ese
    título impreso arriba y nada más -- no abría documento, y el acta de
    notificación quedaba pegada al derecho de petición de las ocho hojas
    anteriores.

    Dos listas de nombres para la misma pregunta divergen siempre, y la que se
    queda corta es la que decide dónde se corta el papel. Ahora hay una.

    Se le pasan los renglones y no el texto corrido, y se le exige a la frase
    que ocupe uno para ella sola. Un título se imprime así; una mención, no. La
    resolución que en su cuarto punto dice "4. Constancia de Visita asociada al
    Acta de Revisión con Orden de Servicio..." nombra un tipo del catálogo en
    mitad de una línea de noventa y cinco caracteres, y sin esa exigencia se
    partía en dos por una frase de su propio cuerpo.
    """
    hallazgo = identificar_rotulo(lineas)
    return hallazgo.nombre.lower() if hallazgo is not None else None


def _cedula(flat: str) -> str | None:
    """El número de documento que la hoja nombra, sin puntos ni comas.

    Sin ellos porque el mismo número se imprime de las dos formas y hay que
    poder compararlos: la carátula de la cédula dice "42.491.816" y el acta que
    la persona firmó dice "CC: 42.491.816", pero otra hoja del mismo expediente
    escribe "42491816" y son el mismo documento.
    """
    hallazgo = _CEDULA.search(flat)
    if hallazgo is None:
        return None
    return hallazgo.group(1).replace(".", "").replace(",", "")


def _ordinals(text: str) -> tuple[int, ...]:
    """La numeración con que el escrito ordena sus párrafos.

    En palabras o en cifras, y **en el orden en que salen en la hoja**, que es lo
    que la regla necesita: le importa dónde arranca la hoja siguiente respecto de
    dónde acabó la anterior, no cuál es el mayor de todos.

    Un contrato lleva dos numeraciones a la vez -- los considerandos en cifras y
    las cláusulas en ordinales -- y la hoja que abre con "4." acaba nombrando
    "PRIMERO, SEGUNDO, TERCERO". Guardarlas por familias y no por posición
    escondía justamente lo que había que ver: que esa hoja empieza en el cuatro y
    termina en el tres.
    """
    plain = _strip_accents(text)
    hallazgos = [
        (m.start(), _ORDINALS[m.group(1).lower()]) for m in _ORDINAL.finditer(plain)
    ] + [(m.start(), int(m.group(1))) for m in _LIST_NUMERAL.finditer(plain)]
    hallazgos.sort()
    return tuple(valor for _, valor in hallazgos)


def _identifiers(text: str, headings: list[Heading]) -> frozenset[tuple[str, str]]:
    """Los identificadores del asunto concreto, no los del expediente.

    Se leen dos veces: pegados al rótulo en el texto corrido, y por geometría
    cuando el escaneo los separó. Lo segundo no es un lujo -- en la caja medida
    había una hoja cuyo NIC sólo existía así, con "Nic:" en un renglón y el
    número en otro, a la misma altura y unos centímetros a la derecha.
    """
    found: set[tuple[str, str]] = set()
    for kind, pattern in _IDENTIFIERS:
        found.update((kind, value) for value in pattern.findall(text))
    found.update(_labelled_values(headings))
    return frozenset(found)


def _folio(headings: list[Heading]) -> int | None:
    """El número suelto escrito en lo alto de la hoja, si hay uno.

    Se queda con el de más arriba porque es donde se folia; a igual altura, con
    el de más a la izquierda. No se comprueba aquí que tenga sentido -- una celda
    de tabla en la banda alta también es un número solo -- porque la regla que lo
    usa sólo lo cree cuando encadena con el de la hoja anterior, y una cifra
    suelta no encadena con nada.
    """
    candidatos = [
        (heading.top, heading.center_x, int(match.group(1)))
        for heading in headings
        if heading.top < FOLIO_BAND
        and (match := _FOLIO.match(heading.text.strip()))
    ]
    return min(candidatos)[2] if candidatos else None


def _labelled_values(headings: list[Heading]) -> set[tuple[str, str]]:
    """Rótulo y valor que el extractor devolvió como renglones separados."""
    found: set[tuple[str, str]] = set()
    for heading in headings:
        kind = next((k for k, rx in _LABEL_ONLY if rx.search(heading.text)), None)
        if kind is None:
            continue
        candidatos = [
            other
            for other in headings
            if abs(other.top - heading.top) < LABEL_ROW_TOLERANCE
            and other.center_x > heading.center_x
            and _LABEL_VALUE.match(other.text.strip())
        ]
        # El más cercano por la derecha: en un formulario, el valor de un rótulo
        # es el que le sigue, no el de la columna del final de la fila.
        if candidatos:
            found.add((kind, min(candidatos, key=lambda c: c.center_x).text.strip()))
    return found


def _clean_serial(raw: str) -> str:
    """El consecutivo sin el espacio que el impreso mete tras el prefijo.

    La regla de continuidad compara consecutivos por igualdad, asi que
    "PA 202170210656" y "PA202170210656" tienen que ser el mismo dato. Las
    mayusculas se fuerzan por lo mismo que en el codigo de caso: el OCR devuelve
    el prefijo en cualquier caja.
    """
    return "".join(raw.split()).upper()


def fingerprint_page(
    page_number: int,
    text: str,
    headings: list[Heading] | None = None,
    sheet: tuple[int, int] | None = None,
) -> PageFingerprint:
    """Reduce one page to the facts that decide its boundaries."""
    headings = headings or []
    flat = " ".join(text.split())
    lineas = text.splitlines()

    place_and_date = None
    match = _PLACE_AND_DATE.search(flat[:_PLACE_AND_DATE_HEAD_CHARS])
    if match:
        place_and_date = f"{match.group(1).strip()[:22]} {match.group(2)}"

    serial_match = _SERIAL.search(flat)
    case_match = _CASE_CODE.search(flat)

    return PageFingerprint(
        page_number=page_number,
        title=_title(text, headings),
        letterhead=_has_letterhead(headings),
        place_and_date=place_and_date,
        serial=_clean_serial(serial_match.group(1)) if serial_match else None,
        pagination=read_pagination(flat),
        case_code=case_match.group(1).upper() if case_match else None,
        opening=_opening_signals(flat[:HEAD_CHARS], lineas[:CABECERA_RENGLONES]),
        label=_document_label(lineas),
        ordinals=_ordinals(flat),
        invoice=bool(_INVOICE_HEAD.search(flat[:HEAD_CHARS])),
        identifiers=_identifiers(flat, headings),
        folio=_folio(headings),
        sheet=sheet,
        announces_attachments=bool(_ANNOUNCES_ATTACHMENTS.search(flat[-ATTACHMENT_TAIL_CHARS:])),
        is_attachment=bool(_IS_ATTACHMENT.match(flat[:HEAD_CHARS].lstrip())),
        cedula=_cedula(flat),
        nombres=frozenset(_NOMBRE_EN_MAYUSCULAS.findall(flat)),
        dense=len(flat) >= DENSE_MIN_CHARS and not is_garbled(flat),
        legible=len(flat) >= LEGIBLE_MIN_CHARS and not is_garbled(flat),
        closes=bool(_CLOSING.search(flat[-CLOSING_TAIL_CHARS:])),
        tail=flat[-45:],
    )
