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
  IA, en un mosaico de cabeceras (diez por página facturada). La cédula de la
  hoja manuscrita que no sale entera se mira otra vez en su esquina, con zoom
  (cuatro por página facturada). Con «Solo OCR» no se leen y cada hoja sale
  con sus páginas por nombre.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import NamedTuple

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
#: Las fechas de pago de los comprobantes («910125 T O T A L»), a la izquierda:
#: a 150 ppp y hasta el 40 % del ancho, Tesseract las lee igual y un tercio más
#: rápido que a 200 y hasta el 55 % (2026-11-06).
BANDA_DEL_PAGO = Band(0.0, 0.0, 0.40, 1.0)
#: De los comprobantes se lee una hoja de cada tantas; donde cambia el mes, las de en medio.
PASO_DE_LOS_COMPROBANTES = 3
#: La cabecera de la tarjeta: apellidos, nombre, cédula y año. Medida sobre la
#: nómina de 1975: ceñida, diez de diez bien leídas; con un recorte más alto el
#: mosaico pierde nitidez y salía «CASTELLAR AGUA 4064» por CASTELLAR MEZA
#: TULIO 9064111. La tarjeta corrida, cuyo nombre no sale, se mira otra vez con
#: más papel (``_mas_alta``). No se ancla en el rótulo «Apellidos» de la capa:
#: el escáner lo trae desplazado.
BANDA_DE_LA_TARJETA = Band(0.40, 0.05, 0.78, 0.17)
#: El renglón del nombre de la hoja manuscrita, con su «C.C.#», y la casilla
#: del año: medido sobre el libro de anotaciones de 1972 y las anotaciones de
#: pago de 1974. Hasta el 80 % del ancho cortaba la cédula de 1972, que va del
#: 70 % al 98 %: la IA leía «$2.351,71 c», el principio de «c.c.#», y el libro
#: salió sin una sola cédula (2026-11-06). Hasta el 95 %; más allá entra el
#: folio de la esquina («21 323») y la IA lo lee por la cédula.
BANDA_DE_LA_HOJA = Band(0.10, 0.0, 0.95, 0.17)
#: La segunda mirada a la cédula de la hoja manuscrita, cuando la IA ve el
#: rótulo «C.C.#» y no un número entero (el operador: «si es necesario hacerle
#: zoom, adelante»): la mitad de arriba de la hoja, una por imagen. La esquina
#: sola o el renglón solo, la IA los toma por una foto y no devuelve nada;
#: con media hoja leyó «26/885693», que la franja dejaba en el borde
#: (2026-11-06, libro de 1972, hoja 301).
BANDA_DE_LA_CEDULA_DE_LA_HOJA = Band(0.0, 0.0, 1.0, 0.5)
#: Una por página facturada, y a qué resolución, en esa mirada.
CEDULAS_DE_HOJA = (1, 300)
#: Los renglones de esa media hoja en que se busca el rótulo: el folio, el
#: nombre y la cédula van arriba; debajo, la cuadrícula.
RENGLONES_DE_LA_SEGUNDA_MIRADA = 6
#: Lo que se dice en la fila y no va a la cola de revisión: lo normal, no una falta.
NOTA_DEL_ANIO = "fechas: el año"
NOTA_DE_CEDULA_EN_BLANCO = "la hoja deja la C.C. en blanco"

#: Cuántas cabeceras por página facturada y a qué resolución. La tarjeta, diez
#: a 200 ppp (las diez leídas, 2026-11-06); la hoja a lápiz de 1974 necesita
#: 300 ppp, y a esa resolución caben ocho.
CABECERAS_DE_TARJETA = (10, 200)
CABECERAS_DE_HOJA = (8, 300)

#: Una capa de texto con menos letras que esto no dice qué hoja es.
_CAPA_POBRE = 60


#: La muestra con que se sabe de qué es un libro sin capa de texto, con la IA:
#: sus primeras hojas -- la tapa, el índice, el primer hablador -- y una de
#: cada tantas después.
PRIMERAS_DE_LA_MUESTRA = 12
UNA_DE_CADA = 8


def muestra_del_libro(paginas: list[int]) -> list[int]:
    """Las primeras doce y una de cada ocho después: de qué es el libro, sin leerlo entero."""
    return [p for posicion, p in enumerate(paginas) if posicion < PRIMERAS_DE_LA_MUESTRA or posicion % UNA_DE_CADA == 0]


def muestra_de_comprobantes(paginas: list[int]) -> list[int]:
    """Una hoja de cada ``PASO_DE_LOS_COMPROBANTES``, y la última."""
    muestra = paginas[::PASO_DE_LOS_COMPROBANTES]
    if paginas and paginas[-1] not in muestra:
        muestra.append(paginas[-1])
    return muestra


def paginas_donde_cambia_el_mes(hojas, muestra: list[int], paginas: list[int]) -> list[int]:
    """Las hojas sin leer entre dos leídas con distinto mes de pago: ahí está el corte."""

    def mes(numero: int):
        fechas = hojas[numero - 1].fechas
        return Counter((f[2], f[1]) for f in fechas).most_common(1)[0][0] if fechas else None

    leidas = [p for p in muestra if mes(p) is not None]
    en_medio: list[int] = []
    for antes, despues in zip(leidas, leidas[1:], strict=False):
        if mes(antes) != mes(despues):
            en_medio.extend(p for p in paginas if antes < p < despues and p not in muestra)
    return en_medio


