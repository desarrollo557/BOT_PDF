"""Lo que un PDF entero declara de sí mismo, para una sola fila del inventario.

Hay un trabajo que no es partir ni separar: inventariar. Llega un PDF que ya es
un documento -- una nota de ajuste, un comprobante de egreso, una conciliación
bancaria -- y lo único que hace falta es anotarlo en el Formato Único de
Inventario Documental: qué es, entre qué fechas va y cuántos folios ocupa. El
archivo no se toca.

La diferencia con el resto del sistema es la unidad. Al partir, la pregunta se
hace de cada grupo de páginas y sale una fila por documento; aquí la pregunta se
hace del archivo completo y sale **una fila y sólo una**. Por eso las fechas
extremas se toman de punta a punta -- la más antigua que aparezca en cualquier
página y la más reciente -- en vez de por documento.

Lo que se lee sale de lo que está impreso, nunca del nombre del archivo. Un PDF
llamado "escaneo 3.pdf" que lleva impreso "NOTA DE AJUSTE" es una nota de
ajuste, y uno llamado "factura.pdf" cuyo encabezado dice otra cosa no lo es.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from .fechas import primera_fecha, ultima_fecha
from .tipo_documental import identificar_documento
from .title import extract_title

#: El número que estos documentos llevan impreso junto a "Número:", con la forma
#: que le da el sistema que los emite: el consecutivo de la compañía, las letras
#: del tipo y el correlativo -- "001-NA-00001204" es la nota de ajuste 1204.
#:
#: Se acepta un correlativo corto porque el OCR recorta ceros con frecuencia:
#: "001-NA-000" es lo que queda de un número cuyo final se perdió, y anotar el
#: número truncado sigue siendo mejor que dejar la columna vacía. Lo que no se
#: acepta es inventarle los dígitos que faltan.
_CONSECUTIVO = re.compile(r"\b(\d{3}-[A-Z]{2,4}-\d{3,10})\b")

#: Cuántas páginas del principio se miran buscando el título impreso. El
#: encabezado de un documento está en su primera hoja; si la primera es una
#: carátula o una separata en blanco, la siguiente lo lleva. Más allá de la
#: tercera ya se está leyendo el cuerpo, y de ahí no sale un título sino una
#: frase.
PAGINAS_DE_ENCABEZADO = 3


@dataclass(frozen=True, slots=True)
class Ficha:
    """La fila de inventario de un archivo, antes de tener forma de Excel.

    Todo puede faltar salvo los folios. Un campo que no se pudo leer vale
    ``None`` y quien escribe la planilla lo traduce a lo que el instructivo del
    formato manda poner donde no hay dato; lo que no se hace nunca es rellenarlo
    con algo verosímil.
    """

    folios: int
    asunto: str | None = None
    #: El nombre canónico del catálogo, cuando el papel se reconoció en él. Va
    #: aparte del asunto porque no son lo mismo: el asunto es lo que el
    #: documento dice llamarse y el tipo es cómo lo llama el archivo.
    tipo_documental: str | None = None
    consecutivo_inicial: str | None = None
    consecutivo_final: str | None = None
    fecha_inicial: date | None = None
    fecha_final: date | None = None

    @property
    def esta_fechada(self) -> bool:
        return self.fecha_inicial is not None or self.fecha_final is not None


def consecutivos(paginas: Sequence[str]) -> tuple[str | None, str | None]:
    """El primer y el último número de documento que aparecen, en ese orden.

    Son las columnas "No. Documento: Desde / Hasta" del formato. En un archivo
    de un solo documento los dos son el mismo número, y así se anota: repetirlo
    es lo que dice el formato, y dejar "Hasta" vacío haría pensar en un rango
    abierto que no existe.

    Se conserva el orden de aparición y no el alfabético: el "desde" es el que
    encabeza la primera hoja, que es lo que alguien va a cotejar contra el papel.
    """
    vistos: list[str] = []
    for pagina in paginas:
        for hallazgo in _CONSECUTIVO.finditer(pagina.upper()):
            numero = hallazgo.group(1)
            if numero not in vistos:
                vistos.append(numero)
    if not vistos:
        return None, None
    return vistos[0], vistos[-1]


#: Qué parte de un título puede ser ruido antes de dejar de creérselo. Un tercio
#: es tolerante a propósito: un encabezado real llega del escáner con alguna
#: marca suelta y sigue siendo legible, y lo que se quiere descartar es lo que
#: es ruido de arriba a abajo.
MAXIMO_DE_RUIDO = 1 / 4

#: Cuántas letras tiene que tener una palabra para contar como palabra. Es lo
#: que separa "ACTA" de la "r" que el OCR dejó suelta entre dos símbolos.
LETRAS_POR_PALABRA = 3

#: Lo que se quita de los bordes de una palabra antes de juzgarla. La puntuación
#: pegada no la convierte en ruido: "AJUSTE." sigue siendo una palabra.
_BORDES = ".,:;-—–_()[]{}¡!¿?\"'«»|/\\"


def _es_ruido(palabra: str) -> bool:
    """Si esta palabra no es una palabra sino lo que el OCR dejó por el camino.

    Tres formas de no serlo: no quedar nada al quitarle la puntuación, no tener
    ni una letra ni un dígito -- un "$" suelto -- o ser una letra sola. Un
    número no es ruido: "ACTA 004 DE 2022" es un título legítimo y sus dos
    números son parte de él.
    """
    limpio = palabra.strip(_BORDES)
    if not limpio:
        return True
    if not any(caracter.isalnum() for caracter in limpio):
        return True
    if len(limpio) == 1 and limpio.isalpha():
        return True
    return _mayusculas_revueltas(limpio)


def _mayusculas_revueltas(palabra: str) -> bool:
    """Si la palabra alterna mayúsculas y minúsculas como no lo hace ninguna.

    Una palabra escrita por una persona va en minúsculas, en mayúsculas o
    capitalizada. "AvUTEO" no es ninguna de las tres: es lo que devuelve el OCR
    cuando no distingue los trazos, y delata una lectura fallida mejor que
    cualquier recuento de símbolos, porque las letras son legítimas una por una
    y sólo el patrón las desmiente.
    """
    letras = [caracter for caracter in palabra if caracter.isalpha()]
    if len(letras) < LETRAS_POR_PALABRA + 1:
        # En palabras cortas no hay patrón que romper: "SAS", "NIT" y "De" son
        # todas normales, y exigirles una forma canónica descartaría siglas.
        return False
    texto = "".join(letras)
    return not (texto.isupper() or texto.islower() or texto.istitle())


def es_legible(titulo: str) -> bool:
    """Si lo que se leyó como título es algo que una persona pueda leer.

    El OCR de una hoja que no se dejó leer no devuelve nada: devuelve basura, y
    la basura pasa los filtros de forma -- tiene tres palabras, empieza en
    mayúscula, no parece una fecha -- porque son filtros pensados para descartar
    renglones legítimos que no son títulos, no para descartar ruido.

    Un asunto ilegible en el inventario es peor que un hueco declarado: el hueco
    se ve y se manda a revisar, y "r a $ Fechas extremas" se queda ahí para
    siempre como si alguien lo hubiera escrito.
    """
    palabras = titulo.split()
    if not palabras:
        return False
    ruido = sum(1 for palabra in palabras if _es_ruido(palabra))
    if ruido / len(palabras) > MAXIMO_DE_RUIDO:
        return False
    # Y algo que leer: una columna de asuntos llena de números y conectores no
    # le dice nada a quien busque el documento dentro de tres años.
    return any(
        sum(1 for caracter in palabra if caracter.isalpha()) >= LETRAS_POR_PALABRA
        for palabra in palabras
    )


def asunto_impreso(paginas: Sequence[str]) -> str | None:
    """El título que el documento lleva impreso en su encabezado.

    Se busca sólo en las primeras hojas y se devuelve tal como está escrito. Es
    la respuesta de segunda: cuando el catálogo reconoce el papel manda el
    catálogo, porque el archivo tiene un nombre oficial para cada tipo y dos
    formas de escribirlo son dos entradas distintas en un inventario que
    alguien va a ordenar.

    Una hoja cuyo encabezado salió ilegible no detiene la búsqueda: se pasa a la
    siguiente, que es lo que hace una persona con un escaneo malo.
    """
    for pagina in paginas[:PAGINAS_DE_ENCABEZADO]:
        titulo = extract_title(pagina)
        if titulo and es_legible(titulo):
            return titulo
    return None


def fichar(paginas: Sequence[str], *, folios: int | None = None) -> Ficha:
    """Lee el archivo entero y devuelve la única fila que le corresponde.

    ``folios`` es el número de páginas del PDF y se pasa aparte porque no se
    deduce del texto: una hoja que salió en blanco del escáner sigue siendo un
    folio y aquí llegaría como una cadena vacía.
    """
    textos = list(paginas)
    total = folios if folios is not None else len(textos)

    # El catálogo primero. Si el papel se reconoce en él, ese es su nombre en el
    # inventario; el título impreso queda de reserva para lo que el catálogo no
    # tiene todavía, que hoy es todo lo que no sea correspondencia de energía.
    del_catalogo = identificar_documento(textos)
    tipo = del_catalogo.nombre if del_catalogo is not None else None
    impreso = asunto_impreso(textos)

    desde, hasta = consecutivos(textos)
    return Ficha(
        folios=total,
        asunto=tipo or impreso,
        tipo_documental=tipo,
        consecutivo_inicial=desde,
        consecutivo_final=hasta,
        # De punta a punta del archivo, que es lo que el formato llama fechas
        # extremas: la más antigua abre el expediente y la más reciente lo
        # cierra, sin importar en qué hoja estén.
        fecha_inicial=primera_fecha(textos),
        fecha_final=ultima_fecha(textos),
    )
