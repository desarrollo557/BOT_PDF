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
import re
from collections.abc import Sequence
from pathlib import Path

from ...application.progress import ProgressEvent, Stage
from .planillas import _escribir_indice
from .taller import Taller, _anunciar

#: El perfil con que el agente revisor mira la caja (``perfiles_de_revision``):
#: sus reglas, sus cruces y su margen.
PERFIL = "correspondencia"

#: Cuántas palabras de cuatro letras o más hacen de una hoja un documento con
#: texto propio y no un anexo: las cédulas leídas traen 25-35, la carta de
#: 1000224 pág. 2 trae 107.
PALABRAS_DE_UN_DOCUMENTO = 60

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
#: Desde qué gris se toma un píxel por tinta al buscar el sello claro junto a la
#: firma: con 220 se ve el de 1005965 p2 («…ACEPTACIÓN», «Grupo-epm»), que la
#: lectura normal no veía. El mismo que realza la tinta clara de las actas.
UMBRAL_DE_LA_TINTA_CLARA = 220
#: Por qué va a Revisión el sello al pie cuyo RE no se cree.
RE_AL_PIE_SIN_VALIDAR = (
    "trae sello de radicación al pie con el RE escrito a mano y la IA no lo leyó: "
    "el nombre va sin RE; escríbalo a mano"
)
#: El documento cuyo RE no se cree: sus candidatos, con su motivo, para que
#: los confirme el operador (2026-11-18).
RE_POR_CONFIRMAR = "RE por confirmar, el nombre va sin él hasta que se confirme en la Revisión"
RE_DEL_SELLO_SIN_LEER = (
    "trae sello de radicación con el RE escrito a mano y no se pudo leer con certeza: "
    "el nombre va sin RE; escríbalo a mano"
)
#: Y con «Solo OCR», donde el RE a mano no se lee nunca (2026-11-18).
RE_DEL_SELLO_SOLO_OCR = (
    "trae sello de radicación de tinta con el RE escrito a mano: con «Solo OCR» no se lee; "
    "escríbalo a mano o vuelva a procesar con «OCR + IA»"
)
#: Por qué va a Revisión el documento que lleva su RE en el nombre por lo que es
#: -- reclamo, constancia, contestación, notificación personal -- y no lo trae
#: en ninguna de sus hojas legibles. El operador (2026-11-18): «Verifica que
#: cada reclamación tenga su respectivo RE… Si un dato no puede identificarse
#: con suficiente certeza, debes marcarlo para revisión en lugar de asumir un
#: valor». La fecha de su sello va al índice, no al nombre.
SIN_SU_RE = "{tipo} sin RE: no se identificó su radicado en sus hojas; el nombre va sin RE, escríbalo a mano"


def folios_contra_hojas(piezas, sellos) -> list[dict]:
    """Los documentos cuyas hojas no cuadran con los folios del sello que los abre, para la Revisión (2026-11-18).

    Cada documento -- cada pieza, no cada archivo: por trámite un archivo junta
    varios --, con el sello de su primera hoja. El sello que no dice folios no
    cuenta.
    """
    from ...domain.sello import folios_que_no_cuadran

    avisos = []
    for pieza in piezas:
        paginas = list(pieza.get("pages") or [])
        sello = sellos.get(paginas[0]) if paginas else None
        motivo = folios_que_no_cuadran(len(paginas), getattr(sello, "folios", None))
        if motivo:
            avisos.append({"page": paginas[0], "reason": f"folios del sello: {motivo}"})
    return avisos


def documentos_con_sello_sin_re(grupos, sellos, *, no_cuentan=frozenset(), escritos=frozenset()) -> list[int]:
    """La primera hoja de cada documento que trae un sello de tinta sin su RE leído y salió sin RE en el nombre.

    Para «Solo OCR» (2026-11-18): el RE a mano no se lee sin la IA, y el
    documento iba sin RE y sin aviso. No cuentan las copias aportadas como
    prueba, el acuerdo de pago ni las copias dentro de los folios. Y el que
    abre con un escrito del usuario (``escritos``), aunque no se haya visto su
    sello: Afinia los radica siempre con el suyo, y con poca tinta la lectura
    no lo ve (1005117, UPD2437857 pág. 4 y UPD2973878 pág. 6).
    """
    from ...domain.nombre_oficial import es_re

    salida = []
    for grupo in grupos.groups:
        if not grupo.page_numbers or any(es_re(pieza) for pieza in grupo.code.value.split()):
            continue
        if grupo.page_numbers[0] in escritos or any(
            p not in no_cuentan and (s := sellos.get(p)) is not None and s.clase == "tinta" and not s.radicado
            for p in grupo.page_numbers
        ):
            salida.append(grupo.page_numbers[0])
    return salida


def documentos_sin_su_re(grupos, ya_avisadas, textos: dict | None = None) -> list[dict]:
    """Los documentos que llevan su RE en el nombre por lo que son y salieron sin él, para la Revisión.

    También con «Solo OCR» (2026-11-18). No repite la hoja que ya tiene su
    aviso del RE -- el sello a mano sin leer, el RE que el agente no cree --.
    La notificación que no cita ningún radicado no lo lleva (``le_falta_su_re``).
    """
    from ...domain.nombre_oficial import es_re, le_falta_su_re

    avisos = []
    for grupo in grupos.groups:
        if not grupo.page_numbers or not le_falta_su_re(
            grupo.kind, None if textos is None else [textos.get(p, "") or "" for p in grupo.page_numbers]
        ):
            continue
        if any(es_re(pieza) for pieza in grupo.code.value.split()):
            continue
        if grupo.page_numbers[0] in ya_avisadas:
            continue
        avisos.append({"page": grupo.page_numbers[0], "reason": SIN_SU_RE.format(tipo=grupo.kind)})
    return avisos


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
#: La cabeza de la hoja, donde va «Ciudad, fecha» de la carta y del formulario,
#: y a cuánto se relee cuando su fecha choca con la de la caja.
CABEZA_DE_LA_HOJA = (0.0, 0.0, 1.0, 0.3)
PPP_PARA_LA_CABEZA = 300


#: Cuántas hojas mira la IA con visión por caja, como mucho, buscando una fecha.
FECHAS_A_LA_VISTA_POR_CAJA = 40


def _contrastar_las_fechas(
    piezas: list[dict], textos: dict, ruta_pdf, taller, releidas: dict[int, list[str]], revision: list[dict]
) -> list[dict]:
    """Las fechas de la caja contra sí mismas: la dudosa se relee en su propio papel; si no se resuelve, vacía y a Revisión.

    Lo pidió el operador el 2026-11-18 ante 4100975: el OCR leyó la solicitud
    «11 de Agosto de 2024» -- el «21» escrito a mano tras el «20» impreso --,
    y el expediente, la declaración, el RETIE y las constancias de esa caja
    son del 11-08-2021.

    La dudosa la dice ``fechas_dudosas``: el mismo día y mes que otras de la
    caja, y un año en minoría. Las demás no le dan su fecha -- otro documento
    no es prueba --: la IA con visión relee su hoja. Si lee el año de la caja,
    vale esa lectura, con el año respaldado por la caja; si lee el suyo, se
    queda. Si no, va sin fecha y a Revisión con las dos candidatas: nunca una
    fecha equivocada en el índice.
    """
    from datetime import date

    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...application.ports import Band
    from ...domain.fecha_por_estructura import (
        PEDIDO_DE_LA_FECHA_A_LA_VISTA,
        fecha_de_lo_visto,
        fechas_dudosas,
    )
    from ...domain.fechas import fechas_de

    def iso(valor) -> date | None:
        try:
            return date.fromisoformat(str(valor)[:10]) if valor else None
        except ValueError:
            return None

    fechas = [iso(pieza.get("fecha")) for pieza in piezas]
    dudosas = fechas_dudosas(fechas)
    if not dudosas:
        return []
    vision = taller.lector_de_fechas_a_la_vista()
    de_pago = taller.lector_de_pago()
    halladas: list[dict] = []
    fuente = None
    try:
        fuente = PyMuPDFPageSource(ruta_pdf, taller.name) if vision is not None or de_pago is not None else None
        for i, candidata in sorted(dudosas.items()):
            pieza, leida = piezas[i], fechas[i]
            pagina = pieza.get("fecha_pagina") or (pieza.get("donde_buscar") or pieza["pages"])[0]
            vista = None
            como = "releída por la IA"
            if fuente is not None and vision is not None:
                try:
                    visto = vision.resumir(
                        PEDIDO_DE_LA_FECHA_A_LA_VISTA, imagen=fuente.render(pagina, None, PPP_PARA_LA_FECHA_CON_IA, "jpeg")
                    ) or ""
                except Exception:  # noqa: BLE001 - sin la relectura, la dudosa va a Revisión
                    logger.warning("la IA no pudo releer la fecha dudosa de la pág. %s", pagina, exc_info=True)
                    visto = ""
                if visto:
                    # El año que la IA lea tiene que estar en lo que leyeron
                    # los demás de la hoja o ser el de la caja.
                    leido = "\n".join([textos.get(pagina, "") or "", *(releidas.get(pagina) or []), str(candidata.year)])
                    releidas.setdefault(pagina, []).append(visto)
                    hallada = fecha_de_lo_visto(visto, leido=leido)
                    vista = hallada[0] if hallada else None
            # Y si la hoja entera no lo resuelve, su cabeza ampliada: el año a
            # mano detrás del «20» impreso -- «de 20 21» -- se lee bien de
            # cerca. En 4100975 (UPD2456241 pág. 3, 2026-11-19) la hoja entera
            # dio 2024, la visión 2014 y la cabeza ampliada 2021, lo que dicen
            # las demás de la caja. Sólo vale si la cabeza lee la de la caja:
            # nunca se copia la fecha de otro documento.
            # Primero la cabecera ceñida, sin el texto impreso de la izquierda
            # -- el mismo recorte que L2c, que la caché ya tiene --, y después
            # la franja entera. En 4100975 la franja entera volvió a leer 2024
            # y la ceñida, 2021 (2026-11-19, la corrida del operador).
            recortes = (
                (Band(*BANDA_DE_LA_CABECERA), PPP_PARA_LA_CABEZA, "png"),
                (Band(*CABEZA_DE_LA_HOJA), PPP_PARA_LA_CABEZA, "jpeg"),
            )
            for banda, ppp, formato in recortes:
                if vista in (leida, candidata) or fuente is None or de_pago is None:
                    break
                try:
                    ampliada = de_pago.read(fuente.render(pagina, banda, ppp, formato)).text or ""
                except Exception:  # noqa: BLE001 - sin la relectura, la dudosa va a Revisión
                    logger.warning("la IA no pudo releer la cabeza de la pág. %s", pagina, exc_info=True)
                    ampliada = ""
                if ampliada:
                    releidas.setdefault(pagina, []).append(ampliada)
                    if candidata in fechas_de(ampliada):
                        vista = candidata
                        como = "releída por la IA en la cabeza ampliada"
            if vista == leida:
                continue
            if vista == candidata:
                pieza["fecha"] = vista.isoformat()
                pieza["fecha_por"] = (
                    f"{como} de la pág. {pagina}: se había leído {leida:%d/%m/%Y} y la caja trae "
                    f"{candidata:%d/%m/%Y}"
                )
                pieza["fecha_pagina"] = pagina
                pieza["fecha_via"] = "visión" if como == "releída por la IA" else "ia"
                halladas.append({"pages": pieza["pages"], "fecha": pieza["fecha"], "como": pieza["fecha_por"]})
                continue
            for clave in ("fecha", "fecha_por", "fecha_pagina", "fecha_via"):
                pieza[clave] = None
            revision.append(
                {
                    "page": pagina,
                    "reason": (
                        f"la fecha leída, {leida:%d/%m/%Y}, contradice la de la caja, {candidata:%d/%m/%Y} (el mismo "
                        "día y mes, otro año): va sin fecha hasta que se confirme"
                    ),
                    "candidatos": [leida.isoformat(), candidata.isoformat()],
                }
            )
    finally:
        if fuente is not None:
            fuente.close()
    return halladas


def _fechas_a_la_vista(piezas: list[dict], textos: dict, fuente, taller, releidas: dict[int, list[str]]) -> list[dict]:
    """La fecha que la IA con visión copia de la hoja principal de cada documento que sigue sin ella.

    Sólo la pieza con que abre cada archivo -- su fecha es la de la fila del
    índice (``fecha_de_cada_archivo``) --, y nunca una cédula. Lo que copia
    queda entre lo releído de la hoja: es su evidencia y lo mira el revisor de
    fechas. Lo que no se lee se queda sin fecha (``fecha_de_lo_visto``).
    """
    from ...domain.fecha_por_estructura import (
        PEDIDO_DE_LA_FECHA_A_LA_VISTA,
        fecha_de_lo_visto,
    )
    from ...domain.tramites import es_cedula

    vision = taller.lector_de_fechas_a_la_vista()
    if vision is None:
        return []
    primeras: dict = {}
    for pieza in piezas:
        primeras.setdefault(pieza.get("archivo"), pieza)
    halladas: list[dict] = []
    for pieza in [p for p in primeras.values() if not p.get("fecha")][:FECHAS_A_LA_VISTA_POR_CAJA]:
        principal = (pieza.get("donde_buscar") or pieza["pages"])[0]
        if es_cedula(textos.get(principal, "") or ""):
            continue
        try:
            visto = vision.resumir(
                PEDIDO_DE_LA_FECHA_A_LA_VISTA, imagen=fuente.render(principal, None, PPP_PARA_LA_FECHA_CON_IA, "jpeg")
            ) or ""
        except Exception:  # noqa: BLE001 - sin la visión, el documento sigue sin fecha y va a Revisión
            logger.warning("la IA no pudo mirar la fecha de la pág. %s", principal, exc_info=True)
            continue
        if not visto:
            continue
        # Lo que leyeron de la hoja los demás lectores: el año que la IA copió
        # tiene que estar ahí (4100877: copió un «09-02-23» que nadie más leyó).
        leido = "\n".join([textos.get(principal, "") or "", *(releidas.get(principal) or [])])
        releidas.setdefault(principal, []).append(visto)
        hallada = fecha_de_lo_visto(visto, leido=leido)
        if hallada is None:
            continue
        fecha, campo = hallada
        pieza["fecha"] = fecha.isoformat()
        pieza["fecha_por"] = f"vista por la IA en la pág. {principal} ({campo})"
        pieza["fecha_pagina"] = principal
        pieza["fecha_via"] = "visión"
        halladas.append({"pages": pieza["pages"], "fecha": pieza["fecha"], "como": pieza["fecha_por"]})
    return halladas


def _el_reconocimiento_mas_reciente(pieza: dict, textos: dict, agente) -> list[dict]:
    """Fecha cada reconocimiento de un acuerdo que trae varios; el acuerdo toma la del más reciente.

    El operador, 2026-11-20: «cuando en un reconocimiento de deuda estén 2
    reconocimientos de deuda, coloca el más reciente». Cada uno se busca
    entero -- su texto, releído, con la IA si se eligió -- y lo releído no se
    vuelve a pagar. Deja en la pieza ``fechas_del_reconocimiento`` --
    [primera hoja, fecha] -- para ordenar el PDF.
    """
    from datetime import date

    fechas: list[tuple[int, date, object]] = []
    actual = date.fromisoformat(str(pieza["fecha"])[:10]) if pieza.get("fecha") else None
    for hojas in pieza.get("reconocimientos") or ():
        if actual is not None and pieza.get("fecha_pagina") in hojas:
            fechas.append((hojas[0], actual, None))
            continue
        hallada = agente.buscar(hojas, textos)
        if hallada is not None:
            fechas.append((hojas[0], hallada.fecha, hallada))
    pieza["fechas_del_reconocimiento"] = [[primera, fecha.isoformat()] for primera, fecha, _ in fechas]
    if not fechas:
        return []
    primera, fecha, hallada = max(fechas, key=lambda f: f[1])
    del_reconocimiento = {p for hojas in pieza["reconocimientos"] for p in hojas}
    if hallada is None or (actual is not None and pieza.get("fecha_pagina") in del_reconocimiento and fecha <= actual):
        return []
    pieza["fecha"] = fecha.isoformat()
    pieza["fecha_por"] = f"{hallada.como()}, el más reciente de {len(pieza['reconocimientos'])} reconocimientos"
    pieza["fecha_pagina"] = hallada.pagina
    pieza["fecha_via"] = hallada.via
    return [{"pages": pieza["pages"], "fecha": pieza["fecha"], "como": pieza["fecha_por"]}]


