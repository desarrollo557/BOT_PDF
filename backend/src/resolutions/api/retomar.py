"""Retomar una carpeta de libros de diplomas: qué llegó al destino y qué falta.

Lo pidió el operador el 2026-10-15, con una corrida de once libros a medias en
el destino: «si hay algún tipo de excepción o error, que el bot tenga la
capacidad de saber qué fue procesado de la fuente a la carpeta destino y qué
no, y a la vez tenga la opción de reprocesar sólo los que faltan, así tenga que
leer el archivo fuente para saber a partir de qué página no ha sido
procesada». Por ahora, sólo para la habilidad de libros de diplomas.

Cuatro modos, que elige el operador al lanzar la carpeta:

- ``no``: lo de siempre, para cualquier habilidad. Un PDF con su constancia de
  entrega vigente (``constancia.py``) se salta sin abrirlo; uno cuya entrega
  se cortó o cuyo origen cambió se rehace entero; el resto se procesa.
- ``faltantes``: sólo libros de diplomas. Por cada PDF del origen se mira el
  destino. Si ya está completo, se salta; si no hay nada, se procesa entero;
  si está a medias, se leen **sólo las páginas que faltan**, con su número de
  página del libro.
- ``revisar``: sólo libros de diplomas. Sólo mirar: no se procesa nada y queda
  el control.
- ``todo``: volver a procesar todo, para cualquier habilidad, aunque esté
  entregado. Lo anterior se aparta en ``_reemplazados``.

Lo que hay en el destino se averigua en el disco, cruzando las páginas del
origen con las de los PDF entregados (``domain/conciliacion.py``), y queda
escrito en «00.CONTROL DE ENTREGA.xlsx», en la raíz del destino.
"""

from __future__ import annotations

import logging
import shutil
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from ..domain.conciliacion import (
    Conciliacion,
    EstadoDeEntrega,
    Huella,
    conciliar,
    rangos,
)

logger = logging.getLogger(__name__)

#: Cómo termina el nombre del FUID que el worker deja junto a cada libro.
SUFIJO_DEL_FUID = "__FUID.xlsx"


class Retomar(StrEnum):
    NO = "no"
    FALTANTES = "faltantes"
    REVISAR = "revisar"
    TODO = "todo"

    @classmethod
    def parse(cls, valor: object) -> Retomar:
        texto = str(valor or "no").strip().lower()
        try:
            return cls(texto)
        except ValueError:
            raise ValueError(f"Modo de retomar desconocido: {valor}") from None


class HuellasDelOrigen:
    """Las huellas de cada PDF de origen, leídas una sola vez por corrida.

    Se miran dos veces -- antes de procesar, para saber qué falta, y después,
    para comprobar cómo quedó -- y leer el origen es lo caro: veinte segundos
    por libro desde una unidad de red. El destino, que es disco local, se
    vuelve a mirar entero cada vez.
    """

    def __init__(self) -> None:
        self._huellas: dict[str, list[Huella]] = {}
        self._cerrojo = threading.Lock()

    def de(self, pdf: Path) -> list[Huella]:
        from ..adapters.huellas_pdf import huellas_de

        clave = str(pdf)
        with self._cerrojo:
            guardadas = self._huellas.get(clave)
        if guardadas is not None:
            return guardadas
        leidas = huellas_de(pdf)
        with self._cerrojo:
            self._huellas[clave] = leidas
        return leidas


