"""Poder parar el trabajo que ya está corriendo.

Un documento de cuatrocientas páginas tarda minutos, y en ese rato el operador
puede darse cuenta de que subió el archivo equivocado, o de que necesita la
máquina para otra cosa. Hasta ahora la única salida era esperar.

Parar de verdad no es matar el proceso. Un worker abatido a mitad de una
escritura deja archivos a medias que nadie sabe si están completos, y deja al
resto del lote sin quien le informe. Lo que se hace aquí es lo contrario: el
trabajo pregunta, entre una página y la siguiente, si debe seguir. Entre páginas
no hay nada a medio escribir, así que ése es el único sitio donde parar es
seguro -- y también el único donde reanudar significa continuar y no empezar de
nuevo.

El precio es que la orden no es instantánea: tarda lo que tarde la página en
curso, que en un escaneo con OCR es alrededor de un segundo. A cambio, lo que
quedó escrito está entero y el sistema puede decir exactamente por dónde iba.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Protocol, runtime_checkable


class RunState(StrEnum):
    """En qué situación está un trabajo que ya empezó."""

    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class Cancelled(Exception):
    """El operador canceló el trabajo.

    No es un error del documento ni del sistema: es una decisión, y se propaga
    como excepción sólo porque es la forma de abandonar el trabajo desde donde
    se esté sin dejar nada a medio hacer.
    """


#: Cada cuánto vuelve a preguntar un trabajo en pausa. Una décima es imperceptible
#: para quien pulsa "reanudar" y no cuesta nada: son diez consultas por segundo a
#: una variable compartida mientras nadie está trabajando.
POLL_SECONDS = 0.1


@runtime_checkable
class RunControl(Protocol):
    """Lo que el trabajo consulta para saber si sigue.

    Deliberadamente diminuto: una sola llamada, en un solo sitio del bucle. Un
    control con más superficie acabaría consultándose a mitad de una escritura,
    que es justo donde no se puede parar.
    """

    def check(self) -> None:
        """Sigue, espera o abandona.

        Devuelve normalmente si el trabajo debe continuar; bloquea mientras esté
        en pausa; y levanta :class:`Cancelled` si se canceló.
        """
        ...


class NullRunControl:
    """El que no para nunca. Es el que se usa cuando nadie está mirando."""

    def check(self) -> None:
        return None


class FlagRunControl:
    """Un control sobre algo que dice, cada vez que se le pregunta, cómo está.

    La fuente es una función y no un valor porque el trabajo corre en otro
    proceso: lo que hay al otro lado es un diccionario compartido, y hay que
    volver a consultarlo cada vez para ver lo que el operador acaba de decidir.
    """

    def __init__(self, read_state, poll_seconds: float = POLL_SECONDS) -> None:
        self._read_state = read_state
        self._poll = poll_seconds

    def check(self) -> None:
        while True:
            state = self._state()
            if state is RunState.CANCELLED:
                raise Cancelled("el operador canceló el trabajo")
            if state is not RunState.PAUSED:
                return
            time.sleep(self._poll)

    def _state(self) -> RunState:
        try:
            raw = self._read_state()
        except Exception:  # noqa: BLE001 - perder el canal no detiene el trabajo
            # Si el control deja de responder, el trabajo sigue. Es la única
            # opción honesta: pararlo por no poder preguntar sería perder el
            # documento por un fallo de la telemetría.
            return RunState.RUNNING
        try:
            return RunState(str(raw))
        except ValueError:
            return RunState.RUNNING
