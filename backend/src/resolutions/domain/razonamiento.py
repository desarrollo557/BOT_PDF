"""Lo que el bot deduce cuando el papel no deja leer un dato: razonar con lo de al lado.

Un libro de actas no es un montón de hojas sueltas: va en orden, y sus actas
se parecen a sus vecinas. Las de grado de una misma ceremonia comparten
número y fecha -- decenas de «ACTA DE GRADO No. 03» del 10-09-1999 seguidas --,
y las de consejo van fechadas en orden. Con eso se completa lo que la lectura
dejó en blanco, sin inventar: cada regla exige que las vecinas estén de
acuerdo, y quien la aplica lo anota en observaciones para que alguien lo mire.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from datetime import date

#: Cuántas actas a cada lado se miran para corregir un año mal leído.
VECINAS_DEL_ANIO = 4


def _cifras_distintas(uno: int, otro: int) -> int:
    a, b = f"{uno:04d}", f"{otro:04d}"
    return sum(1 for x, y in zip(a, b, strict=True) if x != y)


def corregir_anio(
    leida: date, vecinas: Sequence[date], *, a_los_lados: date | None = None
) -> date | None:
    """La fecha leída con el año que dicen sus vecinas, si el error se ve claro.

    El OCR confunde cifras sueltas -- el 9 de «1997» leído 2, el 8 de «2008»
    leído 0 --, y la fecha sale «04-04-1927» en medio de una ceremonia del
    04-04-1997. Dos casos:

    * ``a_los_lados`` -- la fecha que comparten la vecina anterior y la
      siguiente -- tiene el mismo día y mes que la leída: es esa ceremonia;
    * un año de las vecinas a una sola cifra del leído, que cae entre ellas:
      es ese año.

    Con vecinas de años distintos y el mismo día -- el 14-12 de 1981 y el de
    1982 -- no se elige: devuelve ``None``, y entonces no se sabe.
    """
    if a_los_lados is not None and (a_los_lados.day, a_los_lados.month) == (
        leida.day,
        leida.month,
    ):
        return a_los_lados
    if not vecinas:
        return None
    primera, ultima = min(vecinas), max(vecinas)
    for anio in sorted({v.year for v in vecinas}, key=lambda a: abs(a - leida.year)):
        if _cifras_distintas(anio, leida.year) != 1:
            continue
        try:
            candidata = leida.replace(year=anio)
        except ValueError:
            continue
        if primera <= candidata <= ultima:
            return candidata
    return None


def vecinas_de[T](valores: Sequence[T | None], indice: int, cuantas: int = VECINAS_DEL_ANIO) -> list[T]:
    """Los valores conocidos más cercanos a ``indice``, hasta ``cuantas`` por lado."""
    antes = [v for v in valores[:indice] if v is not None][-cuantas:]
    despues = [v for v in valores[indice + 1 :] if v is not None][:cuantas]
    return [*antes, *despues]


def igual_a_los_lados[T](valores: Sequence[T | None], indice: int) -> T | None:
    """El valor de las vecinas más cercanas de cada lado, si es el mismo en las dos.

    Es la regla de la ceremonia: entre dos actas del 10-09-1999 -- la anterior
    y la siguiente que se leyeron -- un acta sin fecha legible es del
    10-09-1999. Con una sola vecina, o con dos que no coinciden, no se sabe.
    """
    anterior = next((v for v in reversed(valores[:indice]) if v is not None), None)
    siguiente = next((v for v in valores[indice + 1 :] if v is not None), None)
    if anterior is not None and anterior == siguiente:
        return anterior
    return None


def mismo_numero(uno: str | None, otro: str | None) -> bool:
    """Si dos números de acta son el mismo: «03» y «3» lo son."""
    if not uno or not otro:
        return False
    a, b = re.sub(r"\D", "", uno), re.sub(r"\D", "", otro)
    return bool(a and b) and int(a) == int(b)


_MESES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7,
    "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}
_MES_Y_ANIO = re.compile(
    r"\b(?P<mes>" + "|".join(_MESES) + r")\s+(?:DE|DEL)?\s*(?:ANO\s+)?(?P<anio>(?:19|20)\d\d)\b"
)


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.upper())


def mes_y_anio(texto: str, *, desde: int = 0, ventana: int = 400) -> tuple[int, int] | None:
    """El mes y el año de un encabezado que no dice el día: «Diciembre de 2006».

    Sólo se mira cerca del encabezado (``ventana`` letras desde ``desde``):
    más abajo el acta cita meses de otras cosas.
    """
    plano = _plano(texto)[desde : desde + ventana]
    hallado = _MES_Y_ANIO.search(plano)
    if hallado is None:
        return None
    return _MESES[hallado.group("mes")], int(hallado.group("anio"))
