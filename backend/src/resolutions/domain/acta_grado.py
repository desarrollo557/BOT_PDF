"""Las actas de grado de un PDF: dónde empieza cada una, su número y su fecha.

Medido sobre las cajas 00C003288 a 00C003290 de Odontología, de 1980 a 2025,
hay dos formas de libro:

* **Moderna** (2016 en adelante): un acta por graduado, una por página, con un
  número largo y consecutivo -- «ACTA DE GRADO N°. 054231116», 117, 118… -- y la
  fecha «a los doce (12) días del mes de Diciembre del año 2023». Antes de cada
  ceremonia, una portada y un listado («Actas de Grado No. 05417710 a 05417725»).
* **Antigua** (1980-2005): un acta por ceremonia -- «ACTA DE GRADO No. 03» --
  con el número repetido en una hoja por graduado, y la fecha en letras con la
  cifra entre paréntesis: «a los veintisiete (27) días del mes de Noviembre de
  mil novecientos ochenta (1.980)», muy maltratada por el OCR.

Una sola regla sirve a las dos: **un acta nueva empieza donde cambia su
número**; si el número no se lee, donde cambia la fecha; y ante la duda la hoja
se queda con el acta anterior. El listado y la portada no abren nada: sin
«en la ciudad de…» o «graduación» detrás del encabezado no es un acta, es su
índice o su constancia.

Sólo texto, sin leer imágenes: lo que trae la capa del escaneo.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from .acta_consejo import ActaDeConsejo, ActasDelPdf, TramoDeActa
from .fechas import MESES, fecha_de_la_pagina
from .graduado import cuanto_dice, dudas_de, graduado

ROTULO = "ACTA DE GRADO"

#: «ACTA DE GRADO N°. 054231116», «ACTA DE GRADO NS 03», «ACTA DE GRADO N201»
#: (el º leído como 2), «acta, DE OHADO» (la G y la R que el OCR confunde).
_ENCABEZADO = re.compile(
    r"\bACTAS?\W{0,3}DE\W{0,2}[GCO]?[RH]ADOS?\W{0,3}"
    # El «°» que el OCR lee como 2, S o una O seguida de punto; nunca un 0,
    # que es la primera cifra de los números modernos («054231116»).
    r"(?:N\W{0,2}(?:[º°\"“^»S2]|O(?=\W))?\W{0,3}(?P<numero>\d{1,10}))?"
)
#: El listado de una ceremonia: «Actas de Grado No. 05417710 a 05417725».
_LISTADO = re.compile(r"^\s*(?:A|AL|HASTA)\s+\d{4,}")
#: Lo que sigue al encabezado de un acta de verdad, y no al de su listado o al
#: de una constancia que la cita.
_CUERPO = re.compile(r"EN LA CIUDAD|GRADUACION|DIAS? DEL MES")
VENTANA_DEL_CUERPO = 600

#: «(12) días del mes de Diciembre del año 2023», «(27) días del mes de
#: Noviembre de mil novecientos ochenta (1.980)».
_FECHA = re.compile(
    # El día no va pegado a una «/»: en «No. 29/05 días del mes de Julio» el 05
    # es del número del acta (Secretaría 3292, UPD3859825 p. 44; 2026-10-31).
    # «14( ) días»: el día a máquina delante del paréntesis vacío del formulario
    # (UPD3859808, 2000).
    r"(?<![/\d])\(?\s*(?P<dia>\d{1,2})\s*\(?\s*\)?\s*D\S{0,2}AS?\s+DEL?\s+MES\s+DE\s+(?P<mes>[A-Z]{4,11})\W+"
    r"(?:DEL?\s+)?(?:A\S?O\s+)?(?:[A-Z ]{0,70}?)\(?\s*(?P<anio>(?:19|20)\d\d|[12]\s*[.,]\s*\d\s*\d\s*\d)\b"
)
#: Para cuando el OCR desordenó la frase: el día entre paréntesis, un mes en
#: algún sitio y un año.
_DIA_SUELTO = re.compile(r"\(?\s*(\d{1,2})\s*\(?\s*\)\s*D")
_ANIO_SUELTO = re.compile(r"\(\s*([12]\s*[.,]?\s*\d\s*\d\s*\d)\s*\)|\b((?:19|20)\d\d)\b")
_PALABRA = re.compile(r"[A-Z]{4,11}")
PARECIDO_DEL_MES = 0.7


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.upper())


def _mes(palabra: str) -> int | None:
    palabra = palabra.lower()
    if palabra in MESES:
        return MESES[palabra]
    parecido = difflib.get_close_matches(palabra, list(MESES), n=1, cutoff=PARECIDO_DEL_MES)
    return MESES[parecido[0]] if parecido else None


def _fecha(dia: int, mes: int | None, anio: str) -> date | None:
    if mes is None:
        return None
    try:
        valor = int(re.sub(r"\D", "", anio))
        if not 1900 <= valor <= 2100:
            return None
        return date(valor, mes, dia)
    except ValueError:
        return None


#: Los números que se escriben en letras en un acta de grado: el día y el año.
_UNIDADES = {
    "UN": 1, "UNO": 1, "PRIMERO": 1, "PRIMER": 1, "DOS": 2, "TRES": 3, "CUATRO": 4,
    "CINCO": 5, "SEIS": 6, "SIETE": 7, "OCHO": 8, "NUEVE": 9,
}
_DEL_DIEZ_AL_TREINTA = {
    "DIEZ": 10, "ONCE": 11, "DOCE": 12, "TRECE": 13, "CATORCE": 14, "QUINCE": 15,
    "DIECISEIS": 16, "DIECISIETE": 17, "DIECIOCHO": 18, "DIECINUEVE": 19, "VEINTE": 20,
    "VEINTIUNO": 21, "VEINTIUN": 21, "VEINTIDOS": 22, "VEINTITRES": 23, "VEINTICUATRO": 24,
    "VEINTICINCO": 25, "VEINTISEIS": 26, "VEINTISIETE": 27, "VEINTIOCHO": 28,
    "VEINTINUEVE": 29, "TREINTA": 30,
}
_DECENAS = {
    "VEINTE": 20, "TREINTA": 30, "CUARENTA": 40, "CINCUENTA": 50, "SESENTA": 60,
    "SETENTA": 70, "OCHENTA": 80, "NOVENTA": 90,
}
_PALABRAS_DE_NUMERO = {*_UNIDADES, *_DEL_DIEZ_AL_TREINTA, *_DECENAS, "NOVECIENTOS", "MIL", "Y"}
#: Cuánto se tiene que parecer una palabra mal leída a la de verdad: «NOOENTA» es
#: «NOVENTA», «AIETE» es «SIETE». Sólo en palabras de cinco letras o más: en
#: las cortas una letra cambiada ya es otra palabra.
PARECIDO_DEL_NUMERO = 0.8
#: Dónde acaba la frase de la fecha: lo que sigue es la resolución que autorizó
#: el acto, con su propia fecha.
_FIN_DE_LA_FRASE = re.compile(r"RESOLUCION|QUIEN AUTORIZO|POR MEDIO DE")
LARGO_DE_LA_FRASE = 260


#: Las de cuatro letras sólo se corrigen hacia una unidad o un número del día,
#: y con más exigencia: «SELS» es «SEIS» y «ECHO» es «OCHO», pero «DIAS» no es
#: «DOS».
_CORTAS = [p for p in (*_UNIDADES, *_DEL_DIEZ_AL_TREINTA) if 4 <= len(p) <= 5]
PARECIDO_DE_LAS_CORTAS = 0.75


def _palabra(token: str) -> str | None:
    """La palabra de número que el OCR quiso escribir, o ``None``."""
    if token in _PALABRAS_DE_NUMERO:
        return token
    if len(token) == 4:
        parecida = difflib.get_close_matches(token, _CORTAS, n=1, cutoff=PARECIDO_DE_LAS_CORTAS)
        return parecida[0] if parecida else None
    if len(token) < 5:
        return None
    parecida = difflib.get_close_matches(
        token, list(_PALABRAS_DE_NUMERO), n=1, cutoff=PARECIDO_DEL_NUMERO
    )
    return parecida[0] if parecida else None


#: El año en cifras entre paréntesis, con el punto de los miles: «(1.989)».
_ANIO_ENTRE_PARENTESIS = re.compile(r"\(\s*1\s*[.,]?\s*9\s*(\d)\s*(\d)\s*\)")


def fecha_en_letras(trozo: str) -> date | None:
    """La fecha escrita en letras, aunque el OCR haya desordenado la frase.

    Los libros de 1980 a 2005 son formularios con los huecos rellenos a máquina,
    y la capa de texto los saca en otro orden: «A LOS DE MIL NOVECIENTOS NOVENTA
    Y DOS ONCE DICIEMBRE» es «a los once días del mes de diciembre de mil
    novecientos noventa y dos». Las cifras entre paréntesis salen rotas --
    «(2?)», «(1.9s&)» -- y las letras no: se lee el año detrás de
    «novecientos» o «dos mil», el día en el número que sobra, y el mes donde
    esté. Un año a medias -- «OCHENTA Y» sin la unidad legible -- no se da por
    1980: o se completa con la cifra entre paréntesis o con la unidad que quedó
    más adelante, o no hay fecha.
    """
    tokens = re.findall(r"[A-Z]+", trozo)
    palabras = [_palabra(token) for token in tokens]
    usados: set[int] = set()

    anio = None
    for indice, palabra in enumerate(palabras):
        if palabra == "NOVECIENTOS":
            base, desde = 1900, indice + 1
        elif palabra == "MIL" and indice and palabras[indice - 1] == "DOS":
            base, desde = 2000, indice + 1
            usados.add(indice - 1)
        else:
            continue
        usados.add(indice)
        cola = _cola_del_anio(palabras, desde, base, usados, trozo)
        if cola is not None:
            anio = base + cola
        break
    if anio is None:
        # El día en letras y el año en cifras: «A LOS DIEZ (LO) DIAS DEL MES DE
        # DICIEMBRE DE 2004». Sólo si no había un año en letras a medias, que
        # diría otra cosa.
        if any(palabra == "NOVECIENTOS" for palabra in palabras):
            return None
        en_cifras = re.search(r"\b(?:19|20)\d\d\b", trozo)
        if en_cifras is None:
            return None
        anio = int(en_cifras.group(0))

    dia = None
    for indice, palabra in enumerate(palabras):
        if indice in usados or palabra is None:
            continue
        if palabra in _DEL_DIEZ_AL_TREINTA or palabra in _UNIDADES:
            dia = _UNIDADES.get(palabra) or _DEL_DIEZ_AL_TREINTA[palabra]
            # «VEINTE Y SEIS», «TREINTA Y UNO», y el «DIEZ Y SIETE» de los
            # libros viejos.
            if palabra in ("DIEZ", "VEINTE", "TREINTA") and palabras[indice + 1 : indice + 2] == ["Y"]:
                siguiente = palabras[indice + 2] if indice + 2 < len(palabras) else None
                if siguiente in _UNIDADES:
                    dia += _UNIDADES[siguiente]
            break
    mes = next((m for m in (_mes(token) for token in tokens if len(token) >= 4) if m), None)
    if dia is None or mes is None:
        return None
    return _fecha(dia, mes, str(anio))


_DOS_MIL_EXACTO = re.compile(r"DOS\s+MIL\W*\(\s*2\s*[.,]?\s*0\s*0\s*0\s*\)")


def _cola_del_anio(
    palabras: list[str | None], desde: int, base: int, usados: set[int], trozo: str
) -> int | None:
    """Lo que va detrás de «novecientos» o de «dos mil»: «noventa y dos», «tres»."""
    # «dos mil (2.000)»: el año 2000 no lleva nada detrás de «mil» (UPD3859808).
    if base == 2000 and _DOS_MIL_EXACTO.search(trozo):
        return 0
    # Entre «novecientos» y la decena puede colarse el día -- «MIL NOVECIENTOS
    # UN NOVENTA Y SEIS» -- o una palabra rota; se saltan sin consumirlas.
    for salto in range(3):
        posicion = desde + salto
        if posicion >= len(palabras):
            return None
        palabra = palabras[posicion]
        if palabra in _DECENAS and base == 1900:
            usados.add(posicion)
            return _decena_y_unidad(palabras, posicion, _DECENAS[palabra], usados, trozo)
        if base == 2000 and (palabra in _UNIDADES or palabra in _DEL_DIEZ_AL_TREINTA):
            usados.add(posicion)
            return _UNIDADES.get(palabra) or _DEL_DIEZ_AL_TREINTA[palabra]
    return None


def _decena_y_unidad(
    palabras: list[str | None], posicion: int, decena: int, usados: set[int], trozo: str
) -> int | None:
    """«OCHENTA Y SIETE», «OCHENTA YSIETE», «OCHENTA Y COLECTIVA SIETE» o «NOVENTA»."""
    siguiente = palabras[posicion + 1] if posicion + 1 < len(palabras) else None
    # Pegada: «OCHENTA YSIETE» -- la «Y» se la comió la unidad --.
    if siguiente in _UNIDADES:
        usados.add(posicion + 1)
        return decena + _UNIDADES[siguiente]
    resto = palabras[posicion + 1 : posicion + 4]
    if "Y" not in resto:
        # «MIL NOVECIENTOS NOVENTA DICIEMBRE»: el año es la decena sola.
        return decena
    tras_y = posicion + 1 + resto.index("Y") + 1
    usados.add(tras_y - 1)
    for otra in range(tras_y, min(tras_y + 2, len(palabras))):
        if palabras[otra] in _UNIDADES:
            usados.add(otra)
            return decena + _UNIDADES[palabras[otra]]
    # La unidad no está detrás de la «Y». La cifra entre paréntesis, si es de
    # la misma década: «OCHENTA Y (26) DIAS DEL MES DE (1989)».
    for cifras in _ANIO_ENTRE_PARENTESIS.finditer(trozo):
        if int(cifras.group(1)) * 10 == decena:
            return decena + int(cifras.group(2))
    # O la unidad que el formulario dejó más adelante: «QUINCE DE MIL
    # NOVECIENTOS OCHENTA Y … DICIEMBRE NUEVE».
    for otra in range(tras_y, len(palabras)):
        if palabras[otra] in _UNIDADES and otra not in usados:
            usados.add(otra)
            return decena + _UNIDADES[palabras[otra]]
    # A medias no vale: 1980 por «OCHENTA Y» desordenaba el libro entero.
    return None


def fecha_de_grado(texto: str) -> date | None:
    """La fecha de la ceremonia escrita en el cuerpo del acta, o ``None``."""
    plano = _plano(texto)
    for match in _FECHA.finditer(plano):
        fecha = _fecha(int(match.group("dia")), _mes(match.group("mes")), match.group("anio"))
        if fecha is not None:
            return fecha
    # En letras: el formulario de los libros viejos, con las cifras rotas.
    # Primero detrás de «a los»; y si el día quedó delante -- la capa pone
    # «Diez y siete ( J días del mes de» antes de «En la ciudad» --, la frase
    # entera desde el encabezado del acta.
    inicio = plano.find("A LOS", max(0, plano.find("EN LA CIUDAD")))
    for desde in (inicio, plano.find("ACTA DE GRADO")):
        if desde < 0:
            continue
        frase = plano[desde : desde + LARGO_DE_LA_FRASE + 120]
        fin = _FIN_DE_LA_FRASE.search(frase)
        fecha = fecha_en_letras(frase[: fin.start()] if fin else frase)
        if fecha is not None:
            return fecha
    # El OCR de los libros viejos mezcla la frase: se busca cada pieza por su lado.
    inicio = plano.find("EN LA CIUDAD")
    trozo = plano[inicio : inicio + 400] if inicio >= 0 else plano[:600]
    dia = _DIA_SUELTO.search(trozo)
    anio = _ANIO_SUELTO.search(trozo)
    mes = next((m for m in (_mes(p) for p in _PALABRA.findall(trozo)) if m), None)
    if dia and anio:
        return _fecha(int(dia.group(1)), mes, anio.group(1) or anio.group(2))
    return None


@dataclass(frozen=True, slots=True)
class AperturaDeGrado:
    """Una hoja que abre un acta de grado, con lo que se leyó de ella."""

    pagina: int
    numero: str | None
    fecha: date | None


def apertura(texto: str, pagina: int = 1) -> AperturaDeGrado | None:
    """Si la hoja abre un acta de grado: su número y su fecha, o ``None``."""
    plano = _plano(texto)
    for match in _ENCABEZADO.finditer(plano):
        detras = plano[match.end() :]
        if match.group("numero") and _LISTADO.match(detras):
            continue
        if not _CUERPO.search(detras[:VENTANA_DEL_CUERPO]):
            continue
        numero = match.group("numero")
        # Ningún acta es la cero: «No. 0» es una cifra que el OCR cortó -- el
        # «01» con la segunda leída como letra --, y se trata como no leído
        # para que decida la fecha.
        if numero is not None and not numero.strip("0"):
            numero = None
        return AperturaDeGrado(pagina, numero, fecha_de_grado(texto))
    return None


#: Lo que dice una hoja de la ceremonia que no es de ningún graduado: el
#: listado de graduandos, la resolución que autoriza la ceremonia, la portada o
#: el separador de cada ceremonia («GRADUADOS JULIO 22 DE 2005»).
_DE_LA_CEREMONIA = re.compile(
    r"RESOLUCION\s+N|LISTADO|GRADUANDOS|GRADUADOS|CEREMONIA\s+DE\s+GRADO|ACTAS\s+DE\s+GRADO"
)
#: Lo que trae el cuerpo de un acta de graduado: con tres de cuatro, la hoja es
#: un acta aunque su encabezado no se lea.
_CUERPO_DEL_ACTA = ("EN LA CIUDAD", "GRADUACION", "CIUDADANIA", "JURAMENTO")
CUERPO_MINIMO = 3
GRADUADO = "graduado"
CEREMONIA = "ceremonia"
SIGUE = "sigue"
ROTULO_DE_CEREMONIA = "CEREMONIA DE GRADO"


def clase_de_hoja(texto: str) -> str:
    """Qué es una hoja de un libro de grados: el acta de un graduado, una hoja de
    la ceremonia, o la continuación de lo anterior (su reverso, una nota)."""
    if apertura(texto):
        return GRADUADO
    plano = _plano(texto)
    if sum(1 for marca in _CUERPO_DEL_ACTA if marca in plano) >= CUERPO_MINIMO:
        return GRADUADO
    if _DE_LA_CEREMONIA.search(plano):
        return CEREMONIA
    return SIGUE


def actas_de_grado_del_pdf(
    paginas: Sequence[str], foliadas: Collection[int] | None = None
) -> ActasDelPdf:
    """Cómo se reparte un libro de actas de grado: un tramo por graduado.

    Cada graduado tiene su acta en su hoja -- en los libros modernos con su
    número, en los antiguos con el número de la ceremonia repetido en la hoja de
    cada uno --, así que cada hoja que abre un acta abre el tramo de un
    graduado, y lo que la sigue sin abrir nada -- su reverso, una nota a mano
    -- es suyo. Las hojas de la ceremonia que no son de nadie -- el listado de
    graduandos, la resolución, la portada -- forman su propio tramo, marcado
    como de ceremonia: salen en su PDF y no llevan fila en el FUID.

    ``foliadas`` son las hojas con folio manuscrito en la esquina. Es como el
    archivista dijo qué hojas van juntas: la que lleva folio abre su documento
    y la que sigue sin folio -- el vuelto, «140/V» -- es del anterior. Así la
    resolución de la ceremonia de las páginas 147 y 148 de UPD3859820 es un
    documento de dos páginas, y no el listado de la 146 con la resolución
    pegada. Sin la medida, las hojas de la ceremonia van juntas.

    Cada tramo dice cuántas páginas lleva (``hojas``), que es lo que va en
    «No. de folios»: una, o dos con su vuelto.
    """
    total = len(paginas)
    con_folio = set(foliadas) if foliadas is not None else None
    tramos: list[list] = []  # desde, hasta, ceremonia
    for numero, texto in enumerate(paginas, start=1):
        clase = clase_de_hoja(texto)
        sin_folio = con_folio is not None and numero not in con_folio
        if clase == GRADUADO:
            # El acta de un graduado es su documento aunque su folio no se vea:
            # pegarla a la anterior juntaría a dos graduados en una fila.
            tramos.append([numero, numero, False])
        elif clase == CEREMONIA and tramos and (sin_folio or (con_folio is None and tramos[-1][2])):
            tramos[-1][1] = numero
        elif clase == CEREMONIA or not tramos:
            # Una hoja de la ceremonia con su folio abre su documento: el
            # listado, la resolución. Y lo que va antes de todo -- una portada
            # sin texto -- es de la ceremonia que empieza.
            tramos.append([numero, numero, True])
        else:
            # El vuelto, una nota a mano: de la hoja anterior.
            tramos[-1][1] = numero
    if not tramos:
        return ActasDelPdf(tramos=(TramoDeActa(1, max(1, total)),))
    return ActasDelPdf(
        tramos=tuple(
            TramoDeActa(desde, hasta, ceremonia=ceremonia, hojas=hasta - desde + 1)
            for desde, hasta, ceremonia in tramos
        )
    )


def mejor_lectura(capa: str, formulario: str) -> str:
    """De las dos lecturas de una hoja, la que más dice del graduado.

    La capa del escáner en su orden, o la página rehecha por su geometría
    (``domain.formulario``). En un acta impresa de corrido las dos dicen lo
    mismo y se queda la capa; en un formulario relleno a máquina gana la
    rehecha, que pone cada dato junto a su rótulo.
    """
    if not formulario.strip():
        return capa
    if cuanto_dice(graduado(formulario)) > cuanto_dice(graduado(capa)):
        return formulario
    return capa


def leer_acta_de_grado(paginas: Sequence[str]) -> ActaDeConsejo:
    """El acta de un graduado -- número, fecha, nombre, título y cédula --, o la
    ceremonia con su fecha si en esas hojas no hay ningún acta."""
    hoja = next(
        (
            (indice, texto)
            for indice, texto in enumerate(paginas, 1)
            if clase_de_hoja(texto) == GRADUADO
        ),
        None,
    )
    if hoja is None:
        return ActaDeConsejo(rotulo=ROTULO_DE_CEREMONIA, fecha=_fecha_de_la_ceremonia(paginas))
    pagina, texto = hoja
    return completar_acta(ActaDeConsejo(rotulo=ROTULO, pagina=pagina), texto)


def _fecha_de_la_ceremonia(paginas: Sequence[str]) -> date | None:
    for texto in paginas:
        fecha = fecha_de_grado(texto) or fecha_de_la_pagina(texto)
        if fecha is not None:
            return fecha
    return None


#: Una constancia de la secretaría que copia un acta antigua: «LA SUSCRITA
#: SECRETARIA ACADEMICA ... HACE CONSTAR: Que en el Libro de Actas de Grado ...
#: aparece el Acta Nº 55 bajo el folio 110 que a la letra dice: ...».
_CONSTANCIA = re.compile(r"HACEN?\W{0,4}CONSTAR|CONSTAR\W{0,4}HACEN?|\bSUSCRITAS?\b")
#: El libro del que copia: «en el Libro de Actas de Grado».
_LIBRO_DE_ACTAS = re.compile(r"\bLIBRO\s+DE\s+A\w{3,5}")
#: «el Acta Nº 55», «el Acta N2 18» (el º leído como 2), «ACTA NS 55».
_ACTA_CITADA = re.compile(
    r"\bACTA\W{0,2}(?:N\W{0,2}[º°OS29]?\W{0,2})?(?P<numero>\d{1,4})\b(?=\W{0,4}(?:BAJO|QUE|DEL?)\b)"
)
_EXPEDIDA = re.compile(r"EXPEDID[AO]")
#: Cómo nombra la constancia al graduado: «a la Señorita ESPERANZA VIANA SILVA».
_TRATAMIENTO = re.compile(r"\b(?:SENORITA|SENOR|SRITA|SRTA|ALUMN[AO])\b\W{0,2}")
#: Y cuándo nombra a varios: «a las ocho (8) señoritas de la promoción», «A: ANA ...».
_COLECTIVA = re.compile(r"\b(?:LAS|LOS)\s+(?:\w+\s+\(\d+\)\s+)?(?:SENORITAS|SENORES|ALUMNAS|ALUMNOS)\b|\bA\s*:\s+[A-Z]")
#: El cargo que sigue al nombre de quien firma o preside, que no es el graduado:
#: «la Srita. VILMA MERCADO V., Decana de la Facultad».
#: También el que va detrás con un «y»: «Srita. Didia Quintero B, y la
#: Secretaria Académica…» es la decana (UPD3859800 pág. 16).
_CARGO = re.compile(
    r"\W{0,4}(?:[A-Z]\W{1,3})?(?:Y\s+(?:LA|EL)\s+)?(?:DECAN|DIRECT|SECRETARI|PROFESOR|PRESID|RECTOR)"
)
_ENLACES_DEL_NOMBRE = {"DE", "DEL", "LA", "LAS", "LOS", "Y"}
#: Lo que nunca es parte de un nombre aunque vaya en mayúsculas detrás: también
#: «… y otras», «… (hoy Sra. de Vela)», «… quienes cumplieron» (UPD3859800).
_NO_ES_NOMBRE = {"ESTE", "QUIEN", "CON", "PARA", "POR", "EL", "SE", "QUE", "OTRAS", "OTROS", "HOY", "QUIENES"}
#: «Licenciada en Enfermería a: MARTHA PEÑALOZA DIAZ (hoy Sra. de Vela) y otras»:
#: la graduada a quien se expide la constancia, nombrada tras los dos puntos.
#: También sin ellos: «Licenciadas en Enfermería a ENYS GUTIERREZ DE MOYA c.c.…».
_A_DOS_PUNTOS = re.compile(r"\bA\s*:\s*|\bENFERMER(?:IA|A|O)S?\s+A\s+(?=[A-Z])")
#: Lo que sigue al nombre de la graduada de la constancia, y nunca al de quien
#: firma: «… y otras», «… (hoy Sra. de Vela)», «… c.c.#32'617.274».
_ES_LA_GRADUADA = re.compile(r"^\W{0,4}(?:\(|Y\s+OTR|C\W{0,2}C\W)")


@dataclass(frozen=True, slots=True)
class Constancia:
    """Lo que dice una constancia que copia un acta de grado."""

    numero: str | None
    nombre: str | None
    #: Cuándo se expidió: la fecha del documento, que es la que va en el FUID.
    expedida: date | None
    #: Cuándo fue el acta que copia.
    del_acta: date | None
    #: Si nombra a varios graduados en vez de a uno.
    colectiva: bool


#: Un cargo dentro de una palabra: el OCR pega «V., Decana» al apellido.
_CARGO_EN_PALABRA = re.compile(r"DECAN|DIRECT|SECRETAR|PROFESOR|PRESIDE|RECTOR")


def _nombre_tras(texto: str) -> str | None:
    """El nombre que sigue a «Señorita», o ``None`` si es el de quien firma.

    «VILMA MERCADO V.DECANA» lleva el cargo pegado: es la decana, no la
    graduada. «DIDIA QUINTERO BUELVAS y la Secretaria» lo lleva aparte: el
    nombre acaba antes del «y».
    """
    palabras: list[str] = []
    for token in texto[:90].split():
        limpio = re.sub(r"[^A-Z]", "", token)
        # «… DE MOYA c.c.#32'617.274»: la cédula pegada acaba el nombre.
        if limpio in _NO_ES_NOMBRE or token.startswith("(") or re.search(r"\d", token) or limpio == "CC":
            break
        # «a las ocho (8) señoritas»: un nombre no empieza por un artículo.
        if not palabras and limpio in _ENLACES_DEL_NOMBRE - {"DE", "DEL"}:
            return None
        if _CARGO_EN_PALABRA.search(limpio):
            # «DIDIA QUINTERO BUELVAS y la Secretaria»: el «y» dice que ella
            # también firma (es la decana), y no se gradúa (UPD3859800 pág. 22).
            if not palabras or palabras[-1] not in _ENLACES_DEL_NOMBRE or "Y" in palabras[-2:]:
                return None
            break
        if len(limpio) >= 2 or limpio in _ENLACES_DEL_NOMBRE:
            palabras.append(limpio)
        if token == "-" or re.search(r"[.,;:]$", token):
            break
    while palabras and palabras[-1] in _ENLACES_DEL_NOMBRE:
        palabras.pop()
    return " ".join(palabras) if 2 <= len(palabras) <= 6 else None


def constancia(texto: str) -> Constancia | None:
    """Si la hoja es una constancia que copia un acta de grado: qué dice, o ``None``.

    Los libros de pregrado de 1981 a 1983 no traen actas sino constancias
    expedidas esos años de actas de 1961 a 1981. Su fecha es la de expedición
    -- la del documento, y la que cuadra con el libro --; la del acta copiada
    va en las observaciones.
    """
    plano = _plano(texto)
    inicio = _CONSTANCIA.search(plano)
    if inicio is None or not _LIBRO_DE_ACTAS.search(plano):
        return None
    cuerpo = plano[inicio.end() :]
    expedida = _EXPEDIDA.search(cuerpo)
    copia = cuerpo[: expedida.start()] if expedida else cuerpo
    numero = _ACTA_CITADA.search(copia)
    nombre = None
    senalada = None
    marcas = sorted([*_TRATAMIENTO.finditer(copia), *_A_DOS_PUNTOS.finditer(copia)], key=lambda m: m.start())
    for marca in marcas:
        candidato = _nombre_tras(copia[marca.end() :])
        if not candidato:
            continue
        # Lo que va justo detrás del nombre: «VILMA MERCADO V., Decana» es quien
        # preside, no quien se gradúa.
        detras = _detras_del_nombre(copia, marca.end(), candidato)
        if _CARGO.match(detras):
            continue
        if senalada is None and _ES_LA_GRADUADA.match(detras):
            senalada = candidato
        if nombre is None and marca.re is _TRATAMIENTO:
            nombre = candidato
    colectiva = bool(_COLECTIVA.search(copia))
    return Constancia(
        numero=numero.group("numero") if numero else None,
        # La que la constancia señala -- «a: MARTHA PEÑALOZA DIAZ y otras» -- es
        # a quien se expide, aunque el acta nombre a varias; si no señala a
        # nadie y nombra a varias, no se adivina.
        nombre=senalada or (None if colectiva else nombre),
        expedida=fecha_de_grado(cuerpo[expedida.start() :]) if expedida else None,
        del_acta=fecha_de_grado(copia),
        colectiva=colectiva,
    )


def _detras_del_nombre(copia: str, desde: int, nombre: str) -> str:
    """Lo que sigue al nombre en la copia, para ver si es un cargo o «y otras»."""
    ultima = nombre.split()[-1]
    posicion = copia.find(ultima, desde)
    fin = posicion + len(ultima) if posicion != -1 else desde + len(nombre)
    return copia[fin : fin + 30]


def _con_la_constancia(acta: ActaDeConsejo, hecha: Constancia) -> ActaDeConsejo:
    """El acta con lo que dice su constancia, y la nota de qué es."""
    nota = "la hoja es una constancia de la secretaría"
    if hecha.expedida:
        nota += f" expedida el {hecha.expedida.strftime('%d-%m-%Y')}"
    if hecha.numero or hecha.del_acta:
        nota += " que copia el acta"
        if hecha.numero:
            nota += f" Nº {hecha.numero}"
        if hecha.del_acta:
            nota += f" del {hecha.del_acta.strftime('%d-%m-%Y')}"
    if hecha.colectiva:
        nota += "; nombra a varios graduados: revise la página"
    return replace(
        acta,
        constancia=True,
        numero=acta.numero or hecha.numero,
        # El de la constancia manda sobre el que adivina el lector general: en
        # «la Decana, Srta. DIDIA QUINTERO BUELVAS y la Secretaria…» aquél
        # tomaba a la decana (UPD3859800). Si nombra a varias sin señalar a
        # ninguna, no hay nombre: mejor N/A que el de otra.
        nombre=hecha.nombre or (None if hecha.colectiva else acta.nombre),
        # La de expedición manda: es la fecha del documento que se inventaría.
        fecha=hecha.expedida or acta.fecha or hecha.del_acta,
        dudas=(*acta.dudas, nota) if nota not in acta.dudas else acta.dudas,
    )


def completar_acta(acta: ActaDeConsejo, texto: str) -> ActaDeConsejo:
    """El acta con lo que le falte leído de ``texto``; lo ya leído no se toca.

    Sirve para la primera lectura y para releer la hoja con otro motor: la
    capa del escáner, después Tesseract, después la IA si se pidió. Cada uno
    llena sólo los huecos que dejó el anterior.
    """
    hecha = constancia(texto)
    if hecha is not None:
        acta = _con_la_constancia(acta, hecha)
    leido = graduado(texto)
    nuevo = replace(
        acta,
        numero=acta.numero or leido.numero,
        fecha=acta.fecha or fecha_de_grado(texto),
        nombre=acta.nombre or leido.nombre,
        titulo=acta.titulo or leido.titulo,
        cedula=acta.cedula or leido.cedula,
    )
    # Las dudas son de lo que quedó: una relectura limpia las borra. La nota
    # de la constancia no es una duda y se queda.
    propias = tuple(d for d in acta.dudas if d.startswith("la hoja es una constancia"))
    return replace(nuevo, dudas=(*dudas_de(nuevo.nombre, nuevo.titulo), *propias))


#: Cuántas hojas foliadas a cada lado se miran para saber por dónde va la
#: foliación.
VENTANA_DE_LA_FOLIACION = 8

LEIDO = "leído"
CORREGIDO = "corregido"
DEDUCIDO = "deducido"


def folios_de_la_foliacion(
    leidos: Mapping[int, int], orden: Mapping[int, int]
) -> dict[int, tuple[int, str, int | None]]:
    """El folio de cada hoja foliada, a partir de lo que se leyó de su esquina.

    ``leidos`` es el folio que la IA leyó en cada página; ``orden``, el puesto
    de cada página entre las hojas foliadas del libro (la primera foliada es 1).
    La foliación es seguida, así que en un tramo del libro el folio y el puesto
    van a la par: folio = puesto + un desfase, que sólo cambia donde una hoja
    foliada no se vio. Ese desfase, el que comparten las lecturas vecinas:

    * confirma la lectura que lo cumple;
    * corrige la que no -- un «140» leído «146» --, si dos o más vecinas
      coinciden en otro;
    * y da el folio de la hoja que no se leyó cuando las lecturas de antes y de
      después están de acuerdo.

    Devuelve, por página, el folio, cómo se supo (``LEIDO``, ``CORREGIDO`` o
    ``DEDUCIDO``) y lo que se había leído, si se leyó otra cosa.
    """
    from collections import Counter

    por_puesto = sorted((puesto, pagina) for pagina, puesto in orden.items())
    desfase = {
        orden[pagina]: folio - orden[pagina] for pagina, folio in leidos.items() if pagina in orden
    }
    resultado: dict[int, tuple[int, str, int | None]] = {}
    for puesto, pagina in por_puesto:
        cerca = [
            valor
            for otro, valor in desfase.items()
            if otro != puesto and abs(otro - puesto) <= VENTANA_DE_LA_FOLIACION
        ]
        comun, veces = Counter(cerca).most_common(1)[0] if cerca else (None, 0)
        leido = leidos.get(pagina)
        if leido is not None:
            propio = leido - puesto
            if comun is None or propio == comun or veces < 2:
                resultado[pagina] = (leido, LEIDO, None)
            else:
                resultado[pagina] = (puesto + comun, CORREGIDO, leido)
            continue
        antes = [desfase[o] for o in sorted(desfase) if o < puesto][-1:]
        despues = [desfase[o] for o in sorted(desfase) if o > puesto][:1]
        if antes and despues and antes == despues:
            resultado[pagina] = (puesto + antes[0], DEDUCIDO, None)
    return resultado


def con_la_franja(acta: ActaDeConsejo, texto: str, confianza: Mapping[str, float]) -> ActaDeConsejo:
    """El acta con la franja del graduado releída: cada dato, de la lectura que más vale.

    ``texto`` es la parte de la hoja del encabezado a la cédula leída otra vez
    con Tesseract, y ``confianza`` lo seguro que estuvo de cada palabra.
    """
    from .graduado import Graduado, fusionar

    capa = Graduado(nombre=acta.nombre, titulo=acta.titulo, cedula=acta.cedula, numero=acta.numero)
    junto = fusionar(capa, graduado(texto), confianza)
    return replace(
        acta,
        numero=junto.numero,
        nombre=junto.nombre,
        titulo=junto.titulo,
        cedula=junto.cedula,
        fecha=acta.fecha or fecha_de_grado(texto),
        dudas=junto.dudas,
    )


def le_falta_algo(acta: ActaDeConsejo) -> bool:
    """Si a un acta de graduado le falta algo que el FUID pide, o trae algo dudoso."""
    if acta.rotulo != ROTULO:
        return False
    if acta.constancia:
        # Una constancia no trae cédula ni título: pedirlos sería pagar por
        # releer una y otra vez una hoja que no los tiene.
        return not all((acta.numero, acta.fecha, acta.nombre))
    dudas = [d for d in acta.dudas if not d.startswith("la hoja es una constancia")]
    return bool(
        dudas or not all((acta.numero, acta.fecha, acta.nombre, acta.titulo, acta.cedula))
    )


# -- la IA que lee el acta como una persona ----------------------------------------

#: Lo que se le pide al lector de texto de la IA sobre la hoja que ya leyó el OCR
#: de pago. En los formularios de 1997-2001 la máquina escribió los datos
#: corridos de sus renglones -- «al estudiante FAIMA / LUZ FELFLE CASTILLA», el
#: título en dos renglones, el número del acta junto al día -- y ninguna regla
#: fija los pone en su sitio; una persona sí (UPD3859808, Odontología,
#: 2026-10-31). Lo que devuelve se valida contra el texto: ninguna palabra ni
#: cifra que la hoja no diga.
INSTRUCCIONES_DEL_ACTA_DE_GRADO = (
    "Eres archivista de la Universidad de Cartagena. Recibes el texto, leído por OCR, de un acta de "
    "grado (o de una constancia de la secretaría que copia un acta de grado). Es un formulario "
    "rellenado a máquina: los datos pueden haber quedado corridos de su renglón y el OCR puede "
    "devolverlos en otro orden.\n\n"
    "Devuelve exactamente estas cinco líneas, sin nada más:\n"
    "NUMERO: el número del acta de grado (el que sigue a «ACTA DE GRADO No.»; no el número impreso al pie "
    "del formulario ni el de la resolución)\n"
    "FECHA: la fecha de la ceremonia en DD-MM-AAAA (la de «a los … días del mes de …»; no la de la resolución "
    "ni la de expedición)\n"
    "TITULO: el título otorgado completo, aunque ocupe dos renglones (por ejemplo «ESPECIALISTA EN ENFERMERIA "
    "MATERNO INFANTIL CON ENFASIS EN NEONATOLOGIA»)\n"
    "NOMBRE: el nombre completo del graduado tal como aparece, nombres y apellidos en el orden del acta, "
    "aunque esté partido en dos renglones (no el rector, el decano, la secretaria ni quien firma)\n"
    "CEDULA: el número de la cédula del graduado, sólo cifras\n\n"
    "- En una constancia que nombra a varios graduados, el nombre es el de quien la constancia señala; si no "
    "señala a ninguno, NINGUNO.\n"
    "- Cada palabra y cada cifra tiene que estar escrita en el texto: no corrijas ni inventes.\n"
    "- Si un dato no está, escribe NINGUNO."
)

#: Las palabras de un título profesional: un «título» sin ninguna -- «FAIMA»,
#: «FECHA» -- es un pedazo de otro renglón.
_DEL_GRADO = re.compile(
    r"ESPECIALIST|ENFERMER|LICENCIAD|MAGISTER|MAESTR|DOCTOR|ODONTOLOG|MEDIC|BACTERIOLOG|QUIMIC|"
    r"FARMACEUT|INGENIER|ABOGAD|ADMINISTRAD|ECONOMIST|CONTADOR|PSICOLOG|TRABAJADOR|TECNOLOG|TECNIC|"
    r"NUTRICION|FONOAUDIOLOG|BIOLOG|MATEMATIC|FISIC|HISTORIADOR|FILOSOF|COMUNICADOR|ARQUITECT|"
    r"PROFESIONAL|NORMALISTA|SOCIOLOG|ANTROPOLOG|LINGUIST|ESTADISTIC|ZOOTECNIST|AGRONOM|VETERINARI"
)


def es_un_titulo(texto: str | None) -> bool:
    """Si dice un título profesional: lleva al menos una palabra de grado."""
    return bool(texto) and _DEL_GRADO.search(_plano(texto)) is not None


def datos_de_la_ia(respuesta: str, texto: str) -> dict[str, object]:
    """Lo que la IA leyó del acta, campo por campo, si la hoja lo dice; lo demás no se devuelve.

    Una palabra o una cifra que no está en el texto descarta el campo entero:
    un dato inventado es peor que uno por revisar.
    """
    palabras_del_texto = set(re.findall(r"[A-Z]+", _plano(texto)))
    cifras_del_texto = re.sub(r"\D", "", texto)
    datos: dict[str, object] = {}
    for linea in (respuesta or "").splitlines():
        campo, _, valor = linea.partition(":")
        campo, valor = _plano(campo).strip(" -*"), valor.strip(" *`")
        if not valor or "NINGUNO" in _plano(valor):
            continue
        if campo in ("NOMBRE", "TITULO"):
            # Con sus tildes y su Ñ, como en el acta; se comparan sin ellas.
            palabras = re.findall(r"[A-ZÁÉÍÓÚÜÑ]+", valor.upper())
            dice_la_hoja = palabras and all(_plano(palabra) in palabras_del_texto for palabra in palabras)
            if campo == "NOMBRE" and dice_la_hoja and len(palabras) >= 2:
                datos["nombre"] = " ".join(palabras)
            elif campo == "TITULO" and dice_la_hoja and es_un_titulo(valor):
                datos["titulo"] = " ".join(palabras)
        elif campo == "CEDULA":
            cifras = re.sub(r"\D", "", valor)
            if 6 <= len(cifras) <= 11 and cifras in cifras_del_texto:
                datos["cedula"] = cifras
        elif campo == "NUMERO":
            # Sólo el que sigue a «ACTA DE GRADO No.»: con el número en blanco, la
            # IA daba el de la resolución (0816) o el folio (73/V) (UPD3859808).
            numero = re.search(r"\d{1,4}", valor)
            if numero and re.search(
                rf"ACTA\W+DE\W+GRADO\W{{0,3}}N\S{{0,3}}\s*0*{int(numero.group(0))}(?!\d)", _plano(texto)
            ):
                datos["numero"] = numero.group(0)
        elif campo == "FECHA":
            partes = re.fullmatch(r"(\d{1,2})\D(\d{1,2})\D(\d{4})", valor.strip())
            if partes:
                dia, mes, anio = (int(parte) for parte in partes.groups())
                fecha = _fecha(dia, mes, str(anio))
                if fecha is not None and _la_hoja_dice_la_fecha(fecha, texto):
                    datos["fecha"] = fecha
    return datos


def _la_hoja_dice_la_fecha(fecha: date, texto: str) -> bool:
    """Si el texto trae esa fecha: la misma que lee la regla, o, si la regla no lee ninguna, su mes y su año.

    Si la regla lee otra, no: «a los Catorce ( 03 ) días» es el día 14 y el 03
    es el número del acta corrido junto al día (UPD3859808 pág. 138).
    """
    de_la_regla = fecha_de_grado(texto)
    if de_la_regla is not None:
        return de_la_regla == fecha
    plano = _plano(texto)
    mes = MESES_EN_LETRAS[fecha.month]
    cifras = re.sub(r"(?<=\d)[.,](?=\d{3})", "", plano)
    return mes in plano and str(fecha.year) in cifras


MESES_EN_LETRAS = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL", 5: "MAYO", 6: "JUNIO", 7: "JULIO",
    8: "AGOSTO", 9: "SEPTIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE",
}
