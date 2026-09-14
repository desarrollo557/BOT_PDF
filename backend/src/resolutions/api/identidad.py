"""Quién manda la petición, y qué se le deja hacer con ella.

La pantalla manda la cédula de quien entró en una cabecera, y el servicio la
busca entre las altas. Es exactamente igual de endeble que el nombre de
operador que ya viajaba en `X-Operator` —una cédula no es un secreto y quien
sepa la de un compañero puede escribirla— y por eso conviene ser preciso sobre
qué sostiene y qué no.

**Lo que sostiene:** que el técnico y el de calidad no se lleven el FUID por
descuido. Esa comprobación tiene que vivir aquí y no sólo en la pantalla,
porque una restricción que únicamente esconde un botón la esquiva cualquiera
que escriba la dirección a mano —y entonces no es ni siquiera una barrera de
uso, sólo la apariencia de una.

**Lo que no sostiene:** nada frente a alguien que quiera saltárselo. Para eso
haría falta una contraseña, y el archivo pidió expresamente entrar con dos
datos y ninguno más.

Una petición sin cédula es una petición de nadie, y a nadie no se le deja
descargar. Es la única lectura que hace que el permiso signifique algo: si la
ausencia de cabecera concediera el permiso, bastaría con no mandarla.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from ..domain.usuario import Usuario
from .contexto import Ctx

#: Por dónde viaja la cédula de quien está sentado delante. Sin acentos ni
#: espacios, así que no hace falta codificarla como el nombre del operador.
CABECERA = "X-Cedula"


def quien_manda(
    ctx: Ctx,
    x_cedula: Annotated[str | None, Header()] = None,
) -> Usuario | None:
    """El usuario dado de alta con esa cédula, o nadie.

    No levanta. Hay endpoints que funcionan igual sin saber quién los pide
    —subir un documento lo hacía desde antes de que existieran los perfiles— y
    obligar a identificarse en todos ellos convertiría un permiso de lectura en
    un muro para trabajo que nunca lo tuvo.
    """
    return ctx.usuarios.buscar(x_cedula)


#: El tipo que pone en su firma un endpoint que quiere saber quién le habla.
Quien = Annotated[Usuario | None, Depends(quien_manda)]


def exigir_identificado(quien: Usuario | None) -> Usuario:
    """Quien lo pide, o un 401 que dice qué hacer."""
    if quien is None:
        raise HTTPException(
            status_code=401,
            detail=(
                "Hay que entrar con cédula y correo para hacer esto. "
                "Si acaba de entrar, vuelva a hacerlo."
            ),
        )
    return quien


def exigir_administrador(quien: Usuario | None) -> Usuario:
    """Quien lo pide, si es administrador."""
    usuario = exigir_identificado(quien)
    if not usuario.perfil.administra_usuarios:
        raise HTTPException(
            status_code=403,
            detail="Sólo el administrador puede administrar usuarios",
        )
    return usuario


def exigir_descarga_de_planillas(quien: Usuario | None) -> Usuario:
    """Quien lo pide, si se le deja bajar el archivo de Excel del FUID.

    El mensaje dice las dos mitades a propósito: qué no puede hacer y qué sí.
    Un 403 que sólo niega manda al operador a preguntar por el pasillo si el
    sistema está roto; éste le dice que la planilla está ahí, en pantalla.
    """
    usuario = exigir_identificado(quien)
    if not usuario.perfil.descarga_planillas:
        raise HTTPException(
            status_code=403,
            detail=(
                f"El perfil {usuario.perfil.label} no descarga el FUID en Excel. "
                "Puede consultarlo en pantalla desde la pantalla de Archivo."
            ),
        )
    return usuario
