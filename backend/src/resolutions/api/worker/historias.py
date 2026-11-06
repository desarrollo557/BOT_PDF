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
import threading
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
    """«04_BARRIOS-RIVERA-HELIDA-45427277.pdf»: orden, nombre y cédula, en mayúsculas.

    Lo dictó el operador el 2026-10-30: sin «HISTORIA-ACADEMICA», que ya dice
    la carpeta. Sin cédula, las cifras de la tarjeta de identidad
    («…-61120803173»); sin ninguna de las dos, las de la libreta militar
    (2026-11-06); o nada. Recortado para que quepa en ``carpeta`` sin pasar el límite de
    Windows, y siempre por el nombre: la cédula no se corta nunca. Ninguno se
    llama «SIN-NOMBRE»: si ni la IA leyó el nombre, el PDF dice sus páginas,
    como la regla general de «UPD… PAGINAS a-b».
    """
    from ...domain.naming import WINDOWS_PATH_LIMIT

    if ficha is None:
        return f"{orden:02d}_SIN-FICHA-DE-ESTUDIANTE.pdf"
    sin_nombre = f"PAGINAS-{paginas[0]}-{paginas[1]}" if paginas else "NOMBRE-POR-REVISAR"
    nombre = _sin_tildes(ficha.nombre) if ficha.nombre else sin_nombre
    # Sólo cifras, sea cédula, tarjeta o libreta militar, en ese orden: sin
    # «TI», guiones ni puntos (lo dictó el operador el 2026-10-30).
    documento = ficha.identificacion[1] if ficha.identificacion else ""
    cola = f"-{documento}" if documento else ""
    cabe = LARGO_DEL_NOMBRE
    if carpeta is not None:
        cabe = min(cabe, WINDOWS_PATH_LIMIT - len(str(carpeta)) - 1 - len(".pdf"))
    prefijo = f"{orden:02d}_"
    nombre = nombre[: max(cabe - len(prefijo) - len(cola), 12)].rstrip("-")
    return f"{prefijo}{nombre}{cola}.pdf"


