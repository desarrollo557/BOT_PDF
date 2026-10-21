"""El agente de las fechas: la busca hasta encontrarla, de lo barato a lo caro.

Lo pidió el operador el 2026-10-20 ante un índice con «S.F.»: «necesito que el
bot obligue a la OCR o a la IA a captar la fecha; no quiero en el inventario
ningún campo sin data». La mayoría de las que faltaban estaban escritas a mano
sobre un papel impreso: Tesseract lee bien lo impreso, da la hoja por buena, y
la IA nunca entraba aunque la fecha manuscrita saliera ilegible.

Un documento sin fecha se busca así, y cada paso sólo si el anterior no la dio:

1. **El texto ya leído**, hoja por hoja, con todas las reglas de
   :mod:`~resolutions.domain.fechas` (también la del formulario «día:3 mes:5
   del año2021»). Gratis.
2. **Releer en local** las hojas donde más probablemente está -- las que traen
   pistas de una fecha («fecha», «día/mes/año», «Ciudad:», la fórmula de
   firma), la última y la primera --, con Tesseract a más resolución y sin
   filtro de confianza. Gratis.
3. **La IA**, sólo si el operador eligió una lectura con IA (con «Solo OCR» no
   se gasta nada): primero esas hojas y luego las demás, hasta
   ``MAX_HOJAS_CON_IA``.

Si el papel de verdad no trae ninguna -- la copia de una cédula --, quien llama
le pone la de su trámite (:func:`fecha_por_su_tramite`), como lo eligió el
operador: un dato del propio expediente, nunca uno inventado.

Aquí no se lee papel: se recibe con qué releer una hoja.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from ..domain.fechas import fecha_de_la_pagina, pistas_de_fecha

logger = logging.getLogger(__name__)

#: Cuántas hojas de un documento se releen en local como mucho.
MAX_RELECTURAS = 3
#: Cuántas hojas de un documento se le pasan a la IA como mucho. Obligarla a
#: buscar no es pagar un libro entero por una fecha.
MAX_HOJAS_CON_IA = 8


@dataclass(frozen=True, slots=True)
class FechaHallada:
    fecha: date
    #: La hoja de la que salió, o ``None`` si vino de otro documento.
    pagina: int | None
    #: «texto», «ocr», «ia» o «tramite».
    via: str

    def como(self) -> str:
        """De dónde salió, dicho para el informe."""
        donde = f" en la pág. {self.pagina}" if self.pagina else ""
        return {
            "texto": f"leída del texto{donde}",
            "ocr": f"releída con OCR{donde}",
            "ia": f"leída por la IA{donde}",
            "tramite": f"la de su trámite (pág. {self.pagina})" if self.pagina else "la de su trámite",
        }.get(self.via, self.via)


class AgenteDeFechas:
    """Busca la fecha de un documento hasta encontrarla, sin gastar IA si no se pidió."""

    def __init__(
        self,
        *,
        releer: Callable[[int], str] | None = None,
        leer_con_ia: Callable[[int], str] | None = None,
        no_fecha: Callable[[str], bool] | None = None,
        max_relecturas: int = MAX_RELECTURAS,
        max_hojas_con_ia: int = MAX_HOJAS_CON_IA,
    ) -> None:
        self._releer = releer
        self._leer_con_ia = leer_con_ia
        #: La hoja que no fecha el documento aunque traiga fechas: la copia de
        #: una cédula (su fecha es la de nacimiento).
        self._no_fecha = no_fecha or (lambda _texto: False)
        self._max_relecturas = max_relecturas
        self._max_hojas_con_ia = max_hojas_con_ia
        #: Lo ya releído, por hoja: una hoja no se paga dos veces.
        self._releidas: dict[tuple[str, int], str] = {}

    @property
    def usa_ia(self) -> bool:
        return self._leer_con_ia is not None

    def buscar(self, paginas: Sequence[int], textos: Mapping[int, str]) -> FechaHallada | None:
        """La fecha del documento de ``paginas``, o ``None`` si el papel no trae ninguna."""
        # Las hojas que no fechan nada -- la copia de una cédula -- no se miran.
        paginas = [p for p in paginas if not self._no_fecha(textos.get(p, "") or "")]
        for pagina in paginas:
            fecha = fecha_de_la_pagina(textos.get(pagina, "") or "")
            if fecha is not None:
                return FechaHallada(fecha, pagina, "texto")
        orden = candidatas(paginas, textos)
        if self._releer is not None:
            for pagina in orden[: self._max_relecturas]:
                hallada = self._con(self._releer, "ocr", pagina)
                if hallada is not None:
                    return hallada
        if self._leer_con_ia is not None:
            for pagina in orden[: self._max_hojas_con_ia]:
                hallada = self._con(self._leer_con_ia, "ia", pagina)
                if hallada is not None:
                    return hallada
        return None

    def _con(self, leer: Callable[[int], str], via: str, pagina: int) -> FechaHallada | None:
        clave = (via, pagina)
        if clave not in self._releidas:
            try:
                self._releidas[clave] = leer(pagina) or ""
            except Exception:  # noqa: BLE001 - una hoja que no se deja releer no tumba nada
                logger.warning("no se pudo releer la pág. %s buscando su fecha (%s)", pagina, via, exc_info=True)
                self._releidas[clave] = ""
        texto = self._releidas[clave]
        # Releída, puede resultar ser una cédula que la primera lectura no dejó ver.
        if self._no_fecha(texto):
            return None
        fecha = fecha_de_la_pagina(texto)
        return FechaHallada(fecha, pagina, via) if fecha is not None else None


def candidatas(paginas: Sequence[int], textos: Mapping[int, str]) -> list[int]:
    """Las hojas en el orden en que conviene buscar la fecha.

    Primero las que traen pistas de una fecha, de más a menos; luego la última
    -- la de las firmas, donde va la fecha de un contrato o un acta -- y la
    primera -- la del encabezado de una carta --; luego las demás, en orden.
    """
    lista = list(paginas)
    if not lista:
        return []
    con_pistas = sorted(
        (p for p in lista if pistas_de_fecha(textos.get(p, "") or "")),
        key=lambda p: -pistas_de_fecha(textos.get(p, "") or ""),
    )
    orden: list[int] = []
    for pagina in [*con_pistas, lista[-1], lista[0], *lista]:
        if pagina not in orden:
            orden.append(pagina)
    return orden


def fecha_por_su_tramite(
    posicion: int, fechas: Sequence[date | None], archivos: Sequence[object]
) -> tuple[date, int] | None:
    """La fecha de su trámite para un documento sin ninguna: (fecha, posición de donde salió).

    La del documento con el que viaja: primero uno fechado del mismo archivo
    (el escrito radicado al que acompaña), y si no hay, el fechado más cercano
    del expediente -- a igual distancia, el anterior, que es al que se une --.
    Lo eligió el operador el 2026-10-20: un dato del propio expediente.
    """
    mismo = [
        i for i, fecha in enumerate(fechas) if fecha is not None and archivos[i] == archivos[posicion]
    ]
    if mismo:
        cercano = min(mismo, key=lambda i: (abs(i - posicion), i > posicion))
        return fechas[cercano], cercano  # type: ignore[return-value]
    fechadas = [i for i, fecha in enumerate(fechas) if fecha is not None]
    if not fechadas:
        return None
    cercano = min(fechadas, key=lambda i: (abs(i - posicion), i > posicion))
    return fechas[cercano], cercano  # type: ignore[return-value]
