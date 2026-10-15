"""La fecha de entrega que el mensajero marcó con una X en la guía de LECTA.

Lo pidió el operador: en los documentos que traen la guía de entrega, la fecha
es la de «las casillas marcadas; tienes que hacerles zoom y analizarlas bien».
La guía es un formato impreso fijo:

    DÍA  [ ][ ][ ] … [ ]         quince casillas, del 1 al 15
      [ ][ ][ ][ ] … [ ]         dieciséis, del 16 al 31, una más a la izquierda
    MES  [ ][ ] … [ ]   [2022]   doce, alineadas con la primera fila, y el año
                                  escrito a mano en el recuadro grande

Debajo de cada casilla va impreso su número. Así que hay una sola rejilla de
dieciséis columnas: en la columna k, la segunda fila es el día 16+k, la
primera el día k y la de MES el mes k.

Cómo se lee, sin librerías de visión:

1. **La rejilla.** Los números impresos de la segunda fila -- 16 a 31, de dos
   cifras, que el OCR lee bien -- dan dónde está cada columna: se ajusta una
   recta posición = a + b·columna con los que se lean, y el resto de las
   columnas sale de ella. La altura de esos números da la de las filas.
2. **Las X.** Son las manchas de tinta más grandes de la cuadrícula: el borde
   de las casillas es tan fino y claro que no llega a tinta, y la X sí. Su
   borde izquierdo dice la columna -- la del mes suele ir pegada al año escrito
   a mano, y la mancha sigue hacia la derecha --, y su altura, la fila.
3. **El año** manuscrito no se lee: se saca de la fecha de admisión que la guía
   trae impresa -- «20220125» --, y si el mes marcado es anterior al de la
   admisión, es del año siguiente.
"""

from __future__ import annotations

import io
import re
from datetime import date

from PIL import Image

#: Desde qué gris un píxel es tinta de una X (el borde impreso es más claro).
UMBRAL = 150
#: Cuánto de alta es una fila respecto del paso entre columnas (medido: 0,885).
ALTO_DE_FILA = 0.885


