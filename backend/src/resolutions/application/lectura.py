"""Con qué se lee el papel, que es una decisión del operador y no del servicio.

Distinta de la de `oracle.py`, y conviene no confundirlas porque contestan
preguntas distintas. Allí se elige **quién juzga una costura dudosa**: un modelo
de razonamiento mirando huellas de páginas que ya se leyeron. Aquí se elige
**con qué se transcribe la imagen**, que es el paso anterior a todo lo demás. Un
expediente mal leído no se arregla con un buen juez de costuras: no hay nada
sobre lo que juzgar.

Por qué es opcional y no automático: el motor local es gratis y el remoto se
paga por página. En un expediente mecanografiado el remoto no aporta nada --
Tesseract lee lo impreso perfectamente -- y activarlo sería pagar por leer dos
veces lo mismo. En un libro de registro de 1982 aporta lo único que importa,
porque ahí todo lo que identifica al documento está escrito a mano: el folio, el
nombre del graduado, la cédula, el título y la fecha. Quién sabe cuál de los dos
casos tiene delante es el operador, y por eso la decisión es suya y viaja con el
trabajo, igual que la acción y el modelo de bordes.

La misma regla que sostiene la elección de modelo vale acá: **una elección no se
degrada en silencio**. Pedir el motor de pago sin su llave es un error que se
contesta antes de aceptar la subida, no una sustitución callada que alguien
descubre tres cajas más tarde, cuando ya archivó lo que salió.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class LecturaChoice(StrEnum):
    """Con qué motor se transcribe cada imagen de este trabajo."""

    #: Tesseract y nada más. Es el valor por omisión, porque es el que había y
    #: porque es el que no cuesta dinero: quien no pida otra cosa sigue
    #: trabajando exactamente como trabajaba.
    LOCAL = "local"

    #: Tesseract primero y, donde el local no saque nada legible, el OCR de
    #: documentos de Mistral. En ese orden y no al revés: lo impreso lo lee
    #: gratis el de casa, y lo que se paga es sólo lo que el de casa no supo
    #: leer, que en estos archivos es lo escrito a mano.
    MISTRAL = "mistral"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def key_setting(self) -> str | None:
        """Qué ajuste del worker tiene que traer llave. `None` para el local."""
        return _KEY_SETTINGS.get(self)

    @property
    def env_var(self) -> str | None:
        """Qué variable de entorno nombrar cuando la llave falta."""
        return _ENV_VARS.get(self)

    def is_available(self, settings: Mapping[str, object]) -> bool:
        if self is LecturaChoice.LOCAL:
            return True
        setting = self.key_setting
        return bool(setting and settings.get(setting))

    @classmethod
    def parse(cls, value: str | None) -> LecturaChoice:
        """Interpreta lo que llegó por la API. Lo desconocido no se adivina."""
        if value in (None, ""):
            return cls.LOCAL
        try:
            return cls(str(value).strip().lower())
        except ValueError as error:
            opciones = ", ".join(choice.value for choice in cls)
            raise ValueError(
                f"motor de lectura desconocido: {value!r}; se esperaba uno de {opciones}"
            ) from error


def available_readers(settings: Mapping[str, object]) -> dict[str, bool]:
    """De cada motor, si hay llave para pedirlo.

    Va en `/api/health` por el mismo motivo que la de los modelos: para que la
    pantalla apague lo que no se puede pedir y diga por qué, en vez de ofrecerlo
    y cosechar un 422 cuando el operador ya eligió el archivo.
    """
    return {choice.value: choice.is_available(settings) for choice in LecturaChoice}


_LABELS = {
    LecturaChoice.LOCAL: "Tesseract",
    LecturaChoice.MISTRAL: "Tesseract + Mistral OCR",
}

_KEY_SETTINGS = {LecturaChoice.MISTRAL: "mistral_api_key"}

_ENV_VARS = {LecturaChoice.MISTRAL: "MISTRAL_API_KEY"}
