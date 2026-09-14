"""Entrar, y administrar a quién se le deja entrar.

Dos cosas distintas bajo el mismo módulo porque son las dos caras del mismo
dato. `POST /api/sesion` es lo que hace la pantalla de entrada con la cédula y
el correo que alguien teclea; el resto es la pantalla que sólo ve el
administrador.

La entrada no crea nada salvo la primera vez en la vida del almacén, y cuando lo
hace lo dice en la respuesta. Un sistema recién instalado en el que no puede
entrar nadie sólo se abre editando un archivo del disco a mano, y eso es peor
que un primer administrador declarado en voz alta.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from ...application.usuarios import NoAutorizado, NoIdentificado, UltimoAdministrador
from ...domain.usuario import UsuarioInvalido
from ..contexto import Ctx
from ..identidad import Quien, exigir_administrador

router = APIRouter()

#: Un campo de texto que no puede ir en blanco. Recorta antes de medir, porque
#: dos espacios son dos caracteres y ninguna letra: sin esto, «  » pasaba por
#: un nombre de dos letras y el alta entraba con el campo vacío igualmente.
Lleno = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

#: Y uno que además tiene que decir algo. Dos letras es lo menos que distingue
#: un nombre de una tecla pulsada por salir del paso.
Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2)]


class Credenciales(BaseModel):
    cedula: str = Field(description="La cédula de quien entra; se compara sin puntos")
    correo: str = Field(description="Su correo; se compara en minúsculas")


class Alta(BaseModel):
    """Un alta, con los cuatro campos y ninguno en blanco.

    El nombre era opcional y dejó de serlo a petición del archivo: un alta sin
    nombre deja una fila que sólo se sabe leer por su cédula, y nadie vuelve
    sobre ella para completarla. La pantalla apaga el botón hasta que estén los
    cuatro, y esto lo exige también aquí, porque una regla que sólo vive en el
    formulario la esquiva cualquier petición escrita a mano.

    El administrador que funda el archivo es la excepción, y no pasa por aquí:
    entra por `/api/sesion` cuando no hay nadie a quien pedirle un alta.
    """

    cedula: Lleno
    correo: Lleno
    perfil: Lleno
    nombre: Nombre = Field(description="Cómo se llama; no puede ir en blanco")


class Cambio(BaseModel):
    """Lo que se puede cambiar de alguien ya dado de alta.

    La cédula no está: es la clave, y cambiarla es dar de baja a una persona y
    de alta a otra. Conviene que eso se vea como dos actos y no como uno.
    """

    #: Ausente significa «no lo toques». Presente significa un valor nuevo, y
    #: por eso ninguno admite la cadena vacía: mandar `""` sería borrar un dato
    #: escribiendo nada, que es lo que el formulario completo existe para
    #: impedir.
    correo: Lleno | None = None
    perfil: Lleno | None = None
    nombre: Nombre | None = None


@router.post("/api/sesion")
async def entrar(ctx: Ctx, credenciales: Credenciales) -> dict[str, object]:
    """Reconocer a quien teclea su cédula y su correo.

    Las dos cosas tienen que cuadrar contra la misma alta. Con la cédula sola
    bastaría con leer cualquier planilla, que es donde está impresa.
    """
    try:
        entrada = ctx.usuarios.entrar(credenciales.cedula, credenciales.correo)
    except UsuarioInvalido as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except NoIdentificado as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    return entrada.as_dict()


@router.get("/api/usuarios")
async def listar_usuarios(ctx: Ctx, quien: Quien) -> dict[str, object]:
    """Quién está dado de alta. Sólo el administrador."""
    exigir_administrador(quien)
    return {"usuarios": [usuario.as_dict() for usuario in ctx.usuarios.listar()]}


@router.post("/api/usuarios", status_code=201)
async def crear_usuario(ctx: Ctx, quien: Quien, alta: Alta) -> dict[str, object]:
    administrador = exigir_administrador(quien)
    try:
        creado = ctx.usuarios.crear(
            administrador,
            cedula=alta.cedula,
            correo=alta.correo,
            perfil=alta.perfil,
            nombre=alta.nombre,
        )
    except UsuarioInvalido as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except NoAutorizado as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    return creado.as_dict()


@router.patch("/api/usuarios/{cedula}")
async def cambiar_usuario(ctx: Ctx, quien: Quien, cedula: str, cambio: Cambio) -> dict[str, object]:
    administrador = exigir_administrador(quien)
    try:
        cambiado = ctx.usuarios.actualizar(
            administrador,
            cedula,
            correo=cambio.correo,
            perfil=cambio.perfil,
            nombre=cambio.nombre,
        )
    except UltimoAdministrador as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except UsuarioInvalido as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except NoAutorizado as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    return cambiado.as_dict()


@router.delete("/api/usuarios/{cedula}")
async def dar_de_baja(ctx: Ctx, quien: Quien, cedula: str) -> dict[str, object]:
    administrador = exigir_administrador(quien)
    try:
        habia = ctx.usuarios.eliminar(administrador, cedula)
    except UltimoAdministrador as error:
        # Un 409 y no un 422 porque lo que llegó está bien escrito: lo que no se
        # puede es el estado en que dejaría al archivo.
        raise HTTPException(status_code=409, detail=str(error)) from error
    except NoAutorizado as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    if not habia:
        raise HTTPException(status_code=404, detail="Esa cédula no está dada de alta")
    return {"cedula": cedula, "baja": True}