def escribir_paginas(original, fuente: Path, paginas: list[int], destino: Path) -> None:
    """El PDF de esas hojas del original, en ese orden, deprisa.

    - **El libro entero, en su orden: se copia el archivo.** «NOMINAS MARZO
      1991» -- 777 hojas, 1,7 GB, un solo mes -- se rehacía hoja por hoja y se
      guardaba con ``garbage=3``, y pasó más de una hora «Escribiendo los PDF»
      (2026-11-06).
    - **Lo demás, por tramos de hojas seguidas** -- una inserción por tramo, no
      una por hoja -- y guardado con ``garbage=1``, como el ensamblador: sobre
      un escaneo de 192 MB, ``garbage=4`` con ``deflate`` costó 347 s y
      ``garbage=1``, 0,65 s (``pymupdf_assembler``).
    """
    import shutil

    import pymupdf

    if paginas == list(range(1, original.page_count + 1)):
        shutil.copyfile(fuente, destino)
        return
    tramos: list[list[int]] = []
    for numero in paginas:
        if tramos and numero == tramos[-1][-1] + 1:
            tramos[-1].append(numero)
        else:
            tramos.append([numero])
    with pymupdf.open() as nuevo:
        for tramo in tramos:
            nuevo.insert_pdf(original, from_page=tramo[0] - 1, to_page=tramo[-1] - 1)
        nuevo.save(destino, garbage=1)


def _sin_tildes(texto: str) -> str:
    plano = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", "-", plano).strip("-")


def _letras(texto: str) -> int:
    return sum(1 for caracter in texto if caracter.isalpha())


#: Lo más largo que se deja ser al nombre de un PDF, sin la extensión (ver historias).
LARGO_DEL_NOMBRE = 80


def nombre_del_pdf(orden: int, documento, *, carpeta: Path | None = None, inicial=None) -> str:
    """El nombre del PDF de un documento, en mayúsculas y con su orden delante.

    - Una persona: sólo su nombre y su cédula, como las historias académicas
      («quítale lo que dice historias académicas», el operador, 2026-11-06):
      «03_CASTELLAR-MEZA-TULIO-9064111.pdf». Sin nombre, sus páginas:
      «07_PAGINAS-12-13.pdf».
    - Un listado: «NOMINA» y su fecha, «05_NOMINA-03-07-1984.pdf»; un mes de
      comprobantes, «NOMINA-01-1991»; el del hablador, «LISTADO-DE-NOMINA-PERSONAL-1991».
    - El índice: «01_INDICE.pdf».

    ``inicial`` (día, mes, año) es la fecha inicial que aseguró el revisor de
    fechas cuando corrigió la leída: el listado se llama por ella (2026-11-10).
    """
    from ...domain import nomina as n
    from ...domain.naming import WINDOWS_PATH_LIMIT

    paginas = f"PAGINAS-{documento.paginas[0]}-{documento.paginas[-1]}"
    if documento.clase == n.DEL_INDICE:
        cuerpo, cola = "INDICE", ""
    elif documento.clase == n.PAQUETE:
        asegurada = inicial
        inicial = min(documento.fechas, key=lambda f: (f[2], f[1], f[0])) if documento.fechas else None
        if asegurada is not None and inicial is not None:
            inicial = asegurada
        if documento.anio is not None and not documento.fechas:
            cuerpo = f"LISTADO-DE-NOMINA-PERSONAL-{asegurada[2] if asegurada else documento.anio}"
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


# -- el revisor de fechas (2026-11-10) -----------------------------------------------------

#: La fecha que la fila tomó del libro -- de su nombre o de su índice -- porque
#: sus hojas no la dicen, y que la fila ya declara («el año 1975 del libro: la
#: hoja no lo dice», «los años 1993 a 1994 del libro»).
_DEL_LIBRO = re.compile(r"(?:el año \d{4}|los años \d{4} a \d{4}) del libro")


def tomada_del_libro(de_donde: str | None) -> bool:
    """Si las fechas de la fila salieron del libro y no de sus hojas, como lo dice ``de_donde``."""
    return bool(de_donde and _DEL_LIBRO.search(de_donde))


def el_papel_de_la_fila(textos, ventana: tuple[int, int] | None = None) -> list[str]:
    """Lo ya leído de las hojas de un documento, cada texto una vez y con sus fechas cortas escritas enteras.

    El contraste del revisor de fechas (``domain/fechas_extremas``) sólo
    entiende años de cuatro cifras y fechas enteras; los papeles de estas
    habilidades las dicen cortas -- «14.06.82» en el listado, «910125» en el
    comprobante, «AÑO 90» en la hoja de notas --. ``con_lo_que_leyeron`` las
    escribe enteras **desde el texto crudo**, con la ventana del libro para el
    siglo. Antes se añadía lo que los lectores de la habilidad habían deducido
    (``lo_leido_en_sus_hojas``): la fecha de la fila, el año del hablador o del
    libro, y la fila se confirmaba a sí misma -- «2.07.81» en el papel, leído
    02/07/1984, salía confirmada (la revisión adversarial, 2026-11-10) --.
    """
    from .fechas_aseguradas import con_lo_que_leyeron, sin_repetir

    return [con_lo_que_leyeron(texto, ventana) for texto in sin_repetir(textos)]