def historias_academicas_job(payload: dict) -> dict:
    """Divide e inventaría un PDF de historias académicas, un expediente por estudiante."""
    from dataclasses import replace

    import pymupdf

    from ...adapters.huellas_pdf import huellas_de
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...adapters.tesseract_ocr import HeaderAndPageOcr
    from ...application.acta_consejo import nombres_conocidos
    from ...application.entrega import comprobar_archivos
    from ...application.integridad_de_los_datos import revisar_los_datos
    from ...application.perfiles_de_revision import perfil_de
    from ...application.revisor_de_cortes import anotar_en_el_informe, revisar_sin_romper
    from ...application.task import TaskKind
    from ...domain.datos_esperados import (
        MAXIMO_DE_ANIOS,
        anio_del_codigo,
        apellidos_al_derecho,
        codigo_por_el_patron,
        patron_de_los_codigos,
    )
    from ...domain.historia_academica import (
        HISTORIA_ACADEMICA,
        SIN_ESTUDIANTE,
        abre_expediente,
        anios,
        codigo_sin_rotulo,
        es_de_notas,
        es_ficha,
        expedientes,
        plano,
        plantilla_de_apertura,
        ventana_de_anios,
    )
    from ...domain.historia_medicina import (
        FICHA_DE_MEDICINA,
        MARGEN_DE_MEDICINA,
        al_reves,
        anios_del_legajo,
        clase_de_pagina,
        es_de_hojas_sueltas,
        es_de_medicina,
        nombre_del_renglon,
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
        # Cuántas páginas trae, para que la pantalla dibuje sus cuadritos; y
        # luego cada una al leerla, con de dónde salió su texto.
        _anunciar(payload, Stage.OPENED, page_count=total)
        textos: list[str] = []
        for numero in range(1, total + 1):
            taller.control.check()
            texto = source.text_of(numero) or ""
            procedencia = "text_layer"
            if al_reves(texto):
                # Una hoja de Medicina escaneada cabeza abajo: se endereza, y su
                # texto es el de Tesseract leyéndola derecha. Gratis.
                source.enderezar(numero)
                try:
                    texto = local.read(source.render(numero, dpi=200)).text
                    procedencia = "ocr_full_page"
                except Exception:  # noqa: BLE001 - sin relectura sigue con su capa
                    logger.debug("no se pudo releer derecha la página %s de %s", numero, nombre, exc_info=True)
            # La ficha y las notas de Medicina se reconocen por su capa: releída,
            # la hoja «ASIGNAITURAS» de Espinosa Buelvas perdía su clase y su
            # nombre (internados 1978-1984, pág. 24).
            if not abre_expediente(texto) and not es_de_notas(texto) and clase_de_pagina(texto) is None:
                # Ni ficha ni notas según la capa de texto: o es una carta, o es
                # una ficha con la capa dañada (la 29 de «EGRESADOS 1996», que
                # dice «NOMBRE DEL ESTU'DIANTE»). El OCR de casa lo decide, sin
                # pagar nada.
                try:
                    leido = local.read(source.render(numero, dpi=200)).text
                    if len(plano(leido)) > len(plano(texto)) // 2:
                        texto = leido
                        procedencia = "ocr_full_page"
                except Exception:  # noqa: BLE001 - una página que no se deja leer sigue con su capa
                    logger.debug("no se pudo releer la página %s de %s", numero, nombre, exc_info=True)
            textos.append(texto)
            _anunciar(
                payload, Stage.PAGE, page_count=total, detail="leyendo cada página", done=numero, total=total,
                page_number=numero, provenance=procedencia,
            )

        # Medicina se corta por el nombre de cada ficha y de cada hoja de notas,
        # que lee la IA si se pidió (2026-11-03). Lo demás, sin pagar nada: de
        # lo que dicen las páginas.
        # Los legajos de matrículas, certificados y recibos de Medicina, un PDF
        # por hoja (2026-10-30), con lo que la IA lee de cada una.
        de_medicina = es_de_medicina(textos)
        de_hojas = not de_medicina and es_de_hojas_sueltas(textos)
        hojas, portada = {}, ""
        # Las lecturas del nombre de cada estudiante -- por su primera página --
        # y los renglones de donde salieron, para votarlas y corregirlas.
        lecturas: dict[int, list[str]] = {}
        renglones: dict[int, list[tuple[object, int]]] = {}
        if de_medicina:
            unidades, lecturas, renglones = _expedientes_de_medicina(payload, taller, source, local, textos, nombre)
        elif de_hojas:
            unidades, hojas, portada = _hojas_sueltas(payload, taller, source, de_pago, textos, nombre)
            lecturas = {u.paginas[0]: [u.ficha.nombre] for u in unidades if u.ficha is not None and u.ficha.nombre}
        else:
            unidades = expedientes(textos, conocidas=conocidas)

        # Los años, de las hojas de notas y los certificados, no de la ficha:
        # la ficha trae la fecha de nacimiento y la del bachillerato. Y dentro
        # de la ventana del PDF, para que un año suelto mal leído no lo extienda.
        def es_la_ficha(texto: str) -> bool:
            if de_medicina:
                return clase_de_pagina(texto) == FICHA_DE_MEDICINA
            return es_ficha(plantilla_de_apertura(texto))

        def sin_la_ficha(paginas: list[int]) -> list[str]:
            return [textos[n - 1] for n in paginas if not es_la_ficha(textos[n - 1])]

        ventana = ventana_de_anios(
            sin_la_ficha(list(range(1, total + 1))),
            nombre=nombre,
            **({"margen": MARGEN_DE_MEDICINA} if de_medicina else {}),
        )

        # Y la IA, si se pidió: la ficha y la hoja de notas de cada estudiante
        # al que le falte algo. Medido sobre 24 fichas de UPD3859718 contra el
        # papel (2026-10-30): con sólo la ficha, 10 nombres de 24 salían bien y
        # el año final se quedaba en el anotado («1983-86») y no en el último
        # semestre. La hoja de notas trae los años y el nombre otra vez, y la IA
        # concilia el nombre entre todo lo leído, sólo con palabras del papel.
        # En Medicina las notas van a máquina: la IA lee las de quien no deja
        # leer sus años en la capa de texto, y nada más.
        textos_de_la_ficha: dict[int, str] = {}
        notas_de_la_ia: dict[int, str] = {}
        if de_pago is not None and not de_hojas:
            _leer_las_fichas_con_la_ia(
                payload, taller, source, de_pago, unidades, textos_de_la_ficha, notas_de_la_ia, nombre,
                de_medicina=de_medicina,
                leer_las_notas=lambda unidad: not de_medicina
                or anios(sin_la_ficha(unidad.paginas), ventana=ventana) == (None, None),
            )
            # Y la segunda lectura de la cédula, de otra imagen: su renglón
            # ampliado. Lo que no coincide va a revisión. Sus franjas son las
            # de la ficha de Enfermería.
            if not de_medicina:
                _segunda_lectura(payload, taller, source, unidades, conocidas)

        # La cédula de Medicina, buscada en todo el expediente, con IA o sin
        # ella: «siempre que un documento tenga cédula y nombre de una persona,
        # y la encuentres, va en el nombre» (el operador, 2026-11-03).
        if de_medicina:
            _buscar_las_cedulas(payload, taller, unidades, textos, textos_de_la_ficha, source)

        # El nombre de Medicina, votado entre sus lecturas y corregido a lo más
        # cercano de lo que dice el renglón (el operador, 2026-11-03).
        notas_del_nombre: dict[int, str] = {}
        if de_medicina or de_hojas:
            if de_medicina:
                for unidad in unidades:
                    # La ficha que leyó entera la IA dice el nombre otra vez.
                    texto = textos_de_la_ficha.get(unidad.pagina_de_la_ficha) if unidad.pagina_de_la_ficha else None
                    if texto and (leido := nombre_del_renglon(texto)):
                        lecturas.setdefault(unidad.paginas[0], []).append(leido)
            _corregir_los_nombres(
                payload, taller, source, de_pago, unidades, lecturas, renglones, hojas, conocidas, nombre,
                notas_del_nombre,
            )

        # El agente se asegura (2026-11-06): ningún estudiante con el número de
        # otro, y lo que falta -- cédula, TI o libreta, código --, buscado otra
        # vez en todo lo leído y, con la IA, en su ficha, antes de darlo por
        # faltante. Lo que de verdad no está queda dicho como tal.
        candado_de_la_fuente = threading.Lock()

        def leer_la_ficha(numero: int) -> str:
            # Una página con el OCR de pago, para verificar sobre lo que dice el papel.
            if de_pago is None:
                return ""
            try:
                with candado_de_la_fuente:
                    imagen = source.render(numero, dpi=200, formato="jpeg")
                return de_pago.read(imagen).text or ""
            except Exception:  # noqa: BLE001 - sin la lectura, la casilla queda sin verificar
                logger.warning("la IA no pudo leer la ficha de la página %s de %s", numero, nombre, exc_info=True)
                return ""

        asegurador = _Asegurador(taller, textos, textos_de_la_ficha, notas_de_la_ia, leer_pagina=leer_la_ficha)
        if not de_hojas:
            _sin_numeros_ajenos(unidades, asegurador)
            asegurador.numeros(payload, unidades)
            _sin_numeros_ajenos(unidades, asegurador)
            # Los apellidos al derecho, por el orden alfabético de la caja: la
            # IA ponía a veces el segundo delante (2026-11-06).
            for indice, corregido in apellidos_al_derecho([u.ficha.nombre if u.ficha else None for u in unidades]).items():
                unidad = unidades[indice]
                unidad.dudas.append(
                    f"nombre «{unidad.ficha.nombre}» ordenado como «{corregido}» por el orden alfabético de la caja: "
                    "revise los apellidos en el papel"
                )
                unidad.ficha = replace(unidad.ficha, nombre=corregido)
        # Cómo empiezan los códigos de esta caja -- «54» en Enfermería --: un
        # código que difiere en una cifra y cuyo año cuadra se corrige.
        patron = patron_de_los_codigos([u.ficha.codigo for u in unidades if u.ficha is not None])

        if not any(unidad.es_de_un_estudiante for unidad in unidades):
            # Ni una ficha reconocible: un formato que esta habilidad todavía no
            # conoce. El PDF se entrega entero, con su nombre, y lleva su fila
            # con el asunto y los años de su nombre, como el inventario del
            # cliente: ningún PDF se queda sin fila (2026-10-30).
            return _sin_estudiantes(payload, taller, nombre, carpeta, total)

        pidio_dividir = payload.get("task") in (str(TaskKind.SPLIT), str(TaskKind.BOTH))
        # El agente revisor (2026-11-05), con el perfil de las historias: cada
        # costura entre estudiantes contra lo que dice el papel -- dos cédulas
        # distintas son dos personas --, se divida o sólo se inventaríe, porque
        # cada estudiante es una fila. Señala y no mueve: el nombre y la fila
        # salen de leer su ficha. Lo que sale del margen lo decide la IA si se
        # eligió.
        del_revisor = perfil_de("historias")
        revision = aviso_del_revisor = None
        if unidades:
            # Con un solo estudiante no hay costuras: sale validado, no «sin revisar».
            por_pagina = dict(enumerate(textos, start=1))
            revision, aviso_del_revisor = revisar_sin_romper(
                _reparto(unidades), por_pagina, del_revisor.patrones(por_pagina), juez=taller.juez_de_costuras()
            )
        #: Qué hojas del original lleva cada PDF escrito, en su orden: con ellas
        #: se comprueba lo que quedó en el disco.
        esperado: dict[str, list[int]] = {}
        comprobacion = None
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
                    en_orden = _con_la_ficha_primero(unidad, textos, de_medicina)
                    # La ficha principal primero, con su reverso: «la primera
                    # página del PDF dividido debe ser la página principal del
                    # estudiante» (el operador, 2026-11-03). Por tramos y con
                    # ``garbage=1``: guardar con ``garbage=3`` era lo lento.
                    from .nominas import escribir_paginas

                    escribir_paginas(original, taller.source, list(en_orden), carpeta_de_salida / archivo)
                    esperado[archivo] = list(en_orden)
                    salidas.append((carpeta_de_salida / archivo).relative_to(taller.destination).as_posix())
                hoja = hojas.get(unidad.paginas[0])
                if de_hojas:
                    # La fecha de la hoja, o el año de su período; si no, los
                    # años del legajo -- su nombre o su portada --, como el
                    # inventario del cliente: ninguna fila sin fecha.
                    inicial = final = hoja.anio if hoja else None
                    if inicial is None and unidad.ficha is not None:
                        inicial, final = anios_del_legajo(nombre, portada)
                else:
                    # Con lo que la IA leyó de su hoja de notas, si la leyó: ahí
                    # están los años de cada semestre, escritos a mano.
                    notas_leidas = notas_de_la_ia.get(unidad.pagina_de_la_ficha)
                    de_las_hojas = sin_la_ficha(unidad.paginas)
                    inicial, final = _anios_del_expediente(
                        unidad, textos, textos_de_la_ficha,
                        [notas_leidas, *de_las_hojas] if notas_leidas else de_las_hojas,
                        ventana, source, local,
                    )
                if not de_hojas and unidad.ficha is not None and not unidad.ficha.codigo and unidad.pagina_de_la_ficha:
                    # El código sin rótulo, que empieza por el año de ingreso.
                    texto_de_la_ficha = textos_de_la_ficha.get(unidad.pagina_de_la_ficha) or textos[unidad.pagina_de_la_ficha - 1]
                    if codigo := codigo_sin_rotulo(texto_de_la_ficha, inicial):
                        unidad.ficha = replace(unidad.ficha, codigo=codigo)
                del_codigo = None
                if (
                    not de_hojas
                    and inicial is None
                    and unidad.ficha is not None
                    and (ingreso := anio_del_codigo(re.sub(r"\D", "", unidad.ficha.codigo or "")))
                    and (final is None or 0 <= final - ingreso <= MAXIMO_DE_ANIOS)
                ):
                    # Sin fecha inicial en las notas, el año de ingreso que dice
                    # el código -- «549310044», ingreso en 1993 --: ninguna fila
                    # sin fecha (el operador, 2026-11-06: «necesitamos muy bien
                    # las fechas extremas»).
                    inicial = del_codigo = ingreso
                # Los años que aún falten, de lo que la IA lee en su ficha y sus
                # notas, si se eligió: ninguna fila sin fecha.
                de_la_ia = None
                if not de_hojas:
                    inicial, final, de_la_ia = asegurador.anios(unidad, inicial, final)
                if (
                    not de_hojas
                    and unidad.ficha is not None
                    and (corregido := codigo_por_el_patron(unidad.ficha.codigo, patron, inicial))
                ):
                    # «599010022» entre veinte «54…»: una cifra mal leída
                    # (SOTO CHAQUIR, 2026-11-06). Corregido, y dicho.
                    unidad.dudas.append(
                        f"código {unidad.ficha.codigo} corregido a {corregido} por el patrón de la caja "
                        f"({patron}…): revíselo en el papel"
                    )
                    unidad.ficha = replace(unidad.ficha, codigo=corregido)
                ficha = unidad.ficha
                faltan = []
                if ficha is not None and de_hojas:
                    # Una matrícula, un certificado o un recibo no traen cédula.
                    if not ficha.nombre:
                        faltan.append("el nombre")
                    if not (hoja and hoja.anio):
                        faltan.append("la fecha de la hoja" + (" (van los años del legajo)" if inicial else ""))
                elif ficha is not None:
                    if not ficha.nombre:
                        faltan.append("el nombre")
                    if not ficha.cedula:
                        faltan.append(
                            "la cédula"
                            + (f" (código {ficha.codigo})" if ficha.codigo else "")
                            + (f" (la ficha trae la tarjeta de identidad {ficha.tarjeta})" if ficha.tarjeta else "")
                            + (
                                f" (la ficha trae la libreta militar {ficha.libreta})"
                                if ficha.libreta and not ficha.tarjeta
                                else ""
                            )
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
                        "libreta": ficha.libreta if ficha else None,
                        # Cómo quedó cada casilla que el agente buscó otra vez:
                        # en blanco, no aparece, ilegible o sin verificar.
                        "verificado": asegurador.estados.get(unidad.paginas[0], {}),
                        "anio_inicial": inicial,
                        "anio_final": final,
                        # Las hojas sueltas dicen qué hoja son, y su fecha entera si la traen.
                        "clase": unidad.plantilla if de_hojas else None,
                        "fecha_exacta": (
                            f"{hoja.fecha[0]:02d}/{hoja.fecha[1]:02d}/{hoja.fecha[2]}" if hoja and hoja.fecha else None
                        ),
                        "folios": len(unidad.paginas),
                        "pagina_inicial": unidad.paginas[0],
                        "pagina_final": unidad.paginas[-1],
                        "archivo": nombre,
                        "carpeta": carpeta,
                        "archivo_generado": archivo if pidio_dividir else None,
                        "observaciones": "; ".join(
                            [
                                *([f"no se leyó {', '.join(faltan)} en {donde} del PDF: revíselo en el papel"] if faltan else []),
                                *(
                                    [f"fecha inicial {del_codigo}: el año de ingreso que dice el código {ficha.codigo}"]
                                    if del_codigo and ficha is not None
                                    else []
                                ),
                                *([nota] if (nota := notas_del_nombre.get(unidad.paginas[0])) else []),
                                *asegurador.notas.get(unidad.paginas[0], []),
                                *([de_la_ia] if de_la_ia else []),
                                *(f"{duda}: revísela" for duda in unidad.dudas),
                            ]
                        ),
                    }
                )
                _anunciar(payload, Stage.ASSEMBLING, detail=f"escribiendo {len(unidades)} PDF", done=orden, total=len(unidades))
        if pidio_dividir:
            # Cada PDF escrito, vuelto a abrir y casado hoja por hoja con el
            # original en el orden en que se escribió; y que ninguna hoja se
            # quede fuera de todos ni vaya en dos.
            comprobacion = comprobar_archivos(
                taller.source, esperado, carpeta_de_salida, huellas_de, paginas_del_original=total
            )
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
    # El agente también en los datos (2026-11-06): de cada estudiante, el
    # nombre, la cédula -- o la tarjeta, o la libreta militar --, el código y
    # las fechas extremas, antes de que vayan al FUID. Lo que no cuadra, a la
    # cola de revisión con su página.
    integridad = revisar_los_datos(filas, del_revisor.datos, aceptable=del_revisor.margen) if del_revisor.datos else None
    if revision is not None or aviso_del_revisor or comprobacion or integridad is not None:
        anotar_en_el_informe(
            report, revision, aviso_del_revisor, comprobacion, perfil=del_revisor.as_dict(), integridad=integridad
        )

    _escribir_el_fuid(payload, taller, nombre, filas, report)
    return report


