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
from collections.abc import Sequence
from dataclasses import replace

from ..domain.diploma import DiplomaRecord
from .fuid import NO_APLICA, FuidRow, Ubicacion

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
    """El nombre del graduando y el título, que es lo que identifica el registro."""
    nombre = (registro.name or "").strip()
    titulo = (registro.degree or "").strip()
    folio = (registro.trusted_folio or "").strip()
    if nombre and titulo:
        base = f"{nombre} - {titulo}"
        return f"{base} ({folio})" if folio else base
    if nombre:
        return f"{nombre} ({folio})" if folio else nombre
    if titulo:
        return f"{titulo} ({folio})" if folio else titulo
    return folio or NO_APLICA


def filas_del_libro(
    registros: Sequence[DiplomaRecord],
    *,
    nombre_del_archivo: str,
    ubicacion: Ubicacion | None = None,
    desde: int = 1,
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
    """
    donde = ubicacion or Ubicacion()
    upd = donde.carpeta_de(nombre_del_archivo)

    filas: list[FuidRow] = []
    for registro in registros:
        if registro.carries_no_identifier and filas:
            anterior = filas[-1]
            filas[-1] = replace(
                anterior,
                folios=anterior.folios + 1,
                folios_siar=anterior.folios_siar + 1,
            )
            continue
        folio, _ = folio_confiable(registro)
        fecha = fecha_fuid(registro.graduation_date)
        filas.append(
            FuidRow(
                orden=desde + len(filas),
                codigo_trd=donde.codigo_trd,
                asunto=asunto(registro),
                # El número de identificación de la unidad documental. En estos
                # libros es la cédula del graduando; los libros antiguos no la
                # traen, y entonces es N/A.
                consecutivo_inicial=registro.identity_number or NO_APLICA,
                # El código del estudiante. Los libros de diplomas no lo
                # imprimen, así que aquí no se rellena nunca desde el papel.
                consecutivo_final=NO_APLICA,
                fecha_inicial=fecha,
                fecha_final=fecha,
                caja=donde.caja,
                carpeta=upd,
                # El libro empastado. Va en Tomo porque el instructivo reserva
                # esa columna justamente para los empastes, y porque cada página
                # lo dice de su puño: "libro No. 8".
                tomo=registro.book or NO_APLICA,
                otro=donde.otro,
                # Un folio por graduando. No es una constante cómoda: es lo
                # que hay. Sube sólo si detrás vienen caras sin identificador,
                # que son la vuelta de esta misma hoja.
                folios=1,
                folios_siar=1,
                soporte=NO_APLICA,
                frecuencia=NO_APLICA,
                # El folio de registro no tiene columna propia en el FUID y es
                # el dato con el que se localiza el asiento dentro del empaste,
                # así que va donde el instructivo manda lo relevante que no cabe
                # en las demás columnas.
                notas=f"Registrado a folio No. {folio}" if folio != NO_APLICA else "",
            )
        )
    return filas
