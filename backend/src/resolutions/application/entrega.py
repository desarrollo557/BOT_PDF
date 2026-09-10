"""Lo que hay que hacer con una agrupación, se haya decidido como se haya decidido.

Cuatro rutas deciden qué páginas forman cada unidad documental, y cada una lo
hace de una manera distinta porque los papeles son distintos: una resolución se
agrupa por el número impreso que la manda, un folio de diplomas es una cara, un
expediente académico es una persona, y una caja de correspondencia se corta por
continuidad. Ahí acaban las diferencias.

A partir de ese punto las cuatro quieren exactamente lo mismo: saber qué clase
de papel es cada unidad y de cuándo es, comprobar que ninguna hoja se perdió,
escribir un PDF por unidad y levantar el inventario de lo que quedó en el disco.

La planilla no se escribe desde aquí: es un Excel, y quien habla con openpyxl es
un adaptador. La deja el borde, con el informe ya montado.

Eso es lo que hay aquí, y tenerlo en un solo sitio es el objetivo. Estuvo
repetido en las cuatro rutas del worker, escrito de forma ligeramente distinta
en cada una, y ese es el origen de una tanda entera de fallos: el inventario que
emparejaba archivos por posición se arregló en dos rutas y no en las otras dos;
la carpeta de destino llegó a tres de cuatro; la planilla automática, a dos.
Cada arreglo había que acordarse de hacerlo cuatro veces.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..domain.grouping import GroupingResult
from .clasificacion import describir
from .inventory import Inventory, build_inventory
from .ports import AssemblyResult, DocumentAssembler


@dataclass(frozen=True, slots=True)
class Entregado:
    """Lo que quedó en el disco y lo que se sabe de ello."""

    #: La agrupación tal como quedó: con el tipo y la fecha de cada unidad.
    agrupacion: GroupingResult
    #: Qué se pudo escribir y qué no.
    assembly: AssemblyResult
    #: Una fila por archivo que existe de verdad.
    inventario: Inventory

    @property
    def salidas(self) -> list[str]:
        """Los archivos producidos, tal como los nombra el inventario.

        Del inventario y no de `assembly.outputs`, aunque salgan de lo mismo:
        dos listas construidas por caminos distintos acaban discrepando, y la
        que manda es la que dice qué archivo tiene qué páginas.
        """
        return [item.file_name for item in self.inventario.items]

    @property
    def ilegibles(self) -> dict[str, str]:
        """Las páginas que no se pudieron copiar, por número."""
        return {str(page): error for page, error in self.assembly.unwritable_pages.items()}

    @property
    def grupos_para_el_informe(self) -> list[dict[str, object]]:
        """Las unidades como las lee la pantalla."""
        anexos = {
            grupo.code.value: list(grupo.attachment_pages)
            for grupo in self.agrupacion.groups
            if getattr(grupo, "attachment_pages", None)
        }
        return [
            {
                "code": grupo.code.value,
                "title": grupo.title,
                # Qué clase de papel resultó ser y de cuándo es. Van al informe
                # además de al nombre del archivo porque son lo que alimenta el
                # inventario, y porque un tipo discutible se corrige en la
                # pantalla sin volver a leer el documento.
                "type": grupo.kind,
                "fecha": grupo.fecha,
                "pages": list(grupo.page_numbers),
                "size": grupo.size,
                "attachments": anexos.get(grupo.code.value, []),
            }
            for grupo in self.agrupacion.groups
        ]


@dataclass(frozen=True, slots=True)
class Destino:
    """Dónde va lo que se produzca, y bajo qué nombre.

    ``carpeta`` es el tramo que se antepone al nombre de cada archivo en el
    inventario: los documentos de una caja se entregan juntos bajo el nombre de
    su origen, y lo que la descarga recibe es la ruta dentro del trabajo y no
    sólo el nombre del archivo.

    ``entregado_en`` es a dónde acabará la copia cuando el trabajo viene de una
    corrida sobre carpeta local. Es sólo un dato que la planilla declara; quien
    copia es otro.
    """

    directorio: Path
    carpeta: str | None = None
    entregado_en: str | None = None


def entregar(
    agrupacion: GroupingResult,
    *,
    origen: Path,
    nombre: str,
    paginas: int,
    destino: Destino,
    assembler: DocumentAssembler,
    texto_de: Callable[[int], str] | None = None,
    en_revision: list[int] | None = None,
    estadisticas: dict[str, object] | None = None,
    anexos: dict[str, list[int]] | None = None,
    heredar_tipo: bool = True,
) -> Entregado:
    """Describe, comprueba, escribe e inventaría una agrupación ya decidida.

    El orden importa y es el mismo para las cuatro rutas:

    1. **Describir.** Qué es cada unidad y de cuándo, con la fuente todavía
       abierta. Va antes de escribir porque el tipo entra en el nombre del
       archivo.
    2. **Comprobar.** Que cada página de origen caiga en exactamente una unidad,
       antes de escribir un solo archivo. Una entrega que pierde o repite una
       hoja se ve idéntica a una correcta mirando la carpeta de salida.
    3. **Escribir.** Un PDF por unidad. Lo que no se pueda escribir se nombra.
    4. **Inventariar.** Una fila por archivo que existe, con el nombre real que
       el escritor puso en el disco.
    """
    descrita = describir(agrupacion, texto_de, heredar=heredar_tipo)
    descrita.verify_integrity(total_pages=paginas)

    assembly = assembler.write(origen, descrita, destino.directorio)

    inventario = build_inventory(
        source_document=nombre,
        source_pages=paginas,
        result=descrita,
        review_pages=list(en_revision or []),
        stats=estadisticas or {},
        file_names=assembly.written,
        folder=destino.carpeta,
        attachments=anexos,
    )
    return Entregado(agrupacion=descrita, assembly=assembly, inventario=inventario)
