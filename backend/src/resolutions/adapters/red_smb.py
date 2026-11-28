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

import contextlib
import io
import logging
import os
import re
import stat as stat_mod
import sys
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from .copia_vigilada import CopiaSinAvance, Vigilancia, vigilado

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
#: Cómo se abre un archivo de la red para leerlo: compartiendo lectura, escritura
#: y borrado con los demás programas, como el Explorador. Sin esto se abría en
#: exclusiva y bastaba WorkDrive sincronizándolo, un visor o el propio bot
#: sugiriendo el tipo de la carpeta para «está abierto en otro programa»; y
#: mientras se copiaba, nadie más podía abrirlo (2026-10-29). El bot sólo lee,
#: y la copia se comprueba por tamaño al terminar.
COMPARTIDO = "rwd"
#: Cuánto se espera, como mucho, el listado de una carpeta pedido por delante
#: (``iterar_carpetas``): uno tarda 21 ms; cinco minutos es un servidor colgado.
SEGUNDOS_PARA_LISTAR = 300.0
#: El tiempo de recepción del cliente SMB (``smbprotocol`` 1.17, variable de
#: entorno experimental que lee al crear cada conexión). Con el servidor
#: callado ese tiempo, el cliente le manda un eco; si tampoco lo contesta en
#: otro tanto, cierra la conexión y suelta las peticiones que la esperaban.
#: Por omisión son 600 s: veinte minutos colgado antes de enterarse. Aquí 120,
#: cuatro minutos; el operador puede fijar otro en el entorno (2026-11-28).
SEGUNDOS_DE_RECEPCION = "120"
os.environ.setdefault("SMB_EXPERIMENTAL_TRANSPORT_RECEIVE_TIMEOUT", SEGUNDOS_DE_RECEPCION)


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


class RedSinAvance(RedNoDisponible, TimeoutError):
    """La red dejó de contestar a mitad de una copia o de un listado (2026-11-28).

    También un ``TimeoutError``: un fallo pasajero que se reintenta
    (``api/reintentos.es_transitorio``), y no un PDF dañado.
    """

    para_el_operador = True


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
_adelantos: dict[str, threading.BoundedSemaphore] = {}


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


def _turno_de_adelanto(servidor: str) -> threading.BoundedSemaphore:
    """Los listados de ``iterar_carpetas``, también uno menos que los turnos del servidor.

    La reserva de ``_turno_de_descarga`` al revés: el adelanto pide varias
    carpetas a la vez y, sin tope propio, podía tener los cuatro turnos y una
    descarga esperaba a que terminaran sus listados. Así siempre queda uno para
    bajar (2026-11-26). Cada uno toma su reserva antes que el turno, y nadie que
    tenga un turno espera una reserva: no hay espera en círculo.
    """
    with _cerrojo:
        return _adelantos.setdefault(
            servidor.lower(), threading.BoundedSemaphore(max(1, A_LA_VEZ_POR_SERVIDOR - 1))
        )


def _sin_creditos(error: BaseException) -> bool:
    """Si el servidor se quedó sin turnos para atender: «… credits are available».

    O sin recursos: «STATUS_INSUFFICIENT_RESOURCES» (0xC000009A), que da el
    Windows que comparte «Z:» -- WorkDrive -- cuando le piden varios PDF de
    200 MB a la vez y aún los está bajando de la nube (2026-10-29). También
    pasa en cuanto termina lo que estaba atendiendo.
    """
    texto = str(error).lower()
    if "credits" in texto and "available" in texto:
        return True
    return "insufficient_resources" in texto or "insufficient system resources" in texto


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
#: Con 0xC0000203 (STATUS_USER_SESSION_DELETED): Samba deja entrar como
#: invitado a una cuenta que no conoce y le borra la sesión; salía como un
#: fallo de red y no como la cuenta equivocada que es.
_CLAVE_MALA = {0xC000006D, 0xC000006A, 0xC0000064, 0xC000015B, 0xC0000072, 0xC0000071, 0xC0000203}
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


