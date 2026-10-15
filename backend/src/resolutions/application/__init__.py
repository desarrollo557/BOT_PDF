"""Use cases and the ports they depend on. No vendor SDK lives here."""

from .acta_fuid import filas_de_actas
from .acta_split import ActaData, ActaSplit, ActaSplitResult

__all__ = [
    "filas_de_actas",
    "ActaSplit",
    "ActaSplitResult",
    "ActaData",
]
