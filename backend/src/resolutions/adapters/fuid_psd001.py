"""Escribe el Formato Único de Inventario Documental F-PSD-001.

El otro formato que hay que saber rellenar. `fuid_inventory` escribe el de la
Universidad -- FO-GD-008, dieciocho columnas, cabecera en celdas sueltas arriba
y bloque de firmas al pie -- y este escribe el F-PSD-001, que es de otro cliente
y está armado al revés: veintisiete columnas de la A a la AA, sin cabecera
aparte, con los datos de la entrega repetidos en una columna de cada fila.

No se genera una planilla propia. Se abre la oficial, se copia el formato de la
primera fila de datos y se rellena debajo, para que lo que salga sea
indistinguible de lo que alguien habría escrito a mano sobre la misma plantilla.

Las reglas de contenido son las del instructivo, iguales que en el otro formato:
lo que no aplica se escribe N/A y nunca se deja en blanco.
"""

from __future__ import annotations

import logging
from copy import copy
from datetime import date
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from ..application.fuid import NO_APLICA, Cabecera, FuidRow
from ..application.progress import (
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
    Stage,
)
from .guardar_libro import guardar_libro

logger = logging.getLogger(__name__)


#: La hoja se llama como el código del formato. La segunda, "CONTROL DE
#: CAMBIOS", es del documento de calidad y no se toca.
HOJA = "F-PSD-001"

#: La fila 7 lleva los encabezados de columna y la 8 es la primera de datos.
PRIMERA_FILA = 8

#: De dónde se copia el formato de cada fila. Es la misma 8: la plantilla viene
#: limpia y con el estilo ya aplicado, así que se lee antes de escribir encima.
FILA_ESTILO = 8

#: Columnas A a AA.
COLUMNAS = 27

#: Cada cuántas filas se dice por dónde va, igual que en el otro formato.
FILAS_POR_AVISO = 50


def _o_na(valor: str | None) -> str:
    """Lo que se indicó, o el N/A que pide el instructivo donde no hay dato."""
    return valor if valor else NO_APLICA


def celdas_de(fila: FuidRow, cabecera: Cabecera, *, inventariado: date | None) -> list[object]:
    """Los valores en el orden de las columnas A a AA del formato.

    El mapeo vive aquí y no en `FuidRow` porque es propio de esta plantilla: la
    fila describe una unidad documental y cada formato la reparte en sus
    columnas. Las de la entrega salen de la cabecera, las del papel de la fila, y
    las que este sistema no puede saber -- la serie, el acta de transferencia --
    salen como N/A en vez de como una celda vacía.
    """
    return [
        fila.orden,                                  # A  N° Orden
        fila.codigo_trd,                             # B  CÓDIGO
        _o_na(cabecera.entidad_remitente),           # C  ENTIDAD REMITENTE
        _o_na(cabecera.entidad_productora),          # D  ENTIDAD PRODUCTORA
        _o_na(cabecera.unidad_administrativa),       # E  UNIDAD ADMINISTRATIVA
        _o_na(cabecera.oficina_productora),          # F  OFICINA PRODUCTORA
        _o_na(cabecera.objeto),                      # G  OBJETO
        _o_na(cabecera.serie),                       # H  SERIE
        _o_na(cabecera.subserie),                    # I  SUBSERIE
        fila.asunto,                                 # J  ASUNTOS
        fila.consecutivo_inicial,                    # K  No. DOCUMENTO  Desde
        fila.consecutivo_final,                      # L  No. DOCUMENTO  Hasta
        fila.fecha_inicial,                          # M  FECHAS EXTREMAS  Inicial
        fila.fecha_final,                            # N  FECHAS EXTREMAS  Final
        fila.caja,                                   # O  CAJA
        fila.carpeta,                                # P  UPD
        fila.tomo,                                   # Q  TOMO
        fila.otro,                                   # R  OTRO
        NO_APLICA,                                   # S  CAJA INTERNA
        fila.folios,                                 # T  FOLIOS
        fila.soporte,                                # U  SOPORTE
        fila.frecuencia,                             # V  FRECUENCIA
        fila.notas,                                  # W  NOTAS
        _o_na(cabecera.elaborado_por),               # X  ELABORADO POR
        # La fecha en que se levantó el inventario sí la sabe el sistema: es el
        # día en que corrió. Las dos de transferencia no: esa la pone quien
        # entrega la caja, el día que la entrega.
        inventariado.strftime("%d-%m-%Y") if inventariado else NO_APLICA,  # Y
        NO_APLICA,                                   # Z  No. ACTA DE TRANSFERENCIA
        NO_APLICA,                                   # AA FECHA DE TRANSFERENCIA
    ]