def asegurar_las_fechas(
    report: dict,
    filas: list[dict],
    textos: list[list[str]],
    *,
    habilidad: str,
    taller: Taller,
    ventana: tuple[int, int] | None = None,
    derivadas: list[tuple[bool, bool]] | None = None,
    de_su_lector: list[bool] | None = None,
) -> None:
    """El revisor de fechas sobre cada fila del PDF, antes del agente de los datos y del FUID.

    Lo pidió el operador el 2026-11-10: «estar muy seguro de cada fecha en cada
    documento, sin importar la habilidad», corrigiendo sólo con prueba. La
    misma pieza en las historias, las nóminas y los certificados:

    - ``textos``, por fila, lo que **ya se leyó** de sus hojas -- la capa, el
      OCR de casa, la IA --, con sus fechas cortas escritas enteras desde ese
      mismo texto (``el_papel_de_la_fila``): nada se relee aquí, y nada de lo
      que dedujo el trabajo, que confirmaría a la fila consigo misma.
    - ``derivadas``, por fila, si su fecha inicial y su final salieron de fuera
      de sus hojas -- el año del libro, el del código -- y la fila ya lo dice.
      Esas no se buscan en un papel que no las trae ni se le preguntan a la IA
      (se paga por documento): sólo se miran si caen fuera de ``ventana``. Así
      salió ACOSTA BELLO (UPD3859727): 1994-2001 en un libro de 1978-1988,
      del código y de la IA.
    - La regla es la del perfil de la habilidad (``regla_de_fechas``); la IA,
      la del trabajo si se eligió «OCR + IA», con su plazo
      (``juez_del_trabajo``): una pregunta por documento, sólo con lo dudoso y
      cada hoja una vez. Entre una fila y la siguiente se puede detener.
    - ``de_su_lector``, por fila, si su fecha la leyó el mismo lector de la
      regla sobre el mismo texto -- la firma de un certificado --: confirmarla
      no es una segunda prueba, y se cuenta aparte
      (``confirmadas_por_su_lector``) para que nadie la lea como tal.

    Lo corregido se escribe en la fila con su formato y su nota; lo dudoso va a
    Revisión con su motivo (``anotar_en_el_informe``). Un fallo del revisor se
    anota y la fila sigue como estaba: nunca tumba el trabajo.
    """
    from dataclasses import replace

    from ...application.control import Cancelled
    from ...application.perfiles_de_revision import perfil_de
    from ...application.revisor_de_fechas import (
        CLAVE_DEL_INFORME,
        CONFIRMADA,
        CORREGIDA,
        anotar_en_el_informe,
        revisar_las_fechas,
    )
    from ...domain.fechas_extremas import fechas_de_la_fila
    from .fechas_aseguradas import juez_del_trabajo, sin_repetir

    if not filas:
        return
    regla = perfil_de(habilidad).regla_de_fechas
    juez = juez_del_trabajo(taller)
    control = getattr(taller, "control", None)

    def fuera(fecha) -> bool:
        return fecha is not None and ventana is not None and not ventana[0] <= fecha.year <= ventana[1]

    for indice, fila in enumerate(filas):
        if control is not None:
            control.check()
        documento = str(fila.get("archivo_generado") or "") or (
            f"{fila.get('archivo') or ''} págs. {fila.get('pagina_inicial')}-{fila.get('pagina_final')}"
        )
        try:
            fechas = fechas_de_la_fila(fila)
            if fechas is not None and derivadas and indice < len(derivadas):
                inicial_de_fuera, final_de_fuera = derivadas[indice]
                fechas = replace(
                    fechas,
                    inicial=None if inicial_de_fuera and not fuera(fechas.inicial) else fechas.inicial,
                    final=None if final_de_fuera and not fuera(fechas.final) else fechas.final,
                )
            suyos = sin_repetir(textos[indice] if indice < len(textos) else [])
            revisadas = revisar_las_fechas(fechas, suyos, regla=regla, juez=juez, ventana=ventana)
            anotar_en_el_informe(report, documento, fila.get("pagina_inicial"), revisadas)
            if revisadas.estado == CONFIRMADA and de_su_lector and indice < len(de_su_lector) and de_su_lector[indice]:
                resumen = report[CLAVE_DEL_INFORME]
                resumen["confirmadas_por_su_lector"] = resumen.get("confirmadas_por_su_lector", 0) + 1
            if revisadas.estado == CORREGIDA:
                _con_las_fechas_corregidas(fila, revisadas)
        except Cancelled:
            raise
        except Exception:  # noqa: BLE001 - el revisor no tumba el trabajo: la fila sigue como estaba
            logger.warning("el revisor de fechas falló en %s; la fila sigue como estaba", documento, exc_info=True)


