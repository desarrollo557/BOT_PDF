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
import threading
from collections import deque
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


#: Las reglas de la caja de correspondencia, dichas a la IA del revisor de
#: cortes en pocas líneas: son las que el operador dictó y mandan sobre lo que
#: la IA crea ver en el papel.
REGLAS_DE_LA_CORRESPONDENCIA = (
    "Caja de correspondencia de Afinia (expediente de un suscriptor). "
    "Cada sello de radicación nuevo abre documento; la carta del cliente con fecha y asunto también. "
    "La constancia de reclamación y la notificación personal van solas, sólo con un anexo evidente detrás "
    "(cédula, factura). La cédula y la factura van con la hoja de delante. "
    "El acuerdo de pago es un documento: reconocimiento de deuda, pagarés, cartas de instrucciones, cédulas "
    "y la Ley Habeas Data, aunque haya otros papeles en medio. "
    "El contrato de transacción va completo, con sus cláusulas y sus firmas. "
    "Cada acta de suspensión es su documento."
)


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
    #: revisor corregiría como revisión. Con «OCR + IA» la IA decide igual lo que
    #: sale del margen: lo que desmiente deja de ir a revisión, y lo que confirma
    #: va con su cita (2026-11-05, el agente igual en todas las habilidades).
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
    #: La costura que lo decidió: (izquierda, derecha).
    costura: tuple[int, int] | None = None

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
            "costura": list(self.costura) if self.costura else None,
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
    #: Las costuras que salieron del margen, con lo que se hizo de cada una:
    #: «corregida», «confirmada» (la IA le dio la razón al bot) o «revision».
    #: Sólo ésas: las demás están dentro del margen y se deducen de los
    #: documentos, así el informe no crece con la caja.
    fuera: tuple[dict[str, object], ...] = ()

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
            "fuera_del_margen": [dict(costura) for costura in self.fuera],
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

    def se_aplica(costura: Costura) -> bool:
        """Si la habilidad sabe nombrar lo que quedaría al corregir esta costura."""
        propuesta = costura.propuesta
        return patrones.puede_mover and not (
            propuesta is not None and propuesta.hacia is None and not patrones.puede_partir
        )

    for costura in fuera:
        if costura.contra_una_regla or costura.propuesta is None:
            en_revision.append(
                (costura.derecha, f"el papel contradice una regla, que manda: {costura.motivo}")
            )
        elif any(p in patrones.fijas for p in costura.propuesta.paginas):
            en_revision.append((costura.derecha, f"fuera del margen, pero la hoja es fija por una regla: {costura.motivo}"))
        elif costura.error_seguro and se_aplica(costura):
            decididas.append((costura, "dos pruebas del papel", costura.motivo))
        elif costura.error_seguro:
            en_revision.append((costura.derecha, f"fuera del margen, con dos pruebas del papel: {costura.motivo}"))
        elif not se_aplica(costura) and juez is None:
            en_revision.append((costura.derecha, f"fuera del margen de error, para mirar: {costura.motivo}"))
        else:
            # Lo decide la IA, en todas las habilidades (2026-11-05: «cuando se
            # salga un caso del margen de error se lo envíe a la IA»). Donde la
            # habilidad no sabe nombrar lo movido, su veredicto no mueve hojas:
            # lo que confirma va a revisión con su cita y lo que desmiente, no.
            preguntar.append(costura)

    confirmadas = 0
    confirmadas_en: set[int] = set()
    #: Las costuras que de verdad se le mandaron a la IA (sin ella, ninguna).
    preguntadas = 0
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
            preguntadas += len(tanda)
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
                if veredicto and veredicto.decision == corrige and veredicto.cita.strip() and se_aplica(costura):
                    decididas.append((costura, "la IA", f"«{veredicto.cita.strip()[:160]}»; {costura.motivo}"))
                elif veredicto and veredicto.decision == corrige and veredicto.cita.strip():
                    en_revision.append(
                        (
                            costura.derecha,
                            f"la IA confirma el error («{veredicto.cita.strip()[:160]}»): {costura.motivo}; "
                            "esta habilidad no mueve hojas, para mirar",
                        )
                    )
                elif veredicto and veredicto.decision == confirma:
                    confirmadas += 1
                    confirmadas_en.add(costura.derecha)
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
            (c.derecha, f"no se corrigió: la corrección perdía o repetía hojas ({motivo})")
            for c, _por, motivo in decididas
        )
        salida, anexos_salida, movimientos = grupos, anexos, []
    else:
        # La decidida que ya no se pudo aplicar -- otra corrección se llevó
        # su bloque -- se dice: no se corrigió.
        aplicadas = {m.costura for m in movimientos}
        en_revision.extend(
            (c.derecha, f"la corrección no se pudo aplicar ({motivo})")
            for c, _por, motivo in decididas
            if (c.izquierda, c.derecha) not in aplicadas
        )
    anexos = anexos_salida
    corregidas_en = {m.costura[1] for m in movimientos if m.costura}

    def resultado(costura: Costura) -> str:
        if costura.derecha in corregidas_en:
            return "corregida"
        if costura.derecha in confirmadas_en:
            return "confirmada"
        return "revision"

    return RevisionDeCortes(
        grupos=salida,
        anexos=anexos,
        movimientos=tuple(movimientos),
        en_revision=tuple(en_revision),
        costuras=len(costuras),
        dentro_del_margen=len(costuras) - len(fuera),
        confirmadas_por_la_ia=confirmadas,
        preguntadas=preguntadas,
        ia_no_respondio=ia_no_respondio,
        releidas=tuple(releidas),
        fuera=tuple(
            {
                "izq": c.izquierda,
                "der": c.derecha,
                "decision": str(c.decision),
                "confianza": round(c.confianza, 2),
                "resultado": resultado(c),
                "motivo": c.motivo,
            }
            for c in fuera
        ),
    )


