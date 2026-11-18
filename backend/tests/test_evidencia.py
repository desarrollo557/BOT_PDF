"""La evidencia del RE: qué se cree, qué se propone y qué no es nada (el operador, 2026-11-18).

«NUNCA INVENTAR INFORMACIÓN»: un RE va al nombre sólo si sus hojas lo traen
tal cual -- una lectura basta para lo impreso, dos lectores distintos para la
letra a mano --. Lo que una regla corrigió y el RE de su trámite son
candidatos que confirma el operador en la Revisión.
"""

from __future__ import annotations

from resolutions.domain.evidencia import (
    Estado,
    EvidenciaDeRE,
    aparece_literal,
    decidir_el_re,
    res_en_la_lectura,
)

RE = "RE2310202402908"


class TestLoLiteral:
    def test_las_trece_cifras_con_los_blancos_del_escaner(self):
        assert aparece_literal(RE, "No DE RADICACION: RE 2310 2024 02908")
        assert aparece_literal(RE, "NUMERORF2310-2024.02908 Folios")
        assert aparece_literal("RE9233202300708", "RE: RE9233202300-708")

    def test_ni_una_cifra_de_mas_ni_letras_por_cifras(self):
        # 1005122: «RE28102024102908» no trae RE2810202410290 dentro.
        assert aparece_literal("RE2810202410290", "DIR. NOTIFICACION: RE28102024102908") is None
        assert aparece_literal("RE8673202203446", "N° PQR: RE86732022b3446") is None

    def test_los_re_de_una_lectura_tal_cual(self):
        assert res_en_la_lectura("No. DE RADICACION: 202460129497\nRE: RE2310202409991") == ["RE2310202409991"]
        assert res_en_la_lectura("RE: RE 2310 2024 09991") == ["RE2310202409991"]
        # El número interno de doce cifras no es un RE.
        assert res_en_la_lectura("No. DE RADICACION: RE202460129497") == []


def _tinta(*lecturas: tuple[str, str], propuesto: str | None = RE, correccion: str | None = None) -> EvidenciaDeRE:
    return EvidenciaDeRE(4, "sello de tinta", propuesto, tuple(lecturas), correccion)


class TestLaRegla:
    def test_lo_impreso_se_cree_con_una_lectura(self):
        hallazgo = decidir_el_re(
            [EvidenciaDeRE(1, "etiqueta impresa", RE, (("capa", f"AL CONTESTAR CITE ESTE NUMERO {RE}"),))]
        )
        assert (hallazgo.estado, hallazgo.valor, hallazgo.lectores) == (Estado.ENCONTRADO, RE, ("capa",))
        assert RE[2:] in hallazgo.fragmento and hallazgo.pagina == 1

    def test_la_letra_a_mano_con_dos_lectores_es_verificada(self):
        hallazgo = decidir_el_re([_tinta(("ocr de pago", f"RE {RE[2:]}"), ("visión", f"RE: {RE}"))])
        assert (hallazgo.estado, hallazgo.valor) == (Estado.VERIFICADO, RE)
        assert hallazgo.lectores == ("ocr de pago", "visión") and hallazgo.valor_original == f"RE {RE[2:]}"

    def test_dos_lecturas_del_mismo_motor_no_son_dos_lectores(self):
        hallazgo = decidir_el_re([_tinta(("tesseract", RE), ("relectura", RE))])
        assert hallazgo.estado is Estado.REQUIERE_VALIDACION

    def test_la_letra_a_mano_de_un_solo_lector_es_un_candidato(self):
        # 1001051: la visión leyó RE8673202103319, el OCR «RE86732021033A».
        hallazgo = decidir_el_re(
            [
                _tinta(
                    ("ocr de pago", "No DE RADICACION: RE 86732021033A"),
                    ("visión", "RE: RE8673202103319"),
                    propuesto=None,
                )
            ]
        )
        assert hallazgo.estado is Estado.REQUIERE_VALIDACION and hallazgo.valor is None
        assert [(c.valor, c.motivo) for c in hallazgo.candidatos] == [
            ("RE8673202103319", "letra a mano leída por un solo lector (visión)")
        ]

    def test_lo_corregido_es_un_candidato_con_su_correccion(self):
        # 1005122: «RE28102024102908» casado con el RE del recurso.
        hallazgo = decidir_el_re(
            [
                _tinta(
                    ("ocr de pago", "DIR. NOTIFICACION: RE28102024102908"),
                    ("visión", "RE: R2810202402908"),
                    correccion="la oficina a una cifra de un RE de la caja",
                )
            ]
        )
        assert hallazgo.estado is Estado.REQUIERE_VALIDACION
        assert hallazgo.candidatos[0].valor == RE
        assert hallazgo.candidatos[0].motivo == "corregido: la oficina a una cifra de un RE de la caja"

    def test_lo_que_no_puede_ser_un_re_no_es_ni_candidato(self):
        def valido(valor, _evidencia):
            return None if valor[2:6] == "2310" else f"la oficina {valor[2:6]} no es ninguna que radique"

        hallazgo = decidir_el_re(
            [_tinta(("ocr de pago", "No DE RADICACION: RE2024600387419"), ("visión", "RE: no hay"), propuesto=None)],
            valido=valido,
        )
        assert hallazgo.estado is Estado.NO_ENCONTRADO and not hallazgo.candidatos

    def test_el_re_de_su_tramite_es_solo_un_candidato(self):
        hallazgo = decidir_el_re([], del_tramite=RE, buscado="sello y etiqueta en las hojas 3")
        assert hallazgo.estado is Estado.REQUIERE_VALIDACION
        assert hallazgo.candidatos[0].motivo == "el de su trámite: ninguna hoja suya lo trae"
        # Y si una hoja suya lo trae, se cree por ella.
        con_etiqueta = decidir_el_re(
            [EvidenciaDeRE(3, "etiqueta impresa", RE, (("capa", f"NUMERO {RE}"),))], del_tramite=RE
        )
        assert con_etiqueta.se_cree and not con_etiqueta.candidatos

    def test_sin_nada_no_encontrado_con_lo_que_se_busco(self):
        hallazgo = decidir_el_re([], buscado="sello y etiqueta en las hojas 1, 2")
        assert (hallazgo.estado, hallazgo.buscado) == (Estado.NO_ENCONTRADO, "sello y etiqueta en las hojas 1, 2")
        assert hallazgo.as_dict()["estado"] == "no encontrado"
