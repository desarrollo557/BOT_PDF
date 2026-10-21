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


#: Los campos de una cédula: una fecha a su lado es la de nacimiento o la de
#: expedición del documento de identidad, nunca la del papel que se archiva.
#: Medido el 2026-10-20 en las cajas de MAGANGUE: «09-SEP-1980 FECHA DE
#: NACIMIENTO» fechaba un acuerdo de pago en 1980.
_DE_LA_CEDULA = re.compile(
    # Con lo que la OCR hace de la palabra: «NACÍMIEMTO» (UPD3102762 p5).
    r"nac[iíl1]m[iíl1]e[nm]t[o0]|estatura|\bg\.?\s*s\.?\s*rh\b|lugar\s+de\s+expedici[oó]n"
    r"|fecha\s+y\s+lugar\s+de\s+expedici|registrad\w*\s+nacional",
    re.IGNORECASE,
)
#: Cuánto texto alrededor se mira para decidir si la fecha es de una cédula.
CONTEXTO_DE_CEDULA = 45


def _citada(texto: str, inicio: int) -> bool:
    """Si lo que hay justo antes de la fecha la convierte en una cita, o es la de una cédula."""
    if _CITA.search(texto[max(0, inicio - CONTEXTO_DE_CITA) : inicio]):
        return True
    alrededor = texto[max(0, inicio - CONTEXTO_DE_CEDULA) : inicio + CONTEXTO_DE_CEDULA + 25]
    return bool(_DE_LA_CEDULA.search(alrededor))


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


