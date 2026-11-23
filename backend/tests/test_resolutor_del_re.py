"""El agente que decide el RE sin certeza, y su auditor (2026-11-23).

El operador: «si son 1000 PDF, yo no voy a darle en confirmar a todos esos…
necesito que se corrijan solos, y se haga una auditoría sobre auditoría». Sin
certeza, el más probable, con su regla y su confianza. Los RE son inventados
con la forma de los de la corrida de Magangué.
"""

from __future__ import annotations

from datetime import date

from resolutions.domain.evidencia import Candidato
from resolutions.domain.resolutor_del_re import (
    BAJA,
    CERRADO,
    DECIDIDO,
    MEDIA,
    REVERTIDO,
    ContextoDelRe,
    Decision,
    auditar_la_decision,
    cerrar_la_revision,
    nombre_de_la_oficina,
    resolver_sin_certeza,
)
from resolutions.domain.sello import OFICINAS_QUE_RADICAN

RADICAN = frozenset(OFICINAS_QUE_RADICAN)


def _c(valor, motivo="leído tal cual", pagina=1):
    return Candidato(valor, motivo, pagina)


class TestLasReglas:
    def test_la_oficina_impresa_en_el_sello(self):
        # 6835194: el 8 a mano leído como 2 o 4; el sello dice «OFICINA SANTA ANA».
        candidatos = [
            _c("RE2673202100532", "leído tal cual: oficina 2673 leída por 8673: sería RE8673202100532"),
            _c("RE4673202100532", "leído tal cual: oficina 4673 leída por 8673: sería RE8673202100532"),
        ]
        assert nombre_de_la_oficina("CARIBEMAR DE LA COSTA\nOFICINA SANTA ANA\nBOLIVAR SUR") == "8673"
        decision = resolver_sin_certeza(candidatos, ContextoDelRe(oficinas_que_radican=RADICAN, oficina_del_sello="8673"))
        assert (decision.valor, decision.confianza) == ("RE8673202100532", MEDIA)

    def test_las_lecturas_convergen_al_corregir_la_oficina(self):
        # Dos lecturas distintas -- «RE2673…» y «RE4673…» -- que convergen en una.
        candidatos = [
            _c("RE2673202100532", "oficina 2673 leída por 8673: sería RE8673202100532"),
            _c("RE8673202100532", "leído RE2673202100532: oficina 2673 leída por 8673: sería RE8673202100532"),
            _c("RE4673202100532", "oficina 4673 leída por 8673: sería RE8673202100532"),
            _c("RE8673202170532", "corregido: oficina 8623 leída por 8673"),
        ]
        decision = resolver_sin_certeza(candidatos, ContextoDelRe(oficinas_que_radican=RADICAN))
        assert decision.valor == "RE8673202100532" and "convergen" in decision.regla

    def test_lo_leido_y_su_correccion_son_una_sola_lectura(self):
        candidatos = [
            _c("RE2673202100532", "oficina 2673 leída por 8673: sería RE8673202100532"),
            _c("RE8673202100532", "leído RE2673202100532: oficina 2673 leída por 8673: sería RE8673202100532"),
        ]
        decision = resolver_sin_certeza(candidatos, ContextoDelRe(oficinas_que_radican=RADICAN))
        assert decision.valor == "RE8673202100532" and decision.confianza == BAJA

    def test_el_reclamo_no_se_queda_con_lo_que_cita_ni_con_el_de_su_tramite(self):
        candidatos = [
            _c("RE2310202100771", "hallado en el barrido de la hoja: el reclamo cita RE de otras reclamaciones"),
            _c("RE2310202100777", "el de su trámite: ninguna hoja suya lo trae", None),
        ]
        contexto = ContextoDelRe(oficinas_que_radican=RADICAN, del_tramite="RE2310202100777", lleva_el_del_tramite=False)
        assert resolver_sin_certeza(candidatos, contexto) is None

    def test_la_oficina_de_la_prosa_no_cuenta(self):
        assert nombre_de_la_oficina("presenté la solicitud en la oficina de Santa Ana el martes") is None
        assert nombre_de_la_oficina("se radicó en la OFICINA SANTA ANA del pueblo") is None

    def test_el_que_se_lee_en_otra_hoja_de_la_caja(self):
        # 4251546: la pág. 1 lee 07144 y 01144; la respuesta de la pág. 2 lee 01144.
        candidatos = [_c("RE2311202107144", "los lectores leen RE distintos"), _c("RE2311202101144", "los lectores leen RE distintos")]
        contexto = ContextoDelRe(
            paginas=frozenset({1}),
            leidos={"RE2311202107144": frozenset({1}), "RE2311202101144": frozenset({1, 2})},
            oficinas_que_radican=RADICAN,
        )
        decision = resolver_sin_certeza(candidatos, contexto)
        assert (decision.valor, decision.confianza) == ("RE2311202101144", MEDIA)

    def test_la_notificacion_lleva_el_de_su_tramite(self):
        contexto = ContextoDelRe(del_tramite="RE2311202002109", lleva_el_del_tramite=True, oficinas_que_radican=RADICAN)
        decision = resolver_sin_certeza([_c("RE2311202002109", "el de su trámite: ninguna hoja suya lo trae", None)], contexto)
        assert (decision.valor, decision.regla) == ("RE2311202002109", "el RE de su trámite")

    def test_el_unico_candidato_va_tal_cual_con_confianza_baja(self):
        decision = resolver_sin_certeza([_c("RE9230202100160", "leído tal cual: la oficina 9230 no es ninguna que radique")], ContextoDelRe(oficinas_que_radican=RADICAN))
        assert (decision.valor, decision.confianza) == ("RE9230202100160", BAJA)

    def test_el_empate_se_decide_con_confianza_baja(self):
        candidatos = [_c("RE2310202408877", "los lectores leen RE distintos"), _c("RE2310202408897", "los lectores leen RE distintos")]
        decision = resolver_sin_certeza(candidatos, ContextoDelRe(oficinas_que_radican=RADICAN))
        assert decision.valor == "RE2310202408877" and decision.confianza == BAJA

    def test_sin_nada_no_decide(self):
        assert resolver_sin_certeza([], ContextoDelRe()) is None


