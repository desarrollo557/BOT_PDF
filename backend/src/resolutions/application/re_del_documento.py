"""El RE de cada documento, buscado en el sello de cualquiera de sus hojas.

Lo pidió el operador el 2026-10-21 al ver la entrega de UPD3102756, donde de
trece archivos sólo uno llevaba su RE: «búscalo en los sellos, ya sea que estén
a mano o digitalizados… necesito que todo quede bien referenciado y
estructurado», con el nombre «número, título y RE». Y después: «que el bot
busque el sello en todas las páginas del grupo de PDF, y en la que lo encuentre
le jale el número de RE, pero de una manera más óptima».

Corre al final, sobre los documentos ya cortados, y no mueve ninguna hoja: sólo
pone el RE en el código de cada documento que no lo trae. De lo más barato a lo
más caro, y se para en cuanto lo encuentra:

1. **El sello que ya se leyó** en cualquiera de sus hojas (no el de una copia
   aportada como prueba). No cuesta nada.
2. **La carta de la empresa** -- su respuesta, su citación -- trae impreso el
   RE del trámite que contesta. Tampoco cuesta.
3. **El OCR de casa**, sólo donde la capa de texto ubica un sello y en la
   cabecera de la primera hoja, que es donde va la etiqueta impresa. Su lectura
   vale si es de la etiqueta o un RE que la caja ya conoce: la letra a mano la
   lee mal, y un RE equivocado en el nombre es peor que ninguno.
4. **La IA, una sola vez por documento**, y sólo si el operador eligió «OCR +
   IA»: un mosaico con los recortes de **todas** las hojas donde puede estar el
   sello -- el sello ubicado, el pie de cada hoja de la carta, el pie de las
   demás hojas y la cabecera de la primera --, que la IA lee como una página.
   Sin cédulas, facturas ni copias, que no llevan el sello del escrito.

Todo RE leído tiene que cuadrar con el año de la carta. Lo que nada de eso deja
leer se queda sin RE: no se adivina. El acuerdo de pago no lleva RE, y lo que
no abre con una carta ni trae un sello no gasta IA.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date

from ..domain.grouping import GroupingResult
from ..domain.sello import Sello, radicado_escrito
from .ports import Band, OcrEngine

logger = logging.getLogger(__name__)

#: Dónde se busca el sello en una hoja: el pie, a la derecha -- el sello de
#: tinta con el RE a mano encima --, y la cabecera -- la etiqueta impresa, o el
#: sello que se estampó arriba --.
PIE = Band(0.30, 0.40, 1.0, 1.0)
CABECERA = Band(0.30, 0.0, 1.0, 0.30)
#: A cuánto lee el OCR de casa un sello ubicado o una cabecera.
PPP_LOCAL = 300
#: Cuántos recortes entran en el mosaico que lee la IA: los primeros, por
#: orden de dónde es más probable el sello. Más recortes achican la letra.
MAX_RECORTES_EN_EL_MOSAICO = 6
#: Tras la palabra NUMERO o CITE de la etiqueta impresa: ahí la lectura de
#: casa es fiable.
_DE_LA_ETIQUETA = re.compile(r"N\W?U\W?M\W?E\W?R\W?[O0]|C\W?I\W?T\W?E", re.IGNORECASE)

#: Un recorte: la hoja y la banda.
Recorte = tuple[int, Band]


@dataclass
class ReDeLosDocumentos:
    """Los documentos con su RE y de dónde salió cada uno."""

    grupos: GroupingResult
    #: Primera hoja del documento → «RE…: del sello de la pág. 8».
    halladas: dict[int, str] = field(default_factory=dict)
    #: El código viejo de cada documento que cambió → el nuevo, para sus anexos.
    renombrados: dict[str, str] = field(default_factory=dict)
    #: Cuántas lecturas se le pidieron a la IA: una por documento, como mucho.
    lecturas_con_ia: int = 0


def recortes_del_mosaico(
    paginas: list[int],
    carta: list[int],
    ubicados: list[Recorte],
    descartadas: set[int] | frozenset[int],
) -> list[Recorte]:
    """Dónde puede estar el sello del documento, de lo más probable a lo menos.

    El sello que la capa ubicó; el pie de la hoja de firmas y de las demás hojas
    de la carta; la cabecera de la primera hoja; y el pie de las demás hojas
    del documento, menos las ``descartadas`` -- cédulas, facturas, copias --.
    """
    orden: list[Recorte] = list(ubicados)
    orden += [(p, PIE) for p in reversed(carta)]
    orden.append((paginas[0], CABECERA))
    orden += [(p, PIE) for p in paginas if p not in carta and p not in descartadas]
    vistos: list[Recorte] = []
    for recorte in orden:
        if recorte not in vistos:
            vistos.append(recorte)
    return vistos[:MAX_RECORTES_EN_EL_MOSAICO]


def poner_los_re(
    grupos: GroupingResult,
    *,
    sellos: Mapping[int, Sello],
    copias: frozenset[int] | set[int],
    sin_re: frozenset[int] | set[int],
    descartadas: frozenset[int] | set[int],
    de_la_carta: Callable[[list[int]], list[int]],
    de_la_empresa: Callable[[list[int]], str | None],
    fecha_de: Callable[[list[int]], date | None],
    ubicar: Callable[[int], Band | None],
    render: Callable[[int, Band, int], bytes],
    mosaico: Callable[[list[Recorte]], bytes],
    local: OcrEngine,
    de_pago: OcrEngine | None,
    conocidos: frozenset[str] | set[str] = frozenset(),
) -> ReDeLosDocumentos:
    """Cada documento con el RE de su sello en el código: «01 RE2310202321592».

    ``sin_re`` son las hojas de lo que no lleva RE -- el acuerdo de pago --;
    ``descartadas``, las que no llevan el sello del escrito -- cédulas,
    facturas, copias --; ``de_la_carta``, las hojas de la carta del cliente con
    que abre el documento -- la primera y las que la siguen -- o ``[]``;
    ``de_la_empresa``, el RE que cita la carta de la empresa, si lo es;
    ``fecha_de``, la fecha de la carta, con la que se comprueba el año del RE;
    ``ubicar``, dónde ubica la capa de texto el sello de una hoja.
    """
    salida = []
    halladas: dict[int, str] = {}
    renombrados: dict[str, str] = {}
    con_ia = 0
    for grupo in grupos.groups:
        valor = grupo.code.value
        numero, _, resto = valor.partition(" ")
        paginas = list(grupo.page_numbers)
        if resto.startswith(("RE", "P")) or not numero.isdigit() or paginas[0] in sin_re:
            salida.append(grupo)
            continue
        radicado, como = None, ""
        # 1. El sello que ya se leyó, en cualquiera de sus hojas.
        for p in paginas:
            if p in sellos and p not in copias and sellos[p].radicado:
                radicado, como = sellos[p].radicado, f"del sello de la pág. {p}"
                break
        carta = de_la_carta(paginas) if radicado is None else []
        # 2. La carta de la empresa trae el RE que contesta.
        if radicado is None and not carta:
            citado = de_la_empresa(paginas)
            if citado:
                radicado, como = citado, "el que cita la carta de la empresa"
        ubicados: list[Recorte] = []
        if radicado is None:
            for p in paginas:
                if p in copias:
                    continue
                banda = ubicar(p) if (p in sellos or p not in descartadas) else None
                if banda is not None:
                    ubicados.append((p, banda))
                elif p in sellos:
                    # Detectado por la lectura de la cabecera y no por la capa.
                    ubicados.append((p, CABECERA))
        fecha = fecha_de(carta or paginas) if radicado is None else None
        anio = fecha.year if fecha else None
        # 3. El OCR de casa, sólo en los sellos ubicados y la cabecera.
        if radicado is None and (carta or ubicados):
            for pagina, banda in [*ubicados, (paginas[0], CABECERA)]:
                try:
                    texto = local.read(render(pagina, banda, PPP_LOCAL)).text
                except Exception:  # noqa: BLE001 - un recorte ilegible no para la caja
                    continue
                leido = radicado_escrito(texto, anio)
                if leido and (leido in conocidos or _DE_LA_ETIQUETA.search(texto)):
                    radicado, como = leido, f"de la etiqueta de la pág. {pagina}"
                    break
        # 4. La IA, una vez, con el mosaico de todas las hojas donde puede estar.
        if radicado is None and de_pago is not None and (carta or ubicados):
            recortes = recortes_del_mosaico(paginas, carta, ubicados, set(descartadas) | set(copias))
            try:
                con_ia += 1
                texto = de_pago.read(mosaico(recortes)).text
                leido = radicado_escrito(texto, anio)
                if leido:
                    hojas = ", ".join(str(p) for p in sorted({p for p, _ in recortes}))
                    radicado, como = leido, f"del sello, leído con IA en las págs. {hojas}"
            except Exception:  # noqa: BLE001 - se queda sin RE, no se adivina
                logger.warning("la IA no leyó los sellos del documento de la pág. %s", paginas[0], exc_info=True)
        if radicado is None:
            salida.append(grupo)
            continue
        halladas[paginas[0]] = f"{radicado}: {como}"
        nuevo = f"{numero} {radicado}"
        renombrados[valor] = nuevo
        salida.append(replace(grupo, code=type(grupo.code)(value=nuevo, raw=radicado)))
    return ReDeLosDocumentos(
        grupos=replace(grupos, groups=salida), halladas=halladas, renombrados=renombrados, lecturas_con_ia=con_ia
    )