#: «VALLEDUPAR, 2020/12/07»: el año delante, como fecha la empresa sus
#: citaciones. Sólo con barras: con guiones es también la forma de los códigos
#: de las guías de envío.
_ANIO_MES_DIA = re.compile(r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b")

#: «día:3 mes:5 del año2021», «Día __03__ Mes __05__ Año __2021__», «dia 3 mes
#: mayo año 2021»: la fecha de un formulario, con cada parte en su casilla. Así
#: firma el CONTRATO DE TRANSACCIÓN de Afinia (UPD2437820 p3), y salía «S.F.»
#: porque ninguna otra regla la reconocía (2026-10-20).
_HUECO = r"\s*[:.\-]?[\s_]*"
_FORMULARIO = re.compile(
    rf"\bd[ií]a{_HUECO}(\d{{1,2}})[\s_,;]*(?:del?\s+)?mes{_HUECO}(\d{{1,2}}|{_MES})[\s_,;]*"
    # Sin `\b` al final: «2021__» no lo cierra, porque `_` cuenta como letra.
    # La raya de la casilla se come, para que la fecha quede suelta.
    rf"(?:del?\s+)?a[ñn]o{_HUECO}(\d{{4}})(?!\d)_*",
    re.IGNORECASE,
)
#: Y el formulario en columnas: los rótulos «DÍA MES AÑO» en un renglón y las
#: cifras debajo, que la OCR deja seguidas: «DIA MES AÑO 03 05 2021».
_FORMULARIO_EN_COLUMNAS = re.compile(
    r"\bD[IÍ]A\W{1,6}MES\W{1,6}A[ÑN]O\W{1,10}(\d{1,2})\W{1,4}(\d{1,2})\W{1,4}(\d{4})\b",
    re.IGNORECASE,
)


#: «26 Nov de 2022», «03-dic-2021», «5 Sept. 2020»: el mes abreviado, como se
#: escribe a mano en el renglón de la fecha de un acta (ACTA DE VERIFICACIÓN DE
#: PREDIO DESOCUPADO, 2026-10-20). Sin él, la fecha salía «S.F.».
_ABREVIADOS = {
    "ene": "enero", "feb": "febrero", "mar": "marzo", "abr": "abril", "may": "mayo",
    "jun": "junio", "jul": "julio", "ago": "agosto", "sep": "septiembre", "sept": "septiembre",
    "set": "septiembre", "oct": "octubre", "nov": "noviembre", "dic": "diciembre",
}
_MES_ABREVIADO = re.compile(
    r"\b(\d{1,2})\s*[,./-]?\s*(ene|feb|mar|abr|may|jun|jul|ago|sept|sep|set|oct|nov|dic)\.?"
    r"(?![a-záéíóúñ])\s*[,./-]?\s*(?:del?\s+)?(\d{4})\b",
    re.IGNORECASE,
)


#: «El Banco 19/10 de 2021», «19 de 10 de 2021»: el día y el mes a mano en los
#: huecos de un formato que trae impreso «___, ____ de 20__». Así lo leyó la IA
#: en el ACTA DE VERIFICACIÓN DE PREDIO DESOCUPADO de UPD2997962 (2026-10-20).
_CIFRAS_Y_DE = re.compile(r"\b(\d{1,2})\s*(?:/|\s+de\s+)\s*(\d{1,2})\s*,?\s+del?\s+(\d{4})\b", re.IGNORECASE)


def _abreviado(hallazgo: re.Match[str]) -> str:
    dia, mes, anio = hallazgo.groups()
    return f"{dia} de {_ABREVIADOS[mes.lower()]} de {anio}"


def _del_formulario(hallazgo: re.Match[str]) -> str:
    dia, mes, anio = hallazgo.groups()
    return f"{dia}/{mes}/{anio}" if mes.isdigit() else f"{dia} de {mes} de {anio}"


def _normalizar(texto: str) -> str:
    """El texto con las fechas escritas como las reconoce :func:`fechas_de`."""
    plano = " ".join(texto.split())
    plano = _ANIO_MES_DIA.sub(r"\3/\2/\1", plano)
    plano = _CIFRAS_CON_ESPACIOS.sub(r"\1\2\3\2\4", plano)
    plano = _FORMULARIO.sub(_del_formulario, plano)
    plano = _FORMULARIO_EN_COLUMNAS.sub(r"\1/\2/\3", plano)
    plano = _MES_ABREVIADO.sub(_abreviado, plano)
    plano = _CIFRAS_Y_DE.sub(r"\1/\2/\3", plano)
    plano = _MES_DIA_ANIO.sub(r"\2 de \1 de \3", plano)
    return _A_LOS_DIAS.sub(r"\1 de \2 de \3", plano)


#: Lo que delata que en una hoja hay una fecha que leer, aunque la OCR no la
#: haya entendido: el rótulo de la fecha, la fórmula de firma, el lugar.
_PISTAS_DE_FECHA = re.compile(
    r"\bfecha\b|\bd[ií]a\b|\bmes\b|\ba[ñn]o\b|\bciudad\s*:|\ba\s*los\s+\S+\s+d[ií]as\b"
    r"|\ben\s+constancia\b|\bse\s+firma\b|\bfirmad[oa]\b|\brecibid[oa]\b",
    re.IGNORECASE,
)


def pistas_de_fecha(texto: str) -> int:
    """Cuántas señales de una fecha por leer trae la hoja; para elegir cuál releer."""
    return len(_PISTAS_DE_FECHA.findall(texto or ""))


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
    encabezado = fecha_del_encabezado(texto, hoy=hoy)
    if encabezado is not None:
        return encabezado
    todas = fechas_de(_normalizar(texto), hoy=hoy)
    return max(todas) if todas else None


def fecha_del_encabezado(texto: str, *, hoy: date | None = None) -> date | None:
    """Sólo la fecha del encabezado «Ciudad, fecha», o ``None`` si no lo lleva.

    Para quien tiene otra fuente mejor que la fecha más reciente de la página:
    el escrito radicado sin encabezado lleva la suya en el sello.
    """
    plano = _normalizar(texto)
    for encabezado in _LUGAR_Y_FECHA.finditer(plano):
        declaradas = fechas_de(encabezado.group(2), hoy=hoy)
        if declaradas:
            return declaradas[0]
    return None


# -- la fecha de expedición de una resolución ------------------------------------

#: Cómo cierra una resolución: «Dada en Cartagena de Indias, a los dieciséis
#: (16) días del mes de enero del año 2025». Es la fecha del documento, y no
#: la más reciente que lleve: detrás vienen sus soportes -- el listado del
#: sistema presupuestal, la resolución del decano, el oficio --, cada uno con
#: sus fechas, y la más reciente de todas fechaba la resolución por un anexo.
_DADA = re.compile(
    r"\b(?:DADA|EXPEDIDA)\s+EN\b.{0,90}?\bA\s+LOS\s+(?P<dia>.{1,45}?)\s+D[I1]AS?\s+DEL?\s+MES\s+DE\s+"
    r"(?P<mes>[A-Z]+)(?P<cola>.{0,40})"
)
_DIA_EN_CIFRAS = re.compile(r"\(\s*(\d{1,2})\s*\)|\b(\d{1,2})\b")
_ANIO = re.compile(r"\b((?:19|20)\d{2})\b")
#: El año del encabezado: «RESOLUCIÓN No. 00004 de 2025». Va impreso, así que
#: suple al de la fecha cuando el OCR lo rompe -- «del añe^lOlS» --.
_ANIO_DEL_ENCABEZADO = re.compile(
    r"\bRESOLUCI[O0]N\s*N\W{0,3}[O0]?\W{0,3}\s*[\d ]{3,8}\s+DE\s+((?:19|20)\d{2})\b"
)
_DIAS_EN_LETRA = {
    "UNO": 1, "UN": 1, "PRIMERO": 1, "DOS": 2, "TRES": 3, "CUATRO": 4, "CINCO": 5,
    "SEIS": 6, "SIETE": 7, "OCHO": 8, "NUEVE": 9, "DIEZ": 10, "ONCE": 11, "DOCE": 12,
    "TRECE": 13, "CATORCE": 14, "QUINCE": 15, "DIECISEIS": 16, "DIECISIETE": 17,
    "DIECIOCHO": 18, "DIECINUEVE": 19, "VEINTE": 20, "VEINTIUNO": 21, "VEINTIUN": 21,
    "VEINTIDOS": 22, "VEINTITRES": 23, "VEINTICUATRO": 24, "VEINTICINCO": 25,
    "VEINTISEIS": 26, "VEINTISIETE": 27, "VEINTIOCHO": 28, "VEINTINUEVE": 29,
    "TREINTA": 30, "TREINTA Y UNO": 31, "TREINTA Y UN": 31,
}


def _plegada(texto: str) -> str:
    import unicodedata

    sin_tildes = unicodedata.normalize("NFD", texto)
    plano = "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn").upper()
    return " ".join(plano.split())


