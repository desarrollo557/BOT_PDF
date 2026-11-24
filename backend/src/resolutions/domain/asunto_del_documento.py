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
#: Lo menos que trae un renglón que cuenta: tres letras o cifras seguidas. La
#: capa rota del escáner deja decenas de renglones de una o dos -- «■I», «¡í»,
#: «i» -- que no son nada y empujaban el título fuera de la cabecera: el
#: reconocimiento de deuda de 4100919 (UPD2985234 pág. 5) está en el renglón 98
#: de su capa y en el 16 de los que traen algo (2026-11-18).
_RENGLON_QUE_CUENTA = re.compile(r"[^\W_]{3}")


def renglones_de_la_cabecera(texto: str | None) -> list[str]:
    """Los primeros ``RENGLONES_DE_CABECERA`` renglones que traen algo, tal cual: donde se buscan los formatos impresos."""
    return [r for r in (texto or "").splitlines() if _RENGLON_QUE_CUENTA.search(r)][:RENGLONES_DE_CABECERA]

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
    # El formulario de recurso de Afinia: «Asunto: Interposición de recurso(s)
    # de ☐ Reposición ☒ Reposición y subsidiariamente apelación ante la SSPD».
    # Las dos casillas van impresas y la marcada no se lee con la OCR, que
    # además deja «Re^sición» y «apeiación»: por su asunto, con el nombre del
    # catálogo. Sin esto su título era «DOCUMENTO», no abría, y el recurso del
    # 24-03-2023 con sus nueve facturas salía dentro de la contestación de
    # delante (1005117, UPD2973878 pág. 6, 2026-11-18).
    ("RECURSO DE REPOSICION EN SUBSIDIO DE APELACION", re.compile(r"\bINTERPOSICI\w{0,3}\s+DE\s+RECURSO")),
    (
        "RECURSO DE REPOSICION EN SUBSIDIO DE APELACION",
        # También «Reposición y Subsidio de Apelación» y «y subsidiariamente el
        # de apelación» (UPD3102756 pág. 56).
        re.compile(
            r"REC\w*\W{0,3}(?:DE\s+)?REPOSICION\s+(?:Y\s+)?(?:EN\s+)?SUBSIDI\w*\s+(?:EL\s+)?(?:DE\s+)?APELACION"
        ),
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
#: Los escritos con que el cliente abre un trámite: su carta abre documento
#: aunque no traiga sello (:mod:`~resolutions.application.cartas`). No la
#: «SOLICITUD» a secas: también se titulan así los formularios que la empresa
#: le da a llenar -- la solicitud de servicio de UPD2555087 pág. 4 --.
ESCRITOS_DEL_TRAMITE = frozenset(nombre for nombre, _ in _TITULOS_DEL_ESCRITO) - {"SOLICITUD"}
#: Lo que imprime la empresa en una carta suya.
_DE_LA_EMPRESA = re.compile(r"\bCONSECUTIVO\s+N[O0°º]?\W")
#: La constancia que firma el usuario al radicar en la oficina. Con lo que la
#: OCR hace de sus palabras: «Recibí Constanza del contenido» (UPD3102729 pág.
#: 2), y por su formulario si el renglón no se lee: «PARA LA EMPRESA», «N° PQR»
#: y «CAUSA:».
#: Y la «O» que el escáner vuelve otra letra: «Recibí cgnstancia del
#: contenido», con «N^POR:» por «N° PQR:» (4132560, UPD2427617 pág. 2,
#: 2026-11-20): no se reconocía, y la constancia salía pegada a la autorización
#: de la hoja de delante.
_CONSTAN = r"C\w?NSTAN\w{1,4}"
_CONSTANCIA = re.compile(r"RECIB\w{0,2}\s+" + _CONSTAN + r"\s+DE\w?\s+(?:\w{1,3}\s+)?CONTENIDO")
_FORMULARIO_DE_LA_CONSTANCIA = (
    re.compile(r"PARA\s+LA\s+EMPRESA"),
    re.compile(r"\bN\W{0,3}\s*P\W?[QO0]\W?R\b"),
    re.compile(r"\bCAUSA\s*[:.]"),
)
#: Las otras dos formas de la constancia en las cajas de Magangué (2026-10-26):
#: la del contenido de la reclamación, con su RE en el título (1003064 pág.
#: 10), y la de recepción de peticiones, quejas y reclamos (1000265 pág. 1).
#: Con lo que el escáner hace de la palabra: «CONSTANOA DE RECEPCIÓN» (1000186
#: pág. 3), «CONSTANZA».
_OTRAS_CONSTANCIAS = re.compile(
    _CONSTAN + r"\s+DEL?\s+CONTENIDO\s+DE\s+LA\s+RECLAMACION|" + _CONSTAN + r"\s+DE\s+RECEPCION\s+DE\s+PETICIONES"
)
#: El formato impreso de la constancia «CONSTANCIA DE RECEPCIÓN DE
#: PETICIONES, QUEJAS Y RECLAMOS (PQR)», por su título o por lo que sólo él
#: imprime. El otro, «PARA LA EMPRESA / Recibí constancia del contenido de la
#: reclamación», no trae nada de esto.
_CONSTANCIA_DE_RECEPCION = re.compile(
    _CONSTAN + r"\s+DE\s+RECEPCION\s+DE\s+PETICIONES|FECHA\s+DE\s+ATENCION\s+VENCE|TIPO\s+DE\s+PQR\b"
)
#: Cómo se llama ese formato (el operador, 2026-11-20: «este formato sí déjale
#: el nombre que tenía antes, es al otro»): la constancia «PARA LA EMPRESA»
#: sigue siendo la CONSTANCIA DEL CONTENIDO DE LA RECLAMACION.
CONSTANCIA_DE_RECEPCION = "CONSTANCIA DE RECEPCION DE PETICIONES"


def es_constancia_de_recepcion(texto: str) -> bool:
    """Si la constancia es la de recepción de peticiones, quejas y reclamos (PQR) y no la «PARA LA EMPRESA»."""
    return bool(_CONSTANCIA_DE_RECEPCION.search(_plano(texto or "")))


#: La publicación del aviso, por su título en su renglón: lleva al lado el aviso,
#: cuyo «Asunto: Notificación por aviso» no la nombra (1000690, 2026-10-22).
_PUBLICACION_DEL_AVISO = re.compile(r"^\W*PUBLICACION\s+DEL?\s+AVISO\W*$")
#: Los papeles que se reconocen por lo que dicen en cualquier parte de su
#: cabeza, medidos en la revisión de los 38 PDF del 2026-10-22: la carta del
#: operador de aseo que autoriza una nota crédito (1000501, 1000683, salían
#: «RECLAMO»), el aviso que notifica un acto (920933, salía «RECURSO DE
#: REPOSICION» por los recursos que ofrece) y el formulario de la visita de
#: cobro (887305, salía «PAGO NO APLICADO» por una casilla sin marcar).
#: La carta del operador de aseo que autoriza la nota crédito de una
#: reclamación («AUT-5073-ASEO»). Su título interno sigue empezando por
#: «AUTORIZACION»: no toma el RE de ningún trámite.
AUTORIZACION_DEL_ASEO = "AUTORIZACION DE NOTA CREDITO DEL ASEO"
#: Cómo se llama, sin RE: «AUTORIZACION DESCUENTO/NOTA DE CREDITO», en
#: mayúsculas (el operador, 2026-11-24, ante 1000501: «RECLAMO -> DESCUENTO/NOTA
#: DE CREDITO ASEOPRONTO ESP -> AUTORIZACION DESCUENTO/NOTA DE CREDITO»). Del
#: 2026-11-20 al 24 se llamó RECLAMACION, y unas horas del 24, DESCUENTO/NOTA DE
#: CREDITO ASEOPRONTO ESP. En el nombre del archivo la barra, que Windows no
#: admite, queda en guion: «01_AUTORIZACION-DESCUENTO-NOTA-DE-CREDITO.pdf»; la
#: fila del índice la lleva tal cual.
NOTA_CREDITO_DEL_ASEO = "AUTORIZACION DESCUENTO/NOTA DE CREDITO"
_POR_LO_QUE_DICEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        AUTORIZACION_DEL_ASEO,
        re.compile(r"\bAUT\W?\d{3,5}\W?ASEO\b|APLICAR\s+DESCUENTO\W{0,3}S?\W{0,3}\s*O\s+NOTAS?\s+CREDITO"),
    ),
    (
        "NOTIFICACION POR AVISO",
        re.compile(r"POR\s+INTERMEDIO\s+DE\s+ESTE\s+AVISO|SE\s+CONSIDERARA\s+SURTIDA\s+AL\s+FINALIZAR"),
    ),
    ("GESTION DE COBRO", re.compile(r"MOTIVO\s+DEL\s+NO\s+PAGO")),
)


