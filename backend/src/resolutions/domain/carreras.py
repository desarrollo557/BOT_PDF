"""La carrera del graduando, completada contra el catálogo de la Universidad.

En un libro de diplomas la carrera va escrita a mano bajo la leyenda impresa
«exigen para optar el título de:», y lo que el OCR devuelve de ese renglón es
una aproximación: sobre el libro 7 de 1982, ECONOMISTA llegó como "Econocida",
"Econrusta" y "Econquista"; MÉDICO Y CIRUJANO como "Quedros y Cirujano";
INGENIERO CIVIL como "Guzmán Civil". Un archivo llamado `ECONQUISTA` no lo
busca nadie.

Lo pidió el operador así: «si la carrera en la página no se ve bien y se ve
"economi", la idea es que la IA lo complete y sepa qué carrera es». Y el modo
de saberlo no es adivinar: es comparar la lectura con **la lista cerrada de
carreras que esta Universidad ha expedido**, y quedarse con la que encaje sin
ambigüedad. Lo que no encaje con ninguna se deja sin carrera, que es mejor que
una carrera inventada; y quien lee el libro vuelve entonces sobre esa cara con
una franja recortada, que lee mejor que la página entera.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from .text_distance import damerau_levenshtein

#: Las carreras tal como se escriben en el nombre de un archivo y en el
#: inventario. Con sus acentos, porque es el nombre propio del título y así lo
#: imprime la Universidad; sin ellos se comparan.
#:
#: Salen de los libros medidos -- el 7 de 1982, el 8 de 1983 y los de
#: posgrados -- y de la oferta histórica de la Universidad de Cartagena. Añadir
#: una carrera es añadir una línea aquí. Conviene que cada una tenga alguna
#: palabra que ninguna otra tenga: es lo que permite reconocerla cuando el OCR
#: sólo acertó esa palabra ("Guzmán Civil").
CATALOGO_DE_CARRERAS: tuple[str, ...] = (
    "ABOGADO",
    "MÉDICO Y CIRUJANO",
    "ODONTÓLOGO",
    "ENFERMERA",
    "QUÍMICO FARMACÉUTICO",
    "BACTERIÓLOGO",
    "NUTRICIONISTA Y DIETISTA",
    "ECONOMISTA",
    "ADMINISTRADOR DE EMPRESAS",
    "CONTADOR PÚBLICO",
    "TRABAJADORA SOCIAL",
    "INGENIERO CIVIL",
    "INGENIERO QUÍMICO",
    "INGENIERO DE ALIMENTOS",
    "INGENIERO DE SISTEMAS",
    "LICENCIADO EN EDUCACIÓN",
    "LICENCIADO EN LINGÜÍSTICA Y LITERATURA",
    "LICENCIADO EN FILOSOFÍA Y LETRAS",
    "ESPECIALISTA EN ADMINISTRACIÓN DE EMPRESAS",
    "ESPECIALISTA EN GERENCIA EN SALUD",
    "ESPECIALISTA EN GESTIÓN DE LA CALIDAD Y AUDITORÍA EN SALUD",
    "DOCTOR EN MEDICINA Y CIRUGÍA",
    "DOCTOR EN ODONTOLOGÍA",
    "DOCTOR EN DERECHO Y CIENCIAS POLÍTICAS",
)

#: Las palabras con que empieza un título **compuesto**: "ESPECIALISTA EN
#: GERENCIA DE PROYECTOS". Un título así se reconoce como carrera por su forma
#: aunque no esté en el catálogo, y a la vez exige más para encajar con una
#: del catálogo: la palabra que sigue a la cabeza es la que dice de qué es, y
#: acertar sólo la cabeza no identifica nada.
CABEZAS = frozenset(
    {
        "ESPECIALISTA",
        "ESPECIALIZACION",
        "MAGISTER",
        "MAESTRIA",
        "DOCTOR",
        "DOCTORA",
        "LICENCIADO",
        "LICENCIADA",
        "TECNOLOGO",
        "TECNOLOGA",
        "TECNICO",
        "PROFESIONAL",
    }
)

#: Las palabras que no distinguen una carrera de otra y no cuentan al comparar.
_VACIAS = frozenset({"Y", "E", "EN", "DE", "DEL", "LA", "EL", "LAS", "LOS", "CON"})

#: Cuánto puede alejarse una palabra leída de la del catálogo para seguir
#: siendo la misma: un tercio de su longitud, que es la holgura de un escáner
#: sobre una palabra -- "ECONQUISTA" está a dos ediciones de "ECONOMISTA".
_TOLERANCIA_POR_PALABRA = 3

#: Y cuántas letras iniciales bastan para reconocer una palabra que llegó
#: truncada o con la cola cambiada: "ECONOCIDA" y "ENFERMEDORA" no están a
#: tres ediciones de nada, pero empiezan como una sola carrera del catálogo.
_PREFIJO_QUE_IDENTIFICA = 5

#: Lo que no puede ser una carrera por su forma: un dígito, un símbolo.
_NO_ES_TITULO = re.compile(r"[^A-Z ]")

#: Un título de más palabras que esto es la leyenda del pie, no una carrera.
_MAX_PALABRAS = 12


def plano(texto: str) -> str:
    """Mayúsculas, sin acentos, sin puntuación y con un solo espacio entre palabras."""
    sin_acentos = "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", texto.upper())
        if not unicodedata.combining(caracter)
    )
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", sin_acentos).split())


def _palabras(texto: str) -> list[str]:
    return [palabra for palabra in plano(texto).split() if palabra not in _VACIAS]


#: El catálogo ya plegado, una vez.
_CATALOGO_PLANO: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (carrera, tuple(_palabras(carrera))) for carrera in CATALOGO_DE_CARRERAS
)

#: Las palabras que sólo una carrera tiene, y cuál.
_PROPIAS_DE_UNA: dict[str, str] = {}
for _carrera, _palabras_de in _CATALOGO_PLANO:
    for _palabra in _palabras_de:
        _PROPIAS_DE_UNA[_palabra] = None if _palabra in _PROPIAS_DE_UNA else _carrera
_PROPIAS_DE_UNA = {p: c for p, c in _PROPIAS_DE_UNA.items() if c is not None}


def carrera_normalizada(texto: str | None) -> str | None:
    """La carrera del catálogo que dice esta lectura, o ``None`` si no dice ninguna.

    Tres formas de encajar, de la más segura a la menos, y en todas se exige
    que **una sola** carrera encaje: si dos lo hacen igual de bien, no se
    elige ninguna, porque un título mal atribuido es peor que uno vacío.

    1. **Entera**: todas las palabras de la carrera se reconocen en la lectura
       y la lectura no trae ninguna de más. Con la holgura del escáner palabra
       a palabra -- un tercio de su largo, o las cinco primeras letras --, que
       es lo que hace que "Econocida", "Enfermedora" y "Abogad" encajen.
    2. **A medias**, sólo para las carreras de una palabra o dos: la mitad de
       sus palabras, sin ninguna de más. "Trabajadora" es TRABAJADORA SOCIAL.
    3. **Por una palabra que sólo ella tiene**, escrita tal cual o casi: "Guzmán
       Civil" es INGENIERO CIVIL porque CIVIL no está en ninguna otra, aunque
       "Guzmán" sea basura. Aquí la holgura es sólo la del prefijo: con la del
       tercio, "Cirujano" encajaría también con "Cirugía".

    4. **Similitud global** (fallback para OCR muy dañado): si la cadena completa
       tiene distancia de Levenshtein <= 2 con una carrera del catálogo, y
       ninguna otra carrera está igual de cerca.

    Un título **compuesto** -- el que empieza por ESPECIALISTA, MAGÍSTER,
    DOCTOR, LICENCIADO... -- sólo encaja entero: acertar la cabeza y una
    palabra no dice de qué es la especialización, y "Especialista en Gerencia
    de Proyectos" no es "Especialista en Gerencia en Salud". Si no encaja
    entero pero viene limpio, se acepta tal cual, en mayúsculas: se reconoce
    como un título aunque no se conozca.

    Lo que no encaja por ninguna vía vuelve como ``None``: "Cartagena", la
    leyenda del pie del diploma, una palabra suelta que no se parece a nada.
    """
    if not texto:
        return None
    limpio = plano(texto)
    if not limpio or _NO_ES_TITULO.search(limpio) or len(limpio.split()) > _MAX_PALABRAS:
        return None

    for carrera, _ in _CATALOGO_PLANO:
        if plano(carrera) == limpio:
            return carrera

    leidas = _palabras(limpio)
    if not leidas:
        return None
    compuesto = leidas[0] in CABEZAS

    candidatas: list[tuple[int, int, str]] = []
    for carrera, propias in _CATALOGO_PLANO:
        cubiertas, sobrantes = _cobertura(leidas, propias)
        if len(cubiertas) == len(propias) and not sobrantes:
            candidatas.append((2, len(cubiertas), carrera))
        elif compuesto:
            continue
        elif len(propias) <= 2 and len(cubiertas) * 2 >= len(propias) and not sobrantes:
            candidatas.append((1, len(cubiertas), carrera))
        elif _por_palabra_propia(leidas, carrera):
            candidatas.append((0, 1, carrera))

    # Fallback 4: similitud global de cadena completa (para "ECONQUISTA" -> "ECONOMISTA")
    # Solo si no hay candidatas de los métodos anteriores
    if not candidatas:
        candidatas = _similitud_global(limpio)

    if candidatas:
        tope = max((rango, cuantas) for rango, cuantas, _ in candidatas)
        ganadoras = [c for rango, cuantas, c in candidatas if (rango, cuantas) == tope]
        return ganadoras[0] if len(ganadoras) == 1 else None

    if compuesto and len(leidas) >= 2 and all(len(palabra) >= 2 for palabra in leidas):
        return limpio
    return None


def _similitud_global(texto_limpio: str) -> list[tuple[int, int, str]]:
    """Busca carrera por similitud global de Levenshtein en toda la cadena.

    Para casos como "ECONQUISTA" que no encajan palabra a palabra pero están
    a 1-3 ediciones de "ECONOMISTA". Solo devuelve matches si hay UNA SOLA
    carrera a distancia <= 3 Y comparten las primeras 3 letras.
    """
    candidatas: list[tuple[int, int, str]] = []
    mejor_distancia = 999
    mejores_carreras: list[str] = []

    for carrera, _ in _CATALOGO_PLANO:
        carrera_plana = plano(carrera)
        if len(texto_limpio) < 4 or len(carrera_plana) < 4:
            continue
        distancia = damerau_levenshtein(texto_limpio, carrera_plana, ceiling=4)
        # Requiere: distancia <= 3 Y mismas 3 primeras letras
        if distancia <= 3 and texto_limpio[:3] == carrera_plana[:3]:
            if distancia < mejor_distancia:
                mejor_distancia = distancia
                mejores_carreras = [carrera]
            elif distancia == mejor_distancia:
                mejores_carreras.append(carrera)

    if mejor_distancia <= 3 and len(mejores_carreras) == 1:
        # Rang -1 para que quede por debajo de los métodos palabra-a-palabra
        candidatas.append((-1, 1, mejores_carreras[0]))

    return candidatas


def _cobertura(
    leidas: Sequence[str], propias: Sequence[str]
) -> tuple[frozenset[str], frozenset[str]]:
    """Qué palabras de la carrera reconoce la lectura, y cuáles le sobran."""
    cubiertas: set[str] = set()
    sobrantes: set[str] = set()
    for leida in leidas:
        pareja = next(
            (propia for propia in propias if propia not in cubiertas and _misma_palabra(leida, propia)),
            None,
        )
        if pareja is None:
            sobrantes.add(leida)
        else:
            cubiertas.add(pareja)
    return frozenset(cubiertas), frozenset(sobrantes)


def _misma_palabra(leida: str, propia: str) -> bool:
    if _mismo_prefijo(leida, propia):
        return True
    holgura = max(1, len(propia) // _TOLERANCIA_POR_PALABRA)
    if damerau_levenshtein(leida, propia, ceiling=holgura) <= holgura:
        return True
    # Fallback: similitud global de la cadena completa (para OCR muy dañado)
    # "ECONQUISTA" vs "ECONOMISTA" -> distancia 2, ratio 0.8
    if len(leida) >= 4 and len(propia) >= 4:
        distancia_global = damerau_levenshtein(leida, propia, ceiling=3)
        if distancia_global <= 2:  # máxima 2 ediciones en toda la palabra
            return True
    return False


def _mismo_prefijo(leida: str, propia: str) -> bool:
    if leida == propia:
        return True
    return len(leida) >= _PREFIJO_QUE_IDENTIFICA and propia.startswith(
        leida[:_PREFIJO_QUE_IDENTIFICA]
    )


def _por_palabra_propia(leidas: Sequence[str], carrera: str) -> bool:
    """Si la lectura trae, tal cual o por su prefijo, una palabra que sólo
    esta carrera tiene en el catálogo."""
    return any(
        _PROPIAS_DE_UNA.get(propia) == carrera
        for leida in leidas
        for propia in _PROPIAS_DE_UNA
        if _mismo_prefijo(leida, propia)
    )