def archivos(ruta: str, extension: str) -> list[str]:
    """Los archivos de ``ruta`` con esa extensión, sin entrar en subcarpetas, como rutas del servicio."""
    import smbclient

    def listar(p: Partes, cuenta: dict) -> list[str]:
        return sorted(
            (
                f"{p.unc}\\{e.name}"
                for e in smbclient.scandir(p.unc, **cuenta)
                if e.is_file() and e.name.lower().endswith(extension)
            ),
            key=str.lower,
        )

    return [partes(unc).del_servicio for unc in _llamar(ruta, listar)]  # type: ignore[union-attr, attr-defined]


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
    p = partes(ruta)
    if p is None:
        raise ValueError(f"No es una ruta de red: {ruta}")
    asegurar(p.raiz)
    # Windows no distingue mayúsculas: «_procesados» y «_PROCESADOS» son la misma.
    saltar = frozenset(nombre.lower() for nombre in saltar)

    def subcarpeta(carpeta: str) -> list:
        try:
            return _listado(p, carpeta)
        except Exception as error:  # noqa: BLE001 - se avisa o se traduce
            _avisar_o_lanzar(error, p, carpeta, al_fallar)
            return []

    try:
        entradas = _listado(p, p.unc)
    except Exception as error:  # noqa: BLE001 - se traduce
        raise _error_al_listar(error, p) from error
    yield from _en_profundidad(p.unc, entradas, subcarpeta, extension=extension, saltar=saltar)


def listar_nivel(
    ruta: str,
    *,
    extension: str = ".pdf",
    saltar: frozenset[str] = frozenset(),
) -> tuple[list[ArchivoDeRed], list[str]]:
    """Un solo listado de ``ruta``: sus archivos con esa extensión y sus subcarpetas, sin entrar en ellas.

    Para empezar una corrida sin recorrer antes el árbol entero (2026-11-26):
    la raíz del origen de Magangué -- unas 32.000 carpetas -- se lista de una
    vez en 7,8 s, y con ella y la raíz del destino se sabe qué carpetas faltan
    por entregar (``application/orden_del_recorrido.py``).

    Los archivos, con tamaño y fecha del mismo listado; las subcarpetas, como
    rutas del servicio («//servidor/recurso/…»), sin las de ``saltar`` (sin
    distinguir mayúsculas). Las dos listas, por nombre sin mayúsculas: el orden
    de ``iterar``. Si ``ruta`` no se deja leer es un error, como la carpeta de
    arriba de ``iterar``: traducido, y una sesión caída se olvida.
    """
    p = partes(ruta)
    if p is None:
        raise ValueError(f"No es una ruta de red: {ruta}")
    asegurar(p.raiz)
    saltar = frozenset(nombre.lower() for nombre in saltar)
    try:
        entradas = _listado(p, p.unc)
    except Exception as error:  # noqa: BLE001 - se traduce
        raise _error_al_listar(error, p) from error
    archivos: list[ArchivoDeRed] = []
    carpetas: list[str] = []
    for entrada in entradas:
        completa = f"{p.unc}\\{entrada.name}"
        if entrada.is_dir():
            if entrada.name.lower() not in saltar:
                # Pegada, no pasada por ``partes``: ésa recorta la ruta entera y
                # una carpeta «1000265 » perdía su espacio final (2026-11-26).
                carpetas.append(f"{p.del_servicio}/{entrada.name}")
        elif entrada.name.lower().endswith(extension):
            archivos.append(_archivo(completa, entrada))
    return archivos, carpetas


def _unc_tal_cual(ruta: str, p: Partes) -> str:
    """La UNC de ``ruta`` con el nombre de su última carpeta tal cual.

    ``partes`` recorta los espacios de las puntas de la ruta entera: una carpeta
    cuyo nombre acaba en espacio («1000265 », que NTFS admite si la creó un
    cliente SMB) perdía el suyo, y se listaba otra que no existe (2026-11-26).
    """
    crudo = str(ruta)
    final = crudo[len(crudo.rstrip()):]
    return p.unc + final if final and p.resto else p.unc


