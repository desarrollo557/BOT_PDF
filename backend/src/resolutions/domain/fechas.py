"""Las fechas que un documento lleva escritas, y cuál de ellas lo fecha.

El archivo necesita fechar cada unidad documental: es lo que el FUID llama
fechas extremas y lo que permite ordenar una caja en el tiempo sin abrirla. No
hay un campo del que leerla -- estos papeles no traen metadatos, son escaneos --
así que se lee del texto, que es donde está.

Lo que hace difícil esto no es reconocer una fecha, que se hace con tres
patrones, sino distinguir la que fecha el documento de las que sólo se citan
dentro de él. Un recurso de reposición nombra la Ley 142 de 1994, la Sentencia
T-1204 de 2001 y el Decreto 2591 de 1991 en su fundamento de derecho, y ninguna
de las tres tiene nada que ver con cuándo se escribió el recurso. Medido sobre
un expediente real: de 214 fechas reconocibles, 49 eran citas de ese tipo.
"""

from __future__ import annotations

import re
from datetime import date

#: Los tres formatos con que estos papeles escriben una fecha. Salen de contar
#: sobre un expediente real de 97 páginas: 157 en cifras con barras, 49 en
#: letra y 8 en cifras con guiones.
_EN_CIFRAS = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_EN_LETRA = re.compile(
    r"\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+(?:de[l]?\s+)?(\d{4})\b",
    re.IGNORECASE,
)

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

#: Lo que, delante de una fecha, la convierte en una cita y no en un dato del
#: documento. Se mira lo que va justo antes: "Ley 142 de 1994", "Sentencia
#: T-1204 de 2001", "el Artículo 29 de la Constitución".
#:
#: La lista es de normas y providencias a propósito. Un escrito jurídico las
#: nombra por docenas y todas llevan año; ninguna dice cuándo se escribió el
#: papel que las cita.
#: El límite de palabra del principio no es decorativo: sin él, `art` casa
#: dentro de "Cartagena" y la fecha de "Cartagena, 08-02-2022" se descartaba
#: como si fuera la cita de un artículo. Era la fecha de la mitad de los
#: oficios del corpus, que se encabezan con la ciudad delante.
_CITA = re.compile(
    r"\b(?:ley(?:es)?|decreto|sentencias?|resoluci[oó]n(?:es)?|circular"
    r"|acuerdo|art[ií]culo|art\.|numeral|inciso|expediente|radicad[oa]"
    r"|[A-Z]{1,3}-\d{2,4})\b[^.\n]{0,40}$",
    re.IGNORECASE,
)

#: Cuánto texto se mira por delante para decidir si la fecha está citada.
CONTEXTO_DE_CITA = 60

#: El año más antiguo que se le cree a una fecha del propio documento. Por
#: debajo, o es una cita que el filtro no atrapó o es un error de OCR: estos
#: expedientes son de correspondencia viva, no de archivo histórico.
ANIO_MINIMO = 1990


def _valida(dia: int, mes: int, anio: int) -> date | None:
    if not (ANIO_MINIMO <= anio <= 2100):
        return None
    try:
        return date(anio, mes, dia)
    except ValueError:
        # "31/02/2022" y "13/25/2021" salen del OCR más veces de lo que
        # parece: una fecha imposible no es una fecha.
        return None


def _citada(texto: str, inicio: int) -> bool:
    """Si lo que hay justo antes de la fecha la convierte en una cita."""
    return bool(_CITA.search(texto[max(0, inicio - CONTEXTO_DE_CITA) : inicio]))


def fechas_de(texto: str) -> list[date]:
    """Todas las fechas que el texto declara como suyas, en orden de aparición.

    Descarta las imposibles y las citadas. Devuelve lista y no conjunto porque
    el orden en la página es información: la primera fecha de un oficio suele
    ser la suya, y la última de un acta es la de su firma.
    """
    plano = " ".join(texto.split())
    encontradas: list[tuple[int, date]] = []

    for hallazgo in _EN_CIFRAS.finditer(plano):
        dia, mes, anio = (int(g) for g in hallazgo.groups())
        fecha = _valida(dia, mes, anio)
        if fecha is not None and not _citada(plano, hallazgo.start()):
            encontradas.append((hallazgo.start(), fecha))

    for hallazgo in _EN_LETRA.finditer(plano):
        mes = MESES.get(hallazgo.group(2).lower())
        if mes is None:
            continue
        fecha = _valida(int(hallazgo.group(1)), mes, int(hallazgo.group(3)))
        if fecha is not None and not _citada(plano, hallazgo.start()):
            encontradas.append((hallazgo.start(), fecha))

    encontradas.sort()
    return [fecha for _, fecha in encontradas]


def ultima_fecha(paginas: list[str]) -> date | None:
    """La fecha más reciente que aparece en un documento entero.

    Es la que fecha la unidad documental: la fecha extrema final, en el
    vocabulario del FUID. Un oficio se fecha el día que se firma, y si su
    última hoja lleva el acuse de recibo, esa es la fecha que cuenta.

    Se recorre el documento completo y no sólo su primera página, que es lo
    que pidió el operador: un acta con cuatro anexos puede llevar la fecha de
    la visita en la hoja uno y la de la notificación en la última.
    """
    todas = [fecha for pagina in paginas for fecha in fechas_de(pagina)]
    return max(todas) if todas else None


def primera_fecha(paginas: list[str]) -> date | None:
    """La más antigua del documento: la fecha extrema inicial del FUID."""
    todas = [fecha for pagina in paginas for fecha in fechas_de(pagina)]
    return min(todas) if todas else None