def _tipo_del_catalogo(asunto: str) -> str | None:
    """El tipo del catálogo que nombra un REF o un ASUNTO: «DECLARACION BAJO GRAVEDAD DE JURAMENTO».

    Sólo si el asunto es una de sus formas o empieza por una de dos palabras o
    más: «RECLAMO por alto consumo» no es por esto un tipo, lo dice su título.
    """
    from .catalogo import FRASES

    plano = re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]+", " ", _plano(asunto))).strip()
    for frase, tipo in FRASES:
        if plano == frase or (len(frase.split()) >= 2 and plano.startswith(f"{frase} ")):
            return tipo.nombre
    return None
#: Los títulos centrados de las comunicaciones de la empresa, en su renglón.
_TITULOS_DE_LA_EMPRESA: tuple[tuple[str, re.Pattern[str]], ...] = (
    # «personai», «persona1»: la «L» que la OCR rompe (UPD2326502 p1).
    ("CITACION PARA NOTIFICACION PERSONAL", re.compile(r"CITACION\s+PARA\s+NOTIFICACION\s+PERSONA[LI1]")),
    ("NOTIFICACION POR AVISO", re.compile(r"NOTIFICACION\s+POR\s+AVISO")),
    ("NOTIFICACION PERSONAL RECLAMOS", re.compile(r"^\W*NOTIFICACION\s+PERSONAL\s+RECLAMOS?\W*$")),
    ("RESPUESTA A RECLAMACION", re.compile(r"^\W*RESPUESTA\s+A\s+(?:LA\s+)?RECLAMACION\W*$")),
    ("NOTIFICACION PERSONAL", re.compile(r"^\W*NOTIFICACION\s+PERSONAL\W*$")),
    # La de la aceptación del desistimiento también va sola: se la llevaba el
    # acuerdo de pago de delante (7975593, UPD2460819 hoja 306, 2026-11-12).
    ("NOTIFICACION PERSONAL", re.compile(r"^\W*NOTIFICACION\s+PERSONAL\s+DE\s+ACEPTACION\s+DEL\s+DESISTIMIENTO\W*$")),
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
    # Con una letra del final que el escáner cambia: «Réconocimíehto»
    # (4100919, UPD2985234 pág. 5, 2026-11-18).
    ("RECONOCIMIENTO DE DEUDA Y ACUERDO DE PAGO", re.compile(r"RECONOCIMI\w{4}\s+DE\s+DEUDA")),
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
    # Con lo que el escáner hace de la H: «Ley Rabeas Data» (1005114,
    # UPD2973876 pág. 1, 2026-11-18): sin esto salía «DOCUMENTO», suelta, fuera
    # de su acuerdo de pago.
    # Y por su cuerpo, cuando el escáner rompe el asunto: «autorizo a CARIBEMAR…
    # para enviar de manera física y/o digital la factura». Lo dictó el
    # operador ese mismo día: «LEY HABEAS DATA NUNCA PUEDE IR FUERA DE
    # RECONOCIMIENTO DE DEUDA Y ACUERDO DE PAGO, NUNCA».
    ("LEY HABEAS DATA", re.compile(r"\b[HR]A[B8]EA[S5]\s+DA[T7]A|ENVIAR\s+DE\s+MANERA\s+F[IL1]SICA")),
    (
        "AUTORIZACION DE NOTIFICACION ELECTRONICA",
        # Con lo que el escáner hace: «Autorización para ia notificación
        # eiectrónica» (1004833, UPD3102764 pág. 17, 2026-11-18), que salía
        # «RECLAMO» aparte en vez de ir con su escrito.
        re.compile(r"AUTORIZACI[O0]N\s+PARA\s+\w{1,2}\s+NOTIFICACI[O0]N\s+E[LI1]ECTR"),
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

#: Los formularios de la oficina que van cada uno en su documento. Lo dictó el
#: operador el 2026-10-26 sobre las cajas de Magangué: «una constancia de
#: reclamación siempre va sola a menos que lleve algún anexo, y sea evidente el
#: anexo», y «la notificación personal también va sola»; la carta de respuesta
#: que la sigue es otro documento, con sus anexos.
CONSTANCIA_DE_RECLAMACION = "CONSTANCIA DE RECLAMACION"
#: En cuántos renglones del principio se busca el «Consecutivo No.» de la
#: carta de la empresa.
RENGLONES_DEL_CONSECUTIVO = 6
NOTIFICACION_PERSONAL = "NOTIFICACION PERSONAL"
#: Cuando la notificación personal no se pudo hacer, la empresa notifica por
#: aviso: la carta «Asunto: Notificación por aviso» y la publicación del aviso
#: en su página. Son la notificación de esa respuesta, y van solas como la
#: personal (4100976, UPD2456242, 2026-11-19: la publicación, la notificación,
#: la contestación y las hojas de un acta de 2021 salían en un solo PDF).
NOTIFICACION_POR_AVISO = "NOTIFICACION POR AVISO"
PUBLICACION_DEL_AVISO = "PUBLICACION DEL AVISO"
#: Las notificaciones de la empresa: lo que sigue a una de ellas sin ser su
#: anexo evidente es otro documento, y la respuesta detrás de ellas también.
NOTIFICACIONES = frozenset({NOTIFICACION_PERSONAL, NOTIFICACION_POR_AVISO, PUBLICACION_DEL_AVISO})
RESPUESTA_DE_LA_EMPRESA = "RESPUESTA DE LA EMPRESA"
LEY_HABEAS_DATA = "LEY HABEAS DATA"
#: Los formatos de la empresa con su membrete -- «Una filial del Grupo EPM ·
#: CARIBEMAR DE LA COSTA S.A.S. ESP · Nit: 901.380.949-1» --: el EXPEDIENTE, la
#: CONSTANCIA DE CONTRATACIÓN DE SERVICIO. Lo dictó el operador el 2026-11-23:
#: «los documentos que tengan esto en primera página siempre irán solos
#: divididos, con sus respectivas fechas y título». En 4251482 (UPD2447022
#: pág. 8) el EXPEDIENTE salía dentro de la declaración de delante.
FORMATO_DE_LA_EMPRESA = "FORMATO DE LA EMPRESA"
#: Y la declaración bajo gravedad de juramento: «también va sola, con su
#: respectivo anexo muy bien analizado antes de unirlo» (el mismo día).
DECLARACION_JURAMENTADA = "DECLARACION BAJO GRAVEDAD DE JURAMENTO"
#: El membrete en la cabeza de la hoja: el nombre de la empresa y su NIT, como
#: lo deja el escáner («CARIBEMAR DE LA COSTA S.A.S. ESP», «Nit: 901.380.949-1»).
_MEMBRETE = re.compile(r"CARIBE\s?MAR\s+DE\s+LA\s+COSTA")
_NIT_DE_LA_EMPRESA = re.compile(r"N\W?[I1L]\W?T\W{0,3}\s*9\s?[0O]\s?1\W?\s?3\s?8\s?[0O]\W?\s?9\s?4\s?9")
#: En cuántos renglones del principio va el membrete.
RENGLONES_DEL_MEMBRETE = 10
#: Lo que trae el membrete sin ser un formato que va solo: el estado de cuenta
#: -- el operador, 2026-11-23: «anexo del anterior» -- y la factura.
_SOPORTE_CON_MEMBRETE = re.compile(r"ESTADO\s+DE\s+CUENTA\s+POR\s+(?:NIC|IDENTIFICADOR)|OPERADOR\s+DE\s+RED")


#: Los procesos que la declaración ofrece para marcar con una «x», como los
#: imprime el formato, con el nombre que toman (el operador, 2026-11-23: «le
#: colocarás el título dependiendo lo que esté seleccionado»).
PROCESOS_DE_LA_DECLARACION: tuple[tuple[str, str], ...] = (
    ("RECONOCIMIENTO DE ACTIVOS", r"RECONOCIMIENTO\s+DE\s+ACTIVOS"),
    ("CAMBIO DE TITULAR DE CONTRATO", r"CAMBIO\s+DE\s+TITULAR\s+DE\s+CONTRATO"),
    ("SOLICITUD DE CONTRATACION NUEVO SUMINISTRO", r"SOLICITUD\s+DE\s+CONTRATACION\s+NUEVO\s+SUMINISTRO"),
    ("BAJA DE CONTRATO", r"BAJA\s+DE\s+CONTRATO"),
)
#: La casilla marcada justo detrás de su proceso, como la transcribe el OCR de
#: pago: «Cambio de Titular de Contrato ☑» (4251482 pág. 4). La vacía, «☐».
_CASILLA_MARCADA = r"\s*(?:☑|☒|✓|✔|✅|\[\s*X\s*\]|\(\s*X\s*\)|\|\s*X\s*\||X(?![A-Z]))"
#: Lo escrito en «Otro Proceso, ¿Cuál?», hasta el párrafo que sigue.
_OTRO_PROCESO = re.compile(r"OTRO\s+PROCESO\W{0,4}\s*\W?CUAL\W{0,3}\s*(?P<cual>.{0,90}?)\s*(?:MEDIANTE\b|$)", re.DOTALL)
#: Cómo se llama la declaración con su proceso: «DECLARACION BGDJ - CAMBIO DE TITULAR DE CONTRATO».
SIGLA_DE_LA_DECLARACION = "DECLARACION BGDJ"
#: Lo más largo que se deja ser al proceso escrito a mano.
LARGO_DEL_OTRO_PROCESO = 50


def _sin_tildes(texto: str) -> str:
    """En mayúsculas y sin tildes, pero con los símbolos de las casillas (☑, ☐)."""
    return "".join(c for c in unicodedata.normalize("NFD", texto or "") if not unicodedata.combining(c)).upper()


def proceso_de_la_declaracion(texto: str) -> str | None:
    """El proceso que la declaración trae marcado, o lo escrito en «Otro Proceso, ¿Cuál?»; ``None`` si no se sabe.

    Del texto del OCR de pago, que transcribe las casillas: una sola marcada
    da su proceso. Sin ninguna marcada, lo que diga «¿Cuál?» -- «Aumento de
    Potencia» (4251482 pág. 11) --, si son palabras. Dos marcadas, o nada, no
    dan nada: nunca se adivina. La capa del escáner no sirve: rompe la «x» en
    «Leo]», «JU]», «XK».
    """
    plano = " ".join(_sin_tildes(texto).split())
    marcadas = [nombre for nombre, proceso in PROCESOS_DE_LA_DECLARACION if re.search(proceso + _CASILLA_MARCADA, plano)]
    if len(marcadas) == 1:
        return marcadas[0]
    if marcadas:
        return None
    hallado = _OTRO_PROCESO.search(plano)
    if hallado is None:
        return None
    cual = re.sub(r"[^A-Z ]", " ", hallado.group("cual"))
    palabras = [p for p in cual.split() if len(p) >= 2]
    if sum(len(p) for p in palabras) < 6 or not any(len(p) >= 4 for p in palabras):
        return None
    return " ".join(palabras)[:LARGO_DEL_OTRO_PROCESO].strip()


def nombre_de_la_declaracion(proceso: str | None) -> str:
    """«DECLARACION BGDJ - <proceso>», o el nombre de siempre si no se sabe el proceso."""
    return f"{SIGLA_DE_LA_DECLARACION} - {proceso}" if proceso else DECLARACION_JURAMENTADA


def trae_el_membrete(texto: str) -> bool:
    """Si la hoja lleva arriba el membrete de la empresa: su nombre y su NIT en los primeros renglones."""
    renglones = [r for r in (texto or "").splitlines() if r.strip()][:RENGLONES_DEL_MEMBRETE]
    cabeza = _plano(" ".join(renglones))
    return bool(_MEMBRETE.search(cabeza)) and bool(_NIT_DE_LA_EMPRESA.search(cabeza))

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


#: La causa de una constancia de PQR que es parte del acuerdo de pago: lo que el
#: usuario pidió para firmarlo (UPD3102729: «Facilidades de pago», «Gestionar
#: financiación»).
_CAUSA_DEL_ACUERDO = re.compile(
    r"FINANCIA|FACILIDAD\w*\s+DE\s+PAGO|ACUERDO\s+DE\s+PAGO|CONVENIO\s+DE\s+PAGO|REFINANC"
)


def causa_de_la_constancia(texto: str) -> str | None:
    """La «CAUSA:» de una constancia de PQR, plana; ``None`` si no la trae."""
    renglones = (texto or "").splitlines()[:RENGLONES_DE_CABECERA]
    for i, renglon in enumerate(renglones):
        hallado = _CAUSA.match(renglon.strip())
        if hallado is None:
            continue
        causa = hallado.group("s").strip() or (renglones[i + 1].strip() if i + 1 < len(renglones) else "")
        return _plano(causa) or None
    return None


def es_causa_del_acuerdo(causa: str | None) -> bool:
    """Si la causa de una constancia es pedir la financiación que el acuerdo concede."""
    return bool(causa) and bool(_CAUSA_DEL_ACUERDO.search(_plano(causa)))


def es_carta_de_la_empresa(texto: str) -> bool:
    """Si la carta es de la empresa -- su respuesta, su citación -- y no del cliente.

    Lleva su consecutivo, o se titula como lo que la empresa le manda al
    cliente. Es la que el trámite une a su escrito por el RE que cita.
    """
    cabeza = " ".join(_plano(r) for r in (texto or "").splitlines()[:RENGLONES_DE_CABECERA])
    if _DE_LA_EMPRESA.search(cabeza):
        return True
    return titulo_del_documento(texto).startswith(("RESPUESTA", "CITACION", "NOTIFICACION", "CONSTANCIA"))


def formulario_que_abre(texto: str) -> str | None:
    """El formulario que empieza en esta hoja y que abre su propio documento.

    - La constancia de reclamación, la notificación personal y la carta de la
      empresa con su «Consecutivo No.» -- la respuesta que la notificación
      entrega -- van cada una en su documento.
    - La Ley Habeas Data y las piezas del acuerdo de pago también se separan
      de lo que tengan delante; después el acuerdo las junta en el suyo.
    - La declaración bajo gravedad de juramento y los formatos con el membrete
      de la empresa -- el EXPEDIENTE, la CONSTANCIA DE CONTRATACIÓN -- van
      solos, con sus anexos (2026-11-23).

    Sólo la primera hoja: la que sigue a la respuesta («Por lo anterior…») no
    trae consecutivo y sigue con ella.
    """
    titulo = titulo_del_documento(texto or "")
    if titulo in PIEZAS_DEL_ACUERDO:
        return ACUERDO_DE_PAGO
    if titulo == CONSTANCIA_DE_RECLAMACION:
        return CONSTANCIA_DE_RECLAMACION
    if titulo.startswith(NOTIFICACION_PERSONAL):
        return NOTIFICACION_PERSONAL
    if titulo == PUBLICACION_DEL_AVISO:
        return PUBLICACION_DEL_AVISO
    if titulo.startswith(NOTIFICACION_POR_AVISO):
        return NOTIFICACION_POR_AVISO
    if titulo == LEY_HABEAS_DATA:
        return LEY_HABEAS_DATA
    # El consecutivo en el encabezado, no citado en el cuerpo: en las
    # respuestas de Magangué está en los primeros cuatro renglones; en las
    # cajas de referencia aparecía en el renglón 13 o el 37 de hojas que no
    # abren nada (UPD2366126, UPD2365925).
    renglones = [r for r in (texto or "").splitlines() if r.strip()][:RENGLONES_DEL_CONSECUTIVO]
    if _DE_LA_EMPRESA.search(" ".join(_plano(r) for r in renglones) + " "):
        return RESPUESTA_DE_LA_EMPRESA
    # La carta de Electricaribe con su «MESUC» es la misma clase de carta: la
    # respuesta de la empresa, con sus reglas para abrir (2026-11-24).
    if titulo == RESPUESTA_A_USUARIO:
        return RESPUESTA_DE_LA_EMPRESA
    # La declaración juramentada y los formatos con el membrete de la empresa
    # van solos, con su anexo (el operador, 2026-11-23). No el estado de
    # cuenta ni la factura, que traen el membrete y son anexos.
    if titulo == DECLARACION_JURAMENTADA:
        return DECLARACION_JURAMENTADA
    if trae_el_membrete(texto) and not _SOPORTE_CON_MEMBRETE.search(_plano(" ".join((texto or "").split()))):
        return FORMATO_DE_LA_EMPRESA
    return None


def escrito_que_interpone(primera_pagina: str) -> str | None:
    """El escrito del trámite que la carta dice interponer en su cuerpo: «interponer DERECHO DE PETICION».

    Para la carta cuyo asunto la llama «SOLICITUD…» y que en su cuerpo dice qué
    escrito presenta (1005965, UPD3102771, 2026-11-11: dos derechos de petición
    con un mes de distancia que salían en un solo PDF). ``None`` si no lo dice.
    """
    renglones = [_plano(r) for r in (primera_pagina or "").splitlines()[:RENGLONES_DE_CABECERA]]
    cabeza = " ".join(renglones)
    for verbo in _INTERPONE.finditer(cabeza):
        propio = _titulo_del_escrito(cabeza[verbo.end() : verbo.end() + 60])
        if propio:
            return propio
    return None


#: El nombre de la respuesta de la empresa a una reclamación. Lo dictó el
#: operador el 2026-11-11 ante 1016215 (UPD2437946 p7): «cuando un documento
#: tenga este formato» -- «Consecutivo No. …», «CIUDAD, fecha», «ASUNTO:
#: Reclamación No. RE…» -- «le colocarás el RE y como nombre contestación a
#: reclamación»; y el 2026-11-18, con «LA»: «CONTESTACIÓN A LA RECLAMACIÓN», el
#: mismo para las cartas de la empresa que abren «EN ATENCIÓN A…». No es un
#: tipo del catálogo del cliente: es su nombre. Y desde el 2026-11-20, «ya no es
#: contestación a la reclamación: respuesta a la reclamación, se llamará así»
#: (el operador): «RESPUESTA A LA RECLAMACION», con su RE.
CONTESTACION_A_RECLAMACION = "RESPUESTA A LA RECLAMACION"
#: «ASUNTO: Reclamación No. RE9234202200564», con lo que la OCR le haga.
_ASUNTO_DE_RECLAMACION = re.compile(r"\bASUNTO\W{0,3}\s*RECLAMACI\w{0,3}\s+N\W{0,2}[O0]?\W{0,3}\s*R\W?E\s?\d")
#: «En atención a su petición…», «En atención al recurso interpuesto…»: como
#: abre la empresa su respuesta (1005117, UPD2973878 p18; el operador,
#: 2026-11-18). Con la «L» de «al».
_EN_ATENCION_A = re.compile(r"\bEN\s+ATENCI\w{0,3}\s+AL?\b")
#: La carta que va dirigida a la empresa es del usuario, no su respuesta:
#: «Señores CARIBEMAR DE LA COSTA S.A.S. E.S.P.», «Señores AFINIA».
_A_LA_EMPRESA = re.compile(r"\bSE\W?N?ORES\W{0,3}\s*(?:CARIBE\s?MAR|AFINIA|ELECTRICARIBE)")
#: Hasta dónde se busca su asunto: va bajo el destinatario y su dirección.
CABEZA_DE_LA_CONTESTACION = 900

#: La carta que Electricaribe le manda al usuario desde su oficina comercial:
#: «MESUC 2818» en el encabezado, «Oficina Comercial: Electricaribe S.A. ESP –
#: Mercados Especiales», «Señor(a): …», «Estimado usuario:». Se llama así por
#: su formato (el operador, 2026-11-24, ante 920933, UPD2998261 pág. 2: «ya no
#: se llamará recurso de queja sino RESPUESTA A USUARIO»). La IA la llamaba
#: RECURSO DE QUEJA por el recurso que el cuerpo le explica al usuario. No es un
#: tipo del catálogo del cliente ni lleva RE: es su nombre, como la respuesta a
#: la reclamación. El aviso que notifica esa misma carta trae el mismo «MESUC»
#: y sigue siendo la NOTIFICACION POR AVISO: su título se reconoce antes.
RESPUESTA_A_USUARIO = "RESPUESTA A USUARIO"
#: «MESUC 2818», con lo que el escáner le haga a sus letras: «MES UC», «MESUC2818».
_CONSECUTIVO_MESUC = re.compile(r"\bM\W?E\W?S\W?U\W?C\W{0,3}\s*\d{3,6}\b")
#: Que la carta va al usuario: su saludo, o la oficina comercial que la firma.
_CARTA_AL_USUARIO = re.compile(r"\bESTIMAD[OA]S?\s+USUARI|\bOFICINA\s+COMERCIAL\b")
#: Los nombres que dictó el operador para un papel por su formato: el nombrado
#: no se los discute a la IA ni al catálogo.
NOMBRES_DEL_OPERADOR = frozenset({CONTESTACION_A_RECLAMACION, RESPUESTA_A_USUARIO, NOTA_CREDITO_DEL_ASEO})
#: El formato que reconoce ``titulo_del_documento`` y el nombre que lleva por
#: él: la auditoría de la entrega avisa si el PDF se llama de otro modo.
NOMBRE_POR_SU_FORMATO: dict[str, str] = {
    RESPUESTA_A_USUARIO: RESPUESTA_A_USUARIO,
    AUTORIZACION_DEL_ASEO: NOTA_CREDITO_DEL_ASEO,
}


def es_respuesta_a_usuario(texto: str) -> bool:
    """Si la hoja tiene el formato de la carta de Electricaribe al usuario: «MESUC NNNN» en su encabezado.

    El «MESUC» tiene que ir en los primeros renglones, donde la empresa numera
    su carta: el escrito del usuario que cita «la comunicación MESUC 2808» lo
    hace en su cuerpo. Y la carta va al usuario -- «Estimado usuario», «Oficina
    Comercial» --, no a la empresa. No mira si es un aviso:
    :func:`titulo_del_documento` reconoce el aviso antes.
    """
    renglones = [r for r in (texto or "").splitlines() if r.strip()]
    encabezado = " ".join(_plano(r) for r in renglones[:RENGLONES_DEL_CONSECUTIVO])
    if not _CONSECUTIVO_MESUC.search(encabezado):
        return False
    cabeza = " ".join(_plano(r) for r in renglones[:RENGLONES_DE_CABECERA])
    return bool(_CARTA_AL_USUARIO.search(cabeza)) and _A_LA_EMPRESA.search(cabeza) is None


#: El número de la carta de la empresa en su encabezado: «Consecutivo
#: No.202270208732», «Consecutivo NO.A202270231268», «Consecutivo No. PA
#: 202270254853».
_NUMERO_DEL_CONSECUTIVO = re.compile(r"\bCONSECUTIVO\s+N[O0°º]?\W{0,3}\s*((?:[A-Z]{1,2}\s?)?\d{9,16})")


#: La notificación por aviso que adjunta la copia del acto que notifica: «el
#: acto administrativo Consecutivo No. 202070083927 de fecha 14-12-2020, cuya
#: copia íntegra se adjunta al presente Aviso» (4251461, UPD2447021 pág. 2).
_ADJUNTA_EL_ACTO = re.compile(
    r"COPIA\s+INTEGRA\s+SE\s+ADJUNTA|SE\s+ADJUNTA\s+(?:LA\s+)?COPIA|ADJUNT[OA]\s+(?:LA\s+)?COPIA\s+(?:INTEGRA\s+)?DEL\s+ACTO"
)
#: El acto que notifica, por su consecutivo: «acto administrativo Consecutivo No. 202070083927».
_ACTO_QUE_NOTIFICA = re.compile(r"ACTO\s+ADMINISTRATIVO\s+(?:CONSECUTIVO\s+)?N[O0°º]?\W{0,3}\s*(\d{9,16})")
#: La hoja que sólo anuncia el anexo del aviso: «ANEXO: Copia del acto
#: administrativo Consecutivo No. 202070083927 de fecha 14-12-2020» (pág. 3).
_PORTADA_DEL_ANEXO = re.compile(
    r"\bANEXO\W{0,3}\s*COPIA\s+DEL\s+ACTO\s+ADMINISTRATIVO(?:\s+CONSECUTIVO\s+N[O0°º]?\W{0,3}\s*(\d{9,16}))?"
)
#: Cuántos renglones con algo puede tener la portada: es una hoja casi en blanco.
RENGLONES_DE_LA_PORTADA = 8


#: El título que imprime la carátula con membrete, en su propio renglón (el
#: operador, 2026-11-24, ante 4251482: «la idea es aplicarle el título que está
#: allí», el subrayado). El EXPEDIENTE salía «AUMENTO DE CARGA» por su casilla
#: «Tipo de Solicitud: Aumentos de potencia». No el campo «No. Expediente:» ni
#: «Número de Expediente:», que trae también la constancia de contratación.
_TITULOS_DE_LA_CARATULA: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "CONSTANCIA DE CONTRATACION DE SERVICIO",
        re.compile(r"^\W*" + _CONSTAN + r"\s+DE\s+CONTRATACI\w{1,3}(?:\s+DEL?\s+SERVICIOS?)?\W*$"),
    ),
    ("EXPEDIENTE", re.compile(r"^\W*EXPEDIENTE\W*$")),
)
#: Hasta qué renglón con algo se busca: el título va en la cabecera.
RENGLONES_DEL_TITULO_DE_LA_CARATULA = 20


