"""Los libros de nómina de la Universidad: un PDF por persona o por paquete, y su fila en el FUID.

Las reglas -- qué es cada hoja, cómo se leen sus datos, qué se junta -- viven
en ``domain/nomina.py``; aquí se lee el libro, se parte y se entrega como las
historias académicas: los PDF y una fila por documento, que la corrida de
carpeta reúne en el FUID de cada subcarpeta.

Lo que cuesta cada cosa:

- **Qué es cada hoja**, gratis: la capa de texto y, donde no la hay, la
  cabecera leída con Tesseract.
- **La fecha de cada listado y de cada comprobante**, gratis: la capa o
  Tesseract sobre su cabecera, votada entre hojas seguidas. Con «OCR + IA», la
  IA lee la primera hoja de cada paquete para confirmarla: una página facturada
  por paquete (Tesseract lee «14.06.82» donde el papel dice 83).
- **El nombre, la cédula y el año de cada persona**, escritos a mano: sólo la
  IA, en un mosaico de cabeceras (diez por página facturada). Con «Solo OCR»
  no se leen y cada hoja sale con sus páginas por nombre.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ...application.ports import Band
from ...application.progress import Stage
from .taller import Taller, _anunciar

logger = logging.getLogger(__name__)

#: Dónde mira Tesseract qué es una hoja sin capa: el tercio de arriba, donde
#: van la cabecera del listado, la de la tarjeta, el índice y el hablador.
BANDA_DE_LA_CABECERA = Band(0.0, 0.0, 1.0, 0.30)
#: La fecha y el «PAG. n» del listado, a la derecha de su cabecera.
BANDA_DE_LA_FECHA = Band(0.40, 0.0, 1.0, 0.16)
#: El tercio de arriba de la hoja de listado, para la IA: la cabecera y los
#: primeros renglones. Más estrecho, la IA lo toma por una foto.
BANDA_DEL_LISTADO = Band(0.0, 0.0, 1.0, 0.33)
#: Las fechas de pago de los comprobantes («910125 T O T A L»), a la izquierda.
BANDA_DEL_PAGO = Band(0.0, 0.0, 0.55, 1.0)
#: La cabecera de la tarjeta: apellidos, nombre, cédula y año. Medida sobre la
#: nómina de 1975: ceñida, diez de diez bien leídas; con un recorte más alto el
#: mosaico pierde nitidez y salía «CASTELLAR AGUA 4064» por CASTELLAR MEZA
#: TULIO 9064111. La tarjeta corrida, cuyo nombre no sale, se mira otra vez con
#: más papel (``_mas_alta``). No se ancla en el rótulo «Apellidos» de la capa:
#: el escáner lo trae desplazado.
BANDA_DE_LA_TARJETA = Band(0.40, 0.05, 0.78, 0.17)
#: El renglón del nombre de la hoja manuscrita, y la casilla del año: medido
#: sobre el libro de anotaciones de 1972 y las anotaciones de pago de 1974.
BANDA_DE_LA_HOJA = Band(0.10, 0.0, 0.80, 0.17)

#: Cuántas cabeceras por página facturada y a qué resolución. La tarjeta, diez
#: a 200 ppp (las diez leídas, 2026-11-06); la hoja a lápiz de 1974 necesita
#: 300 ppp, y a esa resolución caben ocho.
CABECERAS_DE_TARJETA = (10, 200)
CABECERAS_DE_HOJA = (8, 300)

#: Una capa de texto con menos letras que esto no dice qué hoja es.
_CAPA_POBRE = 60


def _sin_tildes(texto: str) -> str:
    plano = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", "-", plano).strip("-")


def _letras(texto: str) -> int:
    return sum(1 for caracter in texto if caracter.isalpha())


#: Lo más largo que se deja ser al nombre de un PDF, sin la extensión (ver historias).
LARGO_DEL_NOMBRE = 80


def nombre_del_pdf(orden: int, documento, *, carpeta: Path | None = None) -> str:
    """El nombre del PDF de un documento, en mayúsculas y con su orden delante.

    - Una persona: sólo su nombre y su cédula, como las historias académicas
      («quítale lo que dice historias académicas», el operador, 2026-11-06):
      «03_CASTELLAR-MEZA-TULIO-9064111.pdf». Sin nombre, sus páginas:
      «07_PAGINAS-12-13.pdf».
    - Un listado: «NOMINA» y su fecha, «05_NOMINA-03-07-1984.pdf»; un mes de
      comprobantes, «NOMINA-01-1991»; el del hablador, «LISTADO-DE-NOMINA-PERSONAL-1991».
    - El índice: «01_INDICE.pdf».
    """
    from ...domain import nomina as n
    from ...domain.naming import WINDOWS_PATH_LIMIT

    paginas = f"PAGINAS-{documento.paginas[0]}-{documento.paginas[-1]}"
    if documento.clase == n.DEL_INDICE:
        cuerpo, cola = "INDICE", ""
    elif documento.clase == n.PAQUETE:
        inicial = min(documento.fechas, key=lambda f: (f[2], f[1], f[0])) if documento.fechas else None
        if documento.anio is not None and not documento.fechas:
            cuerpo = f"LISTADO-DE-NOMINA-PERSONAL-{documento.anio}"
        elif inicial and documento.plantilla == n.COMPROBANTE:
            cuerpo = f"NOMINA-{inicial[1]:02d}-{inicial[2]}"
        elif inicial:
            cuerpo = f"NOMINA-{inicial[0]:02d}-{inicial[1]:02d}-{inicial[2]}"
        else:
            cuerpo = f"NOMINA-{paginas}"
        if documento.anio is not None and documento.fechas:
            cuerpo = f"LISTADO-DE-NOMINA-PERSONAL-{documento.anio}-{cuerpo}"
        cola = ""
    else:
        cuerpo = _sin_tildes(documento.nombre) if documento.nombre else paginas
        cola = f"-{documento.cedula}" if documento.cedula else ""
    cabe = LARGO_DEL_NOMBRE
    if carpeta is not None:
        cabe = min(cabe, WINDOWS_PATH_LIMIT - len(str(carpeta)) - 1 - len(".pdf"))
    prefijo = f"{orden:02d}_"
    cuerpo = cuerpo[: max(cabe - len(prefijo) - len(cola), 12)].rstrip("-")
    return f"{prefijo}{cuerpo}{cola}.pdf"


def _fecha(fecha) -> str | None:
    return f"{fecha[0]:02d}/{fecha[1]:02d}/{fecha[2]}" if fecha else None


def nominas_job(payload: dict) -> dict:
    """Divide e inventaría un libro de nómina: un PDF por persona, por paquete o por índice."""
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
    from ...domain.naming import document_folder

    taller = Taller.desde(payload)
    carpeta = taller.source.parent.name if payload.get("destination") else ""
    nombre = Path(taller.name).name
    local = HeaderAndPageOcr(language=taller.settings["ocr_language"])
    de_pago = taller.lector_de_pago()
    hilos = max(1, min(4, int(taller.settings.get("page_workers") or 4)))

    source = PyMuPDFPageSource(taller.source, taller.name)
    try:
        total = source.page_count
        _anunciar(payload, Stage.OPENED, page_count=total)

        # 1. La capa de texto de cada hoja: qué es, gratis.
        textos: list[str] = []
        for numero in range(1, total + 1):
            taller.control.check()
            textos.append(source.text_of(numero) or "")
            _anunciar(
                payload, Stage.PAGE, page_count=total, detail="leyendo cada página", done=numero, total=total,
                page_number=numero, provenance="text_layer",
            )
        plantillas = [n.plantilla_de(texto) for texto in textos]

        # 2. Lo que la capa no dice, la cabecera con Tesseract: los libros de
        # 1974 y de 1977-1984 no traen capa.
        sin_capa = [i + 1 for i, (t, p) in enumerate(zip(textos, plantillas, strict=True)) if p is None and _letras(t) < _CAPA_POBRE]
        cabeceras = _con_tesseract(
            payload, taller, source, local, sin_capa, BANDA_DE_LA_CABECERA, dpi=250, hilos=hilos,
            detalle="leyendo la cabecera de las hojas sin capa de texto",
        )
        for numero, texto in cabeceras.items():
            plantillas[numero - 1] = n.plantilla_de(texto)
        del_libro = n.plantilla_del_libro(plantillas)
        # La hoja que no dice nada es de lo que es el libro: una tarjeta u hoja
        # de persona, o la continuación del listado. En un libro de
        # certificados no: es un anexo y va con su certificado.
        muda = None if del_libro == n.CERTIFICADO else del_libro
        hojas = [n.Hoja(numero=i + 1, plantilla=p if p is not None else muda) for i, p in enumerate(plantillas)]

        def lo_leido(numero: int) -> str:
            return f"{textos[numero - 1]}\n{cabeceras.get(numero, '')}"

        # 3. El año del hablador y del índice. El hablador que no lo dice en su
        # capa se lee entero con Tesseract: es una hoja de letras grandes.
        for hoja in hojas:
            if hoja.plantilla in (n.HABLADOR, n.INDICE):
                hoja.anio = n.anio_del_hablador(lo_leido(hoja.numero))
        sin_anio = [h.numero for h in hojas if h.plantilla == n.HABLADOR and h.anio is None]
        for numero, texto in _con_tesseract(
            payload, taller, source, local, sin_anio, None, dpi=150, hilos=hilos, detalle="leyendo el año del hablador"
        ).items():
            hojas[numero - 1].anio = n.anio_del_hablador(texto)

        # 4. La fecha y el «PAG. n» de cada listado; las fechas de pago de cada comprobante.
        for hoja in hojas:
            if hoja.plantilla == n.LISTADO:
                hoja.fecha = n.fecha_del_listado(lo_leido(hoja.numero))
                hoja.pagina = n.pagina_del_listado(lo_leido(hoja.numero))
            elif hoja.plantilla == n.COMPROBANTE:
                hoja.fechas = tuple(n.fechas_de_pago(lo_leido(hoja.numero)))
        listados = [h.numero for h in hojas if h.plantilla == n.LISTADO]
        if de_pago is not None:
            # Con la IA, la cabecera de cada hoja de listado: Tesseract lee mal
            # una fecha de cada tres en esa impresión de matriz («2.07.84» por
            # «3.07.84»). El tercio de arriba, una por imagen: en mosaico la IA
            # toma las franjas por fotos y no las transcribe (2026-11-06).
            for numero, texto in _con_la_ia(
                payload, taller, source, de_pago, listados, BANDA_DEL_LISTADO, dpi=200, hilos=hilos,
                detalle="leyendo con la IA la fecha de cada hoja de listado",
            ).items():
                hoja = hojas[numero - 1]
                hoja.fecha = n.fecha_del_listado(texto) or hoja.fecha
                hoja.pagina = n.pagina_del_listado(texto) or hoja.pagina
        sin_fecha = [numero for numero in listados if hojas[numero - 1].fecha is None]
        for numero, texto in _con_tesseract(
            payload, taller, source, local, sin_fecha, BANDA_DE_LA_FECHA, dpi=300, hilos=hilos,
            detalle="leyendo la fecha de cada listado",
        ).items():
            hoja = hojas[numero - 1]
            hoja.fecha = n.fecha_del_listado(texto)
            hoja.pagina = hoja.pagina or n.pagina_del_listado(texto)
        sin_pago = [h.numero for h in hojas if h.plantilla == n.COMPROBANTE and not h.fechas]
        for numero, texto in _con_tesseract(
            payload, taller, source, local, sin_pago, BANDA_DEL_PAGO, dpi=200, hilos=hilos,
            detalle="leyendo la fecha de pago de los comprobantes",
        ).items():
            hojas[numero - 1].fechas = tuple(n.fechas_de_pago(texto))

        # 5. El nombre, la cédula y el año de cada persona: la cabecera de su
        # tarjeta u hoja con la IA, si se pidió.
        sin_leer_la_cabecera, copiadas = _leer_las_personas(payload, taller, source, hojas)

        # 6. Los certificados: de su capa; con la IA, la hoja entera si falta algo.
        for hoja in hojas:
            if hoja.plantilla != n.CERTIFICADO:
                continue
            hoja.datos = n.leer_el_certificado(lo_leido(hoja.numero))
            if de_pago is not None and not (hoja.datos.nombre and hoja.datos.cedula and hoja.datos.fecha):
                try:
                    leido = de_pago.read(source.render(hoja.numero, dpi=200, formato="jpeg")).text or ""
                    hoja.datos = n.leer_el_certificado(leido)
                except Exception:  # noqa: BLE001 - sin la relectura, lo de la capa
                    logger.warning("la IA no pudo leer el certificado de la página %s", hoja.numero, exc_info=True)

        # 7. Los documentos, y la fecha de cada paquete confirmada por la IA.
        documentos = n.documentos(hojas, tolerante=de_pago is None)
        notas_de_la_fecha = _confirmar_las_fechas(payload, taller, source, de_pago, hojas, documentos)
        documentos, notas_de_la_fecha = _juntar_los_paquetes_iguales(documentos, notas_de_la_fecha)

        anio_del_libro = n.anio_del_libro(nombre, [h.anio for h in hojas if h.plantilla == n.INDICE and h.anio])
        tipo_de_hoja = n.tipo_de_la_hoja(nombre)
        ventana = n.ventana_del_libro(nombre)
        # El patrón del libro: si sus hojas manuscritas traen cédula -- las de
        # 1974 sí, las de 1972 no --, la que no la trae es para mirar.
        personas = [d for d in documentos if d.clase == n.PERSONA]
        con_cedula = sum(1 for d in personas if d.cedula)
        piden_cedula = {n.TARJETA, n.CERTIFICADO} | ({n.HOJA} if personas and con_cedula * 2 >= len(personas) else set())

        pidio_dividir = payload.get("task") in (str(TaskKind.SPLIT), str(TaskKind.BOTH))
        del_revisor = perfil_de("nominas")
        revision = aviso_del_revisor = None
        if documentos:
            por_pagina = dict(enumerate(textos, start=1))
            # Lo que abre por una regla y con lo leído: otro nombre, otra fecha,
            # el hablador, el índice. La capa del escáner sobre una tarjeta a
            # mano acaba sin punto, y el revisor tomaba eso por una frase que
            # sigue en la hoja siguiente. Lo que abre sin nombre leído lo sigue
            # mirando él.
            abren = frozenset(
                d.paginas[0]
                for d in documentos
                if d.clase != n.PERSONA or d.nombre
            )
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
                    with pymupdf.open() as nuevo:
                        for numero in documento.paginas:
                            nuevo.insert_pdf(original, from_page=numero - 1, to_page=numero - 1)
                        nuevo.save(carpeta_de_salida / archivo, garbage=3, deflate=True)
                    esperado[archivo] = list(documento.paginas)
                    salidas.append((carpeta_de_salida / archivo).relative_to(taller.destination).as_posix())
                inicial, final, de_donde = n.fechas_extremas(documento, anio_del_libro=anio_del_libro, ventana=ventana)
                notas = _lo_que_falta(documento, inicial, piden_cedula, sin_leer_la_cabecera, con_ia=de_pago is not None)
                if de_donde:
                    notas.append(f"fechas: {de_donde}")
                notas.extend(notas_de_la_fecha.get(id(documento), []))
                notas.extend(f"{duda}: revísela" for duda in documento.dudas)
                notas.extend(
                    f"en la página {pagina} la IA leyó la cédula {copiadas[pagina]}, la de la hoja siguiente: no se tomó"
                    for pagina in documento.paginas
                    if pagina in copiadas
                )
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
                        "asunto": n.asunto(documento, tipo_de_hoja=tipo_de_hoja),
                        "nombre": documento.nombre,
                        "cedula": documento.cedula,
                        "pide_cedula": documento.plantilla in piden_cedula,
                        "fecha_inicial": _fecha(inicial),
                        "fecha_final": _fecha(final),
                        "folios": len(documento.paginas),
                        "pagina_inicial": documento.paginas[0],
                        "pagina_final": documento.paginas[-1],
                        "archivo": nombre,
                        "carpeta": carpeta,
                        "archivo_generado": archivo if pidio_dividir else None,
                        "observaciones": "; ".join(
                            [*([f"{', '.join(notas)} ({donde} del PDF)"] if notas else [])]
                        ),
                    }
                )
                # A la cola de revisión, lo que hay que mirar; no el año que se
                # tomó del libro o del hablador porque la hoja no lo dice, que
                # es lo normal en la tarjeta (la casilla del año va vacía).
                cola.extend(
                    {"page": documento.paginas[0], "reason": f"{archivo}: {nota}"}
                    for nota in notas
                    if not nota.startswith("fechas: el año")
                )
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
        "tipo": "nomina",
        "task": str(TaskKind.INVENTORY_FILE),
        "inventario_actas": filas,
        "nominas": {
            "plantilla_del_libro": del_libro,
            "personas": sum(1 for f in filas if f["clase"] == n.PERSONA),
            "paquetes": sum(1 for f in filas if f["clase"] == n.PAQUETE),
            "indices": sum(1 for f in filas if f["clase"] == n.DEL_INDICE),
        },
        "groups": [{"code": fila["archivo_generado"] or str(orden)} for orden, fila in enumerate(filas, start=1)],
        "review_queue": cola,
    }
    if pidio_dividir:
        report["outputs"] = salidas
        report["dividido"] = True
    if de_pago is None and any(h.plantilla in (n.TARJETA, n.HOJA) for h in hojas):
        report.setdefault("notices", []).append(
            "Con «Solo OCR» no se leen los nombres escritos a mano: cada tarjeta u hoja salió aparte, con sus "
            "páginas por nombre. Con «OCR + IA» se leen y se unen las de la misma persona."
        )
    integridad = revisar_los_datos(filas, del_revisor.datos, aceptable=del_revisor.margen) if del_revisor.datos else None
    if revision is not None or aviso_del_revisor or comprobacion or integridad is not None:
        anotar_en_el_informe(
            report, revision, aviso_del_revisor, comprobacion, perfil=del_revisor.as_dict(), integridad=integridad
        )
    _escribir_el_fuid(payload, taller, nombre, filas, report)
    return report


def _con_tesseract(payload, taller, source, local, paginas, banda, *, dpi, hilos, detalle) -> dict[int, str]:
    """Lo que lee Tesseract en ``banda`` de cada página (la hoja entera sin banda). Gratis.

    Se rasteriza en este hilo -- MuPDF no es seguro entre hilos -- y se lee en
    varios: Tesseract es otro proceso por lectura.
    """
    if not paginas:
        return {}
    leidas: dict[int, str] = {}
    _anunciar(payload, Stage.IDENTIFYING, detail=detalle, done=0, total=len(paginas))

    def leer(par):
        numero, imagen = par
        try:
            return numero, local.read(imagen).text or ""
        except Exception:  # noqa: BLE001 - una hoja que no se deja leer queda sin leer
            logger.debug("Tesseract no pudo leer la página %s", numero, exc_info=True)
            return numero, ""

    with ThreadPoolExecutor(max_workers=hilos) as pool:
        futuros = []
        for numero in paginas:
            taller.control.check()
            try:
                imagen = source.render(numero, banda, dpi) if banda is not None else source.render(numero, dpi=dpi)
            except Exception:  # noqa: BLE001
                logger.debug("no se pudo rasterizar la página %s", numero, exc_info=True)
                continue
            futuros.append(pool.submit(leer, (numero, imagen)))
        for hecho, futuro in enumerate(futuros, start=1):
            numero, texto = futuro.result()
            leidas[numero] = texto
            _anunciar(payload, Stage.IDENTIFYING, detail=detalle, done=hecho, total=len(paginas))
    return leidas


def _con_la_ia(payload, taller, source, de_pago, paginas, banda, *, dpi, hilos, detalle) -> dict[int, str]:
    """Lo que lee la IA en ``banda`` de cada página, una por imagen: una página facturada cada una."""
    if not paginas or de_pago is None:
        return {}
    leidas: dict[int, str] = {}
    _anunciar(payload, Stage.IDENTIFYING, detail=detalle, done=0, total=len(paginas))

    def leer(par):
        numero, imagen = par
        try:
            return numero, de_pago.read(imagen).text or ""
        except Exception:  # noqa: BLE001 - una hoja que no se deja leer queda para Tesseract
            logger.warning("la IA no pudo leer la página %s", numero, exc_info=True)
            return numero, ""

    with ThreadPoolExecutor(max_workers=hilos) as pool:
        futuros = []
        for numero in paginas:
            taller.control.check()
            try:
                imagen = source.render(numero, banda, dpi, formato="jpeg")
            except Exception:  # noqa: BLE001
                logger.debug("no se pudo rasterizar la página %s", numero, exc_info=True)
                continue
            futuros.append(pool.submit(leer, (numero, imagen)))
        for hecho, futuro in enumerate(futuros, start=1):
            numero, texto = futuro.result()
            leidas[numero] = texto
            _anunciar(payload, Stage.IDENTIFYING, detail=detalle, done=hecho, total=len(paginas))
    return leidas


def _leer_las_personas(payload, taller, source, hojas) -> tuple[set[int], dict[int, str]]:
    """El nombre, la cédula y el año de cada tarjeta y hoja manuscrita, de su cabecera leída por la IA.

    Las que no vuelven con nombre se miran otra vez, una por imagen y con más
    zoom (el agente se asegura). La hoja en la que la IA no ve nada escrito
    arriba es el reverso o la continuación de la anterior: se marca vacía y va
    con ella. Devuelve las páginas que no se pudieron leer y, por página, la
    cédula que la IA copió de la hoja de abajo y no se tomó.
    """
    from ...domain import nomina as n

    sin_leer: set[int] = set()
    copiadas: dict[int, str] = {}
    for plantilla, (tamano, dpi), base in (
        (n.TARJETA, CABECERAS_DE_TARJETA, BANDA_DE_LA_TARJETA),
        (n.HOJA, CABECERAS_DE_HOJA, BANDA_DE_LA_HOJA),
    ):
        suyas = [h for h in hojas if h.plantilla == plantilla]
        if not suyas:
            continue
        mosaico = taller.mosaico_de_cabeceras(tamano=tamano, dpi=dpi)
        if mosaico is None:
            sin_leer.update(h.numero for h in suyas)
            continue
        def banda(_pagina: int, base: Band = base) -> Band:
            return base

        _anunciar(payload, Stage.IDENTIFYING, detail="leyendo el nombre de cada persona con la IA", done=0, total=len(suyas))
        leidas = mosaico.leer_franjas(source, [h.numero for h in suyas], banda)
        faltan = [h.numero for h in suyas if not n.leer_los_datos(leidas.get(h.numero, ""), plantilla).nombre]
        if faltan:
            # Con más papel alrededor y más zoom, una por imagen.
            mas_alta = _mas_alta(banda)
            releidas = mosaico.otra_mirada().leer_franjas(source, faltan, mas_alta)
            for numero, texto in releidas.items():
                if n.leer_los_datos(texto, plantilla).nombre or numero not in leidas:
                    leidas[numero] = texto
        for hoja in suyas:
            if hoja.numero not in leidas:
                sin_leer.add(hoja.numero)
                continue
            texto = leidas[hoja.numero]
            hoja.datos = n.leer_los_datos(texto, plantilla)
            hoja.vacia = _nada_escrito(texto, hoja.datos)
        # La cédula que la IA copió de la tarjeta de abajo en la que continúa
        # (2026-11-06): fuera, y dicho.
        limpias, quitadas = n.sin_cedulas_copiadas([h.datos for h in suyas])
        for posicion, cedula in quitadas.items():
            hoja = suyas[posicion]
            hoja.datos = limpias[posicion]
            copiadas[hoja.numero] = cedula
        _anunciar(payload, Stage.IDENTIFYING, detail="leyendo el nombre de cada persona con la IA", done=len(suyas), total=len(suyas))
    return sin_leer, copiadas


#: Los rótulos impresos de la cabecera de la tarjeta, que no son nada escrito.
_ROTULOS_DE_LA_CABECERA = re.compile(
    r"(?i)apellidos?|nombres?|c\.?\s?c\.?|\bo\b|\bnit\b|\bno\b\.?|lugar|\bde\b|expedici[oó]n|dedicaci[oó]n|a[ñn]o|acumulaci[oó]n"
)
#: Dónde empieza la cuadrícula: lo de debajo no es la cabecera.
_CUADRICULA = re.compile(r"(?i)cargo|afiliaci|timbres|retenci|devengado|detalles|sueldo|jueldo|p\.\s?s\b|p\.\s?h\b")


def _nada_escrito(texto: str, datos) -> bool:
    """Si la IA no vio nada escrito en la cabecera: ni nombre, ni cédula, ni letras fuera de los rótulos.

    Es el reverso o la tarjeta que continúa: va con la anterior. La que trae
    algo escrito sin nombre legible no es vacía: abre su PDF y va a revisión.
    """
    if datos.nombre or datos.cedula:
        return False
    cabecera = _CUADRICULA.split(texto, maxsplit=1)[0]
    return _letras(_ROTULOS_DE_LA_CABECERA.sub(" ", cabecera)) < 3


def _mas_alta(banda):
    """La misma franja con más papel arriba y abajo, para la segunda mirada."""

    def otra(pagina: int) -> Band:
        b = banda(pagina)
        alto = b.y1 - b.y0
        return Band(max(0.0, b.x0 - 0.04), max(0.0, b.y0 - alto * 0.3), min(1.0, b.x1 + 0.04), min(1.0, b.y1 + alto * 0.3))

    return otra


def _confirmar_las_fechas(payload, taller, source, de_pago, hojas, documentos) -> dict[int, list[str]]:
    """Con la IA, la fecha de cada paquete leída en su primera hoja: Tesseract confunde cifras.

    Una página facturada por paquete. Lo que la IA lee manda; si no coincide
    con lo de Tesseract, la fila lo dice. Sin la IA, la nota dice que la fecha
    salió del OCR de casa. Devuelve las notas de cada documento, por su ``id``.
    """
    from ...domain import nomina as n

    notas: dict[int, list[str]] = {}
    paquetes = [d for d in documentos if d.clase == n.PAQUETE and d.plantilla in n.DE_PAQUETE]
    if not paquetes:
        return notas
    if de_pago is not None:
        # Los listados ya los leyó la IA hoja por hoja: sólo los comprobantes.
        paquetes = [d for d in paquetes if d.plantilla == n.COMPROBANTE]
    if de_pago is None:
        for documento in paquetes:
            if documento.fechas:
                notas.setdefault(id(documento), []).append("fecha leída con el OCR de casa, sin la IA: confírmela en el papel")
        return notas
    _anunciar(payload, Stage.IDENTIFYING, detail="confirmando con la IA la fecha de cada paquete", done=0, total=len(paquetes))
    for hecho, documento in enumerate(paquetes, start=1):
        taller.control.check()
        primera = next((p for p in documento.paginas if hojas[p - 1].plantilla in n.DE_PAQUETE), documento.paginas[0])
        try:
            leido = de_pago.read(source.render(primera, dpi=200, formato="jpeg")).text or ""
        except Exception:  # noqa: BLE001 - sin la IA, lo de Tesseract
            logger.warning("la IA no pudo leer la página %s para confirmar su fecha", primera, exc_info=True)
            continue
        antes = list(documento.fechas)
        if documento.plantilla == n.COMPROBANTE:
            de_la_ia = n.fechas_de_pago(leido)
            if de_la_ia:
                anio, mes = de_la_ia[0][2], de_la_ia[0][1]
                documento.clave = (anio, mes)
                documento.fechas = [f for f in documento.fechas if (f[2], f[1]) == (anio, mes)] + de_la_ia
        elif fecha := n.fecha_del_listado(leido):
            documento.clave = (fecha[2], fecha[1], fecha[0])
            documento.fechas = [fecha]
        if antes and documento.fechas and set(antes) != set(documento.fechas) and documento.plantilla == n.LISTADO:
            leida = antes[0]
            notas.setdefault(id(documento), []).append(
                f"fecha confirmada por la IA en la página {primera} (el OCR de casa leyó "
                f"{leida[0]:02d}/{leida[1]:02d}/{leida[2]})"
            )
        if not documento.fechas:
            notas.setdefault(id(documento), []).append(f"ni el OCR ni la IA leyeron la fecha (página {primera})")
        _anunciar(payload, Stage.IDENTIFYING, detail="confirmando con la IA la fecha de cada paquete", done=hecho, total=len(paquetes))
    return notas


def _juntar_los_paquetes_iguales(documentos, notas):
    """Dos paquetes seguidos con la misma fecha son uno: «paquete completo cuando las fechas son iguales».

    Pasa cuando Tesseract leyó una fecha distinta a media relación y la IA la
    confirmó igual a la anterior. El que abre un hablador no se junta con el
    de antes: el hablador divide los años.
    """
    from ...domain import nomina as n

    juntos: list = []
    for documento in documentos:
        previo = juntos[-1] if juntos else None
        if (
            previo is not None
            and documento.clase == n.PAQUETE
            and previo.clase == n.PAQUETE
            and documento.anio is None
            and documento.clave is not None
            and documento.clave == previo.clave
        ):
            previo.paginas.extend(documento.paginas)
            previo.fechas.extend(documento.fechas)
            notas.setdefault(id(previo), []).extend(notas.pop(id(documento), []))
            continue
        juntos.append(documento)
    return juntos, notas


def _lo_que_falta(documento, inicial, piden_cedula, sin_leer, *, con_ia: bool) -> list[str]:
    """Lo que no se leyó del documento, dicho para la fila y la cola de revisión."""
    from ...domain import nomina as n

    faltan: list[str] = []
    if documento.clase == n.PERSONA:
        if not documento.nombre:
            faltan.append(
                "no se leyó el nombre" + ("" if con_ia else " (con «Solo OCR» no se lee lo escrito a mano)")
            )
        if documento.plantilla in piden_cedula and not documento.cedula:
            faltan.append("no se leyó la cédula")
        if any(p in sin_leer for p in documento.paginas) and con_ia:
            faltan.append("la IA no pudo leer la cabecera de alguna de sus hojas")
    elif documento.clase == n.PAQUETE and not documento.fechas and documento.anio is None:
        faltan.append("no se leyó la fecha del listado")
    if inicial is None:
        faltan.append("sin fechas extremas")
    return faltan


def _reparto(documentos):
    """Los documentos como grupos de páginas para el revisor de cortes."""
    from ...domain.grouping import GroupingResult, PageGroup
    from ...domain.resolution_code import ResolutionCode

    return GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=f"{orden:03d}", raw=f"{orden:03d}"), page_numbers=list(d.paginas))
            for orden, d in enumerate(documentos, start=1)
        ]
    )


def _escribir_el_fuid(payload: dict, taller: Taller, nombre: str, filas: list[dict], report: dict) -> None:
    """El FUID del PDF junto al trabajo, con la oficina de su carpeta. Que falle no deshace lo leído."""
    from ...adapters.excel_actas import SUFIJO
    from ...adapters.fuid_de_la_entrega import escribir_fuid
    from ...domain.naming import sheet_filename

    _anunciar(payload, Stage.INVENTORYING, detail="escribiendo el FUID", done=0, total=1)
    destino = taller.destination / sheet_filename(nombre, SUFIJO, directory_length=len(str(taller.destination)))
    try:
        report["inventario"] = escribir_fuid(filas, destino, oficina=payload.get("oficina")).name
    except Exception as error:  # noqa: BLE001 - lo leído sirve igual
        logger.warning("no se pudo escribir el FUID de %s", nombre, exc_info=True)
        report["inventario_error"] = f"{type(error).__name__}: {error}"
    _anunciar(payload, Stage.DONE)
