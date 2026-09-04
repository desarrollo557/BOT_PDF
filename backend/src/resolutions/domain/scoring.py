from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field

from .extraction import RawCandidate
from .resolution_code import ResolutionCode
from .text_distance import damerau_levenshtein

# A page's own resolution announces itself: near the top, set in capitals, on a
# short line, in the official form, with no citation verb in front of it. Every
# weight below encodes one of those five observations.
POSITION_WEIGHT = 0.35
CAPITALS_WEIGHT = 0.45
ISOLATION_WEIGHT = 0.20
OFFICIAL_FORM_WEIGHT = 0.30
CITATION_PENALTY = 0.55

# Sequential context is free evidence, but it only arbitrates between weak
# candidates. A confident header is never overruled by what came before.
NEIGHBOUR_BOOST = 0.30
CONFIDENT_FLOOR = 0.60
TIE_MARGIN = 0.12

_CITATION_MARKERS = (
    "VISTO",
    "CONSIDERANDO",
    "MODIFICA",
    "MODIFICATORIA",
    "DEROGA",
    "RATIFICA",
    "SUSTITUYE",
    "AMPLIA",
    "COMPLEMENTA",
    "MEDIANTE",
    "APROBADA POR",
    "APROBADO POR",
    "CONFORME",
)

_SHORT_LINE_WORDS = 6
_LONG_LINE_WORDS = 12

#: Lo único que puede seguir al número en el renglón de un encabezado: la
#: partícula de numeración y la fecha. Todo lo demás es una frase, y una frase
#: que menciona una resolución no es el encabezado de esa resolución.
_PALABRAS_DE_ENCABEZADO = frozenset(
    {
        "N", "NO", "NRO", "NUM", "NUMERO",
        "DE", "DEL",
        "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
        "JULIO", "AGOSTO", "SEPTIEMBRE", "SETIEMBRE", "OCTUBRE",
        "NOVIEMBRE", "DICIEMBRE",
    }
)

#: Puntuación que el escáner cuelga de los extremos de una palabra y que no
#: cambia cuál es esa palabra.
_EDGE_PUNCTUATION = ".,;:()[]\"'¡!¿?°º-–—_■"

#: Cuánto puede haberse equivocado el OCR en una de esas palabras. Una edición,
#: el mismo presupuesto con que se reconoce el ancla.
_MAX_WORD_DISTANCE = 1

#: Hasta dónde puede bajar un encabezado dentro de su página, en fracción de
#: altura. Medido, no elegido: de los 145 encabezados que abren una resolución
#: en los dos libros de la Universidad, el más bajo está en 0,171 y todos los
#: demás por encima. Las dos frases que se hacían pasar por encabezado están en
#: 0,421 y 0,490, así que el corte va por el medio de un hueco enorme.
HEADER_TOP_LIMIT = 0.30

#: Cómo numera rectoría: sólo dígitos, con sus ceros delante. Una resolución
#: escrita así es una unidad documental del libro aunque otra la cite, y por eso
#: no se la absorbe nunca. Las facultades numeran con el año detrás de un guion
#: -- "002-2023" -- y ésas sí son documentos de apoyo: la resolución con que un
#: decano pide algo a rectoría viene encuadernada detrás de la que le responde.
#:
#: Los propios documentos lo dicen. La 00080 llama a la suya "Resolución de
#: Rectoría No. 02234"; la 00087 dice "el decano de la FACULTAD... mediante
#: resolución N° 002-2023 solicitó a este despacho".
_HOUSE_NUMBER = re.compile(r"^\d{3,6}$")

#: Y dónde puede estar su centro horizontal. Los mismos 145 encabezados caen
#: entre 0,464 y 0,612 -- centrados, como se imprimen --; la frase del acta de
#: comité que abrió la resolución 00520 por error tiene su centro en 0,217,
#: pegada al margen izquierdo. La banda es ancha a propósito: rechazar un
#: encabezado de verdad cuesta una resolución entera, y ese error es peor que
#: dejar pasar una frase, que todavía tiene otras tres condiciones que superar.
HEADER_CENTRE = (0.30, 0.75)


