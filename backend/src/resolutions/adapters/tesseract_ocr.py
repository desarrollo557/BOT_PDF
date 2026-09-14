"""OCR local con Tesseract, hablándole al binario directamente.

Se hacía a través de pytesseract, que guarda la imagen en un archivo temporal,
la lee desde ahí y al terminar busca ese archivo con un ``glob`` en la carpeta
temporal del sistema. En la máquina del operador esa carpeta tiene trece mil
archivos, así que cada llamada de OCR pasaba más tiempo listándola que leyendo:
sesenta y seis lecturas eran trece segundos de recorrer la carpeta temporal.

Tesseract acepta la imagen por ``stdin`` y devuelve el TSV por ``stdout`` desde
la versión 3.03, y con eso no hay archivo que escribir, leer ni buscar.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps

from ..application.ports import OcrResult

#: El binario. El instalador de Windows no lo pone en el PATH, y descubrirlo en
#: un proceso worker que heredó un entorno viejo es una forma confusa de
#: enterarse; por eso la ubicación es explícita y configurable.
TESSERACT_CMD = os.environ.get("RESOLUTIONS_TESSERACT_CMD") or "tesseract"

#: Page segmentation modes. A header crop is a single uniform block; a full page
#: needs the layout analyser. Using the right one is free accuracy.
PSM_UNIFORM_BLOCK = 6
PSM_AUTO = 3

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
        data = en_columnas(self._run(_codificar(image)))

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

    def _run(self, image: bytes) -> str:
        """Una llamada al binario: la imagen entra por stdin, el TSV sale por stdout."""
        args = [
            self._command,
            "stdin",
            "stdout",
            "-l",
            self._config.language,
            "--psm",
            str(self._config.psm),
            "tsv",
        ]
        extra: dict[str, object] = {}
        if sys.platform == "win32":
            # Sin esto, un servicio sin consola abre y cierra una ventana negra
            # por cada página que lee.
            extra["creationflags"] = subprocess.CREATE_NO_WINDOW
        completed = subprocess.run(args, input=image, capture_output=True, check=False, **extra)
        if completed.returncode != 0:
            motivo = completed.stderr.decode("utf-8", "replace").strip()
            raise TesseractError(motivo or f"tesseract terminó con código {completed.returncode}")
        return completed.stdout.decode("utf-8", "replace")

    def _prepare(self, image_png: bytes) -> Image.Image:
        image = Image.open(BytesIO(image_png)).convert("L")
        return ImageOps.autocontrast(image) if self._config.autocontrast else image

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


def _codificar(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=_FORMATO)
    return buffer.getvalue()


class HeaderAndPageOcr:
    """Applies the right segmentation mode to each rung of the cascade."""

    def __init__(self, language: str = "spa") -> None:
        self._band = TesseractOcr(TesseractConfig(language=language, psm=PSM_UNIFORM_BLOCK))
        self._page = TesseractOcr(TesseractConfig(language=language, psm=PSM_AUTO))
        self._seen_bytes = 0

    def read(self, image_png: bytes) -> OcrResult:
        # A header crop is a small image; a full page render is not. The size is
        # a reliable enough signal to pick the segmentation mode without
        # threading extra state through the pipeline.
        engine = self._band if len(image_png) < 400_000 else self._page
        return engine.read(image_png)
