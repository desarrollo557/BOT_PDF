from resolutions.domain.extraction import extract_candidates
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.scoring import select_best

HEADER_THEN_CITATIONS = (
    "RESOLUCION N° 0412/2024\n"
    "\n"
    "VISTO la Resolucion N° 0077/2023 y sus modificatorias, y\n"
    "CONSIDERANDO que por Resolucion N° 0099/2022 se aprobo el reglamento"
)


class TestDisambiguation:
    def test_the_header_wins_over_cited_resolutions(self):
        selection = select_best(extract_candidates(HEADER_THEN_CITATIONS))
        assert selection.code == ResolutionCode.parse("0412/2024")

    def test_a_citation_alone_still_loses_to_nothing_and_is_reported_weak(self):
        text = "VISTO la Resolucion N° 0077/2023 que aprobo el plan anual"
        selection = select_best(extract_candidates(text))
        assert selection.code == ResolutionCode.parse("0077/2023")
        assert selection.confidence < 0.5

    def test_returns_none_when_the_page_has_no_candidate(self):
        assert select_best(extract_candidates("ANEXO I - PLANILLA DE BIENES")) is None


class TestNeighbourTiebreak:
    def test_sequential_context_breaks_a_tie_between_equal_candidates(self):
        # Two citations of equal standing: the one matching the running group
        # is the honest answer, and it costs zero tokens to work that out.
        text = "Se remite copia de la Resolucion N° 0412/2024\ny de la Resolucion N° 0555/2024"
        blind = select_best(extract_candidates(text))
        hinted = select_best(extract_candidates(text), previous_code=ResolutionCode.parse("0555/2024"))
        assert blind.code == ResolutionCode.parse("0412/2024")
        assert hinted.code == ResolutionCode.parse("0555/2024")

    def test_the_hint_never_overrides_a_confident_header(self):
        selection = select_best(
            extract_candidates(HEADER_THEN_CITATIONS),
            previous_code=ResolutionCode.parse("0077/2023"),
        )
        assert selection.code == ResolutionCode.parse("0412/2024")


class TestAmbiguityFlag:
    def test_flags_a_page_whose_top_candidates_are_indistinguishable(self):
        text = "Se remite copia de la Resolucion N° 0412/2024\ny de la Resolucion N° 0555/2024"
        assert select_best(extract_candidates(text)).ambiguous is True

    def test_does_not_flag_a_clear_header(self):
        assert select_best(extract_candidates(HEADER_THEN_CITATIONS)).ambiguous is False
