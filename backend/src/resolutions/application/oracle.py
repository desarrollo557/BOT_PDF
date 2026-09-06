"""Quién juzga los bordes que la estructura no pudo decidir.

Hasta acá el proveedor era una consecuencia de qué llave había puesta: Claude si
estaba la suya, si no Gemini, si no Mistral. Eso sirve para que el sistema
arranque solo y no sirve para lo que hace falta ahora, que es comparar dos
modelos sobre la misma caja para saber en cuál confiar.

Así que la elección sube a ser una decisión del operador, tomada al cargar el
archivo, y viaja con el trabajo desde la interfaz hasta el worker -- el mismo
camino que ya recorre la acción en `task.py`.

La regla que sostiene todo lo demás: **una elección no se degrada en silencio**.
Si alguien pide Mistral y el sistema contesta con Gemini, el informe miente sobre
quién decidió los cortes, y un corte cuya autoría no se puede rastrear no sirve
para decidir si el criterio funciona. De modo que pedir un proveedor sin su llave
es un error que se contesta antes de aceptar la subida, y no una sustitución
silenciosa que alguien descubre tres cajas después.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class OracleChoice(StrEnum):
    """A quién se le pregunta por las costuras dudosas de una caja."""

    #: La cascada de siempre: Claude, después Gemini, después Mistral, y el
    #: oráculo nulo si no hay ninguna llave. Es el valor por omisión para no
    #: cambiarle el comportamiento a quien ya lo estaba usando, y la única
    #: opción que no puede quedar indisponible: sin llaves la caja se separa
    #: igual por todo lo que la estructura decide sola.
    AUTO = "auto"

    #: Claude, en su modelo chico. Lo que se le pide es un veredicto binario
    #: sobre una huella de página ya comprimida, no redactar.
    CLAUDE = "claude"

    #: Gemini. La capa gratuita aguanta una caja entera preguntada de una vez.
    GEMINI = "gemini"

    #: Mistral. Ni cachea el prompt ni tiene capa gratuita, pero contesta la
    #: misma pregunta, y tenerlo como tercera opinión es justamente el punto.
    MISTRAL = "mistral"

    @property
    def label(self) -> str:
        """Lo que se lee en pantalla y en el acta."""
        return _LABELS[self]

    @property
    def key_setting(self) -> str | None:
        """Qué ajuste del worker tiene que traer llave. `None` para la cascada."""
        return _KEY_SETTINGS.get(self)

    @property
    def env_var(self) -> str | None:
        """Qué variable de entorno nombrar cuando la llave falta.

        El mensaje de error tiene que decir qué poner y dónde. Un 422 que sólo
        dice "no configurado" manda al operador a leer el código fuente.
        """
        return _ENV_VARS.get(self)

    def is_available(self, settings: Mapping[str, object]) -> bool:
        """Si este proveedor se puede pedir con las llaves que hay puestas."""
        if self is OracleChoice.AUTO:
            return True
        setting = self.key_setting
        return bool(setting and settings.get(setting))

    @classmethod
    def parse(cls, value: str | None) -> OracleChoice:
        """Interpreta lo que llegó por la API. Lo desconocido no se adivina."""
        if value in (None, ""):
            return cls.AUTO
        try:
            return cls(str(value).strip().lower())
        except ValueError as error:
            opciones = ", ".join(choice.value for choice in cls)
            raise ValueError(
                f"modelo desconocido: {value!r}; se esperaba uno de {opciones}"
            ) from error


def available_oracles(settings: Mapping[str, object]) -> dict[str, bool]:
    """De cada opción, si hay llave para pedirla.

    Va en `/api/health` para que la pantalla pueda deshabilitar lo que no se
    puede pedir y decir por qué, en vez de ofrecerlo y cosechar un 422. Un
    proveedor que no aparezca acá es invisible para el front, así que se recorre
    el enum entero en lugar de listar los nombres a mano.
    """
    return {choice.value: choice.is_available(settings) for choice in OracleChoice}


_LABELS = {
    OracleChoice.AUTO: "Automático",
    OracleChoice.CLAUDE: "Claude Haiku",
    OracleChoice.GEMINI: "Gemini Flash",
    OracleChoice.MISTRAL: "Mistral Small",
}

_KEY_SETTINGS = {
    OracleChoice.CLAUDE: "anthropic_api_key",
    OracleChoice.GEMINI: "gemini_api_key",
    OracleChoice.MISTRAL: "mistral_api_key",
}

_ENV_VARS = {
    OracleChoice.CLAUDE: "ANTHROPIC_API_KEY",
    OracleChoice.GEMINI: "GEMINI_API_KEY",
    OracleChoice.MISTRAL: "MISTRAL_API_KEY",
}