def iterar_carpetas(
    carpetas: Iterable[str],
    *,
    extension: str = ".pdf",
    saltar: frozenset[str] = frozenset(),
    al_fallar: Callable[[str, OSError], None] | None = None,
    adelantadas: int | None = None,
) -> Iterator[ArchivoDeRed]:
    """Los archivos de cada una de ``carpetas`` y de sus subcarpetas, carpeta por carpeta en el orden dado.

    De cada carpeta salen en el orden exacto de ``iterar(carpeta)``, pero el
    listado de las siguientes se pide por delante, varias a la vez: una
    carpeta de Magangué tarda 21 ms en listarse (32 ms en el p90), y las
    ~32.000 una tras otra eran unos 10 min antes de llegar a lo pendiente
    (2026-11-26). Lo de dentro de cada una, en profundidad y cuando le toca.

    ``adelantadas``: cuántas carpetas se piden por delante, y sólo ésas quedan
    en memoria. Por omisión y como mucho, ``A_LA_VEZ_POR_SERVIDOR``. A la vez
    se listan como mucho los turnos del servidor menos uno
    (``_turno_de_adelanto``): siempre queda uno para las descargas.

    Una carpeta -- de éstas o de sus subcarpetas -- que no se deja leer va a
    ``al_fallar`` y se sigue; sin ``al_fallar``, se lanza traducida. Una sesión
    que se cae se lanza traducida, como en ``iterar``. Si quien lee cierra el
    generador a medias, lo pedido por delante se cancela sin esperarlo.
    """
    tope = A_LA_VEZ_POR_SERVIDOR if adelantadas is None else adelantadas
    tope = max(1, min(tope, A_LA_VEZ_POR_SERVIDOR))
    saltar = frozenset(nombre.lower() for nombre in saltar)
    por_pedir = iter(carpetas)
    # Lo pedido por delante, en el orden dado: (partes, carpeta UNC, su listado).
    ventana: deque[tuple[Partes, str, Future]] = deque()
    asegurados: set[str] = set()
    cerrado = threading.Event()
    hilos = ThreadPoolExecutor(max_workers=tope, thread_name_prefix="red-adelanto")

    def listar(p: Partes, carpeta: str) -> list:
        with _turno_de_adelanto(p.servidor):
            if cerrado.is_set():
                return []  # se cerró mientras esperaba su turno: nadie lo va a leer
            return _listado(p, carpeta)

    def subcarpeta(p: Partes, carpeta: str) -> list:
        try:
            return listar(p, carpeta)
        except Exception as error:  # noqa: BLE001 - se avisa o se traduce
            _avisar_o_lanzar(error, p, carpeta, al_fallar)
            return []

    def pedir_la_siguiente() -> bool:
        carpeta = next(por_pedir, None)
        if carpeta is None:
            return False
        p = partes(carpeta)
        if p is None:
            raise ValueError(f"No es una ruta de red: {carpeta}")
        if p.raiz.lower() not in asegurados:
            asegurar(p.raiz)
            asegurados.add(p.raiz.lower())
        unc = _unc_tal_cual(carpeta, p)
        ventana.append((p, unc, hilos.submit(listar, p, unc)))
        return True

    try:
        for _ in range(tope):
            if not pedir_la_siguiente():
                break
        while ventana:
            p, carpeta, listado = ventana.popleft()
            # La que sale deja sitio a la siguiente: siempre «tope» por delante.
            pedir_la_siguiente()
            # Con tope (2026-11-28): un servidor colgado dejaba el recorrido
            # esperando este listado para siempre. Pasado, sube como fallo de
            # la red -- el recorrido entero se reintenta -- y no como una
            # carpeta que no se deja leer: ésa se saltaría.
            if not wait([listado], timeout=SEGUNDOS_PARA_LISTAR).done:
                raise RedSinAvance(
                    f"El servidor {p.servidor} no contestó en {SEGUNDOS_PARA_LISTAR:.0f} s al listar {carpeta}"
                )
            try:
                entradas = listado.result()
            except Exception as error:  # noqa: BLE001 - se avisa o se traduce
                _avisar_o_lanzar(error, p, carpeta, al_fallar)
                continue
            yield from _en_profundidad(
                carpeta, entradas, partial(subcarpeta, p), extension=extension, saltar=saltar
            )
    finally:
        # Lo pedido que no empezó se cancela; lo que se está listando termina
        # solo y su hilo se va. No se espera aquí: nadie va a leerlo.
        cerrado.set()
        hilos.shutdown(wait=False, cancel_futures=True)


