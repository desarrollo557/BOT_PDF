"""La fila del Formato Único de Inventario Documental, sin Excel de por medio.

El FUID es un formato, no un archivo: las mismas dieciséis columnas valen para
la planilla que se firma, para una consulta a la base y para lo que se muestre
en pantalla. Por eso la fila vive aquí, en la aplicación, y el adaptador que
sabe de openpyxl la recibe ya decidida.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

#: Lo que el instructivo del formato manda escribir donde no hay dato. Nunca se
#: deja en blanco -- una celda vacía no dice "no aplica", dice "se olvidó" -- y
#: nunca se rellena con algo verosímil.
NO_APLICA = "N/A"


@dataclass(frozen=True, slots=True)
class FuidRow:
    """Una fila del inventario, en el orden de las columnas del formato.

    Los nombres son los del FUID y no los del documento de origen, para que
    quien lea esto con la plantilla delante siga la correspondencia sin traducir.
    """

    orden: int
    asunto: str
    codigo_trd: str = NO_APLICA
    consecutivo_inicial: str = NO_APLICA
    consecutivo_final: str = NO_APLICA
    fecha_inicial: str = NO_APLICA
    fecha_final: str = NO_APLICA
    caja: str = NO_APLICA
    carpeta: str = NO_APLICA
    tomo: str = NO_APLICA
    otro: str = NO_APLICA
    folios: int = 1
    folios_siar: int = 1
    soporte: str = NO_APLICA
    frecuencia: str = NO_APLICA
    notas: str = ""
    #: En qué página del PDF de origen empieza esta unidad documental.
    #:
    #: No es una columna del formato y no sale en `as_cells`: es la costura por
    #: la que esta fila se vuelve a encontrar con el archivo que se escribió
    #: para ella. Emparejarlas por su posición en las dos listas parece
    #: equivalente y no lo es -- una unidad que no se pudo escribir desaparece
    #: de la lista de archivos y desde ahí todo queda corrido una fila --, y un
    #: inventario corrido una fila es peor que uno sin nombres de archivo.
    pagina_inicial: int | None = None

    def as_cells(self) -> list[object]:
        """Los valores en el orden de las columnas A a P de la plantilla."""
        return [
            self.orden,
            self.codigo_trd,
            self.asunto,
            self.consecutivo_inicial,
            self.consecutivo_final,
            self.fecha_inicial,
            self.fecha_final,
            self.caja,
            self.carpeta,
            self.tomo,
            self.otro,
            self.folios,
            self.folios_siar,
            self.soporte,
            self.frecuencia,
            self.notas,
        ]



def con_los_archivos(
    filas: Sequence[FuidRow], archivos: Mapping[int, str]
) -> list[FuidRow]:
    """Las mismas filas, cada una diciendo cómo se llama su archivo.

    La planilla y la carpeta de salida son las dos mitades de la misma entrega y
    hasta ahora sólo se podían cruzar contando: la fila 57 correspondía al
    archivo 57 si nadie se había equivocado en medio. Escribirlo convierte esa
    correspondencia en algo comprobable -- quien recibe la caja lee la fila y
    sabe qué PDF abrir --, y de paso deja constancia de cuáles se nombraron por
    su folio o su orden porque el dato no se dejó leer.

    Va aparte de quien construye las filas porque los dos datos no se saben a la
    vez: el inventario se arma al leer el documento y los nombres de archivo no
    existen hasta que el escritor terminó de partirlo. Volver a armar las filas
    con los nombres dentro habría obligado a leer el documento dos veces.

    El emparejamiento es por **la página que abre la unidad** y no por la
    posición en la lista. La diferencia importa cuando una unidad no se pudo
    escribir: desaparece de la lista de archivos, y emparejar por posición
    correría una fila todos los nombres siguientes. Una fila sin nombre es un
    hueco que se ve; una fila con el nombre del archivo de al lado, no.
    """
    return [
        replace(fila, notas=_con_archivo(fila.notas, archivos.get(fila.pagina_inicial)))
        if fila.pagina_inicial in archivos
        else fila
        for fila in filas
    ]


def _con_archivo(notas: str, archivo: str | None) -> str:
    """Le añade el nombre del archivo a unas notas que ya dicen otra cosa.

    Se escribe sólo lo que hay. Una nota que dijera "Archivo: N/A" gastaría la
    única columna libre del formato en decir que no sabe nada.
    """
    if not archivo or f"Archivo: {archivo}" in notas:
        return notas
    return "; ".join(parte for parte in (notas, f"Archivo: {archivo}") if parte)


@dataclass(frozen=True, slots=True)
class Cabecera:
    """Lo que cambia de una entrega a otra en la parte alta del formato.

    Los dos primeros campos son los que la plantilla de la Universidad lleva
    escritos arriba, en dos celdas. Los demás son del formato F-PSD-001, que en
    vez de una cabecera aparte los repite en una columna de cada fila: son
    constantes de la entrega, no datos que se lean del papel, y por eso viajan
    aquí y no en la fila.

    Todos son opcionales y ninguno se inventa. El que no se indique sale como
    N/A, que es lo que el instructivo manda escribir donde no hay dato.
    """

    oficina_productora: str | None = None
    objeto: str | None = None
    entidad_remitente: str | None = None
    entidad_productora: str | None = None
    unidad_administrativa: str | None = None
    serie: str | None = None
    subserie: str | None = None
    elaborado_por: str | None = None


#: El número de la unidad documental que la Universidad estampa en el empaste o
#: en la carpeta. Va en el nombre del archivo digitalizado -- "4. 3858082
#: REGISTRO DE DIPLOMAS..." -- porque dentro del PDF no consta en ninguna parte.
#: Se escribe pelado, sin anteponerle "UPD": la columna ya se llama así.
#: Siete cifras sueltas, también pegadas a «UPD»: «UPD3859348» no tiene límite
#: de palabra entre la D y el 3, y con ``\b`` la carpeta salía N/A en las
#: corridas de carpeta, donde el UPD va en la subcarpeta del PDF.
_UPD_EN_EL_NOMBRE = re.compile(r"(?<!\d)(\d{7})(?!\d)")

#: Una carpeta que es una caja: «00C003269», o el número pelado «3220».
_CAJA_EN_LA_RUTA = re.compile(r"^(?:\d{2,3}C\d{6}|\d{3,6})$", re.IGNORECASE)


def upd_del_archivo(nombre: str) -> str:
    """El UPD que anuncia el nombre del archivo o su ruta, o N/A si no lo anuncia."""
    encontrado = _UPD_EN_EL_NOMBRE.search(nombre)
    return encontrado.group(1) if encontrado else NO_APLICA


def caja_de_la_ruta(nombre: str) -> str:
    """La caja que dice la ruta del PDF -- «3220\\UPD3859348\\…» --, o N/A.

    En una corrida de carpeta el archivo se entrega en cajas: una carpeta por
    caja, con el número de su sticker. Es lo único que dice dónde está el
    papel, y vale más que un número fijo en los ajustes, que se colaba en
    cajas que no eran la suya (la 3269 de los diplomas en las resoluciones de
    la 3220).
    """
    for parte in re.split(r"[\\/]", nombre)[:-1]:
        if _CAJA_EN_LA_RUTA.match(parte.strip()):
            return parte.strip()
    return NO_APLICA


@dataclass(frozen=True, slots=True)
class Ubicacion:
    """Dónde está físicamente lo que se inventaría.

    Es lo que el PDF no puede saber. La caja lleva un sticker que sólo existe en
    el depósito, así que su valor por defecto es N/A y no un número plausible: el
    operador lo indica, o queda declarado como ausente.
    """

    caja: str = NO_APLICA
    otro: str = NO_APLICA
    codigo_trd: str = NO_APLICA
    #: Cuando se indica, manda sobre el número que traiga el nombre del archivo.
    carpeta: str | None = None

    def carpeta_de(self, nombre_del_archivo: str) -> str:
        return self.carpeta or upd_del_archivo(nombre_del_archivo)

    def caja_de(self, nombre_del_archivo: str) -> str:
        """La caja que indicó el operador, o la que dice la ruta del PDF."""
        if self.caja and self.caja != NO_APLICA:
            return self.caja
        return caja_de_la_ruta(nombre_del_archivo)
