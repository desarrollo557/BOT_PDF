"""Qué papel es cada documento, dicho con el vocabulario del archivo.

Esto corre **después** del corte, nunca antes. Preguntarle a una caja de ciento
veinticinco hojas de qué tipo es no tiene respuesta: dentro hay una notificación,
un pagaré, tres facturas y un acta. La pregunta sólo tiene sentido sobre un
documento que ya tiene bordes, y para entonces casi siempre está contestada en
la propia hoja, impresa arriba.

El catálogo no se inventa aquí: es el listado de tipos documentales del archivo
del cliente, y ninguna otra palabra puede acabar en el nombre de un archivo. Un
papel que no se reconozca sale sin tipo -- que es lo honesto -- en vez de con el
tipo más parecido, que es como un expediente termina teniendo cuatro "facturas"
que nadie facturó.

Dos cosas hacen falta para leer un rótulo en un escaneo. Una es tolerar las
erratas del OCR, porque estos papeles llegan con "NOTIFICACIQN P0R AVIS0". La
otra es no confundir el rótulo con el cuerpo: la palabra "factura" sale en media
correspondencia de una empresa de energía sin que ninguna de esas hojas sea una
factura. Por eso las frases largas -- las que sólo se escriben para titular un
documento -- se buscan en toda la página, y las cortas y corrientes sólo cuentan
cuando ocupan un renglón para ellas solas, que es como se imprime un título.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .anchor import normalize
from .catalogo import FRASES, TipoDocumental
from .text_distance import damerau_levenshtein

#: A partir de cuántos caracteres una frase se busca en toda la página. Por
#: debajo es vocabulario corriente -- "FACTURA", "RECIBO", "PETICION" -- y una
#: aparición suelta en el cuerpo no dice nada sobre qué es la hoja.
ROTULO_MINIMO = 14

#: Cuánto más puede llevar un renglón por detrás de un rótulo corto antes de
#: dejar de ser un título. "PAGARE No 4500123456" lo es; "PAGARE que el suscrito
#: otorga a favor de..." es el cuerpo del documento.
EXTRA_DE_ROTULO = 25

#: Erratas perdonadas por cada diez caracteres. Es la misma proporción con que
#: `fingerprint` lee los rótulos de apertura, medida sobre esta misma caja:
#: "REFUBWCA DE COLOMSIá" contra "republica de colombia" son tres ediciones
#: sobre veintiún caracteres.
EDICIONES_POR_DIEZ = 2

#: Y el tope, pase lo largo que sea la frase. La proporción sola no vale aquí:
#: dos tipos del catálogo se parecen tanto como "CITACION PARA NOTIFICACION
#: PERSONAL" y "AUTORIZACION PARA LA NOTIFICACION PERSONAL", y con ocho erratas
#: perdonadas -- el 20 % de la segunda -- una citación se leía como una
#: autorización. Un escaneo malo rompe letras sueltas; ocho ediciones ya no son
#: un rótulo mal leído, son otro rótulo.
MAX_EDICIONES = 4

#: Por debajo de este largo no se perdona ni una errata. Con una sola edición
#: "PQR" es "POR" y "TMP" es "TEMP": una tolerancia que a los rótulos largos les
#: salva la vida, a los de tres letras les inventa apariciones.
LARGO_MINIMO_DIFUSO = 8

#: Cuántas páginas del documento se miran buscando el rótulo. La primera es la
#: que lo lleva; las dos siguientes cubren al que empieza con una carátula o con
#: la hoja de envío. Más allá se estaría leyendo el cuerpo, y ahí lo que se
#: encuentra son menciones, no títulos.
PAGINAS_MIRADAS = 3

_PUNTUACION = re.compile(r"[^A-Z0-9/ ]+")

#: Cómo se anuncia el asunto de un escrito. Es la fuente más directa que hay
#: para saber de qué es: no es una mención en el cuerpo ni una deducción del
#: rótulo, es el propio documento diciendo de qué trata, en el sitio donde el
#: papel oficial lo declara.
#:
#: "REF" entra porque un derecho de petición se encabeza así -- "REF: Derecho
#: de Petición según el Artículo 23 de nuestra Carta Magna" -- y ese escrito no
#: lleva ningún otro título.
_ASUNTO = re.compile(r"\b(?:asunto|referencia|ref)\s*[:.]\s*(.{3,120})", re.IGNORECASE)


def limpiar(texto: str) -> str:
    """Mayúsculas, sin acentos, sin puntuación y con un solo espacio.

    La puntuación se va porque el escáner la reparte a su antojo: el mismo
    rótulo llega como "ACTA DE SUSPENSION, CORTE Y RECONEXION", como "ACTA DE
    SUSPENSION - CORTE Y RECONEXION" y como "ACTA DE SUSPENSION. CORTE Y
    RECONEXION". Comparar las tres contra una sola forma es lo que evita tener
    que escribirlas todas en el catálogo.
    """
    return re.sub(r"\s+", " ", _PUNTUACION.sub(" ", normalize(texto))).strip()


@dataclass(frozen=True, slots=True)
class Coincidencia:
    """El tipo que se reconoció, y por dónde.

    Se guarda la frase y no sólo el tipo porque es lo que permite auditar un
    nombre discutible sin volver a abrir el PDF: qué se leyó, dónde, y cuántas
    erratas hubo que perdonar para leerlo.
    """

    tipo: TipoDocumental
    frase: str
    posicion: int
    distancia: int
    pagina: int = 1

    @property
    def nombre(self) -> str:
        return self.tipo.nombre

    def as_dict(self) -> dict[str, object]:
        return {
            "tipo": self.tipo.nombre,
            "frase": self.frase,
            "pagina": self.pagina,
            "distancia": self.distancia,
        }




def _presupuesto(frase: str) -> int:
    """Cuántas erratas se le perdonan a una frase antes de dejar de ser ella."""
    return min(MAX_EDICIONES, max(1, len(frase) * EDICIONES_POR_DIEZ // 10))


def _inicios_de_palabra(plano: str) -> dict[str, list[int]]:
    """Dónde empieza cada palabra de la página, agrupado por su primera letra.

    Se calcula una vez por página y lo comparten las ciento y pico frases del
    catálogo. Es lo que hace que esto se pueda pagar: la primera versión probaba
    cada frase contra cada palabra de la página -- ciento setenta frases por
    trescientas palabras, todas con su distancia de edición -- y costaba más de
    medio segundo por documento, que en una caja de doscientos son dos minutos
    de nada.

    Un rótulo impreso empieza donde empieza una palabra y por la letra que le
    toca. El escáner rompe letras por dentro mucho más que la inicial de un
    título, y cuando rompe la inicial el documento sale sin tipo, que es lo que
    ya le pasa a la caja ilegible y es la respuesta honesta.
    """
    indice: dict[str, list[int]] = {}
    anterior = " "
    for posicion, letra in enumerate(plano):
        if anterior == " " and letra != " ":
            indice.setdefault(letra, []).append(posicion)
        anterior = letra
    return indice


def _busca_en_texto(
    frase: str, plano: str, indice: dict[str, list[int]] | None = None
) -> tuple[int, int] | None:
    """Dónde aparece la frase en la página, tolerando las erratas del escáner.

    Devuelve la posición y las erratas que hubo que perdonar, o ``None``. La
    prueba exacta va primero porque sobre una capa de texto sana la contesta
    entera sin calcular una sola distancia; la ventana difusa se paga sólo en las
    frases que el escaneo estropeó.
    """
    exacta = plano.find(frase)
    if exacta >= 0:
        return exacta, 0
    if len(frase) < LARGO_MINIMO_DIFUSO:
        return None

    presupuesto = _presupuesto(frase)
    ancho = len(frase)
    # Sólo desde el principio de una palabra, y sólo de las que empiezan por la
    # letra que toca: un rótulo impreso empieza donde empieza una palabra, y
    # probar los otros mil desplazamientos de la página multiplica el coste por
    # el largo del texto sin encontrar nada más.
    if indice is None:
        indice = _inicios_de_palabra(plano)
    inicios = indice.get(frase[0], ())
    mejor: tuple[int, int] | None = None
    for inicio in inicios:
        ventana = plano[inicio : inicio + ancho]
        if len(ventana) < ancho - presupuesto:
            break
        distancia = damerau_levenshtein(ventana, frase, ceiling=presupuesto)
        if distancia <= presupuesto and (mejor is None or distancia < mejor[1]):
            mejor = (inicio, distancia)
            if distancia == 0:
                break
    return mejor


@dataclass(frozen=True, slots=True)
class _Renglon:
    """Un renglón de la cabecera, listo para que le prueben rótulos encima.

    Los inicios de palabra se calculan una vez y los comparten las ciento
    setenta frases del catálogo. Antes se recalculaban dentro de la búsqueda,
    o sea una vez por frase: el mismo trabajo ciento setenta veces por hoja.
    """

    numero: int
    texto: str
    #: Dónde empieza cada palabra, agrupado por su primera letra. Es lo que
    #: permite no calcular una distancia de edición contra cada palabra.
    inicios: dict[str, list[int]]


def preparar_renglones(renglones: Sequence[str]) -> list[_Renglon]:
    """Los renglones con su índice de palabras, para probarles rótulos."""
    preparados: list[_Renglon] = []
    for numero, texto in enumerate(renglones):
        indice: dict[str, list[int]] = {}
        anterior = " "
        for posicion, letra in enumerate(texto):
            if anterior == " " and letra != " ":
                indice.setdefault(letra, []).append(posicion)
            anterior = letra
        preparados.append(_Renglon(numero=numero, texto=texto, inicios=indice))
    return preparados


def _busca_como_rotulo(
    frase: str, renglones: Sequence[_Renglon]
) -> tuple[int, int] | None:
    """La frase, pero sólo si el renglón que la lleva es un título y no prosa.

    Es lo que separa un título del cuerpo, y la medida es el largo del renglón.
    "FACTURA" en un renglón suyo titula una factura; "FACTURA" dentro de "se le
    informa que la factura del mes de mayo" es prosa, y nombrar el archivo por
    ella es como una notificación acaba llamándose factura.

    Dentro de ese renglón la frase puede empezar en cualquier palabra, no sólo
    en la primera. El escáner pega el logo al título más veces de las que lo
    separa -- "armia Liquidación del Consumo No registrado..." es un renglón
    real -- y exigir que el renglón empezara por la frase perdía justamente los
    títulos de las hojas peor escaneadas, que son las que más falta hacen.

    **Sólo se prueban las palabras que empiezan por la letra que toca**, y ése
    es el filtro que hace esto pagable: sin él, esta función era el 96 % del
    coste de leer una hoja -- 43.432 distancias de edición en un expediente de
    97 páginas, tres segundos de los cuatro que costaba el documento entero.
    Es el mismo criterio que ya aplica `_busca_en_texto`, y tiene el mismo
    precio conocido: cuando el escáner rompe la inicial de un título, el
    documento sale sin tipo. Es la respuesta honesta, y la que ya le toca a la
    hoja ilegible.
    """
    presupuesto = _presupuesto(frase) if len(frase) >= LARGO_MINIMO_DIFUSO else 0
    ancho = len(frase)
    inicial = frase[0]
    for renglon in renglones:
        if len(renglon.texto) > ancho + EXTRA_DE_ROTULO:
            continue
        for inicio in renglon.inicios.get(inicial, ()):
            ventana = renglon.texto[inicio : inicio + ancho]
            if len(ventana) < ancho - presupuesto:
                break
            distancia = damerau_levenshtein(ventana, frase, ceiling=presupuesto)
            if distancia <= presupuesto:
                return renglon.numero, distancia
    return None

def identificar(texto: str, pagina: int = 1) -> Coincidencia | None:
    """El tipo documental que declara una página, si declara alguno.

    Gana la frase más larga que aparezca, porque es la más específica: una hoja
    que dice "RECURSO DE REPOSICION Y SUBSIDIARIAMENTE EL DE APELACION" dice las
    dos cosas, y la que la distingue del recurso simple es la larga. A igual
    largo gana la que aparece antes, que es la que está más cerca del título.

    Devuelve ``None`` cuando nada del catálogo aparece. Es el caso corriente en
    un tercio de la caja y no es un fallo: el archivo sale con nombre genérico y
    lo tipifica una persona, que es mucho mejor que salir con el tipo de al lado.
    """
    plano = limpiar(texto)
    if not plano:
        return None
    renglones = preparar_renglones(
        [limpio for renglon in texto.splitlines() if (limpio := limpiar(renglon))]
    )
    indice = _inicios_de_palabra(plano)

    mejor: Coincidencia | None = None
    for frase, tipo in FRASES:
        if mejor is not None and mejor.distancia == 0 and len(frase) < len(mejor.frase):
            # Las frases vienen ordenadas de larga a corta y ya hay una que se
            # leyó tal cual: ninguna más corta puede mejorarla. Mientras la
            # mejor sea difusa hay que seguir mirando, porque una frase más
            # corta que aparezca sin una errata le gana.
            break
        if len(frase) >= ROTULO_MINIMO:
            hallazgo = _busca_en_texto(frase, plano, indice)
        else:
            hallazgo = _busca_como_rotulo(frase, renglones)
        if hallazgo is None:
            continue
        posicion, distancia = hallazgo
        candidata = Coincidencia(
            tipo=tipo, frase=frase, posicion=posicion, distancia=distancia, pagina=pagina
        )
        if mejor is None or _mejor_que(candidata, mejor):
            mejor = candidata
    return mejor


def _mejor_que(candidata: Coincidencia, actual: Coincidencia) -> bool:
    """Cuál de dos lecturas del mismo papel se queda.

    Manda lo que se leyó sin erratas sobre lo que hubo que adivinar, y sólo
    después manda el largo. Al revés -- que ganara siempre la frase más larga --
    una citación se leía como la autorización que se le parece, porque la
    autorización es más larga y entraba dentro de la tolerancia.
    """
    return (candidata.distancia == 0, len(candidata.frase), -candidata.posicion) > (
        actual.distancia == 0,
        len(actual.frase),
        -actual.posicion,
    )


#: Cuántos renglones de la cabecera se miran buscando el título. El rótulo va
#: arriba, detrás del logo y a veces del consecutivo: en el expediente medido
#: aparecía en el tercer renglón y en el quinto. Más abajo ya es el cuerpo, y
#: lo que se encuentra ahí son menciones.
RENGLONES_DE_CABECERA = 10

#: Cómo empieza el renglón que declara el asunto, ya normalizado.
_EMPIEZA_POR_ASUNTO = re.compile(r"(?:ASUNTO|REFERENCIA|REF)[ ]")


def identificar_rotulo(renglones: Sequence[str]) -> Coincidencia | None:
    """El tipo que la hoja se da a sí misma **como título**, no de pasada.

    Se distingue de :func:`identificar` en una sola cosa, y es la que importa
    para decidir dónde se corta el papel: aquí la frase tiene que ocupar su
    propio renglón, sea larga o corta.

    Es la diferencia entre una hoja que **se titula** "Constancia de Visita" --
    veinte caracteres en un renglón para ellos solos -- y una resolución que en
    su cuarto punto dice "4. Constancia de Visita asociada al Acta de Revisión
    con Orden de Servicio...", noventa y cinco caracteres de prosa. El catálogo
    reconoce la frase en las dos, y sólo la primera abre un documento. Sin esta
    distinción, esa resolución se partía en dos por una frase de su cuerpo.
    """
    limpios = [limpiar(renglon) for renglon in renglones[:RENGLONES_DE_CABECERA]]
    # El renglón del asunto no es un título, aunque lo parezca: "Asunto:
    # Notificación por aviso" cabe de sobra en el largo de un rótulo y nombra
    # un tipo del catálogo. Se deja para `identificar_asunto`, que es de quien
    # es, y así la jerarquía -- título, luego asunto, luego mención -- dice de
    # verdad lo que dice.
    limpios = [
        renglon for renglon in limpios if renglon and not _EMPIEZA_POR_ASUNTO.match(renglon)
    ]
    if not limpios:
        return None
    preparados = preparar_renglones(limpios)

    mejor: Coincidencia | None = None
    for frase, tipo in FRASES:
        if mejor is not None and mejor.distancia == 0 and len(frase) < len(mejor.frase):
            break
        hallazgo = _busca_como_rotulo(frase, preparados)
        if hallazgo is None:
            continue
        renglon, distancia = hallazgo
        candidata = Coincidencia(
            tipo=tipo, frase=frase, posicion=renglon, distancia=distancia, pagina=1
        )
        if mejor is None or _mejor_que(candidata, mejor):
            mejor = candidata
    return mejor


def identificar_asunto(texto: str) -> Coincidencia | None:
    """El tipo que declara el propio campo «Asunto» de la hoja.

    Lo pidió el operador y es la fuente más honesta de las tres: un rótulo hay
    que reconocerlo por su sitio en la página y una mención puede ser
    cualquier cosa, pero el asunto es el documento diciendo de qué trata, en el
    renglón donde el papel oficial lo declara.

    Dentro del asunto se busca sin exigir renglón propio, y ésa es la
    diferencia con :func:`identificar_rotulo`: aquí ya se sabe que lo que se
    está leyendo es el asunto, así que "RECURSO DE REPOSICIÓN ante afinia GRUPO
    EPM y EN SUBSIDIO DE APELACIÓN" nombra el tipo aunque venga con media
    frase detrás.
    """
    for linea in texto.splitlines():
        # Al principio del renglón, no en cualquier sitio. Un acta de
        # notificación personal lleva dentro un formulario que dice "Tipo de
        # PQR o Asunto: RECLAMO", y ese asunto es el de la PQR que se está
        # notificando, no el del acta que se tiene delante: leído como propio,
        # el acta pasaba a llamarse RECLAMO. El asunto de un documento se
        # imprime abriendo su renglón.
        hallazgo = _ASUNTO.match(linea.strip())
        if hallazgo is None:
            continue
        reconocido = identificar(hallazgo.group(1))
        if reconocido is not None:
            return reconocido
    return None


def identificar_documento(paginas: Sequence[str]) -> Coincidencia | None:
    """El tipo de un documento entero, leído por sus primeras páginas.

    Tres fuentes, en el orden que fijó el operador y por los motivos que dio:

    1. **El asunto.** Es el documento diciendo de qué trata, en el renglón
       donde el papel oficial lo declara. No hay nada más directo, y por eso va
       primero: "Asunto: Notificación por aviso" no admite discusión.
    2. **El encabezado.** Cuando no hay asunto -- un acta no lo lleva, una
       constancia tampoco -- lo que queda es cómo se titula la hoja.
    3. **Una mención en el cuerpo.** Sólo si las dos anteriores callan. Un
       escaneo puede haberse comido el encabezado, y entonces una frase del
       catálogo dentro del texto es lo único que hay.

    Se mira la primera página y, sólo si no dijo nada, las siguientes hasta
    :data:`PAGINAS_MIRADAS`. Ese "sólo si" es la regla: un acta de cinco hojas
    que adjunta una factura es un acta, y buscar en todas sus páginas a la vez
    la convertiría en factura por el anexo que lleva detrás.
    """
    for fuente in (_por_asunto, _por_encabezado, _por_mencion):
        for numero, texto in enumerate(paginas[:PAGINAS_MIRADAS], start=1):
            encontrado = fuente(texto)
            if encontrado is not None:
                return Coincidencia(
                    tipo=encontrado.tipo,
                    frase=encontrado.frase,
                    posicion=encontrado.posicion,
                    distancia=encontrado.distancia,
                    pagina=numero,
                )
    return None


def _por_asunto(texto: str) -> Coincidencia | None:
    return identificar_asunto(texto)


def _por_encabezado(texto: str) -> Coincidencia | None:
    return identificar_rotulo(texto.splitlines())


def _por_mencion(texto: str) -> Coincidencia | None:
    return identificar(texto)
