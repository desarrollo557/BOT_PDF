"""El agente de las fechas: ningún documento sin fecha, sin gastar IA si no se pidió.

Lo pidió el operador el 2026-10-20 ante el índice de UPD2437820 con un
«CONTRATO DE TRANSACCION» en «S.F.»: «que el bot en todos los casos tome la
fecha». Las relecturas son de mentira: se prueba el orden y el gasto, no la OCR.
"""

from __future__ import annotations

from datetime import date

from resolutions.application.agente_de_fechas import (
    AgenteDeFechas,
    candidatas,
    fecha_por_su_tramite,
)

#: El contrato real: la fecha va en la última hoja, en formato de formulario.
CONTRATO = {
    1: "CONTRATO DE TRANSACCIÓN Entre las siguientes partes a saber: la AFINIA",
    2: "CLÁUSULAS PRIMERA: objeto del contrato",
    3: "En constancia se suscribe este documento ... Ciudad: MAGANGUE, día:3 mes:5 del año2021.",
}


class _Lector:
    def __init__(self, respuestas: dict[int, str]) -> None:
        self.respuestas = respuestas
        self.leidas: list[int] = []

    def __call__(self, pagina: int) -> str:
        self.leidas.append(pagina)
        return self.respuestas.get(pagina, "")


class TestElAgente:
    def test_la_fecha_del_formulario_sale_del_texto_sin_releer_nada(self):
        local, ia = _Lector({}), _Lector({})
        hallada = AgenteDeFechas(releer=local, leer_con_ia=ia).buscar([1, 2, 3], CONTRATO)
        assert (hallada.fecha, hallada.pagina, hallada.via) == (date(2021, 5, 3), 3, "texto")
        assert local.leidas == [] and ia.leidas == []

    def test_la_manuscrita_la_relee_primero_en_local(self):
        textos = {1: "ACTA DE VISITA", 2: "Fecha: ___ firma del usuario"}
        local = _Lector({2: "Fecha: 12/03/2022"})
        ia = _Lector({2: "Fecha: 12/03/2022"})
        hallada = AgenteDeFechas(releer=local, leer_con_ia=ia).buscar([1, 2], textos)
        assert (hallada.fecha, hallada.via) == (date(2022, 3, 12), "ocr")
        assert ia.leidas == []

    def test_si_la_ocr_no_puede_entra_la_ia_por_la_hoja_con_pistas(self):
        textos = {1: "ACTA DE VISITA", 2: "texto", 3: "Fecha: ____ día ___ mes ___ año"}
        local = _Lector({})
        ia = _Lector({3: "Fecha: 7 de junio de 2021"})
        hallada = AgenteDeFechas(releer=local, leer_con_ia=ia).buscar([1, 2, 3], textos)
        assert (hallada.fecha, hallada.pagina, hallada.via) == (date(2021, 6, 7), 3, "ia")
        assert ia.leidas == [3]

    def test_con_solo_ocr_no_se_gasta_ia(self):
        local = _Lector({})
        hallada = AgenteDeFechas(releer=local, leer_con_ia=None).buscar([1, 2], {1: "x", 2: "y"})
        assert hallada is None
        assert not AgenteDeFechas(releer=local).usa_ia

    def test_la_ia_tiene_tope_por_documento(self):
        ia = _Lector({})
        AgenteDeFechas(leer_con_ia=ia, max_hojas_con_ia=3).buscar(list(range(1, 21)), {})
        assert len(ia.leidas) == 3

    def test_la_cedula_no_fecha_el_documento(self):
        # Un acuerdo de pago con la cédula del deudor detrás (UPD2973859): la
        # fecha de la cédula no es la del acuerdo.
        textos = {1: "RECONOCIMIENTO DE DEUDA", 2: "CEDULA DE CIUDADANIA 12/03/2015"}
        ia = _Lector({1: "Magangué, 4 de abril de 2022"})
        hallada = AgenteDeFechas(
            leer_con_ia=ia, no_fecha=lambda texto: "CEDULA" in texto
        ).buscar([1, 2], textos)
        assert (hallada.fecha, hallada.pagina) == (date(2022, 4, 4), 1)

    def test_una_hoja_que_falla_no_tumba_la_busqueda(self):
        def rota(_pagina):
            raise OSError("la hoja no se deja dibujar")

        ia = _Lector({2: "12/03/2022"})
        hallada = AgenteDeFechas(releer=rota, leer_con_ia=ia).buscar([1, 2], {})
        assert hallada.fecha == date(2022, 3, 12)


class TestDondeSeBusca:
    def test_primero_las_pistas_luego_la_ultima_y_la_primera(self):
        textos = {1: "carta", 2: "texto", 3: "texto", 4: "Ciudad: fecha: día mes año"}
        assert candidatas([1, 2, 3, 4], textos) == [4, 1, 2, 3]
        assert candidatas([5, 6, 7], {}) == [7, 5, 6]


class TestLaFechaDeSuTramite:
    def test_primero_el_de_su_mismo_archivo(self):
        fechas = [date(2021, 1, 1), None, date(2021, 3, 3)]
        # La cédula (1) viaja en el archivo B con el reclamo (2).
        assert fecha_por_su_tramite(1, fechas, ["A", "B", "B"]) == (date(2021, 3, 3), 2)

    def test_si_no_el_mas_cercano_y_a_igual_distancia_el_anterior(self):
        fechas = [date(2021, 1, 1), None, date(2021, 3, 3)]
        assert fecha_por_su_tramite(1, fechas, ["A", "B", "C"]) == (date(2021, 1, 1), 0)

    def test_un_expediente_sin_ninguna_fecha(self):
        assert fecha_por_su_tramite(0, [None, None], ["A", "A"]) is None
