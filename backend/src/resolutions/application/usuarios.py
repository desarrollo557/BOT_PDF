"""Dar de alta, dar de baja y reconocer a quien entra.

El caso de uso, sin saber dónde se guarda nada: detrás puede haber un archivo
JSONL o una base, y las reglas son las mismas. Son cuatro y todas existen porque
sin ellas el alta no significa nada:

1. **Nadie se da de alta solo.** Crear usuarios es del administrador, y el
   servicio lo comprueba además de esconderlo en la pantalla.
2. **La cédula es la clave.** Dar de alta dos veces la misma persona la
   actualiza, nunca la duplica: dos filas con la misma cédula y perfiles
   distintos convierten «qué puede hacer» en una pregunta sin respuesta.
3. **El correo tampoco se repite.** Es el segundo dato con que se entra, así que
   dos personas con el mismo correo y cédulas distintas hacen que la entrada
   dependa de cuál de las dos se mire primero.
4. **Siempre queda un administrador.** Darse de baja a sí mismo siendo el único
   deja el archivo sin nadie que pueda dar de alta a nadie, y la única salida
   sería editar un archivo del disco a mano.

Y una regla de arranque, para que el sistema no nazca cerrado con la llave
dentro: **sobre un almacén vacío, la primera persona que entra queda como
administradora.** Se dice en la respuesta para que no sea un secreto. Es lo
mismo que hace cualquier instalación que se configura la primera vez que se
abre, y ocurre una sola vez en la vida del almacén.
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


class NoAutorizado(Exception):
    """Quien lo pide no tiene el perfil que hace falta."""


class NoIdentificado(Exception):
    """No hay nadie dado de alta con esa cédula y ese correo."""


class UltimoAdministrador(Exception):
    """Lo que se pide dejaría al archivo sin nadie que pueda dar de alta.

    Aparte de `UsuarioInvalido` a propósito: lo que llegó está bien escrito, y
    lo que no se puede es el estado en que dejaría al archivo. Son dos
    respuestas distintas -- 422 y 409 -- y mientras compartieron clase, quitarle
    el perfil al último administrador y borrarlo contestaban cosas distintas
    según por qué endpoint se pidiera.
    """


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

    def listar(self) -> list[Usuario]:
        return self._store.all()

    def buscar(self, cedula: str | None) -> Usuario | None:
        """Quién es esta cédula, o nadie. No levanta: preguntar no es entrar."""
        try:
            clave = normalizar_cedula(cedula)
        except UsuarioInvalido:
            return None
        return next((u for u in self._store.all() if u.cedula == clave), None)

    @property
    def vacio(self) -> bool:
        return not self._store.all()

    # -- entrar ----------------------------------------------------------------

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

    # -- administrar -----------------------------------------------------------

    def crear(
        self,
        quien: Usuario,
        *,
        cedula: str | None,
        correo: str | None,
        perfil: str | None,
        nombre: str | None = None,
    ) -> Usuario:
        """Dar de alta a alguien. Sólo el administrador."""
        self._exigir_administrador(quien)
        nuevo = Usuario.crear(cedula, correo, perfil, nombre)
        self._exigir_correo_libre(nuevo)
        self._store.save(nuevo)
        return nuevo

    def actualizar(
        self,
        quien: Usuario,
        cedula: str | None,
        *,
        correo: str | None = None,
        perfil: str | None = None,
        nombre: str | None = None,
    ) -> Usuario:
        """Cambiar el correo, el perfil o el nombre de alguien ya dado de alta.

        La cédula no se cambia: es la clave, y cambiarla es dar de baja a una
        persona y de alta a otra, que es justo lo que conviene que se vea como
        dos actos y no como uno.
        """
        self._exigir_administrador(quien)
        actual = self.buscar(cedula)
        if actual is None:
            raise UsuarioInvalido("Esa cédula no está dada de alta")

        cambiado = Usuario.crear(
            actual.cedula,
            correo if correo is not None else actual.correo,
            perfil if perfil is not None else actual.perfil,
            nombre if nombre is not None else actual.nombre,
        )
        self._exigir_correo_libre(cambiado)
        if actual.perfil.administra_usuarios and not cambiado.perfil.administra_usuarios:
            self._exigir_que_quede_otro_administrador(actual)
        self._store.save(cambiado)
        return cambiado

    def eliminar(self, quien: Usuario, cedula: str | None) -> bool:
        """Dar de baja. Nunca al último administrador."""
        self._exigir_administrador(quien)
        objetivo = self.buscar(cedula)
        if objetivo is None:
            return False
        if objetivo.perfil.administra_usuarios:
            self._exigir_que_quede_otro_administrador(objetivo)
        return self._store.delete(objetivo.cedula)

    # -- las reglas, en un solo sitio -----------------------------------------

    @staticmethod
    def _exigir_administrador(quien: Usuario | None) -> None:
        if quien is None or not quien.perfil.administra_usuarios:
            raise NoAutorizado(
                "Sólo el administrador puede dar de alta y de baja a los usuarios"
            )

    def _exigir_correo_libre(self, candidato: Usuario) -> None:
        """Que ese correo no sea ya de otra cédula.

        De otra: guardar al mismo con el mismo correo es actualizarlo, y eso sí
        se permite -- es como se le cambia el perfil o el nombre.
        """
        try:
            correo = normalizar_correo(candidato.correo)
        except UsuarioInvalido:
            return
        for usuario in self._store.all():
            if usuario.correo == correo and usuario.cedula != candidato.cedula:
                raise UsuarioInvalido(
                    f"El correo «{correo}» ya es de la cédula {usuario.cedula}"
                )

    def _exigir_que_quede_otro_administrador(self, saliente: Usuario) -> None:
        otros = [
            usuario
            for usuario in self._store.all()
            if usuario.perfil.administra_usuarios and usuario.cedula != saliente.cedula
        ]
        if not otros:
            raise UltimoAdministrador(
                "No se puede quedar sin administrador: dé de alta a otro antes de "
                "quitarle el perfil a éste."
            )
