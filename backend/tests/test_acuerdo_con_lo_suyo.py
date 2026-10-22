"""El acuerdo de pago se lleva lo que se firmó con él (el operador, 2026-10-22).

«La Ley Habeas Data siempre irá anexada a su respectivo reconocimiento de deuda
y propuesta de acuerdo de pago», «cada reconocimiento lleva sus documentos
anexados», y ante UPD3102729: «este documento parece ser uno solo». Ahí, la
autorización de Habeas Data va arriba, tres constancias de PQR de la misma
visita en medio -- facilidades de pago, cambio de datos básicos, gestionar
financiación --, y los dos pagarés con sus cartas y el reconocimiento al final.
"""

from __future__ import annotations

from resolutions.application.anexos_declarados import unir_el_acuerdo_de_pago
from resolutions.domain.asunto_del_documento import (
    causa_de_la_constancia,
    es_causa_del_acuerdo,
)
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode

HABEAS = "aFinia\n2 de abril de 2024\nSeñores\nCARIBEMAR\nASUNTO: Ley Habeas Data - NIC 1000265\nYo, Sandra C. Acosta Cogollo\n"


def _constancia(fecha: str, causa: str) -> str:
    return (
        "PARA LA EMPRESA\nRecibí constancia del contenido de la reclamación presentada ante CARIBEMAR\n"
        f"N° PQR: RE2310202406735\nFECHA: {fecha}\nCODIGO (NIC): 1000265\nCAUSA:\n{causa}\nSERVICIO: 11098\n"
    )


PAGARE = "CARIBEMAR DE LA COSTA S.A.S. ESP\nEMPRESA DE SERVICIOS PUBLICOS DOMICILIARIOS\nPAGARE No. 1000265 -2\n"
CARTA = "CARIBEMAR DE LA COSTA S.A.S. ESP\nCARTA DE INSTRUCCIONES ANEXA A PAGARE No. 1000265 2\n"
RECONOCIMIENTO = (
    "aFinia\nMagangué 2 de abril de 2024\nSeñores:\nCARIBE MAR DE LA COSTA S.A. E.S.P.\n"
    "Ref.: Reconocimiento de deuda y propuesta de acuerdo de pago.\n"
)
DERECHO_DE_PETICION = "Valledupar, 3 de mayo de 2024\nSeñores AFINIA\nREF: DERECHO DE PETICION\n"


def _grupos(*paginas: list[int]) -> GroupingResult:
    return GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=f"{i:02d}", raw=f"{i:02d}"), page_numbers=list(p))
            for i, p in enumerate(paginas, start=1)
        ]
    )


class TestLaCausa:
    def test_la_causa_de_la_constancia(self):
        assert causa_de_la_constancia(_constancia("02/04/2024", "Gestionar financiación")) == "GESTIONAR FINANCIACION"
        assert es_causa_del_acuerdo("Facilidades de pago")
        assert not es_causa_del_acuerdo("Daño medidor")


class TestElAcuerdoConLoSuyo:
    def test_upd3102729_es_un_solo_documento(self):
        textos = {
            1: HABEAS,
            2: _constancia("22/09/2023", "Facilidades de pago"),
            3: _constancia("02/04/2024", "Cambio de datos básicos"),
            4: _constancia("02/04/2024", "Gestionar financiación"),
            5: PAGARE,
            6: CARTA,
            7: RECONOCIMIENTO,
        }
        grupos, anexos, del_acuerdo = unir_el_acuerdo_de_pago(_grupos([1], [2], [3], [4], [5], [6], [7]), textos)
        assert [g.page_numbers for g in grupos.groups] == [[1, 2, 3, 4, 5, 6, 7]]
        assert grupos.groups[0].kind == "RECONOCIMIENTO DE DEUDA Y ACUERDO DE PAGO"
        assert del_acuerdo == {1, 2, 3, 4, 5, 6, 7}
        # Lo que no era pieza del acuerdo va como su anexo.
        assert set(anexos["01"]) >= {1, 2, 3, 4}

    def test_la_habeas_data_tambien_debajo(self):
        textos = {1: PAGARE, 2: RECONOCIMIENTO, 3: HABEAS}
        grupos, _, _ = unir_el_acuerdo_de_pago(_grupos([1], [2], [3]), textos)
        assert [g.page_numbers for g in grupos.groups] == [[1, 2, 3]]

    def test_otro_tramite_corta(self):
        """Una constancia de otra causa y de otro día es otro trámite, y lo de antes no se toca."""
        textos = {
            1: DERECHO_DE_PETICION,
            2: HABEAS,
            3: _constancia("15/01/2024", "Daño medidor"),
            4: PAGARE,
            5: RECONOCIMIENTO,
        }
        grupos, _, _ = unir_el_acuerdo_de_pago(_grupos([1], [2], [3], [4], [5]), textos)
        assert [g.page_numbers for g in grupos.groups] == [[1], [2], [3], [4, 5]]

    def test_lo_que_abre_corta(self):
        textos = {1: HABEAS, 2: PAGARE, 3: RECONOCIMIENTO}
        grupos, _, _ = unir_el_acuerdo_de_pago(_grupos([1], [2], [3]), textos, abren={1})
        assert [g.page_numbers for g in grupos.groups] == [[1], [2, 3]]


class TestLaFranjaDelTitulo:
    """UPD2998726: con el equipo ocupado, Tesseract se agotaba y el documento salía sin nombre."""

    class _Fuente:
        def render(self, pagina, banda, ppp, formato=None):
            from io import BytesIO

            from PIL import Image

            salida = BytesIO()
            Image.new("RGB", (400, 600), "white").save(salida, format="PNG")
            return salida.getvalue()

    class _Lector:
        def __init__(self, *respuestas):
            self.respuestas = list(respuestas)
            self.lecturas = 0

        def read(self, imagen):
            self.lecturas += 1
            respuesta = self.respuestas.pop(0)
            if isinstance(respuesta, Exception):
                raise respuesta

            class _R:
                text = respuesta

            return _R()

    def test_si_se_agota_se_intenta_otra_vez(self):
        from resolutions.api.worker.correspondencia import _titulo_del_encabezado

        lector = self._Lector(TimeoutError("Tesseract superó 15 s"), "FORMATO DE NUEVOS SUMINISTROS O SUMINISTROS MODIFICADOS")
        assert _titulo_del_encabezado(self._Fuente(), 1, lector) == "FORMATO DE NUEVOS SUMINISTROS O SUMINISTROS MODIFICADOS"

    def test_con_ia_la_lee_la_ia_si_el_de_casa_no_puede(self):
        from resolutions.api.worker.correspondencia import _titulo_del_encabezado

        lector = self._Lector(TimeoutError("1"), TimeoutError("2"))
        ia = self._Lector("FORMATO DE NUEVOS SUMINISTROS O SUMINISTROS MODIFICADOS")
        assert _titulo_del_encabezado(self._Fuente(), 1, lector, ia) == "FORMATO DE NUEVOS SUMINISTROS O SUMINISTROS MODIFICADOS"

    def test_si_leyo_y_no_hay_titulo_no_se_repite(self):
        from resolutions.api.worker.correspondencia import _titulo_del_encabezado

        lector = self._Lector("y * n lí í")
        assert _titulo_del_encabezado(self._Fuente(), 1, lector) is None
        assert lector.lecturas == 1
