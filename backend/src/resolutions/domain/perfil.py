"""Qué puede hacer cada quien con lo que el separador produce.

Hasta ahora todos los que se sentaban delante podían hacer lo mismo, y la sesión
era sólo un nombre para que el inventario pudiera contestar «quién procesó
esto». Sigue siendo eso, pero el archivo necesitó además que dos de sus puestos
—el técnico y el de calidad— pudieran **mirar** el Formato Único de Inventario
Documental sin poder **llevárselo**: una planilla que sale de la máquina en un
archivo de Excel deja de estar bajo control del archivo en el momento en que se
copia a un correo, y las dos personas que la revisan no son las que la firman.

De modo que un perfil aquí no contesta «quién es» sino «qué se le deja hacer».
Son tres, y la lista es corta a propósito: cada permiso nuevo es una pregunta
más que hay que hacerse en cada endpoint, y un permiso que nadie comprueba es
peor que no tenerlo porque hace creer que algo está cerrado.

**Esto no es control de acceso y no debe confundirse con él.** Se entra con una
cédula y un correo, sin contraseña, así que quien conozca los de un compañero
entra como él. Lo que el perfil impide es el uso, no el ataque: que quien revisa
no descargue por descuido la planilla que no le toca firmar. La comprobación
vive igualmente en el servicio y no sólo en la pantalla, porque una restricción
que sólo esconde un botón la esquiva cualquiera que escriba la dirección a mano,
y entonces no es ni siquiera una barrera de uso.
"""

from __future__ import annotations

from enum import StrEnum


class Perfil(StrEnum):
    """Los tres puestos que el archivo distingue."""

    #: Hace todo, y además es el único que da de alta a los demás. No hay
    #: registro abierto: alguien tiene que responder por quién entra.
    ADMINISTRADOR = "administrador"

    #: Quien procesa las cajas. Ve el inventario y el FUID en pantalla, y no se
    #: lleva la planilla.
    TECNICO = "tecnico"

    #: Quien revisa lo que salió. Mismas puertas que el técnico: mira y no
    #: descarga. Es un perfil aparte aunque hoy pueda lo mismo, porque las dos
    #: cosas que separa son distintas y van a divergir antes que a juntarse --
    #: y fundirlos ahora obligaría a partirlos después, cuando ya haya usuarios
    #: dados de alta bajo el nombre equivocado.
    CALIDAD = "calidad"

    @property
    def label(self) -> str:
        """Lo que se lee en pantalla."""
        return _ETIQUETAS[self]

    @property
    def administra_usuarios(self) -> bool:
        """Si puede dar de alta, cambiar y dar de baja a los demás."""
        return self is Perfil.ADMINISTRADOR

    @property
    def descarga_planillas(self) -> bool:
        """Si puede bajarse el archivo de Excel del FUID.

        Es el permiso por el que existe este módulo. El técnico y el de calidad
        la ven en pantalla, columna por columna, y no la descargan.
        """
        return self is Perfil.ADMINISTRADOR

    @property
    def ve_planillas(self) -> bool:
        """Si puede mirar el FUID en pantalla.

        Los tres pueden. Revisar un inventario sin verlo no es revisarlo, y
        esconderlo no protege nada: los datos son los mismos que la pantalla de
        Archivo ya muestra documento a documento.
        """
        return True

    @classmethod
    def parse(cls, value: str | None) -> Perfil:
        """Interpreta lo que llegó de fuera. Lo desconocido no se adivina.

        En particular no cae a `ADMINISTRADOR` ni a ningún otro por omisión: un
        perfil mal escrito que se resuelve como el más poderoso es exactamente
        la forma en que una restricción deja de existir sin que nadie lo note.
        """
        try:
            return cls(str(value or "").strip().lower())
        except ValueError as error:
            opciones = ", ".join(perfil.value for perfil in cls)
            raise ValueError(
                f"perfil desconocido: {value!r}; se esperaba uno de {opciones}"
            ) from error


_ETIQUETAS = {
    Perfil.ADMINISTRADOR: "Administrador",
    Perfil.TECNICO: "Técnico",
    Perfil.CALIDAD: "Calidad",
}
