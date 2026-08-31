"""The house header format, taken from real documents.

Every header in the corpus is written one of these three ways::

    RESOLUCION NO. 00086
    Resolución No. 00072 de 2023
    RESOLUCIÓN No. 00083 de 2023

Accents, casing and the trailing year vary; the anchor, the numbering token and
the zero-padded number do not. These tests pin that structure, because it is
what decides where one output PDF ends and the next begins.
"""

from resolutions.domain.extraction import extract_candidates
from resolutions.domain.grouping import GroupingEngine
from resolutions.domain.page import PageClassification
from resolutions.domain.scoring import CONFIDENT_FLOOR, select_best

REAL_HEADERS = [
    ("RESOLUCION NO. 00086", "00086"),
    ("Resolución No. 00072 de 2023", "00072"),
    ("RESOLUCIÓN No. 00083 de 2023", "00083"),
]


class TestRealHeaders:
    def test_every_real_header_yields_its_number(self):
        for text, expected in REAL_HEADERS:
            assert [c.code.value for c in extract_candidates(text)] == [expected], text

    def test_the_trailing_year_is_not_mistaken_for_the_number(self):
        # "de 2023" follows the number and must never replace it.
        assert [c.code.value for c in extract_candidates("Resolución No. 00072 de 2023")] == [
            "00072"
        ]

    def test_a_header_split_across_two_lines_still_reads(self):
        assert [c.code.value for c in extract_candidates("RESOLUCIÓN\nNo. 00083 de 2023")] == [
            "00083"
        ]

    def test_the_numbering_token_glued_to_the_number_still_reads(self):
        assert [c.code.value for c in extract_candidates("RESOLUCION No.00086")] == ["00086"]


class TestOfficialFormSignal:
    def test_the_official_form_is_recognised_in_any_casing(self):
        for text, _ in REAL_HEADERS:
            assert extract_candidates(text)[0].official_form is True, text

    def test_a_title_cased_header_is_confident_without_capitals_to_lean_on(self):
        # Before the structure was scored, this page sat a hundredth above the
        # floor and any competing reading pushed it to the vision model.
        selection = select_best(extract_candidates("Resolución No. 00072 de 2023"))
        assert selection.confidence > CONFIDENT_FLOOR + 0.2
        assert selection.ambiguous is False

    def test_the_header_still_wins_over_a_citation_in_the_same_form(self):
        page = (
            "RESOLUCIÓN No. 00083 de 2023\n"
            "Por la cual se adopta el manual de contratación\n"
            "CONSIDERANDO que la Resolución No. 00072 de 2023 dispuso lo contrario"
        )
        selection = select_best(extract_candidates(page))
        assert selection.code.value == "00083"
        assert selection.ambiguous is False

    def test_a_citation_alone_is_not_promoted_by_its_shape(self):
        # The form says "this is a resolution number", never "this page is it".
        page = "CONSIDERANDO que la Resolución No. 00072 de 2023 dispuso lo contrario"
        assert extract_candidates(page)[0].official_form is True
        assert select_best(extract_candidates(page)).confidence < CONFIDENT_FLOOR

    def test_a_bare_number_with_no_numbering_token_is_not_the_official_form(self):
        assert extract_candidates("RESOLUCION 00086")[0].official_form is False


def as_pages(*headers):
    """Turn a run of page headers into classifications, ``None`` for no header."""
    from resolutions.domain.resolution_code import ResolutionCode

    return [
        PageClassification(
            page_number=index + 1,
            code=ResolutionCode.parse(str(select_best(extract_candidates(text)).code))
            if text
            else None,
        )
        for index, text in enumerate(headers)
    ]


class TestSplittingOnRealHeaders:
    """The rule end to end: a page with no header belongs to the last one seen."""

    def test_pages_without_a_header_stay_with_the_resolution_above_them(self):
        pages = as_pages(
            "RESOLUCION NO. 00086",
            None,  # page 2: body, no header
            None,  # page 3: body, no header
            "Resolución No. 00072 de 2023",
            None,  # page 5: body, no header
        )
        result = GroupingEngine().group(pages)
        assert {g.code.value: g.page_numbers for g in result.groups} == {
            "00086": [1, 2, 3],
            "00072": [4, 5],
        }
        result.verify_integrity(total_pages=5)

    def test_a_new_header_is_what_opens_the_next_output_pdf(self):
        pages = as_pages("RESOLUCION NO. 00086", None, "RESOLUCIÓN No. 00083 de 2023")
        result = GroupingEngine().group(pages)
        assert [g.code.value for g in result.groups] == ["00086", "00083"]
        assert [g.size for g in result.groups] == [2, 1]
