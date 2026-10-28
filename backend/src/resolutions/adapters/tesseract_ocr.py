"""OCR local con Tesseract, hablándole al binario directamente.

Se hacía a través de pytesseract, que guarda la imagen en un archivo temporal,
la lee desde ahí y al terminar busca ese archivo con un ``glob`` en la carpeta
temporal del sistema. En la máquina del operador esa carpeta tiene trece mil
archivos, así que cada llamada de OCR pasaba más tiempo listándola que leyendo:
sesenta y seis lecturas eran trece segundos de recorrer la carpeta temporal.

Tesseract acepta la imagen por ``stdin`` y devuelve el TSV por ``stdout`` desde
la versión 3.03, y con eso no hay archivo que escribir, leer ni buscar.

Para muchas imágenes pequeñas hay además una lectura por lotes: arrancar el
binario cuesta 0,22 s -- es cargar el modelo del español --, y en un libro de
grados eran 303 arranques, la quinta parte del tiempo de Tesseract. Con una
lista de archivos el binario arranca una vez y lee varias; cada imagen se lee
igual que sola, con el mismo modo y el mismo idioma.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageFilter, ImageOps

from ..application.ports import OcrResult

#: El binario. El instalador de Windows no lo pone en el PATH, y descubrirlo en
#: un proceso worker que heredó un entorno viejo es una forma confusa de
#: enterarse; por eso la ubicación es explícita y configurable.
TESSERACT_CMD = os.environ.get("RESOLUTIONS_TESSERACT_CMD") or "tesseract"
#: Un hilo por llamada. El binario usa OpenMP y abre tantos hilos como núcleos
#: tiene la máquina; el bot ya lanza varias llamadas a la vez (varios
#: documentos, varias páginas), y juntas se ahogaban: cuatro PDF de Magangué a
#: la vez tardaban 41 s y con un hilo cada llamada 20 s, mismo resultado. En un
#: equipo con menos núcleos la tanda de sellos pasaba de su tope de 225 s y
#: caía al OCR de pago (2026-10-28). Quien lo fije a mano, manda.
_ENTORNO = {**os.environ, "OMP_THREAD_LIMIT": os.environ.get("OMP_THREAD_LIMIT") or "1"}


def tesseract_disponible() -> bool:
    """Si el comando de Tesseract configurado existe en este equipo.

    Sin abrirlo: una ruta que existe o un nombre que está en el PATH. Lo
    pregunta la salud del servicio para avisar en pantalla, porque sin él cada
    página con «OCR + IA» se paga en el motor remoto y con «Solo OCR» sale
    vacía, y ninguna de las dos cosas se nota hasta ver la factura o el Excel.
    """
    import shutil

    comando = TESSERACT_CMD
    if os.path.dirname(comando):
        return os.path.isfile(comando)
    return shutil.which(comando) is not None

#: Page segmentation modes. A header crop is a single uniform block; a full page
#: needs the layout analyser. Using the right one is free accuracy.
PSM_UNIFORM_BLOCK = 6
PSM_AUTO = 3
#: Un renglón suelto, que es lo que se le pasa al rastrear un campo concreto.
#: Con el modo de página entera, Tesseract busca columnas y párrafos en una
#: banda de cuatro centímetros y decide que no hay texto.
PSM_UNA_LINEA = 7
#: Texto suelto, en cualquier orden: los números impresos bajo una rejilla.
PSM_TEXTO_DISPERSO = 11

#: Cómo viaja la imagen al binario. PNG y no PGM crudo, medido sobre la banda
#: de un encabezado real: pesa doce veces menos y Tesseract la lee un 20 % más
#: rápido, y los 9 ms de codificarla no se notan.
_FORMATO = "PNG"


@dataclass(frozen=True, slots=True)
class TesseractConfig:
    language: str = "spa"
    psm: int = PSM_UNIFORM_BLOCK
    #: Below this mean word confidence the read is treated as unusable, which
    #: routes the page to the next rung instead of poisoning a group.
    min_word_confidence: float = 40.0
    autocontrast: bool = True
    #: Los únicos caracteres que se aceptan como respuesta, o ``None`` para
    #: todos. Atarlo a dígitos al leer una cédula sube mucho el acierto: sin
    #: esto, Tesseract propone letras donde hay números -- "7" leído "?" o "l",
    #: "0" leído "O" -- porque el modelo del idioma español las espera.
    whitelist: str | None = None
    #: Cuánto se amplía la imagen antes de leerla. Un recorte estrecho a 400 dpi
    #: sigue teniendo dígitos de pocos píxeles de alto, y Tesseract acierta
    #: bastante más cuando la altura de la letra pasa de treinta píxeles.
    escala: int = 1
    #: Ninguna página puede dejar detenido el lote indefinidamente.
    timeout_seconds: float = 15.0
    #: Desde qué gris se toma un píxel por tinta, o ``None`` para no tocarlo.
    #: Los datos rellenados a máquina en gris muy claro -- «cuatro (4) días del
    #: mes de abril» en UPD3859806 -- se pierden en el fondo; pasados a negro
    #: puro, Tesseract los lee.
    umbral: int | None = None
    #: Tamaño del filtro de mediana que borra las motas después del umbral, o
    #: ``None``. En un escaneo sucio el umbral vuelve tinta cada mota, y
    #: Tesseract tarda el doble buscando letras en ellas.
    mediana: int | None = None


class TesseractError(RuntimeError):
    """El binario terminó con error, y esto es lo que dijo por stderr."""


def en_columnas(tsv: str) -> dict[str, list]:
    """El TSV de Tesseract como columnas, con el nombre de cada una.

    Es la misma forma que entregaba ``pytesseract.Output.DICT``: ``text`` se
    queda como texto, ``conf`` es decimal y todo lo demás entero. Una fila sin
    la última celda -- pasa con los renglones de estructura, que no tienen
    palabra -- se rellena con vacío en vez de descuadrar las columnas.
    """
    lineas = [linea for linea in tsv.splitlines() if linea]
    if not lineas:
        return {"text": [], "conf": []}
    cabecera = lineas[0].split("\t")
    columnas: dict[str, list] = {nombre: [] for nombre in cabecera}
    for linea in lineas[1:]:
        celdas = linea.split("\t")
        if len(celdas) < len(cabecera):
            celdas += [""] * (len(cabecera) - len(celdas))
        for nombre, celda in zip(cabecera, celdas, strict=False):
            if nombre == "text":
                columnas[nombre].append(celda)
            elif nombre == "conf":
                columnas[nombre].append(float(celda))
            else:
                columnas[nombre].append(int(celda))
    return columnas


class TesseractOcr:
    """Local OCR. Free, CPU-bound, and released from the GIL while it runs."""

    def __init__(
        self, config: TesseractConfig | None = None, *, command: str | None = None
    ) -> None:
        self._config = config or TesseractConfig()
        self._command = command or TESSERACT_CMD

    def read(self, image_png: bytes) -> OcrResult:
        image = self._prepare(image_png)
        return self._resultado(en_columnas(self._run(_codificar(image))))

    def palabras(self, image_png: bytes) -> list[tuple[str, int, int, int, int]]:
        """Cada palabra leída con su caja, en píxeles: (texto, x, y, ancho, alto).

        La usa quien necesita saber dónde está lo que se leyó, no sólo qué:
        la rejilla de casillas de la guía de envío se ubica por sus números.
        Las cajas son de la imagen que se pasó, aunque se haya ampliado.

        Se lee dos veces, la imagen tal cual y la preparada, y se juntan: en la
        guía de UPD2320047 la preparada perdía casi todos los números de la
        rejilla y la cruda los traía.
        """
        factor = max(1, self._config.escala)
        lecturas = [
            (en_columnas(self._run(image_png)), 1),
            (en_columnas(self._run(_codificar(self._prepare(image_png)))), factor),
        ]
        return [
            (
                texto.strip(),
                data["left"][i] // escala,
                data["top"][i] // escala,
                data["width"][i] // escala,
                data["height"][i] // escala,
            )
            for data, escala in lecturas
            for i, texto in enumerate(data["text"])
            if texto and texto.strip()
        ]

    def read_varias(self, images_png: list[bytes]) -> list[OcrResult]:
        """Varias imágenes en un solo arranque del binario, cada una con su resultado."""
        return [self._resultado(data) for data in self._por_lote(images_png)]

    def read_con_confianza_varias(
        self, images_png: list[bytes]
    ) -> list[tuple[str, dict[str, float]]]:
        """Como ``read_con_confianza``, para varias imágenes en un arranque."""
        return [self._con_confianza(data) for data in self._por_lote(images_png)]

    def _por_lote(self, images_png: list[bytes]) -> list[dict[str, list]]:
        """Las columnas del TSV de cada imagen, leídas todas en una llamada.

        Las imágenes van a una carpeta temporal propia -- no a la del sistema,
        que en la máquina del operador tiene trece mil archivos -- y el binario
        recibe la lista. Cada fila del TSV dice de qué imagen es (`page_num`).
        Si el lote falla se lanza el error, y quien lo pidió lee una por una
        para saber cuál de ellas era la que no se dejaba leer.
        """
        if len(images_png) <= 1:
            return [self._sola(imagen) for imagen in images_png]
        with tempfile.TemporaryDirectory(prefix="tess_") as carpeta:
            rutas = []
            for indice, imagen in enumerate(images_png, start=1):
                ruta = os.path.join(carpeta, f"{indice:04d}.png")
                self._prepare(imagen).save(ruta, format=_FORMATO)
                rutas.append(ruta)
            lista = os.path.join(carpeta, "lista.txt")
            with open(lista, "w", encoding="utf-8") as archivo:
                archivo.write("".join(f"{ruta}\n" for ruta in rutas))
            tsv = self._run(None, entrada=lista, imagenes=len(rutas))
        return _partir_por_imagen(en_columnas(tsv), len(images_png))

    def _sola(self, image_png: bytes) -> dict[str, list]:
        return en_columnas(self._run(_codificar(self._prepare(image_png))))

    def _resultado(self, data: dict[str, list]) -> OcrResult:
        words: list[str] = []
        confidences: list[float] = []
        for text, confidence in zip(data["text"], data["conf"], strict=False):
            token = (text or "").strip()
            score = float(confidence)
            if not token or score < 0:
                continue
            words.append(token)
            confidences.append(score)

        if not words:
            return OcrResult(text="", mean_confidence=0.0)

        mean = sum(confidences) / len(confidences)
        if mean < self._config.min_word_confidence:
            # Honest empty beats confident nonsense: an invented code silently
            # moves pages into the wrong file.
            return OcrResult(text="", mean_confidence=mean / 100.0)

        return OcrResult(text=self._reflow(data, words), mean_confidence=mean / 100.0)

    def _run(self, image: bytes | None, *, entrada: str = "stdin", imagenes: int = 1) -> str:
        """Una llamada al binario: la imagen entra por stdin, el TSV sale por stdout.

        Con ``entrada`` la lista de archivos de un lote, y entonces el tiempo
        máximo es el de una imagen por cada una que trae.
        """
        args = [
            self._command,
            entrada,
            "stdout",
            "-l",
            self._config.language,
            "--psm",
            str(self._config.psm),
            "tsv",
        ]
        if self._config.whitelist:
            args[-1:-1] = ["-c", f"tessedit_char_whitelist={self._config.whitelist}"]
        extra: dict[str, object] = {"env": _ENTORNO}
        if sys.platform == "win32":
            # Sin esto, un servicio sin consola abre y cierra una ventana negra
            # por cada página que lee.
            extra["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            completed = subprocess.run(
                args,
                input=image,
                capture_output=True,
                check=False,
                timeout=self._config.timeout_seconds * imagenes,
                **extra,
            )
        except subprocess.TimeoutExpired as error:
            raise TesseractError(
                f"Tesseract superó {self._config.timeout_seconds * imagenes:g} s"
            ) from error
        if completed.returncode != 0:
            motivo = completed.stderr.decode("utf-8", "replace").strip()
            raise TesseractError(motivo or f"tesseract terminó con código {completed.returncode}")
        return completed.stdout.decode("utf-8", "replace")

    def read_con_confianza(self, image_png: bytes) -> tuple[str, dict[str, float]]:
        """El texto por renglones y la confianza de cada palabra, de 0 a 100.

        Para juntar dos lecturas palabra a palabra: una palabra que Tesseract
        lee con 90 se cree; una con 0 es una mancha o una letra que no supo, y
        ahí vale más lo que leyó la otra fuente.
        """
        image = self._prepare(image_png)
        return self._con_confianza(en_columnas(self._run(_codificar(image))))

    def _con_confianza(self, data: dict[str, list]) -> tuple[str, dict[str, float]]:
        palabras = [(t or "").strip() for t in data["text"]]
        confianza: dict[str, float] = {}
        for texto, valor in zip(palabras, data["conf"], strict=False):
            if texto and float(valor) >= 0:
                clave = texto.upper()
                confianza[clave] = max(confianza.get(clave, 0.0), float(valor))
        validas = [p for p, c in zip(palabras, data["conf"], strict=False) if p and float(c) >= 0]
        return self._reflow(data, validas), confianza

    def _prepare(self, image_png: bytes) -> Image.Image:
        image = Image.open(BytesIO(image_png)).convert("L")
        if self._config.escala > 1:
            image = image.resize(
                (image.width * self._config.escala, image.height * self._config.escala),
                Image.LANCZOS,
            )
        if self._config.autocontrast:
            image = ImageOps.autocontrast(image)
        if self._config.umbral is not None:
            corte = self._config.umbral
            image = image.point(lambda gris: 0 if gris < corte else 255)
        if self._config.mediana:
            image = image.filter(ImageFilter.MedianFilter(self._config.mediana))
        return image

    @staticmethod
    def _reflow(data: dict, words: list[str]) -> str:
        """Rebuild line breaks, because the scorer reads position off lines."""
        lines: dict[tuple[int, int, int], list[str]] = {}
        for index, text in enumerate(data["text"]):
            token = (text or "").strip()
            if not token or float(data["conf"][index]) < 0:
                continue
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            lines.setdefault(key, []).append(token)
        if not lines:
            return " ".join(words)
        return "\n".join(" ".join(tokens) for _, tokens in sorted(lines.items()))


def _partir_por_imagen(data: dict[str, list], cuantas: int) -> list[dict[str, list]]:
    """Las columnas de un TSV de lote, separadas por la imagen de la que es cada fila."""
    partes: list[dict[str, list]] = [{nombre: [] for nombre in data} for _ in range(cuantas)]
    for fila, pagina in enumerate(data.get("page_num") or []):
        if not 1 <= pagina <= cuantas:
            continue
        destino = partes[pagina - 1]
        for nombre, columna in data.items():
            destino[nombre].append(columna[fila])
    return partes


def _codificar(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=_FORMATO)
    return buffer.getvalue()


class HeaderAndPageOcr:
    """Applies the right segmentation mode to each rung of the cascade."""

    def __init__(self, language: str = "spa") -> None:
        self._band = TesseractOcr(TesseractConfig(language=language, psm=PSM_UNIFORM_BLOCK))
        self._page = TesseractOcr(TesseractConfig(language=language, psm=PSM_AUTO))

    def read(self, image_png: bytes) -> OcrResult:
        # A header crop is a small image; a full page render is not. The size is
        # a reliable enough signal to pick the segmentation mode without
        # threading extra state through the pipeline.
        return self._motor(image_png).read(image_png)

    def read_varias(self, images_png: list[bytes]) -> list[OcrResult]:
        """Varias en un arranque por motor, cada una con el modo que le toca."""
        resultados: list[OcrResult | None] = [None] * len(images_png)
        for motor in (self._band, self._page):
            suyas = [i for i, imagen in enumerate(images_png) if self._motor(imagen) is motor]
            if suyas:
                leidas = motor.read_varias([images_png[i] for i in suyas])
                for indice, leida in zip(suyas, leidas, strict=True):
                    resultados[indice] = leida
        return [r or OcrResult(text="", mean_confidence=0.0) for r in resultados]

    def _motor(self, image_png: bytes) -> TesseractOcr:
        return self._band if len(image_png) < 400_000 else self._page
