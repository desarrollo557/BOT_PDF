"""La auditoría de cierre de una corrida: la muestra al azar y el margen de error medido.

Lo pidió el operador el 2026-11-05: que el bot, así como vigila cada PDF mientras
procesa, «también lo haga al finalizar el procesamiento», que «se asegure que el
mismo número de registros que está en la fuente esté en el destino» y que
«agarre aleatoriamente unos 100 documentos y valide el margen de errores y los
PDF divididos según los patrones». Eligió 100 fijos y, si la muestra encuentra
errores, revisar otros 100.

Aquí sólo las cuentas, sin abrir nada:

- **La muestra**: al azar y con una **semilla** que se anota, para que la misma
  muestra se pueda repetir y discutir.
- **El margen de error de la corrida entera**, medido en la muestra: la tasa
  observada y su **intervalo de Wilson al 95 %**. Con 100 de 100 bien no se
  dice «0 % de error», que sería mentir: se dice «menos del 3,7 %».
- **El veredicto de cada PDF**: «bien», «error» (algo que no cuadra o un corte
  probado mal), «dudoso» (fuera del margen y nadie pudo decidir) o «no se
  pudo auditar».
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

#: Cuántos PDF entregados se revisan al cerrar una corrida (lo eligió el operador).
TAMANO_DE_LA_MUESTRA = 100
#: Con qué confianza se dice el margen de error.
CONFIANZA = 0.95
#: El error que se acepta en una corrida (lo pidió el operador: «todo manejando
#: un margen de errores»). La corrida está **dentro del margen** si aun en el
#: peor caso de su intervalo queda por debajo; **fuera**, si aun en el mejor
#: queda por encima; y **sin certeza**, si el intervalo lo cruza. Se cambia con
#: ``BOTPDF_MARGEN_ACEPTABLE`` (en por ciento).
MARGEN_ACEPTABLE = 0.05

DENTRO_DEL_MARGEN = "dentro del margen"
FUERA_DEL_MARGEN = "fuera del margen"
SIN_CERTEZA = "sin certeza"
#: El valor z de esa confianza, a dos colas.
_Z = {0.90: 1.6449, 0.95: 1.9600, 0.99: 2.5758}

BIEN = "bien"
ERROR = "error"
DUDOSO = "dudoso"
NO_AUDITADO = "no se pudo auditar"


@dataclass(frozen=True, slots=True)
class MargenDeError:
    """La tasa de error medida en la muestra y entre qué valores está la de la corrida."""

    errores: int
    revisados: int
    tasa: float
    desde: float
    hasta: float
    confianza: float = CONFIANZA
    aceptable: float = MARGEN_ACEPTABLE

    @property
    def dictamen(self) -> str:
        """Si el error de la corrida está dentro del margen aceptable, fuera, o no se puede asegurar."""
        if not self.revisados:
            return SIN_CERTEZA
        if self.hasta <= self.aceptable:
            return DENTRO_DEL_MARGEN
        if self.desde > self.aceptable:
            return FUERA_DEL_MARGEN
        return SIN_CERTEZA

    def texto_del_dictamen(self) -> str:
        """«Dentro del margen aceptable (5 %)», dicho para el operador."""
        aceptable = _por_ciento(self.aceptable)
        if self.dictamen == DENTRO_DEL_MARGEN:
            return f"Dentro del margen aceptable ({aceptable}): aun en el peor caso, el error queda por debajo"
        if self.dictamen == FUERA_DEL_MARGEN:
            return f"Fuera del margen aceptable ({aceptable}): aun en el mejor caso, el error queda por encima"
        if not self.revisados:
            return "Sin muestra que juzgar"
        return f"Sin certeza frente al margen aceptable ({aceptable}): el intervalo lo cruza"

    def texto(self) -> str:
        """«0 de 100 con error: el de la corrida, menos del 3,7 % (95 % de confianza)»."""
        if not self.revisados:
            return "No se revisó ningún PDF."
        base = f"{self.errores} de {self.revisados} con error"
        confianza = f"{round(self.confianza * 100)} % de confianza"
        if not self.errores:
            return f"{base}: el de la corrida, menos del {_por_ciento(self.hasta)} ({confianza})"
        return (
            f"{base} ({_por_ciento(self.tasa)}): el de la corrida, entre el {_por_ciento(self.desde)} "
            f"y el {_por_ciento(self.hasta)} ({confianza})"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "errores": self.errores,
            "revisados": self.revisados,
            "tasa": round(self.tasa, 4),
            "desde": round(self.desde, 4),
            "hasta": round(self.hasta, 4),
            "confianza": self.confianza,
            "aceptable": self.aceptable,
            "dictamen": self.dictamen,
            "texto": self.texto(),
            "texto_del_dictamen": self.texto_del_dictamen(),
        }


def margen_de_error(
    errores: int, revisados: int, confianza: float = CONFIANZA, *, aceptable: float = MARGEN_ACEPTABLE
) -> MargenDeError:
    """La tasa de error de la muestra y su intervalo de Wilson.

    Wilson y no la aproximación normal: con pocos errores -- lo esperado -- la
    normal da intervalos que empiezan por debajo de cero y dice «0 % ± 0 %»
    cuando no se vio ninguno.
    """
    if revisados <= 0:
        return MargenDeError(0, 0, 0.0, 0.0, 0.0, confianza, aceptable)
    errores = max(0, min(errores, revisados))
    z = _Z.get(confianza, 1.96)
    p = errores / revisados
    denominador = 1 + z * z / revisados
    centro = (p + z * z / (2 * revisados)) / denominador
    radio = z * math.sqrt(p * (1 - p) / revisados + z * z / (4 * revisados * revisados)) / denominador
    return MargenDeError(
        errores, revisados, p, max(0.0, centro - radio), min(1.0, centro + radio), confianza, aceptable
    )


def elegir_la_muestra(
    candidatos: Sequence[str], cuantos: int, semilla: int, *, excluir: Iterable[str] = ()
) -> list[str]:
    """``cuantos`` al azar de ``candidatos``, sin los de ``excluir``; todos si no llegan.

    Ordenados primero: la misma semilla sobre los mismos PDF da siempre la misma
    muestra, los liste el disco en el orden que los liste.
    """
    fuera = set(excluir)
    disponibles = sorted(c for c in set(candidatos) if c not in fuera)
    if len(disponibles) <= cuantos:
        return disponibles
    return sorted(random.Random(semilla).sample(disponibles, cuantos))


@dataclass(frozen=True, slots=True)
class PdfAuditado:
    """Lo que la auditoría encontró en un PDF entregado."""

    pdf: str
    estado: str
    #: Lo que no cuadra o lo que hay que mirar, dicho para el operador.
    hallazgos: tuple[str, ...] = ()
    paginas: int = 0
    archivos: int = 0
    costuras: int = 0
    dentro_del_margen: int = 0
    preguntadas_a_la_ia: int = 0
    habilidad: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "pdf": self.pdf,
            "estado": self.estado,
            "hallazgos": list(self.hallazgos),
            "paginas": self.paginas,
            "archivos": self.archivos,
            "costuras": self.costuras,
            "dentro_del_margen": self.dentro_del_margen,
            "preguntadas_a_la_ia": self.preguntadas_a_la_ia,
            "habilidad": self.habilidad,
        }


def veredicto(errores: Sequence[str], dudas: Sequence[str]) -> str:
    """«error» si algo no cuadra; «dudoso» si sólo hay dudas; si no, «bien»."""
    if errores:
        return ERROR
    if dudas:
        return DUDOSO
    return BIEN


def _por_ciento(valor: float) -> str:
    """«3,7 %», con coma decimal y un decimal como mucho."""
    numero = round(valor * 100, 1)
    texto = f"{numero:.1f}".rstrip("0").rstrip(".")
    return f"{texto.replace('.', ',')} %"
