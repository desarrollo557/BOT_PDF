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

from dataclasses import dataclass


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
