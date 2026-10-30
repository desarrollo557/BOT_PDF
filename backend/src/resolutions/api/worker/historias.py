"""Las historias académicas: un PDF por estudiante y su fila en el FUID FO-GD-008.

Ver ``domain/historia_academica.py`` para cómo se reconoce cada expediente. Aquí
se lee cada página, se relee con el OCR de casa la que no se dejó clasificar por
su capa de texto, y se entrega como las actas de grado: los PDF y una fila por
estudiante, que la corrida de carpeta reúne en el FUID de cada subcarpeta.

El corte nunca paga: sale de la capa de texto y del OCR de casa. La IA, si se
pidió, lee sólo la ficha de los estudiantes a los que les falta el nombre o la
cédula después de mirar su ficha y su certificado de matrícula -- que trae el
nombre y el código a máquina --: una página facturada por estudiante, como
mucho, y ninguna por los certificados (2026-10-30).
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
        Ficha,
        abre_expediente,
        es_de_notas,
        es_ficha,
        expedientes,
        leer_ficha,
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

        # Y la IA, si se pidió, sólo donde hace falta: la ficha del estudiante
        # al que, después de su ficha y su certificado, le falta el nombre o la
        # cédula. Lo que lee manda sobre lo de casa, que en la ficha escrita a
        # mano casi nunca es el nombre entero.
        faltan = [
            unidad
            for unidad in unidades
            if unidad.ficha is not None
            and unidad.pagina_de_la_ficha is not None
            and not (unidad.ficha.nombre and unidad.ficha.cedula)
        ]
        textos_de_la_ficha: dict[int, str] = {}
        # Y si ni así sale el nombre, la IA lo saca del texto que el OCR de pago
        # ya leyó: se paga por tokens, no por otra página (2026-10-30).
        nombrador = taller.lector_del_estudiante() if de_pago is not None else None
        if de_pago is not None and faltan:
            for hecho, unidad in enumerate(faltan, start=1):
                taller.control.check()
                _anunciar(
                    payload, Stage.IDENTIFYING, detail="leyendo la ficha de cada estudiante", done=hecho, total=len(faltan)
                )
                try:
                    leido = de_pago.read(source.render(unidad.pagina_de_la_ficha, dpi=200, formato="jpeg")).text
                except Exception:  # noqa: BLE001 - sin la IA queda lo del OCR de casa
                    logger.warning(
                        "la IA no pudo leer la ficha de la página %s de %s", unidad.pagina_de_la_ficha, nombre, exc_info=True
                    )
                    continue
                textos_de_la_ficha[unidad.pagina_de_la_ficha] = leido
                de_la_ia, de_casa = leer_ficha(leido), unidad.ficha
                nombre_leido = de_la_ia.nombre or de_casa.nombre
                if nombre_leido is None and nombrador is not None:
                    nombre_leido = _nombre_por_la_ia(nombrador, leido, nombre)
                unidad.ficha = Ficha(
                    nombre=nombre_leido,
                    cedula=de_la_ia.cedula or de_casa.cedula,
                    codigo=de_casa.codigo or de_la_ia.codigo,
                    anio_de_grado=de_la_ia.anio_de_grado or de_casa.anio_de_grado,
                    tarjeta=de_la_ia.tarjeta or de_casa.tarjeta,
                )

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
                inicial, final = _anios_del_expediente(
                    unidad, textos, textos_de_la_ficha, sin_la_ficha(unidad.paginas), ventana, source, local
                )
                if (inicial is None or final is None) and de_pago is not None:
                    inicial, final = _anios_de_las_notas_por_la_ia(
                        unidad, textos, textos_de_la_ficha, sin_la_ficha(unidad.paginas), ventana, source, de_pago
                    ) or (inicial, final)
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
        "review_queue": [],
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


def _anios_de_las_notas_por_la_ia(unidad, textos, textos_de_la_ficha, de_las_hojas, ventana, source, de_pago):
    """Los años de la hoja de notas leída por la IA, si la ficha no dice los dos extremos.

    Las notas de 1979 a 1987 van escritas a mano -- «I Semestre 1979» … «VIII
    sem 1º p. acad. 1.984» -- y la capa de texto no deja leer ningún año: el
    primero quedaba N/A en 34 de las 85 historias de UPD3859718 (2026-10-30).
    Una página facturada más, sólo para esos estudiantes. ``None`` si no aporta.
    """
    from ...domain.historia_academica import anios, anios_de_la_ficha

    notas = [numero for numero in unidad.paginas if numero != unidad.pagina_de_la_ficha][:1]
    if not notas:
        return None
    try:
        leida = de_pago.read(source.render(notas[0], dpi=200, formato="jpeg")).text
    except Exception:  # noqa: BLE001 - sin la IA quedan los años que ya había
        logger.warning("la IA no pudo leer la hoja de notas de la página %s", notas[0], exc_info=True)
        return None
    if not leida:
        return None
    pagina = unidad.pagina_de_la_ficha
    de_la_ficha = anios_de_la_ficha(textos_de_la_ficha.get(pagina) or textos[pagina - 1]) if pagina else ()
    inicial, final = _con_los_extremos_de_la_ficha(
        anios([leida, *de_las_hojas], ventana=ventana, de_la_ficha=de_la_ficha), de_la_ficha
    )
    return (inicial, final) if inicial or final else None


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