def _el_reconocimiento_la_confirma(pieza: dict, textos: dict, releidas: dict) -> list[dict]:
    """El reconocimiento que escribe la fecha del acuerdo con el año en dos cifras, como la hoja que la da.

    El operador, 2026-11-20: «por qué no está el reconocimiento de deuda de
    primero si tiene sus fechas». El de 4132589 dice a mano «16 de 09 de 20» y
    el de 4132537 «02 de 02 de 22»: el año a medias no fecha la hoja, la fecha
    salía entera de la carta de instrucciones o de la Habeas Data, y el
    reconocimiento, «sin fecha», iba al final. Si su texto -- la capa o lo que
    se releyó de él -- escribe esa misma fecha, es él quien la da.
    """
    from datetime import date

    from ...domain.fechas import fecha_con_el_dia_roto, fecha_escrita_en

    if not pieza.get("fecha"):
        return []
    fecha = date.fromisoformat(str(pieza["fecha"])[:10])
    reconocimientos = pieza.get("reconocimientos") or []
    fechadas = {int(primera) for primera, _ in pieza.get("fechas_del_reconocimiento") or ()}
    pagina_de_la_fecha = pieza.get("fecha_pagina")
    if any(pagina_de_la_fecha in hojas for hojas in reconocimientos):
        fechadas.update(hojas[0] for hojas in reconocimientos if pagina_de_la_fecha in hojas)
    confirmadas: list[tuple[int, int, str, date]] = []
    for hojas in reconocimientos:
        if hojas[0] in fechadas:
            continue
        for pagina in hojas:
            leidos = [textos.get(pagina, "") or "", *(releidas.get(pagina) or [])]
            trozo = next((t for texto in leidos if (t := fecha_escrita_en(texto, fecha))), None)
            if trozo:
                confirmadas.append((hojas[0], pagina, trozo, fecha))
                break
            # El día roto a mano -- «290 de Oct de 2020» por el 29 -- con el
            # día y el mes que da su respaldo: la fecha es la del
            # reconocimiento, con su año escrito entero. El respaldo de 4132553
            # (la carta de instrucciones, pág. 3) se leyó «del año 2010», y la
            # fila salía en 2010 con el reconocimiento al final (2026-11-20).
            roto = next((r for texto in leidos if (r := fecha_con_el_dia_roto(texto, fecha.day, fecha.month))), None)
            if roto:
                confirmadas.append((hojas[0], pagina, roto[1], roto[0]))
                break
    if not confirmadas:
        return []
    pieza["fechas_del_reconocimiento"] = [
        *(pieza.get("fechas_del_reconocimiento") or []),
        *([primera, suya.isoformat()] for primera, _, _, suya in confirmadas),
    ]
    if any(pagina_de_la_fecha in hojas for hojas in reconocimientos):
        return []
    _, pagina, trozo, suya = max(confirmadas, key=lambda c: c[3])
    if suya != fecha:
        pieza["fecha_por"] = (
            f"«{trozo}» en el reconocimiento (pág. {pagina}): el día y el mes los confirma "
            f"{pieza.get('fecha_por')} ({fecha:%d/%m/%Y}); el año, el del reconocimiento"
        )
    else:
        pieza["fecha_por"] = f"«{trozo}» en el reconocimiento (pág. {pagina}), con el año que da {pieza.get('fecha_por')}"
    pieza["fecha"] = suya.isoformat()
    pieza["fecha_pagina"] = pagina
    return [{"pages": pieza["pages"], "fecha": pieza["fecha"], "como": pieza["fecha_por"]}]


def _completar_las_fechas(
    piezas: list[dict],
    textos: dict,
    ruta_pdf,
    taller,
    *,
    releidas: dict[int, list[str]] | None = None,
    sin_leer: list[dict] | None = None,
) -> list[dict]:
    """Pone fecha a cada documento que salió sin ella. Devuelve de dónde salió cada una.

    El agente (:mod:`~resolutions.application.agente_de_fechas`) relee su hoja
    principal y sus respaldos -- en local y, sólo si el operador eligió una
    lectura con IA, con la IA -- y los fecha en el sitio de su clase. Lo que
    no sale queda sin fecha y, si se pasa ``sin_leer``, anotado ahí para la
    cola de Revisión. Un fallo aquí no tumba la caja.

    Para el revisor de fechas (2026-11-10): ``releidas`` guarda lo que se
    releyó de cada hoja -- es papel ya pagado, y en él se buscará la fecha sin
    volver a leerlo --.
    """
    releidas = releidas if releidas is not None else {}

    def guardada(leer):
        def leer_y_guardar(pagina: int) -> str:
            texto = leer(pagina)
            if texto:
                releidas.setdefault(pagina, []).append(texto)
            return texto

        return leer_y_guardar

    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...adapters.tesseract_ocr import PSM_AUTO, TesseractConfig, TesseractOcr
    from ...application.agente_de_fechas import AgenteDeFechas
    from ...domain.fecha_por_estructura import fecha_de_la_hoja
    from ...domain.tramites import es_cedula

    sin_fecha = [i for i, pieza in enumerate(piezas) if not pieza.get("fecha")]
    # El acuerdo con dos reconocimientos: se fecha cada uno (2026-11-20).
    con_varios = [i for i, pieza in enumerate(piezas) if len(pieza.get("reconocimientos") or ()) > 1]
    if not sin_fecha and not con_varios:
        return []
    halladas: list[dict] = []
    fuente = None
    try:
        fuente = PyMuPDFPageSource(ruta_pdf, taller.name)
        local = TesseractOcr(TesseractConfig(min_word_confidence=0, psm=PSM_AUTO, timeout_seconds=SEGUNDOS_PARA_UNA_HOJA))
        de_pago = taller.lector_de_pago()
        agente = AgenteDeFechas(
            releer=guardada(lambda p: local.read(fuente.render(p, None, PPP_PARA_LA_FECHA_LOCAL)).text),
            leer_con_ia=(
                guardada(lambda p: de_pago.read(fuente.render(p, None, PPP_PARA_LA_FECHA_CON_IA, "jpeg")).text)
                if de_pago is not None
                else None
            ),
            # La cédula no fecha nada: su fecha es la de nacimiento.
            no_fecha=es_cedula,
            # Cada hoja, sólo en el sitio donde su clase pone la fecha; y en
            # el orden en que llegan: la principal primero, luego sus
            # respaldos (2026-11-10). La IA ya no lee primero la hoja con más
            # «fechas» -- la del pagaré -- sino la del reconocimiento.
            fechar=fecha_de_la_hoja,
            en_orden=True,
        )
        for i in sin_fecha:
            hallada = agente.buscar(piezas[i].get("donde_buscar") or piezas[i]["pages"], textos)
            if hallada is not None:
                piezas[i]["fecha"] = hallada.fecha.isoformat()
                piezas[i]["fecha_por"] = hallada.como()
                piezas[i]["fecha_pagina"] = hallada.pagina
                piezas[i]["fecha_via"] = hallada.via
                halladas.append({"pages": piezas[i]["pages"], "fecha": piezas[i]["fecha"], "como": hallada.como()})
        for i in con_varios:
            halladas.extend(_el_reconocimiento_mas_reciente(piezas[i], textos, agente))
        for pieza in piezas:
            if pieza.get("reconocimientos"):
                halladas.extend(_el_reconocimiento_la_confirma(pieza, textos, releidas))
        # El último recurso: la IA con visión copia las fechas de la hoja
        # principal (2026-11-18: «que todos los documentos puedan obtener la
        # fecha de creación o de radicación»). Sólo la del documento con que
        # abre cada archivo, que es la que va al índice; no la de sus anexos.
        halladas.extend(_fechas_a_la_vista(piezas, textos, fuente, taller, releidas))
    except Exception:  # noqa: BLE001 - buscar una fecha no tumba la caja
        logger.warning("no se pudo terminar de buscar las fechas que faltan", exc_info=True)
    finally:
        if fuente is not None:
            fuente.close()

    # Lo que su papel no deja leer se queda sin fecha y va a Revisión. Ya no se
    # presta la de su trámite: medido el 2026-11-10 sobre 280 documentos de
    # Afinia contra el papel, la prestada acertó 18 de 65 veces (de 1 a 361
    # días de error), y el operador eligió «vacía y a Revisión»: nunca una
    # fecha equivocada. Casi siempre es la fecha a mano -- el sello de tinta, el
    # encabezado del reconocimiento -- que sólo la IA lee.
    if sin_leer is not None:
        con_ia = taller.lector_de_pago() is not None
        # Sólo la pieza con que abre cada archivo: su fecha es la de la fila del
        # índice. Las hojas 33-37 del acta 28737950 de 4100976 van dentro del
        # acta fechada el 21-07-2021, y pedían a Revisión una fecha propia
        # (2026-11-19).
        primeras: dict = {}
        for pieza in piezas:
            primeras.setdefault(pieza.get("archivo"), pieza)
        for pieza in piezas:
            if pieza.get("fecha") or primeras.get(pieza.get("archivo")) is not pieza:
                continue
            principal = (pieza.get("donde_buscar") or pieza["pages"])[0]
            sin_leer.append(
                {
                    "page": principal,
                    "reason": (
                        "la fecha del documento no se pudo leer en su hoja principal"
                        + ("" if con_ia else " (a mano: sólo la lee «OCR + IA»)")
                        + "; va sin fecha"
                    ),
                }
            )
    return halladas


#: Cómo se dice, en ``fecha_via``, cada fuente de ``fecha_por_estructura`` que
#: no está en la capa de texto del PDF.
_VIA_DE_LA_FUENTE = {"sello de radicación": "sello", "fecha marcada en la guía": "guia"}
#: Cuánto texto leído se guarda por hoja en la constancia.
LARGO_DE_LO_LEIDO = 4000
#: Por debajo de cuántos caracteres una capa de texto no trae nada que leer.
MINIMO_DE_CAPA = 50


def lo_leido_fuera_de_la_capa(
    piezas: list[dict],
    *,
    releidas: dict[int, list[str]],
    leidas_por_ocr: dict[int, str],
) -> list[dict]:
    """Lo que un lector leyó en el papel para fechar cada pieza y la capa no trae.

    Va a la constancia, y la auditoría de cierre lo suma al papel de esas
    hojas: contrastaba la fecha sólo con la capa del PDF, y la que la IA leyó a
    mano en el encabezado del reconocimiento -- «El Banco, 23 de 12 de 2020»,
    que la capa deja en «ÜD _ , ^ de de» -- salía «no escrita en el
    documento» (3807860, 2026-11-11). Lo que salió de la capa no se guarda: la
    auditoría lo lee igual.

    Cada relectura va aparte, como la fechó el agente: juntas, el encabezado
    que se leía era el de la primera -- la de Tesseract, «Ci Cu lo ¡So de 03
    de Zo22» -- y no el «30 de 08 de 2022» de la IA (1000883, 2026-11-11).
    """
    from datetime import date

    salida: list[dict] = []
    for pieza in piezas:
        fecha, pagina, via = pieza.get("fecha"), pieza.get("fecha_pagina"), pieza.get("fecha_via")
        if not fecha or pagina is None:
            continue
        # También lo que vio la IA con visión: el recurso de 4132571 (pág. 6)
        # se fechó «21/10/2020» por lo visto y la auditoría, que no lo tenía,
        # lo daba por «no escrito en el documento» (2026-11-20).
        if via in ("ocr", "ia", "visión"):
            leidos = list(releidas.get(pagina, ()))
        elif via == "sello":
            leidos = [f"SELLO DE RADICACION: {date.fromisoformat(str(fecha)[:10]):%d/%m/%Y}"]
        elif via == "guia":
            leidos = [f"FECHA MARCADA EN LA GUIA: {date.fromisoformat(str(fecha)[:10]):%d/%m/%Y}"]
        else:
            # De la capa, o de la OCR de una hoja que no la trae.
            leidos = [leidas_por_ocr.get(pagina) or ""]
        salida.extend(
            {"paginas": [pagina], "texto": " ".join(texto.split())[:LARGO_DE_LO_LEIDO]}
            for texto in leidos
            if (texto or "").strip()
        )
    return salida


def _asegurar_las_fechas(
    piezas: list[dict],
    textos: dict,
    taller,
    *,
    releidas: dict[int, list[str]],
    prestadas: dict[int, int],
    sellos: dict,
    fechas_de_guia: dict,
) -> dict:
    """El revisor de fechas sobre cada pieza de la caja; devuelve lo anotado, para el informe.

    Lo pidió el operador el 2026-11-10: «estar muy seguro de cada fecha en cada
    documento». Va después de ``_completar_las_fechas`` y antes de entregar:
    lo corregido llega así al índice. Una pieza tiene una fecha, la inicial y
    la final.

    - **Su papel es lo que ya se leyó de sus hojas**: la capa y el OCR de la
      caja, lo que se releyó buscando su fecha, el sello de radicación y la
      fecha marcada en la guía de LECTA, que tienen lector propio. Nada se
      relee aquí. Una fecha que no está en sus hojas -- la del documento del
      corte, que pudo venir de otra pieza -- va a la IA (si se eligió) y si no
      a Revisión.
    - **La prestada de su trámite** (``prestadas``) no se busca en su papel,
      que por definición no la trae: sigue a la pieza de la que se tomó. Si a
      ésa se le corrige, a ella también; si va a Revisión, ella con el mismo
      motivo.
    """
    from ...application.control import Cancelled

    aparte: dict = {}
    try:
        _revisar_cada_pieza(
            aparte, piezas, textos, taller, releidas=releidas, prestadas=prestadas, sellos=sellos,
            fechas_de_guia=fechas_de_guia,
        )
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 - el revisor no tumba la caja: las fechas quedan como estaban
        logger.warning("el revisor de fechas no pudo terminar la caja; las fechas quedan como estaban", exc_info=True)
    return aparte


def _revisar_cada_pieza(
    aparte: dict,
    piezas: list[dict],
    textos: dict,
    taller,
    *,
    releidas: dict[int, list[str]],
    prestadas: dict[int, int],
    sellos: dict,
    fechas_de_guia: dict,
) -> None:
    """Las propias primero, cada una contra sus hojas; luego las prestadas, detrás de la suya."""
    from datetime import date

    from ...application.revisor_de_fechas import CORREGIDA, anotar_en_el_informe
    from ...domain.fecha_por_estructura import pieza_de
    from ...domain.fechas_extremas import EXTREMOS, fechas_de_un_par
    from ...domain.naming import DOCUMENT_PREFIX
    from .fechas_aseguradas import (
        con_lo_que_leyeron,
        juez_del_trabajo,
        regla_de,
        revisar_y_anotar,
    )

    regla = regla_de(PERFIL, EXTREMOS)
    juez = juez_del_trabajo(taller)
    revisadas: dict[int, object] = {}

    def nombre(pieza: dict) -> str:
        return f"{pieza.get('titulo') or pieza.get('type') or DOCUMENT_PREFIX} (pág. {pieza['pages'][0]})"

    def papel(paginas: list[int]) -> list[str]:
        suyo: list[str] = []
        for pagina in paginas:
            suyo.append(con_lo_que_leyeron(textos.get(pagina, "") or ""))
            suyo.extend(con_lo_que_leyeron(t) for t in releidas.get(pagina, ()))
            if pagina in sellos and sellos[pagina].fecha:
                suyo.append(f"SELLO DE RADICACION: {sellos[pagina].fecha:%d/%m/%Y}")
            if fechas_de_guia.get(pagina):
                suyo.append(f"FECHA MARCADA EN LA GUIA: {fechas_de_guia[pagina]:%d/%m/%Y}")
        return suyo

    def corregir(pieza: dict, revisada) -> None:
        if revisada is not None and revisada.estado == CORREGIDA and revisada.inicial:
            pieza["fecha"] = revisada.inicial.isoformat()
            pieza["fecha_por"] = f"corregida por el revisor de fechas: {revisada.nota}"

    # «Detener» entre una pieza y la siguiente: una caja trae cientos, y cada
    # una puede costar una pregunta a la IA (la revisión adversarial, 2026-11-10).
    control = getattr(taller, "control", None)
    for i, pieza in enumerate(piezas):
        if i in prestadas:
            continue
        if control is not None:
            control.check()
        fecha = pieza.get("fecha")
        fechas = fechas_de_un_par(str(fecha)[:10], str(fecha)[:10]) if fecha else None
        # Su papel sin sus anexos (2026-11-10): la fecha de la cédula, de la
        # factura o del certificado que lleva detrás no es la suya, ni para
        # confirmarla ni para que la IA la «corrija» hacia ella.
        propias = [p for p in pieza["pages"] if not pieza_de(textos.get(p, "") or "").anexo] or pieza["pages"]
        revisada = revisar_y_anotar(
            aparte, nombre(pieza), pieza["pages"][0], fechas, papel(propias), regla=regla, juez=juez,
            una_sola=True,
        )
        revisadas[i] = revisada
        corregir(pieza, revisada)
    for i, de in prestadas.items():
        pieza = piezas[i]
        de_quien = revisadas.get(de)
        if de_quien is None:
            continue
        donde = f"la de su trámite (pág. {piezas[de]['pages'][0]})"
        heredada = _heredada(de_quien, donde, date.fromisoformat(str(pieza["fecha"])[:10]) if pieza.get("fecha") else None)
        anotar_en_el_informe(aparte, nombre(pieza), pieza["pages"][0], heredada)
        corregir(pieza, heredada)


def _heredada(de_quien, donde: str, la_suya):
    """Lo que el revisor decidió de la pieza que prestó la fecha, dicho de la que la tomó."""
    from dataclasses import replace

    return replace(
        de_quien,
        correcciones=tuple(
            replace(c, dice_la_fila=la_suya, prueba=f"{donde}: {c.prueba}") for c in de_quien.correcciones
        ),
        motivos=tuple(f"{donde}: {m}" for m in de_quien.motivos),
    )


def fecha_de_cada_archivo(grupos: list, piezas: list[dict]) -> list:
    """La fecha con que cada archivo va al Índice Electrónico: la del documento con que abre, o la del archivo.

    La misma regla que ``planillas._fecha_de_la_fila``: con ella se ordenan
    los PDF y con ella se ordena el índice, así que salen en el mismo orden.
    """
    from datetime import date

    def iso(valor: object) -> date | None:
        try:
            return date.fromisoformat(str(valor)[:10]) if valor else None
        except ValueError:
            return None

    primeras: dict[int, dict] = {}
    for pieza in piezas:
        primeras.setdefault(pieza.get("archivo"), pieza)
    return [iso((primeras.get(puesto) or {}).get("fecha")) or iso(grupo.fecha) for puesto, grupo in enumerate(grupos)]


