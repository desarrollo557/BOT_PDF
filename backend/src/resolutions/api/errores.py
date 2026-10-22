"""Cómo se le cuenta al operador que un parámetro llegó mal.

FastAPI describe cada error de validación como pydantic lo emite: una lista de
diccionarios con `loc`, `msg`, `type` y `ctx`, en inglés. Está pensada para
que la lea un programa. La pantalla de este sistema enseña `detail` tal cual
en un párrafo, así que lo que veía el operador era «[object Object]».

Lo que hay aquí convierte esa lista en una oración en español que dice tres
cosas y nada más: qué parámetro, qué se esperaba de él y qué llegó.
"""

from __future__ import annotations

import errno
from collections.abc import Iterable, Mapping
from pathlib import PureWindowsPath

#: De dónde viene el parámetro. Es útil para el programa y ruido para quien
#: lee: «limit» se entiende; «query.limit» no dice nada más.
_ORIGENES = {"query", "body", "path", "header", "cookie"}

#: Hasta dónde se repite lo que llegó. Un `q` de cinco mil letras no cabe en
#: un mensaje, y con las primeras basta para reconocerlo.
_LARGO_DEL_VALOR = 40

#: Qué se esperaba, por el tipo de error de pydantic. Lo que no está aquí sale
#: como «no es válido» con el motivo original entre paréntesis, que es peor que
#: una traducción y mejor que un hueco.
_ESPERADO = {
    "int_parsing": "debe ser un número entero",
    "int_type": "debe ser un número entero",
    "int_from_float": "debe ser un número entero",
    "float_parsing": "debe ser un número",
    "float_type": "debe ser un número",
    "bool_parsing": "debe ser verdadero o falso",
    "bool_type": "debe ser verdadero o falso",
    "string_type": "debe ser texto",
    "list_type": "debe ser una lista",
    "dict_type": "debe ser un objeto",
    "missing": "es obligatorio",
    "json_invalid": "no es un JSON válido",
}


def _nombre(loc: Iterable[object]) -> str:
    partes = [str(parte) for parte in loc if str(parte) not in _ORIGENES]
    return ".".join(partes) or "la petición"


def _valor(dato: object) -> str:
    texto = str(dato)
    if len(texto) > _LARGO_DEL_VALOR:
        return texto[: _LARGO_DEL_VALOR - 1] + "…"
    return texto


def _esperado(error: Mapping[str, object]) -> str:
    tipo = str(error.get("type") or "")
    contexto = error.get("ctx") or {}
    if not isinstance(contexto, Mapping):
        contexto = {}
    if tipo in _ESPERADO:
        return _ESPERADO[tipo]
    if tipo == "greater_than_equal":
        return f"debe ser mayor o igual que {contexto.get('ge')}"
    if tipo == "greater_than":
        return f"debe ser mayor que {contexto.get('gt')}"
    if tipo == "less_than_equal":
        return f"debe ser menor o igual que {contexto.get('le')}"
    if tipo == "less_than":
        return f"debe ser menor que {contexto.get('lt')}"
    if tipo == "string_too_long":
        return f"no puede pasar de {contexto.get('max_length')} caracteres"
    if tipo == "string_too_short":
        return f"debe tener al menos {contexto.get('min_length')} caracteres"
    if tipo in ("enum", "literal_error"):
        esperados = contexto.get("expected")
        return f"debe ser uno de: {esperados}" if esperados else "no es un valor admitido"
    motivo = str(error.get("msg") or "").strip()
    return f"no es válido ({motivo})" if motivo else "no es válido"


def explicar_validacion(errores: Iterable[Mapping[str, object]]) -> str:
    """Una oración por error, todas en un párrafo, en español.

    «El parámetro «limit» debe ser un número entero; se recibió «abc».» Lo que
    llegó se repite sólo cuando ayuda: en un parámetro que falta no hay nada
    que repetir, y lo que pydantic guarda ahí es el objeto entero que lo
    contenía.
    """
    frases: list[str] = []
    for error in errores:
        tipo = str(error.get("type") or "")
        frase = f"El parámetro «{_nombre(error.get('loc') or ())}» {_esperado(error)}"
        recibido = error.get("input")
        if recibido is not None and tipo != "missing" and not isinstance(recibido, Mapping):
            frase += f"; se recibió «{_valor(recibido)}»"
        frases.append(frase)
    if not frases:
        return "La petición no es válida."
    return ". ".join(frases) + "."


# -- fallos del trabajo -------------------------------------------------------

#: Hasta dónde se repite el texto técnico de un fallo que no se reconoce.
_LARGO_DEL_DETALLE = 300

#: Los fallos de los proveedores, por el nombre de su clase: quien los lanza
#: es un adaptador, y esta capa no tiene por qué importarlo para nombrarlo.
_DE_UN_PROVEEDOR = {
    "TesseractError": "El OCR (Tesseract) no pudo leer una página",
    "MistralOcrError": "El OCR con IA (Mistral) no contestó bien",
    "InventoryUnavailable": "No se pudo escribir en la base del inventario",
    "ResumenNoDisponible": "El resumen con IA no está disponible",
}


