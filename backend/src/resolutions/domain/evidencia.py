"""La evidencia de cada valor extraído: qué se leyó, dónde, quién lo leyó y si se cree.

Lo pidió el operador el 2026-11-18, en su segunda ejecución integral: «NUNCA
INVENTAR INFORMACIÓN… No quiero que el sistema diga que encontró un parámetro:
quiero que pueda demostrar exactamente dónde, cómo y por qué lo encontró».

Y decidió dos reglas:

* **Lo que otro documento sugiere se propone, no se pone.** Un RE que sólo
  existe porque se corrigió una lectura -- la oficina a una cifra, una cifra de
  más, el RE impreso en otra hoja de la caja, el de su trámite -- es un
  *candidato*: va a la Revisión con su motivo, nunca al nombre.
* **La letra a mano se cree con dos lectores.** Un RE escrito a mano en un
  sello entra al nombre sólo si dos lectores distintos -- el OCR de pago y el
  modelo con visión, por ejemplo -- lo leen igual, cifra por cifra. Lo impreso
  -- la etiqueta, el PQR de la constancia, el radicado que cita una
  notificación -- basta con que una lectura lo traiga literal.

«Literal» es la única transformación permitida: las trece cifras seguidas en
la lectura, con a lo sumo un blanco, un punto o un guion entre ellas, como los
mete el escáner. Ni una letra leída por cifra, ni una cifra de más o de menos.

Aquí no se lee papel: entran las lecturas tal como las dejó cada lector.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class Estado(StrEnum):
    """Lo que se sabe de un valor extraído."""

    #: Dos lectores distintos lo leyeron igual, o lo confirmó un revisor con su cita.
    VERIFICADO = "verificado"
    #: Una lectura lo trae literal en una fuente impresa: se cree.
    ENCONTRADO = "encontrado"
    #: Hay candidatos, pero ninguno con la evidencia que exige su fuente.
    REQUIERE_VALIDACION = "requiere validación"
    #: Se buscó y no hay nada que proponer.
    NO_ENCONTRADO = "no encontrado"
    #: Dos valores propios distintos, los dos con evidencia.
    CONTRADICTORIO = "contradictorio"


#: Los estados con los que el valor va al nombre y al índice.
SE_CREE = frozenset({Estado.VERIFICADO, Estado.ENCONTRADO})


@dataclass(frozen=True, slots=True)
class Candidato:
    """Un valor posible que no se pone solo: lo confirma una persona."""

    valor: str
    #: Por qué no se cree: «una sola lectura de letra a mano», «corregido: la
    #: oficina a una cifra», «el de su trámite»…
    motivo: str
    pagina: int | None = None

    def as_dict(self) -> dict:
        return {"valor": self.valor, "motivo": self.motivo, "pagina": self.pagina}


@dataclass(frozen=True, slots=True)
class Hallazgo:
    """Un parámetro de un documento con su evidencia."""

    #: «re», «fecha», «tipo» o «corte».
    parametro: str
    estado: Estado
    #: El valor normalizado que va al nombre, o ``None`` si no se cree ninguno.
    valor: str | None = None
    #: Lo que el lector dejó, tal cual.
    valor_original: str | None = None
    pagina: int | None = None
    #: El trozo de la lectura donde está, para verlo sin abrir el PDF.
    fragmento: str | None = None
    #: De dónde salió: «etiqueta impresa», «PQR de la constancia», «sello de tinta»…
    metodo: str | None = None
    #: Quién lo leyó: «capa», «tesseract», «ocr de pago», «visión».
    lectores: tuple[str, ...] = ()
    #: «alta», «media» o «baja».
    confianza: str | None = None
    candidatos: tuple[Candidato, ...] = ()
    #: Qué se intentó, cuando no se encontró.
    buscado: str | None = None
    #: Lo que dijo el verificador, si bajó el estado.
    motivo: str | None = None

    @property
    def se_cree(self) -> bool:
        return self.estado in SE_CREE

    def as_dict(self) -> dict:
        return {
            "parametro": self.parametro,
            "estado": str(self.estado),
            "valor": self.valor,
            "valor_original": self.valor_original,
            "pagina": self.pagina,
            "fragmento": self.fragmento,
            "metodo": self.metodo,
            "lectores": list(self.lectores),
            "confianza": self.confianza,
            "candidatos": [c.as_dict() for c in self.candidatos],
            "buscado": self.buscado,
            "motivo": self.motivo,
        }


# -- el RE ----------------------------------------------------------------------

#: Un RE entero, como va al nombre.
_RE_ENTERO = re.compile(r"RE\d{13}")
#: Lo que puede ir entre dos cifras de una lectura sin cambiar el valor: el
#: blanco, el punto o el guion que mete el escáner o la letra a mano.
_SEPARADOR = r"[ \t.\-]?"
#: Cuánto texto se guarda alrededor del valor, a cada lado.
ALCANCE_DEL_FRAGMENTO = 30

#: Cada lector, por la familia que lo hace independiente de otro: la relectura
#: y el renglón son Tesseract otra vez; no confirman a Tesseract.
FAMILIA_DEL_LECTOR = {
    "capa": "capa",
    "tesseract": "tesseract",
    "relectura": "tesseract",
    "renglon": "tesseract",
    "ocr de pago": "ocr de pago",
    "vision": "visión",
    "visión": "visión",
}
#: Las fuentes impresas: basta una lectura literal.
FUENTES_IMPRESAS = frozenset(
    {"etiqueta impresa", "sello impreso", "PQR de la constancia", "citado en su texto"}
)
#: Cuántos lectores distintos hacen falta para creer la letra a mano.
LECTORES_PARA_LA_LETRA_A_MANO = 2


def es_re_entero(valor: str | None) -> bool:
    return bool(valor) and _RE_ENTERO.fullmatch(valor.upper()) is not None


def aparece_literal(radicado: str, texto: str | None) -> str | None:
    """El fragmento de ``texto`` donde están las trece cifras del RE seguidas, o ``None``.

    Con a lo sumo un blanco, un punto o un guion entre dos cifras, y sin otra
    cifra pegada delante ni detrás: «RE28102024102908» no trae el
    «2810202410290» que lleva dentro. Ni letras por cifras ni cifras de más.
    """
    if not es_re_entero(radicado) or not texto:
        return None
    cifras = radicado.upper()[2:]
    patron = r"(?<!\d)" + _SEPARADOR.join(cifras) + rf"(?!{_SEPARADOR}\d)"
    hallado = re.search(patron, texto)
    if hallado is None:
        return None
    inicio = max(0, hallado.start() - ALCANCE_DEL_FRAGMENTO)
    fin = min(len(texto), hallado.end() + ALCANCE_DEL_FRAGMENTO)
    return " ".join(texto[inicio:fin].split())


def familia(lector: str) -> str:
    return FAMILIA_DEL_LECTOR.get(lector, lector)


#: Un RE en una lectura, tal cual: «RE», a lo sumo dos signos, y trece cifras
#: con sus separadores; ni una cifra más ni una menos.
_RE_EN_LA_LECTURA = re.compile(r"(?<![A-Z0-9])R\W?E\W{0,2}((?:\d" + _SEPARADOR + r"){12}\d)(?!" + _SEPARADOR + r"\d)")


def res_en_la_lectura(texto: str | None) -> list[str]:
    """Los RE que una lectura trae tal cual, normalizados: «RE 2310 2024 03286» es RE2310202403286."""
    return [
        "RE" + re.sub(r"\D", "", hallado.group(1))
        for hallado in _RE_EN_LA_LECTURA.finditer((texto or "").upper())
    ]


@dataclass(frozen=True, slots=True)
class EvidenciaDeRE:
    """Lo que una hoja propia del documento ofrece como su RE."""

    pagina: int
    #: «etiqueta impresa», «sello impreso», «sello de tinta», «sello al pie»,
    #: «PQR de la constancia», «citado en su texto».
    fuente: str
    #: El valor que propuso quien la leyó, ya con sus correcciones si las hizo.
    propuesto: str | None
    #: Cada lectura cruda: (lector, texto).
    lecturas: tuple[tuple[str, str], ...] = ()
    #: Por qué el valor propuesto se corrigió, si lo dijo quien lo corrigió.
    correccion: str | None = None


@dataclass(frozen=True, slots=True)
class _Visto:
    valor: str
    evidencia: EvidenciaDeRE
    lectores: tuple[str, ...]
    fragmento: str | None
    original: str | None


def _lectores_literales(valor: str, lecturas: Iterable[tuple[str, str]]) -> tuple[tuple[str, ...], str | None, str | None]:
    """Las familias de lectores que traen el valor literal, el primer fragmento y su lectura."""
    familias: list[str] = []
    fragmento = original = None
    for lector, texto in lecturas:
        trozo = aparece_literal(valor, texto)
        if trozo is None:
            continue
        if familia(lector) not in familias:
            familias.append(familia(lector))
        if fragmento is None:
            fragmento, original = trozo, texto
    return tuple(familias), fragmento, original


def decidir_el_re(
    evidencias: Sequence[EvidenciaDeRE],
    *,
    del_tramite: str | None = None,
    valido: Callable[[str, EvidenciaDeRE], str | None] | None = None,
    buscado: str | None = None,
) -> Hallazgo:
    """El RE del documento con su evidencia, o los candidatos que una persona confirma.

    ``evidencias`` van en el orden de sus hojas: manda la primera que se cree.
    ``valido(valor, evidencia)`` devuelve por qué un valor no puede ser un RE de
    verdad -- una oficina que no radica, un año imposible -- o ``None``.
    ``del_tramite`` es el RE de su trámite: si ninguna hoja propia lo prueba,
    es sólo un candidato.
    """
    creidos: list[_Visto] = []
    candidatos: list[Candidato] = []

    def proponer(valor: str, motivo: str, pagina: int | None) -> None:
        if not any(c.valor == valor for c in candidatos):
            candidatos.append(Candidato(valor, motivo, pagina))

    for evidencia in evidencias:
        impresa = evidencia.fuente in FUENTES_IMPRESAS
        valores = [(evidencia.propuesto or "").upper()]
        if not impresa:
            # Del recorte de un sello, también lo que cada lector leyó tal cual,
            # aunque quien lo leyó lo corrigiera o lo rechazara. De la lectura
            # de una carta nunca: cita los RE de otros trámites.
            valores += [v for _, texto in evidencia.lecturas for v in res_en_la_lectura(texto)]
        for propuesto in dict.fromkeys(v for v in valores if es_re_entero(v)):
            lectores, fragmento, original = _lectores_literales(propuesto, evidencia.lecturas)
            basta = 1 if impresa else LECTORES_PARA_LA_LETRA_A_MANO
            por_que_no = valido(propuesto, evidencia) if valido is not None else None
            if por_que_no and propuesto != (evidencia.propuesto or "").upper():
                # Lo que un lector leyó suelto y no puede ser un RE -- el número
                # interno con «RE» delante, «RE2024600387419» -- no es evidencia
                # de nada: ni candidato.
                continue
            if len(lectores) < basta:
                if not lectores:
                    motivo = (
                        f"corregido: {evidencia.correccion}"
                        if evidencia.correccion
                        else "ninguna lectura lo trae tal cual"
                    )
                else:
                    motivo = f"letra a mano leída por un solo lector ({lectores[0]})"
                proponer(propuesto, motivo, evidencia.pagina)
                continue
            if por_que_no:
                proponer(propuesto, por_que_no, evidencia.pagina)
                continue
            creidos.append(_Visto(propuesto, evidencia, lectores, fragmento, original))

    if del_tramite and es_re_entero(del_tramite) and not any(v.valor == del_tramite.upper() for v in creidos):
        proponer(del_tramite.upper(), "el de su trámite: ninguna hoja suya lo trae", None)

    if creidos:
        primero = creidos[0]
        otros = [v for v in creidos[1:] if v.valor != primero.valor]
        for otro in otros:
            proponer(otro.valor, f"otro RE propio, en la pág. {otro.evidencia.pagina}", otro.evidencia.pagina)
        verificado = len(primero.lectores) >= LECTORES_PARA_LA_LETRA_A_MANO
        return Hallazgo(
            parametro="re",
            estado=Estado.VERIFICADO if verificado else Estado.ENCONTRADO,
            valor=primero.valor,
            valor_original=_lo_leido(primero.original, primero.valor),
            pagina=primero.evidencia.pagina,
            fragmento=primero.fragmento,
            metodo=primero.evidencia.fuente,
            lectores=primero.lectores,
            confianza="alta" if verificado or primero.evidencia.fuente in FUENTES_IMPRESAS else "media",
            candidatos=tuple(c for c in candidatos if c.valor != primero.valor),
        )
    if candidatos:
        return Hallazgo(
            parametro="re",
            estado=Estado.REQUIERE_VALIDACION,
            metodo="candidatos",
            confianza="baja",
            candidatos=tuple(candidatos),
            buscado=buscado,
        )
    return Hallazgo(parametro="re", estado=Estado.NO_ENCONTRADO, buscado=buscado)


def _lo_leido(texto: str | None, valor: str) -> str | None:
    """Lo que el lector escribió para ese valor, con sus blancos: «RE 2310 2024 03286»."""
    if not texto:
        return None
    cifras = valor.upper()[2:]
    hallado = re.search(r"(?:R\W?E\W{0,2})?" + _SEPARADOR.join(cifras), texto, re.IGNORECASE)
    return hallado.group(0) if hallado else None


def candidatos_legibles(hallazgo: Hallazgo) -> str:
    """Los candidatos dichos para el aviso de Revisión: «RE… (el de su trámite); RE… (…)»."""
    return "; ".join(f"{c.valor} ({c.motivo})" for c in hallazgo.candidatos)


@dataclass(slots=True)
class Evidencias:
    """Los hallazgos de un trabajo, por documento (su primera hoja)."""

    por_documento: dict[int, list[Hallazgo]] = field(default_factory=dict)

    def anotar(self, primera: int, hallazgo: Hallazgo) -> None:
        self.por_documento.setdefault(primera, [])
        self.por_documento[primera] = [
            h for h in self.por_documento[primera] if h.parametro != hallazgo.parametro
        ] + [hallazgo]

    def as_dict(self) -> dict[str, list[dict]]:
        return {str(p): [h.as_dict() for h in hs] for p, hs in sorted(self.por_documento.items())}
