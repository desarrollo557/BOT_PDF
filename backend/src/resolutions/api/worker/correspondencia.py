"""Separar una caja revuelta en los documentos que la forman.

Sin OCR y sin visión: se decide sobre la capa de texto y sobre dónde están los
renglones, que es lo que hace que una caja de cien páginas se resuelva en
segundos y no en minutos. Un escaneo sin capa de texto no rompe nada aquí --
las huellas salen vacías, ninguna costura tiene evidencia y todas van a
revisión -- pero tampoco se separa solo, y eso tiene que verse en el informe en
vez de descubrirse abriendo los archivos.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ...application.progress import ProgressEvent, Stage
from .planillas import _escribir_indice
from .taller import Taller, _anunciar

logger = logging.getLogger(__name__)

#: Los títulos de lo que no es un escrito del trámite: no toman el RE del
#: trámite en que caen (UPD2326311 p1, UPD2326314 p3, UPD2320047 p7).
_FORMATOS_SIN_RE_AJENO = ("ACTA", "LEY HABEAS", "AUTORIZACION", "SOLICITUD", "CONTRATO", "CERTIFICADO")

#: La franja de arriba de la hoja donde va el título de un formato, y a cuánto
#: se lee. Medido sobre UPD2998726: la tabla escrita a mano hunde la confianza
#: de la página entera y su lectura se descarta, pero la franja sola a 400 ppp
#: deja leer «FORMATO DE NUEVOS SUMINISTROS O SUMINISTROS MODIFICADOS».
ALTO_DEL_ENCABEZADO = 0.22
PPP_DEL_ENCABEZADO = 400
#: Lo más largo que se deja ser al asunto cuando nombra el archivo.
MAX_ASUNTO_EN_EL_NOMBRE = 80
#: Por qué un archivo se llamó por su origen y no por lo que es.
SIN_TITULO = "sin título legible: se nombró por su caja y sus páginas"


#: Cuánto se le deja a Tesseract para leer una sola franja o una sola hoja. Los
#: 15 s de siempre no alcanzan con la carpeta entera leyéndose a la vez: el
#: 2026-10-22, con el equipo ocupado, la franja de UPD2998726 se agotó y el
#: documento salió «UPD2998726 PAGINAS 1-3» en vez de «FORMATO DE NUEVOS
#: SUMINISTROS O SUMINISTROS MODIFICADOS».
SEGUNDOS_PARA_UNA_HOJA = 90.0
#: Cuántas veces se intenta la franja con el OCR de casa.
INTENTOS_DE_LA_FRANJA = 2


def _titulo_del_encabezado(fuente, pagina: int, lector, de_pago=None) -> str | None:
    """El título impreso de una hoja, leído en su franja de arriba.

    Sólo para la hoja que abre un documento que nadie supo nombrar: son pocas.
    Primero el OCR de casa, que no cuesta IA, con un reintento; si no lee nada
    y el operador eligió una lectura con IA, la IA lee esa franja sola. La
    hoja se dibuja ya girada y la franja se recorta de la imagen, que es lo que
    se ve; recortar en la página sin girar tomaba un lateral en un formulario
    apaisado.
    """
    from io import BytesIO

    from PIL import Image

    from ...domain.titulo_impreso import titulo_impreso

    try:
        imagen = Image.open(BytesIO(fuente.render(pagina, None, PPP_DEL_ENCABEZADO)))
        franja = imagen.crop((0, 0, imagen.width, int(imagen.height * ALTO_DEL_ENCABEZADO)))
        salida = BytesIO()
        franja.save(salida, format="PNG")
    except Exception:  # noqa: BLE001 - sin franja, el nombre por su origen
        logger.warning("no se pudo dibujar la franja de la pág. %s", pagina, exc_info=True)
        return None
    for _ in range(INTENTOS_DE_LA_FRANJA):
        try:
            texto = lector.read(salida.getvalue()).text
        except Exception:  # noqa: BLE001 - se agotó o falló: se intenta otra vez
            logger.warning("no se pudo leer la franja de la pág. %s", pagina, exc_info=True)
            continue
        titulo = titulo_impreso(texto)
        if titulo:
            return titulo
        # Leyó y la franja no trae título: repetir no lo cambia.
        break
    if de_pago is None:
        return None
    try:
        return titulo_impreso(de_pago.read(salida.getvalue()).text)
    except Exception:  # noqa: BLE001 - sin franja legible, el nombre por su origen
        logger.warning("la IA no leyó la franja de la pág. %s", pagina, exc_info=True)
        return None


#: Hasta cuánto texto del documento se le manda a la IA para nombrarlo: sus
#: primeras hojas bastan para decir qué es, y el chat cobra por palabra.
LARGO_PARA_NOMBRAR = 6000
#: A cuánto viaja a la IA la hoja que se lee para nombrar el documento.
PPP_PARA_NOMBRAR = 200


def _nombre_con_la_ia(fuente, paginas: list[int], textos: dict, lector_de_pago, nombrador) -> str | None:
    """El nombre que la IA le da a un documento por su cuerpo, o ``None``.

    La primera hoja se relee con el OCR de pago -- su capa puede ser basura,
    como la de UPD2998726 («y * n / lí í») --; las demás van con lo que ya se
    leyó. La IA elige del catálogo del cliente o da un nombre corto
    (``nombre_de_la_ia``). Un fallo aquí no tumba la caja: el documento se
    nombra por su origen y va a revisión.
    """
    from ...domain.nombre_oficial import nombre_de_la_ia

    partes = []
    for puesto, pagina in enumerate(paginas):
        texto = textos.get(pagina, "") or ""
        if puesto == 0 and lector_de_pago is not None:
            try:
                texto = lector_de_pago.read(fuente.render(pagina, None, PPP_PARA_NOMBRAR, "jpeg")).text or texto
            except Exception:  # noqa: BLE001 - se queda con lo que ya se leyó
                logger.warning("la IA no releyó la pág. %s para nombrarla", pagina, exc_info=True)
        partes.append(texto)
    cuerpo = "\n\n".join(p for p in partes if p.strip())[:LARGO_PARA_NOMBRAR]
    if not cuerpo.strip():
        return None
    try:
        return nombre_de_la_ia(nombrador.resumir(cuerpo))
    except Exception:  # noqa: BLE001 - sin nombre de la IA, el de su origen
        logger.warning("la IA no nombró el documento de la pág. %s", paginas[0], exc_info=True)
        return None


#: A cuánto se relee una hoja buscando su fecha: en local, fino; para la IA,
#: lo que ya basta y viaja ligero.
PPP_PARA_LA_FECHA_LOCAL = 300
PPP_PARA_LA_FECHA_CON_IA = 200


def _completar_las_fechas(piezas: list[dict], textos: dict, ruta_pdf, taller) -> list[dict]:
    """Pone fecha a cada documento que salió sin ella. Devuelve de dónde salió cada una.

    Primero el agente (:mod:`~resolutions.application.agente_de_fechas`): el
    texto, la relectura local y, sólo si el operador eligió una lectura con IA,
    la IA. Lo que el papel no trae, la fecha de su trámite. Un fallo aquí no
    tumba la caja: el documento se queda como estaba.
    """
    from datetime import date

    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...adapters.tesseract_ocr import PSM_AUTO, TesseractConfig, TesseractOcr
    from ...application.agente_de_fechas import AgenteDeFechas, fecha_por_su_tramite
    from ...domain.tramites import es_cedula

    sin_fecha = [i for i, pieza in enumerate(piezas) if not pieza.get("fecha")]
    if not sin_fecha:
        return []
    halladas: list[dict] = []
    fuente = None
    try:
        fuente = PyMuPDFPageSource(ruta_pdf, taller.name)
        local = TesseractOcr(TesseractConfig(min_word_confidence=0, psm=PSM_AUTO, timeout_seconds=SEGUNDOS_PARA_UNA_HOJA))
        de_pago = taller.lector_de_pago()
        agente = AgenteDeFechas(
            releer=lambda p: local.read(fuente.render(p, None, PPP_PARA_LA_FECHA_LOCAL)).text,
            leer_con_ia=(
                (lambda p: de_pago.read(fuente.render(p, None, PPP_PARA_LA_FECHA_CON_IA, "jpeg")).text)
                if de_pago is not None
                else None
            ),
            # La cédula no fecha nada: su fecha es la de nacimiento.
            no_fecha=es_cedula,
        )
        for i in sin_fecha:
            hallada = agente.buscar(piezas[i]["pages"], textos)
            if hallada is not None:
                piezas[i]["fecha"] = hallada.fecha.isoformat()
                piezas[i]["fecha_por"] = hallada.como()
                halladas.append({"pages": piezas[i]["pages"], "fecha": piezas[i]["fecha"], "como": hallada.como()})
    except Exception:  # noqa: BLE001 - buscar una fecha no tumba la caja
        logger.warning("no se pudo terminar de buscar las fechas que faltan", exc_info=True)
    finally:
        if fuente is not None:
            fuente.close()

    # Lo que el papel no trae -- la copia de una cédula, una foto --: la fecha
    # de su trámite, el documento con que viaja. Sólo de las fechas del propio
    # papel, para que una prestada no se preste otra vez.
    propias = [
        date.fromisoformat(str(p["fecha"])[:10]) if p.get("fecha") else None for p in piezas
    ]
    archivos = [p.get("archivo") for p in piezas]
    for i, pieza in enumerate(piezas):
        if propias[i] is not None:
            continue
        del_tramite = fecha_por_su_tramite(i, propias, archivos)
        if del_tramite is None:
            continue
        fecha, de = del_tramite
        pieza["fecha"] = fecha.isoformat()
        pieza["fecha_por"] = (
            f"la de su trámite: {piezas[de].get('titulo') or piezas[de].get('type') or 'documento'} "
            f"(pág. {piezas[de]['pages'][0]})"
        )
        halladas.append({"pages": pieza["pages"], "fecha": pieza["fecha"], "como": pieza["fecha_por"]})
    return halladas


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
        PSM_AUTO,
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
    from ...application.cartas import Cartas
    from ...application.entrega import Destino, entregar
    from ...application.segment_document import SegmentDocument
    from ...application.segment_split import group_by_segment
    from ...application.sellos import (
        ajustar_por_cartas,
        cortar_por_sellos,
        dividir_por_tramite,
        hojas_que_pueden_llevar_sello,
        la_ultima_hoja_sola,
        leer_sellos,
        retener_los_folios,
        separar_las_actas,
        separar_los_formularios,
        unir_lo_que_no_abre,
    )
    from ...domain.carta import abre_carta, asunto_de_la_carta
    from ...domain.fingerprint import nic_de_la_caja
    from ...domain.naming import DOCUMENT_PREFIX, document_folder
    from ...domain.nombre_oficial import nombre_oficial
    from ...domain.segmentation import Verdict
    from ...domain.sello import (
        claves_del_envio,
        es_guia_de_envio,
        lleva_etiqueta_de_envio,
        numero_del_acta_de_suspension,
    )
    from ...domain.territorial import nombre_del_expediente
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
    # Las cartas (lo dictó el operador ante UPD3102756: «cada trámite va solo,
    # con sus respectivos anexos»). No todo sello abre: el que va al pie de la
    # hoja de firmas radica la carta que continúa, el de una copia ya radicada
    # en la caja es una prueba, y el radicado de la Superintendencia que la
    # carta anterior cita es el soporte de esa carta.
    cartas = Cartas.de(textos, sellos)
    sellos_que_abren = {p: s for p, s in sellos.items() if p not in cartas.no_abren}
    grupos, anexos, cortes_por_sello = cortar_por_sellos(
        grupos,
        sellos_que_abren,
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
    abren = {g.page_numbers[0] for g in grupos.groups if g.page_numbers[0] in sellos_que_abren or g.page_numbers[0] in etiquetas or g.page_numbers[0] + 1 in etiquetas or g.page_numbers[0] in actas}
    # F2b. Los folios del sello: lo que la oficina recibió como un escrito
    # -- «Folios: 19» -- no lo parte la continuidad. Sólo otro sello o la
    # etiqueta de LECTA abren algo dentro de esas hojas.
    grupos, anexos, por_folios = retener_los_folios(grupos, sellos_que_abren, abren, anexos)
    # F2d. La carta abre su trámite aunque no traiga sello -- salvo dentro de
    # los folios de un sello, que son de ese escrito --; la hoja que la
    # continúa y la prueba que trae van con ella.
    que_abren = cartas.que_abren(sellos_que_abren)
    grupos, anexos, abiertas_por_carta, unidas_por_carta, de_prueba = ajustar_por_cartas(
        grupos, anexos, abren=que_abren, siguen=cartas.siguen, pruebas=cartas.pruebas
    )
    # F2e. Cada formulario de la oficina en su documento (lo dictó el operador
    # el 2026-10-26 sobre las cajas de Magangué): la constancia de reclamación
    # y la notificación personal van solas salvo un anexo evidente, y la carta
    # de respuesta que sigue a la notificación es otro documento. La Habeas
    # Data y las piezas del acuerdo también se separan de lo de delante; el
    # acuerdo (F4b) las junta después en el suyo.
    from ...domain.asunto_del_documento import ACUERDO_DE_PAGO as _ACUERDO
    from ...domain.asunto_del_documento import LEY_HABEAS_DATA as _HABEAS
    from ...domain.asunto_del_documento import formulario_que_abre
    from ...domain.tramites import radicado_de as _radicado_de

    formularios = {}
    for p, texto in textos.items():
        tipo_de_formulario = formulario_que_abre(texto or "")
        if tipo_de_formulario:
            formularios[p] = (
                tipo_de_formulario,
                None if tipo_de_formulario == _ACUERDO else _radicado_de(texto or ""),
            )
    # La respuesta sólo abre aparte cuando sigue a una notificación personal:
    # es el caso que dictó el operador («notificación sola, respuesta
    # aparte»). En lo demás sigue con su escrito, como se validó antes en las
    # cajas de referencia.
    from ...domain.asunto_del_documento import NOTIFICACION_PERSONAL as _NOTIFICACION
    from ...domain.asunto_del_documento import RESPUESTA_DE_LA_EMPRESA as _RESPUESTA

    for p in [p for p, (tipo_f, _) in formularios.items() if tipo_f == _RESPUESTA]:
        if not any(formularios.get(p - atras, ("", None))[0] == _NOTIFICACION for atras in (1, 2, 3)):
            del formularios[p]
    # Dentro de los folios de un sello, o aportado como prueba, un formulario
    # es del escrito que lo trae: no abre. Salvo la Habeas Data, que nunca es
    # prueba de una carta: es de su acuerdo de pago (1002421 pág. 10, detrás de
    # la carta de otra persona).
    intocables = set(por_folios) | {
        p for p in de_prueba if formularios.get(p, ("", None))[0] != _HABEAS
    }
    grupos, anexos, _ = separar_los_formularios(grupos, formularios, anexos, intocables=intocables)
    # Los que van solos abren documento para todo lo que viene después: ni la
    # lista de anexos, ni la cédula, ni el trámite por RE los une a otro. El
    # acuerdo y la Habeas Data no: el acuerdo los busca para juntarlos.
    formularios_solos = {
        g.page_numbers[0]
        for g in grupos.groups
        if g.page_numbers[0] in formularios and formularios[g.page_numbers[0]][0] not in (_ACUERDO, _HABEAS)
    }
    # El trámite no une a su anterior un escrito del cliente, aunque cite su
    # RE: sólo la respuesta o la notificación de la empresa (lo dictó el
    # operador: «cada trámite va solo, no unido a otros trámites por código de
    # referencia»). Y desde el 2026-10-26 tampoco la constancia, la
    # notificación ni la respuesta: cada una va sola.
    abren_el_tramite = abren | cartas.escritos(que_abren) | formularios_solos
    abren = abren | que_abren | formularios_solos
    # F3. Lista de ANEXOS.
    retencion = retener_anexos(grupos, textos, anexos, abren=abren)
    grupos, anexos = retencion.grupos, retencion.anexos
    # F4. Y la cédula y la factura nunca van solas: si el corte dejó una
    # abriendo documento, vuelve al PDF de la página anterior.
    soportes = unir_soportes(grupos, textos, anexos, abren=abren)
    grupos, anexos = soportes.grupos, soportes.anexos
    # F4b. El acuerdo de pago -- pagarés, cartas de instrucciones,
    # reconocimiento de deuda, simulador -- es un solo documento, sin RE.
    # La constancia, la notificación y la respuesta abren su documento pero no
    # cortan el acuerdo: la Habeas Data y los pagarés las cruzan.
    grupos, anexos, del_acuerdo = unir_el_acuerdo_de_pago(
        grupos, textos, anexos, abren=abren, cruzan=formularios_solos
    )
    dudosas = [
        b
        for b in dudosas
        if b.right not in retencion.retenidas
        and b.right not in soportes.movidas
        and b.right not in cortes_por_sello
        and b.right not in por_folios
        and b.right not in abiertas_por_carta
        and b.right not in unidas_por_carta
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

    def _oficial_de_la_hoja(pagina: int, tipo: str | None) -> str:
        """El nombre oficial del documento que abre en esa hoja; DOCUMENTO si no dice qué es.

        Lo mismo para el archivo y para su fila del índice (lo dictó el
        operador el 2026-10-21: «tanto en el nombre del documento como en el
        inventario»). De lo más cierto a lo menos: su título, con el nombre del
        catálogo -- «RECLAMO», no «RECLAMACION» --; si es una carta, lo que su
        REF o su ASUNTO dicen que es -- no lo que el catálogo adivine de su
        cuerpo --; y el tipo del catálogo, ``tipo``.
        """
        texto = textos.get(pagina, "") or ""
        asunto = asunto_de_la_carta(texto)
        titulo = titulo_del_documento(texto, None)
        if titulo != DOCUMENT_PREFIX:
            return nombre_oficial(titulo, asunto) or titulo
        if abre_carta(texto) and (del_asunto := nombre_oficial(DOCUMENT_PREFIX, asunto)):
            return del_asunto
        if tipo and tipo.upper() != DOCUMENT_PREFIX:
            return nombre_oficial(tipo, asunto) or tipo.upper()
        return DOCUMENT_PREFIX

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
        for archivo, entregado in enumerate(entregados):
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
                # si no trae ninguna, la de su primera hoja fechada. No la del
                # sello de una copia aportada como prueba: ésa es de otro día.
                primera = (
                    next((fechas_de_guia[p] for p in paginas if fechas_de_guia.get(p)), None)
                    or next(
                        (
                            sellos[p].fecha
                            for p in paginas
                            if p in sellos and sellos[p].fecha and p not in cartas.copias
                        ),
                        None,
                    )
                    or next(
                        (f for p in titulares if (f := fecha_de_la_hoja(p)) is not None), None
                    )
                )
                piezas.append(
                    {
                        "pages": paginas,
                        # En qué archivo acabó: la fecha de su trámite se busca
                        # primero entre los documentos de su mismo archivo.
                        "archivo": archivo,
                        "type": cortado.kind,
                        "fecha": primera.isoformat() if primera else cortado.fecha,
                        # Lo que el documento dice ser en su primera hoja --
                        # «DERECHO DE PETICION», «RESPUESTA A RECLAMACION» --,
                        # que es el título de su fila en el índice.
                        # Con su nombre oficial, el del catálogo del cliente:
                        # «RECLAMO», no «RECLAMACION» (lo dictó el operador el
                        # 2026-10-21). Es el mismo que nombra el archivo.
                        # Sin título conocido se queda en DOCUMENTO, y la fila
                        # toma el nombre de su archivo.
                        # La autorización que se le unió por delante no titula
                        # la fila: la nombra su archivo, el del documento.
                        "titulo": nombre_oficial(ACUERDO_DE_PAGO)
                        if acuerdo
                        else DOCUMENT_PREFIX
                        if paginas[0] in delanteras
                        else _oficial_de_la_hoja(titulares[0], cortado.kind),
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
        # Sin los sellos de las copias aportadas como prueba: son de otro trámite.
        por_tramite = agrupar_por_tramite(
            grupos,
            leidas,
            anexos,
            retenidas=retencion.retenidas,
            sellos={p: s for p, s in sellos.items() if p not in de_prueba},
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
            # Dentro del escrito de un cliente, el RE de lo que trae como
            # prueba -- la copia de una carta o de un sello ya radicados, que
            # cita el radicado de su propio trámite -- es el de otro trámite, y
            # no parte el escrito ni lo nombra (UPD3102756 pág. 25 dentro del
            # aviso de la 23). Tampoco el sello de una copia.
            escritos = cartas.escritos(que_abren)
            # Ninguna hoja de una copia aportada como prueba da su RE: la
            # copia del sello de la petición del 14-nov (pág. 32) llamaba
            # RE…21592 al aviso de la pág. 23.
            for p in de_prueba:
                propios[p] = None
            # Ni las del acuerdo de pago, que no lleva RE: las constancias de
            # la financiación que se firmaron con él traen el suyo y lo partían
            # (UPD3102729).
            for p in del_acuerdo:
                propios[p] = None
            de_anexo = {p for paginas in anexos.values() for p in paginas}
            for g in grupos.groups:
                if g.page_numbers[0] in escritos:
                    for p in g.page_numbers:
                        if p in cartas.copias or (p in de_anexo and p not in sellos_que_abren):
                            propios[p] = None
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
                # Y lo mismo la carta del cliente que abre sin sello: no toma el
                # RE de su vecino (UPD3102756, trece reclamos con el mismo RE).
                if paginas[0] in sellos_que_abren or paginas[0] in escritos:
                    suyo = del_tramite.get(paginas[0])
                    citado_antes = any(r == suyo for p, r in propios.items() if p < paginas[0])
                    # Sólo toma el RE que le cita después la empresa -- su
                    # respuesta, su citación --, nunca el del sello de otro
                    # escrito: en UPD3102756 los reclamos del 13-oct y del
                    # 8-nov se llamaban con el RE de la solicitud de la pág. 11.
                    citado_despues = any(
                        r == suyo for p, r in propios.items() if p > paginas[-1] and p not in sellos
                    )
                    return citado_antes or not citado_despues
                primera = next((x for x in paginas if x not in guias), paginas[0])
                titulo = titulo_del_documento(textos.get(primera, "") or "", None)
                return titulo.startswith(_FORMATOS_SIN_RE_AJENO) or titulo == DOCUMENT_PREFIX

            grupos, anexos = dividir_por_tramite(
                grupos, propios, del_tramite, abren_el_tramite, anexos, sin_re_ajeno=sin_re_ajeno
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
    grupos, anexos, ultima_sola = la_ultima_hoja_sola(grupos, set(sellos_que_abren) | etiquetas, anexos, guias)
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
        if primera in sellos_que_abren or primera in etiquetas or primera + 1 in etiquetas:
            continue
        # La carta que abre su trámite tampoco se une: trae su asunto.
        if primera in que_abren:
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
    # La autorización con que abre la caja -- Habeas Data, notificación
    # electrónica -- tampoco va sola (lo dictó el operador el 2026-10-22:
    # «ningún habeas data puede ir suelto»): sin documento delante, va con el
    # de después, que se sigue llamando como él.
    delanteras: set[int] = set()
    if len(grupos.groups) > 1:
        primero, segundo = grupos.groups[0], grupos.groups[1]
        if primero.page_numbers[0] not in del_acuerdo and _titulo(
            textos.get(primero.page_numbers[0], "") or "", None
        ) in ("LEY HABEAS DATA", AUTORIZACION_DE_NOTIFICACION):
            from ...application.anexos_declarados import _renumerar

            delanteras.update(primero.page_numbers)
            unido = replace(segundo, page_numbers=list(primero.page_numbers) + list(segundo.page_numbers))
            suyos = anexos.pop(primero.code.value, []) + anexos.pop(segundo.code.value, []) + list(primero.page_numbers)
            anexos[unido.code.value] = sorted(set(suyos))
            restantes, anexos = _renumerar([unido, *grupos.groups[2:]], anexos)
            grupos = replace(grupos, groups=restantes)
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
            return replace(g, kind=nombre_oficial(ACUERDO_DE_PAGO))
        # La carta, no la guía que la precede ni la autorización que se le unió
        # por delante.
        primera = next((x for x in g.page_numbers if x not in guias and x not in delanteras), g.page_numbers[0])
        # El nombre oficial (lo dictó el operador el 2026-10-21: «según el
        # nombre oficial del documento del trámite… tanto en el nombre del
        # documento como en el inventario»): su título con el nombre del
        # catálogo, o lo que su ASUNTO o su REF dicen que es.
        # La carta se llama por lo que su REF dice que es, no por su membrete:
        # «NOTIFICACION DEL REPORTE DEL SILENCIO ADMINISTRATIVO POSITIVO», no
        # «PUBLICOS DOMICILIARIOS DE MAGANGUE BOLIVAR» (UPD3102756 pág. 23).
        oficial = _oficial_de_la_hoja(primera, g.kind)
        if oficial != DOCUMENT_PREFIX:
            return replace(g, kind=oficial)
        # Ningún documento se entrega sin un nombre que lo referencie (lo dictó
        # el operador el 2026-10-20 ante «01_DOCUMENTO.pdf»): el título que
        # imprime su primera hoja, leído del texto o, si la lectura de la hoja
        # entera se descartó, de su franja de arriba; y si ninguno se deja
        # leer, su caja y sus páginas, a revisión.
        impreso = titulo_impreso(textos.get(primera, "") or "")
        if impreso is None:
            if not fuente_de_encabezados:
                fuente_de_encabezados.append(PyMuPDFPageSource(tmp_path, taller.name))
            impreso = _titulo_del_encabezado(
                fuente_de_encabezados[0], primera, lector_de_encabezados, lector_de_pago_de_encabezados
            )
        if impreso:
            return replace(g, kind=impreso)
        # Lo que el documento dice de sí mismo en su «ASUNTO:» o «REF.:» --
        # «COBRO EXCESIVO DEL SERVICIO DE ENERGIA» (UPD2465747, 2026-10-21)
        # --, antes que llamarlo por su caja. Primero el renglón del asunto; si
        # no, lo que su texto dice pedir -- «INFORMACION GENERAL» (UPD2326360
        # págs. 4-5) --, pero no una de sus peticiones, que empieza «Que…»:
        # «QUE LA PRESTADORA AFINIA S» no nombra nada (UPD3102756 pág. 57).
        titulares = [p for p in g.page_numbers if p not in guias][:2] or g.page_numbers[:1]
        for titular in titulares:
            del_asunto = nombre_oficial(DOCUMENT_PREFIX, asunto_de_la_carta(textos.get(titular, "") or ""))
            if del_asunto:
                return replace(g, kind=del_asunto)
        asunto = asunto_del_documento([textos.get(p, "") or "" for p in titulares], None)
        if asunto and not asunto.startswith("QUE "):
            return replace(g, kind=asunto[:MAX_ASUNTO_EN_EL_NOMBRE].rsplit(" ", 1)[0] if len(asunto) > MAX_ASUNTO_EN_EL_NOMBRE else asunto)
        sin_titulo.append(primera)
        return replace(g, kind=nombre_por_su_origen(taller.name, g.page_numbers))

    def nombre_estandar(g):
        """El nombre del archivo por el estándar: un tipo del catálogo del cliente.

        Lo dictó el operador el 2026-10-22: «que los nombres o los tipos de
        documentos estén estandarizados… manejemos los nombres por estándares»,
        y el nombre libre sólo «cuando ni el OCR ni la IA, en última opción,
        logren dar con el nombre del documento». Así:

        1. Lo que dicen las reglas sobre el papel (``tipo_del_archivo``), con
           su forma del catálogo (``estandarizar``).
        2. Si no es un tipo del catálogo y el operador eligió «OCR + IA», la
           IA lee el cuerpo del documento con el catálogo delante.
        3. Si tampoco, el nombre libre: el título impreso, el asunto o el que
           propuso la IA; y si nada, su caja y sus páginas, a revisión.
        """
        nombrado = tipo_del_archivo(g)
        if entregado_por is Agrupacion.MES:
            return nombrado
        nombre = estandarizar(nombrado.kind)
        if nombre in POR_NOMBRE or nombrador is None:
            return replace(nombrado, kind=nombre)
        if not fuente_de_encabezados:
            fuente_de_encabezados.append(PyMuPDFPageSource(tmp_path, taller.name))
        # Todo el documento, no sólo su primera hoja: lo que dice ser puede
        # estar en cualquiera.
        de_la_ia = _nombre_con_la_ia(
            fuente_de_encabezados[0],
            [p for p in g.page_numbers if p not in guias and p not in delanteras] or list(g.page_numbers),
            textos,
            lector_de_pago_de_encabezados,
            nombrador,
        )
        sin_nombre = g.page_numbers[0] in sin_titulo or next(
            (x for x in g.page_numbers if x not in guias and x not in delanteras), g.page_numbers[0]
        ) in sin_titulo
        if de_la_ia and (de_la_ia in POR_NOMBRE or sin_nombre):
            for pagina in g.page_numbers:
                if pagina in sin_titulo:
                    sin_titulo.remove(pagina)
            return replace(nombrado, kind=de_la_ia)
        return replace(nombrado, kind=nombre)

    from ...domain.catalogo import POR_NOMBRE
    from ...domain.nombre_oficial import estandarizar
    from ...domain.titulo_impreso import nombre_por_su_origen, titulo_impreso

    fuente_de_encabezados: list = []
    lector_de_encabezados = TesseractOcr(
        TesseractConfig(min_word_confidence=0, psm=PSM_AUTO, timeout_seconds=SEGUNDOS_PARA_UNA_HOJA)
    )
    # La IA, sólo si el operador eligió una lectura con ella: la franja sola, y
    # el nombre del documento que nada supo nombrar.
    lector_de_pago_de_encabezados = taller.lector_de_pago()
    nombrador = taller.nombrador()
    sin_titulo: list[int] = []
    try:
        grupos = replace(grupos, groups=[nombre_estandar(g) for g in grupos.groups])
    finally:
        for fuente in fuente_de_encabezados:
            fuente.close()
    # Las hojas de cada PDF, en el orden del papel. Un documento con hojas que
    # no van seguidas -- el acuerdo con la Habeas Data de arriba -- recibía la
    # que se le unió al final: 1, 6…14, 2 (1001508/UPD3102736).
    grupos = replace(grupos, groups=[replace(g, page_numbers=sorted(g.page_numbers)) for g in grupos.groups])
    # F6. El nombre. Ningún documento se llama como su anexo: el que abre con
    # un reclamo y trae una cédula detrás es el reclamo, no un «DOCUMENTO DE
    # IDENTIDAD».
    grupos = nombrar_sin_soporte(grupos, textos)
    piezas = describir_piezas(grupos.groups)
    # F7. Ningún documento sin fecha (lo dictó el operador el 2026-10-20: «que
    # el bot en todos los casos tome la fecha»): el agente la busca en el texto,
    # relee en local y, si se eligió una lectura con IA, se la pide a la IA; lo
    # que el papel no trae lleva la de su trámite.
    fechas_halladas = _completar_las_fechas(piezas, textos, tmp_path, taller)
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
            # «Número-título», sin el RE (lo dictó el operador el 2026-10-21:
            # «quita el RE del título, ya no es necesario»): 01_RECLAMO.pdf.
            sin_radicado=True,
        ),
        en_revision=[boundary.right for boundary in costuras_en_revision]
        + [pagina.page for pagina in sin_fecha_en_revision]
        + sin_titulo,
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
        # El documento que no dejó leer ningún título y se nombró por su caja.
        + [{"page": pagina, "reason": SIN_TITULO} for pagina in sin_titulo]
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
        # Las fechas que no estaban a la vista y de dónde salieron: el índice
        # lleva sólo la fecha; aquí queda cómo se obtuvo, para auditarla.
        "fechas_halladas": fechas_halladas,
        # Sólo el PDF, sin la subcarpeta de la caja: «UPD2998266», no
        # «910349 UPD2998266» (la caja va en «Identificación / Nic»).
        "expediente": document_folder(nombre_del_expediente(taller.name)),
    }
    # 4. El Índice Electrónico del cliente, junto a los PDF de la caja y sin
    #    que nadie lo pida. Es el inventario de toda caja de correspondencia y
    #    ocupa el lugar de la planilla de las otras rutas: el archivo recibe un
    #    solo Excel por caja, el suyo.
    _escribir_indice(report, destination, payload)

    _anunciar(payload, Stage.DONE)
    return report
