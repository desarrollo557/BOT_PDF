"""La fecha de un documento de Afinia, leída donde su estructura la pone.

Lo dictó el operador el 2026-11-10, ante la corrida «sinfecha»: «la fecha la
tomarás del documento principal, el día en que se creó el documento; cuando
exista un sello, la fecha que esté dentro del sello». Y enseguida: «la hoja
principal no siempre es la primera, por ejemplo la del acuerdo de pago».

Hasta entonces la caja se fechaba con la primera hoja fechada del documento o,
sin ella, con la fecha más reciente de cualquiera de sus hojas. Medido sobre
309 documentos de 125 PDF revisados contra el papel, eso fechaba con lo que
no era el documento:

* un **anexo** -- el certificado de Cámara de Comercio de 2012 en un acuerdo de
  2020, la factura en una solicitud, el certificado de tradición --;
* un **plazo** -- «le será notificada a más tardar el 25/05/2021» en la
  constancia, «FECHA DE ATENCION VENCE», la tabla «Fecha Vto.» de la carta de
  instrucciones, «Suspensión a partir de» en la factura --;
* una **cita** del cuerpo -- «recibido el día…», la fecha del acta en la
  respuesta --;
* **la hoja equivocada** -- el aviso escaneado junto a su publicación, las
  casillas de la guía de LECTA que acompaña a la citación --.

Aquí cada documento se fecha así:

1. **El sello** de radicación de sus hojas, si trae fecha: manda (el operador).
2. **La hoja principal**, reconocida por lo que dice y no por su posición
   (``hoja_principal``), y en ella **el sitio donde ese tipo pone su fecha**:
   el encabezado del reconocimiento de deuda, «se publica el día» en la
   publicación del aviso, «En la fecha … compareció» en la notificación
   personal, «A los 9 días del mes 12 del 2021» en el acta de revisión, el
   «FECHA:» tras el N° PQR de la constancia, el sello de la caja en el
   comprobante… Cada tipo dice sólo su sitio: ninguna otra fecha de la hoja
   cuenta.
3. **Los respaldos** del mismo documento cuyo sitio también es seguro: en el
   acuerdo de pago, la firma de la carta de instrucciones («Firmado en … a los
   … días del mes de … del …», coincidió con el reconocimiento en 14 de 14) y
   la Ley Habeas Data (8 de 8).
4. Si ninguno la da, ``None``: quien llama relee **la hoja principal** (en
   local y, si el operador eligió IA, con ella) con :func:`fecha_de_la_hoja`, y
   si tampoco, la fecha de su trámite. **Nunca un anexo**: cédula, factura,
   certificados, pagaré, simulador ni la guía que acompaña una carta.

Aquí no se lee papel: entra el texto de cada hoja y lo que el sello dijo.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from .anexos_declarados import clase_de_la_hoja
from .carta import abre_carta
from .fechas import (
    _FORMULARIO,
    _LUGAR_Y_FECHA,
    MESES,
    _normalizar,
    _valida,
    fecha_de_las_casillas,
    fecha_del_encabezado,
    fechas_de,
)
from .sello import es_guia_de_envio, numero_del_acta_de_suspension
from .tramites import es_cedula


def _plano(texto: str) -> str:
    """Sin tildes, en mayúsculas y con un solo espacio: donde se buscan los rótulos."""
    sin_tildes = (
        unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode()
    )
    return " ".join(sin_tildes.upper().split())


_FECHA_EN_CIFRAS = r"(\d{1,2})\s?[/\-.]\s?(\d{1,2})\s?[/\-.]?\s?(\d{4})"
_MES = "|".join(sorted({m.upper() for m in MESES}, key=len, reverse=True))
_FECHA_EN_LETRA = (
    rf"(\d{{1,2}})\s+(?:DE\s+)?({_MES})\s+(?:DE[L]?\s+)?(?:ANO\s+)?(\d{{4}})"
)


def _en_cifras(
    hallado: re.Match[str] | None, hoy: date | None, *, mes_primero: bool = False
) -> date | None:
    if hallado is None:
        return None
    a, b, anio = (int(g) for g in hallado.groups()[-3:])
    dia, mes = (b, a) if mes_primero else (a, b)
    return _valida(dia, mes, anio, hoy)


def _tras(rotulo: str, plano: str, hoy: date | None, *, alcance: int = 40) -> date | None:
    """La primera fecha, en cifras o en letra, justo detrás de un rótulo."""
    for ancla in re.finditer(rotulo, plano):
        tramo = plano[ancla.end() : ancla.end() + alcance]
        cifras = re.match(rf"\W*{_FECHA_EN_CIFRAS}", tramo)
        if cifras and (fecha := _en_cifras(cifras, hoy)):
            return fecha
        letra = re.match(rf"\W*{_FECHA_EN_LETRA}", tramo)
        if letra:
            mes = MESES.get(letra.group(2).lower())
            if mes and (
                fecha := _valida(int(letra.group(1)), mes, int(letra.group(3)), hoy)
            ):
                return fecha
    return None


# -- las trampas: fechas que una hoja lleva y no son la suya ---------------------

#: Lo que, delante de una fecha, dice que no es la del documento: un plazo, un
#: vencimiento, la lectura anterior, lo que el cuerpo cita de otro papel.
#: Medido en el corpus de Afinia (2026-11-10), una a una:
_TRAMPAS = re.compile(
    r"A\s*MAS\s+TARDAR(?:\s+EL)?"  # el plazo de la constancia
    r"|ATENCION\s+VENCE|\bVENCE\b\W{0,3}|FECHA\s+(?:DE\s+)?VENCIMIENTO|FECHA\s+VTO\W?"
    r"|SUSPENSION\s+A\s+PARTIR\s+DE\W?|PAGO\s+OPORTUNO\W?|FECHA\s+ULTIMO\s+PAGO\W?"
    r"|FECHA\s+ULTIMA\s+LECTURA\W?|FECHA\s+LECTURA\s+ACTUAL\W?|PERIODO\s+FACTURADO\W?"
    r"|MESES\s+POR\s+LO\s+QUE\s+RECLAMA\W?|IMPRESO\s+EL"
    r"|(?:PRESENTAD|RECIBID|RADICAD|INTERPUEST|NOTIFICAD)[OA]S?\s+(?:EL\s+)?(?:DIA\s+)?"
    r"|ME\s+NOTIFIQUE\s+(?:EL\s+)?|DE\s+FECHA|FECHA\s+DEL\s+ACTO\s+QUE\s+SE\s+NOTIFICA\W?"
    r"|DOCUMENTO\s+PRIVADO\s+DEL|FECHA\s+DE\s+NACIMIENTO|FECHA\s+Y\s+LUGAR\s+DE\s+EXPEDICION"
)
#: Cuánto texto detrás del rótulo de una trampa se tacha.
_ALCANCE_DE_LA_TRAMPA = 45


def sin_trampas(texto: str) -> str:
    """El texto plano con las fechas de las trampas tachadas (sus cifras, por «#»)."""
    plano = _plano(texto)
    partes: list[str] = []
    fin = 0
    for trampa in _TRAMPAS.finditer(plano):
        if trampa.start() < fin:
            continue
        hasta = trampa.end() + _ALCANCE_DE_LA_TRAMPA
        partes.append(plano[fin : trampa.end()])
        partes.append(re.sub(r"\d", "#", plano[trampa.end() : hasta]))
        fin = hasta
    partes.append(plano[fin:])
    return "".join(partes)


# -- las piezas: qué hoja es y dónde pone su fecha -------------------------------


@dataclass(frozen=True, slots=True)
class Pieza:
    """Una clase de hoja de una caja de Afinia."""

    nombre: str
    #: Cuánto manda para ser la hoja principal: menos, más. Los anexos, 100.
    rango: int
    #: Dónde pone su fecha, leída del texto plano; ``None`` si no la pone.
    fecha: Callable[[str, date | None], date | None] | None = None
    #: Si su fecha respalda la del documento cuando la principal no la deja leer.
    respaldo: bool = False

    @property
    def anexo(self) -> bool:
        return self.rango >= RANGO_DE_ANEXO


RANGO_DE_ANEXO = 100
#: Lo que abre un documento: la publicación, la notificación, el acta, la
#: constancia, la carta de la empresa, el escrito radicado. Entre ellas no hay
#: jerarquía: en un corte que trae dos, manda la primera -- la que lo abre --.
#: Sólo las partes del acuerdo de pago ceden ante su reconocimiento.
ABRE = 5
#: La hoja que no se reconoce: el escrito del cliente, una carta, una hoja de
#: continuación. Manda sobre los anexos y cede ante cualquier pieza conocida.
RANGO_SIN_RECONOCER = 50


def _del_reconocimiento(texto: str, hoy: date | None) -> date | None:
    """«El Banco, 23 de 12 de 2020» encima de «Señores:»: el encabezado de la hoja."""
    cabeza = re.split(r"(?i)se[ñn]ores", texto or "", maxsplit=1)[0]
    if (fecha := fecha_del_encabezado(cabeza, hoy=hoy)) is not None:
        return fecha
    todas = fechas_de(_normalizar(cabeza), hoy=hoy)
    return todas[0] if todas else None


def _de_la_firma(texto: str, hoy: date | None) -> date | None:
    """«Firmado en la ciudad de X a los 24 días del mes de Mayo del 2024».

    La capa de texto de estas hojas desordena las palabras -- «del 2021
    MAGANGUE a los 6 días del mes de Abril Firmado en» --, así que el día, el
    mes y el año se buscan cada uno alrededor del rótulo, no como una frase.
    """
    plano = _plano(texto)
    for ancla in re.finditer(r"FIRMADO\s+EN|EN\s+CONSTANCIA\s+SE\s+SUSCRIBE", plano):
        tramo = plano[max(0, ancla.start() - 90) : ancla.end() + 160]
        dia = re.search(r"A\s*LOS\s+(\d{1,2})\s+DIAS|\bDIA\W{0,3}\s*(\d{1,2})\b", tramo)
        mes = re.search(rf"\bMES\W{{0,3}}\s*(?:DE\s+)?({_MES}|\d{{1,2}})\b", tramo)
        anio = re.search(
            r"\bDEL?\s+(?:ANO\s+)?((?:19|20)\d{2})\b|\bANO\W{0,3}\s*((?:19|20)\d{2})\b",
            tramo,
        )
        if not (dia and mes and anio):
            continue
        d = int(dia.group(1) or dia.group(2))
        m = (
            int(mes.group(1))
            if mes.group(1).isdigit()
            else MESES.get(mes.group(1).lower())
        )
        a = int(anio.group(1) or anio.group(2))
        if m and (fecha := _valida(d, m, a, hoy)):
            return fecha
    return None


def _del_formulario(texto: str, hoy: date | None) -> date | None:
    """«Día 25 Mes 03 Año 2022»: cada parte en su casilla, con la cifra al lado."""
    hallado = _FORMULARIO.search(" ".join((texto or "").split()))
    if hallado is None:
        return None
    dia, mes, anio = hallado.groups()
    m = int(mes) if mes.isdigit() else MESES.get(mes.lower())
    return _valida(int(dia), m, int(anio), hoy) if m else None


def _del_habeas(texto: str, hoy: date | None) -> date | None:
    """Las casillas «Día __ Mes __ Año __» de arriba, o el «Fecha:» del pie."""
    plano = _plano(texto)
    return (
        _del_formulario(texto, hoy)
        or fecha_de_las_casillas(texto or "", hoy=hoy)
        or _tras(r"\bFECHA\s*[:;.]", plano, hoy)
        or _tras(r"\bEL\s+DIA", plano, hoy)
        or fecha_del_encabezado(texto or "", hoy=hoy)
    )


def _de_la_publicacion(texto: str, hoy: date | None) -> date | None:
    """«El presente aviso se publica el día 28/06/2021 06:01:45.0»."""
    plano = _plano(texto)
    return _tras(r"SE\s+PUBLICA\s+EL\s+DIA", plano, hoy)


def _de_la_notificacion(texto: str, hoy: date | None) -> date | None:
    """«En la fecha 10 de agosto de 2023 compareció», o «Fecha real notificación cliente»."""
    plano = _plano(texto)
    return _tras(r"EN\s+LA\s+FECHA", plano, hoy) or _tras(
        r"FECHA\s+REAL\s+(?:DE\s+)?NOTIFICACION\s+(?:AL\s+)?CLIENTE", plano, hoy
    )


_DEL_ACTA = re.compile(
    r"A\s*LOS\s+(\d{1,2})\s+DIAS\s+DEL\s+MES\s+(?:DE\s+)?(\d{1,2}|[A-Z]+)\s+DEL?\s+(?:ANO\s+)?(\d{4})"
)


def _del_acta(texto: str, hoy: date | None) -> date | None:
    """«A los 9 días del mes 12 del 2021 se hace presente en el inmueble…».

    Nunca la «Fecha lectura actual» (viene mes/día: «12/9/2021» es el 9 de
    diciembre) ni la «Fecha última lectura», que es la del ciclo anterior.
    """
    plano = _plano(texto)
    for hallado in _DEL_ACTA.finditer(plano):
        mes = hallado.group(2)
        m = int(mes) if mes.isdigit() else MESES.get(mes.lower())
        if m and (fecha := _valida(int(hallado.group(1)), m, int(hallado.group(3)), hoy)):
            return fecha
    return None


def _de_la_liquidacion(texto: str, hoy: date | None) -> date | None:
    """La casilla «Fecha:» de la liquidación CNRPF, impresa **mes/día/año**.

    «4/20/2021» -- un mes 20 no existe -- y «12/10/2021», un día después del
    acta del 9 de diciembre, lo prueban. La capa la deja en la cabeza de la
    hoja, desordenada: es la primera fecha de esa cabeza.
    """
    plano = _plano(texto)
    cabeza = plano[:500]
    for hallado in re.finditer(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)", cabeza):
        if (fecha := _en_cifras(hallado, hoy, mes_primero=True)) is not None:
            return fecha
    return None


def _de_la_suspension(texto: str, hoy: date | None) -> date | None:
    """La casilla FECHA del acta de suspensión, a mano: casi nunca está en la capa."""
    plano = _plano(texto)
    return _tras(r"\bFECHA\b", plano, hoy, alcance=30)


def _de_la_constancia(texto: str, hoy: date | None) -> date | None:
    """«N° PQR: RE… FECHA: 08/04/2022»: la fecha de radicación, junto a su RE.

    La constancia no lleva sello: ella es el comprobante del radicado.
    """
    plano = _plano(texto)
    return (
        _tras(r"FECHA\s+DE\s+RECEPCION\s*[:;.]?", plano, hoy)
        or _tras(r"PQR\W{0,4}\s*RE\s?\d[\d ]{9,16}\s*FECHA\s*[:;.]?", plano, hoy)
        or _tras(r"(?<!VENCE )(?<!ATENCION )\bFECHA\s*[:;.]", plano, hoy, alcance=30)
    )


def _de_la_contratacion(texto: str, hoy: date | None) -> date | None:
    """«Numero: <NIC> / Fecha dd/mm/aaaa», arriba a la derecha."""
    plano = _plano(texto)
    return _tras(r"\bFECHA\b\s*[:;.]?", plano, hoy, alcance=30)


def _de_la_visita(texto: str, hoy: date | None) -> date | None:
    """«En ___ a los 13 días del mes de Agosto de 2022, siendo las…», a mano."""
    return _del_acta(texto, hoy)


#: Lo que hay detrás de «Consecutivo No.» hasta su fecha: el número y la ciudad.
_TRAS_EL_CONSECUTIVO = 160
#: La cabeza de una carta de la empresa: «Consecutivo No.202270389336 AGUSTIN
#: CODAZZI, 19/09/2022». El número y, **justo detrás**, la ciudad y la fecha.
#: Un recurso del cliente también nombra el consecutivo que recurre --
#: «CONSECUTIVO No 202270274611 DEL 15/07/2022 (RECIBIDO EL DIA, MARTES,
#: 19/07/2022…» (DOCUMENTO_35) -- y no es una carta de la empresa.
_CABEZA_DE_LA_EMPRESA = re.compile(
    r"CONSECUTIVO\s+N\W?O\W{0,3}\s*(?:[A-Z]{1,2}\s?)?\d{9,16}\s+(?!DEL?\b)[A-Z][A-Z .]{2,40},\s*(?:[A-Z]+[ ,]\s*)?\d"
)


def _de_la_carta_de_la_empresa(texto: str, hoy: date | None) -> date | None:
    """La línea «CIUDAD, fecha» bajo el «Consecutivo No.» de la respuesta o el aviso.

    Sólo ésa: el cuerpo cita la fecha del reclamo, de la factura, del acta. La
    OCR a veces se come la barra del año: «22/02 2022».
    """
    llano = " ".join((texto or "").split())
    for ancla in re.finditer(r"(?i)consecutivo\s+n\W?o", llano):
        crudo = llano[ancla.end() : ancla.end() + _TRAS_EL_CONSECUTIVO]
        if not _CABEZA_DE_LA_EMPRESA.match(
            _plano(llano[ancla.start() : ancla.end() + _TRAS_EL_CONSECUTIVO])
        ):
            continue
        if (fecha := fecha_del_encabezado(crudo, hoy=hoy)) is not None:
            return fecha
        tramo = _plano(crudo)
        al_reves = re.search(r",\s*(\d{4})/(\d{1,2})/(\d{1,2})\b", tramo)
        if al_reves and (
            fecha := _valida(
                int(al_reves.group(3)),
                int(al_reves.group(2)),
                int(al_reves.group(1)),
                hoy,
            )
        ):
            return fecha
        hallado = re.search(rf",\s*{_FECHA_EN_CIFRAS}", tramo)
        if hallado and (fecha := _en_cifras(hallado, hoy)):
            return fecha
        letra = re.search(rf",\s*(?:[A-Z]+,\s*)?{_FECHA_EN_LETRA}", tramo)
        if (
            letra
            and (mes := MESES.get(letra.group(2).lower()))
            and (fecha := _valida(int(letra.group(1)), mes, int(letra.group(3)), hoy))
        ):
            return fecha
        mes_delante = re.search(rf",\s*({_MES})\s+(\d{{1,2}})\s+DE\s+(\d{{4}})", tramo)
        if mes_delante and (
            fecha := _valida(
                int(mes_delante.group(2)),
                MESES[mes_delante.group(1).lower()],
                int(mes_delante.group(3)),
                hoy,
            )
        ):
            return fecha
    return None


_MES_CORTO = {
    "ENE": 1,
    "FEB": 2,
    "MAR": 3,
    "ABR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SEP": 9,
    "SET": 9,
    "OCT": 10,
    "NOV": 11,
    "DIC": 12,
}
#: El sello de la caja recaudadora: «25 ABR 2022», que la capa deja partido,
#: «2 5 ABR 2022» -- y así salía el 5 de abril --.
_SELLO_DE_RECAUDO = re.compile(
    r"(?<![\d/])(\d)\s?(\d)?\s*(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEPT?|SET|OCT|NOV|DIC)\W{0,2}\s*((?:19|20)\d{2})(?!\d)"
)


def _del_sello_de_recaudo(plano: str, hoy: date | None) -> date | None:
    for hallado in _SELLO_DE_RECAUDO.finditer(plano):
        dia = int(hallado.group(1) + (hallado.group(2) or ""))
        mes = _MES_CORTO[hallado.group(3)[:3]]
        if (fecha := _valida(dia, mes, int(hallado.group(4)), hoy)) is not None:
            return fecha
    return None


def _del_comprobante(texto: str, hoy: date | None) -> date | None:
    """El sello de la caja; si no se deja leer, las casillas DÍA / MES / AÑO.

    Nunca el «Nro. 3014202203100000…», que lleva dentro algo con forma de
    fecha (20220310) y es el número del cupón.
    """
    return _del_sello_de_recaudo(_plano(texto), hoy) or fecha_de_las_casillas(
        texto or "", hoy=hoy
    )


def _de_la_factura(texto: str, hoy: date | None) -> date | None:
    """Sólo el sello de la caja (pagada): el resto de sus fechas son plazos y periodos."""
    plano = _plano(texto)
    return _del_sello_de_recaudo(plano, hoy)


def _del_escrito(texto: str, hoy: date | None) -> date | None:
    """El escrito del cliente: el sello que la capa deje leer, o su encabezado.

    Nada del cuerpo: el «REF:» de un recurso cita la factura, el acta y el día
    en que se notificó, y ninguna es la del escrito.
    """
    plano = _plano(texto)
    return (
        _tras(r"FECHA\s+DE\s+RECIBIDO\s*[:;.]?", plano, hoy)
        or _del_rotulo_del_sello(plano, hoy)
        or _del_encabezado_de_la_cabeza(texto, hoy)
    )


#: El rótulo impreso de la etiqueta de radicación: «Fecha: 08/09/2021
#: 09:17:47.0». Con la hora: «FECHA: 10/12/2021, FACTURADO SEGÚN LA FACTURA»
#: es lo que el «REF:» de un recurso cita (UPD2365925 p36), no su radicación.
_ROTULO_DEL_SELLO = re.compile(
    rf"\bFECHA\s*(?:DE\s+RECIBO\s*)?[:;.]\W{{0,3}}{_FECHA_EN_CIFRAS}\W{{0,3}}\s*\d{{1,2}}\s?[:.]\s?\d{{2}}"
)
#: Y su firma, aunque la OCR rompa el rótulo -- «l'oeliii: 21/01/2022
#: 14:47:03.0», «Eecliu; 25/03/2022 I4;47.'54.0» (caja 108) --: la fecha con
#: la hora, los minutos y los segundos detrás, como sólo la imprime la etiqueta.
_FIRMA_DEL_ROTULO = re.compile(
    # La hora con «:» o «;»: «09/05/2024 1 14.260» es un importe, no una hora.
    r"(?<!\d)(\d{1,2})\s?/\s?(\d{1,2})\s?/\s?(\d{4})\W{0,2}\s*[\dIL]{1,2}\s?[:;]\s?\d{2}\W{1,3}\d{2}\W?[O0]\b"
)


def _del_rotulo_del_sello(plano: str, hoy: date | None) -> date | None:
    for patron in (_ROTULO_DEL_SELLO, _FIRMA_DEL_ROTULO):
        for hallado in patron.finditer(plano):
            if (fecha := _en_cifras(hallado, hoy)) is not None:
                return fecha
    return None


#: Hasta dónde llega la cabeza de una hoja: donde va el «Ciudad, fecha» de una carta.
_CABEZA_DE_LA_HOJA = 350
_DIAS_DE_LA_SEMANA = re.compile(
    r"(?i)^(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b"
)
#: Y con punto en vez de coma: «Santa Rosa del Sur – Bolívar. Julio 15 de 2021»
#: (1016215, UPD2437946 p1, 2026-11-11), que salía «S.F.». Sólo con la fecha en
#: letras, ya normalizada a «15 de Julio de 2021»: un punto seguido de cifras es
#: también el final de una frase que cita un número.
_LUGAR_PUNTO_Y_FECHA = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]+(?:\s*[-–]?\s*[A-Za-zÁÉÍÓÚÑáéíóúñ]+){0,5})\.\s+"
    r"(\d{1,2}\s+de\s+[A-Za-záéíóúñ]+\s+del?\s+\d{4})"
)


