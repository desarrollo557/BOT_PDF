"""Escribe el Formato Único de Inventario Documental (FUID) de la Universidad.

No genera una planilla propia: abre la plantilla oficial -- FO-GD-008, versión
00 -- y la rellena. El logotipo, la banda de la cabecera, los encabezados a dos
niveles y el bloque de firmas son los del formato aprobado, y lo único que este
módulo aporta son las filas y el sitio al que se corre la firma cuando las filas
no caben en el hueco que la plantilla deja.

Las reglas de contenido no son de este autor: salen del instructivo del propio
formato, que dice qué va en cada columna y, lo más importante, que **lo que no
aplica se escribe N/A**. Una celda vacía en un inventario documental no dice
"no aplica", dice "se olvidó".
"""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from ..application.fuid import Cabecera, FuidRow
from ..application.progress import (
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
    Stage,
)

HOJA = "INVENTARIO"

#: La plantilla congela los paneles en A14, que es como declara dónde empiezan
#: los datos. La fila 14 que trae escrita es la guía de qué va en cada columna,
#: y el primer registro la sustituye.
PRIMERA_FILA = 14

#: De dónde se copia el formato de cada fila de datos. Es la misma fila 14: el
#: estilo se lee antes de escribir nada encima.
FILA_ESTILO = 14

#: Filas de la cabecera que identifican la entrega.
FILA_OFICINA = 8
FILA_OBJETO = 9
COLUMNA_CABECERA = 2

#: Dónde está el bloque de firmas en la plantilla en blanco. Es sólo el punto
#: de partida: se busca por su texto, porque una plantilla que ya se usó lo
#: tiene mucho más abajo -- la de diplomas, con 1.084 filas dentro, lo lleva en
#: la 1100 -- y buscarlo en una fila fija encontraría datos y los tomaría por
#: firmas.
BLOQUE_FIRMAS = (109, 112)

#: Con qué empieza la primera línea del bloque. Es lo que lo identifica.
MARCA_DE_FIRMAS = "elaborado por"

#: Cuántas líneas ocupa: elaborado / cargo / firma / lugar.
ALTO_DE_FIRMAS = 4

FILAS_ANTES_DE_FIRMAR = 2

#: Columnas A a P. Las dos siguientes que trae la hoja están fuera del formato.
COLUMNAS = 16

#: Cada cuántas filas se dice por dónde va. Escribir un FUID de 1.084 filas
#: tarda cinco segundos y medio, y son los últimos del trabajo: la barra de
#: páginas ya está al 100 % y sin este aviso la pantalla parece haberse quedado
#: colgada justo al final. Cincuenta filas es un aviso cada cuarto de segundo,
#: que se nota sin inundar nada.
FILAS_POR_AVISO = 50


@dataclass
class _Firma:
    """Una celda del bloque de firmas, guardada para volver a colocarla."""

    fila_relativa: int
    columna: int
    valor: object
    estilo: object
    ancho_combinado: int = 1


