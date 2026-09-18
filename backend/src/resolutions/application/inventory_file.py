"""Inventariar un PDF entero como una sola unidad documental.

La tercera cosa que se puede pedir del sistema, y la más simple de explicar: no
partas nada, no agrupes nada, sólo anota este archivo en el inventario. Sale una
fila -- qué es, entre qué fechas va, cuántos folios tiene -- y el PDF queda
exactamente como llegó.

Se distingue de `inventory_document`, que también inventaría sin escribir PDF,
en la unidad de la pregunta. Aquél lee un libro empastado y saca una fila por
registro, porque dentro del libro hay cuatrocientos diplomas; éste lee un
archivo que **ya es** un documento y saca la fila de ese documento. Confundirlos
da los dos errores simétricos: un libro anotado en un solo renglón, o una nota
de ajuste repartida en doce.

Lee todas las páginas y no una muestra, y eso es deliberado: las fechas extremas
son la más antigua y la más reciente que aparezcan en cualquier hoja, y una
muestra de doce páginas de un expediente de ochenta se deja fuera justo la que
lo abre o la que lo cierra.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from ..domain.ficha import Ficha, fichar
from .archivo_fuid import fila_del_archivo
from .control import NullRunControl, RunControl
from .fuid import FuidRow, Ubicacion
from .ports import OcrEngine, PageSource
from .progress import NullProgressReporter, ProgressEvent, ProgressReporter, Stage

logger = logging.getLogger(__name__)

#: Por debajo de esto la capa de texto de una página no da para leer nada y hay
#: que mirar la imagen. Es el mismo umbral con que el reconocedor decide lo
#: mismo, y por el mismo motivo: un escaneo sin OCR devuelve cuatro caracteres
#: de basura, no una página vacía.
MIN_CHARS = 80


@dataclass(slots=True)
class FileInventoryOutcome:
    """Lo que se averiguó del archivo, y la única fila que produce."""

    document: str
    page_count: int
    ficha: Ficha
    row: FuidRow
    #: Cuántas páginas hubo que pasar por OCR. Es lo que explica por qué un
    #: trabajo tardó lo que tardó, y se anota en el informe en vez de hacer que
    #: alguien lo deduzca del reloj.
    ocr_pages: int = 0
    #: Las páginas que no se dejaron leer de ninguna de las dos maneras. No
    #: invalidan el inventario -- el resto del archivo se leyó -- pero quien
    #: firme tiene derecho a saber sobre cuánto papel se está pronunciando.
    unreadable: list[int] = field(default_factory=list)

    @property
    def rows(self) -> list[FuidRow]:
        """Una, siempre. La forma de lista es la que espera quien escribe el FUID."""
        return [self.row]

    def as_dict(self) -> dict[str, object]:
        return {
            "document": self.document,
            "page_count": self.page_count,
            "records": 1,
            "asunto": self.ficha.asunto,
            "tipo_documental": self.ficha.tipo_documental,
            "fecha_inicial": self.row.fecha_inicial,
            "fecha_final": self.row.fecha_final,
            "consecutivo_inicial": self.row.consecutivo_inicial,
            "consecutivo_final": self.row.consecutivo_final,
            "folios": self.ficha.folios,
            "ocr_pages": self.ocr_pages,
            "unreadable_pages": list(self.unreadable),
            "incidents": self.incidents,
        }

    @property
    def incidents(self) -> list[str]:
        """Lo que hay que advertirle a quien revise, en su idioma."""
        avisos: list[str] = []
        if self.ficha.asunto is None:
            avisos.append("no se pudo leer el encabezado, así que el archivo quedó sin asunto")
        if not self.ficha.esta_fechada:
            avisos.append("no se encontró ninguna fecha: las fechas extremas quedaron en N/A")
        if self.unreadable:
            cuantas = len(self.unreadable)
            avisos.append(
                f"{cuantas} página(s) no se pudieron leer: "
                + ", ".join(str(numero) for numero in self.unreadable[:10])
            )
        return avisos


class InventoryFile:
    """Lee un PDF de punta a punta y devuelve su fila de inventario."""

    def __init__(
        self,
        ocr: OcrEngine | None = None,
        progress: ProgressReporter | None = None,
        control: RunControl | None = None,
    ) -> None:
        self._ocr = ocr
        self._progress = progress or NullProgressReporter()
        self._control = control or NullRunControl()

    def execute(
        self,
        source: PageSource,
        *,
        document_name: str,
        ubicacion: Ubicacion | None = None,
        orden: int = 1,
        inventariado: date | None = None,
    ) -> FileInventoryOutcome:
        total = source.page_count
        self._report(ProgressEvent(stage=Stage.OPENED, page_count=total))

        paginas: list[str] = []
        ilegibles: list[int] = []
        con_ocr = 0
        for numero in range(1, total + 1):
            # Cancelar tiene que surtir efecto en la página siguiente, no al
            # final: inventariar un expediente largo con OCR son minutos, y un
            # operador que le da a cancelar no espera a que termine igual.
            self._control.check()
            texto, uso_ocr, se_leyo = self._leer(source, numero)
            paginas.append(texto)
            con_ocr += int(uso_ocr)
            if not se_leyo:
                ilegibles.append(numero)
            self._report(
                ProgressEvent(stage=Stage.PAGE, done=numero, total=total, page_number=numero)
            )

        self._report(
            ProgressEvent(
                stage=Stage.INVENTORYING,
                done=0,
                total=1,
                detail="anotando el archivo en el inventario",
            )
        )
        ficha = fichar(paginas, folios=total)
        return FileInventoryOutcome(
            document=document_name,
            page_count=total,
            ficha=ficha,
            row=fila_del_archivo(
                ficha, nombre_del_archivo=document_name, ubicacion=ubicacion, orden=orden
            ),
            ocr_pages=con_ocr,
            unreadable=ilegibles,
        )

    def _leer(self, source: PageSource, numero: int) -> tuple[str, bool, bool]:
        """El texto de una página: de su capa si la tiene, del OCR si no.

        Devuelve además si hubo que pasar por OCR y si se consiguió leer algo,
        que son las dos cosas que el informe necesita y que no se deducen del
        texto -- una página en blanco y una ilegible devuelven la misma cadena
        vacía y no son lo mismo.

        La página entera, no su banda superior. El reconocedor mira sólo el
        encabezado porque le basta para nombrar el documento; aquí hacen falta
        las fechas, y una fecha de firma está al pie.
        """
        try:
            texto = source.text_of(numero)
        except Exception:  # noqa: BLE001 - una página ilegible no tumba el archivo
            logger.debug("no se pudo leer la capa de texto de la página %s", numero, exc_info=True)
            texto = ""

        if len(texto.strip()) >= MIN_CHARS or self._ocr is None:
            return texto, False, bool(texto.strip())

        try:
            leido = self._ocr.read(source.render(numero, None, 200)).text
        except Exception:  # noqa: BLE001 - lo mismo: se anota y se sigue
            logger.warning("no se pudo pasar por OCR la página %s", numero, exc_info=True)
            return texto, True, bool(texto.strip())
        # Lo que diera la capa de texto se conserva junto a lo que dio el OCR:
        # a veces la capa trae el número y el OCR la fecha, y quedarse sólo con
        # uno de los dos pierde la mitad de la fila.
        combinado = f"{texto}\n{leido}".strip()
        return combinado, True, bool(combinado)

    def _report(self, event: ProgressEvent) -> None:
        try:
            self._progress.emit(event)
        except Exception:  # noqa: BLE001 - la telemetría nunca rompe el trabajo
            logger.debug("no se pudo informar del progreso", exc_info=True)
