"""Carpetas de red -- «\\\\servidor\\recurso\\…» -- leídas con un cliente SMB propio.

Lo pidió el operador el 2026-10-20 con la carpeta del repositorio de Afinia,
«\\\\200.100.20.97\\afinia\\REPOSITORIO\\AFINIA\\BOLIVAR SUR\\COMERCIAL\\MAGANGUE»,
y con tres condiciones: que valga cualquier ruta de red y no sólo ésa, que no
haya credenciales escritas en ningún archivo, y que si el servidor pide usuario
y clave se le pidan a él.

Dentro de Docker el servicio corre en Linux y no ve las carpetas de red de
Windows. Montarlas desde el contenedor exige darle permisos de administrador del
sistema (SYS_ADMIN), y eso le quita el aislamiento. Así que se les habla con
SMB directamente, como hace el Explorador: sin permisos extra y sin montar nada.

En Windows, sin Docker, la red ya la abre el sistema con la sesión del usuario;
este módulo sólo entra cuando Windows dice que hacen falta credenciales, y
entonces conecta el recurso con las que da el operador (``WNetAddConnection2``).

Las credenciales viven en la memoria del servicio y en ningún otro sitio: al
reiniciarlo se vuelven a pedir. Sólo se lee de la red; el original no se
escribe, no se mueve y no se borra.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat as stat_mod
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: En Windows la red la abre el sistema; en Linux (Docker), este cliente.
NATIVA = sys.platform == "win32"

#: «\\servidor\recurso\resto» o «//servidor/recurso/resto».
_RUTA = re.compile(r"^(?:\\\\|//)([^\\/]+)[\\/]+([^\\/]+)(?:[\\/]+(.*))?$")
#: Cuánto se espera a que el servidor conteste antes de darlo por caído.
SEGUNDOS_PARA_CONECTAR = 15
#: De a cuánto se copia un PDF de la red.
BLOQUE = 1024 * 1024


class CredencialesDeRed(Exception):
    """El servidor pide usuario y clave, o los que se dieron no sirven.

    No es un ``OSError`` a propósito: los que recorren carpetas tragan los
    ``OSError`` como «no se pudo leer», y esto no es un fallo de lectura sino
    una pregunta para el operador.
    """

    def __init__(self, recurso: str, motivo: str) -> None:
        super().__init__(f"{motivo}: {recurso}")
        self.recurso = recurso
        self.motivo = motivo


class RedNoDisponible(OSError):
    """El servidor no contesta o el recurso compartido no existe."""


@dataclass(frozen=True, slots=True)
class Partes:
    servidor: str
    recurso: str
    resto: str

    @property
    def raiz(self) -> str:
        """«\\\\200.100.20.97\\afinia»."""
        return f"\\\\{self.servidor}\\{self.recurso}"

    @property
    def unc(self) -> str:
        """La ruta completa como la escribe Windows."""
        return self.raiz + (f"\\{self.resto}" if self.resto else "")

    @property
    def del_servicio(self) -> str:
        """La misma ruta con barras: «//200.100.20.97/afinia/REPOSITORIO»."""
        resto = self.resto.replace("\\", "/")
        return f"//{self.servidor}/{self.recurso}" + (f"/{resto}" if resto else "")


def partes(ruta: object) -> Partes | None:
    """Servidor, recurso y resto de una ruta de red, o ``None`` si no lo es."""
    hallado = _RUTA.match(str(ruta).strip())
    if hallado is None:
        return None
    resto = re.sub(r"[\\/]+", "\\\\", (hallado.group(3) or "")).strip("\\")
    return Partes(hallado.group(1), hallado.group(2), resto)


def es_de_red(ruta: object) -> bool:
    return partes(ruta) is not None


def por_smb(ruta: object) -> bool:
    """Si esta ruta se lee con este cliente y no con el sistema de archivos."""
    return not NATIVA and es_de_red(ruta)


# -- las credenciales, sólo en memoria ----------------------------------------------

_cuentas: dict[str, tuple[str, str]] = {}
_conectados: dict[str, str] = {}
_cerrojo = threading.Lock()


def _cuenta(servidor: str) -> dict[str, str]:
    usuario, clave = _cuentas.get(servidor.lower(), ("", ""))
    return {"username": usuario, "password": clave} if usuario else {}