class FuidInventory:
    """Rellena la plantilla oficial con las filas que se le den."""

    def __init__(
        self, plantilla: Path, progress: ProgressReporter | None = None
    ) -> None:
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
    ) -> Path:
        total = len(filas)
        # Abrir la plantilla es lo que más tarda de todo esto -- openpyxl lee el
        # libro entero, con sus estilos -- y ocurre antes de la primera fila, así
        # que hay que decirlo antes de empezar o parecerá que no pasa nada.
        self._anunciar(0, total, "abriendo la plantilla del formato")
        libro = load_workbook(self._plantilla)
        hoja = libro[HOJA]

        self._cabecera(hoja, cabecera or Cabecera())
        estilos = self._estilos_de_fila(hoja)
        desde_firmas, firmas = self._recoger_firmas(hoja)

        ultima = PRIMERA_FILA + len(filas) - 1
        for indice, fila in enumerate(filas):
            self._escribir_fila(hoja, PRIMERA_FILA + indice, fila, estilos)
            if (indice + 1) % FILAS_POR_AVISO == 0:
                self._anunciar(indice + 1, total, "escribiendo las filas")

        # Todo lo que quede por debajo del último registro se limpia. No es sólo
        # cosmética: cuando la plantilla es un inventario anterior -- que es
        # cómo se usa la de diplomas -- ahí abajo hay cientos de filas de otra
        # entrega, y dejarlas convertiría el documento en dos inventarios
        # pegados sin que nadie lo note.
        for numero in range(ultima + 1, max(desde_firmas, ultima) + 1):
            self._vaciar(hoja, numero)

        self._colocar_firmas(hoja, firmas, ultima + FILAS_ANTES_DE_FIRMAR + 1)

        # Guardar vuelve a recorrer el libro entero. Es el otro tramo largo, y
        # el último: si no se anuncia, el trabajo parece colgado en la fila final.
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

    # -- cabecera -------------------------------------------------------------

    @staticmethod
    def _cabecera(hoja: Worksheet, cabecera: Cabecera) -> None:
        if cabecera.oficina_productora:
            hoja.cell(row=FILA_OFICINA, column=COLUMNA_CABECERA).value = (
                f"OFICINA PRODUCTORA: {cabecera.oficina_productora}"
            )
        if cabecera.objeto:
            hoja.cell(row=FILA_OBJETO, column=COLUMNA_CABECERA).value = (
                f"OBJETO: {cabecera.objeto}"
            )

    # -- filas ----------------------------------------------------------------

    @staticmethod
    def _estilos_de_fila(hoja: Worksheet) -> list[dict]:
        """El formato de la fila 14, que es el que llevan todos los registros.

        Se copia celda a celda en lugar de aplicar uno inventado, para que la
        planilla generada sea indistinguible de una rellenada a mano sobre la
        misma plantilla.
        """
        estilos = []
        for columna in range(1, COLUMNAS + 1):
            celda = hoja.cell(row=FILA_ESTILO, column=columna)
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
    def _escribir_fila(
        hoja: Worksheet, numero: int, fila: FuidRow, estilos: list[dict]
    ) -> None:
        for indice, valor in enumerate(fila.as_cells()):
            celda = hoja.cell(row=numero, column=indice + 1, value=valor)
            estilo = estilos[indice]
            celda.font = copy(estilo["font"])
            celda.border = copy(estilo["border"])
            celda.fill = copy(estilo["fill"])
            celda.alignment = copy(estilo["alignment"])
            # El número de orden y los consecutivos son texto en la plantilla:
            # un folio "336BIS" y una cédula con ceros a la izquierda dejan de
            # ser lo que son en cuanto Excel los convierte en número.
            celda.number_format = estilo["number_format"]
        hoja.row_dimensions[numero].height = 20

    @staticmethod
    def _vaciar(hoja: Worksheet, numero: int) -> None:
        """Deja la fila en blanco y sin cuadrícula.

        La fila de la que se copia el estilo es la excepción: pierde el valor
        pero conserva el formato. Es lo que permite que una planilla ya escrita
        vuelva a servir de plantilla -- sin esto, guardar un inventario vacío se
        llevaría por delante el formato de todas las filas siguientes.
        """
        from openpyxl.styles import Border

        conserva_el_formato = numero == FILA_ESTILO
        for columna in range(1, COLUMNAS + 1):
            celda = hoja.cell(row=numero, column=columna)
            celda.value = None
            if not conserva_el_formato:
                celda.border = Border()

    # -- firmas ---------------------------------------------------------------

    @staticmethod
    def _localizar_firmas(hoja: Worksheet) -> tuple[int, int]:
        """Encuentra el bloque de firmas por lo que dice, no por dónde está.

        Una plantilla en blanco lo tiene justo debajo del área de datos; una que
        ya se rellenó, cientos de filas más abajo. Buscarlo por su texto es lo
        único que funciona en las dos.
        """
        for numero in range(PRIMERA_FILA, hoja.max_row + 1):
            valor = hoja.cell(row=numero, column=1).value
            if isinstance(valor, str) and valor.strip().lower().startswith(MARCA_DE_FIRMAS):
                return numero, numero + ALTO_DE_FIRMAS - 1
        return BLOQUE_FIRMAS

    @staticmethod
    def _recoger_firmas(hoja: Worksheet) -> tuple[int, list[_Firma]]:
        """Guarda el bloque de firmas y lo borra de donde estaba."""
        inicio, fin = FuidInventory._localizar_firmas(hoja)
        anchos: dict[tuple[int, int], int] = {}
        for rango in list(hoja.merged_cells.ranges):
            if inicio <= rango.min_row <= fin:
                anchos[(rango.min_row, rango.min_col)] = rango.max_col - rango.min_col + 1
                hoja.unmerge_cells(str(rango))

        recogidas: list[_Firma] = []
        for numero in range(inicio, fin + 1):
            for columna in range(1, COLUMNAS + 1):
                celda = hoja.cell(row=numero, column=columna)
                if celda.value in (None, ""):
                    continue
                recogidas.append(
                    _Firma(
                        fila_relativa=numero - inicio,
                        columna=columna,
                        valor=celda.value,
                        estilo=copy(celda._style),
                        ancho_combinado=anchos.get((numero, columna), 1),
                    )
                )
                celda.value = None
        return fin, recogidas

    @staticmethod
    def _colocar_firmas(hoja: Worksheet, firmas: list[_Firma], desde: int) -> None:
        for firma in firmas:
            numero = desde + firma.fila_relativa
            celda = hoja.cell(row=numero, column=firma.columna, value=firma.valor)
            celda._style = copy(firma.estilo)
            if firma.ancho_combinado > 1:
                hoja.merge_cells(
                    start_row=numero,
                    start_column=firma.columna,
                    end_row=numero,
                    end_column=firma.columna + firma.ancho_combinado - 1,
                )
