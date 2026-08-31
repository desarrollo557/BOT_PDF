"""RF-01: sólo un encabezado oficial abre una resolución.

Tomado de un expediente real de 222 páginas, ``RESOLUCIONES 00072-00094.pdf``,
donde el software abría 34 resoluciones y hay unas 20. Las de más nacían de
números citados en el cuerpo del texto -- ``1968``, ``C0037``, ``01488`` -- que
por sí solos superaban el umbral de confianza. Una de ellas se llevó 59 páginas
que pertenecían a otras resoluciones.

La forma oficial ya sumaba puntos antes de esto. Sumar no alcanzaba: cuando el
error parte un documento por la mitad, la forma oficial tiene que ser una
condición y no una ventaja.
"""

from __future__ import annotations

from resolutions.domain.extraction import extract_candidates
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.scoring import CONFIDENT_FLOOR, opens_a_resolution, select_best


def code(value: str) -> ResolutionCode:
    parsed = ResolutionCode.try_parse(value)
    assert parsed is not None, value
    return parsed


def elegir(text: str, previous: str | None = None):
    return select_best(
        extract_candidates(text),
        previous_code=code(previous) if previous else None,
    )


class TestLoQueAbreYLoQueNo:
    def test_un_encabezado_oficial_abre_una_resolucion_nueva(self):
        seleccion = elegir("RESOLUCIÓN No. 00083 de 2023", previous="00072")

        assert seleccion is not None
        assert seleccion.code.value == "00083"
        assert not seleccion.ambiguous

    def test_los_tres_formatos_reales_de_la_casa_abren_igual(self):
        for texto, esperado in (
            ("RESOLUCION NO. 00086", "00086"),
            ("Resolución No. 00072 de 2023", "00072"),
            ("RESOLUCIÓN No. 00083 de 2023", "00083"),
        ):
            seleccion = elegir(texto, previous="00060")
            assert seleccion is not None, texto
            assert seleccion.code.value == esperado, texto

    def test_una_cita_en_el_cuerpo_no_abre_nada(self):
        # El caso que se llevó 59 páginas: una referencia a otra resolución
        # dentro de un considerando.
        seleccion = elegir(
            "Que mediante Resolución 1968 de 2018 el Ministerio de Educación\n"
            "Nacional otorgó el registro calificado del programa",
            previous="00072",
        )

        assert seleccion is not None
        assert seleccion.code.value == "00072", "la página continúa la resolución anterior"

    def test_un_numero_sin_token_de_numeracion_no_abre_nada(self):
        seleccion = elegir("Resolución 01488 del Consejo Académico", previous="00072")

        assert seleccion is not None
        assert seleccion.code.value == "00072"

    def test_seguir_con_el_mismo_numero_no_es_abrir(self):
        # Una resolución larga repite su propio encabezado en cada página; eso
        # confirma dónde sigue, no abre nada.
        seleccion = elegir("RESOLUCIÓN No. 00072 de 2023", previous="00072")

        assert seleccion is not None
        assert seleccion.code.value == "00072"


class TestLoQueSeMandaARevision:
    def test_algo_que_parecia_encabezado_se_adjunta_pero_queda_marcado(self):
        """Un encabezado al que se le perdió el "No." en el OCR.

        Se adjunta a la anterior -- la regla es la regla -- pero no en silencio:
        la decisión es discutible y tiene que verla una persona.
        """
        seleccion = elegir("RESOLUCIÓN 00083", previous="00072")

        assert seleccion is not None
        assert seleccion.code.value == "00072"
        assert seleccion.ambiguous, "tiene que llegar a la cola de revisión"
        assert seleccion.runner_up is not None
        assert seleccion.runner_up.value == "00083", "queda dicho qué se descartó"

    def test_una_cita_clara_se_adjunta_sin_molestar_a_nadie(self):
        seleccion = elegir(
            "Que mediante Resolución 1968 de 2018 el Ministerio de Educación\n"
            "Nacional otorgó el registro calificado del programa",
            previous="00072",
        )

        assert seleccion is not None
        assert not seleccion.ambiguous, "no hay nada que revisar en una cita del cuerpo"

    def test_la_confianza_baja_cuanto_mas_se_parecia_a_un_encabezado(self):
        parecido = elegir("RESOLUCIÓN 00083", previous="00072")
        cita = elegir(
            "Que mediante Resolución 1968 de 2018 el Ministerio otorgó el registro",
            previous="00072",
        )

        assert parecido is not None and cita is not None
        assert parecido.confidence < cita.confidence


