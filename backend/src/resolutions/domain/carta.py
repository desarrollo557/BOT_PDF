"""La carta de un trámite: dónde empieza, cómo sigue y cuándo es sólo una copia.

Lo pidió el operador el 2026-10-21 ante UPD3102756 (67 hojas, trece trámites
del Comité de Control Social de Magangué): «cada trámite va solo, obviamente
con sus respectivos anexos, no unido a otros trámites», y «existirán trámites
en un mismo PDF duplicados, pero estudia muy bien el caso, porque la mayoría de
veces son anexos a trámites diferentes, o sea como pruebas». El corte acertaba
cinco de trece, por tres razones que este módulo resuelve con el texto:

- **La carta abre su trámite aunque no traiga sello.** Su primera hoja lleva la
  ciudad y la fecha, el «Señores…» y el «ASUNTO:». Sin sello arriba, la
  continuidad la pegaba al trámite anterior (págs. 48, 59 y 63).
- **El sello va al pie de la hoja de firmas.** La segunda hoja de la carta
  empieza a mitad de ella -- «Peticiones.», una frase en minúscula, «2) …» --
  y lleva el sello de la ventanilla junto a la firma: radica la carta, no abre
  otra (págs. 42, 49 y 57).
- **La copia de una carta anterior es una prueba.** La petición del 14 de
  noviembre vuelve a aparecer, con la copia de su sello, dentro del aviso a la
  Superintendencia (pág. 25): es la misma fecha y el mismo asunto de la pág. 11.

Aquí no se lee papel: entra el texto de las hojas y salen las señales.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from difflib import SequenceMatcher

from .fechas import fecha_de_la_pagina
from .text_distance import damerau_levenshtein

#: Cuántos renglones de arriba se miran para el encabezado de la carta.
RENGLONES_DEL_ENCABEZADO = 30
#: Cuánto se parecen dos asuntos para ser el mismo escrito. Los reclamos del
#: mes se escriben con la misma plantilla -- «Reclamo por alto consumo… del mes
#: de Marzo», «… de Abril» --, así que el parecido sólo vale con la misma fecha.
PARECIDO_DE_LA_COPIA = 0.9
#: Cuántas letras del asunto entran en la comparación: el principio, que es lo
#: que la plantilla del cliente no cambia de una copia a otra.
LARGO_DEL_ASUNTO = 90
#: Cuántas palabras lleva el renglón en minúscula para ser la frase que sigue.
PALABRAS_DE_LA_PROSA = 5

#: El renglón del asunto de la carta: «ASUNTO:», «Asunto;», «REF:», «Ref.».
_ASUNTO = re.compile(r"^\W{0,3}(?:REF(?:ERENCIA)?|ASUNTO)\s*[.:;!]{1,3}\s*(?P<resto>.*)$", re.IGNORECASE)
#: El asunto de la etiqueta del sello, que no es el de una carta: «03 RECLAMO»,
#: «06 RECLREPOSICION EN SUBSIDIO DE APELACION» (UPD2326360 pág. 12). Ningún
#: cliente empieza su asunto con la clase del trámite en dos cifras.
_ASUNTO_DEL_SELLO = re.compile(r"^[O0]?\d{1,2}\s+[A-Z]", re.IGNORECASE)
#: A quién va dirigida.
_SALUDO = re.compile(r"^\W*(?:SE[ÑN]OR(?:ES|A|ITA)?|DOCTOR(?:A)?|GERENTE|DR\.|SRES?\.)\b", re.IGNORECASE)
#: Cómo empieza la hoja que sigue a la carta: la sección de lo que pide o de lo
#: que cuenta. Con lo que la OCR hace de la palabra: «PETiCfONES».
_SECCION = re.compile(r"^(?:PETI\w{1,6}|PRETENSI\w{1,6}|HECHOS|FUNDAMENTOS?\b|SOLICITUDES)\b")
#: Un numeral del cuerpo: «2) porque…», «3. Que la empresa…», «b) …».
_NUMERAL = re.compile(r"^(?:\d{1,2}|[a-h])\s*[).-]\s*\S")


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.upper()).strip()


def _renglones(texto: str) -> list[str]:
    return [r.strip() for r in (texto or "").splitlines() if r.strip()][:RENGLONES_DEL_ENCABEZADO]


def _letras(renglon: str) -> int:
    return sum(c.isalpha() for c in renglon)


def _renglon_del_asunto(renglones: list[str]) -> tuple[int, str] | None:
    """Dónde está el asunto de la carta y qué dice, con el renglón que lo continúa."""
    for i, renglon in enumerate(renglones):
        hallado = _ASUNTO.match(renglon)
        if hallado is None:
            continue
        resto = hallado.group("resto").strip()
        if _ASUNTO_DEL_SELLO.match(_plano(resto)):
            continue
        # Con el renglón que lo continúa, siempre: el de los reclamos del mes
        # parte el asunto justo antes del mes -- «… en la factura del mes de /
        # Marzo y cobro…» --, y sin él dos meses distintos parecían una copia.
        siguiente = renglones[i + 1] if i + 1 < len(renglones) else ""
        asunto = f"{resto} {siguiente}".strip()
        if _letras(asunto) >= 12:
            return i, asunto
    return None


def abre_carta(texto: str) -> bool:
    """Si la hoja es la primera de una carta: a quién va o de cuándo es, y su asunto.

    El asunto solo no basta -- la etiqueta del sello también dice «Asunto: 03
    RECLAMO» --: antes de él tiene que ir el saludo o la fecha de la carta. La
    hoja que sólo trae el encabezado, sin asunto -- la pág. 15 de UPD3102756,
    una primera hoja que se imprimió en blanco --, no abre nada.
    """
    renglones = _renglones(texto)
    hallado = _renglon_del_asunto(renglones)
    if hallado is None:
        return False
    antes = renglones[: hallado[0]]
    if any(_SALUDO.match(r) for r in antes):
        return True
    return fecha_de_la_pagina("\n".join(antes)) is not None


def continua_la_carta(texto: str) -> bool:
    """Si la hoja empieza a mitad de una carta: es la segunda hoja de un escrito.

    Su primer renglón legible es la sección de las peticiones o de los hechos,
    un numeral del cuerpo o una frase que empieza en minúscula. El sello que
    traiga va al pie, junto a la firma, y radica la carta que continúa.
    """
    if abre_carta(texto):
        return False
    for renglon in _renglones(texto)[:4]:
        if _letras(renglon) < 4:
            # El ruido de arriba: ««», «*», un trozo del sello.
            continue
        primero = renglon.lstrip(" \"'«“¿¡-–—•·*")
        if _SECCION.match(_plano(primero)) or _NUMERAL.match(primero):
            return True
        # La frase en minúscula tiene que ser prosa: el «afmia» del logo que la
        # OCR deja arriba de una factura también empieza en minúscula.
        return primero[:1].islower() and len(re.findall(r"[^\W\d_]{2,}", primero)) >= PALABRAS_DE_LA_PROSA
    return False


def asunto_de_la_carta(texto: str) -> str | None:
    """El asunto de la primera hoja de una carta, plano, o ``None`` si no lo trae."""
    hallado = _renglon_del_asunto(_renglones(texto))
    return _plano(hallado[1]) if hallado else None


def huella_de_la_carta(texto: str) -> tuple[str, str | None] | None:
    """Lo que hace que dos cartas sean la misma: su asunto y su fecha.

    ``None`` si la hoja no abre una carta. La fecha es la del encabezado, la que
    va antes del asunto; el asunto, sin lo que no es letra, que es donde las dos
    lecturas de una misma copia difieren.
    """
    if not abre_carta(texto):
        return None
    renglones = _renglones(texto)
    hallado = _renglon_del_asunto(renglones)
    if hallado is None:
        return None
    fecha = fecha_de_la_pagina("\n".join(renglones[: hallado[0]]))
    asunto = re.sub(r"[^A-Z]+", "", _plano(hallado[1]))[:LARGO_DEL_ASUNTO]
    return asunto, fecha.isoformat() if fecha else None


def es_la_misma_carta(una: tuple[str, str | None], otra: tuple[str, str | None]) -> bool:
    """Si dos huellas son de la misma carta: la misma fecha y casi el mismo asunto.

    Sin fecha en alguna de las dos, sólo el mismo asunto letra por letra: la
    plantilla del cliente repite el asunto de un mes a otro y sólo cambia el mes.
    """
    asunto, fecha = una
    otro_asunto, otra_fecha = otra
    if not asunto or not otro_asunto:
        return False
    if fecha and otra_fecha:
        return fecha == otra_fecha and SequenceMatcher(None, asunto, otro_asunto).ratio() >= PARECIDO_DE_LA_COPIA
    return asunto == otro_asunto


#: Lo que la OCR pone por una cifra en medio de un número: «202380Ú4468522».
_LETRA_POR_CIFRA = (
    (re.compile(r"(?<=\d)[OoÓóÚúUuDQ](?=\d)"), "0"),
    (re.compile(r"(?<=\d)[Il|!](?=\d)"), "1"),
    (re.compile(r"(?<=\d)[Ss](?=\d)"), "5"),
    (re.compile(r"(?<=\d)B(?=\d)"), "8"),
)


def _cifras(texto: str) -> list[str]:
    texto = re.sub(r"(?<=\d)[\s.\-]+(?=\d)", "", texto or "")
    for letra, cifra in _LETRA_POR_CIFRA:
        texto = letra.sub(cifra, texto)
    return re.findall(r"\d{10,16}", texto)


def cita_el_numero(texto: str, numero: str | None) -> bool:
    """Si el texto cita ese radicado, con una cifra de más o de menos.

    La carta que avisa a la empresa del radicado que le dio la Superintendencia
    lo copia en su cuerpo: «quedó radicada… con Radicado No.202380Ú4468522», y
    la OCR se come una cifra en la Ú (UPD3102756 pág. 23 contra la 24).
    """
    if not numero:
        return False
    return any(damerau_levenshtein(numero, cifras, ceiling=1) <= 1 for cifras in _cifras(texto))


def numeros_del_radicado(texto: str) -> Iterable[str]:
    """Las cifras largas de una hoja: los números de radicado que trae."""
    return _cifras(texto)