def _listado(p: Partes, carpeta: str) -> list:
    """Las entradas de ``carpeta`` (UNC) en un listado, por nombre sin mayúsculas, dentro de su turno.

    ``smbclient.scandir`` es perezoso: se consume entero dentro del turno, o
    seguiría pidiéndole al servidor fuera de él.
    """
    import smbclient

    cuenta = _cuenta(p.servidor)
    return _con_turno(  # type: ignore[return-value]
        p, lambda: sorted(smbclient.scandir(carpeta, **cuenta), key=lambda e: e.name.lower())
    )


def _error_al_listar(error: Exception, p: Partes) -> Exception:
    """El error de un listado, traducido; una sesión caída, además, se olvida."""
    from smbprotocol.exceptions import SMBAuthenticationError, SMBConnectionClosed

    if isinstance(error, (SMBAuthenticationError, SMBConnectionClosed)):
        # La próxima vez se vuelve a entrar con lo que ya se dio.
        with _cerrojo:
            _conectados.pop(f"{p.servidor.lower()}/{p.recurso.lower()}", None)
    return _traducir(error, p, con_usuario=bool(_cuenta(p.servidor)))


def _avisar_o_lanzar(
    error: Exception, p: Partes, carpeta: str, al_fallar: Callable[[str, OSError], None] | None
) -> None:
    """Una carpeta que no se deja leer va a ``al_fallar`` y se sigue; lo demás se lanza traducido."""
    if al_fallar is not None and isinstance(error, OSError):
        al_fallar(partes(carpeta).del_servicio, error)  # type: ignore[union-attr]
        return
    raise _error_al_listar(error, p) from error


def _archivo(completa: str, entrada) -> ArchivoDeRed:
    """Un archivo del listado, con el tamaño y la fecha que trae: sin otra pregunta al servidor."""
    datos = entrada.stat()
    return ArchivoDeRed(
        partes(completa).del_servicio,  # type: ignore[union-attr]
        int(datos.st_size),
        int(datos.st_mtime_ns),
    )


def _en_profundidad(
    carpeta: str,
    entradas: list,
    listar: Callable[[str], list],
    *,
    extension: str,
    saltar: frozenset[str],
) -> Iterator[ArchivoDeRed]:
    """Los archivos de ``carpeta`` -- ya listada en ``entradas`` -- y los de sus subcarpetas.

    En orden de ruta, como el disco local: archivos y subcarpetas mezclados
    por nombre, y cada subcarpeta se lista (``listar``) cuando le toca.
    """
    pila = [(carpeta, iter(entradas))]
    while pila:
        actual, resto = pila[-1]
        entrada = next(resto, None)
        if entrada is None:
            pila.pop()
            continue
        completa = f"{actual}\\{entrada.name}"
        if entrada.is_dir():
            if entrada.name.lower() not in saltar:
                pila.append((completa, iter(listar(completa))))
        elif entrada.name.lower().endswith(extension):
            yield _archivo(completa, entrada)


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
        with smbclient.open_file(p.unc, mode="rb", share_access=COMPARTIDO, **cuenta) as archivo:
            while bloque := archivo.read(1024 * 1024):
                resumen.update(bloque)
        return resumen.hexdigest()

    return str(_llamar(ruta, resumir))


