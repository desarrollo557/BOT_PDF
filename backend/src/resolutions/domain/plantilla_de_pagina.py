"""Qué plantilla es una página, por lo que trae impreso: la más evidente gana.

Lo propuso el operador el 2026-10-16: que cada página diga qué plantilla es y
que la habilidad llame al componente que sabe leerla. Un PDF de resoluciones
de rectoría no es una sola cosa: trae la resolución, y detrás lo que la
soporta -- la resolución con que un decano la pidió, el oficio que la
acompaña, las tablas del presupuesto, los listados de graduandos --, y cada
página se parte o se lee distinto según cuál sea.

La evidencia es tipográfica y gratis: está en la capa de texto o en lo que ya
leyó el OCR. Ninguna plantilla se adivina por el nombre del archivo ni por la
página vecina; si ninguna es evidente, la página es «cuerpo» y la habilidad
sigue como siempre. Medido en la carpeta RESOLUCIONES DE RECTORIA 3220 - 3259:

- «RESOLUCIÓN No. 00316 DE 2025 / EL RECTOR DE LA UNIVERSIDAD DE CARTAGENA»:
  resolución de rectoría.
- «RESOLUCIÓN No. 006 / EL DECANO DE LA FACULTAD DE CIENCIAS SOCIALES Y
  EDUCACION»: resolución de facultad, que en un libro de rectoría es el
  soporte de la resolución que le responde.
- «Cordial saludo», «Atentamente», «Asunto:»: un oficio.
- Renglones de cifras -- códigos presupuestales, valores, cédulas --: una tabla.
- «CÓDIGO: FO-DO/PC-012 / VERSIÓN: 02» y una columna de rótulos terminados en
  dos puntos: un formulario. El de solicitud de apertura de un programa de
  posgrado dice en un campo «Resolución No.002086 de 1984», y ese campo abría
  una resolución que se quedaba con 70 páginas de las 00449 a la 00451.

Un encabezado de resolución en la cabecera de la hoja manda sobre todo lo
demás: hay copias de resoluciones de rectoría impresas sobre un formato con
código (la 02852 de 2024, «CÓDIGO: FO-TH/SE-021»), y siguen siendo resoluciones.

Nada aquí importa nada de fuera del dominio.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class Plantilla(StrEnum):
    RESOLUCION_DE_RECTORIA = "resolución de rectoría"
    RESOLUCION_DE_FACULTAD = "resolución de facultad"
    OFICIO = "oficio"
    FORMULARIO = "formulario"
    TABLA = "tabla"
    CUERPO = "cuerpo"
    ILEGIBLE = "ilegible"


#: Las plantillas que, detrás de una resolución abierta, son su soporte y no
#: abren nada: lo que traigan de «RESOLUCIÓN No.» es la de un decano o una cita.
SOPORTES = frozenset(
    {Plantilla.RESOLUCION_DE_FACULTAD, Plantilla.OFICIO, Plantilla.FORMULARIO}
)


@dataclass(frozen=True, slots=True)
class Evidencia:
    """La plantilla que la página muestra, con qué la muestra y cuánto."""

    plantilla: Plantilla
    puntos: int = 0
    senales: tuple[str, ...] = ()

    @property
    def es_soporte(self) -> bool:
        return self.plantilla in SOPORTES


#: Cuántos renglones de arriba se miran para el encabezado. Un encabezado va en
#: la cabecera de la hoja; más abajo sólo hay citas.
RENGLONES_DE_CABECERA = 15
#: Cuántos renglones debajo del encabezado puede estar quien la expide.
RENGLONES_HASTA_EL_EMISOR = 5
#: Por debajo de esto la página no dice nada legible.
CARACTERES_LEGIBLES = 40
#: Cuántos renglones necesita una tabla, y qué parte de ellos tienen que ser
#: cifras.
RENGLONES_DE_TABLA = 15
PROPORCION_DE_CIFRAS = 0.5

_ENCABEZADO = re.compile(r"^\W{0,6}RESOLUCI[O0]N\s*N\W{0,3}[O0Rº°]?\W{0,3}\s*\d")
_RECTOR = re.compile(r"^\W{0,4}(EL|LA)\s+(SENOR\s+|SENORA\s+)?(VICE)?RECTORA?\b")
_DECANO = re.compile(
    r"^\W{0,4}((EL|LA)\s+DECAN[OA]|EL\s+CONSEJO\s+DE\s+(LA\s+)?FACULTAD|LA\s+DIRECTORA?\s+DEL?\s+PROGRAMA"
    r"|EL\s+DIRECTOR\s+DEL?\s+PROGRAMA)\b"
)
_OFICIO = (
    ("saludo", re.compile(r"\bCORDIAL(ES)?\s+SALUDOS?\b")),
    ("despedida", re.compile(r"^\W{0,4}(ATENTAMENTE|CORDIALMENTE|FRATERNALMENTE)\b")),
    ("asunto", re.compile(r"^\W{0,4}(ASUNTO|REFERENCIA|REF)\s*[:.]")),
    ("tratamiento", re.compile(r"^\W{0,4}(RESPETAD[OA]S?|APRECIAD[OA]S?|ESTIMAD[OA]S?)\b")),
    ("destinatario", re.compile(r"^\W{0,4}(SENOR(A|ES)?|DOCTOR(A)?|DRA?\.)\s*$")),
)
_CODIGO_DE_FORMATO = re.compile(r"^\W{0,4}CODIGO\s*[:.]?\s*F[O0]\s*-")
_VERSION_DEL_FORMATO = re.compile(r"^\W{0,4}VERSION\s*[:.]")
#: Un rótulo de formulario: corto, en mayúsculas en el papel, y terminado en dos
#: puntos o punto y coma -- «UBICACIÓN DEL PROGRAMA:», «NORMA INTERNA DE
#: CREACIÓN;» --. Los de una resolución no cuentan.
_ROTULO = re.compile(r"^[A-Z][A-Z0-9 ().,/-]{3,58}[:;]$")
_ROTULOS_DE_RESOLUCION = ("CONSIDERANDO", "RESUELVE", "VISTO", "VISTOS")
#: Cuántos rótulos hacen un formulario.
ROTULOS_DE_UN_FORMULARIO = 4


def _plegado(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto)
    return "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn").upper()


def _es_un_campo(renglones: list[str], encabezado: int) -> bool:
    """Si el «encabezado» va dentro de un formulario: tras su código y sus rótulos.

    El orden es lo que separa los dos casos reales. La copia de la 02852 de 2024
    abre la hoja con «Resolución No. 02852 de 2024» y lleva el código del
    formato debajo; el formulario de apertura de un posgrado lleva arriba
    «CÓDIGO: FO-DO/PC-012», «VERSIÓN: 02» y sus rótulos, y la resolución sale
    después, como el valor del campo «NORMA INTERNA DE CREACIÓN».
    """
    arriba = renglones[:encabezado]
    con_codigo = any(_CODIGO_DE_FORMATO.match(r) for r in arriba)
    rotulos = sum(
        1 for r in arriba if _ROTULO.match(r) and not r.startswith(_ROTULOS_DE_RESOLUCION)
    )
    return con_codigo and rotulos >= 2


def plantilla_de(texto: str) -> Evidencia:
    """La plantilla más evidente de la página, o «cuerpo» si ninguna lo es."""
    if len(texto.strip()) < CARACTERES_LEGIBLES:
        return Evidencia(Plantilla.ILEGIBLE, 1, ("sin capa de texto legible",))

    renglones = [_plegado(r).strip() for r in texto.splitlines() if r.strip()]
    evidencias: list[Evidencia] = []

    encabezado = next(
        (i for i, r in enumerate(renglones[:RENGLONES_DE_CABECERA]) if _ENCABEZADO.match(r)), None
    )
    if encabezado is not None and _es_un_campo(renglones, encabezado):
        # «Resolución No.002086 de 1984» debajo del código del formato y de sus
        # rótulos no encabeza nada: es lo que se escribió en un campo.
        encabezado = None
    if encabezado is not None:
        # Lo que abre la hoja manda: una resolución impresa sobre un formato o
        # que cita un oficio sigue siendo una resolución.
        debajo = renglones[encabezado + 1 : encabezado + 1 + RENGLONES_HASTA_EL_EMISOR]
        decano = next((r for r in debajo if _DECANO.match(r)), None)
        rector = next((r for r in debajo if _RECTOR.match(r)), None)
        if decano is not None and rector is None:
            return Evidencia(Plantilla.RESOLUCION_DE_FACULTAD, 3, ("encabezado", decano[:60]))
        senales = ("encabezado", rector[:60]) if rector else ("encabezado",)
        return Evidencia(Plantilla.RESOLUCION_DE_RECTORIA, 3 if rector else 2, senales)

    codigo = any(_CODIGO_DE_FORMATO.match(r) for r in renglones[:RENGLONES_DE_CABECERA])
    version = any(_VERSION_DEL_FORMATO.match(r) for r in renglones[:RENGLONES_DE_CABECERA])
    rotulos = sum(
        1 for r in renglones if _ROTULO.match(r) and not r.startswith(_ROTULOS_DE_RESOLUCION)
    )
    if (codigo and version) or rotulos >= ROTULOS_DE_UN_FORMULARIO:
        senales = tuple(
            nombre
            for nombre, hay in (("código del formato", codigo), ("versión", version), (f"{rotulos} rótulos", rotulos))
            if hay
        )
        evidencias.append(
            Evidencia(
                Plantilla.FORMULARIO,
                1 + 2 * (codigo and version) + 2 * (rotulos >= ROTULOS_DE_UN_FORMULARIO),
                senales,
            )
        )

    del_oficio = tuple(
        nombre for nombre, patron in _OFICIO if any(patron.search(r) for r in renglones)
    )
    if "saludo" in del_oficio or len(del_oficio) >= 2:
        evidencias.append(Evidencia(Plantilla.OFICIO, 1 + len(del_oficio), del_oficio))

    if len(renglones) >= RENGLONES_DE_TABLA:
        con_cifras = sum(
            1 for r in renglones if sum(map(str.isdigit, r)) >= max(1, len(r) // 3)
        )
        if con_cifras / len(renglones) >= PROPORCION_DE_CIFRAS:
            evidencias.append(
                Evidencia(Plantilla.TABLA, 1, (f"{con_cifras} de {len(renglones)} renglones de cifras",))
            )

    if not evidencias:
        return Evidencia(Plantilla.CUERPO)
    # La más evidente; a igualdad, la que va primero: un encabezado gana a un
    # oficio que cita una resolución, porque lo que abre la hoja es él.
    return max(evidencias, key=lambda e: e.puntos)


def resumen(evidencias: Sequence[Evidencia]) -> dict[str, int]:
    """Cuántas páginas de cada plantilla, para el informe."""
    cuenta: dict[str, int] = {}
    for evidencia in evidencias:
        cuenta[str(evidencia.plantilla)] = cuenta.get(str(evidencia.plantilla), 0) + 1
    return cuenta
