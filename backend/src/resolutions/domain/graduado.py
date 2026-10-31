"""Quién se graduó en un acta de grado: su nombre, su título, su cédula y el número del acta.

Es lo que lleva cada fila del FUID de actas de grado -- «ACTA DE GRADO No. 01/05
- MARTHA LUCIA HERRERA VILLAMIZAR - ESPECIALISTA EN GESTION DE LA CALIDAD Y
AUDITORIA EN SALUD», con la cédula como consecutivo --, leído del texto de la
hoja del graduado.

El acta es un formulario, y su texto llega de dos maneras:

* **Moderna** (2016 en adelante), impresa de corrido y en orden: «otorga el
  título de; / ENFERMERO / A / ANDRES FELIPE BALLESTAS MENDOZA / Portador de la
  cédula de ciudadanía N°. 1.049.539.266».
* **De formulario** (1980-2015), los huecos rellenos a máquina y la capa de
  texto en otro orden: el título detrás de «el título de:», el nombre en el
  renglón siguiente o detrás de «al profesional», la cédula detrás de
  «ciudadanía No.», y el título otra vez al final: «ejercicio profesional como:
  ENFERMERA».

Lo que no se lee con seguridad no se inventa: sale ``None``, o se marca dudoso
para que la fila lo diga.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Graduado:
    """Lo que el acta dice del graduado. ``None`` donde no se pudo leer."""

    nombre: str | None = None
    titulo: str | None = None
    cedula: str | None = None
    #: El número del acta como va impreso: «01/05», «082-2005», «054231116».
    numero: str | None = None
    #: Qué se leyó pero no es seguro, dicho para la columna de notas.
    dudas: tuple[str, ...] = ()


def _sin_tildes(texto: str) -> str:
    return unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()


def _clave(texto: str) -> str:
    """Para buscar: sin tildes y en mayúsculas, con el mismo largo que el texto."""
    return "".join(_sin_tildes(letra).upper() or "?" for letra in texto)


# -- el número del acta -------------------------------------------------------

#: «ACTA DE GRADO No. 01/05», «ACTA DE GRADO N". 054231116», «No. oi», y sin
#: el «No.» que a veces se come el OCR: «ACTA DE GRADO 05416596», «W. 05417669».
_NUMERO = re.compile(
    r"ACTA\s+DE\s+GRADO\s+(?:[NW][O?]?\W{0,3}\s*)?(?P<numero>[0-9A-Z][0-9A-Z/\-]{0,14})(?![A-Z0-9])"
)
#: Las letras que el OCR pone por cifras en un número: «oi» es «01», «054i6609»
#: es «05416609», «05420B84» es «05420884».
_LETRA_A_CIFRA = str.maketrans("OILSBZG", "0115826")
#: Cuántas letras se le perdonan a un número largo antes de no creérselo.
LETRAS_EN_UN_NUMERO = 1


def numero_impreso(texto: str) -> str | None:
    """El número del acta tal como va impreso, con su barra o su guion."""
    for match in _NUMERO.finditer(_clave(texto)):
        crudo = match.group("numero").strip("/-")
        cifras = sum(1 for letra in crudo if letra.isdigit())
        letras = sum(1 for letra in crudo if letra.isalpha())
        # Uno corto sólo de letras -- «oi» -- o uno con pocas letras entre
        # muchas cifras; un «ACTA DE GRADO EN» no es un número.
        if not (letras <= LETRAS_EN_UN_NUMERO and cifras >= 1) and not (cifras == 0 and len(crudo) <= 2):
            continue
        numero = crudo.translate(_LETRA_A_CIFRA)
        if re.fullmatch(r"\d+(?:[/-]\d+)?", numero) and numero.strip("0/-"):
            return numero
    return None


# -- la cédula ----------------------------------------------------------------

#: «cédula de ciudadanía N°. 1.049.539.266», «ciudadanía No. 45.532.54S».
_CEDULA = re.compile(
    r"CIUDADANIA\W{0,4}(?:NO\W{0,3}|N\W{0,3})?\s*(?P<cifras>[0-9SOIL][0-9SOIL.,\s]{4,18}[0-9SOIL])"
)
_CIFRAS_DE_CEDULA = str.maketrans("SOIL", "5011")
#: Las cédulas colombianas de los graduados van de 6 a 10 cifras; menos es un
#: trozo de otra cifra.
CIFRAS_DE_UNA_CEDULA = (6, 10)


#: Un número con puntos de miles: «50.847.263», «45.532.54S», «468.662».
_CON_PUNTOS = re.compile(r"(?<![\dA-Z])(?P<cifras>[0-9SOIL]{1,3}(?:\s?[.,]\s?[0-9SOIL]{3}){1,3})(?![\d])")
#: El apóstrofo con que se separaban los millones a máquina: «45'430.411».
_APOSTROFOS = str.maketrans({"’": ".", "‘": ".", "'": ".", "´": ".", "`": "."})
#: Lo que va delante de un número que no es la cédula.
_NO_ES_CEDULA = re.compile(r"(RESOLUCION|FECHA|DE)\W{0,4}N?\W{0,4}$")
DISTANCIA_A_LA_CEDULA = 400
DISTANCIA_DELANTE = 120


def cedula(texto: str) -> str | None:
    """La cédula del graduado, sin puntos: «1049539266»."""
    clave = _clave(texto.translate(_APOSTROFOS))
    pegada = _cedula_pegada(clave)
    if pegada:
        return pegada
    # En el formulario el número queda renglones más abajo de «ciudadanía»:
    # «portador de la cédula de ciudadanía / a quien se le tomó / PEREZ REYES /
    # No 50.847.263».
    inicio = clave.find("CIUDADANIA")
    if inicio < 0:
        return None
    # Detrás, y si no, justo delante: la capa a veces pone «1.047.473.026
    # expedida en / Portador de la cédula de ciudadanía N°.».
    detras = list(_CON_PUNTOS.finditer(clave, inicio, inicio + DISTANCIA_A_LA_CEDULA))
    delante = list(_CON_PUNTOS.finditer(clave, max(0, inicio - DISTANCIA_DELANTE), inicio))
    for match in [*detras, *reversed(delante)]:
        if _NO_ES_CEDULA.search(clave[max(0, match.start() - 20) : match.start()]):
            continue
        limpias = re.sub(r"[.,\s]", "", match.group("cifras")).translate(_CIFRAS_DE_CEDULA)
        minimo, maximo = CIFRAS_DE_UNA_CEDULA
        sin_ceros = limpias.lstrip("0")
        if limpias.isdigit() and minimo <= len(sin_ceros) <= maximo:
            return sin_ceros
    return None


def _cedula_pegada(clave: str) -> str | None:
    """La cédula que va justo detrás de «ciudadanía N°.»."""
    for match in _CEDULA.finditer(clave):
        cifras = match.group("cifras")
        # Hasta el primer salto de renglón con algo que no sea cifra detrás.
        cifras = re.split(r"\s{2,}|\n", cifras)[0]
        limpias = re.sub(r"[.,\s]", "", cifras).translate(_CIFRAS_DE_CEDULA)
        minimo, maximo = CIFRAS_DE_UNA_CEDULA
        sin_ceros = limpias.lstrip("0")
        if limpias.isdigit() and minimo <= len(sin_ceros) <= maximo:
            return sin_ceros
    return None


# -- el título ----------------------------------------------------------------

#: El título al final del acta: «ejercicio profesional como: ENFERMERA».
_COMO = re.compile(r"PROFESIONAL\s+COMO\W{0,2}\s*(?P<titulo>[^,\n]+?)\s*(?:,|SEGUN|\n|$)")
#: Y al principio: «el título de: ENFERMERA», «otorga el título de; / ENFERMERO».
_TITULO_DE = re.compile(r"TITULO\s+DE\W{0,2}[ \t]*\n?[ \t]*(?P<titulo>[^\n]+)")
#: Lo que se cuela en el renglón del título en el formulario.
#: Lo que se cuela detrás del título: el rótulo «al estudiante» -- también mal
#: leído, «3L ESTUDIANTE», «A(F ESTUDIANTE» --, con lo que lo sigue.
_COLA_DEL_TITULO = re.compile(r"\s+\S{0,3}\s*(?:LA\s+)?(?:PROFESIONAL|ESTUDIANTE|SENOR\w*)\b.*$")
#: Un trozo del relleno de la máquina: «,X.XEXOXOXO», «X.X.X».
_TROZO_DE_RELLENO = re.compile(r"X[.,]?[A-Z]?[.,]?X", re.IGNORECASE)


def _sin_cola(titulo_leido: str) -> str:
    """El título sin el rótulo que lo sigue ni el relleno de la máquina."""
    titulo_leido = _COLA_DEL_TITULO.sub("", titulo_leido)
    palabras = []
    for palabra in titulo_leido.split():
        if _TROZO_DE_RELLENO.search(palabra) or not any(letra.isalpha() for letra in palabra):
            break
        palabras.append(palabra)
    return " ".join(palabras).strip(" .,;:-")


#: El relleno de la máquina de escribir detrás de un dato: «ENFERMERA .X.X.X.X».
_RELLENO = re.compile(r"\s*[.,]?(?:X[.,]){2,}X?[.,]*|\s*[-_—–=~•]{2,}.*$", re.IGNORECASE)


def _limpio(texto: str) -> str:
    """Mayúsculas, un espacio entre palabras y sin signos ni relleno a los lados."""
    texto = _RELLENO.sub("", texto)
    return re.sub(r"\s+", " ", texto).strip(" .,:;-_'\"—•").upper()


def _es_texto_limpio(texto: str) -> bool:
    """Sólo letras y espacios: lo que un nombre o un título deben ser."""
    return bool(texto) and all(letra.isalpha() or letra in " .'" for letra in texto)


def titulo(texto: str) -> str | None:
    """El título que se otorga: «ESPECIALISTA EN GESTION DE LA CALIDAD Y AUDITORIA EN SALUD»."""
    clave = _clave(texto)
    candidatos = []
    for patron in (_COMO, _TITULO_DE):
        for match in patron.finditer(clave):
            inicio, fin = match.span("titulo")
            original = _sin_cola(_limpio(texto[inicio:fin]))
            if len(original) >= 4:
                candidatos.append(original)
    # El de «como:» va entero en un renglón; el de «título de:» a veces se parte
    # con el nombre en medio. Entre los dos, el limpio y más largo.
    limpios = [c for c in candidatos if _es_texto_limpio(c)]
    if limpios:
        return max(limpios, key=len)
    return candidatos[0] if candidatos else None


# -- el nombre ----------------------------------------------------------------

#: Palabras que no son de un nombre aunque vayan en mayúsculas en su renglón.
_NO_SON_NOMBRE = {
    "CARTAGENA", "EXPEDIDA", "CIUDADANIA", "PORTADOR", "PORTADORA", "UNIVERSIDAD",
    "COLOMBIA", "BOLIVAR", "BOL", "DECANO", "DECANA", "RECTOR", "RECTORA", "SECRETARIO",
    "SECRETARIA", "GENERAL", "ACTA", "GRADO", "TITULO", "FACULTAD", "CEDULA",
    "JURAMENTO", "DIPLOMA", "ESTUDIANTE", "PROFESIONAL", "RESOLUCION", "FECHA",
    "CEREMONIA", "SOLEMNE", "COLECTIVA", "PRIVADA", "GRADUACION", "QUIEN", "RECTORIA",
    "JURADO", "ESTABA", "ESTE", "CONFORMADO", "INTEGRADO", "ENFERMERA", "ENFERMERO",
    "ENFERMERIA", "LICENCIADA", "LICENCIADO", "ESPECIALISTA", "MAGISTER", "ODONTOLOGO",
    "ODONTOLOGA", "PROFESION", "SEGUN", "DISPOSICIONES",
}
_CONECTORES = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "SAN", "SANTA"}

#: «al profesional MARTHA LUCIA HERRERA VILLAMIZAR ,portador de la cédula».
_EN_EL_RENGLON = re.compile(
    r"\bAL?\s+(?:LA\s+)?(?:PROFESIONAL|ESTUDIANTE|SENOR(?:A|ITA)?|EGRESAD[OA])?\s*"
    r"(?P<nombre>[A-Z][A-Z .']{4,70}?)\s*,?\s*PORTADOR"
)


def _como_nombre(texto: str) -> str:
    """El candidato a nombre sin lo que se le pega: «AL ESTUDIANTE» delante, lo
    que va detrás de una coma -- un nombre no lleva comas --."""
    texto = texto.split(",")[0]
    sin_prefijo = _TRAS_EL_ESTUDIANTE.match(_clave(texto))
    if sin_prefijo:
        texto = texto[sin_prefijo.end() :]
    return _limpio(texto)


#: Cuánto se tiene que parecer una palabra a una del formulario para serlo: el
#: OCR escribe «al atediante» por «al estudiante», y eso no es un nombre.
PARECIDO_AL_FORMULARIO = 0.7


def _es_del_formulario(clave: str) -> bool:
    if clave in _NO_SON_NOMBRE:
        return True
    if len(clave) < 7:
        return False
    return bool(
        difflib.get_close_matches(clave, _RODEAN_AL_NOMBRE, n=1, cutoff=PARECIDO_AL_FORMULARIO)
    )


#: Las palabras del formulario que van pegadas al nombre y que el OCR estropea:
#: sólo éstas se comparan por parecido. Con toda la lista, «FERNANDO» se
#: parecía a «ENFERMERO» y se perdían nombres de verdad.
_RODEAN_AL_NOMBRE = ("ESTUDIANTE", "PROFESIONAL", "PORTADOR", "PORTADORA", "CIUDADANIA", "EXPEDIDA")


def _parece_nombre(renglon: str, titulo_leido: str | None) -> bool:
    palabras = renglon.split()
    if not 2 <= len(palabras) <= 7:
        return False
    if titulo_leido and _clave(renglon) == _clave(titulo_leido):
        return False
    claves = [_clave(palabra).strip(".'") for palabra in palabras]
    if any(_es_del_formulario(clave) for clave in claves):
        return False
    letras = sum(1 for letra in renglon if letra.isalpha())
    largas = [c for c in claves if c not in _CONECTORES and len(c) >= 2]
    return len(largas) >= 2 and letras >= 0.8 * len(renglon.replace(" ", ""))


#: «al estudiante», «al profesional», «a la señorita», al final de un renglón;
#: a veces pegado al nombre: «AL ESTUDIANTECANDELARIA».
_TRAS_EL_ESTUDIANTE = re.compile(r"\bAL?\s+(?:LA\s+)?(?:ESTUDIANTE|PROFESIONAL|SENOR(?:A|ITA)?|EGRESAD[OA])\W*")
#: Hasta dónde se buscan los apellidos: la cédula y el juramento van después.
_FIN_DEL_NOMBRE = re.compile(r"EXPEDIDA|JURAMENTO|\bN[OQ]?\W{0,3}\d")
RENGLONES_HASTA_LOS_APELLIDOS = 9
PALABRAS_DE_UN_NOMBRE_COMPLETO = 4


def _limpio_de_rayas(texto: str) -> str:
    """Sin las rayas y puntos con que se rellenaba el hueco: «PEREZ REYES -----»."""
    return re.sub(r"[-_.—–=~]{2,}.*$", "", re.sub(r"\s+", " ", texto)).strip(" ,.-_—")


def _solo_palabras(texto: str) -> str:
    """Las palabras del texto, sin la basura que el OCR deja junto a un nombre:
    «marelvis ',3» es «marelvis»."""
    palabras = (palabra.strip(".,;:'\"’`´-") for palabra in texto.split())
    return " ".join(palabra for palabra in palabras if palabra and palabra.isalpha())


