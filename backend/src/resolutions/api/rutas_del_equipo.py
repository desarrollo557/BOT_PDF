"""Las rutas del equipo vistas desde el contenedor, y al revés.

En Docker el servicio corre en Linux y no ve los discos de Windows: cada unidad
se monta dentro del contenedor («C:\\» en ``/equipo/c``, «Z:\\» en
``/equipo/z``). Sin esta traducción el operador tendría que escribir
``/equipo/c/Users/…`` en lugar de la ruta que copia del Explorador, y el
explorador de la pantalla le enseñaría carpetas que no reconoce.

Las unidades montadas se declaran en ``BOTPDF_UNIDADES`` -- «C:=/equipo/c;Z:=/equipo/z»
--, que escribe el instalador según las unidades que encuentra. Sin ella (el
servicio corriendo directamente en Windows) todo es la identidad: nada cambia.

Las carpetas de red no se montan (lo pidió el operador el 2026-10-20 con
«\\\\200.100.20.97\\afinia\\…»): en el contenedor se leen con el cliente SMB de
``adapters/red_smb.py``, y su ruta viaja con barras -- «//200.100.20.97/afinia/…»
--. El operador sigue pegando la ruta de red tal como la copia del Explorador.

Una unidad también puede declararse con una ruta de red: «Y:=//SIARNAS/Digitalización/…».
Docker monta vacías las unidades de red mapeadas («Y:», «X:») y los discos
virtuales como WorkDrive («Z:»), sin avisar: el bot veía cero PDF donde el
Explorador enseña la caja entera (2026-10-28, «Z:\\Shared with Me\\KINGSPAN»).
Declaradas así, «Y:\\caja» se lee por el cliente de red como «//SIARNAS/…/caja»
y se le enseña al operador otra vez como «Y:\\caja».
"""

from __future__ import annotations

import os
import re

from ..adapters import red_smb

VARIABLE = "BOTPDF_UNIDADES"

#: «C:», «C:\», «C:\Users\ana» o «c:/Users/ana».
_RUTA_DE_WINDOWS = re.compile(r"^([A-Za-z]):(?:[\\/](.*))?$")
#: Dónde puede estar montada una unidad: una ruta absoluta del contenedor
#: («/equipo/c») o, en las pruebas sobre Windows, una carpeta con su letra.
_MONTAJE = re.compile(r"^(/|[A-Za-z]:/)")


def _barras(ruta: str) -> str:
    return ruta.replace("\\", "/")


def unidades() -> dict[str, str]:
    """Las unidades montadas: letra en mayúscula -> carpeta en el contenedor o ruta de red («//…»)."""
    valor = os.environ.get(VARIABLE, "")
    montadas: dict[str, str] = {}
    for par in valor.split(";"):
        letra, _, montaje = par.partition("=")
        letra = letra.strip().rstrip(":").upper()
        montaje = _barras(montaje.strip()).rstrip("/")
        if len(letra) == 1 and letra.isalpha() and _MONTAJE.match(montaje + "/"):
            montadas[letra] = montaje
    return montadas


#: Las cuentas con permiso en el recurso que comparte cada unidad de este
#: equipo con el contenedor: «Z:=SERVER2\\SIAR1,SIAR\\otra». Las anota el
#: instalador, que es quien crea el recurso.
VARIABLE_DE_CUENTAS = "BOTPDF_CUENTAS_DE_RED"


def cuentas_de(ruta: object) -> list[str]:
    """Quién puede entrar al recurso de la unidad de ``ruta``; vacío si no se sabe.

    El recurso de «Z:» sólo deja entrar a la cuenta que instaló (2026-10-29):
    en el otro equipo se escribía «server2», la cuenta era «SIAR1», y el cuadro
    de usuario y clave volvía sin decir cuál era la buena.
    """
    letra = (con_letra(ruta) or "")[:1].upper()
    if not letra:
        return []
    for par in os.environ.get(VARIABLE_DE_CUENTAS, "").split(";"):
        suya, _, cuentas = par.partition("=")
        if suya.strip().rstrip(":").upper() == letra:
            return [cuenta.strip() for cuenta in cuentas.split(",") if cuenta.strip()]
    return []


def es_una_raiz(ruta: str) -> bool:
    """Si es la raíz de una unidad («C:\\») o de un recurso de red («\\\\servidor\\recurso\\»)."""
    if re.fullmatch(r"[A-Za-z]:\\?", ruta):
        return True
    partes = red_smb.partes(ruta)
    return partes is not None and not partes.resto


