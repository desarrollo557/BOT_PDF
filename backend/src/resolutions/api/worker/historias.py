"""Las historias académicas: un PDF por estudiante y su fila en el FUID FO-GD-008.

Ver ``domain/historia_academica.py`` para cómo se reconoce cada expediente. Aquí
se lee cada página, se relee con el OCR de casa la que no se dejó clasificar por
su capa de texto, y se entrega como las actas de grado: los PDF y una fila por
estudiante, que la corrida de carpeta reúne en el FUID de cada subcarpeta.

El corte nunca paga: sale de la capa de texto y del OCR de casa. La IA, si se
pidió, lee la ficha y la primera hoja de notas de cada estudiante -- dos páginas
facturadas -- y concilia su nombre entre todo lo leído; ninguna por los
certificados. Lo pidió el operador el 2026-10-30: el nombre, la cédula y las
fechas, perfectos y del papel.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from ...application.progress import Stage
from .taller import Taller, _anunciar

logger = logging.getLogger(__name__)


def _sin_tildes(texto: str) -> str:
    plano = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", "-", plano).strip("-")


#: Lo más largo que se deja ser al nombre de un PDF de estudiante, sin la
#: extensión: con la carpeta del destino, la de la caja y la del documento
#: delante, uno de 150 pasaba el límite de Windows y la entrega no se escribía
#: («EGRESADOS 1996», 2026-10-30).
LARGO_DEL_NOMBRE = 80


def _nombre_del_pdf(orden: int, ficha, *, carpeta: Path | None = None, paginas: tuple[int, int] | None = None) -> str:
    """«03_HISTORIA-ACADEMICA-AGUAS-GARRIDO-CLARENA-LUCIA-1047382991.pdf», en mayúsculas.

    Recortado para que quepa en ``carpeta`` sin pasar el límite de Windows.
    Ninguno se llama «SIN-NOMBRE» (2026-10-30): si ni la IA leyó el nombre, el
    PDF dice sus páginas, como la regla general de «UPD… PAGINAS a-b».
    """
    from ...domain.naming import WINDOWS_PATH_LIMIT

    if ficha is None:
        return f"{orden:02d}_SIN-FICHA-DE-ESTUDIANTE.pdf"
    sin_nombre = f"PAGINAS-{paginas[0]}-{paginas[1]}" if paginas else "NOMBRE-POR-REVISAR"
    partes = ["HISTORIA-ACADEMICA", _sin_tildes(ficha.nombre) if ficha.nombre else sin_nombre]
    if ficha.cedula:
        partes.append(ficha.cedula)
    tallo = f"{orden:02d}_{'-'.join(partes)}"
    cabe = LARGO_DEL_NOMBRE
    if carpeta is not None:
        cabe = min(cabe, WINDOWS_PATH_LIMIT - len(str(carpeta)) - 1 - len(".pdf"))
    return f"{tallo[: max(cabe, 24)].rstrip('-')}.pdf"


def historias_academicas_job(payload: dict) -> dict:
    """Divide e inventaría un PDF de historias académicas, un expediente por estudiante."""
    import pymupdf

    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...adapters.tesseract_ocr import HeaderAndPageOcr
    from ...application.acta_consejo import nombres_conocidos
    from ...application.task import TaskKind
    from ...domain.historia_academica import (
        HISTORIA_ACADEMICA,
        SIN_ESTUDIANTE,
        abre_expediente,
        es_de_notas,
        es_ficha,
        expedientes,
        plano,
        plantilla_de_apertura,
        ventana_de_anios,
    )
    from ...domain.naming import document_folder

    taller = Taller.desde(payload)
    carpeta = taller.source.parent.name if payload.get("destination") else ""
    nombre = Path(taller.name).name
    local = HeaderAndPageOcr(language=taller.settings["ocr_language"])
    de_pago = taller.lector_de_pago()
    # Un nombre leído gratis -- de la capa de texto o del OCR de casa -- sólo
    # vale si dos de sus palabras están en la lista de nombres conocidos: sin
    # ella pasaban «EGISTRO DEL TUDIANTE» o «SEMESTA ANO» (Enfermería,
    # 2026-10-30). El de la IA no pasa por la lista.
    conocidas = nombres_conocidos()

    source = PyMuPDFPageSource(taller.source, taller.name)
    try:
        total = source.page_count
        _anunciar(payload, Stage.IDENTIFYING, detail="leyendo cada página", done=0, total=total)
        textos: list[str] = []
        for numero in range(1, total + 1):
            taller.control.check()
            texto = source.text_of(numero) or ""
            if not abre_expediente(texto) and not es_de_notas(texto):
                # Ni ficha ni notas según la capa de texto: o es una carta, o es
                # una ficha con la capa dañada (la 29 de «EGRESADOS 1996», que
                # dice «NOMBRE DEL ESTU'DIANTE»). El OCR de casa lo decide, sin
                # pagar nada.
                try:
                    leido = local.read(source.render(numero, dpi=200)).text
                    if len(plano(leido)) > len(plano(texto)) // 2:
                        texto = leido
                except Exception:  # noqa: BLE001 - una página que no se deja leer sigue con su capa
                    logger.debug("no se pudo releer la página %s de %s", numero, nombre, exc_info=True)
            textos.append(texto)
            _anunciar(payload, Stage.IDENTIFYING, detail="leyendo cada página", done=numero, total=total)

        # El corte, sin pagar nada: de lo que dicen las páginas.
        unidades = expedientes(textos, conocidas=conocidas)

        # Y la IA, si se pidió: la ficha y la hoja de notas de cada estudiante
        # al que le falte algo. Medido sobre 24 fichas de UPD3859718 contra el
        # papel (2026-10-30): con sólo la ficha, 10 nombres de 24 salían bien y
        # el año final se quedaba en el anotado («1983-86») y no en el último
        # semestre. La hoja de notas trae los años y el nombre otra vez, y la IA
        # concilia el nombre entre todo lo leído, sólo con palabras del papel.
        textos_de_la_ficha: dict[int, str] = {}
        notas_de_la_ia: dict[int, str] = {}
        if de_pago is not None:
            _leer_las_fichas_con_la_ia(
                payload, taller, source, de_pago, unidades, textos_de_la_ficha, notas_de_la_ia, nombre
            )
            # Y la segunda lectura de la cédula, de otra imagen: su renglón
            # ampliado. Lo que no coincide va a revisión.
            _segunda_lectura(payload, taller, source, unidades)

        # Los años, de las hojas de notas y los certificados, no de la ficha:
        # la ficha trae la fecha de nacimiento y la del bachillerato. Y dentro
        # de la ventana del PDF, para que un año suelto mal leído no lo extienda.
        def sin_la_ficha(paginas: list[int]) -> list[str]:
            return [textos[n - 1] for n in paginas if not es_ficha(plantilla_de_apertura(textos[n - 1]))]

        ventana = ventana_de_anios(sin_la_ficha(list(range(1, total + 1))), nombre=nombre)

        if not any(unidad.es_de_un_estudiante for unidad in unidades):
            # Ni una ficha reconocible: un formato que esta habilidad todavía no
            # conoce. El PDF se entrega entero, con su nombre, y lleva su fila
            # con el asunto y los años de su nombre, como el inventario del
            # cliente: ningún PDF se queda sin fila (2026-10-30).
            return _sin_estudiantes(payload, taller, nombre, carpeta, total)

        pidio_dividir = payload.get("task") in (str(TaskKind.SPLIT), str(TaskKind.BOTH))
        salidas: list[str] = []
        filas: list[dict] = []
        carpeta_de_salida = taller.destination / document_folder(nombre)
        if pidio_dividir:
            carpeta_de_salida.mkdir(parents=True, exist_ok=True)
        _anunciar(payload, Stage.ASSEMBLING, detail=f"escribiendo {len(unidades)} PDF", done=0, total=len(unidades))
        with pymupdf.open(taller.source) as original:
            for orden, unidad in enumerate(unidades, start=1):
                taller.control.check()
                archivo = _nombre_del_pdf(
                    orden, unidad.ficha, carpeta=carpeta_de_salida, paginas=(unidad.paginas[0], unidad.paginas[-1])
                )
                if pidio_dividir:
                    with pymupdf.open() as nuevo:
                        nuevo.insert_pdf(original, from_page=unidad.paginas[0] - 1, to_page=unidad.paginas[-1] - 1)
                        nuevo.save(carpeta_de_salida / archivo, garbage=3, deflate=True)
                    salidas.append((carpeta_de_salida / archivo).relative_to(taller.destination).as_posix())
                # Con lo que la IA leyó de su hoja de notas, si la leyó: ahí están
                # los años de cada semestre, escritos a mano.
                notas_leidas = notas_de_la_ia.get(unidad.pagina_de_la_ficha)
                de_las_hojas = sin_la_ficha(unidad.paginas)
                inicial, final = _anios_del_expediente(
                    unidad, textos, textos_de_la_ficha, [notas_leidas, *de_las_hojas] if notas_leidas else de_las_hojas,
                    ventana, source, local,
                )
                ficha = unidad.ficha
                faltan = []
                if ficha is not None:
                    if not ficha.nombre:
                        faltan.append("el nombre")
                    if not ficha.cedula:
                        faltan.append(
                            "la cédula"
                            + (f" (código {ficha.codigo})" if ficha.codigo else "")
                            + (f" (la ficha trae la tarjeta de identidad {ficha.tarjeta})" if ficha.tarjeta else "")
                        )
                    if inicial is None and final is None:
                        faltan.append("los años de las notas")
                    elif final is None:
                        faltan.append("el año de grado (sólo se leyó el de ingreso)")
                    elif inicial is None:
                        faltan.append("el año de ingreso (sólo se leyó el de grado)")
                donde = (
                    f"la página {unidad.paginas[0]}"
                    if len(unidad.paginas) == 1
                    else f"las páginas {unidad.paginas[0]} a {unidad.paginas[-1]}"
                )
                filas.append(
                    {
                        "tipo": HISTORIA_ACADEMICA if ficha is not None else SIN_ESTUDIANTE,
                        "nombre": ficha.nombre if ficha else None,
                        "cedula": ficha.cedula if ficha else None,
                        "codigo": ficha.codigo if ficha else None,
                        "tarjeta": ficha.tarjeta if ficha else None,
                        "anio_inicial": inicial,
                        "anio_final": final,
                        "folios": len(unidad.paginas),
                        "pagina_inicial": unidad.paginas[0],
                        "pagina_final": unidad.paginas[-1],
                        "archivo": nombre,
                        "carpeta": carpeta,
                        "archivo_generado": archivo if pidio_dividir else None,
                        "observaciones": "; ".join(
                            [
                                *([f"no se leyó {', '.join(faltan)} en {donde} del PDF: revíselo en el papel"] if faltan else []),
                                *(f"{duda}: revísela" for duda in unidad.dudas),
                            ]
                        ),
                    }
                )
                _anunciar(payload, Stage.ASSEMBLING, detail=f"escribiendo {len(unidades)} PDF", done=orden, total=len(unidades))
    finally:
        source.close()

    estudiantes = sum(1 for fila in filas if fila["tipo"] == HISTORIA_ACADEMICA)
    report: dict = {
        "document": nombre,
        "page_count": total,
        "tipo": "historia-academica",
        "task": str(TaskKind.INVENTORY_FILE),
        "inventario_actas": filas,
        "historias": estudiantes,
        "groups": [{"code": fila["archivo_generado"] or str(orden)} for orden, fila in enumerate(filas, start=1)],
        # Lo que las dos lecturas no confirmaron, en la cola de revisión de
        # siempre: la pantalla y el general de procesos ya la cuentan.
        "review_queue": [
            {"page": unidad.pagina_de_la_ficha, "reason": duda}
            for unidad in unidades
            if unidad.pagina_de_la_ficha
            for duda in unidad.dudas
        ],
    }
    if pidio_dividir:
        report["outputs"] = salidas
        report["dividido"] = True

    _escribir_el_fuid(payload, taller, nombre, filas, report)
    return report


def _anios_del_expediente(unidad, textos, textos_de_la_ficha, de_las_hojas, ventana, source, local):
    """El primer y el último año del estudiante, de sus hojas y del ingreso y el grado de su ficha.

    Si con eso no sale ninguno -- en los PDF de 2004 las notas no traen años y la
    capa de texto de la ficha dice «AÑO INGRESO 2-000» --, se relee la ficha con
    el OCR de casa, que sí lee «AÑO INGRESO 2000». Gratis y sólo esa página.
    """
    from ...domain.historia_academica import anios, anios_de_la_ficha

    pagina = unidad.pagina_de_la_ficha
    de_la_ficha = anios_de_la_ficha(textos_de_la_ficha.get(pagina) or textos[pagina - 1]) if pagina else []
    inicial, final = _con_los_extremos_de_la_ficha(anios(de_las_hojas, ventana=ventana, de_la_ficha=de_la_ficha), de_la_ficha)
    if inicial is None and pagina and pagina not in textos_de_la_ficha:
        try:
            releida = local.read(source.render(pagina, dpi=200)).text
        except Exception:  # noqa: BLE001 - sin la relectura queda N/A, con su nota
            logger.debug("no se pudo releer la ficha de la página %s", pagina, exc_info=True)
            return inicial, final
        de_la_ficha = anios_de_la_ficha(releida)
        inicial, final = _con_los_extremos_de_la_ficha(anios(de_las_hojas, ventana=ventana, de_la_ficha=de_la_ficha), de_la_ficha)
    return inicial, final


#: Cuántos estudiantes se leen con la IA a la vez: cada uno son dos páginas de
#: OCR y una consulta al chat, segundos de espera que no ocupan este proceso.
LECTORES_DE_IA = 4


def _leer_las_fichas_con_la_ia(payload, taller, source, de_pago, unidades, textos_de_la_ficha, notas_de_la_ia, nombre):
    """La ficha y la primera hoja de notas de cada estudiante, leídas por la IA, y su nombre conciliado.

    En las de 1960 a 1990, escritas a mano, la capa de texto no deja leer ni el
    nombre, ni la cédula, ni los años: dos páginas facturadas por estudiante.
    Lo que lee la IA manda sobre lo de casa. Las páginas se renderizan de a una
    -- el documento no se lee desde dos hilos -- y se piden de a ``LECTORES_DE_IA``.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from ...domain.historia_academica import Ficha, leer_ficha

    nombrador = taller.lector_del_estudiante()
    candado = threading.Lock()
    con_ficha = [unidad for unidad in unidades if unidad.ficha is not None and unidad.pagina_de_la_ficha is not None]

    def leer_pagina(numero: int) -> str:
        try:
            with candado:
                imagen = source.render(numero, dpi=200, formato="jpeg")
            return de_pago.read(imagen).text or ""
        except Exception:  # noqa: BLE001 - sin la IA queda lo del OCR de casa
            logger.warning("la IA no pudo leer la página %s de %s", numero, nombre, exc_info=True)
            return ""

    def leer(unidad):
        ficha = leer_pagina(unidad.pagina_de_la_ficha)
        siguientes = [numero for numero in unidad.paginas if numero != unidad.pagina_de_la_ficha][:1]
        notas = leer_pagina(siguientes[0]) if siguientes else ""
        conciliado = None
        if nombrador is not None and (ficha or notas):
            conciliado = _nombre_por_la_ia(nombrador, f"{ficha}\n\n{notas}".strip(), nombre)
        return unidad, ficha, notas, conciliado

    pool = ThreadPoolExecutor(max_workers=LECTORES_DE_IA)
    try:
        futuros = [pool.submit(leer, unidad) for unidad in con_ficha]
        for hecho, futuro in enumerate(as_completed(futuros), start=1):
            taller.control.check()
            _anunciar(
                payload, Stage.IDENTIFYING, detail="leyendo con la IA la ficha y las notas de cada estudiante",
                done=hecho, total=len(futuros),
            )
            unidad, ficha, notas, conciliado = futuro.result()
            if ficha:
                textos_de_la_ficha[unidad.pagina_de_la_ficha] = ficha
            if notas:
                notas_de_la_ia[unidad.pagina_de_la_ficha] = notas
            de_la_ia, de_casa = leer_ficha(ficha), unidad.ficha
            unidad.ficha = Ficha(
                nombre=conciliado or de_la_ia.nombre or de_casa.nombre,
                cedula=de_la_ia.cedula or de_casa.cedula,
                codigo=de_casa.codigo or de_la_ia.codigo,
                anio_de_grado=de_la_ia.anio_de_grado or de_casa.anio_de_grado,
                tarjeta=de_la_ia.tarjeta or de_casa.tarjeta,
            )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _segunda_lectura(payload, taller, source, unidades) -> None:
    """La cédula y la tarjeta de cada ficha releídas en su renglón ampliado: lo que discrepa, a revisión.

    Ver ``domain/doble_lectura.py``. Diez renglones por página facturada: unas
    diez páginas por cada cien estudiantes. El nombre no: releído así daba más
    alarmas falsas que errores (33 en 85 fichas de UPD3859718).
    """
    from dataclasses import replace

    from ...domain.doble_lectura import conciliar_numero
    from ...domain.historia_academica import FRANJA_DE_LA_CEDULA, leer_ficha

    con_ficha = [unidad for unidad in unidades if unidad.ficha is not None and unidad.pagina_de_la_ficha]
    if not con_ficha:
        return
    taller.control.check()
    _anunciar(payload, Stage.IDENTIFYING, detail="releyendo la cédula en su renglón ampliado")
    mosaico = taller.mosaico_de_campo(FRANJA_DE_LA_CEDULA)
    leidos = mosaico.leer_franjas(source, [unidad.pagina_de_la_ficha for unidad in con_ficha]) if mosaico else {}
    for unidad in con_ficha:
        de_la_cedula = leer_ficha(leidos.get(unidad.pagina_de_la_ficha, ""))
        cedula, duda_de_la_cedula = conciliar_numero(unidad.ficha.cedula, de_la_cedula.cedula, "la cédula")
        tarjeta, duda_de_la_tarjeta = conciliar_numero(
            unidad.ficha.tarjeta, de_la_cedula.tarjeta, "la tarjeta de identidad"
        )
        unidad.ficha = replace(unidad.ficha, cedula=cedula, tarjeta=tarjeta)
        unidad.dudas.extend(duda for duda in (duda_de_la_cedula, duda_de_la_tarjeta) if duda)


