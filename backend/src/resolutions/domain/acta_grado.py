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

Y una tercera, manuscrita (UPD3859802, 1983-2012): el **libro de actas
colectivas**, en que cada acta gradúa a una promoción -- «Acta de Grado Nº
05408120 a 05408124» con la lista de sus graduados -- y empieza a mitad de la
hoja en que acaba la anterior. Su reparto y su lectura van al final
(``reparto_del_libro_colectivo``): un PDF por acta, una fila por graduado
(2026-11-12).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from .acta_consejo import ActaDeConsejo, ActasDelPdf, TramoDeActa
from .fechas import MESES, fecha_de_la_pagina
from .graduado import (
    LUGARES_DE_EXPEDICION,
    cuanto_dice,
    dudas_de,
    graduado,
    titulo_limpio,
)
from .orden_por_el_folio import folios_corregidos, orden_por_el_folio

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
        # «mil novecientos veintiséis (1926)»: de diez a veintinueve, una palabra.
        if base == 1900 and palabra in _DEL_DIEZ_AL_TREINTA:
            usados.add(posicion)
            return _DEL_DIEZ_AL_TREINTA[palabra]
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


#: «En Cartagena, a trece de Julio de …»: la fecha de las actas manuscritas de
#: examen desde 1934, sin «a los … días del mes».
_EN_CARTAGENA_A = re.compile(r"EN\s+(?:LA\s+C\w{4}D\s+DE\s+)?CARTAGENA\W{0,3}\s+A\s+(?!LOS\b)")


#: Cómo leyó ``fecha_de_grado_y_como`` la fecha: la forma entera, la frase en
#: letras, o las piezas sueltas del OCR revuelto (el respaldo).
POR_LA_FORMA = "forma"
POR_LAS_LETRAS = "letras"
POR_PIEZAS = "piezas"


def fecha_de_grado(texto: str) -> date | None:
    """La fecha de la ceremonia escrita en el cuerpo del acta, o ``None``."""
    return fecha_de_grado_y_como(texto)[0]


def fecha_de_grado_y_como(texto: str) -> tuple[date | None, str]:
    """La fecha de la ceremonia y cómo se leyó (``POR_LA_FORMA``, ``POR_LAS_LETRAS``, ``POR_PIEZAS``); ``(None, "")`` si no.

    El revisor de fechas (2026-11-10) sólo corrige con la forma entera o la
    frase en letras: el respaldo por piezas junta un día suelto, un año suelto
    y la primera palabra que se parezca a un mes, y en «15 ( ) DIAS … 1987 …
    JULIO» corregía la ceremonia del 23/01/1987 al 15/07/1987. La fecha que
    devuelve es la misma de siempre.
    """
    plano = _plano(texto)
    for match in _FECHA.finditer(plano):
        fecha = _fecha(int(match.group("dia")), _mes(match.group("mes")), match.group("anio"))
        if fecha is not None:
            return fecha, POR_LA_FORMA
    # En letras: el formulario de los libros viejos, con las cifras rotas.
    # Primero detrás de «a los»; y si el día quedó delante -- la capa pone
    # «Diez y siete ( J días del mes de» antes de «En la ciudad» --, la frase
    # entera desde el encabezado del acta.
    inicio = plano.find("A LOS", max(0, plano.find("EN LA CIUDAD")))
    # Y el acta manuscrita de 1934-1946 sin «a los … días»: «En Cartagena, a
    # trece de Julio de mil novecientos treinta y cinco» (UPD3859999).
    sin_dias = _EN_CARTAGENA_A.search(plano)
    for desde in (inicio, plano.find("ACTA DE GRADO"), sin_dias.start() if sin_dias else -1):
        if desde < 0:
            continue
        frase = plano[desde : desde + LARGO_DE_LA_FRASE + 120]
        fin = _FIN_DE_LA_FRASE.search(frase)
        fecha = fecha_en_letras(frase[: fin.start()] if fin else frase)
        if fecha is not None:
            return fecha, POR_LAS_LETRAS
    # El OCR de los libros viejos mezcla la frase: se busca cada pieza por su lado.
    inicio = plano.find("EN LA CIUDAD")
    trozo = plano[inicio : inicio + 400] if inicio >= 0 else plano[:600]
    dia = _DIA_SUELTO.search(trozo)
    anio = _ANIO_SUELTO.search(trozo)
    mes = next((m for m in (_mes(p) for p in _PALABRA.findall(trozo)) if m), None)
    if dia and anio:
        fecha = _fecha(int(dia.group(1)), mes, anio.group(1) or anio.group(2))
        return (fecha, POR_PIEZAS) if fecha is not None else (None, "")
    return None, ""


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
    # La hoja que cierra el libro manuscrito: «Son la última acta… queda cerrado el presente libro».
    r"|ULTIMA\s+ACTA|PRESENTE\s+LIBRO"
)
#: Lo que trae el cuerpo de un acta de graduado: con tres de cuatro, la hoja es
#: un acta aunque su encabezado no se lea.
_CUERPO_DEL_ACTA = ("EN LA CIUDAD", "GRADUACION", "CIUDADANIA", "JURAMENTO")
CUERPO_MINIMO = 3
GRADUADO = "graduado"
CEREMONIA = "ceremonia"
SIGUE = "sigue"
ROTULO_DE_CEREMONIA = "CEREMONIA DE GRADO"


#: El acta manuscrita de 1924-1946 (20. ACTAS DE GRADO 3362): «En la ciudad de
#: Cartagena, a los veinticuatro días del mes de Febrero de mil novecientos
#: veintiséis (1926), se constituyó … el Consejo Examinador … con el fin de
#: practicar el quinto examen preparatorio de grado del alumno Jesús Mª Barrios
#: J.», o «… el examen final de grado del alumno …». Una por página.
_EXAMEN_ANTIGUO = re.compile(
    # «En la ciudad de Cartagena», «En la cuidad…» (el OCR) o, desde 1935, «En Cartagena, a…»;
    # desde 1943, «En el Paraninfo de la Universidad de Cartagena, a…» y el «Jurado Examinador».
    r"EN\s+(?:LA\s+C\w{4}D\s+DE\s+|EL\s+\w{6,10}\s+DE\s+LA\s+UNIVERSIDAD\s+DE\s+)?CARTAGENA"
    r".{0,900}?(?:EXAMEN.{0,40}?(?:PREPARATORI|GRADO)"
    r"|CONSEJO\s+EXAMINADOR|JURADO\s+(?:DE\s+)?EXAMINADOR)"
)


#: La carta con que un graduado autoriza a otro: «… autorizo a TATIANA … para
#: recibir en mi nombre los certificados … y mi Acta de Grado …». Nombra el
#: acta de grado y los «días del mes» de su fecha, pero no es un acta (1990-1994
#: TOMO I pág. 139, 2026-11-27). El acta dice «quien autorizó el acto».
_CARTA_QUE_AUTORIZA = re.compile(r"\bAUTORIZO\s+(?:A|AL|A\s+LA)\b.{0,160}?\bPARA\s+(?:QUE\s+)?(?:ME\s+)?(?:RECIB|RECLAM|RETIR)|\bEN\s+MI\s+NOMBRE\b")


def clase_de_hoja(texto: str) -> str:
    """Qué es una hoja de un libro de grados: el acta de un graduado, una hoja de
    la ceremonia, o la continuación de lo anterior (su reverso, una nota)."""
    plano = _plano(texto)
    if _CARTA_QUE_AUTORIZA.search(plano) and sum(1 for marca in _CUERPO_DEL_ACTA if marca in plano) < CUERPO_MINIMO:
        # La carta: la reparte ``tipo_de_hoja`` con el acta de su graduado.
        return SIGUE
    if apertura(texto):
        return GRADUADO
    if _EXAMEN_ANTIGUO.search(_sin_cortes(plano)):
        return GRADUADO
    if sum(1 for marca in _CUERPO_DEL_ACTA if marca in plano) >= CUERPO_MINIMO:
        return GRADUADO
    if es_acta_del_consejo_directivo(texto):
        # La forma de 1980, antes que la ceremonia: cita «según Resolución No.
        # 527» y se tomaba por la resolución de los grados (2026-11-27).
        return GRADUADO
    if _DE_LA_CEREMONIA.search(plano):
        return CEREMONIA
    return SIGUE


# -- lo que el libro de grados trae cosido entre las actas (Odontología 3194-3198) --
#
# Medido el 2026-11-27 hoja por hoja sobre los ocho libros «ACTAS DECADA.» de
# 1980 a 1999 (1.302 hojas): además de las actas del formulario, el libro trae
# las copias autenticadas del acta del Consejo Directivo de 1980 que gradúa a un
# alumno, las portadas «ACTAS UNIVERSIDAD DE CARTAGENA» de cada ceremonia, las
# listas de alumnos del semestre o de la promoción, la constancia de
# calificaciones de un alumno y las cartas y poderes con que un graduado
# autoriza a otro a recibir su diploma. Hasta hoy todo lo que no era un acta
# iba pegado al graduado de delante: la lista de 47 alumnos, en el PDF de uno.

#: El acta del Consejo Directivo que gradúa a un alumno, la forma de 1980 que el
#: libro de 1980-1984 trae en copias autenticadas: «ACTA No. 782 … se reunieron
#: en el Decanato … los Honorables Miembros del Consejo Directivo … se nombró una
#: comisión de examinadores para que verificaran las calificaciones de la
#: alumna MERCY NAIZZIR DIAZ, la cual fue de (3,45) … se le hará entrega del
#: Diploma de Grado que la acredita como ODONTOLOGO CIRUJANO». Una por alumno.
_MARCAS_DEL_ACTA_DEL_CONSEJO = (
    re.compile(r"CONSEJO\s+DIRECTIVO"),
    re.compile(r"EXAMINADORES"),
    re.compile(r"(?:CALIFICACIONES|NOTAS)\s+D\w{0,3}\b"),
    re.compile(r"DIPLOMA"),
)
#: Cuántas de las cuatro marcas hacen falta: el OCR de la copia se come alguna.
MARCAS_DEL_ACTA_DEL_CONSEJO = 3
#: «ACTA No. 782.-», «ACTA Hb. 807», «ACIANO. 774» (el OCR del membrete).
_NUMERO_DEL_ACTA_DEL_CONSEJO = re.compile(r"\bAC\w{0,3}\W{0,3}[NH]\w?\W{0,3}\s*(\d{2,4})\b")
#: El alumno: «las calificaciones dela alumna MERCY NAIZZIR - DIAZ, la cual…»,
#: «las notas de: MARIA TERESA CHAVEZ ANGULO, la cual…».
_ALUMNO_DEL_CONSEJO = re.compile(
    r"(?:CALIFICACIONES|NOTAS)\s+DE\W{0,3}(?:L\W{0,2}(?:A\s+)?ALUMN[AO]S?\W{0,3}|LA\s+ALUMNA\W{0,3}|EL\s+ALUMNO\W{0,3})?"
)
#: El título: «que la acredita como ODONTOLOGO CIRUJANO».
_TITULO_DEL_CONSEJO = re.compile(r"ACREDITA\s+COMO\s+([A-Z][A-Z ]{4,40}?)(?=\s*[,.;]|\s+(?:PARA|SE|Y|EN)\b)")


def es_acta_del_consejo_directivo(texto: str) -> bool:
    """Si la hoja es el acta del Consejo Directivo que gradúa a un alumno (la forma de 1980)."""
    plano = _sin_cortes(_plano(texto))
    return sum(1 for marca in _MARCAS_DEL_ACTA_DEL_CONSEJO if marca.search(plano)) >= MARCAS_DEL_ACTA_DEL_CONSEJO


def numero_del_acta_del_consejo(texto: str) -> str | None:
    """El número del acta del Consejo Directivo, «782», si la hoja es una y lo trae arriba."""
    if not es_acta_del_consejo_directivo(texto):
        return None
    numero = _NUMERO_DEL_ACTA_DEL_CONSEJO.search(_plano(texto)[:600])
    return numero.group(1) if numero and numero.group(1).strip("0") else None


def acta_del_consejo_directivo(texto: str) -> tuple[str | None, str | None, str | None]:
    """El número, el alumno y el título del acta del Consejo Directivo; ``(None, None, None)`` si no es una."""
    if not es_acta_del_consejo_directivo(texto):
        return None, None, None
    # El salto de renglón con guion parte el nombre: «MERCY NAIZZIR - DIAZ»; y
    # el nombre acaba en «la cual fue de…» aunque el OCR se coma la coma:
    # «TERESA ANGULO)!^ CUAL FUE DE».
    plano = re.sub(r"(\w)\s+-\s+(?=\w)", r"\1 ", _sin_cortes(_plano(texto)))
    plano = re.sub(r"[)\]!^]*\s+(?:LA\s+)?CUAL\b", ", LA CUAL", plano)
    nombre = None
    for marca in _ALUMNO_DEL_CONSEJO.finditer(plano):
        nombre = _nombre_tras(plano[marca.end() :])
        if nombre:
            break
    titulo = _TITULO_DEL_CONSEJO.search(plano)
    return numero_del_acta_del_consejo(texto), nombre, titulo.group(1).strip() if titulo else None


#: Las clases que ``tipo_de_hoja`` añade a las de ``clase_de_hoja``.
LISTA = "lista"
PORTADA = "portada"
DOCUMENTO = "documento"
CALIFICACIONES_DEL_ALUMNO = "calificaciones"

#: La portada de cada ceremonia: «ACTAS UNIVERSIDAD DE CARTAGENA», a veces con
#: «NO 198… DE MARZO» a mano. Pocas letras y «ACTAS».
_PORTADA_DEL_LIBRO = re.compile(r"\bACTAS\b")
LETRAS_DE_LA_PORTADA_DEL_LIBRO = 120


def es_portada(texto: str) -> bool:
    """Si la hoja es la portada «ACTAS» de una ceremonia: pocas letras, «ACTAS» y ningún cuerpo de acta."""
    plano = _plano(texto)
    letras = sum(1 for letra in plano if letra.isalpha())
    return letras <= LETRAS_DE_LA_PORTADA_DEL_LIBRO and bool(_PORTADA_DEL_LIBRO.search(plano)) and not _CUERPO.search(plano)


#: Lo que se lee mal de las palabras de la cabeza de una lista: «SEiESTBE»,
#: «^^^MESTfE», «PERIDO», «USIA DEL» (LISTA DEL), «ODONTOUDGIA».
PARECIDO_DE_LA_CABEZA = 0.6
#: Cuánto de la hoja se mira para buscar la cabeza de la lista.
LETRAS_DE_LA_CABEZA_DE_LA_LISTA = 700
_ORDINALES_DEL_SEMESTRE = {
    "PRIMER": "I", "PRIMERO": "I", "SEGUNDO": "II", "TERCER": "III", "TERCERO": "III", "CUARTO": "IV",
    "QUINTO": "V", "SEXTO": "VI", "SEPTIMO": "VII", "OCTAVO": "VIII", "NOVENO": "IX", "DECIMO": "X",
}
_ROMANOS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")
_PERIODOS = {"PRIMER": 1, "PRIMERO": 1, "1ER": 1, "LER": 1, "1O": 1, "1": 1, "SEGUNDO": 2, "2O": 2, "2": 2}
#: «PROMOCION 17 DE DICIEMBRE DE 1999», «PROMOCIÓN 20 DE DICIEMBRE DE 1996». No
#: la que se cita en un texto: «… egresada de la promoción del 16 de diciembre»
#: (la constancia de recibo del acta, 1990-1994 TOMO II pág. 74).
_PROMOCION = re.compile(
    r"(?<!LA )(?<!DE )\bPROMOCI\w{0,3}N\W+(?:DEL?\W+)?(?:(?P<dia>\d{1,2})\W+DE\W+)?(?P<mes>[A-Z]{4,10})\W+(?:DE(?:L)?\W+)?"
    r"(?P<anio>(?:19|20)\d\d|1\W\d{3})\b"
)
#: «EGRESADOS EL 12 DE DICIEMBRE DE 1997».
_EGRESADOS_EL = re.compile(
    r"\bEGRESADOS\s+EL\s+(?P<dia>\d{1,2})\W+DE\W+(?P<mes>[A-Z]{4,10})\W+(?:DE\W+)?(?P<anio>(?:19|20)\d\d)\b"
)
#: Las listas que dicen lo que son con su título: «RELACION DE EGRESADOS QUE
#: ENTREGARON LAS BANDAS», «LISTA DE ALUMNOS QUE TIENEN DEUDAS PENDIENTES».
_LISTA_CON_SU_TITULO = re.compile(
    r"\b(?P<titulo>(?:RELACION|LISTA)\s+DE\s+(?:EGRESADOS|ALUMNOS|ESTUDIANTES|GRADUADOS)\s+QUE\s+[A-Z ]{3,70}?)"
    r"(?=\s*(?:[.,;:(]|\bFECHA\b|\bNOMBRE\b|\bVALOR\b|\bCODIGO\b|\d|$))"
)
#: «CONTINUACION DE LA LISTA DE ALUMNOS…»: la segunda hoja de una lista.
_CONTINUA_LA_LISTA = re.compile(r"\bCON\w{4,9}\s+DE\s+LA\W{0,3}LIST\w*")
#: Un renglón de una lista de alumnos: el código del estudiante -- «8910001»,
#: «528710027», «52199810009», «79-0110» -- junto a un nombre en mayúsculas.
_CODIGO_DE_ALUMNO = re.compile(r"(?<![\d.,'])(?:\d{6,11}|\d{2}-\d{4})(?![\d.,'])")
_RENGLON_NUMERADO_DE_LA_LISTA = re.compile(r"(?m)^\W{0,3}\d{1,3}\s*[.\-)]\s*-?\s*[A-ZÁÉÍÓÚÑ]{3,}")
#: Desde cuántos renglones una hoja es una lista y no un acta con su cédula.
RENGLONES_DE_UNA_LISTA = 8
#: El título de la lista que no dice cuál es: la de códigos sin cabeza legible.
LISTA_DE_ALUMNOS = "LISTA DE ALUMNOS"


def _parecida(palabra: str, otra: str) -> bool:
    return difflib.SequenceMatcher(None, palabra, otra).ratio() >= PARECIDO_DE_LA_CABEZA


def _anio_de_la_lista(trozo: str) -> str | None:
    """El año de la cabeza de una lista: «1.984», «1986», «I986» (la I por 1), «P./84».

    Un año ilegible -- «1.93^», «1387» -- no se adivina aquí: lo completa la
    aplicación con las actas de su ceremonia.
    """
    anio = re.search(r"(?<!\d)[1I]\W?(9\d\d)(?!\d)", trozo)
    if anio:
        return f"1{anio.group(1)}"
    anio = re.search(r"(?<!\d)(20[0-2]\d)(?!\d)", trozo)
    if anio:
        return anio.group(1)
    corto = re.search(r"/\W{0,2}([5-9]\d)\b", trozo)
    return f"19{corto.group(1)}" if corto else None


def _la_mas_parecida(palabra: str, opciones: Collection[str], minimo: float) -> str | None:
    """La opción que más se parece a la palabra, si se parece ``minimo`` o más; la exacta primero."""
    if palabra in opciones:
        return palabra
    mejor = max(opciones, key=lambda opcion: difflib.SequenceMatcher(None, palabra, opcion).ratio())
    return mejor if difflib.SequenceMatcher(None, palabra, mejor).ratio() >= minimo else None


#: Hasta cuántas palabras de «SEMESTRE» se busca «LISTA» o «ALUMNOS»: la capa
#: pone a veces «LISTA DEL» diez palabras detrás (1985-1986-1987 TOMO I pág. 2).
PALABRAS_DE_LA_CABEZA = 12
#: Cuánto se tiene que parecer el ordinal del semestre o del periodo: «DECIMa»
#: es DECIMO; con 0,6 DECIMO se parecía a SEPTIMO (2026-11-27).
PARECIDO_DEL_ORDINAL = 0.7


def _periodo_de(candidata: str) -> int | None:
    if candidata in _PERIODOS:
        return _PERIODOS[candidata]
    if len(candidata) < 5:
        return None
    parecida = _la_mas_parecida(candidata, [opcion for opcion in _PERIODOS if len(opcion) >= 6], PARECIDO_DEL_ORDINAL)
    return _PERIODOS[parecida] if parecida else None


def _cabeza_del_semestre(cabeza: str) -> str | None:
    """«LISTA DE ALUMNOS IX SEMESTRE DE ODONTOLOGIA - 1 PERIODO 1984», de la cabeza de la hoja; ``None`` si no lo es.

    La cabeza lleva «SEMESTRE» y «LISTA» o «ALUMNOS», bien o mal leídos y en
    cualquier orden (la capa pone a veces «LISTA DEL» detrás). Del semestre, el
    ordinal de delante; del periodo, el que va antes de «PERIODO» o tras «AL»;
    el año, detrás.
    """
    palabras = [(hallada.group(0), hallada.start()) for hallada in re.finditer(r"[A-Z0-9]+", cabeza)]
    donde = next(
        (i for i, (palabra, _) in enumerate(palabras) if 6 <= len(palabra) <= 10 and _parecida(palabra, "SEMESTRE")), None
    )
    if donde is None:
        return None
    # «LISTA» o «ALUMNOS» cerca, o la columna «COD.» de los códigos: «USIA DEL
    # DECIMa SEiESTBE … COD. No.» (1985-1986-1987 TOMO I pág. 243).
    cerca = palabras[max(0, donde - PALABRAS_DE_LA_CABEZA) : donde + PALABRAS_DE_LA_CABEZA + 1]
    if not any(len(palabra) >= 4 and (_parecida(palabra, "LISTA") or _parecida(palabra, "ALUMNOS")) for palabra, _ in cerca) and not any(
        palabra in ("COD", "CODIGO") for palabra, _ in palabras
    ):
        return None
    semestre = None
    for palabra, _ in reversed(palabras[max(0, donde - 3) : donde]):
        if palabra in _ROMANOS:
            semestre = palabra
            break
        if len(palabra) >= 5 and (ordinal := _la_mas_parecida(palabra, _ORDINALES_DEL_SEMESTRE, PARECIDO_DEL_ORDINAL)):
            semestre = _ORDINALES_DEL_SEMESTRE[ordinal]
            break
    detras = [palabra for palabra, _ in palabras[donde + 1 : donde + 16]]
    periodo = None
    for indice, palabra in enumerate(detras):
        es_periodo = palabra in ("P", "PERIDO") or (len(palabra) >= 5 and _parecida(palabra, "PERIODO"))
        tras_al = indice > 0 and detras[indice - 1] == "AL"
        candidatas = detras[max(0, indice - 2) : indice] if es_periodo else ([palabra] if tras_al else [])
        periodo = next((cual for candidata in reversed(candidatas) if (cual := _periodo_de(candidata))), None)
        if periodo or es_periodo:
            break
    anio = _anio_de_la_lista(cabeza[palabras[donde][1] :])
    titulo = " ".join([LISTA_DE_ALUMNOS, *([semestre] if semestre else []), "SEMESTRE DE ODONTOLOGIA"])
    cola = " ".join([*([f"{periodo} PERIODO"] if periodo else []), *([anio] if anio else [])])
    return f"{titulo} - {cola}" if cola else titulo


