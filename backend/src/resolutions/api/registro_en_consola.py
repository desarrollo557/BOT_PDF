"""Todo lo que hace el servicio, en la consola y según ocurre.

Hasta acá el servicio no configuraba el registro: se apoyaba en lo que uvicorn
trae de fábrica, que anota las peticiones y nada más. Lo que pasa dentro -- a
qué habilidad fue un documento, cuántas páginas releyó, cuándo le pidió una
lectura a un proveedor de pago, por qué una costura se unió -- ya se escribía
con ``logger.info`` en cada módulo, pero sin un manejador que lo sacara a
ninguna parte. El operador miraba una consola muda y un trabajo de doce minutos
parecía colgado.

Dos cosas hacen que esto sea "en tiempo real" y no "al terminar". La primera es
que el manejador escribe en ``stderr`` línea a línea y vacía el búfer en cada
registro. La segunda es que **los procesos del pool también se configuran**:
en Windows un proceso hijo arranca limpio, sin heredar los manejadores del
padre, y es en los hijos donde ocurre lo que interesa ver. Sin el
inicializador, el log del padre mostraba la petición HTTP y luego silencio.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

#: Hora con milisegundos, nivel, quién y qué. El nombre del módulo es lo que
#: permite saber si una línea viene del lector, del ensamblador o del
#: adaptador de Mistral sin tener que decirlo en cada mensaje.
FORMATO = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s: %(message)s"
FECHA = "%H:%M:%S"
#: En disco, con la fecha y el proceso: el archivo se lee días después, y
#: varios procesos del pool escriben en él a la vez.
FORMATO_EN_DISCO = "%(asctime)s.%(msecs)03d %(process)d %(levelname)-7s %(name)s: %(message)s"

#: Qué nivel se enseña del propio sistema. INFO cuenta cada decisión; DEBUG
#: añade cada reintento y cada esquina medida, que en un libro son miles de
#: líneas y sólo sirven para depurar.
VARIABLE_DE_NIVEL = "RESOLUTIONS_LOG_LEVEL"

_MARCA = "_resolutions_registro_configurado"

#: Dónde queda el registro en disco, además de la consola: una corrida de
#: días no puede depender de una ventana que alguien cierra o en la que un clic
#: deja la salida en pausa. ``RESOLUTIONS_LOG_DIR`` lo cambia; vacío lo apaga.
VARIABLE_DE_CARPETA = "RESOLUTIONS_LOG_DIR"
#: Cuántos días de registro se guardan.
DIAS_DE_REGISTRO = 30


class _Inmediato(logging.StreamHandler):
    """Un manejador que no deja nada en el búfer.

    ``stderr`` ya va línea a línea cuando es una consola, pero el servicio
    corre detrás de un script que a veces lo redirige, y entonces el sistema
    operativo agrupa la salida en bloques de varios kilobytes. Un bloque de
    cuatro kilobytes son cuarenta líneas de log que aparecen de golpe, medio
    minuto tarde.
    """

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


class _ArchivoDelDia(logging.Handler):
    """Un archivo por día, «bot-AAAA-MM-DD.log», abierto para añadir.

    Por día y no rotando por tamaño: rotar renombra el archivo, y en Windows
    no se puede renombrar uno que otro proceso del pool tiene abierto. Así cada
    proceso añade sus líneas al del día y ninguno pisa a otro.
    """

    def __init__(self, carpeta: Path) -> None:
        super().__init__()
        self._carpeta = carpeta
        self._dia: date | None = None
        self._archivo = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            hoy = date.fromtimestamp(record.created)
            if hoy != self._dia or self._archivo is None:
                if self._archivo is not None:
                    self._archivo.close()
                self._archivo = open(  # noqa: SIM115 - vive con el manejador
                    self._carpeta / f"bot-{hoy.isoformat()}.log", "a", encoding="utf-8"
                )
                self._dia = hoy
            self._archivo.write(self.format(record) + "\n")
            self._archivo.flush()
        except Exception:  # noqa: BLE001 - el registro nunca tumba el trabajo
            self.handleError(record)

    def close(self) -> None:
        if self._archivo is not None:
            self._archivo.close()
            self._archivo = None
        super().close()


def _carpeta_del_registro() -> Path | None:
    valor = os.environ.get(VARIABLE_DE_CARPETA)
    if valor is not None:
        return Path(valor) if valor.strip() else None
    return Path(os.environ.get("RESOLUTIONS_DATA_DIR", "./data")).resolve() / "logs"


def _borrar_los_viejos(carpeta: Path) -> None:
    limite = time.time() - timedelta(days=DIAS_DE_REGISTRO).total_seconds()
    for viejo in carpeta.glob("bot-*.log"):
        try:
            if viejo.stat().st_mtime < limite:
                viejo.unlink()
        except OSError:
            continue


def configurar(nivel: str | None = None, *, en_archivo: bool = True) -> None:
    """Deja el registro escribiendo en la consola y en el archivo del día.

    Llamarla dos veces no duplica.
    """
    raiz = logging.getLogger()
    if getattr(raiz, _MARCA, False):
        return
    manejador = _Inmediato(sys.stderr)
    manejador.setFormatter(logging.Formatter(FORMATO, datefmt=FECHA))
    raiz.addHandler(manejador)
    carpeta = _carpeta_del_registro() if en_archivo else None
    if carpeta is not None:
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
            _borrar_los_viejos(carpeta)
            en_disco = _ArchivoDelDia(carpeta)
            # Con la fecha: el archivo es de un día, pero se lee días después.
            en_disco.setFormatter(
                logging.Formatter(FORMATO_EN_DISCO, datefmt="%Y-%m-%d %H:%M:%S")
            )
            raiz.addHandler(en_disco)
        except OSError:
            logging.getLogger(__name__).warning("no se pudo abrir el registro en %s", carpeta)
    # Las bibliotecas ajenas sólo cuando avisan de algo; lo propio, entero.
    raiz.setLevel(logging.WARNING)
    logging.getLogger("resolutions").setLevel(
        (nivel or os.environ.get(VARIABLE_DE_NIVEL) or "INFO").upper()
    )
    setattr(raiz, _MARCA, True)


def configurar_worker() -> None:
    """Lo que corre al arrancar cada proceso del pool.

    Es el inicializador del ``ProcessPoolExecutor``. Sin él, cada worker nace
    sin manejadores y todo lo que el lector cuenta -- el reparto del libro, las
    esquinas leídas, la muestra local descartada -- se pierde en un proceso que
    nadie está mirando.
    """
    configurar()
    logging.getLogger("resolutions.worker").info("worker %s listo", os.getpid())
