from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pymupdf

from ..application.control import NullRunControl, RunControl
from ..application.ports import AssemblyResult
from ..application.progress import (
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
    Stage,
)
from ..domain.grouping import GroupingResult
from ..domain.naming import RESOLUTION_PREFIX, output_filename
from .mupdf_messages import drenar, explicar

logger = logging.getLogger(__name__)

QUARANTINE_FILE = "_quarantine.pdf"

#: Scratch copy of a damaged source, renumbered so its objects can be grafted.
#: Deleted once the outputs are written.
REPAIRED_FILE = "_repaired.pdf"

#: Windows refuses to open a path longer than this, and the refusal arrives at
#: save time -- after every page has been read, grouped and copied. A resolution
#: lost to a long title is a resolution lost for no reason at all.
MAX_PATH = 260

#: Slack for the numbering a destination folder may add on collision, e.g.
#: " (2)" in a delivery folder that already holds the same number.
PATH_MARGIN = 10

#: Una referencia indirecta tal como aparece en la fuente de un objeto PDF:
#: ``70353 0 R``. El número que importa es el primero, el del objeto citado.
_REFERENCIA = re.compile(r"(?<![\d.])(\d+)\s+\d+\s+R(?![A-Za-z0-9])")


def objeto_que_no_resuelve(document: pymupdf.Document) -> int | None:
    """El primer objeto que el PDF cita y su tabla de referencias no contiene.

    Ésta es la avería que perdía resoluciones enteras y que no se ve al abrir el
    archivo. Un escaneo puede traer una tabla que se lee sin una queja y que,
    dentro, remite a un objeto inexistente -- en el material de la Universidad,
    un perfil de color ICC que el escáner nunca llegó a escribir. MuPDF no marca
    nada al abrirlo, porque hasta que alguien no pide ese objeto no hay nada que
    falle, y el fallo llega a media escritura, cuando el documento ya se leyó,
    se agrupó y se cuadró entero.

    Buscarlo es barato porque no hay que tocar el contenido: ``xref_object``
    devuelve el diccionario del objeto, no sus flujos, así que esto es un
    recorrido por los metadatos. Sobre un libro de 323 páginas y 68.309 objetos
    -- 192 MB en disco -- la pasada completa tarda menos de un segundo, frente a
    los minutos que cuesta reescribir el archivo. Sale a cuenta pagarla siempre
    con tal de saber, antes de escribir el primer archivo, si el origen aguanta.

    Devuelve el número del objeto que no se resuelve, o ``None`` si la tabla
    cierra.
    """
    total = document.xref_length()
    for xref in range(1, total):
        try:
            fuente = document.xref_object(xref, compressed=True)
        except Exception:  # noqa: BLE001 - un objeto ilegible ya es la avería
            logger.debug("el objeto %s no se deja leer", xref, exc_info=True)
            return xref
        for match in _REFERENCIA.finditer(fuente):
            citado = int(match.group(1))
            if citado >= total:
                return citado
    return None


def name_budget(destination: Path) -> int:
    """How many characters a file name may use inside ``destination``."""
    try:
        room = MAX_PATH - len(str(destination.resolve())) - 1 - PATH_MARGIN
    except OSError:
        room = MAX_PATH - len(str(destination)) - 1 - PATH_MARGIN
    # Never below what a bare code plus extension needs; a directory that deep
    # is a problem the operator has to solve, not one to silently mangle names
    # over.
    return max(room, 24)


def _runs(page_numbers: list[int]) -> Iterator[tuple[int, int]]:
    """Collapse page numbers into consecutive ranges.

    Copying a 40-page block as one range instead of 40 single-page inserts is
    roughly an order of magnitude fewer object rewrites in the output PDF.
    """
    if not page_numbers:
        return
    start = previous = page_numbers[0]
    for number in page_numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        yield start, previous
        start = previous = number
    yield start, previous


