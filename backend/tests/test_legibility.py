"""Capa de texto que existe y aun así no se puede leer.

Todos los textos de estas pruebas están copiados de páginas reales de
"RESOLUCIONES 00072-00094.pdf", incluida la fuente decorativa que devuelve
`<^OLVCIÓ?{%` donde el papel dice RESOLUCIÓN. Un caso inventado no habría
mostrado que los dígitos sobreviven mientras las letras no, que es justamente
lo que hacía que la página pasara por buena.
"""

from resolutions.domain.anchor import find_anchors
from resolutions.domain.extraction import extract_candidates
from resolutions.domain.legibility import (
    GARBLED_PER_THOUSAND,
    MIN_INTERIOR_CAPITALS,
    garble_score,
    interior_capitals,
    is_garbled,
)

#: Página 18, tal como la devuelve la capa de texto. 2.432 caracteres, así que
#: superaba de sobra el umbral de longitud y se daba por leída.
PAGINA_18 = "\n".join(
    (
        "Universidad ",
        "de Cartagena",
        "Fundada en 1827",
        "UNICARTAGENA",
        "BICENTENARIA",
        "<^OLVCIÓ?{% 00074",
        "<EL <B^cro%<iyE LA Vm^E^WA^D (DE CA(SX^gE?{A",
        "(Ert uso de sus facultades íegaíes,",
        "CO^SKDEWfDO:",
        "A) Que eC día 28 de enero de 2023, faCíeció en [a ciudad de (BarranquiCCa eC maestro Ado fo ",
        "(Rgfaeí (Pacfeco Anido, jugCar mayor de Los Montes de María y eC más reconocido de Cos ",
        "compositores de Cas saSanas deCQran (BoCívar.",
        "(B) Que, en eCaño 1983, eCmaestro Ado fo (RafaeC(Pacheco AniíCb se graduó como ahogado ",
        "en Ca PacuCtad de (Derecho de Ca Universidad de Cartagena, y su paso por nuestra Ahma ",
        "Máter nos dejó Ca evidencia de sus inmensas caCidades humanas, artísticas y académicas, y ",
    )
)

#: Página 20 del mismo documento: la misma clase de resolución, con la fuente
#: bien mapeada. Es el control -- si la señal la marcara, marcaría el documento
#: entero.
PAGINA_20 = "\n".join(
    (
        "Universidad ",
        "de Cartagena",
        "Fundada en 1827",
        "UNICARTAGENA",
        "BICENTENARIA",
        "RESOLUCIÓN No 00075 DE 2023",
        "Por la cual se designa editor de la Revista INGE-NOVA al profesor Miguel Ángel Mueses",
        "EL RECTOR DE LA UNIVERSIDAD DE CARTAGENA",
        "En uso de sus facultades legales y estatutarias, y",
        "CONSIDERANDO:",
        "Que el Consejo Académico, en sesión del 15 de febrero de 2023, recomendó la ",
        "designación del profesor Miguel Ángel Mueses como editor de la revista.",
        "Que la Vicerrectoría de Investigaciones avaló la hoja de vida del docente.",
        "RESUELVE:",
        "Artículo 1. Designar al profesor Miguel Ángel Mueses como editor de la Revista.",
    )
)


class TestLaSenal:
    def test_una_pagina_bien_decodificada_casi_no_la_dispara(self):
        assert interior_capitals(PAGINA_20) <= 2
        assert garble_score(PAGINA_20) < GARBLED_PER_THOUSAND

    def test_una_pagina_mal_decodificada_la_dispara_de_sobra(self):
        assert garble_score(PAGINA_18) > 2 * GARBLED_PER_THOUSAND

    def test_separa_las_dos(self):
        assert is_garbled(PAGINA_18) is True
        assert is_garbled(PAGINA_20) is False


class TestElRuido:
    def test_un_texto_corto_no_se_condena_por_la_proporcion(self):
        # Tres nombres propios pegados en una página de doscientos caracteres
        # dan una proporción altísima y no tienen nada de malo. El mínimo
        # absoluto de golpes es lo que los deja fuera.
        corto = "aB " * (MIN_INTERIOR_CAPITALS - 1)
        assert interior_capitals(corto) < MIN_INTERIOR_CAPITALS
        assert is_garbled(corto) is False

    def test_un_texto_largo_y_sano_no_se_condena_por_el_recuento(self):
        # Cincuenta golpes en cien mil caracteres son medio por mil: mucho
        # recuento y ninguna sospecha.
        largo = ("Que el Consejo Académico recomendó la designación del profesor. " * 1600) + (
            "aB " * 50
        )
        assert interior_capitals(largo) >= MIN_INTERIOR_CAPITALS
        assert is_garbled(largo) is False

    def test_un_texto_vacio_no_es_ilegible_sino_inexistente(self):
        assert is_garbled("") is False
        assert garble_score("") == 0.0


