"""La casilla «Territorial» del Índice Electrónico: el municipio, leído de la ruta.

Lo pidió el operador el 2026-10-20 con su caja real
C:\\Users\\desarrollo.SIAR\\Desktop\\PRUEBAS_BOT\\FUENTE\\MAGANGUE\\210847\\UPD2998726.pdf:
en «Territorial» va «MAGANGUE», la carpeta que contiene la caja.
"""

from __future__ import annotations

import pytest

from resolutions.domain.territorial import territorial_de_la_ruta


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
