from __future__ import annotations

import re

from .anchor import strip_accents
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

#: Y la palabra para lo que se cortó de una caja revuelta y nadie reconoció. La
#: clasificación corre después del corte y contesta a la mayoría, pero no a
#: todas: un tercio de la caja medida no lleva rótulo legible. Para ésas,
#: "DOCUMENTO" es lo más que se puede afirmar sin mentir en el nombre de un
#: archivo. Llamarlo "FACTURA" porque la palabra salía en el cuerpo sería
#: escribir en el disco algo que nadie ha comprobado.
DOCUMENT_PREFIX = "DOCUMENTO"

#: Shortest a title fragment may be squeezed to before it is dropped entirely.
#: Below this it has stopped being a title and is just noise in the name.
MIN_TITLE_SLUG = 12

#: Y lo mínimo que puede quedar del tipo documental antes de que no diga nada.
#: "NOTIFICACION-POR" todavía identifica el papel; "NOT" no.
MIN_KIND_FRAGMENT = 8


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

#: Lo más largo que se deja ser a la carpeta de un documento. El nombre del
#: origen lo pone quien escanea y a veces trae la caja, el radicado y la fecha;
#: con la ruta de trabajo y el nombre del archivo detrás, eso se come el límite
#: de Windows y la entrega no se escribe.
MAX_FOLDER_NAME = 60


def code_fragment(code: ResolutionCode) -> str:
    return slugify(code.value, max_length=CODE_SLUG_LENGTH) or "sin-codigo"


def kind_fragment(kind: str) -> str:
    """El tipo documental tal como se escribe en un nombre de archivo.

    En mayúsculas y con guiones -- "NOTIFICACION-POR-AVISO" -- porque así se lee
    de un vistazo en una carpeta de doscientos archivos y así ordena junto a los
    de su clase. Se conservan las letras y los dígitos y nada más: los nombres
    del catálogo llevan barras ("CAMBIO Y/O ACTUALIZACION...") y Windows no
    admite una barra en un nombre de archivo.
    """
    limpio = re.sub(r"[^A-Z0-9]+", "-", strip_accents(kind).upper())
    return limpio.strip("-") or DOCUMENT_PREFIX


def document_folder(document: str, fallback: str = "documento") -> str:
    """La carpeta donde van los PDF que salieron de un documento.

    Se llama como el documento de origen, sin la extensión: los archivos de una
    caja se entregan juntos y bajo su nombre, no sueltos bajo el identificador
    del trabajo, que no le dice nada a quien abre la carpeta.

    Se le quita a Windows lo que no admite en un nombre de carpeta -- ``\\ / :
    * ? " < > |`` -- y se recorta, porque el nombre del origen viene de un
    escáner y puede traer cualquier cosa. Un nombre imposible aquí no es un
    archivo mal nombrado: es toda la entrega que no se llega a escribir.
    """
    stem = document.rsplit(".", 1)[0] if "." in document else document
    limpio = re.sub(r'[\\/:*?"<>|]+', " ", stem)
    limpio = re.sub(r"\s+", " ", limpio).strip(" .")
    if not limpio:
        return fallback
    return limpio[:MAX_FOLDER_NAME].strip(" .") or fallback


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
    kind: str | None = None,
    con_titulo: bool = False,
) -> str:
    """Nombrar un archivo generado por lo que es y por su número.

    Una sola función decide esto para que el archivo en disco y la fila del
    inventario no puedan discrepar nunca sobre cómo se llama algo. Hay tres
    formas, una por cada clase de unidad, y cada ruta elige la suya:

        RESOLUCION_00086.pdf
        01_DERECHO-DE-PETICION.pdf
        1128047041_JUAN-PEREZ-GOMEZ_DOCUMENTO-DE-IDENTIDAD.pdf

    **Con ``prefix``** manda la palabra y el número, y el tipo documental no
    entra. Es el nombre de una resolución: corto, ordenable y buscable, que es
    para lo que sirve el nombre de un archivo. El asunto vive en su columna del
    inventario, donde sí se puede buscar por texto.

    **Sin ``prefix``** el código va delante y detrás lo que se sepa de la
    unidad. ``con_titulo`` decide si entre los dos va el título, y la diferencia
    no es de gusto: en un libro de folios el título es **de quién** es el
    registro -- "JUAN PEREZ GOMEZ" -- y en una caja revuelta es de dónde salió
    -- "páginas 1-8" --, que ya está en el inventario y en el nombre sólo
    estorba.

    ``budget`` limita el nombre entero. Windows rechaza una ruta de más de 260
    caracteres, y un rechazo al guardar cuesta el documento completo; por eso se
    aprieta primero el título, luego el tipo, y el código no se toca nunca: un
    archivo nombrado sólo con su número se encuentra igual, uno que no llegó a
    escribirse no.
    """
    fragment = code_fragment(code)

    if prefix:
        return f"{prefix}{PREFIX_SEPARATOR}{fragment}{extension}"

    if kind is not None:
        # El código delante y el tipo detrás, con quién en medio si se sabe. En
        # ese orden y no al revés porque la carpeta se lista por nombre, y lo
        # que hace falta al revisar es recorrerla en el orden en que venían las
        # hojas.
        etiqueta = kind_fragment(kind)
        quien = slugify(title or "", max_length=TITLE_SLUG_LENGTH) if con_titulo else ""
        if budget is not None:
            room = budget - len(fragment) - len(PREFIX_SEPARATOR) - len(extension)
            if room < MIN_KIND_FRAGMENT:
                # No cabe ni recortado. El número sí, y un archivo nombrado
                # sólo con su número se encuentra; uno que no se llegó a
                # escribir no.
                return f"{fragment}{extension}"
            # Se aprieta el nombre de la persona antes que el tipo: aquél es
            # largo y el archivo se busca por el otro.
            sobra = room - len(etiqueta) - len(PREFIX_SEPARATOR)
            if quien and sobra < MIN_TITLE_SLUG:
                quien = ""
            elif quien and len(quien) > sobra:
                quien = slugify(quien, max_length=sobra)
            if len(etiqueta) > room:
                etiqueta = etiqueta[:room].rstrip("-")
        piezas = [fragment, *( [quien] if quien else [] ), etiqueta]
        return PREFIX_SEPARATOR.join(piezas) + extension

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