def _en_mayusculas(texto: str) -> bool:
    letras = [letra for letra in texto if letra.isalpha()]
    return len(letras) >= 3 and sum(1 for letra in letras if letra.isupper()) >= 0.8 * len(letras)


def _es_formulario(texto: str, titulo_leido: str | None) -> bool:
    """Lo que está en mayúsculas pero no es el nombre: el título, la ciudad, la facultad."""
    clave = _clave(texto)
    if titulo_leido and clave == _clave(titulo_leido):
        return True
    return any(palabra in _NO_SON_NOMBRE for palabra in clave.split()) or bool(re.search(r"\d", clave))


def nombre(texto: str, titulo_leido: str | None = None) -> str | None:
    """El nombre del graduado, en mayúsculas y con sus tildes."""
    renglones = [renglon.strip() for renglon in texto.splitlines()]
    claves = [_clave(renglon) for renglon in renglones]
    hasta = next(
        (i for i, c in enumerate(claves) if "CONSTANCIA" in c or "INTERVINIERON" in c), len(claves)
    )

    # Moderna: el nombre en su renglón, justo antes de «Portador».
    for indice, clave in enumerate(claves[:hasta]):
        if clave.startswith("PORTADOR") and indice >= 1:
            candidato = _como_nombre(renglones[indice - 1])
            if _parece_nombre(candidato, titulo_leido):
                return candidato

    # De formulario: «al estudiante LIGIA DEL PILAR», y los apellidos en el
    # renglón siguiente en mayúsculas, que es como se rellenaba a máquina:
    # «PEREZ REYES ---- portador de la cédula». El texto impreso del formulario
    # va en minúsculas, así que lo que está en mayúsculas es lo que se escribió.
    for indice, clave in enumerate(claves[:hasta]):
        encontrado = _TRAS_EL_ESTUDIANTE.search(clave)
        if not encontrado:
            continue
        partes = []
        # Lo que sigue a «al estudiante» en su renglón es el hueco relleno,
        # aunque el OCR lo bajara a minúsculas: «LIGIA del pilar».
        resto = _solo_palabras(_limpio_de_rayas(renglones[indice][encontrado.end() :]))
        if resto and not _es_formulario(resto, titulo_leido):
            partes.append(resto)
        # Los apellidos pueden quedar varios renglones más abajo: la capa de
        # texto mete por medio «de mayo», «el titulo de enfermera»... Se
        # buscan hasta la cédula o el juramento, que vienen después.
        for siguiente in renglones[indice + 1 : indice + RENGLONES_HASTA_LOS_APELLIDOS]:
            if _FIN_DEL_NOMBRE.search(_clave(siguiente)):
                break
            limpio = _limpio_de_rayas(re.split(r"(?i)\bportador", siguiente)[0])
            if limpio and _en_mayusculas(limpio) and not _es_formulario(limpio, titulo_leido):
                partes.append(limpio)
                if len(" ".join(partes).split()) >= PALABRAS_DE_UN_NOMBRE_COMPLETO:
                    break
        candidato = _como_nombre(" ".join(partes))
        if _parece_nombre(candidato, titulo_leido):
            return candidato

    # En el mismo renglón: «al profesional NOMBRE ,portador».
    plano = re.sub(r"\s+", " ", " ".join(renglones[:hasta]))
    clave_plana = _clave(plano)
    for match in _EN_EL_RENGLON.finditer(clave_plana):
        inicio, fin = match.span("nombre")
        candidato = _como_nombre(plano[inicio:fin])
        if _parece_nombre(candidato, titulo_leido):
            return candidato

    # De formulario: el renglón que sigue al del título.
    for indice, clave in enumerate(claves[:hasta]):
        if "TITULO DE" in clave:
            for siguiente in renglones[indice + 1 : indice + 4]:
                candidato = _como_nombre(siguiente)
                if _parece_nombre(candidato, titulo_leido):
                    return candidato
    return None