def titulo_de_la_caratula(texto: str) -> str | None:
    """El título impreso de la carátula con membrete: CONSTANCIA DE CONTRATACION DE SERVICIO o EXPEDIENTE; ``None`` si no.

    Nombra el paquete de la empresa que la carátula abre
    (``application.anexos_declarados.unir_el_paquete_de_la_empresa``), y su
    fila del índice.
    """
    if formulario_que_abre(texto or "") != FORMATO_DE_LA_EMPRESA:
        return None
    renglones = [_plano(r) for r in (texto or "").splitlines() if r.strip()][:RENGLONES_DEL_TITULO_DE_LA_CARATULA]
    for nombre, patron in _TITULOS_DE_LA_CARATULA:
        if any(patron.match(renglon) for renglon in renglones):
            return nombre
    return None


def acto_que_adjunta(texto: str) -> str | None:
    """El consecutivo del acto que la notificación por aviso dice adjuntar; «» si no lo da; ``None`` si no adjunta.

    El aviso que adjunta la copia íntegra del acto se la lleva, con la portada
    «ANEXO»: el operador, 2026-11-24, ante 4251461, como el reconocimiento de
    deuda se lleva sus anexos.
    """
    if not titulo_del_documento(texto or "").startswith(NOTIFICACION_POR_AVISO):
        return None
    plano = _plano(" ".join((texto or "").split()))
    if not _ADJUNTA_EL_ACTO.search(plano):
        return None
    hallado = _ACTO_QUE_NOTIFICA.search(plano)
    return hallado.group(1) if hallado else ""


