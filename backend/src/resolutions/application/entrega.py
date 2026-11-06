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

import logging
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.conciliacion import Huella, comprobar_lo_escrito, rangos
from ..domain.grouping import GroupingResult
from .clasificacion import describir
from .inventory import Inventory, build_inventory
from .ports import AssemblyResult, DocumentAssembler
from .segment_split import ES_PROCEDENCIA, procedencia

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Entregado:
    """Lo que quedó en el disco y lo que se sabe de ello."""

    #: La agrupación tal como quedó: con el tipo y la fecha de cada unidad.
    agrupacion: GroupingResult
    #: Qué se pudo escribir y qué no.
    assembly: AssemblyResult
    #: Una fila por archivo que existe de verdad.
    inventario: Inventory
    #: Qué páginas de cada unidad llegaron como anexo y no como cuerpo, por
    #: código de unidad. Se guarda tal como llegó y no se recalcula: quien sabe
    #: que una hoja es un anexo es la ruta que decidió el corte, y esa relación
    #: no sobrevive a la agrupación -- un grupo es una lista de páginas y no
    #: distingue el acta de sus fotografías.
    anexos: dict[str, list[int]] = field(default_factory=dict)
    #: Lo escrito, vuelto a abrir y casado hoja por hoja con el original: vacío
    #: si la ruta no pidió comprobarlo. Ver ``comprobar_lo_escrito``.
    comprobacion: dict[str, object] = field(default_factory=dict)

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
        return [
            {
                "code": grupo.code.value,
                "title": _titulo(grupo),
                # Qué clase de papel resultó ser y de cuándo es. Van al informe
                # además de al nombre del archivo porque son lo que alimenta el
                # inventario, y porque un tipo discutible se corrige en la
                # pantalla sin volver a leer el documento.
                "type": grupo.kind,
                "fecha": grupo.fecha,
                "pages": list(grupo.page_numbers),
                "size": grupo.size,
                "attachments": list(self.anexos.get(grupo.code.value, [])),
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
    paginas_leidas: Sequence[int] | None = None,
    huellas: Callable[[Path], list[Huella]] | None = None,
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
    5. **Comprobar en el disco**, si la ruta da con qué leer ``huellas``: cada
       PDF escrito se vuelve a abrir y cada hoja se casa con la del original que
       le tocaba (lo pidió el operador el 2026-11-05: «validados de extremo a
       extremo»). No tumba la entrega: lo que no cuadra se declara.
    """
    descrita = describir(agrupacion, texto_de, heredar=heredar_tipo)
    # Al retomar una entrega a medias sólo se leyeron las páginas que faltaban,
    # y el cuadre es contra ésas: el resto ya está en el destino.
    descrita.verify_integrity(total_pages=paginas, paginas=paginas_leidas)

    assembly = assembler.write(origen, descrita, destino.directorio)

    # Una página que no se pudo copiar es lo único que el operador no puede
    # inferir mirando la salida: el archivo existe y simplemente tiene menos
    # adentro. Va a revisión venga de la ruta que venga.
    revision = sorted(set(en_revision or []) | set(assembly.unwritable_pages))

    inventario = build_inventory(
        source_document=nombre,
        source_pages=len(paginas_leidas) if paginas_leidas else paginas,
        result=descrita,
        review_pages=revision,
        stats=estadisticas or {},
        file_names=assembly.written,
        folder=destino.carpeta,
        attachments=anexos,
    )
    return Entregado(
        agrupacion=descrita,
        assembly=assembly,
        inventario=inventario,
        anexos={code: list(pages) for code, pages in (anexos or {}).items()},
        comprobacion=(
            comprobar_en_el_disco(origen, descrita, assembly, destino.directorio, huellas)
            if huellas is not None
            else {}
        ),
    )


def comprobar_en_el_disco(
    origen: Path,
    agrupacion: GroupingResult,
    assembly: AssemblyResult,
    directorio: Path,
    huellas: Callable[[Path], list[Huella]],
) -> dict[str, object]:
    """Cada PDF escrito, vuelto a abrir y casado hoja por hoja con el original.

    Nunca lanza: una comprobación que no se pudo hacer se dice como tal, y la
    entrega sigue siendo la que se escribió.
    """
    esperado: dict[str, list[int]] = {}
    for grupo in agrupacion.groups:
        nombre = assembly.written.get(grupo.code.value)
        if nombre:
            esperado[nombre] = [p for p in grupo.page_numbers if p not in assembly.unwritable_pages]
    return comprobar_archivos(origen, esperado, directorio, huellas)


def comprobar_archivos(
    origen: Path,
    esperado: Mapping[str, Sequence[int]],
    directorio: Path,
    huellas: Callable[[Path], list[Huella]],
    *,
    paginas_del_original: int | None = None,
) -> dict[str, object]:
    """Cada archivo de ``esperado``, vuelto a abrir y casado hoja por hoja con el original.

    La de cualquier habilidad que escribe por su cuenta -- las historias con la
    ficha primero, Kingspan por su serie --: ``esperado`` dice qué hojas del
    original lleva cada archivo (relativo a ``directorio``), en el orden en que
    se escribieron. Con ``paginas_del_original``, además, que ninguna hoja se
    quede fuera de todos ni vaya en dos: lo que ``entregar`` comprueba antes de
    escribir y estas rutas no tenían quien lo comprobara.
    """
    problemas: list[dict[str, object]] = []
    if paginas_del_original:
        # La cobertura no necesita abrir nada: sale de lo que se quiso escribir.
        cuantas = Counter(p for paginas in esperado.values() for p in paginas)
        fuera = [p for p in range(1, paginas_del_original + 1) if p not in cuantas]
        dobles = sorted(p for p, veces in cuantas.items() if veces > 1)
        if fuera:
            problemas.append(
                {"archivo": None, "pagina": fuera[0], "texto": f"hojas del original en ningún PDF: {rangos(fuera)}"}
            )
        if dobles:
            problemas.append(
                {"archivo": None, "pagina": dobles[0], "texto": f"hojas del original en más de un PDF: {rangos(dobles)}"}
            )
    if not Path(origen).is_file():
        return {"comprobada": False, "resumen": "Entrega sin comprobar: el origen no es un PDF", "problemas": problemas}
    try:
        del_origen = huellas(Path(origen))
    except Exception as error:  # noqa: BLE001 - sin el original no hay con qué casar
        logger.warning("no se pudo leer el original para comprobar la entrega", exc_info=True)
        return {
            "comprobada": False,
            "resumen": f"Entrega sin comprobar: el original no se dejó leer ({type(error).__name__})",
            "problemas": problemas,
        }
    escritos: dict[str, list[Huella] | None] = {}
    for nombre in esperado:
        try:
            escritos[nombre] = huellas(Path(directorio) / nombre)
        except Exception:  # noqa: BLE001 - el archivo que no se abre es el problema
            logger.warning("no se pudo abrir %s para comprobarlo", nombre, exc_info=True)
            escritos[nombre] = None
    problemas.extend(comprobar_lo_escrito(del_origen, escritos, esperado))
    hojas = sum(len(p) for p in esperado.values())
    resumen = (
        f"Entrega comprobada: {len(esperado)} PDF y {hojas} hojas, cada una en su sitio"
        if not problemas
        else f"Entrega comprobada con {len(problemas)} problema(s): {problemas[0]['texto']}"
    )
    return {
        "comprobada": True,
        "archivos": len(esperado),
        "hojas": hojas,
        "problemas": problemas,
        "resumen": resumen,
    }


def _titulo(grupo) -> str | None:
    """El título del grupo; si sólo dice de qué páginas salió, con las de ahora.

    Ese texto se pone al primer corte, y las reglas del sello -- «Folios: 19» --
    alargan después el documento: el informe decía «15 pág. · páginas 5-6»
    (UPD2465646, 2026-10-28). El archivo salía bien; lo que mentía era el texto.
    """
    titulo = grupo.title
    if titulo and grupo.page_numbers and ES_PROCEDENCIA.fullmatch(titulo):
        return procedencia(grupo.page_numbers)
    return titulo
