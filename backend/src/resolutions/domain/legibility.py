"""Si la capa de texto de una página es una lectura o una mala decodificación.

Un PDF puede traer texto embebido y aun así no poder leerse. Ocurre cuando la
fuente lleva un mapa de caracteres equivocado -- las decorativas de las
resoluciones de rectoría, sobre todo -- y entonces el visor dibuja los glifos
correctos mientras el texto que se puede copiar es otro:

    lo que está impreso : RESOLUCIÓN No 00074
    lo que devuelve     : <^OLVCIÓ?{% 00074
    el cuerpo           : CO^SKDEWfDO:  ·  eCmaestro  ·  deCmes  ·  (Rgfaeí

Esto es peor que no tener capa de texto, porque *parece* que la hay. La cascada
la aceptaba por tener 2.432 caracteres, no encontraba la palabra "RESOLUCIÓN"
-- que había salido convertida en `<^OLVCIÓ?{%` -- y daba la página por una
continuación de la resolución anterior. Las páginas de la 00074 se archivaban
dentro de la 00073 y nadie se enteraba.

La señal que lo delata es barata y no necesita diccionario: **una minúscula
seguida inmediatamente de una mayúscula dentro de una palabra**. La prosa
española no lo hace casi nunca; una fuente mal mapeada lo hace en cada renglón,
porque el desplazamiento del mapa manda letras a la caja contraria. En el
material medido las páginas mal decodificadas dan entre 26 y 30 por cada mil
caracteres, y las sanas no pasan de 6.

Detectarlo no repara nada -- de un texto mal decodificado no se recupera el
original adivinando -- y no es lo que se pretende. Lo que hace es devolver la
página a la cascada, que sabe mirar la imagen: el OCR lee los glifos dibujados,
que son los correctos, y encuentra la palabra en cualquier fuente que esté.
"""

from __future__ import annotations

import re

#: Una minúscula seguida de una mayúscula sin espacio de por medio. En español
#: aparece en algún nombre propio compuesto y poco más; aquí es el rastro de una
#: fuente cuyo mapa manda las letras a la caja equivocada.
_INTERIOR_CAPITAL = re.compile(r"[a-záéíóúüñ][A-ZÁÉÍÓÚÜÑ]")

#: Golpes por cada mil caracteres a partir de los cuales el texto deja de
#: parecer prosa. Medido, no elegido: en los primeros documentos las páginas mal
#: decodificadas daban 26,3 y 29,6, y la página sana más ruidosa 6,5, así que el
#: umbral se puso en doce.
#:
#: Bajó a once con más material. El folio 209 del libro 00960-00979 tiene la
#: capa de texto rota -- la palabra "RESOLUCIÓN" sale como ``msoLVció^í^r`` --
#: y sin embargo puntúa 11,4, justo por debajo del listón: se aceptaba como
#: texto bueno, no se miraba la imagen, y la resolución 00974 desaparecía del
#: entregable. Leída de la imagen aparece entera.
#:
#: El coste se midió antes de moverlo. En las 545 páginas de los dos libros hay
#: doce entre 8 y 12; se comprobó una por una si la imagen escondía un
#: encabezado que el texto hubiera perdido, y sólo lo escondía el folio 209.
#: Bajar a once manda cuatro páginas más al OCR y recupera una resolución
#: entera; bajar más sería pagar renderizados por nada.
GARBLED_PER_THOUSAND = 11.0

#: Y un mínimo absoluto de golpes, porque una proporción sobre poco texto no
#: mide nada: una página de 190 caracteres con tres nombres propios pegados da
#: 15 por mil sin tener nada malo.
MIN_INTERIOR_CAPITALS = 10


def interior_capitals(text: str) -> int:
    """Cuántas veces una mayúscula aparece pegada detrás de una minúscula."""
    return len(_INTERIOR_CAPITAL.findall(text))


def garble_score(text: str) -> float:
    """Golpes por cada mil caracteres. Cero para un texto vacío."""
    if not text:
        return 0.0
    return 1000.0 * interior_capitals(text) / len(text)


def is_garbled(text: str) -> bool:
    """Si esta capa de texto es una mala decodificación y no una lectura.

    Las dos condiciones van juntas a propósito. La proporción sola se dispara en
    páginas cortas; el recuento solo se dispara en páginas largas y sanas. Que
    haya que cumplir las dos es lo que deja fuera a las dos clases de ruido.
    """
    golpes = interior_capitals(text)
    if golpes < MIN_INTERIOR_CAPITALS:
        return False
    return 1000.0 * golpes / len(text) >= GARBLED_PER_THOUSAND