def portada_del_anexo(texto: str) -> str | None:
    """El consecutivo que anuncia la portada «ANEXO: Copia del acto administrativo…»; «» sin él; ``None`` si no es."""
    renglones = [r for r in (texto or "").splitlines() if r.strip()]
    if len(renglones) > RENGLONES_DE_LA_PORTADA:
        return None
    hallado = _PORTADA_DEL_ANEXO.search(_plano(" ".join(renglones)))
    if hallado is None:
        return None
    return hallado.group(1) or ""


#: De qué responde o notifica la hoja: el reclamo o el recurso contra su
#: respuesta. Un mismo RE lleva las dos, cada una con su notificación personal
#: (6834699, 7740476: «Tipo de PQR: Reclamo» y «Tipo de PQR o Asunto:
#: REC_REPOSICION EN SUBSIDIO DE APELACION»).
INSTANCIA_DEL_RECLAMO, INSTANCIA_DEL_RECURSO = "reclamo", "recurso"
#: El renglón de la notificación personal: «Tipo de PQR:», «Tipo de POR o
#: Asunto;» (la OCR lee la Q como O).
_TIPO_DE_LA_PQR = re.compile(r"TIPO\s+DE\s+(?:LA\s+)?P\W?[QO0]\W?R\b(?:\s+O\s+ASUNTO)?\s*[:;]\s*(.{0,60})")
#: El asunto de la respuesta: «ASUNTO: Reclamación No. RE…», «ASUNTO: Recurso
#: de Reposición en subsidio de apelación No. RE…».
_ASUNTO_DE_LA_RESPUESTA = re.compile(r"\bASUNTO\s*[:;]\s*(.{0,60})")
_ES_EL_RECURSO = re.compile(r"RECURSO|REPOSICI|APELACI|\bQUEJA|\bREC_")