def leer_muestra(ruta: str, tope: int) -> tuple[int, float]:
    """Lee hasta ``tope`` bytes del archivo de red: cuántos y en cuántos segundos.

    Es la prueba de velocidad de la corrida (``adapters/acceso.py``). El reloj
    corre con el archivo ya abierto y su turno ya dado: lo que se mide es lo
    que tarda la red en traer los datos, no la espera detrás de otra descarga.
    """
    import time

    import smbclient

    def leer(p: Partes, cuenta: dict) -> tuple[int, float]:
        with smbclient.open_file(p.unc, mode="rb", share_access=COMPARTIDO, **cuenta) as archivo:
            inicio = time.monotonic()
            leidos = 0
            while leidos < tope and (bloque := archivo.read(min(BLOQUE, tope - leidos))):
                leidos += len(bloque)
            return leidos, time.monotonic() - inicio

    return _llamar(ruta, leer)  # type: ignore[return-value]


def traer(
    ruta: str,
    destino: Path,
    al_copiar: Callable[[int, float, float], None] | None = None,
    *,
    al_avanzar: Callable[[int, int], None] | None = None,
) -> Path:
    """Copia el archivo de la red a ``destino`` y devuelve la copia.

    Primero a «.part» y luego se renombra: una copia cortada a medias no queda
    con el nombre del PDF. Se comprueba el tamaño, porque una red que se corta
    puede dejar un archivo más corto sin error.

    ``al_copiar`` recibe los bytes y de cuándo a cuándo (reloj monótono) se
    copiaron, con el archivo ya abierto: la velocidad de la red, sin la espera
    del turno de descarga (``domain/ritmo.py``).

    ``al_avanzar`` recibe, mientras copia, lo copiado y el tamaño del archivo
    (0 si no se supo): la primera vez con 0 en cuanto el archivo se abre -- ya
    tiene su turno --, y después en cada bloque. Si la copia se repite -- la
    red se cortó --, vuelve a empezar de 0. Para que la pantalla diga cuánto
    lleva bajado (el operador, 2026-11-09).

    Vigilada (2026-11-28, ``copia_vigilada``): si pasan dos minutos sin mover
    un byte, ``RedSinAvance`` -- pasajero, se reintenta -- en vez de esperar
    para siempre a un servidor que no contesta.
    """
    import smbclient

    def bajar(vigilancia: Vigilancia) -> int:
        def copiar(p: Partes, cuenta: dict) -> int:
            vigilancia.latir()
            with smbclient.open_file(p.unc, mode="rb", share_access=COMPARTIDO, **cuenta) as origen:
                _volcar(origen, destino, vigilancia, al_copiar, al_avanzar)
            vigilancia.latir()
            return int(smbclient.stat(p.unc, **cuenta).st_size)

        p = partes(ruta)
        return _con_su_turno(p.servidor if p else "", vigilancia, lambda: _llamar(ruta, copiar))

    return _traer_vigilado(ruta, destino, bajar)


def traer_del_sistema(
    ruta: str | Path,
    destino: Path,
    al_copiar: Callable[[int, float, float], None] | None = None,
    *,
    al_avanzar: Callable[[int, int], None] | None = None,
) -> Path:
    """Como ``traer``, pero el archivo lo abre el sistema: una carpeta de red en Windows (2026-11-28).

    En Windows, sin Docker, «\\\\servidor\\recurso\\…» o una unidad de red («Z:»)
    las abre el sistema, y el worker leía el PDF directamente de la red: una
    red que se quedaba callada lo congelaba dentro del lector nativo, donde ni
    la orden de parar llega. Copiado antes a local, con la copia vigilada, la
    red sólo se espera aquí, donde un corte es un fallo pasajero que se reintenta.
    """
    ruta = str(ruta)

    def bajar(vigilancia: Vigilancia) -> int:
        def copiar() -> int:
            vigilancia.latir()
            with open(ruta, "rb") as origen:
                _volcar(origen, destino, vigilancia, al_copiar, al_avanzar)
            vigilancia.latir()
            return os.stat(ruta).st_size

        return _con_su_turno(_servidor_de(ruta), vigilancia, copiar)

    return _traer_vigilado(ruta, destino, bajar)