def titulo_de_la_lista(texto: str) -> str | None:
    """El título impreso de una lista de alumnos, normalizado; ``None`` si la hoja no dice ser una.

    «LISTA DEL DECIMO SEMESTRE DE ODONTOLOGIA, CORRESPONDIENTE AL PRIMER
    PERIODO DE 1986» es «LISTA DE ALUMNOS X SEMESTRE DE ODONTOLOGIA - 1 PERIODO
    1986»; «ALUMNOS X SEMESTRE DE ODONTOLOGIA 2o. periodo de 1996», lo mismo;
    «PROMOCION 17 DE DICIEMBRE DE 1999», «PROMOCION 17-12-1999»; «EGRESADOS EL
    12 DE DICIEMBRE DE 1997», «EGRESADOS 12-12-1997» (2026-11-27). Lo que el
    papel no deja leer -- el semestre, el periodo, el año -- no entra. La hoja
    que continúa una lista (``continua_la_lista``) también devuelve lo que su
    cabeza diga de ella.
    """
    plano = _plano(texto)
    cabeza = plano[:LETRAS_DE_LA_CABEZA_DE_LA_LISTA]
    if promocion := _PROMOCION.search(cabeza):
        mes = _mes(promocion.group("mes"))
        anio = re.sub(r"\D", "", promocion.group("anio"))
        if mes:
            fecha = f"{int(promocion.group('dia')):02d}-{mes:02d}-{anio}" if promocion.group("dia") else f"{mes:02d}-{anio}"
            delante = "LISTA DE EGRESADOS - " if re.search(r"LISTA\s+DE\s+EGRESADOS\W+$", cabeza[: promocion.start()]) else ""
            return f"{delante}PROMOCION {fecha}"
    if egresados := _EGRESADOS_EL.search(cabeza):
        mes = _mes(egresados.group("mes"))
        if mes:
            return f"EGRESADOS {int(egresados.group('dia')):02d}-{mes:02d}-{egresados.group('anio')}"
    if con_titulo := _LISTA_CON_SU_TITULO.search(cabeza):
        return " ".join(con_titulo.group("titulo").split())
    return _cabeza_del_semestre(cabeza)


def continua_la_lista(texto: str) -> bool:
    """Si la hoja dice seguir la lista de la anterior: «CONTINUACION DE LA LISTA DE ALUMNOS…»."""
    return bool(_CONTINUA_LA_LISTA.search(_plano(texto)[:LETRAS_DE_LA_CABEZA_DE_LA_LISTA]))


_DEL_TITULO_DEL_SEMESTRE = re.compile(
    r"^LISTA DE ALUMNOS(?: (?P<semestre>[IVX]+))? SEMESTRE DE ODONTOLOGIA"
    r"(?: - (?:(?P<periodo>\d) PERIODO)? ?(?P<anio>\d{4})?)?$"
)


def titulo_de_las_hojas(titulos: Sequence[str | None]) -> str | None:
    """El título de una lista de varias hojas: el de su primera hoja con título, completado con lo que digan las demás.

    «LISTA DEL … SEMESTRE … AL 1er. PERIODO DE 1.93^» y su continuación «… IX
    SEMESTRE … 1er. P./84» son «LISTA DE ALUMNOS IX SEMESTRE DE ODONTOLOGIA - 1
    PERIODO 1984» (1985-1986-1987 TOMO I, págs. 2-3).
    """
    leidos = [titulo for titulo in titulos if titulo]
    if not leidos:
        return None
    partes = [hallado for titulo in leidos if (hallado := _DEL_TITULO_DEL_SEMESTRE.match(titulo))]
    if not partes or not _DEL_TITULO_DEL_SEMESTRE.match(leidos[0]):
        return leidos[0]

    def primero(campo: str) -> str | None:
        return next((parte.group(campo) for parte in partes if parte.group(campo)), None)

    semestre, periodo, anio = primero("semestre"), primero("periodo"), primero("anio")
    titulo = " ".join([LISTA_DE_ALUMNOS, *([semestre] if semestre else []), "SEMESTRE DE ODONTOLOGIA"])
    cola = " ".join([*([f"{periodo} PERIODO"] if periodo else []), *([anio] if anio else [])])
    return f"{titulo} - {cola}" if cola else titulo


#: Un renglón que es sólo el puesto de la lista: «12.», «13o» (la capa pone los
#: números en una columna y los nombres en otra).
_PUESTO_SOLO = re.compile(r"(?m)^\W{0,2}\d{1,3}\s*[.o]\s*$")


def es_lista_de_alumnos(texto: str) -> bool:
    """Si la hoja es una lista de personas aunque su cabeza no se lea: ocho renglones o más con su código o su número."""
    codigos = len(_CODIGO_DE_ALUMNO.findall(texto))
    numerados = len(_RENGLON_NUMERADO_DE_LA_LISTA.findall(unicodedata.normalize("NFC", texto).upper()))
    puestos = len(_PUESTO_SOLO.findall(texto))
    return max(codigos, numerados, puestos) >= RENGLONES_DE_UNA_LISTA


#: La constancia de calificaciones de un alumno, cosida en el libro de actas
#: (1996-1998-1999 TOMO I pág. 3): «HACE CONSTAR Que, ____ cursó y aprobó en
#: esta Facultad … con las siguientes calificaciones», y su hoja de
#: «Continuación Calificaciones de …».
_CONSTANCIA_DE_CALIFICACIONES = re.compile(r"HACE\W{0,3}CONSTAR.{0,400}?CURS\w*\W+(?:Y\W+)?APROB|\bHA\s+CURSADO\b")
_CONTINUACION_DE_CALIFICACIONES = re.compile(r"\bCON\w{4,10}\s+(?:DE\s+)?CA\w{3,14}\s+DE\b")
_ALUMNO_DE_LA_CONSTANCIA = re.compile(r"HACE\W{0,3}CONSTAR\W{0,6}QUE\W{1,3}")
_ANIO_DE_LAS_NOTAS = re.compile(r"\bSEMESTRE\W{0,3}(?:DE\W+)?(?P<anio>(?:19|20)\d\d)\b|\bANO\W{0,3}(?P<otro>(?:19|20)\d\d)\b")


@dataclass(frozen=True, slots=True)
class CalificacionesDelAlumno:
    """La constancia de calificaciones de un alumno: su nombre, si va a máquina, y los años de sus notas."""

    nombre: str | None
    anio_inicial: int | None
    anio_final: int | None


def calificaciones_del_alumno(paginas: Sequence[str]) -> CalificacionesDelAlumno | None:
    """Si las hojas son la constancia de calificaciones de un alumno: su nombre y sus años; ``None`` si no lo son."""
    planos = [_plano(texto) for texto in paginas]
    if not any(_CONSTANCIA_DE_CALIFICACIONES.search(plano) or _CONTINUACION_DE_CALIFICACIONES.search(plano) for plano in planos):
        return None
    nombre = None
    for plano in planos:
        if marca := _ALUMNO_DE_LA_CONSTANCIA.search(plano):
            # «Que, LIZELIA M. ALFARO ZOLA, cursó…»; a mano sobre la raya, la capa no lo trae.
            nombre = _nombre_tras(plano[marca.end() :])
        elif marca := _CONTINUACION_DE_CALIFICACIONES.search(plano):
            nombre = nombre or _nombre_tras(plano[marca.end() :])
        if nombre:
            break
    anios = sorted(
        int(hallado.group("anio") or hallado.group("otro")) for plano in planos for hallado in _ANIO_DE_LAS_NOTAS.finditer(plano)
    )
    return CalificacionesDelAlumno(nombre, anios[0] if anios else None, anios[-1] if anios else None)


@dataclass(frozen=True, slots=True)
class DocumentoDeUnaPersona:
    """Una carta, un poder o una constancia de una persona, cosida entre las actas."""

    #: Lo que es, para su nombre: «AUTORIZACION PARA RECIBIR EL DIPLOMA».
    clase: str
    nombre: str | None
    cedula: str | None
    #: Una copia de la cédula nunca va sola: va con el acta de su dueño.
    anexo: bool = False


AUTORIZACION = "AUTORIZACION PARA RECIBIR EL DIPLOMA"
PAZ_Y_SALVO = "CONSTANCIA DE PAZ Y SALVO"
RECIBO_DEL_ACTA = "CONSTANCIA DE RECIBO DEL ACTA DE GRADO"
COPIA_DE_LA_CEDULA = "COPIA DE LA CEDULA"
#: «Yo, JULIO ALEJANDRO DE LA OSSA SALCEDO, identificado…» o «… autorizo a…».
_AUTORIZA = re.compile(r"\bAUTORIZ\w*|\bCONFIERO\s+PODER|\bPODER\s+(?:ESPECIAL|AMPLIO)|^\W*PODER\b|\W\sPODER\s")
_PARA_QUE = re.compile(r"RECLAM|RETIR|RECIB|DILIGENCIAS|ACTA\s+DE\s+GRADO|DIPLOMA")
_QUIEN_ESCRIBE = re.compile(r"\bYO\b\W{0,3}(?=[A-Z])")
_MAYOR_DE_EDAD = re.compile(r"((?:[A-Z]{2,}\W{1,3}){2,6}?)(?:MAYOR\s+DE\s+EDAD|IDENTIFICAD[AO])")
_QUIEN_FIRMA = re.compile(r"\bATENTAMENTE\W{0,4}")
_PAZ_Y_SALVO = re.compile(r"PAZ\s+Y\s+SALVO")
_EL_SENOR_DE_LA_CONSTANCIA = re.compile(r"\bEL\s+SENOR\s*(?:\(\W{0,2}SRTA\W{0,3}\)\s*)?\W{0,3}(?:DOCTOR\W+|DR\W+)?")
_RECIBO_DEL_ACTA = re.compile(r"HE\s+RECIBIDO\s+EL\s+ACTA\s+DE\s+GRADO")
_COPIA_DE_LA_CEDULA = re.compile(r"IDENTIFICACION\s+PERSONAL|CEDULA\s+DE\s+CIUDADANIA.{0,120}(?:APELLIDOS|NOMBRES|NACIMIENTO)")
_APELLIDOS_Y_NOMBRES = re.compile(r"APELLIDOS\W+(?P<apellidos>(?:[A-Z]{2,}\W{1,3}){1,3}?)NOMBRES\W+(?P<nombres>(?:[A-Z]{2,}\W{0,3}){1,3})")
_CEDULA_DEL_DOCUMENTO = re.compile(r"(?:C\W?C\W{0,3}|CEDULA\s+DE\s+CIUDADANIA\W{0,3}(?:N\w{0,6}\W{0,3})?)(?:#\W*)?(\d{1,3}(?:\W?\d{3}){2,3})")
#: Lo que no es de un nombre aunque vaya detrás: «RAMON GONZALEZ VALLEJO no (a)».
_COLA_QUE_NO_ES_NOMBRE = {"NO", "EGRESADO", "EGRESADA", "IDENTIFICADO", "IDENTIFICADA", "ALUMNO", "ALUMNA", "VECINO", "VECINA"}


def _sin_cola(nombre: str | None) -> str | None:
    palabras = (nombre or "").split()
    while palabras and palabras[-1] in _COLA_QUE_NO_ES_NOMBRE:
        palabras.pop()
    return " ".join(palabras) if len(palabras) >= 2 else None


def _cifras_de_la_cedula(plano: str, desde: int = 0) -> str | None:
    hallada = _CEDULA_DEL_DOCUMENTO.search(plano, desde)
    return re.sub(r"\D", "", hallada.group(1)) if hallada else None


def documento_de_una_persona(texto: str) -> DocumentoDeUnaPersona | None:
    """Si la hoja es una carta, un poder o una constancia de una persona: qué es y de quién; ``None`` si no.

    El graduado que autoriza a otro a recibir su diploma -- «Yo, JULIO
    ALEJANDRO DE LA OSSA SALCEDO … autorizo al señor MARLON ENRIQUE COHEN
    ARTEAGA … para reclamar mi acta de grado» (1996-1998-1999 TOMO II pág. 1) --,
    el que confiere poder -- «AMANDA BEATRIZ MULETT MENDOZA, mayor de edad …
    confiero poder especial» --, la constancia de paz y salvo de un egresado y la
    copia de una cédula. De quién es lo dice quien escribe o la constancia, no
    a quien se autoriza.
    """
    plano = _plano(texto)
    if _COPIA_DE_LA_CEDULA.search(plano):
        partes = _APELLIDOS_Y_NOMBRES.search(plano)
        nombre = (
            _sin_cola(" ".join([*re.findall(r"[A-Z]{2,}", partes.group("nombres")), *re.findall(r"[A-Z]{2,}", partes.group("apellidos"))]))
            if partes
            else None
        )
        return DocumentoDeUnaPersona(COPIA_DE_LA_CEDULA, nombre, _cifras_de_la_cedula(plano), anexo=True)
    # «HACE C O N S T A R» espaciado no se lee como CONSTAR: basta «el Señor (Srta.)».
    if _PAZ_Y_SALVO.search(plano) and (_CONSTANCIA.search(plano) or _EL_SENOR_DE_LA_CONSTANCIA.search(plano)):
        marca = _EL_SENOR_DE_LA_CONSTANCIA.search(plano)
        nombre = _sin_cola(_nombre_tras(plano[marca.end() :])) if marca else None
        return DocumentoDeUnaPersona(PAZ_Y_SALVO, nombre, None)
    if _RECIBO_DEL_ACTA.search(plano):
        return DocumentoDeUnaPersona(RECIBO_DEL_ACTA, None, _cifras_de_la_cedula(plano))
    if not (_AUTORIZA.search(plano) and _PARA_QUE.search(plano)):
        return None
    nombre = None
    desde = 0
    if quien := _QUIEN_ESCRIBE.search(plano):
        nombre, desde = _sin_cola(_nombre_tras(plano[quien.end() :])), quien.end()
    # Quien se identifica antes de autorizar es quien escribe; el que se
    # identifica después es el autorizado («autorizar a la Dra. NELLYS …,
    # identificada con…»), que no es del libro.
    autoriza = _AUTORIZA.search(plano)
    if not nombre and (mayor := _MAYOR_DE_EDAD.search(plano, 0, autoriza.start() if autoriza else len(plano))):
        nombre = _sin_cola(" ".join(re.findall(r"[A-Z]{2,}", mayor.group(1))[-4:]))
        desde = mayor.end()
    if not nombre and (firma := _QUIEN_FIRMA.search(plano)):
        nombre, desde = _sin_cola(_nombre_tras(plano[firma.end() :])), firma.end()
    return DocumentoDeUnaPersona(AUTORIZACION, nombre, _cifras_de_la_cedula(plano, desde))


def tipo_de_hoja(texto: str) -> str:
    """La clase de la hoja con lo que el libro trae entre las actas: ``LISTA``, ``PORTADA``, ``DOCUMENTO`` o ``CALIFICACIONES_DEL_ALUMNO``.

    Primero lo de siempre (``clase_de_hoja``): el acta y la hoja de la
    ceremonia no cambian. Sólo la hoja que antes «seguía» a la anterior se
    mira otra vez -- y la de la ceremonia que es una lista con su título --.
    """
    clase = clase_de_hoja(texto)
    if clase == GRADUADO:
        return GRADUADO
    # La constancia de calificaciones dice «… semestre de Odontología»: antes que la lista.
    if clase == SIGUE and calificaciones_del_alumno([texto]) is not None:
        return CALIFICACIONES_DEL_ALUMNO
    if clase == SIGUE and (titulo_de_la_lista(texto) is not None or continua_la_lista(texto)):
        return LISTA
    if clase == CEREMONIA:
        return CEREMONIA
    if es_portada(texto):
        return PORTADA
    if documento_de_una_persona(texto) is not None:
        return DOCUMENTO
    if es_lista_de_alumnos(texto):
        return LISTA
    return SIGUE


#: Cuánto se tienen que parecer dos palabras de dos nombres para ser la misma
#: mal leída: «MULSCT» es MULET, «IULFONSO» es ALFONSO (2026-11-27).
PARECIDO_DE_UNA_PALABRA_DEL_NOMBRE = 0.7


#: Lo que precede a un nombre y no es de él: «(Srta.) Doctor RAUL ESPINOSA».
_TRATAMIENTOS = {"SRTA", "SRITA", "SENOR", "SENORA", "SENORITA", "DOCTOR", "DOCTORA", "DRA"}


def _palabras_del_nombre(nombre: str | None) -> list[str]:
    return [
        p for p in re.findall(r"[A-Z]{3,}", _plano(nombre or "")) if p not in _ENLACES_DEL_NOMBRE and p not in _TRATAMIENTOS
    ]


def _la_misma_lista(una: str | None, otra: str | None) -> bool:
    """Si dos hojas seguidas son de la misma lista: el mismo título, o uno que no lo dice o que sólo dice menos."""
    if una is None or otra is None or una == otra:
        return True
    partes = [_DEL_TITULO_DEL_SEMESTRE.match(una), _DEL_TITULO_DEL_SEMESTRE.match(otra)]
    if not all(partes):
        return False
    return all(
        partes[0].group(campo) is None or partes[1].group(campo) is None or partes[0].group(campo) == partes[1].group(campo)  # type: ignore[union-attr]
        for campo in ("semestre", "periodo", "anio")
    )


def palabras_en_comun(uno: str | None, otro: str | None, parecido: float = PARECIDO_DE_UNA_PALABRA_DEL_NOMBRE) -> int:
    """Cuántas palabras de un nombre están, bien o mal leídas, en el otro."""
    otras = _palabras_del_nombre(otro)
    return sum(
        1
        for palabra in _palabras_del_nombre(uno)
        if any(difflib.SequenceMatcher(None, palabra, otra).ratio() >= parecido for otra in otras)
    )


#: Para decir que un documento no tiene nada que ver con el graduado de delante
#: hace falta más que el parecido de una palabra: ELENA se parece a MILENA.
PARECIDO_PARA_NADA_QUE_VER = 0.85


def misma_cedula(una: str | None, otra: str | None) -> bool:
    """Si dos cédulas leídas son la misma: las mismas cifras, o una cambiada si son igual de largas."""
    a, b = re.sub(r"\D", "", una or ""), re.sub(r"\D", "", otra or "")
    if len(a) < 6 or len(b) < 6:
        return False
    return a == b or (len(a) == len(b) and sum(x != y for x, y in zip(a, b, strict=True)) <= 1)


def es_de_la_persona(nombre: str | None, cedula: str | None, de_nombre: str | None, de_cedula: str | None) -> bool:
    """Si un documento es de la persona de un acta: su cédula, o dos palabras del nombre (la mitad o más)."""
    if misma_cedula(cedula, de_cedula):
        return True
    comunes = palabras_en_comun(nombre, de_nombre)
    return comunes >= 2 and comunes * 2 >= min(len(_palabras_del_nombre(nombre)), len(_palabras_del_nombre(de_nombre)))


@dataclass(slots=True)
class _TramoDelLibro:
    desde: int
    hasta: int
    ceremonia: bool
    clase: str
    #: El título de la lista, o el número del acta del Consejo Directivo.
    titulo: str | None = None
    #: De quién es: el graduado de su acta, o quien escribe el documento.
    nombre: str | None = None
    cedula: str | None = None
    #: Del documento suelto: si sólo va como anexo (la copia de la cédula).
    anexo: bool = False


def _persona_del_acta(texto: str) -> tuple[str | None, str | None]:
    acta = leer_acta_de_grado([texto])
    return acta.nombre, acta.cedula


