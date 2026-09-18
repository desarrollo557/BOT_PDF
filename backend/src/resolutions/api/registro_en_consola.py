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

#: Hora con milisegundos, nivel, quién y qué. El nombre del módulo es lo que
#: permite saber si una línea viene del lector, del ensamblador o del
#: adaptador de Mistral sin tener que decirlo en cada mensaje.
FORMATO = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s: %(message)s"
FECHA = "%H:%M:%S"

#: Qué nivel se enseña del propio sistema. INFO cuenta cada decisión; DEBUG
#: añade cada reintento y cada esquina medida, que en un libro son miles de
#: líneas y sólo sirven para depurar.
VARIABLE_DE_NIVEL = "RESOLUTIONS_LOG_LEVEL"

_MARCA = "_resolutions_registro_configurado"


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


def configurar(nivel: str | None = None) -> None:
    """Deja el registro escribiendo en la consola. Llamarla dos veces no duplica."""
    raiz = logging.getLogger()
    if getattr(raiz, _MARCA, False):
        return
    manejador = _Inmediato(sys.stderr)
    manejador.setFormatter(logging.Formatter(FORMATO, datefmt=FECHA))
    raiz.addHandler(manejador)
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
