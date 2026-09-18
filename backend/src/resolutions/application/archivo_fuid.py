"""Convierte la ficha de un archivo en la única fila de FUID que le toca.

El equivalente de `resolution_fuid` y `diploma_fuid` para el trabajo que no
parte nada. Aquellos reciben una agrupación y devuelven una fila por unidad
documental; este recibe un archivo entero y devuelve **una**, porque la unidad
documental es el archivo.

Las reglas de qué va en cada columna no son de este autor: salen del instructivo
del formato, y la que manda sobre todas es que lo que no se pudo leer se escribe
N/A. Una celda vacía en un inventario documental no dice "no aplica", dice "se
olvidó"; y una celda rellenada con algo plausible dice una mentira que nadie va
a poder rastrear hasta el papel.
"""

from __future__ import annotations

from datetime import date

from ..domain.ficha import Ficha
from .fuid import NO_APLICA, FuidRow, Ubicacion

#: Lo que se escribe como asunto de un archivo cuyo encabezado no se dejó leer.
#: Es deliberadamente pobre: quien revise el inventario tiene que ver de un
#: vistazo cuáles hay que mirar a mano, y "Documento sin identificar" se ordena
#: junto a los demás y se busca de una vez.
SIN_ASUNTO = "Documento sin identificar"

#: El soporte de lo que entra por aquí. Todo lo que este sistema inventaría es
#: un PDF, así que la columna no es una incógnita: es papel digitalizado.
SOPORTE = "Digital"


def fecha_fuid(valor: date | None) -> str:
    """La fecha como la pide el formato: DD-MM-AAAA, y N/A si no se leyó."""
    return valor.strftime("%d-%m-%Y") if valor is not None else NO_APLICA


def nota_de_lectura(ficha: Ficha) -> str:
    """Lo que hay que advertirle a quien firme el inventario.

    Sólo se escribe lo que falta. Un archivo bien leído no lleva nota: llenar
    la columna de frases correctas ("se leyeron 12 folios") entierra las tres
    que de verdad importan entre doscientas que no dicen nada.

    Que no haya número de documento no es una falta y no se advierte. El
    operador lo dijo de estos papeles: no todos traen consecutivo impreso, así
    que su ausencia es lo normal. Anotarla en cada fila llenaría el inventario
    entero de una advertencia que no pide ninguna acción, que es la forma más
    segura de que nadie lea las que sí.
    """
    faltas: list[str] = []
    if ficha.asunto is None:
        faltas.append("no se pudo leer el encabezado")
    if not ficha.esta_fechada:
        faltas.append("no se encontró ninguna fecha en el documento")
    return "; ".join(faltas)


def fila_del_archivo(
    ficha: Ficha,
    *,
    nombre_del_archivo: str,
    ubicacion: Ubicacion | None = None,
    orden: int = 1,
) -> FuidRow:
    """La fila que inventaría un archivo entero, sin haberlo partido."""
    donde = ubicacion or Ubicacion()

    return FuidRow(
        orden=orden,
        codigo_trd=donde.codigo_trd,
        asunto=ficha.asunto or SIN_ASUNTO,
        # El número impreso del documento es su identificación, que es lo que el
        # instructivo pide en estas dos columnas. En un archivo de un solo
        # documento las dos llevan el mismo número, y así se anota.
        consecutivo_inicial=ficha.consecutivo_inicial or NO_APLICA,
        consecutivo_final=ficha.consecutivo_final or NO_APLICA,
        fecha_inicial=fecha_fuid(ficha.fecha_inicial),
        fecha_final=fecha_fuid(ficha.fecha_final),
        caja=donde.caja,
        carpeta=donde.carpeta_de(nombre_del_archivo),
        tomo=NO_APLICA,
        otro=donde.otro,
        # Los folios son las páginas del PDF. No se descuentan las que salieron
        # en blanco: el folio existe aunque el escáner no viera nada en él.
        folios=ficha.folios,
        folios_siar=ficha.folios,
        soporte=SOPORTE,
        frecuencia=NO_APLICA,
        notas=nota_de_lectura(ficha),
    )
