"""La caché de las lecturas de pago: cada imagen se paga una vez (2026-11-18).

La segunda ejecución de una caja vuelve a preguntar lo mismo: la misma imagen
al OCR, el mismo sello a la visión. Con la caché la respuesta sale de disco y
no se vuelve a pagar, ni a contar como página pagada.
"""

from __future__ import annotations

import pytest

from resolutions.adapters import cache_de_lecturas


@pytest.fixture
def cache(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTPDF_CACHE_DE_LECTURAS", "1")
    monkeypatch.setenv("RESOLUTIONS_DATA_DIR", str(tmp_path))
    cache_de_lecturas._conexiones.clear()
    yield tmp_path
    for conexion in cache_de_lecturas._conexiones.values():
        conexion.close()
    cache_de_lecturas._conexiones.clear()


def test_lo_guardado_se_lee_y_lo_vacio_no_se_guarda(cache):
    llave = cache_de_lecturas.clave("ocr", "mistral-ocr-latest", b"imagen")
    assert cache_de_lecturas.leer(llave) is None
    cache_de_lecturas.guardar(llave, "RE2310202402908")
    assert cache_de_lecturas.leer(llave) == "RE2310202402908"
    vacia = cache_de_lecturas.clave("ocr", "mistral-ocr-latest", b"otra")
    cache_de_lecturas.guardar(vacia, "")
    assert cache_de_lecturas.leer(vacia) is None
    assert (cache / cache_de_lecturas.NOMBRE).is_file()


def test_la_huella_cambia_con_el_modelo_y_el_pedido(cache):
    assert cache_de_lecturas.clave("chat", "a", "pide", b"x") != cache_de_lecturas.clave("chat", "b", "pide", b"x")
    assert cache_de_lecturas.clave("chat", "a", "pide", b"x") != cache_de_lecturas.clave("chat", "a", "otro", b"x")


def test_el_ocr_no_vuelve_a_pagar_la_misma_imagen(cache, monkeypatch):
    from resolutions.adapters.mistral_ocr import MistralOcr

    pedidas: list[int] = []

    def pedir(self, cuerpo):
        pedidas.append(1)
        return {"pages": [{"markdown": "No DE RADICACION: RE2310202402908"}], "usage_info": {"pages_processed": 1}}

    monkeypatch.setattr(MistralOcr, "_pedir", pedir)
    monkeypatch.setattr("resolutions.adapters.mistral_ocr._aligerada", lambda imagen: imagen)
    ocr = MistralOcr(api_key="llave-de-prueba")
    primera = ocr.read(b"\x89PNG-imagen-del-sello").text
    segunda = ocr.read(b"\x89PNG-imagen-del-sello").text
    assert primera == segunda and "RE2310202402908" in segunda
    assert pedidas == [1]


def test_apagada_no_guarda_nada(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTPDF_CACHE_DE_LECTURAS", "0")
    monkeypatch.setenv("RESOLUTIONS_DATA_DIR", str(tmp_path))
    cache_de_lecturas._conexiones.clear()
    cache_de_lecturas.guardar("x", "y")
    assert cache_de_lecturas.leer("x") is None and not (tmp_path / cache_de_lecturas.NOMBRE).exists()
