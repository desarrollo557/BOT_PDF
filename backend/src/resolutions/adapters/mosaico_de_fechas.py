"""Mosaico de fechas: lee la fecha manuscrita de muchas caras en una sola página facturada.

En los libros de diplomas antiguos (años 80 y anteriores) la fecha va escrita a mano
en la fórmula: "En testimonio de ello firmamos y sellamos con el sello de la
Universidad de Cartagena a los 10 días del mes de Mayo de mil novecientos
ochenta y dos". Tesseract no lee manuscrito, así que este mosaico usa el motor
de pago (Mistral/Claude) sobre la franja donde vive esa fecha.

El ancla son las leyendas impresas del pie del diploma:
- "EN TESTIMONIO DE ELLO FIRMAMOS"
- "SELLAMOS CON EL SELLO"
- "UNIVERSIDAD DE CARTAGENA A LOS"
- "DÍAS DEL MES DE"
- "DE MIL NOVECIENTOS"

Medido sobre el libro 7: la franja del pie es ~12% de la hoja. Diez franjas
apiladas caben en una imagen = una página facturada por cada diez fechas.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from ..application.ports import Band
from ..domain.diploma import fecha_en_letras

logger = logging.getLogger(__name__)

#: Cuántos mosaicos en paralelo contra el proveedor.
LECTORES = 4

#: Cuántas franjas por mosaico (diez = una página facturada).
TAMANO_DEL_MOSAICO = 10

#: DPI para la franja.
DPI = 300

#: Leyendas impresas que anclan la zona de la fecha en el pie del diploma.
LEYENDAS_FECHA = (
    "EN TESTIMONIO DE ELLO FIRMAMOS",
    "SELLAMOS CON EL SELLO",
    "UNIVERSIDAD DE CARTAGENA A LOS",
    "DÍAS DEL MES DE",
    "DE MIL NOVECIENTOS",
    "A LOS",
    "DÍAS DEL MES",
)

#: Alto de la banda en fracción de la hoja (el pie del diploma).
ALTO_DE_LA_BANDA = 0.14
MARGEN_ARRIBA = 0.015


def _plano(texto: str) -> str:
    import unicodedata
    return "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", texto.upper())
        if not unicodedata.combining(caracter)
    )


class MosaicoDeFechas:
    """Lee las fechas manuscritas de muchas caras pagando por pocas páginas."""

    CAMPO = "fechas"
    LEYENDAS = LEYENDAS_FECHA
    ALTO = ALTO_DE_LA_BANDA
    MARGEN = MARGEN_ARRIBA

    def __init__(
        self,
        leer: Callable[[bytes], str],
        tamano: int = TAMANO_DEL_MOSAICO,
        dpi: int = DPI,
        lectores: int = LECTORES,
    ) -> None:
        self._leer = leer
        self._tamano = max(1, tamano)
        self._dpi = dpi
        self._lectores = max(1, lectores)

    def leer_franjas(self, source, paginas: Sequence[int]) -> dict[int, str]:
        """La fecha de cada una de esas caras, en formato DD/MM/AAAA."""
        bandas = self._bandas(source, paginas)
        if not bandas:
            logger.info(
                "ninguna de las %d caras dice dónde está su fecha; no hay mosaico "
                "que armar",
                len(paginas),
            )
            return {}

        encontrados: dict[int, str] = {}
        ordenadas = [pagina for pagina in paginas if pagina in bandas]
        tandas = [
            ordenadas[arranque : arranque + self._tamano]
            for arranque in range(0, len(ordenadas), self._tamano)
        ]
        vuelo: dict = {}

        def recoger(todo: bool = False) -> None:
            while vuelo and (todo or len(vuelo) >= self._lectores):
                listos, _ = wait(list(vuelo), return_when=FIRST_COMPLETED)
                for futuro in listos:
                    tanda = vuelo.pop(futuro)
                    texto = futuro.result()
                    if texto is not None:
                        encontrados.update(self._repartir_texto(texto, tanda))

        with ThreadPoolExecutor(max_workers=self._lectores) as pool:
            for tanda in tandas:
                recoger()
                imagen = self._armar(source, tanda, bandas)
                if imagen is None:
                    continue
                vuelo[pool.submit(self._leer_protegido, imagen, len(tanda))] = tanda
            recoger(todo=True)

        logger.info(
            "mosaico de %s: %d leídas de %d caras en %d páginas facturadas",
            self.CAMPO,
            len(encontrados),
            len(ordenadas),
            (len(ordenadas) + self._tamano - 1) // self._tamano,
        )
        return encontrados

    fechas = leer_franjas

    def _repartir_texto(self, texto: str, tanda: Sequence[int]) -> dict[int, str]:
        return _repartir_fechas(texto, tanda)

    def _leer_protegido(self, imagen: bytes, cuantas: int) -> str | None:
        try:
            return self._leer(imagen)
        except Exception:
            logger.warning("falló el mosaico de %d caras", cuantas, exc_info=True)
            return None

    def _bandas(self, source, paginas: Sequence[int]) -> dict[int, Band]:
        alturas: dict[int, float] = {}
        for pagina in paginas:
            altura = self._altura_de_la_leyenda(source, pagina)
            if altura is not None:
                alturas[pagina] = altura

        if not alturas:
            return {}

        # Usar la altura mediana de las que sí tienen leyenda
        from statistics import median
        habitual = median(alturas.values())
        return {
            pagina: self._banda(alturas.get(pagina, habitual)) for pagina in paginas
        }

    def _banda(self, arriba: float) -> Band:
        desde = max(0.0, arriba - self.MARGEN)
        return Band(0.0, desde, 1.0, min(1.0, desde + self.ALTO + self.MARGEN))

    def _altura_de_la_leyenda(self, source, pagina: int) -> float | None:
        leer = getattr(source, "boxes_of", None)
        if leer is None:
            return None
        try:
            cajas = leer(pagina)
        except Exception:  # noqa: BLE001 - sin cajas, se busca la fecha sin la leyenda
            return None
        for caja in cajas:
            texto = _plano(caja.text or "")
            if any(leyenda in texto for leyenda in self.LEYENDAS):
                return caja.top
        return None

    def _armar(self, source, tanda: Sequence[int], bandas: dict[int, Band]) -> bytes | None:
        try:
            import pymupdf
        except Exception:
            logger.debug("no se pudo importar pymupdf para el mosaico", exc_info=True)
            return None

        recortes = []
        for pagina in tanda:
            try:
                recortes.append(
                    (pagina, pymupdf.Pixmap(source.render(pagina, bandas[pagina], self._dpi)))
                )
            except Exception:  # noqa: BLE001 - una página que no se recorta no tumba el mosaico
                logger.debug("no se pudo recortar la fecha de la página %s", pagina)
        if not recortes:
            return None

        # Mismo patrón que nombres: ancho máximo + espacio para etiqueta
        _ANCHO_ETIQUETA = 150
        _SEPARACION = 14
        ancho = max(pix.width for _, pix in recortes) + _ANCHO_ETIQUETA + _SEPARACION
        alto = sum(pix.height + _SEPARACION for _, pix in recortes) + _SEPARACION
        lienzo = pymupdf.open()
        try:
            hoja = lienzo.new_page(width=ancho, height=alto)
            hoja.draw_rect(hoja.rect, color=(1, 1, 1), fill=(1, 1, 1))
            y = _SEPARACION
            for pagina, pix in recortes:
                hoja.insert_text((_SEPARACION, y + pix.height / 2), f"[{pagina}]", fontsize=44)
                hoja.insert_image(
                    pymupdf.Rect(
                        _ANCHO_ETIQUETA, y, _ANCHO_ETIQUETA + pix.width, y + pix.height
                    ),
                    pixmap=pix,
                )
                y += pix.height + _SEPARACION
            return hoja.get_pixmap(alpha=False).tobytes("jpeg", jpg_quality=88)
        except Exception:
            logger.warning("no se pudo armar el mosaico de fechas", exc_info=True)
            return None
        finally:
            lienzo.close()


#: Etiqueta de página en la respuesta del proveedor.
_ETIQUETA = re.compile(r"\[(\d{1,4})\]")

#: Leyendas de fecha para trocear la respuesta.
_LEYENDA_FECHA = re.compile(
    r"a\s+los\s+\d+|d[ií]as\s+del\s+mes\s+de|de\s+mil\s+novecientos|"
    r"testimonio|firmamos|sellamos|universidad\s+de\s+cartagena",
    re.I,
)


def _repartir_fechas(texto: str, tanda: Sequence[int]) -> dict[int, str]:
    """Cada fecha de vuelta a su página, parseada a DD/MM/AAAA."""
    # Primero intenta por etiqueta [página]
    por_etiqueta = _por_etiqueta(texto, tanda)
    if por_etiqueta is not None:
        return _parsear_fechas(por_etiqueta)

    # Si no, trocea por las leyendas de fecha
    trozos = _por_leyenda_fecha(texto)
    if len(trozos) == len(tanda):
        return _parsear_fechas(dict(zip(tanda, trozos, strict=True)))

    logger.info(
        "mosaico de fechas: %d bloques para %d franjas; no se reparte",
        len(trozos),
        len(tanda),
    )
    return {}


def _por_etiqueta(texto: str, tanda: Sequence[int]) -> dict[int, str] | None:
    esperadas = {int(pagina) for pagina in tanda}
    trozos: dict[int, str] = {}
    for renglon in texto.splitlines():
        etiquetas = [int(e) for e in _ETIQUETA.findall(renglon) if int(e) in esperadas]
        if len(etiquetas) != 1:
            continue
        resto = _ETIQUETA.sub(" ", renglon).replace("|", " ").strip(" -")
        if resto:
            trozos.setdefault(etiquetas[0], resto)
    if set(trozos) != esperadas:
        return None
    return trozos


def _parsear_fechas(trozos: dict[int, str]) -> dict[int, str]:
    """Convierte cada trozo de texto a fecha DD/MM/AAAA usando fecha_en_letras."""
    fechas: dict[int, str] = {}
    for pagina, trozo in trozos.items():
        fecha = fecha_en_letras(trozo)
        if fecha:
            fechas[pagina] = fecha
    return fechas


def _por_leyenda_fecha(texto: str) -> list[str]:
    """Parte el texto en un trozo por franja, usando la leyenda de fecha como separador.

    A diferencia de los nombres (donde la leyenda está ANTES del nombre), en la fecha
    la leyenda "DÍAS DEL MES DE" está EN MEDIO de la fórmula. La línea EXACTA
    "DÍAS DEL MES DE" (sola) marca el final de una fecha y el inicio de la siguiente.
    """
    trozos: list[list[str]] = []
    actual: list[str] = []

    for renglon in texto.splitlines():
        plano_renglon = _plano(renglon).strip()
        # Solo la línea EXACTA "DÍAS DEL MES DE" es separador
        if plano_renglon == "DIAS DEL MES DE":
            if actual:
                trozos.append(actual)
                actual = []
            continue
        actual.append(renglon)

    if actual:
        trozos.append(actual)

    return ["\n".join(trozo) for trozo in trozos if trozo]