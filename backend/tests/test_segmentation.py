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
    _ubiquitous,
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
    opening: tuple[str, ...] = (),
    label: str | None = None,
    ordinals: tuple[int, ...] = (),
    invoice: bool = False,
    identifiers: frozenset[tuple[str, str]] = frozenset(),
    legible: bool = True,
    folio: int | None = None,
    sheet: tuple[int, int] | None = None,
    announces_attachments: bool = False,
    is_attachment: bool = False,
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
        opening=opening,
        label=label,
        ordinals=ordinals,
        invoice=invoice,
        identifiers=identifiers,
        legible=legible,
        folio=folio,
        sheet=sheet,
        announces_attachments=announces_attachments,
        is_attachment=is_attachment,
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

    def test_totales_distintos_no_encadenan_pero_tampoco_cortan(self):
        """`2 de 5` seguido de `3 de 4` no forman cadena, y aun así no se parten.

        La cadena necesita el mismo total; sin él, esto deja de ser una prueba de
        continuidad. Pero tampoco es una de apertura: una hoja que se declara
        tercera no empieza nada, y en el expediente medido ese desacuerdo entre
        totales lo había puesto el escáner. Para cortar hace falta que la hoja
        derecha diga ser la primera.
        """
        fronteras = decide_boundaries([huella(1, pagination=(2, 5)), huella(2, pagination=(3, 4))])
        assert fronteras[0].verdict is Verdict.CONTINUES
        assert decide_boundaries(
            [huella(1, pagination=(2, 5)), huella(2, pagination=(1, 4))]
        )[0].verdict is Verdict.STARTS


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

    def test_un_membrete_en_la_derecha_ya_no_manda_a_callar_la_regla(self):
        """Porque no distingue nada: lo lleva el 89 % del papel de una caja.

        Cuando esta prueba fijaba lo contrario, la caja medida dejaba sin decidir
        frases partidas evidentes -- "…de la empresa llegan son un sus una no" /
        "dueños del predio, manipulan el medidor…" -- por llevar la segunda hoja
        el mismo logo que las ciento diez restantes.
        """
        izquierda = huella(10, tail="el usuario manifiesta que el consumo")
        derecha = huella(11, title="registrado no corresponde", letterhead=True)
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

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


class TestLaHojaQueSeDeclaraContinuacion:
    """El reverso de "se declara página 1", y hacía falta.

    Un acta de irregularidad repite su propio rótulo en las cuatro hojas. Sin
    esta regla, la regla del rótulo leía cuatro actas donde había una.
    """

    def test_una_hoja_que_dice_ser_la_segunda_no_abre_nada(self):
        izquierda = huella(12, label="acta de irregularidad")
        derecha = huella(13, pagination=(2, 4), label="acta de irregularidad")
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

    def test_y_lo_dice_aunque_la_anterior_no_lleve_paginacion(self):
        assert "página 2 de 4" in razon_entre(
            huella(12), huella(13, pagination=(2, 4))
        )

    def test_una_que_dice_ser_la_primera_sigue_abriendo(self):
        assert veredicto_entre(huella(2), huella(3, pagination=(1, 5))) is Verdict.STARTS


class TestLaNumeracionOrdinalDelEscrito:
    """PRIMERO, SEGUNDO, TERCERO: un escrito que se cuenta a sí mismo.

    Once costuras de "UPD2366126.pdf" no traen membrete, ni consecutivo, ni
    paginación — sólo la numeración de sus párrafos, que sigue creciendo de una
    hoja a la siguiente.
    """

    def test_la_numeracion_que_crece_es_el_mismo_escrito(self):
        izquierda = huella(108, ordinals=(7, 8))
        derecha = huella(109, ordinals=(9,))
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

    def test_la_razon_nombra_los_dos_numeros(self):
        assert razon_entre(huella(108, ordinals=(8,)), huella(109, ordinals=(9,))) == (
            "la numeración sigue en 9 tras el 8"
        )

    def test_una_numeracion_que_vuelve_a_empezar_no_prueba_continuidad(self):
        """Un escrito nuevo que arranca en PRIMERO detrás de otro que iba por el OCTAVO."""
        izquierda = huella(1, ordinals=(7, 8))
        derecha = huella(2, ordinals=(1, 2))
        assert veredicto_entre(izquierda, derecha) is not Verdict.CONTINUES

    def test_sin_numeracion_en_alguno_de_los_dos_lados_se_abstiene(self):
        assert veredicto_entre(huella(1, ordinals=(3,)), huella(2)) is not Verdict.CONTINUES