def conectados() -> list[str]:
    """Los recursos a los que ya se entró en esta sesión del servicio."""
    with _cerrojo:
        return sorted(_conectados.values(), key=str.lower)


def olvidar(servidor: str | None = None) -> None:
    """Borra de la memoria las credenciales de un servidor, o de todos."""
    with _cerrojo:
        for clave in [s for s in _cuentas if servidor is None or s == servidor.lower()]:
            _cuentas.pop(clave, None)
        for clave in [r for r in _conectados if servidor is None or r.split("/")[0] == servidor.lower()]:
            _conectados.pop(clave, None)
    if not NATIVA:
        try:
            import smbclient

            smbclient.reset_connection_cache()
        except Exception:  # noqa: BLE001 - olvidar no falla
            logger.debug("no se pudo cerrar la conexión SMB", exc_info=True)


#: Los estados NT que importan, tal como los devuelve el servidor.
_ACCESO_DENEGADO = 0xC0000022
_CLAVE_MALA = {0xC000006D, 0xC000006A, 0xC0000064, 0xC000015B, 0xC0000072, 0xC0000071}
_RECURSO_INEXISTENTE = {0xC00000CC, 0xC00000BE}


def _traducir(error: Exception, p: Partes, *, con_usuario: bool) -> Exception:
    """El error del cliente SMB como lo entiende quien lo atiende."""
    from smbprotocol.exceptions import (
        AccessDenied,
        BadNetworkName,
        LogonFailure,
        SMBAuthenticationError,
    )

    estado = getattr(error, "ntstatus", None) or getattr(error, "status", None)
    if isinstance(error, (SMBAuthenticationError, LogonFailure)) or estado in _CLAVE_MALA:
        motivo = "El usuario o la clave no son correctos" if con_usuario else "El servidor pide usuario y clave"
        return CredencialesDeRed(p.raiz, motivo)
    if isinstance(error, AccessDenied) or estado == _ACCESO_DENEGADO:
        motivo = (
            "Ese usuario no tiene permiso para leer esta carpeta"
            if con_usuario
            else "El servidor pide usuario y clave"
        )
        return CredencialesDeRed(p.raiz, motivo)
    if isinstance(error, BadNetworkName) or estado in _RECURSO_INEXISTENTE:
        return RedNoDisponible(f"El recurso compartido no existe: {p.raiz}")
    if isinstance(error, (ValueError, ConnectionError, TimeoutError)):
        return RedNoDisponible(f"No se pudo conectar con el servidor {p.servidor}: {error}")
    return error


def no_existe(error: BaseException) -> bool:
    """Si el error dice que el archivo o la carpeta no existen."""
    import errno

    return isinstance(error, FileNotFoundError) or getattr(error, "errno", None) == errno.ENOENT


def conectar(ruta: str, usuario: str | None = None, clave: str | None = None) -> str:
    """Entra al recurso de ``ruta``, con usuario y clave si se dan. Devuelve su raíz.

    ``usuario`` puede llevar el dominio: «SIAR\\desarrollo». Si no sirven,
    ``CredencialesDeRed``; si el servidor no contesta, ``RedNoDisponible``.
    """
    p = partes(ruta)
    if p is None:
        raise ValueError(f"No es una ruta de red: {ruta}")
    usuario = (usuario or "").strip()
    if NATIVA:
        _conectar_en_windows(p, usuario, clave or "")
    else:
        _conectar_por_smb(p, usuario, clave or "")
    with _cerrojo:
        if usuario:
            _cuentas[p.servidor.lower()] = (usuario, clave or "")
        _conectados[f"{p.servidor.lower()}/{p.recurso.lower()}"] = p.raiz
    return p.raiz


def _conectar_por_smb(p: Partes, usuario: str, clave: str) -> None:
    import smbclient

    cuenta = {"username": usuario, "password": clave} if usuario else _cuenta(p.servidor)
    try:
        if usuario:
            # Otra cuenta para el mismo servidor: la conexión de antes se cierra,
            # o el cliente seguiría usando la vieja.
            smbclient.reset_connection_cache()
        smbclient.register_session(
            p.servidor, connection_timeout=SEGUNDOS_PARA_CONECTAR, auth_protocol="ntlm", **cuenta
        )
        smbclient.stat(p.raiz, **cuenta)
    except Exception as error:  # noqa: BLE001 - se traduce
        raise _traducir(error, p, con_usuario=bool(cuenta)) from error