def _reparto(unidades):
    """Las unidades -- un estudiante, una hoja suelta -- como grupos de páginas para el revisor."""
    from ...domain.grouping import GroupingResult, PageGroup
    from ...domain.resolution_code import ResolutionCode

    return GroupingResult(
        groups=[
            PageGroup(
                code=ResolutionCode(value=f"{orden:03d}", raw=f"{orden:03d}"),
                page_numbers=sorted(unidad.paginas),
            )
            for orden, unidad in enumerate(unidades, start=1)
        ]
    )


#: Cuántos renglones del nombre de Medicina van en cada mosaico, y a qué
#: resolución: van a máquina, y ocho a 300 ppp los leyó todos en internados
#: (2026-11-03).
RENGLONES_POR_MOSAICO = 8
DPI_DEL_RENGLON = 300


def _ubicar_en_la_capa(desde: float):
    """A qué altura está el rótulo, según la capa de texto: el renglón más alto desde ``desde``.

    La mitad de arriba de la ficha de Medicina es el «Registro de
    actividades», impreso al revés; su capa no dice nada que sirva. Sin
    Tesseract: la capa ya trae el rótulo impreso, y ubicarlo con Tesseract
    costaba una lectura de página entera por cada una.
    """
    from ...domain.historia_academica import plano

    def localizar(source, pagina, leyendas):
        alturas = [
            caja.top
            for caja in source.boxes_of(pagina)
            if caja.top >= desde and any(leyenda in plano(caja.text or "") for leyenda in leyendas)
        ]
        return min(alturas) if alturas else None

    return localizar