def instancia_de_la_pqr(texto: str) -> str | None:
    """De qué es la hoja: ``INSTANCIA_DEL_RECLAMO``, ``INSTANCIA_DEL_RECURSO`` o ``None`` si no lo dice.

    La notificación personal lo dice en su «Tipo de PQR»; la respuesta de la
    empresa, en su «ASUNTO». Empareja cada notificación con la respuesta que
    notifica cuando un RE trae dos (el operador, 2026-11-24).
    """
    plano = _plano(texto or "")
    hallado = _TIPO_DE_LA_PQR.search(plano) or _ASUNTO_DE_LA_RESPUESTA.search(plano)
    if hallado is None or not hallado.group(1).strip():
        return None
    return INSTANCIA_DEL_RECURSO if _ES_EL_RECURSO.search(hallado.group(1)) else INSTANCIA_DEL_RECLAMO


def consecutivo_de(texto: str) -> str | None:
    """El consecutivo con que la empresa numera su carta, sin espacios, o ``None``.

    Sólo el del encabezado: el cuerpo de un recurso del cliente también cita el
    consecutivo que recurre.
    """
    renglones = [r for r in (texto or "").splitlines() if r.strip()][:RENGLONES_DEL_CONSECUTIVO]
    hallado = _NUMERO_DEL_CONSECUTIVO.search(" ".join(_plano(r) for r in renglones))
    return hallado.group(1).replace(" ", "") if hallado else None


