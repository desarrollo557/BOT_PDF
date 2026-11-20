"""El reconocimiento fechado va primero, el más reciente de dos manda, y la constancia va sola (2026-11-20).

Revisando la entrega de la prueba piloto de Magangué, el operador: «por qué no
está el reconocimiento de deuda de primero si tiene sus fechas» (1000258). El
reconocimiento fechado a mano lo lee la IA, pero la firma de la carta de
instrucciones -- que Tesseract sí lee -- fechaba antes el acuerdo, y como esa
hoja no es del reconocimiento, el reconocimiento iba al final.

Y dos reglas que dictó en la misma revisión: «cuando en un reconocimiento de
deuda estén 2 reconocimientos de deuda, coloca el más reciente», y la
constancia de recepción de peticiones va sola siempre, también frente a su
cédula, que pasa al documento siguiente. Desde entonces se llama
«CONSTANCIA DE RECEPCION DE PETICIONES - RE…».

Los datos de las hojas son inventados.
"""

from __future__ import annotations

from datetime import date

from resolutions.api.worker.correspondencia import (
    _el_reconocimiento_mas_reciente,
    _ordenar_los_acuerdos,
)
from resolutions.application.agente_de_fechas import AgenteDeFechas
from resolutions.application.anexos_declarados import (
    constancias_solas,
    orden_del_acuerdo,
    reconocimientos_del_acuerdo,
)
from resolutions.domain.fecha_por_estructura import fecha_de_la_hoja
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.nombre_oficial import lleva_re_en_el_nombre, nombre_oficial
from resolutions.domain.resolution_code import ResolutionCode

RECONOCIMIENTO = (
    "{fecha}\nSeñores:\nCARIBEMAR DE LA COSTA S.A.S E.S.P.\n"
    "Ref.: Reconocimiento de deuda y propuesta de acuerdo de pago.\n"
    "Yo, Pedro Pérez identificado como aparece al pie de mi firma, en mi calidad de usuario.\n"
)
PAGARE = "CARIBEMAR DE LA COSTA S.A.S. ESP\nEMPRESA DE SERVICIOS PUBLICOS DOMICILIARIOS\nPAGARE No. 1000001 -1\n"
CEDULA = "REPUBLICA DE COLOMBIA\nIDENTIFICACION PERSONAL\nCEDULA DE CIUDADANIA\n1.000.000.001\nNUMERO\nPEREZ\nAPELLIDOS\n"
CONSTANCIA = (
    "CARIBEMAR DE LA COSTA S.A.S. ESP\nCONSTANCIA DE RECEPCIÓN DE PETICIONES, QUEJAS Y RECLAMOS (PQR)\n"
    "N° PQR: RE2310202100001\nFECHA DE RECEPCIÓN: 02/03/2021\nCLIENTE: PEDRO PEREZ\n"
)
CARTA = (
    "Magangué, 3 de abril de 2023\nSeñores AFINIA\nREF: Reclamo por cobro excesivo en la factura del mes de marzo\n"
    "Por medio de la presente me dirijo a ustedes para reclamar el cobro excesivo que llegó en mi factura, "
    "porque en la vivienda no hay consumo desde hace meses y solicito la revisión del medidor instalado.\n"
)


class _Lector:
    def __init__(self, textos: dict[int, str]):
        self._textos = textos
        self.leidas: list[int] = []

    def __call__(self, pagina: int) -> str:
        self.leidas.append(pagina)
        return self._textos.get(pagina, "")