def _con_las_fechas_corregidas(fila: dict, revisadas) -> None:
    """Las fechas corregidas, en la fila con su formato, y la nota en sus observaciones.

    Historias: ``anio_inicial``/``anio_final`` o ``fecha_exacta``; nóminas y
    certificados: ``fecha_inicial``/``fecha_final`` «dd/mm/aaaa» (un año es del
    1 de enero al 31 de diciembre); actas: ``fecha`` «dd-mm-aaaa».
    """
    from ...domain.fechas_extremas import ANIO

    for correccion in revisadas.correcciones:
        inicial = correccion.campo == "fecha_inicial"
        fecha = correccion.dice_el_papel
        if fila.get("fecha_exacta") and revisadas.precision != ANIO:
            fila["fecha_exacta"] = fecha.strftime("%d/%m/%Y")
            if "anio_inicial" in fila:
                fila["anio_inicial" if inicial else "anio_final"] = fecha.year
        elif "anio_inicial" in fila or "anio_final" in fila:
            fila["anio_inicial" if inicial else "anio_final"] = fecha.year
        elif "fecha_inicial" in fila or "fecha_final" in fila:
            if revisadas.precision == ANIO:
                escrita = f"01/01/{fecha.year}" if inicial else f"31/12/{fecha.year}"
            else:
                escrita = fecha.strftime("%d/%m/%Y")
            fila["fecha_inicial" if inicial else "fecha_final"] = escrita
        elif "fecha" in fila:
            fila["fecha"] = fecha.strftime("%d-%m-%Y")
    fila["observaciones"] = "; ".join(texto for texto in (fila.get("observaciones"), revisadas.nota) if texto)


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

        # Las fechas de pago, sólo las de los años del libro: Tesseract lee
        # «710125» por «910125», y cada una así parecía otro mes y obligaba a
        # releer las hojas de en medio (274 en «NOMINAS MARZO 1991»).
        anios_de_pago = n.ventana_del_libro(nombre)

        def del_listado(texto: str):
            # «00» es 2000 y «06» 2006: un año fuera del libro es una mala lectura.
            fecha = n.fecha_del_listado(texto)
            if fecha and anios_de_pago and not anios_de_pago[0] - 1 <= fecha[2] <= anios_de_pago[1] + 1:
                return None
            return fecha

        def pagos(texto: str) -> tuple:
            return tuple(
                f for f in n.fechas_de_pago(texto)
                if anios_de_pago is None or anios_de_pago[0] - 1 <= f[2] <= anios_de_pago[1] + 1
            )

        # 2. Lo que la capa no dice, la cabecera con Tesseract: los libros de
        # 1974 y de 1977-1984 no traen capa.
        sin_capa = [i + 1 for i, (t, p) in enumerate(zip(textos, plantillas, strict=True)) if p is None and _letras(t) < _CAPA_POBRE]
        # Basta una muestra para saber de qué es el libro. Leer con Tesseract
        # cada hoja sin capa costaba un segundo por hoja: catorce minutos en
        # «NOMINAS MARZO 1991», que no trae capa en 772 de sus 777 (2026-11-06).
        cabeceras = _con_tesseract(
            payload, taller, source, local, muestra_del_libro(sin_capa), BANDA_DE_LA_CABECERA, dpi=250, hilos=hilos,
            detalle="mirando de qué es el libro",
        )
        for numero, texto in cabeceras.items():
            plantillas[numero - 1] = n.plantilla_de(texto)
        del_libro = n.plantilla_del_libro(plantillas)
        if (de_pago is None and del_libro == n.LISTADO) or del_libro == n.CERTIFICADO:
            # Un libro de listados sin la IA se mira entero: un hablador de en
            # medio sólo se ve en su hoja. Con la IA lo reconoce su lectura de
            # cada hoja de listado (paso 4).
            resto = [p for p in sin_capa if p not in cabeceras]
            for numero, texto in _con_tesseract(
                payload, taller, source, local, resto, BANDA_DE_LA_CABECERA, dpi=250, hilos=hilos,
                detalle="leyendo la cabecera de las hojas sin capa de texto",
            ).items():
                cabeceras[numero] = texto
                plantillas[numero - 1] = n.plantilla_de(texto)
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
                hoja.fecha = del_listado(lo_leido(hoja.numero))
                hoja.pagina = n.pagina_del_listado(lo_leido(hoja.numero))
            elif hoja.plantilla == n.COMPROBANTE:
                hoja.fechas = pagos(lo_leido(hoja.numero))
        listados = [h.numero for h in hojas if h.plantilla == n.LISTADO]
        leidas_por_la_ia: set[int] = set()
        #: Lo que se leyó de cada hoja fuera de su capa y su cabecera -- la IA --:
        #: el papel en que el revisor de fechas busca las de cada documento,
        #: sin releer nada (2026-11-10).
        leido_aparte: dict[int, list[str]] = {}
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
                if not texto.strip():
                    continue
                leidas_por_la_ia.add(numero)
                leido_aparte.setdefault(numero, []).append(texto)
                # El hablador o el índice que la muestra no vio: lo dice lo leído.
                if (otra := n.plantilla_de(texto)) in (n.HABLADOR, n.INDICE):
                    hoja.plantilla, hoja.anio = otra, n.anio_del_hablador(texto)
                    continue
                hoja.fecha = del_listado(texto) or hoja.fecha
                hoja.pagina = n.pagina_del_listado(texto) or hoja.pagina
            # El año del hablador que reconoció la IA va abajo, fuera del tercio
            # que leyó: la hoja entera con Tesseract, como en el paso 3.
            sin_anio = [h.numero for h in hojas if h.plantilla == n.HABLADOR and h.anio is None]
            for numero, texto in _con_tesseract(
                payload, taller, source, local, sin_anio, None, dpi=150, hilos=hilos,
                detalle="leyendo el año del hablador",
            ).items():
                hojas[numero - 1].anio = n.anio_del_hablador(texto)
        # Tesseract, sólo en lo que la IA no pudo leer: la hoja que leyó y no
        # trae la línea de la fecha no la trae, y releerla era tiempo perdido.
        sin_fecha = [
            numero
            for numero in listados
            if hojas[numero - 1].plantilla == n.LISTADO
            and hojas[numero - 1].fecha is None
            and numero not in leidas_por_la_ia
        ]
        for numero, texto in _con_tesseract(
            payload, taller, source, local, sin_fecha, BANDA_DE_LA_FECHA, dpi=300, hilos=hilos,
            detalle="leyendo la fecha de cada listado",
        ).items():
            hoja = hojas[numero - 1]
            hoja.fecha = del_listado(texto)
            hoja.pagina = hoja.pagina or n.pagina_del_listado(texto)
        # Los comprobantes, una hoja de cada tres: un libro de 777 hojas es casi
        # siempre un solo mes, y leerlas todas costaba catorce minutos en
        # «NOMINAS MARZO 1991» (2026-11-06). Donde el mes cambia entre dos hojas
        # leídas, se leen las de en medio para poner el corte en su sitio.
        sin_pago = [h.numero for h in hojas if h.plantilla == n.COMPROBANTE and not h.fechas]
        muestra = muestra_de_comprobantes(sin_pago)
        de_pago_leido: dict[int, str] = {}
        for numero, texto in _con_tesseract(
            payload, taller, source, local, muestra, BANDA_DEL_PAGO, dpi=150, hilos=hilos,
            detalle="leyendo la fecha de pago de los comprobantes",
        ).items():
            hojas[numero - 1].fechas = pagos(texto)
            de_pago_leido[numero] = texto
        en_medio = paginas_donde_cambia_el_mes(hojas, muestra, sin_pago)
        for numero, texto in _con_tesseract(
            payload, taller, source, local, en_medio, BANDA_DEL_PAGO, dpi=150, hilos=hilos,
            detalle="leyendo dónde cambia el mes de pago",
        ).items():
            hojas[numero - 1].fechas = pagos(texto)
            de_pago_leido[numero] = texto
        # La hoja de comprobantes leída que no dice nada de un comprobante -- ni
        # sueldo, ni total, ni caja -- puede ser un hablador o un índice que la
        # muestra del paso 2 no vio (la revisión, 2026-11-06). Sólo esas: la
        # fecha de pago se lee en una hoja de cada cuatro, y releer todas las
        # que no la dicen desharía lo ganado.
        mudas = [
            p for p, texto in de_pago_leido.items()
            if hojas[p - 1].plantilla == n.COMPROBANTE
            and not hojas[p - 1].fechas
            and p not in cabeceras
            and not re.search(r"SUELDO|TOTAL|T O T A L|CAJA|SOBRETASA|PRIMA|PAGO", texto.upper())
        ]
        for numero, texto in _con_tesseract(
            payload, taller, source, local, mudas, BANDA_DE_LA_CABECERA, dpi=250, hilos=hilos,
            detalle="mirando las hojas sin fecha de pago",
        ).items():
            if (otra := n.plantilla_de(texto)) in (n.HABLADOR, n.INDICE):
                hojas[numero - 1].plantilla, hojas[numero - 1].anio = otra, n.anio_del_hablador(texto)

        # 5. El nombre, la cédula y el año de cada persona: la cabecera de su
        # tarjeta u hoja con la IA, si se pidió.
        sin_leer_la_cabecera, copiadas, rotulos = _leer_las_personas(payload, taller, source, hojas, lo_leido=leido_aparte)

        # 6. Los certificados: de su capa; con la IA, la hoja entera si falta algo.
        for hoja in hojas:
            if hoja.plantilla != n.CERTIFICADO:
                continue
            hoja.datos = n.leer_el_certificado(lo_leido(hoja.numero))
            if de_pago is not None and not (hoja.datos.nombre and hoja.datos.cedula and hoja.datos.fecha):
                try:
                    leido = de_pago.read(source.render(hoja.numero, dpi=200, formato="jpeg")).text or ""
                    hoja.datos = n.leer_el_certificado(leido)
                    leido_aparte.setdefault(hoja.numero, []).append(leido)
                except Exception:  # noqa: BLE001 - sin la relectura, lo de la capa
                    logger.warning("la IA no pudo leer el certificado de la página %s", hoja.numero, exc_info=True)

        # 7. Los documentos, y la fecha de cada paquete confirmada por la IA.
        documentos = n.documentos(hojas, tolerante=de_pago is None)
        notas_de_la_fecha = _confirmar_las_fechas(
            payload, taller, source, de_pago, hojas, documentos, lo_leido=leido_aparte
        )
        documentos, notas_de_la_fecha = _juntar_los_paquetes_iguales(documentos, notas_de_la_fecha)
        _las_tarjetas_sin_cedula(payload, taller, source, documentos)

        anio_del_libro = n.anio_del_libro(nombre, [h.anio for h in hojas if h.plantilla == n.INDICE and h.anio])
        tipo_de_hoja = n.tipo_de_la_hoja(nombre)
        ventana = n.ventana_del_libro(nombre)
        # El patrón del libro: si la mitad de sus hojas manuscritas traen
        # cédula, la que no la trae es para mirar. Y, hoja por hoja, la que trae
        # el rótulo «C.C.#» la pide, salvo que lo deje en blanco (ver la fila).
        # Las de 1972 sí la traen: se dio el libro por uno sin cédula porque la
        # franja la cortaba (2026-11-06).
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
        # Para el revisor de fechas: lo leído de cada documento y si sus fechas
        # salieron del libro (2026-11-10).
        textos_de_las_filas: list[list[str]] = []
        derivadas: list[tuple[bool, bool]] = []
        carpeta_de_salida = taller.destination / document_folder(nombre)
        if pidio_dividir:
            carpeta_de_salida.mkdir(parents=True, exist_ok=True)
        # La ventana del revisor de fechas, con el año de holgura con que
        # ``fechas_extremas`` toma los de la hoja.
        ventana_del_revisor = (ventana[0] - 1, ventana[1] + 1) if ventana else None
        #: Lo que falta para escribir cada documento: su orden, su nombre y la fecha
        #: inicial que se leyó. Las
        #: filas primero; los PDF, con la fecha ya asegurada (2026-11-10).
        por_escribir: list[tuple[int, object, str, str | None]] = []
        for orden, documento in enumerate(documentos, start=1):
            taller.control.check()
            archivo = nombre_del_pdf(orden, documento, carpeta=carpeta_de_salida)
            inicial, final, de_donde = n.fechas_extremas(documento, anio_del_libro=anio_del_libro, ventana=ventana)
            textos_de_las_filas.append(
                el_papel_de_la_fila(
                    [
                        *(lo_leido(p) for p in documento.paginas),
                        *(t for p in documento.paginas for t in leido_aparte.get(p, ())),
                        *(de_pago_leido[p] for p in documento.paginas if p in de_pago_leido),
                    ],
                    ventana_del_revisor,
                )
            )
            # Lo que no salió de sus hojas: el año del libro, y el del índice
            # que no dice el suyo (``fechas_extremas`` le pone el del libro sin
            # decirlo).
            del_libro = tomada_del_libro(de_donde) or (
                documento.clase == n.DEL_INDICE and not documento.anio and anio_del_libro is not None
            )
            derivadas.append((del_libro, del_libro))
            en_blanco, pide_cedula = _la_cedula_que_pide(documento, piden_cedula, rotulos)
            notas = _lo_que_falta(documento, inicial, pide_cedula, sin_leer_la_cabecera, con_ia=de_pago is not None)
            if en_blanco:
                notas.append(NOTA_DE_CEDULA_EN_BLANCO)
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
                    "pide_cedula": pide_cedula,
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
            # es lo normal en la tarjeta (la casilla del año va vacía), ni
            # la «C.C.» que la hoja deja en blanco, que se miró con zoom.
            cola.extend(
                {"page": documento.paginas[0], "reason": f"{archivo}: {nota}"}
                for nota in notas
                if not nota.startswith(NOTA_DEL_ANIO) and nota != NOTA_DE_CEDULA_EN_BLANCO
            )
            por_escribir.append((orden, documento, archivo, _fecha(inicial)))

        # El revisor de fechas (el operador, 2026-11-10), antes de escribir los
        # PDF, del agente de los datos y del FUID: cada fecha contra lo ya leído
        # de sus hojas. **Antes de escribir**: un listado se llama por su fecha
        # («05_NOMINA-03-07-1984.pdf») y, revisada después, salía con la vieja
        # mientras su fila llevaba la corregida (la revisión adversarial).
        _anunciar(payload, Stage.ASSEMBLING, detail="revisando las fechas de cada documento")
        fechas_revisadas: dict = {}
        asegurar_las_fechas(
            fechas_revisadas, filas, textos_de_las_filas, habilidad="nominas", taller=taller,
            ventana=ventana_del_revisor, derivadas=derivadas,
        )
        if pidio_dividir:
            por_escribir = _con_el_nombre_asegurado(por_escribir, filas, cola, fechas_revisadas, carpeta_de_salida)

        _anunciar(payload, Stage.ASSEMBLING, detail=f"escribiendo {len(documentos)} PDF", done=0, total=len(documentos))
        with pymupdf.open(taller.source) as original:
            for orden, documento, archivo, _leida in por_escribir:
                taller.control.check()
                if pidio_dividir:
                    escribir_paginas(original, taller.source, list(documento.paginas), carpeta_de_salida / archivo)
                    esperado[archivo] = list(documento.paginas)
                    salidas.append((carpeta_de_salida / archivo).relative_to(taller.destination).as_posix())
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
    # Lo que dijo el revisor de fechas, que ya corrió antes de escribir los PDF.
    from .fechas_aseguradas import pasar_al_informe

    pasar_al_informe(report, fechas_revisadas)
    integridad = revisar_los_datos(filas, del_revisor.datos, aceptable=del_revisor.margen) if del_revisor.datos else None
    if revision is not None or aviso_del_revisor or comprobacion or integridad is not None:
        anotar_en_el_informe(
            report, revision, aviso_del_revisor, comprobacion, perfil=del_revisor.as_dict(), integridad=integridad
        )
    _escribir_el_fuid(payload, taller, nombre, filas, report)
    return report


