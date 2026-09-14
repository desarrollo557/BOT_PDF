"""El OCR le habla al binario por stdin y stdout, sin archivos temporales.

Se hacía a través de pytesseract, que guardaba cada imagen en la carpeta
temporal del sistema y al terminar la buscaba con un glob: con trece mil
archivos en esa carpeta, cada lectura pasaba más tiempo listándola que
leyendo. Estas pruebas fijan que el adaptador construye la llamada correcta,
entiende el TSV que devuelve Tesseract y explica un fallo del binario; y una
de ellas, sólo donde Tesseract está instalado, lee de verdad.
"""

from __future__ import annotations

import shutil
import subprocess
from io import BytesIO

import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from resolutions.adapters.tesseract_ocr import (  # noqa: E402
    TESSERACT_CMD,
    TesseractConfig,
    TesseractError,
    TesseractOcr,
    en_columnas,
)

TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "1\t1\t0\t0\t0\t0\t0\t0\t800\t200\t-1\t\n"
    "4\t1\t1\t1\t1\t0\t10\t10\t400\t30\t-1\t\n"
    "5\t1\t1\t1\t1\t1\t10\t10\t120\t30\t96.5\tRESOLUCION\n"
    "5\t1\t1\t1\t1\t2\t140\t10\t60\t30\t91.0\tNo.\n"
    "5\t1\t1\t1\t1\t3\t210\t10\t80\t30\t88.25\t00412\n"
    "5\t1\t1\t1\t2\t1\t10\t50\t200\t30\t70.0\tPor\n"
    "5\t1\t1\t1\t2\t2\t220\t50\t200\t30\t75.0\tla cual\n"
)


def _png(texto: str = "", ancho: int = 200, alto: int = 60) -> bytes:
    imagen = Image.new("RGB", (ancho, alto), "white")
    if texto:
        ImageDraw.Draw(imagen).text((10, 10), texto, fill="black")
    buffer = BytesIO()
    imagen.save(buffer, format="PNG")
    return buffer.getvalue()


class TestElTsvSeLeeComoColumnas:
    def test_cada_columna_con_su_tipo(self):
        columnas = en_columnas(TSV)
        assert columnas["text"][2:5] == ["RESOLUCION", "No.", "00412"]
        assert columnas["conf"][2] == 96.5
        assert columnas["conf"][0] == -1.0
        assert columnas["line_num"][5] == 2
        assert all(isinstance(valor, int) for valor in columnas["block_num"])

    def test_una_fila_sin_texto_no_descuadra(self):
        """Los renglones de estructura no llevan palabra, y a veces ni la celda."""
        columnas = en_columnas("level\tconf\ttext\n1\t-1\n5\t90\thola\n")
        assert columnas["text"] == ["", "hola"]
        assert columnas["conf"] == [-1.0, 90.0]

    def test_vacio_es_vacio(self):
        assert en_columnas("")["text"] == []


class TestLaLlamadaAlBinario:
    @staticmethod
    def _con_respuesta(monkeypatch, stdout: str = TSV, returncode: int = 0, stderr: str = ""):
        llamadas: list[dict] = []

        def run(args, **kwargs):
            llamadas.append({"args": args, **kwargs})
            return subprocess.CompletedProcess(
                args, returncode, stdout=stdout.encode(), stderr=stderr.encode()
            )

        monkeypatch.setattr(subprocess, "run", run)
        return llamadas

    def test_la_imagen_entra_por_stdin_y_el_tsv_sale_por_stdout(self, monkeypatch):
        llamadas = self._con_respuesta(monkeypatch)
        TesseractOcr(TesseractConfig(language="spa", psm=6), command="tess").read(_png())

        [llamada] = llamadas
        assert llamada["args"][:3] == ["tess", "stdin", "stdout"]
        assert llamada["args"][3:] == ["-l", "spa", "--psm", "6", "tsv"]
        assert llamada["input"][:8] == b"\x89PNG\r\n\x1a\n", "va como PNG"
        assert llamada["capture_output"] is True

    def test_lo_leido_conserva_los_renglones(self, monkeypatch):
        self._con_respuesta(monkeypatch)
        resultado = TesseractOcr().read(_png())
        assert resultado.text == "RESOLUCION No. 00412\nPor la cual"
        assert round(resultado.mean_confidence, 3) == round((96.5 + 91 + 88.25 + 70 + 75) / 500, 3)

    def test_una_lectura_floja_vuelve_vacia(self, monkeypatch):
        """Un texto inventado con poca confianza mueve páginas al archivo equivocado."""
        flojo = TSV.replace("96.5", "20").replace("91.0", "20").replace("88.25", "20")
        flojo = flojo.replace("70.0", "20").replace("75.0", "20")
        self._con_respuesta(monkeypatch, stdout=flojo)
        resultado = TesseractOcr().read(_png())
        assert resultado.text == ""
        assert 0 < resultado.mean_confidence < 0.4

    def test_un_fallo_del_binario_dice_lo_que_dijo(self, monkeypatch):
        self._con_respuesta(monkeypatch, returncode=1, stderr="Error opening data file spa.traineddata")
        with pytest.raises(TesseractError, match="spa.traineddata"):
            TesseractOcr().read(_png())

    def test_sin_binario_falla_como_cualquier_programa_que_no_esta(self):
        with pytest.raises(FileNotFoundError):
            TesseractOcr(command="no-existe-tesseract-xyz").read(_png())


@pytest.mark.skipif(shutil.which(TESSERACT_CMD) is None, reason="sin Tesseract instalado")
class TestConElBinarioDeVerdad:
    def test_lee_un_encabezado_impreso(self):
        imagen = Image.new("RGB", (900, 160), "white")
        try:
            fuente = ImageFont.load_default(size=48)
        except TypeError:  # Pillow viejo: la fuente por defecto no admite tamaño
            fuente = ImageFont.load_default()
        ImageDraw.Draw(imagen).text((30, 40), "RESOLUCION No. 00412", fill="black", font=fuente)
        buffer = BytesIO()
        imagen.save(buffer, format="PNG")

        resultado = TesseractOcr(TesseractConfig(language="spa", psm=6)).read(buffer.getvalue())
        assert "00412" in resultado.text
        assert resultado.mean_confidence > 0.5