#: Lo que Windows contesta cuando faltan o sobran credenciales.
_SIN_CREDENCIALES = {5, 86, 1244, 1326, 1327, 1331, 1907, 2202}
#: Y cuando el servidor o el recurso no existen.
_NO_EXISTE = {53, 67, 1203, 2250}


def _conectar_en_windows(p: Partes, usuario: str, clave: str) -> None:
    if usuario:
        import ctypes
        from ctypes import wintypes

        class NETRESOURCEW(ctypes.Structure):  # noqa: N801 - el nombre de Windows
            _fields_ = [
                ("dwScope", wintypes.DWORD),
                ("dwType", wintypes.DWORD),
                ("dwDisplayType", wintypes.DWORD),
                ("dwUsage", wintypes.DWORD),
                ("lpLocalName", wintypes.LPWSTR),
                ("lpRemoteName", wintypes.LPWSTR),
                ("lpComment", wintypes.LPWSTR),
                ("lpProvider", wintypes.LPWSTR),
            ]

        recurso = NETRESOURCEW()
        recurso.dwType = 1  # RESOURCETYPE_DISK
        recurso.lpRemoteName = p.raiz
        codigo = ctypes.windll.mpr.WNetAddConnection2W(ctypes.byref(recurso), clave, usuario, 0)
        if codigo in _SIN_CREDENCIALES:
            raise CredencialesDeRed(p.raiz, "El usuario o la clave no son correctos")
        if codigo == 1219:
            raise CredencialesDeRed(
                p.raiz,
                "Windows ya está conectado a ese servidor con otro usuario; "
                "cierre esa conexión o use el mismo usuario",
            )
        if codigo in _NO_EXISTE:
            raise RedNoDisponible(f"No se encontró el recurso de red: {p.raiz}")
        if codigo not in (0, 85):
            raise RedNoDisponible(f"Windows no pudo conectar {p.raiz} (error {codigo})")
    asegurar(p.raiz)


def asegurar(ruta: str) -> None:
    """Comprueba que se puede leer el recurso de ``ruta``; si no, dice por qué.

    La primera vez se intenta sin credenciales -- en Windows, con la sesión
    del usuario; en Linux, con las que ya se dieron --: si el servidor las
    pide, ``CredencialesDeRed``, que la pantalla convierte en una pregunta.
    """
    p = partes(ruta)
    if p is None:
        return
    if NATIVA:
        try:
            os.stat(p.raiz)
        except OSError as error:
            codigo = getattr(error, "winerror", None)
            if isinstance(error, PermissionError) or codigo in _SIN_CREDENCIALES:
                raise CredencialesDeRed(p.raiz, "El servidor pide usuario y clave") from error
            raise RedNoDisponible(f"No se encontró el recurso de red: {p.raiz}") from error
        with _cerrojo:
            _conectados[f"{p.servidor.lower()}/{p.recurso.lower()}"] = p.raiz
        return
    with _cerrojo:
        ya = f"{p.servidor.lower()}/{p.recurso.lower()}" in _conectados
    if not ya:
        conectar(p.raiz)


def _llamar(ruta: str, hacer: Callable[[Partes, dict], object]) -> object:
    """Una operación del cliente con la sesión del servidor; si caducó, se reconecta una vez."""
    p = partes(ruta)
    if p is None:
        raise ValueError(f"No es una ruta de red: {ruta}")
    asegurar(p.raiz)
    try:
        return hacer(p, _cuenta(p.servidor))
    except Exception as error:  # noqa: BLE001 - se traduce
        from smbprotocol.exceptions import SMBAuthenticationError, SMBConnectionClosed

        if isinstance(error, (SMBAuthenticationError, SMBConnectionClosed)):
            # La sesión se cerró -- el servidor se reinició, la red parpadeó --:
            # se vuelve a entrar con lo que ya se dio y se repite una vez.
            with _cerrojo:
                _conectados.pop(f"{p.servidor.lower()}/{p.recurso.lower()}", None)
            asegurar(p.raiz)
            try:
                return hacer(p, _cuenta(p.servidor))
            except Exception as otra:  # noqa: BLE001
                raise _traducir(otra, p, con_usuario=bool(_cuenta(p.servidor))) from otra
        raise _traducir(error, p, con_usuario=bool(_cuenta(p.servidor))) from error