class TestElComienzoDelDocumento:
    def test_sin_nada_que_continuar_el_documento_empieza_igual(self):
        # No hay resolución anterior a la que adjuntar: la primera página tiene
        # que abrir algo o las páginas se quedan sin dueño.
        seleccion = elegir("Resolución 01488 del Consejo Académico", previous=None)

        assert seleccion is not None
        assert seleccion.code.value == "01488"

    def test_con_las_dos_formas_presentes_gana_la_oficial(self):
        seleccion = elegir(
            "RESOLUCIÓN No. 00072 de 2023\n"
            "Que mediante Resolución 1968 de 2018 el Ministerio de Educación",
            previous=None,
        )

        assert seleccion is not None
        assert seleccion.code.value == "00072"


class TestLaReglaPorSiSola:
    def test_reconoce_la_forma_oficial(self):
        candidatas = extract_candidates("RESOLUCIÓN No. 00083 de 2023")
        assert candidatas and opens_a_resolution(candidatas[0])

    def test_rechaza_el_numero_suelto(self):
        candidatas = extract_candidates("Resolución 01488 del Consejo Académico")
        assert candidatas and not opens_a_resolution(candidatas[0])

    def test_rechaza_la_forma_oficial_usada_dentro_de_una_cita(self):
        # "MEDIANTE" delante convierte el encabezado en referencia a otra.
        candidatas = extract_candidates(
            "Que MEDIANTE Resolución No. 01488 de 2022 se autorizó lo anterior"
        )
        assert candidatas and not opens_a_resolution(candidatas[0])


def test_el_umbral_de_confianza_sigue_siendo_el_mismo():
    # RF-01 no cambia el umbral: cambia qué se le permite superarlo.
    assert CONFIDENT_FLOOR == 0.60


class TestElMembrete:
    """El membrete de la Universidad, tal como sale del PDF real.

    Aparece impreso en decenas de páginas del expediente. Trae ancla, token de
    numeración y número, así que cumplía la forma oficial y se llevó 68 páginas
    que pertenecían a otras resoluciones. Lo que lo delata es que el ancla va a
    mitad de renglón, detrás de "Acreditación en Alta Calidad".
    """

    MEMBRETE = (
        "Oficina Asesora de Planeación\n"
        "Acreditación en Alta Calidad Resolución\n"
        "No, 1968 dei 12 de feorerc de 2018, MEN.\n"
        "LA SUSCRITA JEFE DE LA OFICINA ASESORA DE PLANEACIÓN\n"
        "CERTIFICA:"
    )

    def test_el_membrete_no_abre_una_resolucion(self):
        seleccion = elegir(self.MEMBRETE, previous="00072")

        assert seleccion is not None
        assert seleccion.code.value == "00072", "las páginas siguen siendo de la anterior"

    def test_ninguna_candidata_del_membrete_abre_nada(self):
        for candidata in extract_candidates(self.MEMBRETE):
            assert not opens_a_resolution(candidata), candidata.line_text

    def test_un_encabezado_de_verdad_empieza_el_renglon(self):
        # La diferencia no está en cómo se escribe el número sino en dónde está.
        candidatas = extract_candidates("RESOLUCIÓN No. 00083 de 2023")
        assert candidatas and candidatas[0].anchor.start == 0
        assert opens_a_resolution(candidatas[0])

    def test_los_tres_formatos_de_la_casa_empiezan_el_renglon(self):
        for texto in (
            "RESOLUCION NO. 00086",
            "Resolución No. 00072 de 2023",
            "RESOLUCIÓN No. 00083 de 2023",
        ):
            candidatas = extract_candidates(texto)
            assert candidatas and opens_a_resolution(candidatas[0]), texto

    def test_el_membrete_no_ensucia_la_cola_de_revision(self):
        """Se rechaza por su estructura, y eso no es una duda.

        Aparece en decenas de páginas y se rechaza por la misma razón todas las
        veces. Marcarlo mandaba 39 páginas a revisión donde había 8 dudas
        reales, y una cola llena de ruido es una cola que nadie mira.
        """
        seleccion = elegir(self.MEMBRETE, previous="00072")

        assert seleccion is not None
        assert not seleccion.ambiguous
