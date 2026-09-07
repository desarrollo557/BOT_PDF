"""Dónde termina un documento y empieza el siguiente.

La secuencia de las páginas 3 a 8 de "UPD2366126.pdf" es el caso que manda: el
papel declara "Página 1 de 5" hasta "Página 5 de 5" y después empieza otra cosa.
Ese documento no necesita modelo — lo resuelve la aritmética. Lo que sí lo
necesita son las 63 páginas de esa caja que no traen ninguna marca.
"""

import pytest

from resolutions.domain.errors import IntegrityError
from resolutions.domain.fingerprint import PageFingerprint, Pagination
from resolutions.domain.segmentation import (
    Verdict,
    assemble,
    decide_boundaries,
)


def huella(
    page_number: int,
    *,
    pagination: tuple[int, int] | None = None,
    serial: str | None = None,
    case_code: str | None = None,
    closes: bool = False,
    letterhead: bool = False,
    title: str | None = None,
    tail: str = "",
    place_and_date: str | None = None,
) -> PageFingerprint:
    return PageFingerprint(
        page_number=page_number,
        title=f"pagina {page_number}" if title is None else title,
        letterhead=letterhead,
        place_and_date=place_and_date,
        serial=serial,
        pagination=Pagination(*pagination) if pagination else None,
        case_code=case_code,
        closes=closes,
        tail=tail,
    )


def veredicto_entre(izquierda: PageFingerprint, derecha: PageFingerprint) -> Verdict:
    """El veredicto de la única costura entre dos huellas."""
    return decide_boundaries([izquierda, derecha])[0].verdict


def razon_entre(izquierda: PageFingerprint, derecha: PageFingerprint) -> str:
    return decide_boundaries([izquierda, derecha])[0].reason


#: Páginas 3 a 8 tal como salen del expediente real.
CAJA_REAL = [
    huella(3, pagination=(1, 5), serial="202170183712", case_code="RE3120202101650"),
    huella(4, pagination=(2, 5)),
    huella(5, pagination=(3, 5)),
    huella(6, pagination=(4, 5)),
    huella(7, pagination=(5, 5), closes=True, case_code="RE3120202101650"),
    huella(8, letterhead=True),
]


class TestLaPaginacionDecideSola:
    def test_una_cadena_consecutiva_continua(self):
        fronteras = decide_boundaries(CAJA_REAL)
        assert fronteras[0].verdict is Verdict.CONTINUES  # 3|4
        assert fronteras[1].verdict is Verdict.CONTINUES  # 4|5
        assert fronteras[2].verdict is Verdict.CONTINUES  # 5|6
        assert fronteras[3].verdict is Verdict.CONTINUES  # 6|7

    def test_la_pagina_uno_abre_documento(self):
        fronteras = decide_boundaries([huella(8), huella(9, pagination=(1, 3))])
        assert fronteras[0].verdict is Verdict.STARTS

    def test_llegar_al_total_cierra_el_documento(self):
        fronteras = decide_boundaries(CAJA_REAL)
        assert fronteras[4].verdict is Verdict.STARTS  # 7|8, tras 5 de 5

    def test_totales_distintos_no_encadenan(self):
        """`2 de 5` seguido de `3 de 4` son dos documentos, no uno."""
        fronteras = decide_boundaries([huella(1, pagination=(2, 5)), huella(2, pagination=(3, 4))])
        assert fronteras[0].verdict is Verdict.STARTS


class TestElConsecutivoDecideCuandoCambia:
    def test_dos_consecutivos_distintos_son_dos_documentos(self):
        fronteras = decide_boundaries(
            [huella(2, serial="A202170196624"), huella(3, serial="202170183712")]
        )
        assert fronteras[0].verdict is Verdict.STARTS

    def test_el_mismo_consecutivo_continua(self):
        fronteras = decide_boundaries(
            [huella(4, serial="202170183712"), huella(5, serial="202170183712")]
        )
        assert fronteras[0].verdict is Verdict.CONTINUES


class TestElCasoNoEsElDocumento:
    def test_compartir_el_numero_de_reclamacion_no_decide_nada(self):
        """El error que costó caro medir.

        Las 125 páginas del expediente comparten `RE3120202101650`. Si eso
        contara como continuidad, la caja entera saldría como un solo documento.
        """
        fronteras = decide_boundaries(
            [huella(1, case_code="RE3120202101650"), huella(2, case_code="RE3120202101650")]
        )
        assert fronteras[0].verdict is Verdict.UNDECIDED


