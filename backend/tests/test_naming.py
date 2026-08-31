from resolutions.domain.naming import output_filename
from resolutions.domain.resolution_code import ResolutionCode

CODE = ResolutionCode.parse("N° 0412/2024")


def test_the_file_carries_the_code_and_the_title():
    assert output_filename(CODE, "Compra de insumos informáticos") == (
        "0412-2024__compra-de-insumos-informaticos.pdf"
    )


def test_an_unnamed_resolution_falls_back_to_the_code_alone():
    assert output_filename(CODE, None) == "0412-2024.pdf"
    assert output_filename(CODE, "   ") == "0412-2024.pdf"


def test_the_slash_in_a_code_never_reaches_the_filesystem():
    assert "/" not in output_filename(CODE, "Algo")


def test_a_long_title_is_trimmed_to_a_usable_length():
    name = output_filename(CODE, " ".join(["palabra"] * 40))
    assert len(name) < 120
    assert name.endswith(".pdf")


def test_distinct_codes_never_collide_on_the_same_title():
    other = ResolutionCode.parse("0555/2024")
    assert output_filename(CODE, "Compra") != output_filename(other, "Compra")