def actas_de_grado_del_pdf(
    paginas: Sequence[str], foliadas: Collection[int] | None = None, *, conocidas: Collection[str] = ()
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

    Lo que el libro trae cosido entre las actas (Odontología 3194-3198,
    2026-11-27; ``tipo_de_hoja``):

    * **la lista de alumnos o de la promoción** va en su tramo, con sus hojas
      de continuación: es un documento con su título y su fila;
    * **la portada «ACTAS»** de cada ceremonia, en el suyo, sin fila;
    * **la copia del acta del Consejo Directivo** de 1980 es el acta de su
      alumno, y la segunda copia de la misma acta (su número) va con ella;
    * **la carta, el poder o la constancia de una persona** van con el acta de
      delante si son de su graduado o no se lee de quién son (los anexos
      siguen la secuencia); con la de detrás si son del graduado de ésa; si
      no son de ninguno de los dos, en su propio tramo, con su fila. La copia
      de una cédula nunca va sola;
    * **la constancia de calificaciones** de un alumno, igual: con su acta si
      es suya, si no, en su tramo.

    ``conocidas`` son los nombres y apellidos hispanos de la lista del bot: un
    documento sólo se separa de su vecina si nombra a alguien de verdad
    («CLAUDIA ROMERO FLOREZ»), no si el OCR dejó su nombre en letras sueltas
    («EFBAUI JAJITODIO OLAIFFIE CASTILLO», el poder de EFRAIN ANTONIO OLARTE).
    """
    total = len(paginas)
    con_folio = set(foliadas) if foliadas is not None else None
    tramos: list[_TramoDelLibro] = []
    for numero, texto in enumerate(paginas, start=1):
        tipo = tipo_de_hoja(texto)
        sin_folio = con_folio is not None and numero not in con_folio
        anterior = tramos[-1] if tramos else None
        if tipo == GRADUADO:
            # El acta de un graduado es su documento aunque su folio no se vea:
            # pegarla a la anterior juntaría a dos graduados en una fila. Salvo
            # la segunda copia de la misma acta del Consejo Directivo: su número
            # es el de un solo alumno (1980-1984 TOMO I, págs. 18-19, la 782).
            del_consejo = numero_del_acta_del_consejo(texto)
            if del_consejo and anterior is not None and anterior.clase == GRADUADO and anterior.titulo == del_consejo:
                anterior.hasta = numero
                continue
            nombre, cedula = _persona_del_acta(texto)
            tramos.append(_TramoDelLibro(numero, numero, False, GRADUADO, del_consejo, nombre, cedula))
        elif tipo == LISTA:
            titulo = titulo_de_la_lista(texto)
            de_su_lista = (
                anterior is not None
                and anterior.clase == LISTA
                and (continua_la_lista(texto) or _la_misma_lista(anterior.titulo, titulo))
            )
            # La hoja de una resolución o de un listado que sigue con sus nombres.
            de_su_ceremonia = titulo is None and anterior is not None and anterior.clase == CEREMONIA
            if de_su_lista or de_su_ceremonia:
                anterior.hasta = numero  # type: ignore[union-attr]
                if de_su_lista and anterior is not None:
                    anterior.titulo = titulo_de_las_hojas([anterior.titulo, titulo])
            else:
                tramos.append(_TramoDelLibro(numero, numero, True, LISTA, titulo))
        elif tipo == PORTADA:
            if anterior is not None and anterior.clase == PORTADA:
                anterior.hasta = numero
            else:
                tramos.append(_TramoDelLibro(numero, numero, True, PORTADA))
        elif tipo == CEREMONIA and anterior is not None and (
            sin_folio or (con_folio is None and anterior.ceremonia) or _sigue_la_resolucion(texto, anterior)
        ):
            anterior.hasta = numero
        elif tipo == CEREMONIA or anterior is None and tipo == SIGUE:
            # Una hoja de la ceremonia con su folio abre su documento: el
            # listado, la resolución. Y lo que va antes de todo -- una portada
            # sin texto -- es de la ceremonia que empieza.
            tramos.append(
                _TramoDelLibro(numero, numero, True, CEREMONIA, numero_de_la_resolucion(texto) if tipo == CEREMONIA else None)
            )
        elif tipo in (DOCUMENTO, CALIFICACIONES_DEL_ALUMNO):
            if tipo == DOCUMENTO:
                documento = documento_de_una_persona(texto)
                nombre, cedula, anexo = (documento.nombre, documento.cedula, documento.anexo) if documento else (None, None, True)
            else:
                calificaciones = calificaciones_del_alumno([texto])
                nombre, cedula, anexo = (calificaciones.nombre if calificaciones else None), None, False
            tramos.append(_TramoDelLibro(numero, numero, True, tipo, None, nombre, cedula, anexo))
        else:
            # El vuelto, una nota a mano: de la hoja anterior.
            anterior.hasta = numero  # type: ignore[union-attr]
    tramos = _documentos_en_su_sitio(tramos, conocidas)
    if not tramos:
        return ActasDelPdf(tramos=(TramoDeActa(1, max(1, total)),))
    return ActasDelPdf(
        tramos=tuple(
            TramoDeActa(tramo.desde, tramo.hasta, ceremonia=tramo.ceremonia, hojas=tramo.hasta - tramo.desde + 1)
            for tramo in tramos
        )
    )


def _documentos_en_su_sitio(tramos: list[_TramoDelLibro], conocidas: Collection[str] = ()) -> list[_TramoDelLibro]:
    """Cada carta, poder o constancia suelta, con el acta de su persona o en su propio tramo.

    Con la de delante si es de su graduado, si no se lee de quién es o si es
    sólo un anexo -- la copia de una cédula --: los anexos siguen la secuencia.
    Con la de detrás si es del graduado de ésa y no se parece en nada al de
    delante. Si no es de ninguno de los dos, se queda en su tramo y lleva su
    fila: nunca dos personas en un PDF. Las hojas que la siguen sin abrir nada
    van con ella.
    """
    resultado: list[_TramoDelLibro] = []
    for indice, tramo in enumerate(tramos):
        if tramo.clase not in (DOCUMENTO, CALIFICACIONES_DEL_ALUMNO):
            resultado.append(tramo)
            continue
        anterior = resultado[-1] if resultado else None
        siguiente = tramos[indice + 1] if indice + 1 < len(tramos) else None
        delante = anterior is not None and anterior.nombre is not None and es_de_la_persona(
            tramo.nombre, tramo.cedula, anterior.nombre, anterior.cedula
        )
        # Si el graduado de delante no se lee, no se sabe: ante la duda se une.
        # Si lo de delante no es de nadie -- una lista, una portada --, nada.
        if anterior is None or (anterior.nombre is None and anterior.clase != GRADUADO):
            nada_que_ver = True
        elif anterior.nombre is None:
            nada_que_ver = False
        else:
            nada_que_ver = palabras_en_comun(tramo.nombre, anterior.nombre, PARECIDO_PARA_NADA_QUE_VER) == 0 and not misma_cedula(
                tramo.cedula, anterior.cedula
            )
        detras = (
            siguiente is not None
            and siguiente.clase == GRADUADO
            and es_de_la_persona(tramo.nombre, tramo.cedula, siguiente.nombre, siguiente.cedula)
        )
        palabras = _palabras_del_nombre(tramo.nombre)
        legible = len([p for p in palabras if p in conocidas] if conocidas else palabras) >= 2
        if detras and nada_que_ver and siguiente is not None:
            siguiente.desde = tramo.desde
        elif anterior is not None and (delante or not legible or tramo.anexo or not nada_que_ver):
            anterior.hasta = tramo.hasta
        else:
            resultado.append(tramo)
    return resultado


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
        encabezado = encabezado_de_la_ceremonia(paginas)
        # La carta o la constancia de una persona: de quién es y su cédula, que
        # su fila del FUID lleva (2026-11-27).
        documento = (
            documento_de_una_persona(paginas[0] or "")
            if paginas and str(encabezado or "").startswith(_ENCABEZADOS_DE_DOCUMENTO)
            else None
        )
        return ActaDeConsejo(
            rotulo=ROTULO_DE_CEREMONIA,
            nombre=documento.nombre if documento else None,
            cedula=documento.cedula if documento else None,
            # La lista, con la de su título: la de un periodo es su año
            # (2026-11-27); un listado de nombres no tiene otra.
            fecha=fecha_de_la_lista(encabezado) if es_encabezado_de_lista(encabezado) else _fecha_de_la_ceremonia(paginas),
            # Lo que dice ser la hoja: la resolución de los grados o la
            # ceremonia con sus actas (2026-11-12). La hoja de la ceremonia no
            # tiene sesión; el campo lo lleva.
            sesion=encabezado,
        )
    pagina, texto = hoja
    return completar_acta(ActaDeConsejo(rotulo=ROTULO, pagina=pagina), texto)


#: Lo que abre el encabezado de un documento del libro que no es un acta ni una
#: hoja de la ceremonia, y que por eso lleva su fila en el FUID (2026-11-27).
_ENCABEZADOS_DE_LISTA = ("LISTA DE ", "PROMOCION ", "EGRESADOS ", "RELACION DE ")
_ENCABEZADOS_DE_DOCUMENTO = (AUTORIZACION, PAZ_Y_SALVO, RECIBO_DEL_ACTA)
#: La constancia de calificaciones que no es de ningún graduado del libro:
#: «CALIFICACIONES - NOMBRE», una fila de calificaciones.
ROTULO_DE_CALIFICACIONES = "CALIFICACIONES"


def es_encabezado_de_lista(encabezado: object) -> bool:
    """Si el encabezado de una hoja de la ceremonia es el de una lista de alumnos o de la promoción."""
    return str(encabezado or "").startswith(_ENCABEZADOS_DE_LISTA)


def es_encabezado_con_fila(encabezado: object) -> bool:
    """Si la hoja que no es un acta es un documento con su fila: una lista, una carta, una constancia.

    La portada y la hoja que sólo lista a los graduandos de la ceremonia siguen
    sin fila (2026-11-12); la resolución de los grados, con la suya.
    """
    texto = str(encabezado or "")
    return es_encabezado_de_lista(texto) or texto.startswith(_ENCABEZADOS_DE_DOCUMENTO)


def fecha_de_la_lista(encabezado: object) -> date | None:
    """La fecha de una lista por su título: el día de la promoción, o el 1 de enero de su año."""
    texto = str(encabezado or "")
    if completa := re.search(r"\b(\d{2})-(\d{2})-(\d{4})\b", texto):
        try:
            return date(int(completa.group(3)), int(completa.group(2)), int(completa.group(1)))
        except ValueError:
            return None
    if mes := re.search(r"\b(\d{2})-(\d{4})\b", texto):
        return date(int(mes.group(2)), int(mes.group(1)), 1) if 1 <= int(mes.group(1)) <= 12 else None
    if anio := re.search(r"\b((?:19|20)\d\d)\b", texto):
        return date(int(anio.group(1)), 1, 1)
    return None


def fechas_extremas_de_la_lista(encabezado: object, fecha: date | None) -> tuple[date | None, date | None]:
    """Las fechas extremas de una lista: la de su promoción en las dos; de un mes o de un año, su primer y su último día.

    Lo dijo el operador para la lista de la promoción (2026-11-27): «la
    promoción completa en las dos; si solo hay periodo o año, 01/01 y 31/12 de
    ese año».
    """
    texto = str(encabezado or "")
    if fecha is None:
        return None, None
    if re.search(r"\b\d{2}-\d{2}-\d{4}\b", texto):
        return fecha, fecha
    if re.search(r"\b\d{2}-\d{4}\b", texto):
        siguiente = date(fecha.year + (fecha.month == 12), fecha.month % 12 + 1, 1)
        return fecha.replace(day=1), date.fromordinal(siguiente.toordinal() - 1)
    return date(fecha.year, 1, 1), date(fecha.year, 12, 31)


def _encabezado_de_lo_cosido(paginas: Sequence[str]) -> str | None:
    """El encabezado de un tramo que abre una lista, una carta o una constancia de calificaciones (2026-11-27)."""
    if not paginas:
        return None
    primera = tipo_de_hoja(paginas[0] or "")
    if primera == LISTA:
        titulos = [titulo_de_la_lista(texto or "") for texto in paginas if tipo_de_hoja(texto or "") == LISTA]
        return titulo_de_las_hojas(titulos) or LISTA_DE_ALUMNOS
    if primera == CALIFICACIONES_DEL_ALUMNO:
        calificaciones = calificaciones_del_alumno(paginas)
        nombre = calificaciones.nombre if calificaciones else None
        return " - ".join([ROTULO_DE_CALIFICACIONES, *([nombre] if nombre else [])])
    if primera == DOCUMENTO and (documento := documento_de_una_persona(paginas[0] or "")) is not None:
        return " - ".join([documento.clase, *([documento.nombre] if documento.nombre else [])])
    return None


#: «RESOLUCIÓN No. 01633», en la cabeza de la hoja.
_RESOLUCION_DE_GRADOS = re.compile(r"RESOLUCI[O0]N\s+N\W?[O0]?\W{0,3}\s*([0-9OIl]{3,6})\b")
#: El número a máquina que la capa pone detrás del «de 1.9» impreso del
#: formulario: «Resolución No. de 1.9 0 289» es la 0289 (1980-1984 TOMO I
#: pág. 31, 2026-11-27).
_RESOLUCION_DEL_FORMULARIO = re.compile(r"RESOLUCI[O0]N\s+N\W?[O0]?\W{0,3}\s*DE\s+1\W?9\W{0,3}\s*(\d{1,2}\s?\d{3})\b")
#: «Resolución No. de 1.9 Hoja 2»: la segunda hoja de la resolución, con el
#: membrete repetido.
_HOJA_DE_LA_RESOLUCION = re.compile(r"\bHOJA\W{0,3}(?:N\W{0,3}[O0]?\W{0,3})?[2-9]\b")


def numero_de_la_resolucion(texto: str) -> str | None:
    """El número de la resolución que nombra la cabeza de la hoja: «0289», «912»; ``None`` si no lo dice."""
    cabeza = _plano(" ".join((texto or "").split())[:1200])
    hallada = min(
        (encontrada for encontrada in (_RESOLUCION_DE_GRADOS.search(cabeza), _RESOLUCION_DEL_FORMULARIO.search(cabeza)) if encontrada),
        key=lambda encontrada: encontrada.start(),
        default=None,
    )
    if hallada is None:
        return None
    return re.sub(r"\s", "", hallada.group(1)).replace("O", "0").replace("I", "1").replace("l", "1")


def _sigue_la_resolucion(texto: str, anterior: _TramoDelLibro) -> bool:
    """Si la hoja de la ceremonia es la siguiente de la resolución de delante: su mismo número o «Hoja 2».

    Cada hoja repite el membrete «Resolución No. … de 1.97…»: las tres de la
    resolución de 1972 que abre «ACTAS DE GRADO 1960-1965», y la «Hoja 2» de la
    0289 (1980-1984 TOMO I pág. 32), son una resolución y no tres (2026-11-27).
    """
    if anterior.clase != CEREMONIA or anterior.titulo is None:
        return False
    cabeza = _plano(" ".join((texto or "").split())[:400])
    numero = numero_de_la_resolucion(texto)
    return numero == anterior.titulo or (numero is None and bool(_HOJA_DE_LA_RESOLUCION.search(cabeza)))


#: «"Por medio de la cual se autorizan grados secretariales"».
_EPIGRAFE = re.compile(r"POR\s+MEDIO\s+DE\s+LA\s+CUAL\s+[A-Z ,]{5,120}?(?=\W{0,3}\s*(?:EL\s+RECTOR|CONSIDERANDO|$))")
#: «Actas de Grado No. 05418726 a 05418731».
_ACTAS_DE_LA_CEREMONIA = re.compile(r"ACTAS\s+DE\s+GRADO\s+N\W?[O0]?\W{0,3}\s*(\d{4,10})\s+A\s+(\d{4,10})")
ROTULO_DE_RESOLUCION = "RESOLUCION"


def encabezado_de_la_ceremonia(paginas: Sequence[str]) -> str | None:
    """Lo que dice ser la hoja que no es el acta de un graduado: la resolución o la ceremonia con sus actas.

    Lo pidió el operador el 2026-11-12 sobre Odontología: la «RESOLUCIÓN No.
    01633, por medio de la cual se autorizan grados secretariales», con su
    lista de cédulas y nombres, salía «CEREMONIA DE GRADO» como la hoja de la
    ceremonia. Ahora es «RESOLUCION 01633 - POR MEDIO DE LA CUAL SE AUTORIZAN
    GRADOS SECRETARIALES»; y la ceremonia, «CEREMONIA DE GRADO - ACTAS 05418726
    A 05418731». Desde el 2026-11-27, también lo cosido entre las actas: la
    lista con su título («LISTA DE ALUMNOS IX SEMESTRE DE ODONTOLOGIA - 1
    PERIODO 1984», «PROMOCION 17-12-1999»), la carta o la constancia de una
    persona («AUTORIZACION PARA RECIBIR EL DIPLOMA - NOMBRE») y la constancia de
    calificaciones de un alumno («CALIFICACIONES - NOMBRE»). ``None`` si no dice
    nada de eso: la portada, la hoja que sólo lista a los graduandos.
    """
    from .title import lo_que_resuelve

    for texto in paginas:
        cabeza = _plano(" ".join((texto or "").split())[:1200])
        # La primera que nombra la cabeza: «Resolución No. de 1.9 0 289 … mediante
        # Resolución No. 014 del 21 de febrero» es la 0289.
        numero = numero_de_la_resolucion(texto or "")
        if numero and "RESUELVE" in _plano(texto or ""):
            # El asunto de una resolución de la Universidad es la resolución
            # más lo que resuelve (el operador, 2026-11-03 en la caja 3303 y
            # 2026-11-12 para todas sus habilidades); sin RESUELVE legible, su
            # epígrafe.
            resuelve = lo_que_resuelve(paginas)
            epigrafe = _EPIGRAFE.search(cabeza)
            resumen = _plano(resuelve) if resuelve else (epigrafe.group(0).strip(" ,") if epigrafe else None)
            return " - ".join([f"{ROTULO_DE_RESOLUCION} {numero}", *([resumen] if resumen else [])])
        if actas := _ACTAS_DE_LA_CEREMONIA.search(cabeza):
            return f"{ROTULO_DE_CEREMONIA} - ACTAS {actas.group(1)} A {actas.group(2)}"
    # Lo que el libro trae cosido entre las actas: la lista, la carta, la
    # constancia de calificaciones (Odontología 3194-3198, 2026-11-27).
    return _encabezado_de_lo_cosido(paginas)


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
#: «… y otras», «… (hoy Sra. de Vela)», «… quienes cumplieron» (UPD3859800), y
#: «… José Miguel Méndez Méndez Presidió el Consejo…» sin el punto, que la IA
#: lee también «Precedio» (UPD3860000, 1946), y «… Lázan Valdelamar Del Consejo
#: fué integrado…» (UPD3859999, 1935).
_NO_ES_NOMBRE = {
    "ESTE", "QUIEN", "CON", "PARA", "POR", "EL", "SE", "QUE", "OTRAS", "OTROS", "HOY", "QUIENES",
    "PRESIDIO", "PRECEDIO", "CONSEJO", "FUE",
}
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
    tras_inicial = False
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
        # Tras una inicial con punto el nombre sólo sigue si aún no tiene
        # apellido o si sigue un enlace: «Jorge H. Navarro Palacio» sigue,
        # «Miguel F. de la Espriella G. Presidió…» acaba en la G.
        # Sin contar los enlaces: «EMMA DEL C. VEGA BANDA» sigue tras la inicial
        # (el acta del Consejo Directivo de 1980, 2026-11-27).
        if (
            tras_inicial
            and len([p for p in palabras if p not in _ENLACES_DEL_NOMBRE]) >= 2
            and limpio not in _ENLACES_DEL_NOMBRE
        ):
            break
        tras_inicial = False
        if len(limpio) >= 2 or limpio in _ENLACES_DEL_NOMBRE:
            palabras.append(limpio)
        # La inicial con su punto, en medio, no acaba el nombre (los libros
        # manuscritos de 1924-1946).
        if re.fullmatch(r"[A-Z]\.", token) and palabras:
            tras_inicial = True
            continue
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


#: Cómo nombra el acta antigua al examinado: «del alumno Jesús Mª Barrios J.»,
#: «al Señor Luis María Merlano,», «del postulante …».
_EL_EXAMINADO = re.compile(
    r"\b(?:DEL\s+ALUMN[OA]|DE\s+LA\s+ALUMNA|AL\s+SENOR|A\s+LA\s+SENORITA|DEL\s+POSTULANTE)\b\W{0,3}"
    # «del alumno señor Rafael Ibáñez Ferrer», «de la alumna de Paulina Bengeff».
    r"(?:SENOR(?:ITA)?\b\W{0,2}|DE\s+(?=[A-Z]{3,}\s))?"
)
_PREPARATORIO = re.compile(
    # «el tercer examen preparatorio», «el examen de tercer preparatorio al grado».
    r"\b(PRIMER|SEGUNDO|TERCER|CUARTO|QUINTO|SEXTO|SEPTIMO|OCTAVO)O?\s+(?:EXAMEN\s+)?PREPARATORI"
)
#: El de arriba de la hoja: «(3er Preparatorio)», «4º Preparatorio», «(3ª preparatoria)».
_PREPARATORIO_DE_ARRIBA = re.compile(r"\b0?([1-8])\s*(?:ER|O|A)?\W{0,2}PREPARATORI")
_ORDINALES = {
    "1": "PRIMER", "2": "SEGUNDO", "3": "TERCER", "4": "CUARTO", "5": "QUINTO", "6": "SEXTO",
    "7": "SEPTIMO", "8": "OCTAVO",
}
#: «le confirió el título de Doctor en Medicina y Cirugía», y en los años
#: cuarenta «el grado de Doctor en …», que la IA lee «Sr. en …» u «Opción en …».
_TITULO_ANTIGUO = re.compile(
    r"(?:TITULO|GRADO)\s+DE\s+(\w{2,8}\.?\s+EN\s+[A-Z ]{5,60}?)"
    r"(?:\s*[,.]|\s+(?:AL|A\s+LA)\s+SEN|\s+Y\s+LE\b)"
)


def examen_antiguo(texto: str) -> tuple[str | None, str | None]:
    """El nombre del examinado y lo que obtuvo, de un acta manuscrita de 1924-1946; ``(None, None)`` si no lo es.

    El título es el del grado -- «DOCTOR EN MEDICINA Y CIRUGIA» -- o, en el
    libro de preparatorios, cuál: «QUINTO EXAMEN PREPARATORIO DE GRADO». El
    nombre, el de la frase -- «del alumno Mario Fernández Mendoza» -- o, si
    no se lee, el que la hoja lleva arriba como título.
    """
    plano = _plano_del_examen(texto)
    if not _EXAMEN_ANTIGUO.search(plano):
        return None, None
    del_texto = None
    for marca in _EL_EXAMINADO.finditer(plano):
        del_texto = _nombre_tras(plano[marca.end() :])
        if del_texto:
            break
    nombre = _nombre_confirmado(_nombre_de_arriba(texto), del_texto)
    preparatorio = _PREPARATORIO.search(plano)
    de_arriba = _PREPARATORIO_DE_ARRIBA.search(plano[: plano.find("CARTAGENA")])
    grado = _TITULO_ANTIGUO.search(plano) or _TITULO_DE_ODONTOLOGO.search(plano)
    if preparatorio:
        titulo = f"{preparatorio.group(1)} EXAMEN PREPARATORIO DE GRADO"
    elif de_arriba and de_arriba.group(1) in _ORDINALES:
        titulo = f"{_ORDINALES[de_arriba.group(1)]} EXAMEN PREPARATORIO DE GRADO"
    elif grado:
        titulo = grado.group(1).strip()
    else:
        titulo = None
    return nombre, titulo


#: Cuál examen es un acta manuscrita: lo que abre su fila y su asunto en el FUID
#: («ACTA DE EXAMEN PREPARATORIO DE GRADO - QUINTO PREPARATORIO - …», lo eligió
#: el operador el 2026-11-04).
PREPARATORIO = "PREPARATORIO"
FINAL = "FINAL"
#: Un acta de examen que no dice cuál: la decide `_los_examenes` por sus vecinas.
SIN_DECIR = ""
#: Cuánto de la frase que abre el acta se mira para saber cuál examen es: el
#: propósito, «con el fin de practicar el quinto examen preparatorio de grado».
LARGO_DEL_PROPOSITO = 300
#: El examen en que se confiere el título: «el examen final de grado», «el
#: examen general de grado», «el título de Doctor en …».
_EXAMEN_FINAL = re.compile(
    r"EXAMEN\s+(?:DE\s+GRADO\s+)?(?:FINAL|GENERAL)|FINAL\s+DE\s+GRADO|(?:TITULO|GRADO)\s+DE\s+DOCTOR"
    r"|MINISTERIO\s+DE\s+LA\s+LEY"
)
#: «el examen de Grado del alumno …»: el examen sin preparatorio (Odontología 1960-1971).
_EXAMEN_DE_GRADO = re.compile(r"\bEXAMEN\s+DE\s+GRADO\b")
#: «se le confirió el título de Odontólogo»: el título de una palabra, sin «Doctor en».
_TITULO_DE_ODONTOLOGO = re.compile(r"(?:TITULO|GRADO)\s+DE\s+(ODONTOLOG[OA])\b")
DOCTOR_EN_ODONTOLOGIA = "DOCTOR EN ODONTOLOGIA"
#: «DOCTOR EN MEDICINA Y GEOGRAFIA», «PODER EN MEDICINA Y CIRUGIA», «ACTO SIN
#: MEDICINA Y CUMBRE», «DOCTOR EN MECANICA Y CIENCIA»: la IA lee mal la letra a
#: mano, y el título que confiere el examen final de la Facultad de Medicina es
#: uno solo, «en Medicina y Cirugía».
_EN_MEDICINA_Y = re.compile(r"^(?:\w+\s+){0,2}MEDICINA\s+Y\s+\w+$|^(?:\w+\s+)?EN\s+\w+\s+Y\s+\w+$")
DOCTOR_EN_MEDICINA = "DOCTOR EN MEDICINA Y CIRUGIA"


def examen_de_grado(texto: str) -> str | None:
    """Cuál examen es un acta manuscrita de 1924-1946: «PREPARATORIO», «FINAL», o ``None`` si no lo es.

    Lo dice la frase que abre el acta -- «con el fin de practicar el quinto
    examen preparatorio», «… el examen final de grado» -- o el renglón de
    arriba, «(5º Preparatorio)». Se mira primero el comienzo: un acta final
    puede nombrar los preparatorios más abajo.

    Un acta de grado con su número -- «ACTA DE GRADO No. 03 … se reunió el
    Consejo Examinador» -- y la constancia que copia una de 1961 hablan igual,
    y no son actas de examen: conservan su número.
    """
    plano = _plano_del_examen(texto)
    abre = _EXAMEN_ANTIGUO.search(plano)
    if not abre or apertura(texto) is not None or constancia(texto) is not None:
        return None
    if "PREPARATORI" in plano[: abre.end() + LARGO_DEL_PROPOSITO]:
        return PREPARATORIO
    if _EXAMEN_FINAL.search(plano) or _TITULO_ANTIGUO.search(plano):
        return FINAL
    if "PREPARATORI" in plano:
        return PREPARATORIO
    # «el Jurado Examinador para verificar el examen de Grado del alumno…»
    # (Odontología, desde 1960) y «el título de Odontólogo»: el examen de grado
    # sin preparatorio es el que confiere el título (2026-11-27).
    if _EXAMEN_DE_GRADO.search(plano) or _TITULO_DE_ODONTOLOGO.search(plano):
        return FINAL
    # Sin nada que lo diga no se adivina: «final» por descarte ponía siete
    # preparatorios de UPD3859999 entre los finales.
    return SIN_DECIR


#: «1ª furiporatorio», «examen de tercer fuejaroztor al grado»: la IA lee mal
#: «Preparatorio» en algunas manos (UPD3859999). Detrás de un ordinal o de
#: «examen», una palabra con «TOR» que se le parece lo es. Sola no:
#: «Laboratorio» se le parece igual.
_PREPARATORIO_MAL_LEIDO = re.compile(
    r"\b((?:PRIMER|SEGUNDO|TERCER|CUARTO|QUINTO|SEXTO|SEPTIMO|OCTAVO)O?|EXAMEN|[1-8]\s?(?:ER|O|A)?)"
    r"(\W{1,3})([A-Z]{7,14})\b"
)
PARECIDO_DEL_PREPARATORIO = 0.5


def _plano_del_examen(texto: str) -> str:
    """El texto del acta manuscrita en mayúsculas, sin palabras partidas y con «PREPARATORIO» legible."""

    def legible(hallado: re.Match[str]) -> str:
        palabra = hallado.group(3)
        if (
            palabra.startswith("PREPARATORI")
            or "TOR" not in palabra
            or difflib.SequenceMatcher(None, palabra, "PREPARATORIO").ratio() < PARECIDO_DEL_PREPARATORIO
        ):
            return hallado.group(0)
        return f"{hallado.group(1)}{hallado.group(2)}PREPARATORIO"

    return _PREPARATORIO_MAL_LEIDO.sub(legible, _sin_cortes(_plano(texto)))


def titulo_del_examen(examen: str | None, titulo: str | None) -> str | None:
    """El título de un acta de examen como va al FUID; fuera de un examen, el mismo.

    Del preparatorio, cuál: «QUINTO EXAMEN PREPARATORIO DE GRADO», también de
    «5º PREPARATORIO». Sin el ordinal no dice cuál, y queda por leer: la IA
    devolvía «EXAMEN PREPARATORIO DE GRADO» y le ganaba a la regla, que sí
    leía «PRIMER». Del final, el que se confirió, con la última palabra que la
    IA lee mal llevada a DOCTOR EN MEDICINA Y CIRUGIA.
    """
    if not titulo or examen is None:
        return titulo
    plano = " ".join(re.sub(r"[^A-Z0-9 ]", " ", _plano(titulo)).split())
    if examen == PREPARATORIO and "PREPARATORI" in plano:
        cual = _PREPARATORIO.search(plano)
        if cual:
            return f"{cual.group(1)} EXAMEN PREPARATORIO DE GRADO"
        de_arriba = _PREPARATORIO_DE_ARRIBA.search(plano)
        if de_arriba and de_arriba.group(1) in _ORDINALES:
            return f"{_ORDINALES[de_arriba.group(1)]} EXAMEN PREPARATORIO DE GRADO"
        return None
    # Sin la cola de la frase ni los signos que el OCR no supo leer: «PODER EN
    # MEDICINA Y CIRUGIA? al Señor…».
    limpio = " ".join(re.sub(r"[^A-Z ]", " ", _plano(titulo_limpio(titulo) or titulo)).split())
    if any(len(palabra) >= 8 and _parecida(palabra, "ODONTOLOGIA") for palabra in limpio.split()):
        # Los exámenes de Odontología de 1952-1971: «Doctor en Odontología», o
        # «Odontólogo» a secas. Antes caían en el «Doctor…» de la Medicina, que
        # es el único título de la caja 3362 (2026-11-27).
        return DOCTOR_EN_ODONTOLOGIA if limpio.startswith("DOCTOR") or " EN " in f" {limpio} " else "ODONTOLOGO"
    if _EN_MEDICINA_Y.match(limpio) or "MEDICINA" in limpio or limpio.startswith("DOCTOR"):
        # «DOCTOREN», «MEDICINA», «DOCTOR EN MEDICINA»: el título cortado.
        # Siempre «DOCTOR»: la IA leyó «Doctora» en el acta de Gabriel R. Lago
        # Arroyo (UPD3860000, 1944), y el título es el mismo.
        return DOCTOR_EN_MEDICINA
    return titulo


#: Un renglón que es sólo un número: «1», «297», «# 44».
_NUMERO_SOLO = re.compile(r"^\W{0,3}(\d{1,3})\W{0,2}$")
#: Donde empieza el acta manuscrita, en el texto con sus mayúsculas y renglones.
_COMIENZO_DEL_ACTA = re.compile(
    r"\bEn\s+(?:la\s+c\w{4}d\s+de\s+|el\s+\w{6,10}\s+de\s+la\s+Universidad\s+de\s+)?Cartagena", re.IGNORECASE
)


def folio_del_texto(texto: str) -> int | None:
    """El número impreso del libro manuscrito en la esquina de la hoja, del texto que leyó la IA.

    La IA lee la página entera y arriba, antes de «En la ciudad de Cartagena»,
    trae el número del libro -- «1», «297» -- y después la foliación del
    archivista -- «1/V», «149», «82 / V» --. Es el primero que va solo en su
    renglón. El folio que eligió el operador para desde y hasta (2026-11-04).
    """
    cabeza = _COMIENZO_DEL_ACTA.split(texto, maxsplit=1)[0]
    for renglon in cabeza.splitlines():
        numero = _NUMERO_SOLO.match(renglon.strip())
        if numero and "/" not in renglon and int(numero.group(1)) > 0:
            return int(numero.group(1))
    return None


def es_acta_de_examen(acta: object) -> bool:
    """Si el encabezado de una fila es el de un acta de examen: «ACTA DE EXAMEN … DE GRADO»."""
    return str(acta or "").startswith("ACTA DE EXAMEN ")


#: «Acta No 132», «Acta Nº 203», «Acta No. 1»: el número del acta de examen de
#: Odontología, arriba de la hoja (1952-1971). Los de 1924-1946 no lo traen.
_NUMERO_DEL_EXAMEN = re.compile(r"\bACTA\W{0,3}N\W{0,2}[O0]?\W{0,3}(\d{1,4})\b")


def numero_del_examen(texto: str) -> str | None:
    """El número del acta de examen, de lo que va antes de «En … Cartagena»; ``None`` si no lo trae."""
    cabeza = _COMIENZO_DEL_ACTA.split(texto or "", maxsplit=1)[0]
    hallado = _NUMERO_DEL_EXAMEN.search(_plano(cabeza))
    return hallado.group(1) if hallado and hallado.group(1).strip("0") else None


#: «QUINTO EXAMEN PREPARATORIO DE GRADO» en el asunto: «QUINTO PREPARATORIO».
_EL_PREPARATORIO = re.compile(r"^(\w+) EXAMEN PREPARATORIO")


def especialidad_del_examen(titulo: str | None) -> str | None:
    """Lo que va tras el nombre en el asunto de un examen: el título conferido o cuál preparatorio fue.

    El estándar único de la Universidad (2026-11-27): «NOMBRE - DOCTOR EN
    ODONTOLOGIA» en el examen final y «NOMBRE - QUINTO PREPARATORIO» en el
    preparatorio, como cualquier persona: «NOMBRE - ESPECIALIDAD».
    """
    if not titulo:
        return None
    preparatorio = _EL_PREPARATORIO.match(titulo)
    return f"{preparatorio.group(1)} PREPARATORIO" if preparatorio else titulo


def asunto_del_examen(
    nombre: str | None,
    titulo: str | None,
    *,
    acta: str | None = None,
    numero: str | None = None,
    folio: object = None,
) -> str:
    """«JESUS MARIA BARRIOS - QUINTO PREPARATORIO», «FRANCISCO LOPEZ LOPEZ - DOCTOR EN ODONTOLOGIA»: el PDF y el asunto de un examen.

    Reemplaza al de 2026-11-04, «ACTA DE EXAMEN PREPARATORIO DE GRADO - QUINTO
    PREPARATORIO - NOMBRE»: el operador pidió el 2026-11-27 un solo estándar
    para todo lo de la Universidad. Sin nombre legible, el examen con su número
    o su folio: ningún PDF sin algo que lo referencie.
    """
    referencia = f"No. {numero}" if numero else (f"FOLIO {folio}" if folio not in (None, "", "N/A") else None)
    del_acta = " ".join(parte for parte in (acta or "ACTA DE EXAMEN DE GRADO", referencia) if parte)
    return asunto_del_graduado(nombre, especialidad_del_examen(titulo), acta=del_acta)


#: Lo que Windows no admite en el nombre de un archivo.
_NO_VALE_EN_UN_NOMBRE = re.compile(r'[<>:"/\\|?*]+')


def asunto_del_graduado(
    nombre: str | None, titulo: str | None, *, acta: str | None = None, cedula: str | None = None
) -> str:
    """«MARTHA LUCIA HERRERA VILLAMIZAR - ENFERMERA»: el nombre del PDF del graduado y su asunto en el FUID.

    Son el mismo texto -- lo pidió el operador el 2026-11-05: «que el nombre
    del PDF sea el mismo que vaya en el FUID», el nombre y la especialidad --,
    y por eso los dos salen de aquí. El número del acta y la cédula ya no van
    en él: tienen sus columnas en el FUID, desde y hasta.

    Del nombre, sólo lo que puede ser un nombre: una palabra imposible --
    «MSCSDSS», «AAAAANONO» -- no va ni al archivo ni al inventario. Sin nombre
    legible, el acta y la cédula: ningún archivo sin algo que lo referencie.
    """
    from .nombres import clave, parece_palabra_de_nombre

    limpio = " ".join(palabra for palabra in (nombre or "").split() if parece_palabra_de_nombre(clave(palabra)))
    if limpio:
        partes = [limpio, *([titulo] if titulo else [])]
    else:
        partes = [acta or f"{ROTULO} SIN NUMERO", *([cedula] if cedula else [])]
    return _NO_VALE_EN_UN_NOMBRE.sub("-", " - ".join(partes)).strip(" .").upper()


def _nombre_confirmado(arriba: str | None, del_texto: str | None) -> str | None:
    """El nombre entre sus dos apariciones en la hoja: arriba como título y en «del alumno …».

    Las dos están escritas a mano y la IA puede leer mal una de ellas: el de
    arriba manda en la forma; el del texto lo completa si lo dice entero
    («RAFAEL IBANEZ» arriba, «RAFAEL IBANEZ FERRER» en el texto) y, si las dos
    difieren en una palabra, se vota (``votar_nombre``). Con una sola, ésa.
    """
    if not arriba or not del_texto:
        return arriba or del_texto
    una, otra = arriba.split(), del_texto.split()
    if len(otra) > len(una) and [p for p in otra if p in una] == una:
        return del_texto
    if len(una) >= len(otra) and [p for p in una if p in otra] == otra:
        return arriba
    from .doble_lectura import votar_nombre

    votado, _duda = votar_nombre(arriba, [del_texto])
    return votado or arriba


def _sin_cortes(plano: str) -> str:
    """El texto sin las palabras partidas al final del renglón: «EX- AMEN» es EXAMEN."""
    return re.sub(r"(\w)-\s+(\w)", r"\1\2", plano)


#: Los renglones de arriba del acta de examen de Odontología que no son el alumno.
_MEMBRETE_DEL_EXAMEN = re.compile(r"^\W*(?:ACTA|REPUBLICA|UNIVERSIDAD|FACULTAD)\b")


def _nombre_de_arriba(texto: str) -> str | None:
    """El nombre que la hoja lleva arriba como título: «# Rodrigo de Vivero», «2 Mario Fernández Mendoza».

    Es el primer renglón con letras antes de «En … Cartagena», sin los números
    de página y folio ni el «(3er Preparatorio)».
    """
    cabeza = re.split(r"\bEn\s+(?:la\s+c\w{4}d\s+de\s+)?Cartagena", texto, maxsplit=1, flags=re.IGNORECASE)[0]
    for renglon in cabeza.splitlines():
        if _MEMBRETE_DEL_EXAMEN.match(_plano(renglon)):
            # «Acta No. 1», «República de Colombia - Universidad de Cartagena -
            # Facultad de Odontología»: el membrete de Odontología, no el alumno
            # (2026-11-27).
            continue
        limpio = re.sub(r"\(.*?\)|\d+\S*|#|[^\wÁÉÍÓÚÜÑáéíóúüñ .]", " ", renglon)
        limpio = re.sub(r"\b\w*PREPARATORI\w*\b", " ", limpio, flags=re.IGNORECASE)
        candidato = _nombre_tras(_plano(limpio) + ".")
        if candidato:
            return candidato
    return None


#: El final de un renglón y el principio del siguiente: «… ESPECIALISTAS EN EN» / «FERMERIA MEDICO…».
_PARTIDA_EN_DOS_RENGLONES = re.compile(r"\b([A-ZÁÉÍÓÚÑ]{2,9})[ \t]*-?[ \t]*\n\s*([A-ZÁÉÍÓÚÑ]{3,})\b")


#: «AL-\nVAREZ», «mon -\nSALVE», «so \xad\nCORRO»: un trozo corto, su guion y, en
#: el renglón siguiente, el resto en mayúsculas.
_NOMBRE_PARTIDO = re.compile(
    r"(?<![^\W\d_])(?P<antes>[^\W\d_]{1,8})(?P<espacio>[ \t]?)[-\xad][ \t]*\n\s*(?P<despues>[A-ZÁÉÍÓÚÑ]{2,})"
)


def con_las_palabras_unidas(texto: str) -> str:
    """El texto con las palabras de título partidas entre dos renglones unidas, y sin el guion blando.

    El acta manuscrita de UPD3859802 (pág. 110, 2026-11-12) partió «ENFERMERIA»
    en «EN» y «FERMERIA», y el título se leía «ESPECIALISTAS EN EN». Sólo se
    unen si juntas son una palabra de título: «EN» / «CARTAGENA» no.
    """
    from .graduado import VOCABULARIO_DE_LOS_TITULOS

    # El nombre a máquina partido al final del renglón del formulario: «LIBARDO
    # AL-» / «VAREZ MANTILLA», «CARLOS MON -» / «SALVE PORTO», «DORIS DEL SO­» /
    # «CORRO» (1985-1986-1987 TOMO I, 2026-11-27: seis de diez nombres de la
    # muestra perdían su mitad). Con un espacio antes del guion, no si lo de
    # delante es un enlace: «DE -» / «CARTAGENA» no es una palabra.
    def unir_el_nombre(hallado: re.Match[str]) -> str:
        if hallado.group("espacio") and _plano(hallado.group("antes")) in _ENLACES_DEL_NOMBRE | {"AL", "A", "EL", "EN"}:
            return hallado.group(0)
        return hallado.group("antes") + hallado.group("despues")

    texto = _NOMBRE_PARTIDO.sub(unir_el_nombre, texto or "")
    texto = texto.replace("\xad\n", "").replace("\xad", "")
    # Y la palabra partida con guion al final del renglón: «al estu- / diante»
    # (UPD3859802 pág. 1, la franja del nombre, 2026-11-13).
    texto = re.sub(r"([a-záéíóúñ])-\s*\n\s*([a-záéíóúñ])", r"\1\2", texto)

    def unir(hallado: re.Match[str]) -> str:
        junta = _plano(hallado.group(1) + hallado.group(2))
        return hallado.group(1) + hallado.group(2) if junta in VOCABULARIO_DE_LOS_TITULOS else hallado.group(0)

    return _PARTIDA_EN_DOS_RENGLONES.sub(unir, texto)


def completar_acta(acta: ActaDeConsejo, texto: str) -> ActaDeConsejo:
    """El acta con lo que le falte leído de ``texto``; lo ya leído no se toca.

    Sirve para la primera lectura y para releer la hoja con otro motor: la
    capa del escáner, después Tesseract, después la IA si se pidió. Cada uno
    llena sólo los huecos que dejó el anterior.
    """
    texto = con_las_palabras_unidas(texto)
    hecha = constancia(texto)
    if hecha is not None:
        acta = _con_la_constancia(acta, hecha)
    leido = graduado(texto)
    del_examen, titulo_antiguo = examen_antiguo(texto)
    # El acta del Consejo Directivo de 1980: su número, su alumno y el título
    # que le acredita (1980-1984 TOMO I, 2026-11-27).
    numero_del_consejo, alumno_del_consejo, titulo_del_consejo = acta_del_consejo_directivo(texto)
    # Un acta con número es de grado, no de examen: las de examen no lo traen.
    examen = acta.examen or (None if acta.numero else examen_de_grado(texto))
    nuevo = replace(
        acta,
        # El acta de examen de Odontología sí lo trae arriba: «Acta No 132» (2026-11-27).
        numero=acta.numero or numero_del_consejo or (numero_del_examen(texto) if examen is not None else None) or leido.numero,
        fecha=acta.fecha or fecha_de_grado(texto),
        # En el acta antigua el lector moderno toma pedazos del texto corrido
        # («HICHO LO QUE ANTECEDE» por nombre): manda lo que lee el formato antiguo.
        nombre=acta.nombre or del_examen or alumno_del_consejo or leido.nombre,
        # El de un examen, completo: un preparatorio sin el ordinal no lo es.
        titulo=next(
            (
                titulo
                for titulo in (
                    titulo_del_examen(examen, otro)
                    for otro in (acta.titulo, titulo_antiguo, titulo_del_consejo, leido.titulo)
                )
                if titulo
            ),
            None,
        ),
        cedula=acta.cedula or leido.cedula,
        examen=examen,
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
            # La que comparten dos vecinas o más tampoco se corrige: donde el
            # libro vuelve a empezar -- el de preparatorios de 1945 cosido detrás
            # de los finales, que empieza en 1 (UPD3860000 pág. 163) -- a cada
            # lado hay ocho vecinas con otro desfase.
            if comun is None or propio == comun or veces < 2 or cerca.count(propio) >= 2:
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
    if acta.examen is not None:
        # El acta de examen no trae número ni cédula: pedirlos sería pagar por
        # releer cada hoja manuscrita del libro.
        return bool(acta.dudas or not all((acta.fecha, acta.nombre, acta.titulo)))
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
    "Razona antes de responder:\n"
    "- El NOMBRE es lo que sigue a «al estudiante» o «a la estudiante» y puede seguir en el renglón de abajo "
    "hasta «portador(a) de la cédula»: «al estudiante VIVIAN LOPEZ / VERHELST ---- portador» es VIVIAN LOPEZ "
    "VERHELST. El título va en otro renglón aunque el OCR lo monte encima: ninguna palabra del título "
    "(ESPECIALISTA, ENFERMERIA, MEDICO QUIRURGICA, CON ENFASIS EN…, Y RECUPERACION, NEUROCIRUGIA) es del nombre; "
    "devuélvela en TITULO. Tampoco son del nombre el «No.» ni la cédula que sigue, el lugar de expedición "
    "(«de Cartagena»), ni los nombres del pie bajo «Rector», «Decano» o «Secretario General».\n"
    "- El número puede venir como «Nº», «No.» o «#».\n"
    "- En una constancia que dice «… aparece relacionada entre otros el nombre de la estudiante X», el NOMBRE es "
    "X y el TITULO es sólo el título otorgado.\n"
    "- En una constancia que nombra a varios graduados, el nombre es el de quien la constancia señala; si no "
    "señala a ninguno, NINGUNO.\n"
    "- En un acta manuscrita de graduación colectiva, si el espacio tras «al estudiante» está vacío o con «x x», "
    "el NOMBRE es el primero de los graduados que el acta nombra (subrayado en la frase o el 1 de su lista), y "
    "la CEDULA, la suya si está escrita.\n"
    "- Si es un acta manuscrita antigua de examen («se constituyó el Consejo Examinador … con el fin de practicar "
    "el quinto examen preparatorio de grado del alumno …», o el examen final de grado), el NOMBRE es el del "
    "alumno examinado, la FECHA la del examen, y el TITULO el que se le confirió («DOCTOR EN MEDICINA Y "
    "CIRUGIA») o, si es un preparatorio, cuál («QUINTO EXAMEN PREPARATORIO DE GRADO»). Esas actas no tienen "
    "número ni cédula: NINGUNO.\n"
    "- Cada palabra y cada cifra tiene que estar escrita en el texto: no corrijas ni inventes.\n"
    "- Si un dato no está, escribe NINGUNO."
)

#: Las palabras de un título profesional: un «título» sin ninguna -- «FAIMA»,
#: «FECHA» -- es un pedazo de otro renglón.
_DEL_GRADO = re.compile(
    r"ESPECIALIST|ENFERMER|LICENCIAD|MAGISTER|MAESTR|DOCTOR|ODONTOLOG|MEDIC|BACTERIOLOG|QUIMIC|"
    r"FARMACEUT|INGENIER|ABOGAD|ADMINISTRAD|ECONOMIST|CONTADOR|PSICOLOG|TRABAJADOR|TECNOLOG|TECNIC|"
    r"NUTRICION|FONOAUDIOLOG|BIOLOG|MATEMATIC|FISIC|HISTORIADOR|FILOSOF|COMUNICADOR|ARQUITECT|"
    r"PROFESIONAL|NORMALISTA|SOCIOLOG|ANTROPOLOG|LINGUIST|ESTADISTIC|ZOOTECNIST|AGRONOM|VETERINARI|PREPARATORIO"
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
    examen = examen_de_grado(texto)
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
                # El de un examen, completo y con su última palabra bien: la IA
                # devolvía «PREPARATORIO» a secas, o «… EN MEDICINA Y GEOGRAFIA».
                titulo = titulo_del_examen(examen, " ".join(palabras))
                if titulo:
                    datos["titulo"] = titulo
        elif campo == "CEDULA":
            cifras = re.sub(r"\D", "", valor)
            if 6 <= len(cifras) <= 11 and cifras in cifras_del_texto:
                datos["cedula"] = cifras
        elif campo == "NUMERO":
            # Sólo el que sigue a «ACTA DE GRADO No.»: con el número en blanco, la
            # IA daba el de la resolución (0816) o el folio (73/V) (UPD3859808).
            # Hasta diez cifras: las actas de 2006 en adelante son «05408120»,
            # y con cuatro quedaba «0540», que el texto no confirma (2026-11-12).
            numero = re.search(r"\d{1,10}", valor)
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


# -- el nombre manuscrito, leído tres veces --------------------------------------

#: Cuánto se parecen dos lecturas de una palabra para ser la misma palabra mal leída.
PARECIDO_DE_UNA_LECTURA = 0.6


def lecturas_del_nombre(texto: str) -> tuple[str | None, str | None]:
    """Las dos veces que un acta manuscrita escribe el nombre: arriba como título, y en «del alumno …»."""
    plano = _sin_cortes(_plano(texto))
    del_texto = None
    for marca in _EL_EXAMINADO.finditer(plano):
        del_texto = _nombre_tras(plano[marca.end() :])
        if del_texto:
            break
    return _nombre_de_arriba(texto), del_texto


def nombre_de_tres_lecturas(
    arriba: str | None, del_texto: str | None, ampliado: str | None, conocidas: Collection[str] = ()
) -> tuple[str | None, str | None]:
    """El nombre que confirman las lecturas de un acta manuscrita, y por qué revisarlo si no lo confirman.

    Palabra por palabra, la del renglón ampliado vale por dos -- se lee sola y
    más grande -- y las de la página, una cada una. Una palabra queda si suma
    más que las demás grafías; en empate, la que está en la lista de nombres
    conocidos, y si ninguna lo está, la de arriba, y el nombre va a revisión con
    las tres lecturas: «Espiulla», «Espinella» o Espriella (UPD3860000, 1925)
    no lo decide nadie sin el papel delante. Lo que no se confirma no se da
    por seguro.
    """
    base = _nombre_confirmado(arriba, del_texto) or ampliado
    if not base:
        return None, None
    lecturas = [(arriba, 1.0), (del_texto, 1.0), (ampliado, 2.0)]
    elegidas: list[str] = []
    dudosas: list[str] = []
    for palabra in base.split():
        votos: dict[str, float] = {}
        for lectura, peso in lecturas:
            if not lectura:
                continue
            parecida = max(
                lectura.split(), key=lambda otra: difflib.SequenceMatcher(None, palabra, otra).ratio(), default=None
            )
            # En las de dos letras -- «Mª», leída «ME» o «MA» -- basta la primera.
            if parecida and (
                difflib.SequenceMatcher(None, palabra, parecida).ratio() >= PARECIDO_DE_UNA_LECTURA
                or (len(palabra) <= 2 and len(parecida) <= 2 and palabra[0] == parecida[0])
            ):
                votos[parecida] = votos.get(parecida, 0.0) + peso
        if not votos:
            elegidas.append(palabra)
            continue
        maximo = max(votos.values())
        empatadas = [grafia for grafia, peso in votos.items() if peso == maximo]
        if len(empatadas) == 1:
            elegidas.append(empatadas[0])
            continue
        conocida = [grafia for grafia in empatadas if grafia in conocidas]
        if len(conocida) == 1:
            elegidas.append(conocida[0])
            continue
        elegidas.append(palabra)
        dudosas.append("/".join(sorted(empatadas)))
    nombre = " ".join(elegidas)
    if not dudosas:
        return nombre, None
    leidas = "; ".join(
        f"{donde}: {lectura}"
        for donde, lectura in (("arriba", arriba), ("en el texto", del_texto), ("ampliado", ampliado))
        if lectura
    )
    return nombre, (
        f"nombre por confirmar en el papel ({', '.join(dudosas)}): la letra a mano se leyó distinto — {leidas}"
    )


# -- el libro de actas colectivas manuscrito ---------------------------------------
#
# Odontología, UPD3859802 (2026-11-12): un libro a mano de 1983 a 2012 en que
# cada acta gradúa a una promoción entera -- «Acta de Grado Nº 01» con la lista
# de sus 31 graduados debajo, «Acta de Grado Nº 05408120 a 05408124» --, y la
# siguiente empieza a mitad de la hoja en que acaba la anterior. La capa del
# escáner es basura: sólo vale lo que la IA leyó de cada hoja. El operador
# eligió un PDF por acta y una fila del FUID por graduado.


def _por_letra(texto: str) -> str:
    """El texto en mayúsculas y sin tildes, letra por letra: cada posición es la misma que en el original.

    Para cortar el texto de un acta donde empieza la siguiente hace falta la
    posición en el texto de la IA, y `_plano` junta los blancos. Lo que tras
    quitarle la tilde no es una letra ASCII -- «º», «°» -- queda en blanco.
    """
    salida = []
    for letra in texto:
        base = unicodedata.normalize("NFD", letra)[:1]
        salida.append(base.upper() if base.isascii() else " ")
    return "".join(salida)


#: «se llevó a cabo la graduación Colectiva», «ceremonia solemne de graduación
#: colectiva», «la graduación colectera» (la IA con la letra de 1983).
_GRADUACION_COLECTIVA = re.compile(r"GRADUACI\w{1,3}\W+(?:DE\W+)?COLECT\w{2,4}\b")
#: El encabezado de un acta del libro: «Acta de Grado Nº 01», «Acta Nº 1»,
#: «Acta de Grado #03», «Acta de Grado Nº» con el número en el renglón de abajo,
#: y como lo transcribe la IA la letra a mano: «# Acta 02.», «Acto N°02»,
#: «Acta de Prado Nº», «Acta de Acdo Nº» (UPD3859802, 2026-11-13: sin «Nº» el
#: encabezado no se veía, y el número del acta salía de «Resolución Nº 1813»).
_ENCABEZADO_DEL_LIBRO = re.compile(
    r"\bACT[AO]\W{1,3}DE\W{1,3}(?:[GCOP][RH]ADO|GRAD0|ACDO)\b|\bACT[AO]?(?=\W{0,3}(?:N[O0]?(?![A-Z])|#|\d))"
)
#: Las cifras de un número del encabezado, con los puntos y las barras que les
#: pone la IA: «12.008.001.», «05409.169», «054/11254».
_CIFRAS_DEL_NUMERO = r"\d(?:\d|[./](?=\d))*"
_NUMERO_DEL_ENCABEZADO = re.compile(rf"\W{{0,4}}(?:(?:N[O0]?(?![A-Z])\.?|#)\W{{0,4}})?(?P<numero>{_CIFRAS_DEL_NUMERO})")
#: «… Nº 05408120 a 05408124», «05412351 - 05412353», «054/1289-a 054/1320»,
#: «2007001, 2007002»: el rango de los números de la promoción. El separador es
#: obligatorio: el «7» suelto debajo de «Acta N° 04» es el folio de la hoja.
_RANGO_DEL_ENCABEZADO = re.compile(
    rf"\s*(?:[-,]\W{{0,2}}(?:A\b|AL\b)?|(?:A|AL|HASTA|Y)\b)\W{{0,3}}(?P<hasta>{_CIFRAS_DEL_NUMERO})"
)
#: Lo que sigue a «Acta No 02 - 26» cuando el 26 es el día de una fecha: «de mayo 1989».
_DIA_DE_UNA_FECHA = re.compile(r"\W{0,3}DE\W+[A-Z]{3,}")
#: El encabezado de un acta abreviada -- la complementaria de la misma ceremonia,
#: sin «En la ciudad de …» --: debajo, el título o la lista. «Acto 04 /
#: Especialista en: Salud Familiar / 1. Pérez Tobias Shirley Margarita», al pie
#: de la hoja 150 de UPD3859802, iba como cola del Acta 03.
_DEBAJO_DEL_ABREVIADO = re.compile(
    r"^\W{0,6}(?:ESPECIALIST|ENFERMER|COMPLEMENTARI|LICENCIAD|CON\W+E\w{0,2}FAS|\d{1,3}\W{1,3}[A-Z]{3,})"
)
#: Lo que puede ir delante del encabezado en su renglón: «# », «Complementario».
_DELANTE_DEL_ABREVIADO = re.compile(r"\W{0,6}(?:[A-Z]{6,14}\W{1,3})?")
#: Lo que dice que el renglón no abre un acta sino que la nombra: una fecha -- el
#: «Acta No 02 - 26 de mayo 1989» arriba de la hoja en que sigue su lista (hoja
#: 4) -- o un año -- «(repite acta N° 03) Resolución 3047 de 14 Dic/2000» --.
_FECHA_EN_EL_RENGLON = re.compile(
    r"\b(?:19|20)\d\d\b|\bDE\W+(?:ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|SEPTIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE)\b"
)
#: Cuántas letras puede llevar el renglón del encabezado detrás del número para
#: ser un encabezado y no una frase: «Acta 01 de 1990», «Acta No. 01 Postgrado».
LETRAS_DETRAS_DEL_ENCABEZADO = 25
#: Donde empieza el cuerpo de un acta: «En la ciudad de Cartagena a los…», también
#: como lo lee la IA en la letra a mano: «cuidad», «Con la ciudad», «En la unidad»
#: (UPD3859802, hojas 3, 6 y 175: el Acta 05408125 a 05408149 se soldaba a la de
#: arriba porque su cuerpo no se reconocía; 2026-11-13).
_CUERPO_DEL_LIBRO = re.compile(r"\b(?:EN|CON)\W{1,3}LA\W{1,3}[CU]\w{3,5}D\W{1,3}DE\W{1,3}[A-Z]{4,}")
#: Lo que sigue a ese comienzo en un acta, y no en «expedida en la ciudad de…»:
#: el día y el mes, o el año.
_DIA_DEL_CUERPO = re.compile(r"D\w{0,2}AS?\W+DEL\W+MES|\b(?:19|20)\d\d\b|\b1\W?9\d\d\b|NOVECIENTOS|DOS\W+MIL")
#: Cuánto antes del cuerpo se busca su encabezado.
VENTANA_DEL_ENCABEZADO = 250
#: Cuántas letras puede haber en una hoja antes del cuerpo para que el
#: encabezado al pie de la anterior sea suyo: el folio y la «80/V» no cuentan.
LETRAS_DE_LA_CABEZA = 40
#: Cuántas letras de la cola del acta anterior hacen falta en la hoja para decir
#: que su cierre -- la lista, las firmas -- quedó en ella.
LETRAS_DE_UN_CIERRE = 20
#: «al estudiante x x x portador», «al estudiante _______, portador», «al
#: estudiante ……. portador»: el formulario sin el nombre, porque son varios.
_ESTUDIANTE_EN_BLANCO = re.compile(
    r"\bESTUDIANTE\W{0,3}(?:(?:X\W{0,3}){2,}|[\\_.\-]{3,}[\s\\_.,\-]*)\W{0,3}PORTA"
)
#: «… el título de Especialista a - - - - - Portador», «a ……… portador(a)»: el
#: graduado en blanco sin la palabra «estudiante».
_GRADUADO_EN_BLANCO = re.compile(r"\bA\W{0,3}(?:[\\_.\-]\W{0,2}){3,}\W{0,3}PORTA")
#: «a los siguientes estudiantes», «a las estudiantes»: la frase que nombra a varios.
_A_LOS_ESTUDIANTES = re.compile(r"\bA\W+L[AO]S\W+(?:SIGUIENTES\W+)?ESTUDIANTES\b")
#: Un renglón de la lista de graduados: «1. Karolay Acevedo Jiménez 45.521.842
#: Cartagena», «31. Ramos Caballero Edgardo Javier CC Nº 1.128.049.264 de
#: Cartagena», «2- Nafkay Ahumada Romero».
#: También con el número corregido al lado -- «5 6 Barrios Huerta Lorayda» -- y
#: con «º», «ª» o «-» detrás: «8º Martinez Ramos Efren», «32-34 Edith …».
_RENGLON_NUMERADO = re.compile(
    r"^\W{0,4}(?P<orden>\d{1,3})(?:\s*[.)\-–:ºª°]\s*|\s+)(?:\d{1,3}\W{1,3})?(?P<resto>[^\W\d_].*)$"
)
#: Un renglón numerado, tenga lo que tenga detrás: el «2.» de una lista en
#: blanco o el renglón que la IA no supo leer también es un puesto de la lista.
_PUESTO_DE_LA_LISTA = re.compile(r"^\W{0,4}(?P<orden>\d{1,3})(?:\s*[.)\-–:ºª°]|\s*$|\s+\S)")
#: Un renglón de la lista sin número: con viñeta -- «- Orieta Narvaez Stella
#: del Socorro cc 45.478.083 de Cartagena (Bol)» -- o el nombre solo bajo el
#: título de su sección, con la cédula en el renglón de abajo (UPD3859802, hoja
#: 25: el Acta 04 de 1996 nombra así a sus siete graduados; 2026-11-13).
_RENGLON_SIN_NUMERO = re.compile(r"^(?P<vineta>[-–•·]\s*)?(?P<resto>[^\W\d_].*)$")
#: La cédula con su rótulo delante: «cc 45.478.083», «C.C. Nº 32.732.022».
_CEDULA_CON_ROTULO = re.compile(r"\bC\W{0,2}[CE]\W{0,3}(?:N[O0]?\W{0,3})?\d")
#: La inicial con su punto y el resto de la palabra en minúscula: «Niño O. sario»
#: es Osorio partido por la IA (UPD3859802, hoja 35). Nunca delante de «de», «la»…
_INICIAL_PARTIDA = re.compile(r"\b([A-ZÁÉÍÓÚÑ])\.\s?(?!(?:de|del|la|las|los|y)\b)([a-záéíóúñ]{2,})")
#: La marca de chequeo detrás del nombre: «Niño Osorio /ect», «… ✓».
_VISTO_AL_FINAL = re.compile(r"\s*/\s*[A-Za-z]{0,4}\W*$")
#: Una cédula: grupos de tres cifras con su separador -- «45.521.842»,
#: «45 525 926», «1'101.384.349», «1/143.332.238», «45:409.979», «1. 129.516.130»
#: -- o las cifras seguidas. «22.844.285-6» es la 22.844.285.
#: También con un solo punto -- «9.177901», «45.517404», «45525.602» -- como
#: la IA transcribe la letra a mano: la regla se quedaba con las cifras de
#: detrás del punto (UPD3859802, hoja 142; 2026-11-13).
_CIFRAS_DE_LA_CEDULA = (
    r"(?:\d{1,3}[.,'’´]\s?\d{6}(?!\d)|\d{4,5}[.,'’´]\d{3}(?!\d)"
    r"|\d{1,4}(?:(?:[.,'’´:/]\s?|\s)\d{3}(?!\d)){1,3}|\d{6,10}(?!\d))"
)
_CEDULA_DEL_RENGLON = re.compile(rf"(?<!\d){_CIFRAS_DE_LA_CEDULA}")
_PALABRA_DEL_RENGLON = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
#: Lo que puede ir entre el nombre y la cédula y no es del nombre: «C.C.»,
#: «c.e» (como transcribe la IA la «c.c» a mano), «cc#», «CCN°».
_NO_ES_DEL_NOMBRE_EN_LA_LISTA = {
    "C", "CC", "CE", "E", "N", "NO", "CCN", "DE", "DEL", "CEDULA", "CIUDADANIA", "CON", "T", "I", "TI",
}
#: El renglón que abre la lista sin números de las actas de 1980: «Las
#: graduandas son:» (UPD3859802, hoja 60; 2026-11-13).
_ABRE_LA_LISTA = re.compile(r"\b(?:GRADUAND|GRADUAD|ESTUDIANTE)\w*\W+SON\W*$")
#: La cédula empezada al final del renglón del nombre, que sigue en el de abajo:
#: «Guadalupe Yáñez Parada con C.C. #34» / «325.259 de Cuenta» es la 34.325.259.
#: «Carmen Teresa Perez Bohanquez con T.I.», «… con C.C. #34»: el nombre dice
#: que su documento va detrás.
_CON_SU_DOCUMENTO = re.compile(r"\bCON\W+(?:C\W?C|T\W?I)\b")
_CEDULA_EMPEZADA = re.compile(r"\bC\W{0,2}C\W{0,3}(?:N[O0]?\W{0,3})?(?P<cifras>\d{1,3})\W*$")
#: Un renglón que sólo trae una cédula -- debajo del nombre, «cc. 32.732.022 de
#: Baranquilla (Atl).», o en la columna aparte, «1. 129.516.130 de Banonguilla»
#: --, sin nombre delante.
_RENGLON_DE_LA_CEDULA = re.compile(
    rf"^\W{{0,4}}(?:(?:C\W{{0,2}}[CE]|CEDULA)\W{{0,3}}(?:N[O0]?\W{{0,3}})?)?(?P<cedula>{_CIFRAS_DE_LA_CEDULA})"
    r"(?:\W.{0,40})?$"
)
#: La marca a lápiz del graduado que no se presentó: «no aparece», y como la lee
#: la IA, «no apmuel», «no apnce» (UPD3859802, 2026-11-13).
_NO_APARECE = re.compile(r"\bNO\W{1,3}AP\w{0,7}\W*$")
NOTA_NO_APARECE = "marcado a lápiz: no aparece"
#: Palabras que no van en el nombre de un graduado: es el orden del día de la
#: ceremonia («1º: Himno de Colombia», «4º: Toma de juramento», hoja 68), que
#: también va numerado, o el pie.
#: También como lo transcribe la IA a mano: «1º Apertura de la sesión», «1º
#: Número a Colombia» (el Himno), hojas 61 y 64 (2026-11-13).
_NO_ES_UN_GRADUADO = re.compile(
    r"\b(?:HIMNO|LECTURA|MOCION|JURAMENTO|DIPLOMAS?|RESOLUCION|ENTREGA|APERTURA|SESION|PALABRAS|DISCURSO"
    r"|INSTALACION|CLAUSURA|BIENVENIDA|INVOCACION|ORACION|FELICITACION|NUMERO\W+A\W+(?:COLOMBIA|CARTAGENA))\b"
)
#: Los títulos dentro de la lista: «Con Énfasis en Neurocirugía», «# ESPECIALISTA
#: EN MEDICO QUIRURGICA», «# COMPLEMENTARIO DE ENFERMERIA» (hoja 16).
_ENFASIS_DE_LA_LISTA = re.compile(r"^\W{0,6}(?:\d{1,3}\W+)?(?:CON\W+)?E\w{0,2}FAS\w{1,3}\W+(?:EN\W+)?(?P<enfasis>[A-Z][A-Z ]{3,60}?)\W*$")
_ESPECIALIDAD_DE_LA_LISTA = re.compile(r"^\W{0,6}(?P<titulo>(?:ESPECIALISTAS?|COMPLEMENTARIO)\b[A-Z :]{0,70}?)\W*$")
#: El acta que dice cuántos gradúa: «se graduaron cuarenta y ocho (48) estudiantes».
_ESTUDIANTES_DECLARADOS = re.compile(r"\(?\s*(\d{1,3})\s*\)?\s+(?:ESTUDIANTES|ALUMN[AO]S|SENORITAS|GRADUAND[AO]S)\b")
#: El acta anulada: «Anulado», «se anula la presente acta».
_ANULADA = re.compile(r"\bANULAD[AO]\b|\bSE\W+ANULA\b")
#: Cuántos puestos en blanco hacen una lista vacía: la del acta anulada (hojas 144-145).
PUESTOS_DE_UNA_LISTA_EN_BLANCO = 5
_CONECTORES_DEL_NOMBRE = {"DE", "DEL", "LA", "LAS", "LOS", "Y"}
PALABRAS_DE_UN_GRADUADO = 7
#: Cuántas hojas del libro tienen que traer la marca de una graduación
#: colectiva con varios graduados para tratarlo como libro colectivo.
HOJAS_DE_UN_LIBRO_COLECTIVO = 2


@dataclass(frozen=True, slots=True)
class GraduadoDelActa:
    """Un graduado de un acta colectiva: su puesto en la lista, su nombre, su cédula y su título."""

    orden: int
    nombre: str | None
    cedula: str | None = None
    #: El suyo si el acta le da uno distinto al común; ``None`` si es el común.
    #: «CON ENFASIS EN NEUROCIRUGIA» se le pone detrás al común.
    titulo: str | None = None
    #: Lo que hay que mirar en el papel de este graduado.
    nota: str | None = None
    #: Su puesto en el texto, de 1 en adelante: la lista vuelve a contar desde
    #: el 1 en cada título («Complementario: 1. …», «Con énfasis en …: 1. …»).
    puesto: int = 0


@dataclass(frozen=True, slots=True)
class ActaDelLibro:
    """Un tramo del libro colectivo: un acta -- con su texto y su cierre -- o las hojas de una ceremonia."""

    #: Su primera y su última hoja del PDF, en el orden del libro.
    desde: int
    hasta: int
    #: El texto del acta, desde su encabezado hasta donde empieza la siguiente:
    #: la cola de la anterior que va en su primera hoja no es suya.
    texto: str = ""
    #: La hoja en que acaba su lista o sus firmas y empieza la siguiente acta:
    #: va en los dos PDF (lo decidió el operador el 2026-11-13) y cuenta en el
    #: de la que empieza en ella.
    cierre: int | None = None
    ceremonia: bool = False
    #: Sus hojas del PDF en el orden del folio impreso, con la del cierre: «(98,
    #: 2)» es el Acta 01 de 1988, que empieza en la hoja 98 y sigue en la 2.
    hojas: tuple[int, ...] = ()
    #: Lo que el reparto razonó y hay que mirar en el papel: el encabezado que
    #: quedó en blanco al pie de su hoja, la portada que va delante.
    notas: tuple[str, ...] = ()

    @property
    def en_el_pdf(self) -> tuple[int, ...]:
        """Sus hojas en el orden en que van en su PDF."""
        return self.hojas or tuple(range(self.desde, self.hasta + 1))


@dataclass(frozen=True, slots=True)
class _Comienzo:
    #: Dónde empieza el acta en la hoja: su encabezado, o su cuerpo si no se lee.
    inicio: int
    #: Dónde empieza y acaba «En la ciudad de …».
    cuerpo: int
    fin_del_cuerpo: int
    #: Si es un acta abreviada, sin cuerpo: el encabezado y debajo el título o la lista.
    abreviada: bool = False


def _comienzos(texto: str) -> list[_Comienzo]:
    """Dónde empieza cada acta en el texto de una hoja: su encabezado y su cuerpo.

    Cada acta del libro abre con «En la ciudad de Cartagena a los … días del
    mes de …», y su encabezado -- «Acta de Grado Nº 02» -- va justo encima. Lo
    que hay antes en la hoja es la cola de la anterior: su lista, sus firmas.
    La complementaria de la misma ceremonia va abreviada: su encabezado al
    principio del renglón y debajo el título o la lista (``_abreviadas``).
    """
    letras = _por_letra(texto)
    hallados: list[_Comienzo] = []
    anterior = 0
    for cuerpo in _CUERPO_DEL_LIBRO.finditer(letras):
        if "EXPEDID" in letras[max(0, cuerpo.start() - 30) : cuerpo.start()]:
            continue
        if not _DIA_DEL_CUERPO.search(letras, cuerpo.end(), cuerpo.end() + 250):
            continue
        desde = max(anterior, cuerpo.start() - VENTANA_DEL_ENCABEZADO)
        encabezados = list(_ENCABEZADO_DEL_LIBRO.finditer(letras, desde, cuerpo.start()))
        inicio = encabezados[-1].start() if encabezados else cuerpo.start()
        hallados.append(_Comienzo(inicio, cuerpo.start(), cuerpo.end()))
        anterior = cuerpo.end()
    hallados += _abreviadas(letras, hallados)
    return sorted(hallados, key=lambda comienzo: comienzo.inicio)


def _abreviadas(letras: str, con_cuerpo: Sequence[_Comienzo]) -> list[_Comienzo]:
    """Las actas abreviadas de la hoja: el encabezado con su número al principio del renglón y, debajo, el título o la lista.

    La complementaria de una ceremonia no repite «En la ciudad de …»: «Acto 04
    / Especialista en: Salud Familiar / 1. Pérez Tobias Shirley Margarita» al
    pie de la hoja 150 de UPD3859802, «ACTA 04. / Especialista en Salud
    Ocupacional» en la 136 (2026-11-13). Sin esto su graduada se contaba en la
    lista del acta de arriba, con su número y su título.
    """
    abreviadas: list[_Comienzo] = []
    for encabezado in _ENCABEZADO_DEL_LIBRO.finditer(letras):
        if any(c.inicio <= encabezado.start() <= c.cuerpo for c in con_cuerpo):
            continue
        principio = letras.rfind("\n", 0, encabezado.start()) + 1
        if not _DELANTE_DEL_ABREVIADO.fullmatch(letras, principio, encabezado.start()):
            continue
        numero = _NUMERO_DEL_ENCABEZADO.match(letras, encabezado.end())
        if numero is None:
            continue
        fin = letras.find("\n", numero.end())
        fin = len(letras) if fin < 0 else fin
        detras = letras[numero.end() : fin]
        if len(re.sub(r"[^A-Z]", "", detras)) > LETRAS_DETRAS_DEL_ENCABEZADO or _FECHA_EN_EL_RENGLON.search(detras):
            continue
        debajo = [renglon for renglon in letras[fin:].splitlines() if renglon.strip()][:3]
        if any(_DEBAJO_DEL_ABREVIADO.match(renglon) for renglon in debajo):
            abreviadas.append(_Comienzo(encabezado.start(), encabezado.start(), fin, abreviada=True))
    return abreviadas


def _encabezado_al_pie(texto: str, desde: int) -> int | None:
    """El encabezado que cierra la hoja sin su cuerpo -- que va arriba de la siguiente --, o ``None``."""
    letras = _por_letra(texto)
    encabezados = [m for m in _ENCABEZADO_DEL_LIBRO.finditer(letras) if m.start() >= desde]
    if not encabezados:
        return None
    detras = re.sub(r"[^A-Z]", "", letras[encabezados[-1].end() :])
    return encabezados[-1].start() if len(detras) <= LETRAS_DE_LA_CABEZA else None


def numero_y_rango(texto: str) -> tuple[str | None, str | None]:
    """El número del acta y el último de su rango, de su encabezado: («05408120», «05408124»), («03», None).

    El primer encabezado del texto, que en el de un acta cortada es el suyo.
    Las cifras van juntas aunque la IA les ponga puntos o barras --
    «054/11254» es 05411254, «12.008.001.» es 12008001 --: con la barra el
    rango salía «054 A 054» (UPD3859802, 2026-11-13). Lo que la IA dejó corto
    lo completa ``rango_reparado`` con la lista y la serie del libro.
    """
    letras = _por_letra(texto)
    encabezado = _ENCABEZADO_DEL_LIBRO.search(letras)
    if encabezado is None:
        return None, None
    numero = _NUMERO_DEL_ENCABEZADO.match(letras, encabezado.end())
    if numero is None:
        return None, None
    desde = re.sub(r"\D", "", numero.group("numero"))
    # Ningún acta es la cero: un «0» suelto es una cifra que la IA cortó.
    if not desde.strip("0"):
        return None, None
    rango = _RANGO_DEL_ENCABEZADO.match(letras, numero.end())
    if rango is None or _DIA_DE_UNA_FECHA.match(letras, rango.end()):
        return desde, None
    hasta = re.sub(r"\D", "", rango.group("hasta"))
    return desde, hasta if hasta.strip("0") else None


#: Cuántas cifras del final tienen que coincidir para completar con la lista
#: o con la serie un número del rango que la IA dejó corto.
CIFRAS_QUE_CASAN = 3


def rango_reparado(
    desde: str | None, hasta: str | None, cuantos: int, sigue_a: str | None = None
) -> tuple[str | None, str | None, str | None]:
    """El rango del acta con lo que la IA leyó mal arreglado por la lista y la serie: (desde, hasta, nota).

    En UPD3859802 (2026-11-13) la IA leyó «054/11254 a 054/1288» (35
    graduados), «05403125 a 05408149» (25) y «054/1289-a 054/1320»: una cifra
    de menos o una cambiada. Lo arregla lo que el libro sabe -- cuántos nombra
    la lista y dónde acabó el acta anterior (``sigue_a``) -- y sólo si las
    últimas cifras casan; lo arreglado se dice en la nota. Sin con qué
    arreglarlo, el rango se queda como se leyó.
    """
    if not desde or not desde.isdigit() or cuantos < 1:
        return desde, hasta, None
    largo = max(len(desde), len(hasta or ""), len(sigue_a or ""))

    def casa(leido: str | None, deducido: int) -> bool:
        return bool(leido) and str(deducido).zfill(largo)[-CIFRAS_QUE_CASAN:] == leido[-CIFRAS_QUE_CASAN:]  # type: ignore[index]

    if hasta and hasta.isdigit() and len(desde) == len(hasta) == largo and int(hasta) - int(desde) + 1 == cuantos:
        return desde, hasta, None
    leido = f"{desde} A {hasta}" if hasta else desde
    if sigue_a and sigue_a.isdigit() and casa(desde, int(sigue_a) + 1):
        nuevo = str(int(sigue_a) + 1).zfill(largo)
        nuevo_hasta = str(int(nuevo) + cuantos - 1).zfill(largo)
        if hasta is None or casa(hasta, int(nuevo_hasta)):
            nuevo_hasta = nuevo_hasta if hasta is not None or cuantos > 1 else None
            if (nuevo, nuevo_hasta) != (desde, hasta):
                return nuevo, nuevo_hasta, (
                    f"el encabezado se leyó «{leido}»; el número sigue al del acta anterior y la lista nombra "
                    f"{cuantos}: revíselo en el papel"
                )
            return desde, hasta, None
    if hasta and hasta.isdigit() and len(desde) == largo and casa(hasta, int(desde) + cuantos - 1):
        return desde, str(int(desde) + cuantos - 1).zfill(largo), (
            f"el encabezado se leyó «{leido}» y la lista nombra {cuantos}: revíselo en el papel"
        )
    if hasta and hasta.isdigit() and len(hasta) == largo and casa(desde, int(hasta) - cuantos + 1):
        return str(int(hasta) - cuantos + 1).zfill(largo), hasta, (
            f"el encabezado se leyó «{leido}» y la lista nombra {cuantos}: revíselo en el papel"
        )
    return desde, hasta, None


def cedula_valida(cifras: str | None) -> str | None:
    """La cédula si su largo es de una cédula colombiana: de 6 a 8 cifras, o 10 que empiezan por 10 u 11.

    En UPD3859802 (2026-11-13) la IA dejó «228442856» (la 22.844.285 con la
    cifra de control) y «129516130» (la 1.129.516.130 sin el 1, de otra
    graduada): de nueve cifras no hay ninguna.
    """
    if not cifras or not cifras.isdigit():
        return None
    if 6 <= len(cifras) <= 8 or (len(cifras) == 10 and cifras[:2] in ("10", "11")):
        return cifras
    return None


def _nombre_del_renglon(resto: str) -> tuple[list[str], str | None]:
    """Las palabras del nombre de un renglón de la lista y su nota a lápiz, sin la cédula ni lo que la sigue."""
    nota = None
    marca = _NO_APARECE.search(_plano(resto))
    if marca is not None:
        nota = NOTA_NO_APARECE
        resto = resto[: marca.start()]
    entre_parentesis = re.search(r"\(([^)]{6,80})\)", resto)
    if entre_parentesis is not None and re.search(r"\bNO\b", _plano(entre_parentesis.group(1))):
        # «Hernandez Uperla Mª Elena (no se ha graduado ni legalizó acta)».
        nota = f"anotado en el papel: «{entre_parentesis.group(1).strip()}»"
        resto = resto[: entre_parentesis.start()]
    cedula = _CEDULA_DEL_RENGLON.search(resto)
    antes = resto[: cedula.start()] if cedula else resto
    anotado = re.search(r"\(([^)]{6,80})\)", antes)
    if anotado is not None and len(_PALABRA_DEL_RENGLON.findall(antes[: anotado.start()])) >= 2:
        # Lo anotado entre paréntesis delante de la cédula no es del nombre:
        # «Calvo Martinez Susana (hoy Señora de Ortiz)» (hoja 25).
        nota = _con_nota(nota, f"anotado en el papel: «{anotado.group(1).strip()}»")
        resto = resto[: anotado.start()] + " " + resto[anotado.end() :]
        cedula = _CEDULA_DEL_RENGLON.search(resto)
    resto = _INICIAL_PARTIDA.sub(r"\1\2", resto)
    if cedula is None:
        resto = _VISTO_AL_FINAL.sub("", resto)
    cedula = _CEDULA_DEL_RENGLON.search(resto)
    # El nombre acaba en la primera palabra con cifras: la cédula mal leída
    # «4N-434 3N6 9pm» le pegaba «N N PM» (hoja 64).
    con_cifras = re.search(r"\S*\d", resto)
    fin = min(cedula.start() if cedula else len(resto), con_cifras.start() if con_cifras else len(resto))
    palabras = _PALABRA_DEL_RENGLON.findall(resto[:fin])
    while palabras and _plano(palabras[-1]).strip() in _NO_ES_DEL_NOMBRE_EN_LA_LISTA:
        palabras.pop()
    if (
        cedula is None
        and nota is None
        and len(palabras) >= 4
        and palabras[-2].lower() == "de"
        and _plano(palabras[-1]).strip() in LUGARES_DE_EXPEDICION
    ):
        # Sin cédula, el lugar de expedición va pegado al apellido: «…
        # Andrade García de Cartagena». Sólo un lugar: «Lorica Phillips de
        # Porras» y «Zully Moreno de Villalba» son apellidos de casada (hojas
        # 60 y 80, 2026-11-13); «Ana María de la Hoz», un nombre.
        palabras = palabras[:-2]
    return palabras, nota


def _es_un_nombre(palabras: Sequence[str], *, con_cedula: bool = False) -> bool:
    """Si las palabras tienen forma de nombre: de dos a siete, y a lo más una en minúscula que no sea «de», «la»…

    La IA escribe a veces un apellido en minúscula -- «11. Cabrera florez Iris
    del Socorro» --; un renglón del cuerpo que empieza por un número -- «30 de
    Junio de 2006 por medio…», «14 días del mes de julio» -- trae varias.
    """
    if not 2 <= len(palabras) <= PALABRAS_DE_UN_GRADUADO:
        return False
    planas = [_plano(palabra).strip() for palabra in palabras]
    # Dos palabras de nombre por lo menos: «93-880 de Catania» es una cédula
    # partida con su lugar de expedición, no «DE CATANIA» (hoja 60).
    if sum(1 for plana in planas if plana not in _CONECTORES_DEL_NOMBRE) < 2:
        return False
    if any(_CARGO_EN_PALABRA.search(p) for p in planas) or _NO_ES_UN_GRADUADO.search(" ".join(planas)):
        return False
    minusculas = [
        indice
        for indice, (palabra, plana) in enumerate(zip(palabras, planas, strict=True))
        if not palabra[:1].isupper() and plana not in _CONECTORES_DEL_NOMBRE
    ]
    if con_cedula:
        # Con su cédula en el renglón es un graduado aunque la IA le pase la
        # «C» a «b»: «8 bostillo bostillo fruity. 3len 45.422.357» (hoja 74,
        # 2026-11-13). El nombre va como se leyó y lo vota la lectura de la IA.
        return len(minusculas) * 2 <= len(palabras)
    # «10 de la Rosa Sougoly Betty»: la mayúscula, en la primera que no es «de», «la».
    primeras = [palabra for palabra, plana in zip(palabras, planas, strict=True) if plana not in _CONECTORES_DEL_NOMBRE]
    return len(minusculas) <= 1 and (primeras[0][:1].isupper() or primeras[1][:1].isupper())


def graduados_de_la_lista(texto: str) -> list[GraduadoDelActa]:
    """Los graduados de la lista numerada del acta, leídos por regla: «1. Karolay Acevedo Jiménez 45.521.842 Cartagena».

    Es la lectura gratuita: sirve cuando no hay IA, para completar lo que el
    lector de la IA dejó sin escribir y para casar cada cédula con su nombre.
    Un renglón vale si lo que va entre el número y la cédula tiene forma de
    nombre (``_es_un_nombre``); el lugar de expedición que sigue a la cédula no
    es del nombre.

    La cédula es la de su renglón, nunca la de otro (UPD3859802, 2026-11-13:
    la IA las casaba por orden de aparición, y una que faltaba corría todas
    las de detrás). Cuando va sola en el renglón de abajo -- «cc. 32.732.022
    de Baranquilla» -- es del nombre de arriba; cuando la IA transcribió la
    columna de las cédulas aparte, debajo de la de los nombres, se casan por
    su puesto sólo si hay tantas como nombres sin cédula. El graduado marcado a
    lápiz «no aparece» se lista con su nota, y los títulos dentro de la lista
    -- «Con Énfasis en Neurocirugía», «Especialista en Médico Quirúrgica» --
    van con los graduados que los siguen.
    """
    graduados: list[GraduadoDelActa] = []
    vistos: set[tuple[int, str]] = set()
    especialidad: str | None = None
    enfasis: str | None = None
    #: Los graduados sin cédula desde la última que se puso, y las cédulas solas seguidas.
    pendientes: list[int] = []
    columna: list[str] = []
    #: Las cifras de la cédula que el renglón del nombre dejó empezadas.
    empezadas: dict[int, str] = {}
    lista_abierta = False

    def poner(indice: int, cifras: str) -> None:
        graduados[indice] = replace(graduados[indice], cedula=cedula_valida(empezadas.pop(indice, "") + cifras))

    def cerrar_la_columna() -> None:
        if len(columna) == 1 and pendientes and pendientes[-1] == len(graduados) - 1:
            poner(pendientes[-1], columna[0])
            pendientes.clear()
        elif len(columna) >= 2 and len(columna) == len(pendientes):
            for indice, cifras in zip(pendientes, columna, strict=True):
                poner(indice, cifras)
            pendientes.clear()
        elif len(columna) >= 2 and pendientes:
            for indice in pendientes:
                graduados[indice] = replace(
                    graduados[indice],
                    nota=_con_nota(
                        graduados[indice].nota,
                        f"las cédulas van en una columna aparte y no cuadran con los nombres ({len(columna)} "
                        f"cédulas, {len(pendientes)} nombres): revísela en el papel",
                    ),
                )
            pendientes.clear()
        columna.clear()

    renglones = [renglon.replace("|", " ").replace("\\", "").replace("*", "").strip() for renglon in (texto or "").splitlines()]
    renglones = [renglon for renglon in renglones if renglon]
    for indice_del_renglon, limpio in enumerate(renglones):
        plano = _plano(limpio).strip()
        sola = _RENGLON_DE_LA_CEDULA.match(plano)
        if sola is not None:
            columna.append(re.sub(r"\D", "", sola.group("cedula")))
            continue
        cerrar_la_columna()
        if _ABRE_LA_LISTA.search(plano):
            lista_abierta = True
            continue
        # El título de una sección de la lista, aunque lleve número delante:
        # «* 5 Con Enfásis en Cuidados Intensivos:» no es un graduado (hoja 3).
        if seccion := _ENFASIS_DE_LA_LISTA.match(plano):
            enfasis = seccion.group("enfasis").strip()
            continue
        seccion = _ESPECIALIDAD_DE_LA_LISTA.match(plano)
        # Delante del primer graduado, el título de la sección también vale
        # («Especialistas en Salud Ocupacional», hoja 25), pero no el renglón
        # del cuerpo que lo otorga: «… Salud Ocupacional a ______ portador».
        if seccion and (graduados or not re.search(r"\bA$|PORTADOR", seccion.group("titulo").strip(" :"))):
            # Sin el «Según → continúa» con que el renglón pasa a la otra hoja (hoja 142).
            especialidad = re.sub(r"\s+SEGUN$", "", seccion.group("titulo").strip(" :"))
            enfasis = None
            continue
        hallado = _RENGLON_NUMERADO.match(limpio)
        if hallado is not None:
            orden, resto = int(hallado.group("orden")), hallado.group("resto")
        else:
            sin_numero = _RENGLON_SIN_NUMERO.match(limpio)
            siguiente = _plano(renglones[indice_del_renglon + 1]) if indice_del_renglon + 1 < len(renglones) else ""
            con_cedula = bool(_CEDULA_CON_ROTULO.search(plano) or _CON_SU_DOCUMENTO.search(plano)) or (
                bool(_RENGLON_DE_LA_CEDULA.match(siguiente))
                and bool(_CEDULA_CON_ROTULO.match(siguiente.strip()) or siguiente.strip().startswith("CEDULA"))
            )
            # Sin número vale el renglón con viñeta o bajo el título de su
            # sección, y sólo con su cédula rotulada en él o justo debajo: las
            # firmas y el cuerpo no la traen. El nombre solo, sin cédula, no:
            # medido en UPD3859802, por cada graduado bien leído entraban tres
            # firmas y rótulos («Edna Gómez Bustamante / Jefe Dpto Académico»,
            # «Facultad de Enfermería»); esa lista la lee la IA (2026-11-13).
            if sin_numero is None or not con_cedula or not (
                sin_numero.group("vineta") or especialidad or enfasis or lista_abierta
            ):
                continue
            orden, resto = len(graduados) + 1, sin_numero.group("resto")
        palabras, nota = _nombre_del_renglon(resto)
        de_su_renglon = _CEDULA_DEL_RENGLON.search(resto)
        con_cedula = bool(de_su_renglon and cedula_valida(re.sub(r"\D", "", de_su_renglon.group(0))))
        if not _es_un_nombre(palabras, con_cedula=con_cedula):
            continue
        nombre = " ".join(palabra.upper() for palabra in palabras)
        if orden == 0 or (orden, nombre) in vistos:
            continue
        vistos.add((orden, nombre))
        cedula = _CEDULA_DEL_RENGLON.search(resto)
        titulo = None
        if especialidad:
            titulo = f"{especialidad} CON ENFASIS EN {enfasis}" if enfasis else especialidad
        elif enfasis:
            titulo = f"CON ENFASIS EN {enfasis}"
        graduados.append(
            GraduadoDelActa(
                orden=orden,
                nombre=nombre,
                cedula=cedula_valida(re.sub(r"\D", "", cedula.group(0))) if cedula else None,
                titulo=titulo,
                nota=nota,
                puesto=len(graduados) + 1,
            )
        )
        if cedula is None:
            pendientes.append(len(graduados) - 1)
            if empezada := _CEDULA_EMPEZADA.search(plano):
                empezadas[len(graduados) - 1] = empezada.group("cifras")
        else:
            pendientes.clear()
    cerrar_la_columna()
    return graduados


def _con_nota(nota: str | None, otra: str | None) -> str | None:
    """Las dos notas juntas, sin repetir."""
    if not otra or (nota and otra in nota):
        return nota
    return f"{nota}; {otra}" if nota else otra


def puestos_de_la_lista(texto: str) -> int:
    """Cuántos graduados numera la lista del acta, se lean o no sus nombres.

    Cuenta el último número de cada tramo -- la lista vuelve a empezar en el 1
    bajo cada título --, y también los renglones en blanco o que la IA no supo
    leer: la hoja 80 de UPD3859802 trae ocho puestos y la IA sólo transcribió
    un nombre (2026-11-13).
    """
    total, ultimo = 0, 0
    for renglon in (texto or "").splitlines():
        limpio = renglon.replace("|", " ").replace("*", "").strip()
        if _NO_ES_UN_GRADUADO.search(_plano(limpio)):
            continue
        hallado = _PUESTO_DE_LA_LISTA.match(limpio)
        if hallado is None or _RENGLON_DE_LA_CEDULA.match(_plano(limpio)):
            continue
        numero = int(hallado.group("orden"))
        if numero == ultimo + 1:
            ultimo = numero
        elif numero == 1 and ultimo:
            total += ultimo
            ultimo = 1
        elif ultimo < numero <= ultimo + SALTO_DE_UN_RENGLON:
            # Un salto corto es un renglón que no se leyó.
            ultimo = numero
    return total + ultimo


#: Cuántos puestos puede saltarse la lista leída y seguir siendo la misma lista.
SALTO_DE_UN_RENGLON = 3


def estudiantes_declarados(texto: str) -> int | None:
    """Cuántos estudiantes dice el acta que gradúa: «… (48) estudiantes», o ``None``."""
    declarado = _ESTUDIANTES_DECLARADOS.search(_plano(texto or ""))
    return int(declarado.group(1)) if declarado else None


def acta_anulada(texto: str) -> str | None:
    """Por qué el acta está anulada, o ``None``: lo dice el papel, o su lista está en blanco.

    El Acta 05 del 12-12-2003 (UPD3859802, hojas 144-145) se firmó «Anulado»
    con la lista del 1 al 46 vacía: no gradúa a nadie, y el inventario sacaba
    una fila sin nombre (2026-11-13).
    """
    if _ANULADA.search(_plano(texto or "")):
        return "el acta dice que se anuló"
    en_blanco = [renglon for renglon in (texto or "").splitlines() if re.fullmatch(r"\W{0,4}\d{1,3}\W{0,3}", renglon.strip())]
    if len(en_blanco) >= PUESTOS_DE_UNA_LISTA_EN_BLANCO and not graduados_de_la_lista(texto):
        return f"su lista de graduados está en blanco ({len(en_blanco)} puestos sin nombre)"
    return None


def acta_sin_terminar(texto: str) -> str | None:
    """Por qué el acta no gradúa a nadie aunque nadie la anuló, o ``None``: su formulario quedó en blanco y sin lista.

    El Acta 02 del 26-04-2003 (UPD3859802, hoja 138) es el formulario con el
    graduado, la cédula y el título en blanco, sin lista debajo y sin firmas:
    salía una fila sin nombre que decía «no se pudo leer la cédula», como si
    el papel la trajera (2026-11-13).
    """
    letras = _por_letra(texto or "")
    if not (_GRADUADO_EN_BLANCO.search(letras) or _ESTUDIANTE_EN_BLANCO.search(letras)):
        return None
    if graduados_de_la_lista(texto) or puestos_de_la_lista(texto) or estudiantes_declarados(texto):
        return None
    return "el acta quedó sin terminar: su formulario tiene el graduado en blanco y no trae lista de graduados"


def es_acta_colectiva(texto: str) -> bool:
    """Si el acta gradúa a varios: un rango de números, el estudiante en blanco o una lista de graduados.

    Lo que sólo dice «graduación colectiva» no basta: las actas individuales
    de hoy lo dicen y nombran a un graduado (``tests/test_acta_grado.py``).
    El acta abreviada -- sin «En la ciudad de …», sólo el título y la lista --
    lo es aunque nombre a uno: su graduado está en la lista, no en una frase.
    """
    letras = _por_letra(texto or "")
    lista = graduados_de_la_lista(texto or "")
    return bool(
        numero_y_rango(texto or "")[1]
        or _ESTUDIANTE_EN_BLANCO.search(letras)
        or _A_LOS_ESTUDIANTES.search(letras)
        or len(lista) >= 2
        or (lista and not _CUERPO_DEL_LIBRO.search(letras))
        # El formulario con el graduado en blanco y su nombre en la lista de
        # abajo: «… en Salud Ocupacional a - - - - Portador …» y «1- Edgardo
        # José Niño Osorio» (hoja 35: la fila salía sin nombre; 2026-11-13).
        or (lista and _GRADUADO_EN_BLANCO.search(letras))
        # «… a cuatro (4) estudiantes … Las graduandas son:» (hoja 60).
        or (estudiantes_declarados(texto or "") or 0) >= 2
    )


def es_hoja_de_acta_colectiva(texto: str) -> bool:
    """Si la hoja abre un acta colectiva: «graduación colectiva» y además varios graduados.

    Varios es el rango «Nº A a B» en un encabezado con su cuerpo, el estudiante
    en blanco, «a los estudiantes» o una lista de dos graduados o más con su
    cédula. «Graduación colectiva» sola, no: las actas individuales modernas la
    dicen (``tests/test_acta_grado.py``, ``tests/test_razonar_lo_que_falta.py``).
    """
    letras = _por_letra(texto or "")
    if not _GRADUACION_COLECTIVA.search(letras):
        return False
    con_rango = any(numero_y_rango(texto[c.inicio : c.cuerpo])[1] for c in _comienzos(texto))
    return bool(
        con_rango
        or _ESTUDIANTE_EN_BLANCO.search(letras)
        or _A_LOS_ESTUDIANTES.search(letras)
        or sum(1 for g in graduados_de_la_lista(texto) if g.cedula) >= 2
    )


def es_libro_de_actas_colectivas(paginas: Sequence[str]) -> bool:
    """Si el libro es de actas colectivas: dos hojas o más que abren un acta colectiva (una, si el PDF es corto)."""
    hojas = sum(1 for texto in paginas if es_hoja_de_acta_colectiva(texto or ""))
    return hojas >= 1 and (hojas >= HOJAS_DE_UN_LIBRO_COLECTIVO or len(paginas) <= 3)


#: El renglón de la esquina de la hoja: el número del libro y la foliación, «157», «81/V».
_RENGLON_DEL_FOLIO = re.compile(r"^\W*\d{1,4}\s*(?:/\s*V)?\W*$", re.IGNORECASE)


def _sin_folio_arriba(texto: str) -> str:
    """La hoja que sigue a otra sin los renglones del folio de arriba.

    El acta Nº 02 de 2006 (UPD3859802, págs. 159-160) deja «al estudiante» al
    pie de una hoja y el nombre arriba de la siguiente, detrás de «157» y
    «81/V»: con ellos en medio, la regla no veía a «Peggy Margarita Nieto
    Periñan» (2026-11-12).
    """
    renglones = texto.splitlines()
    while renglones and (not renglones[0].strip() or _RENGLON_DEL_FOLIO.match(renglones[0].strip())):
        renglones.pop(0)
    return "\n".join(renglones)


#: Cuántos renglones de arriba de la hoja se miran para ver si su lista sigue
#: la del acta de delante: el folio no cuenta, y puede ir antes un renglón como
#: «Resolución Nº 2892 de fecha 5 de diciembre de 2003» (hoja 143).
RENGLONES_DE_ARRIBA = 4
#: Cuántas letras puede traer una hoja -- sin su folio -- para ser una portada
#: o una hoja en blanco: «Pregrado 1980-2012» con su rótulo (hoja 59).
LETRAS_DE_UNA_PORTADA = 60


def _graduado_numerado(renglon: str) -> int | None:
    """El número del renglón si es el de un graduado de la lista -- «45. Omaira Solarte Phenal …» --, o ``None``."""
    limpio = renglon.replace("|", " ").replace("\\", "").replace("*", "").strip()
    plano = _plano(limpio)
    if not limpio or _NO_ES_UN_GRADUADO.search(plano) or _RENGLON_DE_LA_CEDULA.match(plano):
        return None
    hallado = _RENGLON_NUMERADO.match(limpio)
    if hallado is None or not _es_un_nombre(_nombre_del_renglon(hallado.group("resto"))[0]):
        return None
    return int(hallado.group("orden"))


def ultimo_puesto(texto: str) -> int:
    """El último número de la lista que el texto deja abierta: 44 si acaba en «44. …»; 0 si no trae lista."""
    ultimo = 0
    for renglon in (texto or "").splitlines():
        numero = _graduado_numerado(renglon)
        if numero is not None and (numero == 1 or ultimo < numero <= ultimo + SALTO_DE_UN_RENGLON):
            ultimo = numero
    return ultimo


def sigue_la_lista(anterior: str, texto: str) -> bool:
    """Si la hoja sigue la lista del acta de delante: arriba trae el graduado con el número siguiente al último de ella.

    La hoja 64 de UPD3859802 abre con «45. Omaira Solarte Phenal» -- el Acta 02
    de 1980 acabó en el 44 -- y sigue con «La ceremonia estuvo presidida…»; la
    143 abre con «1. Eduardo Isidro Blanco Granados» bajo el «Acta 06 …
    continúa →» de la 142. Las dos salían como «CEREMONIA DE GRADO» con una
    fila vacía, y sus graduados se perdían (2026-11-13).
    """
    renglones = [renglon for renglon in _sin_folio_arriba(texto or "").splitlines() if renglon.strip()]
    for renglon in renglones[:RENGLONES_DE_ARRIBA]:
        numero = _graduado_numerado(renglon)
        if numero is not None:
            return numero == ultimo_puesto(anterior) + 1
    return False


#: Cuántas veces seguidas tiene que repetirse un trozo con letra o cifra para que
#: el renglón sea un bucle de la IA y no la raya en blanco del formulario.
REPETICIONES_DE_UN_BUCLE = 12
_BUCLE = re.compile(rf"((?=[^\W_])[^\W_]{{1,4}}[\W_]{{0,2}})\1{{{REPETICIONES_DE_UN_BUCLE - 1},}}")
#: Cuántos números seguidos con su punto en un renglón son la IA contando sola.
NUMEROS_DE_UN_BUCLE = 20


def renglones_en_bucle(texto: str) -> int:
    """Cuántos renglones de la lectura de la IA son un bucle: «1.1.1.1…», «H. H. H. …», «1. 2. 3. … 100.».

    La IA a veces lee bien el principio de la hoja y se queda repitiendo un
    trozo: la hoja 80 de UPD3859802 trae ocho graduados y devolvió el primero
    y siete renglones de «1.1.1.1…»; la 74, «Galindo Gloria H. H. H. …»
    (2026-11-13). La raya en blanco del formulario -- «a ________ portador»,
    «- - - - -» -- no es un bucle: no trae letras ni cifras.
    """
    return sum(
        1
        for renglon in (texto or "").splitlines()
        if _BUCLE.search(renglon) or len(re.findall(r"\b\d{1,3}\.", renglon)) >= NUMEROS_DE_UN_BUCLE
    )


def _letras_sin_folio(texto: str) -> int:
    """Cuántas letras trae la hoja sin los renglones de su folio."""
    return len(re.sub(r"[^A-Z]", "", _por_letra(_sin_folio_arriba(texto or ""))))


def orden_del_libro(paginas: Sequence[str]) -> list[int]:
    """Las páginas del libro colectivo en el orden de su folio impreso (``orden_por_el_folio``).

    El folio es el que la IA lee arriba de cada hoja (``folio_del_texto``): en
    UPD3859802 las hojas 1 a 12 son los folios 41 a 58 desordenados, y el Acta
    01 de 1988 empieza en la hoja 98 (folio 40) y sigue en la 2 (2026-11-13).
    """
    return orden_por_el_folio(folios_corregidos([folio_del_texto(texto or "") for texto in paginas]))


def reparto_del_libro_colectivo(paginas: Sequence[str], orden: Sequence[int] | None = None) -> list[ActaDelLibro]:
    """El libro colectivo repartido en actas y hojas de ceremonia, en el orden de su folio impreso.

    Un acta empieza en su encabezado -- o en «En la ciudad de …» si el
    encabezado no se lee --, aunque sea a mitad de hoja; la abreviada, en su
    encabezado con el título o la lista debajo. Sus hojas van en el orden del
    folio impreso (``orden_del_libro``), no en el del escaneo: el acta sigue en
    la hoja que lleva el folio siguiente aunque esté lejos en el PDF.

    La hoja que comparten dos actas -- la cola de una, el comienzo de la otra
    -- va en los **dos** PDF (lo decidió el operador el 2026-11-13: en la hoja
    166 quedaban 25 de los 30 graduados del acta de la 165, y su PDF no los
    traía); su ``cierre`` lo dice, y cuenta en el de la que empieza en ella. Dos
    actas que empiezan en la misma hoja salen cada una en su PDF, con esa hoja.

    El texto de cada acta va desde su encabezado hasta donde empieza la
    siguiente. El encabezado al pie de una hoja con el cuerpo arriba de la
    siguiente abre el acta en la hoja del encabezado. Una hoja sin comienzo es
    de la que va delante, salvo la de una ceremonia que no sea la lista de un
    acta -- su lista sigue aunque no traiga cédulas (la hoja 150, ítems 16-31,
    salía como «CEREMONIA DE GRADO») -- y salvo la que no sigue por folio a la
    de delante: dos hojas no se unen a través de un salto del folio impreso.
    Lo que va antes de la primera acta es de la ceremonia.
    """
    total = len(paginas)
    orden = list(orden) if orden is not None else orden_del_libro(paginas)
    textos = [paginas[pagina - 1] or "" for pagina in orden]
    folios = folios_corregidos([folio_del_texto(texto) for texto in textos])

    def salta(puesto: int) -> bool:
        """Si la hoja del puesto no sigue por folio a la de delante en el orden del libro."""
        antes, este = folios[puesto - 2] if puesto > 1 else None, folios[puesto - 1]
        return antes is not None and este is not None and este != antes + 1

    comienzos = {puesto: _comienzos(texto) for puesto, texto in enumerate(textos, start=1)}
    inicios: dict[int, list[int]] = {puesto: [c.inicio for c in hallados] for puesto, hallados in comienzos.items()}
    # El encabezado al pie de una hoja y el cuerpo arriba de la siguiente.
    for puesto in range(1, total):
        siguiente = comienzos[puesto + 1]
        if not siguiente or siguiente[0].abreviada or siguiente[0].inicio != siguiente[0].cuerpo:
            continue
        cabeza = re.sub(r"[^A-Z]", "", _por_letra(textos[puesto][: siguiente[0].cuerpo]))
        if len(cabeza) > LETRAS_DE_LA_CABEZA or salta(puesto + 1):
            continue
        propios = [c for c in comienzos[puesto] if not c.abreviada]
        al_pie = _encabezado_al_pie(textos[puesto - 1], propios[-1].fin_del_cuerpo if propios else 0)
        if al_pie is None or al_pie in inicios[puesto]:
            continue
        inicios[puesto] = sorted([*inicios[puesto], al_pie])
        inicios[puesto + 1] = inicios[puesto + 1][1:]

    def texto_de(parte: list, hasta: int) -> str:
        """El texto de la parte desde su comienzo hasta la hoja ``hasta`` del orden del libro."""
        return "\n".join([textos[parte[0] - 1][parte[3] :], *textos[parte[0] : hasta]])

    partes: list[list] = []  # desde, hasta, ceremonia, inicio (en puestos del orden del libro)
    for puesto, texto in enumerate(textos, start=1):
        sigue = bool(partes) and not salta(puesto)
        if inicios[puesto]:
            partes += [[puesto, puesto, False, inicio] for inicio in inicios[puesto]]
        elif sigue and not partes[-1][2] and sigue_la_lista(texto_de(partes[-1], puesto - 1), texto):
            # Su lista sigue la del acta de delante: es suya aunque diga
            # «La ceremonia estuvo presidida…» (hojas 64 y 143).
            partes[-1][1] = puesto
        elif clase_de_hoja(texto) == CEREMONIA and puestos_de_la_lista(texto) < 2:
            if sigue and partes[-1][2]:
                partes[-1][1] = puesto
            else:
                partes.append([puesto, puesto, True, 0])
        elif sigue:
            partes[-1][1] = puesto
        else:
            partes.append([puesto, puesto, True, 0])

    def hojas(desde: int, hasta: int) -> tuple[int, ...]:
        return tuple(orden[puesto - 1] for puesto in range(desde, hasta + 1))

    hechas: list[ActaDelLibro] = []
    for indice, (desde, hasta, ceremonia, inicio) in enumerate(partes):
        if ceremonia:
            suyas = hojas(desde, hasta)
            hechas.append(ActaDelLibro(suyas[0], suyas[-1], ceremonia=True, hojas=suyas))
            continue
        siguiente = partes[indice + 1] if indice + 1 < len(partes) else None
        if siguiente is not None and not siguiente[2] and siguiente[0] == desde == hasta:
            # La siguiente empieza en la misma hoja: su texto es lo que va entre las dos.
            suyas = hojas(desde, hasta)
            texto = textos[desde - 1][inicio : siguiente[3]].strip()
            hechas.append(ActaDelLibro(suyas[0], suyas[-1], texto, hojas=suyas))
            continue
        trozos = [textos[desde - 1][inicio:], *(_sin_folio_arriba(texto) for texto in textos[desde:hasta])]
        cierre = None
        if siguiente is not None and not siguiente[2] and siguiente[0] == hasta + 1 and not salta(hasta + 1):
            cola = _sin_folio_arriba(textos[hasta][: siguiente[3]])
            if len(re.sub(r"[^A-Z]", "", _por_letra(cola))) >= LETRAS_DE_UN_CIERRE:
                trozos.append(cola)
                cierre = hasta + 1
        suyas = hojas(desde, cierre or hasta)
        hechas.append(
            ActaDelLibro(
                suyas[0],
                suyas[-1],
                "\n".join(trozos).strip(),
                cierre=orden[cierre - 1] if cierre else None,
                hojas=suyas,
            )
        )
    return _con_las_portadas_delante(_sin_encabezados_en_blanco(hechas), paginas)


def _sin_encabezados_en_blanco(partes: list[ActaDelLibro]) -> list[ActaDelLibro]:
    """El reparto sin los encabezados abreviados que quedaron en blanco: no son actas, son una nota de la de delante.

    Al pie de la hoja 140 de UPD3859802 dice «Acto 04 / Especialista en.» y la
    hoja que sigue por folio abre con el Acta 05: el acta 04 se empezó y no se
    escribió. Salía una fila sin graduado, sin fecha y con un PDF de la misma
    hoja que ya va en el del acta 03 (2026-11-13).
    """
    limpias: list[ActaDelLibro] = []
    for parte in partes:
        texto = parte.texto
        en_blanco = (
            not parte.ceremonia
            and len(parte.en_el_pdf) == 1
            and not _CUERPO_DEL_LIBRO.search(_por_letra(texto))
            and puestos_de_la_lista(texto) == 0
            and not graduados_de_la_lista(texto)
        )
        anterior = limpias[-1] if limpias else None
        if en_blanco and anterior is not None and not anterior.ceremonia and parte.en_el_pdf[0] in anterior.en_el_pdf:
            renglon = " / ".join(r.strip() for r in texto.splitlines() if r.strip())
            limpias[-1] = replace(
                anterior,
                notas=(
                    *anterior.notas,
                    f"al pie de la hoja {parte.en_el_pdf[0]} se empezó otra acta («{renglon[:60]}») y quedó en "
                    "blanco: no se inventarió; revísela en el papel",
                ),
            )
            continue
        limpias.append(parte)
    return limpias


def _con_las_portadas_delante(partes: list[ActaDelLibro], paginas: Sequence[str]) -> list[ActaDelLibro]:
    """El reparto con cada portada -- una hoja de ceremonia casi sin letras -- en el PDF del acta que la sigue.

    La hoja 59 de UPD3859802 es la portada «Pregrado 1980-2012» de la segunda
    parte del libro: salía como «CEREMONIA DE GRADO» con una fila vacía en el
    FUID (2026-11-13). Va delante de la primera acta que la sigue; sin acta
    detrás, con la de delante.
    """
    juntas: list[ActaDelLibro] = []
    pendiente: ActaDelLibro | None = None
    for parte in partes:
        portada = parte.ceremonia and all(_letras_sin_folio(paginas[p - 1]) <= LETRAS_DE_UNA_PORTADA for p in parte.en_el_pdf)
        if portada:
            pendiente = parte if pendiente is None else replace(pendiente, hojas=(*pendiente.en_el_pdf, *parte.en_el_pdf))
            continue
        if pendiente is not None and not parte.ceremonia:
            hojas = (*pendiente.en_el_pdf, *parte.en_el_pdf)
            nota = f"la hoja {', '.join(map(str, pendiente.en_el_pdf))} es una portada: va al principio del PDF de esta acta"
            parte = replace(parte, desde=hojas[0], hojas=hojas, notas=(*parte.notas, nota))
        elif pendiente is not None:
            juntas.append(pendiente)
        pendiente = None
        juntas.append(parte)
    if pendiente is not None:
        if juntas and not juntas[-1].ceremonia:
            ultima = juntas[-1]
            hojas = (*ultima.en_el_pdf, *pendiente.en_el_pdf)
            juntas[-1] = replace(ultima, hasta=hojas[-1], hojas=hojas)
        else:
            juntas.append(pendiente)
    return juntas


def paginas_compartidas(partes: Sequence[ActaDelLibro]) -> list[int]:
    """Las hojas que van en dos PDF del libro colectivo: el cierre de un acta y el comienzo de otra."""
    vistas = Counter(pagina for parte in partes for pagina in parte.en_el_pdf)
    return sorted(pagina for pagina, veces in vistas.items() if veces > 1)


def actas_del_libro_colectivo(partes: Sequence[ActaDelLibro], total: int) -> ActasDelPdf:
    """Los tramos del libro colectivo (``reparto_del_libro_colectivo``): uno por acta y uno por cada ceremonia."""
    if not partes:
        return ActasDelPdf(tramos=(TramoDeActa(1, max(1, total)),))
    return ActasDelPdf(
        tramos=tuple(
            TramoDeActa(
                parte.desde,
                parte.hasta,
                ceremonia=parte.ceremonia,
                hojas=len(parte.en_el_pdf),
                paginas_del_pdf=parte.en_el_pdf,
            )
            for parte in partes
        )
    )


def numeros_de_los_graduados(
    desde: str | None, hasta: str | None, cuantos: int
) -> tuple[list[str | None], str | None]:
    """El número del acta de cada graduado, y la nota si el rango no cuadra con la lista.

    Con «Nº 05408120 a 05408124» y cinco graduados, uno por graduado y en el
    orden de la lista: 05408120, 05408121… Si el rango no cuadra con cuántos
    nombra el acta, todos llevan el rango -- «05408120 A 05408124» -- y se
    dice: no se adivina qué número es de quién. Sin rango, el número del acta.
    """
    if desde and hasta and desde.isdigit() and hasta.isdigit():
        if int(hasta) - int(desde) + 1 == cuantos:
            return [str(int(desde) + puesto).zfill(len(desde)) for puesto in range(cuantos)], None
        return [f"{desde} A {hasta}"] * cuantos, (
            f"el acta va del Nº {desde} al {hasta} y nombra {cuantos} graduado(s): no se sabe qué número "
            "es de cada uno; revíselo en el papel"
        )
    return [desde] * cuantos, None


def rotulo_del_acta_colectiva(desde: str | None, hasta: str | None) -> str:
    """«ACTA DE GRADO 05408120 A 05408124», «ACTA DE GRADO No. 03» o «ACTA DE GRADO SIN NUMERO»."""
    if desde and hasta:
        return f"{ROTULO} {desde} A {hasta}"
    if desde:
        return f"{ROTULO} No. {desde}"
    return f"{ROTULO} SIN NUMERO"


#: Lo que se le pide al lector de texto de la IA sobre un acta colectiva: el
#: texto que ya leyó el OCR de pago, cortado donde empieza la siguiente. Lo que
#: devuelve se valida contra ese texto (``lectura_colectiva_de_la_ia``).
INSTRUCCIONES_DEL_ACTA_COLECTIVA = (
    "Eres archivista de la Universidad de Cartagena. Recibes el texto, leído por OCR de un libro manuscrito, "
    "de UN acta de grado colectiva: una sola ceremonia que gradúa a varios estudiantes, nombrados subrayados "
    "en la frase o en una lista numerada debajo del acta («1. Castillo Castilla Freddy  C.C. 45.761.728 de "
    "Cartagena»).\n\n"
    "Devuelve estas líneas y nada más:\n"
    "NUMERO_DESDE: el número del acta (el que sigue a «Acta de Grado Nº»); si es un rango «Nº 05408120 a "
    "05408124», el primero\n"
    "NUMERO_HASTA: el último número del rango, o NINGUNO si el acta lleva un solo número\n"
    "FECHA: la fecha de la ceremonia en DD-MM-AAAA (la de «a los … días del mes de …»; no la de la "
    "resolución)\n"
    "TITULO: el título que otorga el acta («ENFERMERA (O)», «ESPECIALISTA EN SALUD OCUPACIONAL»)\n"
    "y una línea por graduado, en el orden del acta:\n"
    "GRADUADO: n | NOMBRE COMPLETO | CEDULA | TITULO\n\n"
    "Reglas:\n"
    "- Un graduado es cada persona de la lista numerada o subrayada en la frase; nunca el rector, la decana, "
    "la secretaria, el jefe de departamento ni quien firma.\n"
    "- El nombre tal como está escrito y en su orden (a veces van primero los apellidos), sin la cédula, sin "
    "«C.C.» ni «Nº» y sin el lugar de expedición («de Cartagena», «Arjona»).\n"
    "- La cédula, sólo sus cifras; si no está escrita, NINGUNO.\n"
    "- El TITULO del graduado sólo si el acta le da uno distinto del común; si no, NINGUNO.\n"
    "- Si el espacio tras «al estudiante» está vacío, con rayas o con «x x», los graduados son los de la lista.\n"
    "- Cada palabra y cada cifra tiene que estar escrita en el texto: no corrijas ni inventes. Si un dato no "
    "está, NINGUNO; si el acta no nombra a ningún graduado, ninguna línea GRADUADO."
)


@dataclass(frozen=True, slots=True)
class LecturaColectiva:
    """Lo que el lector de la IA entendió de un acta colectiva, ya validado contra su texto."""

    desde: str | None = None
    hasta: str | None = None
    fecha: date | None = None
    titulo: str | None = None
    graduados: tuple[GraduadoDelActa, ...] = ()


def _cifras_seguidas(texto: str) -> str:
    """El texto con las cifras de cada número juntas: «45.521.842» es 45521842.

    Sólo un separador dentro del renglón: con el salto, «05408124» se pegaba al
    folio «158» de la hoja siguiente y el número del rango no se confirmaba.
    """
    return re.sub(r"(?<=\d)[ .,'’´](?=\d)", "", texto or "")


def lectura_colectiva_de_la_ia(respuesta: str, texto: str) -> LecturaColectiva:
    """Lo que la IA leyó de un acta colectiva, campo por campo, si el texto lo dice; lo demás no se devuelve.

    Como ``datos_de_la_ia``: una palabra o una cifra que el texto no trae
    descarta el dato. Del graduado cuyo nombre no se confirma queda el puesto
    -- es un graduado de la lista, y su número de acta depende de él -- con su
    cédula si se confirma, y la nota para revisarlo.
    """
    palabras_del_texto = set(re.findall(r"[A-Z]+", _plano(texto)))
    seguidas = _cifras_seguidas(texto)
    cifras_del_texto = re.sub(r"\D", "", texto)

    def esta_el_numero(valor: str) -> str | None:
        numero = re.search(r"\d{1,10}", valor)
        if numero and re.search(rf"(?<!\d){numero.group(0)}(?!\d)", seguidas):
            return numero.group(0)
        return None

    def palabras_si_estan(valor: str) -> list[str]:
        palabras = re.findall(r"[A-ZÁÉÍÓÚÜÑ]+", valor.upper())
        return palabras if palabras and all(_plano(p).strip() in palabras_del_texto for p in palabras) else []

    datos: dict[str, object] = {}
    graduados: list[GraduadoDelActa] = []
    vistos: set[tuple[str | None, str | None]] = set()
    for linea in (respuesta or "").splitlines():
        campo, _, valor = linea.partition(":")
        campo, valor = _plano(campo).strip(" -*`"), valor.strip(" *`")
        if campo == "GRADUADO":
            partes = [parte.strip(" *`") for parte in valor.split("|")]
            if len(partes) < 2:
                continue
            orden = re.search(r"\d{1,3}", partes[0])
            leido = partes[1] if "NINGUNO" not in _plano(partes[1]) else ""
            palabras = palabras_si_estan(leido)
            nombre = " ".join(palabras) if len(palabras) >= 2 else None
            cedula = None
            if len(partes) > 2 and "NINGUNO" not in _plano(partes[2]):
                cifras = re.sub(r"\D", "", partes[2])
                cedula = cifras if 6 <= len(cifras) <= 11 and cifras in cifras_del_texto else None
            titulo = None
            if len(partes) > 3 and "NINGUNO" not in _plano(partes[3]):
                del_titulo = palabras_si_estan(partes[3])
                titulo = " ".join(del_titulo) if del_titulo and es_un_titulo(partes[3]) else None
            if nombre is None and cedula is None:
                continue
            clave_del_graduado = (nombre, cedula)
            if clave_del_graduado in vistos:
                continue
            vistos.add(clave_del_graduado)
            nota = None
            if nombre is None and leido:
                nota = f"la IA leyó el nombre «{leido}», que el texto no confirma: revíselo en el papel"
            graduados.append(
                GraduadoDelActa(
                    orden=int(orden.group(0)) if orden else len(graduados) + 1,
                    nombre=nombre,
                    cedula=cedula,
                    titulo=titulo,
                    nota=nota,
                )
            )
            continue
        if not valor or "NINGUNO" in _plano(valor):
            continue
        if campo in ("NUMERO_DESDE", "NUMERO DESDE"):
            datos["desde"] = esta_el_numero(valor)
        elif campo in ("NUMERO_HASTA", "NUMERO HASTA"):
            datos["hasta"] = esta_el_numero(valor)
        elif campo == "TITULO":
            palabras = palabras_si_estan(valor)
            if palabras and es_un_titulo(valor):
                datos["titulo"] = " ".join(palabras)
        elif campo == "FECHA":
            partes_de_la_fecha = re.fullmatch(r"(\d{1,2})\D(\d{1,2})\D(\d{4})", valor.strip())
            if partes_de_la_fecha:
                dia, mes, anio = (int(parte) for parte in partes_de_la_fecha.groups())
                fecha = _fecha(dia, mes, str(anio))
                if fecha is not None and _la_hoja_dice_la_fecha(fecha, texto):
                    datos["fecha"] = fecha
    return LecturaColectiva(
        desde=datos.get("desde"),  # type: ignore[arg-type]
        hasta=datos.get("hasta"),  # type: ignore[arg-type]
        fecha=datos.get("fecha"),  # type: ignore[arg-type]
        titulo=datos.get("titulo"),  # type: ignore[arg-type]
        graduados=tuple(sorted(graduados, key=lambda g: g.orden)),
    )


#: El cargo que sigue al nombre de quien firma el acta: «Irma Yolanda Castillo
#: Ávila / Jefe Dpto. Académico», «Amparo Montalvo Prieto, Decana».
_CARGO_DEL_FIRMANTE = re.compile(
    r"\W{0,8}(?:(?:DR|DRA|DOCTOR|DOCTORA)\W+)?(?:DECAN|JEF[AE]|RECTOR|SECRETARI|DIRECT|PRESID|VICERRECTOR)"
)


def sin_quien_firma(graduados: Sequence[GraduadoDelActa], texto: str) -> list[GraduadoDelActa]:
    """Los graduados sin quien firma el acta: el nombre sin cédula que en el texto lleva su cargo detrás.

    La IA tomó por graduada a «Irma Yolanda Castillo Ávila», que firma como
    Jefe del Departamento Académico al pie de la lista (UPD3859802, acta Nº
    12007003 a 12007004; 2026-11-12). Quien lleva cédula es de la lista: los
    firmantes no la escriben.
    """
    plano = _plano(texto)
    return [
        graduado_
        for graduado_ in graduados
        if graduado_.cedula
        or not graduado_.nombre
        or not any(
            _CARGO_DEL_FIRMANTE.match(plano, hallado.end())
            for hallado in re.finditer(re.escape(_plano(graduado_.nombre).strip()), plano)
        )
    ]


#: Cuánto tiene que parecerse el nombre que leyó la IA al de la lista para ser la misma persona.
PARECIDO_DEL_GRADUADO = 0.72


def _parecido_del_nombre(uno: str | None, otro: str | None) -> float:
    """Cuánto se parecen dos nombres de la lista, letra a letra y sin tildes, en cualquier orden.

    La IA escribe a veces el nombre primero y la lista los apellidos: «MARTHA
    CICILIA ALVANS ESCANILLA» es «Alvans Escanilla Martha Cicilia» (hoja 21).
    """
    if not uno or not otro:
        return 0.0
    a, b = _plano(uno).split(), _plano(otro).split()
    return max(
        difflib.SequenceMatcher(None, " ".join(a), " ".join(b)).ratio(),
        difflib.SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio(),
    )


#: Lo que la IA leyó del nombre que el texto no confirma, en su nota (``lectura_colectiva_de_la_ia``).
_LEIDO_SIN_CONFIRMAR = re.compile(r"la IA leyó el nombre «([^»]+)», que el texto no confirma")
#: Cuánto tiene que parecerse a uno ya casado para ser el mismo graduado repetido por la IA.
PARECIDO_DE_UN_REPETIDO = 0.85


def _cedula_en_su_renglon(cedula: str, nombre: str | None, texto: str) -> bool:
    """Si la cédula está escrita en un renglón -- o en el de abajo -- con una palabra del nombre.

    La IA casaba las cédulas por orden de aparición: en el Acta 05408125 a
    05408149 (UPD3859802, hoja 176) la de Diana Cristina Arenas Fumiga
    («1.129.516.130») le tocó a Ruth Amarilis Castillo Alvarez, y las de
    detrás se corrieron (2026-11-13).
    """
    palabras = {p for p in _plano(nombre or "").split() if len(p) > 3}
    renglones = [_plano(renglon) for renglon in (texto or "").splitlines() if renglon.strip()]
    for indice, renglon in enumerate(renglones):
        if cedula not in re.sub(r"(?<=\d)[ .,'’´:/]{1,2}(?=\d)", "", renglon):
            continue
        cerca = " ".join(renglones[max(0, indice - 1) : indice + 1])
        if palabras & set(re.findall(r"[A-Z]+", cerca)):
            return True
    return False


def juntar_graduados(
    de_la_ia: Sequence[GraduadoDelActa], de_la_lista: Sequence[GraduadoDelActa], texto: str = ""
) -> list[GraduadoDelActa]:
    """Los graduados del acta: los de la IA, casados con los que la regla leyó en la lista por su nombre.

    La IA manda en el nombre -- junta el nombre partido, distingue al
    firmante --, pero puede quedarse corta: un renglón que se saltó, el
    marcado a lápiz «no aparece», la respuesta cortada en el graduado 40. Cada
    graduado de la IA se casa con el de la lista que más se le parece, y la
    cédula es la de **su renglón** en la lista: la que la IA le puso sólo vale
    si está en el renglón de su nombre (``_cedula_en_su_renglon``), y una
    cédula que no es válida no vale nunca (``cedula_valida``). El de la lista
    que la IA no trae se añade con su nota; la nota a lápiz y el título de su
    sección pasan del de la lista al de la IA. Van en el orden de la lista.
    """
    if not de_la_ia:
        return list(de_la_lista)
    usados: set[int] = set()
    juntos: list[tuple[float, GraduadoDelActa]] = []
    puesto_anterior = 0.0
    for graduado_ in de_la_ia:
        # El nombre que el texto no confirma también sirve para casarlo con el
        # de la lista, que sí está en el texto: «Carmen De la Hoz Roche» es el
        # «DE LA HOZ ROCHEL CARMEN» de la lista (hoja 21).
        sin_confirmar = _LEIDO_SIN_CONFIRMAR.search(graduado_.nota or "") if not graduado_.nombre else None
        leido = graduado_.nombre or (sin_confirmar.group(1) if sin_confirmar else None)
        parecidos = [(_parecido_del_nombre(leido, de_la_regla.nombre), indice) for indice, de_la_regla in enumerate(de_la_lista)]
        parecido, indice = max(((p, i) for p, i in parecidos if i not in usados), default=(0.0, -1))
        if parecido < PARECIDO_DEL_GRADUADO and any(p >= PARECIDO_DE_UN_REPETIDO for p, i in parecidos if i in usados):
            continue  # la IA lo escribió dos veces
        cedula_de_la_ia = cedula_valida(graduado_.cedula)
        if cedula_de_la_ia and texto and not _cedula_en_su_renglon(cedula_de_la_ia, leido, texto):
            cedula_de_la_ia = None
        if parecido >= PARECIDO_DEL_GRADUADO:
            usados.add(indice)
            de_la_regla = de_la_lista[indice]
            nota = graduado_.nota if graduado_.nombre else None
            graduado_ = replace(
                graduado_,
                nombre=graduado_.nombre or de_la_regla.nombre,
                cedula=de_la_regla.cedula or cedula_de_la_ia,
                titulo=graduado_.titulo or de_la_regla.titulo,
                nota=_con_nota(nota, de_la_regla.nota),
            )
            puesto_anterior = float(de_la_regla.puesto or indice + 1)
            juntos.append((puesto_anterior, graduado_))
            continue
        puesto_anterior += 0.01
        juntos.append((puesto_anterior, replace(graduado_, cedula=cedula_de_la_ia)))
    for indice, de_la_regla in enumerate(de_la_lista):
        if indice not in usados:
            juntos.append(
                (
                    float(de_la_regla.puesto or indice + 1),
                    replace(de_la_regla, nota=_con_nota(de_la_regla.nota, "se leyó de la lista sin la IA: revíselo en el papel")),
                )
            )
    return [graduado_ for _puesto, graduado_ in sorted(juntos, key=lambda par: par[0])]


#: Las franjas en que se relee con zoom la hoja de una lista de graduados, de
#: punta a punta y con el margen: un cuarto de hoja cada una, solapadas un
#: renglón y medio para que ningún renglón quede partido. En una franja la IA
#: pone la cédula del margen izquierdo -- o la escrita en alto, entre dos
#: renglones -- junto al nombre de su renglón; en la hoja entera la corría al
#: graduado de al lado o no la veía (UPD3859802, 2026-11-13: la hoja 85 de
#: 1985 trae quince cédulas en el margen y salieron todas en su renglón).
FRANJAS_DE_LA_LISTA: tuple[tuple[float, float], ...] = (
    (0.0, 0.25),
    (0.2, 0.45),
    (0.4, 0.65),
    (0.6, 0.85),
    (0.8, 1.0),
)
#: Una cédula en el renglón ampliado: con sus puntos, con una cifra de más
#: pegada delante de «/» (la «C» de «C/gena» leída como un 0: «45.525.2670/gena»)
#: o sin separadores.
_CEDULA_DE_LA_FRANJA = re.compile(
    r"(?<![\d.,'’´])(\d{1,3}[.,'’´]\s?\d{6}|\d{1,3}(?:[.,'’´]\s?\d{3}){1,3}\d?|\d{4,6} \d{3,5}(?=/)|\d{6,10})(?!\d)"
)
#: Lo que no es del nombre en el renglón ampliado: el lugar abreviado del
#: margen («C/ger», «Cfsm»), el rótulo de la cédula y los conectores.
_NO_ES_DEL_NOMBRE_EN_LA_FRANJA = _NO_ES_DEL_NOMBRE_EN_LA_LISTA | {
    "LA", "LAS", "LOS", "Y", "GER", "GENA", "GEN", "CFSM", "CGENA", "AP", "APARECE", "COMPLEMENT",
}
#: «no aparece» o «no ap.» escrito a lápiz en el renglón o en su margen.
_NO_APARECE_EN_LA_FRANJA = re.compile(r"\bNO\W{0,3}AP(?:ARECE|\b|\.)")
#: Cuántas palabras del nombre del graduado tiene que traer el renglón, y qué
#: parte de ellas, para ser su renglón: el lugar del margen y la letra mal
#: leída añaden o cambian palabras, pero el apellido se repite.
PALABRAS_DEL_NOMBRE_EN_EL_RENGLON = 2
PARTE_DEL_NOMBRE_EN_EL_RENGLON = 0.6
#: Cuánto se tiene que parecer una palabra leída con zoom a la del nombre:
#: «ASTUD» de la hoja y «Astrid» del zoom, «ORQCO» y «Orozco», 0,73 (hoja 85).
PARECIDO_DE_UNA_PALABRA_AMPLIADA = 0.7
#: Lo que el renglón tiene que superar al segundo graduado más parecido: el
#: renglón que se parece igual a dos graduados no es de ninguno.
VENTAJA_DEL_RENGLON = 0.15
CEDULA_CON_ZOOM = "cédula leída con zoom en su renglón"


@dataclass(frozen=True, slots=True)
class RenglonAmpliado:
    """Un renglón de la lista leído con zoom: las palabras de su nombre, su cédula y si dice «no aparece»."""

    palabras: tuple[str, ...]
    cedula: str | None = None
    no_aparece: bool = False


def _cedulas_de_la_franja(renglon: str) -> list[str]:
    """Las cédulas del renglón ampliado, en su orden, las que tienen largo de cédula (``cedula_valida``).

    Nueve cifras pegadas a «/» son ocho y la inicial del lugar: «45.525.2670/gena»
    es la 45.525.267 de C/gena, y «40992 8675/mbis», la 40.992.867 de S/Andrés
    (UPD3859802, hojas 133 y 142). «3'928794» es la 3.928.794.
    """
    cedulas = []
    for hallada in _CEDULA_DE_LA_FRANJA.finditer(renglon):
        cifras = re.sub(r"\D", "", hallada.group(1))
        if len(cifras) == 9 and renglon[hallada.end(1) : hallada.end(1) + 1] == "/":
            cifras = cifras[:-1]
        if valida := cedula_valida(cifras):
            cedulas.append(valida)
    return cedulas


def renglones_de_la_franja(texto: str) -> list[RenglonAmpliado]:
    """Los renglones con nombre de una franja leída con zoom, cada uno con su cédula.

    La cédula escrita en el margen izquierdo, o en alto entre dos renglones,
    la lee la IA a veces en un renglón suyo, sin nombre: «45.450.533» y debajo
    «C/ger 6- Nicula Del Socorro Boborcos Ortega». Esa cédula va al renglón
    con nombre de debajo si no trae la suya, y si no, al de arriba.
    """
    # Cada renglón leído: sus palabras de nombre, sus cédulas y su «no aparece».
    leidos: list[tuple[list[str], list[str], bool]] = []
    for linea in (texto or "").splitlines():
        if not linea.strip():
            continue
        palabras = [
            p
            for p in (_plano(palabra).strip() for palabra in _PALABRA_DEL_RENGLON.findall(linea))
            if len(p) >= 3 and p not in _NO_ES_DEL_NOMBRE_EN_LA_FRANJA
        ]
        leidos.append((palabras, _cedulas_de_la_franja(linea), _NO_APARECE_EN_LA_FRANJA.search(_plano(linea)) is not None))
    con_nombre = [i for i, (palabras, _c, _n) in enumerate(leidos) if len(palabras) >= PALABRAS_DEL_NOMBRE_EN_EL_RENGLON]
    cedula_de: dict[int, str | None] = {i: (leidos[i][1][0] if leidos[i][1] else None) for i in con_nombre}
    sueltas = [(i, leidos[i][1][0]) for i in range(len(leidos)) if i not in cedula_de and leidos[i][1]]
    # El bloque: la IA devolvió los nombres y debajo sus cédulas, como dos
    # columnas -- «15 De Seón Berrio Esther Helena» … «19 Fontela …», y luego
    # «c.c 40992 8675/mbis» … «c.c 45541368» (hojas 121 y 142) --. Tantas
    # cédulas seguidas como nombres sin cédula justo delante: van en orden.
    usadas: set[int] = set()
    inicio = 0
    while inicio < len(sueltas):
        fin = inicio
        while fin + 1 < len(sueltas) and sueltas[fin + 1][0] == sueltas[fin][0] + 1:
            fin += 1
        bloque = sueltas[inicio : fin + 1]
        delante = []
        for i in reversed([i for i in con_nombre if i < bloque[0][0]]):
            if cedula_de[i] is not None or leidos[i][2]:
                break
            delante.insert(0, i)
        if len(bloque) >= 2 and len(delante) >= len(bloque):
            for destino, (indice, cedula) in zip(delante[-len(bloque) :], bloque, strict=True):
                cedula_de[destino] = cedula
                usadas.add(indice)
        inicio = fin + 1
    # La suelta que queda va al renglón con nombre de debajo si no trae la
    # suya, y si no, al de arriba: la del margen va en su propio renglón,
    # encima del nombre («45.450.533» / «C/ger 6- Nicula …», hoja 85).
    for indice, cedula in sueltas:
        if indice in usadas:
            continue
        debajo = next((i for i in con_nombre if i > indice), None)
        arriba = next((i for i in reversed(con_nombre) if i < indice), None)
        for destino in (debajo, arriba):
            if destino is not None and cedula_de[destino] is None:
                cedula_de[destino] = cedula
                break
    # El renglón con dos cédulas lleva al final la escrita en alto del de
    # debajo: «35 Joery Osorio Eliana 45.454.974 C/gena 38.859.944» y «36 Santos
    # Saavedra Dora Patricia Buga» (hoja 79).
    for posicion, i in enumerate(con_nombre):
        siguiente = con_nombre[posicion + 1] if posicion + 1 < len(con_nombre) else None
        if len(leidos[i][1]) >= 2 and siguiente is not None and cedula_de[siguiente] is None and not leidos[siguiente][2]:
            cedula_de[siguiente] = leidos[i][1][-1]
    return [RenglonAmpliado(tuple(leidos[i][0]), cedula_de[i], leidos[i][2]) for i in con_nombre]


def _parecido_al_renglon(nombre: str | None, renglon: RenglonAmpliado) -> float:
    """Cuánto del nombre del graduado está en el renglón ampliado: la media del parecido de cada palabra.

    La media y no la cuenta: «Ruiz Larios Ingrid Del Carmen» se parece a «RUIZ
    LARIOS JUGID DEL CARMEN» (0,89) mucho más que a «BARRIOS CARMONA PAOLA»
    (0,65), aunque «Larios» y «Carmen» pasen por «Barrios» y «Carmona» (hoja 121).
    Hacen falta al menos dos palabras del nombre en el renglón.
    """
    del_nombre = [p for p in _plano(nombre or "").split() if len(p) >= 3 and p not in _NO_ES_DEL_NOMBRE_EN_LA_FRANJA]
    if len(del_nombre) < PALABRAS_DEL_NOMBRE_EN_EL_RENGLON or not renglon.palabras:
        return 0.0
    parecidos = [
        max(difflib.SequenceMatcher(None, palabra, leida).ratio() for leida in renglon.palabras) for palabra in del_nombre
    ]
    if sum(1 for p in parecidos if p >= PARECIDO_DE_UNA_PALABRA_AMPLIADA) < PALABRAS_DEL_NOMBRE_EN_EL_RENGLON:
        return 0.0
    return sum(parecidos) / len(parecidos)


def necesita_zoom(graduado_: GraduadoDelActa) -> bool:
    """Si al graduado le falta la cédula sin que el papel diga por qué («no aparece», «no se graduó»)."""
    return graduado_.cedula is None and not (graduado_.nota and ("no aparece" in graduado_.nota or "anotado en el papel" in graduado_.nota))


def cedulas_con_zoom(
    graduados: Sequence[GraduadoDelActa], franjas: Sequence[str], texto: str
) -> tuple[list[GraduadoDelActa], list[str]]:
    """Los graduados con la cédula de su renglón leído con zoom, y lo que se hizo para el acta.

    Cada renglón ampliado es del graduado cuyo nombre trae
    (``_parecido_al_renglon``), no del que va en su puesto: así se arregla la
    cédula del margen que la lectura de la hoja entera corrió un renglón (acta
    1 de 1985, hoja 85: la de Nivila Boborcos era la de Yenisy Bustamante). Lo
    que se decide:

    * el graduado sin cédula toma la de su renglón, si es válida y no es de otro;
    * el que ya tiene una distinta la cambia sólo si la hoja también trae la
      del zoom (dos lecturas la ven); si no, se queda la suya y se anota;
    * el renglón que dice «no aparece» lo confirma en la nota;
    * una cédula que el zoom le da a uno y la hoja le había dado a otro se le
      quita a ese otro: era la de su vecino.

    Dos renglones del mismo graduado con cédulas distintas no deciden nada.
    """
    renglones = [renglon for franja in franjas for renglon in renglones_de_la_franja(franja)]
    if not renglones or not graduados:
        return list(graduados), []
    del_graduado: dict[int, list[RenglonAmpliado]] = {}
    for renglon in renglones:
        parecidos = sorted(((_parecido_al_renglon(g.nombre, renglon), i) for i, g in enumerate(graduados)), reverse=True)
        mejor, indice = parecidos[0]
        segundo = parecidos[1][0] if len(parecidos) > 1 else 0.0
        if mejor >= PARTE_DEL_NOMBRE_EN_EL_RENGLON and mejor - segundo >= VENTAJA_DEL_RENGLON:
            del_graduado.setdefault(indice, []).append(renglon)
    seguidas = _cifras_seguidas(texto)

    def en_la_hoja(cifras: str) -> bool:
        return re.search(rf"(?<!\d){cifras}(?!\d)", seguidas) is not None

    def la_de_la_hoja(cedula: str) -> str:
        # La del zoom a una cifra de la que la hoja le dio a otro graduado es
        # esa misma, mal leída por una de las dos: «46.500.293» del zoom y
        # «45500293» de la hoja (hoja 85). Se queda la que la hoja también ve.
        if en_la_hoja(cedula):
            return cedula
        for otro in graduados:
            suya = otro.cedula or ""
            if len(suya) == len(cedula) and sum(a != b for a, b in zip(suya, cedula, strict=True)) == 1 and en_la_hoja(suya):
                return suya
        return cedula

    resultado = list(graduados)
    por_el_zoom: dict[str, int] = {}
    dice_no_aparece = {indice for indice, suyos in del_graduado.items() if any(renglon.no_aparece for renglon in suyos)}
    leidas = corregidas = confirmadas = 0
    for indice, suyos in del_graduado.items():
        graduado_ = resultado[indice]
        cedulas = {la_de_la_hoja(renglon.cedula) for renglon in suyos if renglon.cedula}
        if len(cedulas) > 1:
            resultado[indice] = replace(
                graduado_,
                nota=_con_nota(graduado_.nota, f"con zoom su renglón se leyó con dos cédulas ({', '.join(sorted(cedulas))}): revísela en el papel"),
            )
            continue
        if not cedulas:
            if graduado_.cedula is None and indice in dice_no_aparece:
                resultado[indice] = replace(graduado_, nota=_con_nota(graduado_.nota, NOTA_NO_APARECE))
                confirmadas += 1
            continue
        cedula = cedulas.pop()
        leidas_con_zoom = {renglon.cedula for renglon in suyos if renglon.cedula}
        if cedula not in leidas_con_zoom:
            # La hoja y el zoom leyeron la misma cédula con una cifra distinta:
            # se queda la que la hoja ve, y se dice. En la hoja 85 acertó la
            # hoja una vez («45500293») y el zoom otra («36.544.509»).
            graduado_ = replace(
                graduado_,
                nota=_con_nota(
                    graduado_.nota,
                    f"la hoja leyó la cédula {cedula} y el zoom la {leidas_con_zoom.pop()}: revise esa cifra en el papel",
                ),
            )
            resultado[indice] = graduado_
        if graduado_.cedula == cedula:
            por_el_zoom[cedula] = indice
            continue
        if graduado_.cedula is None:
            resultado[indice] = replace(graduado_, cedula=cedula, nota=_con_nota(graduado_.nota, CEDULA_CON_ZOOM))
            por_el_zoom[cedula] = indice
            leidas += 1
        elif en_la_hoja(cedula):
            resultado[indice] = replace(
                graduado_,
                cedula=cedula,
                nota=_con_nota(
                    graduado_.nota,
                    f"la hoja le daba la {graduado_.cedula}, de otro renglón; con zoom en el suyo se leyó la {cedula}",
                ),
            )
            por_el_zoom[cedula] = indice
            corregidas += 1
        else:
            resultado[indice] = replace(
                graduado_,
                nota=_con_nota(graduado_.nota, f"con zoom en su renglón se leyó la cédula {cedula}: revísela en el papel"),
            )
    quitadas = 0
    for indice, graduado_ in enumerate(resultado):
        dueno = por_el_zoom.get(graduado_.cedula or "")
        if dueno is not None and dueno != indice:
            nota = _con_nota(graduado_.nota, f"la cédula {graduado_.cedula} es la del renglón de {resultado[dueno].nombre}")
            if indice in dice_no_aparece:
                nota = _con_nota(nota, NOTA_NO_APARECE)
            resultado[indice] = replace(graduado_, cedula=None, nota=nota)
            quitadas += 1
        elif graduado_.cedula and indice in dice_no_aparece and dueno is None:
            resultado[indice] = replace(
                graduado_,
                nota=_con_nota(graduado_.nota, f"su renglón dice «no aparece» y lleva la cédula {graduado_.cedula}: revísela en el papel"),
            )
    hecho = []
    if leidas or corregidas or quitadas or confirmadas:
        partes = [
            f"{leidas} cédula(s) leída(s)" if leidas else "",
            f"{corregidas} corregida(s) de renglón" if corregidas else "",
            f"{quitadas} quitada(s) por ser de otro renglón" if quitadas else "",
            f"{confirmadas} «no aparece» confirmado(s)" if confirmadas else "",
        ]
        hecho.append("con zoom en los renglones de la lista: " + ", ".join(p for p in partes if p))
    return resultado, hecho


def numero_en_el_encabezado(numero: str, texto: str) -> bool:
    """Si el número está en el encabezado del acta -- antes de «En la ciudad de …» --, y no en su cuerpo.

    La IA daba como número del acta el de la resolución que la autoriza: «Acta
    01 de 1990 … Resolución nº 1299» salía 1299 (UPD3859802, 2026-11-13).
    """
    letras = _por_letra(texto or "")
    cuerpo = _CUERPO_DEL_LIBRO.search(letras)
    cabeza = (texto or "")[: cuerpo.start() if cuerpo else VENTANA_DEL_ENCABEZADO]
    return bool(numero) and re.search(rf"(?<!\d){re.escape(numero)}(?!\d)", _cifras_seguidas(cabeza).replace("/", "")) is not None


def es_acta_abreviada(texto: str) -> bool:
    """Si el acta es la abreviada de una ceremonia: su encabezado sin «En la ciudad de …» (``_abreviadas``)."""
    letras = _por_letra(texto or "")
    return _CUERPO_DEL_LIBRO.search(letras) is None and _ENCABEZADO_DEL_LIBRO.search(letras) is not None
