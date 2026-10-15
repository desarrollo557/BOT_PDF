"""El trámite completo: su RE aunque el sello llegue roto, y su detalle en el índice.

Los sellos salen de UPD2320043 tal como los deja la OCR. El índice, de lo que
el operador pidió al revisarlo: el expediente con su nombre, cada fila con su
número RE y, dentro, qué documentos junta el trámite con su título y su fecha.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

import pytest

from resolutions.application.agrupacion import PaginasLeidas, agrupar_por_tramite
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.tramites import (
    fecha_del_sello,
    lleva_sello_de_radicacion,
    radicado_del_sello,
)

SELLO_1 = (
    "CHi'lbciiiHv iJc lu rimtM S.A 5. 20210009PÍ37 AT CONTHSTAn C ÍTP, F.STF. "
    "NUMF.nORK3110202139039 i-olios: 3 AHiinto 03 KiíCLAMO Oficina: CAT "
    "|■cclla:0K/09/20 1 09:17:47.0 Señor: GERENTE EMPRESA AFINIA"
)
SELLO_6 = (
    "'■ \"íf i fe • i -Señores: CHi'fl'OiiiBr Je 1« S.A 5. AI CONTHSTAR CITF RSTÍ=, "
    "NU\\IF,nORF.3110202140544 Aívullo 03 RliCLAMO Odios; 2 AFINIAS.A.SE.S.P. "
    "l'cciu': 17/09/202 "
)
SELLO_ILEGIBLE = (
    "Señores: AFINIA S.A.S E.S.P. Cm'ibcmBi' Je lii rtutii 5.A 5. L'Sí' J02ir.0120359 "
    "Af CONTESTAR CtTF f STF. NUMF.RORF.J 11020214J4?9 Asiuito: 03 KiiCLAMO "
    "l oclia: 21/10/2021"
)


class TestElSelloRoto:
    def test_se_rehace_el_radicado(self):
        assert radicado_del_sello(SELLO_1) == "RE3110202139039"
        assert radicado_del_sello(SELLO_6) == "RE3110202140544"

    def test_lo_que_no_se_puede_rehacer_no_se_adivina(self):
        assert radicado_del_sello(SELLO_ILEGIBLE, Counter({"3110": 2})) is None

    def test_el_sello_se_ve_aunque_su_numero_no(self):
        assert lleva_sello_de_radicacion(SELLO_ILEGIBLE)
        assert not lleva_sello_de_radicacion("Por medio de la presente me permito " * 10)

    def test_la_fecha_del_sello_con_el_anio_del_radicado(self):
        assert fecha_del_sello(SELLO_6, "RE3110202140544") == date(2021, 9, 17)
        assert fecha_del_sello(SELLO_ILEGIBLE, None) == date(2021, 10, 21)

    def test_un_dia_ilegible_no_se_completa(self):
        """«0K/09»: la K no es una cifra segura."""
        assert fecha_del_sello(SELLO_1, "RE3110202139039") is None

    def test_un_anio_que_no_es_el_del_radicado_no_se_completa(self):
        assert fecha_del_sello("Fecha: 17/09/201", "RE3110202140544") is None


def _leidas(paginas: dict[int, tuple[str, date | None]]):
    grupos = GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=str(p), raw=str(p)), page_numbers=[p])
            for p in paginas
        ],
        quarantine=[],
        repairs=[],
    )
    leidas = PaginasLeidas(
        fechas={p: f for p, (_t, f) in paginas.items()},
        tipos={p: None for p in paginas},
        asuntos={p: None for p in paginas},
        con_ocr=0,
        textos={p: t for p, (t, _f) in paginas.items()},
    )
    return grupos, leidas


CUERPO = "proceso administrativo sin fecha alguna " * 10


class TestUPD2320043:
    """Tres escritos radicados: dos sellos se rehacen y el tercero no."""

    @pytest.fixture
    def tramites(self):
        grupos, leidas = _leidas(
            {
                1: (SELLO_1, None),
                2: (CUERPO, None),
                3: (SELLO_6, None),
                4: (CUERPO, None),
                5: (SELLO_ILEGIBLE, date(2021, 10, 21)),
                6: (CUERPO, None),
            }
        )
        return agrupar_por_tramite(grupos, leidas)

    def test_cada_escrito_radicado_es_su_tramite(self, tramites):
        assert [g.page_numbers for g in tramites.grupos.groups] == [[1, 2], [3, 4], [5, 6]]
        assert [g.code.raw for g in tramites.grupos.groups] == [
            "RE3110202139039",
            "RE3110202140544",
            "SIN-RADICADO-2021-10-21",
        ]

    def test_la_fecha_del_sello_fecha_el_tramite(self, tramites):
        assert tramites.grupos.groups[1].fecha == "2021-09-17"

    def test_el_sello_ilegible_va_a_revision(self, tramites):
        [hoja] = [h for h in tramites.en_revision if h.page == 5]
        assert "no se pudo leer" in hoja.motivo


class TestElIndiceDelTramite:
    openpyxl = pytest.importorskip("openpyxl")

    def test_titulo_con_su_re_y_expediente(self, tmp_path):
        from resolutions.adapters import indice_electronico
        from resolutions.api.worker.planillas import _escribir_indice

        report = {
            "agrupar": "tramite",
            "expediente": "UPD2321099",
            "inventory": {
                "items": [
                    {
                        "file_name": "UPD2321099/01-re3110202043677-02-12-2020_RECLAMO.pdf",
                        "code": "01 RE3110202043677 02-12-2020",
                        "type": "RECLAMO",
                        "fecha": "2020-12-02",
                        "page_count": 10,
                        "page_numbers": list(range(1, 11)),
                    }
                ]
            },
            "piezas": [
                {
                    "pages": list(range(1, 9)),
                    "type": "DERECHO DE PETICION",
                    "fecha": "2020-12-02",
                    "titulo": "DERECHO DE PETICION",
                    "asunto": "DESCARGAR DEL SISTEMA LOS VALORES ADEUDADOS POR EL ARRENDATARIO",
                },
                {"pages": [9], "type": "PQR", "fecha": None},
                {"pages": [10], "type": "CITACION PARA NOTIFICACION PERSONAL", "fecha": "2020-12-07"},
            ],
        }

        _escribir_indice(report, tmp_path, {"territorial": "CESAR", "operator": "SIAR"})

        hoja = self.openpyxl.load_workbook(tmp_path / indice_electronico.NOMBRE_DEL_INDICE).active
        assert hoja["B3"].value == "UPD2321099"
        # Lo que dice ser la primera hoja, el RE del trámite y su fecha: no la
        # clase del trámite (RECLAMO) ni una frase de la petición.
        assert hoja["A8"].value == "DERECHO DE PETICION - RE3110202043677 - 02/12/2020"
        # La creación es la fecha del documento -- su sello, su guía --; la
        # incorporación, el día del bot.
        assert hoja["B8"].value == "02/12/2020"
        # Observaciones vacía: es la del negocio.
        assert hoja["G8"].value is None
        # Y el nombre largo se lee: el texto se ajusta y la fila crece.
        assert hoja["A8"].alignment.wrap_text

    def test_sin_titulo_queda_el_tipo_y_observaciones_vacia(self, tmp_path):
        from resolutions.adapters import indice_electronico
        from resolutions.api.worker.planillas import _escribir_indice

        report = {
            "agrupar": "documento",
            "inventory": {
                "items": [
                    {
                        "file_name": "caja/01_RECLAMO.pdf",
                        "code": "01",
                        "type": "RECLAMO",
                        "page_count": 2,
                        "page_numbers": [1, 2],
                    }
                ]
            },
            "piezas": [{"pages": [1, 2], "type": "RECLAMO", "fecha": None}],
        }

        _escribir_indice(report, tmp_path, {})

        hoja = self.openpyxl.load_workbook(tmp_path / indice_electronico.NOMBRE_DEL_INDICE).active
        assert hoja["A8"].value == "RECLAMO"
        assert hoja["G8"].value is None
