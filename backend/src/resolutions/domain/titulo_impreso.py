"""El título impreso en el encabezado de una hoja: lo que el papel dice ser.

Lo pidió el operador el 2026-10-20 al abrir «01_DOCUMENTO.pdf» de la caja
UPD2998266: la hoja decía bien grande «ACTA DE VERIFICACIÓN DE PREDIO
DESOCUPADO», y el archivo salió llamado «DOCUMENTO». La regla, para todo el
software: **ningún documento se entrega sin un nombre que lo referencie**. Lo
que el catálogo y los títulos conocidos no reconocen se llama como su
encabezado, y sólo si la hoja no deja leer ninguno, por su origen y sus páginas.

Un título impreso se distingue del resto del encabezado así, medido sobre las
cajas de Afinia:

- va en los primeros renglones, en mayúsculas, con dos a catorce palabras;
- lo que más lo delata es su primera palabra: ACTA, FORMATO, CONSTANCIA,
  CERTIFICADO, SOLICITUD, CONTRATO… -- la clase de papel --;
- no es la fecha («26 Nov de 2022»), ni el membrete («afinia Grupo-epm»), ni el
  rótulo del formato («REVISIÓN 1», «FECHA: 17/01/2012»), ni un saludo;
- y la OCR no lo rompió: «FORMATO DE DAS DA Pe MA E MODIFICADOS» no es un
  título, aunque empiece como uno.

Aquí no se lee papel: entra el texto y sale el título, o ``None``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

#: Cuántos renglones del principio de la hoja se miran.
RENGLONES_DEL_ENCABEZADO = 15
#: Lo más largo que se deja ser al título en el nombre de un archivo.
MAX_TITULO = 80
#: Palabras con que empieza el título de un papel: la clase de documento.
CLASES_DE_PAPEL = frozenset(
    {
        "ACTA", "ACTAS", "ACUERDO", "ANEXO", "AUTORIZACION", "AVISO", "CARTA",
        "CERTIFICADO", "CERTIFICACION", "CIRCULAR", "CITACION", "COMPROBANTE",
        "COMUNICADO", "CONSTANCIA", "CONTRATO", "CONVENIO", "CUENTA", "DECLARACION",
        "DERECHO", "ESTADO", "FACTURA", "FICHA", "FORMATO", "FORMULARIO", "INFORME",
        "INVENTARIO", "LIQUIDACION", "MEMORANDO", "MEMORIAL", "NOTIFICACION",
        "OFICIO", "ORDEN", "PAGARE", "PAZ", "PETICION", "PLANILLA", "PODER",
        "PROTOCOLO", "QUEJA", "RECIBO", "RECLAMACION", "RECLAMO", "RECURSO",
        "REGISTRO", "RELACION", "REPORTE", "REQUERIMIENTO", "RESOLUCION",
        "RESPUESTA", "SOLICITUD", "TRAMITE", "VERIFICACION", "VISITA",
    }
)
#: Las palabras cortas que sí van dentro de un título.
CONECTORES = frozenset({"DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "O", "E", "A", "AL", "EN", "POR", "PARA", "CON", "SU", "SUS", "N", "NO"})
#: Lo que está en el encabezado y no es el título.
_NO_ES_TITULO = re.compile(
    r"^(?:REVISION|VERSION|CODIGO|FECHA|PAGINA|PAG|HOJA|FOLIO|NIT|TEL|TELEFONO|CEL|"
    r"DIRECCION|CALLE|CARRERA|CRA|KM|WWW|HTTP|EMAIL|CORREO|SENOR|SENORA|SENORES|"
    r"ESTIMAD[OA]S?|CORDIAL|RESPETAD[OA]S?|APRECIAD[OA]S?|DOCTOR|DOCTORA|REF|"
    r"REFERENCIA|ASUNTO|NIC|CC|RADICADO|CONSECUTIVO|VO|VOBO|FIRMA|NOMBRE|"
    r"IDENTIFICACION|IDENTIFICADO|EL|LA|YO|QUE|POR\s+MEDIO|CUENTA\s+INTERNA|MATRICULA)\b"
)
#: El membrete: quien emite, no qué es el papel. También el del comité o la
#: entidad que escribe la carta: «COMITE DE DESARROLLO Y CONTROL SOCIAL DE LOS
#: SERVICIOS / PUBLICOS DOMICILIARIOS DE MAGANGUE BOLIVAR» (UPD3102756).
_MEMBRETE = re.compile(
    r"\b(?:AFINIA|GRUPO\s*EPM|ELECTRICARIBE|CARIBEMAR|SIAR|S\.?\s*A\.?\s*S?\.?\s*E\.?\s*S\.?\s*P"
    r"|COMITES?|PUBLICOS\s+DOMICILIARIOS|SUPERINTENDENCIA)\b"
)
#: Una fecha suelta: «26 , Nov de 2022», «Valledupar, 02 de diciembre de 2020».
_MESES = r"ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|SET|OCT|NOV|DIC"
_FECHA = re.compile(rf"\b(?:{_MESES})\w*\.?\s+(?:DE\s+)?\d{{4}}\b|\b\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}\b")

# -- el formato que se reconoce por sus marcas ---------------------------------------

#: La planilla del recaudador «FORMATO DE RELACIÓN DIARIA DE PAGOS No. 8055349»:
#: fecha, punto de pago y gestor arriba, una tabla de 25 pagos («VR. PAGADO»,
#: «ABONO A DEUDA», «MES APLICADO») y al pie «Valor Recaudado» y «Valor a
#: consignar». Su título va en dos renglones y el genérico sólo tomaba el
#: primero, «FORMATO DE RELACION». Lo dictó el operador el 2026-11-26 ante
#: UPD2995828, que salió «01_DOCUMENTO.pdf»: «no quiero nombres genéricos…
#: sino originales evidenciados en el mismo documento… apliquémoslo solo a este
#: formato». Sin el número de la planilla: es de cada hoja, no del formato.
RELACION_DIARIA_DE_PAGOS = "FORMATO DE RELACION DIARIA DE PAGOS"
#: En cuántos renglones con algo del principio se busca su título: la capa lo
#: pone tras «FECHA:» y la OCR de casa, tras el punto de pago y el gestor.
RENGLONES_DEL_FORMATO = 20
#: Su título, como lo dejan la capa y Tesseract: «DIARIA Di: PAGOS», «DIARIA
#: Df: PAGO5», «D£ PAGOs», y los dos renglones separados por lo que el escáner
#: lee en medio («FORMATO DE RELACIÓN / Tesal / [ / S / O / DIARIA DE PAGOS»).
_TITULO_DE_LA_RELACION_DIARIA = re.compile(
    r"F[O0]RMAT[O0]\s*D[EF]\s*RELACI[O0][NM][\s\S]{0,40}?D[I1L]AR[I1L]A\s*D\w?\W{0,2}\s*PAG[O0][S5]"
)
#: Lo que puede seguir al título en su renglón: nada, o su «No.». Otra palabra
#: es otro formato que empieza igual: «… DIARIA DE PAGOS ANULADOS».
_RESTO_DEL_TITULO = re.compile(r"\s*(?:N\W?[O0°º](?![A-Z]).*|[\W\d_]*)")
#: El número de la planilla pegado al título: «No. 8055349», «No. 8055:348».
_NUMERO_DE_LA_PLANILLA = re.compile(r"\s*N\W?[O0°º]\W{0,3}\s*\d{3,}\W?\d{2,}")
#: Lo que sólo imprime su tabla o su pie: «VR. PAGADO», «ABONO A DEUDA», «MES
#: APLICADO», «Valor Recaudado», «Valor a consignar», la nota «Cualquier
#: enmendadura anula el registro» y el visto bueno del «Pyme/Recaudador».
_MARCAS_DE_LA_RELACION_DIARIA = re.compile(
    r"\bVR\W{0,2}\s*PAGAD[O0]\b|\bAB[O0]N[O0]\s+A\s+DEUDA\b|\bMES\s+APLICAD[O0]\b"
    r"|\bVAL[O0]R\s+RECAUDAD[O0]\b|\bVAL[O0]R\s+A\s+C[O0]NSIGNAR\b"
    r"|\bENMENDADURA\s+ANULA\s+EL\s+REGISTR[O0]\b|\bPYME\W{0,2}\s*RECAUDAD[O0]R\b"
)


def _sin_tildes(texto: str) -> str:
    """En mayúsculas y sin tildes, con sus renglones."""
    return "".join(c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c)).upper()


def titulo_por_su_formato(texto: str) -> str | None:
    """El título de un formato que se reconoce por sus marcas impresas, o ``None``.

    Hoy uno solo, el FORMATO DE RELACION DIARIA DE PAGOS (el operador,
    2026-11-26). Se reconoce por su título -- «FORMATO DE RELACIÓN» y «DIARIA
    DE PAGOS», aunque el escáner los parta o los rompa -- y por algo que sólo él
    imprime, para no confundirlo con otro: una marca de su tabla o de su pie, o
    el número de la planilla pegado al título. Esto último hace falta: la OCR
    de casa leyó de UPD2995828 pág. 4 sólo el recuadro del título, y la misma
    planilla habría salido con dos nombres en la caja.

    Sólo nombra, como todo título impreso: no corta ni decide el RE.
    """
    renglones = [r for r in (texto or "").splitlines() if r.strip()][:RENGLONES_DEL_FORMATO]
    cabeza = _sin_tildes("\n".join(renglones))
    hallado = _TITULO_DE_LA_RELACION_DIARIA.search(cabeza)
    if hallado is None:
        return None
    resto = cabeza[hallado.end() :].split("\n", 1)[0]
    if not _RESTO_DEL_TITULO.fullmatch(resto):
        return None
    todo = re.sub(r"\s+", " ", _sin_tildes(texto or ""))
    if _NUMERO_DE_LA_PLANILLA.match(resto) or _MARCAS_DE_LA_RELACION_DIARIA.search(todo):
        return RELACION_DIARIA_DE_PAGOS
    return None


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.upper()).strip()


def _palabras(renglon: str) -> list[str]:
    return re.findall(r"[A-Z0-9]+", renglon)


def _roto(palabras: list[str]) -> bool:
    """Si la OCR lo dejó en pedazos: palabras de una o dos letras que no son conectores."""
    sueltas = [p for p in palabras if len(p) <= 2 and p not in CONECTORES and not p.isdigit()]
    sin_vocal = [p for p in palabras if len(p) >= 3 and not re.search(r"[AEIOU]", p) and not p.isdigit()]
    return len(sueltas) + len(sin_vocal) > max(1, len(palabras) // 5)


def _candidato(original: str) -> tuple[int, str] | None:
    """El renglón como título y lo que vale, o ``None`` si no lo es."""
    letras = [c for c in original if c.isalpha()]
    if len(letras) < 8:
        return None
    # Un campo del formulario con su valor -- «ASOCIADO COMERCIAL: 444 PA…» --
    # no es su título (945220, 2026-10-22).
    if re.search(r":\s*\S", original):
        return None
    # Impreso en mayúsculas: el título de un formato no va en letra de carta.
    if sum(c.isupper() for c in letras) / len(letras) < 0.8:
        return None
    plano = _plano(original)
    plano = re.sub(r"[^A-Z0-9 ]+", " ", plano)
    plano = re.sub(r"\s+", " ", plano).strip()
    palabras = _palabras(plano)
    # Sin el número suelto y la letra suelta del final que deja la OCR: «… MODIFICADOS A».
    while palabras and (palabras[-1].isdigit() or (len(palabras[-1]) == 1 and palabras[-1] not in {"Y", "O"})):
        palabras.pop()
    largas = [p for p in palabras if len(p) >= 3]
    if not 2 <= len(palabras) <= 14 or len(largas) < 2:
        return None
    titulo = " ".join(palabras)
    if _NO_ES_TITULO.match(titulo) or _MEMBRETE.search(titulo) or _FECHA.search(titulo):
        return None
    if _roto(palabras):
        return None
    valor = 3 if palabras[0] in CLASES_DE_PAPEL else 0
    valor += 1 if len(largas) >= 3 else 0
    # Sin la clase de papel delante, sólo vale si es un renglón corto y entero.
    if valor < 3 and len(palabras) > 8:
        return None
    return valor, titulo


def titulo_impreso(texto: str) -> str | None:
    """El título que imprime la hoja en su encabezado, o ``None`` si no imprime ninguno.

    El formato que se reconoce por sus marcas lleva su título entero, aunque el
    escáner lo parta en dos renglones (``titulo_por_su_formato``, 2026-11-26).
    """
    if por_su_formato := titulo_por_su_formato(texto):
        return por_su_formato
    renglones = [r for r in (texto or "").splitlines() if r.strip()][:RENGLONES_DEL_ENCABEZADO]
    mejor: tuple[int, int, str] | None = None
    for posicion, renglon in enumerate(renglones):
        hallado = _candidato(renglon)
        if hallado is None:
            continue
        valor, titulo = hallado
        # Sin la clase de papel delante, sólo en lo alto de la hoja: más abajo,
        # un renglón en mayúsculas es un nombre o una dirección, no el título.
        if valor < 3 and posicion > 2:
            continue
        # El que lleva la clase de papel gana; entre iguales, el de más arriba.
        clave = (valor, -posicion, titulo)
        if mejor is None or clave[:2] > mejor[:2]:
            mejor = clave
    if mejor is None or mejor[0] < 1:
        return None
    titulo = mejor[2]
    if len(titulo) > MAX_TITULO:
        titulo = titulo[:MAX_TITULO].rsplit(" ", 1)[0]
    # Sin el conector en que quedó cortado: «… SUMINISTROS O».
    while (partes := titulo.rsplit(" ", 1)) and len(partes) == 2 and partes[1] in CONECTORES:
        titulo = partes[0]
    return titulo


def nombre_por_su_origen(origen: str, paginas: Sequence[int]) -> str:
    """El nombre de lo que no deja leer ningún título: de dónde salió y qué hojas.

    «UPD2998726 PAGINAS 1-3». Nunca «DOCUMENTO»: con esto el archivo se
    encuentra en su caja sin abrirlo, y el informe lo manda a revisión.
    """
    base = re.split(r"[\\/]", origen or "")[-1]
    base = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", base).strip().upper()
    base = re.sub(r"[^A-Z0-9 ]+", " ", _plano(base)).strip()
    if not paginas:
        return base or "SIN TITULO"
    desde, hasta = min(paginas), max(paginas)
    hojas = f"PAGINA {desde}" if desde == hasta else f"PAGINAS {desde}-{hasta}"
    return f"{base} {hojas}".strip()