def _expedientes_de_medicina(payload, taller, source, local, textos, nombre):
    """Los expedientes de un PDF de Medicina, por el nombre de cada ficha y de cada hoja de notas.

    El nombre se lee del renglón: «Nombre del alumno» en la ficha y «Nombre»
    al pie de las notas. Con «OCR + IA», la IA, ``RENGLONES_POR_MOSAICO`` por
    página facturada; con «Solo OCR», el OCR de casa, renglón por renglón.
    """
    from ...adapters.mosaico_de_nombres import MosaicoDeCampo
    from ...domain.historia_medicina import (
        DESDE_LA_ALTURA,
        FICHA_DE_MEDICINA,
        FRANJA_DEL_ALUMNO,
        FRANJA_DEL_PIE,
        NOTAS_DE_MEDICINA,
        clase_de_pagina,
        expedientes_de_medicina,
        nombre_del_renglon,
    )

    clases = [clase_de_pagina(texto) for texto in textos]
    nombres: dict[int, str] = {}
    for franja, clase in ((FRANJA_DEL_ALUMNO, FICHA_DE_MEDICINA), (FRANJA_DEL_PIE, NOTAS_DE_MEDICINA)):
        taller.control.check()
        paginas = [numero for numero, de in enumerate(clases, start=1) if de == clase]
        if not paginas:
            continue
        localizar = _ubicar_en_la_capa(DESDE_LA_ALTURA[franja.campo])
        _anunciar(payload, Stage.IDENTIFYING, detail=f"leyendo {franja.campo}", done=0, total=len(paginas))
        # Sólo por el orden de los rótulos: el nombre decide el corte, y la
        # etiqueta de cada franja la devuelve el proveedor a veces cambiada.
        mosaico = taller.mosaico_de_campo(
            franja, localizar=localizar, tamano=RENGLONES_POR_MOSAICO, dpi=DPI_DEL_RENGLON, por_etiqueta=False
        )
        if mosaico is None:
            # Solo OCR: el mismo renglón, uno por imagen, con el OCR de casa.
            mosaico = MosaicoDeCampo(
                franja, localizar=localizar, leer=lambda imagen: local.read(imagen).text,
                tamano=1, dpi=DPI_DEL_RENGLON, lectores=2,
            )
        leidos = mosaico.leer_franjas(source, paginas)
        for numero in paginas:
            if leido := nombre_del_renglon(leidos.get(numero, "")):
                nombres[numero] = leido
        # Lo que no se leyó se vuelve a mirar antes de cortar, con otro recorte
        # y más zoom: un pie sin leer dejaba pegada la cartulina de VELASQUEZ
        # CANO RAFAEL a la de RAMON VILLALOBOS LOPEZ (UPD 3859597, 2026-11-03).
        # Las fichas en blanco no traen nombre y se vuelven a mirar igual: es
        # una franja por cada una, y no se sabe cuáles lo están.
        if sin_leer := [numero for numero in paginas if numero not in nombres]:
            releidos = mosaico.otra_mirada().leer_franjas(source, sin_leer)
            for numero in sin_leer:
                if leido := nombre_del_renglon(releidos.get(numero, "")):
                    nombres[numero] = leido
        logger.info("%s: %s leído en %d de %d páginas", nombre, franja.campo, sum(1 for n in paginas if n in nombres), len(paginas))
    unidades = expedientes_de_medicina(clases, nombres)
    # Las lecturas del nombre de cada estudiante: primero las del pie, con los
    # apellidos primero, y luego las de la ficha. Y los renglones de donde
    # salieron, por si hay que volver a mirarlos.
    lecturas: dict[int, list[str]] = {}
    renglones: dict[int, list[tuple[object, int]]] = {}
    for unidad in unidades:
        if unidad.ficha is None:
            continue
        de_cada = {
            clase: [numero for numero in unidad.paginas if clases[numero - 1] == clase]
            for clase in (NOTAS_DE_MEDICINA, FICHA_DE_MEDICINA)
        }
        lecturas[unidad.paginas[0]] = [
            nombres[numero] for clase in (NOTAS_DE_MEDICINA, FICHA_DE_MEDICINA) for numero in de_cada[clase] if numero in nombres
        ]
        renglones[unidad.paginas[0]] = [
            (franja, de_cada[clase][0])
            for franja, clase in ((FRANJA_DEL_PIE, NOTAS_DE_MEDICINA), (FRANJA_DEL_ALUMNO, FICHA_DE_MEDICINA))
            if de_cada[clase]
        ]
    return unidades, lecturas, renglones


def _con_la_ficha_primero(unidad, textos, de_medicina: bool) -> list[int]:
    """Las páginas del PDF del estudiante, con su ficha principal primero.

    El operador (2026-11-03): «la primera página del PDF dividido debe ser la
    página principal del estudiante». En Medicina el escaneo pone a veces las
    notas antes que la ficha (Ferrer Triana, internados, págs. 3 y 4) o una
    ficha en blanco delante (Castillo, UPD 3859597, pág. 1): la ficha con su
    nombre va primero, con su reverso -- la hoja de notas que la sigue --, y
    luego lo demás en el orden del escaneo. Sin ficha, como venía.
    """
    from ...domain.historia_medicina import NOTAS_DE_MEDICINA, clase_de_pagina

    ficha = unidad.pagina_de_la_ficha
    if not ficha or ficha not in unidad.paginas or ficha == unidad.paginas[0]:
        return list(unidad.paginas)
    primero = [ficha]
    reverso = ficha + 1
    if de_medicina and reverso in unidad.paginas and clase_de_pagina(textos[reverso - 1]) == NOTAS_DE_MEDICINA:
        primero.append(reverso)
    return primero + [numero for numero in unidad.paginas if numero not in primero]