def _del_encabezado_de_la_cabeza(texto: str, hoy: date | None) -> date | None:
    """«Talaigua nuevo Bolívar, 20 de diciembre de 2023»: sólo en la cabeza de la hoja.

    Más abajo, «Ciudad, fecha» es lo que el cuerpo cita: «(RECIBIDO EL DÍA,
    MARTES, 19/07/2022…» (DOCUMENTO_35). Y un día de la semana no es una ciudad.
    """
    cabeza = " ".join((texto or "").split())[:_CABEZA_DE_LA_HOJA]
    normalizada = _normalizar(cabeza)
    for patron in (_LUGAR_Y_FECHA, _LUGAR_PUNTO_Y_FECHA):
        for encabezado in patron.finditer(normalizada):
            if _DIAS_DE_LA_SEMANA.match(encabezado.group(1).strip()):
                continue
            declaradas = fechas_de(encabezado.group(2), hoy=hoy)
            if declaradas:
                return declaradas[0]
    return None


#: Hasta dónde llega la cabeza de un formulario para su rótulo «FECHA:».
_CABEZA_DEL_FORMULARIO = 400
_ROTULO_DE_LA_FECHA = re.compile(r"\bFECHA\s*[:;.]")
#: Lo que, poco antes del rótulo, dice que la fecha es de otro papel: lo que
#: un recurso cita en su referencia.
_CITA_DE_OTRO_PAPEL = re.compile(r"\bREF\b|REFERENCIA|ASUNTO")
_ANTES_DEL_ROTULO = 150


