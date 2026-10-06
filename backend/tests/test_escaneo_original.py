"""La fuente sabe dar el escaneo original de una cara, y sabe cuándo no debe.

Un libro escaneado es, cara por cara, un único JPEG que cubre la hoja. Al
proveedor de pago le da igual recibir ese JPEG o una copia rasterizada de él
-- lee lo mismo --, pero para este proceso no es lo mismo: rasterizar cuesta
170 ms del hilo que manda por cara, y sacar la imagen tal cual cuesta uno.

Lo que se fija aquí es que se dé **sólo cuando lo que hay dentro es lo que se
ve**: una imagen, en JPEG, que cubre la hoja y sin girar. Todo lo demás vuelve
como ``None`` y quien pregunta rasteriza, que es lo que había.
"""

from io import BytesIO

import pymupdf
import pytest
from PIL import Image

from resolutions.adapters.pymupdf_source import PyMuPDFPageSource


def jpeg(ancho: int, alto: int) -> bytes:
    salida = BytesIO()
    Image.new("L", (ancho, alto), 230).save(salida, "JPEG", quality=85)
    return salida.getvalue()


@pytest.fixture
def escaneo(tmp_path):
    """Un libro de dos caras escaneadas, y una tercera que no lo es."""
    original = jpeg(300, 400)
    documento = pymupdf.open()
    for _ in range(2):
        pagina = documento.new_page(width=300, height=400)
        pagina.insert_image(pagina.rect, stream=original)
    vectorial = documento.new_page(width=300, height=400)
    vectorial.insert_text((40, 60), "Folio 336", fontsize=18)
    ruta = tmp_path / "escaneo.pdf"
    documento.save(ruta)
    documento.close()
    return ruta, original


class TestElEscaneoOriginal:
    def test_una_cara_escaneada_devuelve_su_jpeg_tal_cual(self, escaneo):
        ruta, original = escaneo
        with PyMuPDFPageSource(ruta) as fuente:
            assert fuente.imagen_escaneada(1) == original
            assert fuente.imagen_escaneada(2) == original

    def test_una_cara_sin_imagen_no_devuelve_nada(self, escaneo):
        ruta, _ = escaneo
        with PyMuPDFPageSource(ruta) as fuente:
            assert fuente.imagen_escaneada(3) is None

    def test_una_cara_girada_no_se_da_por_buena(self, tmp_path):
        """Girada, lo que el proveedor vería no es lo que ve el operador."""
        documento = pymupdf.open()
        pagina = documento.new_page(width=300, height=400)
        pagina.insert_image(pagina.rect, stream=jpeg(300, 400))
        pagina.set_rotation(90)
        ruta = tmp_path / "girado.pdf"
        documento.save(ruta)
        documento.close()
        with PyMuPDFPageSource(ruta) as fuente:
            assert fuente.imagen_escaneada(1) is None

    def test_una_imagen_que_no_cubre_la_hoja_no_es_la_hoja(self, tmp_path):
        """Una fotografía pegada en un formulario no es el formulario."""
        documento = pymupdf.open()
        pagina = documento.new_page(width=300, height=400)
        pagina.insert_image(pymupdf.Rect(20, 20, 140, 180), stream=jpeg(120, 160))
        ruta = tmp_path / "foto.pdf"
        documento.save(ruta)
        documento.close()
        with PyMuPDFPageSource(ruta) as fuente:
            assert fuente.imagen_escaneada(1) is None

    def test_una_imagen_que_no_es_jpeg_se_rasteriza(self, tmp_path):
        png = BytesIO()
        Image.new("L", (300, 400), 230).save(png, "PNG")
        documento = pymupdf.open()
        pagina = documento.new_page(width=300, height=400)
        pagina.insert_image(pagina.rect, stream=png.getvalue())
        ruta = tmp_path / "png.pdf"
        documento.save(ruta)
        documento.close()
        with PyMuPDFPageSource(ruta) as fuente:
            assert fuente.imagen_escaneada(1) is None


class TestElFormatoDelRasterizado:
    def test_por_omision_es_png_y_a_peticion_es_jpeg(self, escaneo):
        ruta, _ = escaneo
        with PyMuPDFPageSource(ruta) as fuente:
            assert fuente.render(1, None, 100).startswith(b"\x89PNG")
            assert fuente.render(1, None, 100, formato="jpeg").startswith(b"\xff\xd8\xff")

    def test_el_jpeg_mide_lo_mismo_que_el_png(self, escaneo):
        ruta, _ = escaneo
        with PyMuPDFPageSource(ruta) as fuente:
            png = Image.open(BytesIO(fuente.render(1, None, 100)))
            jpg = Image.open(BytesIO(fuente.render(1, None, 100, formato="jpeg")))
            assert png.size == jpg.size


class TestLosRenglonesSeExtraenUnaSolaVez:
    def test_lineas_y_cajas_salen_de_la_misma_pasada(self, escaneo):
        """Las dos formas dicen lo mismo del mismo renglón."""
        ruta, _ = escaneo
        with PyMuPDFPageSource(ruta) as fuente:
            lineas = fuente.lines_of(3)
            cajas = fuente.boxes_of(3)
            assert [linea.text for linea in lineas] == ["Folio 336"]
            assert [caja.text for caja in cajas] == ["Folio 336"]

    def test_lo_devuelto_no_es_la_memoria_interna(self, escaneo):
        """Quien ordene o vacíe lo que recibe no cambia lo que recibe el siguiente."""
        ruta, _ = escaneo
        with PyMuPDFPageSource(ruta) as fuente:
            fuente.lines_of(3).clear()
            assert [linea.text for linea in fuente.lines_of(3)] == ["Folio 336"]