class TestLaHojaPrincipalPrimeroYEntera:
    def test_la_ia_lee_el_reconocimiento_antes_de_aceptar_la_firma_de_la_carta(self):
        # Hoja 1, el reconocimiento con la fecha a mano que la capa no trae;
        # hoja 2, la carta de instrucciones con su firma fechada en la capa.
        textos = {1: RECONOCIMIENTO.format(fecha=""), 2: "a los 18 días del mes septiembre del año 2020"}
        ia = _Lector({1: RECONOCIMIENTO.format(fecha="Magangué 8 de marzo de 2021")})
        agente = AgenteDeFechas(leer_con_ia=ia, fechar=fecha_de_la_hoja, en_orden=True)
        hallada = agente.buscar([1, 2], textos)
        assert (hallada.fecha, hallada.pagina, hallada.via) == (date(2021, 3, 8), 1, "ia")
        assert ia.leidas == [1]

    def test_sin_fecha_en_la_principal_vale_el_respaldo(self):
        textos = {1: RECONOCIMIENTO.format(fecha=""), 2: "Magangué 18 de septiembre de 2020"}
        agente = AgenteDeFechas(leer_con_ia=_Lector({}), en_orden=True)
        assert agente.buscar([1, 2], textos).pagina == 2


class TestDosReconocimientos:
    TEXTOS = {
        1: RECONOCIMIENTO.format(fecha="Magangué 8 de marzo de 2021"),
        2: PAGARE,
        3: RECONOCIMIENTO.format(fecha="Magangué 10 de junio de 2022"),
        4: PAGARE,
        5: CEDULA,
    }

    def test_cada_reconocimiento_por_separado(self):
        assert reconocimientos_del_acuerdo(range(1, 6), self.TEXTOS) == [[1], [3]]

    def test_el_mas_reciente_primero_y_el_anterior_detras_antes_de_los_pagares(self):
        fechas = {1: date(2021, 3, 8), 3: date(2022, 6, 10)}
        orden = orden_del_acuerdo(range(1, 6), self.TEXTOS, reconocimiento_fechado=True, fechas_del_reconocimiento=fechas)
        assert orden == (3, 1, 2, 4, 5)

    def test_el_que_no_tiene_fecha_va_detras_de_los_fechados(self):
        orden = orden_del_acuerdo(
            range(1, 6), self.TEXTOS, reconocimiento_fechado=True, fechas_del_reconocimiento={3: date(2022, 6, 10)}
        )
        assert orden == (3, 1, 2, 4, 5)
        orden = orden_del_acuerdo(
            range(1, 6), self.TEXTOS, reconocimiento_fechado=True, fechas_del_reconocimiento={1: date(2021, 3, 8)}
        )
        assert orden == (1, 3, 2, 4, 5)

    def test_el_acuerdo_toma_la_fecha_del_mas_reciente(self):
        pieza = {"pages": [1, 2, 3, 4, 5], "fecha": "2021-03-08", "fecha_pagina": 1, "reconocimientos": [[1], [3]]}
        agente = AgenteDeFechas(fechar=fecha_de_la_hoja, en_orden=True)
        halladas = _el_reconocimiento_mas_reciente(pieza, self.TEXTOS, agente)
        assert (pieza["fecha"], pieza["fecha_pagina"]) == ("2022-06-10", 3)
        assert pieza["fechas_del_reconocimiento"] == [[1, "2021-03-08"], [3, "2022-06-10"]]
        assert "el más reciente de 2 reconocimientos" in halladas[0]["como"]

    def test_y_el_pdf_sale_con_el_mas_reciente_delante(self):
        grupo = PageGroup(code=ResolutionCode(value="01", raw="01"), page_numbers=[1, 2, 3, 4, 5])
        pieza = {
            "archivo": 0,
            "pages": [1, 2, 3, 4, 5],
            "fecha": "2022-06-10",
            "fecha_pagina": 3,
            "reconocimientos": [[1], [3]],
            "fechas_del_reconocimiento": [[1, "2021-03-08"], [3, "2022-06-10"]],
        }
        grupos = _ordenar_los_acuerdos(GroupingResult(groups=[grupo]), [pieza], self.TEXTOS, set(range(1, 6)))
        assert grupos.groups[0].en_el_pdf == [3, 1, 2, 4, 5]


