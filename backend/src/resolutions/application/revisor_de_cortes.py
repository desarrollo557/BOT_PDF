"""El revisor de cortes: cada PDF que sale, comprobado costura por costura.

Lo pidió el operador el 2026-11-05 ante la caja 1004569 de MAGANGUE (ver
``domain/revision_de_cortes.py``): un agente que «verifique y rectifique todo sin
importar la habilidad, haciendo valer que se cumpla cada patrón y con un margen
de error», y que lo que se salga del margen «se lo envíe a la IA, la IA lo
analice y decida», «consumiendo pocos tokens». Va al final del corte de cada
habilidad, cuando los documentos ya están decididos y antes de nombrarlos, y
cada costura sale por una de tres puertas:

1. **Dentro del margen**: validada. No cuesta nada, y es casi todo.
2. **Error seguro** -- dos pruebas fuertes del papel que apuntan a lo mismo --:
   se corrige sin preguntar a nadie, también con «Solo OCR».
3. **Fuera del margen**: la decide la IA, si el operador eligió una lectura con
   ella, con **una sola pregunta por PDF** que lleva todas sus costuras dudosas y
   la huella de las hojas de alrededor. Sin IA, o si la IA no contesta o no cita
   el papel, va a revisión.

Lo que una regla del operador decidió no lo deshace nadie: la hoja **fija** --
el sello que abre, la etiqueta de LECTA, la guía -- no se mueve, y la costura
que el papel contradice pero una regla puso así va a revisión, no a la IA. Cada
habilidad dice cuáles son las suyas en sus ``Patrones``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace

from ..domain.grouping import GroupingResult, PageGroup
from ..domain.revision_de_cortes import (
    Costura,
    Decision,
    huella_para_la_ia,
    revisar_costuras,
)
from .ports import JuezDeCosturas

logger = logging.getLogger(__name__)

#: Una hoja con menos palabras que éstas no le dice nada a la IA: si cae en la
#: ventana de una costura dudosa y la habilidad sabe releerla con el OCR de
#: pago, se relee -- una página, sólo ésa --.
PALABRAS_PARA_JUZGAR = 12
#: Cuántas costuras dudosas van en una pregunta. Con su ventana de cuatro hojas,
#: unos 4 000 tokens de entrada como mucho: la pregunta no crece con la caja.
COSTURAS_POR_PREGUNTA = 8
#: Cuántas preguntas se le hacen como mucho a la IA por caja. Una caja con más
#: de 48 costuras dudosas no está para que la arregle la IA: está mal leída o es
#: de otra clase, y va a revisión.
PREGUNTAS_POR_CAJA = 6


@dataclass(frozen=True, slots=True)
class Patrones:
    """Lo que una habilidad le dice al revisor de su papel."""

    #: Las hojas que abren documento por una regla del operador.
    abren: frozenset[int] = frozenset()
    #: Las que por regla van lejos de su documento: la Habeas Data con su acuerdo.
    cruces: frozenset[int] = frozenset()
    #: Las que ninguna corrección mueve.
    fijas: frozenset[int] = frozenset()
    #: Diplomas, actas de grado, historias: una persona por PDF.
    una_persona_por_pdf: bool = False
    #: Las reglas de la habilidad, dichas a la IA en pocas líneas.
    reglas: str = ""
    #: Qué clase de soporte es una hoja -- «documento de identidad», «factura»
    #: --, para que la IA la vea por lo que es y no lea su basura.
    clase: Callable[[str], str | None] | None = None
    #: Si la habilidad sabe nombrar un documento que nace de partir otro. Si no,
    #: la costura que pide partir va a revisión.
    puede_partir: bool = True
    #: Si la habilidad sabe nombrar y fechar sus documentos después de que el
    #: revisor mueva hojas. Las que no -- diplomas, actas de grado, resoluciones,
    #: cuyas filas del FUID salen de leer cada documento -- reciben lo que el
    #: revisor corregiría como revisión, y a la IA no se le pregunta: no se
    #: gasta en una decisión que no se va a aplicar.
    puede_mover: bool = True


@dataclass(frozen=True, slots=True)
class Movimiento:
    """Una corrección: qué hojas se movieron, de dónde a dónde y por qué."""

    paginas: tuple[int, ...]
    desde: tuple[int, ...]
    #: Las hojas del documento al que fueron, como estaba antes; ``None`` si
    #: abrieron el suyo.
    hacia: tuple[int, ...] | None
    por: str
    motivo: str

    def texto(self) -> str:
        bloque = _rango(self.paginas)
        destino = f"con las hojas {_rango(self.hacia)}" if self.hacia else "en su propio documento"
        return f"hojas {bloque}: de las hojas {_rango(self.desde)} {destino} ({self.por}: {self.motivo})"

    def as_dict(self) -> dict[str, object]:
        return {
            "paginas": list(self.paginas),
            "desde": list(self.desde),
            "hacia": list(self.hacia) if self.hacia else None,
            "por": self.por,
            "motivo": self.motivo,
        }


@dataclass(frozen=True, slots=True)
class RevisionDeCortes:
    grupos: GroupingResult
    anexos: dict[str, list[int]]
    movimientos: tuple[Movimiento, ...] = ()
    #: (hoja, motivo) de lo que se queda como estaba y alguien tiene que mirar.
    en_revision: tuple[tuple[int, str], ...] = ()
    costuras: int = 0
    dentro_del_margen: int = 0
    #: Costuras que la IA miró y en que le dio la razón al bot.
    confirmadas_por_la_ia: int = 0
    #: Costuras que se le preguntaron a la IA.
    preguntadas: int = 0
    ia_no_respondio: bool = False
    #: Las páginas que se releyeron con el OCR de pago para que la IA las viera.
    releidas: tuple[int, ...] = field(default=())

    @property
    def estado(self) -> str:
        if self.movimientos:
            return "corregido"
        if self.en_revision:
            return "en revisión"
        return "validado"

    def resumen(self) -> str:
        partes = [f"{self.costuras} costuras, {self.dentro_del_margen} dentro del margen"]
        if self.movimientos:
            partes.append(f"{len(self.movimientos)} corregidas")
        if self.confirmadas_por_la_ia:
            partes.append(f"{self.confirmadas_por_la_ia} confirmadas por la IA")
        if self.en_revision:
            partes.append(f"{len(self.en_revision)} a revisión")
        if self.ia_no_respondio:
            partes.append("la IA no respondió")
        return f"Revisor de cortes: {self.estado} ({'; '.join(partes)})"

    def documentos(self) -> list[dict[str, object]]:
        """El estado de cada PDF que sale."""
        tocadas = {p for m in self.movimientos for p in (*m.paginas, *m.desde, *(m.hacia or ()))}
        dudosas = {p for p, _ in self.en_revision}
        salida = []
        for grupo in self.grupos.groups:
            paginas = set(grupo.page_numbers)
            estado = "corregido" if paginas & tocadas else "en revisión" if paginas & dudosas else "validado"
            salida.append({"paginas": list(grupo.page_numbers), "estado": estado})
        return salida

    def as_dict(self) -> dict[str, object]:
        return {
            "estado": self.estado,
            "resumen": self.resumen(),
            "costuras": self.costuras,
            "dentro_del_margen": self.dentro_del_margen,
            "preguntadas_a_la_ia": self.preguntadas,
            "confirmadas_por_la_ia": self.confirmadas_por_la_ia,
            "ia_no_respondio": self.ia_no_respondio,
            "releidas": list(self.releidas),
            "movimientos": [m.as_dict() for m in self.movimientos],
            "en_revision": [{"page": p, "reason": motivo} for p, motivo in self.en_revision],
            "documentos": self.documentos(),
        }


def revisar_los_cortes(
    grupos: GroupingResult,
    textos: Mapping[int, str],
    patrones: Patrones,
    *,
    juez: JuezDeCosturas | None = None,
    anexos: Mapping[str, list[int]] | None = None,
    releer: Callable[[int], str | None] | None = None,
) -> RevisionDeCortes:
    """Valida, corrige o manda a revisión cada costura de lo que se va a entregar."""
    anexos = {codigo: list(paginas) for codigo, paginas in (anexos or {}).items()}
    documentos = [list(g.page_numbers) for g in grupos.groups]
    costuras = revisar_costuras(
        documentos,
        textos,
        abren=patrones.abren,
        cruces=patrones.cruces,
        una_persona_por_pdf=patrones.una_persona_por_pdf,
    )
    fuera = [c for c in costuras if c.fuera_del_margen]
    en_revision: list[tuple[int, str]] = []
    decididas: list[tuple[Costura, str, str]] = []
    preguntar: list[Costura] = []
    for costura in fuera:
        if costura.contra_una_regla or costura.propuesta is None:
            en_revision.append(
                (costura.derecha, f"el papel contradice una regla, que manda: {costura.motivo}")
            )
        elif any(p in patrones.fijas for p in costura.propuesta.paginas):
            en_revision.append((costura.derecha, f"fuera del margen, pero la hoja es fija por una regla: {costura.motivo}"))
        elif not patrones.puede_mover or (costura.propuesta.hacia is None and not patrones.puede_partir):
            en_revision.append((costura.derecha, f"fuera del margen de error, para mirar: {costura.motivo}"))
        elif costura.error_seguro:
            decididas.append((costura, "dos pruebas del papel", costura.motivo))
        else:
            preguntar.append(costura)

    confirmadas = 0
    ia_no_respondio = False
    releidas: list[int] = []
    if preguntar and juez is None:
        en_revision.extend(
            (c.derecha, f"fuera del margen de error ({c.motivo}); con «OCR + IA» la decidiría la IA")
            for c in preguntar
        )
    elif preguntar:
        todas = {p for paginas in documentos for p in paginas}
        clase = patrones.clase or (lambda _texto: None)
        vistas: dict[int, str] = {}
        tope = COSTURAS_POR_PREGUNTA * PREGUNTAS_POR_CAJA
        for costura in preguntar[tope:]:
            # Una caja con más dudas que esto no se pregunta entera: a revisión.
            en_revision.append((costura.derecha, f"fuera del margen de error ({costura.motivo}); demasiadas dudas en la caja para preguntarlas todas"))
        for desde in range(0, min(len(preguntar), tope), COSTURAS_POR_PREGUNTA):
            tanda = preguntar[desde : desde + COSTURAS_POR_PREGUNTA]
            ventana = sorted(
                {q for c in tanda for q in (c.izquierda - 1, c.izquierda, c.derecha, c.derecha + 1) if q in todas}
            )
            for q in ventana:
                if q in vistas:
                    continue
                vistas[q] = textos.get(q, "") or ""
                if releer is not None and clase(vistas[q]) is None and _palabras(vistas[q]) < PALABRAS_PARA_JUZGAR:
                    try:
                        nuevo = releer(q)
                    except Exception:  # noqa: BLE001 - sin relectura, la IA ve lo que había
                        nuevo = None
                    if nuevo and _palabras(nuevo) > _palabras(vistas[q]):
                        vistas[q] = nuevo
                        releidas.append(q)
            huellas = [huella_para_la_ia(q, vistas[q], clase(vistas[q])) for q in ventana]
            respuesta = _preguntar(juez, huellas, tanda, patrones.reglas)
            # La costura que la IA dejó sin contestar se le pregunta otra vez,
            # sola: medido con 1004569, la misma pregunta volvió una vez con la
            # lista vacía y la siguiente con el veredicto y su cita.
            faltan = [c for c in tanda if respuesta is not None and (c.izquierda, c.derecha) not in respuesta]
            if faltan:
                otra = _preguntar(juez, huellas, faltan, patrones.reglas)
                respuesta.update(otra or {})
            if respuesta is None:
                ia_no_respondio = True
                en_revision.extend(
                    (c.derecha, f"fuera del margen de error ({c.motivo}) y la IA no respondió") for c in tanda
                )
                continue
            for costura in tanda:
                veredicto = respuesta.get((costura.izquierda, costura.derecha))
                corrige = "continua" if costura.decision is Decision.CORTE else "abre"
                confirma = "abre" if costura.decision is Decision.CORTE else "continua"
                if veredicto and veredicto.decision == corrige and veredicto.cita.strip():
                    decididas.append((costura, "la IA", f"«{veredicto.cita.strip()[:160]}»; {costura.motivo}"))
                elif veredicto and veredicto.decision == confirma:
                    confirmadas += 1
                else:
                    en_revision.append(
                        (costura.derecha, f"fuera del margen de error ({costura.motivo}) y la IA no lo pudo decidir")
                    )

    salida, anexos_salida, movimientos = _aplicar(
        grupos, {codigo: list(paginas) for codigo, paginas in anexos.items()}, decididas
    )
    # Ninguna corrección pierde ni repite una hoja: si lo que sale no tiene
    # exactamente las mismas hojas que lo que entró, se descarta entera y la
    # caja sale como la cortaron las reglas.
    antes = sorted(p for g in grupos.groups for p in g.page_numbers)
    despues = sorted(p for g in salida.groups for p in g.page_numbers)
    if despues != antes:
        logger.error("el revisor de cortes iba a perder o repetir hojas; se descarta su corrección")
        en_revision.extend(
            (m.paginas[0], f"no se corrigió: la corrección perdía o repetía hojas ({m.motivo})") for m in movimientos
        )
        salida, anexos_salida, movimientos = grupos, anexos, []
    anexos = anexos_salida
    return RevisionDeCortes(
        grupos=salida,
        anexos=anexos,
        movimientos=tuple(movimientos),
        en_revision=tuple(en_revision),
        costuras=len(costuras),
        dentro_del_margen=len(costuras) - len(fuera),
        confirmadas_por_la_ia=confirmadas,
        preguntadas=len(preguntar),
        ia_no_respondio=ia_no_respondio,
        releidas=tuple(releidas),
    )


def _preguntar(juez: JuezDeCosturas, huellas, costuras: list[Costura], reglas: str):
    """Una pregunta al juez; si revienta, es que no respondió."""
    try:
        respuesta = juez.decidir(huellas, [(c.izquierda, c.derecha) for c in costuras], reglas)
    except Exception:  # noqa: BLE001 - un juez roto es un juez que no respondió
        logger.warning("el juez del revisor de cortes falló; sus costuras van a revisión", exc_info=True)
        return None
    return dict(respuesta) if respuesta is not None else None


def revisar_sin_romper(
    grupos: GroupingResult,
    textos: Mapping[int, str],
    patrones: Patrones,
    **opciones,
) -> tuple[RevisionDeCortes | None, str | None]:
    """El revisor, que nunca tumba la caja: si falla, la caja sale como la cortaron las reglas.

    Devuelve la revisión, o ``None`` y el aviso que lo dice.
    """
    try:
        return revisar_los_cortes(grupos, textos, patrones, **opciones), None
    except Exception as error:  # noqa: BLE001 - un fallo del revisor no es un fallo de la caja
        logger.exception("el revisor de cortes falló; la caja sale como la cortaron las reglas")
        return None, (
            f"El revisor de cortes no pudo revisar esta caja ({type(error).__name__}); "
            "sale como la cortaron las reglas"
        )


def anotar_en_el_informe(
    informe: dict,
    revision: RevisionDeCortes | None,
    aviso: str | None,
    comprobacion: Mapping[str, object] | None,
) -> None:
    """Lo que el revisor y la comprobación del disco dejan en el informe de cualquier habilidad.

    La cola de revisión recibe lo que hay que mirar; ``notices``, el resumen si
    algo no salió validado; y dos claves con el detalle: ``revision_de_cortes``
    y ``comprobacion_de_la_entrega``.
    """
    cola = informe.setdefault("review_queue", [])
    avisos = informe.setdefault("notices", [])
    if revision is not None:
        cola.extend({"page": p, "reason": f"revisor de cortes: {motivo}"} for p, motivo in revision.en_revision)
        if revision.estado != "validado":
            avisos.append(revision.resumen())
            avisos.extend(f"Corregido: {m.texto()}" for m in revision.movimientos)
        informe["revision_de_cortes"] = revision.as_dict()
    elif aviso:
        avisos.append(aviso)
        informe["revision_de_cortes"] = {"estado": "no corrió", "resumen": aviso}
    if comprobacion:
        problemas = list(comprobacion.get("problemas") or [])
        cola.extend(
            {"page": p.get("pagina") or 1, "reason": f"comprobación de la entrega: {p['texto']}"} for p in problemas
        )
        if problemas:
            avisos.append(str(comprobacion.get("resumen")))
        informe["comprobacion_de_la_entrega"] = dict(comprobacion)


def _aplicar(
    grupos: GroupingResult,
    anexos: dict[str, list[int]],
    decididas: list[tuple[Costura, str, str]],
) -> tuple[GroupingResult, dict[str, list[int]], list[Movimiento]]:
    """Mueve los bloques decididos, en el orden del papel, sobre lo que haya quedado."""
    if not decididas:
        return grupos, anexos, []
    from .anexos_declarados import _renumerar

    entradas: list[tuple[PageGroup | None, list[int], PageGroup]] = [
        (grupo, list(grupo.page_numbers), grupo) for grupo in grupos.groups
    ]

    def donde(pagina: int) -> int | None:
        return next((i for i, (_, paginas, _) in enumerate(entradas) if pagina in paginas), None)

    movimientos: list[Movimiento] = []
    for costura, por, motivo in sorted(decididas, key=lambda d: d[0].derecha):
        propuesta = costura.propuesta
        assert propuesta is not None
        origen = donde(costura.derecha)
        if origen is None:
            continue
        bloque = [p for p in propuesta.paginas if p in entradas[origen][1]]
        if not bloque or len(bloque) == len(entradas[origen][1]) and propuesta.hacia is None:
            continue
        desde = tuple(entradas[origen][1])
        if propuesta.hacia is not None:
            destino = donde(propuesta.hacia)
            if destino is None or destino == origen:
                continue
            hacia: tuple[int, ...] | None = tuple(entradas[destino][1])
            entradas[destino][1].extend(bloque)
            entradas[destino][1].sort()
        else:
            hacia = None
            base = entradas[origen][2]
            nuevo = PageGroup(code=base.code, page_numbers=[], title=None, kind=None, fecha=None)
            entradas.insert(origen + 1, (None, list(bloque), nuevo))
        for pagina in bloque:
            entradas[origen][1].remove(pagina)
        codigo = entradas[origen][2].code.value
        if codigo in anexos:
            anexos[codigo] = [p for p in anexos[codigo] if p not in bloque]
        movimientos.append(Movimiento(tuple(bloque), desde, hacia, por, motivo))

    nuevos = [
        replace(base, page_numbers=sorted(paginas))
        for _grupo, paginas, base in entradas
        if paginas
    ]
    anexos = {codigo: paginas for codigo, paginas in anexos.items() if paginas}
    renumerados, anexos = _renumerar(nuevos, anexos)
    return (
        GroupingResult(groups=renumerados, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs)),
        anexos,
        movimientos,
    )


def _palabras(texto: str) -> int:
    return len(re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", texto or ""))


def _rango(paginas) -> str:
    paginas = sorted(paginas or ())
    if not paginas:
        return ""
    if paginas == list(range(paginas[0], paginas[-1] + 1)):
        return str(paginas[0]) if len(paginas) == 1 else f"{paginas[0]}-{paginas[-1]}"
    return ", ".join(map(str, paginas))
