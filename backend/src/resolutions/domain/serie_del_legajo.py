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
import unicodedata
from collections.abc import Sequence
from datetime import date

from .fechas import fecha_de_expedicion

#: Cuánto puede saltar la serie entre una resolución y la siguiente.
SALTO_DE_LA_SERIE = 150

_DE_RECTORIA = re.compile(r"^\d{5,6}$")

#: Con qué empieza el código de las hojas que un legajo de facultad trae antes
#: de su primera resolución -- la SOLICITUD DE EXAMEN de la pág. 1 de «1992-2002-
#: tomo 2» --: no son de ninguna resolución, y van en su propio PDF con su fila
#: (2026-11-27). El código es «PREVIAS-<su primera página>».
PREVIAS = "PREVIAS"


def es_de_las_previas(codigo: str) -> bool:
    """Si el código es el de las hojas previas a la primera resolución, no el de una resolución."""
    return codigo.startswith(f"{PREVIAS}-")


# -- el año de cada resolución de facultad -----------------------------------------

#: Los años que puede llevar una resolución de estos legajos.
_PRIMER_ANIO, _ULTIMO_ANIO = 1900, 2099
#: La fórmula de cierre con el «en Cartagena» destrozado por el OCR -- «Dada^jBR
#: Dartagena a los 26 días de marzo de 1998.», «Dada enjigrtagena…» --, que
#: ``fecha_de_expedicion`` no reconoce: de ella sólo se toma el año.
_DADA_DANADA = re.compile(r"\bDAD[AO]\b.{0,90}?\b((?:19|20)\d{2})\b")
#: La fecha impresa bajo el número en la cabecera: «Resolución 03 / 2 de febrero
#: de 1995» (tomo 001-061, 1995).
_FECHA_DE_LA_CABECERA = re.compile(r"\b\d{1,2}\s+DE\s+[A-Z]{3,}\s+DEL?\s+((?:19|20)\d{2})\b")
_RENGLONES_DE_LA_CABECERA = 15


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn").upper()


def anio_de_su_papel(textos: Sequence[str], numero: str | None = None) -> int | None:
    """El año en que se expidió una resolución, de lo que dicen sus propias hojas; ``None`` si no lo dicen.

    Es lo que distingue la 001 de 2003 de la 001 de 2004 en un tomo de varios
    años, donde la numeración vuelve a empezar cada año (2026-11-27, «TOMO 1
    2003-2010»). En orden de confianza: la fecha de su fórmula de cierre
    (``fecha_de_expedicion``), el año de esa fórmula aunque el OCR haya
    destrozado el resto, y la fecha impresa bajo el número en la cabecera.
    """
    paginas = list(textos)
    if fecha := fecha_de_expedicion(paginas, numero=numero):
        return fecha.year
    for texto in paginas:
        plano = " ".join(_plano(texto).split())
        if (hallado := _DADA_DANADA.search(plano)) and _PRIMER_ANIO <= int(hallado.group(1)) <= _ULTIMO_ANIO:
            return int(hallado.group(1))
    if paginas:
        cabecera = " ".join(_plano("\n".join(paginas[0].splitlines()[:_RENGLONES_DE_LA_CABECERA])).split())
        if hallado := _FECHA_DE_LA_CABECERA.search(cabecera):
            return int(hallado.group(1))
    return None


def anios_de_la_serie(
    numeros: Sequence[int | None], anios: Sequence[int | None]
) -> list[tuple[int | None, bool]]:
    """El año de cada resolución del legajo, y si se sacó de la serie en vez de su papel.

    ``numeros`` es el consecutivo de cada resolución en el orden del legajo
    (``None`` si no es de la serie: una de rectoría), y ``anios`` el que dijo
    su papel (``anio_de_su_papel``). A la que no lo dice se le pone el de sus
    vecinas que lo dicen, si la numeración lo sostiene: el de la anterior si
    su número sigue al de ella, el de la siguiente si su número la precede, y
    si las dos valen, el de la más cercana en número. Si las dos vecinas son
    del mismo año, ése. Si nada lo sostiene, ``None``: no se inventa.

    Medido en los tomos de decanatura de Odontología (2026-11-27): la
    numeración vuelve a empezar cada año («034» de 2008 y luego «001» de
    2009), así que una resolución sin fecha legible entre la 033 y la 035 es
    del año de las dos.

    Y la que dice un año que la serie desmiente toma el de la serie: entre la
    184 y la 190 de 2006, la 187 que fija el calendario «del segundo periodo
    del 2006» cierra con «Dada en Cartagena de Indias, a los 17 días de Julio
    de 2003» (TOMO 1 2003-2010, pág. 126: la fórmula copiada de otra), y con
    ese año se juntaba con la 187 de 2003. Sólo cuando las dos vecinas dicen
    el mismo año y su número queda entre los de ellas.
    """
    con_anio = [i for i, (n, a) in enumerate(zip(numeros, anios, strict=True)) if n is not None and a is not None]

    def vecinas(i: int, de: list[int]) -> tuple[int | None, int | None]:
        return next((j for j in reversed(de) if j < i), None), next((j for j in de if j > i), None)

    # Primero, los años que dice el papel y la serie desmiente: los dos
    # vecinos del mismo año y el número entre los de ellos. Con los años ya
    # corregidos se rellenan después los que faltan (la 048 entre la 047 de
    # 1997 y la 049, cuya fecha el OCR leyó «1937»).
    corregidos: list[int | None] = list(anios)
    por_la_serie = [False] * len(anios)
    for i in con_anio:
        antes, despues = vecinas(i, con_anio)
        if antes is None or despues is None or anios[antes] != anios[despues] or anios[i] == anios[antes]:
            continue
        if (numeros[antes] or 0) < (numeros[i] or 0) < (numeros[despues] or 0):
            corregidos[i], por_la_serie[i] = anios[antes], True

    resultado: list[tuple[int | None, bool]] = []
    for i, numero in enumerate(numeros):
        if numero is None or corregidos[i] is not None:
            resultado.append((corregidos[i], por_la_serie[i]))
            continue
        antes, despues = vecinas(i, con_anio)
        if antes is not None and despues is not None and corregidos[antes] == corregidos[despues]:
            resultado.append((corregidos[antes], True))
            continue
        # A igual distancia gana la anterior: el libro va en el orden en que se expidieron.
        opciones: list[tuple[int, int, int]] = []
        if antes is not None and numero >= (previo := numeros[antes] or 0):
            opciones.append((numero - previo, 0, corregidos[antes] or 0))
        if despues is not None and numero <= (siguiente := numeros[despues] or 0):
            opciones.append((siguiente - numero, 1, corregidos[despues] or 0))
        resultado.append((min(opciones)[2], True) if opciones else (None, False))
    return resultado


