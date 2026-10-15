"""El texto de un formulario relleno a máquina, en el orden en que se lee en el papel.

Las actas de grado de 1980 a 2005 son un formulario impreso con los huecos
rellenos a máquina. Lo rellenado va en otra letra -- negrita, o la de la
máquina -- y un poco por encima de su renglón, así que la capa de texto del
escáner lo saca suelto y fuera de sitio: «03» antes de «ACTA DE GRADO No.»,
«CLARA INES» antes de «al estudiante» y «VARGAS CASSIANI» detrás de «el titulo
de». Quien lee esa capa en orden pega cada dato al rótulo equivocado.

Aquí se rehace la página por su geometría: los trozos en la letra del
formulario forman los renglones impresos, y cada trozo rellenado se coloca en
el renglón impreso que tiene justo debajo, en su sitio de izquierda a derecha.
Sale «ACTA DE GRADO No. 03», «el titulo de ENFERMERA al estudiante CLARA INES»,
«VARGAS CASSIANI portador de la cédula de ciudadanía», que es como se lee.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Trozo:
    """Un trozo de texto de la página con su caja y su letra."""

    texto: str
    x0: float
    y0: float
    x1: float
    y1: float
    #: La letra: fuente y si va en negrita. Lo rellenado a máquina va en otra.
    letra: str

    @property
    def centro(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def alto(self) -> float:
        return max(1.0, self.y1 - self.y0)


#: Hasta cuántas alturas de su letra puede quedar un relleno por encima de su
#: renglón impreso.
ALTURAS_SOBRE_EL_RENGLON = 1.4
#: Cuánto se le perdona a un trozo por salirse de la columna del formulario: lo
#: rellenado a máquina pasa unos puntos del margen impreso («INES» acaba en el
#: 546 y el formulario en el 538), una mancha del borde queda mucho más allá.
MARGEN = 20.0
#: Cuánto ancho tiene el recuadro de un dato detrás de su rótulo, en puntos.
ANCHO_DEL_DATO = 170.0


def recuadro_tras(trozos: Sequence[Trozo], rotulo: str, antes: str | None = None) -> tuple[float, float, float, float] | None:
    """Dónde va escrito a máquina el dato que sigue a un rótulo del formulario.

    El recuadro empieza donde acaba el «No.» del renglón que dice ``rotulo``
    -- «ACTA DE GRADO No.» -- y sube una altura de letra y media, porque lo
    rellenado queda por encima del renglón. Con ``antes`` se busca el «No.» que
    abre el renglón siguiente al que dice ``antes``: el de la cédula va al
    principio del renglón de debajo de «ciudadanía».

    Sirve para leer con el OCR sólo ese recuadro cuando la capa del escáner se
    saltó el dato: el «04» del acta de RAQUEL MARIA ROCHA MARIN no está en la
    capa, pero sí en el papel. Devuelve la caja en puntos, o ``None``.
    """
    import re

    renglones = _renglones([t for t in trozos if t.texto.strip()])
    textos = [" ".join(t.texto.strip() for t in sorted(r, key=lambda t: t.x0)).upper() for r in renglones]
    for indice, texto in enumerate(textos):
        if antes is not None:
            if antes not in _sin_tildes(texto) or indice + 1 >= len(renglones):
                continue
            renglon = sorted(renglones[indice + 1], key=lambda t: t.x0)
        elif rotulo in _sin_tildes(texto):
            renglon = sorted(renglones[indice], key=lambda t: t.x0)
        else:
            continue
        numero = next((t for t in renglon if re.fullmatch(r"N[OoQ°º]?\W{0,2}", t.texto.strip())), None)
        if numero is None:
            continue
        alto = numero.alto
        return (numero.x1, numero.y0 - alto * 1.6, numero.x1 + ANCHO_DEL_DATO, numero.y1 + alto * 0.2)
    return None


def _sin_tildes(texto: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()


def _renglones(trozos: Sequence[Trozo]) -> list[list[Trozo]]:
    """Los trozos agrupados en renglones: los que se solapan en altura van juntos."""
    renglones: list[list[Trozo]] = []
    for trozo in sorted(trozos, key=lambda t: t.centro):
        if renglones:
            ultimo = renglones[-1]
            arriba = min(t.y0 for t in ultimo)
            abajo = max(t.y1 for t in ultimo)
            if arriba <= trozo.centro <= abajo:
                ultimo.append(trozo)
                continue
        renglones.append([trozo])
    return renglones


def texto_del_formulario(trozos: Sequence[Trozo]) -> str:
    """La página como se lee: cada relleno dentro de su renglón impreso.

    La letra del formulario es la que más texto ocupa en la página; lo que va
    en otra es lo rellenado. Si toda la página va en una letra -- un acta
    impresa de corrido, no un formulario --, sale agrupada por renglones sin
    más, que es lo mismo que leerla de arriba abajo.
    """
    con_texto = [t for t in trozos if t.texto.strip()]
    if not con_texto:
        return ""
    peso = Counter()
    for trozo in con_texto:
        peso[trozo.letra] += len(trozo.texto.strip())
    del_formulario = peso.most_common(1)[0][0]
    impresos = [t for t in con_texto if t.letra == del_formulario]
    # Lo que cae fuera de la columna del formulario no es un dato: una mancha
    # del margen -- la «I» del borde derecho que se pegaba al nombre «RAQUEL I
    # MARIA ROCHA MARIN» -- o el canto de la hoja.
    izquierda = min(t.x0 for t in impresos) - MARGEN
    derecha = max(t.x1 for t in impresos) + MARGEN
    rellenos = [
        t
        for t in con_texto
        if t.letra != del_formulario and t.x0 >= izquierda and t.x1 <= derecha
    ]

    renglones = _renglones(impresos)
    centros = [sum(t.centro for t in renglon) / len(renglon) for renglon in renglones]
    sueltos: list[Trozo] = []
    for relleno in rellenos:
        # El renglón impreso que tiene justo debajo, o a su misma altura.
        candidatos = [
            (centro - relleno.centro, indice)
            for indice, centro in enumerate(centros)
            if -relleno.alto * 0.5 <= centro - relleno.centro <= relleno.alto * ALTURAS_SOBRE_EL_RENGLON
        ]
        if candidatos:
            renglones[min(candidatos)[1]].append(relleno)
        else:
            sueltos.append(relleno)
    # Lo rellenado que no cae sobre ningún renglón impreso -- un nombre en su
    # renglón propio -- se queda en el suyo.
    renglones.extend(_renglones(sueltos))
    renglones.sort(key=lambda renglon: min(t.y0 for t in renglon if t.letra == del_formulario)
                   if any(t.letra == del_formulario for t in renglon) else min(t.y0 for t in renglon))
    return "\n".join(
        " ".join(t.texto.strip() for t in sorted(renglon, key=lambda t: t.x0) if t.texto.strip())
        for renglon in renglones
    )
