"""El revisor de fechas en las rutas que parten: resoluciones, diplomas, matrículas, correspondencia y Kingspan.

Lo pidió el operador el 2026-11-10: «estar muy seguro de cada fecha en cada
documento, sin importar la habilidad», corrigiendo sólo con prueba y con un
margen de error. La decisión vive en ``application/revisor_de_fechas``; aquí
sólo lo que comparten los trabajos que la usan, para que el enganche sea el
mismo en todos:

- **Una IA por trabajo, con plazo** (``juez_del_trabajo``): la de «OCR + IA», o
  nadie; y no pregunta más allá de ``BOTPDF_TIEMPO_DEL_REVISOR_DE_FECHAS``.
- **Nunca tumba el trabajo** (``revisar_y_anotar``): un fallo del revisor se
  anota en el registro y el documento sigue como estaba; la cancelación sí sube.
- **Sólo lo ya leído** (``con_lo_que_leyeron``): el contraste del dominio
  entiende «17/12/2012» y «17 de diciembre de 2012»; los papeles de estas rutas
  también dicen «2023/10/14» (Kingspan), «DÍA 3 MES 5 AÑO 2021» (formularios),
  «Cartagena, 21-dic-2021», «3.07.84» o «AÑO 90». Lo que dice ese mismo texto
  se le añade escrito entero: nada se relee, y nada de lo que produjo la fila.
- **Con medio texto no se juzga** (``completo``): si una hoja se leyó por OCR y
  ese texto no se guardó, lo que la capa no trae no prueba nada en contra.
- **Cada fila con su formato** (``asegurar_las_filas_del_fuid``): la fila del
  FUID lleva «dd-mm-aaaa», o el año solo en una matrícula; la corregida sale
  igual, y su nota a NOTAS (que el FUID del cliente entrega vacía).
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import date

logger = logging.getLogger(__name__)

#: «2023/10/14»: año, mes y día, como fecha el sistema contable de Kingspan.
_ANIO_MES_DIA = re.compile(r"(?<!\d)(\d{4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})(?!\d)")

#: Cuánto puede preguntarle a la IA el revisor de fechas en un trabajo, en
#: segundos: lo que quede dudoso después va a Revisión con su motivo, y el
#: trabajo termina igual. ``BOTPDF_TIEMPO_DEL_REVISOR_DE_FECHAS`` lo cambia. La
#: auditoría de cierre ya tenía el suyo (``BOTPDF_TIEMPO_DE_LA_AUDITORIA``); al
#: procesar no había tope (la revisión adversarial, 2026-11-10): un libro con
#: cien documentos dudosos podía pasarse cien preguntas con tres reintentos.
TIEMPO_DEL_REVISOR_DE_FECHAS = 300.0

#: Desde cuántos caracteres la capa de texto de una hoja es lo que se leyó de
#: ella: por debajo, la lectura la pasa por OCR (``application/inventory_file.MIN_CHARS``).
MINIMO_DE_LA_CAPA = 80

#: Por qué una fila que el papel no confirma queda sin dato y no a Revisión.
SIN_TODO_EL_TEXTO = (
    "parte de sus páginas se leyó por OCR y ese texto no se guardó: lo que la capa "
    "de texto no trae no prueba nada en contra (la auditoría de cierre lo mira en "
    "su muestra)"
)


def regla_de(habilidad: str, por_omision: str) -> str:
    """La regla de fechas del perfil de la habilidad (``perfil.regla_de_fechas``), o ``por_omision`` si no la trae."""
    from ...application.perfiles_de_revision import perfil_de

    try:
        return getattr(perfil_de(habilidad), "regla_de_fechas", None) or por_omision
    except Exception:  # noqa: BLE001 - sin perfil, la regla de la habilidad
        return por_omision


def tiempo_del_revisor() -> float:
    """El plazo de la IA del revisor de fechas en un trabajo (``BOTPDF_TIEMPO_DEL_REVISOR_DE_FECHAS``)."""
    try:
        return max(10.0, float(os.environ.get("BOTPDF_TIEMPO_DEL_REVISOR_DE_FECHAS", TIEMPO_DEL_REVISOR_DE_FECHAS)))
    except ValueError:
        return TIEMPO_DEL_REVISOR_DE_FECHAS


def juez_del_trabajo(taller, *, plazo: float | None = None):
    """La IA que contesta lo dudoso de las fechas, una para todo el trabajo; ``None`` con «Solo OCR» o si falla.

    Con su plazo (``tiempo_del_revisor``): pasado, no pide ni reintenta, y lo
    que quede dudoso va a Revisión con su motivo. Es el mismo freno que la
    auditoría de cierre le pone al suyo (``juez.hasta``).
    """
    from ...application.control import Cancelled

    try:
        juez = taller.juez_de_datos()
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 - sin IA, lo dudoso va a Revisión con su motivo
        logger.warning("no se pudo preparar la IA del revisor de fechas", exc_info=True)
        return None
    if juez is not None and callable(getattr(juez, "hasta", None)):
        segundos = tiempo_del_revisor() if plazo is None else plazo
        limite = time.monotonic() + segundos
        avisado: list[bool] = []

        def agotado() -> bool:
            if time.monotonic() <= limite:
                return False
            if not avisado:
                avisado.append(True)
                logger.warning(
                    "el revisor de fechas agotó su plazo de IA (%.0f s): lo dudoso que quede va a Revisión", segundos
                )
            return True

        juez.hasta(agotado)
    return juez


def sin_repetir(textos: Iterable[str]) -> list[str]:
    """Los textos con algo escrito, cada uno una vez y en su orden.

    La misma hoja llega por dos caminos -- la capa y la lectura que la
    sustituyó, la cabecera y la hoja entera --, y a la IA se le paga por
    token: repetirla no da más prueba (la revisión adversarial, 2026-11-10).
    """
    return list(dict.fromkeys(t for t in textos if t and t.strip()))


def revisar_y_anotar(
    report: dict,
    documento: str,
    pagina: int | None,
    fechas,
    textos: Sequence[str],
    *,
    regla: str,
    juez=None,
    ventana: tuple[int, int] | None = None,
    una_sola: bool = False,
    completo: bool = True,
):
    """Las fechas de un documento, revisadas y anotadas en el informe; ``None`` si el revisor falló.

    Con ``una_sola`` el documento tiene una fecha -- la pieza de una caja, el
    documento de una serie de Kingspan --: si el papel corrigiera la inicial y
    la final a dos fechas distintas no hay cuál escribir, y va a Revisión.

    Con ``completo=False`` el texto no es todo lo que se leyó (``solo_lo_confirmado``):
    no se le pregunta a la IA y sólo cuenta lo que el papel confirma.

    Un fallo se anota en el registro y el documento sale como estaba: la fecha
    es un dato más, y el operador eligió que nada tumbe la corrida.
    """
    from ...application.control import Cancelled
    from ...application.revisor_de_fechas import (
        A_REVISION,
        CORREGIDA,
        anotar_en_el_informe,
        revisar_las_fechas,
    )

    try:
        revisadas = revisar_las_fechas(
            fechas, sin_repetir(textos), regla=regla, juez=juez if completo else None, ventana=ventana
        )
        if una_sola and revisadas.estado == CORREGIDA and revisadas.inicial != revisadas.final:
            revisadas = replace(
                revisadas,
                estado=A_REVISION,
                inicial=fechas.inicial,
                final=fechas.final,
                correcciones=(),
                motivos=(
                    "el papel da dos fechas distintas a un documento de una sola: "
                    + "; ".join(f"{c.campo.replace('_', ' ')} {c.dice_el_papel:%d/%m/%Y} ({c.prueba})" for c in revisadas.correcciones),
                ),
            )
        if not completo:
            revisadas = solo_lo_confirmado(revisadas, fechas)
        anotar_en_el_informe(report, documento, pagina, revisadas)
        return revisadas
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 - el revisor no tumba el trabajo
        logger.warning("el revisor de fechas falló en %s; sigue como estaba", documento, exc_info=True)
        return None


def solo_lo_confirmado(revisadas, fechas):
    """Lo decidido sobre medio texto: lo confirmado vale; corregir o mandar a Revisión, no.

    Sin la hoja que se leyó por OCR y no se guardó no hay prueba para corregir
    -- la fecha de la fila puede estar justo en ella -- ni motivo para Revisión:
    queda sin dato, con su porqué. Lo mismo que hace el inventario
    (``inventario._RevisorDeFechas``) y por lo mismo.
    """
    from ...application.revisor_de_fechas import (
        A_REVISION,
        CORREGIDA,
        SIN_DATO,
        FechasRevisadas,
    )

    if fechas is None or revisadas.estado not in (CORREGIDA, A_REVISION):
        return revisadas
    return FechasRevisadas(
        SIN_DATO,
        fechas.inicial,
        fechas.final,
        fechas.precision,
        motivos=(SIN_TODO_EL_TEXTO,),
        confirmadas=revisadas.confirmadas,
    )


def pasar_al_informe(report: dict, aparte: dict) -> None:
    """Lo que el revisor anotó en un informe aparte, en el del trabajo.

    Para las rutas que arman su informe al final -- la caja de correspondencia,
    Kingspan, las nóminas -- y revisan las fechas antes, cuando todavía se
    pueden escribir corregidas: las cuentas, los avisos y lo que va a Revisión,
    igual que si se hubiera anotado ahí.
    """
    from ...application.revisor_de_fechas import CLAVE_DEL_INFORME

    if CLAVE_DEL_INFORME in aparte:
        report[CLAVE_DEL_INFORME] = aparte[CLAVE_DEL_INFORME]
    for clave in ("notices", "review_queue"):
        if aparte.get(clave):
            report.setdefault(clave, []).extend(aparte[clave])


def renombrar_en_lo_anotado(aparte: dict, viejo: str, nuevo: str) -> None:
    """El documento con el nombre que de verdad lleva su PDF, en lo que el revisor anotó de él.

    Una nómina se llama por su fecha («05_NOMINA-03-07-1984.pdf»): si el
    revisor la corrige, el PDF sale con la corregida, y lo anotado tiene que
    nombrar ése y no el que tenía antes de revisarla (2026-11-10).
    """
    from ...application.revisor_de_fechas import CLAVE_DEL_INFORME

    if not viejo or viejo == nuevo:
        return
    aparte["notices"] = [str(aviso).replace(viejo, nuevo) for aviso in aparte.get("notices") or []]
    for entrada in aparte.get("review_queue") or []:
        entrada["reason"] = str(entrada.get("reason") or "").replace(viejo, nuevo)
    for entrada in (aparte.get(CLAVE_DEL_INFORME) or {}).get("detalle") or []:
        if entrada.get("documento") == viejo:
            entrada["documento"] = nuevo


# -- lo que dice el mismo texto, escrito entero --------------------------------------------------

#: «3.07.84», «08/06/00», «14-06-83»: día, mes y año de dos cifras, con el mismo
#: separador. No «26-10-0001» (el renglón de un listado: el año lleva cuatro).
_FECHA_CORTA = re.compile(r"(?<![\d.,/-])(\d{1,2})\s?([./-])\s?(\d{1,2})\s?\2\s?(\d{2})(?![\d.,/-]?\d)")
#: «910125 T O T A L»: el comprobante de pago, en clave AAMMDD delante del total.
_FECHA_DEL_TOTAL = re.compile(r"(?<!\d)(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)\W{0,6}T\s?O\s?T\s?A\s?L")
#: «AÑO 90», «AÑO: 93», «ACUMULACION 75»: el año de dos cifras detrás de su rótulo.
_ANIO_CORTO_CON_ROTULO = re.compile(r"\b(?:A[NÑ]O|ACUMULA\w*)\W{0,3}(\d{2})\b")
#: «IPA/05», «II P.A-93»: el período académico con su año.
_PERIODO_ACADEMICO = re.compile(r"\b(?:I{1,2}|J{1,2})\s?P\s?\.?A\s?[/\-]\s?(\d{2})\b")
#: «1977-83»: un período con el segundo año corto.
_PERIODO_CORTO = re.compile(r"(?<!\d)(19\d{2}|20[0-3]\d)\s?[-–]\s?(\d{2})(?![\d.,/-]?\d)")
#: Lo más largo que dura un período de estudio o de un libro, en años.
_LARGO_DE_UN_PERIODO = 15


def con_lo_que_leyeron(texto: str, ventana: tuple[int, int] | None = None) -> str:
    """El texto de una hoja, más las fechas que ese mismo texto dice, escritas enteras.

    No es un dato nuevo: es la misma fecha del mismo papel, dicha como la
    reconoce el contraste («14/10/2023» por «2023/10/14», «03/07/1984» por
    «3.07.84», «1990» por «AÑO 90»). Sin esto, una fecha bien leída iría a
    Revisión sólo por cómo está escrita.

    **Sólo del texto crudo** (la revisión adversarial, 2026-11-10): nunca lo que
    el trabajo dedujo de él -- la fecha de la fila, la del libro, la que eligió
    el lector de la habilidad --, que confirmaría a la fila consigo misma. Un
    año de dos cifras se escribe entero sólo si su siglo no tiene duda: el
    único que cae en ``ventana`` (los años del libro), o, sin ella, el único que
    no es futuro; «05» sin ventana es 1905 o 2005, y no se escribe.
    """
    from ...domain.fechas import fecha_de_la_pagina, fecha_de_las_casillas

    texto = texto or ""
    if not texto.strip():
        return texto
    leidas: list[date] = []
    anios: list[int] = []
    try:
        leidas.extend(f for f in (fecha_de_la_pagina(texto), fecha_de_las_casillas(texto)) if f)
    except Exception:  # noqa: BLE001 - un texto raro deja sólo el texto
        logger.debug("no se pudieron leer las fechas de una hoja", exc_info=True)
    for anio, mes, dia in _ANIO_MES_DIA.findall(texto):
        if fecha := _fecha(int(dia), int(mes), int(anio)):
            leidas.append(fecha)
    mayusculas = texto.upper()
    for dia, _separador, mes, corto in _FECHA_CORTA.findall(texto):
        if (anio := _siglo(int(corto), ventana)) and (fecha := _fecha(int(dia), int(mes), anio)):
            leidas.append(fecha)
    for corto, mes, dia in _FECHA_DEL_TOTAL.findall(mayusculas):
        if (anio := _siglo(int(corto), ventana)) and (fecha := _fecha(int(dia), int(mes), anio)):
            leidas.append(fecha)
    for corto in [*_ANIO_CORTO_CON_ROTULO.findall(mayusculas), *_PERIODO_ACADEMICO.findall(mayusculas)]:
        if anio := _siglo(int(corto), ventana):
            anios.append(anio)
    for desde, corto in _PERIODO_CORTO.findall(texto):
        hasta = int(desde) // 100 * 100 + int(corto)
        hasta += 100 if hasta < int(desde) else 0
        if 0 < hasta - int(desde) <= _LARGO_DE_UN_PERIODO and (ventana is None or ventana[0] <= hasta <= ventana[1]):
            anios.append(hasta)
    if not leidas and not anios:
        return texto
    escritas = ", ".join(dict.fromkeys([*(f.strftime("%d/%m/%Y") for f in leidas), *map(str, anios)]))
    return f"{texto}\nLEIDO EN LA HOJA: {escritas}"


def _fecha(dia: int, mes: int, anio: int) -> date | None:
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def _siglo(corto: int, ventana: tuple[int, int] | None) -> int | None:
    """El año entero de uno de dos cifras, si sólo uno es posible; ``None`` si hay duda."""
    hoy = date.today().year
    posibles = [siglo + corto for siglo in (1900, 2000) if siglo + corto <= hoy]
    if ventana is not None:
        posibles = [anio for anio in posibles if ventana[0] <= anio <= ventana[1]]
    return posibles[0] if len(posibles) == 1 else None


# -- las filas del FUID --------------------------------------------------------------------------


def escrita_en_el_fuid(fecha: date, precision: str) -> str:
    """Una fecha en la celda del FUID: «dd-mm-aaaa», o el año solo si la fila es de años (matrículas)."""
    from ...domain.fechas_extremas import ANIO

    return str(fecha.year) if precision == ANIO else fecha.strftime("%d-%m-%Y")


def asegurar_las_filas_del_fuid(
    report: dict,
    filas: Sequence,
    grupos: Sequence,
    texto_de: Callable[[int], str],
    *,
    regla: str,
    juez=None,
    archivos: Mapping[int, str] | None = None,
    aparte: Mapping[int, str] | None = None,
    control=None,
    minimo: int = MINIMO_DE_LA_CAPA,
) -> list:
    """Cada fila del FUID (``FuidRow``) con sus fechas revisadas contra sus páginas; las corregidas, escritas.

    ``grupos`` son los de la entrega (``PageGroup``): por la página que abre
    cada uno se saben las hojas de cada fila (``pagina_inicial``). ``texto_de``
    da la capa de texto de una hoja, y ``aparte`` lo que se leyó de ella por
    otro camino -- lo que contestó la IA de una cara --. ``archivos`` nombra el
    documento en el informe como se llama su PDF. ``control`` deja detener el
    trabajo entre una fila y la siguiente.

    Una hoja cuya capa no llega a ``minimo`` caracteres se leyó por OCR al
    procesar, y ese texto no se guardó: si no hay otra lectura suya en
    ``aparte``, la fila sólo se confirma (``solo_lo_confirmado``). Antes se le
    preguntaba a la IA sobre la basura de la capa y la fila iba a Revisión
    (la revisión adversarial del 2026-11-10, el mismo caso que ya guardaba el
    inventario).
    """
    from ...application.revisor_de_fechas import A_REVISION, CORREGIDA
    from ...domain.fechas_extremas import fechas_de_un_par

    hojas_de = {g.page_numbers[0]: list(g.page_numbers) for g in grupos if g.page_numbers}
    nombres = archivos or {}
    otras = aparte or {}
    revisadas_las_filas = []
    for fila in filas:
        if control is not None:
            control.check()
        primera = fila.pagina_inicial
        hojas = hojas_de.get(primera) or (
            list(range(primera, primera + max(1, int(fila.folios or 1)))) if primera else []
        )
        capas = {p: _texto(texto_de, p) for p in hojas}
        textos = [con_lo_que_leyeron(capas[p]) for p in hojas]
        textos += [con_lo_que_leyeron(otras[p]) for p in hojas if otras.get(p)]
        completo = all(len(capas[p].strip()) >= minimo or (otras.get(p) or "").strip() for p in hojas)
        documento = nombres.get(primera) or f"{fila.asunto} (pág. {primera})"
        revisadas = revisar_y_anotar(
            report,
            documento,
            primera,
            fechas_de_un_par(fila.fecha_inicial, fila.fecha_final),
            textos,
            regla=regla,
            juez=juez,
            completo=completo,
        )
        if revisadas is not None and revisadas.estado == CORREGIDA:
            fila = replace(
                fila,
                fecha_inicial=escrita_en_el_fuid(revisadas.inicial, revisadas.precision)
                if revisadas.inicial
                else fila.fecha_inicial,
                fecha_final=escrita_en_el_fuid(revisadas.final, revisadas.precision)
                if revisadas.final
                else fila.fecha_final,
            )
            _con_la_fecha_corregida(report, primera, revisadas)
        if revisadas is not None and revisadas.estado in (CORREGIDA, A_REVISION):
            fila = replace(fila, notas="; ".join(p for p in (fila.notas, revisadas.nota) if p))
        revisadas_las_filas.append(fila)
    return revisadas_las_filas


def _con_la_fecha_corregida(report: dict, primera: int, revisadas) -> None:
    """La fecha corregida en el FUID, también en el ítem del inventario de ese documento.

    De ese ítem salen la planilla que va junto a los PDF, el acta del lote y
    las unidades de la constancia: el FUID decía 16-01-2025 y la planilla
    2019-05-03, la de la serie (la revisión adversarial, 2026-11-10). Sólo una
    fecha con su día; un año suelto no se vuelve «01-01».
    """
    from ...domain.fechas_extremas import DIA

    if not primera or revisadas.inicial is None or revisadas.precision != DIA:
        return
    for item in (report.get("inventory") or {}).get("items") or []:
        if isinstance(item, dict) and item.get("first_page") == primera:
            item["fecha"] = revisadas.inicial.isoformat()
    for grupo in report.get("groups") or []:
        if isinstance(grupo, dict) and "fecha" in grupo and (grupo.get("pages") or [None])[0] == primera:
            grupo["fecha"] = revisadas.inicial.isoformat()


def _texto(texto_de: Callable[[int], str], pagina: int) -> str:
    from ...application.control import Cancelled

    try:
        return texto_de(pagina) or ""
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 - una hoja que no da texto se queda sin él
        logger.debug("no se pudo leer el texto de la pág. %s", pagina, exc_info=True)
        return ""
