"""Qué forma un archivo de salida en una caja de correspondencia.

El corte decide dónde termina cada documento, y eso no cambia aquí. Lo que el
operador puede elegir es qué se entrega **después** del corte:

- **un archivo por documento**, que es lo que había y sigue siendo el valor por
  omisión;
- **un archivo por mes**, que lee la fecha de **cada página** y junta en un solo
  PDF todas las páginas del mismo mes, aunque sean de días distintos y en la
  caja estén separadas por otras.

El operador lo llama «por fecha», y lo fue precisando con el papel delante. Sus
palabras, en el orden en que las dijo:

1. «los documentos que tengan la misma fecha, unirlos» -- y al elegir, que se
   unen **todos** los de esa fecha, no sólo los seguidos;
2. «cuando dije por fecha me refería al mismo mes»;
3. «que en cada página la OCR busque la fecha, y las páginas que tengan el mismo
   mes, unirlas; y si encuentras alguna página sin fecha, simplemente únela a la
   anterior».

De ahí las reglas. **Un mes es un archivo**, con las hojas en el orden en que
venían en la caja. **La página sin fecha va con la anterior**; la primera de la
caja, que no tiene anterior, con la siguiente que sí la tenga. La que queda
entre dos meses distintos se declara en la cola de revisión, porque ahí unirla
a la anterior es una elección y no una evidencia -- ante la duda se une, y se
dice. Si ninguna página tiene fecha, la caja sale como siempre, un archivo por
documento, y el informe lo dice.

La fecha de cada página la decide :func:`~resolutions.domain.fechas.fecha_de_la_pagina`.
El texto sale de la capa del PDF cuando la tiene y de la OCR cuando es un
escaneo, que es lo normal en estas cajas: la ruta de correspondencia no leía
con OCR, y sin esto una caja escaneada no tendría una sola fecha.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from ..domain.fechas import fecha_de_la_pagina
from ..domain.grouping import GroupingResult, PageGroup
from ..domain.naming import DOCUMENT_PREFIX
from ..domain.resolution_code import ResolutionCode
from ..domain.tipo_documental import asunto_de, identificar_documento, limpiar
from .control import NullRunControl, RunControl
from .ports import OcrEngine

logger = logging.getLogger(__name__)


class Agrupacion(StrEnum):
    """Qué se entrega como un archivo, una vez cortada la caja."""

    #: Un PDF por documento, tal como sale del corte. Es el valor por omisión
    #: porque es lo que hacía la habilidad antes de que existiera la elección.
    DOCUMENTO = "documento"

    #: Un PDF por mes: todas las páginas fechadas en un mismo mes, juntas.
    MES = "mes"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @classmethod
    def parse(cls, value: str | None) -> Agrupacion:
        """Interpreta lo que llegó por la API. Lo desconocido no se adivina."""
        if value in (None, ""):
            return cls.DOCUMENTO
        try:
            return cls(str(value).strip().lower())
        except ValueError as error:
            opciones = ", ".join(choice.value for choice in cls)
            raise ValueError(
                f"agrupación desconocida: {value!r}; se esperaba una de {opciones}"
            ) from error


_LABELS = {
    Agrupacion.DOCUMENTO: "Un archivo por documento",
    Agrupacion.MES: "Un archivo por mes",
}


def mes_de(fecha: date | str) -> str:
    """El mes de una fecha, en ISO: el 28 de mayo de 2023 es ``2023-05``."""
    return (fecha.isoformat() if isinstance(fecha, date) else fecha)[:7]


# -- leer cada página ---------------------------------------------------------

#: Lo menos que tiene que traer la capa de texto de una página para creerle y
#: no pasarla por OCR. Un escaneo suele traer cero; un PDF nativo, cientos.
MIN_CAPA_DE_TEXTO = 40

#: La resolución a la que se rasteriza una página para buscarle la fecha. La
#: misma que usa el resto del separador para leer una página entera.
DPI_DE_LECTURA = 200


class _Paginas(Protocol):
    @property
    def page_count(self) -> int: ...

    def text_of(self, page_number: int) -> str: ...

    def render(self, page_number: int, band=None, dpi: int = 200) -> bytes: ...


@dataclass(frozen=True, slots=True)
class PaginasLeidas:
    """Lo que dice cada página de sí misma, y cuántas hubo que leer con OCR."""

    #: La fecha que fecha la página, o ``None``.
    fechas: dict[int, date | None]
    #: El tipo del catálogo que declara la página, o ``None``.
    tipos: dict[int, str | None]
    #: Lo que la página declara en su renglón de «Asunto:» o «Ref.:», o ``None``.
    asuntos: dict[int, str | None]
    con_ocr: int


def leer_paginas(
    source: _Paginas,
    ocr: OcrEngine,
    *,
    workers: int = 4,
    control: RunControl | None = None,
    avance: Callable[[int, int], None] | None = None,
) -> PaginasLeidas:
    """La fecha, el tipo y el asunto de cada página.

    Del texto de la página: su capa de texto si la trae, y si no, la OCR. Las
    tres cosas salen de la misma lectura, que es lo que cuesta; el tipo y el
    asunto son los que nombran lo que junta cada archivo por mes, porque en un
    escaneo el corte no tiene texto con qué reconocerlos.

    Se rasteriza en este hilo -- el documento abierto no se comparte entre
    hilos -- y por tandas, para que una caja de cuatrocientas páginas no tenga
    todas sus imágenes en memoria a la vez. La OCR de cada tanda sí va en
    paralelo, que es lo que cuesta.

    Una página que la OCR no pudo leer queda sin fecha y se une a la anterior,
    como cualquier otra sin fecha: un fallo de lectura no para la caja.
    """
    control = control or NullRunControl()
    total = source.page_count
    textos: dict[int, str] = {}
    pendientes: list[int] = []
    for pagina in range(1, total + 1):
        capa = source.text_of(pagina)
        if len(capa.strip()) >= MIN_CAPA_DE_TEXTO:
            textos[pagina] = capa
        else:
            pendientes.append(pagina)

    hechas = len(textos)
    if avance:
        avance(hechas, total)

    def leer(imagen: bytes) -> str:
        try:
            return ocr.read(imagen).text
        except Exception:  # noqa: BLE001 - una página ilegible no para la caja
            logger.warning("no se pudo leer una página para fecharla", exc_info=True)
            return ""

    tanda = max(1, workers) * 2
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for inicio in range(0, len(pendientes), tanda):
            control.check()
            paginas = pendientes[inicio : inicio + tanda]
            imagenes = [source.render(pagina, None, DPI_DE_LECTURA) for pagina in paginas]
            for pagina, texto in zip(paginas, pool.map(leer, imagenes), strict=True):
                textos[pagina] = texto
            hechas += len(paginas)
            if avance:
                avance(hechas, total)

    paginas = range(1, total + 1)
    return PaginasLeidas(
        fechas={pagina: fecha_de_la_pagina(textos[pagina]) for pagina in paginas},
        tipos={pagina: _tipo_de(textos[pagina]) for pagina in paginas},
        asuntos={pagina: asunto_de(textos[pagina]) for pagina in paginas},
        con_ocr=len(pendientes),
    )


def _tipo_de(texto: str) -> str | None:
    encontrado = identificar_documento([texto]) if texto.strip() else None
    return encontrado.nombre if encontrado is not None else None


# -- agrupar por mes ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SinFecha:
    """Una página sin fecha legible que se unió al mes de una vecina."""

    page: int
    #: A qué mes se unió, en ISO: ``2023-05``.
    mes: str
    #: Si se unió a la anterior o, por ser de las primeras de la caja, a la
    #: siguiente con fecha.
    al_anterior: bool
    #: Si está entre dos meses distintos, que es cuando unirla a la anterior es
    #: una elección y no una evidencia, y por eso va a revisión.
    en_frontera: bool

    @property
    def motivo(self) -> str:
        vecina = "el de la página anterior" if self.al_anterior else "el de la siguiente con fecha"
        return f"sin fecha legible: se unió al mes {self.mes}, {vecina}"


@dataclass(frozen=True, slots=True)
class PorMes:
    """La caja agrupada por mes, con lo necesario para contar cómo se hizo."""

    grupos: GroupingResult
    #: Los anexos de cada archivo, reindexados por el código nuevo.
    anexos: dict[str, list[int]]
    #: Cuántas páginas tiene la caja.
    paginas: int
    #: Las páginas sin fecha que se unieron a una vecina.
    sin_fecha: list[SinFecha]
    #: Si se agrupó. Sin una sola página fechada no hay con qué, y la caja sale
    #: como la dejó el corte: un archivo por documento.
    agrupo: bool = True

    @property
    def en_revision(self) -> list[SinFecha]:
        """Las páginas sin fecha que quedaron entre dos meses distintos."""
        return [pagina for pagina in self.sin_fecha if pagina.en_frontera]

    def aviso(self) -> str:
        """Lo que el informe dice de la agrupación, en una frase."""
        if not self.agrupo:
            return (
                "Se pidió un archivo por mes, pero ninguna página de la caja trae una "
                "fecha legible: se entregó un archivo por documento."
            )
        archivos = len(self.grupos.groups)
        frase = (
            f"Agrupado por mes: las {self.paginas} páginas quedaron en {archivos} "
            f"{'archivo' if archivos == 1 else 'archivos'}, uno por mes."
        )
        if self.sin_fecha:
            n = len(self.sin_fecha)
            frase += (
                " 1 página sin fecha se unió a la anterior"
                if n == 1
                else f" {n} páginas sin fecha se unieron a la anterior"
            )
            revisar = len(self.en_revision)
            if revisar:
                frase += (
                    f"; {revisar} de ellas {'queda' if revisar == 1 else 'quedan'} en "
                    "revisión por estar entre dos meses distintos."
                )
            else:
                frase += "."
        return frase


def agrupar_por_mes(
    grupos: GroupingResult,
    fechas: Mapping[int, date | None],
    anexos: dict[str, list[int]] | None = None,
    *,
    tipos: Mapping[int, str | None] | None = None,
    asuntos: Mapping[int, str | None] | None = None,
) -> PorMes:
    """Un archivo por mes, con las hojas en el orden en que venían en la caja.

    ``grupos`` son los documentos del corte: de ellos salen las páginas de la
    caja y, si no se da ``tipos``, el tipo de cada una. ``fechas``, ``tipos`` y
    ``asuntos`` son lo que :func:`leer_paginas` sacó de cada página. ``anexos``
    son las hojas anexas de cada documento, por su código; cada una se traslada
    al archivo en que acabe.

    El título de cada archivo dice qué documentos junta, con su tipo y su
    asunto -- «PETICION: No. RE9411202102942; NOTIFICACION POR AVISO» --, que
    es lo que el operador pidió ver junto al tipo documental: un archivo por
    mes casi siempre mezcla papeles distintos, y «DOCUMENTO» solo no dice nada.

    El código de cada archivo pasa a ser su mes, así que el nombre sale como
    ``2023-05_OFICIO.pdf`` y la carpeta se lista en orden cronológico. La fecha
    del archivo es la más reciente de sus páginas, que es lo que la columna
    «Fecha» del inventario ya significa para cualquier unidad: su fecha extrema
    final.
    """
    anexos = anexos or {}
    asuntos = asuntos or {}
    del_corte: dict[int, str | None] = {}
    for grupo in grupos.groups:
        for pagina in grupo.page_numbers:
            # «DOCUMENTO» es lo que el corte pone cuando no reconoció nada: no
            # es un tipo, es la ausencia de uno.
            del_corte[pagina] = grupo.kind if grupo.kind != DOCUMENT_PREFIX else None
    paginas = sorted(del_corte)
    tipo_de = dict(tipos) if tipos is not None else del_corte

    meses = _meses_efectivos(paginas, fechas)
    if meses is None:
        # Ni una página con fecha: no hay con qué agrupar, y juntar todo lo que
        # no la tiene sería tratar la ausencia de un dato como un mismo mes.
        return PorMes(
            grupos=grupos, anexos=dict(anexos), paginas=len(paginas), sin_fecha=[], agrupo=False
        )

    sin_fecha = _sin_fecha(paginas, fechas, meses)

    por_mes: dict[str, list[int]] = {}
    for pagina in paginas:
        por_mes.setdefault(meses[pagina], []).append(pagina)

    anexas = {pagina for lista in anexos.values() for pagina in lista}
    unidos: list[PageGroup] = []
    anexos_unidos: dict[str, list[int]] = {}
    # En orden de mes: un mes ISO ordena igual como texto que como fecha, y así
    # el orden de los archivos es el mismo en el informe y en la carpeta.
    for mes in sorted(por_mes):
        hojas = por_mes[mes]
        distintos = {tipo_de.get(pagina) for pagina in hojas}
        codigo = ResolutionCode(value=mes, raw=mes)
        unidos.append(
            PageGroup(
                code=codigo,
                page_numbers=hojas,
                title=_titulo(hojas, tipo_de, asuntos),
                # Un tipo sólo cuando todas las hojas lo comparten. Un archivo que
                # junta un oficio y una factura no es ninguna de las dos cosas, y
                # nombrarlo por la primera diría algo que no es cierto; tampoco
                # uno que trae hojas que nadie reconoció.
                kind=(
                    next(iter(distintos))
                    if len(distintos) == 1 and None not in distintos
                    else DOCUMENT_PREFIX
                ),
                fecha=max(
                    fecha for pagina in hojas if (fecha := fechas.get(pagina)) is not None
                ).isoformat(),
            )
        )
        suyas = [pagina for pagina in hojas if pagina in anexas]
        if suyas:
            anexos_unidos[codigo.value] = suyas

    return PorMes(
        grupos=GroupingResult(
            groups=unidos, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs)
        ),
        anexos=anexos_unidos,
        paginas=len(paginas),
        sin_fecha=sin_fecha,
    )


def _meses_efectivos(
    paginas: list[int], fechas: Mapping[int, date | None]
) -> dict[int, str] | None:
    """El mes con que se agrupa cada página, o ``None`` si ninguna tiene fecha.

    El de su fecha cuando la tiene. Si no, el de la anterior; y las primeras de
    la caja, que no tienen anterior, el de la primera que sí la tenga.
    """
    primera = next((fechas[p] for p in paginas if fechas.get(p) is not None), None)
    if primera is None:
        return None
    meses: dict[int, str] = {}
    anterior = mes_de(primera)
    for pagina in paginas:
        fecha = fechas.get(pagina)
        if fecha is not None:
            anterior = mes_de(fecha)
        meses[pagina] = anterior
    return meses


def _sin_fecha(
    paginas: list[int], fechas: Mapping[int, date | None], meses: dict[int, str]
) -> list[SinFecha]:
    """Las páginas sin fecha, cada una con a qué mes se unió y si fue dudoso."""
    resultado: list[SinFecha] = []
    visto_con_fecha = False
    for indice, pagina in enumerate(paginas):
        if fechas.get(pagina) is not None:
            visto_con_fecha = True
            continue
        siguiente = next(
            (mes_de(f) for p in paginas[indice + 1 :] if (f := fechas.get(p)) is not None),
            None,
        )
        resultado.append(
            SinFecha(
                page=pagina,
                mes=meses[pagina],
                al_anterior=visto_con_fecha,
                # Dudosa cuando pudo ser de otro mes: la primera de la caja, que
                # se unió hacia delante, o la que tiene detrás un mes distinto
                # del que tomó. Entre dos páginas del mismo mes no hay elección.
                en_frontera=not visto_con_fecha
                or (siguiente is not None and siguiente != meses[pagina]),
            )
        )
    return resultado


def _titulo(
    paginas: list[int],
    tipos: Mapping[int, str | None],
    asuntos: Mapping[int, str | None],
) -> str:
    """Qué documentos junta el archivo: el tipo y el asunto de cada uno.

    Uno por cada cosa distinta que declaren sus páginas, en el orden de la
    caja: la segunda hoja de una carta no declara nada y no repite a la
    primera. Si ninguna declara nada, de qué hojas salió, por tramos -- «páginas
    1-9» diría que trae hojas que no trae, porque un archivo por mes junta
    páginas que en la caja pueden estar separadas.
    """
    entradas: list[str] = []
    vistas: set[str] = set()
    for pagina in paginas:
        entrada = _entrada(tipos.get(pagina), asuntos.get(pagina))
        if entrada and (clave := limpiar(entrada)) not in vistas:
            vistas.add(clave)
            entradas.append(entrada)
    return "; ".join(entradas) if entradas else _procedencia(paginas)


def _entrada(tipo: str | None, asunto: str | None) -> str | None:
    """«TIPO: asunto», sin repetir en el asunto lo que ya dice el tipo.

    «Citación para notificación personal Radicado número RE94…» con el tipo
    CITACION PARA NOTIFICACION PERSONAL queda en «CITACION PARA NOTIFICACION
    PERSONAL: Radicado número RE94…».
    """
    if not asunto:
        return tipo
    if not tipo:
        return asunto
    palabras_tipo = limpiar(tipo).split()
    palabras = asunto.split()
    if limpiar(" ".join(palabras[: len(palabras_tipo)])) == " ".join(palabras_tipo):
        resto = " ".join(palabras[len(palabras_tipo) :]).lstrip(":.-— ")
        return f"{tipo}: {resto}" if resto else tipo
    return f"{tipo}: {asunto}"


def _procedencia(paginas: list[int]) -> str:
    tramos: list[tuple[int, int]] = []
    for pagina in paginas:
        if tramos and pagina == tramos[-1][1] + 1:
            tramos[-1] = (tramos[-1][0], pagina)
        else:
            tramos.append((pagina, pagina))
    if len(tramos) == 1 and tramos[0][0] == tramos[0][1]:
        return f"página {tramos[0][0]}"
    partes = [str(a) if a == b else f"{a}-{b}" for a, b in tramos]
    return f"páginas {', '.join(partes)}"
