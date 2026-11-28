"""El latido de un trabajo: cada petición que termina dice que el trabajo sigue vivo (2026-11-27).

El operador, 2026-11-27, con «ACTAS DE GRADO» de Odontología en «OCR + IA»:
«de vez en cuando se traba: Sin novedades desde hace 10 min», y pidió «que no se
trabe por falta de petición o algo; un sistema que cubra todos los escenarios».

No estaba trabado. La etapa «asegurando el nombre de 124 graduado(s)» anuncia
una noticia al empezar y después hace una petición a la IA por graduado, de 4 a
10 segundos cada una (el registro del contenedor iba por la 601 de un solo
libro), sin decir nada más. El vigilante (``api/ejecucion._esperar``) mide el
silencio desde la última noticia: a los 10 minutos la pantalla decía «sin
novedades» y a los 20 daba el libro por atascado y lo mandaba a reintentar al
final, tirando lo hecho.

Aquí está el latido. El trabajo lo enciende al empezar en su proceso
(``activar``), y lo llaman desde abajo quienes hacen trabajo de verdad:

* cada petición que un proveedor atendió, rechazó o dio por perdida
  (``application.consumo.Consumo``);
* cada lectura de Tesseract;
* cada página que se renderiza.

Cada llamada de ``pulso`` le dice al servicio «sigo vivo» sin cambiar la etapa
que ve el operador. Así sirve en todas las habilidades sin tocar cada bucle.

Lo que de verdad se cuelga -- una petición que no vuelve, una página que el
lector no suelta, una expresión regular sin fin -- no late, y el vigilante lo
sigue cortando como antes. Cada petición tiene su tiempo límite en su adaptador.

Un proceso del pool atiende un trabajo a la vez, así que el latido es del
proceso: lo comparten los hilos que abre el trabajo (las lecturas en paralelo
de la IA) sin pasarlo de mano en mano.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

#: Cada cuánto, como mucho, sale un latido: una noticia cada pocos segundos
#: basta para el vigilante y no llena la cola de avance con cientos por minuto.
INTERVALO = 5.0

_cerrojo = threading.Lock()
_avisar: Callable[[], None] | None = None
_ultimo = 0.0


def activar(avisar: Callable[[], None]) -> None:
    """Enciende el latido del trabajo que empieza en este proceso: ``avisar`` manda la noticia."""
    global _avisar, _ultimo
    with _cerrojo:
        _avisar = avisar
        _ultimo = 0.0


def desactivar() -> None:
    """Lo apaga al terminar el trabajo: el siguiente del mismo proceso enciende el suyo."""
    global _avisar
    with _cerrojo:
        _avisar = None


def pulso() -> None:
    """El trabajo sigue vivo: avisa, como mucho una vez cada ``INTERVALO`` segundos.

    Nunca lanza: un aviso que falla no puede tumbar la lectura que lo dio.
    """
    global _ultimo
    with _cerrojo:
        avisar = _avisar
        ahora = time.monotonic()
        if avisar is None or ahora - _ultimo < INTERVALO:
            return
        _ultimo = ahora
    try:
        avisar()
    except Exception:  # noqa: BLE001 - la telemetría nunca rompe el trabajo
        return