class TestElAuditor:
    def test_sostiene_lo_que_cuadra(self):
        decision = Decision("RE8673202100532", "regla", MEDIA, "")
        assert auditar_la_decision(decision, ContextoDelRe(anio=2021, oficinas_que_radican=RADICAN)) is None

    def test_revierte_el_ano_que_no_es_el_de_la_hoja(self):
        decision = Decision("RE2310201900532", "regla", BAJA, "")
        assert "año" in auditar_la_decision(decision, ContextoDelRe(anio=2021, oficinas_que_radican=RADICAN))

    def test_revierte_el_re_de_otro_tramite(self):
        decision = Decision("RE2310202100100", "regla", BAJA, "")
        contexto = ContextoDelRe(anio=2021, oficinas_que_radican=RADICAN, de_otros_tramites=frozenset({"RE2310202100100"}))
        assert "otro trámite" in auditar_la_decision(decision, contexto)

    def test_un_ano_imposible(self):
        assert "imposible" in auditar_la_decision(Decision("RE2310209900532", "r", BAJA, ""), ContextoDelRe(), hoy=date(2026, 11, 23))


class TestElCierreDeLaRevision:
    def test_cada_aviso_dice_lo_que_hizo_el_agente(self):
        decision = {
            "page": 1, "paginas": [1, 2], "valor": "RE2310202408877", "regla": "el más votado", "confianza": BAJA,
            "auditor": "verificada por el auditor", "por_que": "leído …",
        }  # fmt: skip
        avisos = [
            {"page": 2, "reason": "trae sello de radicación al pie con el RE escrito a mano y la IA no lo leyó"},
            {"page": 5, "reason": "el radicado RE2310202108375 se diferencia en una cifra del RE2310202108374: confirmar"},
            {"page": 6, "reason": "la fecha del documento no se pudo leer en su hoja principal; va sin fecha"},
            {"page": 7, "reason": "folios del sello: su sello dice 7 folios y el documento tiene 1 hojas"},
            {"page": 8, "reason": "RE por confirmar: …"},
        ]
        cerrados = cerrar_la_revision(avisos, [decision], impresos=frozenset({"RE2310202108375", "RE2310202108374"}))
        assert [a["resuelto"]["accion"] for a in cerrados] == [DECIDIDO, CERRADO, CERRADO, CERRADO, CERRADO]
        assert "dos trámites distintos" in cerrados[1]["resuelto"]["conclusion"]
        assert "sin fecha" in cerrados[2]["resuelto"]["conclusion"]

    def test_la_revertida_por_el_auditor(self):
        decision = {"page": 1, "valor": None, "propuesto": "RE2310201900532", "auditor": "no la sostiene: año"}
        [aviso] = cerrar_la_revision([{"page": 1, "reason": "RE por confirmar: …"}], [decision])
        assert aviso["resuelto"]["accion"] == REVERTIDO
