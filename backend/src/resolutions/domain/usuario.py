"""Quién está sentado delante, y cómo se escribe eso sin ambigüedad.

Dos datos y ninguno más: la cédula y el correo. Los eligió el archivo porque son
los dos que ya tiene de cada empleado y porque ninguno de los dos hay que
inventarlo ni recordarlo aparte.

Casi todo lo que hay aquí es normalización, y no es adorno. La misma persona
teclea su cédula hoy como `1.047.382.991` y mañana como `1047382991`, y su
correo con la mayúscula que el móvil le pone delante. Si esas tres formas son
tres usuarios distintos, dar de alta a alguien deja de significar nada: la
primera vez entra y la segunda no, sin que nadie pueda explicar por qué. De modo
que se guarda una sola forma de cada cosa y se compara contra ella.

Lo que no hay aquí es contraseña. Se dice en voz alta porque callarlo sería
peor: **esto identifica, no autentica.** Quien sepa la cédula y el correo de un
compañero entra como él. Lo que compra de todos modos es real -- cada trabajo
lleva quién lo corrió hasta el libro mayor, y un perfil impide el descuido de
descargar lo que no toca -- pero nada de lo que hay detrás puede tratarse como
si una cédula fuese un secreto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import DomainError
from .perfil import Perfil


class UsuarioInvalido(DomainError):
    """Lo que llegó no puede identificar a una persona."""


#: Lo más corto y lo más largo que se acepta como cédula. Colombia usa de seis a
#: diez dígitos; el margen de arriba deja sitio a los documentos de extranjería
#: sin dejar pasar un número de teléfono pegado por error.
MIN_CEDULA = 5
MAX_CEDULA = 15

#: Un correo, mirado con la desconfianza justa. No valida que exista -- eso sólo
#: lo dice mandarle algo -- sino que tenga la forma de uno, que es lo que
#: distingue un correo de un nombre tecleado en la casilla equivocada.
_CORREO = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

MAX_CORREO = 120
MAX_NOMBRE = 80


def normalizar_cedula(raw: str | None) -> str:
    """La cédula reducida a sus dígitos.

    Los puntos, los espacios y los guiones que la gente escribe son adorno de
    lectura, nunca parte del número: `1.047.382.991` y `1047382991` son la misma
    persona y tienen que ser la misma clave.
    """
    digitos = re.sub(r"\D", "", str(raw or ""))
    if not digitos:
        raise UsuarioInvalido("La cédula no puede estar vacía")
    if len(digitos) < MIN_CEDULA:
        raise UsuarioInvalido(
            f"La cédula tiene {len(digitos)} dígitos y hacen falta al menos {MIN_CEDULA}"
        )
    if len(digitos) > MAX_CEDULA:
        raise UsuarioInvalido(
            f"La cédula tiene {len(digitos)} dígitos y el máximo es {MAX_CEDULA}"
        )
    return digitos


def normalizar_correo(raw: str | None) -> str:
    """El correo en minúsculas y sin espacios alrededor.

    En minúsculas porque la parte del dominio no distingue mayúsculas y la parte
    del buzón, en la práctica, tampoco: ningún servidor de este edificio entrega
    `Jperez@` y `jperez@` en dos bandejas distintas, y tratarlos como dos
    usuarios sólo produce el alta que no deja entrar.
    """
    correo = str(raw or "").strip().lower()
    if not correo:
        raise UsuarioInvalido("El correo no puede estar vacío")
    if len(correo) > MAX_CORREO:
        raise UsuarioInvalido(f"El correo pasa de {MAX_CORREO} caracteres")
    if not _CORREO.match(correo):
        raise UsuarioInvalido(f"«{correo}» no tiene forma de correo electrónico")
    return correo


def normalizar_nombre(raw: str | None) -> str:
    """El nombre, recortado. Es una etiqueta y no se interpreta nunca."""
    return str(raw or "").strip()[:MAX_NOMBRE]


@dataclass(frozen=True, slots=True)
class Usuario:
    """Una persona dada de alta, con lo que se le deja hacer.

    Inmutable a propósito: cambiar un perfil produce un usuario nuevo que
    sustituye al anterior en el almacén, y así no hay ningún punto del programa
    en que un permiso cambie debajo de quien lo estaba comprobando.
    """

    cedula: str
    correo: str
    perfil: Perfil
    #: Cómo se llama, para que la pantalla y el libro mayor no tengan que
    #: enseñar un número. Puede faltar: una cédula ya identifica.
    nombre: str = ""

    @classmethod
    def crear(
        cls,
        cedula: str | None,
        correo: str | None,
        perfil: str | Perfil | None,
        nombre: str | None = None,
    ) -> Usuario:
        """Un usuario a partir de lo que se tecleó, o el motivo de que no.

        Valida todo antes de construir nada. Un alta a medias -- la cédula
        buena y el correo mal escrito -- no deja rastro en el almacén.
        """
        try:
            elegido = perfil if isinstance(perfil, Perfil) else Perfil.parse(perfil)
        except ValueError as error:
            raise UsuarioInvalido(str(error)) from error
        return cls(
            cedula=normalizar_cedula(cedula),
            correo=normalizar_correo(correo),
            perfil=elegido,
            nombre=normalizar_nombre(nombre),
        )

    @property
    def etiqueta(self) -> str:
        """Cómo se le nombra en el informe y en el libro mayor.

        El nombre cuando lo hay, y la cédula cuando no. Nunca vacío: una fila
        del libro mayor que no dice quién la produjo es la que obliga a
        preguntar por el pasillo dentro de tres años.
        """
        return self.nombre or self.cedula

    def identifica(self, cedula: str | None, correo: str | None) -> bool:
        """Si estos dos datos son los suyos, comparados ya normalizados.

        Las dos cosas tienen que coincidir. Con la cédula sola bastaría para
        entrar sabiendo un número que está impreso en cualquier planilla.
        """
        try:
            return self.cedula == normalizar_cedula(cedula) and self.correo == normalizar_correo(
                correo
            )
        except UsuarioInvalido:
            return False

    def as_dict(self) -> dict[str, str]:
        return {
            "cedula": self.cedula,
            "correo": self.correo,
            "nombre": self.nombre,
            "perfil": str(self.perfil),
            "perfil_label": self.perfil.label,
        }