def fecha_razonada(texto: str, hoy: date | None = None) -> date | None:
    """La fecha de una hoja sin estructura conocida, razonada: la de su rótulo «FECHA:» en la cabeza (2026-11-11).

    Lo pidió el operador ante «REVISIÓN DE PROCEDIMIENTOS» (945220,
    UPD2998536): un formulario a mano, «FECHA: 03/08/2021», que la IA leyó
    bien y salió «S.F.» porque la hoja no es de ninguna clase conocida y al
    escrito sólo se le cree un «FECHA:» con la hora del rótulo de radicación.

    Sólo lo que es prueba de ser la fecha del documento:

    - un rótulo «FECHA:» **sin calificar** («FECHA DE VENCIMIENTO», «FECHA
      VTO.», «FECHA ÚLTIMA LECTURA»… son trampas y se tachan antes);
    - en la **cabeza** de la hoja, donde un formulario la pide;
    - **no citado**: sin «REF:», «REFERENCIA» ni «ASUNTO» poco antes -- el
      «FECHA: 10/12/2021, FACTURADO» que cita un recurso (UPD2365925 p36) --.

    Medido sobre las 281 piezas de Afinia (capa de texto): de las que la
    estructura deja sin fecha, da 1 bien y 0 mal. La regla más suelta -- la
    única fecha de la hoja -- daba 7 bien y **12 mal** (la fecha de la carta en
    un escrito que se radicó al día siguiente): no se usa.
    """
    cabeza = " ".join(sin_trampas(texto or "").split())[:_CABEZA_DEL_FORMULARIO]
    for rotulo in _ROTULO_DE_LA_FECHA.finditer(cabeza):
        if _CITA_DE_OTRO_PAPEL.search(cabeza[max(0, rotulo.start() - _ANTES_DEL_ROTULO) : rotulo.start()]):
            continue
        if (fecha := _tras(r"\bFECHA\s*[:;.]", cabeza[rotulo.start() :], hoy)) is not None:
            return fecha
    return None


