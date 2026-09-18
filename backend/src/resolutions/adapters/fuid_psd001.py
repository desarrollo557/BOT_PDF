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
    """Rellena la plantilla F-PSD-001 con las filas que se le den."""

    def __init__(self, plantilla: Path, progress: ProgressReporter | None = None) -> None:
        self._plantilla = Path(plantilla)
        if not self._plantilla.is_file():
            raise FileNotFoundError(f"no se encuentra la plantilla del FUID: {plantilla}")
        self._progress = progress or NullProgressReporter()

    def write(
        self,
        filas: list[FuidRow],
        destino: Path,
        *,
        cabecera: Cabecera | None = None,
        inventariado: date | None = None,
    ) -> Path:
        total = len(filas)
        # Abrir la plantilla es lo que más tarda, y ocurre antes de la primera
        # fila: sin este aviso la pantalla parece colgada justo al empezar.
        self._anunciar(0, total, "abriendo la plantilla del formato")
        libro = load_workbook(self._plantilla)
        hoja = libro[HOJA]

        estilos = self._estilos_de_fila(hoja)
        fecha = inventariado or date.today()
        for indice, fila in enumerate(filas):
            self._escribir_fila(
                hoja, PRIMERA_FILA + indice, fila, cabecera or Cabecera(), estilos, fecha
            )
            if (indice + 1) % FILAS_POR_AVISO == 0:
                self._anunciar(indice + 1, total, "escribiendo las filas")

        self._anunciar(total, total, "guardando la planilla")
        destino.parent.mkdir(parents=True, exist_ok=True)
        libro.save(destino)
        return destino

    def _anunciar(self, hechas: int, total: int, detalle: str) -> None:
        """Decir por dónde va. Un fallo del aviso nunca pierde la planilla."""
        try:
            self._progress.emit(
                ProgressEvent(
                    stage=Stage.INVENTORYING, done=hechas, total=total, detail=detalle
                )
            )
        except Exception:  # noqa: BLE001 - la telemetría nunca rompe el trabajo
            pass

    @staticmethod
    def _estilos_de_fila(hoja: Worksheet) -> list[dict]:
        """El formato de la fila 8, que es el que llevan todos los registros."""
        estilos = []
        for columna in range(1, COLUMNAS + 1):
            celda = hoja.cell(row=FILA_ESTILO, column=columna)
            estilos.append(
                {
                    "font": copy(celda.font),
                    "border": copy(celda.border),
                    "fill": copy(celda.fill),
                    "alignment": copy(celda.alignment),
                }
            )
        return estilos

    @staticmethod
    def _escribir_fila(
        hoja: Worksheet,
        numero: int,
        fila: FuidRow,
        cabecera: Cabecera,
        estilos: list[dict],
        inventariado: date,
    ) -> None:
        for indice, valor in enumerate(celdas_de(fila, cabecera, inventariado=inventariado)):
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
            celda.number_format = "@" if isinstance(valor, str) else "General"