def numerar_por_fecha(grupos, anexos: dict, piezas: list[dict]):
    """Los PDF numerados por la fecha de su documento, como el Índice Electrónico (2026-11-11).

    Lo dictó el operador ante «1000690», donde el Excel decía Orden 5 para el
    recurso y su archivo era «06_…»: «como esté en el Excel, también estará
    en el orden de archivos y numeración… esto es sólo Afinia». Antes (el
    2026-11-04) sólo el índice iba por fecha y los PDF guardaban el orden de
    sus hojas.

    Lo antiguo primero, lo que no trae fecha al final y, a igual fecha, el
    orden de las hojas (``orden_cronologico``, la regla del índice). Se
    renumera 01, 02, 03… conservando el RE del código (``_renumerar``), y las
    piezas pasan a decir en qué archivo acabaron. Si algún código no empieza
    por su número no se toca nada: el orden cambiaría sin que el nombre lo dijera.
    """
    from dataclasses import replace

    from ...application.anexos_declarados import _renumerar
    from ...domain.orden_del_indice import orden_cronologico

    if not grupos.groups or not all(re.match(r"^\d+", g.code.value) for g in grupos.groups):
        return grupos, anexos, piezas
    orden = orden_cronologico(fecha_de_cada_archivo(grupos.groups, piezas))
    if orden == list(range(len(orden))):
        return grupos, anexos, piezas
    numerados, anexos = _renumerar([grupos.groups[viejo] for viejo in orden], anexos)
    nuevo_de = {viejo: nuevo for nuevo, viejo in enumerate(orden)}
    piezas = sorted(
        ({**pieza, "archivo": nuevo_de.get(pieza.get("archivo"), pieza.get("archivo"))} for pieza in piezas),
        key=lambda pieza: pieza.get("archivo") if isinstance(pieza.get("archivo"), int) else len(orden),
    )
    return replace(grupos, groups=numerados), anexos, piezas


#: Cuántos documentos hacia atrás se busca la fecha de lo que va delante de una
#: respuesta, saltando los anexos sin fecha (la compraventa de 1016215).
DOCUMENTOS_HACIA_ATRAS = 3


def _sigue_con_lo_de_delante(
    pagina: int, radicado: str | None, grupos, textos: dict, sellos: dict, abren: frozenset[int] | set[int] = frozenset()
) -> bool:
    """Si la respuesta de la empresa que abre en ``pagina`` es de lo que va delante de ella.

    Lo es si lo de delante lleva su RE -- el de su sello o el que cita su
    texto --, o si la fecha más cercana de lo de delante cae en la ventana de
    su trámite (``en_ventana``): el escrito del cliente sin sello sólo toma el
    RE que le cita la respuesta, y es la fecha la que dice que es el suyo. Lo
    de otra fecha es de otro trámite (1016215, 2026-11-11: una carta de 2021 y
    sus anexos delante de una respuesta de 2022 a otra persona).

    Hacia atrás sólo se saltan los anexos sin fecha, lo que no abre nada por sí
    mismo (``abren``: sello o carta). Un escrito que abre y no se deja fechar es
    una duda, y no se salta: en UPD2366126 el recurso de p18-20 lleva sello con
    la fecha ilegible, y saltarlo llevaba a un acta de abril y partía la
    publicación del aviso de su escrito.

    Ante la duda -- nada de delante trae fecha ni RE, o la respuesta no se deja
    fechar -- sigue con lo de delante, como siempre.
    """
    from ...domain.fecha_por_estructura import fecha_por_estructura
    from ...domain.tramites import en_ventana, radicado_de

    delante = [g for g in grupos if g.page_numbers and max(g.page_numbers) < pagina]
    delante.sort(key=lambda g: g.page_numbers[0])
    if not delante:
        return True

    def re_de(pagina_suya: int) -> str | None:
        sello = sellos.get(pagina_suya)
        if sello is not None and sello.radicado:
            return sello.radicado
        return radicado_de(textos.get(pagina_suya, "") or "")

    if radicado and any(re_de(p) == radicado for p in delante[-1].page_numbers):
        return True
    suya = fecha_por_estructura([pagina], textos).fecha
    if suya is None:
        return True
    for grupo in reversed(delante[-DOCUMENTOS_HACIA_ATRAS:]):
        fecha = fecha_por_estructura(list(grupo.page_numbers), textos).fecha
        if fecha is not None:
            return en_ventana(fecha, suya)
        if grupo.page_numbers[0] in abren:
            return True
    return True


def _poner_el_re_en_el_nombre(
    grupos,
    anexos: dict,
    *,
    textos: dict,
    sellos: dict,
    sin_re: set,
    abren: set,
    oficinas: frozenset[str] | set[str] = frozenset(),
    rechazados: list | None = None,
    sellos_sin_re: set[int] | frozenset[int] = frozenset(),
    releidas_del_pqr: dict[int, tuple[str, str]] | None = None,
    evidencias: dict[str, dict] | None = None,
):
    """El RE de cada documento para su nombre, sólo con la evidencia de sus propias hojas.

    Lo decidió el operador el 2026-11-18 («NUNCA INVENTAR INFORMACIÓN»), y lo
    decide ``domain.evidencia.decidir_el_re``:

    - **Lo impreso** -- la etiqueta de radicación, el sello impreso, el PQR de
      la constancia, el RE que cita la notificación o la contestación -- se
      cree si una lectura lo trae tal cual.
    - **La letra a mano** del sello de tinta, si dos lectores distintos la leen
      igual: el OCR de pago y el modelo con visión.
    - **Lo demás es un candidato**: lo que las reglas corrigieron -- la oficina
      a una cifra, una cifra de más, el impreso de la caja --, lo que leyó un
      solo lector y el RE de su trámite que ninguna hoja suya trae. El nombre
      va sin RE y el documento a Revisión con sus candidatos.

    Qué documentos lo llevan no cambia: el reclamo, la constancia, la
    contestación y la notificación (``CON_RE_EN_EL_NOMBRE``) siempre que se
    pruebe; los demás si su sello o su etiqueta lo trae (2026-11-11). Nunca el
    de una copia aportada como prueba ni el de un anexo (``sin_re`` y los
    anexos que no abren), ni el RE que el reclamo sólo cita (2026-11-18).

    ``sellos_sin_re``: las hojas cuyo sello leyó entera la IA y no trae RE; el
    documento que abre con una de ellas no recibe el de su trámite (UPD2460819
    pág. 12, 2026-11-13). ``releidas_del_pqr``: por hoja, la capa original y la
    relectura del «N° PQR» roto, que son su evidencia. ``evidencias`` recibe el
    hallazgo de cada documento, por su primera hoja.

    Devuelve los grupos, los anexos con sus códigos nuevos y, por su primera
    hoja, de dónde salió cada RE.
    """
    from dataclasses import replace

    from ...domain.evidencia import (
        FUENTES_IMPRESAS,
        Estado,
        EvidenciaDeRE,
        candidatos_legibles,
        decidir_el_re,
        familia,
        oficina_confirmada,
        re_impreso_que_casa,
    )
    from ...domain.fechas import fecha_de_la_pagina
    from ...domain.nombre_oficial import es_re, lleva_re_en_el_nombre
    from ...domain.sello import (
        OFICINAS_QUE_RADICAN,
        leer_sello,
        radicados_impresos,
        validar_el_re_a_mano,
    )
    from ...domain.tramites import radicado_de

    impresos_de_la_caja = set().union(*(radicados_impresos(t or "") for t in textos.values())) if textos else set()
    # Para el cruce de la letra a mano (2026-11-20): cada RE impreso de la caja,
    # con las hojas que lo imprimen y su fecha. Sin las copias aportadas como
    # prueba ni el acuerdo, que no son de ningún trámite de la caja.
    impresos_fechados: dict[str, list[tuple[int, object]]] = {}
    for pagina_impresa, texto_impreso in (textos or {}).items():
        if pagina_impresa in sin_re or not (de_la_hoja := radicados_impresos(texto_impreso or "")):
            continue
        fecha_impresa = fecha_de_la_pagina(texto_impreso or "")
        for impreso in de_la_hoja:
            impresos_fechados.setdefault(impreso, []).append((pagina_impresa, fecha_impresa))

    def impresos_fuera_de(paginas: set[int]) -> dict[str, list[tuple[int, object]]]:
        """Los impresos de la caja que traen otras hojas, no las del documento: el escrito cita los RE de otros."""
        fuera = {r: [(p, f) for p, f in hojas if p not in paginas] for r, hojas in impresos_fechados.items()}
        return {r: hojas for r, hojas in fuera.items() if hojas}

    de_anexo = {p for paginas in anexos.values() for p in paginas if p not in abren}
    releidas_del_pqr = releidas_del_pqr or {}
    validas = OFICINAS_QUE_RADICAN | set(oficinas)
    salida = []
    renombrados: dict[str, str] = {}
    hallados: dict[str, str] = {}

    def de_la_capa(pagina: int) -> tuple[tuple[str, str], ...]:
        """Lo que la capa dice de la hoja; con la relectura del PQR roto, la capa original y la relectura."""
        if pagina in releidas_del_pqr:
            original, relectura = releidas_del_pqr[pagina]
            return (("capa", original), ("tesseract", relectura))
        return (("capa", textos.get(pagina, "") or ""),)

    def valido(valor: str, evidencia: EvidenciaDeRE) -> str | None:
        """Por qué el valor no puede ser un RE de verdad, o ``None``: la oficina y, en la letra a mano, el año."""
        if evidencia.fuente in FUENTES_IMPRESAS:
            return None if valor[2:6] in validas else f"la oficina {valor[2:6]} no es ninguna que radique"
        sello = sellos.get(evidencia.pagina)
        # La oficina fuera de la lista, si dos lectores la leen igual, va tal
        # cual (1005122, 2026-11-18).
        creido, motivo = validar_el_re_a_mano(
            valor,
            sello.fecha if sello else None,
            oficinas,
            oficina_confirmada=oficina_confirmada(valor, evidencia.lecturas),
        )
        if creido == valor:
            return None
        if creido is not None:
            # La oficina a una cifra de una que radica: se propone la corregida.
            return f"{motivo}: sería {creido}"
        if valor in impresos_de_la_caja and valor[2:6] in validas:
            # El funcionario erró el año de la fecha del sello y el RE es el
            # que el escrito trae impreso (hoja 52 de UPD2460819): no cambia
            # nada del valor, lo confirma.
            return None
        return motivo or "no se cree"

    for grupo in grupos.groups:
        numero, _, resto = grupo.code.value.partition(" ")
        primera = grupo.page_numbers[0]
        del_tramite = next((pieza.upper() for pieza in resto.split() if es_re(pieza)), None)
        con_re = lleva_re_en_el_nombre(grupo.kind)
        es_reclamo = _plano_del_sello(grupo.kind or "") == "RECLAMO"
        es_constancia = "CONSTANCIA" in _plano_del_sello(grupo.kind or "")
        propias = [
            p for p in (grupo.page_numbers if numero.isdigit() else ()) if p not in sin_re and p not in de_anexo
        ]
        evidencias_del_documento: list[EvidenciaDeRE] = []
        for pagina in propias:
            texto = textos.get(pagina, "") or ""
            if pagina in sellos:
                sello = sellos[pagina]
                evidencias_del_documento.append(
                    EvidenciaDeRE(
                        pagina,
                        "sello impreso" if sello.clase == "impreso" else "sello de tinta",
                        sello.radicado,
                        sello.lecturas,
                        sello.correccion,
                    )
                )
            # La etiqueta de radicación impresa en el texto de la hoja, aunque
            # la lectura del sello no la viera (el operador, 2026-11-18: «ya
            # sea en el sello o en la página»).
            etiqueta = leer_sello(texto)
            if etiqueta is not None and etiqueta.clase == "impreso" and es_re(etiqueta.radicado):
                evidencias_del_documento.append(
                    EvidenciaDeRE(pagina, "etiqueta impresa", etiqueta.radicado, de_la_capa(pagina))
                )
            # El que su texto trae impreso: el PQR de la constancia, el que cita
            # la notificación o la contestación. Nunca el que el reclamo cita:
            # es el de otra reclamación (2026-11-18).
            if con_re and not es_reclamo and pagina not in sellos and es_re(citado := radicado_de(texto)):
                evidencias_del_documento.append(
                    EvidenciaDeRE(
                        pagina,
                        "PQR de la constancia" if es_constancia else "citado en su texto",
                        citado,
                        de_la_capa(pagina),
                    )
                )
        buscado = (
            f"sello y etiqueta de radicación{', PQR o RE citado' if con_re and not es_reclamo else ''}"
            f" en las hojas {', '.join(map(str, propias)) or 'ninguna propia'}"
        )
        hallazgo = decidir_el_re(
            evidencias_del_documento,
            # El del trámite se propone sólo a quien lo lleva por su tipo, y no
            # al documento cuyo sello se leyó entero sin RE.
            del_tramite=del_tramite if con_re and primera not in sellos_sin_re else None,
            valido=valido,
            buscado=buscado,
        )
        if not hallazgo.se_cree:
            # El cruce (el operador, 2026-11-20, 1000690 pág. 3): la letra a mano
            # del sello que los lectores de la IA leen igual de mal --
            # «RE23D20210565», el «10» hecho una «D» y el «7» perdido -- casada
            # con el único RE que su trámite trae impreso. Sólo con lo que
            # leyeron el OCR de pago y la visión: con «Solo OCR», nada.
            cruzadas = []
            for evidencia in evidencias_del_documento:
                if evidencia.fuente != "sello de tinta":
                    continue
                de_la_ia = tuple(
                    (lector, leido)
                    for lector, leido in evidencia.lecturas
                    if familia(lector) in ("ocr de pago", "visión")
                )
                cruce = re_impreso_que_casa(
                    de_la_ia,
                    impresos_fuera_de(set(grupo.page_numbers)),
                    fecha_del_sello=sellos[evidencia.pagina].fecha,
                    valido=lambda valor, evidencia=evidencia: valido(valor, evidencia),
                )
                if cruce is not None:
                    cruzadas.append(
                        replace(
                            evidencia,
                            fuente="sello de tinta cruzado con lo impreso" if cruce.se_cree else evidencia.fuente,
                            propuesto=cruce.valor,
                            cruce=cruce.porque if cruce.se_cree else None,
                            correccion=None if cruce.se_cree else cruce.porque,
                        )
                    )
            if cruzadas:
                hallazgo = decidir_el_re(
                    [*cruzadas, *evidencias_del_documento],
                    del_tramite=del_tramite if con_re and primera not in sellos_sin_re else None,
                    valido=valido,
                    buscado=buscado,
                )
        if evidencias is not None:
            evidencias[str(primera)] = hallazgo.as_dict()
        if hallazgo.se_cree:
            nuevo = f"{numero} {hallazgo.valor}"
            if nuevo != grupo.code.value:
                renombrados[grupo.code.value] = nuevo
            hallados[str(primera)] = (
                f"{hallazgo.valor}: {hallazgo.metodo} de la pág. {hallazgo.pagina}"
                f" ({hallazgo.estado}: {', '.join(hallazgo.lectores)})"
            )
            salida.append(
                replace(grupo, code=type(grupo.code)(value=nuevo, raw=hallazgo.valor), re_en_el_nombre=True)
            )
            continue
        if primera in sellos_sin_re:
            hallados[str(primera)] = "sin RE: su sello trae la fecha y el radicado, y ningún RE"
        elif hallazgo.estado is Estado.REQUIERE_VALIDACION:
            hallados[str(primera)] = f"sin RE en el nombre, por confirmar: {candidatos_legibles(hallazgo)}"
            if rechazados is not None:
                rechazados.append(
                    {
                        "page": primera,
                        "reason": f"{RE_POR_CONFIRMAR}: {candidatos_legibles(hallazgo)}",
                        "candidatos": [c.as_dict() for c in hallazgo.candidatos],
                    }
                )
        if con_re:
            # Sin un RE que se crea, el nombre va sin él: el del trámite que
            # traía su código no se pone (2026-11-18).
            sin_el_re = " ".join([numero, *(p for p in resto.split() if not es_re(p))])
            if sin_el_re != grupo.code.value:
                renombrados[grupo.code.value] = sin_el_re
                grupo = replace(grupo, code=type(grupo.code)(value=sin_el_re, raw=numero))
        salida.append(grupo)
    anexos = {renombrados.get(codigo, codigo): paginas for codigo, paginas in anexos.items()}
    return replace(grupos, groups=salida), anexos, hallados


#: Por qué abre un documento su primera hoja, de la señal más fuerte a la más débil.
MOTIVOS_DEL_CORTE = (
    ("sello", "un sello de radicación abre el documento", "alta"),
    ("guia", "la guía de envío abre el documento", "alta"),
    ("formulario", "un formulario que va solo: constancia, notificación o respuesta", "alta"),
    ("folio", "el folio 1 escrito en la esquina", "alta"),
    ("carta", "una carta que abre su trámite, con su asunto", "alta"),
    ("acuerdo", "el acuerdo de pago con sus piezas", "alta"),
    ("primera", "la primera hoja del PDF de origen", "alta"),
)


def _evidencia_de_las_piezas(
    piezas: list[dict],
    textos: dict,
    releidas: dict,
    *,
    con_ia: bool,
    senales: dict[str, set[int]] | None = None,
) -> dict:
    """La evidencia de la fecha, del tipo y del corte de cada documento, por la primera hoja de su pieza (2026-11-18).

    La fecha, con su hoja, su vía -- capa, sello, OCR, IA -- y el trozo donde
    está escrita: de la capa, o de lo que releyó el agente de fechas. El corte,
    con la señal que abrió el documento en su primera hoja (``senales``: las
    hojas de cada señal); sin ninguna, lo dejó así la continuidad, el trámite o
    el revisor de cortes, con confianza media.
    """
    from ...domain.evidencia import (
        Estado,
        Hallazgo,
        hallazgo_de_la_fecha,
        hallazgo_del_tipo,
    )

    senales = senales or {}

    def texto_de(pagina: int) -> str:
        return "\n".join([textos.get(pagina, "") or "", *(releidas.get(pagina) or [])])

    fecha: dict[str, dict] = {}
    tipo: dict[str, dict] = {}
    corte: dict[str, dict] = {}
    for pieza in piezas:
        if not pieza.get("pages"):
            continue
        primera = min(pieza["pages"])
        clave = str(primera)
        fecha[clave] = hallazgo_de_la_fecha({**pieza, "con_ia": con_ia}, texto_de).as_dict()
        tipo[clave] = hallazgo_del_tipo(pieza, texto_de).as_dict()
        motivo = next(
            ((que, confianza) for senal, que, confianza in MOTIVOS_DEL_CORTE if primera in senales.get(senal, set())),
            ("sin señal propia en su primera hoja: lo separaron la continuidad, el trámite o el revisor de cortes", "media"),
        )
        corte[clave] = Hallazgo(
            parametro="corte",
            estado=Estado.ENCONTRADO,
            valor=f"{primera}-{max(pieza['pages'])}",
            pagina=primera,
            metodo=motivo[0],
            confianza=motivo[1],
        ).as_dict()
    return {"fecha": fecha, "tipo": tipo, "corte": corte}