def es_contestacion_a_reclamacion(texto: str) -> bool:
    """Si la hoja abre la respuesta de la empresa a una reclamación: la CONTESTACIÓN A LA RECLAMACIÓN.

    Sólo cartas de la empresa (lo eligió el operador el 2026-11-18): nunca una
    notificación, una constancia, una pieza del acuerdo ni la Habeas Data, que
    también citan la respuesta. Lo es:

    - la carta con su «Consecutivo No.» en el encabezado
      (``formulario_que_abre``) que en su asunto cita la reclamación con su RE
      (2026-11-11), o que abre «EN ATENCIÓN A…» (2026-11-18);
    - la que no dejó leer su consecutivo pero cita la reclamación en su asunto,
      abre «EN ATENCIÓN A…» y no va dirigida a la empresa: la carta del
      usuario se dirige a «Señores Caribemar»; la respuesta, al usuario.

    Sólo la primera hoja: la que sigue no trae ninguna de esas señales.
    """
    formulario = formulario_que_abre(texto or "")
    if formulario not in (RESPUESTA_DE_LA_EMPRESA, None):
        return False
    # La carta «MESUC» tiene su propio nombre por su formato (2026-11-24).
    if titulo_del_documento(texto or "") == RESPUESTA_A_USUARIO:
        return False
    cabeza = _plano(" ".join((texto or "").split())[:CABEZA_DE_LA_CONTESTACION])
    cita_la_reclamacion = _ASUNTO_DE_RECLAMACION.search(cabeza) is not None
    en_atencion = _EN_ATENCION_A.search(cabeza) is not None
    if formulario == RESPUESTA_DE_LA_EMPRESA:
        return cita_la_reclamacion or en_atencion
    return cita_la_reclamacion and en_atencion and _A_LA_EMPRESA.search(cabeza) is None