def al_servicio(ruta: str) -> str:
    """La ruta que escribió el operador, donde el servicio la encuentra.

    «C:\\Users\\ana\\ENTRADA» -> «/equipo/c/Users/ana/ENTRADA», y en el
    contenedor «\\\\200.100.20.97\\afinia\\REPOSITORIO» -> «//200.100.20.97/afinia/REPOSITORIO».
    Una ruta de una unidad que no está montada, o una que ya es del contenedor,
    pasa tal cual.
    """
    if red_smb.por_smb(ruta):
        return red_smb.partes(ruta).del_servicio  # type: ignore[union-attr]
    montadas = unidades()
    coincide = _RUTA_DE_WINDOWS.match(ruta.strip()) if montadas else None
    if not coincide:
        return ruta
    montaje = montadas.get(coincide.group(1).upper())
    if montaje is None:
        return ruta
    resto = _barras(coincide.group(2) or "").strip("/")
    return f"{montaje}/{resto}" if resto else montaje


def unidad_que_no_ve(ruta: str) -> str | None:
    """La letra de una ruta de Windows que el servicio no tiene conectada, o ``None``.

    Sólo en Docker (con unidades declaradas), y sólo si el propio proceso
    tampoco ve la raíz de esa unidad: fuera de Docker la resuelve Windows.
    """
    montadas = unidades()
    coincide = _RUTA_DE_WINDOWS.match(ruta.strip()) if montadas else None
    if not coincide:
        return None
    letra = coincide.group(1).upper()
    if letra in montadas or os.path.isdir(f"{letra}:\\"):
        return None
    return letra


def por_que_no_se_ve(ruta: str) -> str | None:
    """Por qué el servicio no ve ``ruta``, si es por su unidad, en palabras del operador.

    «Z:\\Shared with Me\\REPOSITORIO UDC\\…» contestaba «La carpeta no existe»
    (2026-10-28) con la carpeta abierta en el Explorador: la unidad no estaba
    conectada al contenedor. Y de destino era peor: la carpeta se creaba
    dentro del contenedor, con «Z:\\…» como nombre, y lo entregado no salía.
    """
    letra = unidad_que_no_ve(ruta)
    if letra is None:
        return None
    conectadas = ", ".join(f"{otra}:" for otra in sorted(unidades()))
    return (
        f"El servicio no ve la unidad {letra}: (corre en Docker y sólo tiene conectadas {conectadas}); "
        "la carpeta puede existir, pero desde aquí no se alcanza. Vuelva a ejecutar instalar-docker.cmd: "
        f"si {letra}: es una unidad de red la conecta sola, y si es WorkDrive u otro disco virtual dice "
        "el comando para compartirla una vez como administrador. Mientras tanto puede escribir la "
        "ruta de red de esa carpeta (\\\\servidor\\recurso\\…)."
    )


def _bajo(ruta: str, montaje: str) -> bool:
    """Si ``ruta`` es ``montaje`` o está dentro. En la red, sin distinguir mayúsculas, como Windows."""
    if montaje.startswith("//"):
        ruta, montaje = ruta.casefold(), montaje.casefold()
    return ruta == montaje or ruta.startswith(montaje + "/")


def al_operador(ruta: object) -> str:
    """La ruta del contenedor como la reconoce el operador: «C:\\Users\\ana\\ENTRADA»."""
    texto = str(ruta)
    comparable = _barras(texto)
    if red_smb.por_smb(texto):
        # Una ruta de red con barras repetidas o al revés: la forma de `partes`.
        comparable = red_smb.partes(texto).del_servicio  # type: ignore[union-attr]
    # Primero las unidades: una de red se le enseña con su letra, «Z:\\…». Si
    # una cubre el recurso entero y otra una carpeta dentro, gana la más honda.
    for letra, montaje in sorted(unidades().items(), key=lambda par: -len(par[1])):
        if _bajo(comparable, montaje):
            resto = comparable[len(montaje) :].strip("/")
            return f"{letra}:\\" + resto.replace("/", "\\")
    if red_smb.por_smb(texto):
        partes = red_smb.partes(texto)
        return partes.unc if partes.resto else f"{partes.raiz}\\"  # type: ignore[union-attr]
    return texto


def con_letra(ruta: object) -> str | None:
    """La ruta con la letra de su unidad («Z:\\…»), o ``None`` si ninguna unidad la cubre."""
    mostrada = al_operador(ruta)
    return mostrada if _RUTA_DE_WINDOWS.match(mostrada) and mostrada != str(ruta) else None


def raices() -> list[dict[str, str]]:
    """Las unidades montadas y las carpetas de red ya abiertas: los puntos de partida del explorador."""
    discos = [{"name": f"Disco {letra}:", "path": f"{letra}:\\"} for letra in sorted(unidades())]
    return discos + red_abierta()


def red_abierta() -> list[dict[str, str]]:
    """Los recursos de red a los que ya se entró en esta sesión del servicio.

    Sin los que ya son una unidad: ésos salen como «Disco Z:».
    """
    return [
        {"name": f"Red {raiz}", "path": f"{raiz}\\"}
        for raiz in red_smb.conectados()
        if con_letra(raiz) is None
    ]
