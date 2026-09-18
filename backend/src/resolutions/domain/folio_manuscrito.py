"""Si la esquina alta de la hoja lleva folio escrito a mano, sin leer cuál.

Un libro de registro se folia a mano en la esquina superior derecha de la cara
de delante, con una "v" al lado. La cara de atrás nunca lo lleva, porque nunca
lo tuvo: es la vuelta de la misma hoja. Así que la marca dice dónde empieza
cada registro, y su ausencia dice que la hoja pertenece al anterior.

Lo que hace a esta señal barata es que **no hace falta leer el número**. La
pregunta no es "qué folio es" sino "hay algo escrito ahí", y ésa se contesta
contando tinta. Medido sobre el libro `UPD3859766` -- 398 páginas, 199 caras de
delante y 199 vueltas -- son doce segundos para todo el libro, contra los 752
que tarda pasarle OCR; y el OCR, además, no sirve: el folio es manuscrito y
Tesseract falla en 228 de las 398.

Quien mide la tinta es el adaptador, que es quien tiene los píxeles. Aquí sólo
vive qué significan sus dos cuentas.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

#: Dónde se busca el folio, en fracciones de la página. Pegado al margen
#: derecho y a la cabecera, y sin llegar al borde del papel: lo que hay más
#: allá de 0.985 es el canto del libro, que el escáner devuelve como una franja
#: negra en la mitad de las hojas.
BANDA_DEL_FOLIO = (0.60, 0.005, 0.985, 0.070)


class MarcaDeFolio(StrEnum):
    """Qué se encontró en esa esquina."""

    #: Hay trazo de escritura: esta cara abre un registro.
    PRESENTE = "presente"
    #: La esquina está limpia: es la vuelta de la hoja anterior.
    AUSENTE = "ausente"
    #: Se miró y no se pudo decir. Hay algo, pero poco para llamarlo escritura
    #: y bastante para no llamarlo papel limpio. No es evidencia de que aquí
    #: empiece nada, así que la hoja se queda con el registro abierto y la
    #: costura se declara para revisión.
    DUDOSA = "dudosa"
    #: Nadie miró la esquina: una fuente sin píxeles, una página que no se dejó
    #: rasterizar. Es distinto de ``DUDOSA`` y la diferencia importa. Una
    #: medida ambigua es una hoja concreta que une; no haber medido son todas
    #: las hojas del libro, y unirlas a todas soldaría el libro entero en un
    #: documento. Aquí no se decide: deciden las reglas de los identificadores
    #: leídos, como antes de que esta señal existiera.
    SIN_MEDIR = "sin medir"


@dataclass(frozen=True, slots=True)
class TrazoEnEsquina:
    """Lo que el adaptador encontró en esa esquina, en dos números.

    El primero es cuánta tinta hay con el tono de un trazo escrito. El tono
    importa tanto como la cantidad: el folio se anota a mano, en tinta o lápiz,
    y sale gris medio, mientras que lo que el escáner añade -- el canto del
    libro, la sombra del alimentador, el borde de la hoja levantada -- sale
    negro saturado. Contar sólo los grises deja fuera casi todo el defecto de
    escaneo sin tocar la escritura.

    El segundo dice qué parte de la banda hubo que descartar por esa misma
    razón, para saber cuándo la medida se hizo sobre tan poco papel que no
    significa nada.
    """

    #: Tinta con tono de trazo, en proporción al cuadrado del alto de la banda
    #: -- que es tanto como decir "cuántos caracteres de escritura caben en lo
    #: que se encontró". Normalizar así y no por el ancho es lo que hace que un
    #: folio corto cuente igual que uno largo: "1/v" ocupa un tercio de ancho
    #: que "126 v", y medido en fracción de ancho se perdía por pequeño.
    trazo: float
    #: Qué parte de la banda quedó descartada por canto o sombra.
    vetado: float


#: Desde cuánto trazo se cree que hay un folio. Medido sobre el libro de 398
#: páginas: las 199 caras de delante dan de 0.032 a 0.148, con mediana 0.099, y
#: las 199 vueltas de 0.000 a 0.112, con mediana 0.001 y el percentil 95 en
#: 0.007. Entre las dos poblaciones hay un valle de un factor cinco, así que el
#: umbral no está encajado con calzador: a 0.025 se reconocen las 199 caras de
#: delante sin excepción y sólo tres vueltas salen marcadas.
TINTA_DE_FOLIO = 0.025

#: Y por debajo de cuánto se declara limpia la esquina. Entre este número y el
#: anterior no se afirma nada. En el libro medido cae ahí una sola página de
#: las 398, que es la medida de lo poco que se usa esta zona.
TINTA_DE_PAPEL_LIMPIO = 0.012

#: Cuánta banda puede descartarse antes de que lo que quede no sea medible. El
#: máximo observado en el libro es 0.489 -- media banda comida por el canto --
#: y aun ahí el folio se ve en la otra media.
BANDA_INSERVIBLE = 0.60


def marca_de_folio(trazo: TrazoEnEsquina | None) -> MarcaDeFolio:
    """Qué dice esa esquina sobre si aquí empieza un registro.

    Sin medida, o con la banda comida por el canto, la respuesta es
    ``SIN_MEDIR`` y nunca ``AUSENTE``: no haber mirado no es haber visto la
    esquina limpia, y tratarlo al revés uniría el libro entero en un solo
    documento.
    """
    if trazo is None or trazo.vetado > BANDA_INSERVIBLE:
        return MarcaDeFolio.SIN_MEDIR
    if trazo.trazo >= TINTA_DE_FOLIO:
        return MarcaDeFolio.PRESENTE
    if trazo.trazo < TINTA_DE_PAPEL_LIMPIO:
        return MarcaDeFolio.AUSENTE
    return MarcaDeFolio.DUDOSA


# -----------------------------------------------------------------------------
#  El ritmo del libro
# -----------------------------------------------------------------------------
#  Una esquina se mide sola, pero un libro tiene ritmo, y el ritmo sabe cosas
#  que la esquina no. Un libro encuadernado se escanea hoja por hoja y por las
#  dos caras: folio, vuelta, folio, vuelta. Ese compás es un hecho del propio
#  documento, medible sin leer una palabra, y sirve justamente para lo que la
#  medida de tinta no puede: reconocer que lo que hay en una esquina no es un
#  folio aunque esté escrito.
#
#  Medido sobre `UPD3859766`, el libro 7 de 1982, 398 páginas: las 199 caras de
#  delante se reconocen sin excepción -- la más floja da 0.032 contra un umbral
#  de 0.025 -- y tres vueltas salen marcadas de más. Las tres, miradas una a
#  una: la 140 es la franja negra del borde superior de la hoja, la 354 es la
#  punta de la hoja levantada sobre el cristal, y la 224 lleva escrita a mano la
#  palabra "Anulada". La 224 es el caso que enseña por qué hace falta esto: hay
#  escritura de verdad en esa esquina, así que ninguna medida de tinta la va a
#  descartar nunca, y sin embargo no es un folio.
#
#  Lo que costaban esas tres: seis documentos de una sola cara en lugar de tres
#  de dos. Cada uno de los tres registros partido en dos archivos -- el diploma
#  por un lado y su vuelta por otro -- que es el FALSE_SPLIT que esta casa
#  evita antes que ninguna otra cosa.
# -----------------------------------------------------------------------------

#: Cuántas aperturas hacen falta antes de hablar de ritmo. Tres hojas no tienen
#: compás: tienen tres hojas. Por debajo de esto no se corrige nada, porque una
#: coincidencia en una muestra corta no es una regla del documento.
MINIMO_PARA_RITMO = 8

#: Qué parte de las aperturas tiene que ir de dos en dos para creer que el libro
#: se escaneó por las dos caras. En el libro medido son 196 de 199, un 0.985.
#: El margen que queda por debajo es deliberado: un libro con algunas hojas
#: escaneadas por una sola cara sigue teniendo ritmo, y uno donde la mitad de
#: las hojas van sueltas no lo tiene y no se le inventa.
RITMO_ALTERNO = 0.90


def libro_alterna(marcas: Sequence[MarcaDeFolio]) -> bool:
    """Si este libro se escaneó hoja por hoja y por las dos caras.

    Se contesta con las distancias entre aperturas y nada más. Un escaneo de
    doble cara las pone de dos en dos; uno de cara simple, de una en una, y
    entonces aquí no hay ritmo que aplicar y esta función dice que no.
    """
    aperturas = [i for i, marca in enumerate(marcas) if marca is MarcaDeFolio.PRESENTE]
    if len(aperturas) < MINIMO_PARA_RITMO:
        return False
    saltos = [
        siguiente - actual
        for actual, siguiente in zip(aperturas, aperturas[1:], strict=False)
    ]
    if not saltos:
        return False
    return sum(1 for salto in saltos if salto == 2) / len(saltos) >= RITMO_ALTERNO


def marcas_en_ritmo(marcas: Sequence[MarcaDeFolio]) -> list[MarcaDeFolio]:
    """Las mismas marcas, con las que rompen el compás del libro rebajadas.

    En un libro que va de dos en dos, una cara marcada justo detrás de otra
    marcada no cabe: entre un folio y el siguiente va la vuelta, y la vuelta no
    lleva folio. Lo que haya en esa esquina será una anotación, un borde o una
    sombra, pero no es la marca que abre un registro.

    Rebajada a ``DUDOSA`` y no a ``AUSENTE``, y la diferencia es todo el
    sentido de esta función: la hoja se une a la anterior -- que es lo que manda
    ante la duda -- y la costura sale nombrada en la cola de revisión, para que
    alguien pueda comprobar esas tres esquinas sin repasar las otras trescientas
    noventa y cinco. Afirmar que la esquina está limpia, en cambio, sería decir
    algo que no se ha visto: en la página 224 del libro medido lo que hay
    escrito es la palabra "Anulada", y eso el operador tiene que saberlo.

    Un libro sin ritmo -- hojas escaneadas por una sola cara -- vuelve tal cual
    entró. La regla no decide por descarte: sin compás demostrado no hay nada
    que contradiga a la tinta.
    """
    if not libro_alterna(marcas):
        return list(marcas)
    corregidas = list(marcas)
    anterior: int | None = None
    for posicion, marca in enumerate(marcas):
        if marca is not MarcaDeFolio.PRESENTE:
            continue
        if anterior is not None and posicion - anterior == 1:
            corregidas[posicion] = MarcaDeFolio.DUDOSA
            # Y no cuenta como folio para la siguiente. Si contara, cada esquina
            # rebajada arrastraría consigo a la cara de después -- que sí lleva
            # folio y sí abre registro -- y el compás correría desplazado un
            # lugar durante el resto del libro. Medido antes de corregirlo: las
            # tres esquinas del libro 7 se llevaban por delante tres registros
            # buenos y los soldaban al anterior en documentos de cuatro caras.
            continue
        anterior = posicion
    return corregidas


#: Lo que se le dice al operador de una cara rebajada por el ritmo. Dice las dos
#: cosas que necesita saber para comprobarla en diez segundos: que la esquina no
#: estaba vacía y por qué aun así no se cortó ahí.
AVISO_FUERA_DE_RITMO = (
    "la esquina lleva algo escrito, pero el libro va de dos en dos y esta cara "
    "viene detrás de un folio: se unió a la anterior en vez de abrir registro"
)


# -----------------------------------------------------------------------------
#  Qué folio es, cuando alguien supo leerlo
# -----------------------------------------------------------------------------
#  Hasta acá no hizo falta el número: para repartir el libro basta con saber si
#  la esquina tiene algo escrito. Para **nombrar** el archivo sí hace falta, y
#  entonces alguien tiene que leer manuscrito -- Tesseract no sabe -- y lo que
#  conteste hay que comprobarlo.
#
#  Lo que se lee en esa esquina son dos anotaciones, no una: arriba el número de
#  página del escaneo y debajo el folio del libro, con su "v" al lado. Medido
#  sobre el libro 7 con el OCR de Mistral: "135 70/1" en la página 139, cuyo
#  folio es 70; "396 200/V" en la 397, cuyo folio es 200; "2513/v" en la 25,
#  cuyo folio es 13 y viene pegado al número de página. La barra con la "v" es
#  lo que distingue un número del otro, y por eso es lo que se busca.
# -----------------------------------------------------------------------------

#: El folio y su "v". La letra llega escrita de todas las formas en que un OCR
#: puede confundir una uve manuscrita -- v, u, 1, 0, l, i -- y aceptar todas no
#: afloja nada, porque lo que se está identificando es la barra: el número de
#: página que va encima nunca la lleva.
_FOLIO_CON_V = re.compile(r"(\d{1,4})\s*[/|]\s*[vVuU1lIi0oO]")

#: El folio a secas, para las esquinas donde la "v" no sobrevivió al OCR. Se usa
#: sólo si no hubo ninguna con barra, y lo que salga de aquí se comprueba igual
#: contra la progresión del libro antes de creerlo.
_SOLO_NUMEROS = re.compile(r"\d{1,4}")


def folio_de_la_esquina(texto: str, pagina: int | None = None) -> str | None:
    """El folio que dice esa esquina, o ``None`` si no dice ninguno.

    ``pagina`` es el número de página del escaneo, que está escrito ahí mismo
    encima del folio. Sirve para deshacer el caso en que el OCR devuelve los dos
    pegados: en la página 25 contesta "2513/v", y saber que 25 es la página deja
    el 13, que es el folio. Sin ese dato la lectura sería 2513, un folio que no
    existe en un libro de doscientas hojas.

    Nunca se devuelve algo que no estuviera escrito. Una esquina que el OCR
    contestó "N/A", "1974" o "No 44" -- las tres son lecturas reales del libro
    medido -- vuelve como ``None``, y el archivo se nombrará por su página, que
    es un dato cierto, en vez de por un folio inventado.
    """
    if not texto:
        return None

    encontrados = _FOLIO_CON_V.findall(texto)
    if encontrados:
        return _sin_el_numero_de_pagina(encontrados[-1], pagina)

    numeros = _SOLO_NUMEROS.findall(texto)
    if not numeros:
        return None
    # Sin barra que los distinga, el folio es el último: en esa esquina se
    # escribe debajo del número de página.
    return _sin_el_numero_de_pagina(numeros[-1], pagina)


def _sin_el_numero_de_pagina(leido: str, pagina: int | None) -> str | None:
    """Quita del número leído el de página, cuando vinieron pegados.

    Sólo cuando lo que queda es un número: "2513" con la página 25 deja "13".
    Si lo leído **es** el número de página no se descarta aquí, se devuelve tal
    cual y se deja pasar al siguiente paso, que compara cada lectura con la
    progresión del libro. En la página 1 el folio es 1 y los dos números
    coinciden, así que descartarlo acá perdería un folio bueno; en la 139 un
    "139" leído es el número de página, y quien lo va a tumbar es la progresión,
    que en esa cara espera un 70. Juzga mejor el que ve el libro entero.
    """
    limpio = leido.lstrip("0") or leido
    if pagina is None:
        return limpio or None
    prefijo = str(pagina)
    if limpio.startswith(prefijo) and len(limpio) > len(prefijo):
        return limpio[len(prefijo) :].lstrip("0") or None
    return limpio or None


#: Cuánto puede alejarse un folio leído de lo que el libro hace esperar en esa
#: cara. Dos, y no cero, porque la foliación real salta: en el libro 7 la cara
#: 111 lleva el folio 111 y la 199 lleva el 200, así que en algún punto el
#: foliador se dejó un número. Un margen de dos absorbe esos saltos sin dejar
#: pasar una lectura inventada, que falla por decenas: "No 44" en la cara 6,
#: "1974" en la 7.
TOLERANCIA_DE_PROGRESION = 2


def folios_comprobados(
    lecturas: Sequence[tuple[int, str | None]],
    tolerancia: int = TOLERANCIA_DE_PROGRESION,
) -> dict[int, str]:
    """De todo lo que se leyó en las esquinas, lo que el libro confirma.

    ``lecturas`` son pares de página y folio leído, en el orden del libro. Lo
    que se devuelve es sólo lo que encaja con la progresión, indexado por
    página; lo demás se deja fuera, y una cara sin folio comprobado se nombrará
    por su página, que es un dato cierto.

    La comprobación es la que haría cualquiera con el libro delante: los folios
    van en orden y de uno en uno, así que la distancia entre el folio y el lugar
    que ocupa esa cara tiene que ser la misma en todo el libro. Se cuenta esa
    distancia en cada lectura, gana la más repetida, y lo que se aparte de ella
    más de la cuenta no se cree. Medido sobre el libro 7 leído con el OCR de
    Mistral, es lo que separa los dos tercios de folios bien leídos del tercio
    en que el OCR contestó cualquier cosa.

    Ninguna cara recibe un folio que no se leyera. Rellenar los huecos contando
    -- la cara número k lleva el folio k -- es tentador y está mal: en este mismo
    libro la cara 199 lleva el folio 200, así que ese conteo nombraría mal la
    última mitad del libro y nadie tendría cómo saberlo.
    """
    candidatas = [
        (pagina, int(folio), posicion)
        for posicion, (pagina, folio) in enumerate(lecturas)
        if folio and folio.isdigit()
    ]
    if not candidatas:
        return {}

    votos: dict[int, int] = {}
    for _pagina, folio, posicion in candidatas:
        distancia = folio - posicion
        votos[distancia] = votos.get(distancia, 0) + 1
    ganadora = max(votos, key=lambda distancia: (votos[distancia], -abs(distancia)))

    # Y la ganadora tiene que ganar de verdad: la mitad de las lecturas, por lo
    # menos. Sin esto, un libro del que sólo se leyeron cuatro folios sueltos y
    # dispares daba por bueno el primero que saliera -- un `7_DIPLOMA.pdf` entre
    # el 004 y el 006, que parece un dato y no lo es. Una mayoría no dice que la
    # lectura sea correcta, pero sí que hay una progresión contra la que
    # comprobarla; sin mayoría no hay progresión, sólo números sueltos.
    #
    # Con una sola lectura la condición se cumple sola, que es lo que debe
    # pasar: en un documento de un registro, ese folio es todo lo que hay.
    if votos[ganadora] * 2 < len(candidatas):
        return {}

    return {
        pagina: str(folio)
        for pagina, folio, posicion in candidatas
        if abs((folio - posicion) - ganadora) <= tolerancia
    }
