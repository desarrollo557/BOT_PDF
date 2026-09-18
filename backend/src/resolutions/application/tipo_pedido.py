"""Qué clase de documento declara el operador que está cargando.

Hasta acá el sistema lo averiguaba solo: leía una muestra de doce páginas y de
ahí salía a qué habilidad iba el trabajo. Eso funciona cuando el papel se
declara con claridad y falla justo donde más cuesta, porque **una muestra que
se equivoca condena el archivo entero**. Un libro de registro de diplomas que
acabe en la ruta de continuidad no se corta mal por poco: esa ruta no lee el
papel, así que no puede saber de quién es cada hoja, y devuelve el libro
partido por donde la estructura alcanzó.

De modo que el operador puede decirlo. Él tiene el libro delante y sabe lo que
es antes de subirlo; preguntárselo cuesta un clic y ahorra reconocer. Sigue
existiendo el automático, que es lo que había y lo que se usa cuando la caja es
heterogénea o no se sabe qué trae.

Lo que **no** hace esta elección es decidir cómo se corta. Elegir "Diplomas"
manda el trabajo a la habilidad que sabe leer libros de registro; dentro de
ella siguen mandando las reglas de siempre -- el folio de la esquina, la cédula
que confirma la unión -- y ninguna se salta porque el operador haya declarado el
tipo. Declarar qué es un documento no es declarar dónde termina.
"""

from __future__ import annotations

from enum import StrEnum

from ..domain.doctype import DocumentType


class TipoPedido(StrEnum):
    """Lo que el operador declara estar cargando."""

    #: Que lo averigüe el sistema leyendo una muestra. Es el valor por omisión,
    #: porque es lo que hacía antes de que esta elección existiera y porque es
    #: lo correcto para una caja de la que nadie sabe qué trae.
    AUTO = "auto"

    #: Un libro de registro de diplomas. Va derecho a la habilidad que lee cada
    #: cara -- nombre, cédula y folio -- sin gastar la muestra de reconocimiento.
    DIPLOMA = "diploma"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def document_type(self) -> DocumentType | None:
        """El tipo que esta elección declara, o ``None`` para el automático."""
        return _DOCUMENT_TYPES.get(self)

    @classmethod
    def parse(cls, value: str | None) -> TipoPedido:
        """Interpreta lo que llegó por la API. Lo desconocido no se adivina."""
        if value in (None, ""):
            return cls.AUTO
        try:
            return cls(str(value).strip().lower())
        except ValueError as error:
            opciones = ", ".join(choice.value for choice in cls)
            raise ValueError(
                f"tipo de documento desconocido: {value!r}; se esperaba uno de {opciones}"
            ) from error


def tipos_declarables() -> list[dict[str, str]]:
    """Los tipos que la pantalla puede ofrecer, con su etiqueta.

    Sale por `/api/health` en vez de estar escrito a mano en el front, para que
    añadir un tipo sea una sola línea en este archivo y no dos en dos idiomas.
    Hoy son dos; el catálogo crecerá a medida que cada habilidad tenga quien la
    llame por su nombre.
    """
    return [{"id": choice.value, "label": choice.label} for choice in TipoPedido]


_LABELS = {
    TipoPedido.AUTO: "Detectar automáticamente",
    TipoPedido.DIPLOMA: "Diplomas",
}

_DOCUMENT_TYPES = {TipoPedido.DIPLOMA: DocumentType.DIPLOMA}
