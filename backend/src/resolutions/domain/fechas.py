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


def _valida(dia: int, mes: int, anio: int, hoy: date | None = None) -> date | None:
    if anio < ANIO_MINIMO:
        return None
    try:
        fecha = date(anio, mes, dia)
    except ValueError:
        # "31/02/2022" y "13/25/2021" salen del OCR más veces de lo que
        # parece: una fecha imposible no es una fecha.
        return None
    # Y una fecha que todavía no ha llegado tampoco. Un papel que ya está
    # escaneado no pudo firmarse mañana, así que una fecha futura es siempre un
    # error de lectura: el OCR lee "19/02/2024" y escribe "19/02/2074" porque el
    # 2 y el 7 se parecen en un escaneo malo. Sin este corte esa errata se
    # convertía en la fecha extrema final del expediente -- la más reciente gana
    # -- y el inventario salía diciendo que el documento se cierra en 2074.
    return fecha if fecha <= (hoy or date.today()) else None


def _citada(texto: str, inicio: int) -> bool:
    """Si lo que hay justo antes de la fecha la convierte en una cita."""
    return bool(_CITA.search(texto[max(0, inicio - CONTEXTO_DE_CITA) : inicio]))


def fechas_de(texto: str, *, hoy: date | None = None) -> list[date]:
    """Todas las fechas que el texto declara como suyas, en orden de aparición.

    Descarta las imposibles, las futuras y las citadas. Devuelve lista y no conjunto porque
    el orden en la página es información: la primera fecha de un oficio suele
    ser la suya, y la última de un acta es la de su firma.
    """
    plano = " ".join(texto.split())
    encontradas: list[tuple[int, date]] = []

    for hallazgo in _EN_CIFRAS.finditer(plano):
        dia, mes, anio = (int(g) for g in hallazgo.groups())
        fecha = _valida(dia, mes, anio, hoy)
        if fecha is not None and not _citada(plano, hallazgo.start()):
            encontradas.append((hallazgo.start(), fecha))

    for hallazgo in _EN_LETRA.finditer(plano):
        mes = MESES.get(hallazgo.group(2).lower())
        if mes is None:
            continue
        fecha = _valida(int(hallazgo.group(1)), mes, int(hallazgo.group(3)), hoy)
        if fecha is not None and not _citada(plano, hallazgo.start()):
            encontradas.append((hallazgo.start(), fecha))

    encontradas.sort()
    return [fecha for _, fecha in encontradas]


def ultima_fecha(paginas: list[str], *, hoy: date | None = None) -> date | None:
    """La fecha más reciente que aparece en un documento entero.

    Es la que fecha la unidad documental: la fecha extrema final, en el
    vocabulario del FUID. Un oficio se fecha el día que se firma, y si su
    última hoja lleva el acuse de recibo, esa es la fecha que cuenta.

    Se recorre el documento completo y no sólo su primera página, que es lo
    que pidió el operador: un acta con cuatro anexos puede llevar la fecha de
    la visita en la hoja uno y la de la notificación en la última.
    """
    todas = [fecha for pagina in paginas for fecha in fechas_de(pagina, hoy=hoy)]
    return max(todas) if todas else None


def primera_fecha(paginas: list[str], *, hoy: date | None = None) -> date | None:
    """La más antigua del documento: la fecha extrema inicial del FUID."""
    todas = [fecha for pagina in paginas for fecha in fechas_de(pagina, hoy=hoy)]
    return min(todas) if todas else None


# -- la fecha de una página ---------------------------------------------------

_MES = (
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre"
    "|octubre|noviembre|diciembre"
)

#: «25/ 05/ 2021»: la OCR mete espacios alrededor de las barras de una fecha
#: escaneada, y sin quitarlos la fecha no se reconoce.
_CIFRAS_CON_ESPACIOS = re.compile(r"\b(\d{1,2})\s*([/-])\s*(\d{1,2})\s*\2\s*(\d{4})\b")

#: «Mayo 20 de 2021»: el mes delante del día, como se encabezan algunos oficios.
_MES_DIA_ANIO = re.compile(rf"\b({_MES})\s+(\d{{1,2}})\s*(?:de|,)\s*(\d{{4}})\b", re.IGNORECASE)

#: «a los 26 días del mes de Abril del 2021»: la fórmula con que se firman
#: pagarés, actas y certificados. La OCR suele pegar «alos».
_A_LOS_DIAS = re.compile(
    rf"\ba\s*los\s+(\d{{1,2}})\s+d[ií]as?\s+del\s+mes\s+de\W{{0,4}}({_MES})\s+(?:del?\s+)?(\d{{4}})\b",
    re.IGNORECASE,
)

#: «SAHAGUN, 25/05/2021» o «Sahagun, 07 de Diciembre de 2021»: el lugar y la
#: fecha con que se encabeza una carta. Es la fecha que el papel declara de sí
#: mismo, y por eso manda sobre las demás que haya en la página.
_LUGAR_Y_FECHA = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ.]+(?: [A-Za-zÁÉÍÓÚÑáéíóúñ.]+){0,3}),\s*"
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+de\s+[A-Za-záéíóúñ]+\s+(?:del?\s+)?\d{4})"
)


def _normalizar(texto: str) -> str:
    """El texto con las fechas escritas como las reconoce :func:`fechas_de`."""
    plano = " ".join(texto.split())
    plano = _CIFRAS_CON_ESPACIOS.sub(r"\1\2\3\2\4", plano)
    plano = _MES_DIA_ANIO.sub(r"\2 de \1 de \3", plano)
    return _A_LOS_DIAS.sub(r"\1 de \2 de \3", plano)


def fecha_de_la_pagina(texto: str, *, hoy: date | None = None) -> date | None:
    """La fecha que fecha una página suelta, o ``None`` si no lleva ninguna.

    Primero la del encabezado «Ciudad, fecha», que es la que una carta declara
    de sí misma. Hace falta preferirla porque la más reciente de la página
    engaña: medido sobre un expediente real, una carta encabezada «Cartagena,
    21/12/2021» cita más abajo un plazo del 01/02/2022, y por la más reciente
    habría ido a parar a febrero.

    Sin encabezado, la más reciente de la página, que es lo que la columna
    Fecha del inventario ya significa para cualquier unidad: su fecha extrema
    final. Así se fechan bien la tabla de cuotas de un pagaré, la publicación de
    un aviso o una notificación personal, que no llevan lugar delante.
    """
    plano = _normalizar(texto)
    for encabezado in _LUGAR_Y_FECHA.finditer(plano):
        declaradas = fechas_de(encabezado.group(2), hoy=hoy)
        if declaradas:
            return declaradas[0]
    todas = fechas_de(plano, hoy=hoy)
    return max(todas) if todas else None