def _buscar_las_cedulas(payload, taller, unidades, textos, textos_de_la_ficha, source) -> None:
    """La cédula de cada estudiante de Medicina que todavía no la tiene, buscada en todo su expediente.

    Primero lo que ya se leyó, gratis: la capa de texto de cada página suya y
    la ficha que leyó la IA (``cedula_del_expediente``). Y si se pidió la IA,
    el último intento: el renglón de la cédula de sus fichas, ampliado
    (``FRANJA_DE_LA_CEDULA``). El OCR de casa no: cambia cifras. Antes la
    cédula de Medicina sólo salía de la ficha leída por la IA (el operador,
    2026-11-03: «si un diploma, una historia académica debería llevar cédula…
    obligatoriamente; si no la lleva, déjalo así»).
    """
    from dataclasses import replace

    from ...domain.historia_medicina import (
        DESDE_LA_ALTURA,
        FICHA_DE_MEDICINA,
        FRANJA_DE_LA_CEDULA,
        cedula_de_la_ficha,
        cedula_del_expediente,
        clase_de_pagina,
    )

    sin_cedula = [unidad for unidad in unidades if unidad.ficha is not None and not unidad.ficha.cedula]
    for hecho, unidad in enumerate(sin_cedula, start=1):
        _anunciar(payload, Stage.IDENTIFYING, detail="buscando la cédula de cada estudiante", done=hecho, total=len(sin_cedula))
        leidos = [textos[numero - 1] for numero in unidad.paginas]
        leidos += [textos_de_la_ficha[numero] for numero in unidad.paginas if numero in textos_de_la_ficha]
        # Sin Tesseract: cambia cifras de la cédula -- «377851» por 877851,
        # «312325» por 4312325 (UPD 3859597, págs. 5 y 58) --, y una cédula
        # equivocada en el nombre del archivo es peor que ninguna.
        if cedula := cedula_del_expediente(leidos):
            unidad.ficha = replace(unidad.ficha, cedula=cedula)

    # El último intento, con la IA: el renglón de la cédula de cada ficha de
    # quien sigue sin ella, ampliado, tres por imagen.
    faltan = [unidad for unidad in sin_cedula if not unidad.ficha.cedula]
    fichas = {
        numero: unidad
        for unidad in faltan
        for numero in unidad.paginas
        if clase_de_pagina(textos[numero - 1]) == FICHA_DE_MEDICINA
    }
    mosaico = (
        taller.mosaico_de_campo(
            FRANJA_DE_LA_CEDULA,
            localizar=_ubicar_en_la_capa(DESDE_LA_ALTURA[FRANJA_DE_LA_CEDULA.campo]),
            por_etiqueta=False,
        )
        if fichas
        else None
    )
    if mosaico is None:
        return
    _anunciar(payload, Stage.IDENTIFYING, detail="leyendo con la IA el renglón de la cédula que falta")
    for numero, leido in mosaico.leer_franjas(source, sorted(fichas)).items():
        unidad = fichas[numero]
        if not unidad.ficha.cedula and (cedula := cedula_de_la_ficha(leido)):
            unidad.ficha = replace(unidad.ficha, cedula=cedula)


#: Cuántos renglones van por imagen al volver a mirarlos: menos que la primera
#: vez, para que la letra salga más grande.
RENGLONES_AL_RELEER = 3
#: La franja de la hoja suelta que se vuelve a mirar, en fracción de la hoja: la
#: mitad de arriba, donde va el nombre en la matrícula, el certificado y el recibo.
CABECERA_DE_LA_HOJA = (0.0, 0.05, 1.0, 0.6)


def _corregir_los_nombres(
    payload, taller, source, de_pago, unidades, lecturas, renglones, hojas, conocidas, nombre, notas_del_nombre
) -> None:
    """El nombre de cada estudiante, lo más parecido a lo que dice el renglón de su página.

    Lo pidió el operador el 2026-11-03: «que si el nombre está mal escrito, la
    IA tenga la habilidad de colocarle una aproximación correcta y muy
    cercana… lo más parecido a lo que se pueda leer en el renglón».

    1. Las lecturas del estudiante votan cada palabra, y la lista de nombres
       conocidos corrige la que nada confirma y está a una letra
       (``nombre_por_consenso``). Gratis.
    2. Si aún queda una palabra sin confirmar y se pidió la IA, se vuelve a
       mirar el renglón del PDF: con otro recorte y más zoom (``otra_mirada``)
       en Medicina, la cabecera de la hoja a más resolución en las hojas
       sueltas. Esa lectura vota también.
    3. Lo que siga sin confirmar lo corrige la IA con todas las lecturas, y
       sólo se acepta una aproximación de lo leído (``aproximacion_de_la_ia``).

    Si el nombre cambia, la fila dice qué se leyó.
    """
    from dataclasses import replace

    from ...application.ports import Band
    from ...domain.historia_medicina import (
        DESDE_LA_ALTURA,
        corregir_con_la_ia,
        leer_hoja,
        nombre_del_renglon,
        nombre_por_consenso,
    )

    por_unidad = {unidad.paginas[0]: unidad for unidad in unidades if unidad.ficha is not None}
    votados = {clave: nombre_por_consenso(lecturas.get(clave, []), conocidas) for clave in por_unidad}
    # Los que tienen palabras sin confirmar, y los que no tienen nombre: ningún
    # documento sin nombre.
    dudosos = [clave for clave, votado in votados.items() if votado.sin_confirmar or not votado.nombre]

    if dudosos and de_pago is not None:
        _anunciar(payload, Stage.IDENTIFYING, detail="volviendo a mirar el renglón de los nombres dudosos")
        if renglones:
            # Medicina: el pie y la ficha de cada uno, con otra mirada.
            por_franja: dict[object, list[tuple[int, int]]] = {}
            for clave in dudosos:
                for franja, pagina in renglones.get(clave, []):
                    por_franja.setdefault(franja, []).append((clave, pagina))
            for franja, pares in por_franja.items():
                mosaico = taller.mosaico_de_campo(
                    franja, localizar=_ubicar_en_la_capa(DESDE_LA_ALTURA[franja.campo]),
                    tamano=RENGLONES_AL_RELEER, dpi=DPI_DEL_RENGLON, por_etiqueta=False,
                )
                if mosaico is None:
                    continue
                leidos = mosaico.otra_mirada().leer_franjas(source, [pagina for _, pagina in pares])
                for clave, pagina in pares:
                    if leido := nombre_del_renglon(leidos.get(pagina, "")):
                        lecturas.setdefault(clave, []).append(leido)
        else:
            # Hojas sueltas: su cabecera, a más resolución.
            cabeceras = _leer_paginas_con_la_ia(
                payload, taller, source, de_pago, dudosos, nombre, "volviendo a mirar el nombre de cada hoja",
                banda=Band(*CABECERA_DE_LA_HOJA), dpi=300,
            )
            for clave, texto in cabeceras.items():
                if leido := leer_hoja(texto, por_unidad[clave].plantilla).nombre:
                    lecturas.setdefault(clave, []).append(leido)
        for clave in dudosos:
            votados[clave] = nombre_por_consenso(lecturas.get(clave, []), conocidas)

    corrector = taller.corrector_de_nombres() if de_pago is not None else None
    for clave, votado in votados.items():
        final = votado.nombre
        if final and votado.sin_confirmar and corrector is not None:
            todas = [votado.nombre, *[lectura for lectura in lecturas.get(clave, []) if lectura != votado.nombre]]
            try:
                respuesta = corrector.resumir("\n".join(f"- {lectura}" for lectura in todas if lectura))
            except Exception:  # noqa: BLE001 - sin la IA queda lo votado
                logger.warning("la IA no corrigió un nombre de %s", nombre, exc_info=True)
            else:
                final = corregir_con_la_ia(votado, respuesta, todas) or final
        if not final:
            continue
        unidad = por_unidad[clave]
        unidad.ficha = replace(unidad.ficha, nombre=final)
        if votado.leido and final != votado.leido:
            notas_del_nombre[clave] = f"nombre corregido; se leyó «{votado.leido}»"
            logger.info("%s: «%s» → «%s» (lecturas: %s)", nombre, votado.leido, final, lecturas.get(clave))
    logger.info(
        "%s: %d nombres, %d con palabras dudosas, %d corregidos", nombre, len(votados), len(dudosos),
        len(notas_del_nombre),
    )


