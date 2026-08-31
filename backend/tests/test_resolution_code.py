import pytest

from resolutions.domain.errors import InvalidResolutionCode
from resolutions.domain.resolution_code import ResolutionCode


class TestParsing:
    def test_keeps_the_raw_token_for_auditing(self):
        code = ResolutionCode.parse("  N° 0412/2024 ")
        assert code.raw == "N° 0412/2024"

    @pytest.mark.parametrize(
        "raw",
        [
            "N° 0412/2024",
            "Nº 0412/2024",
            "NRO. 0412/2024",
            "No 0412/2024",
            "# 0412/2024",
            "0412/2024",
            "  0412 / 2024  ",
        ],
    )
    def test_strips_numbering_prefixes_and_inner_spacing(self, raw):
        assert ResolutionCode.parse(raw).value == "0412/2024"

    def test_uppercases_alphanumeric_codes(self):
        assert ResolutionCode.parse("res-2024-abc").value == "RES-2024-ABC"

    @pytest.mark.parametrize("raw", ["", "   ", "N°", "RESOLUCION", "----", "N° ---"])
    def test_rejects_tokens_without_digits(self, raw):
        # A code with no digit at all is never a resolution number, it is noise
        # the OCR dragged in. Rejecting here keeps garbage out of the groups.
        with pytest.raises(InvalidResolutionCode):
            ResolutionCode.parse(raw)


class TestEquality:
    def test_codes_compare_by_normalized_value_not_by_raw_text(self):
        assert ResolutionCode.parse("N° 0412/2024") == ResolutionCode.parse("0412 / 2024")

    def test_equal_codes_share_a_hash_so_they_collapse_into_one_group(self):
        bucket = {ResolutionCode.parse("N° 0412/2024"), ResolutionCode.parse("0412/2024")}
        assert len(bucket) == 1

    def test_different_codes_are_not_equal(self):
        assert ResolutionCode.parse("0412/2024") != ResolutionCode.parse("0555/2024")


class TestDistance:
    def test_distance_between_ocr_variants_is_small(self):
        assert ResolutionCode.parse("0412/2024").distance_to(ResolutionCode.parse("04I2/2024")) == 1

    def test_distance_between_unrelated_codes_is_large(self):
        assert ResolutionCode.parse("0412/2024").distance_to(ResolutionCode.parse("0555/2023")) >= 3