@dataclass(slots=True)
class ControlDeUnLibro:
    """Lo que había de un PDF de origen en el destino, qué se hizo y cómo quedó."""

    pdf: str
    carpeta: str
    antes: Conciliacion | None = None
    accion: str = ""
    despues: Conciliacion | None = None
    #: Los PDF del destino que no se dejaron abrir: un archivo a medio escribir
    #: cuando la corrida se cortó. No cuentan como entregados.
    ilegibles: tuple[str, ...] = ()
    error: str | None = None

    @property
    def ultima(self) -> Conciliacion | None:
        return self.despues or self.antes

    def observaciones(self) -> str:
        notas: list[str] = []
        if self.error:
            notas.append(self.error)
        ultima = self.ultima
        if ultima is not None:
            for archivo in ultima.sin_partir:
                notas.append(
                    f"«{archivo.nombre}» trae {len(archivo.paginas)} páginas: el libro no se "
                    "partió; para rehacerlo, borre su carpeta del destino y retome"
                )
            if ultima.repetidas:
                notas.append(f"páginas entregadas dos veces: {rangos(ultima.repetidas)}")
            if ultima.ajenos:
                notas.append(f"archivos que no son de este PDF: {', '.join(ultima.ajenos)}")
        if self.ilegibles:
            notas.append(f"archivos dañados, no cuentan: {', '.join(self.ilegibles)}")
        return "; ".join(notas)

    def as_dict(self) -> dict[str, object]:
        return {
            "pdf": self.pdf,
            "carpeta": self.carpeta,
            "antes": self.antes.as_dict() if self.antes else None,
            "accion": self.accion,
            "despues": self.despues.as_dict() if self.despues else None,
            "observaciones": self.observaciones(),
        }

    def fila(self):
        from ..adapters.excel_inventory import FilaDeControl

        antes, ultima = self.antes, self.ultima
        return FilaDeControl(
            pdf=self.pdf,
            destino=self.carpeta,
            paginas=antes.paginas_del_origen if antes else 0,
            estado_antes=str(antes.estado) if antes else "—",
            entregadas_antes=len(antes.entregadas) if antes else 0,
            faltaban=rangos(antes.faltantes) if antes else "",
            accion=self.accion or ("falló" if self.error else "pendiente"),
            estado_despues=str(ultima.estado) if ultima else "—",
            faltan=rangos(ultima.faltantes) if ultima else "",
            observaciones=self.observaciones(),
        )


def conciliar_libro(
    origen: Path, carpeta: Path, huellas: HuellasDelOrigen
) -> tuple[Conciliacion, tuple[str, ...]]:
    """Qué páginas de ``origen`` están en los PDF de ``carpeta``, y cuáles no abren.

    Si la carpeta no existe o no trae ningún PDF no se lee el origen entero:
    basta con contar sus páginas para saber que faltan todas.
    """
    from ..adapters.huellas_pdf import huellas_de, paginas_de

    pdfs = sorted(carpeta.glob("*.[pP][dD][fF]")) if carpeta.is_dir() else []
    if not pdfs:
        total = paginas_de(origen)
        return conciliar([Huella()] * total, {}), ()

    entregados: dict[str, list[Huella]] = {}
    ilegibles: list[str] = []
    for pdf in pdfs:
        try:
            entregados[pdf.name] = huellas_de(pdf)
        except Exception as error:  # noqa: BLE001 - un archivo dañado no cuenta como entregado
            logger.warning("no cuenta como entregado: %s", error)
            ilegibles.append(pdf.name)
    return conciliar(huellas.de(origen), entregados), tuple(ilegibles)


def que_hacer(conciliacion: Conciliacion) -> tuple[list[int] | None, str]:
    """Qué páginas procesar -- ``None`` es el libro entero -- y cómo se cuenta.

    El primer valor es ``[]`` cuando no hay nada que hacer.
    """
    if conciliacion.estado is EstadoDeEntrega.COMPLETO:
        return [], "ya estaba completo: no se volvió a procesar"
    if conciliacion.estado is EstadoDeEntrega.SIN_PROCESAR:
        return None, "no había nada entregado: se procesó entero"
    faltantes = list(conciliacion.faltantes)
    return faltantes, (
        f"se procesaron sólo las {len(faltantes)} páginas que faltaban "
        f"({rangos(faltantes)})"
    )


