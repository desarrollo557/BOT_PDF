"""La serie de un legajo de resoluciones, y las copias que vienen fuera de ella.

Un legajo de rectoría es una racha de números seguidos -- «RESOLUCION
02991-02998» --, y detrás de cada resolución viene encuadernado lo que la
soporta: también **copias de otras resoluciones de rectoría**, de otros años o
anteriores, con su propio encabezado impreso. Una copia no es una unidad del
legajo: va dentro de la resolución que la trae.

Lo confirmó el inventario documental de la carpeta «RESOLUCIONES DE RECTORIA
3220 - 3259» (2026-10-29), una fila por resolución con sus folios: la 02991
tiene 8 folios y el bot entregaba 3 suyos y 5 de la copia 00121 en un archivo
aparte; la 00075 perdía la copia 02852. En toda la muestra las copias iban
hacia atrás (la 00121, la 00958 detrás de la 02991 o la 03522) o saltaban
miles de números (la 02852 detrás de la 00075).

La serie es la cadena más larga de números que crecen sin saltar más de
``SALTO_DE_LA_SERIE``: el inventario salta 2 a 4 números entre resoluciones
seguidas y, como mucho, 120. Se busca en todo el legajo y no a partir del
primer número, para que un legajo que empiece por una copia no la tome por
la serie. Sólo cuentan los números de rectoría -- cinco o seis cifras --: los
de facultad («002-2023») tienen su propia regla de soporte.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

#: Cuánto puede saltar la serie entre una resolución y la siguiente.
SALTO_DE_LA_SERIE = 150

_DE_RECTORIA = re.compile(r"^\d{5,6}$")


def serie_del_legajo(codigos: Sequence[str | None]) -> set[str]:
    """Los números que forman la serie del legajo, de los que traen sus páginas.

    ``codigos`` es el número de cada página en orden (``None`` si no trae).
    Entre dos cadenas igual de largas gana la que cubre más páginas.
    """
    paginas: dict[str, int] = {}
    orden: list[str] = []
    for codigo in codigos:
        if codigo is None or not _DE_RECTORIA.match(codigo):
            continue
        if codigo not in paginas:
            orden.append(codigo)
        paginas[codigo] = paginas.get(codigo, 0) + 1
    if not orden:
        return set()
    numeros = [int(codigo) for codigo in orden]
    # La cadena más larga que termina en cada número: (largo, páginas), y de dónde viene.
    mejor: list[tuple[int, int]] = []
    antes: list[int | None] = []
    for i, numero in enumerate(numeros):
        puntaje, previo = (1, paginas[orden[i]]), None
        for j in range(i):
            if numeros[j] < numero <= numeros[j] + SALTO_DE_LA_SERIE:
                candidato = (mejor[j][0] + 1, mejor[j][1] + paginas[orden[i]])
                if candidato > puntaje:
                    puntaje, previo = candidato, j
        mejor.append(puntaje)
        antes.append(previo)
    final: int | None = max(range(len(orden)), key=lambda i: mejor[i])
    serie: set[str] = set()
    while final is not None:
        serie.add(orden[final])
        final = antes[final]
    return serie


def completar_por_la_serie(fechas: Sequence[date | None]) -> list[date | None]:
    """Las fechas que faltan en la serie, por las de sus vecinas.

    En un legajo los números van en orden de fecha: en el inventario de la
    carpeta 3220 - 3259, el 98,9 % de las resoluciones seguidas tienen la fecha
    igual o creciente, y el 98,9 % de las que quedan entre dos de la misma
    fecha la comparten. A la que no se le pudo leer la fórmula -- «Dada en
    Cartagena de Indias^ajos^^^ e 2.025» -- se le pone la de su vecina anterior,
    que es su cota inferior (y la exacta si la siguiente dice lo mismo); sin
    anterior, la de la siguiente.
    """
    completas = list(fechas)
    for i, fecha in enumerate(fechas):
        if fecha is not None:
            continue
        antes = next((f for f in reversed(fechas[:i]) if f is not None), None)
        despues = next((f for f in fechas[i + 1 :] if f is not None), None)
        completas[i] = antes if antes is not None else despues
    return completas


def copias_fuera_de_la_serie(codigos: Sequence[str | None]) -> set[str]:
    """Los números de rectoría que aparecen en el legajo sin ser de su serie: copias."""
    serie = serie_del_legajo(codigos)
    return {
        codigo
        for codigo in codigos
        if codigo is not None and _DE_RECTORIA.match(codigo) and codigo not in serie
    }