#: A cuánto lee la IA la hoja de una Habeas Data o de un reconocimiento para saber de quién es.
PPP_DE_LA_PERSONA = 200


class _PersonasDeLasHojas:
    """La persona que firma cada hoja -- su nombre y su cédula --, para casar la Habeas Data con su acuerdo.

    De la capa; si la capa no trae la cédula -- el nombre y el número van a
    mano --, con el OCR de pago si se eligió «OCR + IA». Una lectura por hoja,
    y sólo de las que se preguntan: las Habeas sueltas y los reconocimientos de
    un PDF con varios acuerdos (4100921, 2026-11-18).
    """

    def __init__(self, taller, ruta_pdf, textos: dict) -> None:
        self._taller = taller
        self._ruta = ruta_pdf
        self._textos = textos
        self._leidas: dict[int, object] = {}
        #: Lo que la IA leyó de cada hoja, para su fecha.
        self._de_la_ia: dict[int, str] = {}
        self._fuente = None

    def __call__(self, pagina: int):
        from ...domain.persona_de_la_hoja import Persona, persona_de_la_hoja

        if pagina in self._leidas:
            return self._leidas[pagina]
        persona = persona_de_la_hoja(self._textos.get(pagina, "") or "")
        lector = self._taller.lector_de_pago() if not persona.cedulas else None
        if lector is not None:
            try:
                from ...adapters.pymupdf_source import PyMuPDFPageSource

                if self._fuente is None:
                    self._fuente = PyMuPDFPageSource(self._ruta, self._taller.name)
                self._de_la_ia[pagina] = lector.read(
                    self._fuente.render(pagina, None, PPP_DE_LA_PERSONA, "jpeg")
                ).text
                leida = persona_de_la_hoja(self._de_la_ia[pagina])
                persona = Persona(persona.nombre | leida.nombre, persona.cedulas | leida.cedulas)
            except Exception:  # noqa: BLE001 - sin la IA, la Habeas va con el acuerdo más cercano
                logger.warning("no se pudo leer la persona de la pág. %s", pagina, exc_info=True)
        self._leidas[pagina] = persona
        return persona

    def fecha_de(self, pagina: int):
        """La fecha que la hoja pone en su sitio -- las casillas de la Habeas, el encabezado del reconocimiento --.

        De la capa o de lo que leyó la IA al buscar su persona.
        """
        from ...domain.fecha_por_estructura import fecha_de_la_hoja

        self(pagina)
        for texto in (self._textos.get(pagina, "") or "", self._de_la_ia.get(pagina, "")):
            if texto and (fecha := fecha_de_la_hoja(texto)) is not None:
                return fecha
        return None

    def cerrar(self) -> None:
        if self._fuente is not None:
            self._fuente.close()
            self._fuente = None


#: A cuánto se relee la hoja cuyo campo «N° PQR:» rompió la capa: a 200 y 300
#: Tesseract leyó entero el de 1005652; a 400 lo perdió.
PPP_DEL_PQR = 300


def _con_el_pqr_releido(
    source, textos: dict, releidas: dict[int, tuple[str, str]] | None = None, de_pago=None
) -> dict:
    """Los textos con el RE del campo «N° PQR:» que la capa rompió, releído por Tesseract si coincide en lo que sí leyó.

    Sólo las hojas con el campo roto: una relectura de la hoja entera por
    cada una. Lo que no se repara se queda como estaba, sin RE. En
    ``releidas`` quedan, por hoja reparada, la capa original y la relectura:
    la evidencia del RE (2026-11-18), que el texto reparado ya no muestra.

    Si Tesseract no lo repara y se eligió «OCR + IA», lo intenta el OCR de pago
    (``de_pago``): en el Docker del operador la constancia de 1005652 salió sin
    su RE aunque aquí Tesseract lo leía (2026-11-18).
    """
    from ...adapters.tesseract_ocr import TesseractConfig, TesseractOcr
    from ...domain.tramites import pqr_reparado, pqr_roto

    rotas = {p: roto for p, t in textos.items() if (roto := pqr_roto(t or ""))}
    if not rotas:
        return textos
    salida = dict(textos)
    local = TesseractOcr(TesseractConfig(min_word_confidence=0))
    for pagina, roto in rotas.items():
        try:
            releido = local.read(source.render(pagina, None, PPP_DEL_PQR)).text
        except Exception:  # noqa: BLE001 - sin relectura, la hoja se queda sin su RE
            logger.warning("no se pudo releer el campo PQR de la pág. %s", pagina, exc_info=True)
            continue
        reparado = pqr_reparado(roto, releido)
        if reparado is None and de_pago is not None:
            try:
                releido = de_pago.read(source.render(pagina, None, 200, "jpeg")).text
                reparado = pqr_reparado(roto, releido)
            except Exception:  # noqa: BLE001 - sin la IA, la hoja se queda sin su RE
                logger.warning("la IA no releyó el campo PQR de la pág. %s", pagina, exc_info=True)
        if reparado:
            if releidas is not None:
                releidas[pagina] = (salida[pagina] or "", releido)
            salida[pagina] = (salida[pagina] or "").replace(roto, reparado[2:], 1)
    return salida


def _con_lo_impreso(sellos: dict, al_pie: dict, textos: dict) -> tuple[dict, dict, dict[int, str]]:
    """Los sellos de tinta con su RE a mano corregido por el que la caja trae impreso, y qué se corrigió en cada hoja.

    Sólo el de tinta -- la letra a mano --, y sólo si un único RE impreso en la
    caja está a una cifra de él (``el_impreso_a_una_cifra``). Y si su oficina
    no es una que radique, la que el agente le daría con las oficinas de la
    caja -- las de su texto y las de sus etiquetas impresas --: «RE9238…» en
    una caja de la 9233 es RE9233… (1005117, UPD2437857 p5, 2026-11-18). Antes
    de armar los trámites: armados con la lectura cruda, el RE de su trámite
    volvía a ser el «9238» y se ponía en el nombre.
    """
    from dataclasses import replace

    from ...domain.sello import (
        OFICINAS_QUE_RADICAN,
        el_impreso_a_una_cifra,
        radicados_impresos,
        validar_el_re_a_mano,
    )

    impresos = set().union(*(radicados_impresos(t or "") for t in textos.values())) if textos else set()
    oficinas_de_la_caja = {r[2:6] for r in impresos} | {
        s.radicado[2:6] for s in (*sellos.values(), *al_pie.values()) if s.clase == "impreso" and s.radicado
    }
    corregidos: dict[int, str] = {}

    def corregir(cuales: dict) -> dict:
        salida = dict(cuales)
        for pagina, sello in cuales.items():
            if sello.clase != "tinta" or not sello.radicado:
                continue
            impreso = el_impreso_a_una_cifra(sello.radicado, impresos)
            if impreso:
                corregidos[pagina] = f"el sello se leyó {sello.radicado}; la caja trae impreso {impreso}"
                salida[pagina] = replace(
                    sello, radicado=impreso, correccion=f"a una cifra del RE {impreso} impreso en la caja"
                )
            elif sello.radicado.upper()[2:6] not in OFICINAS_QUE_RADICAN | oficinas_de_la_caja:
                valido, motivo = validar_el_re_a_mano(sello.radicado, sello.fecha, oficinas_de_la_caja)
                if valido and valido != sello.radicado.upper():
                    corregidos[pagina] = f"el sello se leyó {sello.radicado}; {motivo}"
                    salida[pagina] = replace(sello, radicado=valido, correccion=motivo)
                elif valido is None:
                    # Lo que el agente no cree no arma el trámite: con la lectura
                    # cruda el reclamo de 1005117 salía «RE2022202203579», de una
                    # oficina «2022» que no existe, puesto por su trámite aunque
                    # el nombre lo hubiera rechazado (2026-11-18). Va sin RE y a
                    # Revisión, como el sello que no se leyó.
                    corregidos[pagina] = f"el sello se leyó {sello.radicado}; no se cree: {motivo}"
                    salida[pagina] = replace(sello, radicado=None)
        return salida

    return corregir(sellos), corregir(al_pie), corregidos


#: Cuántas cabeceras -- de sellos sin RE y de cartas sin sello visto -- se le
#: enseñan a la IA como mucho por caja: una página pagada cada una. Con los
#: sellos sin RE pasó de 30 a 40 (UPD2460819 trae 42 cartas; 2026-11-13).
CARTAS_SIN_SELLO_POR_CAJA = 40
#: La cabecera de la carta, donde la ventanilla estampa el sello de tinta.
BANDA_DE_LA_CABECERA = (0.25, 0.0, 1.0, 0.22)
#: Dónde mira el modelo con visión el sello que el OCR dejó como imagen: la
#: mitad derecha y más abajo que la cabecera, porque el sello de tinta de
#: Afinia baja hasta el tercio de la hoja y la cabecera lo cortaba en su RE
#: (1005117, UPD2973878 pág. 6, 2026-11-18).
BANDA_DEL_SELLO_A_LA_VISTA = (0.4, 0.0, 1.0, 0.4)
#: Lo que acompaña a la imagen del sello: el pedido entero va en las instrucciones.
PEDIDO_DEL_SELLO = "El sello de radicación de esta carta, con su RE."
#: Y a la imagen girada: el RE escrito de lado, en el borde del sello.
PEDIDO_DEL_SELLO_GIRADO = "El sello de radicación de esta carta, girado: su RE puede ir escrito de lado."


def _girada(imagen: bytes) -> bytes | None:
    """La imagen girada un cuarto de vuelta a la derecha: el RE escrito de abajo arriba en el borde del sello queda derecho.

    En el reclamo de 1005117 (UPD2437857 pág. 2, 2026-11-18) el RE va escrito
    de lado, junto al recuadro, y derecho la IA sólo leía «…2203577».
    """
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(imagen)) as original:
            salida = io.BytesIO()
            original.rotate(-90, expand=True).convert("RGB").save(salida, format="JPEG", quality=90)
            return salida.getvalue()
    except Exception:  # noqa: BLE001 - sin girar, se queda con lo que vio derecho
        logger.debug("no se pudo girar la imagen del sello", exc_info=True)
        return None


def _plano_del_sello(texto: str) -> str:
    """La lectura del sello en mayúsculas y sin tildes: «RADICACIÓN» es RADICACION."""
    import unicodedata

    return unicodedata.normalize("NFD", (texto or "").upper()).encode("ascii", "ignore").decode()


#: Cuántas hojas se miran detrás del sello que no dice sus folios, para casar su RE ilegible.
HOJAS_SIN_FOLIOS = 3
#: El número de radicación de doce cifras del sello de tinta, sin «RE», en su
#: propio renglón: «No DE RADICACION: 202160036696». En otra casilla no vale:
#: con los campos corridos (UPD2460819 pág. 255, «No DE FOLIOS: 2021600 95
#: 115») el RE a mano se perdió en la lectura, no falta en el sello.
_RADICACION_SIN_RE = re.compile(r"RADI\w{0,6}N\W{0,4}((?:\d[ \t]?){12})(?![\d])")


def _sellos_de_las_cartas(
    taller, source, textos: dict, sellos: dict, conocidos: set, leidos: dict[int, str] | None = None
) -> tuple[dict, set[int]]:
    """L2c: el sello de tinta de cada carta que abre y no lo mostró a Tesseract, o sin el RE a mano, leído por la IA.

    Sólo con «OCR + IA» (con «Solo OCR», nada). De lo que transcribe la IA de
    la cabecera: si es un sello de tinta, su fecha, su RE a mano -- con una
    cifra de más si hace falta -- y sus folios. Devuelve también las hojas
    cuyo sello se leyó entero y no trae RE: se radicaron sin él. En ``leidos``
    deja, por hoja, lo que se leyó del RE que no se creyó, para el aviso.
    """
    from ...application.ports import Band
    from ...domain.carta import abre_carta
    from ...domain.sello import (
        FOLIOS_DE_UN_ESCRITO,
        Sello,
        el_conocido_por_la_lectura,
        fecha_del_sello_de_tinta,
        folios_del_sello_de_tinta,
        leer_sello,
        lo_que_se_leyo_del_re,
        radicado_con_una_cifra_de_mas,
        radicado_del_texto,
        radicado_escrito,
        radicados_impresos,
        re_del_sello,
        sello_sin_transcribir,
        trae_un_re_a_mano,
    )

    lector = taller.lector_de_pago()
    if lector is None:
        return {}, set(), set()
    transcriptor = taller.transcriptor_de_sellos()
    mirados: set[int] = set()
    #: Lo que vio el modelo con visión en cada hoja: el segundo lector del RE a mano.
    vistas: dict[int, str] = {}

    def a_la_vista(pagina: int) -> str:
        """Lo que el modelo con visión lee del sello de la hoja: derecho y, si no da un RE, girado.

        Una vez por hoja. Lo que diga se lee y se valida como cualquier RE a
        mano; a la carta sin sello le dice «sin sello».
        """
        if transcriptor is None or pagina in mirados:
            return ""
        mirados.add(pagina)
        try:
            imagen = source.render(pagina, Band(*BANDA_DEL_SELLO_A_LA_VISTA), 200, "jpeg")
            # Sólo la imagen, con una frase: con lo que el OCR leyó de la
            # cabecera delante, el modelo contestaba «sin sello».
            visto = transcriptor.resumir(PEDIDO_DEL_SELLO, imagen=imagen) or ""
            if radicado_del_texto(visto) or radicado_escrito(visto) or "SIN SELLO" in visto.upper():
                vistas[pagina] = visto
                return visto
            girada = _girada(imagen)
            if girada is not None:
                visto = f"{visto}\n{transcriptor.resumir(PEDIDO_DEL_SELLO_GIRADO, imagen=girada) or ''}"
            vistas[pagina] = visto
            return visto
        except Exception:  # noqa: BLE001 - sin él, el sello queda como lo dejó el OCR
            logger.warning("no se pudo transcribir el sello de la pág. %s", pagina, exc_info=True)
            return ""

    # También la carta cuyo sello de tinta vio Tesseract sin poder leer su RE
    # a mano: en 7975593 (UPD2460819, 2026-11-13) siete escritos con su sello
    # salían sin RE -- …04663, …03442, …05402, …05408, …06812 -- y uno con el
    # que citaba su texto.
    sin_su_re = {
        p for p, s in sellos.items() if s.clase == "tinta" and re_del_sello(s)[0] is None
    }
    # Primero las hojas con su sello visto y sin RE -- aunque la capa rota no
    # deje ver la carta: la 255 de UPD2460819 --, después las cartas sin sello.
    cartas = sorted(p for p in sin_su_re if p in textos) + [
        p for p, t in sorted(textos.items()) if p not in sellos and abre_carta(t or "")
    ]
    hallados: dict = {}
    sin_re_en_el_sello: set[int] = set()
    vistos_sin_su_re: set[int] = set()
    for pagina in cartas[:CARTAS_SIN_SELLO_POR_CAJA]:
        taller.control.check()
        try:
            leido = lector.read(source.render(pagina, Band(*BANDA_DE_LA_CABECERA), 300)).text or ""
        except Exception:  # noqa: BLE001 - sin la lectura, la carta abre como carta
            logger.warning("no se pudo leer la cabecera de la pág. %s", pagina, exc_info=True)
            continue
        if sello_sin_transcribir(leido):
            # El OCR no transcribió ningún sello -- lo dejó como imagen o lo
            # omitió --: el modelo con visión mira la esquina del sello (1005117,
            # UPD2973878 pág. 6, 2026-11-18).
            leido = f"{leido}\n{a_la_vista(pagina)}"
        sello = leer_sello(leido)
        # Con «CARIBEMAR DE LA COSTA» y «Folios» el lector lo toma por la
        # etiqueta impresa; con su «FECHA DE RECIBIDO» o sus folios a mano es
        # el de tinta (UPD3126960 pág. 9).
        folios = folios_del_sello_de_tinta(leido)
        fecha = fecha_del_sello_de_tinta(leido)
        ya_visto = sellos.get(pagina)
        if sello is None and ya_visto is None and (folios or fecha) and not (
            radicado_del_texto(leido) or radicado_escrito(leido, fecha.year if fecha else None)
        ):
            # Un sello que el lector no reconoce -- su «FECHA DE RECIBIDO», sus
            # folios -- y sin RE legible: no abre nada, pero su RE va a
            # Revisión (UPD2460819 pág. 176, «KEP310202105408»).
            vistos_sin_su_re.add(pagina)
        if (sello is None or (sello.clase != "tinta" and folios is None and fecha is None)) and ya_visto is None:
            continue
        fecha = fecha or (sello.fecha if sello else None) or (ya_visto.fecha if ya_visto else None)
        #: Lo que leyó el OCR de pago, tal cual: la evidencia del RE.
        del_ocr = leido
        correccion = None
        radicado = radicado_del_texto(leido)
        if radicado is None:
            radicado = radicado_con_una_cifra_de_mas(
                leido, conocidos, fecha.year if fecha else None
            ) or radicado_escrito(leido, fecha.year if fecha else None)
            if radicado:
                correccion = "la letra a mano rehecha: una cifra de más o de menos, o letras por cifras"
        if radicado is not None and pagina not in vistas:
            # El segundo lector de la letra a mano: el RE se cree sólo si el
            # modelo con visión lee el mismo (el operador, 2026-11-18).
            a_la_vista(pagina)
        if radicado is None and (visto := a_la_vista(pagina)):
            # El sello está pero su RE no se leyó: el modelo con visión lo mira,
            # derecho y girado -- el RE escrito de lado en el borde del sello,
            # 1005117, UPD2437857 pág. 2, 2026-11-18 --.
            leido = f"{leido}\n{visto}"
            fecha = fecha or fecha_del_sello_de_tinta(visto)
            folios = folios or folios_del_sello_de_tinta(visto)
            radicado = radicado_del_texto(visto)
            if radicado is None:
                radicado = radicado_con_una_cifra_de_mas(
                    visto, conocidos, fecha.year if fecha else None
                ) or radicado_escrito(visto, fecha.year if fecha else None)
                if radicado:
                    correccion = "la letra a mano rehecha: una cifra de más o de menos, o letras por cifras"
        if radicado is None:
            # La letra a mano ilegible -- «REB3102021034V2» --, casada con el RE
            # que el escrito imprime en las hojas que cubren los folios de su
            # sello (UPD2460819 págs. 52 y 95, 2026-11-13). Desde el 2026-11-18
            # es sólo un candidato: lo confirma el operador.
            hojas = min(folios or (ya_visto.folios if ya_visto else None) or HOJAS_SIN_FOLIOS, FOLIOS_DE_UN_ESCRITO)
            suyos = set().union(*(radicados_impresos(textos.get(q, "") or "") for q in range(pagina, pagina + hojas)))
            radicado = el_conocido_por_la_lectura(leido, suyos)
            if radicado:
                correccion = "la letra ilegible casada con un RE impreso en sus hojas"
        if (
            radicado is None
            and (fecha or ya_visto)
            and _RADICACION_SIN_RE.search(_plano_del_sello(leido))
            # Ni un RE a mano ilegible en otra casilla: «KEP310202105408» en la
            # del funcionario (hoja 176) dice que el sello sí lo trae.
            and not trae_un_re_a_mano(leido)
        ):
            # El sello leído entero -- su fecha y su radicado de doce cifras --
            # sin RE: el escrito se radicó sin él (UPD2460819 pág. 12, «20216003
            # 6696»), y no se le pone el de su trámite.
            sin_re_en_el_sello.add(pagina)
        if radicado is None and leidos is not None and (crudo := lo_que_se_leyo_del_re(leido)):
            leidos[pagina] = crudo
        lecturas = tuple(
            (lector, texto)
            for lector, texto in (("ocr de pago", del_ocr), ("visión", vistas.get(pagina, "")))
            if texto
        )
        if ya_visto is not None:
            # El sello que ya vio Tesseract se queda con lo suyo; la IA le pone
            # el RE a mano que él no leyó, y lo que le faltara.
            if radicado:
                hallados[pagina] = Sello(
                    ya_visto.clase,
                    radicado,
                    ya_visto.fecha or fecha,
                    ya_visto.folios or folios,
                    lecturas=(*ya_visto.lecturas, *lecturas),
                    correccion=correccion,
                    zona=ya_visto.zona or BANDA_DE_LA_CABECERA,
                )
            elif lecturas:
                # Sin RE, lo que se leyó también es evidencia: de ahí salen sus
                # candidatos (4100974: la visión leyó «RE2020…», a una cifra de
                # la oficina 2320, y sin esto no se proponía nada).
                from dataclasses import replace as _con

                hallados[pagina] = _con(ya_visto, lecturas=(*ya_visto.lecturas, *lecturas))
            continue
        hallados[pagina] = Sello(
            "tinta",
            radicado,
            fecha,
            folios or sello.folios,
            lecturas=lecturas,
            correccion=correccion,
            # Donde lo leyó la IA: la cabecera. Ahí se relee, abierta, si su RE
            # no se cree (L2d).
            zona=BANDA_DE_LA_CABECERA,
        )
    return hallados, sin_re_en_el_sello, vistos_sin_su_re - sin_re_en_el_sello