class TestElPapelQueDiceSuNombre:
    def test_un_rotulo_reconocido_abre_documento(self):
        veredicto = veredicto_entre(huella(11), huella(12, label="acta de irregularidad"))
        assert veredicto is Verdict.STARTS

    def test_la_razon_cita_el_rotulo(self):
        assert razon_entre(huella(11), huella(12, label="constancia de visita")) == (
            "la hoja se titula «constancia de visita»"
        )


class TestLaCabeceraDeApertura:
    """Lo que sólo se imprime al abrir: destinatario, asunto, consecutivo, radicado.

    Medido contra las veintidós hojas de la caja que declaran su propia
    paginación: las seis que abren traen al menos una de estas marcas y las
    dieciséis de continuación no traen ninguna.
    """

    def test_una_cabecera_con_destinatario_abre(self):
        assert veredicto_entre(huella(50), huella(51, opening=("destinatario",))) is Verdict.STARTS

    def test_la_razon_dice_que_marcas_encontro(self):
        razon = razon_entre(huella(93), huella(94, opening=("consecutivo", "asunto")))
        assert razon == "la cabecera abre: consecutivo, asunto"

    def test_si_la_anterior_abrio_y_esta_no_abre_nada_es_su_cuerpo(self):
        izquierda = huella(101, opening=("destinatario",))
        derecha = huella(102)
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

    def test_esa_regla_no_se_aplica_si_ambas_abren(self):
        izquierda = huella(1, opening=("consecutivo",))
        derecha = huella(2, opening=("consecutivo",))
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS


class TestElCobroSuelto:
    """Una factura detrás de algo que no lo era: ¿anexo o documento aparte?

    Se decide por lo que comparten, y el código de expediente no cuenta: lo
    llevan las 125 páginas de la caja, así que usarlo une el expediente entero.
    """

    def test_un_cobro_que_comparte_identificador_es_anexo_de_la_anterior(self):
        izquierda = huella(37, identifiers=frozenset({("nic", "5826232")}))
        derecha = huella(38, invoice=True, identifiers=frozenset({("nic", "5826232")}))
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

    def test_un_cobro_sin_nada_en_comun_es_otro_documento(self):
        izquierda = huella(47, identifiers=frozenset({("nic", "5826232")}))
        derecha = huella(48, invoice=True, identifiers=frozenset({("nic", "9999999")}))
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS

    def test_un_cobro_detras_de_otro_cobro_no_dispara_esta_regla(self):
        """Dos hojas de la misma factura las resuelven las reglas de siempre."""
        izquierda = huella(1, invoice=True)
        derecha = huella(2, invoice=True)
        assert razon_entre(izquierda, derecha) != "un cobro sin nada en común con la hoja anterior"

    def test_el_codigo_de_expediente_no_cuenta_como_contexto_compartido(self):
        izquierda = huella(47, case_code="RE3120202101650")
        derecha = huella(48, invoice=True, case_code="RE3120202101650")
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS


class TestLaNumeracionImperfecta:
    """El OCR pierde hojas y estropea totales. Ninguna de las dos cosas parte nada.

    Medido: "2 de 3" seguido de "3 de 5" era el único falso corte que quedaba en
    el expediente, y el desacuerdo entre los totales era del escáner -- el mismo
    que convierte "1 de 6" en "1 de o".
    """

    def test_un_hueco_en_la_cuenta_no_rompe_el_documento(self):
        izquierda = huella(2, pagination=(2, 5))
        derecha = huella(3, pagination=(4, 5))
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

    def test_la_razon_dice_que_hubo_un_salto(self):
        razon = razon_entre(huella(2, pagination=(2, 5)), huella(3, pagination=(4, 5)))
        assert razon == "la cuenta salta de 2 a 4 de 5"

    def test_un_total_distinto_no_abre_si_la_hoja_no_se_dice_primera(self):
        izquierda = huella(10, pagination=(2, 3))
        derecha = huella(11, pagination=(3, 5))
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

    def test_un_total_distinto_si_abre_cuando_la_hoja_se_dice_primera(self):
        izquierda = huella(10, pagination=(2, 3))
        derecha = huella(11, pagination=(1, 5))
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS

    def test_una_cuenta_que_retrocede_tampoco_corta_por_si_sola(self):
        """Nadie numera hacia atrás, pero el OCR sí confunde dígitos.

        Y la hoja sigue diciendo que es la segunda de algo, que es lo contrario
        de abrir. Se prefiere unir y declararlo antes que partir por una lectura
        que el escáner pudo haber inventado.
        """
        izquierda = huella(4, pagination=(4, 5))
        derecha = huella(5, pagination=(2, 5))
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES


