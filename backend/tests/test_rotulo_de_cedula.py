"""Un número es una cédula sólo si su rótulo va justo a su izquierda (el operador, 2026-11-03)."""

from __future__ import annotations

import pytest

from resolutions.domain.rotulo_de_cedula import tiene_rotulo


@pytest.mark.parametrize(
    "izquierda",
    [
        "NOMBRE DEL ALUMNO RAMON VILLALOBOS LOPEZ CEDULA - TARJETA NO. ",
        "C. DE C. NO. ",
        "PORTADOR DE LA CEDULA DE CIUDADANIA N°. ",
        "CC # ",
        "C.C ",
        "T.I. ",
        "TARJETA DE IDENTIDAD NO: ",
        "TDE. IDENTI. NO. ",
        "TDE. IDENT. NO. ",
        "|  C. DE C. NO. | ",
        "|  CODULA - TARJETA NO. | ",
    ],
)
def test_con_su_rotulo(izquierda):
    assert tiene_rotulo(izquierda)


@pytest.mark.parametrize(
    "izquierda",
    [
        "FIRMA ",
        "PEREZ REYES NO ",
        "MATRICULA NO. ",
        "TEL. ",
        "CEDULA - TARJETA NO. EXPEDIDA EN CARTAGENA DIRECCION CALLE 30 ",
        "",
    ],
)
def test_sin_su_rotulo(izquierda):
    assert not tiene_rotulo(izquierda)