def _dia(trozo: str) -> int | None:
    cifras = _DIA_EN_CIFRAS.search(trozo)
    if cifras:
        return int(cifras.group(1) or cifras.group(2))
    palabras = re.sub(r"[^A-Z ]", " ", trozo).split()
    for largo in (3, 1):
        for inicio in range(len(palabras) - largo + 1):
            dia = _DIAS_EN_LETRA.get(" ".join(palabras[inicio : inicio + largo]))
            if dia:
                return dia
    return None


def fecha_de_expedicion(paginas: list[str], *, hoy: date | None = None) -> date | None:
    """La fecha en que se expidió la resolución, de su fórmula de cierre.

    La primera que aparece, que es la suya: lo que viene detrás son sus
    soportes. El día y el mes salen de la fórmula; el año también, y si el OCR
    lo rompió, del encabezado de la propia resolución, que lo lleva impreso.
    Sin la fórmula no hay fecha de expedición, y quien llama decide qué otra
    usar.
    """
    anio_del_encabezado: int | None = None
    for pagina in paginas:
        plano = _plegada(pagina)
        if anio_del_encabezado is None:
            encabezado = _ANIO_DEL_ENCABEZADO.search(plano)
            if encabezado:
                anio_del_encabezado = int(encabezado.group(1))
        for hallazgo in _DADA.finditer(plano):
            mes = MESES.get(hallazgo.group("mes").lower())
            dia = _dia(hallazgo.group("dia"))
            if mes is None or dia is None:
                continue
            anio = _ANIO.search(hallazgo.group("cola"))
            for candidato in ([int(anio.group(1))] if anio else []) + (
                [anio_del_encabezado] if anio_del_encabezado else []
            ):
                fecha = _valida(dia, mes, candidato, hoy)
                if fecha is not None:
                    return fecha
    return None