class TestLaHojaQueNoSePudoLeer:
    """Una fotografía, un sello, una capa de texto rota: ausencia de evidencia.

    Ni de apertura ni de continuidad. La hoja acaba unida al documento abierto
    -- ante la duda se une -- pero la costura queda DECLARADA, que es la única
    diferencia que importa: un escaneo entero sin capa de texto tiene que salir
    con todas sus costuras en la cola de revisión, no con un informe que dice
    que el papel las decidió todas.
    """

    def test_una_hoja_ilegible_no_decide_nada(self):
        assert veredicto_entre(huella(90), huella(91, legible=False)) is Verdict.UNDECIDED

    def test_una_caja_sin_capa_de_texto_va_entera_a_revision(self):
        """La regresión. Con "no legible" como CONTINUES, esto salía como un
        documento de diez hojas y la cola de revisión vacía: el informe afirmaba
        que la estructura había resuelto nueve costuras que nadie miró."""
        paginas = [huella(n, legible=False, sheet=(614, 792)) for n in range(1, 11)]
        resultado = assemble(paginas, decide_boundaries(paginas))
        assert [s.page_numbers for s in resultado.segments] == [list(range(1, 11))]
        assert len(resultado.undecided) == 9

    def test_pero_una_hoja_ilegible_que_se_declara_primera_si_abre(self):
        """La paginación manda: si la hoja dice "1 de 3", eso sí se leyó."""
        derecha = huella(91, legible=False, pagination=(1, 3))
        assert veredicto_entre(huella(90), derecha) is Verdict.STARTS


class TestLosAnexos:
    """Un anexo pertenece al documento que lo trae, no es un documento aparte."""

    def test_una_hoja_que_se_presenta_como_anexo_se_queda_con_la_anterior(self):
        veredicto = veredicto_entre(huella(73), huella(74, is_attachment=True))
        assert veredicto is Verdict.ATTACHMENT

    def test_lo_que_la_anterior_anuncia_se_le_atribuye(self):
        izquierda = huella(18, announces_attachments=True)
        derecha = huella(19)
        assert veredicto_entre(izquierda, derecha) is Verdict.ATTACHMENT

    def test_pero_no_se_traga_algo_que_abre_por_su_cuenta(self):
        izquierda = huella(18, announces_attachments=True)
        derecha = huella(19, opening=("consecutivo",))
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS

    def test_ni_algo_que_lleva_su_propio_nombre(self):
        izquierda = huella(18, announces_attachments=True)
        derecha = huella(19, label="cedula de ciudadania")
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS

    def test_el_anexo_queda_dentro_del_documento_y_anotado(self):
        paginas = [
            huella(1, announces_attachments=True),
            huella(2, is_attachment=True),
            huella(3, is_attachment=True),
        ]
        resultado = assemble(paginas, decide_boundaries(paginas))
        assert [s.page_numbers for s in resultado.segments] == [[1, 2, 3]]
        assert resultado.segments[0].attachment_pages == [2, 3]

    def test_un_acta_con_fotos_es_un_documento_y_no_cinco(self):
        """El caso del §13: acta de dos hojas más tres fotografías anunciadas."""
        paginas = [
            huella(1, label="acta de irregularidad"),
            # La última hoja del cuerpo cierra la cuenta y, en el mismo pie,
            # enumera lo que adjunta. Sin ese anuncio el acta habría terminado.
            huella(2, pagination=(2, 2), announces_attachments=True),
            huella(3, is_attachment=True),
            huella(4, legible=False),
            huella(5, legible=False),
        ]
        resultado = assemble(paginas, decide_boundaries(paginas))
        assert [s.page_numbers for s in resultado.segments] == [[1, 2, 3, 4, 5]]


