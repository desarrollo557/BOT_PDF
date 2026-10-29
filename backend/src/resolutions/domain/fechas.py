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
#: El «de» entre el día y el mes es opcional: «Talaigua nuevo Bolívar, 07
#: octubre del 2022» (UPD2465747, 2026-10-21) salía «S.F.». Que la palabra sea
#: un mes de verdad lo comprueba `MESES`, así que «12 meses 2021» no casa.
_EN_LETRA = re.compile(
    r"\b(\d{1,2})\s+(?:de\s+)?([a-záéíóúñ]+)\s*,?\s+(?:de[l]?\s+)?(?:a[ñn]o\s+)?(\d{4})\b",
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
_MES_DIA_ANIO = re.compile(rf"\b({_MES})\s+(\d{{1,2}})\s*(?:del?|,)\s*(\d{{4}})\b", re.IGNORECASE)

#: «a los 26 días del mes de Abril del 2021»: la fórmula con que se firman
#: pagarés, actas y certificados. La OCR suele pegar «alos».
_A_LOS_DIAS = re.compile(
    rf"\ba\s*los\s+(\d{{1,2}})\s+d[ií]as?\s+(?:del\s+mes\s+)?de\W{{0,4}}({_MES})\s+(?:del?\s+)?(?:a[ñn]o\s+)?(\d{{4}})\b",
    re.IGNORECASE,
)

#: «SAHAGUN, 25/05/2021» o «Sahagun, 07 de Diciembre de 2021»: el lugar y la
#: fecha con que se encabeza una carta. Es la fecha que el papel declara de sí
#: mismo, y por eso manda sobre las demás que haya en la página.
_LUGAR_Y_FECHA = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ.]+(?: [A-Za-zÁÉÍÓÚÑáéíóúñ.]+){0,3}),\s*"
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+(?:de\s+)?[A-Za-záéíóúñ]+\s+(?:del?\s+)?\d{4})"
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
    # «año», «ano» o «anio», como lo escriben los formularios sin eñe.
    rf"(?:del?\s+)?a(?:[ñn]|ni)o{_HUECO}(\d{{4}})(?!\d)_*",
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


# -- todas las formas de escribir una fecha (2026-10-21) ----------------------------
#
# «Que el bot cubra todas las excepciones posibles» (el operador, ante UPD2465747):
# cada forma con que estos papeles escriben una fecha se lleva aquí a una que
# `fechas_de` reconoce. Ninguna inventa nada: si la parte no es un día, un mes o
# un año de verdad, la fecha no sale.

_UNIDADES = {
    "un": 1, "uno": 1, "una": 1, "primero": 1, "primer": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11,
    "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintiun": 21,
    "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
    "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30,
    "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90,
}


