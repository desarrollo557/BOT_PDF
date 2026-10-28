"""Las carpetas de red: entrar con usuario y clave, ver a cuáles se entró y salir.

La pantalla llega aquí cuando una ruta «\\\\servidor\\recurso\\…» contestó 401
con el código ``credenciales_de_red``: pide usuario y clave, los manda a
``POST /api/red/conectar`` y repite lo que estaba haciendo. Las credenciales se
quedan en la memoria del servicio (ver ``adapters/red_smb.py``) y no se
escriben en ningún archivo ni en el registro.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from ...adapters import red_smb
from ..folders import clean_path
from ..rutas_del_equipo import al_servicio

router = APIRouter()


@router.post("/api/red/conectar")
async def conectar(payload: dict | None = None) -> dict[str, object]:
    """Entra al recurso de ``ruta`` con ``usuario`` (puede llevar «DOMINIO\\») y ``clave``."""
    datos = payload or {}
    # «Z:\» si esa unidad se lee por la red: el 401 se la nombra así al operador.
    ruta = al_servicio(clean_path(str(datos.get("ruta") or "")))
    if not red_smb.es_de_red(ruta):
        raise HTTPException(status_code=422, detail="Indique una ruta de red: \\\\servidor\\recurso\\…")
    usuario = str(datos.get("usuario") or "").strip()
    clave = str(datos.get("clave") or "")
    if not usuario:
        raise HTTPException(status_code=422, detail="Indique el usuario")
    # Si no sirven, `CredencialesDeRed` vuelve como 401 y la pantalla los pide
    # de nuevo con el motivo; si el servidor no contesta, 503.
    raiz = await asyncio.to_thread(red_smb.conectar, ruta, usuario, clave)
    return {"recurso": raiz, "conectado": True}


@router.get("/api/red")
async def abiertas() -> dict[str, object]:
    """Los recursos de red a los que ya se entró en esta sesión del servicio."""
    return {"recursos": red_smb.conectados()}


@router.post("/api/red/olvidar")
async def olvidar(payload: dict | None = None) -> dict[str, object]:
    """Borra de la memoria las credenciales de un servidor, o de todos."""
    ruta = al_servicio(clean_path(str((payload or {}).get("ruta") or "")))
    partes = red_smb.partes(ruta)
    await asyncio.to_thread(red_smb.olvidar, partes.servidor if partes else None)
    return {"recursos": red_smb.conectados()}