class TestLoQueNadiePuedeDecidirQuedaMarcado:
    def test_sin_senales_la_frontera_es_dudosa(self):
        fronteras = decide_boundaries([huella(50), huella(51)])
        assert fronteras[0].verdict is Verdict.UNDECIDED

    def test_cada_frontera_dice_por_que(self):
        for frontera in decide_boundaries(CAJA_REAL):
            assert frontera.reason


class TestNingunaPaginaSePierde:
    def test_las_paginas_caen_en_un_solo_segmento(self):
        resultado = assemble(CAJA_REAL, decide_boundaries(CAJA_REAL))
        resultado.verify_integrity([h.page_number for h in CAJA_REAL])
        assert [segmento.page_numbers for segmento in resultado.segments] == [
            [3, 4, 5, 6, 7],
            [8],
        ]

    def test_una_pagina_repetida_se_denuncia(self):
        resultado = assemble(CAJA_REAL, decide_boundaries(CAJA_REAL))
        resultado.segments[0].page_numbers.append(8)
        with pytest.raises(IntegrityError):
            resultado.verify_integrity([h.page_number for h in CAJA_REAL])

    def test_un_documento_de_una_sola_pagina_es_valido(self):
        paginas = [huella(1, pagination=(1, 1)), huella(2, pagination=(1, 1))]
        resultado = assemble(paginas, decide_boundaries(paginas))
        assert [s.page_numbers for s in resultado.segments] == [[1], [2]]

    def test_sin_paginas_no_hay_segmentos(self):
        resultado = assemble([], [])
        assert resultado.segments == []


class TestLoQueQuedaParaElModelo:
    def test_solo_se_escalan_las_fronteras_dudosas(self):
        fronteras = decide_boundaries(CAJA_REAL)
        dudosas = [f for f in fronteras if f.verdict is Verdict.UNDECIDED]
        assert dudosas == []

    def test_una_caja_sin_marcas_escala_entera(self):
        paginas = [huella(n) for n in range(1, 6)]
        fronteras = decide_boundaries(paginas)
        assert all(f.verdict is Verdict.UNDECIDED for f in fronteras)
        assert len(fronteras) == 4


