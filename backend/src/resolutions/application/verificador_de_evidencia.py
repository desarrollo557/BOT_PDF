"""El verificador independiente de la evidencia: cada hallazgo, contra su propia evidencia, sin creerle a quien lo extrajo.

Lo pidió el operador el 2026-11-18: «Los agentes auditores deben trabajar
sobre evidencias y resultados estructurados, no simplemente aceptar las
conclusiones de otros agentes». Es determinista y gratis, y mira el 100 % de
los documentos -- la auditoría de cierre, con la IA, sigue mirando una
muestra --. Comprueba que:

- el RE que se cree tiene su forma y aparece **literal** en su fragmento, salvo
  el que confirmó una persona;
- la fecha es una fecha posible -- ni futura ni anterior a 1990 -- y su
  fragmento, si lo hay, la dice;
- lo que se cree tiene valor, y lo que no, dice qué se buscó o qué se propone.

Lo que no pasa no se corrige aquí: se dice, con el motivo, y se cuenta.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from ..domain.evidencia import (
    SE_CREE,
    Estado,
    aparece_literal,
    es_re_entero,
    fragmento_de_la_fecha,
)

#: El año más antiguo que se le cree a la fecha de un documento.
ANIO_MINIMO = 1990
#: El método del RE que confirmó una persona en la Revisión: no tiene fragmento.
CONFIRMADO_POR_EL_OPERADOR = "confirmado por el operador"


@dataclass(frozen=True, slots=True)
class Reparo:
    """Lo que el verificador no aceptó de un hallazgo."""

    documento: str
    parametro: str
    motivo: str


def _se_cree(hallazgo: Mapping) -> bool:
    return str(hallazgo.get("estado") or "") in {str(e) for e in SE_CREE}


def reparos_del_hallazgo(hallazgo: Mapping, *, hoy: date | None = None) -> list[str]:
    """Por qué el hallazgo no se sostiene con su propia evidencia; vacío si se sostiene."""
    hoy = hoy or date.today()
    parametro = str(hallazgo.get("parametro") or "")
    valor = hallazgo.get("valor")
    fragmento = hallazgo.get("fragmento")
    reparos: list[str] = []
    if _se_cree(hallazgo):
        if not valor:
            return ["se cree sin valor"]
        if parametro == "re":
            if not es_re_entero(str(valor)):
                reparos.append(f"«{valor}» no es un RE entero")
            elif hallazgo.get("metodo") != CONFIRMADO_POR_EL_OPERADOR and not aparece_literal(str(valor), fragmento):
                reparos.append(f"{valor} no aparece tal cual en su fragmento")
        elif parametro == "fecha":
            try:
                fecha = date.fromisoformat(str(valor))
            except ValueError:
                return [f"«{valor}» no es una fecha"]
            if fecha > hoy:
                reparos.append(f"la fecha {valor} es futura")
            if fecha.year < ANIO_MINIMO:
                reparos.append(f"la fecha {valor} es anterior a {ANIO_MINIMO}")
            if fragmento and fragmento_de_la_fecha(str(fragmento), str(valor)) is None:
                reparos.append(f"su fragmento no dice la fecha {valor}")
    elif str(hallazgo.get("estado")) == str(Estado.REQUIERE_VALIDACION) and not hallazgo.get("candidatos"):
        reparos.append("requiere validación sin ningún candidato")
    elif str(hallazgo.get("estado")) == str(Estado.NO_ENCONTRADO) and not hallazgo.get("buscado"):
        reparos.append("no encontrado sin decir qué se buscó")
    return reparos


def verificar(evidencia: Mapping[str, Mapping[str, Mapping]], documento: str, *, hoy: date | None = None) -> list[Reparo]:
    """Los reparos de la evidencia de un PDF -- ``{parametro: {primera_hoja: hallazgo}}`` --, con su documento."""
    return [
        Reparo(f"{documento} · hoja {primera}", parametro, motivo)
        for parametro, por_hoja in sorted(evidencia.items())
        if isinstance(por_hoja, Mapping)
        for primera, hallazgo in sorted(por_hoja.items(), key=lambda par: int(par[0]) if str(par[0]).isdigit() else 0)
        if isinstance(hallazgo, Mapping)
        for motivo in reparos_del_hallazgo(hallazgo, hoy=hoy)
    ]


def verificar_todo(evidencias: Iterable[tuple[str, Mapping]], *, hoy: date | None = None) -> list[Reparo]:
    """Los reparos de varios PDF: (documento, evidencia)."""
    return [reparo for documento, evidencia in evidencias for reparo in verificar(evidencia, documento, hoy=hoy)]
