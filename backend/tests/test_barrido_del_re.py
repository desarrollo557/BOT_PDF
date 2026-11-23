"""El barrido de la hoja: el RE que no se halló se busca en la hoja entera (2026-11-23).

El operador, ante 1000186 (el recurso con el RE a mano en la casilla de los
folios del sello al pie): «cuando no se encuentre el RE, que se busque en toda
la página las letras RE con números seguido»; «cuando no exista el RE, que de
verdad el bot se asegure muy bien». Lo hallado se cree con dos lectores o
casado con un RE impreso en otra hoja de la caja; nunca el que la hoja cita.
Los RE y los nombres son inventados.
"""

from __future__ import annotations

from datetime import date

from resolutions.domain.evidencia import (
    BARRIDO,
    Estado,
    decidir_el_re,
    evidencias_del_barrido,
    lecturas_sin_citas,
    res_en_la_lectura,
)

RE = "RE2310202007709"
#: La constancia de la caja, en otra hoja, que trae impreso el mismo RE.
IMPRESO = {RE: [(3, date(2020, 11, 9))]}


def _decidir(lecturas, impresos=None, *, reclamo=False, fecha=None):
    return decidir_el_re(evidencias_del_barrido(1, lecturas, impresos or {}, fecha=fecha, solo_candidato=reclamo))


class TestLoQueSeCree:
    def test_dos_lectores_lo_leen_igual(self):
        hallazgo = _decidir([("ocr de pago", f"N° de folios: {RE}"), ("visión", f"{RE} | sello | N° de folios")])
        assert hallazgo.se_cree and hallazgo.valor == RE and hallazgo.metodo == BARRIDO

    def test_uno_solo_si_es_el_impreso_de_la_caja(self):
        hallazgo = _decidir([("visión", f"{RE} | sello | N° de folios")], IMPRESO)
        assert hallazgo.se_cree and hallazgo.valor == RE

    def test_la_letra_a_mano_mal_leida_casa_con_el_impreso(self):
        lecturas = [("ocr de pago", "folios: RE23102020077O9"), ("visión", "RE231020200T709 | sello")]
        hallazgo = _decidir(lecturas, IMPRESO, fecha=date(2020, 11, 9))
        assert hallazgo.se_cree and hallazgo.valor == RE
        # Impreso antes de la fecha de la hoja: no es de su trámite, sólo se propone.
        assert not _decidir(lecturas, IMPRESO, fecha=date(2020, 11, 13)).se_cree


class TestLoQueNoSeCree:
    def test_uno_solo_sin_nada_que_lo_confirme_es_candidato(self):
        hallazgo = _decidir([("visión", f"{RE} | margen | a mano")])
        assert not hallazgo.se_cree and hallazgo.estado is Estado.REQUIERE_VALIDACION
        assert hallazgo.candidatos[0].valor == RE and "barrido" in hallazgo.candidatos[0].motivo

    def test_el_que_la_hoja_cita_no_cuenta(self):
        cita = f"para que revoque la decisión tomada por la empresa a través del Consecutivo No. {RE} de fecha"
        assert not any(res_en_la_lectura(t) for _, t in lecturas_sin_citas([("capa", cita)]))
        # Con el salto de renglón entre «radicado» y el RE (6834372 pág. 1).
        partida = "hacer conocer de la reclamación, reclamo radicado\nRE-2310202404804 por concepto de irregularidad"
        assert not any(res_en_la_lectura(t) for _, t in lecturas_sin_citas([("capa", partida)]))
        # El del sello, en su casilla, se queda.
        sello = "FECHA DE RECIBO: 29-04-2024\nN DE RADICACION: 2024600115257\nN DE FOLIOS: RE2310202408897"
        assert res_en_la_lectura(lecturas_sin_citas([("ocr de pago", sello)])[0][1]) == ["RE2310202408897"]
        hallazgo = _decidir([("capa", cita), ("ocr de pago", cita)], IMPRESO)
        assert not hallazgo.se_cree and hallazgo.estado is Estado.NO_ENCONTRADO

    def test_en_el_reclamo_solo_se_propone(self):
        hallazgo = _decidir([("ocr de pago", RE), ("visión", RE)], IMPRESO, reclamo=True)
        assert not hallazgo.se_cree and hallazgo.candidatos[0].valor == RE

    def test_sin_ningun_re_no_hay_nada(self):
        assert _decidir([("capa", "Atentamente, MARIA PEREZ")]).estado is Estado.NO_ENCONTRADO


class TestElSelloAlPie:
    def test_las_senales_del_sello_con_la_tinta_realzada(self):
        from resolutions.application.sellos import parece_un_sello

        # Lo que Tesseract dejó del sello al pie de 1000186 pág. 1.
        realzado = "RECIBIDO ÑO. IMPLICA ASEPTACION $ . YE. Dir. Notific: 2 ub do Funcionario Receptan ap"
        assert parece_un_sello(realzado)
        assert not parece_un_sello("Atentamente, FIRMA Y C.C. Celular")


class TestLaCitaYLoPropio:
    """La revisión del 2026-11-23: lo que el filtro de citas borra y lo que conserva."""

    def _quedan(self, texto):
        return [v for _, t in lecturas_sin_citas([("lector", texto)]) for v in res_en_la_lectura(t)]

    def test_borra_las_citas(self):
        assert self._quedan("reclamación, reclamo radicado\nRE-2310202404804 por concepto de irregularidad") == []
        assert self._quedan("revoque la decisión a través del Consecutivo No. R$2310202008827 de fecha") == []
        assert self._quedan("RE2310202404804 | texto | reclamo radicado RE-2310202404804") == []

    def test_conserva_lo_propio(self):
        constancia = "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION\nN° PQR: RE2310202406735 FECHA: 08/09/2021"
        assert self._quedan(constancia) == ["RE2310202406735"]
        vision = "RE2310202404804 | texto | reclamo radicado RE-2310202404804\nRE2310202408897 | sello | N de folios"
        assert self._quedan(vision) == ["RE2310202408897"]
        assert self._quedan("Radicado No. RE2311202101144") == ["RE2311202101144"]
