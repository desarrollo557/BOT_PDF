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

Nada de esto lee con OCR ni paga: la huella y la capa de texto, nada más.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from ..domain.auditoria import NO_AUDITADO, PdfAuditado, veredicto
from ..domain.conciliacion import Huella, conciliar, rangos
from ..domain.revision_de_cortes import Decision, huella_para_la_ia, revisar_costuras
from .fuid import FuidRow
from .integridad_de_los_datos import auditar_los_datos
from .perfiles_de_revision import perfil_de
from .ports import JuezDeCosturas
from .revisor_de_cortes import COSTURAS_POR_PREGUNTA

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
