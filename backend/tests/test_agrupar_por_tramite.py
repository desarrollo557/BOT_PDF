"""Una caja de correspondencia entregada por trámite: el radicado abre, la fecha reparte.

Los casos salen de los expedientes UPD2555087 y UPD2555083: una solicitud de
servicio de 2019 y varias reclamaciones de 2021 y 2022 del mismo suscriptor,
mezcladas con sus cédulas, facturas y certificados. Ninguna prueba lee papel ni
llama a un proveedor: el texto de cada página se da hecho.
"""

from __future__ import annotations

from datetime import date

from resolutions.application.agrupacion import (
    Agrupacion,
    PaginasLeidas,
    agrupar_por_tramite,
)
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.tramites import (
    abre_un_tramite,
    en_ventana,
    nic_de,
    radicado_de,
    radicados_de,
)

EXPEDIENTE = "ELECTRIFICADORA DEL CARIBE EXPEDIENTE No. Expediente: P43102019110005 NIC: 4415228"
CONSTANCIA = (
    "Recibí constancia del contenido de la reclamación presentada ante CARIBEMAR "
    "N* POR: RE4310202207352 FECHA: 18/08/2022 CODIGO (NIC): 4415228"
)
RESPUESTA = "Consecutivo No. 220818120212431 ASUNTO: Reclamación No. RE4310202207352"
OTRA_RECLAMACION = "Recibí constancia del contenido de la reclamación N* PQR: RE4310202208426"


class TestElRadicado:
    def test_la_pqr_y_el_expediente(self):
        assert radicado_de(CONSTANCIA) == "RE4310202207352"
        assert radicado_de(EXPEDIENTE) == "P43102019110005"

    def test_el_ocr_mete_un_espacio(self):
        assert radicado_de("N° PQR: R E 4310202209000") == "RE4310202209000"

    def test_la_pqr_manda_sobre_el_expediente(self):
        assert radicados_de(f"{EXPEDIENTE} {RESPUESTA}") == ["P43102019110005", "RE4310202207352"]
        assert radicado_de(f"{EXPEDIENTE} {RESPUESTA}") == "RE4310202207352"

    def test_el_consecutivo_de_la_respuesta_no_es_un_radicado(self):
        assert radicados_de("Consecutivo No. 220818120212431") == []

    def test_el_nic(self):
        assert nic_de(CONSTANCIA) == "4415228"

    def test_lo_que_abre_un_tramite(self):
        assert abre_un_tramite("REF: DERECHO DE PETICION. ASUNTO: CONSUMO ELEVADO")
        assert not abre_un_tramite("REPUBLICA DE COLOMBIA CEDULA DE CIUDADANIA")

    def test_la_ventana_de_un_tramite(self):
        assert en_ventana(date(2022, 6, 21), date(2022, 8, 18))  # la factura que se reclama
        assert en_ventana(date(2022, 9, 7), date(2022, 8, 18))  # el plazo de respuesta
        assert not en_ventana(date(2019, 11, 6), date(2022, 8, 18))


def _leidas(paginas: dict[int, tuple[str, date | None]]) -> tuple[GroupingResult, PaginasLeidas]:
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
        con_ocr=len(paginas),
        textos={p: t for p, (t, _f) in paginas.items()},
    )
    return grupos, leidas


