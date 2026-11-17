"""Los nombres asegurados de cada trabajo: la capa común del revisor de nombres en los workers.

Es el gemelo de ``fechas_aseguradas.py`` (el operador, 2026-11-17: «centralizarlas
y conectarlas a todas las habilidades»). La decisión vive en
``application/revisor_de_nombres.py``; aquí, lo que un trabajo necesita para
usarla:

* **la regla de su habilidad** (``perfil.regla_del_nombre``): dónde está escrito
  el nombre y cómo;
* **el padrón** de la Universidad, leído una vez por trabajo;
* **la IA**, si se eligió: la que mira la imagen (``taller.juez_del_nombre``) y la
  que compara lecturas en texto (``taller.corrector_de_nombres``);
* **el recorte** de las zonas de la regla, para la IA y para la Revisión;
* **lo que queda en el informe**, con la misma forma en todas las habilidades.

Nada de esto tumba el trabajo: lo que falla queda como se leyó, y lo dudoso va a
Revisión. Cancelar sí corta.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable, Hashable, Mapping, Sequence

logger = logging.getLogger(__name__)

#: A cuántos puntos por pulgada se recortan las zonas: la letra a mano se lee y
#: la imagen no pasa de dos mil puntos de ancho.
PPP_DEL_RECORTE = 200


def regla_del_nombre(habilidad: str):
    """La regla del nombre del perfil de la habilidad, o ``None`` si no tiene una persona por documento."""
    from ...application.perfiles_de_revision import perfil_de

    try:
        return perfil_de(habilidad).regla_del_nombre
    except Exception:  # noqa: BLE001 - sin perfil, sin regla
        return None


def padron_del_trabajo(taller):
    """El padrón de la Universidad, listo para buscar; vacío si no hay o no se deja leer."""
    from ...domain.padron import IndiceDelPadron

    ruta = (taller.settings or {}).get("padron_path")
    if not ruta:
        return IndiceDelPadron([])
    try:
        from ...adapters.padron_jsonl import PadronEnArchivo

        return IndiceDelPadron(PadronEnArchivo(ruta).personas())
    except Exception:  # noqa: BLE001 - sin padrón, los nombres se leen igual
        logger.warning("no se pudo leer el padrón %s", ruta, exc_info=True)
        return IndiceDelPadron([])


def jueces_del_trabajo(taller, *, de_pago=True):
    """La IA que mira el renglón y la que compara lecturas, o ``(None, None)`` con «Solo OCR»."""
    from ...application.control import Cancelled

    if not de_pago:
        return None, None
    try:
        return taller.juez_del_nombre(), taller.corrector_de_nombres()
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 - sin IA, lo dudoso va a Revisión
        logger.warning("no se pudo preparar la IA del revisor de nombres", exc_info=True)
        return None, None


def recorte_de_las_zonas(source, pagina: int, regla, siguiente: int | None = None) -> bytes | None:
    """Las zonas de la regla en la hoja ``pagina`` y, si las hay, las de la hoja ``siguiente``, en un JPEG.

    Para la habilidad que no ubica su renglón con Tesseract: la regla dice dónde
    escribe su papel el nombre, en fracción de la hoja.
    """
    from PIL import Image

    from ...application.ports import Band

    piezas = [(pagina, zona) for zona in regla.zonas]
    if siguiente is not None:
        piezas += [(siguiente, zona) for zona in regla.zonas_de_la_siguiente]
    try:
        recortes = [
            Image.open(io.BytesIO(source.render(numero, Band(0.0, arriba, 1.0, abajo), PPP_DEL_RECORTE))).convert("RGB")
            for numero, (arriba, abajo) in piezas
        ]
    except Exception:  # noqa: BLE001 - sin imagen, el nombre queda votado
        logger.debug("no se pudo recortar el nombre de la página %s", pagina, exc_info=True)
        return None
    if not recortes:
        return None
    return apilar(recortes)


def apilar(recortes) -> bytes:
    """Los recortes uno debajo de otro, en un JPEG de dos mil puntos como mucho."""
    from PIL import Image

    ancho = max(recorte.width for recorte in recortes)
    lienzo = Image.new("RGB", (ancho, sum(recorte.height + 10 for recorte in recortes)), "white")
    y = 0
    for recorte in recortes:
        lienzo.paste(recorte, (0, y))
        y += recorte.height + 10
    lienzo.thumbnail((2000, 2000))
    salida = io.BytesIO()
    lienzo.save(salida, "JPEG", quality=85)
    return salida.getvalue()


def asegurar_los_nombres(
    report: dict | None,
    personas: Sequence,
    *,
    taller,
    documento: str,
    conocidas=(),
    padron=None,
    de_pago=True,
    mirar: bool = True,
    releer: Callable[[list[Hashable]], Mapping[Hashable, Sequence[str]]] | None = None,
    a_revision: bool = True,
    a_la_cola: bool = True,
) -> dict:
    """El nombre de cada persona del trabajo, revisado con la pieza común, y lo que queda en su informe.

    ``personas`` son ``PorRevisar`` (``application/revisor_de_nombres.py``). Con
    ``mirar``, la IA mira la imagen de cada una -- a todas, siempre, por
    decisión del operador --; sin él, sólo compara lecturas de lo que nada
    confirma. ``a_la_cola`` lleva lo dudoso a la cola de Revisión; la habilidad
    que ya lleva sus dudas a la cola no lo pide.
    """
    from ...application.control import Cancelled
    from ...application.revisor_de_nombres import (
        anotar_en_el_informe,
        revisar_los_nombres,
    )

    juez, corrector = jueces_del_trabajo(taller, de_pago=de_pago)
    try:
        revisados = revisar_los_nombres(
            personas,
            conocidas=conocidas,
            padron=padron,
            juez=juez if mirar else None,
            corrector=corrector,
            releer=releer,
            a_revision=a_revision,
            control=getattr(taller, "control", None),
            documento=documento,
        )
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 - el revisor nunca tumba el trabajo
        logger.warning("el revisor de nombres falló en %s; quedan como se leyeron", documento, exc_info=True)
        return {}
    if report is not None:
        anotar_en_el_informe(report, revisados, documento, a_la_cola=a_la_cola)
    return revisados
