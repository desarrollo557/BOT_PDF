"""Qué contiene el informe de un trabajo terminado.

El informe es un diccionario y viaja como JSON hasta la pantalla, así que aquí
no se le pone una clase encima: lo que se declara es **cuáles son sus claves**,
en un solo sitio, para que quien lo construye no pueda inventarse una y quien lo
lee no tenga que adivinar cuáles existen.

Hace falta porque las cuatro rutas lo arman por separado y la pantalla lee
catorce claves en treinta y nueve sitios. Un `dict.get` con un nombre mal
escrito no falla: devuelve `None`, la pantalla enseña un hueco y nadie se entera
hasta que alguien mira un informe de producción. Pasó exactamente así con las
cuentas de procedencia, que buscaban `ocr_band` mientras el dominio emitía
`ocr_region`, y estuvieron en cero durante meses.
"""

from __future__ import annotations

#: Lo que toda ruta que produce archivos tiene que dejar en su informe. La
#: pantalla lo lee sin preguntar de qué tipo de documento venía, así que una
#: ruta que se deje una clave rompe una vista que no tiene nada que ver con
#: ella. Es lo que le pasó a la ruta de diplomas cuando su informe traía otras
#: claves: la pantalla se quedaba sin modal de cierre y con la barra caída.
CLAVES_OBLIGATORIAS = (
    #: El nombre que el operador le dio al PDF, no el generado con que se
    #: almacenó la subida.
    "document",
    "page_count",
    #: Una entrada por unidad documental producida, con su tipo y su fecha.
    "groups",
    #: Las páginas que quedaron sin dueño, si la ruta puede producirlas.
    "quarantine",
    #: Las lecturas de OCR que se corrigieron por contexto.
    "repairs",
    #: Lo que alguien tiene que mirar, con el motivo de cada página.
    "review_queue",
    #: Los archivos escritos, con la ruta que la descarga necesita.
    "outputs",
    #: Cómo salió de cara la lectura, medido y no supuesto.
    "stats",
)

#: Y lo que además dejan las rutas que inventarían. No es obligatorio porque un
#: trabajo puede terminar sin producir ni una fila -- un escaneo del que no se
#: pudo leer nada -- y decirlo es mejor que fingir un inventario vacío.
CLAVES_OPCIONALES = (
    #: El inventario del documento: una fila por archivo que existe de verdad.
    "inventory",
    #: Qué páginas no se pudieron copiar al PDF de salida, por número.
    "unwritable_pages",
    #: De qué suscriptor es la caja. Sólo la ruta de correspondencia lo lee.
    "nic",
    #: Qué se le pidió al sistema que hiciera con el documento.
    "task",
    #: Avisos para el operador sobre la ruta que se eligió.
    "notices",
)


def claves_que_faltan(report: dict) -> list[str]:
    """Las claves obligatorias que un informe no trae.

    Se usa en las pruebas de cada ruta, y esa es toda su intención: que añadir
    una clave al contrato obligue a repasar las cuatro, en vez de descubrir en
    producción que una de ellas no la pone.
    """
    return [clave for clave in CLAVES_OBLIGATORIAS if clave not in report]
