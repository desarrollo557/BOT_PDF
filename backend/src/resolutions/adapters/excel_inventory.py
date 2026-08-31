from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.worksheet import Worksheet

#: Written beside the generated PDFs, and delivered with them.
SUFFIX = "__inventario.xlsx"
RUN_SHEET = "_inventario_del_lote.xlsx"

# -----------------------------------------------------------------------------
#  Paleta
# -----------------------------------------------------------------------------
#  Tres grises y nada más. Una planilla que se imprime y se firma no gana nada
#  con color: lo que la hace legible es la alineación, el aire y el borde en el
#  sitio justo. El único relleno fuerte está en la línea del cuadre, que es la
#  que alguien tiene que mirar antes de firmar.
# -----------------------------------------------------------------------------
_TINTA = "1B2733"
_SUAVE = "6E7B87"
_TENUE = "9AA5AF"

_BANDA = PatternFill("solid", fgColor="1B2733")     # cabecera de sección
_ENCABEZADO = PatternFill("solid", fgColor="EDF1F4")  # cabecera de tabla
_CEBRA = PatternFill("solid", fgColor="F7F9FA")       # fila alterna
_ETIQUETA = PatternFill("solid", fgColor="F2F5F7")    # celda de etiqueta
_CUADRA = PatternFill("solid", fgColor="DFF3E4")
_NO_CUADRA = PatternFill("solid", fgColor="FBE3E3")
_PENDIENTE = PatternFill("solid", fgColor="FFF4DE")

_FINO = Side(style="thin", color="C9D2D9")
_MEDIO = Side(style="medium", color="1B2733")
_CAJA = Border(left=_FINO, right=_FINO, top=_FINO, bottom=_FINO)

_TITULO = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
_SUBTITULO = Font(name="Calibri", size=9, color="C9D2D9")
_SECCION = Font(name="Calibri", size=9, bold=True, color="FFFFFF")
_ETIQ = Font(name="Calibri", size=8.5, bold=True, color=_SUAVE)
_VALOR = Font(name="Calibri", size=10, color=_TINTA)
_CELDA = Font(name="Calibri", size=9.5, color=_TINTA)
_COL = Font(name="Calibri", size=8.5, bold=True, color=_TINTA)
_TOTAL = Font(name="Calibri", size=9.5, bold=True, color=_TINTA)
_PIE = Font(name="Calibri", size=8, color=_TENUE)

_IZQ = Alignment(horizontal="left", vertical="center", wrap_text=False)
_IZQ_ARRIBA = Alignment(horizontal="left", vertical="top", wrap_text=True)
_CENTRO = Alignment(horizontal="center", vertical="center")
_DER = Alignment(horizontal="right", vertical="center")

_PROVENANCIA = {
    "text_layer": "Capa de texto",
    "ocr_region": "OCR de encabezado",
    "ocr_full_page": "OCR de página completa",
    "vision_model": "Modelo de visión",
    "none": "Ilegible",
}


# -----------------------------------------------------------------------------
#  Piezas de maquetación
# -----------------------------------------------------------------------------


def _ancho(sheet: Worksheet, widths: list[float]) -> None:
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def _portada(sheet: Worksheet, span: int, titulo: str, subtitulo: str) -> int:
    """La banda superior. Una sola pieza oscura, sin adornos."""
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=span)

    cabecera = sheet.cell(row=1, column=1, value=titulo)
    cabecera.font = _TITULO
    cabecera.alignment = Alignment(horizontal="left", vertical="center", indent=1)

    pie = sheet.cell(row=2, column=1, value=subtitulo)
    pie.font = _SUBTITULO
    pie.alignment = Alignment(horizontal="left", vertical="center", indent=1)

    for row in (1, 2):
        for column in range(1, span + 1):
            sheet.cell(row=row, column=column).fill = _BANDA
    sheet.row_dimensions[1].height = 30
    sheet.row_dimensions[2].height = 16
    return 4


def _seccion(sheet: Worksheet, row: int, span: int, texto: str) -> int:
    """Un rótulo de sección: barra oscura de borde a borde."""
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    cell = sheet.cell(row=row, column=1, value=texto.upper())
    cell.font = _SECCION
    cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    for column in range(1, span + 1):
        sheet.cell(row=row, column=column).fill = _BANDA
    sheet.row_dimensions[row].height = 18
    return row + 1