def _leer_paginas_con_la_ia(
    payload, taller, source, de_pago, paginas, nombre, detalle, *, banda=None, dpi=200
) -> dict[int, str]:
    """Cada una de esas páginas, entera o su ``banda``, leída por la IA: una página facturada por página.

    Se rasterizan de a una -- el documento no se lee desde dos hilos -- y se
    piden de a ``LECTORES_DE_IA``. La que falla queda sin leer.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    candado = threading.Lock()

    def leer(numero: int) -> tuple[int, str]:
        try:
            with candado:
                imagen = source.render(numero, banda, dpi=dpi, formato="jpeg")
            return numero, de_pago.read(imagen).text or ""
        except Exception:  # noqa: BLE001 - sin la IA queda la capa de texto
            logger.warning("la IA no pudo leer la página %s de %s", numero, nombre, exc_info=True)
            return numero, ""

    leidas: dict[int, str] = {}
    pool = ThreadPoolExecutor(max_workers=LECTORES_DE_IA)
    try:
        futuros = [pool.submit(leer, numero) for numero in paginas]
        for hecho, futuro in enumerate(as_completed(futuros), start=1):
            taller.control.check()
            _anunciar(payload, Stage.IDENTIFYING, detail=detalle, done=hecho, total=len(futuros))
            numero, texto = futuro.result()
            if texto:
                leidas[numero] = texto
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return leidas


def _hojas_sueltas(payload, taller, source, de_pago, textos, nombre):
    """Un expediente por hoja suelta, y lo que dice cada una: nombre, código y fecha.

    Con «OCR + IA» la IA lee cada hoja entera: los nombres van a máquina en
    tablas que la capa de texto revuelve, o a mano en los recibos. Una página
    facturada por hoja. Con «Solo OCR», lo que deje leer la capa.
    """
    from ...domain.historia_academica import Ficha
    from ...domain.historia_medicina import (
        hojas_sueltas,
        leer_hoja,
        tipo_de_hoja,
        ventana_del_legajo,
    )

    leidas = {}
    if de_pago is not None:
        leidas = _leer_paginas_con_la_ia(
            payload, taller, source, de_pago, list(range(1, len(textos) + 1)), nombre, "leyendo con la IA cada hoja"
        )
    tipos = [tipo_de_hoja(leidas.get(numero, "")) or tipo_de_hoja(texto) for numero, texto in enumerate(textos, start=1)]
    unidades = hojas_sueltas(tipos)
    # La portada, si la hay: lo de antes de la primera hoja.
    portada = "\n".join(
        leidas.get(numero) or textos[numero - 1] for numero in (unidades[0].paginas if unidades[0].ficha is None else [])
    )
    ventana = ventana_del_legajo(nombre, portada)
    hojas = {}
    for unidad in unidades:
        if unidad.ficha is None:
            continue
        primera = unidad.paginas[0]
        hoja = leer_hoja(leidas.get(primera) or textos[primera - 1], unidad.plantilla, ventana=ventana)
        unidad.ficha = Ficha(nombre=hoja.nombre, codigo=hoja.codigo)
        hojas[primera] = hoja
    logger.info(
        "%s: %d hojas sueltas, %d con nombre y %d con fecha", nombre, len(hojas),
        sum(1 for hoja in hojas.values() if hoja.nombre), sum(1 for hoja in hojas.values() if hoja.anio),
    )
    return unidades, hojas, portada


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


def _leer_las_fichas_con_la_ia(
    payload, taller, source, de_pago, unidades, textos_de_la_ficha, notas_de_la_ia, nombre, *,
    de_medicina=False, leer_las_notas=lambda unidad: True,
):
    """La ficha y la primera hoja de notas de cada estudiante, leídas por la IA, y su nombre conciliado.

    En las de 1960 a 1990, escritas a mano, la capa de texto no deja leer ni el
    nombre, ni la cédula, ni los años: dos páginas facturadas por estudiante.
    Lo que lee la IA manda sobre lo de casa. Las páginas se renderizan de a una
    -- el documento no se lee desde dos hilos -- y se piden de a ``LECTORES_DE_IA``.

    En Medicina (``de_medicina``) la ficha, por la cédula, y las notas sólo de
    quien ``leer_las_notas``: van a máquina y su capa de texto suele traer los
    años. Y el nombre es el de su renglón, que la IA ya leyó para cortar, con
    los apellidos primero.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from ...domain.historia_academica import Ficha, leer_ficha
    from ...domain.historia_medicina import cedula_de_la_ficha

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
        notas = leer_pagina(siguientes[0]) if siguientes and leer_las_notas(unidad) else ""
        conciliado = None
        if nombrador is not None and (ficha or notas) and not (de_medicina and unidad.ficha.nombre):
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
            # La cédula escrita al pie de la hoja de notas, si la ficha no la
            # trae: «CC 45444285 C/gena» (UPD3859718, pág. 144).
            de_las_notas = leer_ficha(notas)
            unidad.ficha = Ficha(
                nombre=(de_casa.nombre or conciliado) if de_medicina else (conciliado or de_la_ia.nombre or de_casa.nombre),
                cedula=de_la_ia.cedula
                or (cedula_de_la_ficha(ficha) if de_medicina else None)
                or de_casa.cedula
                or de_las_notas.cedula,
                codigo=de_casa.codigo or de_la_ia.codigo,
                anio_de_grado=de_la_ia.anio_de_grado or de_casa.anio_de_grado,
                tarjeta=de_la_ia.tarjeta or de_casa.tarjeta or de_las_notas.tarjeta,
                libreta=de_la_ia.libreta or de_casa.libreta,
            )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


#: Cuánto texto de cada estudiante se le da a la IA para verificar: la ficha
#: entera y el principio de su hoja de notas.
TEXTO_PARA_VERIFICAR = 7000