def _en_tubo(payload, taller, source, paginas, preparar, leer, *, hilos, detalle, procedencia) -> dict[int, str]:
    """Lee esas páginas en varios hilos y avisa a la pantalla **en cuanto termina cada una**.

    La imagen se prepara en este hilo -- MuPDF no es seguro entre hilos -- y se
    lee en otro; nunca hay más del doble de los hilos esperando. Antes se
    preparaban todas las del libro y sólo después se contaban: la barra se
    quedaba quieta mientras la IA ya iba leyendo (el operador, 2026-11-06:
    «necesito que todo sea reflejado en caliente y muy rápido»). Cada página
    leída repinta su cuadrito con quien la leyó.
    """
    if not paginas:
        return {}
    leidas: dict[int, str] = {}
    total = len(paginas)
    total_del_libro = source.page_count
    _anunciar(payload, Stage.IDENTIFYING, detail=detalle, done=0, total=total)
    vuelo: dict = {}
    hechas = 0

    def protegido(numero: int, imagen: bytes) -> str | None:
        try:
            return leer(imagen) or ""
        except Exception:  # noqa: BLE001 - una hoja que no se deja leer queda sin leer
            # ``None``: ni se pinta como leída ni se da por leída (la revisión, 2026-11-06).
            logger.warning("no se pudo leer la página %s (%s)", numero, procedencia, exc_info=True)
            return None

    def una_mas(numero: int, texto: str | None) -> None:
        nonlocal hechas
        hechas += 1
        if texto is not None:
            leidas[numero] = texto
            _anunciar(payload, Stage.PAGE, page_count=total_del_libro, page_number=numero, provenance=procedencia)
        _anunciar(payload, Stage.IDENTIFYING, detail=detalle, done=hechas, total=total)

    def recoger(todo: bool = False) -> None:
        while vuelo and (todo or len(vuelo) >= 2 * hilos):
            listos, _ = wait(list(vuelo), return_when=FIRST_COMPLETED)
            for futuro in listos:
                una_mas(vuelo.pop(futuro), futuro.result())

    with ThreadPoolExecutor(max_workers=hilos) as pool:
        for numero in paginas:
            taller.control.check()
            recoger()
            try:
                imagen = preparar(numero)
            except Exception:  # noqa: BLE001 - una hoja que no se deja rasterizar queda sin leer
                logger.debug("no se pudo rasterizar la página %s", numero, exc_info=True)
                una_mas(numero, None)
                continue
            vuelo[pool.submit(protegido, numero, imagen)] = numero
        recoger(todo=True)
    return leidas


