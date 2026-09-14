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
    from ...application.entrega import Destino, entregar
    from ...application.segment_document import SegmentDocument
    from ...application.segment_split import group_by_segment
    from ...domain.fingerprint import nic_de_la_caja
    from ...domain.naming import document_folder
    from ...domain.segmentation import Verdict

    taller = Taller.desde(payload)
    # Los PDF de una caja van juntos y bajo el nombre de la caja. La carpeta del
    # trabajo sigue siendo la de arriba -- es la que la pantalla y la descarga
    # saben encontrar -- pero quien abra el disco ve "UPD2366126" y no un
    # identificador de treinta y dos letras que no le dice de qué documento es.
    carpeta = document_folder(taller.name)
    destination = taller.destination / carpeta

    # 1. Decidir los grupos: costura por costura, con la fuente abierta, y
    #    después del corte y no antes preguntarle a cada documento qué es --
    #    ahora tiene bordes, así que la pregunta tiene una sola respuesta.
    source = PyMuPDFPageSource(taller.source, taller.name)
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
    finally:
        source.close()
    _anunciar(
        payload,
        Stage.ASSEMBLING,
        detail="preparando la escritura",
        done=0,
        total=len(grupos.groups),
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
        en_revision=[boundary.right for boundary in dudosas],
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
            for boundary in dudosas
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
        # Los avisos viven en el informe y no sólo en el progreso: el progreso
        # se ve mientras corre y el informe se lee después, que es cuando el
        # operador se pregunta por qué salieron ochenta documentos.
        "notices": list(avisos),
    }
    # 4. La planilla, junto a los PDF de la caja y sin que nadie la pida.
    _escribir_planilla(report, destination, payload)

    _anunciar(payload, Stage.DONE)
    return report
