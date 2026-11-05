"""Red o local, y la prueba de velocidad de lectura y de escritura (2026-11-05)."""

from __future__ import annotations

from resolutions.adapters import acceso

#: Lo que ve el contenedor del bot con «W:» montada por la red (``montar-unidad-de-red.ps1``).
MONTAJES = """overlay / overlay rw,relatime 0 0
C:\\134 /equipo/c 9p rw,dirsync,noatime 0 0
//200.100.20.101/Users/SIAR1/Desktop /equipo/w cifs rw,vers=3.0 0 0
//srv/datos /equipo/mi\\040carpeta cifs rw 0 0
"""


class TestRedOLocal:
    def test_la_unidad_montada_por_la_red_es_de_red(self):
        assert acceso.montada_por_la_red("/equipo/w/FOLIA-BOT/MAGANGUE PROCESADO", MONTAJES)

    def test_la_unidad_del_equipo_que_comparte_docker_es_local(self):
        assert not acceso.montada_por_la_red("/equipo/c/Users/SIAR1/Desktop/salida", MONTAJES)
        assert not acceso.montada_por_la_red("/datos/salida", MONTAJES)

    def test_manda_el_montaje_mas_largo_y_con_espacios(self):
        assert acceso.montada_por_la_red("/equipo/mi carpeta/x", MONTAJES)
        # «/equipo/wx» no está dentro de «/equipo/w».
        assert not acceso.montada_por_la_red("/equipo/wx/a", MONTAJES)

    def test_una_ruta_de_red_es_de_red_en_cualquier_sistema(self):
        assert acceso.es_de_red(r"\\200.100.20.97\afinia\REPOSITORIO")
        assert acceso.es_de_red("//200.100.20.97/afinia/REPOSITORIO")

    def test_una_carpeta_de_este_equipo_es_local(self, tmp_path):
        assert not acceso.es_de_red(tmp_path)


class TestLaPruebaDeVelocidad:
    def test_lee_la_muestra_y_no_mas(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"x" * 3_000_000)
        leidos, segundos = acceso.medir_lectura(pdf, tope=1_000_000)
        assert leidos == 1_000_000 and segundos >= 0

    def test_un_pdf_pequeno_se_lee_entero(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"x" * 1000)
        assert acceso.medir_lectura(pdf)[0] == 1000

    def test_escribe_y_no_deja_nada(self, tmp_path):
        escritos, segundos = acceso.medir_escritura(tmp_path, cuanto=2_500_000)
        assert escritos == 2_500_000 and segundos >= 0
        assert list(tmp_path.iterdir()) == []

    def test_no_crea_la_carpeta_si_no_esta(self, tmp_path):
        import pytest

        with pytest.raises(OSError):
            acceso.medir_escritura(tmp_path / "no-existe", cuanto=10)
        assert not (tmp_path / "no-existe").exists()
