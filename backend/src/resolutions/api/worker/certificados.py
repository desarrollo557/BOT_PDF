"""Los certificados de tiempo de servicio de la Universidad: un PDF por certificado, con sus anexos, y su fila en el FUID.

Lo pidió el operador el 2026-11-06 para «22. CERTIFICADOS DE TIEMPO SERVICIOS»
del REPOSITORIO UDC, «con el mismo formato de FUID», como lo marcó en
«ESTRUCTURA LIBROS UNICARTAGENA.pdf»: asunto «CERTIFICADO DE TIEMPO DE SERVICIO
+ NOMBRE», la cédula como número de documento desde y hasta, la fecha de la
firma como fecha extrema, y «este documento lleva anexos: hacer la división
entre cada uno y no dejar por fuera cada anexo ligado a cada certificado».

Un certificado es su número (``domain/nomina.py``, ``encabezado_del_certificado``):
abre el que trae un número nuevo -- o el formulario sin número --; la hoja con
el mismo número o que dice «VIENEN», «PASAN», «HOJA Nº 2» lo continúa o lo
repite (el definitivo y sus borradores van seguidos); lo demás -- la carta con
que se pidió, las hojas de cálculo a mano, los recibos, los contratos, las
copias de posesión, los certificados de las facultades -- es su anexo.

Lo que cuesta:

- **Qué hojas pueden ser de un certificado**, gratis: la capa de texto y el
  tercio de arriba leído con Tesseract. Las hojas a mano, las cartas cortas y
  los recibos no se leen más.
- **Esas hojas enteras**: con «OCR + IA», la IA -- una página facturada cada
  una --; la capa del escáner dice «CZHTinCADO Ho.ooi» y Tesseract no lee el
  número de uno de cada tres formularios. Con «Solo OCR», Tesseract.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ...application.progress import Stage
from .nominas import (
    BANDA_DE_LA_CABECERA,
    _con_la_ia,
    _con_tesseract,
    _escribir_el_fuid,
    _fecha,
    _letras,
    _reparto,
    escribir_paginas,
    nombre_del_pdf,
)
from .taller import Taller, _anunciar

logger = logging.getLogger(__name__)

#: Lo que delata, aun roto, la hoja de un certificado: su número, la sección
#: de archivo, quien lo suscribe, la sindicatura, el «HACE CONSTAR».
PISTA = re.compile(
    r"C[EI]R?T[I1L]F[I1L]C|SECCI\w{0,3}N\s+(?:DE\s+)?ARCH|CORRESPON|SUSCRIT|SINDICAT|CONSTAR|ARCHIVO"
)
#: Una hoja con tantas letras impresas en su tercio de arriba se lee entera
#: aunque no traiga pista: puede ser un formulario que Tesseract no leyó.
LETRAS_DE_UNA_IMPRESA = 120


def certificados_job(payload: dict) -> dict:
    """Divide e inventaría un libro de certificados de tiempo de servicio: un PDF por certificado."""
    import pymupdf

    from ...adapters.huellas_pdf import huellas_de
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...adapters.tesseract_ocr import HeaderAndPageOcr
    from ...application.entrega import comprobar_archivos
    from ...application.integridad_de_los_datos import revisar_los_datos
    from ...application.perfiles_de_revision import perfil_de
    from ...application.revisor_de_cortes import anotar_en_el_informe, revisar_sin_romper
    from ...application.task import TaskKind
    from ...domain import nomina as n
    from ...domain.historia_academica import plano
    from ...domain.naming import document_folder

    taller = Taller.desde(payload)
    carpeta = taller.source.parent.name if payload.get("destination") else ""
    nombre = Path(taller.name).name
    local = HeaderAndPageOcr(language=taller.settings["ocr_language"])
    de_pago = taller.lector_de_pago()
    hilos = max(1, min(4, int(taller.settings.get("page_workers") or 4)))
    ventana = n.ventana_del_libro(nombre)

    source = PyMuPDFPageSource(taller.source, taller.name)
    try:
        total = source.page_count
        _anunciar(payload, Stage.OPENED, page_count=total)
        textos: list[str] = []
        for numero in range(1, total + 1):
            taller.control.check()
            textos.append(source.text_of(numero) or "")
            _anunciar(
                payload, Stage.PAGE, page_count=total, detail="leyendo cada página", done=numero, total=total,
                page_number=numero, provenance="text_layer",
            )

        # 1. Qué hojas pueden ser de un certificado: la capa y el tercio de
        # arriba con Tesseract. Gratis.
        cabeceras = _con_tesseract(
            payload, taller, source, local, list(range(1, total + 1)), BANDA_DE_LA_CABECERA, dpi=250, hilos=hilos,
            detalle="mirando qué hojas son de un certificado",
        )
        candidatas = []
        for numero in range(1, total + 1):
            arriba = plano(cabeceras.get(numero, ""))
            capa = plano(textos[numero - 1][:1500])
            if PISTA.search(arriba) or PISTA.search(capa) or _letras(arriba) >= LETRAS_DE_UNA_IMPRESA:
                candidatas.append(numero)

        # 2. Esas hojas enteras: con la IA, si se pidió; si no, con Tesseract.
        if de_pago is not None:
            leidas = _con_la_ia(
                payload, taller, source, de_pago, candidatas, None, dpi=200, hilos=hilos,
                detalle="leyendo con la IA cada hoja de certificado",
            )
        else:
            leidas = _con_tesseract(
                payload, taller, source, local, candidatas, None, dpi=200, hilos=hilos,
                detalle="leyendo cada hoja de certificado",
            )

        # 3. Qué es cada hoja, su número y lo que dice de su persona.
        hojas = []
        #: El texto con que se juzgó cada hoja: de él salen las fechas.
        texto_de: dict[int, str] = {}
        for numero in range(1, total + 1):
            texto = leidas.get(numero) or ""
            if not texto.strip():
                # La IA no la pudo leer: lo que haya de la capa y de su cabecera.
                texto = f"{cabeceras.get(numero, '')}\n{textos[numero - 1]}"
            texto_de[numero] = texto
            encabezado = n.encabezado_del_certificado(texto) if numero in candidatas else n.Encabezado(es=False)
            if encabezado.es:
                hojas.append(
                    n.Hoja(
                        numero=numero,
                        plantilla=n.CERTIFICADO,
                        datos=n.leer_el_certificado(texto, ventana),
                        certificado=encabezado.numero,
                        sigue=encabezado.sigue,
                    )
                )
            else:
                hojas.append(n.Hoja(numero=numero, plantilla=None))
        documentos = n.documentos(hojas)
        if not any(d.plantilla == n.CERTIFICADO for d in documentos):
            return _sin_certificados(payload, taller, nombre, carpeta, total)
        for documento in documentos:
            # Sus fechas extremas: las de la firma de sus versiones.
            # Sólo de sus hojas de certificado -- la primera, las que siguen, los
            # borradores --: la carta de solicitud es un anexo y su fecha no es
            # la del certificado (la revisión, 2026-11-06).
            suyas = [p for p in documento.paginas if hojas[p - 1].plantilla == n.CERTIFICADO]
            documento.fechas = n.fechas_del_certificado([texto_de[p] for p in suyas], ventana)

        # El patrón del libro: si sus certificados traen cédula -- los de 1964 no
        # --, el que no la trae es para mirar.
        de_certificado = [d for d in documentos if d.plantilla == n.CERTIFICADO]
        pide_cedula = sum(1 for d in de_certificado if d.cedula) * 2 >= len(de_certificado)

        pidio_dividir = payload.get("task") in (str(TaskKind.SPLIT), str(TaskKind.BOTH))
        del_revisor = perfil_de("certificados")
        revision = aviso_del_revisor = None
        por_pagina = dict(enumerate(textos, start=1))
        abren = frozenset(d.paginas[0] for d in documentos if d.nombre or d.numero is not None)
        revision, aviso_del_revisor = revisar_sin_romper(
            _reparto(documentos), por_pagina, del_revisor.patrones(por_pagina, abren=abren),
            juez=taller.juez_de_costuras(),
        )

        esperado: dict[str, list[int]] = {}
        comprobacion = None
        salidas: list[str] = []
        filas: list[dict] = []
        cola: list[dict] = []
        carpeta_de_salida = taller.destination / document_folder(nombre)
        if pidio_dividir:
            carpeta_de_salida.mkdir(parents=True, exist_ok=True)
        _anunciar(payload, Stage.ASSEMBLING, detail=f"escribiendo {len(documentos)} PDF", done=0, total=len(documentos))
        with pymupdf.open(taller.source) as original:
            for orden, documento in enumerate(documentos, start=1):
                taller.control.check()
                archivo = nombre_del_pdf(orden, documento, carpeta=carpeta_de_salida)
                if pidio_dividir:
                    escribir_paginas(original, taller.source, list(documento.paginas), carpeta_de_salida / archivo)
                    esperado[archivo] = list(documento.paginas)
                    salidas.append((carpeta_de_salida / archivo).relative_to(taller.destination).as_posix())
                inicial, final, de_donde = n.fechas_extremas(
                    documento, anio_del_libro=n.anio_del_libro(nombre), ventana=ventana
                )
                if inicial is None and ventana:
                    inicial, final = (1, 1, ventana[0]), (31, 12, ventana[1])
                    de_donde = f"los años {ventana[0]} a {ventana[1]} del libro: no se leyó la fecha de la firma"
                notas = []
                if not documento.nombre:
                    notas.append("no se leyó el nombre" + ("" if de_pago else " (sin la IA)"))
                if not documento.cedula and pide_cedula:
                    notas.append("no se leyó la cédula")
                if not documento.fechas:
                    notas.append("no se leyó la fecha de la firma")
                if de_donde:
                    notas.append(f"fechas: {de_donde}")
                donde = (
                    f"la página {documento.paginas[0]}"
                    if len(documento.paginas) == 1
                    else f"las páginas {documento.paginas[0]} a {documento.paginas[-1]}"
                )
                filas.append(
                    {
                        "tipo": n.NOMINA,
                        "clase": documento.clase,
                        "plantilla": documento.plantilla,
                        "asunto": n.asunto(documento),
                        "nombre": documento.nombre,
                        "cedula": documento.cedula,
                        "pide_cedula": pide_cedula and documento.plantilla == n.CERTIFICADO,
                        "certificado": documento.numero,
                        "fecha_inicial": _fecha(inicial),
                        "fecha_final": _fecha(final),
                        "folios": len(documento.paginas),
                        "pagina_inicial": documento.paginas[0],
                        "pagina_final": documento.paginas[-1],
                        "archivo": nombre,
                        "carpeta": carpeta,
                        "archivo_generado": archivo if pidio_dividir else None,
                        "observaciones": f"{', '.join(notas)} ({donde} del PDF)" if notas else "",
                    }
                )
                cola.extend({"page": documento.paginas[0], "reason": f"{archivo}: {nota}"} for nota in notas)
                _anunciar(payload, Stage.ASSEMBLING, detail=f"escribiendo {len(documentos)} PDF", done=orden, total=len(documentos))
        if pidio_dividir:
            comprobacion = comprobar_archivos(
                taller.source, esperado, carpeta_de_salida, huellas_de, paginas_del_original=total
            )
    finally:
        source.close()

    report: dict = {
        "document": nombre,
        "page_count": total,
        "tipo": "certificado-tiempo",
        "task": str(TaskKind.INVENTORY_FILE),
        "inventario_actas": filas,
        "certificados": {
            "certificados": len(filas),
            "hojas_leidas": len(candidatas),
            "anexos": total - sum(1 for h in hojas if h.plantilla == n.CERTIFICADO),
        },
        "groups": [{"code": fila["archivo_generado"] or str(orden)} for orden, fila in enumerate(filas, start=1)],
        "review_queue": cola,
    }
    if pidio_dividir:
        report["outputs"] = salidas
        report["dividido"] = True
    if de_pago is None:
        report.setdefault("notices", []).append(
            "Con «Solo OCR» el nombre, la cédula y la fecha de cada certificado salen de Tesseract, que lee mal "
            "estas copias: con «OCR + IA» se leen bien."
        )
    integridad = revisar_los_datos(filas, del_revisor.datos, aceptable=del_revisor.margen) if del_revisor.datos else None
    if revision is not None or aviso_del_revisor or comprobacion or integridad is not None:
        anotar_en_el_informe(
            report, revision, aviso_del_revisor, comprobacion, perfil=del_revisor.as_dict(), integridad=integridad
        )
    _escribir_el_fuid(payload, taller, nombre, filas, report)
    return report


def _sin_certificados(payload: dict, taller: Taller, nombre: str, carpeta: str, total: int) -> dict:
    """Un PDF sin ningún certificado reconocible: una fila para el PDF entero, que se entrega tal cual."""
    from ...adapters.fuid_de_la_entrega import PDF_ENTERO
    from ...application.task import TaskKind

    logger.info("%s: ningún certificado reconocible; se inventaría el PDF entero", nombre)
    filas = [
        {
            "tipo": PDF_ENTERO,
            "archivo": nombre,
            "carpeta": carpeta,
            "folios": total,
            "pagina_inicial": 1,
            "pagina_final": total,
            "entero": True,
            "observaciones": (
                "No se reconoció ningún certificado: se inventaría el PDF entero, con el asunto y los años de su "
                "nombre. Revíselo para dividirlo."
            ),
        }
    ]
    report: dict = {
        "document": nombre,
        "page_count": total,
        "tipo": "certificado-tiempo",
        "task": str(TaskKind.INVENTORY_FILE),
        "inventario_actas": filas,
        "groups": [{"code": "1"}],
        "review_queue": [],
        "notices": ["Ningún certificado reconocible: el PDF se entregó entero, con una fila en el FUID."],
    }
    _escribir_el_fuid(payload, taller, nombre, filas, report)
    return report
