"""Convertir el fallo de una biblioteca en una frase que el operador entienda.

Quien procesa una caja de expedientes no está depurando un programa. Cuando la
consola le dice ``RuntimeError: code=4: source object number out of range`` no
está recibiendo información: está recibiendo un texto correcto y opaco que no
dice qué pasó, ni si la culpa es del archivo o del sistema, ni qué puede hacer
al respecto. Y como todos los mensajes se ven igual, tampoco distingue el que le
costó una página del que no le costó nada.

Aquí vive el vocabulario con que se le habla: qué significa cada mensaje que
MuPDF sabe emitir, en español, y si lo que cuenta se recuperó o se perdió. Es
una traducción, no un adorno -- el texto original viaja siempre pegado a la
explicación, porque es lo único que sirve para buscar en la documentación de la
biblioteca cuando aparezca algo que esta tabla todavía no recoge.

El módulo es de la capa de aplicación y no del adaptador a propósito: quien
formatea el motivo que se le enseña al operador es el caso de uso, y ni el
pipeline ni el proceso de un documento pueden importar un adaptador. Lo que sí
necesita MuPDF -- desviar sus mensajes y vaciar su almacén -- se queda en
``adapters/mupdf_messages.py``, que es donde toca.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Gravedad(StrEnum):
    """Qué consecuencia tuvo lo que MuPDF encontró."""

    #: El documento venía dañado y MuPDF siguió adelante igual. La salida está
    #: completa; lo que hay que saber es que el original tiene un defecto.
    RECUPERADO = "recuperado"

    #: Algo del documento se quedó fuera: una anotación, un perfil de color, una
    #: página. La salida es utilizable pero no es idéntica al original.
    PERDIDA = "perdida"


@dataclass(frozen=True, slots=True)
class Incidencia:
    """Un mensaje de MuPDF, entendido.

    Se conserva el texto original junto a la explicación. Traducir sin guardar
    lo que se tradujo convierte un mensaje buscable en una frase bonita que no
    lleva a ninguna parte.
    """

    original: str
    explicacion: str
    gravedad: Gravedad
    #: Cuántas veces apareció el mismo mensaje en el documento. Un escaneo de
    #: cuatrocientas páginas con el perfil de color roto lo repite cuatrocientas
    #: veces, y cuatrocientas líneas iguales no informan más que una con su
    #: cuenta al lado.
    veces: int = 1

    def __str__(self) -> str:
        repeticion = f" ({self.veces} veces)" if self.veces > 1 else ""
        return f"{self.explicacion}{repeticion} [MuPDF: {self.original}]"

    def as_dict(self) -> dict[str, object]:
        return {
            "mensaje": self.original,
            "explicacion": self.explicacion,
            "gravedad": str(self.gravedad),
            "veces": self.veces,
        }


#: Qué significa cada mensaje de MuPDF, en el orden en que se busca.
#:
#: Los patrones están sacados del catálogo de cadenas de la propia biblioteca
#: (``mupdfcpp64.dll``), no inventados a partir de lo que se vio una vez en una
#: consola: una traducción que no corresponde a ningún mensaje real es una
#: entrada que nunca va a coincidir, y ese fallo es silencioso.
#:
#: Se compara por subcadena y no por igualdad porque MuPDF antepone su propia
#: clasificación al texto ("format error: ", "syntax error: ") y mete números
#: dentro de la frase. El orden es de lo particular a lo general: la primera
#: entrada que coincide es la que responde.
#:
#: Cada explicación cuenta la causa en el PDF, no la reacción de la biblioteca.
#: Al operador le sirve saber que el archivo que le entregaron trae la tabla de
#: objetos rota; no le sirve saber que una función de C devolvió un código.
_TRADUCCIONES: tuple[tuple[str, str, Gravedad], ...] = (
    # -- el injerto de páginas: lo único de esta lista que pierde páginas -----
    (
        "source object number out of range",
        "el PDF de origen remite a un objeto que no figura en su tabla de "
        "referencias cruzadas: la tabla está rota y sus páginas no pueden "
        "copiarse tal cual",
        Gravedad.PERDIDA,
    ),
    (
        "grafted objects must all belong to the same source document",
        "se intentó copiar páginas de dos documentos distintos a la vez",
        Gravedad.PERDIDA,
    ),
    (
        "tried to add an object belonging to a different document",
        "se intentó copiar un objeto que pertenece a otro documento",
        Gravedad.PERDIDA,
    ),
    # -- la tabla de referencias cruzadas -------------------------------------
    (
        "object number out of range",
        "el PDF remite a un objeto que no figura en su tabla de referencias "
        "cruzadas",
        Gravedad.PERDIDA,
    ),
    (
        "out of range",
        "el PDF declara una cantidad de objetos que no cuadra con su tabla de "
        "referencias cruzadas",
        Gravedad.PERDIDA,
    ),
    (
        "unlisted object",
        "el documento usa un objeto que su tabla de referencias cruzadas no "
        "declara",
        Gravedad.PERDIDA,
    ),
    (
        "trying to repair broken xref",
        "la tabla de referencias cruzadas del PDF está rota y se está "
        "reconstruyendo leyendo el archivo entero",
        Gravedad.RECUPERADO,
    ),
    (
        "broken xref",
        "un tramo de la tabla de referencias cruzadas está mal formado; se "
        "continúa sin él",
        Gravedad.RECUPERADO,
    ),
    (
        "repairing",
        "el PDF venía con la estructura dañada y hubo que reconstruirla antes "
        "de poder leerlo",
        Gravedad.RECUPERADO,
    ),
    (
        "cannot find startxref",
        "el PDF no declara dónde empieza su tabla de referencias cruzadas; hay "
        "que reconstruirla leyendo el archivo entero",
        Gravedad.RECUPERADO,
    ),
    (
        "cannot find xref marker",
        "el PDF no trae la marca que señala su tabla de referencias cruzadas",
        Gravedad.RECUPERADO,
    ),
    (
        "cannot recognize xref format",
        "la tabla de referencias cruzadas no tiene un formato que MuPDF "
        "reconozca",
        Gravedad.RECUPERADO,
    ),
    (
        "malformed xref table",
        "la tabla de referencias cruzadas está mal formada",
        Gravedad.RECUPERADO,
    ),
    (
        "no objects found",
        "no se encontró ningún objeto dentro del archivo: no es un PDF o está "
        "vacío",
        Gravedad.PERDIDA,
    ),
    # -- objetos y flujos sueltos --------------------------------------------
    (
        "object is not a stream",
        "un objeto del PDF se declara como flujo de datos y no lo es; el "
        "contenido al que apuntaba no está donde el documento dice",
        Gravedad.RECUPERADO,
    ),
    (
        "corrupt object stream",
        "un flujo de objetos del PDF está corrompido",
        Gravedad.PERDIDA,
    ),
    (
        "object missing 'endobj' token",
        "un objeto del PDF no está cerrado como manda el formato; el archivo se "
        "escribió mal en origen",
        Gravedad.RECUPERADO,
    ),
    (
        "cannot find endstream token",
        "un flujo del PDF no declara dónde termina; hay que buscar su final "
        "leyendo el contenido",
        Gravedad.RECUPERADO,
    ),
    (
        "expected 'endstream' keyword",
        "un flujo del PDF no está cerrado como manda el formato",
        Gravedad.RECUPERADO,
    ),
    (
        "cannot load content stream",
        "no se pudo leer el contenido de una página",
        Gravedad.PERDIDA,
    ),
    (
        "syntax error in content stream",
        "el contenido de una página tiene instrucciones mal escritas; se dibuja "
        "lo que se entienda",
        Gravedad.RECUPERADO,
    ),
    (
        # El resumen que MuPDF imprime al terminar una página cuyo contenido
        # traía errores de sintaxis de los que se pudo recuperar. Salió sobre el
        # libro de resoluciones 00960-00979 de la Universidad y hasta ahora
        # llegaba a la consola sin traducir.
        "encountered syntax errors",
        "una página traía errores de sintaxis en su contenido; se dibujó lo que "
        "se entendía y puede no salir exacta",
        Gravedad.RECUPERADO,
    ),
    (
        "zlib",
        "un flujo comprimido del PDF no se puede descomprimir: sus datos están "
        "corrompidos",
        Gravedad.PERDIDA,
    ),
    (
        "truncated",
        "una parte del PDF termina antes de lo que el propio archivo declara: "
        "llegó incompleto o se truncó al copiarlo",
        Gravedad.PERDIDA,
    ),
    # -- color: MuPDF siempre tiene a qué recurrir, así que nunca pierde nada --
    (
        "icc",
        "el perfil de color ICC del documento no se puede usar; se dibuja con "
        "el espacio de color equivalente y la página se ve igual",
        Gravedad.RECUPERADO,
    ),
    (
        "unknown colorspace",
        "el documento usa un espacio de color que MuPDF no conoce; se dibuja "
        "con el equivalente más cercano",
        Gravedad.RECUPERADO,
    ),
    (
        "cannot determine colorspace",
        "no se pudo determinar el espacio de color de una imagen; se dibuja "
        "con el equivalente más cercano",
        Gravedad.RECUPERADO,
    ),
    (
        "colorspace",
        "el espacio de color declarado por el documento no es válido; se dibuja "
        "con el equivalente más cercano",
        Gravedad.RECUPERADO,
    ),
    # -- enlaces y anotaciones: se pierden ellos, no el contenido de la página -
    (
        # No es una pérdida. El enlace ya venía roto en el original -- apuntaba
        # a un destino que no existe --, así que no copiarlo no quita nada que
        # funcionara: el texto y las imágenes de la página son los mismos. Se
        # contaba como pérdida y por eso salía en la consola del operador con
        # el mismo peso que una página que no se pudo escribir.
        "skipping bad link / annot item",
        "un enlace del original apuntaba a un destino que no existe y no se "
        "copió; el contenido de la página es el mismo",
        Gravedad.RECUPERADO,
    ),
    (
        "invalid link destination",
        "un enlace del original apunta a un sitio que no existe en el "
        "documento; el contenido de la página no cambia",
        Gravedad.PERDIDA,
    ),
    (
        "cannot create appearance stream",
        "una anotación del original no se puede dibujar; el contenido de la "
        "página no cambia",
        Gravedad.PERDIDA,
    ),
    # -- tipografías: el texto se dibuja igual, con otra letra ----------------
    (
        "corrupt encoding",
        "la codificación de una tipografía del documento está corrompida; el "
        "texto puede leerse mal",
        Gravedad.RECUPERADO,
    ),
    (
        "corrupt charset",
        "el juego de caracteres de una tipografía del documento está "
        "corrompido; el texto puede leerse mal",
        Gravedad.RECUPERADO,
    ),
    # -- estructura de páginas ------------------------------------------------
    (
        "non-page object in page tree",
        "el árbol de páginas del PDF contiene algo que no es una página",
        Gravedad.RECUPERADO,
    ),
    (
        "invalid page object",
        "una página del PDF no está descrita como manda el formato",
        Gravedad.PERDIDA,
    ),
)

#: Lo que MuPDF antepone a su propio texto y que no aporta nada una vez
#: traducido. Se recorta sólo para decidir si el mensaje ya era conocido.

#: Lo que MuPDF antepone a su propio texto y que no aporta nada una vez
#: traducido. Se recorta sólo para decidir si el mensaje ya era conocido.
_PREFIJOS = (
    "format error: ",
    "syntax error: ",
    "library error: ",
    "warning: ",
    "error: ",
)

#: Cómo repite PyMuPDF un mensaje idéntico consecutivo dentro de su almacén.
_REPETICION = re.compile(r"^\.\.\.\s*repeated (\d+) times\.\.\.$")

#: El ``code=N:`` con que PyMuPDF encabeza el texto de sus excepciones.
_CODIGO = re.compile(r"^\s*code=\d+:\s*")

#: Lo que se dice de un mensaje que la tabla no reconoce. Está aparte porque
#: :func:`explicar` necesita distinguirlo para no envolver en una frase genérica
#: un texto que nadie ha entendido.
SIN_TRADUCIR = "MuPDF informó de un problema que este sistema todavía no sabe explicar"


def traducir(mensaje: str) -> Incidencia:
    """Qué significa un mensaje de MuPDF.

    Lo que no está en la tabla se devuelve tal cual y como pérdida. Es la
    postura prudente: un mensaje que este módulo no sabe leer puede ser
    cualquier cosa, y presentarlo como inofensivo sería afirmar algo que no se
    ha comprobado.
    """
    texto = mensaje.strip()
    desnudo = texto.lower()
    for prefijo in _PREFIJOS:
        if desnudo.startswith(prefijo):
            desnudo = desnudo[len(prefijo) :]
            break
    for patron, explicacion, gravedad in _TRADUCCIONES:
        if patron in desnudo:
            return Incidencia(original=texto, explicacion=explicacion, gravedad=gravedad)
    return Incidencia(original=texto, explicacion=SIN_TRADUCIR, gravedad=Gravedad.PERDIDA)


def agrupar(crudo: str) -> list[Incidencia]:
    """Traducir un volcado de mensajes y juntar los iguales con su cuenta.

    PyMuPDF ya colapsa las repeticiones consecutivas en una línea aparte
    ("... repeated 5 times..."), que pertenece al mensaje anterior y no es un
    mensaje propio: se suma a su cuenta en vez de contarse como un aviso más.
    """
    orden: list[str] = []
    vistas: dict[str, Incidencia] = {}
    ultima: str | None = None
    for linea in crudo.splitlines():
        texto = linea.strip()
        if not texto:
            continue
        repeticion = _REPETICION.match(texto)
        if repeticion is not None and ultima is not None:
            # La cuenta que da PyMuPDF incluye la aparición que ya se contó.
            vistas[ultima] = _mas(vistas[ultima], max(int(repeticion.group(1)), 1) - 1)
            continue
        incidencia = traducir(texto)
        clave = incidencia.original
        if clave in vistas:
            vistas[clave] = _mas(vistas[clave], 1)
        else:
            vistas[clave] = incidencia
            orden.append(clave)
        ultima = clave
    return [vistas[clave] for clave in orden]


def _mas(incidencia: Incidencia, veces: int) -> Incidencia:
    return Incidencia(
        original=incidencia.original,
        explicacion=incidencia.explicacion,
        gravedad=incidencia.gravedad,
        veces=incidencia.veces + veces,
    )


def explicar(error: BaseException | str) -> str:
    """La frase que se le enseña al operador cuando algo falló.

    Se traduce lo que se reconoce y se conserva el original detrás, entre
    corchetes, para quien tenga que depurarlo.

    Lo que no se reconoce se devuelve tal como venía, con el nombre de la
    excepción delante. Envolver en una explicación genérica un mensaje que nadie
    ha entendido sería aparentar un diagnóstico que no existe, y quitarle el
    nombre de la clase dejaría motivos ilegibles: un ``KeyError('spa')`` sin su
    nombre es sólo ``'spa'``.
    """
    if isinstance(error, BaseException):
        texto = str(error).strip()
        etiqueta = type(error).__name__
    else:
        texto = str(error).strip()
        etiqueta = None
    if not texto:
        return etiqueta or ""
    incidencia = traducir(_CODIGO.sub("", texto))
    if incidencia.explicacion is SIN_TRADUCIR:
        return f"{etiqueta}: {texto}" if etiqueta else texto
    return f"{incidencia.explicacion} [MuPDF: {texto}]"