#: Cuántos sucesos recuerda el registro en vivo de una corrida.
SUCESOS_EN_VIVO = 8


@dataclass
class AgenteDeLaCorrida:
    """Lo que hizo el revisor de cortes en una corrida de carpeta, PDF a PDF.

    Lo pidió el operador el 2026-11-05: ver en la pantalla «el trabajo del agente
    revisando todo». La corrida lo suma al terminar cada PDF, desde el hilo que
    lo terminó, y la pantalla lo lee desde el suyo: por eso el cerrojo.
    """

    pdf: int = 0
    validados: int = 0
    corregidos: int = 0
    en_revision: int = 0
    #: Los que el revisor no pudo revisar: falló, o la habilidad no lo tiene.
    sin_revisar: int = 0
    costuras: int = 0
    dentro_del_margen: int = 0
    preguntadas_a_la_ia: int = 0
    confirmadas_por_la_ia: int = 0
    correcciones: int = 0
    hojas_comprobadas: int = 0
    problemas_de_entrega: int = 0
    #: Los datos de cada documento contra lo que espera su habilidad
    #: (2026-11-06): cuántos documentos, cuántos completos, para mirar y con
    #: error, y por campo -- nombre, identificación, código, fechas --.
    datos_documentos: int = 0
    datos_completos: int = 0
    datos_con_dudas: int = 0
    datos_con_errores: int = 0
    datos_con_en_blanco: int = 0
    datos_por_campo: dict = field(default_factory=dict)
    #: Lo último que merece contarse -- una corrección, una revisión, un
    #: problema en el disco --, lo más nuevo primero.
    sucesos: deque = field(default_factory=lambda: deque(maxlen=SUCESOS_EN_VIVO))
    _candado: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def sumar(self, pdf: str, informe: Mapping[str, object]) -> None:
        """Suma lo que dijeron el revisor y la comprobación del disco de un PDF terminado."""
        revision = informe.get("revision_de_cortes") or {}
        comprobacion = informe.get("comprobacion_de_la_entrega") or {}
        datos = informe.get("integridad_de_los_datos") or {}
        if not revision and not comprobacion and not datos:
            # Una habilidad que no parte PDF -- un inventario sin dividir --
            # no tiene costuras que revisar: no cuenta.
            return
        estado = str(revision.get("estado") or "no corrió")
        problemas = list(comprobacion.get("problemas") or [])
        with self._candado:
            self.pdf += 1
            if estado == "validado":
                self.validados += 1
            elif estado == "corregido":
                self.corregidos += 1
            elif estado == "en revisión":
                self.en_revision += 1
            else:
                self.sin_revisar += 1
            self.costuras += int(revision.get("costuras") or 0)
            self.dentro_del_margen += int(revision.get("dentro_del_margen") or 0)
            self.preguntadas_a_la_ia += int(revision.get("preguntadas_a_la_ia") or 0)
            self.confirmadas_por_la_ia += int(revision.get("confirmadas_por_la_ia") or 0)
            movimientos = list(revision.get("movimientos") or [])
            self.correcciones += len(movimientos)
            self.hojas_comprobadas += int(comprobacion.get("hojas") or 0)
            self.problemas_de_entrega += len(problemas)
            self.datos_documentos += int(datos.get("documentos") or 0)
            self.datos_completos += int(datos.get("completos") or 0)
            self.datos_con_dudas += int(datos.get("con_dudas") or 0)
            self.datos_con_errores += int(datos.get("con_errores") or 0)
            self.datos_con_en_blanco += int(datos.get("con_en_blanco") or 0)
            for campo, cuentas in (datos.get("por_campo") or {}).items():
                suyas = self.datos_por_campo.setdefault(campo, {"bien": 0, "dudas": 0, "errores": 0, "en_blanco": 0})
                for clave in suyas:
                    suyas[clave] += int((cuentas or {}).get(clave) or 0)
            texto = _lo_que_paso(estado, revision, movimientos, problemas)
            de_los_datos = [h for h in datos.get("hallazgos") or [] if h.get("gravedad") == "error"]
            if texto and (problemas or movimientos):
                self.sucesos.appendleft(
                    {"pdf": pdf, "estado": "problema" if problemas else estado, "texto": texto}
                )
            elif de_los_datos:
                # Un dato que no puede estar bien pesa más que una costura a revisión.
                primero = de_los_datos[0]
                mas = f" (y {len(de_los_datos) - 1} más)" if len(de_los_datos) > 1 else ""
                self.sucesos.appendleft(
                    {"pdf": pdf, "estado": "datos", "texto": f"{primero.get('documento')}: {primero.get('texto')}{mas}"}
                )
            elif texto:
                self.sucesos.appendleft({"pdf": pdf, "estado": estado, "texto": texto})

    def as_dict(self) -> dict[str, object]:
        with self._candado:
            return {
                "pdf": self.pdf,
                "validados": self.validados,
                "corregidos": self.corregidos,
                "en_revision": self.en_revision,
                "sin_revisar": self.sin_revisar,
                "costuras": self.costuras,
                "dentro_del_margen": self.dentro_del_margen,
                "preguntadas_a_la_ia": self.preguntadas_a_la_ia,
                "confirmadas_por_la_ia": self.confirmadas_por_la_ia,
                "correcciones": self.correcciones,
                "hojas_comprobadas": self.hojas_comprobadas,
                "problemas_de_entrega": self.problemas_de_entrega,
                "datos": {
                    "documentos": self.datos_documentos,
                    "completos": self.datos_completos,
                    "con_dudas": self.datos_con_dudas,
                    "con_errores": self.datos_con_errores,
                    "con_en_blanco": self.datos_con_en_blanco,
                    "por_campo": {campo: dict(cuentas) for campo, cuentas in self.datos_por_campo.items()},
                },
                "sucesos": list(self.sucesos),
            }