def fuid_del_libro(carpeta: Path) -> Path | None:
    """El FUID que ya está entregado junto a los PDF de un libro, si hay uno."""
    if not carpeta.is_dir():
        return None
    return next(iter(sorted(carpeta.glob(f"*{SUFIJO_DEL_FUID}"))), None)


def _archivo_de(notas: str) -> str:
    return notas.removeprefix("Archivo: ").strip() if notas.startswith("Archivo: ") else ""


def entregar_fuid(
    del_trabajo: Path,
    carpeta: Path,
    *,
    previo: Conciliacion | None = None,
    paginas_nuevas: Mapping[str, int] | None = None,
    renombres: Mapping[str, str] | None = None,
) -> Path:
    """Deja el FUID del libro junto a sus PDF, sumando lo ya entregado si se retomó.

    Un libro procesado entero lleva su FUID tal cual. Uno retomado a medias
    trae sólo las filas de las páginas que faltaban, y lo que se entrega es
    **un** FUID del libro: las filas que ya estaban, más las nuevas, en el
    orden de las páginas del libro y con el número de orden corrido. Cada fila
    se sitúa por su archivo: el de las viejas, por la conciliación; el de las
    nuevas, por el inventario del trabajo.
    """
    from ..adapters.fuid_inventory import FuidInventory
    from ..adapters.fuid_reader import filas_de_fuid
    from ..application.fuid import Cabecera
    from ..application.inventory_document import template_for
    from ..domain.doctype import DocumentType

    renombres = dict(renombres or {})
    existente = fuid_del_libro(carpeta)
    destino = existente or carpeta / del_trabajo.name
    # Se suma a lo anterior sólo si había algo entregado y su FUID está ahí.
    sumar = previo is not None and bool(previo.entregadas) and existente is not None
    if not sumar and not renombres:
        shutil.copy2(del_trabajo, destino)
        return destino

    nuevas, oficina = filas_de_fuid(del_trabajo)
    paginas_nuevas = dict(paginas_nuevas or {})
    situadas: list[tuple[float, int, object]] = []
    for indice, fila in enumerate(nuevas):
        archivo = _archivo_de(fila.notas)
        entregado = renombres.get(archivo, archivo)
        if archivo and entregado != archivo:
            fila = replace(fila, notas=f"Archivo: {entregado}")
        pagina = paginas_nuevas.get(archivo)
        situadas.append((pagina if pagina is not None else float("inf"), indice, fila))

    if sumar:
        viejas, oficina_vieja = filas_de_fuid(existente)
        oficina = oficina_vieja or oficina
        # NOTAS va vacía desde el 2026-10-30: sin «Archivo:», la página de
        # cada fila vieja sale del orden. El FUID se escribió en el orden del
        # libro, una fila por PDF entregado.
        primeras = sorted(p for p in (a.primera for a in previo.archivos) if p is not None) if previo else []
        for indice, fila in enumerate(viejas, start=len(nuevas)):
            pagina = previo.pagina_de(_archivo_de(fila.notas)) if previo else None
            if pagina is None and len(primeras) == len(viejas):
                pagina = primeras[indice - len(nuevas)]
            situadas.append((pagina if pagina is not None else float("inf"), indice, fila))

    situadas.sort(key=lambda item: (item[0], item[1]))
    filas = [replace(fila, orden=numero) for numero, (_, _, fila) in enumerate(situadas, start=1)]
    return FuidInventory(template_for(DocumentType.DIPLOMA)).write(
        filas, destino, cabecera=Cabecera(oficina_productora=oficina or None)
    )


def escribir_control(
    controles: list[ControlDeUnLibro],
    destino: Path,
    *,
    origen: str,
    operador: str | None,
) -> Path | None:
    from ..adapters.excel_inventory import ExcelControlDeEntrega

    if not controles:
        return None
    return ExcelControlDeEntrega().write(
        [control.fila() for control in controles],
        destino,
        origen=origen,
        operador=operador,
    )
