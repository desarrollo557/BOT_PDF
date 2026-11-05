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
   vuelve a mirar cada costura con los patrones de la habilidad. Dos pruebas
   del papel que contradicen un corte son un **error**; una sola es una
   **duda**, que decide la IA si la corrida se hizo con ella (una pregunta por
   PDF, con la huella de las hojas de alrededor); sin IA queda como duda.
3. **El índice**: si se sabe cuántas filas tiene el índice de su carpeta y
   cuántos PDF hay en ella, que sean los mismos.

Nada de esto lee con OCR ni paga: la huella y la capa de texto, nada más.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from ..domain.auditoria import NO_AUDITADO, PdfAuditado, veredicto
from ..domain.conciliacion import Huella, conciliar, rangos
from ..domain.revision_de_cortes import Decision, huella_para_la_ia, revisar_costuras
from .ports import JuezDeCosturas
from .revisor_de_cortes import (
    COSTURAS_POR_PREGUNTA,
    REGLAS_DE_LA_CORRESPONDENCIA,
    Patrones,
)

logger = logging.getLogger(__name__)

#: Las habilidades que entregan una persona por PDF: dos cédulas son dos personas.
_UNA_PERSONA = ("diploma", "acta de grado", "actas de grado", "historia")


def patrones_de(habilidad: str, textos: Mapping[int, str]) -> Patrones:
    """Los patrones con que se revisa un PDF de esa habilidad al auditarlo.

    En la caja de correspondencia, lo que por regla va lejos de su documento --
    las piezas del acuerdo y la Habeas Data, por su propio título -- no es una
    prueba de error; en las de una persona por PDF, dos cédulas sí.
    """
    nombre = (habilidad or "").lower()
    if "correspondencia" in nombre:
        from ..domain.asunto_del_documento import (
            LEY_HABEAS_DATA,
            PIEZAS_DEL_ACUERDO,
            titulo_del_documento,
        )

        cruces = {
            pagina
            for pagina, texto in textos.items()
            if titulo_del_documento(texto or "") in (*PIEZAS_DEL_ACUERDO, LEY_HABEAS_DATA)
        }
        return Patrones(cruces=frozenset(cruces), reglas=REGLAS_DE_LA_CORRESPONDENCIA)
    if any(clave in nombre for clave in _UNA_PERSONA):
        return Patrones(una_persona_por_pdf=True)
    return Patrones()


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
) -> PdfAuditado:
    """Lo que la auditoría encuentra en un PDF entregado.

    ``entregados`` son los PDF que salieron de él, por su nombre, con la huella
    de cada hoja (``None`` si no se dejó abrir), en el orden en que se
    numeraron. ``filas_del_indice`` y ``pdf_en_su_carpeta``, si se saben, son
    las filas del índice de su carpeta y los PDF que hay en ella.
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
    patrones = patrones_de(habilidad, textos)
    costuras = revisar_costuras(
        documentos,
        textos,
        cruces=patrones.cruces,
        una_persona_por_pdf=patrones.una_persona_por_pdf,
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
        huellas = [huella_para_la_ia(q, textos.get(q, "") or "") for q in ventana]
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

    if (
        filas_del_indice is not None
        and pdf_en_su_carpeta is not None
        and filas_del_indice != pdf_en_su_carpeta
    ):
        errores.append(
            f"el índice de su carpeta tiene {filas_del_indice} filas y la carpeta {pdf_en_su_carpeta} PDF"
        )

    return PdfAuditado(
        pdf,
        veredicto(errores, dudas),
        tuple(errores + dudas),
        paginas=len(origen),
        archivos=len(entregados),
        costuras=len(costuras),
        dentro_del_margen=len(costuras) - len(fuera),
        preguntadas_a_la_ia=preguntadas,
        habilidad=habilidad,
    )