def dudas_de(nombre_leido: str | None, titulo_leido: str | None) -> tuple[str, ...]:
    """Lo leído que no es seguro: un nombre o un título con signos que no son letras."""
    dudas = []
    if nombre_leido and not _es_texto_limpio(nombre_leido):
        dudas.append("el nombre trae signos que el OCR no supo leer: revíselo en el papel")
    if titulo_leido and not _es_texto_limpio(titulo_leido):
        dudas.append("el título trae signos que el OCR no supo leer: revíselo en el papel")
    return tuple(dudas)


def cuanto_dice(leido: Graduado) -> int:
    """Cuántos datos del graduado trae una lectura, y limpios: para elegir la mejor."""
    datos = sum(1 for valor in (leido.numero, leido.nombre, leido.titulo, leido.cedula) if valor)
    return datos * 2 - len(leido.dudas)


#: Desde cuánta confianza se cree una palabra leída por Tesseract.
CONFIANZA_ALTA = 80.0
#: Por debajo de esto una palabra sin pareja no se usa: es una mancha.
CONFIANZA_MINIMA = 40.0
#: Cuánto se tienen que parecer dos palabras para ser la misma mal leída.
PARECIDO_DE_PALABRA = 0.55
_RELLENO_PEGADO = re.compile(r"[.,]?(?:X[.,]?){2,}.*$|[.,\-—=]+$", re.IGNORECASE)


