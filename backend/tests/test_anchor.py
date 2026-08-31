from resolutions.domain.anchor import find_anchors, fold_ocr_confusions, normalize


class TestNormalization:
    def test_uppercases_and_strips_accents(self):
        assert normalize("Resolución") == "RESOLUCION"

    def test_collapses_whitespace(self):
        assert normalize("  RES   OLUCION  ") == "RES OLUCION"


class TestOcrConfusionFolding:
    def test_folds_digits_that_look_like_letters(self):
        assert fold_ocr_confusions("RES0LUCI0N") == "RESOLUCION"
        assert fold_ocr_confusions("RESOLUC1ON") == "RESOLUCION"
        assert fold_ocr_confusions("RE5OLUCION") == "RESOLUCION"

    def test_folds_the_rn_to_m_pair(self):
        assert fold_ocr_confusions("NURNERO") == "NUMERO"

    def test_leaves_clean_text_untouched(self):
        assert fold_ocr_confusions("RESOLUCION") == "RESOLUCION"


class TestAnchorDetection:
    def test_finds_a_clean_anchor(self):
        anchors = find_anchors("RESOLUCION N° 0412/2024")
        assert [a.matched_text for a in anchors] == ["RESOLUCION"]
        assert anchors[0].line_index == 0
        assert anchors[0].distance == 0

    def test_finds_an_accented_anchor(self):
        assert len(find_anchors("Resolución N° 0412/2024")) == 1

    def test_finds_anchors_mangled_by_ocr(self):
        # This is the whole point of the fuzzy matcher: an exact regex loses
        # every one of these lines, and they are the common case on scans.
        for line in ["RES0LUCI0N", "RESOLUCLON", "RESOLUCION", "RESOLUCIQN", "RESQLUCION"]:
            assert find_anchors(f"{line} N° 0412/2024"), line

    def test_matches_common_abbreviations(self):
        assert find_anchors("RESOL. N° 0412/2024")
        assert find_anchors("RES. N° 0412/2024")

    def test_reports_the_line_index_of_every_anchor(self):
        text = "ACTA DE SESION\nVISTO la Resolucion N° 0077/2023\nRESOLUCION N° 0412/2024"
        anchors = find_anchors(text)
        assert [a.line_index for a in anchors] == [1, 2]

    def test_ignores_words_that_merely_start_alike(self):
        assert find_anchors("RESPUESTA AL RECLAMO") == []
        assert find_anchors("RESERVA DE DERECHOS") == []

    def test_ignores_text_without_any_anchor(self):
        assert find_anchors("CONSIDERANDO QUE EL EXPEDIENTE 44 SE ENCUENTRA") == []
