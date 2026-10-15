"""Reconocer a quien entra.

El caso de uso, sin saber dónde se guarda nada: detrás puede haber un archivo
JSONL o una base. Desde el 2026-10-13 se entra sólo como «siar», sin
contraseña ni alta previa, con perfil de administrador: lo pidió el archivo
(«con el usuario siar es más que suficiente»). Ya no hay altas ni bajas.

Por la API sigue valiendo la cédula con el correo de quien esté en el almacén,
y las dos cosas tienen que cuadrar. Y una regla de arranque, para que el
sistema no nazca cerrado con la llave dentro: **sobre un almacén vacío, la
primera persona que entra así queda como administradora**, y se dice en la
respuesta para que no sea un secreto.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.perfil import Perfil
from ..domain.usuario import (
    Usuario,
    UsuarioInvalido,
    normalizar_cedula,
    normalizar_correo,
)
from .ports import UserStore

#: El usuario de la casa. Entra escribiendo «siar», sin contraseña ni alta
#: previa, con perfil de administrador. No vive en el almacén: está aquí para
#: que el sistema nunca quede cerrado con la llave dentro.
USUARIO_SIAR = "siar"
SIAR = Usuario(cedula=USUARIO_SIAR, correo="", perfil=Perfil.ADMINISTRADOR, nombre="SIAR")


class NoIdentificado(Exception):
    """No hay nadie dado de alta con esa cédula y ese correo."""


@dataclass(frozen=True, slots=True)
class Entrada:
    """El resultado de entrar: quién resultó ser, y si acaba de nacer el archivo."""

    usuario: Usuario
    #: Verdadero sólo la primera vez que alguien entra a un almacén vacío. La
    #: pantalla lo dice con todas sus letras; un permiso que se concede en
    #: silencio es el que nadie revisa después.
    primer_administrador: bool = False

    def as_dict(self) -> dict[str, object]:
        return {**self.usuario.as_dict(), "primer_administrador": self.primer_administrador}


class Usuarios:
    """Las altas del archivo, sobre el almacén que se le dé."""

    def __init__(self, store: UserStore) -> None:
        self._store = store

    # -- consultas -------------------------------------------------------------

    def buscar(self, cedula: str | None) -> Usuario | None:
        """Quién es esta cédula, o nadie. No levanta: preguntar no es entrar."""
        if str(cedula or "").strip().lower() == USUARIO_SIAR:
            return SIAR
        try:
            clave = normalizar_cedula(cedula)
        except UsuarioInvalido:
            return None
        return next((u for u in self._store.all() if u.cedula == clave), None)

    @property
    def vacio(self) -> bool:
        return not self._store.all()

    # -- entrar ----------------------------------------------------------------

    def entrar_como(self, usuario: str | None) -> Entrada:
        """Entrar con el nombre de usuario, sin contraseña. Sólo existe «siar»."""
        if str(usuario or "").strip().lower() != USUARIO_SIAR:
            raise NoIdentificado(f"Usuario no reconocido. Entre como «{USUARIO_SIAR}».")
        return Entrada(usuario=SIAR)

    def entrar(self, cedula: str | None, correo: str | None) -> Entrada:
        """Reconocer a quien teclea su cédula y su correo.

        Las dos cosas tienen que cuadrar contra la misma alta. Con la cédula
        sola bastaría con leer una planilla, que es donde está impresa.

        Lo que llegó se comprueba antes de buscarlo, y no sólo sobre el almacén
        vacío. Una cédula con letras no está dada de alta -- no puede estarlo --
        pero contestar «no hay nadie dado de alta con esa cédula» manda al
        operador a pedir un alta que ya tiene, cuando lo que pasa es que se
        equivocó de casilla.
        """
        normalizar_cedula(cedula)
        normalizar_correo(correo)

        registrados = self._store.all()
        if not registrados:
            # El almacén vacío. Nace el archivo y nace su administrador, porque
            # la alternativa es un sistema en el que no puede entrar nadie y que
            # sólo se abre editando un archivo del disco.
            primero = Usuario.crear(cedula, correo, Perfil.ADMINISTRADOR)
            self._store.save(primero)
            return Entrada(usuario=primero, primer_administrador=True)

        for usuario in registrados:
            if usuario.identifica(cedula, correo):
                return Entrada(usuario=usuario)
        raise NoIdentificado(
            "No hay nadie dado de alta con esa cédula y ese correo. "
            "Pídale al administrador que lo registre."
        )
