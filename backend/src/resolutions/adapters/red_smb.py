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
from collections.abc import Callable, Iterator
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
#: Cuántas peticiones a la vez se le hacen a un mismo servidor. El servidor
#: SMB reparte «créditos» -- turnos para atender peticiones -- por conexión, y
#: con la carpeta entera leyéndose a la vez se acababan: «Request requires 1
#: credits but only 0 credits are available», y el PDF fallaba sin haber nada
#: malo en él (\\200.100.20.97, 2026-10-22). Se ajusta con BOTPDF_RED_A_LA_VEZ.
A_LA_VEZ_POR_SERVIDOR = max(1, int(os.environ.get("BOTPDF_RED_A_LA_VEZ") or 4))
#: Y si aun así el servidor se queda sin créditos, cuánto se espera antes de
#: cada reintento: los devuelve en cuanto termina lo que estaba atendiendo.
ESPERAS_SIN_CREDITOS = (0.5, 1.0, 2.0, 4.0, 8.0)


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
    # Ni «.» ni «..» en ningún trozo: la copia local de una carpeta de red se
    # arma con ellos, y «..» la sacaba de su carpeta y podía pisar archivos
    # del equipo con lo que contestara un servidor cualquiera (2026-10-27).
    if any(trozo in (".", "..") for trozo in (hallado.group(1), hallado.group(2), *resto.split("\\"))):
        return None
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


_turnos: dict[str, threading.BoundedSemaphore] = {}
_descargas: dict[str, threading.BoundedSemaphore] = {}


def _turno_del_servidor(servidor: str) -> threading.BoundedSemaphore:
    with _cerrojo:
        return _turnos.setdefault(servidor.lower(), threading.BoundedSemaphore(A_LA_VEZ_POR_SERVIDOR))


def _turno_de_descarga(servidor: str) -> threading.BoundedSemaphore:
    """Las descargas, una menos que los turnos del servidor.

    Una descarga tiene su turno mientras dura la copia entera. Con tantas
    descargas como turnos, el recorrido no podía listar ni una carpeta más hasta
    que terminara alguna, y en una unidad lenta eso eran minutos sin descubrir
    nada (2026-10-28). Así siempre queda uno para listar.
    """
    with _cerrojo:
        return _descargas.setdefault(
            servidor.lower(), threading.BoundedSemaphore(max(1, A_LA_VEZ_POR_SERVIDOR - 1))
        )


def _sin_creditos(error: BaseException) -> bool:
    """Si el servidor se quedó sin turnos para atender: «… credits are available»."""
    texto = str(error).lower()
    return "credits" in texto and "available" in texto


def _con_turno(p: Partes, hacer: Callable[[], object]) -> object:
    """Una petición al servidor dentro de su tope de peticiones a la vez.

    Si el servidor contesta que no le quedan créditos, se espera un poco y se
    vuelve a pedir: es que está terminando otras, no que algo esté mal.
    """
    import time

    turno = _turno_del_servidor(p.servidor)
    for espera in (*ESPERAS_SIN_CREDITOS, None):
        with turno:
            try:
                return hacer()
            except Exception as error:  # noqa: BLE001 - sólo se reintenta la falta de créditos
                if espera is None or not _sin_creditos(error):
                    raise
        logger.info("el servidor %s no tiene créditos libres: se reintenta en %.1f s", p.servidor, espera)
        time.sleep(espera)
    raise AssertionError("inalcanzable")  # pragma: no cover


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


#: Con Windows Hello se entra con un PIN, que no sirve en la red: se pide la
#: clave de la cuenta.
_CLAVE_INCORRECTA = "El usuario o la clave no son correctos (es la clave de Windows, no el PIN)"


def _traducir(error: Exception, p: Partes, *, con_usuario: bool) -> Exception:
    """El error del cliente SMB como lo entiende quien lo atiende."""
    from smbprotocol.exceptions import (
        AccessDenied,
        BadNetworkName,
        LogonFailure,
        SMBAuthenticationError,
    )

    estado = getattr(error, "ntstatus", None) or getattr(error, "status", None)
    if _como_invitado(error):
        # El servidor no reconoció la cuenta y la dejó entrar como invitado,
        # que no se acepta: sin firma, cualquiera en la red podría hacerse
        # pasar por el servidor (Windows 11 también lo bloquea).
        return CredencialesDeRed(
            p.raiz,
            "El servidor no reconoció ese usuario (lo trató como invitado). Escríbalo con su "
            "dominio, como entra a Windows: DOMINIO\\usuario",
        )
    if isinstance(error, (SMBAuthenticationError, LogonFailure)) or estado in _CLAVE_MALA:
        motivo = _CLAVE_INCORRECTA if con_usuario else "El servidor pide usuario y clave"
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
    from smbprotocol.exceptions import SMBException

    if _sin_creditos(error):
        # Ni con los reintentos: el servidor sigue ocupado. El PDF vuelve en la
        # vuelta de reintento del final de la carpeta.
        return RedNoDisponible(
            f"El servidor {p.servidor} está atendiendo demasiadas peticiones a la vez y no tomó "
            "ésta; se reintentará al final de la carpeta"
        )
    if isinstance(error, SMBException) and not isinstance(error, OSError):
        # Cualquier otra negativa del protocolo se dice tal cual, no como un
        # fallo del servicio sin explicación.
        return RedNoDisponible(f"El servidor {p.servidor} no aceptó la conexión: {error}")
    return error


