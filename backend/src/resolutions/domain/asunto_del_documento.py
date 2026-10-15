"""De qué trata un documento, dicho con sus propias palabras: su título.

Lo pidió el operador al revisar el índice: «¿dónde está el título al nombre del
documento? Agrégale el asunto, el tipo de documento». El tipo dice qué clase de
papel es -- DERECHO DE PETICION --; el título dice de qué trata -- «descargar
del sistema los valores adeudados por el arrendatario» --, y es lo que hace
que una fila del índice se entienda sin abrir el PDF.

El asunto está en el papel, pero no siempre donde se espera. Medido sobre la
caja «afinar afinia», hay cuatro sitios, y se buscan en este orden:

1. **El renglón «REF:» o «ASUNTO:» del escrito**, con su continuación: «REF.:
   DERECHO DE PETICION EN CONTRA DE LA EDFC DE FECHA DE agosto / DE 2021 POR
   VALOR DE $ 1.972.040». Lo que sólo repite el tipo -- «DERECHO DE PETICIÓN
   (ART 23 C.N.)» -- no es un título y se sigue buscando.
2. **La respuesta de la empresa**, que resume el reclamo que contesta:
   «mediante el cual reclama por exceso de consumo facturado en 09/08/2021».
3. **La petición del escrito**: «Solicito … se sirva descargar del sistema los
   valores adeudados por el arrendatario…».
4. **La carta sencilla**: «Es para informar mi inconformidad del aumento del
   monto de la factura del mes de agosto 2021».

Lo que no es título se descarta aunque esté en el renglón del asunto: el
«Asunto: 03 RECLAMO» del sello de radicación (es la clase del trámite), la
«Referencia: Cuenta Interna No. 1012171» (es un número de cuenta) y el «No.
RE3110202138312» (el radicado ya va aparte en el nombre).

Aquí no se lee papel: entra el texto de las hojas y sale el título.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

#: Lo más largo que se deja ser a un título. Un índice no es un resumen: lo
#: que pase de aquí se corta en la última palabra entera.
MAX_TITULO = 110
#: Cuántos renglones de cabecera se miran para el REF/ASUNTO.
RENGLONES_DE_CABECERA = 60

#: El renglón del asunto, como lo escribe el papel y como lo deja la OCR:
#: «REF:», «REF.:», «.REF!», «Ref.», «Referencia:», «ASUNTO:».
_RENGLON_DEL_ASUNTO = re.compile(
    # Con su puntuación de rótulo: un renglón del cuerpo que empieza
    # «referencia, en los términos…» no es el campo. El «;» es el «:» que la
    # OCR rompe: «REF; RECURSO DE REPOSICIÓN…» (UPD2326418 p4).
    r"^\W{0,3}(?:REF(?:ERENCIA)?|ASUNTO)\s*[.:;!]{1,3}\s*(?P<resto>.*)$", re.IGNORECASE
)
#: El renglón que ya es otra cosa: un campo del encabezado, el saludo, el
#: cuerpo de la carta.
_OTRO_CAMPO = re.compile(
    r"^\W*(?:ACCIONANTE|ACCIONAD[OA]|NIC|CONSECUTIVO|PETICI[OÓ]N\s+N|RADICADO|ESTIMAD[OA]"
    r"|CORDIAL|RESPETAD[OA]|SE[ÑN]OR|DOCTOR|APRECIAD[OA]|YO\b|EL\s+SUSCRITO|LA\s+SUSCRITA"
    r"|CUENTA\s+INTERNA|MATR[IÍ]CULA|DIRECCI[OÓ]N|OFICINA|FOLIOS?)",
    re.IGNORECASE,
)
#: Lo que no es título aunque esté en el renglón del asunto.
_NO_ES_TITULO = (
    # El sello: «03 RECLAMO», «03 RCCLAMO», «04 RECURSO».
    re.compile(r"^\d{1,2}\s+\S+$"),
    # Sólo un número de cuenta, un NIC o un radicado.
    re.compile(r"^(?:CUENTA\s+INTERNA|NIC|RADICADO)\b", re.IGNORECASE),
)
#: Lo que se quita de un título porque ya está en otra parte o no dice nada.
_RUIDO = (
    re.compile(r"\(?\s*ART(?:ICULO|\.)?\s*23\s*(?:DE\s*)?(?:LA\s*)?C\.?\s*[NPM]\.?\s*\)?", re.IGNORECASE),
    re.compile(r"\bN[O°º]?\.?\s*(?:RE|R\s?E)\s?\d{13}\b|\bRE\d{13}\b", re.IGNORECASE),
    re.compile(r"\bN[O°º]\.?\s*\d{6,}\b", re.IGNORECASE),
)

#: Las frases con que la respuesta de la empresa resume lo que contesta. Con la
#: tilde que la OCR pone donde no va: «medíante».
_LA_RESPUESTA_DICE = re.compile(
    r"med[ií]ante\s+(?:el|la)\s+cual\s+(?:reclama|presenta|solicita|interpone|manifiesta)"
    r"\s+(?:por\s+)?(?P<s>.+?)(?:,\s*al\s+respecto|\.\s|;|,\s*le\s+informamos|$)",
    re.IGNORECASE | re.DOTALL,
)
#: El campo «CAUSA:» de la constancia de una reclamación: «Daño Medidor y/o
#: Acometida», «Cobros de Conexión, Reconexión o Reinstalación».
_CAUSA = re.compile(r"^\W*CAUSA\s*[:.]\s*(?P<s>.*)$", re.IGNORECASE)
#: Lo que pide el escrito. Primero «se sirva descargar…», que es la petición
#: misma; si no, lo que sigue a «solicito», saltando a quién se le pide.
_SE_SIRVA = re.compile(
    r"se\s+sirvan?\s+(?P<s>.+?)(?:,\s*(?:debido|por\s+cuanto|toda\s+vez|ya\s+que|teniendo)|\.\s|;|$)",
    re.IGNORECASE | re.DOTALL,
)
_SOLICITO = re.compile(
    r"solicito\s+(?:de\s+manera\s+respetuosa\s*,?\s*|respetuosamente\s*,?\s*)?"
    r"(?:a\s+(?:la\s+empresa|usted(?:es)?)[^,]*?,?\s*)?(?:que\s+)?(?:se\s+me\s+)?"
    r"(?P<s>.+?)(?:,\s*(?:debido|por\s+cuanto|toda\s+vez|ya\s+que|teniendo)|\.\s|;|$)",
    re.IGNORECASE | re.DOTALL,
)
#: Las palabras con que un renglón queda a medias y sigue en el siguiente.
_A_MEDIAS = re.compile(r"\b(?:DE|DEL|LA|EL|LOS|LAS|EN|Y|O|A|POR|PARA|CON|SU|SUS|AL)$", re.IGNORECASE)
#: Lo que ya no es el título: el NIC, la cédula, la dirección.
_CORTE = re.compile(r"\s(?:NIC|NK|N[I1]C|CC|C\.C|C\.\s?C|EN\s+LA\s+DIRECCI[OÓ]N|DIRECCI[OÓ]N)\b", re.IGNORECASE)
#: La sección donde el escrito pide.
_SECCION_DE_PETICION = re.compile(
    r"^\W*(?:PETICI[OÓ]N(?:ES)?|PRETENSI[OÓ]N(?:ES)?|SOLICITUD(?:ES)?)\W*$", re.IGNORECASE | re.MULTILINE
)
#: La carta sencilla: «Es para informar mi inconformidad del aumento…».
_LA_CARTA_DICE = re.compile(
    r"(?:es\s+para|me\s+dirijo\s+(?:a\s+usted(?:es)?\s+)?para|con\s+el\s+fin\s+de)\s+"
    r"(?:informar|manifestar|presentar|reclamar|solicitar)\s+(?:mi\s+|una\s+|la\s+)?(?P<s>.+?)(?:\.\s|;|$)",
    re.IGNORECASE | re.DOTALL,
)


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.upper()).strip()


def legible(texto: str) -> bool:
    """Si el texto son palabras y no la basura de una lectura rota.

    «ERENR^^- ''•«ENTA INTERNA» no es un título: casi todo lo que debería ser
    letra es otra cosa, y las palabras que quedan no llevan vocal.
    """
    if not texto:
        return False
    raros = sum(1 for c in texto if not (c.isalnum() or c.isspace() or c in ".,;:$/()-"))
    if raros / len(texto) > 0.05:
        return False
    palabras = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", texto)
    con_vocal = [p for p in palabras if re.search(r"[AEIOUÁÉÍÓÚaeiouáéíóú]", p)]
    return len(palabras) >= 2 and len(con_vocal) / len(palabras) >= 0.8


def _limpio(texto: str) -> str:
    """Un renglón o una frase, listos para ir al índice."""
    cortado = _CORTE.search(texto)
    if cortado:
        texto = texto[: cortado.start()]
    for ruido in _RUIDO:
        texto = ruido.sub(" ", texto)
    texto = re.sub(r"\s+", " ", texto).strip(" .,;:-–—()[]\"'«»")
    texto = texto.upper()
    if len(texto) > MAX_TITULO:
        texto = texto[:MAX_TITULO].rsplit(" ", 1)[0].rstrip(" ,;:-")
    # Sin la palabra suelta en que se cortó: «… FACTURAS DE ENERGÍA Y».
    while (colgando := _A_MEDIAS.search(texto)) and colgando.start() > 0:
        texto = texto[: colgando.start()].rstrip(" ,;:-")
    return texto


def _palabras(texto: str) -> list[str]:
    return [p for p in re.findall(r"[A-Z0-9$.]{2,}", _plano(texto)) if p not in {"DE", "LA", "EL", "EN", "Y", "LOS", "LAS", "DEL"}]


def _dice_algo(titulo: str, tipo: str | None) -> bool:
    """Si el título dice algo más que el tipo: «DERECHO DE PETICION» no."""
    propias = _palabras(titulo)
    if len(propias) < 2:
        return False
    del_tipo = set(_palabras(tipo or ""))
    return len([p for p in propias if p not in del_tipo]) >= 2


def _sin_el_tipo(titulo: str, tipo: str | None) -> str:
    """«DERECHO DE PETICION EN CONTRA DE LA EDFC…» → «EN CONTRA DE LA EDFC…»."""
    if tipo and _plano(titulo).startswith(_plano(tipo)):
        return titulo[len(tipo) :].strip(" .,;:-")
    return titulo


def _del_renglon(renglones: list[str], tipo: str | None) -> str | None:
    """El REF/ASUNTO con su continuación, si dice algo más que el tipo."""
    for i, renglon in enumerate(renglones[:RENGLONES_DE_CABECERA]):
        hallado = _RENGLON_DEL_ASUNTO.match(renglon.strip())
        if hallado is None:
            continue
        titulo = hallado.group("resto").strip()
        if not titulo or any(p.match(titulo) for p in _NO_ES_TITULO):
            continue
        # La continuación: el asunto que no cupo en un renglón. Sólo si el
        # anterior no cerró y el siguiente no es otro campo; de un renglón largo
        # -- ya es el cuerpo -- sólo lo que sigue en mayúsculas: «DEUDA para que
        # la empresa…» aporta «DEUDA».
        siguiente = renglones[i + 1].strip() if i + 1 < len(renglones) else ""
        a_medias = bool(_A_MEDIAS.search(titulo.rstrip(" ,")))
        sigue = bool(re.match(r"^(?:DE|DEL|POR|PARA|CON|Y|EN|\d|[a-záéíóúñ])", siguiente))
        if (
            siguiente
            and not titulo.endswith((".", ")"))
            and not _OTRO_CAMPO.match(siguiente)
            and not _RENGLON_DEL_ASUNTO.match(siguiente)
            and (a_medias or sigue)
        ):
            if len(siguiente) <= 60:
                titulo = f"{titulo} {siguiente}"
            elif a_medias:
                mayusculas = re.match(
                    r"^((?:[A-ZÁÉÍÓÚÑ0-9$.,]+\s+)*[A-ZÁÉÍÓÚÑ0-9$.,]+)(?=\s+[a-záéíóúñ])", siguiente
                )
                if mayusculas:
                    titulo = f"{titulo} {mayusculas.group(1)}"
        if not legible(titulo):
            continue
        titulo = _limpio(_sin_el_tipo(_limpio(titulo), tipo))
        if titulo and _dice_algo(titulo, tipo):
            return titulo
    return None


def _de_la_causa(renglones: list[str], tipo: str | None) -> str | None:
    """«CAUSA: Daño Medidor y/o Acometida», o en el renglón de debajo."""
    for i, renglon in enumerate(renglones[:RENGLONES_DE_CABECERA]):
        hallado = _CAUSA.match(renglon.strip())
        if hallado is None:
            continue
        causa = hallado.group("s").strip() or (renglones[i + 1].strip() if i + 1 < len(renglones) else "")
        if causa and not _OTRO_CAMPO.match(causa) and legible(causa):
            titulo = _limpio(causa)
            if titulo:
                return titulo
    return None


def _de_la_frase(texto: str, patron: re.Pattern[str], tipo: str | None) -> str | None:
    for hallado in patron.finditer(texto):
        if not legible(hallado.group("s")):
            continue
        titulo = _limpio(hallado.group("s"))
        if titulo and _dice_algo(titulo, tipo):
            return titulo
    return None


def asunto_del_documento(paginas: Sequence[str], tipo: str | None = None) -> str | None:
    """El título de un documento: de qué trata, con sus palabras. ``None`` si no lo dice.

    ``paginas`` son las del documento, en orden y sin sus anexos; ``tipo`` es
    su tipo documental, para no devolver como título lo que sólo lo repite.
    """
    if not paginas:
        return None
    primera = paginas[0] or ""
    titulo = _del_renglon(primera.splitlines(), tipo) or _de_la_causa(primera.splitlines(), tipo)
    if titulo:
        return titulo
    # El texto corrido, sin los saltos que la OCR mete a mitad de frase.
    corrido = [re.sub(r"\s*\n\s*", " ", texto or "") for texto in paginas]
    for texto in corrido:
        titulo = _de_la_frase(texto, _LA_RESPUESTA_DICE, tipo)
        if titulo:
            return titulo
    for original in paginas:
        seccion = _SECCION_DE_PETICION.search(original or "")
        if seccion is None:
            continue
        resto = re.sub(r"\s*\n\s*", " ", (original or "")[seccion.end() :])
        titulo = _de_la_frase(resto, _SE_SIRVA, tipo) or _de_la_frase(resto, _SOLICITO, tipo)
        if titulo:
            return titulo
        # Peticiones en viñetas: «PETICIONES: • SEA RELIQUIDADO DICHOS MONTOS.»
        vineta = re.match(r"^[\W\d]*(?P<s>[^.;]{8,}?)(?:\.|;|$)", resto.strip())
        if vineta and legible(vineta.group("s")) and _dice_algo(vineta.group("s"), tipo):
            return _limpio(vineta.group("s"))
    for texto in corrido:
        titulo = _de_la_frase(texto, _LA_CARTA_DICE, tipo)
        if titulo:
            return titulo
    return None


# -- el título directo: lo que el documento dice ser ---------------------------------

#: Los títulos que un escrito se da en su REF o su ASUNTO, del más largo al más
#: corto: el recurso «en subsidio de apelación» es un título entero, no un
#: recurso de reposición con media frase detrás.
_TITULOS_DEL_ESCRITO: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "RECURSO DE REPOSICION EN SUBSIDIO DE APELACION",
        re.compile(r"REC\w*\W{0,3}(?:DE\s+)?REPOSICION\s+(?:Y\s+)?EN\s+SUBSIDIO\s+(?:EL\s+)?(?:DE\s+)?APELACION"),
    ),
    ("RECURSO DE APELACION", re.compile(r"RECURSO\s+DE\s+APELACION")),
    ("RECURSO DE REPOSICION", re.compile(r"REC\w*\W{0,3}(?:DE\s+)?REPOSICION")),
    ("RECURSO DE QUEJA", re.compile(r"RECURSO\s+DE\s+QUEJA")),
    ("DERECHO DE PETICION", re.compile(r"DERECHO\s+DE\s+PETICI")),
    # Con lo que la OCR hace de la palabra: «Redamación», «RCCLAMO».
    ("RECLAMACION", re.compile(r"\bRE?[CDL]{1,2}AMACION\b|\bR[EC]CLAMO\b")),
    ("QUEJA", re.compile(r"\bQUEJA\b")),
    ("SOLICITUD", re.compile(r"\bSOLICITUD\b")),
)
#: Lo que imprime la empresa en una carta suya.
_DE_LA_EMPRESA = re.compile(r"\bCONSECUTIVO\s+N[O0°º]?\W")
#: La constancia que firma el usuario al radicar en la oficina.
_CONSTANCIA = re.compile(r"RECIBI\s+CONSTANCIA\s+DEL\s+CONTENIDO\s+DE\s+LA\s+RECLAMACION")
#: Los títulos centrados de las comunicaciones de la empresa, en su renglón.
_TITULOS_DE_LA_EMPRESA: tuple[tuple[str, re.Pattern[str]], ...] = (
    # «personai», «persona1»: la «L» que la OCR rompe (UPD2326502 p1).
    ("CITACION PARA NOTIFICACION PERSONAL", re.compile(r"CITACION\s+PARA\s+NOTIFICACION\s+PERSONA[LI1]")),
    ("NOTIFICACION POR AVISO", re.compile(r"NOTIFICACION\s+POR\s+AVISO")),
    ("NOTIFICACION PERSONAL RECLAMOS", re.compile(r"^\W*NOTIFICACION\s+PERSONAL\s+RECLAMOS?\W*$")),
    ("RESPUESTA A RECLAMACION", re.compile(r"^\W*RESPUESTA\s+A\s+(?:LA\s+)?RECLAMACION\W*$")),
    ("NOTIFICACION PERSONAL", re.compile(r"^\W*NOTIFICACION\s+PERSONAL\W*$")),
    ("CONSTANCIA DE NOTIFICACION", re.compile(r"^\W*CONSTANCIA\s+DE\s+NOTIFICACION")),
)
#: Los formatos impresos que llevan su título en un recuadro de la cabecera,
#: no en un renglón propio: el acta, la guía de envío.
_FORMATOS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Sin exigir la A: la OCR deja «\CTA DE SUSPENSION».
    ("ACTA DE SUSPENSION CORTE Y RECONEXION", re.compile(r"CTA\s+DE\s+SUSPENSION")),
    ("ACTA DE IRREGULARIDAD", re.compile(r"CTA\s+DE\s+IRREGULARIDAD")),
    ("ACTA DE INSPECCION ELECTRICA", re.compile(r"CTA\s+DE\s+INSPECCION")),
    ("GUIA DE ENVIO", re.compile(r"\bLECTA\b|INTENTO\s+DE\s+ENTREGA|FECHA\s+DE\s+ENTREGA")),
    # El acuerdo de pago y sus piezas (UPD2326302). La carta de instrucciones
    # va antes que el pagaré: su título nombra el pagaré que acompaña.
    ("CARTA DE INSTRUCCIONES", re.compile(r"CARTA\s+DE\s+INSTRUCCIONES")),
    ("PAGARE", re.compile(r"\bPAGAR[EÉ]\s+N[O0]")),
    ("RECONOCIMIENTO DE DEUDA Y ACUERDO DE PAGO", re.compile(r"RECONOCIMIENTO\s+DE\s+DEUDA")),
    ("SIMULADOR DE NEGOCIACION Y FINANCIACION", re.compile(r"SIMULADOR\s+DE\s+NEGOCIACI")),
    # El que pone fin al cobro de lo dejado de facturar: no es una
    # reclamación aunque el cuerpo hable de ella (UPD2326470 p10).
    ("CONTRATO DE TRANSACCION", re.compile(r"CONTRATO\s+DE\s+TRANSACCI")),
    # El formato que el cliente llena al radicar para que le notifiquen por
    # correo: va con su escrito, no abre nada (UPD2326346 p4, UPD2326317 p12).
    # Sin él se llamaba «RECLAMACION» por la «petición, queja, reclamación» de
    # su texto.
    # La autorización de tratamiento de datos: «ASUNTO: / Ley Habeas Data -
    # NIC» (UPD2326311 p1).
    ("LEY HABEAS DATA", re.compile(r"HABEAS\s+DATA")),
    (
        "AUTORIZACION DE NOTIFICACION ELECTRONICA",
        re.compile(r"AUTORIZACI[O0]N\s+PARA\s+\w{1,2}\s+NOTIFICACI[O0]N\s+ELECTR"),
    ),
)
#: Los formatos que van con el escrito que tienen delante.
AUTORIZACION_DE_NOTIFICACION = "AUTORIZACION DE NOTIFICACION ELECTRONICA"
#: Las piezas de un acuerdo de pago. Lo decidió el operador ante UPD2326302:
#: los pagarés, sus cartas de instrucciones, el reconocimiento de deuda y el
#: simulador de la financiación son UN documento, sin RE propio.
PIEZAS_DEL_ACUERDO = frozenset(
    {
        "PAGARE",
        "CARTA DE INSTRUCCIONES",
        "RECONOCIMIENTO DE DEUDA Y ACUERDO DE PAGO",
        "SIMULADOR DE NEGOCIACION Y FINANCIACION",
    }
)
#: Cómo se llama el documento que las junta.
ACUERDO_DE_PAGO = "RECONOCIMIENTO DE DEUDA Y ACUERDO DE PAGO"

#: Cuánto de la cabecera se mira para los formatos.
CABEZA_DEL_FORMATO = 600
#: El radicado que la carta de la empresa cita en su asunto: «No. RE3110…».
_CITA_RADICADO = re.compile(r"\bRE\s?\d{13}\b|\bN[O0°º]\.?\s*RE")


#: Hasta cuántas letras un renglón se lee como título y no como prosa.
LARGO_DEL_TITULO = 60
#: Lo que el cliente dice que hace con su escrito: «con el fin de INTERPONER
#: derecho de petición», «PRESENTO reclamación». No «la presente reclamación».
_INTERPONE = re.compile(
    r"\b(?:INTERPON(?:ER|GO|E|EMOS)|PRESENT(?:AR|O|AMOS)|ELEV(?:AR|O)|FORMUL(?:AR|O)"
    r"|IMPETR(?:AR|O)|RADIC(?:AR|O))\b"
)


#: El renglón del asunto en la etiqueta del sello: «Asunto: 01 PETICION
#: Folios: 5», «Asunto; 03 RECLAMO», «Asunto 06 REC_REPOSICION EN SUBSIDIO DE
#: APELACION».
_ASUNTO_DEL_SELLO = re.compile(r"^\W*AS\w{0,3}N?T?[O0]\W{0,3}\s*[O0]?\d\s+(.+)$")
#: Lo que cada asunto del sello quiere decir.
_TIPO_DEL_SELLO: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("RECURSO DE REPOSICION EN SUBSIDIO DE APELACION", re.compile(r"REPOSICI\w*\s+EN\s+SUBSID")),
    ("RECURSO DE REPOSICION", re.compile(r"REPOSICI")),
    ("RECURSO DE APELACION", re.compile(r"APELACI")),
    ("RECURSO DE QUEJA", re.compile(r"QUEJA")),
    ("RECLAMACION", re.compile(r"\w?CLAM[O0A]")),
    ("DERECHO DE PETICION", re.compile(r"PETI\w{1,3}N")),
)


def _titulo_del_escrito(texto: str) -> str | None:
    for nombre, patron in _TITULOS_DEL_ESCRITO:
        if patron.search(texto):
            return nombre
    return None


def titulo_del_documento(primera_pagina: str, tipo: str | None = None) -> str:
    """Lo que el documento dice ser en su primera hoja: su título directo.

    Lo pidió el operador mirando la primera imagen de cada documento: no una
    frase de su petición, sino lo que el papel se llama -- «DERECHO DE
    PETICION», «RECURSO DE REPOSICION EN SUBSIDIO DE APELACION», «RESPUESTA A
    RECLAMACION» --, para que la fila se lea con su radicado y su fecha. En
    orden:

    1. **La carta de la empresa** -- «Consecutivo No.» -- con «ASUNTO:
       Reclamación No. RE…» es la respuesta a esa reclamación: «RESPUESTA A
       RECLAMACION». Si su asunto es la citación o la notificación, es eso.
    2. **La constancia** que firma el usuario al radicar: «CONSTANCIA DE
       RECLAMACION».
    3. **El título de la hoja**, en su renglón: «NOTIFICACIÓN PERSONAL».
    4. **El REF o el ASUNTO del escrito** del cliente: «REF: DERECHO DE
       PETICION (ART 23 C.N.)». Si su REF no nombra un tipo -- «REF: ERROR EN
       LECTURA» --, lo que el cuerpo dice que interpone: «con el fin de
       INTERPONER DERECHO DE PETICION».
    5. **El tipo del catálogo**, si nada de lo anterior lo dice.
    """
    originales = (primera_pagina or "").splitlines()[:RENGLONES_DE_CABECERA]
    renglones = [_plano(r) for r in originales]
    cabeza = " ".join(renglones)
    # El REF o el ASUNTO con el renglón que lo continúa: «REF. RECURSO DE
    # REPOSICIÓN EN SUBSIDIO DE / APELACION.»
    asuntos = []
    for i, original in enumerate(originales):
        hallado = _RENGLON_DEL_ASUNTO.match(original.strip())
        if hallado is None or any(p.match(hallado.group("resto").strip()) for p in _NO_ES_TITULO):
            continue
        asunto = hallado.group("resto")
        siguiente = originales[i + 1].strip() if i + 1 < len(originales) else ""
        if siguiente and not _OTRO_CAMPO.match(siguiente) and len(siguiente) <= 60:
            asunto = f"{asunto} {siguiente}"
        asuntos.append(_plano(asunto))
    for nombre, patron in _TITULOS_DE_LA_EMPRESA[:2]:
        if any(patron.search(a) for a in asuntos):
            return nombre
    # La respuesta de la empresa: su carta con consecutivo, y en el asunto lo
    # que contesta con el radicado detrás -- «Reclamación No. RE…» --. El
    # recurso del cliente también cita un consecutivo, pero su REF nombra lo
    # que él interpone, sin radicado.
    if _DE_LA_EMPRESA.search(cabeza):
        for asunto in asuntos:
            contestado = _titulo_del_escrito(asunto)
            if contestado and _CITA_RADICADO.search(asunto):
                return f"RESPUESTA A {contestado}"
    if _CONSTANCIA.search(cabeza):
        return "CONSTANCIA DE RECLAMACION"
    for renglon in renglones:
        for nombre, patron in _TITULOS_DE_LA_EMPRESA:
            if patron.search(renglon) and len(renglon) <= 60:
                return nombre
    for nombre, patron in _FORMATOS:
        if patron.search(cabeza[:CABEZA_DEL_FORMATO]):
            return nombre
    for asunto in asuntos:
        propio = _titulo_del_escrito(asunto)
        if propio:
            return propio
    # Sin REF ni ASUNTO que lo digan: el renglón corto que se lee como título
    # -- «DERECHO DE PETICIÓN.» --, o lo que el cuerpo dice que interpone. No
    # el tipo que la prosa nombra de pasada: «…fueron solicitados en el
    # derecho de petición, mientras…» es la hoja del petitorio de un recurso,
    # no un derecho de petición nuevo (UPD2326418 p3 y p5).
    for renglon in renglones:
        if len(renglon.strip()) <= LARGO_DEL_TITULO:
            propio = _titulo_del_escrito(renglon)
            if propio:
                return propio
    for verbo in _INTERPONE.finditer(cabeza):
        propio = _titulo_del_escrito(cabeza[verbo.end() : verbo.end() + 60])
        if propio:
            return propio
    # Y si el escrito no lo dice, lo que dice su sello de radicación: «Asunto:
    # 01 PETICION» (UPD2326321 p15). Último, porque el REF manda sobre él: el
    # sello lo pone la ventanilla, no el cliente (UPD2326307 p3).
    for original in originales:
        del_sello = _ASUNTO_DEL_SELLO.match(_plano(original).strip())
        if del_sello:
            for nombre, patron in _TIPO_DEL_SELLO:
                if patron.search(del_sello.group(1)):
                    return nombre
    return (tipo or "DOCUMENTO").upper()