def _grupo(valor: str, paginas: list[int]) -> PageGroup:
    return PageGroup(code=ResolutionCode(value=valor, raw=valor), page_numbers=paginas)


class TestLaConstanciaVaSola:
    TEXTOS = {1: CONSTANCIA, 2: CEDULA, 3: CARTA, 4: CEDULA}
    CONSTANCIAS = {1: "RE2310202100001"}

    def test_su_cedula_va_con_el_documento_siguiente(self):
        grupos = GroupingResult(groups=[_grupo("01", [1, 2]), _grupo("02", [3, 4])])
        solas = constancias_solas(grupos, self.TEXTOS, {}, constancias=self.CONSTANCIAS)
        assert [g.page_numbers for g in solas.grupos.groups] == [[1], [2, 3, 4]]
        assert [g.code.value for g in solas.grupos.groups] == ["01", "02"]
        assert solas.movidas == {2: 3}

    def test_sin_documento_siguiente_va_con_el_anterior(self):
        grupos = GroupingResult(groups=[_grupo("01", [3]), _grupo("02", [1, 2])])
        solas = constancias_solas(grupos, self.TEXTOS, {}, constancias=self.CONSTANCIAS)
        assert [g.page_numbers for g in solas.grupos.groups] == [[2, 3], [1]]

    def test_nunca_con_otra_constancia(self):
        textos = {1: CONSTANCIA, 2: CEDULA, 3: CONSTANCIA, 4: CARTA}
        grupos = GroupingResult(groups=[_grupo("01", [1, 2]), _grupo("02", [3]), _grupo("03", [4])])
        solas = constancias_solas(grupos, textos, {}, constancias={1: "RE2310202100001", 3: "RE2310202100002"})
        assert [g.page_numbers for g in solas.grupos.groups] == [[1], [3], [2, 4]]

    def test_la_carta_de_detras_es_su_propio_documento(self):
        grupos = GroupingResult(groups=[_grupo("01", [1, 3])])
        solas = constancias_solas(grupos, self.TEXTOS, {}, constancias=self.CONSTANCIAS)
        assert [g.page_numbers for g in solas.grupos.groups] == [[1], [3]]
        assert solas.movidas == {}

    def test_las_dos_hojas_de_la_misma_constancia_siguen_juntas(self):
        grupos = GroupingResult(groups=[_grupo("01", [1, 2])])
        constancias = {1: "RE2310202100001", 2: "RE2310202100001"}
        solas = constancias_solas(grupos, {1: CONSTANCIA, 2: CONSTANCIA}, {}, constancias=constancias)
        assert solas.grupos is grupos

    def test_sin_constancia_nada_cambia(self):
        grupos = GroupingResult(groups=[_grupo("01", [3, 4])])
        assert constancias_solas(grupos, self.TEXTOS, {}, constancias=self.CONSTANCIAS).grupos is grupos


class TestSuNombre:
    """El operador, 2026-11-20: «este formato sí déjale el nombre que tenía antes, es al otro»."""

    PARA_LA_EMPRESA = (
        "PARA LA EMPRESA\nRecibí constancia del contenido de la reclamación presentada ante CARIBEMAR\n"
        "N° PQR: RE2310202200001\nFECHA: 08/04/2022\nCAUSA:\nEmisión de documento para pago"
    )

    def test_la_de_para_la_empresa_sigue_con_su_nombre(self):
        from resolutions.domain.nombre_oficial import nombre_de_la_constancia

        assert nombre_de_la_constancia(self.PARA_LA_EMPRESA) == "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION"
        assert nombre_oficial("CONSTANCIA DE RECLAMACION") == "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION"

    def test_la_de_recepcion_de_peticiones_se_llama_asi(self):
        from resolutions.domain.nombre_oficial import nombre_de_la_constancia

        assert nombre_de_la_constancia(CONSTANCIA) == "CONSTANCIA DE RECEPCION DE PETICIONES"
        # Aunque el escáner rompa el título: «FECHA DE ATENCION VENCE» sólo lo trae ella.
        assert nombre_de_la_constancia("N° PQR: RE2310202100001\nFECHA DE ATENCION VENCE: 31/12/2999") == (
            "CONSTANCIA DE RECEPCION DE PETICIONES"
        )

    def test_las_dos_llevan_su_re(self):
        assert lleva_re_en_el_nombre("CONSTANCIA DE RECEPCION DE PETICIONES")
        assert lleva_re_en_el_nombre("CONSTANCIA DEL CONTENIDO DE LA RECLAMACION")


