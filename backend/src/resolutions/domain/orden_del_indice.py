"""El Índice Electrónico de una caja va por la fecha de sus documentos.

Lo dictó el operador el 2026-11-04, primero para las cajas ya entregadas de
MAGANGUE y después para lo que entregue el bot: «ubicarás los documentos por
fecha de creación de documento… lo antiguo va de primero y lo nuevo de último».
Y «no vas a renombrar por fecha»: sólo cambia el índice. Los PDF conservan su
número, el del orden de las hojas, y «Orden Documento» se renumera 1, 2, 3… en
el orden nuevo.

- Lo que no trae fecha («S.F.») va al final: no se sabe dónde va.
- A igual fecha, el orden de antes, el de las hojas: el reclamo y su
  notificación del mismo día no se cruzan, y ordenar dos veces da lo mismo.

Es la misma regla que aplica ``scripts/renombrar_reclamaciones.py`` a las cajas
que ya estaban entregadas: lo que entrega el bot y lo que deja el script tienen
que quedar iguales.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date


def orden_cronologico(fechas: Sequence[date | None]) -> list[int]:
    """Los puestos de antes en el orden nuevo: lo antiguo primero y lo que no trae fecha al final."""
    return sorted(range(len(fechas)), key=lambda i: (fechas[i] is None, fechas[i] or date.min, i))
