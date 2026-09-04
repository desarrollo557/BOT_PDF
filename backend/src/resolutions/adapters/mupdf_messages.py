"""Quitar a MuPDF la consola y devolverle la palabra por el registro del sistema.

MuPDF es una biblioteca en C y avisa como tal: escribe en la salida del proceso,
en inglés, una línea suelta sin decir de qué documento habla ni si lo que cuenta
es grave. En la consola del operador eso aparece así::

    MuPDF error: format error: object is not a stream
    MuPDF error: syntax error: invalid ICC colorspace

Ninguna de las dos detuvo nada -- MuPDF se recuperó y siguió -- pero son
indistinguibles de un fallo que sí pierde una página, y quien las ve no tiene
forma de saber cuál es cuál. El problema no es que avise: es que avisa sin
contexto y sin gravedad.

Lo que hace este adaptador es quedarse con esos mensajes antes de que salgan por
la consola y volverlos a emitir por el registro del sistema, con el nombre del
documento delante y en el nivel que les corresponde. Traducirlos es cosa de
:mod:`resolutions.application.diagnostico`; aquí sólo está la fontanería que
hace falta para hablar con PyMuPDF.

Hay además una razón de memoria. PyMuPDF acumula cada mensaje en una lista
global que nadie vacía nunca (``JM_mupdf_warnings_store``). Un worker que
procese una caja entera de escaneos con el perfil de color roto la va llenando
documento tras documento durante toda la vida del proceso. Vaciarla al terminar
cada documento, que es lo que hace :func:`drenar`, cierra esa fuga.
"""

from __future__ import annotations

import logging

import pymupdf

from ..application.diagnostico import Gravedad, Incidencia, agrupar, explicar, traducir

__all__ = ["Gravedad", "Incidencia", "drenar", "explicar", "instalar", "traducir"]

logger = logging.getLogger(__name__)

_instalado = False


def instalar() -> None:
    """Desviar los mensajes de MuPDF al registro, una vez por proceso.

    Son dos canales distintos y hay que cerrar los dos. Los errores y los avisos
    de la biblioteca los imprime PyMuPDF cuando los recibe de C; se apagan y
    quedan sólo guardados, que es de donde los recoge :func:`drenar`. Los
    mensajes propios de PyMuPDF -- "skipping bad link", por ejemplo -- no pasan
    por ese almacén sino por su función ``message``, que escribe en la salida
    estándar: a ésa se le pone delante un destino nuestro.

    Es idempotente y se llama al importar el módulo, así que basta con que un
    adaptador lo importe para que su proceso quede cubierto; volver a llamarla
    no encadena un desvío sobre otro.
    """
    global _instalado
    if _instalado:
        return
    # Guardado sí, impreso no: la traducción necesita el texto, la consola no
    # necesita el original en inglés.
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    pymupdf.set_messages(stream=_SalidaAlRegistro())
    _instalado = True


class _SalidaAlRegistro:
    """El destino de los mensajes que PyMuPDF escribe por su cuenta.

    Llegan línea a línea y ya traen su salto; se traducen y se registran en el
    acto. No pasan por el almacén de avisos, así que aquí no hay nada que
    agrupar: acumularlos para contarlos los retrasaría hasta el final del
    documento sin que nadie gane nada.
    """

    def write(self, texto: str) -> None:
        for linea in texto.splitlines():
            limpia = linea.strip()
            if limpia:
                registrar(traducir(limpia), None)

    def flush(self) -> None:
        return None


def drenar(documento: str | None = None) -> list[Incidencia]:
    """Recoger lo que MuPDF acumuló, registrarlo en español y vaciar el almacén.

    Se llama al terminar con un documento, no durante. Las páginas se leen en
    varios hilos sobre el mismo PDF y el almacén de MuPDF es uno solo para todo
    el proceso: intentar decir de qué página vino cada mensaje sería adjudicarlo
    al azar, y un aviso atribuido a la página equivocada engaña más que uno sin
    página.
    """
    try:
        crudo = pymupdf.TOOLS.mupdf_warnings()
    except Exception:  # noqa: BLE001 - saber esto nunca vale un documento
        logger.debug("no se pudo leer el almacén de avisos de MuPDF", exc_info=True)
        return []
    incidencias = agrupar(crudo)
    for incidencia in incidencias:
        registrar(incidencia, documento)
    return incidencias


def registrar(incidencia: Incidencia, documento: str | None) -> None:
    """Dejarlo escrito con el documento delante y en el nivel que le toca.

    Lo recuperado va como informativo y lo perdido como advertencia: es la
    diferencia entre "este archivo viene defectuoso" y "esto no llegó a la
    salida", y mezclarlas en un solo nivel es exactamente lo que hacía imposible
    leer la consola.
    """
    prefijo = f"{documento}: " if documento else ""
    nivel = logging.INFO if incidencia.gravedad is Gravedad.RECUPERADO else logging.WARNING
    logger.log(nivel, "%s%s", prefijo, incidencia)


instalar()