class _Asegurador:
    """El agente se asegura antes de dar un dato por faltante.

    El operador, 2026-11-06, con las historias de Enfermería: «todavía hay falta
    de cédulas y de códigos… haz que los agentes se aseguren cuando en realidad
    no encuentren algo». A cada estudiante al que le falte la cédula (o la TI,
    o la libreta), el código o un año:

    1. **Otra vez, gratis**: en todo lo leído de sus hojas -- la capa de texto,
       la ficha y las notas que leyó la IA --, con todos los rótulos que se
       conocen («Código. 54-9010033», «Carné Estudiantil N°», «Documento de
       Identificación … N°»).
    2. **La IA, si se eligió**: sobre el texto que su OCR ya leyó (se paga por
       tokens, no por página), sólo por las casillas que faltan. Un número sólo
       se toma si está escrito en ese texto; si la casilla está en blanco, se
       dice que está en blanco.

    Lo que quede, queda con su estado -- «en blanco», «no aparece», «ilegible»
    o «sin verificar» -- en la fila (``verificado``), para que el agente de los
    datos y la auditoría digan la verdad de cada casilla.
    """

    def __init__(self, taller, textos, textos_de_la_ficha, notas_de_la_ia, leer_pagina=None):
        self._verificador = taller.verificador_de_fichas()
        #: Quien lee una página con el OCR de pago: sólo se verifica sobre una
        #: lectura de verdad, no sobre la capa de texto del escáner, que de la
        #: letra a mano trae basura y hacía decir «no aparece» a lo que estaba
        #: (págs. 13, 26 y 28 de UPD3859734, 2026-11-06).
        self._leer_pagina = leer_pagina
        self._textos = textos
        self._de_la_ficha = textos_de_la_ficha
        self._notas = notas_de_la_ia
        self._respuestas: dict[int, object] = {}
        #: Por estudiante (su primera página): casilla -> estado.
        self.estados: dict[int, dict[str, str]] = {}
        #: Por estudiante: lo que se encontró al asegurarse, para su fila.
        self.notas: dict[int, list[str]] = {}

    def propios(self, unidad) -> list[str]:
        """Todo lo leído de las hojas del estudiante: su capa de texto y lo que leyó la IA."""
        pagina = unidad.pagina_de_la_ficha
        return [
            *(texto for texto in (self._de_la_ficha.get(pagina), self._notas.get(pagina)) if texto),
            *(self._textos[numero - 1] for numero in unidad.paginas if 0 < numero <= len(self._textos)),
        ]

    def lectura_real(self, unidad) -> str:
        """La ficha leída por la IA; si aún no se leyó, se lee ahora (una página). Vacía si no se pudo."""
        pagina = unidad.pagina_de_la_ficha
        if (
            pagina
            and pagina not in self._de_la_ficha
            and self._leer_pagina is not None
            and (texto := self._leer_pagina(pagina))
        ):
            self._de_la_ficha[pagina] = texto
        return self._de_la_ficha.get(pagina) or ""

    def _para_la_ia(self, unidad) -> str:
        ficha = self.lectura_real(unidad)
        if not ficha.strip():
            return ""
        notas = self._notas.get(unidad.pagina_de_la_ficha) or ""
        return (f"FICHA:\n{ficha}\n\nHOJA DE NOTAS:\n{notas}" if notas else ficha)[:TEXTO_PARA_VERIFICAR]

    def _preguntar(self, unidad):
        """Lo que dice la IA de las casillas de su ficha, una vez por estudiante."""
        from ...domain.historia_academica import Verificacion, leer_la_verificacion

        clave = unidad.paginas[0]
        if clave not in self._respuestas:
            texto = self._para_la_ia(unidad)
            if not texto.strip():
                # Sin una lectura de verdad de su ficha no se verifica nada.
                self._respuestas[clave] = None
                return None
            try:
                respuesta = self._verificador.resumir(texto)
            except Exception:  # noqa: BLE001 - sin respuesta, la casilla queda sin verificar
                logger.warning("la IA no verificó la ficha de la página %s", unidad.pagina_de_la_ficha, exc_info=True)
                self._respuestas[clave] = None
            else:
                verificacion = leer_la_verificacion(respuesta, texto) if respuesta else Verificacion()
                self._respuestas[clave] = verificacion
                # Lo que dijo de cada casilla, sin sus números.
                logger.info(
                    "verificación de la ficha de la pág. %s: %s", unidad.pagina_de_la_ficha,
                    ", ".join(
                        f"{casilla} {estado}" + (f" ({verificacion.motivos[casilla]})" if casilla in verificacion.motivos else "")
                        for casilla, estado in verificacion.estados.items()
                    ),
                )
        return self._respuestas[clave]

    def _releer_gratis(self, unidad) -> None:
        from dataclasses import replace

        from ...domain.historia_academica import leer_ficha

        ficha = unidad.ficha
        for texto in self.propios(unidad):
            if ficha.identificacion and ficha.codigo:
                break
            otra = leer_ficha(texto)
            if not ficha.identificacion and otra.identificacion:
                ficha = replace(ficha, cedula=otra.cedula, tarjeta=otra.tarjeta, libreta=otra.libreta)
            if not ficha.codigo and otra.codigo and otra.codigo != re.sub(r"\D", "", ficha.cedula or ""):
                ficha = replace(ficha, codigo=otra.codigo)
        unidad.ficha = ficha

    def numeros(self, payload, unidades) -> None:
        """La identificación y el código de cada estudiante, asegurados."""
        from concurrent.futures import ThreadPoolExecutor
        from dataclasses import replace

        from ...domain.historia_academica import LEIDO, SIN_VERIFICAR

        faltan = []
        for unidad in unidades:
            if unidad.ficha is None or not unidad.pagina_de_la_ficha:
                continue
            self._releer_gratis(unidad)
            if not unidad.ficha.identificacion or not unidad.ficha.codigo:
                faltan.append(unidad)
        if not faltan:
            return
        if self._verificador is None:
            for unidad in faltan:
                self.estados[unidad.paginas[0]] = {
                    casilla: SIN_VERIFICAR for casilla in self._casillas_que_faltan(unidad.ficha)
                }
            return
        _anunciar(payload, Stage.IDENTIFYING, detail=f"asegurando con la IA los datos de {len(faltan)} estudiantes")
        # Antes de preguntar, una lectura de verdad de cada ficha que no la
        # tenga; con ella se vuelve a buscar gratis, y sólo lo que siga
        # faltando se le pregunta a la IA.
        for unidad in faltan:
            if self.lectura_real(unidad):
                self._releer_gratis(unidad)
        faltan = [u for u in faltan if not u.ficha.identificacion or not u.ficha.codigo]
        with ThreadPoolExecutor(max_workers=LECTORES_DE_IA) as pool:
            respuestas = list(pool.map(self._preguntar, faltan))
        for unidad, verificacion in zip(faltan, respuestas, strict=True):
            clave = unidad.paginas[0]
            casillas = self._casillas_que_faltan(unidad.ficha)
            if verificacion is None:
                self.estados[clave] = {casilla: SIN_VERIFICAR for casilla in casillas}
                continue
            ficha = unidad.ficha
            if not ficha.identificacion:
                for casilla in ("cedula", "tarjeta", "libreta"):
                    if numero := verificacion.numeros.get(casilla):
                        ficha = replace(ficha, **{casilla: numero})
                        self.notas.setdefault(clave, []).append(f"{casilla} {numero} leída al verificar con la IA")
                        break
            if (
                not ficha.codigo
                and (numero := verificacion.numeros.get("codigo"))
                and numero != re.sub(r"\D", "", ficha.cedula or "")
            ):
                ficha = replace(ficha, codigo=numero)
                self.notas.setdefault(clave, []).append(f"código {numero} leído al verificar con la IA")
            unidad.ficha = ficha
            self.estados[clave] = {
                casilla: verificacion.estados.get(casilla, SIN_VERIFICAR)
                for casilla in self._casillas_que_faltan(ficha)
                if verificacion.estados.get(casilla) != LEIDO
            }

    @staticmethod
    def _casillas_que_faltan(ficha) -> list[str]:
        casillas = [] if ficha.identificacion else ["cedula", "tarjeta", "libreta"]
        return casillas if ficha.codigo else [*casillas, "codigo"]

    def anios(self, unidad, inicial, final) -> tuple[int | None, int | None, str | None]:
        """Los años que le falten al estudiante, de lo que la IA lee en su ficha y sus notas."""
        from ...domain.datos_esperados import MAXIMO_DE_ANIOS
        from ...domain.historia_academica import anios as anios_de

        if (inicial and final) or self._verificador is None or unidad.ficha is None or not unidad.pagina_de_la_ficha:
            return inicial, final, None
        pagina = unidad.pagina_de_la_ficha
        if pagina not in self._notas and self._leer_pagina is not None:
            # Su hoja de notas, leída de verdad si no lo estaba: sus períodos
            # -- «IPA/05», «AÑO 90» -- son los años (TORRES PARERNINA, 2026-11-06).
            siguiente = next((numero for numero in unidad.paginas if numero != pagina), None)
            if siguiente and (texto := self._leer_pagina(siguiente)):
                self._notas[pagina] = texto
                self._respuestas.pop(unidad.paginas[0], None)  # se pregunta otra vez, con las notas
                desde, hasta = anios_de([texto])
                nuevo_inicial, nuevo_final = inicial or desde, final or hasta
                if (
                    (nuevo_inicial, nuevo_final) != (inicial, final)
                    and not (nuevo_inicial and nuevo_final and not 0 <= nuevo_final - nuevo_inicial <= MAXIMO_DE_ANIOS)
                ):
                    inicial, final = nuevo_inicial, nuevo_final
                    if inicial and final:
                        return inicial, final, "fechas extremas completadas con la hoja de notas leída al verificar"
        verificacion = self._preguntar(unidad)
        if verificacion is None:
            return inicial, final, None
        nuevo_inicial = inicial or verificacion.anio_ingreso
        nuevo_final = final or verificacion.anio_final
        if nuevo_inicial and nuevo_final and not 0 <= nuevo_final - nuevo_inicial <= MAXIMO_DE_ANIOS:
            return inicial, final, None
        if (nuevo_inicial, nuevo_final) == (inicial, final):
            return inicial, final, None
        return nuevo_inicial, nuevo_final, "fechas extremas completadas al verificar la ficha con la IA"