#: Cuánto se parecen dos formularios para que el segundo sea copia del primero.
PARECIDO_DE_UNA_COPIA = 0.85
#: Cuánto de cada formulario se compara, desde su título.
LARGO_DE_LA_FIRMA = 220


def _copias_de_formularios(formularios: dict, textos: dict) -> list[int]:
    """Los formularios que repiten uno anterior del mismo tipo: la copia que un escrito trae anexa.

    Se comparan desde el título, sin espacios ni signos, porque la OCR de la
    cabecera cambia de una copia a otra («S.fi Grupo-epnQ», «Grupo-epn^»).
    Sólo las notificaciones personales: las constancias, los pagarés y la
    Habeas Data son formatos impresos que se parecen sin ser copias -- la
    constancia de la 272 y la de la 297 son de dos radicados --.
    """
    from difflib import SequenceMatcher

    from ...domain.asunto_del_documento import NOTIFICACION_PERSONAL
    from ...domain.revision_de_cortes import plano

    def firma(pagina: int) -> str:
        limpio = re.sub(r"[^A-Z0-9]", "", plano(textos.get(pagina, "") or ""))
        inicio = limpio.find("NOTIFICACION")
        return limpio[max(inicio, 0) :][:LARGO_DE_LA_FIRMA]

    copias = []
    vistas: list[tuple[str, str]] = []
    for pagina in sorted(formularios):
        tipo = formularios[pagina][0]
        if tipo != NOTIFICACION_PERSONAL:
            continue
        suya = firma(pagina)
        if len(suya) >= 40 and any(
            t == tipo and SequenceMatcher(None, f, suya).ratio() >= PARECIDO_DE_UNA_COPIA for t, f in vistas
        ):
            copias.append(pagina)
            continue
        vistas.append((tipo, suya))
    return copias


#: Cuántas esquinas van en cada página pagada.
FOLIOS_POR_MOSAICO = 10
#: Cuántos mosaicos se leen a la vez.
MOSAICOS_A_LA_VEZ = 4


def _leer_los_folios(payload: dict, taller, source, page_count: int) -> dict[int, int]:
    """L4: el folio a mano de la esquina de cada hoja, leído por la IA en mosaicos etiquetados.

    Sin la IA, ninguno. Un mosaico que falla deja sus hojas sin folio: el
    corte de esas hojas queda como lo decidan las demás reglas.
    """
    from concurrent.futures import ThreadPoolExecutor

    from ...application.ports import Band
    from ...domain.foliacion_del_escrito import BANDA_DEL_FOLIO_DE_LA_CAJA

    lector = taller.lector_de_folios()
    franjas = getattr(lector, "armar_mosaico_de_franjas", None)
    leer = getattr(lector, "leer_mosaico_etiquetado", None)
    if franjas is None or leer is None:
        return {}
    banda = Band(*BANDA_DEL_FOLIO_DE_LA_CAJA)

    def armar(fuente, tanda):
        # Sólo el número, con su hoja al lado: sin el logo ni la caja del NIC.
        return franjas(fuente, [(pagina, banda) for pagina in tanda])
    tandas = [
        list(range(desde, min(desde + FOLIOS_POR_MOSAICO, page_count + 1)))
        for desde in range(1, page_count + 1, FOLIOS_POR_MOSAICO)
    ]
    folios: dict[int, int] = {}
    with ThreadPoolExecutor(max_workers=MOSAICOS_A_LA_VEZ) as hilos:
        vuelo = []
        for tanda in tandas:
            taller.control.check()
            # El mosaico se arma en este hilo: MuPDF no admite más de uno.
            imagen = armar(source, tanda)
            if imagen:
                vuelo.append(hilos.submit(leer, imagen, tanda))
        for hechas, futuro in enumerate(vuelo, start=1):
            try:
                folios.update(futuro.result())
            except Exception:  # noqa: BLE001 - esas hojas se quedan sin folio
                logger.warning("no se pudo leer un mosaico de folios en %s", taller.name, exc_info=True)
            _anunciar(
                payload,
                Stage.GROUPING,
                detail="leyendo el folio a mano de cada hoja",
                done=hechas,
                total=len(vuelo),
            )
    return folios


def _ordenar_los_acuerdos(grupos, piezas: list[dict], textos: dict, del_acuerdo: set[int], *, por_mes: bool = False):
    """El orden en el PDF de cada acuerdo de pago (``orden_del_acuerdo``), por la fecha de su reconocimiento.

    El reconocimiento está fechado si la pieza del acuerdo lleva fecha y salió
    de sus hojas -- no de un pagaré ni de un anexo --. ``piezas`` ya dice en qué
    archivo acabó cada una (``numerar_por_fecha``).

    Con ``por_mes`` el archivo es un mes con documentos de toda clase: sólo se
    ordena el tramo del acuerdo -- de su primera hoja a la última --, en su
    sitio; lo demás del mes no se mueve. Antes el mes entero se ordenaba como
    si fuera el acuerdo, y sus otros documentos acababan detrás como
    «anexos» (2026-11-18).
    """
    from dataclasses import replace
    from datetime import date

    from ...application.anexos_declarados import (
        RECONOCIMIENTO,
        orden_del_acuerdo,
        partes_del_acuerdo,
    )

    salida = []
    for indice, grupo in enumerate(grupos.groups):
        paginas = list(grupo.page_numbers)
        antes: list[int] = []
        despues: list[int] = []
        if por_mes:
            suyas = [i for i, p in enumerate(paginas) if p in del_acuerdo]
            if suyas:
                antes, despues = paginas[: suyas[0]], paginas[suyas[-1] + 1 :]
                paginas = paginas[suyas[0] : suyas[-1] + 1]
        reconocimiento = (
            {p for parte, hojas in partes_del_acuerdo(paginas, textos) if parte == RECONOCIMIENTO for p in hojas}
            if set(paginas) & del_acuerdo
            else set()
        )
        if not reconocimiento:
            salida.append(grupo)
            continue
        del_archivo = [
            pieza
            for pieza in piezas
            if pieza.get("archivo") == indice and set(pieza.get("pages") or ()) & reconocimiento
        ]
        fechado = any(
            pieza.get("fecha")
            and (pieza.get("fecha_pagina") is None or pieza.get("fecha_pagina") in reconocimiento)
            for pieza in del_archivo
        )
        # La fecha de cada reconocimiento, por su primera hoja: con dos, el más
        # reciente va primero (2026-11-20). La del acuerdo -- que pudo corregir
        # el revisor de fechas -- es la del reconocimiento de su hoja.
        fechas: dict[int, date] = {}
        for pieza in del_archivo:
            for primera, valor in pieza.get("fechas_del_reconocimiento") or ():
                fechas[int(primera)] = date.fromisoformat(valor)
            pagina = pieza.get("fecha_pagina")
            if pieza.get("fecha") and pagina in reconocimiento:
                for hojas in pieza.get("reconocimientos") or ():
                    if pagina in hojas:
                        fechas[hojas[0]] = date.fromisoformat(str(pieza["fecha"])[:10])
        orden = [
            *antes,
            *orden_del_acuerdo(paginas, textos, reconocimiento_fechado=fechado, fechas_del_reconocimiento=fechas),
            *despues,
        ]
        salida.append(replace(grupo, orden=None if list(orden) == sorted(grupo.page_numbers) else orden))
    return replace(grupos, groups=salida)


def marcas_de_las_hojas(folios: dict[int, int], sellos: dict, al_pie: dict) -> dict[int, str]:
    """Lo que cada hoja trae fuera de su texto, dicho para la IA: «folio a mano 12; sello de radicación RE… del 08/06/2021, 10 folios».

    Con esto razonan el revisor de cortes y la auditoría (2026-11-12: «que el
    bot y los agentes tengan la capacidad de razonar»).
    """
    marcas: dict[int, str] = {}
    for pagina in sorted(set(folios) | set(sellos) | set(al_pie)):
        partes = []
        if pagina in folios:
            partes.append(f"folio a mano {folios[pagina]}")
        sello = sellos.get(pagina) or al_pie.get(pagina)
        if sello is not None:
            partes.append(
                "sello de radicación"
                + (" al pie" if pagina not in sellos else "")
                + (f" {sello.radicado}" if sello.radicado else "")
                + (f" del {sello.fecha:%d/%m/%Y}" if sello.fecha else "")
                + (f", {sello.folios} folios" if sello.folios else "")
            )
        marcas[pagina] = "; ".join(partes)
    return marcas


def _res_de_los_sellos(sellos: dict, al_pie: dict, oficinas: set[str]) -> dict[int, str]:
    """Por hoja, el RE de su sello que se cree -- arriba o al pie --, como lo cree el nombre (``re_del_sello``)."""
    from ...domain.sello import re_del_sello

    return {
        pagina: radicado
        for pagina, sello in {**al_pie, **sellos}.items()
        if (radicado := re_del_sello(sello, oficinas)[0])
    }


#: Lo que el agente no pudo decidir de un PDF con varios sellos: va a Revisión.
VARIOS_SELLOS_EN_REVISION = "en revisión"
VARIOS_SELLOS_CONFIRMADO = "confirmado por la IA: es un documento"


def pdf_con_varios_sellos(
    salidas: Sequence[tuple[str, Sequence[int]]],
    res: dict[int, str],
    *,
    explicados: dict[int, str],
    al_pie: frozenset[int] | set[int],
    revision=None,
) -> list[dict]:
    """Los PDF entregados con dos o más sellos de RE distinto, con lo que hizo el agente de cada uno.

    Lo pidió el operador el 2026-11-12: «cuando me dividas un PDF y tenga más
    de 2 sellos, me avises», contando cada RE una vez y desde dos. ``salidas``
    son, por PDF, su nombre y sus hojas; ``res``, el RE que se cree de cada
    sello; ``explicados``, la hoja cuyo sello explica una regla y por qué;
    ``revision``, lo que dejó el revisor de cortes (``None`` si no corrió). El
    estado de cada uno:

    - el de la regla, si todo sello de más lo explica una (``explicados``);
    - «confirmado por la IA: es un documento», si la IA vio cada costura que
      los sellos ponían en duda y le dio la razón al corte;
    - «en revisión», si no: sin IA, sin respuesta o sin revisor.

    El PDF que el agente partió ya no trae los dos RE, y no sale aquí: lo dice
    ``revision_de_cortes.movimientos``.
    """
    from ...domain.revision_de_cortes import costuras_de_los_sellos
    from ...domain.sello import SELLOS_PARA_AVISAR, res_del_documento

    fuera = {int(c["der"]): str(c["resultado"]) for c in (revision.fuera if revision is not None else ())}
    sin_explicar = {p: r for p, r in res.items() if p not in explicados}
    avisos = []
    for nombre, paginas in salidas:
        hallados = res_del_documento(paginas, res)
        if len(hallados) < SELLOS_PARA_AVISAR:
            continue
        reglas = sorted({explicados[p] for p, _ in hallados[1:] if p in explicados})
        dudosas = costuras_de_los_sellos([paginas], sin_explicar, al_pie)
        if not dudosas and reglas:
            estado = reglas[0]
        elif dudosas and all(fuera.get(p) == "confirmada" for p in dudosas):
            estado = VARIOS_SELLOS_CONFIRMADO
        else:
            estado = VARIOS_SELLOS_EN_REVISION
        avisos.append(
            {
                "archivo": nombre,
                "paginas": list(paginas),
                "sellos": [{"pagina": p, "re": r, "al_pie": p in al_pie} for p, r in hallados],
                "estado": estado,
                "motivo": "; ".join([*dict.fromkeys(dudosas.values()), *reglas]),
            }
        )
    return avisos


def aviso_de_varios_sellos(varios: Sequence[dict]) -> str | None:
    """El resumen para los avisos y el Excel de procesos: «2 PDF con 2 o más sellos: 03_X.pdf (RE…, RE…; en revisión)»."""
    if not varios:
        return None
    cada = ", ".join(
        f"{Path(str(v['archivo'])).name} ({', '.join(s['re'] for s in v['sellos'])}; {v['estado']})" for v in varios
    )
    return f"{len(varios)} PDF con 2 o más sellos: {cada}"


