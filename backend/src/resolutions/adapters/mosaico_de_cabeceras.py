"""Diez cabeceras por página facturada, cada una bajo su «PAGINA n».

El OCR de pago cobra por página procesada (ver ``mosaico_de_nombres``). De una
tarjeta de nómina basta su cabecera -- «Apellidos … Nombre … C.C. o NIT No. …
Año de Acumulación» --, un diez por ciento de la hoja, y de la hoja manuscrita
el renglón del nombre. Diez de esas franjas apiladas son una página facturada.

Lo distinto del mosaico de nombres es **cómo vuelve cada franja a su página**.
Allí la etiqueta va a la izquierda y el proveedor la devuelve en un bloque
aparte; aquí va **encima**, en su propio renglón y en letra limpia: «PAGINA 34».
El proveedor lee de arriba abajo, así que contesta «PAGINA 34», lo de la franja
34, «PAGINA 35»… Medido el 2026-11-06 sobre diez tarjetas de la nómina de 1975
y diez hojas del libro de anotaciones de 1972: las diez etiquetas, en su
orden, cada una con lo suyo.

Y la regla que impide el error que no se ve -- el nombre de una persona en la
página de otra --: **una tanda vale sólo si vuelven todas sus etiquetas, una
vez cada una**. Si falta alguna -- el proveedor tomó la franja por una foto y
devolvió «![img-3.jpeg]» --, la tanda se vuelve a leer en mitades, hasta una
franja por imagen. Se paga sólo lo que falló.
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from ..application.ports import Band

logger = logging.getLogger(__name__)

#: Cuántas franjas por mosaico, cuántos mosaicos en vuelo y a qué resolución.
TAMANO = 10
LECTORES = 4
DPI = 200

#: Alto del renglón de la etiqueta y separación entre franjas, en puntos.
_ROTULO = 70
_SEPARACION = 16

_ETIQUETA = re.compile(r"PAGINA\s*(\d{1,4})", re.IGNORECASE)
#: Lo que devuelve el proveedor cuando toma la franja por una imagen.
_IMAGEN = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def repartir(texto: str, tanda: Sequence[int]) -> dict[int, str] | None:
    """Lo leído de cada franja, por su etiqueta; ``None`` si no volvieron todas, una vez cada una."""
    halladas = [(int(m.group(1)), m.start(), m.end()) for m in _ETIQUETA.finditer(texto)]
    numeros = [numero for numero, _, _ in halladas]
    if sorted(numeros) != sorted(tanda) or len(set(numeros)) != len(numeros):
        return None
    trozos: dict[int, str] = {}
    for posicion, (numero, _desde, hasta) in enumerate(halladas):
        fin = halladas[posicion + 1][1] if posicion + 1 < len(halladas) else len(texto)
        trozo = _IMAGEN.sub(" ", texto[hasta:fin])
        # Lo que deja la tabla alrededor de la etiqueta: «|», «#» y espacios.
        trozos[numero] = trozo.strip(" |#\n\t")
    return trozos


class MosaicoDeCabeceras:
    """Lee la cabecera de muchas hojas pagando por unas pocas páginas.

    Recibe la función de lectura -- ``leer(bytes) -> str`` -- y no el motor,
    como el mosaico de nombres: sirve el de pago, uno local o un doble de prueba.
    """

    def __init__(
        self,
        leer: Callable[[bytes], str],
        *,
        tamano: int = TAMANO,
        dpi: int = DPI,
        lectores: int = LECTORES,
    ) -> None:
        self._leer = leer
        self._tamano = max(1, tamano)
        self._dpi = dpi
        self._lectores = max(1, lectores)
        #: Las páginas de las tandas que no volvieron enteras.
        self._sin_repartir: list[int] = []

    def leer_franjas(self, source, paginas: Sequence[int], banda: Callable[[int], Band]) -> dict[int, str]:
        """Lo que dice la franja de cada página: ``banda(pagina)`` dice dónde recortarla.

        Nunca levanta: un mosaico que falla deja sin leer sus franjas, que se
        vuelven a pedir en mitades; una franja sola que vuelve vacía queda sin
        leer, y lo dice quien llama.
        """
        self._sin_repartir = []
        leidas = self._una_pasada(source, list(paginas), banda)
        if self._sin_repartir and self._tamano > 1:
            mitad = copy.copy(self)
            mitad._tamano = max(1, self._tamano // 2)
            logger.info("se releen %d cabeceras en mosaicos de %d", len(self._sin_repartir), mitad._tamano)
            leidas.update(mitad.leer_franjas(source, list(self._sin_repartir), banda))
        return leidas

    def otra_mirada(self) -> MosaicoDeCabeceras:
        """Una franja por imagen y con más zoom: para lo que no se leyó en la tanda."""
        clon = copy.copy(self)
        clon._tamano = 1
        clon._dpi = int(self._dpi * 1.5)
        return clon

    def _una_pasada(self, source, paginas: list[int], banda: Callable[[int], Band]) -> dict[int, str]:
        tandas = [paginas[i : i + self._tamano] for i in range(0, len(paginas), self._tamano)]
        leidas: dict[int, str] = {}
        vuelo: dict = {}

        def recoger(todo: bool = False) -> None:
            while vuelo and (todo or len(vuelo) >= self._lectores):
                listos, _ = wait(list(vuelo), return_when=FIRST_COMPLETED)
                for futuro in listos:
                    tanda = vuelo.pop(futuro)
                    texto = futuro.result()
                    repartido = repartir(texto, tanda) if texto is not None else None
                    if repartido is None:
                        if len(tanda) == 1 and texto:
                            # Una franja sola: todo lo leído es suyo.
                            leidas[tanda[0]] = _IMAGEN.sub(" ", texto).strip()
                        else:
                            self._sin_repartir.extend(tanda)
                    else:
                        leidas.update(repartido)

        # Los mosaicos se arman en este hilo -- MuPDF no es seguro entre hilos
        # sobre el mismo documento -- y se leen en varios.
        with ThreadPoolExecutor(max_workers=self._lectores) as pool:
            for tanda in tandas:
                recoger()
                imagen = self._armar(source, tanda, banda)
                if imagen is None:
                    self._sin_repartir.extend(tanda)
                    continue
                vuelo[pool.submit(self._leer_protegido, imagen, len(tanda))] = tanda
            recoger(todo=True)
        logger.info(
            "mosaico de cabeceras: %d de %d leídas en %d páginas facturadas",
            len(leidas), len(paginas), len(tandas),
        )
        return leidas

    def _leer_protegido(self, imagen: bytes, cuantas: int) -> str | None:
        try:
            return self._leer(imagen)
        except Exception:  # noqa: BLE001 - una tanda, no el libro
            logger.warning("falló el mosaico de %d cabeceras", cuantas, exc_info=True)
            return None

    def _armar(self, source, tanda: Sequence[int], banda: Callable[[int], Band]) -> bytes | None:
        """Las franjas apiladas, cada una con «PAGINA n» encima y una raya debajo."""
        try:
            import pymupdf
        except Exception:  # noqa: BLE001 - sin MuPDF no hay mosaico
            return None
        recortes = []
        for pagina in tanda:
            try:
                recortes.append((pagina, pymupdf.Pixmap(source.render(pagina, banda(pagina), self._dpi))))
            except Exception:  # noqa: BLE001 - una franja, no la tanda
                logger.debug("no se pudo recortar la cabecera de la página %s", pagina, exc_info=True)
        if not recortes:
            return None
        ancho = max(pix.width for _, pix in recortes) + 2 * _SEPARACION
        alto = sum(pix.height + _ROTULO + _SEPARACION for _, pix in recortes) + _SEPARACION
        lienzo = pymupdf.open()
        try:
            hoja = lienzo.new_page(width=ancho, height=alto)
            hoja.draw_rect(hoja.rect, color=(1, 1, 1), fill=(1, 1, 1))
            y = _SEPARACION
            for pagina, pix in recortes:
                hoja.insert_text((_SEPARACION, y + 50), f"PAGINA {pagina}", fontsize=44)
                y += _ROTULO
                hoja.insert_image(pymupdf.Rect(_SEPARACION, y, _SEPARACION + pix.width, y + pix.height), pixmap=pix)
                raya = y + pix.height + _SEPARACION / 2
                hoja.draw_line((_SEPARACION, raya), (ancho - _SEPARACION, raya), color=(0, 0, 0), width=3)
                y += pix.height + _SEPARACION
            return hoja.get_pixmap(alpha=False).tobytes("jpeg", jpg_quality=88)
        except Exception:  # noqa: BLE001 - armar el mosaico no puede tumbar el libro
            logger.warning("no se pudo armar el mosaico de cabeceras", exc_info=True)
            return None
        finally:
            lienzo.close()