def _confianza_de(palabra: str, confianza: Mapping[str, float]) -> float:
    """La confianza de una palabra, aunque Tesseract la leyera pegada a otra cosa.

    «MARTINEZ,x.X.X.X» lleva el relleno de la máquina pegado y sale con 5;
    la palabra en sí está bien leída. «estudiantecISELA» va pegada al rótulo.
    """
    clave = palabra.upper()
    if clave in confianza:
        return confianza[clave]
    for otra, valor in confianza.items():
        if clave and clave in otra:
            resto = _RELLENO_PEGADO.sub("", otra)
            # Lo que sobraba era relleno: la palabra está bien leída.
            if resto == clave and resto != otra:
                return max(valor, CONFIANZA_ALTA)
            return valor
    return 0.0


def _parecido(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _clave(a), _clave(b)).ratio()


def _alinear(franja: list[str], capa: list[str]) -> list[tuple[int, int]]:
    """Las parejas de palabras de las dos lecturas que son la misma, en orden.

    Como un diff de palabras: la alineación que más parecido junta sin cruzar
    el orden. Emparejar cada palabra con la más parecida suelta junta «NORA»
    con «BORDA» y descoloca el nombre entero.
    """
    filas, columnas = len(franja), len(capa)
    puntos = [[0.0] * (columnas + 1) for _ in range(filas + 1)]
    for a in range(1, filas + 1):
        for b in range(1, columnas + 1):
            parecido = _parecido(franja[a - 1], capa[b - 1])
            juntas = puntos[a - 1][b - 1] + parecido if parecido >= PARECIDO_DE_PALABRA else -1.0
            puntos[a][b] = max(puntos[a - 1][b], puntos[a][b - 1], juntas)
    parejas: list[tuple[int, int]] = []
    a, b = filas, columnas
    while a and b:
        parecido = _parecido(franja[a - 1], capa[b - 1])
        if parecido >= PARECIDO_DE_PALABRA and puntos[a][b] == puntos[a - 1][b - 1] + parecido:
            parejas.append((a - 1, b - 1))
            a, b = a - 1, b - 1
        elif puntos[a][b] == puntos[a - 1][b]:
            a -= 1
        else:
            b -= 1
    return parejas[::-1]


