import pytest

from resolutions.domain.errors import IntegrityError
from resolutions.domain.grouping import GroupingEngine
from resolutions.domain.page import PageClassification
from resolutions.domain.resolution_code import ResolutionCode


def pages(*raw_codes):
    """Build a page sequence from codes, where None means 'no code detected'."""
    return [
        PageClassification(
            page_number=i + 1,
            code=ResolutionCode.parse(c) if c else None,
            confidence=1.0 if c else 0.0,
        )
        for i, c in enumerate(raw_codes)
    ]


def layout(result):
    return {g.code.value: g.page_numbers for g in result.groups}


engine = GroupingEngine()


class TestCoreRules:
    def test_consecutive_pages_with_the_same_code_form_one_group(self):
        assert layout(engine.group(pages("0001", "0001", "0001"))) == {"0001": [1, 2, 3]}

    def test_a_different_code_opens_a_new_group(self):
        result = engine.group(pages("0001", "0001", "0002"))
        assert layout(result) == {"0001": [1, 2], "0002": [3]}

    def test_a_page_without_a_code_inherits_the_previous_page(self):
        result = engine.group(pages("0001", None, None, "0002", None))
        assert layout(result) == {"0001": [1, 2, 3], "0002": [4, 5]}

    def test_groups_are_ordered_by_first_appearance(self):
        result = engine.group(pages("0555", "0001"))
        assert [g.code.value for g in result.groups] == ["0555", "0001"]


class TestReappearance:
    def test_a_code_that_comes_back_rejoins_its_original_group(self):
        # Confirmed rule: grouping is by code, not by contiguity.
        result = engine.group(pages("0412", "0412", "0555", "0555", "0412", "0412"))
        assert layout(result) == {"0412": [1, 2, 5, 6], "0555": [3, 4]}

    def test_pages_inside_a_group_keep_their_original_document_order(self):
        result = engine.group(pages("0412", "0555", "0412"))
        assert layout(result)["0412"] == [1, 3]

    def test_inheritance_follows_the_previous_page_not_the_group(self):
        result = engine.group(pages("0412", "0555", None, "0412", None))
        assert layout(result) == {"0412": [1, 4, 5], "0555": [2, 3]}


class TestQuarantine:
    def test_pages_before_the_first_code_are_quarantined_not_guessed(self):
        # Guessing here would silently contaminate a real group. A short review
        # queue is always cheaper than an invisible mistake.
        result = engine.group(pages(None, None, "0412", "0412"))
        assert result.quarantine == [1, 2]
        assert layout(result) == {"0412": [3, 4]}

    def test_a_document_with_no_codes_at_all_quarantines_everything(self):
        result = engine.group(pages(None, None, None))
        assert result.groups == []
        assert result.quarantine == [1, 2, 3]


class TestOcrPhantomRepair:
    def test_a_single_page_misread_between_two_identical_neighbours_is_absorbed(self):
        result = engine.group(pages("0412", "0412", "04I2", "0412", "0412"))
        assert layout(result) == {"0412": [1, 2, 3, 4, 5]}

    def test_the_repair_is_recorded_for_auditing_never_done_silently(self):
        result = engine.group(pages("0412", "04I2", "0412"))
        assert len(result.repairs) == 1
        repair = result.repairs[0]
        assert repair.page_number == 2
        assert repair.observed.value == "04I2"
        assert repair.applied.value == "0412"

    def test_a_genuinely_different_code_is_never_absorbed(self):
        result = engine.group(pages("0412", "9999", "0412"))
        assert layout(result) == {"0412": [1, 3], "9999": [2]}

    def test_a_run_of_two_pages_is_not_treated_as_a_misread(self):
        # Two pages agreeing on the same reading is evidence, not noise.
        result = engine.group(pages("0412", "04I2", "04I2", "0412"))
        assert layout(result) == {"0412": [1, 4], "04I2": [2, 3]}

    def test_repair_does_not_apply_when_neighbours_disagree(self):
        result = engine.group(pages("0412", "04I2", "0555"))
        assert layout(result) == {"0412": [1], "04I2": [2], "0555": [3]}


def titled(*specs):
    """Build a page sequence from ``(code, title)`` pairs."""
    return [
        PageClassification(
            page_number=i + 1,
            code=ResolutionCode.parse(code) if code else None,
            title=title,
        )
        for i, (code, title) in enumerate(specs)
    ]


class TestGroupTitles:
    def test_a_group_is_named_by_the_page_that_declares_its_code(self):
        result = engine.group(titled(("0412", "Compra de insumos"), (None, None)))
        assert result.groups[0].title == "Compra de insumos"

    def test_the_first_declaration_wins_when_a_code_reappears(self):
        result = engine.group(
            titled(("0412", "Compra de insumos"), ("0555", "Otra cosa"), ("0412", "Texto posterior"))
        )
        assert {g.code.value: g.title for g in result.groups} == {
            "0412": "Compra de insumos",
            "0555": "Otra cosa",
        }

    def test_a_continuation_page_never_names_the_group(self):
        # Page 2 carries no code, so whatever its first line says is prose.
        result = engine.group(titled((None, None), ("0412", None), (None, "Prosa del cuerpo")))
        assert result.groups[0].title is None

    def test_a_group_without_a_readable_title_stays_unnamed(self):
        result = engine.group(titled(("0412", None), (None, None)))
        assert result.groups[0].title is None


class TestIntegrity:
    def test_every_page_is_accounted_for_exactly_once(self):
        result = engine.group(pages(None, "0412", None, "0555", "0412"))
        result.verify_integrity(total_pages=5)

    def test_a_missing_page_fails_the_job_instead_of_shipping_partial_output(self):
        result = engine.group(pages("0412", "0412"))
        with pytest.raises(IntegrityError):
            result.verify_integrity(total_pages=3)

    def test_integrity_covers_quarantined_pages_too(self):
        result = engine.group(pages(None, "0412"))
        assert result.page_count == 2
        result.verify_integrity(total_pages=2)


class TestScale:
    def test_grouping_is_a_single_linear_pass_over_a_large_document(self):
        sequence = []
        for block in range(50):
            sequence += [f"{block:04d}"] + [None] * 7
        result = engine.group(pages(*sequence))
        assert len(result.groups) == 50
        assert all(len(g.page_numbers) == 8 for g in result.groups)
        result.verify_integrity(total_pages=400)
