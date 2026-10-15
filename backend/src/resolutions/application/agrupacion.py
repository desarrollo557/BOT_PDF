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
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Protocol

from ..domain.fechas import fecha_de_la_pagina
from ..domain.grouping import GroupingResult, PageGroup
from ..domain.naming import DOCUMENT_PREFIX
from ..domain.resolution_code import ResolutionCode
from ..domain.sello import Sello, es_radicado_de_la_superintendencia
from ..domain.tipo_documental import asunto_de, identificar_documento, limpiar
from ..domain.tramites import (
    abre_un_tramite,
    despues_de_la_ventana,
    donde_aparece_la_persona,
    en_ventana,
    es_cedula,
    es_reclamo,
    fecha_del_sello,
    lleva_sello_de_radicacion,
    nic_de,
    nic_mas_comun,
    radicado_de,
    radicado_del_sello,
    radicados_de,
    radicados_parecidos,
)
from .control import NullRunControl, RunControl, hilos, mapear
from .ports import OcrEngine

logger = logging.getLogger(__name__)


class Agrupacion(StrEnum):
    """Qué se entrega como un archivo, una vez cortada la caja."""

    #: Un PDF por documento, tal como sale del corte. Es el valor por omisión
    #: porque es lo que hacía la habilidad antes de que existiera la elección.
    DOCUMENTO = "documento"

    #: Un PDF por mes: todas las páginas fechadas en un mismo mes, juntas.
    MES = "mes"

    #: Un PDF por trámite: la solicitud, cada reclamación con su respuesta y su
    #: notificación, cada una con sus anexos. Se reconoce por el radicado, y la
    #: fecha decide a qué trámite van las hojas que no lo traen.
    TRAMITE = "tramite"

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
    Agrupacion.TRAMITE: "Un archivo por trámite",
}


def mes_de(fecha: date | str) -> str:
    """El mes de una fecha, en ISO: el 28 de mayo de 2023 es ``2023-05``."""
    return (fecha.isoformat() if isinstance(fecha, date) else fecha)[:7]


# -- leer cada página ---------------------------------------------------------

#: Lo menos que tiene que traer la capa de texto de una página para creerle y
#: no pasarla por OCR. Un escaneo suele traer cero; un PDF nativo, cientos.
MIN_CAPA_DE_TEXTO = 40
#: Menos palabras que éstas en lo que leyó la OCR y la página se vuelve a leer
#: con ``releer``: es la fotocopia gris de una cédula, de la que la lectura de
#: página entera saca diez manchas y ni un nombre.
MIN_PALABRAS_LEIDAS = 15
#: A cuánto se rasteriza esa segunda lectura: la letra de una cédula es chica.
DPI_DE_RELECTURA = 300

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
    #: El texto de cada página, de su capa o de la OCR: de él salen el radicado
    #: y el NIC cuando se agrupa por trámite.
    textos: dict[int, str] = field(default_factory=dict)


