from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.grouping import GroupingResult


@dataclass(frozen=True, slots=True)
class InventoryItem:
    """One generated PDF, traced back to the pages it came from."""

    file_name: str
    code: str
    title: str | None
    page_count: int
    page_numbers: list[int]
    #: Qué clase de papel resultó ser, con el nombre del catálogo del archivo.
    #: Lo pone la clasificación, que corre después del corte. Vacío en las
    #: unidades que nadie clasificó -- una resolución se identifica por su
    #: número y no necesita tipo -- y por eso no se rellena con nada: una
    #: columna que dice "FACTURA" porque era lo más parecido es peor que una
    #: vacía, que al menos se puede filtrar.
    kind: str | None = None
    #: La fecha más reciente escrita en el documento, en ISO. Es la que fecha
    #: la unidad -- la fecha extrema final del FUID -- y se lee del texto
    #: porque estos papeles son escaneos y no traen metadatos.
    fecha: str | None = None
    #: Las páginas de esta unidad que entraron como anexo y no como cuerpo. Van
    #: dentro de ``page_numbers`` -- un anexo no es un documento aparte -- y se
    #: anotan porque perder la relación es perder la única respuesta a "¿de qué
    #: acta son estas fotos?".
    attachment_pages: list[int] = field(default_factory=list)

    @property
    def first_page(self) -> int:
        return self.page_numbers[0]

    @property
    def last_page(self) -> int:
        return self.page_numbers[-1]

    def as_dict(self) -> dict[str, object]:
        return {
            "file_name": self.file_name,
            "code": self.code,
            "title": self.title,
            "type": self.kind,
            "fecha": self.fecha,
            "page_count": self.page_count,
            "first_page": self.first_page,
            "last_page": self.last_page,
            "page_numbers": self.page_numbers,
            "attachments": self.attachment_pages,
        }


@dataclass(frozen=True, slots=True)
class Inventory:
    """What came out of one source document, and where every page went.

    This is the audit trail: given a generated file you can name the pages it
    came from, and given a source page you can name the file it ended up in.
    """

    source_document: str
    source_pages: int
    items: list[InventoryItem] = field(default_factory=list)
    quarantine_pages: list[int] = field(default_factory=list)
    review_pages: list[int] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)

    @property
    def pages_accounted_for(self) -> int:
        return sum(item.page_count for item in self.items) + len(self.quarantine_pages)

    def as_dict(self) -> dict[str, object]:
        return {
            "source_document": self.source_document,
            "source_pages": self.source_pages,
            "generated_files": len(self.items),
            "pages_accounted_for": self.pages_accounted_for,
            "items": [item.as_dict() for item in self.items],
            "quarantine_pages": self.quarantine_pages,
            "review_pages": self.review_pages,
            "stats": self.stats,
        }


def build_inventory(
    source_document: str,
    source_pages: int,
    result: GroupingResult,
    review_pages: list[int],
    stats: dict[str, object],
    file_names: dict[str, str] | None = None,
    folder: str | None = None,
    attachments: dict[str, list[int]] | None = None,
) -> Inventory:
    """Describe what one document produced. One row per file actually on disk.

    ``file_names`` es lo que el escritor dejó en el disco, indexado por código.
    Manda sobre cualquier nombre recalculado, porque el escritor puede acortar
    uno para que quepa en el sistema de archivos y un inventario que nombra un
    archivo que nadie puede abrir es peor que no tener inventario.

    Y por eso una unidad que no aparece en ese mapa **no produce fila**. Antes
    se le inventaba el nombre que le habría tocado: el archivo no se había
    escrito -- una página con los objetos rotos se lleva por delante el PDF
    entero de su unidad -- y aun así el inventario lo listaba y la pantalla
    enlazaba a una descarga que contesta 404. Sus páginas no se pierden de
    vista: `_write_guarded` las mete una por una en `unwritable_pages`, que es
    lo que las lleva a la cola de revisión.

    ``folder`` es la carpeta en que quedaron, dentro del trabajo, cuando los
    archivos de un documento se entregan agrupados bajo el nombre de su origen.
    Va delante del nombre porque lo que la descarga recibe es la ruta dentro
    del trabajo y no sólo el nombre del archivo.

    ``attachments`` dice, por código, qué páginas de esa unidad llegaron como
    anexo. Sin esto un acta con sus cuatro fotografías es indistinguible en el
    inventario de un acta de cinco hojas.
    """
    names = file_names or {}
    anexos = attachments or {}
    items: list[InventoryItem] = []
    for group in result.groups:
        name = names.get(group.code.value)
        if not name:
            continue
        items.append(
            InventoryItem(
                file_name=f"{folder}/{name}" if folder else name,
                code=group.code.value,
                title=group.title,
                kind=group.kind,
                fecha=group.fecha,
                page_count=group.size,
                page_numbers=group.page_numbers,
                attachment_pages=list(anexos.get(group.code.value) or []),
            )
        )
    return Inventory(
        source_document=source_document,
        source_pages=source_pages,
        items=items,
        quarantine_pages=list(result.quarantine),
        review_pages=review_pages,
        stats=stats,
    )


