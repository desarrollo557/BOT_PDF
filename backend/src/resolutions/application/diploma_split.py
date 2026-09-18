"""Partir un libro de diplomas: un archivo por registro.

Un documento de resoluciones se parte por herencia -- un número manda hasta que
aparece otro -- y por eso una resolución puede ocupar cuarenta páginas. Un libro
de folios no funciona así: cada cara es un registro terminado, con su folio y su
graduando, y la división es uno a uno.

De modo que aquí no hay nada que agrupar. Lo único que hace falta decidir es
cómo se llama cada archivo y qué hacer cuando dos páginas dicen el mismo folio,
que en estos libros pasa: una hoja fotografiada dos veces produce dos registros
idénticos, y si los dos archivos se llamaran igual, el segundo borraría al
primero y nadie volvería a saber que la duplicación existió.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.diploma import DiplomaRecord, pertenece_al_anterior
from ..domain.folio_manuscrito import folios_comprobados
from ..domain.grouping import GroupingResult, PageGroup
from ..domain.resolution_code import ResolutionCode

#: El tipo documental de lo que sale de aquí. No se consulta al catálogo del
#: archivo -- que es de correspondencia de servicios públicos y no tiene ningún
#: tipo para un diploma universitario -- porque en esta ruta el dato se conoce:
#: el operador eligió partir un libro de diplomas.
TIPO_DIPLOMA = "DIPLOMA"


def _identity(
    record: DiplomaRecord, taken: set[str], orden: int, folio: str | None
) -> ResolutionCode:
    """Cómo se llama el archivo de este registro, sin pisar a ninguno.

    La cédula, que es la mejor identidad que tiene un diploma porque pertenece
    a la persona: el folio pertenece al libro y vuelve a empezar por uno en el
    tomo siguiente, así que dos libros de la misma estantería tienen los dos su
    folio 5 y sus archivos se pisarían.

    Y cuando no se leyó ninguna de las dos, el **orden del documento dentro
    del libro**: `001`, `002`, `003`. Es lo que permite partir un libro entero
    sin pagar una sola lectura, que es justo lo que hay que poder hacer: el
    corte sale de la tinta de la esquina y no necesita OCR, así que sin él se
    pierden los nombres pero no los documentos.

    Tres dígitos porque la carpeta se lista por nombre y "10" no puede ir antes
    que "2". Y un consecutivo y no el número de página porque cuenta lo que hay
    en la carpeta: el documento 57 es el archivo 57 de 199, mientras que
    "pagina-113" obliga a dividir mentalmente para saber por dónde va.

    No pretende ser el folio, y conviene no confundirlos: en el libro medido la
    cara 199 lleva escrito el folio 200, porque el foliador se saltó un número.
    Cuál es el folio de verdad sólo lo dice quien sepa leer manuscrito; el
    inventario, mientras tanto, dice qué páginas forman cada documento.

    Sin prefijo delante. Lo lleva el tipo documental, que va al final del nombre
    -- `7882907__ALBERTO-FERNANDEZ_DIPLOMA.pdf` -- y decirlo dos veces sólo
    gastaría los caracteres que Windows cuenta para su límite de ruta.

    Cuando no se pudo leer, el folio; y cuando tampoco, la página, que es un
    dato cierto. Nunca se inventa un número: un archivo mal nombrado se busca
    peor que uno llamado por su página.
    """
    identity = (record.identity_number or "").strip()
    base = identity or (folio or "").strip() or f"{orden:03d}"
    candidate = base if base not in taken else f"{base}-p{record.page_number}"
    taken.add(candidate)
    return ResolutionCode.try_parse(candidate) or ResolutionCode(
        value=f"PAGINA-{record.page_number}", raw=candidate
    )


def _subject(record: DiplomaRecord) -> str | None:
    """Lo que va en el nombre del archivo después del folio."""
    partes = [part for part in (record.name, record.degree) if part]
    return " ".join(partes) if partes else None


def _folios_creibles(records: Sequence[DiplomaRecord]) -> dict[int, str]:
    """De los folios leídos, los que encajan con la progresión del libro.

    Se comprueban todos igual, los impresos y los escritos a mano, porque en
    estos libros ninguno de los dos es fiable por sí solo. El impreso lo saca
    Tesseract de una capa de texto ruidosa: un "7" en la página 7 y un "3" en la
    395, que producían archivos llamados `7_DIPLOMA.pdf` y `3-p395_DIPLOMA.pdf`
    -- un folio inventado, que es peor que no tener ninguno, porque parece un
    dato.

    Los folios van en orden y de uno en uno, así que la distancia entre el folio
    y el lugar que ocupa su cara tiene que ser la misma en todo el libro. Lo que
    se aparte de esa distancia no se cree, y ese documento se nombra por su orden
    en la carpeta, que es un dato cierto.
    """
    aperturas = [
        record
        for indice, record in enumerate(records)
        if not pertenece_al_anterior(record, records[indice - 1] if indice else None)
    ]

    # Se comprueba la parte numérica y se conserva el folio tal como lo escribe
    # el papel: "336BIS" avanza en la progresión como 336 y se archiva como
    # 336BIS, que es lo que dice la hoja. Perderle el sufijo sería inventar un
    # folio distinto, y en estos libros el BIS existe precisamente para
    # distinguir dos registros que comparten número.
    tal_cual: dict[int, str] = {}
    numericos: list[tuple[int, str | None]] = []
    for record in aperturas:
        folio = (record.trusted_folio or "").strip()
        digitos = "".join(caracter for caracter in folio if caracter.isdigit())
        if folio:
            tal_cual[record.page_number] = folio
        numericos.append((record.page_number, digitos or None))

    return {
        pagina: tal_cual[pagina]
        for pagina in folios_comprobados(numericos)
        if pagina in tal_cual
    }


def group_by_record(records: Sequence[DiplomaRecord]) -> GroupingResult:
    """Un archivo por registro, con las páginas que ese registro se lleve.

    Lo que decide dónde empieza cada registro es el folio escrito a mano en la
    esquina superior derecha, con su "v" al lado. El archivo de la Universidad
    escanea las hojas por las dos caras y sólo la de delante lleva folio, de
    manera que una cara sin folio no es un registro: es la vuelta de la hoja
    anterior, o algo que alguien anexó -- la fotografía de una cédula, un
    formato --, y va en el mismo archivo.

    De ahí que la señal sea la presencia de la marca y no lo que diga el papel:
    en estos libros todo lo variable está manuscrito y el OCR no lo lee. Medido
    sobre `UPD3859766`, 398 páginas: la marca reconoce 197 de las 199 caras de
    delante en once segundos, mientras que pasarle OCR cuesta 752 y deja el
    folio sin leer en 228 páginas. Cuando no se pudo mirar la esquina se cae a
    la regla anterior, la de los identificadores leídos, y donde tampoco ella
    dice nada la hoja se queda con el registro abierto.

    Cuando dos páginas repiten el mismo folio, sólo se agrupan si pertenecen a la
    misma cédula. Si el folio repite pero el graduando es distinto, no hay
    excepción: son dos registros diferentes y cada uno sale por su identidad.
    """
    taken: set[str] = set()
    creibles = _folios_creibles(records)
    abiertos: list[tuple[ResolutionCode, list[int], str | None, DiplomaRecord]] = []
    for record in records:
        # Lo primero que se mira, porque es lo primero que miraría un archivista:
        # si la esquina alta lleva folio escrito a mano. Esa marca la puso quien
        # armó el libro para decir dónde empieza cada hoja, y decide sin
        # depender de que el OCR haya sabido leer una palabra -- que en estos
        # libros, con todo lo variable manuscrito, casi nunca sabe.
        # La misma regla que usa el FUID para sumarle un folio a una fila, y
        # tiene que ser la misma: si el inventario contara una fila donde la
        # carpeta escribe media, prometería más diplomas de los que hay.
        padre = abiertos[-1][3] if abiertos else None
        if abiertos and pertenece_al_anterior(record, padre):
            abiertos[-1][1].append(record.page_number)
            continue

        identity = _identity(
            record, taken, len(abiertos) + 1, creibles.get(record.page_number)
        )
        abiertos.append((identity, [record.page_number], _subject(record), record))
    return GroupingResult(
        groups=[
            # El tipo documental viene puesto de aquí y no de la clasificación,
            # porque aquí se sabe con certeza: quien llega a esta función está
            # partiendo un libro de registro de diplomas, y cada unidad que sale
            # es un diploma. Preguntárselo al catálogo era inventarse una duda
            # que no existe, y contestaba mal: el diploma empieza por "LA
            # REPUBLICA DE COLOMBIA", que el catálogo reconoce como el
            # encabezado de una cédula de ciudadanía, así que las 199 unidades
            # del libro medido salían llamadas DOCUMENTO-DE-IDENTIDAD.
            PageGroup(code=code, page_numbers=paginas, title=titulo, kind=TIPO_DIPLOMA)
            for code, paginas, titulo, _record in abiertos
        ]
    )
