"""El orden de las hojas de un libro por el folio impreso de su esquina, no por el del escaneo.

UPD3859802 (actas de grado colectivas de Enfermería, 1980-2012; 2026-11-13):
el libro se escaneó con hojas fuera de su sitio. Las doce primeras del PDF son
los folios 42, 41, 46, 45, 43, 44, 51, 52, 56, 55, 58 y 57 --hojas sueltas
que alguien volvió a meter por pares--, y la 98 (folio 40) abre el Acta 01 de
1988, cuya lista sigue en la hoja 2 (folio 41). Repartido en el orden del
escaneo, la hoja 1 soldaba cuatro actas en una y la del Acta 01 salía sin 30
de sus 36 graduados.

El folio impreso lo trae el texto que lee la IA (``folio_del_texto``). Se
recorre el libro como el escaneo, salvo donde el folio salta: allí se busca la
hoja que lleva el folio siguiente **y que también está fuera de su sitio** --
la que no sigue por folio a la que tiene delante--, y si hay una sola, el libro
sigue por ella. Una hoja bien puesta nunca se arranca de su vecina, y un folio
mal leído no mueve nada: o no hay a dónde ir, o hay más de una hoja y no se
adivina. Sin folios, el orden es el del escaneo.
"""

from __future__ import annotations

from collections.abc import Sequence


def folios_corregidos(folios: Sequence[int | None]) -> list[int | None]:
    """Los folios leídos, con el que la IA leyó mal entre dos que cuadran corregido.

    La hoja 87 de UPD3859802 trae el folio 29 y la IA leyó un 7 suelto: entre el
    28 y el 30 sólo cabe el 29. Sólo con las dos vecinas del escaneo a dos de
    distancia y un folio que no puede ser el suyo: el que no se leyó, el que ya
    lleva otra hoja o uno muy lejos. Entre el 56 y el 58 un 55 es una hoja
    cambiada de sitio (las hojas 9 a 11 del mismo libro), no un error de la IA.
    """
    repetidos = {f for f in folios if f is not None and folios.count(f) > 1}
    corregidos = list(folios)
    for indice in range(1, len(folios) - 1):
        antes, este, despues = folios[indice - 1], folios[indice], folios[indice + 1]
        if antes is None or despues is None or despues != antes + 2 or este == antes + 1:
            continue
        if este is None or este in repetidos or abs(este - (antes + 1)) > LEJOS_PARA_SER_SUYO:
            corregidos[indice] = antes + 1
    return corregidos


#: Cuánto puede alejarse un folio del que le toca entre sus vecinas para tenerlo
#: por una hoja cambiada de sitio y no por una lectura mala.
LEJOS_PARA_SER_SUYO = 10


def orden_por_el_folio(folios: Sequence[int | None]) -> list[int]:
    """Las páginas del PDF (desde 1) en el orden del libro: el del escaneo, seguido por el folio donde salta.

    ``folios`` es el folio impreso de cada página, en el orden del PDF
    (``None`` si no se leyó). Devuelve una permutación de ``1..len(folios)``:
    cada hoja una vez.
    """
    total = len(folios)
    folio = {pagina: f for pagina, f in enumerate(folios, start=1)}

    def en_su_sitio(pagina: int) -> bool:
        """Si la hoja sigue por folio a la que tiene delante en el escaneo."""
        anterior = folio.get(pagina - 1)
        return folio[pagina] is not None and anterior is not None and folio[pagina] == anterior + 1

    fuera_de_sitio: dict[int, list[int]] = {}
    for pagina in range(1, total + 1):
        if folio[pagina] is not None and not en_su_sitio(pagina):
            fuera_de_sitio.setdefault(folio[pagina], []).append(pagina)

    siguiente: dict[int, int] = {}
    tomadas: set[int] = set()
    # Primero los saltos: la hoja con el folio que sigue, fuera de su sitio y única.
    for pagina in range(1, total + 1):
        actual = folio[pagina]
        if actual is None or folio.get(pagina + 1) == actual + 1:
            continue
        candidatas = [q for q in fuera_de_sitio.get(actual + 1, []) if q != pagina]
        if len(candidatas) == 1 and candidatas[0] not in tomadas:
            siguiente[pagina] = candidatas[0]
            tomadas.add(candidatas[0])
    # Después, donde no hay salto o no se sabe a dónde ir, la del escaneo, si nadie la tomó.
    for pagina in range(1, total):
        if pagina not in siguiente and pagina + 1 not in tomadas:
            siguiente[pagina] = pagina + 1
            tomadas.add(pagina + 1)

    orden: list[int] = []
    puestas: set[int] = set()

    def seguir(desde: int) -> None:
        pagina: int | None = desde
        while pagina is not None and pagina not in puestas:
            orden.append(pagina)
            puestas.add(pagina)
            pagina = siguiente.get(pagina)

    # Cada cadena desde la hoja que nadie sigue, en el orden del escaneo; lo que
    # quede -- un ciclo, que no debería darse -- en el orden del escaneo.
    for pagina in range(1, total + 1):
        if pagina not in tomadas:
            seguir(pagina)
    for pagina in range(1, total + 1):
        if pagina not in puestas:
            seguir(pagina)
    return orden


def tramos_seguidos(paginas: Sequence[int]) -> list[tuple[int, int]]:
    """Las páginas agrupadas en tramos seguidos, en su orden: [98, 2, 3] da [(98, 98), (2, 3)]."""
    tramos: list[list[int]] = []
    for pagina in paginas:
        if tramos and pagina == tramos[-1][1] + 1:
            tramos[-1][1] = pagina
        else:
            tramos.append([pagina, pagina])
    return [(desde, hasta) for desde, hasta in tramos]
