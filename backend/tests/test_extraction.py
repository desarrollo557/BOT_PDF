from resolutions.domain.extraction import extract_candidates


def codes(text):
    return [c.code.value for c in extract_candidates(text)]


class TestCodeCapture:
    def test_captures_the_code_next_to_the_anchor(self):
        assert codes("RESOLUCION N° 0412/2024") == ["0412/2024"]

    def test_captures_a_code_without_a_numbering_prefix(self):
        assert codes("RESOLUCION 0412/2024") == ["0412/2024"]

    def test_captures_a_code_after_a_colon(self):
        assert codes("RESOLUCION: 0412/2024") == ["0412/2024"]

    def test_falls_back_to_the_following_line_when_the_anchor_line_ends(self):
        # Centred headers routinely wrap. The code sits one line below the word.
        assert codes("RESOLUCION\n0412/2024") == ["0412/2024"]

    def test_accepts_alphanumeric_code_shapes(self):
        assert codes("RESOLUCION RES-2024-00123") == ["RES-2024-00123"]

    def test_ignores_the_anchor_when_no_plausible_code_follows(self):
        assert codes("RESOLUCION DE DIRECTORIO") == []

    def test_requires_digits_in_the_captured_token(self):
        assert codes("RESOLUCION N° SIN NUMERO") == []


class TestMultipleCandidates:
    def test_returns_every_candidate_on_the_page(self):
        text = (
            "RESOLUCION N° 0412/2024\n"
            "VISTO la Resolucion N° 0077/2023 y sus modificatorias\n"
            "CONSIDERANDO que la Resolucion N° 0099/2022 dispuso"
        )
        assert codes(text) == ["0412/2024", "0077/2023", "0099/2022"]

    def test_reports_positional_context_for_scoring(self):
        text = "RESOLUCION N° 0412/2024\nVISTO la Resolucion N° 0077/2023"
        first, second = extract_candidates(text)
        assert first.line_index == 0 and second.line_index == 1
        assert first.total_lines == 2
        assert "VISTO" in second.context_before
        assert first.context_before.strip() == ""
