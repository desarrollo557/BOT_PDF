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
#: El membrete: quien emite, no qué es el papel.
_MEMBRETE = re.compile(r"\b(?:AFINIA|GRUPO\s*EPM|ELECTRICARIBE|CARIBEMAR|SIAR|S\.?\s*A\.?\s*S?\.?\s*E\.?\s*S\.?\s*P)\b")
#: Una fecha suelta: «26 , Nov de 2022», «Valledupar, 02 de diciembre de 2020».
_MESES = r"ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|SET|OCT|NOV|DIC"
_FECHA = re.compile(rf"\b(?:{_MESES})\w*\.?\s+(?:DE\s+)?\d{{4}}\b|\b\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}\b")


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
    """El título que imprime la hoja en su encabezado, o ``None`` si no imprime ninguno."""
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
