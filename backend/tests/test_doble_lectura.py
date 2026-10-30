"""Dos lecturas de cada dato que identifica un documento (2026-10-30).

Los casos son de UPD3859718, leídos contra el papel: el renglón ampliado de la
cédula lee peor que la página entera, pero cada discrepancia señala una cifra
en riesgo, y va a revisión con las dos lecturas.
"""

from __future__ import annotations

from resolutions.adapters.mosaico_de_nombres import MosaicoDeCampo
from resolutions.domain.doble_lectura import conciliar_numero
from resolutions.domain.historia_academica import FRANJA_DE_LA_CEDULA, leer_ficha


def test_la_cedula_que_discrepa_va_a_revision_y_queda_la_de_la_pagina():
    assert conciliar_numero("49751465", "49751465", "la cédula") == ("49751465", None)
    assert conciliar_numero(None, "45459115", "la cédula") == ("45459115", None)
    # UPD3859718, pág. 49: el papel dice 39011905; el renglón ampliado leyó 39011903.
    cedula, duda = conciliar_numero("39011905", "39011903", "la cédula")
    assert cedula == "39011905" and "39011903" in duda


def test_el_mosaico_reparte_por_el_rotulo_de_cada_renglon():
    mosaico = MosaicoDeCampo(FRANJA_DE_LA_CEDULA, leer=lambda imagen: "")
    texto = (
        "Cédula o tarjeta No. CC 9'132.107 Magangué Libreta Militar No.\n"
        "Cédula o tarjeta No. 650609-03314 Libreta Militar No. C.C 45.474.260 c/gena"
    )
    trozos = mosaico._repartir_texto(texto, [1, 39])
    assert leer_ficha(trozos[1]).cedula == "9132107"
    assert (leer_ficha(trozos[39]).cedula, leer_ficha(trozos[39]).tarjeta) == ("45474260", "650609-03314")
    # Un rótulo de menos: nada, antes que dar el dato a otro estudiante.
    assert mosaico._repartir_texto(texto, [1, 39, 41]) == {}