class TestElAnioEnDosCifras:
    """4132589 y 4132537 (2026-11-20): el reconocimiento dice a mano «16 de 09 de 20» o «02 de 02 de 22»."""

    def test_la_fecha_escrita_con_el_anio_a_medias(self):
        from resolutions.domain.fechas import fecha_escrita_en

        assert fecha_escrita_en("Mgue , 16 de 09 de 20", date(2020, 9, 16)) == "16 de 09 de 20"
        assert fecha_escrita_en("Magangue, 02 de 02 de 22", date(2022, 2, 2)) == "02 de 02 de 22"
        assert fecha_escrita_en("Magangue. 16 de Sept. de 2020", date(2020, 9, 16))
        # Otro día, otro mes u otro año no la escriben.
        assert fecha_escrita_en("18 de 09 de 20", date(2020, 9, 16)) is None
        assert fecha_escrita_en("16 de 09 de 21", date(2020, 9, 16)) is None

    def test_el_reconocimiento_que_la_escribe_es_el_que_fecha_el_acuerdo(self):
        from resolutions.api.worker.correspondencia import _el_reconocimiento_la_confirma

        pieza = {
            "pages": [1, 2, 3, 4, 5],
            "fecha": "2022-02-02",
            "fecha_por": "leída por la IA en la pág. 1",
            "fecha_pagina": 1,
            "reconocimientos": [[5]],
        }
        textos = {5: RECONOCIMIENTO.format(fecha="")}
        releidas = {5: [RECONOCIMIENTO.format(fecha="Magangue , 02 de 02 de 22")]}
        assert _el_reconocimiento_la_confirma(pieza, textos, releidas)
        assert pieza["fecha_pagina"] == 5 and "«02 de 02 de 22» en el reconocimiento" in pieza["fecha_por"]
        assert pieza["fechas_del_reconocimiento"] == [[5, "2022-02-02"]]

    def test_el_que_escribe_otra_fecha_no(self):
        from resolutions.api.worker.correspondencia import _el_reconocimiento_la_confirma

        pieza = {"pages": [1, 5], "fecha": "2022-02-02", "fecha_pagina": 1, "reconocimientos": [[5]]}
        textos = {5: RECONOCIMIENTO.format(fecha="Magangue , 03 de 02 de 22")}
        assert _el_reconocimiento_la_confirma(pieza, textos, {}) == []
        assert pieza["fecha_pagina"] == 1

    def test_con_dos_cada_uno_que_la_escribe(self):
        from resolutions.api.worker.correspondencia import _el_reconocimiento_la_confirma

        pieza = {"pages": list(range(1, 11)), "fecha": "2020-09-16", "fecha_pagina": 3, "reconocimientos": [[4], [8]]}
        textos = {
            4: RECONOCIMIENTO.format(fecha="Mgue, 16 de 09 de 20"),
            8: RECONOCIMIENTO.format(fecha="Magangue. 16 de Sept. de 2020"),
        }
        _el_reconocimiento_la_confirma(pieza, textos, {})
        assert pieza["fecha_pagina"] == 4
        assert pieza["fechas_del_reconocimiento"] == [[4, "2020-09-16"], [8, "2020-09-16"]]