def fusionar_nombres(
    capa: str | None, franja: str | None, confianza: Mapping[str, float]
) -> tuple[str | None, bool]:
    """El nombre de las dos lecturas, palabra a palabra, y si queda alguna dudosa.

    La capa del escáner y la franja releída con Tesseract se equivocan en
    sitios distintos: «LEONOR CAMPO TORREGROZA» y «ETILVIA TEDIDE CAAO
    TORRCECOIDA» son «ETILVIA LEONOR CAMPO TORREGROZA». Se alinean como un diff:

    * dos palabras que son la misma -- «CAAO» y «CAMPO» -- dejan la de la franja
      si Tesseract la leyó con confianza, y si no la de la capa;
    * entre dos parejas, lo que sobra en cada lectura: si sobra lo mismo en las
      dos, cada palabra ocupa el sitio de la otra; si no, se quedan las de la
      franja leídas con confianza y las de la capa;
    * lo que a una lectura le falta al principio o al final lo pone la otra.
    """
    palabras = [p for p in (franja or "").split() if p.isalpha()]
    de_la_capa = [p for p in (capa or "").split() if p.isalpha()]
    if not palabras:
        return (" ".join(de_la_capa) or None), False
    if not de_la_capa:
        return " ".join(palabras), any(
            _confianza_de(p, confianza) < CONFIANZA_ALTA for p in palabras
        )
    salida: list[str] = []
    dudoso = False

    def hueco(de_franja: list[str], de_capa: list[str]) -> None:
        nonlocal dudoso
        if de_franja and de_capa and len(de_franja) == len(de_capa):
            for palabra, otra in zip(de_franja, de_capa, strict=True):
                if _confianza_de(palabra, confianza) >= CONFIANZA_ALTA:
                    salida.append(palabra)
                else:
                    salida.append(otra)
                    dudoso = True
            return
        seguras = [p for p in de_franja if _confianza_de(p, confianza) >= CONFIANZA_ALTA]
        if not de_capa:
            regulares = [p for p in de_franja if _confianza_de(p, confianza) >= CONFIANZA_MINIMA]
            dudoso = dudoso or len(regulares) > len(seguras)
            salida.extend(regulares)
            return
        salida.extend(seguras)
        salida.extend(de_capa)

    anterior_f, anterior_c = 0, 0
    for en_franja, en_capa in _alinear(palabras, de_la_capa):
        hueco(palabras[anterior_f:en_franja], de_la_capa[anterior_c:en_capa])
        palabra, otra = palabras[en_franja], de_la_capa[en_capa]
        if palabra == otra or _confianza_de(palabra, confianza) >= CONFIANZA_ALTA:
            salida.append(palabra)
        else:
            salida.append(otra)
            dudoso = dudoso or _confianza_de(palabra, confianza) < CONFIANZA_MINIMA
        anterior_f, anterior_c = en_franja + 1, en_capa + 1
    hueco(palabras[anterior_f:], de_la_capa[anterior_c:])
    return " ".join(salida) or None, dudoso


