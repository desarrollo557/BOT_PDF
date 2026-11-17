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


def test_el_mosaico_que_no_cuadra_se_relee_en_mosaicos_de_la_mitad(tmp_path):
    """INTERNADOS ROTATORIO 1978-1984 (2026-11-03): siete rótulos para ocho renglones y se perdían los ocho."""
    import pymupdf

    from resolutions.adapters.pymupdf_source import PyMuPDFPageSource
    from resolutions.domain.historia_medicina import FRANJA_DEL_PIE

    pdf = tmp_path / "notas.pdf"
    with pymupdf.open() as documento:
        for _ in range(4):
            documento.new_page()
        documento.save(pdf)
    respuestas = iter([
        # Las cuatro juntas: un rótulo de menos.
        "NOMBRE ARGOTA CAICEDO GABRIEL\nNOMBRE AMADOR ARIZA MARGARITA\nNOMBRE ALTAMAR COLON OSVALDO",
        # De a dos: cuadran.
        "NOMBRE ARGOTA CAICEDO GABRIEL\nNOMBRE AMADOR ARIZA MARGARITA",
        "NOMBRE ALTAMAR COLON OSVALDO\nNOMBRE CANTILLO FERRANS GREGORIO",
    ])
    leidas = []

    def leer(imagen):
        leidas.append(imagen)
        return next(respuestas)

    mosaico = MosaicoDeCampo(FRANJA_DEL_PIE, localizar=lambda *_: 0.9, leer=leer, tamano=4, lectores=1)
    leidos = mosaico.leer_franjas(PyMuPDFPageSource(pdf), [1, 2, 3, 4])
    assert len(leidas) == 3
    assert "CANTILLO FERRANS" in leidos[4] and "AMADOR ARIZA" in leidos[2]


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


def test_con_la_ia_cada_dato_se_cruza_y_lo_que_discrepa_va_a_revision():
    """«Que el bot se asegure de que lo que entrega sí es lo que está en el PDF» (2026-10-31)."""
    from resolutions.domain.doble_lectura import decidir_con_la_ia

    assert decidir_con_la_ia("la cédula", "1049539266", "1049539266", 1) == ("1049539266", None)
    assert decidir_con_la_ia("la cédula", None, "1049539266", 0) == ("1049539266", None)
    assert decidir_con_la_ia("la cédula", "1049539266", None, 1) == ("1049539266", None)
    # Discrepan: gana la IA, y a revisión con las dos lecturas.
    valor, nota = decidir_con_la_ia("la cédula", "1049539286", "1049539266", 1)
    assert valor == "1049539266" and "1049539286" in nota
    # Dos lecturas gratuitas que coinciden pesan más que la IA, pero también a revisión.
    valor, nota = decidir_con_la_ia("el número del acta", "016", "018", 2)
    assert valor == "016" and "018" in nota


# -- 2026-11-17: la ficha de Enfermería, con todos sus renglones ------------------------

#: Lo que contestó la IA al mosaico de las cédulas de ALVAREZ (pág. 1 del banco) y
#: CAMPO TORREGROZA (pág. 3), UPD3859718: una tabla con la etiqueta en la primera
#: columna y la cédula un renglón más abajo.
_MOSAICO_EN_TABLA = (
    "|  [1] | Bajo el folio del libro  |\n| --- | --- |\n"
    "|   |  Cédula o tarjeta No. Libreta Militar No.  |\n|   |  Nombre del acudiente (s)  |\n"
    "|   |  Dirección: Tel.  |\n|  [3] | Bajo el folio 119 del libro 24.  |\n"
    "|   |  Cédula o tarjeta No. C.C # 49.731.465 de Libreta Militar No.  |\n"
    "|   |  Nombre del acudiente (s) Ana Rolón calle 50 # 13-03 Torico Cortezema  |\n"
    "|   |  Dirección: la misma Tel.  |"
)


