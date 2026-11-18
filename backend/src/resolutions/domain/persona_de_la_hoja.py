"""La persona que firma una hoja: su nombre tras «Yo,» y su cédula, para casar la Habeas Data con su acuerdo.

Lo enseñó el operador el 2026-11-18 con 4100921 (UPD2985187): dos Habeas Data
al principio y dos acuerdos de pago detrás. Puestas «con el acuerdo más
cercano», la de Alfonso Velilla **Corrales** cayó en el acuerdo de Luis Alfonso
Velilla **Arias**, y el de Corrales se quedó sin ella. Él lo resolvió «yendo a
los nombres». La cédula lo dice mejor que el nombre: los dos se llaman Alfonso
Velilla, pero 9265245 y 1051655090 no se parecen. El nombre manda sólo por lo
que distingue a cada uno.

Aquí no se lee papel: entra el texto de la hoja, de la capa o de la IA.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

#: «Yo, Alfonso Velilla Corrales, identificado con la cédula…»: el nombre entre
#: «Yo» y «identificado».
_YO = re.compile(r"\bYO\W{0,3}\s*(.{3,80}?)\s*,?\s*IDENTIFICAD", re.DOTALL)
#: La cédula tras su rótulo: «cédula de ciudadanía No. 9265245», «C.C. 1.051.655.090».
_CEDULA = re.compile(
    r"(?:C[EÉ]DULA(?:\s+DE\s+CIUDADAN[IÍ]A)?|\bC\W?\s?C\W?)\W{0,4}\s*(?:N[O0°º]\W{0,2}\s*)?(\d[\d.,\s]{4,16}\d)"
)
#: Lo que no es un nombre aunque vaya en el renglón.
_NO_ES_NOMBRE = frozenset({"DE", "LA", "DEL", "LOS", "LAS", "CON", "COMO", "MAYOR", "EDAD", "SENOR", "SENORA"})
#: Cuántas cifras hacen una cédula, y cuántas tiene que compartir el principio de dos lecturas.
CIFRAS_DE_UNA_CEDULA = (6, 11)


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode()
    return sin_tildes.upper()


@dataclass(frozen=True, slots=True)
class Persona:
    nombre: frozenset[str]
    cedulas: frozenset[str]

    @property
    def vacia(self) -> bool:
        return not self.nombre and not self.cedulas


def persona_de_la_hoja(texto: str | None) -> Persona:
    """El nombre (sus palabras) y las cédulas que una hoja dice de quien la firma."""
    plano = _plano(texto or "")
    nombre: set[str] = set()
    if hallado := _YO.search(plano):
        nombre = {p for p in re.findall(r"[A-Z]{3,}", hallado.group(1)) if p not in _NO_ES_NOMBRE}
    cedulas = {
        cifras
        for hallado in _CEDULA.finditer(plano)
        if CIFRAS_DE_UNA_CEDULA[0] <= len(cifras := re.sub(r"\D", "", hallado.group(1))) <= CIFRAS_DE_UNA_CEDULA[1]
    }
    return Persona(frozenset(nombre), frozenset(cedulas))


def _misma_cedula(a: str, b: str) -> bool:
    """La misma cédula, aunque una lectura la deje sin sus últimas cifras: «1051655» y «1051655090»."""
    corta, larga = sorted((a, b), key=len)
    return len(corta) >= CIFRAS_DE_UNA_CEDULA[0] and larga.startswith(corta)


def de_quien_es(persona: Persona, candidatas: Mapping[int, Persona]) -> int | None:
    """De cuál de las ``candidatas`` es la ``persona``, si una sola lo es sin duda; si no, ``None``.

    Primero la cédula: la que comparte con una sola. Si no, el nombre, pero
    sólo con las palabras que distinguen a cada candidata de las demás: «VELILLA»
    no dice nada si las dos lo llevan.
    """
    por_cedula = [
        clave
        for clave, otra in candidatas.items()
        if any(_misma_cedula(a, b) for a in persona.cedulas for b in otra.cedulas)
    ]
    if len(por_cedula) == 1:
        return por_cedula[0]
    if len(por_cedula) > 1:
        return None
    propias = {
        clave: otra.nombre - frozenset().union(*(o.nombre for k, o in candidatas.items() if k != clave))
        for clave, otra in candidatas.items()
    }
    por_nombre = [clave for clave, palabras in propias.items() if palabras & persona.nombre]
    return por_nombre[0] if len(por_nombre) == 1 else None


def la_persona_del_grupo(paginas: Sequence[int], persona_de) -> Persona:
    """La persona de un grupo de hojas: la suma de lo que dice cada una."""
    nombre: set[str] = set()
    cedulas: set[str] = set()
    for pagina in paginas:
        persona = persona_de(pagina)
        if persona is not None:
            nombre |= persona.nombre
            cedulas |= persona.cedulas
    return Persona(frozenset(nombre), frozenset(cedulas))