def _confianza_media(texto: str | None, confianza: Mapping[str, float]) -> float:
    palabras = [p for p in (texto or "").split() if p.isalpha()]
    if not palabras:
        return 0.0
    return sum(_confianza_de(p, confianza) for p in palabras) / len(palabras)


def _confianza_de_cifras(cifras: str, confianza: Mapping[str, float]) -> float:
    """Lo seguro que estuvo Tesseract del número: «45'366.705» es la cédula 45366705."""
    return max(
        (valor for clave, valor in confianza.items() if re.sub(r"\D", "", clave) == cifras),
        default=0.0,
    )


#: Desde cuánta confianza media se cree el título releído.
CONFIANZA_DEL_TITULO = 75.0
#: Y desde cuánta, la cédula releída cuando no coincide con la de la capa.
CONFIANZA_DE_LA_CEDULA = 85.0
#: Cuánto se tiene que parecer un título suelto a uno repetido del libro para
#: tenerlo por el mismo mal leído.
PARECIDO_DEL_TITULO = 0.75


# -- limpieza para el FUID y el nombre del archivo (2026-10-31) -------------------
#
# Medido en «16. SECRETARIA 3292» contra el modelo del operador (749 graduados):
# 8 de 54 nombres de UPD3859822 salían con un trozo del título pegado
# («… TNGENIERO», «TITULODE INGENIERA ODALIS…»), 2 con la «X» con que se chuleó
# la resolución («BAENAX»), y títulos que eran renglones del formulario
# («CIUDADANÍA NO», «SEGÚN LAS DISPOSICIONES LEGALES VIGENTES»).

#: Las palabras de un título que se pegan al nombre leído con OCR.
_DEL_TITULO = (
    "INGENIERO", "INGENIERA", "TITULO", "TITULODE", "QUIMICO", "QUIMICA", "ADMINISTRADOR",
    "ADMINISTRADORA", "RESOLUCION", "ABOGADO", "ABOGADA", "MEDICO", "MEDICA", "CONTADOR",
    "CONTADORA", "LICENCIADO", "LICENCIADA", "ENFERMERA", "ENFERMERO", "ESPECIALISTA",
)
#: Los comienzos de dos consonantes con que empieza una palabra en español.
_INICIOS_VALIDOS = ("BL", "BR", "CL", "CR", "CH", "DR", "FL", "FR", "GL", "GR", "LL", "PL", "PR", "TR", "RR", "TH", "SH")


def _es_del_titulo(palabra: str, titulo: str | None) -> bool:
    clave = _clave(palabra)
    if titulo and clave in _clave(titulo).split() and clave not in _CONECTORES:
        return True
    return any(
        len(clave) >= 5 and difflib.SequenceMatcher(None, clave, del_titulo).ratio() >= 0.75 for del_titulo in _DEL_TITULO
    )


def _es_basura_corta(palabra: str) -> bool:
    """«N», «TNA», «BBSO»: un trozo de 1 a 4 letras que no empieza como una palabra."""
    clave = _clave(palabra)
    if clave in _CONECTORES:
        return False
    if len(clave) <= 1:
        return True
    return len(clave) <= 4 and clave[0] not in "AEIOU" and clave[1] not in "AEIOU" and clave[:2] not in _INICIOS_VALIDOS


#: Lo de una resolución o del formulario que se queda delante del nombre.
_DE_LA_RESOLUCION = frozenset({
    "USO", "SUS", "ATRIBUCIONES", "LEGALES", "RESUELVE", "SALUD", "CONSIDERANDO", "OTORGAR",
    "OTORGA", "CONFIERE", "CONFERIR",
})
#: Desde cuántas letras una palabra que no está en la lista no es un nombre.
LARGO_IMPOSIBLE = 15

#: Nombres y apellidos que sí terminan en X: la de chequeo no se les quita.
_TERMINAN_EN_X = frozenset({"FELIX", "ALEX", "MAX", "ROUX", "MARX"})