class FuidPsd001:
    """Rellena la plantilla F-PSD-001 con las filas que se le den.

    ``hoja`` y ``primera_fila`` existen porque el mismo formato circula en dos
    versiones: la de la plantilla de siempre (hoja «F-PSD-001», datos desde la
    fila 8) y la del inventario oficial de Kingspan (hoja «FUID», datos desde la
    7). Las columnas son las mismas; sólo cambia dónde empiezan.

    ``formato_de_la_plantilla`` deja en cada celda el formato de número que trae
    la fila de estilo, en vez del de texto que se impone por omisión. Lo pide
    el inventario de Kingspan, que tiene que salir igual que su oficial: fechas
    guardadas como fechas con el formato del oficial, texto donde el oficial
    pone texto y General en el resto.
    """

    def __init__(
        self,
        plantilla: Path,
        progress: ProgressReporter | None = None,
        *,
        hoja: str = HOJA,
        primera_fila: int = PRIMERA_FILA,
        formato_de_la_plantilla: bool = False,
    ) -> None:
        self._plantilla = Path(plantilla)
        if not self._plantilla.is_file():
            raise FileNotFoundError(f"no se encuentra la plantilla del FUID: {plantilla}")
        self._progress = progress or NullProgressReporter()
        self._hoja = hoja
        self._primera_fila = primera_fila
        self._formato_de_la_plantilla = formato_de_la_plantilla

    def write(
        self,
        filas: list[FuidRow],
        destino: Path,
        *,
        cabecera: Cabecera | None = None,
        inventariado: date | None = None,
    ) -> Path:
        fecha = inventariado or date.today()
        return self.write_cells(
            [celdas_de(fila, cabecera or Cabecera(), inventariado=fecha) for fila in filas],
            destino,
        )

    def write_cells(self, filas: list[list[object]], destino: Path | str) -> Path:
        """Escribe filas ya repartidas en las columnas A a AA.

        Es la mitad de `write` que no sabe de `FuidRow`: la usa el inventario
        general de una carpeta, que junta filas leídas de otros FUID ya escritos
        y no tiene de dónde reconstruir la fila original.
        """
        destino_path = Path(destino)
        total = len(filas)
        # Abrir la plantilla es lo que más tarda, y ocurre antes de la primera
        # fila: sin este aviso la pantalla parece colgada justo al empezar.
        self._anunciar(0, total, "abriendo la plantilla del formato")
        libro = load_workbook(self._plantilla)
        hoja = libro[self._hoja]

        estilos = self._estilos_de_fila(hoja, self._primera_fila)
        for indice, celdas in enumerate(filas):
            self._escribir_celdas(
                hoja, self._primera_fila + indice, celdas, estilos, self._formato_de_la_plantilla
            )
            if (indice + 1) % FILAS_POR_AVISO == 0:
                self._anunciar(indice + 1, total, "escribiendo las filas")

        self._anunciar(total, total, "guardando la planilla")
        destino_path.parent.mkdir(parents=True, exist_ok=True)
        guardar_libro(libro, destino_path)
        return destino_path

    def _anunciar(self, hechas: int, total: int, detalle: str) -> None:
        """Decir por dónde va. Un fallo del aviso nunca pierde la planilla."""
        try:
            self._progress.emit(
                ProgressEvent(
                    stage=Stage.INVENTORYING, done=hechas, total=total, detail=detalle
                )
            )
        except Exception:  # noqa: BLE001 - la telemetría nunca rompe el trabajo
            # Se traga, pero deja rastro: un aviso que falla en silencio hace
            # que la barra se quede quieta sin que nadie sepa por qué.
            logger.debug("no se pudo anunciar el avance del FUID", exc_info=True)

    @staticmethod
    def _estilos_de_fila(hoja: Worksheet, fila: int = FILA_ESTILO) -> list[dict]:
        """El formato de la primera fila de datos, que es el que llevan todos los registros."""
        estilos = []
        for columna in range(1, COLUMNAS + 1):
            celda = hoja.cell(row=fila, column=columna)
            estilos.append(
                {
                    "font": copy(celda.font),
                    "border": copy(celda.border),
                    "fill": copy(celda.fill),
                    "alignment": copy(celda.alignment),
                    "number_format": celda.number_format,
                }
            )
        return estilos

    @staticmethod
    def _escribir_celdas(
        hoja: Worksheet,
        numero: int,
        celdas: list[object],
        estilos: list[dict],
        formato_de_la_plantilla: bool = False,
    ) -> None:
        # Una fila escrita se ve. La plantilla de Kingspan salió de un oficial
        # con un filtro que ocultaba 1.436 filas, la 7 entre ellas, y el
        # inventario llegaba con su única fila escondida: parecía vacío.
        hoja.row_dimensions[numero].hidden = False
        for indice, valor in enumerate(celdas[:COLUMNAS]):
            celda = hoja.cell(row=numero, column=indice + 1, value=valor)
            estilo = estilos[indice]
            celda.font = copy(estilo["font"])
            celda.border = copy(estilo["border"])
            celda.fill = copy(estilo["fill"])
            celda.alignment = copy(estilo["alignment"])
            # Las fechas van como texto DD-MM-AAAA, que es como las pide el
            # instructivo y como se escriben en el otro formato. La plantilla
            # trae esas dos columnas con formato de fecha estadounidense
            # (mm-dd-yy), y dejarlo puesto haría que Excel leyera "03-08-2022"
            # como el 8 de marzo. Además la celda puede llevar N/A, que no es
            # una fecha en ningún formato. El número de orden y los folios sí
            # son números y se dejan como tales.
            #
            # Con ``formato_de_la_plantilla`` manda el de la fila de estilo: el
            # inventario de Kingspan guarda fechas de verdad y sale igual que
            # su oficial.
            if formato_de_la_plantilla:
                celda.number_format = estilo["number_format"]
            else:
                celda.number_format = "@" if isinstance(valor, str) else "General"
