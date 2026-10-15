"""Ninguna página en un trámite que no es el suyo.

El operador lo pidió así: «no necesito una página en un radicado, fecha o tema
que no pertenezca». Después de repartir por radicado y fecha, cada hoja se
comprueba contra lo que ella misma dice -- su NIC, la persona de su cédula, su
fecha, su tema, el radicado que cita --: lo que la contradice con pruebas la
mueve, y lo que no se puede probar se declara en revisión con su porqué.

Las cédulas son lecturas reales de UPD2555087, con lo que la OCR les hace.
Ninguna prueba lee papel ni llama a un proveedor.
"""

from __future__ import annotations

from datetime import date

from fakes import FakePage, FakePageSource

from resolutions.application.agrupacion import (
    PaginasLeidas,
    agrupar_por_tramite,
    leer_paginas,
)
from resolutions.application.ports import OcrResult
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.tramites import (
    despues_de_la_ventana,
    donde_aparece_la_persona,
    es_cedula,
    numeros_de,
    radicados_parecidos,
)

#: La cédula de Endelimo Payares tal como la leyó la segunda lectura: el
#: número con una coma, los rótulos con letras comidas.
CEDULA_DE_ENDELIMO = (
    "REPUBLICA DE COLOMBIA ¡DENTIFICACION PERSONAL CEDULA DE GIUDADANIA MA 92,516,337 "
    "PAYARES SERPA S6 piNes ENDELIMO DELSO recvaii acimEnto O6-JUL-1971 SINCELEJO (SUCRE)"
)
CEDULA_DE_DILIA = (
    "REPUBLICA DE COLOMBIA IDENTIFICACION FERSONAL CEDULA DE GIUDADANIA m - 64581480 "
    "SIERRA VERGARA EE DILIA MARIA FEC-A DE NACIMIENTO T3-MAR-1977 BUENAVISTA (CORDOBA)"
)
EXPEDIENTE = (
    "EXPEDIENTE No. Expediente: P43102019110005 NIC: 4415228 DATOS CLIENTE NOMBRE "
    "SIERRA VERGARA DILIA MARIA DOCUMENTO IDENTIDAD 64581460"
)
RECLAMO_DE_ENDELIMO = (
    "Recibí constancia del contenido de la reclamación N* PQR: RE4310202207352 "
    "CODIGO (NIC): 4415228"
)
CARTA_DE_ENDELIMO = (
    "REF: DERECHO DE PETICION. ASUNTO: CONSUMO ELEVADO. ENDELIMO PAYARES CERPA "
    "ATENTAMENTE, ENDELIMO PAYARES CERPA C.C. 92.516.337."
)
RESPUESTA_A_ENDELIMO = (
    "ASUNTO: Reclamación No. RE4310202207352 SEÑOR(A) ENDELIMO DELSO PAYARES SERPA"
)
RECLAMO_DE_ESTRATO = (
    "Recibí constancia del contenido de la reclamación N* PQR: RE4310202208426 "
    "NOMBRE SIERRA VERGARA, DILIA MARIA DOCUMENTO DE IDENTIDAD 64581460"
)


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


def _archivos(resultado) -> dict[str, list[int]]:
    return {g.code.raw: g.page_numbers for g in resultado.grupos.groups}


class TestLaCedula:
    def test_se_reconoce_aunque_la_ocr_se_coma_letras(self):
        assert es_cedula(CEDULA_DE_ENDELIMO)
        assert es_cedula(CEDULA_DE_DILIA)

    def test_un_formulario_que_pide_la_cedula_no_es_una_cedula(self):
        assert not es_cedula(EXPEDIENTE)
        assert not es_cedula("CONSTANCIA DE CONTRATACION CEDULA DE CIUDADANIA FECHA DE NACIMIENTO")

    def test_su_numero_con_comas_y_el_del_codigo_de_barras(self):
        assert "92516337" in numeros_de(CEDULA_DE_ENDELIMO)
        assert "64581460" in numeros_de("A-2820000-00223816-F-0064581460-20100311")

    def test_se_sabe_que_tramite_nombra_a_la_persona(self):
        donde = donde_aparece_la_persona(
            CEDULA_DE_ENDELIMO,
            {"RE4310202207352": CARTA_DE_ENDELIMO, "RE4310202208426": RECLAMO_DE_ESTRATO},
        )
        assert list(donde) == ["RE4310202207352"]
        assert "n.º 92516337" in donde["RE4310202207352"]

    def test_un_numero_mal_leido_en_una_cifra_sigue_siendo_suyo(self):
        donde = donde_aparece_la_persona(CEDULA_DE_DILIA, {"P43102019110005": EXPEDIENTE})
        assert donde == {"P43102019110005": ["n.º 64581480", "«DILIA MARIA»", "«SIERRA VERGARA»"]}

    def test_lo_que_nombran_todos_los_tramites_no_distingue(self):
        # El titular del servicio está en todas las facturas: su nombre no
        # dice de qué trámite es su cédula.
        donde = donde_aparece_la_persona(
            "IDENTIFICACION PERSONAL CEDULA DE CIUDADANIA SIERRA VERGARA",
            {"A": "titular SIERRA VERGARA", "B": "usuario SIERRA VERGARA"},
        )
        assert donde == {}