#: El escrito con el sello de tinta de la oficina. Es también lo que pasa a ser
#: una hoja con sello que parecía un anexo.
_ESCRITO_RADICADO = Pieza("escrito radicado", ABRE, _del_escrito)


#: Las piezas, en el orden en que se prueban sobre una hoja (la primera que la
#: reconoce la nombra). Los rangos dicen cuál manda como hoja principal.
_PIEZAS: list[tuple[re.Pattern[str], Pieza]] = [
    (
        re.compile(
            r"RECONOCIMIENTO\s+DE\s+DEUDA\s+Y\s+PROPUESTA|RECONOZCO\s+COMO\s+DEUDA|ACOGERME\s+AL\s+ACUERDO\s+DE\s+PAGO"
        ),
        Pieza("reconocimiento de deuda", ABRE, _del_reconocimiento),
    ),
    (
        re.compile(r"SE\s+PUBLICA\s+EL\s+DIA"),
        Pieza("publicación del aviso", ABRE, _de_la_publicacion),
    ),
    # El escrito con el sello de tinta de la oficina: abre su documento aunque
    # la fecha, a mano, no se deje leer en la capa (la plantilla de Agustín
    # Codazzi, 0 de 11: se fechaba con lo que cita su «REF:»).
    (
        re.compile(
            r"RECIBIDO\s+NO\s+IM[PB]LICA|NO\s+IM[PB]LICA\s+A\W?C\W?EPTACI|FECHA\s+[DC]E\s+RECIBIDO"
        ),
        _ESCRITO_RADICADO,
    ),
    (
        re.compile(
            r"NOTIFICACION\s+PERSONAL.{0,400}EN\s+LA\s+FECHA|EN\s+LA\s+FECHA.{0,80}COMPARECI"
        ),
        Pieza("notificación personal", ABRE, _de_la_notificacion),
    ),
    (
        re.compile(
            r"ACTA\s+DE\s+REVISION\s+NUMERO|A\s*LOS\s+\d{1,2}\s+DIAS\s+DEL\s+MES\s+\d{1,2}\s+DEL\s+\d{4}\s+SE\s+HACE\s+PRESENTE"
        ),
        Pieza("acta de revisión", ABRE, _del_acta),
    ),
    (
        re.compile(r"^.{0,200}C\.?\s?N\.?\s?R\.?\s?P\.?\s?F\b"),
        Pieza("liquidación del consumo", ABRE, _de_la_liquidacion),
    ),
    (
        re.compile(r"SUSPENSION\s+CORTE\s+Y\s+RECONEXION"),
        Pieza("acta de suspensión", ABRE, _de_la_suspension),
    ),
    # «Recibí Constanza del contenido» (UPD3102729 p2): como la deja la OCR.
    (
        re.compile(
            r"CONSTANCIA\s+DE\s+RECEPCION|RECIBI\s+CONSTAN\w*\s+DEL\s+CONTENIDO|CONSTAN\w*\s+DEL\s+CONTENIDO\s+DE\s+LA\s+RECLAMACION"
            r"|PARA\s+LA\s+EMPRESA.{0,300}N\W{0,2}\s*PQR\W"
        ),
        Pieza("constancia de la reclamación", ABRE, _de_la_constancia),
    ),
    (
        re.compile(r"CONSTANCIA\s+DE\s+CONTRATACION\s+DE\s+SERVICIO"),
        Pieza("constancia de contratación", ABRE, _de_la_contratacion),
    ),
    (
        re.compile(r"^.{0,300}CONSTANCIA\s+DE\s+VISITA\s+REALIZADA"),
        Pieza("constancia de visita", ABRE, _de_la_visita),
    ),
    (
        re.compile(r"EN\s+CONSTANCIA\s+SE\s+SUSCRIBE"),
        Pieza("contrato de transacción", 12, _de_la_firma, respaldo=True),
    ),
    (
        re.compile(
            r"FIRMADO\s+EN.{0,200}DIAS\s+DEL\s+MES|DIAS\s+DEL\s+MES.{0,200}FIRMADO\s+EN"
        ),
        Pieza("firma de la carta de instrucciones", 20, _de_la_firma, respaldo=True),
    ),
    (
        re.compile(r"HABEAS\s+DATA|TRATAMIENTO\s+DE\s+DATOS\s+PERSONALES"),
        Pieza("Ley Habeas Data", 25, _del_habeas, respaldo=True),
    ),
    # El comprobante sólo manda cuando va solo: dentro de un acuerdo es el pago
    # de su cuota inicial, y junto a un escrito, su prueba. Cede ante el escrito.
    (
        re.compile(r"CUPON\s+MANUAL"),
        Pieza("comprobante de pago", RANGO_SIN_RECONOCER + 5, _del_comprobante),
    ),
    (
        _CABEZA_DE_LA_EMPRESA,
        Pieza("carta de la empresa", ABRE, _de_la_carta_de_la_empresa),
    ),
    # Lo que fecha otra cosa o nada: nunca la hoja principal si hay otra.
    (re.compile(r"CARTA\s+DE\s+INSTRUCCIONES"), Pieza("carta de instrucciones", 60)),
    (re.compile(r"CONTRATO\s+DE\s+TRANSACCION"), Pieza("contrato de transacción", 60)),
    (re.compile(r"^.{0,400}PAGARE\s+N"), Pieza("pagaré", RANGO_DE_ANEXO)),
    (re.compile(r"SIMULADOR\s+DE\s+NEGOCIACION"), Pieza("simulador", RANGO_DE_ANEXO)),
    (
        re.compile(
            r"CAMARA\s+DE\s+COMERCIO|CERTIFICADO\s+DE\s+(?:MATRICULA|TRADICION|EXISTENCIA)|OFICINA\s+DE\s+REGISTRO\s+DE\s+INSTRUMENTOS"
        ),
        Pieza("certificado", RANGO_DE_ANEXO),
    ),
]

