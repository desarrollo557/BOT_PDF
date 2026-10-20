"""La territorial del Índice Electrónico, leída de la ruta de la caja en el repositorio.

Lo pidió el operador el 2026-10-20 con la ruta real
\\\\200.100.20.97\\afinia\\REPOSITORIO\\AFINIA\\BOLIVAR SUR\\COMERCIAL.
"""

from __future__ import annotations

import pytest

from resolutions.domain.territorial import territorial_de_la_ruta


@pytest.mark.parametrize(
    ("ruta", "territorial"),
    [
        (r"\\200.100.20.97\afinia\REPOSITORIO\AFINIA\BOLIVAR SUR\COMERCIAL\MOMPOX\108C000534\UPD2452915.pdf", "BOLIVAR SUR"),
        (r"\\200.100.20.97\afinia\REPOSITORIO\AFINIA\BOLIVAR SUR\COMERCIAL\MAGANGUE\1000183\UPD2437814.pdf", "BOLIVAR SUR"),
        (r"\\200.100.20.97\afinia\REPOSITORIO\AFINIA\CORDOBA\OTRAS OFICINAS\MONTERIA\108C000001\UPD1.pdf", "CORDOBA"),
        (r"Z:\REPOSITORIO\AFINIA\CESAR\COMERCIAL\VALLEDUPAR\108C000777\UPD9.pdf", "CESAR"),
        # Dentro de Docker, montada en /equipo/<letra>.
        ("/equipo/z/REPOSITORIO/AFINIA/SUCRE/COMERCIAL/SINCELEJO/108C000002/UPD3.pdf", "SUCRE"),
        # Una copia local que conserva la estructura, sin la raíz AFINIA.
        (r"C:\Users\ana\Desktop\CAJAS\BOLIVAR NORTE\COMERCIAL\TURBACO\108C000003\UPD4.pdf", "BOLIVAR NORTE"),
        # En minúsculas también.
        (r"z:\repositorio\afinia\bolivar sur\comercial\mompox\108c000534\upd2452915.pdf", "BOLIVAR SUR"),
    ],
)
def test_la_territorial_sale_de_la_ruta(ruta, territorial):
    assert territorial_de_la_ruta(ruta) == territorial


@pytest.mark.parametrize(
    "ruta",
    [
        # Una caja que cuelga directamente de la raíz no tiene territorial.
        r"\\200.100.20.97\afinia\REPOSITORIO\AFINIA\108C003007\UPD3501095.pdf",
        # Un archivo subido suelto.
        r"C:\BOT_PDF\data\uploads\3f2a.pdf",
        "",
    ],
)
def test_si_la_ruta_no_la_dice_vale_la_escrita(ruta):
    assert territorial_de_la_ruta(ruta) is None