def _con_tesseract(payload, taller, source, local, paginas, banda, *, dpi, hilos, detalle) -> dict[int, str]:
    """Lo que lee Tesseract en ``banda`` de cada página (la hoja entera sin banda). Gratis."""
    return _en_tubo(
        payload, taller, source, paginas,
        lambda numero: source.render(numero, banda, dpi) if banda is not None else source.render(numero, dpi=dpi),
        lambda imagen: local.read(imagen).text,
        hilos=hilos, detalle=detalle, procedencia="ocr_region",
    )


def _con_la_ia(payload, taller, source, de_pago, paginas, banda, *, dpi, hilos, detalle) -> dict[int, str]:
    """Lo que lee la IA en ``banda`` de cada página, una por imagen: una página facturada cada una."""
    if de_pago is None:
        return {}
    return _en_tubo(
        payload, taller, source, paginas,
        lambda numero: source.render(numero, banda, dpi, formato="jpeg"),
        lambda imagen: de_pago.read(imagen).text,
        hilos=hilos, detalle=detalle, procedencia="vision_model",
    )


class LoLeidoDeLasPersonas(NamedTuple):
    """Lo que dejó la lectura de las cabeceras, para las filas."""

    #: Las páginas cuya cabecera no se pudo leer.
    sin_leer: set[int]
    #: Por página, la cédula que la IA copió de la hoja de abajo y no se tomó.
    copiadas: dict[int, str]
    #: Por página de hoja manuscrita con el rótulo «C.C.#», cómo está su cédula:
    #: ``CEDULA_LEIDA``, ``CEDULA_EN_BLANCO`` o ``CEDULA_INCOMPLETA`` de ``nomina``.
    rotulos: dict[int, str]


