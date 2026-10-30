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


def test_el_nombre_se_vota_entre_la_pagina_y_sus_dos_zonas():
    """UPD3859718: la página dice «OLEA»; el renglón del nombre y Observaciones, OLGA."""
    from resolutions.domain.doble_lectura import votar_nombre

    assert votar_nombre("ALVAREZ LONDONO OLEA", ["OLGA ALVAREZ LONDONO", "ALVAREZ LONDONO OLGA"]) == (
        "ALVAREZ LONDONO OLGA", None,
    )
    # Dos de tres iguales: vale, con el orden de la página.
    assert votar_nombre("MERINO RHENALS CARMEN", ["CARMEN MERINO RHENALS", None]) == ("MERINO RHENALS CARMEN", None)
    # Una palabra en empate: desempata la lista de nombres conocidos.
    nombre, duda = votar_nombre("IANACHO RODRIGUEZ REGINA", ["REGINA CAMACHO RODRIGUEZ"], {"CAMACHO", "RODRIGUEZ", "REGINA"})
    assert (nombre, duda) == ("CAMACHO RODRIGUEZ REGINA", None)
    # Sin desempate: queda la página y va a revisión con las lecturas.
    nombre, duda = votar_nombre("MARTINEZ LAVARTE NANCY", ["NANCY MARTINEZ LARRARTE"], {"MARTINEZ", "NANCY"})
    assert nombre == "MARTINEZ LAVARTE NANCY" and "LARRARTE" in duda


def test_el_nombre_que_la_ficha_repite_bajo_observaciones():
    from resolutions.domain.historia_academica import nombre_de_observaciones

    conocidas = {"MERINO", "RHENALS", "CARMEN", "MUNOZ", "BARBOZA", "MARIA"}
    assert nombre_de_observaciones("| Observaciones | MERIÑO RHENALS CARMEN 1977-80", conocidas) == "MERINO RHENALS CARMEN"
    assert (
        nombre_de_observaciones("Observaciones\n\nMUÑOZ BARBOZA MARIA DEL CARMEN 1977-80", conocidas)
        == "MUNOZ BARBOZA MARIA DEL CARMEN"
    )
    # «Obtuvo el grado…» tiene forma de nombre y no lo es: la lista lo descarta.
    assert nombre_de_observaciones("Observaciones Obtuvo el grado 1964", conocidas) is None