def _servidor_de(ruta: str) -> str:
    """El servidor de una ruta de red («200.100.20.97») o su unidad («z:»): con quién se comparte el turno."""
    p = partes(ruta)
    if p is not None:
        return p.servidor
    unidad = re.match(r"^([A-Za-z]:)", ruta)
    return unidad.group(1).lower() if unidad else ""


def _con_su_turno(servidor: str, vigilancia: Vigilancia, hacer: Callable[[], int]) -> int:
    """``hacer`` con el turno de descarga del servidor; esperarlo no cuenta como estar colgado."""
    turno = _turno_de_descarga(servidor)
    with vigilancia.esperando():
        turno.acquire()
    try:
        return hacer()
    finally:
        turno.release()


def _parcial_de(destino: Path) -> Path:
    return destino.with_name(destino.name + ".part")


def _volcar(
    origen,
    destino: Path,
    vigilancia: Vigilancia,
    al_copiar: Callable[[int, float, float], None] | None,
    al_avanzar: Callable[[int, int], None] | None,
) -> None:
    """Copia ``origen`` (ya abierto) en el «.part» de ``destino``, latiendo con cada bloque."""
    import time

    def avisar(copiados: int, total: int) -> None:
        if al_avanzar is None:
            return
        try:
            al_avanzar(copiados, total)
        except Exception:  # noqa: BLE001 - avisar nunca tumba una descarga
            logger.debug("no se pudo avisar del avance de %s", destino, exc_info=True)

    parcial = _parcial_de(destino)
    with parcial.open("wb") as copia:
        total = _tamano_abierto(origen)
        inicio = time.monotonic()
        copiados = 0
        avisar(copiados, total)
        while bloque := origen.read(BLOQUE):
            # Si ya la abandonaron por no avanzar, no escribe nada más.
            vigilancia.latir()
            copia.write(bloque)
            copiados += len(bloque)
            avisar(copiados, total)
        fin = time.monotonic()
    if al_copiar is not None:
        try:
            al_copiar(parcial.stat().st_size, inicio, fin)
        except Exception:  # noqa: BLE001 - medir nunca tumba una descarga
            logger.debug("no se pudo anotar la velocidad de %s", destino, exc_info=True)


def _traer_vigilado(ruta: str, destino: Path, bajar: Callable[[Vigilancia], int]) -> Path:
    """La copia de ``bajar`` -- que devuelve el tamaño del original -- vigilada, comprobada y renombrada."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = _parcial_de(destino)
    try:
        try:
            tamano = vigilado(bajar, que=f"La descarga de {ruta}")
        except CopiaSinAvance as error:
            raise RedSinAvance(str(error)) from error
        if parcial.stat().st_size != tamano:
            raise RedNoDisponible(f"La copia de {ruta} quedó incompleta; la red se cortó")
        os.replace(parcial, destino)
    finally:
        # Abandonada, la copia puede tener todavía el «.part» abierto (Windows no
        # deja borrarlo): queda para la limpieza de las copias de la corrida.
        with contextlib.suppress(OSError):
            parcial.unlink(missing_ok=True)
    return destino


def _tamano_abierto(archivo) -> int:
    """El tamaño de un archivo ya abierto, sin otra ida a la red; 0 si no se deja medir."""
    try:
        tamano = archivo.seek(0, io.SEEK_END)
        archivo.seek(0)
        return int(tamano)
    except Exception:  # noqa: BLE001 - sin tamaño, la barra no dice el porcentaje
        logger.debug("no se pudo medir el tamaño del archivo abierto", exc_info=True)
        return 0