def nombre_limpio(nombre_leido: str | None, titulo_leido: str | None = None, conocidas: Collection[str] = ()) -> str | None:
    """El nombre del graduado sin lo que no es suyo: el título pegado, la basura y la «X» de chequeo."""
    if not nombre_leido:
        return nombre_leido
    palabras = nombre_leido.split()
    # «JOSE MARIO GUARDO ROA INGENIERO CIVIL»: desde la primera palabra del
    # título que va detrás de un nombre de dos palabras o más, nada es nombre.
    corte = next((i for i, palabra in enumerate(palabras) if i >= 2 and _es_del_titulo(palabra, titulo_leido)), None)
    if corte is not None:
        palabras = palabras[:corte]
    cambio = True
    while palabras and cambio:
        cambio = False
        for indice in (0, -1):
            if palabras and (_es_del_titulo(palabras[indice], titulo_leido) or _es_basura_corta(palabras[indice])):
                palabras.pop(indice)
                cambio = True
    # «USO DE SUS ATRIBUCIONES LEGALES Y CORREA…», «SALUD REINALDO…», «SA DIANA…»:
    # lo de la resolución o del renglón de arriba que quedó delante (Secretaría
    # 3292, procesada el 2026-10-31).
    while palabras:
        primera = _clave(palabras[0])
        siguiente = next((_clave(p) for p in palabras[1:] if _clave(p) not in _CONECTORES), "")
        if primera in _DE_LA_RESOLUCION or primera == "Y":
            palabras.pop(0)
        elif primera in _CONECTORES:
            # «DE LA HOZ» es un apellido; «DE SUS ATRIBUCIONES», no.
            if siguiente not in _DE_LA_RESOLUCION:
                break
            palabras.pop(0)
        elif len(primera) <= 2 and primera not in conocidas:
            palabras.pop(0)
        else:
            break
    while palabras and (_clave(palabras[-1]) in _CONECTORES or _clave(palabras[-1]) == "EN"):
        palabras.pop()
    limpias = []
    for palabra in palabras:
        clave = _clave(palabra)
        # Una letra suelta o una palabra imposible por larga («COOCOMONMAMANN…»).
        if (len(clave) == 1 and clave not in _CONECTORES) or (len(clave) >= LARGO_IMPOSIBLE and clave not in conocidas):
            continue
        # «BAENAX»: la X con que alguien chuleó la lista, si sin ella es un nombre.
        if clave.endswith("X") and clave not in conocidas and clave not in _TERMINAN_EN_X and (
            clave[:-1] in conocidas or (len(clave) >= 5 and clave[-2] in "AEIOU")
        ):
            palabra = palabra[:-1]
        limpias.append(palabra)
    return " ".join(limpias) or None


#: Lo que el OCR toma por título y es un renglón del formulario.
_NO_ES_TITULO = re.compile(
    r"CIUDADANIA|DISPOSICIONES|EXPEDIDA|PORTADOR|AL ESTUDIANTE|ESRCDIANTE|SOLICITUD|^AL$|^NO$|^ESTUDIANTE$|^GRADO$"
)


#: Lo que sigue al título en el formulario y se le pega: «… AL DOCTOR», «…
#: AL ODONTOLOGO», «… A STUDIANTE», «… A EGRESADO DE LA FACULTAD DE …».
_COLA_DEL_FORMULARIO = re.compile(
    r"[\s,]+(?:AL?\W?|A\s+LA)\s+\W?(?:DOCTOR|ODONTOLOG|MEDIC|E?S?T?UDIANTE|EGRESAD|SENOR|PROFESIONAL)\w*(?:\W.*)?$"
)


#: «… AL ESTUIMANTE», «… AL PROFESTONAL»: la cola mal leída, una palabra tras «AL».
_AL_Y_UNA_PALABRA = re.compile(r"\s+AL\W?\s+\S+$")


def titulo_limpio(titulo_leido: str | None) -> str | None:
    """El título, sin las colas del formulario ni letras sueltas; ``None`` si es un renglón del formulario."""
    if not titulo_leido:
        return None
    clave = _AL_Y_UNA_PALABRA.sub("", _COLA_DEL_FORMULARIO.sub("", _clave(titulo_leido)))
    # Sin letras sueltas ni palabras imposibles por largas («OOOOOOMEANCMCNMM…»).
    palabras = [p for p in clave.split() if (len(p) > 1 or p == "Y") and len(p) < LARGO_IMPOSIBLE]
    while palabras and (palabras[0] in ("RESUELVE", "Y", "DE", "EN") or (len(palabras[0]) <= 3 and not palabras[0].isalpha())):
        palabras.pop(0)
    while palabras and palabras[-1] in ("Y", "DE", "EN", "AL", "LA"):
        palabras.pop()
    titulo = " ".join(palabras).strip(" ,;:.()¿?¡!*\"'“”-")
    if len(titulo) < 4 or _NO_ES_TITULO.search(titulo):
        return None
    # Con sus tildes si el original las traía y no se tocó.
    return titulo_leido if titulo == _clave(titulo_leido) else titulo


def _mismo_titulo(leido: str, otro: str) -> bool:
    """Si ``leido`` es ``otro`` mal leído: palabra por palabra, y no otra especialidad.

    Con el parecido del título entero, ORTODONCIA pasaba a ENDODONCIA y
    ESTRUCTURAS a TEORÍA (Secretaría 3292, 2026-10-31): una especialidad no es
    la otra por compartir «ESPECIALISTA EN».
    """
    una, otra = _clave(leido).split(), _clave(otro).split()
    if "".join(una) == "".join(otra):
        return True
    if len(una) != len(otra):
        return difflib.SequenceMatcher(None, "".join(una), "".join(otra)).ratio() >= 0.93
    return all(difflib.SequenceMatcher(None, a, b).ratio() >= PARECIDO_DEL_TITULO for a, b in zip(una, otra, strict=True))


def _genero(titulo_leido: str) -> str:
    """«INGENIERA CIVIL» → A; «INGENIERO» → O; «CONTADORA» → A; «CONTADOR» → O."""
    primera = "".join(letra for letra in (_clave(titulo_leido).split() or [""])[0] if letra.isalpha())
    if primera.endswith(("A", "ORA")):
        return "A"
    if primera.endswith(("O", "OR")):
        return "O"
    return ""