#: La carta de instrucciones escrita como título: en mayúsculas, como la
#: imprime el formato -- «CARTA DE INSTRUCCIONES ANEXA A PAGARE No.» --, o con
#: el «ANEXA» que la sigue aunque la OCR le cambie la caja.
_CARTA_COMO_TITULO = re.compile(r"CARTA\s+DE\s+INSTRUCCIONES")
_CARTA_ANEXA = re.compile(r"CARTA\s+DE\s+INSTRUCCIONES\s+ANEX", re.IGNORECASE)


def _carta_en_su_titulo(renglones: Sequence[str]) -> bool:
    """Si la hoja ES una carta de instrucciones, y no la nombra de pasada.

    La tercera hoja del contrato de transacción de 2023 empieza «TERCERO: Para
    garantizar el pago… EL CLIENTE suscribe… un pagaré en blanco con carta de
    instrucciones», y se llamaba CARTA DE INSTRUCCIONES: el acuerdo de pago se
    la llevaba con la cédula de detrás, saltando la constancia de en medio, y el
    contrato quedaba sin sus firmas (1004569/UPD2437853 pág. 4, 2026-11-05).
    Las tildes se quitan sin cambiar la caja: el escáner lee «CARTA DÉ
    INSTRUCCIONES ANEXA» (UPD2326357 pág. 2). Medido sobre 365 PDF: de 231
    cartas sólo deja de serlo esa hoja del contrato.
    """
    cabeza = " ".join(renglones)
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", cabeza) if not unicodedata.combining(c)
    )
    return bool(_CARTA_COMO_TITULO.search(sin_tildes) or _CARTA_ANEXA.search(" ".join(sin_tildes.split())))


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
    # Para los formatos impresos, los renglones que traen algo: la capa rota
    # los empuja fuera de la cabecera con renglones de ruido. Sólo para ellos:
    # con todo lo demás, la ventana más honda alcanza la publicidad de una
    # factura -- «Solicitud de nuevos…» -- y la titula (4100982 pág. 4).
    utiles = renglones_de_la_cabecera(primera_pagina)
    cabeza_util = " ".join(_plano(r) for r in utiles)
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
    if any(_PUBLICACION_DEL_AVISO.match(r) for r in renglones):
        return "PUBLICACION DEL AVISO"
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
    if (
        _CONSTANCIA.search(cabeza)
        or _OTRAS_CONSTANCIAS.search(cabeza)
        or all(campo.search(cabeza) for campo in _FORMULARIO_DE_LA_CONSTANCIA)
    ):
        return CONSTANCIA_DE_RECLAMACION
    for nombre, patron in _POR_LO_QUE_DICEN:
        if patron.search(cabeza):
            return nombre
    for renglon in renglones:
        for nombre, patron in _TITULOS_DE_LA_EMPRESA:
            if patron.search(renglon) and len(renglon) <= 60:
                return nombre
    # La carta de Electricaribe al usuario, por su formato: «MESUC 2818»
    # (el operador, 2026-11-24). Después del aviso, que trae el mismo MESUC.
    if es_respuesta_a_usuario(primera_pagina):
        return RESPUESTA_A_USUARIO
    for nombre, patron in _FORMATOS:
        en_la_cabeza = patron.search(cabeza[:CABEZA_DEL_FORMATO])
        if en_la_cabeza or patron.search(cabeza_util[:CABEZA_DEL_FORMATO]):
            if nombre == "CARTA DE INSTRUCCIONES" and not _carta_en_su_titulo(originales if en_la_cabeza else utiles):
                continue
            return nombre
    # El REF o el ASUNTO que ya es un tipo del catálogo: «REFERENCIA:
    # DECLARACION BAJO GRAVEDAD DE JURAMENTO» (1000265, salía «SOLICITUD» por
    # una casilla del formulario).
    for asunto in asuntos:
        del_catalogo = _tipo_del_catalogo(asunto)
        if del_catalogo:
            return del_catalogo
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
