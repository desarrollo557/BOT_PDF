"""Convierte los registros de diplomas en filas del FUID.

Aquí vive una sola cosa: la correspondencia entre lo que dice el papel y la
columna del formato en que se escribe. Está separada del lector y del escritor
porque es la parte discutible -- la que un archivista puede querer cambiar -- y
porque cada decisión necesita explicarse al lado del código que la aplica.

Las reglas salen del instructivo del propio FUID, que acompaña al formato:

  * "No. de orden: debe anotarse en forma consecutiva el número correspondiente
    de cada unidad documental por cajas."
  * "No. DOCUMENTO (desde - Hasta): debe anotarse el número consecutivo o número
    de Identificación de cada unidad documental."
  * "Fechas extremas: deben consignarse la fecha inicial y final de cada unidad
    documental... Cuando la documentación no tenga fecha se anotará N/A."
  * "UPD: se consignará el número asignado a cada unidad documental (carpeta,
    A-Z, legajos, empastes)."
  * "Tomo: se consignará el número asignado a cada unidad documental (Tomo,
    Empastes)."
  * "Soporte: se utilizará esta columna para anotar los soportes diferentes al
    papel."
  * "Notas: se consignarán los datos que sean relevantes y no se hayan
    registrado en las columnas anteriores."
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace

from ..domain.diploma import CriterioDeCorte, DiplomaRecord, pertenece_al_anterior
from .fuid import NO_APLICA, FuidRow, Ubicacion, con_los_archivos

#: Se reexporta porque nació aquí y hay quien la importa de este módulo.
__all__ = ["asunto", "con_los_archivos", "fecha_fuid", "filas_del_libro", "folio_confiable"]

_FECHA = re.compile(r"^(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{2,4})$")


def fecha_fuid(valor: str | None) -> str:
    """La fecha como la pide el encabezado del formato: DD-MM-AAAA.

    Una fecha ilegible se escribe N/A, que es lo que manda el instructivo. No se
    deduce del resto del libro ni se copia de la página vecina: una fecha
    inventada en un inventario documental es peor que un hueco declarado.
    """
    if not valor:
        return NO_APLICA
    partes = _FECHA.match(valor.strip())
    if not partes:
        return NO_APLICA
    dia, mes, anio = partes.groups()
    return f"{int(dia):02d}-{int(mes):02d}-{anio}"


def folio_confiable(registro: DiplomaRecord) -> tuple[str, bool]:
    """El folio en que se confía, y si las dos lecturas del papel discreparon.

    La regla de cuál creer vive en el dominio, junto al registro que la
    justifica; aquí sólo se traduce "no se pudo leer" al N/A que pide el
    instructivo del formato.
    """
    folio = registro.trusted_folio
    discrepan = bool(
        registro.folio and registro.registered_folio and registro.folio != registro.registered_folio
    )
    return (folio or NO_APLICA), discrepan


def asunto(registro: DiplomaRecord) -> str:
    """El nombre del graduando y el título en mayúsculas: NOMBRE - TÍTULO.

    Como lo escribe el inventario de referencia del archivo
    («ANGELICA MARIA CUELLO SALCEDO - ESPECIALISTA EN GERENCIA EN SALUD»,
    REGISTROS DE DIPLOMAS 3269 - 3291). El asiento ya no va aquí entre
    paréntesis: tiene su columna, «Otro».
    """
    nombre = (registro.name or "").strip()
    carrera = (registro.degree or "").strip().upper()
    if nombre and carrera:
        return f"{nombre} - {carrera}"
    return nombre or carrera or NO_APLICA


def asiento(registro: DiplomaRecord) -> str:
    """Dónde quedó registrado el diploma: «folio-libro», como «728-8».

    Es la columna «Otro» del inventario de referencia del archivo. Sin libro
    legible se escribe sólo el folio; sin folio no hay asiento.
    """
    folio, _ = folio_confiable(registro)
    if folio == NO_APLICA:
        return NO_APLICA
    libro = (registro.book or "").strip()
    return f"{folio}-{libro}" if libro else folio


def _notas(archivo: str | None) -> str:
    """Lo relevante de esta fila que no cabe en ninguna columna del formato.

    El nombre del archivo va aquí porque la planilla y la carpeta de salida son
    las dos mitades de la misma entrega y hasta ahora sólo se podían cruzar
    contando: la fila 57 correspondía al archivo 57 si nadie se había
    equivocado en medio. Escribirlo convierte esa correspondencia en algo
    comprobable -- quien recibe la caja lee la fila y sabe qué abrir --, y de
    paso deja constancia de cuáles se nombraron por su folio o por su orden
    porque la cédula no se dejó leer. El folio de registro ya no va aquí: tiene
    su columna, «Otro» (``asiento``).

    Se escribe sólo lo que hay. Una nota que dijera "Archivo: N/A" gastaría la
    única columna libre del formato en decir que no sabe nada.
    """
    return f"Archivo: {archivo}" if archivo else ""


def filas_del_libro(
    registros: Sequence[DiplomaRecord],
    *,
    nombre_del_archivo: str,
    ubicacion: Ubicacion | None = None,
    desde: int = 1,
    archivos: Mapping[int, str] | None = None,
    criterio: CriterioDeCorte = CriterioDeCorte.PAGINA,
) -> list[FuidRow]:
    """Una fila por registro, en el orden en que están en el PDF.

    El orden es el del documento y no el del folio: los libros alternan recto y
    verso sin un criterio fijo -- unas veces el BIS va antes y otras después --
    y el inventario tiene que poder recorrerse con el PDF al lado.

    Una página que no trae ningún identificador no abre fila. Es la vuelta de la
    hoja anterior -- el archivo escanea por las dos caras y lo anota con una "v"
    junto al folio escrito a mano -- o algo anexado, y no es una unidad
    documental: suma un folio a la fila de arriba, que es la misma decisión que
    toma el separador al meter esa página en el PDF de ese registro. Si las dos
    partes no dijeran lo mismo, el inventario prometería más diplomas de los que
    hay archivos en la carpeta.

    ``archivos`` dice cómo se llamó el PDF que se escribió para cada registro,
    indexado por la página que lo abre. Es opcional porque el inventario se
    levanta también cuando no se escribe ningún archivo -- un libro empastado
    que sólo se inventaría --, y entonces no hay ningún nombre que anotar.
    """
    donde = ubicacion or Ubicacion()
    upd = donde.carpeta_de(nombre_del_archivo)
    nombres = archivos or {}

    filas: list[FuidRow] = []
    padres: list[DiplomaRecord] = []
    for registro in registros:
        # El mismo criterio con que el separador partió la carpeta, y tiene que
        # ser el mismo: si el inventario contara una fila donde la carpeta
        # escribe media, prometería más diplomas de los que hay.
        if filas and pertenece_al_anterior(registro, padres[-1], criterio):
            anterior = filas[-1]
            filas[-1] = replace(
                anterior,
                folios=anterior.folios + 1,
                folios_siar=anterior.folios_siar + 1,
            )
            continue
        padres.append(registro)
        fecha = fecha_fuid(registro.graduation_date)
        cedula = registro.identity_number if registro.identity_creible else NO_APLICA
        filas.append(
            FuidRow(
                orden=desde + len(filas),
                codigo_trd=donde.codigo_trd,
                asunto=asunto(registro),
                # El número de identificación de la unidad documental. En estos
                # libros es la cédula del graduando; los libros antiguos no la
                # traen, y entonces es N/A. También va N/A cuando lo que se leyó
                # no se sostiene como cédula: un inventario documental con
                # "30761" en la columna de identificación es peor que uno con
                # N/A, porque N/A se puede filtrar y buscar, y un número
                # incompleto se da por bueno y nadie vuelve a mirarlo.
                consecutivo_inicial=cedula,
                # La misma cédula: el inventario de referencia del archivo la
                # escribe en las dos columnas del consecutivo.
                consecutivo_final=cedula,
                fecha_inicial=fecha,
                fecha_final=fecha,
                caja=donde.caja_de(nombre_del_archivo),
                carpeta=upd,
                # El libro va en «Otro», junto a su folio de registro --
                # «728-8» --, como en el inventario de referencia del archivo;
                # Tomo queda en N/A. Si el operador dio un «Otro» para toda la
                # caja, manda el suyo.
                tomo=NO_APLICA,
                otro=donde.otro if donde.otro != NO_APLICA else asiento(registro),
                # Un folio por graduando. No es una constante cómoda: es lo
                # que hay. Sube sólo si detrás vienen caras sin identificador,
                # que son la vuelta de esta misma hoja.
                folios=1,
                folios_siar=1,
                soporte=NO_APLICA,
                frecuencia=NO_APLICA,
                # El nombre del archivo, el dato relevante sin columna propia
                # en el formato (el folio de registro ya va en «Otro»). El
                # instructivo reserva Notas exactamente para eso -- "los datos
                # que sean relevantes y no se hayan registrado en las columnas
                # anteriores" --, y añadirle al FUID una columna decimoséptima
                # rompería la plantilla que se firma.
                notas=_notas(nombres.get(registro.page_number)),
                pagina_inicial=registro.page_number,
            )
        )
    return filas