class TestAgruparPorTramite:
    def test_el_expediente_de_la_caja(self):
        grupos, leidas = _leidas(
            {
                1: (EXPEDIENTE, date(2019, 11, 6)),
                2: ("REPUBLICA DE COLOMBIA CEDULA", date(1988, 10, 7)),  # nacimiento: no cuenta
                3: ("CERTIFICADO DE TRADICION Impreso el 5 de noviembre de 2019", date(2019, 11, 5)),
                4: (EXPEDIENTE, date(2019, 11, 6)),  # la segunda copia de la portada
                5: (CONSTANCIA, date(2022, 9, 7)),  # cita el plazo de respuesta
                6: (RESPUESTA, date(2022, 8, 18)),
                7: (f"NOTIFICACION PERSONAL RECLAMOS {RESPUESTA}", date(2022, 8, 18)),
                8: ("REF: DERECHO DE PETICION", date(2022, 8, 18)),
                9: ("Estado de cuenta factura", date(2022, 6, 21)),
                10: (OTRA_RECLAMACION, date(2022, 9, 26)),
                11: ("CERTIFICADO DE ESTRATIFICACION", None),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        archivos = [(g.code.value, g.page_numbers, g.kind, g.fecha) for g in resultado.grupos.groups]
        assert archivos == [
            ("01 P43102019110005 06-11-2019", [1, 2, 3, 4], "DOCUMENTO", "2019-11-06"),
            ("02 RE4310202207352 18-08-2022", [5, 6, 7, 8, 9], "RECLAMO", "2022-08-18"),
            ("03 RE4310202208426 26-09-2022", [10, 11], "RECLAMO", "2022-09-26"),
        ]
        assert "NIC 4415228" in resultado.grupos.groups[0].title

    def test_un_anexo_va_al_tramite_de_su_fecha(self):
        # La factura de septiembre va antes de la constancia que la reclama:
        # su fecha no encaja en la reclamación de 2019 y sí en la de 2022.
        grupos, leidas = _leidas(
            {
                1: ("N° PQR: RE4310202103559 reclamación", date(2021, 8, 11)),
                2: ("Estado de cuenta factura", date(2022, 7, 30)),
                3: ("N° PQR: RE4310202207571 reclamación", date(2022, 8, 26)),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        assert [g.page_numbers for g in resultado.grupos.groups] == [[1], [2, 3]]
        assert resultado.por_fecha == 1

    def test_sin_fecha_se_une_y_se_declara_si_queda_en_la_frontera(self):
        grupos, leidas = _leidas(
            {
                1: ("N° PQR: RE4310202103559 reclamación", date(2021, 8, 11)),
                2: ("REPUBLICA DE COLOMBIA CEDULA", None),
                3: ("N° PQR: RE4310202207571 reclamación", date(2022, 8, 26)),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        assert [g.page_numbers for g in resultado.grupos.groups] == [[1, 2], [3]]
        assert [h.page for h in resultado.en_revision] == [2]

    def test_una_constancia_sin_radicado_legible_abre_el_suyo(self):
        grupos, leidas = _leidas(
            {
                1: ("N° PQR: RE4310202103559 reclamación", date(2021, 8, 11)),
                2: ("Recibí constancia del contenido de la reclamación N* PQR: ilegible", date(2023, 3, 2)),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        assert [g.code.value for g in resultado.grupos.groups] == [
            "01 RE4310202103559 11-08-2021",
            "02 SIN-RADICADO-2023-03-02",
        ]

    def test_sin_ningun_radicado_no_agrupa(self):
        grupos, leidas = _leidas({1: ("una carta", date(2022, 1, 1)), 2: ("otra", None)})
        resultado = agrupar_por_tramite(grupos, leidas)
        assert not resultado.agrupo
        assert "por documento" in resultado.aviso()


def test_la_opcion_se_pide_por_la_api():
    assert Agrupacion.parse("tramite") is Agrupacion.TRAMITE
    assert Agrupacion.TRAMITE.label == "Un archivo por trámite"


class TestLaFechaDelTramite:
    def test_sin_fecha_en_el_radicado_toma_la_del_escrito_que_lo_abre(self):
        """UPD2321099: el radicado sólo se lee en la guía de entrega, que no trae
        una fecha legible. El trámite no queda sin fecha: lleva la del derecho
        de petición que lo abre, «Valledupar, diciembre 02 de 2020»."""
        grupos, leidas = _leidas(
            {
                1: ("Valledupar, diciembre 02 de 2020 REF: DERECHO DE PETICION", date(2020, 12, 2)),
                2: ("CONTRATO DE ARRENDAMIENTO DE VIVIENDA", date(2018, 11, 25)),
                3: ("GUIA DE ENTREGA PQR RE3110202043677", None),
            }
        )

        por_tramite = agrupar_por_tramite(grupos, leidas)

        [tramite] = por_tramite.grupos.groups
        assert tramite.fecha == "2020-12-02"