def _revisar_los_cortes(
    grupos,
    anexos: dict,
    *,
    textos: dict,
    taller,
    pdf,
    abren: set,
    delanteras: set,
    del_acuerdo: set,
    fijas: set,
    cortados: list,
    sellos: dict[int, str] | None = None,
    al_pie: frozenset[int] = frozenset(),
    folios: dict[int, int] | None = None,
    marcas: dict[int, str] | None = None,
):
    """F5e: el revisor de cortes sobre los documentos de la caja.

    Devuelve la revisión y los documentos del corte con lo que se movió, que
    son los que el índice describe. ``del_acuerdo`` se corrige en su sitio: una
    hoja que sale del acuerdo deja de nombrarse y fecharse como él.
    ``sellos`` es, por hoja, el RE de su sello que se cree, sin las hojas cuyo
    sello explica una regla: dos distintos en un documento los revisa el agente
    (2026-11-12).
    """
    from dataclasses import replace

    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...application.anexos_declarados import SOPORTES
    from ...application.perfiles_de_revision import perfil_de
    from ...application.ports import Band
    from ...application.revisor_de_cortes import revisar_los_cortes
    from ...domain.anexos_declarados import HOJA_MUDA, clase_de_la_hoja
    from ...domain.asunto_del_documento import (
        LEY_HABEAS_DATA,
        PIEZAS_DEL_ACUERDO,
        titulo_del_documento,
    )

    # La cabeza de un documento al que la caja le puso delante su Habeas Data
    # ya no abre: la regla la dejó dentro a propósito.
    tras_la_habeas = {
        min(p for p in g.page_numbers if p not in delanteras)
        for g in grupos.groups
        if set(g.page_numbers) & delanteras and any(p not in delanteras for p in g.page_numbers)
    }
    # Lo que por regla cruza: las piezas del acuerdo y su Habeas Data, por su
    # propio título -- no por estar en el acuerdo: estar ahí por un título mal
    # puesto es justo el error que hay que ver --.
    cruces = {
        p
        for p in del_acuerdo
        if titulo_del_documento(textos.get(p, "") or "") in (*PIEZAS_DEL_ACUERDO, LEY_HABEAS_DATA)
    }

    def clase(texto: str) -> str | None:
        hallada = clase_de_la_hoja(texto)
        return hallada if hallada in SOPORTES or hallada == HOJA_MUDA else None

    lector_de_pago = taller.lector_de_pago()
    fuente: list = []

    def releer(pagina: int) -> str | None:
        # La hoja que la IA tiene que juzgar y que Tesseract dejó muda: una
        # página con el OCR de pago, sólo ésa, y sólo si se eligió.
        if lector_de_pago is None:
            return None
        try:
            if not fuente:
                fuente.append(PyMuPDFPageSource(pdf, taller.name))
            return lector_de_pago.read(fuente[0].render(pagina, Band(), 200)).text
        except Exception:  # noqa: BLE001 - sin relectura, la IA ve lo que había
            return None

    try:
        revision = revisar_los_cortes(
            grupos,
            textos,
            # Los patrones de la caja, del registro central de perfiles, con
            # lo que sólo sabe esta ruta: qué abre por regla, qué cruza y qué
            # no se mueve.
            perfil_de(PERFIL).patrones(
                textos,
                abren=frozenset(abren - tras_la_habeas),
                cruces=frozenset(cruces | delanteras),
                fijas=frozenset(fijas),
                clase=clase,
                sellos=dict(sellos or {}),
                al_pie=frozenset(al_pie),
                # El folio a mano y lo que cada hoja trae fuera de su texto:
                # con ellos razona la IA (2026-11-12).
                folios=dict(folios or {}),
                marcas=dict(marcas or {}),
            ),
            juez=taller.juez_de_costuras(),
            anexos=anexos,
            releer=releer,
        )
    finally:
        for abierta in fuente:
            abierta.close()

    for movimiento in revision.movimientos:
        movidas = set(movimiento.paginas)
        # Los documentos del corte, con el bloque en el suyo nuevo: de ellos
        # salen el título y la fecha de cada fila del índice.
        cortados = [
            replace(c, page_numbers=[p for p in c.page_numbers if p not in movidas])
            for c in cortados
            if [p for p in c.page_numbers if p not in movidas]
        ]
        if movimiento.hacia:
            ancla = movimiento.hacia[0]
            cortados = [
                replace(c, page_numbers=sorted([*c.page_numbers, *movidas])) if ancla in c.page_numbers else c
                for c in cortados
            ]
        else:
            from ...domain.grouping import PageGroup

            base = cortados[0]
            cortados = sorted(
                [*cortados, PageGroup(code=base.code, page_numbers=sorted(movidas))],
                key=lambda c: c.page_numbers[0],
            )
    return revision, cortados


def revisados_del_acuerdo(del_acuerdo: set, revision) -> set:
    """Las hojas del acuerdo de pago después de lo que movió el revisor.

    La que sale del acuerdo deja de nombrarse y fecharse como él; la que entra
    en él, se nombra como él.
    """
    resultado = set(del_acuerdo)
    for movimiento in revision.movimientos:
        movidas = set(movimiento.paginas)
        resultado -= movidas
        if movimiento.hacia and set(movimiento.hacia) & set(del_acuerdo):
            resultado |= movidas
    return resultado


def _segment_job(payload: dict, task, *, avisos: Sequence[str] = ()) -> dict:
    """Un PDF por unidad documental, cortando costura por costura.

    ``avisos`` son las advertencias que el despachador ya reunió sobre la ruta
    elegida -- que el papel dice ser un legajo de resoluciones, por ejemplo --
    y que van al informe además de al progreso.

    El PDF unido de un origen que es una carpeta se borra al terminar, salga
    bien o mal: se dejaba en el temporal del sistema, uno por trabajo.
    """
    import contextlib

    temporales: list[Path] = []
    try:
        return _segmentar(payload, task, avisos=avisos, temporales=temporales)
    finally:
        for ruta in temporales:
            with contextlib.suppress(OSError):
                ruta.unlink(missing_ok=True)


