"""Una copia que se vigila: si pasa un rato sin mover un byte, se da por colgada (2026-11-28).

El operador, 2026-11-27: «que no se trabe por falta de petición o algo; un
sistema que cubra todos los escenarios». La auditoría de atascos de ese día
encontró que las copias de la red -- bajar un PDF del origen, entregar uno en
el destino -- iban en un hilo sin tiempo límite. Un servidor SMB que se queda
callado deja la lectura o la escritura esperando para siempre: el hilo no
vuelve, el PDF retiene su ranura de la corrida y, a veces, el cerrojo de la
entrega, y la carpeta entera se para sin un error que mirar.

Un hilo que espera a la red no se puede interrumpir desde fuera. Así que la
copia corre en un hilo propio y quien la pidió la vigila: cada bloque copiado
«late» (``Vigilancia.latir``), y si pasan ``SEGUNDOS_SIN_AVANCE`` sin un latido
se lanza ``CopiaSinAvance`` -- un ``TimeoutError``: fallo de red, pasajero, que
se reintenta --. El hilo abandonado no escribe nada más en cuanto la red le
devuelve el control: su siguiente latido lo para.

Esperar un turno (el de descarga de un servidor) no es estar colgado: mientras
se espera (``Vigilancia.esperando``) el reloj no corre.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, wait

#: Cuánto puede pasar una copia sin mover un byte antes de darla por colgada.
SEGUNDOS_SIN_AVANCE = 120.0
#: Cada cuánto, como mucho, mira el vigilante.
_MIRADA = 5.0


class CopiaSinAvance(TimeoutError):
    """La copia lleva ``SEGUNDOS_SIN_AVANCE`` sin mover un byte: la red o el disco se colgaron."""

    para_el_operador = True

    def __str__(self) -> str:
        # Sólo el mensaje: quien la recoge le pone el archivo (``filename``), y
        # un ``OSError`` con él se diría «[Errno None] None: …».
        return str(self.args[0]) if self.args else "la copia no avanzó"


class Vigilancia:
    """Lo que la copia le dice a quien la vigila: «avancé» o «espero mi turno»."""

    def __init__(self) -> None:
        self._cerrojo = threading.Lock()
        self._ultimo = time.monotonic()
        self._esperando = 0
        #: Quien vigilaba se fue: la copia no escribe nada más.
        self.abandonada = threading.Event()

    def latir(self) -> None:
        """La copia avanzó. Si ya la abandonaron, se para aquí y no escribe nada más."""
        if self.abandonada.is_set():
            raise CopiaSinAvance("la copia se abandonó por no avanzar")
        with self._cerrojo:
            self._ultimo = time.monotonic()

    @contextlib.contextmanager
    def esperando(self) -> Iterator[None]:
        """Mientras espera su turno el reloj no corre: esperar no es estar colgada."""
        with self._cerrojo:
            self._esperando += 1
        try:
            yield
        finally:
            with self._cerrojo:
                self._esperando -= 1
                self._ultimo = time.monotonic()
        self.latir()

    def quieta(self) -> float:
        """Los segundos que lleva sin avanzar; 0 mientras espera su turno."""
        with self._cerrojo:
            return 0.0 if self._esperando else time.monotonic() - self._ultimo


class EscrituraVigilada:
    """Un archivo abierto para escribir cuyo cada ``write`` late: para ``shutil.copyfileobj``."""

    def __init__(self, archivo, vigilancia: Vigilancia) -> None:
        self._archivo = archivo
        self._vigilancia = vigilancia

    def write(self, datos) -> int:
        self._vigilancia.latir()
        escritos = self._archivo.write(datos)
        self._vigilancia.latir()
        return escritos


def vigilado[T](
    hacer: Callable[[Vigilancia], T], *, sin_avance: float | None = None, que: str = "La copia"
) -> T:
    """Lo que devuelve ``hacer``, corriéndolo en un hilo propio que debe latir.

    ``hacer`` recibe la ``Vigilancia`` y llama a ``latir`` con cada bloque. Si
    pasan ``sin_avance`` segundos (``SEGUNDOS_SIN_AVANCE`` por omisión; 0 o
    menos, sin vigilancia) sin un latido, se lanza ``CopiaSinAvance`` y el hilo
    se abandona. Lo que lance ``hacer`` sube tal cual.
    """
    tope = SEGUNDOS_SIN_AVANCE if sin_avance is None else float(sin_avance)
    vigilancia = Vigilancia()
    if tope <= 0:
        return hacer(vigilancia)
    futuro: Future = Future()

    def correr() -> None:
        try:
            futuro.set_result(hacer(vigilancia))
        except BaseException as error:  # noqa: BLE001 - viaja a quien vigila
            futuro.set_exception(error)

    threading.Thread(target=correr, name="copia-vigilada", daemon=True).start()
    while True:
        hechos, _ = wait([futuro], timeout=min(_MIRADA, tope))
        if hechos:
            return futuro.result()
        if vigilancia.quieta() >= tope:
            vigilancia.abandonada.set()
            raise CopiaSinAvance(
                f"{que} lleva {tope:.0f} s sin mover un byte: la red no contesta. Se da por "
                "cortada y se reintenta."
            )