def _con_los_extremos_de_la_ficha(de_las_notas, de_la_ficha):
    """Si la ficha dice los dos extremos -- «1965-1968» y el grado en 1970 --, mandan sobre el grupo de las notas.

    El grupo de años de ``anios`` parte en dos un ingreso y un grado separados
    más de cuatro años, y se quedaba con uno solo: «1961-1961» para quien
    entró en 1961 y se licenció en 1974 (caja 00C003277, 2026-10-30).
    """
    inicial, final = de_las_notas
    ingreso, grado = (list(de_la_ficha) + [None, None])[:2]
    if ingreso and grado and ingreso <= grado:
        inicial = min(ingreso, inicial or ingreso)
        final = max(grado, final or grado)
    return inicial, final


def _nombre_por_la_ia(nombrador, texto: str, nombre: str) -> str | None:
    """El nombre del estudiante que la IA saca del texto de su ficha, o ``None`` si no lo dice el papel."""
    from ...application.ports import ResumenNoDisponible
    from ...domain.historia_academica import nombre_de_la_ia

    try:
        respuesta = nombrador.resumir(texto)
    except ResumenNoDisponible as error:
        logger.warning("la IA no nombró a un estudiante de %s: %s", nombre, error)
        return None
    return nombre_de_la_ia(respuesta, texto)


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


def _sin_estudiantes(payload: dict, taller: Taller, nombre: str, carpeta: str, total: int) -> dict:
    """Un PDF sin ninguna ficha reconocible: una fila para el PDF entero, que se entrega tal cual."""
    from ...adapters.fuid_de_la_entrega import PDF_ENTERO
    from ...application.task import TaskKind

    logger.info("%s: ninguna ficha de estudiante reconocible; se inventaría el PDF entero", nombre)
    _anunciar(payload, Stage.ASSEMBLING, detail="ninguna ficha reconocible: el PDF se inventaría entero")
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
                "No se reconoció la ficha de ningún estudiante: se inventaría el PDF entero, "
                "con el asunto y los años de su nombre. Revíselo para dividirlo por estudiante."
            ),
        }
    ]
    report: dict = {
        "document": nombre,
        "page_count": total,
        "tipo": "historia-academica",
        "task": str(TaskKind.INVENTORY_FILE),
        "inventario_actas": filas,
        "historias": 0,
        "groups": [{"code": "1"}],
        "review_queue": [],
        "notices": ["Ninguna ficha de estudiante reconocible: el PDF se entregó entero, con una fila en el FUID."],
    }
    _escribir_el_fuid(payload, taller, nombre, filas, report)
    return report