def _archivo(error: OSError) -> str:
    # Sólo el nombre: la ruta entera dice dónde vive el servicio a quien no le hace falta.
    # PureWindowsPath parte por «\» y por «/» en cualquier sistema: con Path, en
    # Linux, una ruta de Windows salía entera.
    nombre = PureWindowsPath(str(error.filename)).name if error.filename else ""
    return f" «{nombre}»" if nombre else ""


#: Los errores de Windows de un archivo que otro programa tiene abierto:
#: «The process cannot access the file because it is being used by another
#: process» (32) y el de una parte bloqueada (33).
_EN_USO_DE_WINDOWS = (32, 33)


def archivo_en_uso(error: BaseException | None) -> bool:
    """Si el fallo es que otro programa -- un visor, Excel, el antivirus -- tiene el archivo tomado.

    Mira también la causa: quien espera a que se libere y se rinde lanza su
    propio error con el de Windows debajo.
    """
    for candidato in (error, getattr(error, "__cause__", None)):
        if candidato is None:
            continue
        if getattr(candidato, "winerror", None) in _EN_USO_DE_WINDOWS:
            return True
        texto = str(candidato).lower()
        if "being used by another process" in texto or "locked a portion" in texto:
            return True
    return False


def fallo_conocido(error: BaseException) -> str | None:
    """El fallo en palabras del operador si es uno de los que se saben explicar.

    Sin el texto crudo de la excepción, que lleva rutas e interioridades: lo que
    devuelve se puede enseñar en cualquier pantalla. ``None`` si no se reconoce.
    """
    if archivo_en_uso(error):
        return (
            f"El archivo{_archivo(error) if isinstance(error, OSError) else ''} está abierto en otro "
            "programa (un visor de PDF, Excel, el antivirus u otra corrida sobre la misma carpeta) y "
            "Windows no deja usarlo. Ciérrelo: el PDF se vuelve a intentar al final de la carpeta."
        )
    if isinstance(error, PermissionError):
        return (
            f"No hay permiso para usar{_archivo(error)}. Si es un Excel o un PDF, "
            "ciérrelo en el programa que lo tenga abierto; si es una carpeta, revise "
            "que no sea de solo lectura. Después vuelva a intentarlo."
        )
    if isinstance(error, FileNotFoundError):
        if "tesseract" in str(error.filename or "").lower():
            return "No se encontró Tesseract en este equipo: hay que instalarlo o configurar su ruta."
        return (
            f"No se encontró{_archivo(error)}: se movió, se renombró o se borró "
            "mientras se procesaba."
        )
    if isinstance(error, IsADirectoryError | NotADirectoryError):
        return f"La ruta{_archivo(error)} no es lo que se esperaba (archivo o carpeta)."
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return "El disco de destino se quedó sin espacio. Libere espacio y vuelva a intentarlo."
    if isinstance(error, MemoryError):
        return (
            "El equipo se quedó sin memoria con este documento. Pruebe a procesar "
            "menos documentos a la vez."
        )
    if type(error).__name__ == "BrokenProcessPool":
        return (
            "El proceso que leía el documento se cerró de golpe, casi siempre por "
            "falta de memoria. Vuelva a intentarlo."
        )
    if isinstance(error, TimeoutError):
        return "Una operación tardó demasiado y se abandonó. Vuelva a intentarlo."
    if isinstance(error, ConnectionError):
        return "Se perdió la conexión con un servicio externo. Revise la red y vuelva a intentarlo."
    return None


def explicar_fallo(error: BaseException) -> str:
    """Un fallo del procesamiento contado en español, con qué hacer cuando se sabe.

    El texto crudo de una excepción -- «PermissionError: [Errno 13] Permission
    denied: '…inventario.xlsx'» -- no le dice al operador que el Excel está
    abierto y basta con cerrarlo. Los fallos conocidos se traducen; los demás
    conservan su texto técnico recortado, que sigue sirviendo para buscarlo.
    Es para el estado de un trabajo, que sólo ve quien lo lanzó; una respuesta
    HTTP usa ``fallo_conocido``.
    """
    if getattr(error, "para_el_operador", False):
        return str(error)
    nombre = type(error).__name__
    if nombre in _DE_UN_PROVEEDOR:
        return f"{_DE_UN_PROVEEDOR[nombre]}: {_recortar(str(error))}"
    conocido = fallo_conocido(error)
    if conocido:
        return conocido
    if isinstance(error, OSError):
        motivo = error.strerror or str(error)
        return f"El sistema de archivos rechazó la operación{_archivo(error)}: {_recortar(motivo)}"
    return f"{nombre}: {_recortar(str(error))}"


def _recortar(texto: str) -> str:
    texto = " ".join(texto.split())
    if len(texto) > _LARGO_DEL_DETALLE:
        return texto[: _LARGO_DEL_DETALLE - 1] + "…"
    return texto or "sin detalle"
