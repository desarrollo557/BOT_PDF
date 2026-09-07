"""Qué se le pide al sistema que haga con un documento.

Hasta ahora sólo había una respuesta posible -- partir el PDF en uno por
resolución -- y por eso no hacía falta nombrarla. Pero un libro de registro de
diplomas no se parte: se inventaría. Y hay documentos que se quieren partir sin
inventariar, y al revés.

De modo que la acción es ahora una decisión del operador, tomada al cargar el
archivo, y viaja con el trabajo desde la interfaz hasta el worker.
"""

from __future__ import annotations

from enum import StrEnum


class TaskKind(StrEnum):
    """Lo que hay que hacer con el documento."""

    #: Partir el PDF en un archivo por unidad documental, y dejar el inventario
    #: de lo producido junto a los archivos. Es lo que el sistema hacía siempre,
    #: y sigue siendo el valor por omisión para no cambiar el comportamiento de
    #: quien ya lo estaba usando.
    SPLIT = "split"

    #: Leer el documento y levantar su inventario, sin escribir ningún PDF. El
    #: original queda intacto: es el caso de los libros empastados, que no se
    #: parten porque no se pueden desencuadernar.
    INVENTORY = "inventory"

    #: Las dos cosas, sobre una sola lectura. No es hacer el trabajo dos veces:
    #: partir e inventariar necesitan exactamente lo mismo -- saber qué páginas
    #: forman cada unidad documental -- y una vez que eso está decidido, escribir
    #: los PDF y escribir el FUID son dos salidas de la misma decisión.
    BOTH = "both"

    #: Separar una caja revuelta en los documentos que la forman. No es partir:
    #: partir supone un número impreso que manda hasta que aparece otro, y una
    #: caja de correspondencia no lo tiene. El número de reclamación que llevan
    #: todas sus hojas identifica el expediente entero, así que aquí la decisión
    #: es de continuidad -- si la hoja siguiente sigue a la anterior o empieza
    #: otra cosa -- y no de identidad.
    #:
    #: No inventaría. El FUID pide asunto y tipo documental, y eso son preguntas
    #: sobre un documento que ya tiene bordes; hacerlas de una caja sin cortar es
    #: lo que hace que un clasificador conteste lo mismo para noventa páginas
    #: distintas.
    SEGMENT = "segment"

    @property
    def label(self) -> str:
        """Lo que se lee en pantalla y en el acta."""
        return _LABELS[self]

    @property
    def writes_documents(self) -> bool:
        return self in (TaskKind.SPLIT, TaskKind.BOTH, TaskKind.SEGMENT)

    @property
    def writes_inventory(self) -> bool:
        return self in (TaskKind.INVENTORY, TaskKind.BOTH)

    @classmethod
    def parse(cls, value: str | None) -> TaskKind:
        """Interpreta lo que llegó por la API. Lo desconocido no se adivina."""
        if value in (None, ""):
            return cls.SPLIT
        try:
            return cls(str(value).strip().lower())
        except ValueError as error:
            opciones = ", ".join(kind.value for kind in cls)
            raise ValueError(f"acción desconocida: {value!r}; se esperaba una de {opciones}") from error


_LABELS = {
    TaskKind.SPLIT: "Dividir en documentos",
    TaskKind.INVENTORY: "Solo inventariar",
    TaskKind.BOTH: "Dividir e inventariar",
    TaskKind.SEGMENT: "Separar por documento",
}