_GUIA = Pieza("guía de LECTA", RANGO_DE_ANEXO)
_CEDULA = Pieza("documento de identidad", RANGO_DE_ANEXO)
_FACTURA = Pieza("factura", RANGO_DE_ANEXO, _de_la_factura)
_OTRO_ANEXO = Pieza("anexo", RANGO_DE_ANEXO)
_ESCRITO = Pieza("escrito", RANGO_SIN_RECONOCER, _del_escrito)
_CARTA = Pieza("carta", ABRE, _del_escrito)
#: Cuánto texto es la cabeza de una hoja para reconocerla como anexo (la misma
#: medida que ``CABEZA_DEL_SOPORTE`` de la aplicación).
_CABEZA_DEL_ANEXO = 700
#: Las clases de :func:`~resolutions.domain.anexos_declarados.clase_de_la_hoja`
#: que son anexo de lo que acompañan.
_CLASES_DE_ANEXO = {
    "factura": _FACTURA,
    "certificado de tradición": _OTRO_ANEXO,
    "certificado catastral": _OTRO_ANEXO,
    "certificado de existencia": _OTRO_ANEXO,
    "escritura pública": _OTRO_ANEXO,
    "fotografías": _OTRO_ANEXO,
}


def pieza_de(texto: str) -> Pieza:
    """Qué clase de hoja es, por lo que dice."""
    plano = _plano(texto)
    for reconoce, pieza in _PIEZAS:
        if reconoce.search(plano):
            return pieza
    if es_guia_de_envio(texto or ""):
        return _GUIA
    if es_cedula(texto or ""):
        return _CEDULA
    if numero_del_acta_de_suspension(texto or ""):
        return Pieza("acta de suspensión", ABRE, _de_la_suspension)
    # La primera hoja de una carta -- el saludo o la fecha, y su «REF:» o
    # «ASUNTO:» -- abre su documento como cualquier pieza conocida. Si no, la
    # copia de una publicación que el cliente aporta como prueba detrás de su
    # recurso le ganaba y lo fechaba (RESOLUCION_010-2020 p50 con la p56). Va
    # antes que los anexos: una factura no abre carta, y la basura que la OCR
    # deja del sello en la cabeza de la p50 la hacía pasar por una.
    if abre_carta(texto or ""):
        return _CARTA
    # Un anexo se reconoce en su cabeza, como en ``clase_de_soporte``: un
    # recurso que en su cuerpo nombra la factura y las fotografías que aporta
    # no es una factura (DOCUMENTO_35 p5).
    clase = clase_de_la_hoja(texto or "")
    if (
        clase in _CLASES_DE_ANEXO
        and clase_de_la_hoja((texto or "")[:_CABEZA_DEL_ANEXO]) == clase
    ):
        return _CLASES_DE_ANEXO[clase]
    return _ESCRITO