@dataclass(frozen=True, slots=True)
class Selection:
    """The page's resolution, with enough context to audit or escalate it."""

    code: ResolutionCode
    confidence: float
    ambiguous: bool
    runner_up: ResolutionCode | None = None
    signals: dict[str, float] = field(default_factory=dict)


def _position(candidate: RawCandidate) -> float:
    span = max(candidate.total_lines - 1, 1)
    return max(0.0, 1.0 - candidate.line_index / span)


def _capitals(candidate: RawCandidate) -> float:
    letters = [ch for ch in candidate.line_text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(ch.isupper() for ch in letters) / len(letters)


def _isolation(candidate: RawCandidate) -> float:
    words = len(candidate.line_text.split())
    if words <= _SHORT_LINE_WORDS:
        return 1.0
    return max(0.0, (_LONG_LINE_WORDS - words) / (_LONG_LINE_WORDS - _SHORT_LINE_WORDS))


def _is_citation(candidate: RawCandidate) -> bool:
    return any(marker in candidate.context_before for marker in _CITATION_MARKERS)


def _official_form(candidate: RawCandidate) -> float:
    """Whether the candidate is written the way a real header writes it.

    "RESOLUCION No. 00086" is the house format, and it stays the house format
    when the page is typeset in title case. Recognising the structure is what
    keeps ``Resolución No. 00072 de 2023`` off the escalation path, where the
    capitals signal alone would have left it one hundredth above the floor.

    A citation is written in exactly the same form, so the signal is withheld
    there: the shape says "this is a resolution number", never "this page is it".
    """
    if not candidate.official_form or _is_citation(candidate):
        return 0.0
    return 1.0


def signals_for(candidate: RawCandidate) -> dict[str, float]:
    return {
        "position": _position(candidate),
        "capitals": _capitals(candidate),
        "isolation": _isolation(candidate),
        "official_form": _official_form(candidate),
        "citation": 1.0 if _is_citation(candidate) else 0.0,
    }


def score(candidate: RawCandidate) -> float:
    signals = signals_for(candidate)
    total = (
        POSITION_WEIGHT * signals["position"]
        + CAPITALS_WEIGHT * signals["capitals"]
        + ISOLATION_WEIGHT * signals["isolation"]
        + OFFICIAL_FORM_WEIGHT * signals["official_form"]
        - CITATION_PENALTY * signals["citation"]
    )
    return min(1.0, max(0.0, total))


def opens_a_resolution(candidate: RawCandidate) -> bool:
    """Si esta candidata puede abrir una resolución nueva (RF-01).

    Sólo un encabezado oficial abre una resolución: el ancla, el token de
    numeración y el número, tal como están escritos en los documentos reales
    (``RESOLUCIÓN No. 00072 de 2023``). Un número suelto en medio del texto no
    abre nada, por muy número que parezca.

    Antes esto sólo sumaba puntos, y no alcanzaba: en un expediente de 222
    páginas se abrían 34 resoluciones donde había unas 20, porque números
    citados en el cuerpo superaban el umbral por su cuenta. Puntuar no basta
    cuando el error parte un documento por la mitad; la forma oficial tiene que
    ser una condición.

    Un encabezado además **abre su renglón**. Lo que lo obligó fue el membrete
    de la Universidad, que dice "Acreditación en Alta Calidad Resolución No,
    1968 dei 12 de febrero de 2018, MEN." y va impreso en decenas de páginas:
    trae ancla, token de numeración y número, así que pasaba por encabezado y
    se llevó 68 páginas que eran de otras resoluciones. La diferencia no está
    en cómo se escribe el número sino en dónde está: en las 222 páginas del
    expediente, las 22 resoluciones reales empiezan el renglón con el ancla las
    22 veces, y el membrete no lo hace ni una -- aparece en la columna 29, 30 o
    49, detrás de otras palabras. Los tres formatos de la casa cumplen esto:
    ``RESOLUCION NO. 00086``, ``Resolución No. 00072 de 2023`` y
    ``RESOLUCIÓN No. 00083 de 2023`` empiezan por el ancla.

    Pero "abrir el renglón" no es "estar en la columna cero". Un escaneo mete
    delante del encabezado lo que había en el papel o lo que el rasterizador
    creyó ver: la resolución 00964 del libro 00960-00979 está impresa entre dos
    filetes y su capa de texto sale como
    ``____________ RESOLUCION NO. 00964 ______________________``. Con el ancla
    en la columna 13 no abría nada, así que sus ocho páginas se archivaron
    dentro de la 00963 y la resolución desapareció del entregable sin dejar
    rastro: ni un aviso, ni una página en revisión, ni un hueco visible en la
    numeración de los archivos.

    Lo que separa un caso del otro es si delante del ancla hay **palabras** o
    sólo tinta. El membrete lleva "Acreditación en Alta Calidad"; los filetes,
    los puntos sueltos y las marcas de escáner no llevan ninguna letra. Medido
    sobre las 545 páginas de los dos libros: la condición de columna cero
    bloqueaba 79 candidatas de forma oficial, y de esas 79 sólo tres no tenían
    ninguna letra delante. Una era la 00964 que faltaba.
    """
    return (
        candidate.official_form
        and _nothing_but_ink_before(candidate)
        and _nothing_but_a_date_after(candidate)
        and _where_a_header_goes(candidate)
        and not _is_citation(candidate)
    )


def _where_a_header_goes(candidate: RawCandidate) -> bool:
    """Si el renglón está donde va un encabezado: arriba y centrado.

    Es la condición que ninguna cantidad de análisis del texto podía dar, porque
    no está en el texto. El acta de comité del folio 245 del libro 00960-00979
    contiene la frase "La Dra. Rosaura Arrieta Flórez realiza la respectiva
    sustentación de la…", que parte a mitad de página y cuyo segundo renglón
    empieza por "Resolución No. 00520 de 202.". Ese renglón cumple todo lo demás
    -- abre su renglón, no lleva palabras detrás salvo la fecha, tiene la forma
    oficial -- y abrió un archivo de once páginas que no es ninguna resolución.

    Sobre el papel la diferencia salta a la vista: un encabezado va centrado y en
    la cabecera de la hoja, sea cual sea la fuente y el tamaño. Esa frase está a
    media altura y pegada al margen izquierdo.

    Sin geometría no se juzga. El OCR entrega texto sin coordenadas, y negarle a
    una página el encabezado por no saber dónde estaba sería perder resoluciones
    justo en las páginas que peor se leen.
    """
    if candidate.top is None or candidate.center_x is None:
        return True
    izquierda, derecha = HEADER_CENTRE
    return candidate.top <= HEADER_TOP_LIMIT and izquierda <= candidate.center_x <= derecha


def _nothing_but_ink_before(candidate: RawCandidate) -> bool:
    """Si delante del ancla, en su renglón, no hay ninguna palabra.

    Espacios, filetes, puntos y la basura que deja un escáner no son palabras y
    no impiden que el renglón sea el encabezado. Una letra sí: es lo que
    convierte "Resolución No. 1968" en la coletilla de un membrete.
    """
    return not any(character.isalpha() for character in candidate.context_before)


def _nothing_but_a_date_after(candidate: RawCandidate) -> bool:
    """Si detrás del número no sigue hablando nadie.

    Un encabezado ocupa su renglón entero y termina ahí, con la fecha como
    mucho: ``RESOLUCION NO. 00082 DE 2023``, ``RESOLUCIÓN No 03117 de 2022``.
    Una cita en el cuerpo empieza igual y sigue, porque la frase continúa:
    ``RESOLUCION NO.02809 DE NOVIEMBRE 23 DE 2022, SE EXCLUYE AL SENOR
    CHRISTIAN DAVID FERNANDEZ AVILA``.

    Sin esto no bastaba con dejar pasar los filetes: esa cita tampoco lleva
    palabras delante -- el escáner puso un ``■`` y nada más -- y se habría
    llevado doce páginas de la resolución 00979 para abrir una que no empieza
    ahí. Así que se admite lo que puede acompañar legítimamente a un número --
    el token de numeración, las preposiciones de la fecha y los meses -- y
    cualquier otra palabra cierra la puerta.

    Se admite además un error de lectura por palabra, con el mismo criterio que
    el ancla. La resolución 02500 de ese libro tiene la fecha impresa flojo y
    sale como ``RESOLUCION NO 02500 DO 2022``: exigir un "DE" exacto la habría
    perdido, y perder una resolución por una letra es justo lo que este módulo
    existe para evitar. Una palabra de verdad no se salva por un error: en la
    cita de arriba, "SE" queda a una edición de "DE" y pasa, pero "EXCLUYE" no
    se parece a nada de la lista y cierra la puerta igual.
    """
    for token in candidate.context_after.split():
        limpio = token.strip(_EDGE_PUNCTUATION)
        if not limpio or not any(character.isalpha() for character in limpio):
            continue
        if not _acompana_a_un_numero(limpio):
            return False
    return True


def _acompana_a_un_numero(word: str) -> bool:
    if word in _PALABRAS_DE_ENCABEZADO:
        return True
    return any(
        damerau_levenshtein(word, permitida, ceiling=_MAX_WORD_DISTANCE)
        <= _MAX_WORD_DISTANCE
        for permitida in _PALABRAS_DE_ENCABEZADO
    )


def select_best(
    candidates: list[RawCandidate],
    previous_code: ResolutionCode | None = None,
    announced_by_open_unit: Collection[str] = (),
) -> Selection | None:
    """Pick the resolution that owns the page, or ``None`` if there is none.

    ``announced_by_open_unit`` son los números que la resolución abierta nombró
    en su propio texto. Una resolución de rectoría dice en su CONSIDERANDO de
    qué se funda -- "Que el decano de la FACULTAD DE CIENCIAS SOCIALES Y
    EDUCACION mediante resolución N° 002-2023 del 24 del mes de enero del año
    2023 solicitó a este despacho autorización..." -- y lo que nombra ahí viene
    encuadernado detrás de ella, como anexo. Un encabezado que ya fue anunciado
    así no abre nada: pertenece al expediente que lo anunció.
    """
    if not candidates:
        return None

    # Stable sort: equal scores keep reading order, so the earliest wins ties.
    ranked = sorted(((score(c), c) for c in candidates), key=lambda pair: -pair[0])

    if previous_code is not None:
        # RF-01: la página continúa la resolución anterior salvo que traiga un
        # encabezado oficial propio. Seguir con el mismo código también vale:
        # eso no abre nada, sólo confirma dónde sigue estando.
        admitidas = [
            pair
            for pair in ranked
            if pair[1].code == previous_code
            or (opens_a_resolution(pair[1]) and not _is_an_annex(pair[1], announced_by_open_unit))
        ]
        if not admitidas:
            # ¿Se descartó porque el expediente abierto ya lo había anunciado?
            # Entonces no hay duda que revisar: es su anexo.
            anunciado = any(
                opens_a_resolution(candidate)
                and _is_an_annex(candidate, announced_by_open_unit)
                for _, candidate in ranked
            )
            return _continues(previous_code, ranked[0], announced=anunciado)
        ranked = admitidas
    else:
        # Nada que continuar todavía: el documento tiene que empezar en algún
        # lado, así que aquí la forma oficial ordena en vez de excluir.
        oficiales = [pair for pair in ranked if opens_a_resolution(pair[1])]
        if oficiales:
            ranked = oficiales

    top_score, top = ranked[0]

    if previous_code is not None and top_score < CONFIDENT_FLOOR:
        ranked = sorted(
            (
                (value + NEIGHBOUR_BOOST if candidate.code == previous_code else value, candidate)
                for value, candidate in ranked
            ),
            key=lambda pair: -pair[0],
        )
        top_score, top = ranked[0]
        top_score = min(1.0, top_score)

    runner_up_score = ranked[1][0] if len(ranked) > 1 else 0.0
    runner_up = ranked[1][1].code if len(ranked) > 1 else None

    # Una página que sólo repite el número de la resolución en la que está no es
    # más dudosa que una que no dice nada, y ésa hereda en silencio. En el libro
    # 00960-00979, las páginas 186, 274 y 317 mencionan de pasada "la Resolución
    # No. 00767 / 00696" dentro de una frase del cuerpo; la mención puntúa bajo,
    # como debe, pero coincide con la resolución abierta. Llamarlas conflicto era
    # mandar a revisar tres páginas que están exactamente donde tienen que estar.
    confirma_lo_abierto = previous_code is not None and top.code == previous_code
    ambiguous = (top_score < CONFIDENT_FLOOR and not confirma_lo_abierto) or (
        runner_up is not None and runner_up != top.code and top_score - runner_up_score < TIE_MARGIN
    )

    return Selection(
        code=top.code,
        confidence=round(top_score, 4),
        ambiguous=ambiguous,
        runner_up=runner_up,
        signals=signals_for(top),
    )


def _is_an_annex(candidate: RawCandidate, announced: Collection[str]) -> bool:
    """Si este encabezado es un documento de apoyo del expediente abierto.

    Dos condiciones, y las dos hacen falta. La resolución abierta tuvo que
    nombrarlo en su propio texto -- de ahí se sabe que viene encuadernado
    detrás -- y además tiene que estar numerado como numeran las facultades.

    Lo segundo no estaba y costó un archivo con dos resoluciones dentro. La
    00080 dice en su título "se modifica la Resolución de Rectoría No. 02234", y
    con eso bastaba para absorberla: el PDF de la 00080 salió con siete folios,
    cuatro suyos y tres de la 02234, que es una resolución de rectoría entera
    con su propio encabezado. Una resolución del mismo tipo que las del libro es
    una unidad documental por derecho propio, aunque otra la cite.

    Lo que sí se absorbe es lo que no pertenece a esa serie: la resolución con
    que un decano pide algo -- "002-2023" -- es el soporte de la que le
    responde, y su sitio es el expediente de ésta.
    """
    return candidate.code.value in announced and not _HOUSE_NUMBER.match(candidate.code.value)


def _continues(
    previous_code: ResolutionCode,
    suppressed: tuple[float, RawCandidate],
    *,
    announced: bool = False,
) -> Selection:
    """La página pertenece a la resolución anterior, y por qué.

    Se marca ambigua sólo cuando el rechazo es discutible: la candidata abría su
    renglón, no venía detrás de un verbo de cita, y aun así se descartó por no
    traer el token de numeración -- que es exactamente lo que pasa cuando el OCR
    se come el "No." de un encabezado verdadero. Eso tiene que verlo una persona.

    Un rechazo estructural no es discutible y no ensucia la cola. El membrete de
    la Universidad aparece en decenas de páginas y se rechaza por la misma razón
    todas las veces; marcarlo mandaba 39 páginas a revisión donde había 8 dudas
    reales, y una cola llena de ruido es una cola que nadie mira.

    Estar en el sitio equivocado es también un rechazo estructural, y faltaba
    contarlo. Cuando se empezó a exigirle al encabezado que fuera centrado y
    arriba, las frases que se hacían pasar por uno dejaron de abrir resoluciones
    -- que era el objetivo -- pero seguían llegando a la cola como si el rechazo
    fuera discutible: la del acta de comité del folio 245 y la del folio 195 del
    libro 00960-00979, las dos a media página y pegadas al margen. Se ve de un
    vistazo que no son encabezados; no hay nada que preguntarle a nadie.

    ``announced`` es el caso más firme de todos y por eso nunca es discutible: la
    resolución abierta nombró ese número en su propio CONSIDERANDO, así que la
    página no es un encabezado que se haya descartado a ojo, es el anexo que el
    expediente anunciaba. Marcarlo mandaba a revisión las 35 páginas de los doce
    anexos de un libro, todas correctamente archivadas.

    La confianza es la del enunciado que se está afirmando -- "esto continúa lo
    anterior" -- y por eso baja a medida que la candidata rechazada se parecía
    más a un encabezado. Salvo cuando el expediente lo anunció: entonces se
    afirma con todo.
    """
    rejected_score, rejected = suppressed
    if announced:
        return Selection(
            code=previous_code,
            confidence=1.0,
            ambiguous=False,
            runner_up=rejected.code,
            signals=signals_for(rejected),
        )
    debatable = (
        rejected_score >= CONFIDENT_FLOOR
        and rejected.anchor.start == 0
        and _where_a_header_goes(rejected)
        and not _is_citation(rejected)
    )
    return Selection(
        code=previous_code,
        confidence=round(max(0.0, 1.0 - rejected_score), 4),
        ambiguous=debatable,
        runner_up=rejected.code,
        signals=signals_for(rejected),
    )