def _campo(sheet: Worksheet, row: int, span: int, etiqueta: str, valor, relleno=None) -> int:
    """Etiqueta a la izquierda, valor en el resto de la fila. Todo con borde.

    Es la forma de un formulario, y la que hace que se pueda leer en diagonal:
    la columna de etiquetas siempre en el mismo sitio, el valor siempre alineado
    con el de arriba.
    """
    label = sheet.cell(row=row, column=1, value=etiqueta)
    label.font = _ETIQ
    label.fill = _ETIQUETA
    label.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    label.border = _CAJA

    sheet.merge_cells(start_row=row, start_column=2, end_row=row, end_column=span)
    value = sheet.cell(row=row, column=2, value=valor)
    value.font = _VALOR
    value.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    if relleno is not None:
        value.fill = relleno
    for column in range(2, span + 1):
        sheet.cell(row=row, column=column).border = _CAJA
    sheet.row_dimensions[row].height = 17
    return row + 1


def _cabecera_tabla(sheet: Worksheet, row: int, columnas: list[tuple[str, float]]) -> int:
    for index, (nombre, _) in enumerate(columnas, start=1):
        cell = sheet.cell(row=row, column=index, value=nombre.upper())
        cell.font = _COL
        cell.fill = _ENCABEZADO
        cell.border = Border(left=_FINO, right=_FINO, top=_MEDIO, bottom=_MEDIO)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[row].height = 26
    return row + 1


