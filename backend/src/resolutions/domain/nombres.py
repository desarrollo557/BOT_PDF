"""El nombre y la cédula de un graduado, decididos entre todas las lecturas de su hoja.

Una misma hoja se lee varias veces -- la capa del escáner, Tesseract sobre la
franja del graduado, la hoja con la tinta realzada y, si se pidió, la IA -- y
cada lectura se equivoca en un sitio distinto. Medido sobre la caja de
Odontología: «ROSA HARÍA CABALLERO MONTÜXA», «ROSA VARIA CABALLERO MONTOYA» y
«MOSA MARRA CABALLENO MONTOYA» son ROSA MARIA CABALLERO MONTOYA. Ninguna
lectura sola lo trae bien; votadas palabra a palabra, sí.

Aquí está lo que no depende de cómo se leyó:

* ``zona_del_nombre``: el nombre tal como va en el formulario, entre «al
  estudiante» y «portador de la cédula», con sus dos renglones, sin el relleno
  de la máquina y sin lo que se le cuela del título o de la fecha;
* ``consenso``: el nombre que sale de votar las lecturas palabra a palabra, y
  si quedó confirmado o dudoso;
* ``consenso_de_cedulas``: lo mismo para la cédula.

Un diccionario de nombres -- una lista genérica más las palabras que se repiten
entre los graduados del mismo libro -- sólo desempata. Nunca reemplaza una
palabra que las lecturas confirman: usado solo, convertía URBINA en RINA.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass

#: Lo que el formulario dice antes del nombre: «al estudiante», «al
#: profesional», «a la señorita». El OCR los estropea -- «atediante»,
#: «EStUdiante» --, así que se reconocen por parecido.
_ANTES_DEL_NOMBRE = ("ESTUDIANTE", "PROFESIONAL", "EGRESADO", "EGRESADA")
_TRATAMIENTOS = {"SENOR", "SENORA", "SENORITA", "SRITA", "SRTA"}
#: Y lo que va después: «portador de la cédula», «con cédula», «identificado».
_DESPUES_DEL_NOMBRE = ("PORTADOR", "PORTADORA", "IDENTIFICADO", "IDENTIFICADA", "EXPEDIDA")
PARECIDO_DEL_ROTULO = 0.72
#: Cuántas palabras, como mucho, hay entre los dos rótulos: dos renglones.
PALABRAS_DE_LA_ZONA = 16

#: Lo que nunca es parte de un nombre aunque se cuele en su zona: el título,
#: la fecha en letras, el formulario.
_NO_ES_NOMBRE = {
    "ESPECIALISTA", "ESPEC", "EN", "SALUD", "OCUPACIONAL", "ENFERMERA", "ENFERMERO",
    "ENFERMERIA", "LICENCIADA", "LICENCIADO", "LICENCIADAS", "MAGISTER", "ODONTOLOGO",
    "ODONTOLOGA", "TITULO", "COMO", "ESTUDIANTE", "PROFESIONAL", "PORTADOR", "PORTADORA",
    "CEDULA", "CIUDADANIA", "EXPEDIDA", "CARTAGENA", "BOLIVAR", "MIL", "NOVECIENTOS",
    "OCHENTA", "NOVENTA", "SETENTA", "DIAS", "MES", "ANO", "CON", "ENFASIS", "MATERNO",
    "PERINATAL", "URGENCIAS", "GERENCIA", "ACTA", "GRADO", "QUIEN", "SE", "LE", "EL",
    "AL", "OTORGA", "SEGUN", "CEREMONIA", "SOLEMNE", "UNIVERSIDAD", "FACULTAD",
    "DISPOSICIONES", "VIGENTES", "QUE", "PARA", "POR", "EJERCICIO", "PROFESION", "DIPLOMA",
    "ENTREGA", "JURAMENTO", "RIGOR", "AUTORIZA", "ESTE", "ES", "EQUIVALENTE", "ANTES",
    "PROMULGACION", "LEY", "TOMO", "HIZO", "ESPECIALIDAD", "SENORITA", "SENOR",
    # Lo de los títulos de especialización, que se cuela cuando el título se
    # leyó mal y no se puede restar entero: «Cuidados intensivos», «Quirófano
    # y recuperación».
    "INTENSIVOS", "INTENSIVO", "CUIDADO", "CUIDADOS", "QUIROFANO", "RECUPERACION",
    "QUIRURGICA", "QUIRURGICO", "ADMINISTRACION", "SERVICIOS", "HOSPITALARIOS",
    "INFANTIL", "NEFROLOGIA", "ONCOLOGIA", "PEDIATRIA", "FAMILIAR", "MENTAL", "PUBLICA",
    "AUDITORIA", "CALIDAD", "GESTION", "EPIDEMIOLOGIA", "ENFERMERAS", "MEDICO", "MEDICA",
    "CLINICA", "CRITICO", "ADULTO", "NEONATAL", "PSIQUIATRIA", "OBSTETRICIA",
    # Los meses de la fecha, que también se cuelan: «I DICIEMBRE DE ERIKA LENIS».
    # Sin JULIO, MAYO, ABRIL ni MARZO, que también son apellidos y nombres:
    # «EUGENIA JULIO ALVAREZ» está en la caja.
    "ENERO", "FEBRERO", "JUNIO", "AGOSTO", "SEPTIEMBRE", "SETIEMBRE", "OCTUBRE", "NOVIEMBRE",
    "DICIEMBRE",
}
#: Las palabras que unen un nombre y nunca se votan solas.
CONECTORES = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "SAN", "SANTA", "VDA", "VIUDA"}
#: Los números en letras de la fecha: «noventa y siete» no es un apellido.
_NUMEROS_EN_LETRAS = {
    "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE", "DIEZ",
    "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "VEINTE", "TREINTA", "CUARENTA",
    "CINCUENTA", "SESENTA",
}

#: Lo que la máquina de escribir y el OCR confunden dentro de un nombre, medido
#: sobre la caja: «$ARAY» es SARAY, «5OCORRO» SOCORRO, «4l estudiante» al.
_CIFRA_POR_LETRA = str.maketrans({"$": "S", "5": "S", "0": "O", "1": "I", "|": "I", "4": "A", "8": "B"})
#: El relleno con que se completaba el renglón a máquina: «.X.X.X», «-----», «nnnn».
_RELLENO = re.compile(r"(?:[.,]?X){2,}[.,]?|[-_=—–~\"“”*#|]+|^[NMEO]{4,}$", re.IGNORECASE)


def clave(texto: str) -> str:
    """El texto en mayúsculas, sin tildes ni diéresis -- la Ñ se queda -- y sin signos."""
    texto = texto.upper().replace("Ñ", "\0")
    plano = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return plano.replace("\0", "Ñ")


#: El relleno con letras por medio: «.X.XeXoXoXoX.X» -- la e y la o son los
#: puntos del relleno leídos como letras --.
_RELLENO_CON_LETRAS = re.compile(r"[.,]*(?:X[.,EO]*){3,}[.,]*", re.IGNORECASE)


def _palabra_limpia(token: str) -> str:
    """Una palabra de nombre sin lo que el OCR le pega: cifras por letras, signos."""
    if _RELLENO_CON_LETRAS.fullmatch(token):
        return ""
    sin_relleno = _RELLENO_CON_LETRAS.sub("", _RELLENO.sub("", token))
    return re.sub(r"[^A-ZÑ]", "", clave(sin_relleno.translate(_CIFRA_POR_LETRA)))


#: Los rótulos que se parecen a palabras del resto del acta piden más parecido:
#: «la profesión de» no es «al profesional».
_PARECIDO_EXIGIDO = {"PROFESIONAL": 0.9}


def _es_rotulo(palabra: str, rotulos: Sequence[str]) -> bool:
    if len(palabra) < 6:
        return False
    for rotulo in rotulos:
        exigido = _PARECIDO_EXIGIDO.get(rotulo, PARECIDO_DEL_ROTULO)
        if difflib.SequenceMatcher(None, palabra, rotulo).ratio() >= exigido:
            return True
    return False


def palabras_de(
    nombre: str | None, *, titulo: str | None = None, conocidas: Collection[str] = ()
) -> list[str]:
    """Las palabras de un nombre leído, limpias y sin lo que no es nombre.

    Une las letras de una palabra escrita espaciada -- «E D N A» es EDNA --,
    quita las palabras del título de esa misma acta -- «SARAY ELENA OCUPACIONAL
    CASTILLO» -- y las de la fecha en letras.
    """
    if not nombre:
        return []
    del_titulo = {clave(p) for p in (titulo or "").split()} - CONECTORES
    crudas = [_palabra_limpia(token) for token in nombre.split()]
    unidas: list[str] = []
    sueltas: list[str] = []
    for palabra in [*crudas, ""]:
        if len(palabra) == 1 and palabra != "Y":
            sueltas.append(palabra)
            continue
        if len(sueltas) >= 2:
            junta = "".join(sueltas)
            # «E DNA D N A»: la segunda tanda repite el final de la primera.
            if not (unidas and unidas[-1].endswith(junta)):
                unidas.append(junta)
        elif sueltas:
            # «C LAUDIA», «I VAN», «E DNA»: la letra suelta es la primera de la
            # palabra que sigue, si juntas son un nombre que se conoce.
            if palabra and (sueltas[0] + palabra) in conocidas:
                palabra = sueltas[0] + palabra
            else:
                unidas.append(sueltas[0])
        sueltas = []
        if palabra:
            unidas.append(palabra)
    return [
        p
        for p in unidas
        if p
        and not _no_es_nombre(p)
        and not _es_numero_en_letras(p)
        and (p in CONECTORES or p not in del_titulo)
    ]


def _no_es_nombre(palabra: str) -> bool:
    """Si es una palabra del formulario o del título, aunque mal leída: «RECUPERACIOON»."""
    if palabra in _NO_ES_NOMBRE:
        return True
    largas = [p for p in _NO_ES_NOMBRE if len(p) >= 8]
    corte = 0.8 if len(palabra) >= 10 else 0.88
    return len(palabra) >= 9 and bool(difflib.get_close_matches(palabra, largas, n=1, cutoff=corte))


#: La fecha en letras que se cuela, también mal leída: «SXETE» es SIETE.
_DE_LA_FECHA = _NUMEROS_EN_LETRAS | {"MIL", "NOVECIENTOS", "OCHENTA", "NOVENTA", "SETENTA"}


def _es_numero_en_letras(palabra: str) -> bool:
    """Si es un número de la fecha, aunque con una letra mal leída: «SXETE» es SIETE.

    Una sola letra y del mismo largo: con más holgura CASTRO pasaba por CUATRO
    y TERESA por TRES, y se perdían apellidos de verdad.
    """
    if palabra in _DE_LA_FECHA:
        return True
    return len(palabra) >= 5 and any(
        len(numero) == len(palabra) and sum(a != b for a, b in zip(numero, palabra, strict=True)) == 1
        for numero in _DE_LA_FECHA
    )


def _sin_conectores_sueltos(palabras: list[str]) -> list[str]:
    """Sin el «DE» que se cuela delante -- «DE JAIRO JOSE» -- ni el conector final.

    «DE LA OSSA» sí empieza por DE: va seguido de LA, LAS o LOS.
    """
    palabras = list(palabras)
    while palabras and palabras[0] in {"DE", "DEL", "Y"} and (
        len(palabras) < 2 or palabras[1] not in {"LA", "LAS", "LOS"}
    ):
        palabras.pop(0)
    while palabras and palabras[-1] in CONECTORES:
        palabras.pop()
    return palabras


def _ordenado(palabras: list[str]) -> list[str]:
    """Lo que nunca va así en un nombre, arreglado.

    * una letra suelta delante -- «A DES CARMEN» -- o detrás -- «TOVAR E» --:
      las iniciales van en medio («ANA J MONTAÑEZ»);
    * la misma palabra dos veces seguidas: «VILLADIEGO VILLADIEGO»;
    * un «Y» pegado a un conector: «ROSARIO DEL Y SOCORRO».
    """
    salida: list[str] = []
    for palabra in palabras:
        if salida and palabra == salida[-1] and palabra not in CONECTORES:
            continue
        if palabra == "Y" and salida and salida[-1] in {"DE", "DEL", "LA", "LAS", "LOS"}:
            continue
        salida.append(palabra)
    while salida and len(salida[0]) == 1 and salida[0] != "Y":
        salida.pop(0)
    utiles = [p for p in salida if p not in CONECTORES and len(p) > 1]
    while len(utiles) >= 2 and salida and len(salida[-1]) == 1:
        salida.pop()
    return salida


def _sin_trozos(palabras: list[str]) -> list[str]:
    """Sin el trozo de palabra que repite la siguiente: «GONZAL E GONZALEZ» es GONZALEZ."""
    salida: list[str] = []
    saltar_letra = False
    for indice, palabra in enumerate(palabras):
        siguientes = palabras[indice + 1 : indice + 3]
        if len(palabra) >= 4 and any(
            otra != palabra and otra.startswith(palabra) for otra in siguientes
        ):
            saltar_letra = True
            continue
        if saltar_letra and len(palabra) == 1:
            saltar_letra = False
            continue
        saltar_letra = False
        salida.append(palabra)
    return salida


def zona_del_nombre(
    texto: str, *, titulo: str | None = None, conocidas: Collection[str] = ()
) -> str | None:
    """El nombre tal como va en el formulario: de «al estudiante» a «portador».

    Con sus dos renglones -- «al estudiante LEDA MARIA / GARCES GUERRA portador
    de la cédula» --, que es justo lo que se perdía al cortar en el primero.
    ``None`` si la hoja no trae esa zona o lo que hay no parece un nombre.
    """
    tokens = texto.split()
    claves = [clave(t) for t in tokens]
    for inicio, palabra in enumerate(claves):
        limpia = re.sub(r"[^A-Z]", "", palabra)
        if not (_es_rotulo(limpia, _ANTES_DEL_NOMBRE) or limpia in _TRATAMIENTOS):
            continue
        fin = None
        for indice in range(inicio + 1, min(len(claves), inicio + 1 + PALABRAS_DE_LA_ZONA)):
            siguiente = re.sub(r"[^A-Z]", "", claves[indice])
            con_cedula = siguiente == "CON" and indice + 1 < len(claves) and claves[indice + 1].startswith("C")
            if _es_rotulo(siguiente, _DESPUES_DEL_NOMBRE) or con_cedula:
                fin = indice
                break
            # «PNORTADOR», «DORTADOR»: el rótulo con una letra de más o de menos.
            if "ORTADOR" in siguiente:
                fin = indice
                break
        if fin is None:
            continue
        palabras = _sin_conectores_sueltos(
            palabras_de(" ".join(tokens[inicio + 1 : fin]), titulo=titulo, conocidas=conocidas)
        )
        utiles = [p for p in palabras if p not in CONECTORES]
        largas = [p for p in utiles if len(p) >= 3]
        if 2 <= len(utiles) <= 7 and len(largas) >= 2:
            return " ".join(palabras)
    return None


# -- el consenso --------------------------------------------------------------

#: Desde cuánto parecido dos palabras de lecturas distintas son la misma.
PARECIDO_DE_LA_MISMA = 0.72


def _parecido(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _peso_al_alinear(a: str, b: str) -> float:
    """Lo que suma emparejar dos palabras: un conector casi nada.

    Sin esto el «Y» de una lectura se emparejaba con el «Y» de otra -- parecido
    perfecto -- y descolocaba MARRHA de su MARTHA.
    """
    if a in CONECTORES or b in CONECTORES:
        return 0.3 if a == b else 0.0
    if _una_confusion(a, b):
        # «IUZ» y «LUZ»: una sola letra de las que se confunden, aunque sea corta.
        return max(_parecido(a, b), PARECIDO_DE_LA_MISMA)
    return _parecido(a, b)


def _empareja(peso: float) -> bool:
    return peso == 0.3 or peso >= PARECIDO_DE_LA_MISMA


def _alinear(base: list[str], otra: list[str]) -> list[tuple[int, int]]:
    """Las parejas de palabras de dos lecturas que son la misma, sin cruzar el orden."""
    filas, columnas = len(base), len(otra)
    puntos = [[0.0] * (columnas + 1) for _ in range(filas + 1)]
    for a in range(1, filas + 1):
        for b in range(1, columnas + 1):
            parecido = _peso_al_alinear(base[a - 1], otra[b - 1])
            juntas = puntos[a - 1][b - 1] + parecido if _empareja(parecido) else -1.0
            puntos[a][b] = max(puntos[a - 1][b], puntos[a][b - 1], juntas)
    parejas: list[tuple[int, int]] = []
    a, b = filas, columnas
    while a and b:
        parecido = _peso_al_alinear(base[a - 1], otra[b - 1])
        if _empareja(parecido) and puntos[a][b] == puntos[a - 1][b - 1] + parecido:
            parejas.append((a - 1, b - 1))
            a, b = a - 1, b - 1
        elif puntos[a][b] == puntos[a - 1][b]:
            a -= 1
        else:
            b -= 1
    return parejas[::-1]


def parece_palabra_de_nombre(palabra: str) -> bool:
    """Si una palabra puede ser de un nombre: «MSCSDSS» o «AAAAANONO» no pueden."""
    if palabra in CONECTORES:
        return True
    if len(palabra) < 2 or not re.search(r"[AEIOU]", palabra):
        return False
    if (len(palabra) >= 7 and len(set(palabra)) <= 3) or (len(palabra) >= 9 and len(set(palabra)) <= 4):
        # «NAANNANCANAACANAA», «ECOCECCNEC»: el relleno de la máquina leído
        # como letras -- muchas y casi siempre las mismas --.
        return False
    return not (re.search(r"(.)\1\1", palabra) or re.search(r"[^AEIOUY]{5,}", palabra))


@dataclass(frozen=True, slots=True)
class Consenso:
    """El nombre que sale de votar las lecturas, y qué tan seguro es."""

    nombre: str | None
    #: Si cada palabra la conoce el diccionario o la confirman tres lecturas: con
    #: dos no basta, porque dos lecturas de la misma imagen se equivocan igual
    #: («PIÍAMA» en la capa y en la franja, por DIANA).
    confirmado: bool
    #: Cuántas lecturas tenían un nombre que votar.
    lecturas: int
    #: Si alguna palabra no la conoce el diccionario ni la repite otra lectura:
    #: eso sí es un nombre dudoso, que se dice en observaciones.
    dudoso: bool = False


#: Desde cuánto parecido una palabra desconocida es la conocida mal leída:
#: ANTONO es ANTONIO. Alto a propósito: URBINA no es RINA.
PARECIDO_PARA_CORREGIR = 0.9


#: Las letras que la máquina de escribir y el OCR confunden, medidas en la caja:
#: «HARIA» por MARIA, «SUILLERMO» por GUILLERMO, «MERCEDBB» por MERCEDES.
_CONFUSIONES = {
    frozenset(par) for par in ("SG", "HM", "BE", "KR", "CG", "IL", "OQ", "VY", "NM", "UO", "EF")
}


def _una_confusion(leida: str, conocida: str) -> bool:
    """Si dos palabras sólo se diferencian en una letra, y es una de las que se confunden."""
    if len(leida) != len(conocida) or len(leida) < 3:
        return False
    distintas = [(a, b) for a, b in zip(leida, conocida, strict=True) if a != b]
    return len(distintas) == 1 and frozenset(distintas[0]) in _CONFUSIONES


def calidad(palabras: Sequence[str], conocidas: Collection[str]) -> float:
    """Cuánto parece un nombre: palabras conocidas, posibles e imposibles."""
    total = 0.0
    for palabra in palabras:
        if palabra in CONECTORES or len(palabra) < 2:
            continue
        if palabra in conocidas:
            total += 2
        elif parece_palabra_de_nombre(palabra):
            # Una posible pero desconocida vale poco: no puede ganar a una conocida.
            total += 0.5
        else:
            total -= 2
    return total


def consenso(
    candidatos: Sequence[tuple[str | None, float]],
    conocidas: Collection[str] = (),
    *,
    titulo: str | None = None,
    de_pila: Collection[str] = (),
    apellidos: Collection[str] = (),
) -> Consenso:
    """El nombre de todas las lecturas, votado palabra a palabra.

    ``candidatos`` son los nombres leídos, cada uno con su peso -- una lectura
    de la IA cuenta doble --; ``conocidas``, las palabras que se saben de
    nombre. Se elige como base la lectura que más palabras confirmadas trae
    -- así gana la que tiene los apellidos sobre la que los cortó -- y cada una
    de sus palabras se cambia por la variante más votada entre las lecturas
    alineadas con ella; en un empate, la que el diccionario conoce.
    """
    conocidas = set(conocidas)
    lecturas = [
        (palabras_de(nombre, titulo=titulo, conocidas=conocidas), peso)
        for nombre, peso in candidatos
        if nombre
    ]
    lecturas = [(palabras, peso) for palabras, peso in lecturas if len(palabras) >= 2]
    if not lecturas:
        return Consenso(None, False, 0)

    def apoyo(palabra: str, propia: int) -> float:
        return sum(
            peso
            for indice, (otras, peso) in enumerate(lecturas)
            if indice != propia and any(_parecido(palabra, otra) >= PARECIDO_DE_LA_MISMA for otra in otras)
        )

    def puntos(indice: int) -> float:
        palabras = lecturas[indice][0]
        total = 0.0
        for palabra in palabras:
            if palabra in CONECTORES or len(palabra) < 2:
                continue
            if apoyo(palabra, indice) > 0 or palabra in conocidas:
                total += 1.0
            elif parece_palabra_de_nombre(palabra):
                # Una palabra posible que sólo trae esta lectura también cuenta:
                # es el apellido que las otras cortaron (DABEIBA, MONTAÑEZ NIÑO).
                total += 0.3
            else:
                total -= 1.0
        return total + 0.1 * lecturas[indice][1]

    base_indice = max(range(len(lecturas)), key=puntos)
    base = _con_lo_que_le_falta(
        list(lecturas[base_indice][0]), lecturas, base_indice, conocidas, de_pila, apellidos
    )

    # Cada palabra de la base, por la variante más votada de las alineadas.
    variantes: list[Counter] = [Counter({palabra: lecturas[base_indice][1]}) for palabra in base]
    for indice, (otras, peso) in enumerate(lecturas):
        if indice == base_indice:
            continue
        for en_base, en_otra in _alinear(base, otras):
            variantes[en_base][otras[en_otra]] += peso
    elegidas: list[str] = []
    for palabra, votos in zip(base, variantes, strict=True):
        if palabra in CONECTORES:
            elegidas.append(palabra)
            continue
        mejor = max(
            votos,
            key=lambda v: (votos[v], v in conocidas, parece_palabra_de_nombre(v), -abs(len(v) - len(palabra))),
        )
        if mejor not in conocidas:
            # Una variante conocida gana a la desconocida que se le parece,
            # aunque tenga menos votos: dos lecturas de la misma imagen se
            # equivocan igual -- ENCARDO por EDGARDO, HARIA por MARIA --, y el
            # diccionario no se equivoca de esa manera.
            conocidas_aqui = [
                v for v in votos if v in conocidas and _parecido(v, mejor) >= PARECIDO_DE_LA_MISMA
            ]
            if conocidas_aqui:
                mejor = max(conocidas_aqui, key=lambda v: votos[v])
        # Un empate entre una palabra imposible y una conocida lo gana la conocida
        # aunque tenga menos votos: «HARIA» contra «MARIA».
        if mejor not in conocidas and not parece_palabra_de_nombre(mejor):
            conocida = next((v for v in votos if v in conocidas), None)
            if conocida:
                mejor = conocida
        if mejor not in conocidas and votos[mejor] <= lecturas[base_indice][1]:
            # Nadie más la votó: si el diccionario conoce una casi igual, es ésa.
            parecida = difflib.get_close_matches(mejor, conocidas, n=1, cutoff=0.8)
            if parecida and not parece_palabra_de_nombre(mejor):
                mejor = parecida[0]
        if mejor not in conocidas and votos[mejor] < 2:
            # Las lecturas no se ponen de acuerdo -- VARIA, HARIA, ARIA, MARRA --
            # pero todas se parecen a una misma palabra conocida: es ésa (MARIA).
            mejor = _la_conocida_de_todas(votos, conocidas) or mejor
        if mejor not in conocidas and len(mejor) >= 3:
            casi = [
                c
                for c in difflib.get_close_matches(mejor, conocidas, n=1, cutoff=PARECIDO_PARA_CORREGIR)
                if c[0] == mejor[0]
            ] or [c for c in conocidas if _una_confusion(mejor, c)][:1]
            if casi:
                mejor = casi[0]
        elegidas.append(mejor)
    # Lo que no puede ser de un nombre se queda fuera: una palabra imposible
    # («NAANNANCANAACANAA») o un resto de dos letras que nadie conoce («UZ», «ME»).
    elegidas = [
        p
        for p in elegidas
        if p in CONECTORES
        or p in conocidas
        or len(p) == 1
        or (len(p) > 2 and parece_palabra_de_nombre(p))
    ]
    elegidas = _sin_conectores_sueltos(_ordenado(_sin_trozos(elegidas)))
    if len([p for p in elegidas if p not in CONECTORES and len(p) > 1]) < 2:
        return Consenso(None, False, len(lecturas))

    def votos_de(palabra: str) -> float:
        return sum(peso for otras, peso in lecturas if palabra in otras)

    confirmado = all(
        palabra in CONECTORES or palabra in conocidas or votos_de(palabra) >= 3
        for palabra in elegidas
    )
    dudoso = any(
        palabra not in CONECTORES
        and len(palabra) > 1
        and palabra not in conocidas
        and (votos_de(palabra) < 2 or not parece_palabra_de_nombre(palabra))
        for palabra in elegidas
    )
    return Consenso(" ".join(elegidas), confirmado, len(lecturas), dudoso)


#: Desde cuánto parecido una variante leída cuenta como la palabra conocida.
PARECIDO_A_LA_CONOCIDA = 0.75


def _la_conocida_de_todas(votos: Counter, conocidas: set[str]) -> str | None:
    """La palabra conocida a la que se parecen más variantes, si son al menos dos votos."""
    mejor, sus_votos = None, 0.0
    for variante in votos:
        for conocida in difflib.get_close_matches(variante, conocidas, n=3, cutoff=PARECIDO_A_LA_CONOCIDA):
            total = sum(
                v for otra, v in votos.items() if _parecido(otra, conocida) >= PARECIDO_A_LA_CONOCIDA
            )
            if total > sus_votos:
                mejor, sus_votos = conocida, total
    return mejor if sus_votos >= 2 else None


def _con_lo_que_le_falta(
    base: list[str],
    lecturas: list[tuple[list[str], float]],
    base_indice: int,
    conocidas: set[str],
    de_pila: Collection[str] = (),
    apellidos: Collection[str] = (),
) -> list[str]:
    """La base con el nombre de pila o el apellido que sólo trae otra lectura más completa.

    «GONZALEZ VIDES» lo leen bien dos lecturas y una tercera trae además
    «SUILLERMO» delante: es GUILLERMO. Sólo se añade lo que va antes de la
    primera palabra de la base o después de la última, de una lectura que
    contiene a la base entera, y si es una palabra conocida o casi.
    """
    for indice, (otras, _peso) in enumerate(lecturas):
        if indice == base_indice:
            continue
        parejas = _alinear(base, otras)
        utiles = [i for i, palabra in enumerate(base) if palabra not in CONECTORES]
        if len({a for a, _ in parejas} & set(utiles)) < len(utiles):
            continue
        primera, ultima = parejas[0][1], parejas[-1][1]
        # Delante sólo van nombres de pila, y detrás sólo apellidos: «ROSA MARIA
        # ANA» o «RUIZ STELLA» serían palabras de otro renglón.
        delante = [_conocida_o_none(p, set(de_pila) or conocidas) for p in otras[:primera]]
        detras = [_conocida_o_none(p, set(apellidos) or conocidas) for p in otras[ultima + 1 :]]
        if delante and all(delante) and len(delante) <= 2:
            base = [*delante, *base]
        if detras and all(detras) and len(detras) <= 2:
            base = [*base, *detras]
    return base


def _conocida_o_none(palabra: str, conocidas: set[str]) -> str | None:
    if palabra in conocidas:
        return palabra
    parecida = difflib.get_close_matches(palabra, conocidas, n=1, cutoff=0.8)
    return parecida[0] if parecida else None


def sin_perder_conocidas(
    leidas: Sequence[str], votadas: Sequence[str], conocidas: Collection[str]
) -> list[str] | None:
    """El nombre votado sin perder ninguna palabra conocida del leído, o ``None``.

    El voto no puede empeorar lo que ya estaba bien: si la lectura original
    traía EDGARDO y el voto dice ENCARDO, se repone EDGARDO en su sitio --
    el de la palabra desconocida que más se le parece --. Si no hay dónde
    reponerla, el voto no vale y se queda el nombre leído.
    """
    resultado = list(votadas)
    for palabra in leidas:
        if palabra not in conocidas or len(palabra) <= 2 or palabra in resultado:
            continue
        sitios = [
            i
            for i, otra in enumerate(resultado)
            if otra not in conocidas and otra not in CONECTORES and _parecido(palabra, otra) >= 0.5
        ]
        if not sitios:
            return None
        sitio = max(sitios, key=lambda i: _parecido(palabra, resultado[i]))
        resultado[sitio] = palabra
    return resultado


# -- la cédula ----------------------------------------------------------------

CIFRAS_DE_UNA_CEDULA = (6, 10)


def consenso_de_cedulas(candidatas: Sequence[tuple[str | None, float]]) -> tuple[str | None, bool]:
    """La cédula más votada entre las lecturas, y si más de una coincide.

    El «1» de más delante -- «133155659» por 33155659, del «No.l» leído como
    cifra -- se cuenta como la otra cuando otra lectura trae el número sin él.
    """
    votos: Counter = Counter()
    for cedula, peso in candidatas:
        cifras = re.sub(r"\D", "", cedula or "")
        if CIFRAS_DE_UNA_CEDULA[0] <= len(cifras) <= CIFRAS_DE_UNA_CEDULA[1]:
            votos[cifras] += peso
    if not votos:
        return None, False
    for cifras in list(votos):
        corta = cifras[1:]
        if cifras.startswith("1") and len(cifras) == 9 and corta in votos:
            votos[corta] += votos.pop(cifras)
    ordenadas = votos.most_common()
    ganadora, cuantos = ordenadas[0]
    empate = len(ordenadas) > 1 and ordenadas[1][1] == cuantos
    return (None if empate else ganadora), cuantos >= 2 and not empate
