"""Separar una caja revuelta en los documentos que la forman.

Sin OCR y sin visión: se decide sobre la capa de texto y sobre dónde están los
renglones, que es lo que hace que una caja de cien páginas se resuelva en
segundos y no en minutos. Un escaneo sin capa de texto no rompe nada aquí --
las huellas salen vacías, ninguna costura tiene evidencia y todas van a
revisión -- pero tampoco se separa solo, y eso tiene que verse en el informe en
vez de descubrirse abriendo los archivos.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...application.progress import ProgressEvent, Stage
from .planillas import _escribir_indice
from .taller import Taller, _anunciar

#: Los títulos de lo que no es un escrito del trámite: no toman el RE del
#: trámite en que caen (UPD2326311 p1, UPD2326314 p3, UPD2320047 p7).
_FORMATOS_SIN_RE_AJENO = ("ACTA", "LEY HABEAS", "AUTORIZACION", "SOLICITUD", "CONTRATO", "CERTIFICADO")


def _segment_job(payload: dict, task, *, avisos: Sequence[str] = ()) -> dict:
    """Un PDF por unidad documental, cortando costura por costura.

    ``avisos`` son las advertencias que el despachador ya reunió sobre la ruta
    elegida -- que el papel dice ser un legajo de resoluciones, por ejemplo --
    y que van al informe además de al progreso.
    """
    from dataclasses import replace

    from ...adapters.casillas_de_la_guia import fecha_de_la_guia
    from ...adapters.pymupdf_assembler import PyMuPDFAssembler
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...adapters.tesseract_ocr import (
        PSM_TEXTO_DISPERSO,
        PSM_UNA_LINEA,
        TesseractConfig,
        TesseractOcr,
    )
    from ...application.ports import Band

    #: Dónde va la rejilla de casillas en la guía de LECTA de hoja entera.
    BANDA_DE_LA_REJILLA = Band(0.0, 0.10, 1.0, 0.35)
    from ...application.agrupacion import (
        Agrupacion,
        agrupar_por_mes,
        agrupar_por_tramite,
        leer_paginas,
    )
    from ...application.anexos_declarados import (
        clase_de_soporte,
        nombrar_sin_soporte,
        retener_anexos,
        unir_el_acuerdo_de_pago,
        unir_soportes,
        verificar_en_el_documento,
    )
    from ...application.entrega import Destino, entregar
    from ...application.segment_document import SegmentDocument
    from ...application.segment_split import group_by_segment
    from ...application.sellos import (
        cortar_por_sellos,
        dividir_por_tramite,
        hojas_que_pueden_llevar_sello,
        la_ultima_hoja_sola,
        leer_sellos,
        retener_los_folios,
        separar_las_actas,
        unir_lo_que_no_abre,
    )
    from ...domain.fingerprint import nic_de_la_caja
    from ...domain.naming import DOCUMENT_PREFIX, document_folder
    from ...domain.segmentation import Verdict
    from ...domain.sello import (
        claves_del_envio,
        es_guia_de_envio,
        lleva_etiqueta_de_envio,
        numero_del_acta_de_suspension,
    )
    from ...domain.tramites import radicado_de

    taller = Taller.desde(payload)
    agrupacion = taller.agrupacion()
    # Los PDF de una caja van juntos y bajo el nombre de la caja. La carpeta del
    # trabajo sigue siendo la de arriba -- es la que la pantalla y la descarga
    # saben encontrar -- pero quien abra el disco ve "UPD2366126" y no un
    # identificador de treinta y dos letras que no le dice de qué documento es.
    carpeta = document_folder(taller.name)
    destination = taller.destination / carpeta

    # 1. Decidir los grupos: costura por costura, con la fuente abierta, y
    #    después del corte y no antes preguntarle a cada documento qué es --
    #    ahora tiene bordes, así que la pregunta tiene una sola respuesta.
    # Si taller.source es un directorio, unir todos los PDFs en él
    if taller.source.is_dir():
        import tempfile
        from pathlib import Path

        import fitz
        
        # Buscar todos los PDFs en el directorio
        pdf_files = sorted([f for f in taller.source.iterdir() if f.suffix.lower() == '.pdf'])
        if not pdf_files:
            raise ValueError(f"El directorio {taller.source} no contiene archivos PDF")
        
        # Unir todos los PDFs en uno temporal
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp_path = Path(tmp.name)
        
        merged = fitz.open()
        for pdf_file in pdf_files:
            doc = fitz.open(pdf_file)
            merged.insert_pdf(doc)
            doc.close()
        merged.save(tmp_path)
        merged.close()
    else:
        tmp_path = taller.source
    
    # -- El orden de los filtros --------------------------------------------
    # Lo pidió el operador: «agrégales un orden de ejecución lógico». Cada hoja
    # se lee una sola vez, y los filtros van del indicio más fuerte al más
    # débil; ninguno deshace lo que decidió uno anterior:
    #
    #   LECTURA  L1  el texto de cada hoja: su capa, o la OCR si no la trae.
    #            L2  el sello de radicación, leído aparte y sólo donde puede ir.
    #   CORTE    F1  continuidad hoja contra hoja (la segmentación).
    #            F2  sello: cada sello nuevo abre un documento; la carta con la
    #                etiqueta de envío de LECTA también, y la guía de entrega
    #                que va justo antes de ella es suya.
    #            F3  lista de ANEXOS: lo que el escrito declara se queda con él.
    #            F4  cédula y factura nunca solas: van con la hoja anterior.
    #   TRÁMITE  F5  mismo RE -- del sello o del texto --, mismo trámite; un
    #                sello ilegible corta hasta el próximo RE o sello; la fecha
    #                reparte las hojas que no traen ninguno.
    #            F5b la última hoja de la caja, si trae sello, va sola.
    #   NOMBRE   F6  título directo, radicado y fecha.
    source = PyMuPDFPageSource(tmp_path, taller.name)
    workers = int(taller.settings.get("page_workers") or 4)
    try:
        page_count = source.page_count
        # F1. Continuidad: costura por costura, con la fuente abierta.
        segmentacion = SegmentDocument(
            oracle=taller.oraculo_de_bordes(),
            reporter=taller.progress,
            control=taller.control,
            # La cinta la pinta L1, con lo que de verdad se leyó. Pintada aquí,
            # la hoja sin capa legible -- la guía de LECTA de UPD2320047, un
            # recorte pequeño -- salía como «enviada a revisión» aunque L1 la
            # lee y la guía se une a su carta.
            marcar_paginas=False,
        ).run(source)
        grupos = group_by_segment(segmentacion.segments, source.text_of)
        # El NIC del suscriptor, que es de la caja entera y no de ninguno de
        # sus documentos. No decide ningún corte -- lo llevan todas las hojas
        # -- pero es con lo que el archivo identifica el expediente, y la
        # entrega en carpeta lo usa para nombrar la carpeta de destino.
        nic = nic_de_la_caja(segmentacion.fingerprints)
        # L1. Cada hoja leída: estas cajas suelen ser escaneos sin capa de
        # texto, y sin leerlas no hay título, ni fecha, ni radicado que poner
        # en el índice -- salía «DOCUMENTO», «S.F.» --. Se leen siempre, se
        # agrupe como se agrupe; la hoja que trae capa de texto no pasa por la
        # OCR. Con el motor que eligió el operador.
        leidas = leer_paginas(
            source,
            taller.ocr(),
            workers=workers,
            control=taller.control,
            avance=lambda hechas, total: _anunciar(
                payload,
                Stage.GROUPING,
                detail="leyendo el título y la fecha de cada página",
                done=hechas,
                total=total,
            ),
            marcar=lambda pagina, procedencia: taller.progress.emit(
                ProgressEvent(
                    stage=Stage.PAGE,
                    page_number=pagina,
                    page_count=page_count,
                    provenance=procedencia,
                )
            ),
        )
        textos = {p: source.text_of(p) for p in range(1, page_count + 1)}
        textos.update({p: t for p, t in leidas.textos.items() if t})
        # L2. El sello de radicación de cada hoja que puede llevarlo, leído
        # aparte con el OCR de casa. Los radicados bien escritos en la caja
        # corrigen la cifra que la OCR del sello leyó mal.
        conocidos = {r for r in map(radicado_de, textos.values()) if r and r.startswith("RE")}
        sellos = leer_sellos(
            source,
            TesseractOcr(TesseractConfig(min_word_confidence=0)),
            hojas_que_pueden_llevar_sello(textos),
            # El número, con el OCR de pago si el operador eligió «OCR + IA»:
            # sólo la etiqueta de cada hoja con sello, que es donde el de casa
            # yerra una cifra.
            de_pago=taller.lector_de_pago(),
            conocidos=conocidos,
            workers=workers,
            control=taller.control,
            # El renglón del número de la etiqueta que nada dejó leer, solo y
            # más fino, de dos maneras: vale si las dos dan el mismo.
            lectores_del_renglon=(
                TesseractOcr(TesseractConfig(min_word_confidence=0, psm=PSM_UNA_LINEA)),
                TesseractOcr(TesseractConfig(min_word_confidence=0)),
            ),
            avance=lambda hechas, total: _anunciar(
                payload,
                Stage.GROUPING,
                detail="leyendo el sello de radicación",
                done=hechas,
                total=total,
            ),
        )
        # L3. La fecha de entrega que el mensajero marcó en cada guía de
        # LECTA: el día y el mes con una X, el año de la fecha impresa.
        lector_de_rejillas = TesseractOcr(
            TesseractConfig(min_word_confidence=0, psm=PSM_TEXTO_DISPERSO)
        )
        fechas_de_guia = {}
        for p, texto in textos.items():
            if es_guia_de_envio(texto or ""):
                try:
                    imagen = source.render(p, BANDA_DE_LA_REJILLA, 300)
                    fechas_de_guia[p] = fecha_de_la_guia(
                        imagen, lector_de_rejillas.palabras(imagen), texto or ""
                    )
                except Exception:  # noqa: BLE001 - sin la fecha marcada, la del texto
                    fechas_de_guia[p] = None
    finally:
        source.close()
    # La fecha del sello fecha la hoja que no trae otra.
    leidas = replace(
        leidas,
        fechas={
            p: f or (sellos[p].fecha if p in sellos else None) for p, f in leidas.fechas.items()
        },
    )
    dudosas = [b for b in segmentacion.boundaries if b.verdict is Verdict.UNDECIDED]
    # De qué documento es cada anexo. Se calculaba y no salía a ninguna parte,
    # así que un acta con sus cuatro fotografías era indistinguible de un acta de
    # cinco hojas, que es justo la relación que el veredicto ATTACHMENT existe
    # para no perder.
    anexos = {
        grupo.code.value: segmento.attachment_pages
        for grupo, segmento in zip(grupos.groups, segmentacion.segments, strict=False)
        if segmento.attachment_pages
    }
    # La lista de «ANEXOS» de cada escrito: lo que nombra y aparece detrás se
    # une al escrito, y lo que no aparece se declara. Va antes de agrupar por
    # trámite o por mes, que trabajan sobre los documentos ya completos; y las
    # costuras que la lista decidió ya no piden que nadie las mire.
    # F2. Sello: cada sello nuevo abre un documento, aunque el corte lo hubiera
    # dejado a mitad de otro. Y la etiqueta de envío de LECTA, con la guía de
    # entrega que la precede.
    guias = {p for p, texto in textos.items() if es_guia_de_envio(texto or "")}
    etiquetas = {p for p, texto in textos.items() if lleva_etiqueta_de_envio(texto or "")}
    grupos, anexos, cortes_por_sello = cortar_por_sellos(
        grupos,
        sellos,
        anexos,
        etiquetas=etiquetas,
        guias=guias,
        # La guía se empareja con su carta por el número de guía, que llevan
        # las dos; sin él, por su posición.
        envios={p: claves_del_envio(textos.get(p, "") or "") for p in guias | etiquetas},
    )
    # F2c. Cada acta de suspensión es su documento, por su número impreso
    # (lo dictó el operador: «ese tipo de documentos en específico van
    # separados»; UPD2326309, tres actas seguidas).
    grupos, anexos, actas = separar_las_actas(
        grupos, {p: numero_del_acta_de_suspension(t or "") for p, t in textos.items()}, anexos
    )
    abren = {g.page_numbers[0] for g in grupos.groups if g.page_numbers[0] in sellos or g.page_numbers[0] in etiquetas or g.page_numbers[0] + 1 in etiquetas or g.page_numbers[0] in actas}
    # F2b. Los folios del sello: lo que la oficina recibió como un escrito
    # -- «Folios: 19» -- no lo parte la continuidad. Sólo otro sello o la
    # etiqueta de LECTA abren algo dentro de esas hojas.
    grupos, anexos, por_folios = retener_los_folios(grupos, sellos, abren, anexos)
    # F3. Lista de ANEXOS.
    retencion = retener_anexos(grupos, textos, anexos, abren=abren)
    grupos, anexos = retencion.grupos, retencion.anexos
    # F4. Y la cédula y la factura nunca van solas: si el corte dejó una
    # abriendo documento, vuelve al PDF de la página anterior.
    soportes = unir_soportes(grupos, textos, anexos, abren=abren)
    grupos, anexos = soportes.grupos, soportes.anexos
    # F4b. El acuerdo de pago -- pagarés, cartas de instrucciones,
    # reconocimiento de deuda, simulador -- es un solo documento, sin RE.
    grupos, anexos, del_acuerdo = unir_el_acuerdo_de_pago(grupos, textos, anexos, abren=abren)
    dudosas = [
        b
        for b in dudosas
        if b.right not in retencion.retenidas
        and b.right not in soportes.movidas
        and b.right not in cortes_por_sello
        and b.right not in por_folios
        # Ni la costura que dejó detrás un soporte -- el certificado, la
        # factura, la cédula --: ésa la decidió la regla de los soportes, con
        # evidencia, no la duda (UPD2326306, UPD2326322).
        and clase_de_soporte(textos.get(b.right, "") or "") is None
    ]
    # Los documentos tal como salieron del corte, con su título y su fecha.
    # Al agrupar por trámite o por mes un archivo junta varios, y el índice
    # tiene que poder decir qué trae dentro: es el detalle de cada fila.
    from ...application.clasificacion import describir

    # La fecha de cada uno es la de su primera hoja fechada: la del
    # encabezado del escrito, «Valledupar, diciembre 02 de 2020», o la de la
    # citación, «VALLEDUPAR, 2020/12/07». No la más reciente del texto, que en
    # un reclamo es la de los hechos y en una hoja mal leída es basura. La
    # cédula no fecha nada: su fecha es la de nacimiento.
    from ...domain.asunto_del_documento import (
        ACUERDO_DE_PAGO,
        asunto_del_documento,
        titulo_del_documento,
    )
    from ...domain.tramites import es_cedula, radicado_del_sello

    # Hasta dónde se busca el título: el escrito pide en sus primeras hojas, y
    # lo que viene detrás son sus anexos.
    PAGINAS_DEL_TITULO = 6

    def fecha_de_la_hoja(pagina: int):
        texto = textos.get(pagina, "") or ""
        if es_cedula(texto):
            return None
        return leidas.fechas.get(pagina)

    cortados = describir(
        nombrar_sin_soporte(grupos, textos), lambda pagina: textos.get(pagina, "") or ""
    ).groups

    def describir_piezas(entregados) -> list[dict]:
        """Cada documento del corte, partido por el archivo en que acabó.

        Un trámite puede llevarse sólo parte de un documento del corte -- dos
        constancias que el corte unió y que son de dos radicados --, y el título
        y la fecha de cada parte tienen que ser los suyos, no los de la otra.
        """
        piezas = []
        for entregado in entregados:
            suyas = set(entregado.page_numbers)
            for cortado in cortados:
                paginas = [p for p in cortado.page_numbers if p in suyas]
                if not paginas:
                    continue
                # La guía de entrega no titula ni fecha: es la carta que la
                # sigue la que dice qué es y de cuándo.
                titulares = [p for p in paginas if p not in guias] or paginas
                acuerdo = paginas[0] in del_acuerdo
                if acuerdo:
                    # El acuerdo se titula y se fecha por su reconocimiento
                    # de deuda, que es lo que el usuario firmó y fechó.
                    titulares = [
                        p
                        for p in paginas
                        if titulo_del_documento(textos.get(p, "") or "") == ACUERDO_DE_PAGO
                    ] or titulares
                # La fecha del documento, de lo más cierto a lo menos: la que
                # el mensajero marcó en la guía, la del sello de radicación y,
                # si no trae ninguna, la de su primera hoja fechada.
                primera = (
                    next((fechas_de_guia[p] for p in paginas if fechas_de_guia.get(p)), None)
                    or next(
                        (sellos[p].fecha for p in paginas if p in sellos and sellos[p].fecha),
                        None,
                    )
                    or next(
                        (f for p in titulares if (f := fecha_de_la_hoja(p)) is not None), None
                    )
                )
                piezas.append(
                    {
                        "pages": paginas,
                        "type": cortado.kind,
                        "fecha": primera.isoformat() if primera else cortado.fecha,
                        # Lo que el documento dice ser en su primera hoja --
                        # «DERECHO DE PETICION», «RESPUESTA A RECLAMACION» --,
                        # que es el título de su fila en el índice.
                        "titulo": ACUERDO_DE_PAGO
                        if acuerdo
                        else titulo_del_documento(
                            textos.get(titulares[0], "") or "", cortado.kind
                        ),
                        # Y su radicado: el del sello si lo trae, si no el que
                        # cite su texto. El acuerdo de pago no lleva.
                        "radicado": None if acuerdo else next(
                            (
                                r
                                for p in paginas
                                if (r := (sellos[p].radicado if p in sellos else None)
                                    or radicado_de(textos.get(p, "") or "")
                                    or radicado_del_sello(textos.get(p, "") or ""))
                            ),
                            None,
                        ),
                        # De qué trata, con sus palabras. Va al informe.
                        "asunto": asunto_del_documento(
                            [textos.get(p, "") or "" for p in paginas[:PAGINAS_DEL_TITULO]],
                            cortado.kind,
                        ),
                    }
                )
        return piezas
    # Un archivo por mes, si el operador lo pidió. Va después de los anexos
    # y no antes: se emparejan con los segmentos por posición, y la posición
    # sólo es la del corte mientras los documentos no se hayan unido.
    #
    # Y con él cambia lo que se manda a revisión. Una costura dudosa entre dos
    # documentos ya no decide ningún archivo -- lo que sale es un mes, no un
    # documento --, así que no se pide que nadie la mire. Lo que sí se declara
    # es la página sin fecha que quedó entre dos meses distintos, porque ahí
    # unirla a la anterior fue una elección.
    costuras_en_revision = dudosas
    sin_fecha_en_revision = []
    tramite_en_revision = []
    avisos_de_agrupacion = []
    entregado_por = Agrupacion.DOCUMENTO
    if agrupacion is Agrupacion.TRAMITE:
        # F5. Trámite: mismo RE, mismo trámite.
        por_tramite = agrupar_por_tramite(
            grupos, leidas, anexos, retenidas=retencion.retenidas, sellos=sellos
        )
        avisos_de_agrupacion.append(por_tramite.aviso())
        if por_tramite.agrupo:
            # Manda el sello: los archivos son los documentos ya cortados, que
            # sólo se juntan con el anterior cuando traen su mismo RE y no abren
            # nada propio. Del recorrido por RE y fecha se toma el trámite de
            # cada hoja, con el que se nombra lo que no trae RE.
            # Sin la hoja que el recorrido dejó en un trámite sin evidencia -- ni
            # RE ni fecha --: ponerle ese RE sería nombrarla con el de otro.
            sin_evidencia = {h.page for h in por_tramite.en_revision}
            del_tramite = {
                p: g.code.raw
                for g in por_tramite.grupos.groups
                for p in g.page_numbers
                if p not in sin_evidencia and p not in del_acuerdo
            }
            # El RE propio de una hoja con sello es el de su sello, y sólo
            # ése: el que cita su texto -- «CONTRA LA RECLAMACIÓN N° RE…»,
            # «dando respuesta al RE…» -- es el de otro trámite (UPD2326324
            # p8). La hoja sin sello sí se reconoce por el RE que cita: la
            # respuesta o la notificación de la empresa.
            propios = {
                p: sellos[p].radicado if p in sellos else radicado_de(textos.get(p, "") or "")
                for g in grupos.groups
                for p in g.page_numbers
            }
            # Lo que no es un escrito del trámite no se nombra con su RE: el
            # acta, la autorización de habeas data o de notificación, la
            # solicitud de un formato.
            def sin_re_ajeno(paginas: list[int]) -> bool:
                # El escrito con su propio sello, aunque no se le lea el
                # número, es un radicado nuevo: no hereda el de un documento
                # anterior (UPD2326316 p8, sello de tinta con el RE a mano).
                # Sí toma el que le cita después la respuesta que le contesta
                # (UPD2321099: la citación de la p10 cita el RE de la
                # petición de la p1).
                if paginas[0] in sellos:
                    suyo = del_tramite.get(paginas[0])
                    citado_antes = any(r == suyo for p, r in propios.items() if p < paginas[0])
                    citado_despues = any(r == suyo for p, r in propios.items() if p > paginas[-1])
                    return citado_antes or not citado_despues
                primera = next((x for x in paginas if x not in guias), paginas[0])
                titulo = titulo_del_documento(textos.get(primera, "") or "", None)
                return titulo.startswith(_FORMATOS_SIN_RE_AJENO) or titulo == DOCUMENT_PREFIX

            grupos, anexos = dividir_por_tramite(
                grupos, propios, del_tramite, abren, anexos, sin_re_ajeno=sin_re_ajeno
            )
            # Un trámite hecho sólo de cédulas o facturas iría solo.
            sueltos = unir_soportes(
                grupos, textos, anexos, solo_si_queda_solo=True, abren=abren
            )
            grupos, anexos = sueltos.grupos, sueltos.anexos
            costuras_en_revision = []
            sin_fecha_en_revision = []
            tramite_en_revision = por_tramite.en_revision
            entregado_por = Agrupacion.TRAMITE
        else:
            tramite_en_revision = por_tramite.en_revision
    elif agrupacion is Agrupacion.MES:
        por_mes = agrupar_por_mes(
            grupos, leidas.fechas, anexos, tipos=leidas.tipos, asuntos=leidas.asuntos
        )
        avisos_de_agrupacion.append(por_mes.aviso())
        # Sólo si agrupó. Sin una sola página fechada la caja sale como la dejó
        # el corte, con su revisión de siempre, y el informe dice que se entregó
        # por documento: decir «mes» ahí sería afirmar algo que no se hizo.
        if por_mes.agrupo:
            grupos, anexos = por_mes.grupos, por_mes.anexos
            costuras_en_revision = []
            sin_fecha_en_revision = por_mes.en_revision
            entregado_por = Agrupacion.MES
    # F5b. La última hoja de la caja, si trae sello -- de radicación o de envío
    # --, va sola: lo dictó el operador, y manda sobre el trámite.
    grupos, anexos, ultima_sola = la_ultima_hoja_sola(grupos, set(sellos) | etiquetas, anexos, guias)
    if entregado_por is Agrupacion.TRAMITE:
        # El aviso cuenta los archivos que se escriben, no los trámites.
        avisos_de_agrupacion[0] = por_tramite.aviso(archivos=len(grupos.groups))
    # El documento que nació de un corte -- un sello, la última hoja -- no trae
    # tipo: se le pone lo que su carta dice ser, que es lo que nombra el archivo.
    from ...domain.asunto_del_documento import AUTORIZACION_DE_NOTIFICACION
    from ...domain.asunto_del_documento import titulo_del_documento as _titulo

    # F5c. Lo que no abre nada va con el anterior: sin sello, sin etiqueta de
    # LECTA, sin un título que diga qué es y sin un RE propio distinto del de
    # su vecino, no hay evidencia de que empiece otro documento. Las
    # autorizaciones -- de notificación electrónica, de habeas data --
    # tampoco abren: son de lo que el cliente firmó con ellas.
    def _re_del(g) -> str:
        return (g.code.raw or "").split()[-1] if (g.code.raw or "").startswith(("RE", "P")) else ""

    sin_apertura = set()
    for anterior, g in zip(grupos.groups, grupos.groups[1:], strict=False):
        primera = g.page_numbers[0]
        if primera in sellos or primera in etiquetas or primera + 1 in etiquetas:
            continue
        if primera in del_acuerdo or primera == ultima_sola:
            continue
        if _re_del(g) and _re_del(g) != _re_del(anterior):
            continue
        titular = next((x for x in g.page_numbers if x not in guias), primera)
        if _titulo(textos.get(titular, "") or "", None) in (
            DOCUMENT_PREFIX,
            AUTORIZACION_DE_NOTIFICACION,
            # La de datos personales va con lo que firma: el acuerdo de pago
            # (UPD2326318 p7-9), el escrito.
            "LEY HABEAS DATA",
        ):
            sin_apertura.add(primera)
    grupos, anexos, _ = unir_lo_que_no_abre(grupos, sin_apertura, anexos)
    # La lista de ANEXOS de cada escrito, verificada contra su PDF final: los
    # soportes, los folios y lo que no abría nada ya se le unieron.
    escritos = verificar_en_el_documento(retencion.escritos, grupos, textos, abren=abren)

    def _de_que_documento(pagina: int) -> str:
        """«en el documento de las págs. 1-6 (RE3110202044488)», para el aviso."""
        grupo = next((g for g in grupos.groups if pagina in g.page_numbers), None)
        if grupo is None:
            return f"en la pág. {pagina}"
        desde, hasta = grupo.page_numbers[0], grupo.page_numbers[-1]
        radicado = (grupo.code.raw or "") if (grupo.code.raw or "").startswith(("RE", "P")) else ""
        return f"en el documento de las págs. {desde}-{hasta}" + (f" ({radicado})" if radicado else "")
    if entregado_por is Agrupacion.TRAMITE:
        # La revisión del trámite se calculó hoja por hoja, antes de que el
        # sello y los folios decidieran los documentos. Sólo vale para la hoja
        # que abre un documento: la de dentro -- la segunda hoja de un recurso,
        # el certificado dentro de los folios -- ya la decidió el corte, y el
        # «se movió» de una hoja que nadie movió es falso (manda el sello). Ni
        # para la que trae su propio sello con RE: citar el RE anterior es lo
        # que hace todo recurso. Ni para el acuerdo de pago, que no es de
        # ningún trámite. Lo pidió el operador al ver la cola llena de esto.
        primeras = {g.page_numbers[0] for g in grupos.groups}
        con_sello_propio = {p for p, sello in sellos.items() if sello.radicado}

        def formato_sin_re(pagina: int) -> bool:
            # El acta, el contrato, la autorización sin sello no toman el RE de
            # ningún trámite: a cuál quedó asignada no cambia su archivo, y
            # el «se movió» no le dice nada al operador (UPD2326470 p10).
            if pagina in sellos:
                return False
            titulo = _titulo(textos.get(pagina, "") or "", None)
            return titulo.startswith(_FORMATOS_SIN_RE_AJENO)

        tramite_en_revision = [
            hoja
            for hoja in tramite_en_revision
            if hoja.page in primeras
            and hoja.page not in con_sello_propio
            and hoja.page not in del_acuerdo
            and not formato_sin_re(hoja.page)
        ]

    def tipo_del_archivo(g):
        """Lo que nombra el archivo: lo mismo que su fila del índice.

        El título de su primera hoja -- la carta, no la guía que la precede
        --; si la hoja no dice nada, el tipo del catálogo; el acuerdo de pago,
        por su nombre. Por mes no: un mes junta documentos de toda clase.
        """
        if entregado_por is Agrupacion.MES:
            return g
        if g.page_numbers[0] in del_acuerdo:
            return replace(g, kind=ACUERDO_DE_PAGO)
        primera = next((x for x in g.page_numbers if x not in guias), g.page_numbers[0])
        titulo = _titulo(textos.get(primera, "") or "", None)
        if titulo != DOCUMENT_PREFIX:
            return replace(g, kind=titulo)
        return g if g.kind else replace(g, kind=DOCUMENT_PREFIX)

    grupos = replace(grupos, groups=[tipo_del_archivo(g) for g in grupos.groups])
    # F6. El nombre. Ningún documento se llama como su anexo: el que abre con
    # un reclamo y trae una cédula detrás es el reclamo, no un «DOCUMENTO DE
    # IDENTIDAD».
    grupos = nombrar_sin_soporte(grupos, textos)
    piezas = describir_piezas(grupos.groups)
    _anunciar(
        payload,
        Stage.ASSEMBLING,
        detail="preparando la escritura",
        done=0,
        total=len(grupos.groups),
    )
    del_modelo = [b for b in segmentacion.boundaries if not b.deterministic]

    # Lo que hace falta para saber si la caja salió cara o barata, y por qué.
    # Las tres últimas reparten las costuras: lo que decidió el papel, lo que
    # decidió el modelo y lo que quedó sin decidir. Se calculan aquí, y no
    # dentro del informe, porque el inventario del documento las lleva también:
    # una planilla que no dice cómo se decidió el corte no se puede auditar.
    estadisticas = {
        "documents": len(grupos.groups),
        "seams": len(segmentacion.boundaries),
        "settled_free": len(segmentacion.boundaries) - len(dudosas) - len(del_modelo),
        "model_decided": len(del_modelo),
        "undecided": len(dudosas),
    }
    # Cuántas páginas hubo que pasar por OCR: es lo que cuesta, y con el
    # motor de pago se paga por página. Y cuántos sellos se leyeron.
    estadisticas["pages_dated_by_ocr"] = leidas.con_ocr
    estadisticas["stamps_read"] = len(sellos)

    # 2. Entregar: el tramo que es igual para las cuatro rutas. Sin prefijo en
    #    el nombre: lo forman el puesto en la caja y el tipo, y "DOCUMENTO" es
    #    el tipo de lo que nadie reconoció, no una palabra que se anteponga.
    #    Llamar "RESOLUCION_01" a lo que sale de aquí sería escribir en el
    #    disco algo que nadie comprobó.
    entregado = entregar(
        grupos,
        origen=taller.source,
        nombre=taller.name,
        paginas=page_count,
        destino=Destino(
            directorio=destination, carpeta=carpeta, entregado_en=taller.delivered_to
        ),
        assembler=PyMuPDFAssembler(
            control=taller.control,
            progress=taller.progress,
            naming_prefix=None,
            # Todo el nombre en mayúsculas, como lo pidió el operador: el RE
            # del trámite se escribe «RE3110…» y no «re3110…».
            mayusculas=True,
            nombre=taller.name,
        ),
        en_revision=[boundary.right for boundary in costuras_en_revision]
        + [pagina.page for pagina in sin_fecha_en_revision],
        estadisticas=estadisticas,
        anexos=anexos,
    )
    # 3. El informe, con lo que sólo esta ruta sabe: el NIC, los avisos y cómo
    #    se decidió cada costura.
    report = {
        "document": taller.name,
        "page_count": page_count,
        # Las unidades como las lee la pantalla, armadas donde las arman las
        # otras tres rutas. Estuvieron escritas a mano aquí, y esa copia se
        # quedaba fuera de cada arreglo que entraba por el camino común: le
        # faltaba la fecha de cada unidad, que la pantalla ya sabía leer.
        "groups": entregado.grupos_para_el_informe,
        # Una caja no deja páginas huérfanas: toda hoja pertenece al documento
        # que se estuviera leyendo, aunque todavía no se sepa cuál es.
        "quarantine": [],
        "repairs": [],
        # La costura que nadie pudo decidir NO se cortó: la hoja se queda en el
        # documento abierto, porque partir una unidad documental no deja rastro
        # de que existió y unir de más deja un archivo que esta cola nombra. Va
        # aquí, hoja por hoja, para que alguien la mire.
        "review_queue": [
            {
                "page": boundary.right,
                "reason": "no hay evidencia de si esta hoja abre un documento nuevo",
            }
            for boundary in costuras_en_revision
        ]
        # Y la página sin fecha que la agrupación por mes unió a la anterior
        # estando entre dos meses: se unió porque ante la duda se une, y se
        # declara por lo mismo.
        + [{"page": pagina.page, "reason": pagina.motivo} for pagina in sin_fecha_en_revision]
        # Las hojas que la agrupación por trámite dejó en revisión porque la
        # evidencia no alcanza para moverlas, o porque la comprobación las volvió
        # al trámite abierto aunque la fecha y el radicado no lo soporten.
        + [{"page": hoja.page, "reason": hoja.motivo} for hoja in tramite_en_revision]
        # Y el escrito que enumera anexos que no aparecen detrás.
        # Dice de qué documento es la lista: una caja trae varios escritos con
        # su propia lista, y «pág. 2» a secas se confundía con la lista de la
        # otra petición, que sí estaba completa (UPD2326315).
        + [
            {"page": escrito.pagina, "reason": f"{_de_que_documento(escrito.pagina)}: {motivo}"}
            for escrito in escritos
            if (motivo := escrito.motivo_de_revision())
        ],
        # Del inventario y no de `assembly.outputs`, aunque salgan de lo mismo:
        # dos listas construidas por caminos distintos acaban discrepando, y la
        # que manda es la que dice qué archivo tiene qué páginas. Llevan la
        # carpeta delante porque lo que la descarga recibe es la ruta dentro del
        # trabajo, no sólo el nombre del archivo.
        "outputs": entregado.salidas,
        "unwritable_pages": entregado.ilegibles,
        # Qué salió de esta caja y de qué páginas salió cada cosa. Esta ruta no
        # levanta FUID -- el formulario pide datos que sólo se saben documento a
        # documento -- pero el inventario no es el FUID: es el rastro que
        # permite ir de un archivo a sus páginas de origen y al revés, y la
        # separación por continuidad lo necesita más que ninguna otra ruta,
        # porque sus nombres son un número de orden y no dicen nada por sí solos.
        "inventory": entregado.inventario.as_dict(),
        # De qué suscriptor es esta caja. Va al informe para que la entrega en
        # carpeta pueda agrupar por él sin volver a abrir el PDF.
        "nic": nic,
        "stats": estadisticas,
        "task": str(task),
        # Qué se entregó como un archivo: cada documento o cada mes.
        "agrupar": str(entregado_por),
        # Los avisos viven en el informe y no sólo en el progreso: el progreso
        # se ve mientras corre y el informe se lee después, que es cuando el
        # operador se pregunta por qué salieron ochenta documentos.
        "notices": [
            *avisos,
            *avisos_de_agrupacion,
            *([aviso] if (aviso := retencion.aviso()) else []),
            *([aviso] if (aviso := soportes.aviso()) else []),
        ],
        # Lo que cada escrito dijo que traía contra lo que se encontró. Lo lee
        # el Índice Electrónico para sus observaciones.
        "anexos_declarados": [escrito.as_dict() for escrito in escritos],
        # Los documentos que forman cada archivo, y el expediente: la caja.
        "piezas": piezas,
        "expediente": document_folder(taller.name),
    }
    # 4. El Índice Electrónico del cliente, junto a los PDF de la caja y sin
    #    que nadie lo pida. Es el inventario de toda caja de correspondencia y
    #    ocupa el lugar de la planilla de las otras rutas: el archivo recibe un
    #    solo Excel por caja, el suyo.
    _escribir_indice(report, destination, payload)

    _anunciar(payload, Stage.DONE)
    return report
