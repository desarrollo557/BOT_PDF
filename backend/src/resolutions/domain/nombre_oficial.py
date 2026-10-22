"""El nombre oficial de un documento: como lo llama el catálogo del cliente.

Lo pidió el operador el 2026-10-21 al abrir la entrega de UPD3102756: «colócale
el nombre al documento según el nombre oficial del documento del trámite, por
ejemplo derecho de petición, reclamo, pagaré, notificación personal, tanto en
el nombre del documento como en el inventario». Salían «RECLAMACION» -- que
no es un tipo del catálogo: el catálogo dice RECLAMO --, «SOLICITUD» a secas
para una solicitud de silencio administrativo positivo, y el membrete del
Comité, «PUBLICOS DOMICILIARIOS DE MAGANGUE BOLIVAR», para una carta que en su
REF dice qué es.

Dos reglas, en este orden:

1. **El título que el papel se da, con su nombre del catálogo.** El título
   conocido de la primera hoja (:func:`~.asunto_del_documento.titulo_del_documento`)
   se traduce al nombre canónico del listado del cliente (:mod:`.catalogo`), y
   el reclamo que en su asunto dice ser por consumo estimado es el «RECLAMO POR
   CONSUMO ESTIMADO» del catálogo.
2. **Lo que el catálogo no tiene, como lo nombra su asunto.** La clase de papel
   con su complemento -- «SOLICITUD DE RECONOCIMIENTO DE SILENCIO
   ADMINISTRATIVO POSITIVO» --, sin lo que ya es el motivo -- «… por no dar
   respuesta dentro de los términos» --.

Aquí no se lee papel: entran el título y el asunto, sale el nombre.
"""

from __future__ import annotations

import re
import unicodedata

from .catalogo import CATALOGO, FRASES

#: Los títulos que el bot conoce y su nombre en el catálogo del cliente.
AL_CATALOGO: dict[str, str] = {
    "RECLAMACION": "RECLAMO",
    "AUTORIZACION DE NOTIFICACION ELECTRONICA": "AUTORIZACION PARA LA NOTIFICACION ELECTRONICA",
    "RECONOCIMIENTO DE DEUDA Y ACUERDO DE PAGO": "RECONOCIMIENTO DE DEUDA Y PROPUESTA DE ACUERDO DE PAGO",
    "CONSTANCIA DE RECLAMACION": "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION",
}
#: El reclamo por consumo estimado, como lo escribe el cliente en su asunto:
#: «RECLAMO POR COBRO DE SERVICIO ENERGIA POR ESTIMADO» (UPD3102756 pág. 8).
_POR_ESTIMADO = re.compile(r"\bESTIMAD[OA]S?\b")
RECLAMO_POR_CONSUMO_ESTIMADO = "RECLAMO POR CONSUMO ESTIMADO"
#: Las clases de papel que sólo dicen algo con su complemento.
_GENERICOS = frozenset({"SOLICITUD", "DOCUMENTO"})
#: Donde acaba el nombre del papel en su asunto y empieza su motivo.
_MOTIVO = re.compile(
    r"\s(?:POR|EN|CONTRA|PARA|SOBRE|CON|A|AL|QUE|SEGUN|MEDIANTE|ANTE|NIC|N[O0]|RADICAD[OA])\b"
    r"|[,.;:()\[\]\-–—]"
)
#: Lo más largo que se deja ser al nombre.
MAX_NOMBRE = 80
#: Lo que no puede cerrar un nombre.
_COLGANDO = frozenset({"DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "O", "E"})


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.upper()).strip()


def nombre_del_asunto(asunto: str | None) -> str | None:
    """La clase de papel con su complemento, del renglón del asunto. ``None`` si no dice.

    «Solicitud de reconocimiento de silencio administrativo positivo por no dar
    respuesta…» → «SOLICITUD DE RECONOCIMIENTO DE SILENCIO ADMINISTRATIVO
    POSITIVO». «NOTIFICACION DEL REPORTE DEL SILENCIO ADMINISTRATIVO POSITIVO
    A LA SUPER SERVICIOS» → «NOTIFICACION DEL REPORTE DEL SILENCIO
    ADMINISTRATIVO POSITIVO».
    """
    plano = re.sub(r"[^A-Z0-9 ,.;:()\[\]\-–—]+", " ", _plano(asunto or ""))
    plano = re.sub(r"\s+", " ", plano).strip(" ,.;:-")
    if not plano:
        return None
    cortado = _MOTIVO.search(plano)
    nombre = plano[: cortado.start()] if cortado else plano
    palabras = [p for p in nombre.split() if p]
    while palabras and palabras[-1] in _COLGANDO:
        palabras.pop()
    largas = [p for p in palabras if len(p) >= 3 and not p.isdigit()]
    if len(palabras) < 2 or len(largas) < 2:
        return None
    nombre = " ".join(palabras)
    if len(nombre) > MAX_NOMBRE:
        nombre = nombre[:MAX_NOMBRE].rsplit(" ", 1)[0]
    return nombre


def estandarizar(nombre: str | None) -> str | None:
    """El nombre con su forma del catálogo, si es la de uno de sus tipos.

    Lo pidió el operador el 2026-10-22: «que los nombres de los tipos de
    documentos estén estandarizados… manejemos los nombres por estándares». El
    nombre que trae el papel con otra redacción -- «DECLARACION BAJO LA GRAVEDAD
    DE JURAMENTO», «CONSTANCIA DE RECEPCION DE PETICIONES QUEJAS Y RECLAMOS PQR»
    -- es el del catálogo: «DECLARACION BAJO GRAVEDAD DE JURAMENTO», «CONSTANCIA
    DE RECEPCION DE PETICIONES QUEJAS Y RECLAMOS». Vale si el nombre es una de
    sus formas o empieza por una de dos palabras o más; una palabra suelta dentro
    de un nombre largo no lo cambia.
    """
    if not nombre:
        return nombre
    plano = re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]+", " ", _plano(nombre))).strip()
    for frase, tipo in FRASES:
        if plano == frase or (len(frase.split()) >= 2 and plano.startswith(f"{frase} ")):
            return tipo.nombre
    return nombre