# -- leer -----------------------------------------------------------------------------


def es_carpeta(ruta: str) -> bool:
    import smbclient

    try:
        datos = _llamar(ruta, lambda p, cuenta: smbclient.stat(p.unc, **cuenta))
    except OSError as error:
        if no_existe(error):
            return False
        raise
    return stat_mod.S_ISDIR(datos.st_mode)


def carpetas(ruta: str) -> list[str]:
    """Las subcarpetas de ``ruta``, por nombre."""
    import smbclient

    def listar(p: Partes, cuenta: dict) -> list[str]:
        return sorted(
            (e.name for e in smbclient.scandir(p.unc, **cuenta) if e.is_dir()), key=str.lower
        )

    return _llamar(ruta, listar)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class ArchivoDeRed:
    #: La ruta con barras, como la maneja el servicio: «//servidor/recurso/…/UPD1.pdf».
    ruta: str
    tamano: int
    modificado_ns: int


def recorrer(
    ruta: str,
    *,
    extension: str = ".pdf",
    saltar: frozenset[str] = frozenset(),
    al_fallar: Callable[[str, OSError], None] | None = None,
) -> list[ArchivoDeRed]:
    """Los archivos de ``ruta`` y sus subcarpetas, con tamaño y fecha.

    Un solo listado por carpeta: el tamaño y la fecha vienen en él, sin otra
    pregunta al servidor por cada archivo. Una subcarpeta que no se deja leer
    va a ``al_fallar`` y el recorrido sigue; la de arriba que no se deja leer
    es un error.
    """
    import smbclient

    # Windows no distingue mayúsculas: «_procesados» y «_PROCESADOS» son la misma.
    saltar = frozenset(nombre.lower() for nombre in saltar)

    def recorrer_desde(p: Partes, cuenta: dict) -> list[ArchivoDeRed]:
        encontrados: list[ArchivoDeRed] = []
        pendientes = [p.unc]
        primera = True
        while pendientes:
            carpeta = pendientes.pop()
            try:
                entradas = list(smbclient.scandir(carpeta, **cuenta))
            except OSError as error:
                if primera or al_fallar is None:
                    raise
                al_fallar(partes(carpeta).del_servicio, error)  # type: ignore[union-attr]
                continue
            primera = False
            for entrada in entradas:
                completa = f"{carpeta}\\{entrada.name}"
                if entrada.is_dir():
                    if entrada.name.lower() not in saltar:
                        pendientes.append(completa)
                elif entrada.name.lower().endswith(extension):
                    datos = entrada.stat()
                    encontrados.append(
                        ArchivoDeRed(
                            partes(completa).del_servicio,  # type: ignore[union-attr]
                            int(datos.st_size),
                            int(datos.st_mtime_ns),
                        )
                    )
        return encontrados

    archivos = _llamar(ruta, recorrer_desde)
    return sorted(archivos, key=lambda archivo: archivo.ruta.lower())  # type: ignore[arg-type]


def huella(ruta: str) -> tuple[int, int]:
    """Tamaño y fecha de modificación, como ``constancia.huella_del_origen``."""
    import smbclient

    datos = _llamar(ruta, lambda p, cuenta: smbclient.stat(p.unc, **cuenta))
    return int(datos.st_size), int(datos.st_mtime_ns)


def traer(ruta: str, destino: Path) -> Path:
    """Copia el archivo de la red a ``destino`` y devuelve la copia.

    Primero a «.part» y luego se renombra: una copia cortada a medias no queda
    con el nombre del PDF. Se comprueba el tamaño, porque una red que se corta
    puede dejar un archivo más corto sin error.
    """
    import smbclient

    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".part")

    def copiar(p: Partes, cuenta: dict) -> int:
        with smbclient.open_file(p.unc, mode="rb", **cuenta) as origen, parcial.open("wb") as copia:
            shutil.copyfileobj(origen, copia, BLOQUE)
        return int(smbclient.stat(p.unc, **cuenta).st_size)

    try:
        tamano = _llamar(ruta, copiar)
        if parcial.stat().st_size != tamano:
            raise RedNoDisponible(f"La copia de {ruta} quedó incompleta; la red se cortó")
        os.replace(parcial, destino)
    finally:
        parcial.unlink(missing_ok=True)
    return destino
