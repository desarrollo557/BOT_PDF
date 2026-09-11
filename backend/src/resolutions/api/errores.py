"""Cómo se le cuenta al operador que un parámetro llegó mal.

FastAPI describe cada error de validación como pydantic lo emite: una lista de
diccionarios con `loc`, `msg`, `type` y `ctx`, en inglés. Está pensada para
que la lea un programa. La pantalla de este sistema enseña `detail` tal cual
en un párrafo, así que lo que veía el operador era «[object Object]».

Lo que hay aquí convierte esa lista en una oración en español que dice tres
cosas y nada más: qué parámetro, qué se esperaba de él y qué llegó.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

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