class TestLoQueSeEscondia:
    """Por qué la página pasaba por buena: no es que fallara, es que no se veía."""

    def test_la_capa_de_texto_no_deja_ver_la_palabra(self):
        assert find_anchors(PAGINA_18) == []
        assert extract_candidates(PAGINA_18) == []

    def test_los_digitos_sobreviven_aunque_las_letras_no(self):
        # Es lo que hace el fallo tan silencioso: el número está ahí, entero,
        # pero sin la palabra delante nadie lo reconoce como un encabezado.
        assert "00074" in PAGINA_18

    def test_la_misma_pagina_bien_decodificada_si_se_lee(self):
        candidatos = extract_candidates(PAGINA_20)
        assert [c.code.value for c in candidatos] == ["00075"]
        assert candidatos[0].official_form is True


# -----------------------------------------------------------------------------
#  La cascada
# -----------------------------------------------------------------------------
#  El detector sólo sirve si cambia lo que hace el sistema. Antes de esto, una
#  página con la capa de texto mal decodificada se aceptaba por tener texto de
#  sobra, no se le encontraba encabezado, y se daba por una continuación: sus
#  páginas heredaban en silencio el número de la resolución anterior. En
#  "RESOLUCIONES 00072-00094.pdf" eso hacía desaparecer la resolución 00074
#  entera, y el nombre del archivo prometía una serie que no estaba completa.
# -----------------------------------------------------------------------------

from fakes import FakeOcr, FakePage, FakePageSource  # noqa: E402

from resolutions.application.pipeline import PageAnalyzer, PipelineConfig  # noqa: E402
from resolutions.domain.page import Provenance  # noqa: E402

CUERPO_SANO = (
    "EL RECTOR DE LA UNIVERSIDAD DE CARTAGENA, en uso de sus facultades legales "
    "y estatutarias, y CONSIDERANDO: Que el Consejo Académico recomendó la "
    "designación del profesor como editor de la revista institucional."
)


def _analizar(page: FakePage) -> tuple:
    fuente = FakePageSource(pages=[page])
    analizador = PageAnalyzer(FakeOcr(), PipelineConfig())
    return analizador.analyse(fuente, 1), fuente


class TestLaCascadaConTextoMalDecodificado:
    def test_una_pagina_sana_se_resuelve_gratis(self):
        analisis, fuente = _analizar(
            FakePage(text=f"RESOLUCION No 00075 DE 2023\n{CUERPO_SANO}")
        )
        assert analisis.provenance is Provenance.TEXT_LAYER
        assert analisis.mis_decoded is False
        # Ni un solo renderizado: es el peldaño que no cuesta nada.
        assert fuente.renders == []
        assert [c.code.value for c in analisis.candidates] == ["00075"]

    def test_una_pagina_mal_decodificada_baja_a_mirar_la_imagen(self):
        analisis, fuente = _analizar(
            FakePage(text=PAGINA_18, header="RESOLUCIÓN N. 00074")
        )
        assert analisis.mis_decoded is True
        assert analisis.provenance is Provenance.OCR_REGION
        assert fuente.band_renders == 1

    def test_y_recupera_el_numero_que_la_capa_de_texto_escondia(self):
        analisis, _ = _analizar(FakePage(text=PAGINA_18, header="RESOLUCIÓN N. 00074"))
        assert [c.code.value for c in analisis.candidates] == ["00074"]
        assert analisis.candidates[0].official_form is True

    def test_sin_el_detector_la_pagina_habria_pasado_por_continuacion(self):
        # La prueba de que el fallo era silencioso: el texto supera de sobra el
        # umbral de longitud, así que nada en la longitud lo delataba.
        assert len(PAGINA_18) >= PipelineConfig().min_text_layer_chars
        assert extract_candidates(PAGINA_18) == []

    def test_lo_declara_para_que_pueda_contarse(self):
        # Que un PDF llegue así es un problema del documento de origen, no del
        # proceso, y quien lo reciba tiene que poder saberlo.
        analisis, _ = _analizar(FakePage(text=PAGINA_18, header="RESOLUCIÓN N. 00074"))
        assert analisis.mis_decoded is True