class TestAnteLaDudaSeUne:
    """La política, fijada por una prueba para que no se cambie sin querer.

    Se decidió con la caja medida delante: unir en la duda deja el documento
    mayor en seis páginas y baja los de una sola hoja de 64 a 34. Partir una
    unidad documental no deja rastro de que existió; unir de más deja una hoja
    señalada en la cola de revisión.
    """

    def test_una_costura_sin_evidencia_mantiene_la_hoja_donde_estaba(self):
        paginas = [huella(n) for n in range(1, 5)]
        resultado = assemble(paginas, decide_boundaries(paginas))
        assert [s.page_numbers for s in resultado.segments] == [[1, 2, 3, 4]]

    def test_pero_la_duda_sigue_declarada_para_que_alguien_la_mire(self):
        paginas = [huella(n) for n in range(1, 5)]
        resultado = assemble(paginas, decide_boundaries(paginas))
        assert len(resultado.undecided) == 3

    def test_una_apertura_probada_si_corta(self):
        paginas = [huella(1), huella(2, pagination=(1, 2))]
        resultado = assemble(paginas, decide_boundaries(paginas))
        assert [s.page_numbers for s in resultado.segments] == [[1], [2]]


class TestElTamanoDeLaHoja:
    """Un cambio de tamaño de papel es un cambio de lote de escaneo.

    Es la única señal de la huella que no sale del texto, así que decide hojas
    que el OCR dejó mudas. Medida sobre la caja real: ocho cambios en 125 hojas,
    ninguno en contra de la paginación que el papel declara.
    """

    def test_un_papel_distinto_abre_documento(self):
        izquierda = huella(17, sheet=(614, 794))
        derecha = huella(18, sheet=(615, 937))
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS

    def test_la_razon_da_las_dos_medidas(self):
        razon = razon_entre(huella(17, sheet=(614, 794)), huella(18, sheet=(615, 937)))
        assert razon == "cambia el tamaño de la hoja (614x794 a 615x937)"

    def test_el_temblor_del_alimentador_no_es_un_documento_nuevo(self):
        """614x790 y 616x795 son la misma bandeja, no dos legajos."""
        izquierda = huella(1, sheet=(614, 790))
        derecha = huella(2, sheet=(616, 795))
        assert veredicto_entre(izquierda, derecha) is not Verdict.STARTS

    def test_una_fuente_que_no_sabe_su_tamano_no_estorba(self):
        assert veredicto_entre(huella(1, sheet=(614, 794)), huella(2)) is Verdict.UNDECIDED

    def test_el_papel_no_gana_a_su_propia_paginacion(self):
        """Un anexo en otro formato dentro de un documento que se cuenta solo."""
        izquierda = huella(1, pagination=(1, 3), sheet=(614, 794))
        derecha = huella(2, pagination=(2, 3), sheet=(615, 937))
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

    def test_ni_a_los_anexos_que_el_documento_anuncio(self):
        izquierda = huella(1, announces_attachments=True, sheet=(614, 794))
        derecha = huella(2, sheet=(615, 937))
        assert veredicto_entre(izquierda, derecha) is Verdict.ATTACHMENT


class TestElIdentificadorQueCambia:
    """Tres facturas seguidas con el encabezado ilegible y el NIC intacto.

    Es el caso de las páginas 26 a 28 de la caja: `nic 5826232254`,
    `nic 5826232252` y `nic 5826232253`. Nada más se podía leer en ellas.
    """

    def test_dos_hojas_sin_ningun_identificador_en_comun_son_dos_asuntos(self):
        izquierda = huella(27, identifiers=frozenset({("nic", "5826232252")}))
        derecha = huella(28, identifiers=frozenset({("nic", "5826232253")}))
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS

    def test_la_razon_nombra_la_clase_que_cambio(self):
        razon = razon_entre(
            huella(27, identifiers=frozenset({("nic", "1")})),
            huella(28, identifiers=frozenset({("nic", "2")})),
        )
        assert razon == "cambia el identificador (nic)"

    def test_compartir_uno_basta_para_no_partir(self):
        """Una hoja puede citar varios números; con que uno coincida, es el mismo asunto."""
        izquierda = huella(1, identifiers=frozenset({("nic", "58"), ("factura", "31")}))
        derecha = huella(2, identifiers=frozenset({("nic", "58"), ("factura", "99")}))
        assert veredicto_entre(izquierda, derecha) is not Verdict.STARTS

    def test_una_hoja_muda_no_contradice_a_la_otra(self):
        """El silencio no es desacuerdo: hace falta la misma clase en ambas."""
        izquierda = huella(1, identifiers=frozenset({("nic", "58")}))
        derecha = huella(2, identifiers=frozenset())
        assert veredicto_entre(izquierda, derecha) is not Verdict.STARTS

    def test_clases_distintas_tampoco_se_contradicen(self):
        izquierda = huella(1, identifiers=frozenset({("nic", "58")}))
        derecha = huella(2, identifiers=frozenset({("factura", "31")}))
        assert veredicto_entre(izquierda, derecha) is not Verdict.STARTS

    def test_el_codigo_de_expediente_sigue_sin_contar(self):
        """Lo llevan las 125 hojas de la caja; usarlo aquí no partiría nunca nada."""
        izquierda = huella(1, case_code="RE3120202101650")
        derecha = huella(2, case_code="RE3120202101999")
        assert veredicto_entre(izquierda, derecha) is Verdict.UNDECIDED


