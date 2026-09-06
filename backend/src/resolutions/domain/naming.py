from __future__ import annotations

from .resolution_code import ResolutionCode
from .title import slugify

CODE_SLUG_LENGTH = 40
TITLE_SLUG_LENGTH = 60
SEPARATOR = "__"

#: Con qué se nombra un archivo generado: la palabra que dice qué es, un guion
#: bajo y el número. "RESOLUCION_00086.pdf".
#:
#: Lo pidió el operador y sustituye al nombre largo que se usaba antes --
#: "00086__por-medio-de-la-cual-se-anula-un-diploma-y-se-autoriza-la.pdf" --
#: donde el número quedaba enterrado bajo un resumen del asunto. El asunto no se
#: pierde: sigue en la columna que le corresponde del inventario, que es donde
#: se busca por texto. El nombre del archivo sirve para otra cosa, que es
#: encontrar la resolución 00086 entre trescientas de un vistazo.
PREFIX_SEPARATOR = "_"
RESOLUTION_PREFIX = "RESOLUCION"

#: Y la palabra para lo que se cortó de una caja revuelta. Un documento recién
#: segmentado todavía no sabe qué es -- eso lo dirá la clasificación, que viene
#: después -- así que "DOCUMENTO" es lo más que se puede afirmar sin mentir en el
#: nombre de un archivo. Llamarlo "RESOLUCION" sería escribir en el disco algo
#: que nadie ha comprobado.
DOCUMENT_PREFIX = "DOCUMENTO"

#: Shortest a title fragment may be squeezed to before it is dropped entirely.
#: Below this it has stopped being a title and is just noise in the name.
MIN_TITLE_SLUG = 12


#: Lo que Windows acepta como ruta completa. MAX_PATH son 260 contando el cero
#: final, así que lo utilizable son 259; se dejan cuatro de margen porque una
#: ruta de 259 exactos ya falló al guardar en una carpeta de trabajo profunda.
#:
#: Pasarse no da un archivo con el nombre recortado: da una excepción al
#: guardar, y con ella se pierde el trabajo entero de leer el documento.
WINDOWS_PATH_LIMIT = 255

#: Lo mínimo que puede quedar del nombre del documento antes de que deje de
#: identificarlo. Por debajo de esto es preferible un nombre genérico.
MIN_DOCUMENT_STEM = 8


def code_fragment(code: ResolutionCode) -> str:
    return slugify(code.value, max_length=CODE_SLUG_LENGTH) or "sin-codigo"


def sheet_filename(
    document: str,
    suffix: str,
    directory_length: int = 0,
    fallback: str = "inventario",
) -> str:
    """Nombra una planilla por el documento que describe, sin pasarse de largo.

    El nombre que puso el operador puede ser larguísimo -- "6.3858084 REGISTRO
    DE DIPLOMAS N°08 2012-2013 (30 paginas)" -- y la carpeta de salida lleva un
    identificador de 32 caracteres. Sumados a una ruta de trabajo profunda, el
    guardado falla con "No such file or directory", que es lo último que uno
    mira cuando el problema es el largo.

    Así que el sufijo no se toca nunca -- es lo que hace reconocible el archivo
    y lo que lo encuentra el endpoint de descarga -- y lo que se recorta es el
    nombre del documento, hasta desaparecer si hace falta.
    """
    stem = document.rsplit(".", 1)[0] if "." in document else document
    stem = stem.strip() or fallback

    room = WINDOWS_PATH_LIMIT - directory_length - len(suffix) - 1
    if room < MIN_DOCUMENT_STEM:
        return f"{fallback}{suffix}"
    if len(stem) > room:
        stem = stem[:room].rstrip(" .-_")
    return f"{stem or fallback}{suffix}"


def output_filename(
    code: ResolutionCode,
    title: str | None,
    extension: str = ".pdf",
    budget: int | None = None,
    prefix: str | None = RESOLUTION_PREFIX,
) -> str:
    """Nombrar un archivo generado por lo que es y por su número.

    Una sola función decide esto para que el archivo en disco y la fila del
    inventario no puedan discrepar nunca sobre cómo se llama algo.

    Con ``prefix`` -- lo normal -- el nombre es "RESOLUCION_00086.pdf": la
    palabra que dice qué es, y el número. Corto, ordenable y buscable, que es
    para lo que sirve el nombre de un archivo. El asunto no entra: vive en su
    columna del inventario, donde sí se puede buscar por texto.

    Con ``prefix=None`` se conserva el nombre largo de antes -- número, dos
    guiones bajos y el asunto -- para las unidades documentales que no son
    resoluciones y a las que esa palabra no les corresponde.

    ``budget`` limita el nombre entero. Windows rechaza una ruta de más de 260
    caracteres, y un rechazo al guardar cuesta la resolución completa; por eso
    el asunto se aprieta, luego se descarta, y el número no se toca nunca: un
    archivo nombrado sólo con su número se encuentra igual, uno que no llegó a
    escribirse no.
    """
    fragment = code_fragment(code)
    if prefix:
        return f"{prefix}{PREFIX_SEPARATOR}{fragment}{extension}"

    title_slug = slugify(title or "", max_length=TITLE_SLUG_LENGTH)

    if budget is not None:
        room = budget - len(fragment) - len(SEPARATOR) - len(extension)
        if room < MIN_TITLE_SLUG:
            title_slug = ""
        elif len(title_slug) > room:
            title_slug = slugify(title_slug, max_length=room)

    if title_slug:
        return f"{fragment}{SEPARATOR}{title_slug}{extension}"
    return f"{fragment}{extension}"