def _como_invitado(error: Exception) -> bool:
    """Si el servidor degradó la sesión a invitado («authenticated as a guest»)."""
    texto = str(error).lower()
    return "guest" in texto and ("signing" in texto or "encryption" in texto or "negotiate" in texto)


#: El dominio del equipo, que el instalador pasa al contenedor (``USERDOMAIN``
#: de Windows). No es un secreto: es el «SIAR» de «SIAR\usuario».
VARIABLE_DE_DOMINIO = "BOTPDF_DOMINIO"


def con_dominio(usuario: str) -> str:
    """El usuario con el dominio del equipo delante, si se escribió sin él.

    «desarrollo» → «SIAR\\desarrollo». Uno que ya lo trae («SIAR\\desarrollo»,
    «desarrollo@siar.local») queda tal cual, y sin dominio conocido también.
    """
    usuario = usuario.strip()
    dominio = os.environ.get(VARIABLE_DE_DOMINIO, "").strip()
    if not usuario or not dominio or "\\" in usuario or "@" in usuario:
        return usuario
    return f"{dominio}\\{usuario}"


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
    escrito = (usuario or "").strip()
    usuario, clave = con_dominio(escrito), clave or ""
    llave = f"{p.servidor.lower()}/{p.recurso.lower()}"
    # De a una por servidor: al escribir la ruta la pantalla pide varias cosas
    # a la vez, y cada entrada con usuario reinicia las conexiones; dos a la
    # vez se cerraban la sesión una a la otra y el cuadro volvía (2026-10-28).
    with _entrada_al_servidor(p.servidor):
        with _cerrojo:
            # La misma cuenta ya entró mientras ésta esperaba: no se repite.
            if usuario and llave in _conectados and _cuentas.get(p.servidor.lower()) in (
                (usuario, clave),
                (escrito, clave),
            ):
                return p.raiz
        entrar = _conectar_en_windows if NATIVA else _conectar_por_smb
        try:
            entrar(p, usuario, clave)
        except CredencialesDeRed:
            if usuario == escrito:
                raise
            # Sin dominio puede ser una cuenta del propio servidor -- la del
            # equipo que comparte su unidad con el contenedor --, que con el
            # dominio delante no existe.
            entrar(p, escrito, clave)
            usuario = escrito
        with _cerrojo:
            if usuario:
                _cuentas[p.servidor.lower()] = (usuario, clave)
            _conectados[llave] = p.raiz
    return p.raiz


_entradas: dict[str, threading.RLock] = {}


def _entrada_al_servidor(servidor: str) -> threading.RLock:
    with _cerrojo:
        return _entradas.setdefault(servidor.lower(), threading.RLock())


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
            raise CredencialesDeRed(p.raiz, _CLAVE_INCORRECTA)
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
    with _cerrojo:  # Linux: ya se entró en esta sesión del servicio
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
        return _con_turno(p, lambda: hacer(p, _cuenta(p.servidor)))
    except Exception as error:  # noqa: BLE001 - se traduce
        from smbprotocol.exceptions import SMBAuthenticationError, SMBConnectionClosed

        if isinstance(error, (SMBAuthenticationError, SMBConnectionClosed)):
            # La sesión se cerró -- el servidor se reinició, la red parpadeó --:
            # se vuelve a entrar con lo que ya se dio y se repite una vez.
            with _cerrojo:
                _conectados.pop(f"{p.servidor.lower()}/{p.recurso.lower()}", None)
            asegurar(p.raiz)
            try:
                return _con_turno(p, lambda: hacer(p, _cuenta(p.servidor)))
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