def fecha_de_la_hoja(texto: str, *, hoy: date | None = None) -> date | None:
    """La fecha que la hoja pone en el sitio de su clase, o ``None``.

    Para releer la hoja principal -- en local o con la IA -- y fecharla igual
    que su capa: sólo con el sitio de su clase, nunca con la más reciente. Si
    su clase no la da y la hoja no es un anexo, la razonada: su rótulo
    «FECHA:» en la cabeza (``fecha_razonada``, 2026-11-11).
    """
    pieza = pieza_de(texto)
    if pieza.fecha and (fecha := pieza.fecha(texto or "", hoy)) is not None:
        return fecha
    return None if pieza.anexo else fecha_razonada(texto, hoy)


@dataclass(frozen=True, slots=True)
class FechaPorEstructura:
    """La fecha de un documento y de dónde salió."""

    fecha: date | None
    #: La hoja de la que salió, o ``None`` si no salió.
    pagina: int | None
    #: La hoja principal del documento: la que se relee si no hay fecha.
    principal: int
    #: Qué la dio: «sello de radicación», «publicación del aviso»…
    fuente: str | None
    #: Dónde buscarla si no salió: la principal y los respaldos, nunca un anexo.
    donde_buscar: tuple[int, ...] = ()

    def como(self) -> str | None:
        if self.fecha is None:
            return None
        return f"{self.fuente} (pág. {self.pagina})"


