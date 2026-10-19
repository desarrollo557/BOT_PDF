"""Qué páginas de un PDF de origen ya están entregadas en el destino, y cuáles no.

Lo pidió el operador el 2026-10-15, con una carpeta de once libros de diplomas
a medias delante: tres terminados, tres con el libro entero metido en un solo
archivo, tres cancelados y dos sin empezar. Si una corrida se corta -- un
error, un corte de luz, un «Detener» --, el bot tiene que saber qué llegó del
origen al destino y qué no, y poder seguir sólo con lo que falta.

La respuesta se saca **del disco y no de un registro**. Un registro dice lo
que el bot creyó hacer; el destino dice lo que hay, también después de que
alguien borre o mueva un archivo a mano, y también para corridas hechas antes
de que existiera esta función. Cada página entregada es una copia de una
página del origen -- el escritor la copia con su capa de texto y su imagen
escaneada tal cual --, así que se reconoce por su **huella**: el texto de su
capa, o los bytes de su imagen cuando la capa no dice casi nada. Medido sobre
los libros 3858080 y 3858083: 396 y 399 páginas reconocidas de 396 y 399, por
texto y por imagen.

Nada aquí abre un PDF: las huellas llegan hechas (ver
``adapters/huellas_pdf.py``) y esto sólo las cruza.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

#: Cuántas páginas puede tener el PDF de un diploma antes de ser sospechoso.
#: Un diploma es una cara, y dos cuando se le une una continuación. El libro
#: entero metido en un archivo -- 396 páginas en UPD3858080 -- está «entregado»
#: página a página y sin embargo no está partido.
PAGINAS_DE_UN_DIPLOMA = 2


@dataclass(frozen=True, slots=True)
class Huella:
    """Lo que identifica una página sin mirarla entera.

    ``texto`` es el resumen de su capa de texto cuando dice lo bastante para
    distinguirla; ``imagen``, el de los bytes de su imagen escaneada. Una de
    las dos basta para casar dos páginas.
    """

    texto: str | None = None
    imagen: str | None = None

    @property
    def vacia(self) -> bool:
        return not self.texto and not self.imagen


class EstadoDeEntrega(StrEnum):
    SIN_PROCESAR = "sin procesar"
    INCOMPLETO = "incompleto"
    COMPLETO = "completo"


@dataclass(frozen=True, slots=True)
class ArchivoEntregado:
    """Un PDF del destino y la página del origen a la que corresponde cada cara suya."""

    nombre: str
    paginas: tuple[int | None, ...]

    @property
    def primera(self) -> int | None:
        return next((p for p in self.paginas if p is not None), None)

    @property
    def ajeno(self) -> bool:
        """Si trae alguna cara que no es de este origen."""
        return any(p is None for p in self.paginas)


@dataclass(frozen=True, slots=True)
class Conciliacion:
    """Lo que hay en el destino de un PDF de origen, página a página."""

    paginas_del_origen: int
    entregadas: frozenset[int]
    #: Las páginas del origen que no están en ningún archivo del destino.
    faltantes: tuple[int, ...]
    #: Las que están en más de un archivo.
    repetidas: tuple[int, ...]
    archivos: tuple[ArchivoEntregado, ...]

    @property
    def estado(self) -> EstadoDeEntrega:
        if not self.entregadas:
            return EstadoDeEntrega.SIN_PROCESAR
        if self.faltantes:
            return EstadoDeEntrega.INCOMPLETO
        return EstadoDeEntrega.COMPLETO

    @property
    def ajenos(self) -> tuple[str, ...]:
        return tuple(a.nombre for a in self.archivos if a.ajeno)

    @property
    def sin_partir(self) -> tuple[ArchivoEntregado, ...]:
        """Los archivos con más páginas de las que tiene un diploma."""
        return tuple(a for a in self.archivos if len(a.paginas) > PAGINAS_DE_UN_DIPLOMA)

    def pagina_de(self, nombre: str) -> int | None:
        """La primera página del origen que lleva el archivo de ese nombre."""
        return next((a.primera for a in self.archivos if a.nombre == nombre), None)

    def as_dict(self) -> dict[str, object]:
        return {
            "estado": str(self.estado),
            "paginas_del_origen": self.paginas_del_origen,
            "entregadas": len(self.entregadas),
            "faltantes": len(self.faltantes),
            "faltantes_rangos": rangos(self.faltantes),
            "repetidas": rangos(self.repetidas),
            "archivos": len(self.archivos),
            "ajenos": list(self.ajenos),
            "sin_partir": [
                {"archivo": a.nombre, "paginas": len(a.paginas)} for a in self.sin_partir
            ],
        }


def conciliar(
    origen: Sequence[Huella], entregados: Mapping[str, Sequence[Huella]]
) -> Conciliacion:
    """Cruza las huellas del origen con las de cada archivo del destino.

    Una página entregada casa con la del origen que tenga su mismo texto o,
    si no, su misma imagen. Cuando dos páginas del origen comparten huella --
    la misma hoja escaneada dos veces --, cada copia del destino se lleva la
    primera que siga libre, para que dos entregas no cuenten como una.
    """
    por_texto: dict[str, deque[int]] = defaultdict(deque)
    por_imagen: dict[str, deque[int]] = defaultdict(deque)
    for numero, huella in enumerate(origen, start=1):
        if huella.texto:
            por_texto[huella.texto].append(numero)
        if huella.imagen:
            por_imagen[huella.imagen].append(numero)

    usadas: defaultdict[int, int] = defaultdict(int)

    def casar(huella: Huella) -> int | None:
        candidatas: list[int] = []
        if huella.texto and huella.texto in por_texto:
            candidatas = list(por_texto[huella.texto])
        elif huella.imagen and huella.imagen in por_imagen:
            candidatas = list(por_imagen[huella.imagen])
        if not candidatas:
            return None
        libre = next((p for p in candidatas if not usadas[p]), candidatas[0])
        usadas[libre] += 1
        return libre

    archivos = tuple(
        ArchivoEntregado(nombre=nombre, paginas=tuple(casar(h) for h in huellas))
        for nombre, huellas in sorted(entregados.items())
    )
    entregadas = frozenset(p for p, veces in usadas.items() if veces)
    total = len(origen)
    return Conciliacion(
        paginas_del_origen=total,
        entregadas=entregadas,
        faltantes=tuple(p for p in range(1, total + 1) if p not in entregadas),
        repetidas=tuple(sorted(p for p, veces in usadas.items() if veces > 1)),
        archivos=archivos,
    )


def rangos(paginas: Iterable[int]) -> str:
    """«1-206, 210, 215-399»: cómo lo diría una persona."""
    ordenadas = sorted(set(paginas))
    if not ordenadas:
        return ""
    tramos: list[str] = []
    inicio = anterior = ordenadas[0]
    for pagina in ordenadas[1:]:
        if pagina == anterior + 1:
            anterior = pagina
            continue
        tramos.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
        inicio = anterior = pagina
    tramos.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
    return ", ".join(tramos)
