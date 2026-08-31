from resolutions.domain.title import extract_title, slugify


class TestSubjectMarkers:
    def test_reads_the_subject_line_when_the_document_declares_one(self):
        text = "RESOLUCION N° 0412/2024\nASUNTO: Aprobación del reglamento interno\nVISTO el expediente"
        assert extract_title(text) == "Aprobación del reglamento interno"

    def test_accepts_the_usual_marker_variants(self):
        for marker in ("ASUNTO", "REFERENCIA", "REF", "OBJETO", "TEMA", "MOTIVO"):
            text = f"RESOLUCION N° 0412/2024\n{marker}: Designación de personal transitorio"
            assert extract_title(text) == "Designación de personal transitorio", marker

    def test_accepts_a_dash_separator(self):
        text = "RESOLUCION N° 0412/2024\nASUNTO - Compra de insumos informáticos"
        assert extract_title(text) == "Compra de insumos informáticos"


class TestFallbackToTheCaptionLine:
    def test_takes_the_first_substantive_line_after_the_header(self):
        text = "RESOLUCION N° 0412/2024\nDesignación de personal transitorio\nVISTO el expediente"
        assert extract_title(text) == "Designación de personal transitorio"

    def test_skips_citation_openings(self):
        text = "RESOLUCION N° 0412/2024\nVISTO el expediente 44/2024 y sus antecedentes"
        assert extract_title(text) is None

    def test_skips_datelines(self):
        text = "RESOLUCION N° 0412/2024\nBuenos Aires, 12 de marzo de 2024\nCompra de insumos"
        assert extract_title(text) == "Compra de insumos"

    def test_skips_folio_and_page_furniture(self):
        text = "RESOLUCION N° 0412/2024\nPágina 1 de 12 del expediente\nCompra de insumos"
        assert extract_title(text) == "Compra de insumos"

    def test_ignores_fragments_too_short_to_be_a_title(self):
        text = "RESOLUCION N° 0412/2024\nDIRECCION\nCompra de insumos informáticos"
        assert extract_title(text) == "Compra de insumos informáticos"

    def test_skips_recital_openings(self):
        # "Que ..." opens every recital in Spanish administrative drafting, so a
        # line starting with it is body text no matter how title-shaped it looks.
        text = "RESOLUCION N° 0412/2024\nQue la presente medida se dicta en uso de las facultades"
        assert extract_title(text) is None

    def test_returns_none_when_the_page_offers_nothing(self):
        assert extract_title("RESOLUCION N° 0412/2024") is None
        assert extract_title("") is None


class TestBoundaries:
    def test_stops_scanning_a_few_lines_past_the_header(self):
        text = "RESOLUCION N° 0412/2024\n" + "\n".join(["VISTO lo actuado"] * 10) + "\nCompra de insumos"
        assert extract_title(text) is None

    def test_truncates_a_runaway_line_on_a_word_boundary(self):
        long_title = " ".join(["palabra"] * 60)
        title = extract_title(f"RESOLUCION N° 0412/2024\n{long_title}")
        assert title is not None
        assert len(title) <= 120
        assert not title.endswith("palab")


class TestSlugify:
    def test_produces_a_filesystem_safe_fragment(self):
        assert slugify("Aprobación del reglamento interno") == "aprobacion-del-reglamento-interno"

    def test_collapses_punctuation_and_repeated_separators(self):
        assert slugify("Compra   de   insumos: informáticos / 2024") == "compra-de-insumos-informaticos-2024"

    def test_truncates_without_leaving_a_trailing_separator(self):
        slug = slugify(" ".join(["palabra"] * 30), max_length=20)
        assert len(slug) <= 20
        assert not slug.endswith("-")

    def test_returns_an_empty_string_for_unusable_input(self):
        assert slugify("///") == ""
        assert slugify("") == ""
