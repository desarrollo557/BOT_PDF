"""El folio escrito a mano en la esquina de cada hoja de una caja de correspondencia.

Lo dictó el operador el 2026-11-12 sobre 7975593: «asegúrate de que cuando
exista el folio, o el número de folios, el bot lo tenga en cuenta para dividir e
inventariar». La oficina folia a mano, arriba a la derecha, cada hoja de lo que
recibe: el escrito y sus anexos van 1, 2, 3… hasta el «No. DE FOLIOS» del sello,
y el escrito siguiente vuelve a empezar en 1. Medido en UPD2460819 con la IA:
29 de 30 esquinas bien leídas, y la numeración cuadra con los sellos.

Por eso **el folio manda** (lo eligió el operador): la hoja cuyo folio sigue al
de la anterior es del mismo escrito aunque traiga un sello «Recibido» -- la
copia anexa de otro radicado lleva su folio intermedio --, y la hoja con el
folio 1 detrás de un folio mayor abre uno nuevo.

Aquí no se lee papel: entran los folios leídos, por hoja.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

#: Dónde va el folio en la hoja (x0, y0, x1, y1, en fracción de la página): el
#: número solo, arriba a la derecha. Más ancha cogía el logo y la caja del NIC
#: de las facturas, y el OCR de pago devolvía una tabla con las filas corridas
#: -- el «1» de la hoja 95 caía en la 94 -- (UPD2460819, 2026-11-12).
BANDA_DEL_FOLIO_DE_LA_CAJA = (0.82, 0.0, 0.995, 0.075)
#: Cuánto puede saltar la numeración sin dejar de ser la misma: el folio 5 que
#: falta en el escaneo (03 de 7975593), el 32 que el funcionario se saltó.
SALTO_DE_FOLIO = 2
#: Cuántas hojas sin folio puede haber entre dos foliadas del mismo escrito: el
#: reverso de una factura escaneada por las dos caras no se folia.
HOJAS_SIN_FOLIO = 2


@dataclass(frozen=True, slots=True)
class Foliacion:
    """Lo que la numeración a mano dice de cada costura."""

    #: Las hojas que siguen al escrito de la hoja de delante: su folio continúa
    #: el anterior, o son el reverso sin folio entre dos que continúan.
    continua: frozenset[int] = frozenset()
    #: Las hojas que abren un escrito: folio 1 detrás de un folio mayor.
    abre: frozenset[int] = frozenset()
    #: El folio leído de cada hoja.
    folios: Mapping[int, int] | None = None

    def motivo(self, pagina: int) -> str:
        """Por qué la hoja continúa o abre, para el revisor y la auditoría."""
        folios = self.folios or {}
        if pagina in self.abre:
            return f"la hoja {pagina} lleva el folio 1: abre un escrito"
        anterior = max((p for p in folios if p < pagina), default=None)
        if pagina in folios and anterior is not None:
            return f"el folio {folios[pagina]} de la hoja {pagina} sigue al {folios[anterior]} de la hoja {anterior}"
        return f"la hoja {pagina} va sin folio entre dos hojas del mismo escrito"


#: Hasta cuántas hojas después de un «1» se busca que la numeración del escrito
#: vuelva: la copia anexa que trae su foliación vieja (1, 2, 3, 4) en medio.
HOJAS_DE_UNA_COPIA = 20


def _lecturas(folio: int) -> set[int]:
    """El folio leído y lo que sería con cada «7» leído por un «1»: el 1 a mano con su rasgo se lee 7.

    En UPD2460819 la IA leyó «77», «78», «79» por 17, 18, 19 y «27», «37» por
    21, 31 (2026-11-12).
    """
    cifras = str(folio)
    posiciones = [i for i, c in enumerate(cifras) if c == "7"]
    salida = {folio}
    for mascara in range(1, 2 ** len(posiciones)):
        nuevas = list(cifras)
        for bit, posicion in enumerate(posiciones):
            if mascara >> bit & 1:
                nuevas[posicion] = "1"
        salida.add(int("".join(nuevas)))
    return salida


def _encaja(folios: Mapping[int, int], anterior: int, pagina: int) -> bool:
    """Si el folio de ``pagina`` sigue al de ``anterior``: uno más por hoja, con el salto que se perdona."""
    distancia = pagina - anterior
    if distancia > HOJAS_SIN_FOLIO + 1:
        return False
    return any(
        suyo >= 2 and 0 <= suyo - de_delante <= distancia + SALTO_DE_FOLIO - 1
        for suyo in _lecturas(folios[pagina])
        for de_delante in _lecturas(folios[anterior])
    )


def foliacion_del_escrito(
    folios: Mapping[int, int], paginas: Iterable[int], abren_solas: Iterable[int] = ()
) -> Foliacion:
    """Qué hojas continúan el escrito de delante y cuáles abren uno, por su folio a mano.

    Sólo cuenta la numeración que se confirma a sí misma:

    - **continúa** la hoja cuyo folio sigue al de la foliada anterior -- uno más
      por hoja, con un salto de ``SALTO_DE_FOLIO`` --, con a lo sumo
      ``HOJAS_SIN_FOLIO`` hojas sin folio en medio, que continúan también. Un
      folio mal leído en medio no la rompe: si el siguiente encaja con el de
      antes, el mal leído se salta (UPD2460819 hoja 134, «47» por «41»);
    - **abre** la hoja con el folio 1 detrás de una foliada con 2 o más, salvo
      que la numeración del escrito vuelva poco después: entonces el 1, 2, 3…
      es la foliación vieja de una copia anexa, y continúa (hojas 207-210, con
      la 211 en el folio 18 detrás de la 205 en el 12). Ni abre el «1» mal
      leído en medio (detrás viene el 13);
    - **abre** también, cuando la numeración de un escrito se acaba, la hoja
      siguiente sin folio que abre por sí misma (``abren_solas``: una carta, un
      sello): la solicitud de la hoja 175 detrás del folio 26 de la queja. El
      reverso sin folio de un recibo de luz -- un folio, dos caras -- no abre
      nada por sí mismo y se queda con su escrito (el operador, 2026-11-12).
    """
    orden = sorted(paginas)
    foliadas = [p for p in orden if folios.get(p)]
    continua: set[int] = set()
    abre: set[int] = set()
    for indice, pagina in enumerate(foliadas):
        if indice == 0:
            continue
        anterior = foliadas[indice - 1]
        if folios[pagina] == 1:
            if folios[anterior] < 2 or pagina - anterior > HOJAS_SIN_FOLIO + 1:
                continue
            vuelve = next(
                (
                    r
                    for r in foliadas[indice + 1 :]
                    if r - anterior <= HOJAS_DE_UNA_COPIA
                    and folios[r] > folios[anterior]
                    and abs((folios[r] - folios[anterior]) - (r - anterior)) <= SALTO_DE_FOLIO
                ),
                None,
            )
            if vuelve is not None:
                continua.update(range(anterior + 1, vuelve + 1))
                continue
            siguiente = foliadas[indice + 1] if indice + 1 < len(foliadas) else None
            if siguiente is None or siguiente - pagina > HOJAS_SIN_FOLIO + 1 or folios[siguiente] <= 3:
                abre.add(pagina)
        elif _encaja(folios, anterior, pagina):
            continua.update(range(anterior + 1, pagina + 1))
        elif indice >= 2 and _encaja(folios, foliadas[indice - 2], pagina):
            continua.update(range(foliadas[indice - 2] + 1, pagina + 1))
    # El cierre: tras la última hoja de una numeración confirmada -- una hoja
    # que sigue a la anterior, no un número suelto: el «11» mal leído en la
    # constancia de la 303 abría la Habeas Data de la 304 --, la que abre por
    # sí misma. Sin folio, o con uno que no sigue: la 175 se leyó «6100».
    for pagina in sorted(set(abren_solas)):
        if pagina - 1 in continua and pagina not in continua:
            abre.add(pagina)
    return Foliacion(continua=frozenset(continua - abre), abre=frozenset(abre), folios=dict(folios))