def _firma(sheet: Worksheet, row: int, span: int) -> int:
    """Dos casillas para firmar. Un acta sin dónde firmar no es un acta."""
    row += 1
    mitad = max(2, span // 2)
    for inicio, texto in ((1, "Entregado por"), (mitad + 1, "Recibido por")):
        fin = mitad if inicio == 1 else span
        sheet.merge_cells(start_row=row, start_column=inicio, end_row=row, end_column=fin)
        celda = sheet.cell(row=row, column=inicio, value="")
        celda.border = Border(bottom=Side(style="thin", color=_TENUE))
        for column in range(inicio, fin + 1):
            sheet.cell(row=row, column=column).border = Border(
                bottom=Side(style="thin", color=_TENUE)
            )

        sheet.merge_cells(start_row=row + 1, start_column=inicio, end_row=row + 1, end_column=fin)
        pie = sheet.cell(row=row + 1, column=inicio, value=f"{texto}   ·   nombre y fecha")
        pie.font = _PIE
        pie.alignment = Alignment(horizontal="left", vertical="top", indent=1)
    sheet.row_dimensions[row].height = 30
    return row + 3


def _imprimible(sheet: Worksheet, span: int, repetir: str | None = None) -> None:
    """Preparada para papel: sin cuadrícula, ajustada al ancho, con paginado.

    Esta planilla se imprime y se archiva. Que quepa en una hoja y repita la
    cabecera en cada página es la diferencia entre un documento y un volcado.
    """
    sheet.sheet_view.showGridLines = False
    sheet.page_setup.orientation = "landscape" if span > 5 else "portrait"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    sheet.page_margins.left = sheet.page_margins.right = 0.4
    sheet.page_margins.top = sheet.page_margins.bottom = 0.5
    if repetir:
        sheet.print_title_rows = repetir
    sheet.oddFooter.left.text = "&F"
    sheet.oddFooter.left.size = 8
    sheet.oddFooter.left.color = "9AA5AF"
    sheet.oddFooter.right.text = "Página &P de &N"
    sheet.oddFooter.right.size = 8
    sheet.oddFooter.right.color = "9AA5AF"


def _reloj(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y  %H:%M:%S")
    except ValueError:
        return value


def _peso(size: int) -> str:
    if not size:
        return "—"
    valor = float(size)
    for unidad in ("B", "KB", "MB", "GB"):
        if valor < 1024 or unidad == "GB":
            return f"{valor:,.1f} {unidad}".replace(",", "@").replace(".", ",").replace("@", ".")
        valor /= 1024
    return "—"


def _rangos(item: dict) -> str:
    numbers = item.get("page_numbers") or []
    if not numbers:
        first, last = item.get("first_page"), item.get("last_page")
        return f"{first}–{last}" if first and last else "—"
    partes: list[str] = []
    inicio = anterior = numbers[0]
    for numero in numbers[1:]:
        if numero == anterior + 1:
            anterior = numero
            continue
        partes.append(str(inicio) if inicio == anterior else f"{inicio}–{anterior}")
        inicio = anterior = numero
    partes.append(str(inicio) if inicio == anterior else f"{inicio}–{anterior}")
    return ", ".join(partes)


# -----------------------------------------------------------------------------
#  Los dos libros
# -----------------------------------------------------------------------------


class ExcelInventory:
    """El acta de entrega de un documento procesado.

    Un listado de lo que salió es la mitad de lo que hace falta. La otra mitad
    es la prueba de que no se perdió nada: el documento traía 222 páginas, las
    resoluciones dan cuenta de 222, luego ninguna se perdió. Ese cuadre va
    arriba, resaltado, porque es lo que alguien mira antes de firmar.
    """

    COLUMNAS = [
        ("#", 5),
        ("Número de resolución", 20),
        ("Título", 54),
        ("Páginas", 14),
        ("Cant.", 7),
        ("Archivo generado", 46),
        ("Carpeta de destino", 34),
        ("Verificado", 11),
    ]

    def write(
        self,
        report: dict,
        destination: Path,
        *,
        delivered_to: str | None = None,
        operator: str | None = None,
        processed_at: str | None = None,
    ) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        inventory = report.get("inventory") or {}
        items = inventory.get("items") or []
        review = report.get("review_queue") or []
        repairs = report.get("repairs") or []
        quarantine = report.get("quarantine") or []
        stats = report.get("stats") or {}
        documento = report.get("document") or "documento"

        book = Workbook()
        self._resumen(
            book.active, documento, inventory, report, items, review, repairs,
            quarantine, stats, delivered_to, operator, processed_at,
        )
        self._resoluciones(book.create_sheet("Resoluciones"), documento, items, delivered_to)
        if review:
            self._revision(book.create_sheet("Revisión"), documento, review)
        if repairs:
            self._correcciones(book.create_sheet("Correcciones"), documento, repairs)

        target = destination / f"{Path(documento).stem}{SUFFIX}"
        book.save(target)
        return target

    # -- hoja 1 ---------------------------------------------------------------

    def _resumen(
        self, sheet, documento, inventory, report, items, review, repairs,
        quarantine, stats, delivered_to, operator, processed_at,
    ) -> None:
        sheet.title = "Resumen"
        span = 6
        _ancho(sheet, [26, 20, 20, 20, 20, 20])

        row = _portada(sheet, span, "INVENTARIO DE RESOLUCIONES",
                       "Acta de entrega de un documento procesado")

        row = _seccion(sheet, row, span, "Identificación")
        row = _campo(sheet, row, span, "Documento de origen", documento)
        row = _campo(sheet, row, span, "Procesado el", _reloj(processed_at))
        row = _campo(sheet, row, span, "Operador", operator or "no registrado")
        row = _campo(sheet, row, span, "Carpeta de destino",
                     delivered_to or "no se entregó a una carpeta")
        row = _campo(sheet, row, span, "Peso del documento",
                     _peso(int(inventory.get("source_bytes") or 0)))
        row += 1

        paginas = int(inventory.get("source_pages") or report.get("page_count") or 0)
        en_archivos = sum(int(item.get("page_count") or 0) for item in items)
        contabilizadas = en_archivos + len(quarantine)
        cuadra = contabilizadas == paginas

        row = _seccion(sheet, row, span, "Cuadre de páginas")
        row = _campo(sheet, row, span, "Páginas del documento", paginas)
        row = _campo(sheet, row, span, "Páginas en las resoluciones", en_archivos)
        row = _campo(sheet, row, span, "Páginas en cuarentena", len(quarantine))
        row = _campo(sheet, row, span, "Total contabilizado", contabilizadas)
        row = _campo(
            sheet, row, span, "Resultado",
            "CUADRA — ninguna página se perdió" if cuadra
            else f"NO CUADRA — faltan {paginas - contabilizadas} páginas",
            _CUADRA if cuadra else _NO_CUADRA,
        )
        row += 1

        row = _seccion(sheet, row, span, "Resultado del proceso")
        row = _campo(sheet, row, span, "Resoluciones generadas", len(items))
        row = _campo(sheet, row, span, "Requieren revisión", len(review),
                     _PENDIENTE if review else _CUADRA)
        row = _campo(sheet, row, span, "Correcciones de OCR", len(repairs))
        row += 1

        provenance = stats.get("by_provenance") or {}
        if provenance:
            row = _seccion(sheet, row, span, "Cómo se leyó cada página")
            for clave, etiqueta in _PROVENANCIA.items():
                cuenta = int(provenance.get(clave) or 0)
                if not cuenta:
                    continue
                parte = f"  ({100 * cuenta / paginas:.1f} %)" if paginas else ""
                row = _campo(sheet, row, span, etiqueta, f"{cuenta}{parte}")
            row = _campo(sheet, row, span, "Enviadas al modelo",
                         f"{stats.get('escalated', 0)}   (coste en tokens)")

        _firma(sheet, row, span)
        _imprimible(sheet, span)

    # -- hoja 2 ---------------------------------------------------------------

    def _resoluciones(self, sheet, documento, items, delivered_to) -> None:
        sheet.title = "Resoluciones"
        _ancho(sheet, [width for _, width in self.COLUMNAS])
        span = len(self.COLUMNAS)

        row = _portada(sheet, span, "RESOLUCIONES GENERADAS", documento)
        cabecera = row
        row = _cabecera_tabla(sheet, row, self.COLUMNAS)
        primera = row

        for indice, item in enumerate(items, start=1):
            valores = [
                indice,
                item.get("code") or "",
                item.get("title") or "—",
                _rangos(item),
                int(item.get("page_count") or 0),
                item.get("file_name") or "",
                delivered_to or "—",
                "",
            ]
            cebra = indice % 2 == 0
            for columna, valor in enumerate(valores, start=1):
                cell = sheet.cell(row=row, column=columna, value=valor)
                cell.font = _CELDA
                cell.border = _CAJA
                cell.alignment = (
                    _CENTRO if columna in (1, 4, 5, 8)
                    else _IZQ_ARRIBA if columna in (3, 6, 7)
                    else _IZQ
                )
                if cebra:
                    cell.fill = _CEBRA
            sheet.row_dimensions[row].height = 28
            row += 1

        if items:
            for columna in range(1, span + 1):
                cell = sheet.cell(row=row, column=columna)
                cell.border = Border(top=_MEDIO, left=_FINO, right=_FINO, bottom=_FINO)
            etiqueta = sheet.cell(row=row, column=4, value="TOTAL")
            etiqueta.font = _TOTAL
            etiqueta.alignment = _DER
            # Fórmula viva, no un número congelado: si se retira una resolución
            # y se borra su fila, el total la sigue.
            total = sheet.cell(row=row, column=5, value=f"=SUM(E{primera}:E{row - 1})")
            total.font = _TOTAL
            total.alignment = _CENTRO
            sheet.auto_filter.ref = f"A{cabecera}:{get_column_letter(span)}{row - 1}"

        sheet.freeze_panes = sheet.cell(row=primera, column=1)
        _imprimible(sheet, span, repetir=f"{cabecera}:{cabecera}")

    # -- hojas opcionales -----------------------------------------------------

    def _revision(self, sheet, documento, review) -> None:
        columnas = [("Página", 10), ("Motivo", 96), ("Resuelto por", 22), ("Fecha", 16)]
        _ancho(sheet, [width for _, width in columnas])
        row = _portada(sheet, len(columnas), "PÁGINAS QUE REQUIEREN REVISIÓN", documento)
        cabecera = row
        row = _cabecera_tabla(sheet, row, columnas)
        for indice, item in enumerate(review, start=1):
            for columna, valor in enumerate(
                [item.get("page"), item.get("reason") or "", "", ""], start=1
            ):
                cell = sheet.cell(row=row, column=columna, value=valor)
                cell.font = _CELDA
                cell.border = _CAJA
                cell.alignment = _CENTRO if columna in (1, 4) else _IZQ_ARRIBA
                if indice % 2 == 0:
                    cell.fill = _CEBRA
            sheet.row_dimensions[row].height = 26
            row += 1
        sheet.freeze_panes = sheet.cell(row=cabecera + 1, column=1)
        _imprimible(sheet, len(columnas), repetir=f"{cabecera}:{cabecera}")

    def _correcciones(self, sheet, documento, repairs) -> None:
        columnas = [("Página", 10), ("Se leyó", 20), ("Se aplicó", 20), ("Distancia", 12)]
        _ancho(sheet, [width for _, width in columnas])
        row = _portada(sheet, len(columnas), "CORRECCIONES DE OCR APLICADAS", documento)
        cabecera = row
        row = _cabecera_tabla(sheet, row, columnas)
        for indice, item in enumerate(repairs, start=1):
            for columna, clave in enumerate(("page", "observed", "applied", "distance"), start=1):
                cell = sheet.cell(row=row, column=columna, value=item.get(clave))
                cell.font = _CELDA
                cell.border = _CAJA
                cell.alignment = _CENTRO
                if indice % 2 == 0:
                    cell.fill = _CEBRA
            row += 1
        sheet.freeze_panes = sheet.cell(row=cabecera + 1, column=1)
        _imprimible(sheet, len(columnas), repetir=f"{cabecera}:{cabecera}")


class ExcelRunInventory:
    """El acta de una entrega completa, dejada en la carpeta de destino.

    Quien recibe seiscientos PDF necesita una página que diga qué llegó y de
    dónde salió cada archivo. Las actas por documento contestan eso documento a
    documento; ésta lo contesta para la entrega.
    """

    COLUMNAS = [
        ("#", 5),
        ("Número de resolución", 20),
        ("Título", 50),
        ("Documento de origen", 36),
        ("Páginas", 14),
        ("Cant.", 7),
        ("Archivo entregado", 46),
        ("Verificado", 11),
    ]

    def write(
        self,
        rows: list[dict],
        destination: Path,
        *,
        source: str | None = None,
        operator: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        delivered_to: str | None = None,
    ) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        book = Workbook()

        documentos = {row.get("source_document") for row in rows if row.get("source_document")}
        paginas = sum(int(row.get("page_count") or 0) for row in rows)

        sheet = book.active
        sheet.title = "Resumen"
        span = 6
        _ancho(sheet, [26, 20, 20, 20, 20, 20])

        row = _portada(sheet, span, "INVENTARIO DE LA ENTREGA",
                       "Acta de entrega de un lote de documentos procesados")

        row = _seccion(sheet, row, span, "Identificación")
        row = _campo(sheet, row, span, "Carpeta de origen", source or "—")
        # Dónde quedaron los PDF, que no siempre es dónde se escribe el libro:
        # el inventario completo se arma en una carpeta temporal y anunciarla no
        # le diría nada a nadie.
        row = _campo(sheet, row, span, "Carpeta de destino", delivered_to or str(destination))
        row = _campo(sheet, row, span, "Operador", operator or "no registrado")
        row = _campo(sheet, row, span, "Iniciada", _reloj(started_at))
        row = _campo(sheet, row, span, "Terminada", _reloj(finished_at))
        row += 1

        row = _seccion(sheet, row, span, "Contenido de la entrega")
        row = _campo(sheet, row, span, "Documentos procesados", len(documentos))
        row = _campo(sheet, row, span, "Resoluciones entregadas", len(rows))
        row = _campo(sheet, row, span, "Páginas en total", paginas)

        _firma(sheet, row, span)
        _imprimible(sheet, span)

        detalle = book.create_sheet("Resoluciones")
        _ancho(detalle, [width for _, width in self.COLUMNAS])
        ancho = len(self.COLUMNAS)

        fila = _portada(detalle, ancho, "RESOLUCIONES ENTREGADAS", delivered_to or str(destination))
        cabecera = fila
        fila = _cabecera_tabla(detalle, fila, self.COLUMNAS)
        primera = fila

        for indice, item in enumerate(rows, start=1):
            valores = [
                indice,
                item.get("code") or "",
                item.get("title") or "—",
                item.get("source_document") or "",
                item.get("pages") or _rangos(item),
                int(item.get("page_count") or 0),
                item.get("file_name") or "",
                "",
            ]
            for columna, valor in enumerate(valores, start=1):
                cell = detalle.cell(row=fila, column=columna, value=valor)
                cell.font = _CELDA
                cell.border = _CAJA
                cell.alignment = (
                    _CENTRO if columna in (1, 5, 6, 8)
                    else _IZQ_ARRIBA if columna in (3, 4, 7)
                    else _IZQ
                )
                if indice % 2 == 0:
                    cell.fill = _CEBRA
            detalle.row_dimensions[fila].height = 28
            fila += 1

        if rows:
            for columna in range(1, ancho + 1):
                detalle.cell(row=fila, column=columna).border = Border(
                    top=_MEDIO, left=_FINO, right=_FINO, bottom=_FINO
                )
            etiqueta = detalle.cell(row=fila, column=5, value="TOTAL")
            etiqueta.font = _TOTAL
            etiqueta.alignment = _DER
            total = detalle.cell(row=fila, column=6, value=f"=SUM(F{primera}:F{fila - 1})")
            total.font = _TOTAL
            total.alignment = _CENTRO
            detalle.auto_filter.ref = f"A{cabecera}:{get_column_letter(ancho)}{fila - 1}"

        detalle.freeze_panes = detalle.cell(row=primera, column=1)
        _imprimible(detalle, ancho, repetir=f"{cabecera}:{cabecera}")

        target = destination / RUN_SHEET
        book.save(target)
        return target