def iterar(
    ruta: str,
    *,
    extension: str = ".pdf",
    saltar: frozenset[str] = frozenset(),
    al_fallar: Callable[[str, OSError], None] | None = None,
) -> Iterator[ArchivoDeRed]:
    """Los archivos de ``ruta`` y sus subcarpetas, con tamaño y fecha, a medida que se leen.

    Carpeta por carpeta y en orden -- primero los archivos de una carpeta, luego
    sus subcarpetas, por nombre --, sin juntar el árbol entero: con cientos de
    miles de PDF en la red, quien los procesa empieza por el primer lote
    mientras el resto todavía no se ha listado (lo pidió el operador el
    2026-10-20: «hagámoslo por conteo por lotes»).

    Un solo listado por carpeta: el tamaño y la fecha vienen en él, sin otra
    pregunta al servidor por cada archivo. Una subcarpeta que no se deja leer
    va a ``al_fallar`` y el recorrido sigue; la de arriba que no se deja leer,
    o una sesión que se cae, es un error.
    """
    import smbclient
    from smbprotocol.exceptions import SMBAuthenticationError, SMBConnectionClosed

    p = partes(ruta)
    if p is None:
        raise ValueError(f"No es una ruta de red: {ruta}")
    asegurar(p.raiz)
    # Windows no distingue mayúsculas: «_procesados» y «_PROCESADOS» son la misma.
    saltar = frozenset(nombre.lower() for nombre in saltar)

    def nivel(carpeta: str, *, primera: bool) -> list:
        cuenta = _cuenta(p.servidor)
        try:
            return _con_turno(  # type: ignore[return-value]
                p, lambda: sorted(smbclient.scandir(carpeta, **cuenta), key=lambda e: e.name.lower())
            )
        except Exception as error:  # noqa: BLE001 - se traduce o se avisa
            if not primera and al_fallar is not None and isinstance(error, OSError):
                al_fallar(partes(carpeta).del_servicio, error)  # type: ignore[union-attr]
                return []
            if isinstance(error, (SMBAuthenticationError, SMBConnectionClosed)):
                # La próxima vez se vuelve a entrar con lo que ya se dio.
                with _cerrojo:
                    _conectados.pop(f"{p.servidor.lower()}/{p.recurso.lower()}", None)
            raise _traducir(error, p, con_usuario=bool(cuenta)) from error

    # En orden de ruta, como el disco local: archivos y subcarpetas mezclados
    # por nombre, y cada subcarpeta se lista cuando le toca.
    pila = [(p.unc, iter(nivel(p.unc, primera=True)))]
    while pila:
        carpeta, entradas = pila[-1]
        entrada = next(entradas, None)
        if entrada is None:
            pila.pop()
            continue
        completa = f"{carpeta}\\{entrada.name}"
        if entrada.is_dir():
            if entrada.name.lower() not in saltar:
                pila.append((completa, iter(nivel(completa, primera=False))))
        elif entrada.name.lower().endswith(extension):
            datos = entrada.stat()
            yield ArchivoDeRed(
                partes(completa).del_servicio,  # type: ignore[union-attr]
                int(datos.st_size),
                int(datos.st_mtime_ns),
            )


def recorrer(
    ruta: str,
    *,
    extension: str = ".pdf",
    saltar: frozenset[str] = frozenset(),
    al_fallar: Callable[[str, OSError], None] | None = None,
) -> list[ArchivoDeRed]:
    """Todo ``iterar`` de una vez, para quien necesita la lista completa."""
    return list(iterar(ruta, extension=extension, saltar=saltar, al_fallar=al_fallar))


def huella(ruta: str) -> tuple[int, int]:
    """Tamaño y fecha de modificación, como ``constancia.huella_del_origen``."""
    import smbclient

    datos = _llamar(ruta, lambda p, cuenta: smbclient.stat(p.unc, **cuenta))
    return int(datos.st_size), int(datos.st_mtime_ns)


def firma(ruta: str) -> str:
    """SHA-256 del contenido de un archivo de red, leído por bloques."""
    import hashlib

    import smbclient

    def resumir(p: Partes, cuenta: dict) -> str:
        resumen = hashlib.sha256()
        with smbclient.open_file(p.unc, mode="rb", **cuenta) as archivo:
            while bloque := archivo.read(1024 * 1024):
                resumen.update(bloque)
        return resumen.hexdigest()

    return str(_llamar(ruta, resumir))


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

    p = partes(ruta)
    try:
        with _turno_de_descarga(p.servidor if p else ""):
            tamano = _llamar(ruta, copiar)
        if parcial.stat().st_size != tamano:
            raise RedNoDisponible(f"La copia de {ruta} quedó incompleta; la red se cortó")
        os.replace(parcial, destino)
    finally:
        parcial.unlink(missing_ok=True)
    return destino
