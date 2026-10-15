"""Entrar.

`POST /api/sesion` es lo que hace la pantalla de entrada: «siar», sin
contraseña. Las altas y las bajas de usuarios salieron de la pantalla el
2026-10-13 y del servicio el 2026-10-15: el archivo pidió entrar sólo como
«siar» y nada las usaba.

La entrada no crea nada salvo la primera vez en la vida del almacén, y cuando lo
hace lo dice en la respuesta.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...application.usuarios import NoIdentificado
from ...domain.usuario import UsuarioInvalido
from ..contexto import Ctx

router = APIRouter()


class Credenciales(BaseModel):
    #: La entrada de la pantalla: «siar», sin contraseña.
    usuario: str | None = Field(default=None, description="Nombre de usuario; hoy sólo «siar»")
    cedula: str | None = Field(default=None, description="La cédula de quien entra; se compara sin puntos")
    correo: str | None = Field(default=None, description="Su correo; se compara en minúsculas")


@router.post("/api/sesion")
async def entrar(ctx: Ctx, credenciales: Credenciales) -> dict[str, object]:
    """Dejar entrar a quien lo pide.

    Desde la pantalla, con el usuario «siar» y nada más, que es lo que pidió el
    archivo. Por la API sigue valiendo la cédula con el correo de un alta, y ahí
    las dos cosas tienen que cuadrar: con la cédula sola bastaría con leer
    cualquier planilla, que es donde está impresa.
    """
    try:
        if credenciales.usuario is not None:
            entrada = ctx.usuarios.entrar_como(credenciales.usuario)
        else:
            entrada = ctx.usuarios.entrar(credenciales.cedula, credenciales.correo)
    except UsuarioInvalido as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except NoIdentificado as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    return entrada.as_dict()