class _Origen:
    """El PDF de origen, con una reparación en la recámara.

    Copiar páginas de un PDF a otro es injertar objetos, y para eso los números
    que el árbol de páginas cita tienen que estar en la tabla de referencias
    cruzadas del origen. Cuando no lo están, MuPDF aborta el injerto con
    ``source object number out of range`` y la página se pierde.

    Hay dos formas de llegar a esa situación y sólo una se ve al abrir el
    archivo. Si MuPDF tuvo que reconstruir la tabla, lo dice (``is_repaired``) y
    se sabe de antemano. Pero un escaneo puede traer una tabla que se lee
    perfectamente y que, dentro, remite a objetos que no existen: MuPDF no marca
    nada, porque hasta que alguien no pide ese objeto no hay nada que falle. El
    daño aparece a media escritura, cuando ya se leyó, se agrupó y se cuadró el
    documento entero.

    Por eso la reparación se decide antes de escribir nada. Reescribir el origen
    -- guardarlo con la tabla renumerada y volver a abrirlo -- deja los números
    consistentes y el injerto vuelve a funcionar; cuesta una pasada sobre el
    archivo y se paga una sola vez por documento, no una por resolución.
    :meth:`preparar` mira las dos formas del daño: la que MuPDF ya marcó al
    abrir y la que sólo se ve recorriendo la tabla. Queda además el intento
    perezoso, por si algo se le escapa a las dos: la primera vez que una
    escritura falle.
    """

    def __init__(self, source: Path, destination: Path, nombre: str | None = None) -> None:
        self._source = source
        self._destination = destination
        #: Cómo se le nombra en los avisos. Las subidas llegan con un nombre
        #: generado y decir "6ea93142663d.pdf viene dañado" no identifica nada.
        self._nombre = nombre or source.name
        self._scratch: Path | None = None
        self._intentado = False
        self._document = pymupdf.open(source)

    @property
    def document(self) -> pymupdf.Document:
        return self._document

    @property
    def name(self) -> str:
        return self._nombre

    def preparar(self, avisar: Callable[[str], None] | None = None) -> None:
        """Dejar el origen en condiciones antes de escribir la primera salida.

        Repararlo aquí, y no cuando falle una escritura, es lo que evita dar por
        buena media entrega sacada de un documento del que MuPDF no puede
        copiarlo todo, y lo que le ahorra al operador un aviso de fallo por una
        avería que el sistema sabe arreglar. Revisar la tabla cuesta menos de un
        segundo incluso en un libro de 192 MB; repararla cuesta minutos, así que
        sólo se repara cuando la revisión encuentra algo.
        """
        if self._document.is_repaired:
            # MuPDF ya reconstruyó la tabla al abrirlo, así que los números que
            # cita el árbol de páginas no son los de la tabla que hay en
            # memoria. Aquí no hay nada más que mirar.
            logger.info(
                "%s trae la tabla de referencias cruzadas reconstruida por MuPDF",
                self._nombre,
            )
            self.normalizar(avisar)
            return

        if avisar is not None:
            avisar("revisando la tabla de objetos del documento")
        colgante = objeto_que_no_resuelve(self._document)
        if colgante is None:
            return
        logger.info(
            "%s cita el objeto %s, que no figura en su tabla de referencias cruzadas",
            self._nombre,
            colgante,
        )
        self.normalizar(avisar)

    def normalizar(self, avisar: Callable[[str], None] | None = None) -> bool:
        """Reescribir el origen para que sus objetos puedan injertarse.

        Devuelve si el documento cambió, que es lo que decide si vale la pena
        reintentar. Un segundo intento no repara más que el primero, así que
        sólo se prueba una vez por documento: insistir convertiría cada
        resolución de un archivo irrecuperable en otra pasada completa sobre el
        archivo.

        Se guarda con ``garbage=1`` y nada más. Lo que hay que arreglar es la
        tabla de referencias, y para eso basta con renumerar los objetos y
        volver a escribirla. ``clean`` reanaliza todos los flujos de contenido y
        ``deflate`` los recomprime uno a uno: en un escaneo, cuyo contenido ya
        son imágenes comprimidas, las dos cosas recorren el archivo entero para
        no arreglar nada.

        La diferencia no es de matiz. Sobre el libro de la Universidad que
        levantó la avería -- ``RESOLUCIONES 00960-00979.pdf``, 323 páginas y
        192 MB -- guardar con ``garbage=4, clean=True, deflate=True`` costó
        347,57 s y guardar con ``garbage=1`` costó 0,65 s; las dos copias
        admiten después el injerto de las 323 páginas y pesan lo mismo. Los
        casi seis minutos de la primera son exactamente el hueco que el
        registro del servicio mostraba entre la última resolución escrita antes
        de la reparación y la siguiente.
        """
        if self._intentado:
            return False
        self._intentado = True
        # Informativo y no advertencia: esto no es un problema del trabajo, es
        # un defecto del archivo de origen que el sistema arregla antes de
        # escribir nada, y en menos de un segundo. Lo que merece una advertencia
        # es lo que se pierde, y aquí no se pierde nada. Dicho a gritos, además,
        # tapaba en la consola los avisos que sí piden algo de alguien.
        logger.info(
            "%s trae la tabla de objetos dañada; se reescribe una copia "
            "normalizada antes de escribir las resoluciones",
            self._nombre,
        )
        if avisar is not None:
            # Reescribir un libro de cientos de megas tarda, y hasta ahora
            # transcurría sin que la pantalla dijera nada: la barra se quedaba
            # quieta y el trabajo parecía colgado.
            avisar("reparando la tabla de objetos del documento de origen")
        scratch = self._destination / REPAIRED_FILE
        try:
            self._document.save(scratch, garbage=1)
        except Exception as error:  # noqa: BLE001 - el original todavía sirve
            logger.warning(
                "no se pudo normalizar %s (%s); se sigue con el original",
                self._nombre,
                explicar(error),
            )
            scratch.unlink(missing_ok=True)
            return False
        self._document.close()
        self._document = pymupdf.open(scratch)
        self._scratch = scratch
        return True

    def close(self) -> None:
        self._document.close()
        if self._scratch is not None:
            # Es un archivo de trabajo, y quien abra la carpeta de salida tiene
            # que ver resoluciones, no una copia del documento que subió.
            self._scratch.unlink(missing_ok=True)


