"""Cutting a shuffled box into the documents it is made of.

The shipped splitter groups pages by a code every page carries. A box of utility
correspondence has no such code: an invoice, the claim disputing it and the reply
to the claim are three documents that share every identifier the archive knows.
So this decides by continuity instead -- page by page, does the next sheet carry
on or start something new.

Every boundary is decided by evidence and says which. What the evidence cannot
settle comes back as UNDECIDED rather than as a guess, because those are exactly
the boundaries worth paying a model to judge, and a guess dressed as a decision
is indistinguishable from an answer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .errors import IntegrityError
from .fingerprint import (
    NOMBRES_QUE_DEBEN_COINCIDIR,
    SHEET_TOLERANCE,
    PageFingerprint,
)


class Verdict(StrEnum):
    """What happens between one page and the next."""

    #: The right-hand page opens a new document.
    STARTS = "starts"
    #: The right-hand page carries on the left-hand one.
    CONTINUES = "continues"
    #: La hoja pertenece al documento abierto, pero como anexo y no como cuerpo.
    #: Se agrupa igual que una continuación; lo que cambia es que la relación
    #: queda registrada, para que el inventario pueda decir "el acta, con sus
    #: cuatro fotografías" en vez de "cinco documentos".
    ATTACHMENT = "attachment"
    #: Nothing on either page settles it. Escalate.
    UNDECIDED = "undecided"


@dataclass(frozen=True, slots=True)
class Boundary:
    """The seam between two adjacent pages, and why it was called that way."""

    left: int
    right: int
    verdict: Verdict
    reason: str
    #: False once a model has overruled or filled in the deterministic verdict,
    #: so a run's cost and its confidence stay measurable after the fact.
    deterministic: bool = True


@dataclass(slots=True)
class Segment:
    """Contiguous pages that form one document."""

    page_numbers: list[int]
    reason: str = ""
    #: Las páginas de este documento que llegaron como anexo y no como cuerpo.
    #: Van dentro de `page_numbers` -- un anexo no es un documento aparte -- y
    #: aquí sólo se anota cuáles son, porque perder esa relación es perder la
    #: única respuesta a "¿de qué acta son estas fotos?".
    attachment_pages: list[int] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.page_numbers)


@dataclass(slots=True)
class SegmentationResult:
    segments: list[Segment] = field(default_factory=list)
    boundaries: list[Boundary] = field(default_factory=list)
    #: Las huellas de las que salió este reparto. Se conservan porque hay
    #: preguntas que son de la caja entera y no de ninguno de sus documentos
    #: -- de qué suscriptor es -- y volver a leer el PDF para contestarlas
    #: sería leerlo dos veces.
    fingerprints: list[PageFingerprint] = field(default_factory=list)

    @property
    def attachments(self) -> list[Boundary]:
        """Las costuras en que una hoja entró como anexo de la anterior."""
        return [b for b in self.boundaries if b.verdict is Verdict.ATTACHMENT]

    @property
    def undecided(self) -> list[Boundary]:
        """The seams a model still has to judge."""
        return [b for b in self.boundaries if b.verdict is Verdict.UNDECIDED]

    def verify_integrity(self, page_numbers: Sequence[int]) -> None:
        """Fail loudly unless every page landed in exactly one segment.

        Called before a single output file is written. A split that silently
        drops or duplicates a page looks identical to a correct one at a glance,
        which is why it has to be impossible rather than unlikely.
        """
        seen: set[int] = set()
        duplicated: set[int] = set()
        for segment in self.segments:
            for page_number in segment.page_numbers:
                if page_number in seen:
                    duplicated.add(page_number)
                seen.add(page_number)

        expected = set(page_numbers)
        missing = expected - seen
        stray = seen - expected
        if duplicated or missing or stray:
            raise IntegrityError(
                "la segmentación no cubre el documento: "
                f"repetidas={sorted(duplicated)} "
                f"faltantes={sorted(missing)} "
                f"ajenas={sorted(stray)}"
            )


def _decide(
    left: PageFingerprint,
    right: PageFingerprint,
    ubiquitous: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[Verdict, str]:
    left_pages, right_pages = left.pagination, right.pagination

    # The strongest evidence there is: the paper counting itself. A sheet that
    # says "1 de 5" is a first page whatever else is printed on it.
    if right_pages and right_pages.is_first:
        return Verdict.STARTS, "la siguiente se declara página 1"

    if left_pages and right_pages and left_pages.total == right_pages.total:
        if right_pages.index == left_pages.index + 1:
            return Verdict.CONTINUES, f"cadena {left_pages.index}->{right_pages.index}"
        # Un salto hacia adelante dentro de la misma cuenta es una hoja que el
        # OCR no supo leer, no un documento nuevo: "1 de 5, 2 de 5, 4 de 5" sigue
        # siendo un documento de cinco hojas.
        if right_pages.index > left_pages.index:
            return (
                Verdict.CONTINUES,
                f"la cuenta salta de {left_pages.index} a {right_pages.index} de {right_pages.total}",
            )

    # El reverso de la primera regla, y hacía falta: una hoja que se declara
    # "2 de 4" no abre nada, diga lo que diga su encabezado. Sin esto, las hojas
    # intermedias de un acta -- que repiten el rótulo "Acta de Irregularidad" en
    # cada página -- se leían como cuatro actas distintas.
    #
    # Cubre también los totales que no coinciden y las cuentas que retroceden.
    # En la caja medida ese desacuerdo lo había puesto el escáner -- el mismo que
    # convierte "1 de 6" en "1 de o" -- y cortar ahí era el único falso corte que
    # quedaba contra la propia numeración del papel.
    if right_pages:
        return (
            Verdict.CONTINUES,
            f"la hoja se declara página {right_pages.index} de {right_pages.total}",
        )

    # A completed count ends its document even when the next page says nothing.
    # Salvo que lo que cerró anunciara sus anexos. Una cuenta interna numera el
    # cuerpo de un documento, no lo que viene pegado detrás: un acta que dice
    # "2 de 2" y enumera sus fotografías no ha terminado, ha dejado de tener
    # cuerpo. Cortar ahí convierte un acta en cinco documentos, que es justo el
    # caso que la regla de anexos existe para evitar.
    trae_anexos = left.announces_attachments and not right.opening and not right.label
    if left_pages and left_pages.is_last and not trae_anexos:
        return Verdict.STARTS, f"la anterior cerró en {left_pages.total} de {left_pages.total}"

    # The serial is per document, unlike the case code.
    if left.serial and right.serial:
        if left.serial == right.serial:
            return Verdict.CONTINUES, "mismo consecutivo"
        return Verdict.STARTS, "cambia el consecutivo"

    # Un escrito que numera sus párrafos PRIMERO, SEGUNDO, TERCERO se cuenta a sí
    # mismo igual que una paginación, y esa cuenta sobrevive donde no hay membrete
    # ni consecutivo: son once costuras de un expediente real que ninguna otra
    # regla alcanzaba. Va antes que las de apertura porque una hoja de
    # continuación puede traer, en su primera línea, algo que parece una cabecera.
    # Donde arranca la hoja siguiente, contra donde acabó la anterior. Por
    # posición y no por el mayor de cada una: una hoja de contrato abre en el
    # considerando cuarto y termina nombrando la cláusula tercera, así que su
    # máximo no dice nada y su primero lo dice todo.
    if left.ordinals and right.ordinals and right.ordinals[0] > left.ordinals[-1]:
        return (
            Verdict.CONTINUES,
            f"la numeración sigue en {right.ordinals[0]} tras el {left.ordinals[-1]}",
        )

    # Prioridad 3: los identificadores del asunto. Dos hojas que llevan la misma
    # clase de identificador y no comparten ni uno hablan de asuntos distintos.
    # Es la regla que separa tres facturas seguidas cuyo encabezado el escáner
    # dejó ilegible: lo único intacto en ellas era el NIC, y era distinto en cada
    # una. Exige que ambas hojas traigan la misma clase -- si una no la trae, su
    # silencio no contradice nada.
    compartidos = (left.identifiers & right.identifiers) - ubiquitous
    if compartidos:
        cuales = ", ".join(sorted(f"{clase} {valor}" for clase, valor in compartidos)[:2])
        return Verdict.CONTINUES, f"las dos hojas llevan el mismo {cuales}"

    clases_izq = {clase for clase, _ in left.identifiers}
    clases_der = {clase for clase, _ in right.identifiers}
    comunes = clases_izq & clases_der
    if comunes and not (left.identifiers & right.identifiers):
        return Verdict.STARTS, f"cambia el identificador ({', '.join(sorted(comunes))})"

    # Prioridad 4: los anexos. Una hoja que se presenta como anexo, o que viene
    # detrás de un documento que anunció los suyos y no trae marca de abrir nada,
    # pertenece al documento abierto. Va antes que el cambio de tipo documental a
    # propósito: un anexo fotográfico ES de otro tipo que el acta que lo trae, y
    # leer ese cambio como frontera es exactamente lo que parte un acta en cinco.
    if right.is_attachment:
        return Verdict.ATTACHMENT, "la hoja se presenta como anexo"
    if trae_anexos:
        return Verdict.ATTACHMENT, "la anterior anuncia anexos y ésta no abre nada"

    # La copia de un documento de identidad es siempre el soporte de otra cosa.
    # Nadie archiva la cédula de alguien por sí misma: va detrás del escrito que
    # esa persona firmó, del acta en que compareció o de la solicitud que
    # presentó. Medido en un expediente real: la cédula de la peticionaria iba
    # pegada al acta de notificación personal que acababa de firmar, y leerla
    # como documento aparte dejaba en la entrega un PDF de una hoja con la
    # fotocopia de un documento de identidad y sin nada que dijera de quién era.
    #
    # Va aquí y no entre los anexos de arriba porque aquélla es una regla sobre
    # lo que la hoja dice de sí misma -- "ANEXOS", "evidencia fotográfica" -- y
    # ésta es sobre lo que la hoja **es**.
    if right.label in HOJAS_DE_SOPORTE and left.label not in HOJAS_DE_SOPORTE:
        return _soporte_de_quien(left, right)

    # El papel diciendo su propio nombre. Después de la paginación, porque la
    # hoja 3 de un acta también lleva escrito "Acta de Irregularidad".
    #
    # Y sólo cuando ese nombre CAMBIA. Dos hojas seguidas que se titulan igual
    # son casi siempre el mismo documento: un acta de cuatro hojas repite su
    # rótulo en las cuatro, y cortando por él salían cuatro actas de una hoja.
    # Dos documentos distintos del mismo tipo -- que los hay, dos avisos de
    # publicación seguidos -- se separan por lo que de verdad los distingue, que
    # es el consecutivo, y esa regla ya se aplicó mucho más arriba.
    #
    # Es también lo que evita la entrega que nadie quiere ver: dos archivos
    # contiguos con el mismo tipo documental en el nombre, que es como se ve un
    # documento partido por la mitad cuando se mira la carpeta.
    if right.label and right.label != left.label:
        return Verdict.STARTS, f"la hoja se titula «{right.label}»"

    # Lo que sólo se imprime al abrir: a quién va dirigido, bajo qué asunto, con
    # qué consecutivo. Medido contra las hojas que declaran su propia paginación,
    # ninguna hoja de continuación trae una de estas marcas en su cabecera.
    if right.opening:
        return Verdict.STARTS, f"la cabecera abre: {', '.join(right.opening)}"

    # Prioridad 6: el papel mismo. Un cambio de tamaño de hoja es un cambio de
    # lote de escaneo, y va aquí -- después de la numeración, los identificadores,
    # los anexos y el tipo -- porque un anexo puede venir en otro papel sin dejar
    # de pertenecer al documento que lo trae. Medido sobre la caja real: ocho
    # cambios en 125 hojas y ninguno contradice la paginación que el papel
    # declara. Es la única señal que sobrevive a una hoja sin texto.
    if left.sheet and right.sheet:
        ancho = abs(left.sheet[0] - right.sheet[0])
        alto = abs(left.sheet[1] - right.sheet[1])
        if ancho > SHEET_TOLERANCE or alto > SHEET_TOLERANCE:
            return (
                Verdict.STARTS,
                f"cambia el tamaño de la hoja ({left.sheet[0]}x{left.sheet[1]}"
                f" a {right.sheet[0]}x{right.sheet[1]})",
            )

    # Un impreso de cobro suelto detrás de algo que no lo era. Si comparte
    # identificadores con la hoja anterior es su anexo; si no comparte ninguno,
    # es otro asunto y va aparte. El código de expediente no cuenta aquí -- lo
    # llevan las 125 páginas de la caja -- y por eso no está entre ellos.
    if right.invoice and not left.invoice:
        shared = right.identifiers & left.identifiers
        if shared:
            return Verdict.CONTINUES, "el cobro comparte identificador con la hoja anterior"
        return Verdict.STARTS, "un cobro sin nada en común con la hoja anterior"

    # El folio escrito a mano. Va aquí abajo, y no arriba con la paginación
    # impresa, aunque las dos sean el papel contándose: la impresa es del
    # documento y se reinicia con él, mientras que el folio lo pone quien archiva
    # y en media Colombia numera el expediente entero de corrido. Ahí
    # `folio + 1` es cierto también en la frontera entre dos documentos, así que
    # por encima del consecutivo, del rótulo y de la cabecera soldaría la caja --
    # el mismo modo de fallo por el que el código de expediente no decide nada.
    # Debajo de todas ellas sólo habla donde nadie más tenía nada que decir.
    if left.folio is not None and right.folio == left.folio + 1:
        return Verdict.CONTINUES, f"el folio sigue en {right.folio} tras el {left.folio}"

    # La oración partida por el escáner. Es la evidencia más fuerte que quedaba
    # gratis y no se usaba: `tail` y `title` ya se calculaban -- se le mandaban al
    # modelo en la huella -- así que se pagaba una llamada por costuras que la
    # tipografía del texto ya resolvía.
    if _sentence_runs_on(left, right):
        return Verdict.CONTINUES, "la oración sigue cortada en la hoja siguiente"

    # Un documento que se despidió y otro que abre son dos. `closes` también se
    # calculaba y también se ignoraba. Esta regla empuja a cortar, que es el lado
    # seguro del error: partir un documento en dos se repara en segundos, soldar
    # dos en uno esconde el segundo donde nadie lo va a buscar.
    if left.closes and (right.letterhead or right.place_and_date):
        return Verdict.STARTS, "la anterior se despide y la siguiente abre"

    # Y lo último antes de rendirse: si la hoja anterior abrió un documento y ésta
    # no trae ninguna marca de abrir nada, es el cuerpo de aquélla. Va al final
    # porque es la más débil de todas -- se apoya en la ausencia de evidencia --
    # y sólo se la consulta cuando ninguna presencia de evidencia dijo nada.
    # Abrir es traer marcas de apertura o titularse. Las dos cosas dicen "aquí
    # empieza algo", y lo que va detrás sin ninguna de ellas es su cuerpo: una
    # liquidación titulada en su primera hoja sigue en la segunda con "Adjunto
    # encontrará el Formato de Liquidación…" y ni una marca más.
    if (left.opening or left.label) and not (right.opening or right.label):
        return Verdict.CONTINUES, "la anterior abre y ésta no abre nada"

    # Y su hermana, para el medio de un escrito largo: dos hojas llenas de prosa
    # y ninguna de las dos abre nada. En un expediente donde las aperturas van
    # marcadas -- con consecutivo, con destinatario, con asunto, con un rótulo --
    # dos páginas seguidas de prosa densa sin una sola de esas marcas son el
    # cuerpo de lo mismo.
    #
    # Es la evidencia más débil que se admite, porque se apoya en ausencias, y de
    # ahí las tres exigencias: prosa densa en las dos -- una hoja de cuatro líneas
    # sin marcas puede ser cualquier cosa, y la ausencia sólo dice algo cuando hay
    # bastante donde no encontrar nada --, y que la anterior no se haya despedido.
    if _es_cuerpo(left) and _es_cuerpo(right) and not left.closes:
        return Verdict.CONTINUES, "dos hojas llenas de prosa y ninguna abre nada"

    # Deliberately no rule on `case_code`. Every page of an expediente shares it,
    # so reading it as continuity welds the whole box into one document -- an
    # error measured on a real 125-page file before this module existed.
    return Verdict.UNDECIDED, "sin evidencia estructural"


#: A partir de qué presencia un identificador deja de identificar. El NIC de un
#: expediente de un solo cliente aparece en 35 de sus 38 hojas con identificador:
#: leerlo como "estas dos hojas hablan de lo mismo" soldaría la caja entera, que
#: es el mismo motivo por el que el código de expediente no decide nada. Un
#: importe concreto, en cambio, sale en dos o tres hojas -- el recibo por delante
#: y por detrás -- y ahí sí dice algo.
UBIQUITOUS_SHARE = 0.5

#: Y por debajo de cuántas hojas la proporción no mide nada. En una caja con dos
#: hojas que llevan NIC, el NIC que comparten es el 100 % de su clase y aun así
#: no hay ninguna razón para desconfiar de él: la ubicuidad es un hecho sobre
#: muchas hojas, no sobre dos.
UBIQUITOUS_MIN_SHEETS = 4

#: Cuántas palabras necesita el final de una hoja para leerse como prosa cortada
#: y no como un rótulo. Un anexo cuya página entera dice "anexo uno" también
#: termina en letra, y soldarlo con "anexo dos" es el error exacto que esta cuenta
#: evita -- lo detectó la prueba de tres anexos sueltos antes que un operador.
RUNON_TAIL_WORDS = 5

#: Y cuántas necesita el arranque de la siguiente. Una frase retomada es una
#: frase; "anexo dos" son dos palabras y una etiqueta.
RUNON_HEAD_WORDS = 3


#: Los tipos que nunca son un documento por sí solos: son el soporte de otro.
#: Se nombran con el nombre del catálogo, en minúscula, que es como los devuelve
#: la huella. La lista es corta a propósito -- sólo lo que no puede archivarse
#: suelto -- porque cada entrada aquí es una hoja que deja de poder abrir nada.
HOJAS_DE_SOPORTE = frozenset({"documento de identidad"})


def _soporte_de_quien(left: PageFingerprint, right: PageFingerprint) -> tuple[Verdict, str]:
    """A qué documento pertenece la copia de un documento de identidad.

    No se supone: se comprueba contra la hoja anterior, que es lo que pidió el
    operador y además lo correcto. Una cédula suelta detrás de un escrito es su
    soporte cuando es la cédula de quien lo firmó; si es la de otra persona,
    pertenece a otra cosa y unirla escondería un documento dentro de otro.

    Se mira primero el número, que es el dato que no se presta a
    interpretación. Cuando el escáner se lo comió -- pasa, y estas carátulas
    llegan muy rotas -- se cae a los nombres propios en mayúscula, y se piden
    dos coincidencias: un apellido corriente lo comparten hojas de asuntos
    distintos del mismo municipio, y "CESAR" aquí es un departamento.

    Y si no se puede comprobar de ninguna de las dos formas, se une igual. Es
    la política de la casa aplicada a un caso concreto: la copia de una cédula
    no es una unidad documental que nadie vaya a buscar por sí misma, así que
    el error de unirla deja un anexo donde debía, y el de separarla deja en la
    entrega un PDF de una hoja con la fotocopia de un documento de identidad y
    sin nada que diga de quién es.
    """
    if right.cedula and left.cedula:
        if right.cedula == left.cedula:
            return Verdict.ATTACHMENT, f"la cédula {right.cedula} es la de la hoja anterior"
        return (
            Verdict.STARTS,
            f"la cédula {right.cedula} no es la de la hoja anterior ({left.cedula})",
        )

    comunes = right.nombres & left.nombres
    if len(comunes) >= NOMBRES_QUE_DEBEN_COINCIDIR:
        cuales = ", ".join(sorted(comunes)[:2])
        return Verdict.ATTACHMENT, f"la cédula es de {cuales}, como la hoja anterior"

    return Verdict.ATTACHMENT, f"la hoja es un soporte y no un documento: {right.label}"


def _es_cuerpo(page: PageFingerprint) -> bool:
    """Si la hoja es prosa densa y no trae ninguna marca de abrir un documento."""
    # `serial` queda fuera y `opening` lo cubre: el consecutivo cuenta como marca
    # de apertura cuando está en la cabecera, y ahí es donde `opening` lo busca.
    # Un escrito que cita en su cuerpo el consecutivo del oficio al que responde
    # no es por eso una primera hoja.
    return page.dense and not (
        page.opening or page.label or page.place_and_date or page.pagination
    )


def _sentence_runs_on(left: PageFingerprint, right: PageFingerprint) -> bool:
    """Si la oración de la izquierda sigue, sin terminar, en la derecha.

    Estricta a propósito, y la asimetría del error es la razón. Un falso
    CONTINUES suelda dos documentos y el segundo desaparece del inventario sin
    que nadie lo note; un falso STARTS deja dos archivos que el operador junta de
    un vistazo. De modo que una marca que sólo aparece al abrir
    -- ciudad y fecha, un consecutivo, un rótulo -- calla esta regla, y ante un
    dato ausente se abstiene en vez de suponer. El membrete no está entre ellas:
    lo lleva el 89 % del papel de una caja y no distingue nada.

    Tres condiciones, y las tres hacen falta:

    * el final de la izquierda es una letra o una coma -- cualquier signo de
      cierre significa que la frase terminó, y con ella pudo terminar el papel;
    * ese final es prosa y no un rótulo, medido en palabras. Una hoja cuyo texto
      completo es "anexo uno" también termina en letra;
    * el arranque de la derecha es una frase en minúscula, no una etiqueta.
    """
    # El membrete no calla nada por sí solo. Lo llevan 111 de las 125 hojas de la
    # caja medida -- el logo de la empresa va impreso en todo su papel -- así que
    # no distingue una apertura de una continuación, y usarlo aquí dejaba sin
    # decidir prosa cortada a media frase que seguía en minúscula en la hoja de
    # al lado. Lo que sí la calla es una marca que sólo aparece al abrir.
    if right.place_and_date or right.serial or right.opening or right.label:
        return False

    tail = (left.tail or "").rstrip()
    if not tail or not (tail[-1].isalpha() or tail[-1] == ","):
        return False
    if len(tail.split()) < RUNON_TAIL_WORDS:
        return False

    head = (right.title or "").strip()
    if len(head.split()) < RUNON_HEAD_WORDS:
        return False

    first_letter = next((char for char in head if char.isalpha()), None)
    return first_letter is not None and first_letter.islower()


def _ubiquitous(fingerprints: Sequence[PageFingerprint]) -> frozenset[tuple[str, str]]:
    """Los identificadores que lleva tanta hoja que ya no identifican ninguna.

    Se cuenta sobre la caja entera, y por eso vive aquí y no en `_decide`: dos
    huellas sueltas no pueden saber si el número que comparten es del cobro del
    que hablan o del suscriptor del que habla el expediente completo.
    """
    # Se cuenta dentro de la clase, no sobre la caja. Un NIC hay que compararlo
    # con las hojas que llevan NIC: si sale en 35 de esas 38 es el del suscriptor
    # y no distingue nada, y eso sigue siendo cierto aunque otras noventa hojas
    # traigan importes y diluyan el total.
    hojas_por_clase: dict[str, int] = {}
    cuenta: dict[tuple[str, str], int] = {}
    for huella in fingerprints:
        for clase in {clase for clase, _ in huella.identifiers}:
            hojas_por_clase[clase] = hojas_por_clase.get(clase, 0) + 1
        for identificador in huella.identifiers:
            cuenta[identificador] = cuenta.get(identificador, 0) + 1
    return frozenset(
        (clase, valor)
        for (clase, valor), veces in cuenta.items()
        if hojas_por_clase[clase] >= UBIQUITOUS_MIN_SHEETS
        and veces > hojas_por_clase[clase] * UBIQUITOUS_SHARE
    )


def decide_boundaries(fingerprints: Sequence[PageFingerprint]) -> list[Boundary]:
    """Judge every seam on structure alone, free of charge."""
    ubicuos = _ubiquitous(fingerprints)
    boundaries: list[Boundary] = []
    for left, right in zip(fingerprints, fingerprints[1:], strict=False):
        verdict, reason = _decide(left, right, ubicuos)
        boundaries.append(
            Boundary(
                left=left.page_number,
                right=right.page_number,
                verdict=verdict,
                reason=reason,
            )
        )
    return boundaries


def assemble(
    fingerprints: Sequence[PageFingerprint],
    boundaries: Sequence[Boundary],
) -> SegmentationResult:
    """Fold page-by-page verdicts into whole documents.

    Una costura indecisa **une**, y la página queda marcada para revisión.

    Es lo contrario de lo que hacía esta función, y el cambio se tomó con la
    caja medida delante. El argumento viejo -- cortar de más se ve, soldar
    esconde -- suponía que unir podía tragarse documentos enteros. Con las reglas
    de estructura puestas eso deja de ser cierto: sobre un expediente real de 125
    páginas, unir en la duda deja el documento mayor en seis páginas y baja los
    de una sola hoja de 64 a 34. El riesgo que justificaba cortar no aparece, y
    el sobre-corte que produce sí.

    Partir un documento de cinco hojas en cinco archivos destruye la unidad
    documental sin dejar rastro de que existió; unir dos que iban aparte deja un
    archivo de más que la cola de revisión nombra, hoja por hoja. Se prefiere el
    error que se puede deshacer sabiendo qué se deshace.
    """
    if not fingerprints:
        return SegmentationResult()

    by_seam = {(b.left, b.right): b for b in boundaries}
    segments = [Segment(page_numbers=[fingerprints[0].page_number], reason="inicio")]

    for left, right in zip(fingerprints, fingerprints[1:], strict=False):
        boundary = by_seam.get((left.page_number, right.page_number))
        # Una duda declarada une; una costura que falta, no. Son cosas distintas
        # y confundirlas sale caro: quien llame con una lista incompleta -- o con
        # números de página que no casan con las huellas -- vería todo el PDF
        # pegado en un documento sin una sola señal de que algo iba mal.
        if boundary is None:
            segments.append(
                Segment(page_numbers=[right.page_number], reason="sin veredicto para esta costura")
            )
            continue
        if boundary.verdict is not Verdict.STARTS:
            segments[-1].page_numbers.append(right.page_number)
            if boundary is not None and boundary.verdict is Verdict.ATTACHMENT:
                segments[-1].attachment_pages.append(right.page_number)
        else:
            segments.append(Segment(page_numbers=[right.page_number], reason=boundary.reason))


    return SegmentationResult(
        segments=segments,
        boundaries=list(boundaries),
        fingerprints=list(fingerprints),
    )
