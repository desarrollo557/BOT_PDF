"""La auditoría de un PDF ya entregado: sus hojas casadas con el original y sus cortes revisados otra vez.

Lo pidió el operador el 2026-11-05: al terminar la corrida, «que agarre
aleatoriamente unos 100 documentos y valide el margen de errores y valide los
PDF divididos según los patrones y margen de errores establecidos». Cada PDF de
la muestra pasa por esto, con lo que ya está en el disco y sin volver a
procesar nada:

1. **Las hojas**: cada PDF entregado se casa hoja por hoja con el original por
   su huella. Una hoja del original que no está en ningún PDF, una que está en
   dos, o una entregada que no es de este original, son **errores**.
2. **Los cortes**: con cómo quedaron repartidas las hojas, el agente revisor
   vuelve a mirar cada costura con los patrones de la habilidad -- los de su
   perfil en ``perfiles_de_revision``, los mismos con que se revisó al
   procesar --. Dos pruebas
   del papel que contradicen un corte son un **error**; una sola es una
   **duda**, que decide la IA si la corrida se hizo con ella (una pregunta por
   PDF, con la huella de las hojas de alrededor); sin IA queda como duda.
3. **El índice**: si se sabe cuántas filas tiene el índice de su carpeta y
   cuántos PDF hay en ella, que sean los mismos.
4. **Los datos** (2026-11-06): en las habilidades que esperan datos de cada
   documento -- las historias: nombre, cédula o TI o libreta, código, fechas
   extremas --, cada PDF contra su fila del FUID entregado.

5. **Las fechas** (2026-11-10, el revisor de fechas): cada PDF entregado con
   su fila de la constancia -- casada por ``archivo_generado`` o por su primera
   hoja del original --, su fecha inicial y su final contra el texto de **sus**
   hojas, con la regla de su habilidad (``perfil.regla_de_fechas``) y el mismo
   margen que al procesar (``revisor_de_fechas``). Lo que el papel corrige con
   prueba es un **error**; lo que no confirma, una **duda**, que decide la IA de
   los datos si la corrida se hizo con ella: **una pregunta por PDF de la
   muestra** con lo dudoso de todos sus documentos, no una por documento.

   Tras la revisión adversarial (2026-11-10) llega a **todas las habilidades**:
   la caja de correspondencia, por las filas de su Índice Electrónico
   (``filas_del_indice_con_su_pdf``), y Kingspan, por las puntas de su inventario contra
   todo el original (``DE_TODO_EL_ORIGINAL``). Y no infla el margen con lo que
   no es error de la entrega: la fecha fuera de los años del libro
   (``ventana_de_la_auditoria``) es duda sin pagar la IA; el texto que no se
   deja leer -- letra a mano -- deja sin dato lo que no confirma.

Nada de esto lee con OCR: la huella y la capa de texto, nada más. Sólo paga la
IA, y sólo con lo dudoso, si la corrida se hizo con ella.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import PurePath

from ..domain.acta_grado import es_libro_de_actas_colectivas
from ..domain.auditoria import NO_AUDITADO, PdfAuditado, veredicto
from ..domain.auditoria_de_filas import (
    error_de_fecha,
    fecha_escrita,
    fechas_sin_prueba_si_no_se_leen,
    nombre_en_el_texto,
    paginas_de_la_fila,
    plano,
    texto_legible,
)
from ..domain.conciliacion import ArchivoEntregado, Huella, conciliar, rangos
from ..domain.fechas_extremas import (
    FechasDeLaFila,
    RevisionDeFechas,
    contrastar_las_fechas,
    fechas_de_la_fila,
)
from ..domain.revision_de_cortes import Decision, huella_para_la_ia, revisar_costuras
from ..domain.revision_de_nombres import nombre_del_asunto
from .auditoria_de_filas import (
    FECHAS_CON_ERROR,
    FECHAS_CONFIRMADAS,
    FECHAS_EN_DUDA,
    FECHAS_SIN_DATO,
    NOMBRE_CONFIRMADO,
    NOMBRE_EN_DUDA,
    NOMBRE_SIN_DATO,
    regla_de_fechas_de,
    ventana_de_la_auditoria,
)
from .control import Cancelled
from .fuid import FuidRow
from .integridad_de_los_datos import auditar_los_datos
from .perfiles_de_revision import REGLAS_DEL_LIBRO_COLECTIVO, perfil_de
from .ports import JuezDeCosturas, JuezDeDatos
from .revisor_de_cortes import COSTURAS_POR_PREGUNTA
from .revisor_de_fechas import (
    A_REVISION,
    CONFIRMADA,
    CORREGIDA,
    SIN_DATO,
    TEXTO_PARA_LA_IA,
    revisar_las_fechas,
)

logger = logging.getLogger(__name__)

def auditar_un_pdf(
    pdf: str,
    origen: Sequence[Huella],
    textos: Mapping[int, str],
    entregados: Mapping[str, Sequence[Huella] | None],
    *,
    habilidad: str = "",
    juez: JuezDeCosturas | None = None,
    filas_del_indice: int | None = None,
    pdf_en_su_carpeta: int | None = None,
    filas_del_fuid: Sequence[FuidRow] | None = None,
    verificados: Mapping[str, Mapping[str, str]] | None = None,
    tipos: Mapping[str, str] | None = None,
    filas_de_la_constancia: Sequence[Mapping[str, object]] | None = None,
    juez_de_datos: JuezDeDatos | None = None,
    filas_del_indice_electronico: Sequence[Mapping[str, object]] | None = None,
    lo_leido: Sequence[Mapping[str, object]] = (),
    varios_sellos: Sequence[Mapping[str, object]] = (),
    folios: Mapping[int, int] | None = None,
    marcas: Mapping[int, str] | None = None,
) -> PdfAuditado:
    """Lo que la auditoría encuentra en un PDF entregado.

    ``entregados`` son los PDF que salieron de él, por su nombre, con la huella
    de cada hoja (``None`` si no se dejó abrir), en el orden en que se
    numeraron. ``filas_del_indice`` y ``pdf_en_su_carpeta``, si se saben, son
    las filas del índice de su carpeta y los PDF que hay en ella.
    ``filas_del_fuid`` son las del FUID entregado en su carpeta (``None`` si no
    tiene): en las habilidades que esperan datos de cada documento -- las
    historias --, cada PDF se compara con su fila (``integridad_de_los_datos``).
    ``verificados`` dice, por PDF entregado, cómo quedó al procesar cada casilla
    que el agente buscó otra vez: la que está en blanco en el papel no es duda.
    ``filas_de_la_constancia`` son las filas que el PDF aportó al inventario
    (``constancia.actas``): sus fechas se contrastan con las hojas de cada PDF
    entregado, y lo dudoso lo decide ``juez_de_datos`` si lo hay (2026-11-10).
    ``filas_del_indice_electronico`` son las del Índice Electrónico de una caja
    de correspondencia, que no deja filas en la constancia: cada una se casa
    con su PDF por título y páginas (``filas_del_indice_con_su_pdf``), y sus fechas se
    auditan igual.
    """
    errores: list[str] = []
    dudas: list[str] = []
    for nombre, huellas in entregados.items():
        if huellas is None:
            errores.append(f"«{nombre}» no se dejó abrir")
    legibles = {nombre: huellas for nombre, huellas in entregados.items() if huellas is not None}
    if not legibles:
        return PdfAuditado(
            pdf,
            NO_AUDITADO if not entregados else veredicto(errores, dudas),
            tuple(errores or ["no tiene ningún PDF entregado que abrir"]),
            paginas=len(origen),
            habilidad=habilidad,
        )

    conciliacion = conciliar(origen, legibles)
    if conciliacion.faltantes:
        errores.append(f"hojas del original que no están en ningún PDF entregado: {rangos(conciliacion.faltantes)}")
    if conciliacion.repetidas:
        errores.append(f"hojas entregadas en más de un PDF: {rangos(conciliacion.repetidas)}")
    for archivo in conciliacion.archivos:
        if archivo.ajeno:
            errores.append(f"«{archivo.nombre}» trae hojas que no son de este original")

    # Cómo quedaron repartidas las hojas, en el orden en que se numeraron los PDF.
    documentos = [[p for p in archivo.paginas if p is not None] for archivo in conciliacion.archivos]
    documentos = [hojas for hojas in documentos if hojas]
    # Los patrones de su habilidad, del mismo registro con que la revisó el
    # agente al procesarla (``perfiles_de_revision``): la caja de
    # correspondencia no cuenta como prueba lo que cruza por regla -- las
    # piezas del acuerdo y la Habeas Data --; las de una persona por PDF, dos
    # cédulas sí.
    patrones = perfil_de(habilidad).patrones(textos)
    if perfil_de(habilidad).clave == "actas-de-grado" and es_libro_de_actas_colectivas(list(textos.values())):
        # El libro de actas colectivas (UPD3859802, 2026-11-12) lleva en el PDF
        # de cada acta a toda su promoción: varias cédulas no son un error. Se
        # reconoce en el mismo texto que la auditoría ya tiene; si no se
        # reconoce -- la capa es basura --, la regla del perfil dice la excepción
        # a la IA que decide lo dudoso.
        patrones = perfil_de(habilidad).patrones(
            textos, una_persona_por_pdf=False, reglas=REGLAS_DEL_LIBRO_COLECTIVO
        )
    costuras = revisar_costuras(
        documentos,
        textos,
        cruces=patrones.cruces,
        una_persona_por_pdf=patrones.una_persona_por_pdf,
        # El folio a mano de cada hoja, como lo leyó el revisor al procesar: el
        # que sigue es prueba contra un corte y el 1 contra una unión (2026-11-12).
        folios=folios,
    )
    fuera = [c for c in costuras if c.fuera_del_margen]
    preguntar = []
    for costura in fuera:
        if costura.error_seguro:
            errores.append(f"hojas {costura.izquierda}-{costura.derecha}: {costura.motivo} (dos pruebas del papel)")
        elif any(prueba.fuerte for prueba in costura.pruebas) or juez is not None:
            preguntar.append(costura)
        # Una prueba débil sola -- la «frase que sigue» -- no levanta una duda
        # sin la IA: la OCR la fabrica con un membrete mal leído (1000224 y
        # 1000265 pág. 2, medido en la auditoría de las cajas de MAGANGUE), y
        # al procesar la descartaba la regla de la constancia, que aquí no se ve.

    preguntadas = 0
    if preguntar and juez is not None:
        tanda, resto = preguntar[:COSTURAS_POR_PREGUNTA], preguntar[COSTURAS_POR_PREGUNTA:]
        todas = {p for hojas in documentos for p in hojas}
        ventana = sorted(
            {q for c in tanda for q in (c.izquierda - 1, c.izquierda, c.derecha, c.derecha + 1) if q in todas}
        )
        # Con las marcas de cada hoja -- folio a mano, sello --, para que la IA
        # razone con lo mismo que el revisor (2026-11-12).
        huellas = [huella_para_la_ia(q, textos.get(q, "") or "", marcas=(marcas or {}).get(q)) for q in ventana]
        preguntadas = len(tanda)
        try:
            respuesta = juez.decidir(huellas, [(c.izquierda, c.derecha) for c in tanda], patrones.reglas) or {}
        except Exception:  # noqa: BLE001 - un juez roto deja las dudas como dudas
            logger.warning("el juez de la auditoría falló con %s", pdf, exc_info=True)
            respuesta = {}
        for costura in tanda:
            dicho = respuesta.get((costura.izquierda, costura.derecha))
            corrige = "continua" if costura.decision is Decision.CORTE else "abre"
            confirma = "abre" if costura.decision is Decision.CORTE else "continua"
            if dicho and dicho.decision == corrige and dicho.cita.strip():
                errores.append(
                    f"hojas {costura.izquierda}-{costura.derecha}: {costura.motivo} "
                    f"(la IA: «{dicho.cita.strip()[:120]}»)"
                )
            elif not (dicho and dicho.decision == confirma):
                dudas.append(f"hojas {costura.izquierda}-{costura.derecha}: {costura.motivo}")
        dudas.extend(f"hojas {c.izquierda}-{c.derecha}: {c.motivo}" for c in resto)
    else:
        dudas.extend(f"hojas {c.izquierda}-{c.derecha}: {c.motivo}" for c in preguntar)

    # Las fechas de cada PDF entregado contra sus hojas (2026-11-10).
    fechas = None
    filas = [*(filas_de_la_constancia or [])]
    if filas_del_indice_electronico:
        filas += filas_del_indice_con_su_pdf(
            filas_del_indice_electronico, conciliacion.archivos, prefijo=PurePath(pdf.replace("\\", "/")).stem, origen=pdf
        )
    if filas:
        fechas = auditar_las_fechas(
            conciliacion.archivos,
            textos,
            filas,
            regla=regla_de_fechas_de(habilidad),
            juez=juez_de_datos,
            # Los años del libro, los mismos que en la muestra de filas.
            ventana=ventana_de_la_auditoria(habilidad, pdf, list(textos.values())),
            lo_leido=lo_leido,
        )
        errores.extend(fechas.errores)
        dudas.extend(fechas.dudas)
        preguntadas += fechas.preguntadas

    # El nombre de cada persona de cada PDF entregado contra sus hojas
    # (2026-11-17), en las habilidades con una persona por documento: como las
    # fechas, con la misma pieza que el revisor de nombres al procesar.
    nombres = None
    if perfil_de(habilidad).regla_del_nombre is not None and (filas or filas_del_fuid):
        nombres = auditar_los_nombres(
            conciliacion.archivos, textos, filas, filas_del_fuid=filas_del_fuid, lo_leido=lo_leido
        )
        dudas.extend(nombres.dudas)

    # Los radicados de la caja de correspondencia (2026-11-18): el RE de cada
    # nombre, la contestación, los folios de la etiqueta y el orden del
    # acuerdo, con lo que ya se leyó.
    radicados = None
    if perfil_de(habilidad).clave == "correspondencia":
        radicados = auditar_los_radicados(conciliacion.archivos, textos)
        errores.extend(radicados.errores)
        dudas.extend(radicados.dudas)

    # Los datos de cada PDF contra su fila del FUID entregado (2026-11-06).
    if (esperados := perfil_de(habilidad).datos) is not None:
        de_los_datos, dudas_de_los_datos = auditar_los_datos(
            list(entregados), filas_del_fuid, esperados, verificados=verificados, tipos=tipos
        )
        errores.extend(de_los_datos)
        dudas.extend(dudas_de_los_datos)

    if (
        filas_del_indice is not None
        and pdf_en_su_carpeta is not None
        and filas_del_indice != pdf_en_su_carpeta
    ):
        errores.append(
            f"el índice de su carpeta tiene {filas_del_indice} filas y la carpeta {pdf_en_su_carpeta} PDF"
        )

    # Los PDF entregados con dos o más sellos de RE distinto (2026-11-12): se
    # avisan todos; el que el agente dejó en revisión es una duda.
    avisos, de_los_sellos = avisos_de_varios_sellos(conciliacion.archivos, varios_sellos)
    dudas.extend(de_los_sellos)

    return PdfAuditado(
        pdf,
        veredicto(errores, dudas),
        tuple(errores + dudas + avisos),
        paginas=len(origen),
        archivos=len(entregados),
        costuras=len(costuras),
        dentro_del_margen=len(costuras) - len(fuera),
        preguntadas_a_la_ia=preguntadas,
        habilidad=habilidad,
        extra={
            **({"fechas": dict(fechas.cuentas)} if fechas is not None else {}),
            **({"nombres": dict(nombres.cuentas)} if nombres is not None and nombres.cuentas else {}),
            **({"radicados": dict(radicados.cuentas)} if radicados is not None and radicados.cuentas else {}),
            **({"varios_sellos": len(avisos) + len(de_los_sellos)} if avisos or de_los_sellos else {}),
        },
    )


#: Lo que el agente dejó sin decidir de un PDF con varios sellos.
_SELLOS_EN_REVISION = "en revisión"


def avisos_de_varios_sellos(
    archivos: Sequence[ArchivoEntregado], varios_sellos: Sequence[Mapping[str, object]]
) -> tuple[list[str], list[str]]:
    """Los PDF entregados que siguen con dos o más sellos de RE distinto: (avisos, dudas).

    Cada uno de ``varios_sellos`` (de la constancia) se casa con su PDF
    entregado por sus hojas del original, no por su nombre: la carpeta del NIC
    los renumera. El que el agente dejó «en revisión» es una duda; el que
    confirmó la IA o explica una regla, un aviso que no cambia el veredicto.
    """
    por_hojas = {frozenset(p for p in archivo.paginas if p is not None): archivo for archivo in archivos}
    avisos: list[str] = []
    dudas: list[str] = []
    for varios in varios_sellos:
        try:
            hojas = frozenset(int(p) for p in varios.get("paginas") or [])
            sellos = [(int(s["pagina"]), str(s["re"])) for s in varios.get("sellos") or []]
        except (TypeError, ValueError, KeyError):
            continue
        archivo = por_hojas.get(hojas)
        if archivo is None or len(sellos) < 2:
            continue
        estado = str(varios.get("estado") or _SELLOS_EN_REVISION)
        texto = (
            f"«{archivo.nombre}» trae {len(sellos)} sellos de RE distinto: "
            + ", ".join(f"{radicado} (pág. {pagina})" for pagina, radicado in sellos)
            + f"; {estado}"
        )
        (dudas if estado == _SELLOS_EN_REVISION else avisos).append(texto)
    return avisos, dudas


# -- las fechas de lo entregado (2026-11-10) ------------------------------------------------

#: Cuántos documentos de un PDF van, como mucho, en una pregunta de fechas a la
#: IA: con más, a cada uno le tocan menos de 4 000 caracteres de su texto.
DOCUMENTOS_POR_PREGUNTA = 8
#: Lo que el revisor decidió, dicho como lo cuenta la auditoría.
_ESTADO_DE_LA_AUDITORIA = {
    CONFIRMADA: FECHAS_CONFIRMADAS,
    CORREGIDA: FECHAS_CON_ERROR,
    A_REVISION: FECHAS_EN_DUDA,
}
#: La fila que no es de un PDF entregado sino de todo un tramo del original:
#: las puntas de un paquete de Kingspan, cuyo DESDE y HASTA caen en PDF
#: distintos. Se audita contra sus hojas del original, no contra un PDF.
DE_TODO_EL_ORIGINAL = "de_todo_el_original"


@dataclass(slots=True)
class FechasAuditadas:
    """Lo que la auditoría encontró en las fechas de los PDF entregados de un original."""

    errores: list[str] = field(default_factory=list)
    dudas: list[str] = field(default_factory=list)
    #: Cuántas fechas contestó la IA citando el papel.
    preguntadas: int = 0
    #: Por estado (``FECHAS_*``), cuántos PDF entregados.
    cuentas: Counter = field(default_factory=Counter)


@dataclass(slots=True)
class _Documento:
    nombre: str
    fechas: FechasDeLaFila
    textos: tuple[str, ...]
    #: El contraste con su texto, una sola vez: con él se decide qué se le
    #: pregunta a la IA y lo decide ``revisar_las_fechas`` (que antes lo volvía
    #: a hacer). ``revision`` es él mismo, o, si el texto no se lee, lo que queda.
    contraste: RevisionDeFechas | None = None
    revision: RevisionDeFechas | None = None
    legible: bool = True

    @property
    def una_sola(self) -> bool:
        return self.fechas.inicial is not None and self.fechas.inicial == self.fechas.final


def fila_del_archivo(
    archivo: ArchivoEntregado, filas: Sequence[Mapping[str, object]]
) -> Mapping[str, object] | None:
    """La fila de la constancia de un PDF entregado: la que lo nombra, o la única que empieza en su primera hoja.

    Por el nombre primero (``archivo_generado``, sin la carpeta y sin mirar
    mayúsculas). Si ninguna lo nombra, por la hoja del original en que empieza:
    las filas del FUID de un legajo no guardan su archivo, sí su página. Dos
    filas que empiezan en la misma hoja no se casan: adivinar cuál es la de este
    PDF sería auditar otra.

    Para muchos PDF del mismo original, ``filas_por_archivo``: la misma regla
    con sus índices armados una vez.
    """
    return filas_por_archivo(filas)(archivo)


def filas_por_archivo(
    filas: Sequence[Mapping[str, object]],
) -> Callable[[ArchivoEntregado], Mapping[str, object] | None]:
    """``fila_del_archivo`` de cada PDF de un original, con sus dos índices -- por nombre y por primera hoja -- armados una vez.

    Antes cada PDF recorría todas las filas: con 1 600 PDF de una hoja, 3 s por
    el nombre y 10 s por la primera hoja (la revisión adversarial, 2026-11-10).
    Elige lo mismo, también en los empates: por el nombre, la primera fila que
    lo nombra; por la hoja, sólo la única que empieza en ella.
    """
    por_nombre: dict[str, Mapping[str, object]] = {}
    por_hoja: dict[int, list[Mapping[str, object]]] = {}
    for fila in filas:
        generado = str(fila.get("archivo_generado") or "")
        if generado:
            por_nombre.setdefault(_sin_la_carpeta(generado), fila)
        if not fila.get("archivo_generado") and (paginas := paginas_de_la_fila(fila)):
            por_hoja.setdefault(paginas[0], []).append(fila)

    def la_suya(archivo: ArchivoEntregado) -> Mapping[str, object] | None:
        if (fila := por_nombre.get(_sin_la_carpeta(str(archivo.nombre)))) is not None:
            return fila
        primera = archivo.primera
        if primera is None:
            return None
        suyas = por_hoja.get(primera, ())
        return suyas[0] if len(suyas) == 1 else None

    return la_suya


def _sin_la_carpeta(nombre: str) -> str:
    return PurePath(nombre.replace("\\", "/")).name.upper()


# -- los radicados de la caja de correspondencia (2026-11-18) ---------------------------------

#: Cómo quedó el RE de cada PDF auditado, en el orden en que se dice.
RE_CONFIRMADO = "re confirmados"
RE_A_MANO = "re a mano"
RE_QUE_FALTA = "sin re"


@dataclass(slots=True)
class RadicadosAuditados:
    """Lo que la auditoría encontró en los radicados de los PDF entregados de una caja de correspondencia."""

    errores: list[str] = field(default_factory=list)
    dudas: list[str] = field(default_factory=list)
    #: Cuántos PDF con su RE confirmado en sus hojas, con un RE escrito a
    #: mano (que la capa no trae) y sin el RE que su tipo pide.
    cuentas: Counter = field(default_factory=Counter)


def _titulo_del_nombre(nombre: str) -> str:
    """El tipo que dice el nombre de un PDF entregado: «04_RECLAMO-RE9233….pdf» es «RECLAMO»."""
    stem = PurePath(str(nombre).replace("\\", "/")).stem
    stem = re.sub(r"^(?:UPD\d+_)?\d+_", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"-RE\d{13}$", "", stem, flags=re.IGNORECASE)
    return stem.replace("-", " ").strip()


def _escrito_del_usuario(texto: str) -> bool:
    """Si la hoja abre un escrito del usuario -- reclamo, recurso, petición, queja --: lo que se radica con sello."""
    from ..domain.asunto_del_documento import es_carta_de_la_empresa
    from ..domain.carta import abre_carta
    from .cartas import _es_escrito_del_tramite

    return abre_carta(texto) and _es_escrito_del_tramite(texto) and not es_carta_de_la_empresa(texto)


#: Los nombres de PDF que pueden llevar un pagaré: el suyo y los del acuerdo de pago.
TITULOS_DEL_PAGARE = frozenset({"PAGARE", "CARTA DE INSTRUCCIONES"})


def _comparable(nombre: str) -> str:
    """Un nombre sin lo que el archivo no puede llevar: «DESCUENTO/NOTA…» es «DESCUENTO-NOTA…» en el disco."""
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", nombre.upper()).split())


def auditar_los_radicados(archivos: Sequence[ArchivoEntregado], textos: Mapping[int, str]) -> RadicadosAuditados:
    """Las reglas del operador para Afinia (2026-11-18), otra vez sobre lo entregado: lo que se puede comprobar sin IA.

    - **El RE del nombre**: el tipo que lo pide y no lo trae es duda; el que
      lo trae se confirma si está en sus hojas, y si no, lo escribió la mano
      en el sello (sólo se cuenta). Si su hoja trae la etiqueta impresa con
      otro RE, es duda: el del nombre puede ser el de otro papel.
    - **La contestación**: la carta de la empresa que abre el PDF y que es una
      contestación, con otro nombre, es duda. Lo mismo el papel que se llama
      por su formato (``NOMBRE_POR_SU_FORMATO``) con otro nombre: la carta
      «MESUC» de Electricaribe, la nota crédito de Aseopronto (2026-11-24).
    - **Los folios de la etiqueta**: menos hojas de las que declara es duda
      (por trámite un PDF junta varios escritos: más hojas no prueba nada).
    - **El orden del acuerdo**: el reconocimiento de deuda va primero (con
      fecha) o al final (sin ella); en medio es un error, y al final con el
      renglón de su fecha escrito es duda (2026-11-24).
    - **El nombre de un tipo con par**: PETICION, que es DERECHO DE PETICION,
      es duda (2026-11-24).
    - **El pagaré fuera de su sitio**: un pagaré o su carta de instrucciones
      dentro de un PDF que no es el acuerdo ni el PAGARE es un error
      (1000478, 2026-11-24).
    - **La notificación personal y su respuesta**: con el mismo RE en dos PDF
      es un error; van en uno, con el nombre de la notificación (2026-11-24).
    """
    from ..domain.asunto_del_documento import (
        CONTESTACION_A_RECLAMACION,
        NOMBRE_POR_SU_FORMATO,
        NOTIFICACION_PERSONAL,
        es_contestacion_a_reclamacion,
        formulario_que_abre,
        titulo_de_la_caratula,
        titulo_del_documento,
    )
    from ..domain.fecha_por_estructura import fecha_en_blanco
    from ..domain.nombre_oficial import (
        le_falta_su_re,
        re_del_archivo,
        tipo_unificado,
    )
    from ..domain.sello import folios_que_no_cuadran, leer_sello, radicados_impresos
    from ..domain.tramites import radicados_de
    from .anexos_declarados import RECONOCIMIENTO, partes_del_acuerdo

    resultado = RadicadosAuditados()
    for archivo in archivos:
        hojas = [p for p in archivo.paginas if p is not None]
        if not hojas:
            continue
        titulo = _titulo_del_nombre(archivo.nombre)
        radicado = re_del_archivo(archivo.nombre)
        primera = textos.get(hojas[0], "") or ""
        etiqueta = leer_sello(primera)
        # La notificación que no cita ningún radicado no lo lleva (920933, 2026-11-20).
        if radicado is None and le_falta_su_re(titulo, [textos.get(p, "") or "" for p in hojas]):
            resultado.cuentas[RE_QUE_FALTA] += 1
            resultado.dudas.append(f"«{archivo.nombre}»: {titulo} sin RE en el nombre")
        elif radicado is None and _escrito_del_usuario(primera):
            # El escrito del usuario se radica siempre con su sello: sin RE, es
            # que no se leyó (el recurso de 1005117, UPD2437857 pág. 5).
            resultado.cuentas[RE_QUE_FALTA] += 1
            resultado.dudas.append(f"«{archivo.nombre}»: escrito del usuario sin RE; su sello de radicación no se leyó")
        elif radicado is not None:
            en_sus_hojas = set().union(
                *(
                    {r for r in radicados_de(textos.get(p, "") or "") if r.startswith("RE")}
                    | radicados_impresos(textos.get(p, "") or "")
                    for p in hojas
                )
            )
            resultado.cuentas[RE_CONFIRMADO if radicado in en_sus_hojas else RE_A_MANO] += 1
            if etiqueta is not None and etiqueta.clase == "impreso" and etiqueta.radicado and etiqueta.radicado != radicado:
                resultado.dudas.append(
                    f"«{archivo.nombre}»: su etiqueta de radicación dice {etiqueta.radicado} y el nombre lleva {radicado}"
                )
        # La notificación personal unida a su respuesta lleva su nombre aunque
        # en el papel la respuesta vaya delante (7740246, 2026-11-24).
        con_su_notificacion = titulo.upper().startswith(NOTIFICACION_PERSONAL) and any(
            formulario_que_abre(textos.get(p, "") or "") == NOTIFICACION_PERSONAL for p in hojas
        )
        if (
            es_contestacion_a_reclamacion(primera)
            and titulo.upper() != CONTESTACION_A_RECLAMACION
            and not con_su_notificacion
        ):
            resultado.dudas.append(f"«{archivo.nombre}»: abre con una contestación de la empresa y se llama {titulo}")
        # Lo que se llama por su formato (2026-11-24): la carta «MESUC» de
        # Electricaribe al usuario, la nota crédito de Aseopronto.
        esperado = NOMBRE_POR_SU_FORMATO.get(titulo_del_documento(primera)) or titulo_de_la_caratula(primera)
        if esperado and _comparable(titulo) != _comparable(esperado):
            resultado.dudas.append(f"«{archivo.nombre}»: su formato es el de {esperado} y se llama {titulo}")
        motivo = folios_que_no_cuadran(len(hojas), etiqueta.folios) if etiqueta is not None else None
        if motivo and "faltarle" in motivo:
            resultado.dudas.append(f"«{archivo.nombre}»: {motivo}")
        if "ACUERDO" in titulo.upper() or "RECONOCIMIENTO" in titulo.upper():
            reconocimiento = {p for parte, suyas in partes_del_acuerdo(hojas, textos) if parte == RECONOCIMIENTO for p in suyas}
            if reconocimiento and len(hojas) > len(reconocimiento):
                donde = [i for i, p in enumerate(hojas) if p in reconocimiento]
                al_principio = donde == list(range(len(donde)))
                al_final = donde == list(range(len(hojas) - len(donde), len(hojas)))
                if not (al_principio or al_final):
                    resultado.errores.append(
                        f"«{archivo.nombre}»: el reconocimiento de deuda está en medio del acuerdo (hoja "
                        f"{donde[0] + 1} de {len(hojas)}); va primero si está fechado, si no al final"
                    )
                # Al final sólo va el que tiene el renglón de su fecha en blanco
                # (4251530, 2026-11-24): si está escrito, aunque no se leyera, es duda.
                elif al_final and not al_principio and not any(
                    fecha_en_blanco(textos.get(p, "") or "") for p in reconocimiento
                ):
                    resultado.dudas.append(
                        f"«{archivo.nombre}»: el reconocimiento de deuda va al final y el renglón de su fecha "
                        "no está en blanco; va primero si el acuerdo tiene fecha"
                    )
        # El pagaré va con su reconocimiento de deuda o solo, nunca con otro
        # documento (1000478, 2026-11-24: se pegaba al contrato de transacción).
        elif titulo.upper() not in TITULOS_DEL_PAGARE:
            con_pagare = [
                i + 1
                for i, p in enumerate(hojas)
                if titulo_del_documento(textos.get(p, "") or "") in ("PAGARE", "CARTA DE INSTRUCCIONES")
            ]
            if con_pagare:
                resultado.errores.append(
                    f"«{archivo.nombre}»: lleva un pagaré o su carta de instrucciones (hoja {con_pagare[0]} de "
                    f"{len(hojas)}) y no es el acuerdo de pago; sin reconocimiento de deuda, el pagaré va solo"
                )
        # El mismo documento con un solo nombre: PETICION es DERECHO DE PETICION (4251556, 2026-11-24).
        unificado = tipo_unificado(titulo.upper())
        if unificado and unificado != titulo.upper():
            resultado.dudas.append(f"«{archivo.nombre}»: se llama {titulo} y ese documento es {unificado}")
    # La notificación personal y la respuesta de su mismo RE van en un PDF (el
    # operador, 2026-11-24): en dos es un error.
    notificaciones = {
        re_del_archivo(a.nombre): a.nombre
        for a in archivos
        if _titulo_del_nombre(a.nombre).upper().startswith(NOTIFICACION_PERSONAL) and re_del_archivo(a.nombre)
    }
    for archivo in archivos:
        radicado = re_del_archivo(archivo.nombre)
        if _titulo_del_nombre(archivo.nombre).upper() == CONTESTACION_A_RECLAMACION and radicado in notificaciones:
            resultado.errores.append(
                f"«{archivo.nombre}»: la respuesta a la reclamación salió aparte de su notificación personal "
                f"«{notificaciones[radicado]}»; con el mismo RE van en un PDF"
            )
    _auditar_lo_que_va_con_su_documento(archivos, textos, resultado)
    return resultado


def _auditar_lo_que_va_con_su_documento(
    archivos: Sequence[ArchivoEntregado], textos: Mapping[int, str], resultado: RadicadosAuditados
) -> None:
    """Lo que el operador dictó el 2026-11-24 que va con su documento, otra vez sobre lo entregado.

    - **El aviso con su acto** (4251461): la notificación por aviso que adjunta
      la copia del acto y la deja en otro PDF, o el PDF que es sólo la portada
      «ANEXO», son errores.
    - **El paquete de la empresa** (4251482): el documento que va justo detrás
      de una carátula con membrete (CONSTANCIA DE CONTRATACIÓN, EXPEDIENTE) sin
      ser algo que lo cierre -- un formulario que va solo, un escrito de
      trámite, un sello visible -- y que salió aparte, es duda. Sin carátula, la
      declaración juramentada que salió aparte justo detrás de un documento que
      no la corta también es duda (6831824).
    """
    from ..domain.asunto_del_documento import (
        DECLARACION_JURAMENTADA,
        FORMATO_DE_LA_EMPRESA,
        acto_que_adjunta,
        consecutivo_de,
        formulario_que_abre,
        portada_del_anexo,
    )
    from ..domain.sello import leer_sello
    from .cartas import _es_escrito_del_tramite

    archivo_de = {p: a.nombre for a in archivos for p in a.paginas if p is not None}

    def texto(pagina: int) -> str:
        return textos.get(pagina, "") or ""

    for archivo in archivos:
        hojas = [p for p in archivo.paginas if p is not None]
        if not hojas:
            continue
        primera = min(hojas)
        if portada_del_anexo(texto(primera)) is not None and all(
            portada_del_anexo(texto(p)) is not None for p in hojas
        ):
            resultado.errores.append(
                f"«{archivo.nombre}»: es sólo la portada «ANEXO» de un acto; va con la notificación por aviso que lo adjunta"
            )
        acto = acto_que_adjunta(texto(primera))
        siguiente = max(hojas) + 1
        if acto and siguiente in archivo_de and archivo_de[siguiente] != archivo.nombre:
            de_su_acto = portada_del_anexo(texto(siguiente)) is not None or consecutivo_de(texto(siguiente)) == acto
            if de_su_acto:
                resultado.errores.append(
                    f"«{archivo.nombre}»: la notificación por aviso adjunta la copia del acto {acto} y la copia salió "
                    f"en «{archivo_de[siguiente]}»"
                )
        anterior = primera - 1
        if anterior in archivo_de and archivo_de[anterior] != archivo.nombre:
            otro = next(a for a in archivos if a.nombre == archivo_de[anterior])
            caratula = min(p for p in otro.paginas if p is not None)
            cierra = (
                formulario_que_abre(texto(primera)) not in (None, DECLARACION_JURAMENTADA)
                or _es_escrito_del_tramite(texto(primera))
                or leer_sello(texto(primera)) is not None
            )
            if formulario_que_abre(texto(caratula)) == FORMATO_DE_LA_EMPRESA and not cierra:
                resultado.dudas.append(
                    f"«{archivo.nombre}»: va justo detrás de la carátula de «{otro.nombre}» (hoja {caratula}) y "
                    "salió aparte; la carátula se lleva lo que la sigue"
                )
            # Sin carátula, la declaración juramentada va con las piezas de su
            # paquete que la preceden (2026-11-24, 6831824).
            elif formulario_que_abre(texto(primera)) == DECLARACION_JURAMENTADA and not (
                formulario_que_abre(texto(caratula)) is not None
                or _es_escrito_del_tramite(texto(caratula))
                or leer_sello(texto(caratula)) is not None
                or any(
                    palabra in _titulo_del_nombre(otro.nombre).upper()
                    for palabra in ("ACUERDO", "RECONOCIMIENTO", "PAGARE", "CONTRATO")
                )
            ):
                resultado.dudas.append(
                    f"«{archivo.nombre}»: la declaración juramentada salió aparte, justo detrás de «{otro.nombre}»; "
                    "sin carátula va con las piezas de su paquete"
                )


# -- los nombres de lo entregado (2026-11-17) -------------------------------------------------


@dataclass(slots=True)
class NombresAuditados:
    """Lo que la auditoría encontró en los nombres de las personas de los PDF entregados de un original."""

    dudas: list[str] = field(default_factory=list)
    #: Por estado (``NOMBRE_*`` de la auditoría de filas), cuántas personas.
    cuentas: Counter = field(default_factory=Counter)


def _nombre_de_la_fila(fila: Mapping[str, object]) -> str | None:
    """El nombre de la persona de una fila de la constancia: el suyo o el de su fila del FUID (matrículas)."""
    datos = fila.get("fuid") if isinstance(fila.get("fuid"), Mapping) else {}
    nombre = str(fila.get("nombre") or datos.get("nombre") or "").strip()  # type: ignore[union-attr]
    return nombre or None


def auditar_los_nombres(
    archivos: Sequence[ArchivoEntregado],
    textos: Mapping[int, str],
    filas: Sequence[Mapping[str, object]],
    *,
    filas_del_fuid: Sequence[FuidRow] | None = None,
    lo_leido: Sequence[Mapping[str, object]] = (),
) -> NombresAuditados:
    """El nombre de cada persona de cada PDF entregado contra el texto de sus hojas del original.

    La otra mitad de la muestra de PDF (2026-11-17): la de filas ya contaba el
    nombre de cada persona. El operador: usar las herramientas de las fechas
    también para los nombres, en todas las habilidades.

    - **De quién es cada PDF:** sus filas de la constancia, por el nombre del
      PDF (``archivo_generado``) o por la hoja en que empieza si sólo una
      empieza en ella. Un acta colectiva trae a todos sus graduados.
    - **Sin filas en la constancia** -- un libro de diplomas --: las del FUID
      entregado, en orden, si son tantas como PDF; su nombre, el que va
      delante del título en el asunto (``nombre_del_asunto``).
    - **El contraste** es el del revisor de nombres, gratis
      (``nombre_en_el_texto``): una o dos letras del OCR no lo cambian. Lo que
      no aparece es duda, con su motivo: sin la IA no hay prueba de error.
    - **Un texto que no se deja leer** -- letra a mano -- no dice nada: ni bien
      ni mal, y no cuenta.
    """
    resultado = NombresAuditados()
    por_archivo: dict[str, list[Mapping[str, object]]] = {}
    por_hoja: dict[int, list[Mapping[str, object]]] = {}
    for fila in filas:
        if not isinstance(fila, Mapping) or fila.get(DE_TODO_EL_ORIGINAL):
            continue
        generado = str(fila.get("archivo_generado") or "")
        if generado:
            por_archivo.setdefault(_sin_la_carpeta(generado), []).append(fila)
        elif paginas := paginas_de_la_fila(fila):
            por_hoja.setdefault(paginas[0], []).append(fila)
    por_orden = (
        list(filas_del_fuid)
        if not filas and filas_del_fuid and len(filas_del_fuid) == len(archivos)
        else None
    )
    leido_por_hoja: dict[int, list[str]] = {}
    for leido in lo_leido:
        texto = str(leido.get("texto") or "") if isinstance(leido, Mapping) else ""
        for pagina in (leido.get("paginas") or []) if texto else []:
            if isinstance(pagina, int):
                leido_por_hoja.setdefault(pagina, []).append(texto)

    for indice, archivo in enumerate(archivos):
        suyas = por_archivo.get(_sin_la_carpeta(str(archivo.nombre)))
        if suyas is None and archivo.primera is not None:
            en_la_hoja = por_hoja.get(archivo.primera, [])
            suyas = en_la_hoja if len(en_la_hoja) == 1 else []
        nombres = [nombre for fila in suyas or [] if (nombre := _nombre_de_la_fila(fila))]
        if not nombres and por_orden is not None and (nombre := nombre_del_asunto(por_orden[indice].asunto)):
            nombres = [nombre]
        if not nombres:
            resultado.cuentas[NOMBRE_SIN_DATO] += 1
            continue
        suyos = [textos.get(p, "") or "" for p in archivo.paginas if p is not None] + [
            texto for p in archivo.paginas if p is not None for texto in leido_por_hoja.get(p, ())
        ]
        if not texto_legible(suyos):
            continue
        texto = "\n".join(suyos)
        for nombre in dict.fromkeys(nombres):
            if nombre_en_el_texto(nombre, texto):
                resultado.cuentas[NOMBRE_CONFIRMADO] += 1
            else:
                resultado.cuentas[NOMBRE_EN_DUDA] += 1
                resultado.dudas.append(f"«{archivo.nombre}»: el nombre «{nombre}» no aparece en sus hojas")
    return resultado


def titulo_del_archivo(nombre: str, prefijo: str = "") -> str:
    """El título de un PDF entregado, para casarlo con su fila del Índice Electrónico: sin número, sin su UPD, sin signos.

    «04_RECLAMO-RE2310202405234.pdf» es «RECLAMORE2310202405234», como su fila
    «RECLAMO-RE2310202405234»; «01_NIC 5940155-11_01_DOCUMENTO.pdf» y
    «UPD2998726_01_DOCUMENTO.pdf», «DOCUMENTO»: el número y el nombre de su
    origen delante, como quedaron en una carpeta de NIC.
    """
    stem = PurePath(str(nombre).replace("\\", "/")).stem
    for _ in range(3):
        stem = re.sub(r"^\d+_", "", stem)
        if prefijo and stem.casefold().startswith(f"{prefijo}_".casefold()):
            stem = stem[len(prefijo) + 1 :]
        elif hallado := re.match(r"^UPD\d+_", stem, re.IGNORECASE):
            stem = stem[hallado.end() :]
    return _clave(stem)


def _clave(texto: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", plano(texto))


def filas_del_indice_con_su_pdf(
    indice: Sequence[Mapping[str, object]],
    archivos: Sequence[ArchivoEntregado],
    *,
    prefijo: str = "",
    origen: str = "",
) -> list[dict]:
    """Las filas del Índice Electrónico de un PDF, cada una con el PDF entregado que es suyo (2026-11-10).

    La caja de correspondencia no deja filas en la constancia: su inventario es
    el índice, con el título y la fecha de cada documento y sus páginas, en
    orden de fecha y no de hojas. Se casan por **título y páginas**: el título
    es el nombre del PDF sin su número, y las páginas, las que tiene. Varios PDF
    con el mismo título y las mismas páginas se casan sólo si sus filas dicen la
    misma fecha: adivinar cuál es de cuál sería auditar la fecha de otro. La
    fila sin fecha («S.F.») no tiene qué auditar.
    """
    filas: dict[tuple[str, int], list[Mapping[str, object]]] = {}
    for fila in indice:
        if not isinstance(fila, Mapping) or not fila.get("fecha_creacion"):
            continue
        clave = (_clave(fila.get("nombre")), int(fila.get("paginas") or 0))
        filas.setdefault(clave, []).append(fila)
    pdfs: dict[tuple[str, int], list[ArchivoEntregado]] = {}
    for archivo in archivos:
        pdfs.setdefault((titulo_del_archivo(archivo.nombre, prefijo), len(archivo.paginas)), []).append(archivo)
    casadas: list[dict] = []
    for clave, suyos in pdfs.items():
        suyas = filas.get(clave) or []
        fechas = {str(f.get("fecha_creacion"))[:10] for f in suyas}
        if not suyas or len(suyas) != len(suyos) or (len(suyos) > 1 and len(fechas) > 1):
            continue
        fecha = next(iter(fechas))
        casadas.extend(
            {"archivo_generado": archivo.nombre, "fecha_inicial": fecha, "fecha_final": fecha, "archivo": origen}
            for archivo in suyos
        )
    return casadas


def auditar_las_fechas(
    archivos: Sequence[ArchivoEntregado],
    textos: Mapping[int, str],
    filas: Sequence[Mapping[str, object]],
    *,
    regla: str,
    juez: JuezDeDatos | None = None,
    ventana: tuple[int, int] | None = None,
    lo_leido: Sequence[Mapping[str, object]] = (),
) -> FechasAuditadas:
    """La fecha inicial y la final de cada PDF entregado contra el texto de sus hojas del original.

    De lo barato a lo caro, como el revisor de fechas al procesar:

    1. el contraste con el texto ya leído (la capa), gratis, para todos, con
       los años del libro (``ventana``);
    2. lo dudoso de todos los PDF, **en una pregunta** a la IA -- de
       ``DOCUMENTOS_POR_PREGUNTA`` en ``DOCUMENTOS_POR_PREGUNTA`` --, cada dato
       con una clave corta («d1_fecha_inicial»): con el nombre del PDF en la
       clave, la IA podía copiarla mal y su respuesta se perdía (2026-11-10);
    3. cada uno decidido por ``revisar_las_fechas`` con su parte de la
       respuesta: la cita vale sólo si está en **sus** hojas.

    Lo corregido con prueba es error (lo entregado no es lo que dice el
    papel), lo que queda en duda va con su motivo, y un PDF sin fila, sin
    fechas o sin texto no dice nada: ni bien ni mal. Tampoco el que tiene un
    texto que no se deja leer -- letra a mano --: lo confirmado vale y lo demás
    queda sin dato, sin pagar la IA (2026-11-10). La fecha fuera de los años
    del libro es duda sin preguntar.

    Las filas ``DE_TODO_EL_ORIGINAL`` -- las puntas de Kingspan -- se auditan
    contra sus hojas del original, no contra un PDF.

    ``lo_leido`` es lo que un lector leyó en el papel al procesar y la capa no
    trae (``constancia.lo_leido``): la fecha a mano que transcribió la IA, la
    del sello de tinta. Se suma al papel de sus hojas. Sin ello, la fecha bien
    leída a mano salía «no escrita en el documento» (3807860, 2026-11-11).
    """
    resultado = FechasAuditadas()
    documentos: list[_Documento] = []
    la_suya = filas_por_archivo([f for f in filas if not f.get(DE_TODO_EL_ORIGINAL)])
    leido_por_hoja: dict[int, list[str]] = {}
    for leido in lo_leido:
        texto = str(leido.get("texto") or "") if isinstance(leido, Mapping) else ""
        for pagina in (leido.get("paginas") or []) if texto else []:
            if isinstance(pagina, int):
                leido_por_hoja.setdefault(pagina, []).append(texto)
    for archivo in archivos:
        fila = la_suya(archivo)
        fechas = fechas_de_la_fila(fila) if fila is not None else None
        if fechas is None:
            continue
        suyas = tuple(textos.get(p, "") or "" for p in archivo.paginas if p is not None) + tuple(
            texto for p in archivo.paginas if p is not None for texto in leido_por_hoja.get(p, ())
        )
        documentos.append(_Documento(archivo.nombre, fechas, suyas))
    total = max(textos, default=0)
    for orden, fila in enumerate(f for f in filas if f.get(DE_TODO_EL_ORIGINAL)):
        fechas = fechas_de_la_fila(fila)
        tramo = paginas_de_la_fila(fila, total or None)
        if fechas is None or tramo is None:
            continue
        nombre = str(fila.get("punta") or f"tramo {orden + 1}")
        documentos.append(_Documento(nombre, fechas, hojas_de_la_punta(fila, textos, tramo)))

    for documento in documentos:
        documento.legible = texto_legible(documento.textos)
        documento.contraste = contrastar_las_fechas(documento.fechas, documento.textos, regla=regla, ventana=ventana)
        documento.revision = fechas_sin_prueba_si_no_se_leen(documento.contraste, legible=documento.legible)

    respuestas: dict[int, dict | None] = {}
    if juez is not None:
        dudosos = [
            (numero, documento, preguntas)
            for numero, documento in enumerate(documentos)
            if documento.legible and (preguntas := _lo_que_se_pregunta(documento))
        ]
        for desde in range(0, len(dudosos), DOCUMENTOS_POR_PREGUNTA):
            respuestas.update(_una_pregunta(dudosos[desde : desde + DOCUMENTOS_POR_PREGUNTA], juez))

    for numero, documento in enumerate(documentos):
        if documento.legible:
            juez_suyo = _Contestado(respuestas[numero], documento.una_sola) if numero in respuestas else None
            revisadas = revisar_las_fechas(
                documento.fechas,
                documento.textos,
                regla=regla,
                juez=juez_suyo,
                ventana=ventana,
                contraste=documento.contraste,
            )
            estado, correcciones, motivos = revisadas.estado, revisadas.correcciones, revisadas.motivos
            preguntadas = revisadas.preguntadas_a_la_ia
        else:
            estado, correcciones, motivos = _sin_la_ia(documento)
            preguntadas = 0
        resultado.cuentas[_ESTADO_DE_LA_AUDITORIA.get(estado, FECHAS_SIN_DATO)] += 1
        resultado.preguntadas += min(preguntadas, 1) if documento.una_sola else preguntadas
        dicho = "la fecha" if documento.una_sola else None
        if estado == CORREGIDA:
            vistas = set()
            for correccion in correcciones:
                texto = error_de_fecha(correccion, documento.fechas, dicho=dicho)
                if texto not in vistas:
                    vistas.add(texto)
                    resultado.errores.append(f"«{documento.nombre}»: {texto}")
        elif estado == A_REVISION:
            resultado.dudas.append(f"«{documento.nombre}»: " + "; ".join(_sin_repetir(motivos, documento.una_sola)))
    return resultado


#: El número de un documento de Kingspan: «001-CEE-00000557», «DSS 1747».
_CODIGO_DE_KINGSPAN = re.compile(r"(?:\d+\s*)?([A-Z]{2,3})\s*0*(\d+)$")


def hojas_de_la_punta(
    fila: Mapping[str, object], textos: Mapping[int, str], tramo: tuple[int, int]
) -> tuple[str, ...]:
    """El texto de las hojas de una punta de Kingspan: las que traen su número, o todo su tramo si ninguna.

    Al procesar, cada punta se revisa contra su hoja. Contra las seiscientas
    hojas de una UPD, cualquier fecha propia de otro documento la confirmaba:
    con la fecha corrida un día, 12 de 23 puntas de nueve UPD seguían
    «confirmadas» (medido el 2026-11-10). Con las hojas que traen su número
    -- «001-CEE-00000557» leído como «CEE 557» -- se mira donde va.

    El texto plano de las hojas se saca una vez por documento (``_planos``):
    las cuatro puntas de un UPD lo pedían, cada una, de todas sus hojas.
    """
    del_tramo = tuple(textos.get(p, "") or "" for p in range(tramo[0], tramo[1] + 1))
    hallado = _CODIGO_DE_KINGSPAN.search(plano(fila.get("su_numero")))
    if hallado:
        serie, numero = hallado.group(1), hallado.group(2).lstrip("0") or "0"
        patron = re.compile(rf"\b{serie}\s*0*{numero}\b")
        suyas = tuple(
            texto for texto, llano in zip(del_tramo, _planos(del_tramo), strict=True) if patron.search(llano)
        )
        if suyas:
            return suyas
    return del_tramo


@lru_cache(maxsize=4)
def _planos(textos: tuple[str, ...]) -> tuple[str, ...]:
    """El texto plano de cada hoja de un tramo: las mismas hojas, en el mismo orden, son el mismo documento."""
    return tuple(plano(texto) for texto in textos)


def _lo_que_se_pregunta(documento: _Documento) -> list[tuple[str, str]]:
    """Los campos dudosos de un documento que una cita puede decidir, y su valor; una sola vez si es una fecha.

    Lo que va derecho a duda (``para_la_ia=False``: fuera de los años del
    libro) no se paga.
    """
    revision = documento.revision
    return [
        (p.campo, p.valor)
        for p in (revision.preguntas if revision is not None else ())
        if getattr(p, "para_la_ia", True) and (not documento.una_sola or p.campo == "fecha_inicial")
    ]


def _sin_la_ia(documento: _Documento) -> tuple[str, tuple, tuple[str, ...]]:
    """Cómo quedan las fechas de un documento cuyo texto no se lee: sólo con lo que el contraste dejó."""
    revision = documento.revision or RevisionDeFechas()
    motivos = [p.duda for p in revision.preguntas]
    fechas = documento.fechas
    if fechas.inicial and fechas.final and fechas.final < fechas.inicial:
        motivos.append(f"la fecha final {fecha_escrita(fechas.final, fechas.precision)} es anterior a la inicial")
    if motivos:
        return A_REVISION, (), tuple(motivos)
    return (CONFIRMADA if revision.confirmadas else SIN_DATO), (), ()


def _una_pregunta(
    dudosos: Sequence[tuple[int, _Documento, list[tuple[str, str]]]], juez: JuezDeDatos
) -> dict[int, dict | None]:
    """Lo dudoso de varios PDF en una sola pregunta: su texto, cada uno con su rótulo corto, y sus campos."""
    cuota = TEXTO_PARA_LA_IA // max(1, len(dudosos))
    partes = []
    datos = []
    for orden, (_, documento, preguntas) in enumerate(dudosos, start=1):
        partes.append(f"=== DOCUMENTO d{orden}: «{documento.nombre}» ===\n" + "\n".join(documento.textos)[:cuota])
        datos.extend({"campo": f"d{orden}_{campo}", "valor": valor} for campo, valor in preguntas)
    try:
        respuesta = juez.verificar("\n\n".join(partes), datos)
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 - una IA que falla deja las dudas como dudas
        logger.warning("la IA de la auditoría no contestó las fechas", exc_info=True)
        respuesta = None
    suyas: dict[int, dict | None] = {}
    for orden, (numero, _, preguntas) in enumerate(dudosos, start=1):
        if not respuesta:
            suyas[numero] = None
            continue
        suyas[numero] = {
            campo: dicho for campo, _ in preguntas if (dicho := respuesta.get(f"d{orden}_{campo}")) is not None
        }
    return suyas


class _Contestado:
    """La parte de la respuesta de la IA que le toca a un PDF, servida como si se la preguntara a él solo."""

    def __init__(self, respuesta: dict | None, una_sola: bool) -> None:
        self._respuesta = respuesta
        self._una_sola = una_sola

    def verificar(self, texto: str, datos: list[dict[str, str]]):
        if self._respuesta is None:
            return None
        respuesta = dict(self._respuesta)
        if self._una_sola and "fecha_inicial" in respuesta:
            # La misma fecha en las dos puntas: se preguntó una vez.
            respuesta.setdefault("fecha_final", respuesta["fecha_inicial"])
        return respuesta


def _sin_repetir(motivos: Sequence[str], una_sola: bool) -> list[str]:
    """Los motivos de la duda, sin decir dos veces lo mismo de una fecha que va en las dos puntas."""
    vistos: list[str] = []
    for motivo in motivos:
        if una_sola:
            if motivo.startswith("la fecha final"):
                continue
            motivo = motivo.replace("la fecha inicial", "la fecha")
        if motivo not in vistos:
            vistos.append(motivo)
    return vistos