def _segmentar(payload: dict, task, *, avisos: Sequence[str] = (), temporales: list[Path]) -> dict:
    from dataclasses import replace

    from ...adapters.casillas_de_la_guia import fecha_de_la_guia
    from ...adapters.huellas_pdf import huellas_de
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
        constancias_solas,
        nombrar_sin_soporte,
        reconocimientos_del_acuerdo,
        retener_anexos,
        unir_el_acuerdo_de_pago,
        unir_soportes,
        verificar_en_el_documento,
    )
    from ...application.cartas import Cartas
    from ...application.entrega import Destino, entregar
    from ...application.foliacion import aplicar_la_foliacion
    from ...application.segment_document import SegmentDocument
    from ...application.segment_split import group_by_segment
    from ...application.sellos import (
        ajustar_por_cartas,
        cortar_por_sellos,
        dividir_por_tramite,
        hojas_que_pueden_llevar_sello,
        la_ultima_hoja_sola,
        leer_sellos,
        releer_la_zona_del_sello,
        retener_los_folios,
        sellos_al_pie,
        separar_las_actas,
        separar_los_formularios,
        unir_lo_que_no_abre,
    )
    from ...domain.carta import abre_carta, asunto_de_la_carta
    from ...domain.fingerprint import nic_de_la_caja
    from ...domain.foliacion_del_escrito import foliacion_del_escrito
    from ...domain.naming import DOCUMENT_PREFIX, document_folder
    from ...domain.nombre_oficial import (
        CON_RE_EN_EL_NOMBRE,
        nombre_de_la_constancia,
        nombre_oficial,
    )
    from ...domain.segmentation import Verdict, continua_por_el_papel
    from ...domain.sello import (
        claves_del_envio,
        es_guia_de_envio,
        lleva_etiqueta_de_envio,
        numero_del_acta_de_suspension,
    )
    from ...domain.sello import re_del_sello as _re_del_sello
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
        temporales.append(tmp_path)

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
        # Las hojas cuya capa no trae nada que leer: lo que la OCR leyó en
        # ellas va a la constancia si fecha un documento (``lo_leido``).
        sin_capa = {p for p, t in textos.items() if len((t or "").strip()) < MINIMO_DE_CAPA}
        textos.update({p: t for p, t in leidas.textos.items() if t})
        # L1c. El campo «N° PQR:» de la constancia que la capa rompió, releído
        # con el OCR de casa (gratis): sin él la constancia tomaba por su fecha
        # el RE de la de al lado (1005652, «RE86732022b3446», 2026-11-18).
        releidas_del_pqr: dict[int, tuple[str, str]] = {}
        textos = _con_el_pqr_releido(source, textos, releidas_del_pqr, taller.lector_de_pago())
        # El segundo lector de la letra a mano de los sellos: el modelo con
        # visión sobre el mismo recorte (el operador, 2026-11-18: «dos
        # lectores coinciden»). Sólo con «OCR + IA».
        _transcriptor = taller.transcriptor_de_sellos()
        vision_del_sello = (
            (lambda imagen: _transcriptor.resumir(PEDIDO_DEL_SELLO, imagen=imagen) or "")
            if _transcriptor is not None
            else None
        )
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
            avance_del_numero=lambda hechas, total: _anunciar(
                payload,
                Stage.GROUPING,
                detail="leyendo el número de cada sello con el OCR de pago",
                done=hechas,
                total=total,
            ),
            vision=vision_del_sello,
        )
        # L2c. El sello tenue de la carta que abre y en el que Tesseract no vio
        # nada (7975593, UPD3126960 págs. 9 y 44, 2026-11-12): con la IA, su
        # cabecera, una página por carta.
        re_leidos_sin_creer: dict[int, str] = {}
        de_las_cartas, sellos_sin_re, sellos_que_no_se_leyeron = _sellos_de_las_cartas(
            taller, source, textos, sellos, conocidos, leidos=re_leidos_sin_creer
        )
        sellos.update(de_las_cartas)
        # L2b. El sello de tinta clara junto a la firma, que la capa no dejó
        # ver (1005965 p2, 2026-11-11): con la tinta realzada en la zona de la
        # firma de cada hoja de firma sin sello, y su RE y su fecha a mano por
        # la IA si se eligió, validado el año del RE con el de la fecha. No
        # abren documento: dan el RE del nombre y la fecha.
        al_pie = sellos_al_pie(
            source,
            textos,
            set(sellos),
            lector_realzado=TesseractOcr(
                TesseractConfig(
                    min_word_confidence=0,
                    psm=6,
                    umbral=UMBRAL_DE_LA_TINTA_CLARA,
                    mediana=3,
                    timeout_seconds=SEGUNDOS_PARA_UNA_HOJA,
                )
            ),
            de_pago=taller.lector_de_pago(),
            control=taller.control,
            # Los RE que la caja ya trae: los de su texto y los de sus sellos,
            # validados -- nunca la lectura cruda de una letra a mano --.
            conocidos=conocidos | {r for s in sellos.values() if (r := _re_del_sello(s)[0])},
            vision=vision_del_sello,
        )
        # El RE a mano del sello de tinta a una sola cifra de uno que la caja
        # trae impreso es el impreso (7975593, UPD3126960 págs. 9 y 33,
        # 2026-11-13): antes de agrupar por trámite, que parte el trámite por
        # una cifra mal leída.
        sellos, al_pie, corregidos_por_lo_impreso = _con_lo_impreso(sellos, al_pie, textos)
        # L2d. El sello de tinta cuyo RE a mano ninguna lectura dejó creer,
        # releído en toda su zona, abierta alrededor y más fina (el operador,
        # 2026-11-18, ante 4100974: «que busque afuera, alrededor, en toda el
        # área del sello»). Sólo con «OCR + IA».
        for de_donde in (sellos, al_pie):
            de_donde.update(
                releer_la_zona_del_sello(
                    source,
                    de_donde,
                    de_pago=taller.lector_de_pago(),
                    vision=vision_del_sello,
                    control=taller.control,
                    oficinas={s.radicado[2:6] for s in sellos.values() if s.clase == "impreso" and s.radicado},
                    workers=workers,
                )
            )
        # El agente no cree el RE que no cuadra: con la IA, el sello al pie sin
        # RE válido va a Revisión.
        re_al_pie_sin_validar = sorted(p for p, s in al_pie.items() if not s.radicado) if taller.con_ia() else []
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
        # L4. El folio a mano de la esquina de cada hoja (2026-11-12: «el folio
        # manda»), con la IA si se eligió: diez esquinas por página pagada, cada
        # una con su hoja al lado. Tesseract no lee la letra a mano: con «Solo
        # OCR» no hay folios y el corte queda como estaba.
        # Sin las rachas del mismo número, que no son foliación (4132539,
        # 2026-11-20): tampoco van a la constancia ni a las marcas.
        from ...domain.foliacion_del_escrito import folios_creibles

        folios_de_la_esquina = folios_creibles(_leer_los_folios(payload, taller, source, page_count))
    finally:
        source.close()
    # Lo que abre por sí mismo cuando la numeración de un escrito se acaba: la
    # carta y el sello (arriba o al pie). El reverso de un recibo, no.
    from ...domain.carta import abre_carta as _abre_carta

    foliacion = foliacion_del_escrito(
        folios_de_la_esquina,
        range(1, page_count + 1),
        abren_solas={p for p, t in textos.items() if _abre_carta(t or "")} | set(sellos) | set(al_pie),
    )
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
    # Ni el sello de la hoja cuyo folio a mano sigue al de la anterior: es la
    # copia «Recibido» de otro radicado que el escrito trae anexa (2026-11-12,
    # «el folio manda»; 7975593 partía así doce escritos).
    sellos_que_abren = {p: s for p, s in sellos.items() if p not in cartas.no_abren and p not in foliacion.continua}
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
    # Ni la carta en una hoja cuyo folio a mano sigue al de la anterior: es la
    # copia que el escrito trae (2026-11-12, «el folio manda»).
    que_abren = cartas.que_abren(sellos_que_abren) - foliacion.continua
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
    from ...domain.asunto_del_documento import CONSTANCIA_DE_RECLAMACION as _CONSTANCIA
    from ...domain.asunto_del_documento import NOTIFICACIONES as _NOTIFICACIONES
    from ...domain.asunto_del_documento import RESPUESTA_DE_LA_EMPRESA as _RESPUESTA
    from ...domain.asunto_del_documento import consecutivo_de as _consecutivo_de

    # El folio no une dos formularios que traen cada uno su radicado, y
    # distinto: son dos trámites, y el folio leído -- la IA sacó «1000» de las
    # esquinas en blanco de dos constancias -- es el que se equivoca (4100976,
    # UPD2456242 págs. 1-2, 2026-11-19: RE2320202203675 y RE2320202207081).
    con_su_radicado = (_CONSTANCIA, *_NOTIFICACIONES)
    radicado_de_delante = None
    distintos = set()
    for p in sorted(formularios):
        tipo_f, radicado_f = formularios[p]
        if (
            tipo_f in con_su_radicado
            and radicado_f
            and radicado_de_delante
            and radicado_f != radicado_de_delante
            and p in foliacion.continua
        ):
            distintos.add(p)
        if radicado_f:
            radicado_de_delante = radicado_f
    if distintos:
        foliacion = replace(foliacion, continua=foliacion.continua - distintos)

    # Y desde el 2026-11-11 también cuando lo de delante no es de su trámite:
    # ni lleva su RE ni cae en su ventana de fechas. En 1016215 (UPD2437946) la
    # respuesta de 2022 a YORLENE RIAPIRA quedó detrás del contrato que anexaba
    # la carta de 2021 de otro suscriptor, y el archivo salió «CONTRATO DE
    # TRANSACCION», sin fecha.
    # La notificación por aviso y la publicación del aviso son notificaciones
    # como la personal: la respuesta que va detrás es otro documento
    # (4100976, 2026-11-19).
    for p in [p for p, (tipo_f, _) in formularios.items() if tipo_f == _RESPUESTA]:
        tras_la_notificacion = any(
            formularios.get(p - atras, ("", None))[0] in _NOTIFICACIONES for atras in (1, 2, 3)
        )
        if not tras_la_notificacion and _sigue_con_lo_de_delante(
            p, formularios[p][1], grupos.groups, textos, sellos, abren=set(sellos_que_abren) | set(que_abren)
        ):
            del formularios[p]
    # La copia de un formulario que ya salió en la caja -- la misma notificación
    # de aceptación del desistimiento en la 306 y, dentro del desistimiento, en
    # la 309 (7975593, 2026-11-12) -- es del escrito que la trae: no abre.
    for p in _copias_de_formularios(formularios, textos):
        del formularios[p]
    # Dentro de los folios de un sello, o aportado como prueba, un formulario
    # es del escrito que lo trae: no abre. Salvo la Habeas Data, que nunca es
    # prueba de una carta: es de su acuerdo de pago (1002421 pág. 10, detrás de
    # la carta de otra persona).
    intocables = set(por_folios) | {
        p for p in de_prueba if formularios.get(p, ("", None))[0] != _HABEAS
    } | set(foliacion.continua)
    # Detrás de la constancia y la notificación sólo sigue el anexo evidente:
    # la cédula, la factura, la hoja muda o la foto, que traen poco texto. Una
    # hoja con texto propio es otro documento (1000224 pág. 2, una carta que la
    # lectura tomaba por certificado catastral).
    from ...application.anexos_declarados import SOPORTES as _SOPORTES
    from ...domain.anexos_declarados import HOJA_MUDA as _MUDA
    from ...domain.anexos_declarados import clase_de_la_hoja as _clase

    def _anexo_evidente(pagina: int) -> bool:
        texto = textos.get(pagina, "") or ""
        # Una carta -- fecha o saludo y su REF -- es un escrito, no el anexo de
        # la constancia, por corta que sea: la de 1005652 (UPD2437864 pág. 3,
        # 2026-11-20) tenía 55 palabras y se quedaba con la constancia.
        if abre_carta(texto):
            return False
        if _clase(texto) in _SOPORTES or _clase(texto) == _MUDA:
            return True
        return len(re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", texto)) < PALABRAS_DE_UN_DOCUMENTO

    # Dos cartas de la empresa seguidas con el mismo RE son dos cartas si su
    # consecutivo es otro: la respuesta del 07-06-2022 y la del 08-06-2022 a la
    # petición RE8673202201958 (4100976, págs. 41 y 42, 2026-11-19). La hoja
    # que continúa una carta no repite el consecutivo.
    def _clave(pagina: int) -> tuple[str, str | None]:
        tipo_f, radicado_f = formularios[pagina]
        consecutivo = _consecutivo_de(textos.get(pagina, "") or "") if tipo_f == _RESPUESTA else None
        return (tipo_f, f"{radicado_f or ''}#{consecutivo}") if consecutivo else (tipo_f, radicado_f)

    grupos, anexos, _ = separar_los_formularios(
        grupos,
        {p: _clave(p) for p in formularios},
        anexos,
        intocables=intocables,
        solos=frozenset({_CONSTANCIA, *_NOTIFICACIONES}),
        anexo_evidente=_anexo_evidente,
    )
    # Los que van solos abren documento para todo lo que viene después: ni la
    # lista de anexos, ni la cédula, ni el trámite por RE los une a otro. El
    # acuerdo y la Habeas Data no: el acuerdo los busca para juntarlos.
    formularios_solos = {
        g.page_numbers[0]
        for g in grupos.groups
        if g.page_numbers[0] in formularios and formularios[g.page_numbers[0]][0] not in (_ACUERDO, _HABEAS)
    }
    # Y el documento que va detrás de una constancia o una notificación sin
    # ser su anexo evidente -- lo haya separado este filtro o la continuidad
    # --: no vuelve a unírsele por no traer título (1000224 pág. 2).
    solos_tipos = (_CONSTANCIA, *_NOTIFICACIONES)
    for anterior, grupo in zip(grupos.groups, grupos.groups[1:], strict=False):
        primera = grupo.page_numbers[0]
        if (
            formularios.get(anterior.page_numbers[0], ("", None))[0] in solos_tipos
            and primera not in formularios
            and primera not in intocables
            and not _anexo_evidente(primera)
        ):
            formularios_solos.add(primera)
    # F2f. El folio manda (2026-11-12): lo que la numeración a mano dice que
    # sigue vuelve a su escrito, y el folio 1 abre el suyo. Lo que el folio
    # une no lo vuelve a abrir nada de lo que viene.
    por_el_folio = aplicar_la_foliacion(grupos, anexos, foliacion)
    grupos, anexos = por_el_folio.grupos, por_el_folio.anexos
    formularios_solos -= foliacion.continua
    abren -= foliacion.continua
    # El trámite no une a su anterior un escrito del cliente, aunque cite su
    # RE: sólo la respuesta o la notificación de la empresa (lo dictó el
    # operador: «cada trámite va solo, no unido a otros trámites por código de
    # referencia»). Y desde el 2026-10-26 tampoco la constancia, la
    # notificación ni la respuesta: cada una va sola.
    abren_el_tramite = abren | cartas.escritos(que_abren) | formularios_solos | foliacion.abre
    abren = abren | que_abren | formularios_solos | foliacion.abre
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
    # Con varios acuerdos, cada Habeas Data con el de su persona: su nombre y
    # su cédula, de la capa o, si no los trae, de la IA (4100921, 2026-11-18).
    personas = _PersonasDeLasHojas(taller, tmp_path, textos)
    try:
        grupos, anexos, del_acuerdo = unir_el_acuerdo_de_pago(
            grupos,
            textos,
            anexos,
            abren=abren,
            cruzan=formularios_solos,
            persona_de=personas,
            fecha_de=personas.fecha_de,
        )
    finally:
        personas.cerrar()
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

    # La fecha de cada uno, donde su estructura la pone: el sello, o la hoja
    # principal -- que no siempre es la primera -- en el sitio de su clase
    # (:mod:`~resolutions.domain.fecha_por_estructura`, 2026-11-10). No la
    # primera hoja fechada ni la más reciente del texto, que en un acuerdo es
    # la de un anexo y en un reclamo la de los hechos.
    from ...domain.asunto_del_documento import (
        ACUERDO_DE_PAGO,
        asunto_del_documento,
        titulo_del_documento,
    )
    from ...domain.fecha_por_estructura import fecha_por_estructura
    from ...domain.fecha_por_estructura import pieza_de as pieza_de_la_hoja
    from ...domain.tramites import radicado_del_sello

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
        if titulo == _CONSTANCIA:
            # Cada formato con su nombre (el operador, 2026-11-20).
            return nombre_de_la_constancia(texto)
        if titulo != DOCUMENT_PREFIX:
            return nombre_oficial(titulo, asunto) or titulo
        if abre_carta(texto) and (del_asunto := nombre_oficial(DOCUMENT_PREFIX, asunto)):
            return del_asunto
        if tipo and tipo.upper() != DOCUMENT_PREFIX:
            return nombre_oficial(tipo, asunto) or tipo.upper()
        return DOCUMENT_PREFIX

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
                del_reconocimiento: list[int] = []
                if acuerdo:
                    # El acuerdo se titula y se fecha por su reconocimiento
                    # de deuda, que es lo que el usuario firmó y fechó.
                    del_reconocimiento = [
                        p
                        for p in paginas
                        if titulo_del_documento(textos.get(p, "") or "") == ACUERDO_DE_PAGO
                    ]
                    titulares = del_reconocimiento or titulares
                # La fecha del documento, donde su estructura la pone (lo
                # dictó el operador el 2026-11-10: «del documento principal…
                # cuando exista un sello, la fecha que esté dentro del sello»):
                # el sello; si no, la hoja principal -- que no siempre es la
                # primera -- en el sitio de su clase; si no, sus respaldos.
                # Nunca un anexo, ni la guía que acompaña a una carta, ni el
                # sello de una copia aportada como prueba: ésa es de otro día.
                # Con los sellos al pie (L2b) que traen su fecha -- la leyó la IA
                # --: es la del sello. Sin fecha no cuentan, y «Solo OCR» queda
                # como estaba.
                con_pie = {**{p: s for p, s in al_pie.items() if s.fecha}, **sellos}
                # El acuerdo, sólo en las hojas de su reconocimiento: en todas,
                # la hoja principal salía el reverso de la cédula -- «FECHA DE
                # NACIMIENTO 21-MAY-1963» -- y la carta de instrucciones, y el
                # reconocimiento fechado a mano «27 de Nov de 2021» quedaba sin
                # fecha y al final (1005114, UPD2973876, 2026-11-18).
                # Sus respaldos -- la firma de la carta de instrucciones, la
                # Habeas Data -- sólo si el reconocimiento no la da ni releído
                # ni con la IA: el reconocimiento «18 de 09 de 20» deja el año
                # a medias y la carta dice «a los 18 días del mes septiembre
                # del año 2020» (4100971, UPD2985239, 2026-11-19). En esta
                # primera pasada no: la firma de la carta, que Tesseract sí
                # lee, ganaba al reconocimiento escrito a mano antes de que la
                # IA lo mirara, y el reconocimiento fechado quedaba al final
                # (1000258, 2026-11-20). La cédula sigue fuera.
                respaldos_del_acuerdo = [
                    p
                    for p in paginas
                    if del_reconocimiento
                    and p not in del_reconocimiento
                    and pieza_de_la_hoja(textos.get(p, "") or "").respaldo
                ]
                estructura = fecha_por_estructura(
                    del_reconocimiento or paginas,
                    textos,
                    sellos={
                        p: con_pie[p].fecha
                        for p in paginas
                        if p in con_pie and con_pie[p].fecha and p not in cartas.copias
                    },
                    guias=fechas_de_guia,
                    con_sello={p for p in paginas if p in con_pie and p not in cartas.copias},
                )
                primera = estructura.fecha
                piezas.append(
                    {
                        "pages": paginas,
                        # En qué archivo acabó: la fecha de su trámite se busca
                        # primero entre los documentos de su mismo archivo.
                        "archivo": archivo,
                        "type": cortado.kind,
                        # Sin la de su estructura, ninguna: la del corte es la
                        # más reciente de todas sus hojas, anexos incluidos
                        # (el certificado de Cámara de Comercio de 2012 en un
                        # acuerdo de 2020). La busca después el agente.
                        "fecha": primera.isoformat() if primera else None,
                        **({"fecha_por": estructura.como()} if primera else {}),
                        # De qué hoja y por qué vía, para dejar en la
                        # constancia lo que se leyó fuera de la capa.
                        **(
                            {"fecha_pagina": estructura.pagina, "fecha_via": _VIA_DE_LA_FUENTE.get(estructura.fuente, "texto")}
                            if primera
                            else {}
                        ),
                        # Dónde releerla si no salió: la hoja principal y
                        # sus respaldos.
                        "donde_buscar": [
                            *estructura.donde_buscar,
                            *(p for p in respaldos_del_acuerdo if p not in estructura.donde_buscar),
                        ],
                        # Las hojas de cada reconocimiento: si trae dos, se
                        # fecha cada uno y manda el más reciente (2026-11-20).
                        **(
                            {"reconocimientos": reconocimientos_del_acuerdo(paginas, textos)}
                            if acuerdo and del_reconocimiento
                            else {}
                        ),
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
        # El soporte -- la cédula, la factura -- nunca es la pieza con que abre
        # su archivo, aunque vaya primero en el papel: la que abre da la fecha
        # y el título de la fila. La cédula que iba detrás de una constancia
        # pasa al documento siguiente (F5f) y, delante del acuerdo, lo dejaba
        # sin fecha (1000228, UPD3102727 pág. 3, 2026-11-20).
        from ...domain.tramites import es_cedula as _es_cedula

        def solo_soporte(pieza: dict) -> bool:
            return all(
                clase_de_soporte(textos.get(p, "") or "") is not None or _es_cedula(textos.get(p, "") or "")
                for p in pieza["pages"]
            )

        for archivo in dict.fromkeys(p["archivo"] for p in piezas):
            suyas = [i for i, p in enumerate(piezas) if p["archivo"] == archivo]
            primera = next((i for i in suyas if not solo_soporte(piezas[i])), None)
            if primera is not None and primera != suyas[0]:
                piezas.insert(suyas[0], piezas.pop(primera))
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
        # Las hojas que siguen a la anterior por lo que el papel dice de sí
        # mismo: el RE que citan no las saca de su documento.
        # Y la que sigue por su folio a mano (2026-11-12, «el folio manda»).
        continuan_por_el_papel = {b.right for b in segmentacion.boundaries if continua_por_el_papel(b)} | set(
            foliacion.continua
        )
        # Sin los sellos de las copias aportadas como prueba: son de otro trámite.
        por_tramite = agrupar_por_tramite(
            grupos,
            leidas,
            anexos,
            retenidas=retencion.retenidas,
            sellos={p: s for p, s in sellos.items() if p not in de_prueba},
            # La hoja que sigue a la anterior por su frase, su numeración o su
            # folio no cambia de trámite por un RE que cita (2026-11-12).
            continuan=continuan_por_el_papel,
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
            # Ni la hoja que sigue a la anterior por su frase, su numeración o
            # su folio, con el RE que cita en el cuerpo (7975593, UPD2460819
            # p203-204, 2026-11-12): sólo con el de su sello.
            for p in continuan_por_el_papel:
                if p in propios and p not in sellos:
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

    from ...domain.fecha_por_estructura import ABRE as _ABRE
    from ...domain.fecha_por_estructura import CARTA_RADICADA_DE_LA_EMPRESA
    from ...domain.fecha_por_estructura import pieza_de as _pieza_de

    _FORMULARIOS_DE_LA_EMPRESA = frozenset(
        {
            "publicación del aviso",
            "notificación personal",
            "acta de revisión",
            "liquidación del consumo",
            "acta de suspensión",
            "constancia de la reclamación",
            "constancia de contratación",
            "constancia de visita",
            CARTA_RADICADA_DE_LA_EMPRESA,
        }
    )

    def _es_comprobante(pagina: int) -> bool:
        return _pieza_de(textos.get(pagina, "") or "").nombre == "comprobante de pago"

    sin_apertura = set()
    for anterior, g in zip(grupos.groups, grupos.groups[1:], strict=False):
        primera = g.page_numbers[0]
        if primera in sellos_que_abren or primera in etiquetas or primera + 1 in etiquetas:
            continue
        # La carta que abre su trámite tampoco se une: trae su asunto.
        if primera in que_abren:
            continue
        # Ni el formulario que va solo, ni lo que sigue a una constancia o una
        # notificación sin ser su anexo evidente (1000224 pág. 2).
        if primera in formularios_solos:
            continue
        if primera in del_acuerdo or primera == ultima_sola:
            continue
        if _re_del(g) and _re_del(g) != _re_del(anterior):
            continue
        # Un comprobante detrás de otro comprobante es otro pago, con su fecha:
        # va en su documento (4100875, UPD2985229, 2026-11-19: el del 08-04-2022
        # y el del 17-07-2021 salían en un solo PDF). Detrás de un escrito sí
        # es su prueba de pago, y va con él.
        if _es_comprobante(primera) and _es_comprobante(anterior.page_numbers[0]):
            continue
        titular = next((x for x in g.page_numbers if x not in guias), primera)
        # Ni el formulario de la empresa que su estructura reconoce aunque la
        # capa no deje leer un título: la constancia de visita, el acta de
        # revisión, la liquidación del consumo, la publicación del aviso, la
        # carta con su «Radicación #». Son documentos con su fecha, y en
        # 4100976 (UPD2456242, 2026-11-19) los de un acta de 2021 acababan
        # dentro de la contestación de 2022.
        if _pieza_de(textos.get(titular, "") or "").nombre in _FORMULARIOS_DE_LA_EMPRESA:
            continue
        # Y la hoja que repite el título del acta de delante -- «Acta de
        # Irregularidad» va en la cabeza de cada hoja del formato -- sin abrir
        # un acta nueva es su continuación: el acta 28737950 de 4100976 salía
        # partida en 31-32 y 33-38.
        titulo_suyo = _titulo(textos.get(titular, "") or "", None)
        if (
            titulo_suyo.startswith("ACTA DE ")
            and titulo_suyo == _titulo(textos.get(anterior.page_numbers[0], "") or "", None)
            and _pieza_de(textos.get(titular, "") or "").rango != _ABRE
        ):
            sin_apertura.add(primera)
            continue
        if titulo_suyo in (
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
        # Sólo la autorización suelta, con sus soportes: si su documento trae
        # pagarés o un reconocimiento, es el acuerdo de pago, y pegarlo al de
        # después lo nombraba como él (4100919, UPD2985234, 2026-11-18: el
        # acuerdo entero, 1-7, acabó dentro de la DECLARACION de la 8).
        from ...domain.asunto_del_documento import PIEZAS_DEL_ACUERDO

        con_piezas = any(
            _titulo(textos.get(p, "") or "", None) in PIEZAS_DEL_ACUERDO for p in primero.page_numbers
        )
        if not con_piezas and primero.page_numbers[0] not in del_acuerdo and _titulo(
            textos.get(primero.page_numbers[0], "") or "", None
        ) in ("LEY HABEAS DATA", AUTORIZACION_DE_NOTIFICACION):
            from ...application.anexos_declarados import _renumerar

            delanteras.update(primero.page_numbers)
            unido = replace(segundo, page_numbers=list(primero.page_numbers) + list(segundo.page_numbers))
            suyos = anexos.pop(primero.code.value, []) + anexos.pop(segundo.code.value, []) + list(primero.page_numbers)
            anexos[unido.code.value] = sorted(set(suyos))
            restantes, anexos = _renumerar([unido, *grupos.groups[2:]], anexos)
            grupos = replace(grupos, groups=restantes)
    # F5d. Y otra vez el folio, sobre lo que dejaron el trámite y lo que no
    # abre: es la regla que manda (2026-11-12). Lo que mueva aquí se suma a lo
    # que movió en F2f, para el informe.
    final_por_el_folio = aplicar_la_foliacion(grupos, anexos, foliacion)
    grupos, anexos = final_por_el_folio.grupos, final_por_el_folio.anexos
    # F5e. El revisor de cortes (lo pidió el operador el 2026-11-05 ante
    # 1004569, donde el acuerdo de pago se llevó la última hoja del contrato de
    # transacción saltando una constancia): cada costura de lo que va a salir,
    # validada dentro del margen de error, corregida si dos pruebas del papel
    # coinciden, decidida por la IA si se eligió y si no a revisión. Antes de
    # nombrar y fechar, para que lo corregido se nombre y se feche bien. Por mes
    # no: ahí un archivo es un mes, no un documento.
    revisados = None
    revisor_roto = None
    # El RE que se cree de cada sello, arriba o al pie (2026-11-12: el PDF con
    # dos o más sellos de RE distinto lo revisa el agente y se avisa). Sin los
    # de las hojas cuyo sello explica una regla: la copia aportada como prueba
    # trae el de otro trámite, y el acuerdo de pago es un documento.
    res_de_los_sellos = _res_de_los_sellos(sellos, al_pie, {r[2:6] for r in conocidos if len(r) == 15})
    explicados = {
        **{p: "explicado: acuerdo de pago" for p in del_acuerdo},
        **{p: "explicado: copia aportada como prueba" for p in (*cartas.copias, *de_prueba)},
        # El sello en una hoja con folio intermedio es la copia que el escrito
        # trae: lo explica su folio a mano (2026-11-12).
        **{p: "explicado: copia dentro de los folios del escrito" for p in foliacion.continua},
    }
    marcas_por_hoja = marcas_de_las_hojas(folios_de_la_esquina, sellos, al_pie)
    if entregado_por is not Agrupacion.MES:
        try:
            revisados, cortados_revisados = _revisar_los_cortes(
                grupos,
                anexos,
                textos=textos,
                taller=taller,
                pdf=tmp_path,
                abren=set(abren_el_tramite if entregado_por is Agrupacion.TRAMITE else abren),
                delanteras=delanteras,
                del_acuerdo=set(del_acuerdo),
                # Y lo que decidió el folio a mano, que manda (2026-11-12).
                fijas=set(sellos_que_abren) | etiquetas | guias | foliacion.continua | foliacion.abre,
                cortados=cortados,
                sellos={p: r for p, r in res_de_los_sellos.items() if p not in explicados},
                al_pie=frozenset(p for p in al_pie if p not in sellos),
                folios=folios_de_la_esquina,
                marcas=marcas_por_hoja,
            )
        except Exception as error:  # noqa: BLE001 - el revisor nunca tumba la caja
            # Sale como la cortaron las reglas, y se dice.
            logger.exception("el revisor de cortes falló en %s", taller.name)
            revisor_roto = f"El revisor de cortes no pudo revisar esta caja ({type(error).__name__}); sale como la cortaron las reglas"
        else:
            grupos, anexos, cortados = revisados.grupos, revisados.anexos, cortados_revisados
            del_acuerdo = revisados_del_acuerdo(del_acuerdo, revisados)
    # F5f. La constancia del contenido de la reclamación, sola, siempre (el
    # operador, 2026-11-20): lo que los filtros de arriba le pegaron detrás --
    # la cédula, la carta -- sale; la cédula, con el documento siguiente. Salvo
    # la constancia que un escrito aporta dentro de sus folios o como prueba:
    # ésa es del escrito.
    constancias_sueltas = None
    if entregado_por is not Agrupacion.MES:
        constancias_sueltas = constancias_solas(
            grupos,
            textos,
            anexos,
            constancias={
                p: radicado_f
                for p, (tipo_f, radicado_f) in formularios.items()
                if tipo_f == _CONSTANCIA and p not in intocables
            },
        )
        grupos, anexos = constancias_sueltas.grupos, constancias_sueltas.anexos
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
        # Ni la cédula que se le unió por delante: la que iba detrás de una
        # constancia pasa al documento siguiente (F5f), y la declaración
        # juramentada de 4132540 (UPD3119343 págs. 5-6) se llamaba «PQR»
        # (2026-11-20). Ningún documento se llama como su anexo.
        from ...domain.tramites import es_cedula as _es_cedula_del_nombre

        primera = next(
            (
                x
                for x in g.page_numbers
                if x not in guias
                and x not in delanteras
                and clase_de_soporte(textos.get(x, "") or "") is None
                and not _es_cedula_del_nombre(textos.get(x, "") or "")
            ),
            primera,
        )
        # La respuesta de la empresa a una reclamación se llama como la nombró
        # el operador, «CONTESTACION A LA RECLAMACION», y lleva su RE
        # (2026-11-11; con «LA» y también «EN ATENCIÓN A…», 2026-11-18).
        if es_contestacion_a_reclamacion(textos.get(primera, "") or ""):
            return replace(g, kind=CONTESTACION_A_RECLAMACION)
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
        # El nombre que dio el operador a la contestación no se le discute a la IA.
        if nombre in POR_NOMBRE or nombre == CONTESTACION_A_RECLAMACION or nombrador is None:
            return replace(nombrado, kind=nombre)
        if not fuente_de_encabezados:
            fuente_de_encabezados.append(PyMuPDFPageSource(tmp_path, taller.name))
        # Todo el documento, no sólo su primera hoja: lo que dice ser puede
        # estar en cualquiera. Menos las autorizaciones que lleva como anexo:
        # con la suya delante, la IA llamaba «AUTORIZACION PARA LA
        # NOTIFICACION ELECTRONICA» al derecho de petición que la trae
        # (1004833, UPD3102764 págs. 16-17, 2026-11-18).
        propias = [p for p in g.page_numbers if p not in guias and p not in delanteras]
        # Ni la cédula o la factura: no dicen qué es el documento (2026-11-20).
        from ...domain.tramites import es_cedula as _es_cedula_de_la_ia

        sin_anexos = [
            p
            for p in propias
            if _titulo(textos.get(p, "") or "", None) not in (AUTORIZACION_DE_NOTIFICACION, "LEY HABEAS DATA")
            and clase_de_soporte(textos.get(p, "") or "") is None
            and not _es_cedula_de_la_ia(textos.get(p, "") or "")
        ]
        de_la_ia = _nombre_con_la_ia(
            fuente_de_encabezados[0],
            sin_anexos or propias or list(g.page_numbers),
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

    from ...domain.asunto_del_documento import (
        CONTESTACION_A_RECLAMACION,
        es_contestacion_a_reclamacion,
    )
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
    # F6b. El reclamo y la constancia de su contenido llevan su RE en el
    # nombre (lo dictó el operador el 2026-11-04), y la contestación y todo
    # documento con su sello (2026-11-11). Por mes no: el archivo es un mes, no
    # un documento.
    re_en_el_nombre: dict[str, str] = {}
    re_rechazados: list[dict] = []
    #: El hallazgo del RE de cada documento, con su evidencia (2026-11-18).
    evidencia_del_re: dict[str, dict] = {}
    # El sello al pie de una copia aportada como prueba no es del documento que
    # la trae: su RE no se pide (7975593, UPD3126960 p43).
    re_al_pie_que_importa = [p for p in re_al_pie_sin_validar if p not in cartas.copias and p not in de_prueba]
    re_del_sello_sin_leer: list[int] = []
    re_del_sello_solo_ocr: list[int] = []
    sin_su_re: list[dict] = []
    if entregado_por is not Agrupacion.MES:
        grupos, anexos, re_en_el_nombre = _poner_el_re_en_el_nombre(
            grupos,
            anexos,
            textos=textos,
            # Con los sellos al pie: dan el RE del documento, no abren nada.
            sellos={**al_pie, **sellos},
            # El agente valida el RE a mano con las oficinas que radican y las
            # de los RE impresos de la caja; lo que no cree va a Revisión. Las
            # de su texto y las de sus etiquetas impresas: en 1005117 el RE de
            # la etiqueta va pegado a «NUMERO» en la capa y el texto no lo da
            # (2026-11-18).
            # Sólo de lo impreso -- las etiquetas y los sellos impresos --,
            # nunca del RE que cita una carta (2026-11-18).
            oficinas={s.radicado[2:6] for s in sellos.values() if s.clase == "impreso" and s.radicado},
            releidas_del_pqr=releidas_del_pqr,
            evidencias=evidencia_del_re,
            rechazados=re_rechazados,
            # Ni la copia «Recibido» que el escrito trae dentro de sus folios:
            # su sello es el del radicado de otro papel (2026-11-18; ya la
            # explicaba el aviso de varios sellos, pero su RE iba al nombre).
            sin_re=set(cartas.copias) | set(de_prueba) | set(del_acuerdo) | set(foliacion.continua),
            abren=set(sellos_que_abren),
            sellos_sin_re=sellos_sin_re,
        )
        if taller.con_ia():
            from ...domain.nombre_oficial import es_re as _es_re

            con_re = {g.page_numbers[0] for g in grupos.groups if any(_es_re(p) for p in g.code.value.split())}
            primeras = {g.page_numbers[0] for g in grupos.groups}
            ya_rechazadas = {rechazado["page"] for rechazado in re_rechazados}
            sin_su_re = {p for p, s in sellos.items() if s.clase == "tinta" and not s.radicado} | set(
                sellos_que_no_se_leyeron
            )
            re_del_sello_sin_leer = sorted(
                p
                for p in sin_su_re
                if p in primeras
                and p not in sellos_sin_re
                and p not in con_re
                and p not in ya_rechazadas
                and p not in cartas.copias
                and p not in de_prueba
            )
        else:
            # Con «Solo OCR» el RE a mano del sello de tinta no se lee nunca: el
            # documento que trae uno y salió sin RE va a Revisión, sea del tipo
            # que sea (2026-11-18).
            re_del_sello_solo_ocr = documentos_con_sello_sin_re(
                grupos,
                {**al_pie, **sellos},
                no_cuentan=set(cartas.copias) | set(de_prueba) | set(del_acuerdo) | set(foliacion.continua),
                # El escrito del usuario -- reclamo, recurso, petición, queja --
                # se radica siempre con su sello: sin RE, es que no se leyó,
                # aunque la lectura no haya visto el sello de poca tinta.
                escritos=set(cartas.de_tramite) - set(cartas.copias),
            )
        # Y todo reclamo, constancia, contestación o notificación que salió sin
        # su RE, también con «Solo OCR» (el operador, 2026-11-18).
        sin_su_re = documentos_sin_su_re(
            grupos,
            {
                *re_del_sello_sin_leer,
                *re_del_sello_solo_ocr,
                *re_al_pie_que_importa,
                *(rechazado["page"] for rechazado in re_rechazados),
            },
            textos,
        )
    piezas = describir_piezas(grupos.groups)
    # F7. La fecha que la estructura no dio en la capa: el agente relee la hoja
    # principal y sus respaldos, en local y, si se eligió una lectura con IA,
    # con la IA. Lo que no sale va sin fecha y a Revisión (2026-11-10: la de su
    # trámite, prestada, acertaba 18 de 65; el operador: «vacía y a Revisión»).
    releidas: dict[int, list[str]] = {}
    # Ya no se presta ninguna: el revisor la sigue recibiendo, vacía.
    prestadas: dict[int, int] = {}
    fechas_sin_leer: list[dict] = []
    fechas_halladas = _completar_las_fechas(
        piezas, textos, tmp_path, taller, releidas=releidas, sin_leer=fechas_sin_leer
    )
    # F7a. Las fechas de la caja contra sí mismas (2026-11-18): la que
    # comparte día y mes con las demás y no su año se relee en su papel.
    fechas_halladas.extend(_contrastar_las_fechas(piezas, textos, tmp_path, taller, releidas, fechas_sin_leer))
    # F7b. El revisor de fechas (2026-11-10): la de cada pieza contra lo que ya
    # se leyó de sus hojas, antes de entregar, para que el índice lleve la
    # corregida. Lo anotado pasa al informe cuando éste se arma.
    fechas_revisadas = _asegurar_las_fechas(
        piezas,
        textos,
        taller,
        releidas=releidas,
        prestadas=prestadas,
        sellos=sellos,
        fechas_de_guia=fechas_de_guia,
    )
    # F8. El número de cada PDF, por la fecha de su documento: el mismo orden
    # que el Índice Electrónico (lo dictó el operador el 2026-11-11). Por mes
    # no: el archivo es un mes, y su código no es un puesto.
    numerado_por_fecha = entregado_por is not Agrupacion.MES
    if numerado_por_fecha:
        grupos, anexos, piezas = numerar_por_fecha(grupos, anexos, piezas)
    # F8c. Los folios del sello contra las hojas de cada documento (el
    # operador, 2026-11-18: «contrasta la cantidad de folios indicada en los
    # sellos con las páginas reales»). Sólo avisa, a Revisión.
    folios_sin_cuadrar = folios_contra_hojas(piezas, sellos)
    # F8b. Las hojas del acuerdo de pago en su orden: el reconocimiento primero
    # si está fechado, si no al final; los pagarés, la Habeas Data y los anexos
    # (lo dictó el operador el 2026-11-12). Sólo el orden del PDF escrito: el
    # inventario y las fechas siguen con el del papel.
    grupos = _ordenar_los_acuerdos(
        grupos, piezas, textos, set(del_acuerdo), por_mes=entregado_por is Agrupacion.MES
    )
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
            # «quita el RE del título, ya no es necesario»): 01_DERECHO-DE-PETICION.pdf.
            sin_radicado=True,
            # Salvo el reclamo y la constancia de su contenido, que lo llevan
            # detrás (2026-11-04): 03_RECLAMO-RE2310202405234.pdf.
            radicado_en=CON_RE_EN_EL_NOMBRE,
        ),
        en_revision=[boundary.right for boundary in costuras_en_revision]
        + [pagina.page for pagina in sin_fecha_en_revision]
        + sin_titulo
        + [pagina for pagina, _ in (revisados.en_revision if revisados else ())]
        + [sin_leer["page"] for sin_leer in fechas_sin_leer]
        + re_al_pie_que_importa
        + re_del_sello_sin_leer
        + [rechazado["page"] for rechazado in re_rechazados]
        + [aviso["page"] for aviso in sin_su_re]
        + re_del_sello_solo_ocr
        + [aviso["page"] for aviso in folios_sin_cuadrar],
        estadisticas=estadisticas,
        anexos=anexos,
        # Cada PDF escrito, vuelto a abrir y casado hoja por hoja con el
        # original (2026-11-05: «validados de extremo a extremo»).
        huellas=huellas_de,
    )
    # Los PDF con dos o más sellos de RE distinto (el operador, 2026-11-12):
    # con lo que hizo el agente de cada uno, para los avisos, el Excel de
    # procesos y la auditoría. Por mes no: un archivo es un mes, no un documento.
    varios_sellos = (
        pdf_con_varios_sellos(
            [(item.file_name, item.page_numbers) for item in entregado.inventario.items],
            res_de_los_sellos,
            explicados=explicados,
            al_pie=frozenset(p for p in al_pie if p not in sellos),
            revision=revisados,
        )
        if entregado_por is not Agrupacion.MES
        else []
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
        # Y el que no dejó leer su fecha: va sin ella, a que alguien la mire.
        + fechas_sin_leer
        # Y el sello al pie (L2b) cuyo RE a mano la IA no leyó, o leyó con otro
        # año que el de la fecha del sello: el agente no lo cree y no va al
        # nombre (2026-11-11). Sin la IA no se lee nunca, y no se repite aquí.
        + [{"page": pagina, "reason": RE_AL_PIE_SIN_VALIDAR} for pagina in re_al_pie_que_importa]
        # Y el sello de arriba con su RE a mano que ni Tesseract ni la IA
        # leyeron con certeza (UPD2460819 pág. 176, 2026-11-13).
        + [
            {
                "page": pagina,
                "reason": RE_DEL_SELLO_SIN_LEER
                + (f" (se leyó «{re_leidos_sin_creer[pagina]}»)" if pagina in re_leidos_sin_creer else ""),
            }
            for pagina in re_del_sello_sin_leer
        ]
        # Y el RE a mano que la IA leyó y el agente no cree: otro año que el del
        # sello, o una oficina que no radica.
        + re_rechazados
        # Y el reclamo, la constancia, la contestación o la notificación que
        # salió sin su RE (2026-11-18).
        + sin_su_re
        # Y, con «Solo OCR», el documento con sello de tinta que salió sin RE.
        + [{"page": pagina, "reason": RE_DEL_SELLO_SOLO_OCR} for pagina in re_del_sello_solo_ocr]
        # Y el documento cuyas hojas no cuadran con los folios de su sello.
        + folios_sin_cuadrar
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
            *(
                [
                    f"{len(constancias_sueltas.movidas)} hoja(s) de soporte que iban detrás de una constancia "
                    "pasaron al documento siguiente: la constancia va sola"
                ]
                if constancias_sueltas is not None and constancias_sueltas.movidas
                else []
            ),
            *([aviso] if (aviso := aviso_de_varios_sellos(varios_sellos)) else []),
        ],
        # Y el detalle de cada PDF con dos o más sellos de RE distinto: sus
        # sellos, lo que hizo el agente y por qué (2026-11-12).
        "varios_sellos": varios_sellos,
        # El folio a mano de cada hoja (L4) y lo que hizo con él la regla del
        # folio: las hojas que volvieron a su escrito y las que abrieron el
        # suyo. La auditoría razona con los folios y las marcas de cada hoja.
        "folios_de_la_esquina": {str(p): f for p, f in sorted(folios_de_la_esquina.items())},
        "por_el_folio": {
            "unidas": sorted({*por_el_folio.unidas, *final_por_el_folio.unidas}),
            "partidas": sorted({*por_el_folio.partidas, *final_por_el_folio.partidas}),
        },
        "marcas": {str(p): m for p, m in marcas_por_hoja.items()},
        # Lo que cada escrito dijo que traía contra lo que se encontró. Lo lee
        # el Índice Electrónico para sus observaciones.
        "anexos_declarados": [escrito.as_dict() for escrito in escritos],
        # Los documentos que forman cada archivo, y el expediente: la caja.
        "piezas": piezas,
        # Si los PDF van numerados por la fecha de su documento, como el
        # índice: la carpeta del NIC los numera seguidos por la misma fecha.
        "numerado_por_fecha": numerado_por_fecha,
        # Las fechas que no estaban a la vista y de dónde salieron: el índice
        # lleva sólo la fecha; aquí queda cómo se obtuvo, para auditarla.
        "fechas_halladas": fechas_halladas,
        # Y lo que se leyó para fecharlas fuera de la capa del PDF: va a la
        # constancia, y la auditoría de cierre lo suma al papel (2026-11-11).
        "lo_leido": lo_leido_fuera_de_la_capa(
            piezas,
            releidas=releidas,
            leidas_por_ocr={p: t for p, t in textos.items() if p in sin_capa and t},
        ),
        # Y el RE de cada reclamo y constancia, por su primera hoja, con de
        # dónde salió: «RE2310…: del sello de la pág. 8».
        "re_en_el_nombre": re_en_el_nombre,
        # La evidencia de cada parámetro, por la primera hoja de su documento.
        "evidencia": {
            "re": evidencia_del_re,
            **_evidencia_de_las_piezas(
                piezas,
                textos,
                releidas,
                con_ia=taller.con_ia(),
                senales={
                    "sello": set(sellos_que_abren),
                    "guia": set(etiquetas) | {p - 1 for p in etiquetas},
                    "formulario": set(formularios_solos),
                    "folio": set(foliacion.abre),
                    "carta": set(que_abren),
                    "acuerdo": set(del_acuerdo),
                    "primera": {1},
                },
            ),
        },
        # El RE a mano de cada sello que se corrigió por el que la caja trae
        # impreso, con lo que se leyó: la auditoría lo puede cruzar.
        "re_corregidos_por_lo_impreso": {str(p): nota for p, nota in corregidos_por_lo_impreso.items()},
        # Los sellos al pie que halló L2b, con lo que se les leyó: la
        # auditoría de cierre los cruza con el papel.
        "sellos_al_pie": {
            str(p): {"radicado": s.radicado, "fecha": s.fecha.isoformat() if s.fecha else None}
            for p, s in sorted(al_pie.items())
        },
        # Sólo el PDF, sin la subcarpeta de la caja: «UPD2998266», no
        # «910349 UPD2998266» (la caja va en «Identificación / Nic»).
        "expediente": document_folder(nombre_del_expediente(taller.name)),
    }
    # Lo que dijeron el revisor de cortes y la comprobación del disco: lo que
    # hay que mirar a la cola, el resumen a los avisos y el detalle aparte.
    # Es lo mismo en todas las habilidades.
    from ...application.perfiles_de_revision import perfil_de
    from ...application.revisor_de_cortes import anotar_en_el_informe

    anotar_en_el_informe(report, revisados, revisor_roto, entregado.comprobacion, perfil=perfil_de(PERFIL).as_dict())
    # Y lo que dijo el revisor de fechas de cada pieza (F7b).
    from .fechas_aseguradas import pasar_al_informe

    pasar_al_informe(report, fechas_revisadas)
    # 4. El Índice Electrónico del cliente, junto a los PDF de la caja y sin
    #    que nadie lo pida. Es el inventario de toda caja de correspondencia y
    #    ocupa el lugar de la planilla de las otras rutas: el archivo recibe un
    #    solo Excel por caja, el suyo.
    _escribir_indice(report, destination, payload)

    _anunciar(payload, Stage.DONE)
    return report
