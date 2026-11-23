"""El agente que decide el RE que la evidencia no dejó creer, y el auditor que lo revisa (2026-11-23).

El operador, ante 48 avisos de Revisión de la corrida de Magangué: «si son 1000
PDF, yo no voy a darle en confirmar a todos esos… necesito que se corrijan
solos, y se haga una auditoría sobre auditoría… el bot haga absolutamente
todo». Y decidió: sin certeza, el bot elige el más probable y lo deja anotado
«decidido por el agente, confianza baja» para auditarlo por muestreo.

``resolver_sin_certeza`` decide entre los candidatos que dejó ``decidir_el_re``
-- nunca un valor que nadie leyó --, de la regla más segura a la menos:

1. la oficina que el sello trae impresa («OFICINA SANTA ANA» → 8673);
2. la oficina corregida en la que convergen las lecturas (6835194: «RE2673…»,
   «RE4673…» → RE8673202100532);
3. el que se lee igual en otra hoja de la caja (4251546: la respuesta lee
   RE2311202101144);
4. el de su trámite, para la notificación y la constancia;
5. el único candidato, leído tal cual (7741429: la oficina 9230);
6. el más votado, o el primero que leyó el OCR de pago.

``auditar_la_decision`` es independiente: un RE de trece cifras, de un año
posible para la hoja, de una oficina que radica o leído tal cual, y que no es
el de otro trámite de la caja. Lo que no sostiene se revierte: el nombre va sin
RE y queda anotado por qué.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from .evidencia import Candidato, es_re_entero

#: La corrección de la oficina que propone el agente: «…: sería RE8673202100532».
_SERIA = re.compile(r"sería (RE\d{13})")
MEDIA, BAJA = "media", "baja"
VERIFICADA = "verificada por el auditor"

#: El nombre que el sello de tinta trae impreso, «OFICINA SANTA ANA / BOLIVAR
#: SUR», y su oficina. Lo leído en el sello de 6835194 (2026-11-23); se suman
#: las que la caja enseña con un RE que se cree (``oficinas_por_su_nombre``).
OFICINAS_POR_SU_NOMBRE: dict[str, str] = {"SANTA ANA": "8673"}
#: El rótulo, al principio de su renglón y en mayúsculas como va impreso:
#: «OFICINA SANTA ANA». No la prosa: «en la oficina de Santa Ana…».
_NOMBRE_DE_LA_OFICINA = re.compile(r"(?m)^\W*OFICINA\s+([A-ZÑ]+(?:[ \t]+[A-ZÑ]+)?)")


def nombre_de_la_oficina(texto: str) -> str | None:
    """El nombre de la oficina que trae impreso el sello: «SANTA ANA», «MAGANGUE»; ``None`` si no lo trae."""
    import unicodedata

    plano = "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c))
    for hallado in _NOMBRE_DE_LA_OFICINA.finditer(plano):
        nombre = hallado.group(1).strip()
        for conocido in OFICINAS_POR_SU_NOMBRE:
            if nombre == conocido or nombre.startswith(conocido + " "):
                return OFICINAS_POR_SU_NOMBRE[conocido]
    return None


@dataclass(frozen=True, slots=True)
class ContextoDelRe:
    """Lo que la caja sabe para decidir el RE de un documento."""

    #: Las hojas del documento.
    paginas: frozenset[int] = frozenset()
    #: Cada RE que algún lector leyó tal cual en la caja, con sus hojas.
    leidos: Mapping[str, frozenset[int]] = field(default_factory=dict)
    #: Los RE que la caja trae impresos.
    impresos: frozenset[str] = frozenset()
    oficinas_que_radican: frozenset[str] = frozenset()
    #: La oficina del nombre que el sello del documento trae impreso.
    oficina_del_sello: str | None = None
    #: El RE de su trámite, y si el documento lo lleva por lo que es.
    del_tramite: str | None = None
    lleva_el_del_tramite: bool = False
    #: El año de la hoja -- el del sello si lo tiene --.
    anio: int | None = None
    #: Los RE de los demás trámites de la caja.
    de_otros_tramites: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Decision:
    valor: str
    regla: str
    confianza: str
    por_que: str


def _destino(candidato: Candidato) -> str:
    """A qué RE apunta un candidato: su corrección, si la tiene, o él mismo."""
    corregido = _SERIA.search(candidato.motivo or "")
    return corregido.group(1) if corregido else candidato.valor


#: El candidato que es la corrección de lo leído: «leído RE2673…: oficina…».
_LEIDO = re.compile(r"leído (RE\d{13}):")
#: Lo que nunca decide el agente: lo que el reclamo sólo cita (2026-11-18).
_LO_QUE_EL_RECLAMO_CITA = "el reclamo cita RE de otras reclamaciones"
#: Y el RE de su trámite, salvo para lo que lo lleva por ser de él.
_EL_DE_SU_TRAMITE = "el de su trámite"


def _votos(candidatos: Sequence[Candidato], radican: frozenset[str]) -> Counter:
    """Cuántas lecturas distintas apuntan a cada RE: lo leído y su corrección son una sola."""
    lecturas: dict[str, set[str]] = {}
    for candidato in candidatos:
        destino = _destino(candidato)
        if es_re_entero(destino) and (not radican or destino[2:6] in radican):
            leido = _LEIDO.search(candidato.motivo or "")
            lecturas.setdefault(destino, set()).add(leido.group(1) if leido else candidato.valor)
    return Counter({destino: len(origenes) for destino, origenes in lecturas.items()})


def _leido(candidatos: Sequence[Candidato]) -> str:
    return ", ".join(dict.fromkeys(c.valor for c in candidatos))


def resolver_sin_certeza(candidatos: Sequence[Candidato], contexto: ContextoDelRe) -> Decision | None:
    """El RE más probable entre los candidatos de un documento, con la regla que lo eligió; ``None`` si no hay nada."""
    validos = [
        c
        for c in candidatos
        if es_re_entero(c.valor)
        and _LO_QUE_EL_RECLAMO_CITA not in (c.motivo or "")
        and (contexto.lleva_el_del_tramite or not (c.motivo or "").startswith(_EL_DE_SU_TRAMITE))
    ]
    destinos = list(dict.fromkeys(_destino(c) for c in validos if es_re_entero(_destino(c))))
    votos = _votos(validos, contexto.oficinas_que_radican)
    leido = _leido(validos)

    # 1. La oficina que el sello trae impresa.
    if contexto.oficina_del_sello and contexto.oficina_del_sello.isdigit():
        con_ella = [d for d in destinos if d[2:6] == contexto.oficina_del_sello]
        if con_ella:
            elegido = max(con_ella, key=lambda d: (votos.get(d, 0), -destinos.index(d)))
            return Decision(
                elegido,
                "la oficina que el sello trae impresa",
                MEDIA,
                f"el sello trae impresa la oficina {contexto.oficina_del_sello}; leído {leido}",
            )
    # 2. La oficina corregida en la que convergen las lecturas.
    if votos:
        (primero, n), *resto = votos.most_common()
        segundo = resto[0][1] if resto else 0
        if n >= 2 and n > segundo:
            return Decision(
                primero,
                "las lecturas convergen al corregir la letra a mano",
                MEDIA,
                f"{n} de {sum(votos.values())} lecturas dan {primero}; leído {leido}",
            )
    # 3. El que se lee igual en otra hoja de la caja.
    fuera = [
        d
        for d in destinos
        if (contexto.leidos.get(d, frozenset()) - contexto.paginas) or d in contexto.impresos
    ]
    if len(fuera) == 1:
        hojas = sorted(contexto.leidos.get(fuera[0], frozenset()) - contexto.paginas)
        donde = f"en la pág. {', '.join(map(str, hojas))}" if hojas else "impreso en la caja"
        return Decision(fuera[0], "se lee igual en otra hoja de la caja", MEDIA, f"{fuera[0]} se lee {donde}; leído {leido}")
    # 4. El de su trámite, para lo que lo lleva por ser de él.
    tramite = (contexto.del_tramite or "").upper()
    if es_re_entero(tramite) and contexto.lleva_el_del_tramite and (not destinos or tramite in destinos):
        return Decision(tramite, "el RE de su trámite", MEDIA, f"es de su trámite {tramite} y su hoja no trae otro")
    # 5. El único candidato, leído tal cual.
    if len(destinos) == 1:
        return Decision(destinos[0], "el único candidato", BAJA, f"lo único leído: {leido}")
    # 6. El más votado; si empatan, el primero que se leyó.
    if votos:
        primero = votos.most_common(1)[0][0]
        return Decision(primero, "el más votado entre lecturas que no coinciden", BAJA, f"leído {leido}")
    if destinos:
        return Decision(destinos[0], "el primero leído entre lecturas que no coinciden", BAJA, f"leído {leido}")
    return None


def auditar_la_decision(decision: Decision, contexto: ContextoDelRe, *, hoy: date | None = None) -> str | None:
    """Por qué el auditor no sostiene la decision del agente, o ``None`` si la sostiene."""
    valor = decision.valor.upper()
    if not es_re_entero(valor):
        return f"{valor} no es un RE de trece cifras"
    anio = int(valor[6:10])
    hoy = hoy or date.today()
    if not 1990 <= anio <= hoy.year:
        return f"el año {anio} de {valor} es imposible"
    if contexto.anio and not (contexto.anio - 1 <= anio <= contexto.anio) and valor not in contexto.impresos:
        return f"el año {anio} de {valor} no es el de la hoja ({contexto.anio})"
    if (
        contexto.oficinas_que_radican
        and valor[2:6] not in contexto.oficinas_que_radican
        and not contexto.leidos.get(valor)
        and decision.regla != "el único candidato"
    ):
        return f"la oficina {valor[2:6]} no radica y nadie la leyó así"
    if valor in contexto.de_otros_tramites and valor != (contexto.del_tramite or "").upper():
        return f"{valor} es el RE de otro trámite de la caja"
    return None


# -- el cierre de la Revisión: cada aviso con lo que hizo el agente ---------------
#
# El operador eligió (2026-11-23) que los avisos informativos los verifique el
# agente y los cierre solo, con su conclusión en el Excel. Ningún aviso queda
# esperando un «Confirmar»: cada uno lleva lo que se hizo y por qué.

DECIDIDO, CERRADO, REVERTIDO = "decidido por el agente", "cerrado por el agente", "revertido por el auditor"
_DEL_RE = re.compile(
    r"^RE por confirmar|RE escrito a mano|el RE leído a mano|sin su RE|sin RE\b|sello de radicación al pie"
    r"|RE a mano|\bRE del sello",
    re.IGNORECASE,
)
_UNA_CIFRA = re.compile(r"el radicado (RE\d{13}) se diferencia en una cifra del (RE\d{13})")
_FOLIOS = re.compile(r"^folios del sello", re.IGNORECASE)
_ANEXOS = re.compile(r"anexo", re.IGNORECASE)
_SIN_FECHA = re.compile(r"fecha del documento no se pudo leer|va sin fecha", re.IGNORECASE)
_REVISOR_DE_FECHAS = re.compile(r"^revisor de fechas", re.IGNORECASE)
_COSTURA = re.compile(r"no hay evidencia de si esta hoja abre", re.IGNORECASE)


def lo_que_hizo_el_agente(
    razon: str, decision: Mapping | None = None, *, impresos: frozenset[str] = frozenset()
) -> dict:
    """Lo que el agente hizo con un aviso de la Revisión: ``{"accion", "conclusion"}``."""
    razon = razon or ""
    if _DEL_RE.search(razon):
        if decision and decision.get("valor"):
            return {
                "accion": DECIDIDO,
                "conclusion": (
                    f"puso {decision['valor']} ({decision['regla']}, confianza {decision['confianza']}; "
                    f"{decision['auditor']}): {decision['por_que']}"
                ),
            }
        if decision:
            return {
                "accion": REVERTIDO,
                "conclusion": f"propuso {decision.get('propuesto')} y el auditor {decision['auditor']}: el nombre va sin RE",
            }
        return {
            "accion": CERRADO,
            "conclusion": "sin RE: se buscó en el sello, en toda la hoja y en la caja, y el papel no deja leer ninguno",
        }
    if hallado := _UNA_CIFRA.search(razon):
        uno, otro = hallado.groups()
        if uno in impresos and otro in impresos:
            return {"accion": CERRADO, "conclusion": f"{uno} y {otro} están impresos tal cual: son dos trámites distintos"}
        return {"accion": CERRADO, "conclusion": f"se conserva {uno} tal como se leyó; {otro} es otro trámite de la caja"}
    if _FOLIOS.search(razon):
        return {"accion": CERRADO, "conclusion": "informativo: los folios que declara el sello no están todos en este PDF"}
    if _REVISOR_DE_FECHAS.search(razon):
        return {"accion": CERRADO, "conclusion": "se conserva la fecha tomada del sello o de la hoja principal"}
    if _SIN_FECHA.search(razon):
        return {
            "accion": CERRADO,
            "conclusion": "sin fecha: se leyó con la capa, Tesseract, el OCR de pago y la visión, y el papel no la trae",
        }
    if _COSTURA.search(razon):
        return {"accion": CERRADO, "conclusion": "se dejó unida al documento de delante: ante la duda, se une"}
    if _ANEXOS.search(razon):
        return {"accion": CERRADO, "conclusion": "informativo: el escrito enumera un anexo que no viene en este PDF"}
    return {"accion": CERRADO, "conclusion": "revisado por el agente: se conserva lo hecho"}


def cerrar_la_revision(
    avisos: Sequence[dict], decisiones: Sequence[Mapping], *, impresos: frozenset[str] = frozenset()
) -> list[dict]:
    """Cada aviso de la Revisión con ``resuelto``: lo que hizo el agente. Ninguno queda por confirmar."""
    por_hoja: dict[int, Mapping] = {}
    for decision in decisiones:
        for hoja in decision.get("paginas") or [decision.get("page")]:
            if hoja is not None:
                por_hoja[int(hoja)] = decision
    return [
        {
            **aviso,
            "resuelto": lo_que_hizo_el_agente(
                str(aviso.get("reason") or ""), por_hoja.get(int(aviso.get("page") or 0)), impresos=impresos
            ),
        }
        for aviso in avisos
    ]


def avisos_pendientes(avisos: Sequence[Mapping] | None) -> list[Mapping]:
    """Los avisos de la Revisión que el agente no resolvió: lo único que espera a una persona.

    El mismo criterio que ``pendientes`` de la pantalla (``web/src/lib/pendientes.ts``):
    el libro mayor, el Excel de procesos y las métricas cuentan éstos.
    """
    return [a for a in avisos or [] if isinstance(a, Mapping) and not isinstance(a.get("resuelto"), Mapping)]