def leer_paginas(
    source: _Paginas,
    ocr: OcrEngine,
    *,
    workers: int = 4,
    control: RunControl | None = None,
    avance: Callable[[int, int], None] | None = None,
    marcar: Callable[[int, str], None] | None = None,
    releer: OcrEngine | None = None,
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

    ``marcar`` recibe cada página con de dónde salió su texto -- la capa o la
    OCR --, para pintar la cinta de la pantalla con lo que de verdad se leyó.

    ``releer`` es una segunda lectura, más fina, sólo para las páginas de las
    que la primera no sacó casi nada: se queda la que traiga más palabras. Es
    la que le pone nombre y número a la fotocopia de una cédula, y con eso se
    comprueba de qué trámite es.
    """
    control = control or NullRunControl()
    total = source.page_count
    textos: dict[int, str] = {}
    pendientes: list[int] = []
    for pagina in range(1, total + 1):
        capa = source.text_of(pagina)
        if len(capa.strip()) >= MIN_CAPA_DE_TEXTO:
            textos[pagina] = capa
            if marcar:
                marcar(pagina, "text_layer")
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
    with hilos(max(1, workers)) as pool:
        for inicio in range(0, len(pendientes), tanda):
            control.check()
            paginas = pendientes[inicio : inicio + tanda]
            imagenes = [source.render(pagina, None, DPI_DE_LECTURA) for pagina in paginas]
            for pagina, texto in zip(paginas, mapear(pool, leer, imagenes, control), strict=True):
                textos[pagina] = texto
                if marcar:
                    marcar(pagina, "ocr_full_page")
            hechas += len(paginas)
            if avance:
                avance(hechas, total)

        mudas = [p for p in pendientes if _palabras(textos[p]) < MIN_PALABRAS_LEIDAS]
        if releer is not None and mudas:

            def de_nuevo(imagen: bytes) -> str:
                try:
                    return releer.read(imagen).text
                except Exception:  # noqa: BLE001 - se queda la primera lectura
                    logger.warning("no se pudo releer una página", exc_info=True)
                    return ""

            for inicio in range(0, len(mudas), tanda):
                control.check()
                paginas = mudas[inicio : inicio + tanda]
                imagenes = [source.render(p, None, DPI_DE_RELECTURA) for p in paginas]
                for pagina, texto in zip(
                    paginas, mapear(pool, de_nuevo, imagenes, control), strict=True
                ):
                    if _palabras(texto) > _palabras(textos[pagina]):
                        textos[pagina] = texto

    paginas = range(1, total + 1)
    return PaginasLeidas(
        fechas={pagina: fecha_de_la_pagina(textos[pagina]) for pagina in paginas},
        tipos={pagina: _tipo_de(textos[pagina]) for pagina in paginas},
        asuntos={pagina: asunto_de(textos[pagina]) for pagina in paginas},
        con_ocr=len(pendientes),
        textos=textos,
    )


def _palabras(texto: str) -> int:
    """Cuántas palabras de verdad -- tres letras o más -- trae una lectura."""
    return sum(1 for palabra in texto.split() if sum(c.isalpha() for c in palabra) >= 3)


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


# -- agrupar por trámite --------------------------------------------------------

#: Cómo se llama el trámite cuyo radicado no se pudo leer.
SIN_RADICADO = "SIN-RADICADO"


@dataclass(frozen=True, slots=True)
class HojaSuelta:
    """Una página cuyo trámite alguien tiene que mirar, con el porqué.

    Sin ``razon`` es la de siempre: una hoja sin radicado ni fecha que se dejó
    con la anterior justo antes de otro trámite. Con ella, lo que encontró una
    de las comprobaciones de ``_validar_tramites``.
    """

    page: int
    tramite: str
    razon: str | None = None
    #: De qué trámite se sacó, si una comprobación la movió.
    venia_de: str | None = None

    @property
    def motivo(self) -> str:
        if self.razon:
            return self.razon
        return (
            f"sin radicado ni fecha que lo confirme: se dejó en el trámite {self.tramite}, "
            "el de la página anterior"
        )


@dataclass(frozen=True, slots=True)
class PorTramite:
    """La caja agrupada por trámite, con lo necesario para contar cómo se hizo."""

    grupos: GroupingResult
    anexos: dict[str, list[int]]
    paginas: int
    #: Las hojas sin radicado ni fecha útil que quedaron justo antes de otro
    #: trámite: ahí dejarlas en el anterior fue una elección.
    en_revision: list[HojaSuelta]
    #: Cuántas páginas sin radicado se movieron a otro trámite por su fecha.
    por_fecha: int = 0
    agrupo: bool = True
    #: Las páginas que una comprobación sacó del trámite donde las dejó el
    #: recorrido: su NIC, su fecha o la persona de su cédula eran de otro.
    movidas: int = 0

    def aviso(self, archivos: int | None = None) -> str:
        """``archivos`` son los que de verdad se escriben: manda el sello, y un
        trámite puede salir en varios documentos. Sin él, los trámites."""
        if not self.agrupo:
            return (
                "Se pidió un archivo por trámite, pero ninguna página trae un radicado "
                "legible (RE… o P…): se entregó un archivo por documento."
            )
        tramites = len(self.grupos.groups)
        archivos = tramites if archivos is None else archivos
        frase = (
            f"Agrupado por trámite: las {self.paginas} páginas quedaron en {archivos} "
            f"{'archivo' if archivos == 1 else 'archivos'}"
            + (
                ", uno por radicado."
                if archivos == tramites
                else f" de {tramites} {'trámite' if tramites == 1 else 'trámites'}: cada sello abre su documento."
            )
        )
        if self.por_fecha:
            frase += (
                f" {self.por_fecha} "
                f"{'página sin radicado fue' if self.por_fecha == 1 else 'páginas sin radicado fueron'}"
                " al trámite que les correspondía por su fecha."
            )
        if self.movidas:
            frase += (
                f" {self.movidas} "
                f"{'página estaba' if self.movidas == 1 else 'páginas estaban'}"
                " en un trámite que no era el suyo y se "
                f"{'movió' if self.movidas == 1 else 'movieron'} al que la nombra."
            )
        if self.en_revision:
            n = len(self.en_revision)
            frase += f" {n} {'queda' if n == 1 else 'quedan'} en revisión."
        return frase


def agrupar_por_tramite(
    grupos: GroupingResult,
    leidas: PaginasLeidas,
    anexos: dict[str, list[int]] | None = None,
    retenidas: Mapping[int, int] | None = None,
    sellos: Mapping[int, Sello] | None = None,
) -> PorTramite:
    """Un archivo por trámite: el radicado lo abre y la fecha reparte lo demás.

    ``retenidas`` son las hojas que la lista de «ANEXOS» de un escrito unió a
    él, con la hoja de la lista: van al trámite de su escrito pase lo que pase,
    porque el cliente escribió que las traía.

    ``sellos`` son los sellos de radicación leídos aparte, por hoja: su RE
    manda sobre el que se lea en la página -- la página entera no ve la letra
    de la etiqueta --, y una etiqueta con el número ilegible abre trámite
    igual, hasta el próximo RE o el próximo sello.

    Las reglas, en el orden en que se aplican a cada página de la caja:

    1. **Con radicado** (RE… o P…): va a su trámite. Uno nuevo lo abre; uno ya
       visto -- la segunda copia de una portada -- vuelve al suyo.
    2. **Sin radicado**: va con el trámite abierto, salvo que su fecha no
       encaje en él y sí en el que viene detrás, que es donde se mueve (la
       cédula y las facturas que se anexan antes de la constancia).
    3. **Una hoja que abre un trámite** -- constancia, derecho de petición,
       portada -- sin radicado legible y con una fecha que no encaja en el
       abierto abre uno «SIN-RADICADO», fechado con la suya.

    La ventana de un trámite va de ``DIAS_ANTES`` antes de su fecha a
    ``DIAS_DESPUES`` después. La fecha del trámite es la que más se repite
    entre sus hojas con radicado: la constancia dice el plazo de respuesta y
    la respuesta y la notificación dicen el día del trámite.

    Ante la duda se une: una hoja sin radicado y sin fecha queda en el trámite
    abierto, y si es la última antes de otro trámite se declara en revisión.

    Y después se comprueba que ninguna hoja quedó donde no es -- ver
    ``_validar_tramites`` --: lo que la contradice con pruebas se mueve al
    trámite que la nombra, y lo que no se puede probar se declara.

    La fecha de una cédula no cuenta: la de nacimiento y la de expedición no
    dicen nada de cuándo se anexó.
    """
    anexos = anexos or {}
    textos = leidas.textos
    fechas = leidas.fechas
    paginas = sorted(p for grupo in grupos.groups for p in grupo.page_numbers)
    radicado = {p: radicado_de(textos.get(p, "")) for p in paginas}
    sellos = sellos or {}
    for p, sello in sellos.items():
        if p in radicado and sello.radicado:
            radicado[p] = sello.radicado
    # Y el del sello que la OCR rompió -- «NUMF.nORK3110202139039» --, rehecho
    # con la oficina de los radicados bien leídos de la caja. Dos vueltas: lo
    # que se rehízo en la primera también dice cuál es la oficina.
    for _ in range(2):
        oficinas = Counter(r[2:6] for r in radicado.values() if r and r.startswith("RE"))
        for p in paginas:
            if radicado[p] is None:
                radicado[p] = radicado_del_sello(textos.get(p, ""), oficinas)
    if not any(radicado.values()):
        return PorTramite(
            grupos=grupos, anexos=dict(anexos), paginas=len(paginas), en_revision=[], agrupo=False
        )

    cedulas = {p for p in paginas if es_cedula(textos.get(p, ""))}
    fechas = {p: None if p in cedulas else fechas.get(p) for p in paginas}

    fecha_de: dict[str, date | None] = {}
    for clave in dict.fromkeys(r for r in radicado.values() if r):
        suyas = [fechas.get(p) for p in paginas if radicado[p] == clave and fechas.get(p)]
        cuenta = Counter(suyas)
        fecha_de[clave] = (
            max(cuenta, key=lambda f: (cuenta[f], -f.toordinal())) if cuenta else None
        )
        if fecha_de[clave] is None:
            # La del sello, aunque la OCR le haya cortado el año: el radicado
            # lo trae entero.
            fecha_de[clave] = next(
                (
                    f
                    for p in paginas
                    if radicado[p] == clave
                    and (f := fecha_del_sello(textos.get(p, ""), clave)) is not None
                ),
                None,
            )

    def siguiente_con_radicado(desde: int, distinto_de: str | None) -> str | None:
        return next(
            (radicado[p] for p in paginas[desde + 1 :] if radicado[p] and radicado[p] != distinto_de),
            None,
        )

    def encaja(fecha: date | None, clave: str | None) -> bool:
        del_tramite = fecha_de.get(clave) if clave else None
        return fecha is not None and del_tramite is not None and en_ventana(fecha, del_tramite)

    asignada: dict[int, str] = {}
    sin_evidencia: list[int] = []
    sellos_ilegibles: list[HojaSuelta] = []
    abiertos_por_sello: set[str] = set()
    previas: list[int] = []
    actual: str | None = None
    por_fecha = 0
    for indice, pagina in enumerate(paginas):
        propio = radicado[pagina]
        if propio:
            actual = propio
            asignada[pagina] = propio
            continue
        fecha = fechas.get(pagina)
        texto = textos.get(pagina, "")
        sello = sellos.get(pagina)
        de_la_sspd = (sello is not None and sello.clase == "sspd") or es_radicado_de_la_superintendencia(
            texto
        )
        if (
            lleva_sello_de_radicacion(texto)
            or de_la_sspd
            or (sello is not None and sello.clase == "impreso")
        ):
            # Un escrito radicado abre su propio documento aunque no se haya
            # podido leer su número: el sello está. Va antes que la fecha
            # porque manda más que ella (UPD2320043 p8).
            nuevo = f"{SIN_RADICADO}-{fecha.isoformat() if fecha else f'HOJA-{pagina}'}"
            fecha_de[nuevo] = fecha
            actual = nuevo
            asignada[pagina] = nuevo
            abiertos_por_sello.add(nuevo)
            if de_la_sspd:
                # El radicado de la Superintendencia: el escrito abre, pero no
                # hay RE que leer ni que escribir a mano.
                continue
            sellos_ilegibles.append(
                HojaSuelta(
                    page=pagina,
                    tramite=nuevo,
                    razon="trae sello de radicación pero el número RE no se pudo leer: "
                    "abre un trámite sin radicado hasta el próximo sello o RE; "
                    "escriba el RE a mano",
                )
            )
            continue
        if actual is None:
            previas.append(pagina)
            continue
        if actual in abiertos_por_sello:
            # Lo dictó el operador: cuando no se lee el RE del sello, no se
            # parte por radicado ni por fecha; lo que sigue es de ese escrito
            # hasta la página con un sello nuevo o un RE nuevo.
            asignada[pagina] = actual
            continue
        siguiente = siguiente_con_radicado(indice, actual)
        if fecha is not None and not encaja(fecha, actual) and encaja(fecha, siguiente):
            actual = siguiente
            asignada[pagina] = siguiente
            por_fecha += 1
            continue
        if (
            fecha is not None
            and abre_un_tramite(texto)
            and not encaja(fecha, actual)
            and fecha_de.get(actual) is not None
        ):
            nuevo = f"{SIN_RADICADO}-{fecha.isoformat()}"
            fecha_de[nuevo] = fecha
            actual = nuevo
            asignada[pagina] = nuevo
            continue
        asignada[pagina] = actual
        if fecha is None or not encaja(fecha, actual):
            sin_evidencia.append(pagina)
    # Lo que va antes del primer radicado -- una portada, una carátula -- es del
    # primer trámite.
    primero = next(r for r in (radicado[p] for p in paginas) if r)
    for pagina in previas:
        asignada[pagina] = primero

    frontera = [
        HojaSuelta(page=pagina, tramite=asignada[pagina])
        for pagina in sin_evidencia
        if (despues := next((asignada[p] for p in paginas if p > pagina), None)) is not None
        and despues != asignada[pagina]
    ]
    reparos = _validar_tramites(paginas, asignada, radicado, textos, fechas, fecha_de, cedulas)
    retenidas = retenidas or {}
    # Lo que la lista de anexos retuvo no lo mueve ninguna comprobación: la
    # lista es la palabra del cliente, y vale más que una fecha que encaja.
    reparos = [reparo for reparo in reparos if reparo.page not in retenidas]
    for reparo in reparos:
        asignada[reparo.page] = reparo.tramite
    for pagina, ancla in retenidas.items():
        if pagina in asignada and ancla in asignada:
            asignada[pagina] = asignada[ancla]
    con_reparo = {reparo.page for reparo in reparos}
    en_revision = sorted(
        reparos
        + [hoja for hoja in sellos_ilegibles if hoja.page not in con_reparo]
        + [hoja for hoja in frontera if hoja.page not in con_reparo and hoja.page not in retenidas],
        key=lambda hoja: hoja.page,
    )
    orden = list(dict.fromkeys(asignada[p] for p in paginas))

    anexas = {pagina for lista in anexos.values() for pagina in lista}
    unidos: list[PageGroup] = []
    anexos_unidos: dict[str, list[int]] = {}
    for puesto, clave in enumerate(orden, start=1):
        hojas = [p for p in paginas if asignada[p] == clave]
        # La de su radicación; y si ninguna hoja con radicado trae una fecha
        # legible -- el radicado sólo se leyó en la guía de entrega --, la de
        # la primera hoja fechada, que es la del escrito que abre el trámite:
        # «Valledupar, diciembre 02 de 2020». Las cédulas ya no tienen fecha.
        del_tramite = fecha_de.get(clave) or next(
            (fechas[p] for p in hojas if fechas.get(p)), None
        )
        rotulo = f"{puesto:02d} {clave}" + (
            f" {del_tramite.strftime('%d-%m-%Y')}" if del_tramite and SIN_RADICADO not in clave else ""
        )
        codigo = ResolutionCode(value=rotulo, raw=clave)
        nic = nic_mas_comun(nic_de(textos.get(p, "")) for p in hojas)
        cabeza = f"Trámite {clave}" + (f" del {del_tramite.strftime('%d-%m-%Y')}" if del_tramite else "")
        if nic:
            cabeza += f" (NIC {nic})"
        unidos.append(
            PageGroup(
                code=codigo,
                page_numbers=hojas,
                title=f"{cabeza}: {_titulo(hojas, leidas.tipos, leidas.asuntos)}",
                kind=_tipo_del_tramite(clave, hojas, textos, leidas.tipos),
                fecha=_fecha_del_tramite(del_tramite),
            )
        )
        suyas = [p for p in hojas if p in anexas]
        if suyas:
            anexos_unidos[codigo.value] = suyas

    return PorTramite(
        grupos=GroupingResult(
            groups=unidos, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs)
        ),
        anexos=anexos_unidos,
        paginas=len(paginas),
        en_revision=en_revision,
        por_fecha=por_fecha,
        movidas=sum(1 for reparo in reparos if reparo.venia_de),
    )


def _validar_tramites(
    paginas: list[int],
    asignada: dict[int, str],
    radicado: dict[int, str | None],
    textos: Mapping[int, str],
    fechas: Mapping[int, date | None],
    fecha_de: Mapping[str, date | None],
    cedulas: set[int],
) -> list[HojaSuelta]:
    """Que ninguna página quede en un trámite que no es el suyo.

    El recorrido reparte por el radicado y la fecha; aquí se comprueba cada
    hoja contra lo que ella misma dice, y se pregunta, en este orden:

    1. **Su NIC** -- el del suministro --: si es otro que el del trámite y lo
       comparte con un solo trámite de la caja, es de ése.
    2. **Su cédula**: la persona de la fotocopia tiene que aparecer en el
       trámite -- su número o su nombre en la carta que firmó, en la respuesta
       --. Si sólo la nombra otro trámite, es de ése: la cédula del reclamante
       de una reclamación no se queda en la siguiente.
    3. **Su fecha**: si no encaja en la ventana de su trámite y sí en la de
       uno solo de los otros, es de ése -- el certificado de 2019 que el
       recorrido arrastró detrás de una factura de 2022 --. Anterior a su
       trámite y sin otro donde encaje es un anexo viejo y se queda; posterior
       y sin destino único, se declara.
    4. **Su tema**: una hoja de las que abren un trámite -- una constancia, un
       derecho de petición -- sin radicado ni fecha, con el radicado más
       cercano de otro trámite, no se sabe de cuál es. Junto al suyo es la
       notificación o la carta de ese mismo trámite, y no se marca.
    5. **Su radicado**: si cita además el radicado de otro trámite de la caja,
       o si dos radicados se diferencian en una cifra -- un mal leído --.

    Lo que tiene un destino probado se mueve, y se declara de dónde salió; lo
    que no, se queda donde estaba -- ante la duda se une -- y se declara con su
    porqué. Las hojas con radicado no se mueven nunca: el radicado manda.
    """
    claves = list(dict.fromkeys(asignada[p] for p in paginas))
    hojas_de = {clave: [p for p in paginas if asignada[p] == clave] for clave in claves}
    nic_del_tramite = {
        clave: nic_mas_comun(nic_de(textos.get(p, "")) for p in hojas)
        for clave, hojas in hojas_de.items()
    }
    sin_cedulas = {
        clave: "\n".join(textos.get(p, "") for p in hojas if p not in cedulas)
        for clave, hojas in hojas_de.items()
    }
    # Un trámite sigue vivo mientras haya cartas que lo citen: la revocatoria
    # de oficio de 2019 que cita el RE de 2015 hace de 2019 una fecha suya, y
    # la constancia que la notifica encaja (UPD2326398, UPD2326420).
    citado_el: dict[str, set[date]] = {clave: set() for clave in claves}
    for p in paginas:
        if radicado[p] in citado_el and fechas.get(p):
            citado_el[radicado[p]].add(fechas[p])

    def en_su_ventana(fecha: date, clave: str) -> bool:
        return any(
            en_ventana(fecha, f) for f in (fecha_de.get(clave), *citado_el.get(clave, ())) if f
        )

    def vivo_hasta(clave: str) -> date:
        return max(citado_el.get(clave) or {date.min})

    reparos: list[HojaSuelta] = []

    def mover(pagina: int, destinos: list[str], porque: str, si_no: str) -> None:
        propio = asignada[pagina]
        if len(destinos) == 1:
            reparos.append(
                HojaSuelta(
                    page=pagina,
                    tramite=destinos[0],
                    razon=f"{porque}: se movió del trámite {propio} al {destinos[0]}",
                    venia_de=propio,
                )
            )
        else:
            reparos.append(HojaSuelta(page=pagina, tramite=propio, razon=f"{porque}: {si_no}"))

    for pagina in paginas:
        propio = asignada[pagina]
        texto = textos.get(pagina, "")
        if radicado[pagina]:
            otros = [r for r in radicados_de(texto) if r != radicado[pagina] and r in hojas_de]
            if otros:
                reparos.append(
                    HojaSuelta(
                        page=pagina,
                        tramite=propio,
                        razon=(
                            f"es del trámite {radicado[pagina]} y cita también el {otros[0]}, "
                            "que es otro trámite de esta caja: confirmar de cuál es"
                        ),
                    )
                )
            continue

        nic = nic_de(texto)
        del_tramite = nic_del_tramite.get(propio)
        # El mismo NIC con una cifra de menos o de más es la OCR, no otro
        # suscriptor: «339859» es «5339859» sin su primera cifra (UPD2326307).
        mismo_nic = bool(nic and del_tramite) and (nic in del_tramite or del_tramite in nic)
        if nic and del_tramite and nic != del_tramite and not mismo_nic:
            mover(
                pagina,
                [c for c in claves if c != propio and nic_del_tramite[c] == nic],
                f"trae el NIC {nic} y el trámite {propio} es del NIC {del_tramite}",
                "ningún otro trámite de la caja es de ese NIC; se dejó donde estaba",
            )
            continue

        if pagina in cedulas:
            donde = donde_aparece_la_persona(texto, sin_cedulas)
            if donde and propio not in donde:
                destinos = list(donde)
                pruebas = ", ".join(donde[destinos[0]]) if len(destinos) == 1 else ""
                if len(destinos) == 1 and not _prueba_suficiente(donde[destinos[0]]):
                    # Dos palabras sueltas pueden ser el lugar de nacimiento
                    # -- «PLANETA RICA» --: sin el número ni el nombre entero
                    # no se mueve, se declara.
                    reparos.append(
                        HojaSuelta(
                            page=pagina,
                            tramite=propio,
                            razon=(
                                f"es una cédula que el trámite {propio} no nombra y el "
                                f"{destinos[0]} sólo por {pruebas}: se dejó donde estaba, "
                                "confirmar de cuál es"
                            ),
                        )
                    )
                    continue
                mover(
                    pagina,
                    destinos,
                    f"es la cédula de una persona que el trámite {propio} no nombra"
                    + (f" ({pruebas})" if pruebas else ""),
                    f"la nombran {len(destinos)} trámites ({', '.join(destinos)}); "
                    "se dejó donde estaba",
                )
            continue

        fecha = fechas.get(pagina)
        inicio = fecha_de.get(propio)
        if fecha and inicio and not en_su_ventana(fecha, propio):
            encaja_en = [c for c in claves if c != propio and en_su_ventana(fecha, c)]
            # Anterior a su trámite y sin otro donde encaja es un anexo viejo
            # -- la factura que se reclama, el certificado de tradición --: es
            # suyo. Posterior, o con otro trámite que la reclama, no.
            if encaja_en or despues_de_la_ventana(fecha, max(vivo_hasta(propio), inicio)):
                cuando = "después de lo que dura" if fecha > inicio else "fuera de la ventana de"
                mover(
                    pagina,
                    encaja_en,
                    f"está fechada el {fecha.strftime('%d-%m-%Y')}, {cuando} el "
                    f"trámite {propio} del {inicio.strftime('%d-%m-%Y')}",
                    (
                        f"encaja en {len(encaja_en)} trámites ({', '.join(encaja_en)}); "
                        "se dejó donde estaba"
                        if encaja_en
                        else "no encaja en ningún otro trámite de la caja; se dejó donde estaba"
                    ),
                )
            continue

        cercano = _radicado_mas_cercano(pagina, paginas, radicado)
        if fecha is None and abre_un_tramite(texto) and cercano not in (None, propio):
            reparos.append(
                HojaSuelta(
                    page=pagina,
                    tramite=propio,
                    razon=(
                        "es de las hojas que abren un trámite, no trae radicado ni fecha y "
                        f"el radicado más cercano es el del {cercano}: se dejó en el "
                        f"{propio}, confirmar de cuál es"
                    ),
                )
            )

    vistas = {r.page for r in reparos}
    con_radicado = [c for c in claves if not c.startswith(SIN_RADICADO)]
    # Cuántas veces se lee entero cada radicado en la caja: el que se lee igual
    # dos veces o más no es una mala lectura. Dos expedientes de números
    # seguidos -- P…028 y P…029, de dos personas, cada uno impreso dos veces en
    # su hoja (UPD2326394, UPD2326365) -- son dos trámites.
    todo = re.sub(r"\s", "", "\n".join(textos.get(p, "") or "" for p in paginas)).upper()

    def confirmado(clave: str) -> bool:
        return todo.count(clave) >= 2

    for indice, uno in enumerate(con_radicado):
        for otro in con_radicado[indice + 1 :]:
            if not radicados_parecidos(uno, otro):
                continue
            if confirmado(uno) and confirmado(otro):
                continue
            menor = min((uno, otro), key=lambda c: len(hojas_de[c]))
            mayor = otro if menor == uno else uno
            pagina = next(p for p in paginas if radicado[p] == menor)
            if pagina not in vistas:
                vistas.add(pagina)
                reparos.append(
                    HojaSuelta(
                        page=pagina,
                        tramite=menor,
                        razon=(
                            f"el radicado {menor} se diferencia en una cifra del {mayor}: "
                            "confirmar que no sea el mismo trámite mal leído"
                        ),
                    )
                )
    return reparos


def _prueba_suficiente(pruebas: list[str]) -> bool:
    """Si lo que nombra a la persona de una cédula alcanza para mover la hoja.

    Su número, o dos pares de palabras de su nombre -- apellidos y nombres --:
    un par suelto puede ser el lugar de nacimiento impreso en la tarjeta.
    """
    return any(prueba.startswith("n.º") for prueba in pruebas) or len(pruebas) >= 2


def _radicado_mas_cercano(
    pagina: int, paginas: list[int], radicado: Mapping[int, str | None]
) -> str | None:
    """El radicado de la hoja con radicado más cercana; a igual distancia, la anterior."""
    con_radicado = [p for p in paginas if radicado[p]]
    if not con_radicado:
        return None
    return radicado[min(con_radicado, key=lambda p: (abs(p - pagina), p > pagina))]


def _tipo_del_tramite(
    clave: str, hojas: list[int], textos: Mapping[int, str], tipos: Mapping[int, str | None]
) -> str:
    """Qué trámite es, con un nombre del catálogo.

    Una PQR que habla de reclamación es un RECLAMO -- la constancia, la
    respuesta y la notificación lo dicen --; si no, el tipo de su primera hoja
    reconocida, que en un expediente es su solicitud.
    """
    if clave.startswith("RE") and es_reclamo(textos.get(p, "") for p in hojas):
        return "RECLAMO"
    primero = next((tipos.get(p) for p in hojas if tipos.get(p)), None)
    return primero or DOCUMENT_PREFIX


def _fecha_del_tramite(del_tramite: date | None) -> str | None:
    """La fecha del trámite: la de su radicación.

    No la más reciente de sus hojas: la constancia de una reclamación cita el
    plazo de respuesta -- «notificada a más tardar el 07/09/2022» --, que es una
    fecha que se escribe pero no la del trámite.
    """
    return del_tramite.isoformat() if del_tramite else None