def instrucciones_para_nombrar() -> str:
    """Lo que se le pide a la IA para nombrar un documento que nada supo nombrar.

    Lo pidió el operador el 2026-10-22: «analiza todo el documento con la IA,
    contextualízala, y que de acuerdo al cuerpo del PDF le agregue el nombre;
    la idea es que no se vaya vacío». El contexto es el catálogo del cliente:
    la IA elige de ahí si el papel es uno de sus tipos.
    """
    tipos = "\n".join(f"- {tipo.nombre}" for tipo in CATALOGO)
    return (
        "Eres archivista de Afinia (Caribemar de la Costa S.A.S. E.S.P.), la empresa de "
        "energía, y nombras los documentos del expediente de un suscriptor para el Índice "
        "Electrónico. Recibes el texto de UN documento, ya separado de una caja de "
        "correspondencia; viene de un OCR y trae errores de lectura.\n\n"
        "Devuelve el nombre del documento:\n"
        "- Si el documento es uno de los tipos de la lista oficial, devuelve exactamente ese nombre.\n"
        "- Si no, un nombre corto, de dos a ocho palabras, que diga qué documento es: la clase "
        "de papel con su complemento, como «ACTA DE VERIFICACION DE PREDIO DESOCUPADO» o "
        "«FORMATO DE NUEVOS SUMINISTROS».\n"
        "- En mayúsculas y sin tildes. Nunca nombres de personas, números, fechas, NIC ni radicados.\n"
        "- Devuelve solo el nombre, en una línea, sin comillas ni explicación.\n\n"
        f"Lista oficial:\n{tipos}"
    )


#: Lo más largo que se le acepta a la IA como nombre.
PALABRAS_DEL_NOMBRE_DE_LA_IA = 10


def nombre_de_la_ia(respuesta: str | None) -> str | None:
    """El nombre que devolvió la IA, limpio y con el del catálogo si es uno de sus tipos.

    ``None`` si la respuesta no es un nombre: vacía, larga como una frase, con
    cifras -- un radicado, una fecha -- o con «no puedo».
    """
    plano = _plano((respuesta or "").splitlines()[0] if respuesta else "")
    plano = re.sub(r"[^A-Z ]+", " ", plano)
    palabras = plano.split()
    if not palabras or len(palabras) > PALABRAS_DEL_NOMBRE_DE_LA_IA or re.search(r"\d", respuesta or ""):
        return None
    nombre = " ".join(palabras)
    if nombre.startswith(("NO PUEDO", "NO ES POSIBLE", "LO SIENTO", "DOCUMENTO ILEGIBLE")):
        return None
    tipo = next((t for t in CATALOGO if t.nombre == nombre or nombre in t.frases), None)
    return tipo.nombre if tipo else nombre


def _del_catalogo_en(asunto: str, empieza: str) -> str | None:
    """El tipo del catálogo que el asunto nombra y que empieza por ``empieza``."""
    plano = re.sub(r"[^A-Z0-9 ]+", " ", _plano(asunto))
    plano = f" {re.sub(r'\s+', ' ', plano)} "
    for frase, tipo in FRASES:
        if tipo.nombre.startswith(empieza) and f" {frase} " in plano:
            return tipo.nombre
    return None


def nombre_oficial(titulo: str | None, asunto: str | None = None) -> str | None:
    """El nombre con que el archivo y su fila del índice nombran el documento.

    ``titulo`` es lo que el documento dice ser en su primera hoja; ``asunto``,
    el renglón de su «ASUNTO:» o «REF:», si lo trae. ``None`` si ninguno dice
    qué es: entonces se nombra por su encabezado o por su caja.
    """
    titulo = _plano(titulo or "")
    nombre = AL_CATALOGO.get(titulo, titulo)
    if nombre == "RECLAMO" and asunto and _POR_ESTIMADO.search(_plano(asunto)):
        return RECLAMO_POR_CONSUMO_ESTIMADO
    if nombre in _GENERICOS:
        if asunto:
            del_catalogo = _del_catalogo_en(asunto, nombre) if nombre != "DOCUMENTO" else None
            del_asunto = nombre_del_asunto(asunto)
            if del_catalogo:
                return del_catalogo
            # La solicitud se llama por lo que solicita; el documento sin
            # título, por lo que su asunto dice ser.
            if del_asunto and (nombre == "DOCUMENTO" or del_asunto.startswith(nombre)):
                return del_asunto
        return None if nombre == "DOCUMENTO" else nombre
    return nombre or None

