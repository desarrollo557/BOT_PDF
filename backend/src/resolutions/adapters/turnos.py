"""El turno común de llamadas a la IA, sin que un proceso muerto lo retenga para siempre.

El tope de llamadas a la vez es un semáforo del Manager que comparten todos
los procesos del pool. Si un proceso muere -- memoria, un fallo nativo --
mientras tiene un turno, ese turno no se devuelve nunca, y tras unas cuantas
muertes las llamadas a la IA se quedaban esperando para siempre: la corrida
parecía viva y no avanzaba. Ahora se espera un turno como mucho
``ESPERA_MAXIMA`` segundos; si no llega, se llama igual y se avisa en el
registro. Pasarse un poco del tope es un 429 que los adaptadores ya saben
esperar; quedarse parado no lo arregla nadie.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

ESPERA_MAXIMA = 600.0


@contextmanager
def turno(semaforo, espera: float = ESPERA_MAXIMA) -> Iterator[bool]:
    """Toma un turno del semáforo común, o sigue sin él tras ``espera`` segundos."""
    if semaforo is None:
        yield True
        return
    if not hasattr(semaforo, "acquire"):
        # Un gestor de contexto cualquiera hace de turno tal cual.
        with semaforo:
            yield True
        return
    try:
        tomado = bool(semaforo.acquire(True, espera))
    except Exception:  # noqa: BLE001 - un Manager caído no impide leer la página
        logger.warning("no se pudo pedir turno para la IA; se sigue sin él", exc_info=True)
        tomado = False
    if not tomado:
        logger.warning(
            "ningún turno de IA libre en %.0f s (¿un proceso murió con uno?); se llama sin él",
            espera,
        )
    try:
        yield tomado
    finally:
        if tomado:
            try:
                semaforo.release()
            except Exception:  # noqa: BLE001 - devolver el turno nunca tumba la lectura
                logger.debug("no se pudo devolver el turno de IA", exc_info=True)
