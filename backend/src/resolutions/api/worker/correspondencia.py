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

from ...application.progress import Stage
from .planillas import _escribir_planilla
from .taller import Taller, _anunciar


def _segment_job(payload: dict, task, *, avisos: Sequence[str] = ()) -> dict:
    """Un PDF por unidad documental, cortando costura por costura.

    ``avisos`` son las advertencias que el despachador ya reunió sobre la ruta
    elegida -- que el papel dice ser un legajo de resoluciones, por ejemplo --
    y que van al informe además de al progreso.
    """
    from ...adapters.pymupdf_assembler import PyMuPDFAssembler
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...application.agrupacion import Agrupacion, agrupar_por_mes, leer_paginas
    from ...application.entrega import Destino, entregar
    from ...application.segment_document import SegmentDocument
    from ...application.segment_split import group_by_segment
    from ...domain.fingerprint import nic_de_la_caja
    from ...domain.naming import document_folder
    from ...domain.segmentation import Verdict

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
        from pathlib import Path
        import tempfile
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
    
    source = PyMuPDFPageSource(tmp_path, taller.name)
    try:
        page_count = source.page_count
        segmentacion = SegmentDocument(
            oracle=taller.oraculo_de_bordes(),
            reporter=taller.progress,
            control=taller.control,
        ).run(source)
        grupos = group_by_segment(segmentacion.segments, source.text_of)
        # El NIC del suscriptor, que es de la caja entera y no de ninguno de
        # sus documentos. No decide ningún corte -- lo llevan todas las hojas
        # -- pero es con lo que el archivo identifica el expediente, y la
        # entrega en carpeta lo usa para nombrar la carpeta de destino.
        nic = nic_de_la_caja(segmentacion.fingerprints)
        # Un archivo por mes necesita la fecha de cada página, y se busca aquí,
        # con la fuente abierta: estas cajas suelen ser escaneos sin capa de
        # texto, así que la fecha sale de la OCR, y la OCR lee la página
        # rasterizada. Con el motor que eligió el operador, como las demás rutas.
        leidas = None
        if agrupacion is Agrupacion.MES:
            leidas = leer_paginas(
                source,
                taller.ocr(),
                workers=int(taller.settings.get("page_workers") or 4),
                control=taller.control,
                avance=lambda hechas, total: _anunciar(
                    payload,
                    Stage.GROUPING,
                    detail="buscando la fecha de cada página",
                    done=hechas,
                    total=total,
                ),
            )
    finally:
        source.close()
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
    avisos_de_agrupacion = []
    entregado_por = Agrupacion.DOCUMENTO
    if leidas is not None:
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
    if leidas is not None:
        # Cuántas páginas hubo que pasar por OCR para fecharlas: es lo que
        # cuesta esta opción, y con el motor de pago se paga por página.
        estadisticas["pages_dated_by_ocr"] = leidas.con_ocr

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
        + [{"page": pagina.page, "reason": pagina.motivo} for pagina in sin_fecha_en_revision],
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
        "notices": [*avisos, *avisos_de_agrupacion],
    }
    # 4. La planilla, junto a los PDF de la caja y sin que nadie la pida.
    _escribir_planilla(report, destination, payload)

    _anunciar(payload, Stage.DONE)
    return report