class TestNingunaHojaDondeNoEs:
    def test_la_cedula_del_reclamante_vuelve_a_su_reclamacion(self):
        # UPD2555087: la cédula de Endelimo quedó, por el orden del escaneo,
        # entre las hojas del reclamo de estrato de Dilia.
        grupos, leidas = _leidas(
            {
                1: (RECLAMO_DE_ENDELIMO, date(2022, 8, 18)),
                2: (RESPUESTA_A_ENDELIMO, date(2022, 8, 18)),
                3: (CARTA_DE_ENDELIMO, date(2022, 8, 18)),
                4: (RECLAMO_DE_ESTRATO, date(2022, 9, 26)),
                5: ("CERTIFICADO DE ESTRATIFICACION", None),
                6: (CEDULA_DE_ENDELIMO, date(1971, 7, 6)),
                7: ("Estado de cuenta factura", date(2022, 9, 16)),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        assert _archivos(resultado) == {
            "RE4310202207352": [1, 2, 3, 6],
            "RE4310202208426": [4, 5, 7],
        }
        assert resultado.movidas == 1
        [hoja] = resultado.en_revision
        assert hoja.page == 6
        assert "se movió del trámite RE4310202208426 al RE4310202207352" in hoja.motivo
        assert "92516337" in hoja.motivo
        assert "se movió al que la nombra" in resultado.aviso()

    def test_la_cedula_que_su_tramite_nombra_se_queda(self):
        grupos, leidas = _leidas(
            {
                1: (EXPEDIENTE, date(2019, 11, 6)),
                2: (CEDULA_DE_DILIA, None),
                3: (RECLAMO_DE_ENDELIMO, date(2022, 8, 18)),
                4: (CARTA_DE_ENDELIMO, date(2022, 8, 18)),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        assert _archivos(resultado) == {"P43102019110005": [1, 2], "RE4310202207352": [3, 4]}
        assert resultado.movidas == 0

    def test_la_fecha_de_nacimiento_de_una_cedula_no_la_reparte(self):
        # Fechada en 1971 no encaja en ningún trámite, y eso no dice nada.
        grupos, leidas = _leidas(
            {
                1: (RECLAMO_DE_ENDELIMO, date(2022, 8, 18)),
                2: (CEDULA_DE_ENDELIMO, date(1971, 7, 6)),
                3: (CARTA_DE_ENDELIMO, date(2022, 8, 18)),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        assert _archivos(resultado) == {"RE4310202207352": [1, 2, 3]}
        assert resultado.en_revision == []

    def test_una_hoja_con_el_nic_de_otro_tramite_se_va_al_suyo(self):
        grupos, leidas = _leidas(
            {
                1: ("N° PQR: RE4310202103559 reclamación NIC: 4415218", date(2022, 8, 1)),
                2: ("N° PQR: RE4310202207352 reclamación NIC: 4415228", date(2022, 8, 18)),
                3: ("Estado de cuenta NIC: 4415218", None),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        assert _archivos(resultado) == {"RE4310202103559": [1, 3], "RE4310202207352": [2]}
        assert "NIC 4415218" in resultado.en_revision[0].motivo

    def test_un_nic_que_no_es_de_ningun_tramite_se_declara(self):
        grupos, leidas = _leidas(
            {
                1: ("N° PQR: RE4310202207352 reclamación NIC: 4415228", date(2022, 8, 18)),
                2: ("Estado de cuenta NIC: 9999999", date(2022, 8, 1)),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        assert _archivos(resultado) == {"RE4310202207352": [1, 2]}
        assert "ningún otro trámite de la caja es de ese NIC" in resultado.en_revision[0].motivo

    def test_fechada_despues_de_su_tramite_y_con_dos_destinos_se_declara(self):
        # Una factura de septiembre de 2022 detrás del expediente de 2019, que
        # es el último trámite de la caja: encaja en las dos reclamaciones de
        # 2022, y elegir una sería adivinar.
        grupos, leidas = _leidas(
            {
                1: (RECLAMO_DE_ENDELIMO, date(2022, 8, 18)),
                2: (RECLAMO_DE_ESTRATO, date(2022, 9, 26)),
                3: (EXPEDIENTE, date(2019, 11, 6)),
                4: ("Estado de cuenta factura", date(2022, 9, 16)),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        assert _archivos(resultado)["P43102019110005"] == [3, 4]
        [hoja] = resultado.en_revision
        assert "16-09-2022" in hoja.motivo
        assert "encaja en 2 trámites" in hoja.motivo

    def test_fechada_despues_de_su_tramite_y_con_un_destino_se_mueve(self):
        grupos, leidas = _leidas(
            {
                1: (RECLAMO_DE_ESTRATO, date(2022, 9, 26)),
                2: (EXPEDIENTE, date(2019, 11, 6)),
                3: ("Estado de cuenta factura", date(2022, 9, 16)),
                4: ("CERTIFICADO DE TRADICION", date(2019, 11, 5)),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        assert _archivos(resultado) == {"RE4310202208426": [1, 3], "P43102019110005": [2, 4]}
        assert resultado.movidas == 1

    def test_el_certificado_que_arrastro_una_factura_vuelve_a_su_tramite(self):
        # La factura de 2022 se va con su reclamación, y el certificado de
        # 2019 que venía detrás no puede irse con ella.
        grupos, leidas = _leidas(
            {
                1: (EXPEDIENTE, date(2019, 11, 6)),
                2: ("Estado de cuenta factura", date(2022, 9, 16)),
                3: ("CERTIFICADO DE TRADICION", date(2019, 11, 5)),
                4: (RECLAMO_DE_ESTRATO, date(2022, 9, 26)),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        assert _archivos(resultado) == {"P43102019110005": [1, 3], "RE4310202208426": [2, 4]}
        [hoja] = resultado.en_revision
        assert hoja.page == 3
        assert "se movió del trámite RE4310202208426 al P43102019110005" in hoja.motivo

    def test_una_factura_vieja_no_se_mueve(self):
        # Antes de la ventana es un anexo: la factura que se reclama.
        assert not despues_de_la_ventana(date(2019, 1, 1), date(2022, 8, 18))
        assert despues_de_la_ventana(date(2022, 12, 1), date(2022, 8, 18))

    def test_una_hoja_que_cita_el_radicado_de_otro_tramite_se_declara(self):
        grupos, leidas = _leidas(
            {
                1: (RECLAMO_DE_ENDELIMO, date(2022, 8, 18)),
                2: (RECLAMO_DE_ESTRATO, date(2022, 9, 26)),
                3: ("ASUNTO: Reclamación No. RE4310202208426, ver RE4310202207352", date(2022, 9, 30)),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        assert _archivos(resultado)["RE4310202208426"] == [2, 3]
        assert "cita también el RE4310202207352" in resultado.en_revision[0].motivo

    def test_dos_radicados_que_difieren_en_una_cifra_se_declaran(self):
        assert radicados_parecidos("RE4310202207352", "RE4310202207362")
        assert not radicados_parecidos("RE4310202207352", "RE4310202208426")
        grupos, leidas = _leidas(
            {
                1: (RECLAMO_DE_ENDELIMO, date(2022, 8, 18)),
                2: (RESPUESTA_A_ENDELIMO, date(2022, 8, 18)),
                3: ("ASUNTO: Reclamación No. RE4310202207362", date(2022, 8, 18)),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        [hoja] = resultado.en_revision
        assert hoja.page == 3
        assert "se diferencia en una cifra del RE4310202207352" in hoja.motivo

    def test_una_constancia_sin_radicado_ni_fecha_junto_a_otro_radicado(self):
        grupos, leidas = _leidas(
            {
                1: (RECLAMO_DE_ENDELIMO, date(2022, 8, 18)),
                2: ("Estado de cuenta", date(2022, 8, 1)),
                3: ("Estado de cuenta", date(2022, 8, 1)),
                4: ("REF: DERECHO DE PETICION ilegible", None),
                5: (RECLAMO_DE_ESTRATO, date(2022, 9, 26)),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        motivos = {h.page: h.motivo for h in resultado.en_revision}
        assert "el radicado más cercano es el del RE4310202208426" in motivos[4]

    def test_la_notificacion_junto_a_su_radicado_no_se_marca(self):
        # UPD2555087 p39: la notificación de la Alcaldía del reclamo de estrato,
        # con la fecha en casillas que no se lee, dos hojas después del suyo.
        grupos, leidas = _leidas(
            {
                1: (RECLAMO_DE_ESTRATO, date(2022, 9, 26)),
                2: ("CERTIFICADO DE ESTRATIFICACION", date(2022, 9, 22)),
                3: ("NOTIFICACION DEL RECLAMO RESUELTO POR LA ALCALDIA", None),
            }
        )
        resultado = agrupar_por_tramite(grupos, leidas)
        assert resultado.en_revision == []


class TestLaSegundaLectura:
    """La fotocopia gris de una cédula sale muda de la lectura de página entera."""

    def test_una_pagina_muda_se_relee_y_se_queda_la_que_mas_dice(self):
        fuente = FakePageSource([FakePage(text="", body=".. a e")])

        class Fina:
            calls = 0

            def read(self, image_png: bytes) -> OcrResult:
                Fina.calls += 1
                return OcrResult(text=CEDULA_DE_ENDELIMO, mean_confidence=0.3)

        from fakes import FakeOcr

        leidas = leer_paginas(fuente, FakeOcr(), releer=Fina())
        assert Fina.calls == 1
        assert leidas.textos[1] == CEDULA_DE_ENDELIMO

    def test_una_pagina_que_ya_se_leyo_bien_no_se_relee(self):
        fuente = FakePageSource([FakePage(text="", body=CARTA_DE_ENDELIMO * 2)])

        class Fina:
            calls = 0

            def read(self, image_png: bytes) -> OcrResult:
                Fina.calls += 1
                return OcrResult(text="", mean_confidence=0.0)

        from fakes import FakeOcr

        leer_paginas(fuente, FakeOcr(), releer=Fina())
        assert Fina.calls == 0