def _por_codigo(outputs: list[str]) -> dict[str, str]:
    """Los archivos escritos, indexados por el código de la unidad que contienen.

    El código está siempre en el nombre, pero no siempre en el mismo sitio,
    porque hay tres formas de nombrar un archivo generado:

        RESOLUCION_00086.pdf              el prefijo delante y el código detrás
        01_NOTIFICACION-POR-AVISO.pdf     el código delante y el tipo detrás
        00072__por-medio-de-la-cual.pdf   el código delante y el asunto detrás

    Así que se prueban los cuatro tramos que pueden serlo y se indexan todos.
    Un tramo que aparece en dos archivos deja de identificar a ninguno y se
    descarta, en vez de elegirse a suertes.
    """
    encontrados: dict[str, str | None] = {}
    for output in outputs:
        nombre = str(output).replace("\\", "/").rsplit("/", 1)[-1]
        tronco = nombre.rsplit(".", 1)[0]
        piezas = {
            tronco,
            tronco.split("__", 1)[0],
            tronco.split("_", 1)[0],
            tronco.split("_", 1)[-1],
        }
        for pieza in piezas:
            clave = pieza.strip()
            if not clave:
                continue
            # None marca el tramo visto dos veces: deja de servir para decidir.
            encontrados[clave] = None if clave in encontrados else str(output)
    return {clave: valor for clave, valor in encontrados.items() if valor}


def rows_of(report: dict) -> list[dict[str, object]]:
    """Las filas que un informe terminado aporta al inventario.

    Existe porque hay dos formas de terminar y los dos almacenes tienen que
    entender las dos. La ruta de resoluciones deja un `inventory.items` ya
    armado; la de segmentación deja `groups` y `outputs` y ningún inventario,
    porque separar por continuidad no levanta FUID -- el formulario pide asunto
    y tipo documental, que son preguntas sobre un documento que ya tiene bordes.

    Tenerlo dos veces salió caro: el archivo JSONL sabía leer las dos formas y
    el de MySQL sólo la primera, así que una caja separada por documento
    escribía sus PDF y no aparecía en la pantalla de Archivo. Sin excepción, sin
    aviso y sin nada en el registro: `record` devolvía cero y nadie mira ese
    número.
    """
    inventory = report.get("inventory") or {}
    items = list(inventory.get("items") or [])
    if items:
        return items

    groups = report.get("groups") or []
    outputs = report.get("outputs") or []
    if not groups and not outputs:
        return []

    # Emparejar por código y no por posición.
    #
    # Las dos listas van en el mismo orden mientras se escriban todos los
    # archivos, y dejan de ir en cuanto uno falla: una unidad que el escritor no
    # pudo escribir no aparece en `outputs`, corre la lista, y a partir de ahí
    # cada grupo queda apuntando al PDF del siguiente. El inventario no falla
    # -- tiene tantas filas como antes -- y afirma de cada archivo unas páginas
    # que no son las suyas, que es la peor forma posible de estar mal.
    #
    # El nombre de un archivo empieza por el código de su unidad, así que se
    # puede reconstruir la correspondencia. Lo que no se reconoce no se
    # inventa: se queda fuera, porque una fila que nombra un archivo ajeno es
    # peor que una fila que falta.
    por_codigo = _por_codigo(outputs)
    for index, group in enumerate(groups):
        pages = list(group.get("pages") or [])
        code = str(group.get("code") or "")
        file_name = por_codigo.get(code)
        if file_name is None and len(outputs) == len(groups):
            # Sin ninguna baja, la posición sigue siendo de fiar y cubre los
            # nombres que no empiezan por su código.
            file_name = outputs[index]
        if not file_name:
            continue
        items.append(
            {
                "code": code,
                "title": group.get("title"),
                "type": group.get("type"),
                "fecha": group.get("fecha"),
                "file_name": file_name,
                "page_count": int(group.get("size") or len(pages) or 0),
                "first_page": pages[0] if pages else 0,
                "last_page": pages[-1] if pages else 0,
                "page_numbers": pages,
                "attachments": list(group.get("attachments") or []),
            }
        )

    # Un trabajo que escribió archivos sin dejar grupos sigue siendo trabajo
    # hecho, y el operador tiene que poder encontrarlo. Sólo sin grupos: con
    # ellos delante, unas filas sin código ni páginas no serían un respaldo,
    # serían el rastro bueno sustituido por uno peor.
    if not groups and not items and outputs:
        items = [
            {
                "code": "",
                "title": None,
                "file_name": file_name,
                "page_count": 1,
                "first_page": 0,
                "last_page": 0,
                "page_numbers": [],
            }
            for file_name in outputs
        ]
    return items