def _componentes(negro: list[list[bool]], ancho: int, alto: int) -> list[tuple[int, int, int, int, int]]:
    """Las manchas conexas de tinta: (x0, y0, x1, y1, píxeles)."""
    visto = [[False] * ancho for _ in range(alto)]
    manchas = []
    for y in range(alto):
        for x in range(ancho):
            if not negro[y][x] or visto[y][x]:
                continue
            pila = [(x, y)]
            visto[y][x] = True
            x0 = x1 = x
            y0 = y1 = y
            n = 0
            while pila:
                cx, cy = pila.pop()
                n += 1
                x0, x1, y0, y1 = min(x0, cx), max(x1, cx), min(y0, cy), max(y1, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < ancho and 0 <= ny < alto and negro[ny][nx] and not visto[ny][nx]:
                        visto[ny][nx] = True
                        pila.append((nx, ny))
            manchas.append((x0, y0, x1, y1, n))
    return manchas


def _recta(puntos: list[tuple[int, float]]) -> tuple[float, float] | None:
    """La recta x = a + b·k que mejor pasa por los puntos, descartando los raros.

    Con la mediana de las pendientes entre pares: un número mal leído -- «2»
    por «21» -- no tuerce la rejilla.
    """
    if len(puntos) < 3:
        return None
    pendientes = sorted(
        (x2 - x1) / (k2 - k1) for i, (k1, x1) in enumerate(puntos) for k2, x2 in puntos[i + 1 :] if k2 != k1
    )
    b = pendientes[len(pendientes) // 2]
    if b <= 0:
        return None
    a = sorted(x - b * k for k, x in puntos)[len(puntos) // 2]
    # Sólo los que caen en su sitio.
    buenos = [(k, x) for k, x in puntos if abs(x - (a + b * k)) < b * 0.35]
    if len(buenos) < 3:
        return None
    return a, b


def casillas_marcadas(
    imagen_png: bytes,
    palabras: list[tuple[str, float, float, float, float]],
) -> tuple[int | None, int | None]:
    """El día y el mes marcados, o ``None`` si no se ven.

    ``palabras`` son las que el OCR leyó en la misma imagen: (texto, x0, y0,
    ancho, alto), en píxeles. De ellas salen los números impresos de la rejilla.
    """
    # 1. La rejilla, por los números de la segunda fila de días.
    segunda = [
        (int(t) - 16, x + w / 2, y)
        for t, x, y, w, h in palabras
        if t.isdigit() and len(t) == 2 and 16 <= int(t) <= 31
    ]
    recta = _recta([(k, x) for k, x, _ in segunda])
    if recta is None:
        return None, None
    a, b = recta
    en_su_sitio = [y for k, x, y in segunda if abs(x - (a + b * k)) < b * 0.35]
    # La fila de casillas va justo encima de sus números.
    y_numeros_2 = sorted(en_su_sitio)[len(en_su_sitio) // 2]
    paso = b * ALTO_DE_FILA
    filas = {
        "dia_bajo": y_numeros_2 - paso,  # números de la primera fila
        "dia_alto": y_numeros_2,
        "mes": y_numeros_2 + paso,
    }

    # 2. Las X: manchas de tinta del tamaño de una casilla o más.
    imagen = Image.open(io.BytesIO(imagen_png)).convert("L")
    ancho, alto = imagen.size
    datos = imagen.load()
    negro = [[datos[x, y] < UMBRAL for x in range(ancho)] for y in range(alto)]
    marcas = [
        m
        for m in _componentes(negro, ancho, alto)
        if m[2] - m[0] >= b * 0.45 and m[3] - m[1] >= b * 0.45 and m[4] >= b * b * 0.08
    ]

    def ubicar(marca) -> tuple[str, int] | None:
        x0, y0, x1, y1, _ = marca
        # El borde izquierdo y el alto de una casilla: la X del mes suele
        # seguir en el año escrito a mano, hacia la derecha.
        xc = x0 + min(x1 - x0, b) / 2
        yc = y0 + min(y1 - y0, b) / 2
        columna = round((xc - a) / b)
        # La fila: la de los números que quedan justo debajo.
        fila = min(filas, key=lambda f: abs(filas[f] - paso * 0.55 - yc))
        if abs(filas[fila] - paso * 0.55 - yc) > paso * 0.6:
            return None
        return fila, columna

    dias: list[tuple[int, int]] = []
    meses: list[tuple[int, int]] = []
    for marca in marcas:
        ubicada = ubicar(marca)
        if ubicada is None:
            continue
        fila, k = ubicada
        if fila == "dia_alto" and 0 <= k <= 15:
            dias.append((marca[4], 16 + k))
        elif fila == "dia_bajo" and 1 <= k <= 15:
            dias.append((marca[4], k))
        elif fila == "mes" and 1 <= k <= 12:
            meses.append((marca[4], k))
    dia = max(dias)[1] if dias else None
    mes = max(meses)[1] if meses else None
    return dia, mes


#: La fecha de admisión que la guía trae impresa: «20220125», «2020-12-14».
_IMPRESA = re.compile(r"\b(20\d{2})[-/]?(\d{2})[-/]?(\d{2})\b")


def fecha_de_la_guia(
    imagen_png: bytes,
    palabras: list[tuple[str, float, float, float, float]],
    texto_de_la_guia: str,
) -> date | None:
    """La fecha de entrega marcada en la guía, con el año de su fecha impresa."""
    dia, mes = casillas_marcadas(imagen_png, palabras)
    if dia is None or mes is None:
        return None
    impresas = []
    for hallada in _IMPRESA.finditer(" ".join([texto_de_la_guia or "", *(p[0] for p in palabras)])):
        try:
            impresas.append(date(int(hallada.group(1)), int(hallada.group(2)), int(hallada.group(3))))
        except ValueError:
            continue
    if not impresas:
        return None
    admision = min(impresas)
    anio = admision.year + (1 if mes < admision.month else 0)
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None
