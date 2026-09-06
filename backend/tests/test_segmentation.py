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
) -> PageFingerprint:
    return PageFingerprint(
        page_number=page_number,
        title=f"pagina {page_number}",
        letterhead=letterhead,
        place_and_date=None,
        serial=serial,
        pagination=Pagination(*pagination) if pagination else None,
        case_code=case_code,
        closes=closes,
        tail="",
    )


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