def _sin_tildes(texto: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _numero(palabras: str) -> int | None:
    """«treinta y uno» → 31, «veintidós» → 22; ``None`` si no es un número de dos cifras."""
    total = 0
    for palabra in _sin_tildes(palabras).lower().split():
        if palabra == "y":
            continue
        valor = _UNIDADES.get(palabra)
        if valor is None:
            return None
        total += valor
    return total if 0 < total < 100 else None


_PALABRA_DE_NUMERO = r"(?:y|un[oa]?|primer[o]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince|diecis[eé]is|diecisiete|dieciocho|diecinueve|veinte|veinti\w+|treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa)"
#: «dos mil veintidós», «mil novecientos noventa y ocho»: el año en letra.
_ANIO_EN_LETRA = re.compile(
    rf"\b(dos\s+mil|mil\s+novecientos)((?:\s+{_PALABRA_DE_NUMERO})*)\b", re.IGNORECASE
)


def _anio_en_letra(hallazgo: re.Match[str]) -> str:
    base = 2000 if hallazgo.group(1).lower().startswith("dos") else 1900
    resto = hallazgo.group(2).strip()
    if not resto:
        return str(base) if base == 2000 else hallazgo.group(0)
    numero = _numero(resto)
    return str(base + numero) if numero is not None else hallazgo.group(0)


#: «siete (7) de octubre», «veintiuno (21) días»: el día en letra con la cifra al lado.
_DIA_CON_CIFRA = re.compile(rf"\b{_PALABRA_DE_NUMERO}(?:\s+y\s+\w+)?\s*\(\s*(\d{{1,2}})\s*\)", re.IGNORECASE)
#: «siete de octubre», «primero de mayo», «treinta y uno de diciembre»: sólo letra.
_DIA_EN_LETRA = re.compile(
    rf"\b({_PALABRA_DE_NUMERO}(?:\s+y\s+{_PALABRA_DE_NUMERO})?)(\s+(?:d[ií]as?\s+del\s+mes\s+)?de\s+(?:{_MES})\b)",
    re.IGNORECASE,
)


def _dia_en_letra(hallazgo: re.Match[str]) -> str:
    numero = _numero(hallazgo.group(1))
    return f"{numero}{hallazgo.group(2)}" if numero is not None and numero <= 31 else hallazgo.group(0)


#: «07.10.2022»: con puntos.
_CON_PUNTOS = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
#: «07/10/22»: el año con dos cifras, sólo con barras (con guiones es un código).
_ANIO_CORTO = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b(?![/\d])")
#: «de 2.022»: el año con el punto de los miles, como se escribe una cifra.
_ANIO_CON_PUNTO = re.compile(r"\b(del?\s+(?:a[ñn]o\s+)?)([12])\.(\d{3})\b", re.IGNORECASE)
#: «Fecha de emisión: 2022-10-07»: el año delante con guiones, sólo tras el
#: rótulo de una fecha (sin él, con guiones es un código de guía).
_ISO_CON_ROTULO = re.compile(r"(\bfecha\b[^\d\n]{0,25})(\d{4})-(\d{1,2})-(\d{1,2})\b", re.IGNORECASE)
#: La «O» que la OCR lee en lugar de un cero dentro de una cifra: «O7/1O/2O22».
#: Sólo la que no va pegada a una letra: la «o» de «año2021» es una letra.
_O_POR_CERO = re.compile(r"(?<=\d)[Oo](?=[\d/.\-]|\s|$)|(?<![^\W\d_])[Oo](?=\d)")


def _anio_corto(hallazgo: re.Match[str]) -> str:
    from datetime import date as _date

    dia, mes, corto = hallazgo.groups()
    anio = 2000 + int(corto)
    if anio > _date.today().year:
        anio -= 100
    return f"{dia}/{mes}/{anio}"


def _todas_las_formas(plano: str) -> str:
    """Las formas raras de una fecha, llevadas a una que `fechas_de` reconoce."""
    plano = _O_POR_CERO.sub("0", plano)
    plano = _ANIO_EN_LETRA.sub(_anio_en_letra, plano)
    plano = _DIA_CON_CIFRA.sub(r"\1", plano)
    plano = _DIA_EN_LETRA.sub(_dia_en_letra, plano)
    plano = _ISO_CON_ROTULO.sub(r"\1\4/\3/\2", plano)
    plano = _CON_PUNTOS.sub(r"\1/\2/\3", plano)
    plano = _ANIO_CORTO.sub(_anio_corto, plano)
    return _ANIO_CON_PUNTO.sub(r"\1\2\3", plano)


def _del_formulario(hallazgo: re.Match[str]) -> str:
    dia, mes, anio = hallazgo.groups()
    return f"{dia}/{mes}/{anio}" if mes.isdigit() else f"{dia} de {mes} de {anio}"


def _normalizar(texto: str) -> str:
    """El texto con las fechas escritas como las reconoce :func:`fechas_de`."""
    plano = " ".join(texto.split())
    plano = _todas_las_formas(plano)
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
    # La de las casillas de un formulario, que es la del papel aunque la
    # página traiga otras: la fecha del pago de un comprobante.
    casillas = fecha_de_las_casillas(texto, hoy=hoy)
    if casillas is not None:
        return casillas
    todas = fechas_de(_normalizar(texto), hoy=hoy)
    return max(todas) if todas else None


#: Los rótulos de las casillas de una fecha: «DIA MES AÑO», «DÍA | MES | ANIO»,
#: «DIA MES ANO». Así fecha el COMPROBANTE CUPÓN MANUAL (UPD2973860, 2026-10-21).
_ROTULOS_DE_CASILLAS = re.compile(r"\bD[IÍ]A\b\W{1,15}\bMES\b\W{1,15}\bA(?:[ÑN]|NI)?O\b", re.IGNORECASE)
#: Hasta dónde se buscan, tras los rótulos, las cifras de la fecha.
_ALCANCE_DE_LAS_CASILLAS = 260
_TRES_CIFRAS = re.compile(r"(?<!\d)(\d{1,2})\W{1,6}(\d{1,2})\W{1,6}((?:19|20)\d{2})(?!\d)")


def fecha_de_las_casillas(texto: str, *, hoy: date | None = None) -> date | None:
    """La fecha escrita en las casillas DÍA / MES / AÑO de un formulario.

    Tras los rótulos, el primer día-mes-año que sea una fecha de verdad. Las
    cifras llegan como las deja quien las lee: en una tabla, en negrita, o
    pegadas a las de la casilla vecina -- la IA leyó «9 16 09 08 2022», con el
    final del ID de cobros delante --; se prueba desde cada posición y vale la
    primera que forma una fecha.
    """
    plano = _O_POR_CERO.sub("0", " ".join((texto or "").split()))
    for rotulo in _ROTULOS_DE_CASILLAS.finditer(plano):
        tramo = plano[rotulo.end() : rotulo.end() + _ALCANCE_DE_LAS_CASILLAS]
        for inicio in range(len(tramo)):
            hallado = _TRES_CIFRAS.match(tramo, inicio)
            if hallado is None:
                continue
            fecha = _valida(int(hallado.group(1)), int(hallado.group(2)), int(hallado.group(3)), hoy)
            if fecha is not None:
                return fecha
    return None


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
#: «Dada» o «Dado»: la 00384 dice «Dado en Cartagena» (2026-10-29), y sin
#: reconocerlo se fechaba por el soporte del decano que lleva detrás.
#:
#: Y tal como la deja el OCR, medido en la carpeta 3220 - 3259 el mismo día:
#: «a 19 días de diciembre» (sin «los» ni «del mes»), «a ios dipcinueve (19)
#: días del mes de diciemb^ de 2.025», «de IndiasjJ^/Cftpcinueve (19) días…».
#: Por eso el día es lo que hay entre el lugar y «días» -- la cifra entre
#: paréntesis, si la hay --, y el mes se reconoce por su raíz (``_mes``).
#: «Días» va con sus bordes de palabra: «Indias» lo lleva dentro.
_DADA = re.compile(
    r"\b(?:DAD[AO]|EXPEDID[AO])\s+EN\b(?P<dia>.{1,90}?)\bD[I1]AS?\b\W{0,3}(?:DEL?\s+MES\s+)?DE\s*"
    r"(?P<mes>[A-Z]{3,})(?P<cola>.{0,40})"
)
#: «2.025»: el año con punto de miles, como lo escribe la fórmula.
_ANIO_CON_PUNTO_DE_MILES = re.compile(r"\b2[.,]0(\d{2})\b")
#: El número que declara el encabezado de una página, para saber si ya es otra
#: resolución: la del decano o la copia que viene detrás.
_NUMERO_DEL_ENCABEZADO = re.compile(r"\bRESOLUCI[O0]N\s*N\W{0,3}[O0]?\W{0,3}\s*(\d[\d ]{0,7}\d|\d)")
#: Cuánto del principio de una página es su encabezado.
_CABEZA = 400
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


def _mes(palabra: str) -> int | None:
    """El mes por su raíz: «DICIEMTMP», «DICIEMB^» o «DICIEMBRPYDE» son diciembre."""
    palabra = palabra.lower()
    for nombre, numero in MESES.items():
        if palabra.startswith(nombre[:5]):
            return numero
    return None


def _es_otra_resolucion(plano: str, numero: str) -> bool:
    """Si el encabezado de la página declara una resolución distinta de ``numero``."""
    hallado = _NUMERO_DEL_ENCABEZADO.search(plano[:_CABEZA])
    if hallado is None or not numero.isdigit():
        return False
    return int(hallado.group(1).replace(" ", "")) != int(numero)


def fecha_de_expedicion(
    paginas: list[str], *, numero: str | None = None, hoy: date | None = None
) -> date | None:
    """La fecha en que se expidió la resolución, de su fórmula de cierre.

    La primera que aparece, que es la suya: lo que viene detrás son sus
    soportes. El día y el mes salen de la fórmula; el año también, y si el OCR
    lo rompió, del encabezado de la propia resolución, que lo lleva impreso.
    Sin la fórmula no hay fecha de expedición, y quien llama decide qué otra
    usar.

    Con ``numero`` se deja de buscar en la primera página -- después de la
    primera, que es la suya -- que encabeza otra resolución: si la fórmula
    propia no se dejó leer, la del decano o la de una copia que viene detrás
    no es la suya (la 00390 se fechaba por la del decano, 2026-10-29).
    """
    anio_del_encabezado: int | None = None
    for indice, pagina in enumerate(paginas):
        plano = _plegada(pagina)
        if numero and indice and _es_otra_resolucion(plano, numero):
            break
        if anio_del_encabezado is None:
            encabezado = _ANIO_DEL_ENCABEZADO.search(plano)
            if encabezado:
                anio_del_encabezado = int(encabezado.group(1))
        for hallazgo in _DADA.finditer(plano):
            mes = _mes(hallazgo.group("mes"))
            dia = _dia(hallazgo.group("dia"))
            if mes is None or dia is None:
                continue
            anio = _ANIO.search(_ANIO_CON_PUNTO_DE_MILES.sub(r"20\1", hallazgo.group("cola")))
            for candidato in ([int(anio.group(1))] if anio else []) + (
                [anio_del_encabezado] if anio_del_encabezado else []
            ):
                fecha = _valida(dia, mes, candidato, hoy)
                if fecha is not None:
                    return fecha
    return None