def _lo_que_paso(estado: str, revision: Mapping, movimientos: list, problemas: list) -> str | None:
    """Una línea para el registro en vivo, o nada si el PDF salió validado y en su sitio."""
    if problemas:
        return str(problemas[0].get("texto") or "la entrega no cuadra")
    if movimientos:
        primero = movimientos[0]
        bloque = _rango(primero.get("paginas") or ())
        destino = f"con las hojas {_rango(primero['hacia'])}" if primero.get("hacia") else "a su propio documento"
        mas = f" (y {len(movimientos) - 1} más)" if len(movimientos) > 1 else ""
        return f"hojas {bloque} {destino}, por {primero.get('por')}{mas}"
    if estado == "en revisión":
        primera = (revision.get("en_revision") or [{}])[0]
        return f"hoja {primera.get('page')}: {primera.get('reason', 'para mirar')}"
    if estado == "no corrió":
        return str(revision.get("resumen") or "el revisor no pudo revisar este PDF")
    return None


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
    *,
    perfil: Mapping[str, object] | None = None,
    integridad=None,
) -> None:
    """Lo que el revisor y la comprobación del disco dejan en el informe de cualquier habilidad.

    La cola de revisión recibe lo que hay que mirar; ``notices``, el resumen si
    algo no salió validado; y dos claves con el detalle: ``revision_de_cortes``
    y ``comprobacion_de_la_entrega``. ``perfil`` es el de la habilidad con que
    se revisó (``perfiles_de_revision``), para que se vea con qué patrones.
    ``integridad`` es lo que dijo el agente de los datos de cada documento
    (``integridad_de_los_datos``), con su clave ``integridad_de_los_datos``.
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
    if perfil and "revision_de_cortes" in informe:
        informe["revision_de_cortes"]["perfil"] = dict(perfil)
    if integridad is not None and integridad.documentos:
        # Los datos de cada documento (2026-11-06): lo que no cuadra, a la
        # cola de revisión con su página, y el resumen si algo falta.
        cola.extend(
            {"page": h.get("pagina") or 1, "reason": f"datos de {h.get('documento')}: {h.get('texto')}"}
            for h in integridad.hallazgos
        )
        if integridad.estado != "validado":
            avisos.append(integridad.resumen())
        informe["integridad_de_los_datos"] = integridad.as_dict()
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
        movimientos.append(
            Movimiento(tuple(bloque), desde, hacia, por, motivo, costura=(costura.izquierda, costura.derecha))
        )

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