def numeros_por_la_serie(
    numeros: Sequence[int | None], anios: Sequence[int | None], dudosos: Sequence[bool]
) -> list[tuple[int | None, bool]]:
    """El número de cada resolución, con el de la serie para el dudoso que choca con otra.

    El número escrito a máquina sobre la raya de «Resolución No. ____» no está
    en la capa de texto y se lee con OCR en la banda (``dudosos``), pero su
    letra estilizada engaña a Tesseract: la 088 entre la 087 y la 089 se leyó
    «049» y la 173 detrás de la 172 se leyó «075», y cada una se juntaba con la
    049 o la 075 de verdad, cien páginas antes (07-115 TOMO 1, pág. 156; 088-173
    TOMO 2, pág. 196; 2026-11-27). Sólo cuando el número leído ya es el de otra
    resolución del mismo año: entonces es el siguiente al de la anterior, si la
    siguiente no lo tiene ya y nadie más lo usa. Un número que no choca se
    respeta, aunque salte (los tomos de 1999 son resoluciones sueltas).
    """
    cuenta: dict[tuple[int, int], int] = {}
    for numero, anio in zip(numeros, anios, strict=True):
        if numero is not None and anio is not None:
            cuenta[(numero, anio)] = cuenta.get((numero, anio), 0) + 1
    resultado: list[tuple[int | None, bool]] = [(numero, False) for numero in numeros]
    for i, (numero, anio) in enumerate(zip(numeros, anios, strict=True)):
        if not dudosos[i] or numero is None or anio is None or cuenta.get((numero, anio), 0) < 2:
            continue
        previo = next(((resultado[j][0], anios[j]) for j in range(i - 1, -1, -1) if resultado[j][0] is not None), None)
        if previo is None or previo[1] != anio or previo[0] is None:
            continue
        candidato = previo[0] + 1
        siguiente = next((numeros[j] for j in range(i + 1, len(numeros)) if numeros[j] is not None), None)
        if siguiente == candidato or cuenta.get((candidato, anio), 0):
            continue
        cuenta[(numero, anio)] -= 1
        cuenta[(candidato, anio)] = 1
        resultado[i] = (candidato, True)
    return resultado


def anios_del_legajo(
    numeros: Sequence[int | None], anios: Sequence[int | None], fechas: Sequence[date | None]
) -> list[tuple[int | None, bool]]:
    """``anios_de_la_serie``, sin juntar dos resoluciones distintas con el mismo número y año.

    La Decanatura expide en noviembre la resolución del calendario del año
    siguiente con el número de ese año: la 001 «Dada… a los 21 días del mes
    de noviembre de 2007» fija el primer periodo de 2008 y va entre la 135 de
    2007 y la 003 de 2008, mientras la 001 de enero de 2007 fija el de 2007
    (TOMO 1 2003-2010, págs. 153 y 199; 2026-11-27). Las dos decían «001-2007»
    y el agrupador las juntaba. Cuando dos resoluciones no seguidas dan el
    mismo número y año y sus fechas (``fechas``, la de su fórmula de cierre)
    son distintas, la segunda toma el año de su serie, si es otro. Con la
    misma fecha, o sin fecha, son copias de la misma y siguen juntas.
    """
    completos = anios_de_la_serie(numeros, anios)
    vistos: dict[tuple[int, int], int] = {}
    for i, (anio, _) in enumerate(completos):
        numero = numeros[i]
        if numero is None or anio is None:
            continue
        primero = vistos.setdefault((numero, anio), i)
        if primero == i or fechas[i] is None or fechas[primero] is None or fechas[i] == fechas[primero]:
            continue
        sin_el_suyo = list(anios)
        sin_el_suyo[i] = None
        otro = anios_de_la_serie(numeros, sin_el_suyo)[i][0]
        if otro is not None and otro != anio and (numero, otro) not in vistos:
            completos[i] = (otro, True)
            vistos[(numero, otro)] = i
    return completos


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