def hoja_principal(
    paginas: Sequence[int],
    piezas: Mapping[int, Pieza],
    con_sello: frozenset[int] = frozenset(),
) -> int:
    """La hoja que manda: la de sello, si la hay; si no, la de la pieza de menor rango.

    A igual rango, la primera. Si todas son anexos, la primera: el documento es
    ese anexo (un comprobante suelto, una factura sola).
    """
    sellada = [p for p in paginas if p in con_sello and not piezas[p].anexo]
    if sellada:
        return sellada[0]
    return min(paginas, key=lambda p: (piezas[p].rango, paginas.index(p)))


def fecha_por_estructura(
    paginas: Sequence[int],
    textos: Mapping[int, str],
    *,
    sellos: Mapping[int, date | None] | None = None,
    guias: Mapping[int, date | None] | None = None,
    con_sello: frozenset[int] | set[int] = frozenset(),
    hoy: date | None = None,
) -> FechaPorEstructura:
    """La fecha del documento de ``paginas``, leída donde su estructura la pone.

    ``sellos``: la fecha que el lector del sello sacó de cada hoja que lo trae
    (sin las copias, que son de otro día). ``guias``: la que el mensajero marcó
    en las casillas de cada guía de LECTA; sólo fecha un documento que es la
    guía misma.
    """
    paginas = list(paginas)
    sellos = sellos or {}
    guias = guias or {}
    piezas = {p: pieza_de(textos.get(p, "") or "") for p in paginas}
    # Una hoja con sello nunca es un anexo (regla F4 de la caja): es el escrito
    # que la oficina radicó, aunque su cabeza nombre la factura que aporta
    # (DOCUMENTO_35 p5, UPD2366126 p68: el sello leído no llegaba al documento).
    for pagina in (*sellos, *con_sello):
        if pagina in piezas and piezas[pagina].anexo:
            piezas[pagina] = _ESCRITO_RADICADO
    # La hoja con sello -- aunque su fecha, a mano, no se haya podido leer -- es
    # la que el operador radicó: la principal.
    principal = hoja_principal(
        paginas, piezas, frozenset(p for p in (*sellos, *con_sello) if p in piezas)
    )
    respaldos = sorted(
        (p for p in paginas if p != principal and piezas[p].respaldo),
        key=lambda p: (piezas[p].rango, paginas.index(p)),
    )
    donde = (principal, *respaldos)

    def hallada(fecha: date, pagina: int, fuente: str) -> FechaPorEstructura:
        return FechaPorEstructura(fecha, pagina, principal, fuente, donde)

    # 1. El sello manda: el de la principal y, si no, el de otra hoja propia.
    for pagina in [principal, *paginas]:
        if not piezas[pagina].anexo and (fecha := sellos.get(pagina)) is not None:
            return hallada(fecha, pagina, "sello de radicación")
    # 2. La hoja principal, en el sitio de su clase.
    pieza = piezas[principal]
    if pieza.fecha and (fecha := pieza.fecha(textos.get(principal, "") or "", hoy)):
        return hallada(fecha, principal, pieza.nombre)
    # La guía sola se fecha con lo que marcó el mensajero.
    if pieza is _GUIA and (fecha := guias.get(principal)) is not None:
        return hallada(fecha, principal, "fecha marcada en la guía")
    # 3. Los respaldos del mismo documento.
    for pagina in respaldos:
        respaldo = piezas[pagina]
        if respaldo.fecha and (
            fecha := respaldo.fecha(textos.get(pagina, "") or "", hoy)
        ):
            return hallada(fecha, pagina, respaldo.nombre)
    # 4. Razonada, en la hoja principal si no es un anexo: su rótulo «FECHA:»
    #    en la cabeza (2026-11-11). Lo último: la estructura manda.
    if not pieza.anexo and (fecha := fecha_razonada(textos.get(principal, "") or "", hoy)) is not None:
        return hallada(fecha, principal, "rótulo «FECHA:» en la cabeza de la hoja")
    return FechaPorEstructura(None, None, principal, None, donde)