class PyMuPDFAssembler:
    """Writes one PDF per resolution, plus a file holding whatever was quarantined.

    Damage is expected, not exceptional. Scanners, mail gateways and decades-old
    archives all produce PDFs whose object tables do not survive a strict read,
    and a document that arrives at this stage has already been read, grouped and
    balanced -- losing it here would throw away all of that work.

    Por eso lo primero es mirar el origen: si su tabla de objetos no cierra, se
    repara antes de escribir la primera resolución, de modo que la entrega
    entera salga de un documento consistente. A partir de ahí el escritor
    degrada en cuatro pasos: copiar por bloques, reparar el origen y volver a
    copiarlo por bloques -- para el daño que la revisión no vea --, reconstruir
    el grupo página a página, y por último apartar las páginas que no se dejan
    copiar de ninguna manera, informando de ellas en vez de dar el documento por
    perdido.
    """

    def __init__(
        self,
        control: RunControl | None = None,
        progress: ProgressReporter | None = None,
        naming_prefix: str | None = RESOLUTION_PREFIX,
        # Si el título de la unidad va dentro del nombre del archivo. En un
        # libro de folios el título es de quién es el registro y hace falta;
        # en una caja revuelta es de qué páginas salió, que ya está en el
        # inventario y en el nombre sólo estorba.
        con_titulo: bool = False,
        nombre: str | None = None,
    ) -> None:
        #: Escribir cuatrocientos archivos tarda tanto como leerlos. Sin un punto
        #: de parada aquí, una cancelación pedida durante la escritura se
        #: ignoraba en silencio y el trabajo terminaba igual.
        self._control = control or NullRunControl()
        #: Y por la misma razón hay que contarlo. Escribir 287 archivos son
        #: decenas de segundos en los que la barra de páginas ya está al 100 %:
        #: sin decir por dónde va, el trabajo parece terminado y quieto.
        self._progress = progress or NullProgressReporter()
        #: La palabra con que empieza el nombre de cada archivo. Quien parte un
        #: documento sabe qué son sus unidades; el escritor no, y nombrar
        #: "RESOLUCION_728" a un folio de un libro de diplomas sería escribir en
        #: el disco algo que no es verdad.
        self._prefix = naming_prefix
        self._con_titulo = con_titulo
        #: Cómo llamó el operador al documento de origen. Las subidas se guardan
        #: con un nombre generado, y un aviso sobre "6ea93142663d.pdf" no dice
        #: de qué archivo se está hablando.
        self._nombre = nombre

    def write(
        self,
        source: Path,
        result: GroupingResult,
        destination: Path,
    ) -> AssemblyResult:
        destination.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        names: dict[str, str] = {}
        unwritable: dict[int, str] = {}
        budget = name_budget(destination)

        total = len(result.groups) + (1 if result.quarantine else 0)
        self._announce(0, total, "preparando el documento de origen")

        origin = _Origen(source, destination, self._nombre)
        try:
            # Antes de la primera resolución, no a mitad de la entrega. Y con la
            # cancelación consultada delante, porque reparar un libro de
            # cientos de megas es el tramo más largo de toda la escritura y no
            # tiene sentido empezarlo si el operador acaba de decir que pare.
            self._control.check()
            origin.preparar(lambda detalle: self._announce(0, total, detalle))

            for index, group in enumerate(result.groups, start=1):
                # Entre un archivo y el siguiente: el anterior ya está cerrado y
                # el siguiente aún no existe, así que aquí no se deja nada a
                # medio escribir.
                self._control.check()
                name = output_filename(
                    group.code,
                    group.title,
                    budget=budget,
                    prefix=self._prefix,
                    con_titulo=self._con_titulo,
                    kind=group.kind,
                )
                target = destination / name
                if self._write_guarded(origin, group.page_numbers, target, unwritable):
                    written.append(target)
                    names[group.code.value] = name
                self._announce(index, total, name)

            if result.quarantine:
                # Never dropped, never guessed at: quarantined pages ship as their
                # own file so the operator can see exactly what was set aside.
                target = destination / QUARANTINE_FILE
                if self._write_guarded(origin, result.quarantine, target, unwritable):
                    written.append(target)
                self._announce(total, total, QUARANTINE_FILE)
        finally:
            origin.close()
            # Lo que MuPDF fue anotando mientras se copiaban las páginas, dicho
            # en español y con el documento delante. Vaciarlo aquí es además lo
            # que impide que su almacén global siga creciendo documento tras
            # documento en la vida del worker.
            drenar(origin.name)

        return AssemblyResult(outputs=written, unwritable_pages=unwritable, written=names)

    def _announce(self, done: int, total: int, detail: str) -> None:
        """Decir por dónde va. Un fallo del aviso nunca interrumpe la escritura."""
        try:
            self._progress.emit(
                ProgressEvent(stage=Stage.ASSEMBLING, done=done, total=total, detail=detail)
            )
        except Exception:  # noqa: BLE001 - la telemetría nunca rompe el trabajo
            logger.debug("no se pudo anunciar el avance de la escritura", exc_info=True)

    def _write_guarded(
        self,
        origin: _Origen,
        page_numbers: list[int],
        target: Path,
        unwritable: dict[int, str],
    ) -> bool:
        """Write one file, containing any failure to that file.

        The last line of defence. Whatever goes wrong with one resolution, the
        other resolutions of the same document still get written, and the pages
        of the one that failed are named rather than quietly missing.
        """
        try:
            return self._write_pages(origin, page_numbers, target, unwritable)
        except Exception as error:  # noqa: BLE001 - contained to this file
            motivo = explicar(error)
            logger.warning("no se pudo escribir %s: %s", target.name, motivo)
            target.unlink(missing_ok=True)
            for page_number in page_numbers:
                unwritable.setdefault(page_number, motivo)
            return False

    def _write_pages(
        self,
        origin: _Origen,
        page_numbers: list[int],
        target: Path,
        unwritable: dict[int, str],
    ) -> bool:
        """Write one output file. Returns whether anything was actually written.

        Tres intentos, de más barato a más caro. El rápido copia rangos enteros y
        guarda una vez, que es lo que necesita cualquier documento sano. Si algo
        ahí levanta -- incluido el guardado, porque MuPDF resuelve los objetos
        injertados de forma perezosa y un objeto dañado sale por ahí y no en el
        insert -- se repara el origen y se vuelve a probar el camino rápido. Y
        sólo si eso tampoco basta se reconstruye el grupo página a página.

        El orden importa. Ir directamente a la copia página a página, que es lo
        que se hacía antes, no arregla nada cuando el daño está en la tabla del
        origen: la copia de una sola página injerta desde el mismo documento roto
        y falla exactamente igual, y la página se da por perdida sin haber
        probado lo único que la salvaba.

        Los pasos intermedios se cuentan como informativos y no como advertencia.
        Que un camino no sirva y se pruebe el siguiente no es una pérdida: la
        pérdida, si la hay, la avisa quien la sufre -- la página que no se deja
        copiar o el archivo que no se llega a escribir. Mezclarlas dejaba en la
        consola del operador la palabra "falló" junto al nombre de una
        resolución que acabó saliendo entera.
        """
        try:
            if self._write_in_blocks(origin.document, page_numbers, target):
                return True
        except Exception as error:  # noqa: BLE001 - se repara y se reintenta
            logger.info(
                "la copia por bloques de %s no salió a la primera (%s); "
                "se repara el origen y se reintenta",
                target.name,
                explicar(error),
            )
            target.unlink(missing_ok=True)
            if origin.normalizar():
                try:
                    if self._write_in_blocks(origin.document, page_numbers, target):
                        return True
                except Exception as segundo:  # noqa: BLE001 - queda el último camino
                    logger.warning(
                        "%s sigue sin poder copiarse por bloques tras normalizar "
                        "el origen (%s); se reconstruye página a página",
                        target.name,
                        explicar(segundo),
                    )
                    target.unlink(missing_ok=True)

        return self._write_page_by_page(origin.document, page_numbers, target, unwritable)

    @staticmethod
    def _write_in_blocks(
        origin: pymupdf.Document, page_numbers: list[int], target: Path
    ) -> bool:
        """The fast path: one insert per consecutive range, one save."""
        if not page_numbers:
            return False
        with pymupdf.open() as output:
            for first, last in _runs(page_numbers):
                output.insert_pdf(origin, from_page=first - 1, to_page=last - 1)
            output.save(target, garbage=3, deflate=True)
        return True

    def _write_page_by_page(
        self,
        origin: pymupdf.Document,
        page_numbers: list[int],
        target: Path,
        unwritable: dict[int, str],
    ) -> bool:
        """The salvage path: every page is proved on its own before it goes in.

        Each page is serialised by itself first. That forces MuPDF to resolve
        exactly one page's objects, so a page that cannot be copied fails here,
        by number, instead of poisoning the save of the whole file. It costs a
        serialise per page and runs only after the fast path has already failed.
        """
        with pymupdf.open() as output:
            copied = 0
            for page_number in page_numbers:
                try:
                    isolated = self._isolate(origin, page_number)
                except Exception as error:  # noqa: BLE001 - reported, not swallowed
                    # The page is lost, the document is not. It goes to review
                    # named, so nobody has to diff page counts to find it.
                    motivo = explicar(error)
                    logger.warning("la página %s no pudo copiarse: %s", page_number, motivo)
                    unwritable[page_number] = motivo
                    continue

                with pymupdf.open("pdf", isolated) as clean:
                    output.insert_pdf(clean)
                copied += 1

            if not copied:
                # Every page failed. An empty PDF on disk would look like a
                # resolution that legitimately has no pages.
                return False
            self._save_defensively(output, target)
        return True

    @staticmethod
    def _save_defensively(output: pymupdf.Document, target: Path) -> None:
        """Save, and if compaction is what objects to the file, save without it.

        Garbage collection and compression both walk every object. When one of
        them is what raises, writing the file plainly still produces a PDF a
        reader can open, which is the thing that actually matters.
        """
        try:
            output.save(target, garbage=3, deflate=True)
        except Exception as error:  # noqa: BLE001 - retried without compaction
            logger.warning(
                "el guardado compactado de %s falló (%s); se guarda sin compactar",
                target.name,
                explicar(error),
            )
            target.unlink(missing_ok=True)
            output.save(target)

    @staticmethod
    def _isolate(origin: pymupdf.Document, page_number: int) -> bytes:
        """Serialise one page on its own, so its damage cannot spread."""
        single = pymupdf.open()
        try:
            single.insert_pdf(origin, from_page=page_number - 1, to_page=page_number - 1)
            return single.tobytes(garbage=3, deflate=True)
        finally:
            single.close()
