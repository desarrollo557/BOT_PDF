"""Dos lecturas de cada dato que identifica un documento, y qué hacer cuando no coinciden.

Lo pidió el operador el 2026-10-30, para todas las habilidades: «que se lea muy
bien cada área: nombre, cédula, todo». La IA de pago es determinista y, a página
entera, se equivoca igual en todas las apariciones de un nombre manuscrito
(«IANACHO» por CAMACHO en la ficha y en la hoja de notas). Una segunda lectura
de **otra imagen** -- el renglón del campo, recortado y ampliado -- se equivoca
en otros sitios, y así los errores se ven.

Cada habilidad describe dónde está cada campo con una :class:`Franja`; el
adaptador del mosaico la recorta y la lee, diez por página facturada; y aquí se
decide entre las dos lecturas:

* Iguales, o una sola: vale la que hay.
* Distintas: se queda la de la página entera y el dato va a revisión con las
  dos lecturas, para que alguien lo mire en el papel.

Medido sobre UPD3859718 contra 24 fichas leídas a ojo (2026-10-30): el renglón
ampliado lee **peor** que la página entera -- cambió dos cédulas buenas, y en
los nombres dio 33 alarmas en 85 fichas, casi todas suyas («GENITA» por
ACUÑA) --, pero cada discrepancia de cédula señala una cifra en riesgo. Por
eso es un detector y no un corrector, y sólo para los números.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True, slots=True)
class Franja:
    """Dónde está un campo en su formulario, para recortarlo y leerlo otra vez."""

    #: Cómo se dice el campo en la nota de revisión: «el nombre», «la cédula».
    campo: str
    #: Las leyendas impresas del renglón, en mayúsculas y sin tildes, con que
    #: la capa de texto dice a qué altura está.
    leyendas: tuple[str, ...]
    #: El rótulo impreso, como expresión regular, con que se reparte la
    #: respuesta del mosaico entre sus franjas.
    rotulo: str
    #: Alto de la franja y margen por arriba, en fracción de la altura de la hoja.
    alto: float
    margen: float


def conciliar_numero(principal: str | None, segunda: str | None, campo: str) -> tuple[str | None, str | None]:
    """El número que queda -- cédula, tarjeta -- y, si las lecturas discrepan, por qué revisarlo."""
    if not segunda or segunda == principal:
        return principal, None
    if not principal:
        return segunda, None
    return principal, f"{campo} se leyó {principal} en la página y {segunda} en el renglón ampliado"


#: Cuánto se parecen dos palabras para tomarlas por la misma, mal leída.
PARECIDO_MINIMO = 0.6


def votar_nombre(
    principal: str | None, otras: Sequence[str | None], conocidas: Collection[str] = ()
) -> tuple[str | None, str | None]:
    """El nombre que dicen la mayoría de las lecturas, y por qué revisarlo si no hay mayoría.

    Las lecturas son la de la página entera (``principal``, apellidos primero)
    y las de cada zona donde la ficha escribe el nombre. Si dos dicen las
    mismas palabras, vale eso, con el orden de la principal o, si ella no es
    de la mayoría, el de la zona de Observaciones (apellidos primero). Si no,
    se vota palabra por palabra: para cada palabra de la principal, la grafía
    que repiten las otras; con un empate, la que está en la lista de nombres
    conocidos. Lo que no se pueda votar se queda como lo leyó la principal, y
    a revisión.
    """
    lecturas = [lectura for lectura in (principal, *otras) if lectura]
    if not lecturas:
        return None, None
    if len(lecturas) == 1:
        return lecturas[0], None
    conjuntos = Counter(frozenset(lectura.split()) for lectura in lecturas)
    mayoria, votos = conjuntos.most_common(1)[0]
    if votos >= 2:
        if principal and frozenset(principal.split()) == mayoria:
            return principal, None
        return next(lectura for lectura in reversed(lecturas) if frozenset(lectura.split()) == mayoria), None
    base = (principal or lecturas[0]).split()
    resto = [lectura.split() for lectura in lecturas if lectura != (principal or lecturas[0])]
    votado: list[str] = []
    dudosa = False
    for palabra in base:
        candidatas = [palabra]
        for otra in resto:
            parecida = max(otra, key=lambda p: SequenceMatcher(None, palabra, p).ratio(), default=None)
            if parecida and SequenceMatcher(None, palabra, parecida).ratio() >= PARECIDO_MINIMO:
                candidatas.append(parecida)
        cuenta = Counter(candidatas).most_common()
        if len(cuenta) > 1 and cuenta[0][1] == cuenta[1][1]:
            empatadas = [p for p, n in cuenta if n == cuenta[0][1]]
            conocida = [p for p in empatadas if p in conocidas]
            elegida = conocida[0] if len(conocida) == 1 else palabra
            dudosa = dudosa or len(conocida) != 1
        else:
            elegida = cuenta[0][0]
        votado.append(elegida)
    nombre = " ".join(votado)
    if dudosa:
        leidas = " / ".join(f"«{lectura}»" for lectura in lecturas)
        return nombre, f"el nombre se leyó distinto en cada zona: {leidas}"
    return nombre, None


#: Cuántas lecturas gratuitas que coinciden pesan más que la IA que discrepa.
APOYOS_CONTRA_LA_IA = 2


def decidir_con_la_ia(
    campo: str,
    actual: object | None,
    de_la_ia: object | None,
    apoyos: int,
    *,
    igual=lambda a, b: a == b,
    mostrar=str,
) -> tuple[object | None, str | None]:
    """Lo que se entrega de un campo cuando la IA leyó también la hoja, y por qué revisarlo.

    Con «OCR + IA», la IA lee toda hoja que da una fila, no sólo las que traen
    un hueco: un número mal leído pero completo salía sin aviso (Odontología y
    Secretaría, 2026-10-31: «que el bot se asegure de que lo que entrega sí es
    lo que está en el PDF»).

    * La IA no leyó nada: queda lo del OCR.
    * El OCR no leyó nada: queda lo de la IA.
    * Coinciden: confirmado, sin nota.
    * Discrepan: gana la IA, salvo que ``apoyos`` lecturas gratuitas
      independientes digan lo mismo que el OCR. Y en los dos casos va a
      revisión con las dos lecturas.
    """
    if de_la_ia is None:
        return actual, None
    if actual is None:
        return de_la_ia, None
    if igual(actual, de_la_ia):
        return actual, None
    if apoyos >= APOYOS_CONTRA_LA_IA:
        return actual, (
            f"{campo}: el OCR leyó {mostrar(actual)} en {apoyos} lecturas y la IA "
            f"{mostrar(de_la_ia)}; se dejó {mostrar(actual)}: revíselo en el papel"
        )
    return de_la_ia, (
        f"{campo}: el OCR leyó {mostrar(actual)} y la IA {mostrar(de_la_ia)}; "
        "se dejó lo de la IA: revíselo en el papel"
    )
