"""La casilla «Territorial» del Índice Electrónico: el municipio, leído de la ruta.

Lo pidió el operador el 2026-10-20 con su caja real
C:\\Users\\desarrollo.SIAR\\Desktop\\PRUEBAS_BOT\\FUENTE\\MAGANGUE\\210847\\UPD2998726.pdf:
en «Territorial» va «MAGANGUE», la carpeta que contiene la caja.
"""

from __future__ import annotations

import pytest

from resolutions.domain.territorial import (
    nic_de_la_ruta,
    nombre_del_expediente,
    territorial_de_la_ruta,
)


class TestElEncabezadoDeLaCaja:
    """Lo fijó el operador con su planilla de UPD2998266 el 2026-10-20."""

    def test_el_nic_es_la_carpeta_de_la_caja(self):
        assert nic_de_la_ruta(r"C:\PRUEBAS_BOT\FUENTE\MAGANGUE\910349\UPD2998266.pdf") == "910349"
        assert nic_de_la_ruta("/equipo/c/FUENTE/MAGANGUE/210847/UPD2998726.pdf") == "210847"

    def test_una_caja_con_numero_de_caja_no_es_un_nic(self):
        assert nic_de_la_ruta(r"…\COMERCIAL\MOMPOX\108C000534\UPD2452915.pdf") is None
        assert nic_de_la_ruta(r"…\FUENTE\MAGANGUE\UPD2998266.pdf") is None
        assert nic_de_la_ruta("") is None

    def test_el_expediente_es_el_pdf_sin_la_carpeta(self):
        assert nombre_del_expediente("910349/UPD2998266.pdf") == "UPD2998266"
        assert nombre_del_expediente(r"910349\UPD2998266.pdf") == "UPD2998266"
        assert nombre_del_expediente("UPD2326399.pdf") == "UPD2326399"


@pytest.mark.parametrize(
    ("ruta", "municipio"),
    [
        # La caja de prueba del operador, fuera del repositorio.
        (r"C:\Users\desarrollo.SIAR\Desktop\PRUEBAS_BOT\FUENTE\MAGANGUE\210847\UPD2998726.pdf", "MAGANGUE"),
        # El repositorio de Afinia: territorial, área, municipio, caja.
        (r"\\200.100.20.97\afinia\REPOSITORIO\AFINIA\BOLIVAR SUR\COMERCIAL\MOMPOX\108C000534\UPD2452915.pdf", "MOMPOX"),
        (r"\\200.100.20.97\afinia\REPOSITORIO\AFINIA\BOLIVAR SUR\COMERCIAL\MAGANGUE\1000183\UPD2437814.pdf", "MAGANGUE"),
        (r"\\200.100.20.97\afinia\REPOSITORIO\AFINIA\CORDOBA\OTRAS OFICINAS\MONTERIA\108C000001\UPD1.pdf", "MONTERIA"),
        # Dentro de Docker, montada en /equipo/<letra>.
        ("/equipo/c/Users/desarrollo.SIAR/Desktop/PRUEBAS_BOT/FUENTE/MAGANGUE/210847/UPD2998726.pdf", "MAGANGUE"),
        # En minúsculas sale en mayúsculas, como el resto de la planilla.
        (r"z:\repositorio\afinia\bolivar sur\comercial\magangue\210847\upd2998726.pdf", "MAGANGUE"),
    ],
)
def test_la_territorial_es_el_municipio_de_la_ruta(ruta, municipio):
    assert territorial_de_la_ruta(ruta) == municipio


@pytest.mark.parametrize(
    "ruta",
    [
        # Una caja que cuelga directamente de la raíz o de un área no tiene municipio.
        r"\\200.100.20.97\afinia\REPOSITORIO\AFINIA\108C003007\UPD3501095.pdf",
        r"\\200.100.20.97\afinia\REPOSITORIO\AFINIA\CORDOBA\COMERCIAL\108C000001\UPD1.pdf",
        # Un PDF en la raíz de un disco.
        r"C:\caja\UPD1.pdf",
        "",
    ],
)
def test_si_la_ruta_no_lo_dice_vale_lo_escrito(ruta):
    assert territorial_de_la_ruta(ruta) is None