class TestLaOracionCortadaContinua:
    """La señal más fuerte que la estructura tiene gratis, y no se usaba.

    Una hoja que termina a media oración y otra que arranca en minúscula son la
    misma frase partida por el escáner. Estaba en la huella -- `tail` y `title`
    se calculan y se mandan al modelo -- y la capa gratuita las ignoraba, así que
    se pagaba un modelo por costuras que la aritmética del texto ya resolvía.

    La regla es deliberadamente estricta. Soldar dos documentos en uno esconde el
    segundo donde nadie lo va a buscar; partir uno en dos se repara en segundos.
    Ante cualquier señal de apertura en la hoja derecha, esta regla se calla.
    """

    def test_una_frase_cortada_y_retomada_en_minuscula_continua(self):
        izquierda = huella(10, tail="el usuario manifiesta que el consumo")
        derecha = huella(11, title="registrado no corresponde a su vivienda")
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

    def test_una_coma_al_final_tambien_corta_la_frase(self):
        izquierda = huella(10, tail="una vez revisado el medidor del inmueble,")
        derecha = huella(11, title="se encontro que la lectura registrada")
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

    def test_la_razon_dice_en_que_se_baso(self):
        izquierda = huella(10, tail="el usuario manifiesta que el consumo")
        derecha = huella(11, title="registrado no corresponde a su vivienda")
        assert "oración" in razon_entre(izquierda, derecha)

    def test_un_punto_final_no_alcanza_para_continuar(self):
        """Una oración terminada no dice nada: el documento pudo cerrar ahí."""
        izquierda = huella(10, tail="quedamos atentos a su respuesta.")
        derecha = huella(11, title="registrado no corresponde")
        assert veredicto_entre(izquierda, derecha) is Verdict.UNDECIDED

    def test_arrancar_en_mayuscula_no_es_continuar(self):
        izquierda = huella(10, tail="el usuario manifiesta que el consumo")
        derecha = huella(11, title="Solicitud de revision de medidor")
        assert veredicto_entre(izquierda, derecha) is Verdict.UNDECIDED

    def test_un_membrete_en_la_derecha_manda_a_callar_la_regla(self):
        """Un documento nuevo puede abrir con una minúscula en el membrete."""
        izquierda = huella(10, tail="el usuario manifiesta que el consumo")
        derecha = huella(11, title="registrado no corresponde", letterhead=True)
        assert veredicto_entre(izquierda, derecha) is Verdict.UNDECIDED

    def test_una_ciudad_y_fecha_en_la_derecha_tambien(self):
        izquierda = huella(10, tail="el usuario manifiesta que el consumo")
        derecha = huella(11, title="registrado no corresponde", place_and_date="Cartagena, 3 de marzo")
        assert veredicto_entre(izquierda, derecha) is Verdict.UNDECIDED

    def test_un_consecutivo_nuevo_en_la_derecha_tambien(self):
        izquierda = huella(10, tail="el usuario manifiesta que el consumo")
        derecha = huella(11, title="registrado no corresponde", serial="202170199999")
        assert veredicto_entre(izquierda, derecha) is Verdict.UNDECIDED

    def test_sin_cola_no_se_puede_decidir(self):
        izquierda = huella(10, tail="")
        derecha = huella(11, title="registrado no corresponde")
        assert veredicto_entre(izquierda, derecha) is Verdict.UNDECIDED

    def test_sin_titulo_tampoco(self):
        izquierda = huella(10, tail="el usuario manifiesta que el consumo")
        derecha = huella(11, title="")
        assert veredicto_entre(izquierda, derecha) is Verdict.UNDECIDED

    def test_un_titulo_que_no_empieza_con_letra_no_decide(self):
        """Un número o un guion no dicen si la frase venía cortada."""
        izquierda = huella(10, tail="el usuario manifiesta que el consumo")
        derecha = huella(11, title="-------- 12345 --------")
        assert veredicto_entre(izquierda, derecha) is Verdict.UNDECIDED


    def test_un_rotulo_corto_no_es_una_oracion_cortada(self):
        """El caso que detectó la suite: tres anexos sueltos, uno por hoja.

        "anexo uno" termina en letra y "anexo dos" empieza en minúscula, así que
        una regla floja los solda. Son dos documentos distintos y tienen que
        seguir dudosos, que es lo que la caja real pide.
        """
        assert veredicto_entre(huella(1, tail="anexo uno", title="anexo uno"),
                               huella(2, title="anexo dos")) is Verdict.UNDECIDED

    def test_una_cola_de_pocas_palabras_no_alcanza(self):
        izquierda = huella(10, tail="total a pagar")
        derecha = huella(11, title="mas intereses de mora causados")
        assert veredicto_entre(izquierda, derecha) is Verdict.UNDECIDED

    def test_un_arranque_de_pocas_palabras_tampoco(self):
        izquierda = huella(10, tail="el usuario manifiesta que el consumo")
        derecha = huella(11, title="registrado alto")
        assert veredicto_entre(izquierda, derecha) is Verdict.UNDECIDED

    def test_la_paginacion_sigue_mandando_sobre_esta_regla(self):
        """La aritmética del papel es evidencia más fuerte que la tipografía."""
        izquierda = huella(10, tail="el usuario manifiesta que el consumo")
        derecha = huella(11, title="registrado no corresponde a su vivienda", pagination=(1, 3))
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS


class TestLaDespedidaSeguidaDeUnaAperturaAbre:
    """Un documento que se despidió y otro que abre con membrete son dos.

    `closes` ya se calculaba y también se ignoraba. Es la contracara de la regla
    anterior: acá la evidencia empuja a cortar, que es el lado seguro del error.
    """

    def test_despedida_y_membrete_abren_documento(self):
        izquierda = huella(10, closes=True)
        derecha = huella(11, letterhead=True)
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS

    def test_despedida_y_ciudad_con_fecha_tambien(self):
        izquierda = huella(10, closes=True)
        derecha = huella(11, place_and_date="Cartagena, 3 de marzo de 2021")
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS

    def test_la_razon_nombra_las_dos_señales(self):
        razon = razon_entre(huella(10, closes=True), huella(11, letterhead=True))
        assert "despide" in razon or "despedida" in razon

    def test_una_despedida_sola_no_alcanza(self):
        """Un anexo puede seguir a la firma sin abrir nada nuevo."""
        assert veredicto_entre(huella(10, closes=True), huella(11)) is Verdict.UNDECIDED

    def test_un_membrete_solo_no_alcanza(self):
        """Muchas hojas de continuación repiten el membrete en cada página."""
        assert veredicto_entre(huella(10), huella(11, letterhead=True)) is Verdict.UNDECIDED

    def test_el_consecutivo_sigue_mandando_sobre_esta_regla(self):
        izquierda = huella(10, closes=True, serial="202170183712")
        derecha = huella(11, letterhead=True, serial="202170183712")
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES
