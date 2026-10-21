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

from .catalogo import FRASES

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