def _leer_las_personas(payload, taller, source, hojas, *, lo_leido: dict[int, list[str]] | None = None) -> LoLeidoDeLasPersonas:
    """El nombre, la cédula y el año de cada tarjeta y hoja manuscrita, de su cabecera leída por la IA.

    Las que no vuelven con nombre se miran otra vez, una por imagen y con más
    zoom (el agente se asegura). La hoja manuscrita con el rótulo «C.C.#» y
    sin un número entero detrás, también: su esquina, con zoom
    (``_las_cedulas_con_zoom``). La hoja en la que la IA no ve nada escrito
    arriba es el reverso o la continuación de la anterior: se marca vacía y va
    con ella. Devuelve las páginas que no se pudieron leer, por página la
    cédula que la IA copió de la hoja de abajo y no se tomó, y cómo está la
    cédula de cada hoja manuscrita con rótulo. ``lo_leido`` recoge, por
    página, lo que leyó la IA: el papel del revisor de fechas (2026-11-10).
    """
    from ...domain import nomina as n

    sin_leer: set[int] = set()
    copiadas: dict[int, str] = {}
    rotulos: dict[int, str] = {}
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

        detalle = "leyendo con la IA el nombre de cada persona"
        _anunciar(payload, Stage.IDENTIFYING, detail=detalle, done=0, total=len(suyas))
        vistas: set[int] = set()
        total_del_libro = source.page_count

        def al_leer(
            repartido: dict[int, str],
            detalle: str = detalle,
            total: int = len(suyas),
            vistas: set[int] = vistas,
            total_del_libro: int = total_del_libro,
        ) -> None:
            # Cada tanda que vuelve, en vivo: su avance y el cuadrito de cada hoja.
            for numero in repartido:
                _anunciar(payload, Stage.PAGE, page_count=total_del_libro, page_number=numero, provenance="vision_model")
            vistas.update(repartido)
            _anunciar(payload, Stage.IDENTIFYING, detail=detalle, done=len(vistas), total=total)

        leidas = mosaico.leer_franjas(source, [h.numero for h in suyas], banda, al_leer)
        faltan = [h.numero for h in suyas if not n.leer_los_datos(leidas.get(h.numero, ""), plantilla).nombre]
        if faltan:
            # Con más papel alrededor y más zoom, una por imagen.
            mas_alta = _mas_alta(banda)
            _anunciar(payload, Stage.IDENTIFYING, detail=f"mirando otra vez {len(faltan)} nombres que no salieron", done=0, total=len(faltan))
            otra_vez: set[int] = set()

            def al_releer(repartido: dict[int, str], total: int = len(faltan), otra_vez: set[int] = otra_vez) -> None:
                otra_vez.update(repartido)
                _anunciar(
                    payload, Stage.IDENTIFYING, detail=f"mirando otra vez {total} nombres que no salieron",
                    done=len(otra_vez), total=total,
                )

            releidas = mosaico.otra_mirada().leer_franjas(source, faltan, mas_alta, al_releer)
            for numero, texto in releidas.items():
                if n.leer_los_datos(texto, plantilla).nombre or numero not in leidas:
                    leidas[numero] = texto
        for hoja in suyas:
            if hoja.numero not in leidas:
                sin_leer.add(hoja.numero)
                continue
            texto = leidas[hoja.numero]
            if lo_leido is not None and texto.strip():
                lo_leido.setdefault(hoja.numero, []).append(texto)
            hoja.datos = n.leer_los_datos(texto, plantilla)
            hoja.vacia = _nada_escrito(texto, hoja.datos)
        if plantilla == n.HOJA:
            rotulos.update(_las_cedulas_con_zoom(payload, taller, source, suyas, leidas))
        # La cédula que la IA copió de la tarjeta de abajo en la que continúa
        # (2026-11-06): fuera, y dicho.
        limpias, quitadas = n.sin_cedulas_copiadas([h.datos for h in suyas])
        for posicion, cedula in quitadas.items():
            hoja = suyas[posicion]
            hoja.datos = limpias[posicion]
            copiadas[hoja.numero] = cedula
    return LoLeidoDeLasPersonas(sin_leer, copiadas, rotulos)


def _las_cedulas_con_zoom(payload, taller, source, suyas, leidas: dict[int, str]) -> dict[int, str]:
    """Cómo está la cédula de cada hoja manuscrita con rótulo, mirando con zoom las dudosas.

    La hoja de 1972 lleva «cc#» en el renglón del nombre y, detrás, la cédula
    hasta el borde de la hoja, o nada. Si la IA ve el rótulo y no un número
    entero, se mira otra vez la mitad de arriba de la hoja
    (``BANDA_DE_LA_CEDULA_DE_LA_HOJA``), una por imagen. Lo que vuelve con
    número se toma; con el rótulo solo, la hoja lo deja en blanco; con cifras
    a medias, a revisión. Lo que no vuelve, o vuelve sin el rótulo, se queda
    como lo dijo la primera mirada.
    """
    from dataclasses import replace

    from ...domain import nomina as n

    rotulos: dict[int, str] = {}
    for hoja in suyas:
        if hoja.numero in leidas:
            _, estado = n.cedula_de_la_hoja(leidas[hoja.numero])
            if estado:
                rotulos[hoja.numero] = estado
    dudosas = [h for h in suyas if rotulos.get(h.numero) in (n.CEDULA_EN_BLANCO, n.CEDULA_INCOMPLETA)]
    tamano, dpi = CEDULAS_DE_HOJA
    zoom = taller.mosaico_de_cabeceras(tamano=tamano, dpi=dpi) if dudosas else None
    if zoom is None:
        return rotulos
    detalle = f"mirando con zoom {len(dudosas)} cédulas"
    _anunciar(payload, Stage.IDENTIFYING, detail=detalle, done=0, total=len(dudosas))
    vistas: set[int] = set()

    def al_leer(repartido: dict[int, str]) -> None:
        vistas.update(repartido)
        _anunciar(payload, Stage.IDENTIFYING, detail=detalle, done=len(vistas), total=len(dudosas))

    esquinas = zoom.leer_franjas(
        source, [h.numero for h in dudosas], lambda _pagina: BANDA_DE_LA_CEDULA_DE_LA_HOJA, al_leer
    )
    for hoja in dudosas:
        cedula, estado = n.cedula_de_la_hoja(esquinas.get(hoja.numero, ""), renglones=RENGLONES_DE_LA_SEGUNDA_MIRADA)
        if cedula:
            hoja.datos = replace(hoja.datos, cedula=cedula)
            rotulos[hoja.numero] = n.CEDULA_LEIDA
        elif estado:
            rotulos[hoja.numero] = estado
    return rotulos


#: De cada persona con tarjeta y sin cédula, cuántas de sus tarjetas se miran otra vez.
TARJETAS_POR_PERSONA = 2