def _sin_numeros_ajenos(unidades, asegurador: _Asegurador) -> None:
    """Ningún estudiante se queda con la cédula, la TI, la libreta o el código de otro.

    CONDE DIAZ (Retirados 2003, 2026-11-06) salió con la cédula 22809768 de
    VILLALOBOS GARI, la de antes: su ficha la trae en blanco. Si dos estudiantes
    distintos comparten un número, se lo queda el que lo trae escrito en sus
    hojas; al otro se le quita, con su nota. Si ninguno o los dos lo traen, se
    queda como está y el agente de los datos lo marca como error.
    """
    from dataclasses import replace

    from ...domain.historia_academica import en_el_texto

    etiquetas = {"cedula": "la cédula", "tarjeta": "la tarjeta de identidad", "libreta": "la libreta militar", "codigo": "el código"}
    for casilla, etiqueta in etiquetas.items():
        por_numero: dict[str, list] = {}
        for unidad in unidades:
            if unidad.ficha is not None and (numero := re.sub(r"\D", "", getattr(unidad.ficha, casilla) or "")):
                por_numero.setdefault(numero, []).append(unidad)
        for numero, suyas in por_numero.items():
            if len(suyas) < 2 or len({(u.ficha.nombre or "").upper() for u in suyas}) < 2:
                continue
            propias = [u for u in suyas if any(en_el_texto(numero, t) for t in asegurador.propios(u))]
            if not propias or len(propias) == len(suyas):
                continue
            dueno = propias[0].ficha.nombre or f"la página {propias[0].paginas[0]}"
            for unidad in suyas:
                if unidad in propias:
                    continue
                unidad.ficha = replace(unidad.ficha, **{casilla: None})
                unidad.dudas.append(f"{etiqueta} {numero} es de {dueno} y no está en sus hojas: se quitó")
                logger.info("%s %s quitada de %s: es de %s", etiqueta, numero, unidad.ficha.nombre, dueno)


def _segunda_lectura(payload, taller, source, unidades, conocidas=()) -> None:
    """El nombre y la cédula de cada ficha releídos con zoom en sus zonas, y votados con la página.

    Tesseract ubica en la imagen el rótulo de cada zona -- «Nombre del
    estudiante», «Observaciones», «Cédula o tarjeta» -- y su renglón se lee
    ampliado, tres por página facturada (``domain/doble_lectura.py``). El
    nombre se vota entre la página y las dos zonas donde la ficha lo escribe,
    como pidió el operador (2026-10-30); la cédula, si discrepa, queda la de
    la página y va a revisión. Lo que no se resuelve va a la cola de revisión.
    """
    from dataclasses import replace

    from ...domain.doble_lectura import conciliar_numero, votar_nombre
    from ...domain.historia_academica import (
        FRANJA_DE_LA_CEDULA,
        FRANJA_DE_OBSERVACIONES,
        FRANJA_DEL_NOMBRE,
        leer_ficha,
        nombre_de_observaciones,
    )

    con_ficha = [unidad for unidad in unidades if unidad.ficha is not None and unidad.pagina_de_la_ficha]
    if not con_ficha:
        return
    paginas = [unidad.pagina_de_la_ficha for unidad in con_ficha]
    leidos = {}
    for franja in (FRANJA_DE_LA_CEDULA, FRANJA_DEL_NOMBRE, FRANJA_DE_OBSERVACIONES):
        taller.control.check()
        _anunciar(payload, Stage.IDENTIFYING, detail=f"releyendo {franja.campo} con zoom")
        mosaico = taller.mosaico_de_campo(franja)
        leidos[franja.campo] = mosaico.leer_franjas(source, paginas) if mosaico is not None else {}
    for unidad in con_ficha:
        pagina = unidad.pagina_de_la_ficha
        de_la_cedula = leer_ficha(leidos[FRANJA_DE_LA_CEDULA.campo].get(pagina, ""))
        cedula, duda_de_la_cedula = conciliar_numero(unidad.ficha.cedula, de_la_cedula.cedula, "la cédula")
        tarjeta, duda_de_la_tarjeta = conciliar_numero(
            unidad.ficha.tarjeta, de_la_cedula.tarjeta, "la tarjeta de identidad"
        )
        del_renglon = leer_ficha(leidos[FRANJA_DEL_NOMBRE.campo].get(pagina, "")).nombre
        de_observaciones = nombre_de_observaciones(
            leidos[FRANJA_DE_OBSERVACIONES.campo].get(pagina, ""), conocidas
        )
        nombre, duda_del_nombre = votar_nombre(unidad.ficha.nombre, [del_renglon, de_observaciones], conocidas)
        unidad.ficha = replace(unidad.ficha, nombre=nombre, cedula=cedula, tarjeta=tarjeta)
        unidad.dudas.extend(
            duda for duda in (duda_del_nombre, duda_de_la_cedula, duda_de_la_tarjeta) if duda
        )


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