class TestLaCadenaDelFolio:
    """Un folio vale por su cadena con el vecino, nunca suelto.

    Medido sobre la caja real: veintinueve costuras encadenadas, ninguna en
    contra de la paginación impresa, y el ruido de la cola de revisión bajó de
    diecisiete costuras a ocho.
    """

    def test_el_folio_que_sigue_es_la_misma_pieza_de_papel(self):
        assert veredicto_entre(huella(41, folio=3), huella(42, folio=4)) is Verdict.CONTINUES

    def test_la_razon_da_los_dos_numeros(self):
        assert razon_entre(huella(41, folio=3), huella(42, folio=4)) == (
            "el folio sigue en 4 tras el 3"
        )

    def test_un_folio_que_no_encadena_no_dice_nada(self):
        """Dos cifras sueltas que se parecen no son una numeración."""
        assert veredicto_entre(huella(1, folio=3), huella(2, folio=9)) is Verdict.UNDECIDED

    def test_un_folio_que_vuelve_a_empezar_tampoco_lo_decide_esta_regla(self):
        assert veredicto_entre(huella(1, folio=4), huella(2, folio=1)) is Verdict.UNDECIDED

    def test_hace_falta_folio_en_las_dos_hojas(self):
        assert veredicto_entre(huella(1, folio=3), huella(2)) is Verdict.UNDECIDED
        assert veredicto_entre(huella(1), huella(2, folio=4)) is Verdict.UNDECIDED

    def test_el_folio_cero_es_un_folio(self):
        """Y no un valor ausente: `if left.folio` lo habría descartado."""
        assert veredicto_entre(huella(1, folio=0), huella(2, folio=1)) is Verdict.CONTINUES

    def test_la_paginacion_impresa_manda_sobre_el_folio(self):
        """El papel que se cuenta a sí mismo gana a la numeración de quien lo archiva."""
        izquierda = huella(1, pagination=(2, 2), folio=3)
        derecha = huella(2, pagination=(1, 4), folio=4)
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS


class TestElFolioNoManda:
    """La regresión del folio: en media Colombia se folia el expediente entero.

    Ahí `folio + 1` es cierto también en la frontera entre dos documentos, así
    que por encima del consecutivo, del rótulo o de la cabecera soldaría la caja
    -- el mismo modo de fallo por el que el código de expediente no decide nada.
    """

    def test_un_consecutivo_que_cambia_gana_al_folio_que_sigue(self):
        izquierda = huella(1, serial="A202170196624", folio=30, closes=True)
        derecha = huella(2, serial="PA202170210656", folio=31, letterhead=True)
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS
        assert razon_entre(izquierda, derecha) == "cambia el consecutivo"

    def test_un_rotulo_gana_al_folio_que_sigue(self):
        izquierda = huella(1, folio=30)
        derecha = huella(2, folio=31, label="cedula de ciudadania")
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS

    def test_una_cabecera_de_apertura_gana_al_folio_que_sigue(self):
        izquierda = huella(1, folio=30)
        derecha = huella(2, folio=31, opening=("consecutivo", "asunto"))
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS

    def test_pero_donde_nadie_mas_habla_el_folio_decide(self):
        assert veredicto_entre(huella(1, folio=30), huella(2, folio=31)) is Verdict.CONTINUES