def _completado(titulo: str | None, titulos: Sequence[str | None]) -> str | None:
    """Un título cortado o con una palabra mal escrita, llevado al repetido del libro.

    «ED EN GESTION DE LA CALIDAD Y AUDITORIA» es «ESPECIALISTA EN GESTION DE LA
    CALIDAD Y AUDITORIA» sin su principio; «ESSPECIALISTA», «ETOMATOLOGIA» son
    palabras que el libro escribe bien en otros títulos (Secretaría 3292).
    """
    from collections import Counter

    if not titulo:
        return titulo
    repetidos = [t for t, n in Counter(t for t in titulos if t).items() if n >= 2 and t != titulo]
    palabras = _clave(titulo).split()
    sin_cabeza = [p for p in palabras if len(p) > 2 or p in ("DE", "EN", "LA", "Y")]
    while sin_cabeza and len(sin_cabeza[0]) <= 2:
        sin_cabeza.pop(0)
    resto = " ".join(sin_cabeza)
    if len(sin_cabeza) >= 3:
        # Sin su comienzo: «ED EN GESTION…», o ya sin la letra suelta, «GESTION…».
        for otro in repetidos:
            if _clave(otro) != resto and _clave(otro).endswith(resto):
                return otro
    del_libro = Counter(p for t in titulos if t for p in _clave(t).split() if len(p) >= 5)
    corregidas = []
    for palabra in palabras:
        if palabra.endswith("S") and del_libro[palabra[:-1]] >= 3 * max(del_libro[palabra], 1):
            # «ESPECIALISTAS» donde el libro dice ESPECIALISTA.
            palabra = palabra[:-1]
        elif len(palabra) >= 5:
            parecida = max(
                (otra for otra in del_libro if otra != palabra),
                key=lambda otra: difflib.SequenceMatcher(None, palabra, otra).ratio(),
                default=None,
            )
            if (
                parecida
                and del_libro[parecida] >= 3 * max(del_libro[palabra], 1)
                and difflib.SequenceMatcher(None, palabra, parecida).ratio() >= 0.85
            ):
                palabra = parecida
        corregidas.append(palabra)
    corregido = " ".join(corregidas)
    return titulo if corregido == _clave(titulo) else corregido


def titulos_unificados(titulos: Sequence[str | None]) -> list[str | None]:
    """Los títulos de un libro, con los mal leídos llevados al repetido que se les parece.

    En un libro de grados el título se repite: decenas de ENFERMERA, de
    ESPECIALISTA EN SALUD FAMILIAR. Uno que sale una sola vez y se parece a uno
    repetido -- «ESPECIALISTA ENSALUD FAMILIAR», «ESFECÍAUSTA EÍÍ SALUD
    OCOPACIOÜAL» -- es ése mal leído. Uno que no se parece a ninguno se queda:
    puede ser el único especialista de su promoción.
    """
    from collections import Counter

    titulos = [_completado(t, titulos) for t in titulos]
    cuenta = Counter(t for t in titulos if t)
    repetidos = [t for t, n in cuenta.items() if n >= 2]
    resultado: list[str | None] = []
    for titulo in titulos:
        if not titulo or cuenta[titulo] >= 2 or not repetidos:
            resultado.append(titulo)
            continue
        # Sin cambiar el género: «INGENIERA CIVIL» no es «INGENIERO CIVIL» mal
        # leído (UPD3859822 p. 28).
        del_mismo_genero = [otro for otro in repetidos if _genero(otro) == _genero(titulo)]
        if not del_mismo_genero:
            resultado.append(titulo)
            continue
        mejor = max(del_mismo_genero, key=lambda otro: _parecido(titulo, otro))
        resultado.append(mejor if _mismo_titulo(titulo, mejor) else titulo)
    return resultado


def fusionar(capa: Graduado, franja: Graduado, confianza: Mapping[str, float]) -> Graduado:
    """El graduado de las dos lecturas: la capa del escáner y la franja releída."""
    nombre, dudoso = fusionar_nombres(capa.nombre, franja.nombre, confianza)
    if franja.titulo and _confianza_media(franja.titulo, confianza) >= CONFIANZA_DEL_TITULO:
        titulo = franja.titulo
    else:
        titulo = capa.titulo or franja.titulo
    if franja.cedula and capa.cedula and franja.cedula != capa.cedula:
        seguro = _confianza_de_cifras(franja.cedula, confianza) >= CONFIANZA_DE_LA_CEDULA
        cedula_leida = franja.cedula if seguro else capa.cedula
    else:
        cedula_leida = capa.cedula or franja.cedula
    dudas = list(dudas_de(nombre, titulo))
    if dudoso and nombre:
        dudas.append("el nombre se leyó con letras dudosas: revíselo en el papel")
    return Graduado(
        nombre=nombre,
        titulo=titulo,
        cedula=cedula_leida,
        numero=capa.numero or franja.numero,
        dudas=tuple(dudas),
    )


def graduado(texto: str) -> Graduado:
    """Todo lo que el acta dice del graduado, con lo dudoso señalado."""
    titulo_leido = titulo(texto)
    nombre_leido = nombre(texto, titulo_leido)
    return Graduado(
        nombre=nombre_leido,
        titulo=titulo_leido,
        cedula=cedula(texto),
        numero=numero_impreso(texto),
        dudas=dudas_de(nombre_leido, titulo_leido),
    )
