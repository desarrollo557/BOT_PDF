"""Un PDF que no se puede leer falla con un motivo que el operador entiende."""

from __future__ import annotations

import pymupdf
import pytest

from resolutions.adapters.pymupdf_source import PdfQueNoSeAbre, PyMuPDFPageSource


def _pdf(ruta, **guardar):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 60), "ACTA ORDINARIA No. 005")
        doc.save(ruta, **guardar)
    return ruta


@pytest.mark.parametrize(
    ("contenido", "motivo"),
    [(b"", "vacío"), (b"%PDF-1.4 esto no es un pdf", "dañado")],
)
def test_vacio_o_danado(tmp_path, contenido, motivo):
    ruta = tmp_path / "x.pdf"
    ruta.write_bytes(contenido)
    with pytest.raises(PdfQueNoSeAbre, match=motivo):
        PyMuPDFPageSource(ruta, "acta.pdf")


def test_con_contrasena_no_se_inventaria_como_hoja_en_blanco(tmp_path):
    ruta = _pdf(tmp_path / "x.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="a", owner_pw="b")
    with pytest.raises(PdfQueNoSeAbre, match="contraseña"):
        PyMuPDFPageSource(ruta, "acta.pdf")


def test_que_ya_no_esta(tmp_path):
    with pytest.raises(PdfQueNoSeAbre, match="ya no está"):
        PyMuPDFPageSource(tmp_path / "no-existe.pdf", "acta.pdf")


def test_uno_sano_se_abre(tmp_path):
    fuente = PyMuPDFPageSource(_pdf(tmp_path / "x.pdf"), "acta.pdf")
    try:
        assert fuente.page_count == 1
    finally:
        fuente.close()


def test_el_mensaje_va_sin_el_nombre_de_la_clase():
    assert PdfQueNoSeAbre("x").para_el_operador