class TestElAnuncioDeAnexosNoSeCreeUnaPalabraSuelta:
    """La regresión del anuncio: "pruebas" y "soportes" son prosa jurídica.

    Leerlas como anuncio desactivaba la regla de que un documento que agotó su
    propia paginación ha terminado, y lo pegaba al siguiente.
    """

    def test_una_resolucion_que_valora_pruebas_no_anuncia_anexos(self):
        from resolutions.domain.fingerprint import fingerprint_page

        cola = "Valoradas las pruebas obrantes en el expediente. Cordialmente,"
        assert fingerprint_page(3, "x" * 200 + cola).announces_attachments is False

    def test_y_por_eso_sigue_cerrando_donde_su_cuenta_se_agota(self):
        izquierda = huella(3, pagination=(3, 3), announces_attachments=False)
        derecha = huella(4, title="Registro fotográfico del predio")
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS
        assert razon_entre(izquierda, derecha) == "la anterior cerró en 3 de 3"

    def test_el_anuncio_de_verdad_se_sigue_leyendo(self):
        from resolutions.domain.fingerprint import fingerprint_page

        cola = "Se anexan los siguientes documentos adjuntos al presente escrito."
        assert fingerprint_page(3, "x" * 200 + cola).announces_attachments is True


class TestUnaCosturaQueFaltaNoEsUnaDuda:
    """`assemble` acepta cualquier lista de costuras, incluida una incompleta."""

    def test_sin_veredicto_para_una_costura_se_corta_y_se_dice(self):
        paginas = [huella(1), huella(2), huella(3)]
        fronteras = decide_boundaries(paginas)
        resultado = assemble(paginas, fronteras[:1])
        assert [s.page_numbers for s in resultado.segments] == [[1, 2], [3]]
        assert resultado.segments[-1].reason == "sin veredicto para esta costura"


class TestElMembreteNoCallaLaOracionCortada:
    """El logo va impreso en todo el papel de la empresa: no distingue nada.

    Lo llevan 111 de las 125 hojas de la caja medida. Usarlo para silenciar la
    regla de la frase partida dejaba sin decidir continuaciones evidentes --
    prosa cortada a media frase que sigue en minúscula en la hoja siguiente.
    """

    def test_la_frase_partida_se_lee_aunque_haya_membrete(self):
        izquierda = huella(19, tail="de la empresa llegan son un sus una no")
        derecha = huella(20, letterhead=True, title="dueños del predio, manipulan el medidor")
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

    def test_pero_una_marca_de_apertura_si_la_calla(self):
        izquierda = huella(19, tail="de la empresa llegan son un sus una no")
        derecha = huella(20, opening=("consecutivo",), title="dueños del predio, manipulan")
        assert veredicto_entre(izquierda, derecha) is not Verdict.CONTINUES

    def test_y_un_rotulo_tambien(self):
        izquierda = huella(19, tail="de la empresa llegan son un sus una no")
        derecha = huella(20, label="acta de irregularidad", title="dueños del predio, manipulan")
        assert veredicto_entre(izquierda, derecha) is Verdict.STARTS


class TestElIdentificadorCompartidoUne:
    """El caso del recibo por delante y por detrás.

    Las páginas 36, 37 y 38 de la caja son un asunto y sus dos recibos, y lo que
    lo prueba no es el NIC -- ése lo llevan casi todas las hojas del expediente --
    sino el importe: "1.766.840" y "2.107.130" están impresos en las dos caras.
    """

    def test_dos_hojas_con_el_mismo_importe_son_la_misma_pieza(self):
        izquierda = huella(37, identifiers=frozenset({("importe", "1.766.840")}))
        derecha = huella(38, identifiers=frozenset({("importe", "1.766.840")}))
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

    def test_la_razon_dice_cual_comparten(self):
        izquierda = huella(37, identifiers=frozenset({("importe", "1.766.840")}))
        derecha = huella(38, identifiers=frozenset({("importe", "1.766.840")}))
        assert razon_entre(izquierda, derecha) == "las dos hojas llevan el mismo importe 1.766.840"

    def test_y_gana_al_rotulo_de_la_hoja_siguiente(self):
        """La 38 se titula «estado de cuenta» y aun así es el reverso de la 37."""
        izquierda = huella(37, identifiers=frozenset({("importe", "1.766.840")}))
        derecha = huella(38, label="estado de cuenta",
                         identifiers=frozenset({("importe", "1.766.840")}))
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES


class TestUnIdentificadorUbicuoNoIdentifica:
    """El NIC del suscriptor lo lleva casi todo el expediente: no distingue nada.

    Es el mismo motivo por el que el código de expediente no decide ninguna
    costura. Se mide dentro de su propia clase -- un NIC contra las hojas que
    llevan NIC -- porque si no, noventa hojas con importes diluirían la cuenta.
    """

    def test_el_valor_que_lleva_casi_toda_la_caja_se_descarta(self):
        paginas = [huella(n, identifiers=frozenset({("nic", "5826232")})) for n in range(1, 10)]
        paginas.append(huella(10, identifiers=frozenset({("nic", "9999999")})))
        assert _ubiquitous(paginas) == frozenset({("nic", "5826232")})

    def test_y_por_eso_no_une_dos_documentos_distintos(self):
        paginas = [huella(n, identifiers=frozenset({("nic", "5826232")})) for n in range(1, 10)]
        paginas[5] = huella(6, identifiers=frozenset({("nic", "5826232")}),
                            opening=("radicado",))
        fronteras = decide_boundaries(paginas)
        assert fronteras[4].verdict is Verdict.STARTS

    def test_un_valor_de_pocas_hojas_si_identifica(self):
        paginas = [huella(n) for n in range(1, 9)]
        paginas[6] = huella(7, identifiers=frozenset({("importe", "1.766.840")}))
        paginas[7] = huella(8, identifiers=frozenset({("importe", "1.766.840")}))
        assert ("importe", "1.766.840") not in _ubiquitous(paginas)
        assert decide_boundaries(paginas)[6].verdict is Verdict.CONTINUES

    def test_una_caja_sin_identificadores_no_descarta_nada(self):
        assert _ubiquitous([huella(1), huella(2)]) == frozenset()


class TestLaNumeracionEnCifras:
    """"5." al frente de un párrafo cuenta igual que "QUINTO:".

    La carta de instrucciones anexa al pagaré enumera sus cláusulas en cifras, y
    cuando su segunda hoja arranca en el punto 5 eso es lo único que dice que es
    la segunda hoja y no otra carta.
    """

    def test_la_lista_que_sigue_creciendo_es_el_mismo_escrito(self):
        izquierda = huella(49, ordinals=(1, 2, 3, 4))
        derecha = huella(50, ordinals=(5, 6))
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

    def test_una_cantidad_de_dinero_no_es_un_numeral_de_lista(self):
        from resolutions.domain.fingerprint import fingerprint_page

        assert fingerprint_page(1, "por la suma de 1.766.840 pesos").ordinals == ()

    def test_un_folio_suelto_tampoco(self):
        from resolutions.domain.fingerprint import fingerprint_page

        assert fingerprint_page(1, "7 ANEXOS Y PRUEBAS Todo lo sustentado").ordinals == ()


class TestLaNumeracionSeLeePorPosicion:
    """El contrato de transacción lleva dos numeraciones a la vez.

    Los considerandos en cifras -- "1.", "2.", "3.", "4." -- y las cláusulas en
    ordinales -- PRIMERO, SEGUNDO, TERCERO, CUARTO. La hoja del medio abre en el
    considerando cuarto y termina nombrando la cláusula tercera, así que su mayor
    no dice nada: lo que importa es dónde arranca contra dónde acabó la anterior.
    """

    def test_la_hoja_que_abre_donde_acabo_la_anterior_continua(self):
        izquierda = huella(53, ordinals=(1, 2, 3))
        derecha = huella(54, ordinals=(4, 1, 2, 3))
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES
        assert razon_entre(izquierda, derecha) == "la numeración sigue en 4 tras el 3"

    def test_y_la_siguiente_tambien_aunque_el_mayor_coincida(self):
        """La 54 tiene un 4 y la 55 empieza en 4: por máximos no encadenarían."""
        izquierda = huella(54, ordinals=(4, 1, 2, 3))
        derecha = huella(55, ordinals=(4,))
        assert veredicto_entre(izquierda, derecha) is Verdict.CONTINUES

    def test_una_numeracion_que_vuelve_a_empezar_sigue_sin_encadenar(self):
        izquierda = huella(1, ordinals=(1, 2, 3))
        derecha = huella(2, ordinals=(1, 2))
        assert veredicto_entre(izquierda, derecha) is not Verdict.CONTINUES

    def test_las_dos_familias_se_guardan_en_el_orden_de_la_hoja(self):
        from resolutions.domain.fingerprint import fingerprint_page

        texto = "4. Que el CLIENTE reconoce. PRIMERO: el objeto. SEGUNDO: el plazo."
        assert fingerprint_page(54, texto).ordinals == (4, 1, 2)