def _las_tarjetas_sin_cedula(payload, taller, source, documentos) -> int:
    """La cédula de la persona cuya tarjeta volvió sin ella, mirada otra vez una por imagen.

    La IA lee diez tarjetas por página facturada y a veces la tanda entera
    vuelve sin cédula o con la cédula partida por la raya de la cuadrícula:
    en 1977 tomo 2, las hojas 41 a 50, diez personas y ninguna cédula
    (2026-11-06). Cada persona con tarjeta que no la tiene se mira otra vez:
    sus primeras tarjetas, cada una en su imagen, con más papel y más zoom.
    Lo leído se suma a sus lecturas; con «Solo OCR» no hay a quién pedírselo.
    Devuelve cuántas personas salieron con cédula.
    """
    from ...domain import nomina as n

    sin = [d for d in documentos if d.clase == n.PERSONA and d.plantilla == n.TARJETA and not d.cedula]
    tamano, dpi = CABECERAS_DE_TARJETA
    mosaico = taller.mosaico_de_cabeceras(tamano=tamano, dpi=dpi) if sin else None
    if mosaico is None:
        return 0
    paginas = [p for d in sin for p in d.paginas[:TARJETAS_POR_PERSONA]]
    detalle = f"mirando otra vez la cédula de {len(sin)} personas"
    _anunciar(payload, Stage.IDENTIFYING, detail=detalle, done=0, total=len(paginas))
    vistas: set[int] = set()

    def al_leer(repartido: dict[int, str]) -> None:
        vistas.update(repartido)
        _anunciar(payload, Stage.IDENTIFYING, detail=detalle, done=len(vistas), total=len(paginas))

    def banda(_pagina: int) -> Band:
        return BANDA_DE_LA_TARJETA

    leidas = mosaico.otra_mirada().leer_franjas(source, paginas, _mas_alta(banda), al_leer)
    rescatadas = 0
    for documento in sin:
        for pagina in documento.paginas[:TARJETAS_POR_PERSONA]:
            if cedula := n.leer_la_tarjeta(leidas.get(pagina, "")).cedula:
                documento.lecturas.append(n.DatosDeLaHoja(cedula=cedula))
        rescatadas += bool(documento.cedula)
    logger.info("la segunda mirada a la tarjeta dio la cédula de %d de %d personas", rescatadas, len(sin))
    return rescatadas


def _la_cedula_que_pide(documento, piden_cedula: set[str], rotulos: dict[int, str]) -> tuple[bool, bool]:
    """Si la hoja deja la «C.C.» en blanco, y si la fila pide la cédula.

    La pide la tarjeta y el certificado; la hoja manuscrita, si la trae la
    mitad del libro o si alguna de sus hojas lleva el rótulo «C.C.#». La que
    lleva el rótulo y nada detrás -- mirado con zoom -- la deja en blanco: la
    celda va vacía con su porqué, no a revisión.
    """
    from ...domain import nomina as n

    estados = [rotulos[p] for p in documento.paginas if p in rotulos]
    en_blanco = (
        documento.clase == n.PERSONA
        and not documento.cedula
        and bool(estados)
        and all(estado == n.CEDULA_EN_BLANCO for estado in estados)
    )
    pide = (documento.plantilla in piden_cedula or bool(estados)) and not en_blanco
    return en_blanco, pide


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


def _confirmar_las_fechas(
    payload, taller, source, de_pago, hojas, documentos, *, lo_leido: dict[int, list[str]] | None = None
) -> dict[int, list[str]]:
    """Con la IA, la fecha de cada paquete leída en su primera hoja: Tesseract confunde cifras.

    Una página facturada por paquete. Lo que la IA lee manda; si no coincide
    con lo de Tesseract, la fila lo dice. Sin la IA, la nota dice que la fecha
    salió del OCR de casa. Devuelve las notas de cada documento, por su ``id``;
    ``lo_leido`` recoge lo que leyó la IA, para el revisor de fechas (2026-11-10).
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
        if lo_leido is not None and leido.strip():
            lo_leido.setdefault(primera, []).append(leido)
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


def _con_el_nombre_asegurado(por_escribir, filas: list[dict], cola: list[dict], aparte: dict, carpeta: Path):
    """Cada documento con el nombre que le da su fecha asegurada; la fila, la cola y lo anotado dicen ése.

    Sólo cambia el de un listado cuya fecha inicial corrigió el revisor de
    fechas: los demás no se llaman por su fecha (2026-11-10).
    """
    from ...domain.fechas_extremas import leer_fecha
    from .fechas_aseguradas import renombrar_en_lo_anotado

    nuevos = []
    for indice, (orden, documento, archivo, leida) in enumerate(por_escribir):
        fila = filas[indice]
        nombre = archivo
        asegurada, _precision = leer_fecha(fila.get("fecha_inicial"))
        if asegurada is not None and fila.get("fecha_inicial") != leida:
            nombre = nombre_del_pdf(
                orden, documento, carpeta=carpeta, inicial=(asegurada.day, asegurada.month, asegurada.year)
            )
        if nombre != archivo:
            fila["archivo_generado"] = nombre
            for entrada in cola:
                if str(entrada.get("reason") or "").startswith(f"{archivo}: "):
                    entrada["reason"] = nombre + entrada["reason"][len(archivo):]
            renombrar_en_lo_anotado(aparte, archivo, nombre)
        nuevos.append((orden, documento, nombre, leida))
    return nuevos


def _lo_que_falta(documento, inicial, pide_cedula: bool, sin_leer, *, con_ia: bool) -> list[str]:
    """Lo que no se leyó del documento, dicho para la fila y la cola de revisión."""
    from ...domain import nomina as n

    faltan: list[str] = []
    if documento.clase == n.PERSONA:
        if not documento.nombre:
            faltan.append(
                "no se leyó el nombre" + ("" if con_ia else " (con «Solo OCR» no se lee lo escrito a mano)")
            )
        if pide_cedula and not documento.cedula:
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
    from ...adapters.fuid_de_la_entrega import SUFIJO_JUNTO_AL_TRABAJO as SUFIJO
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