def test_el_mosaico_en_tabla_da_a_cada_franja_todos_sus_renglones():
    """Repartido por la celda de al lado de «[3]», la cédula 49.731.465 no llegaba nunca a votar."""
    mosaico = MosaicoDeCampo(FRANJA_DE_LA_CEDULA, leer=lambda imagen: "")
    trozos = mosaico._repartir_texto(_MOSAICO_EN_TABLA, [1, 3])
    assert leer_ficha(trozos[3]).cedula == "49731465"
    assert leer_ficha(trozos[1]).cedula is None
    # Lo de la franja de abajo no se cuela en la de arriba.
    assert "119" not in trozos[1]


def test_una_etiqueta_fuera_de_su_sitio_reparte_por_el_rotulo():
    """El proveedor cambia a veces la etiqueta (INTERNADOS ROTATORIO, 2026-11-03): manda el orden de los rótulos."""
    mosaico = MosaicoDeCampo(FRANJA_DE_LA_CEDULA, leer=lambda imagen: "")
    cambiado = _MOSAICO_EN_TABLA.replace("[1]", "[9]").replace("[3]", "[1]").replace("[9]", "[3]")
    trozos = mosaico._repartir_texto(cambiado, [1, 3])
    assert leer_ficha(trozos[3]).cedula == "49731465"
    assert leer_ficha(trozos[1]).cedula is None


def test_la_cedula_en_disputa_la_decide_una_tercera_mirada():
    """CAMPO TORREGROZA: la página leyó 49751465 y el renglón ampliado 49731465, que es lo que dice el papel."""
    from resolutions.domain.doble_lectura import desempatar_numero

    assert desempatar_numero("49751465", "49751465", None, "la cédula") == ("49751465", None, None)
    # Otra mirada del renglón dice lo mismo que el renglón: dos de tres.
    cedula, duda, nota = desempatar_numero("49751465", "49731465", "49731465", "la cédula")
    assert (cedula, duda) == ("49731465", None) and "49751465" in nota
    # Dice lo mismo que la página: vale la página.
    assert desempatar_numero("39011905", "39011903", "39011905", "la cédula") == ("39011905", None, None)
    # Tres lecturas distintas: la de la página, a revisión con las tres.
    cedula, duda, nota = desempatar_numero("49751465", "49731465", "49731965", "la cédula")
    assert cedula == "49751465" and nota is None and "49731965" in duda


def test_el_renglon_del_nombre_es_el_de_encima_de_la_direccion(monkeypatch):
    """ALVAREZ LONDOÑO (UPD3859718, pág. 3): Tesseract leyó «MBRE» y el primer «NOMBRE» era el de los padres."""
    from resolutions.adapters import mosaico_de_nombres
    from resolutions.domain.historia_academica import FRANJA_DEL_NOMBRE

    palabras = [
        ("ENFERMERIA", 0.063), ("MBRE", 0.105), ("ESTUDIANTE", 0.105), ("DIRECCION", 0.124),
        ("NOMBRE", 0.217), ("PADRES", 0.218), ("DIRECCION:", 0.241),
    ]
    monkeypatch.setattr(mosaico_de_nombres, "_palabras_de", lambda source, pagina, dpi: palabras)
    localizar = mosaico_de_nombres.ubicar_encima_de(FRANJA_DEL_NOMBRE.encima_de)
    assert localizar(None, 3, FRANJA_DEL_NOMBRE.leyendas) == 0.105
    # Antes: la primera «NOMBRE» de la hoja.
    assert mosaico_de_nombres.ubicar_con_tesseract(None, 3, ("NOMBRE",)) == 0.217
    # Sin rótulo cerca de la dirección, ninguno: hereda la altura de las demás fichas.
    monkeypatch.setattr(mosaico_de_nombres, "_palabras_de", lambda source, pagina, dpi: palabras[3:])
    assert localizar(None, 3, FRANJA_DEL_NOMBRE.leyendas) is None
