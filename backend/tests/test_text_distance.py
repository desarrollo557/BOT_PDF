from resolutions.domain.text_distance import damerau_levenshtein


def test_identical_strings_have_zero_distance():
    assert damerau_levenshtein("0412/2024", "0412/2024") == 0


def test_single_substitution():
    assert damerau_levenshtein("0412/2024", "04I2/2024") == 1


def test_transposition_counts_as_one_edit():
    # A plain Levenshtein reports 2 for each of these. OCR swaps adjacent glyphs
    # often enough that treating it as a single edit materially improves recall.
    assert damerau_levenshtein("RESOLUCION", "RESOLUICON") == 1
    assert damerau_levenshtein("0412", "0142") == 1


def test_insertion_and_deletion():
    assert damerau_levenshtein("RES", "RESO") == 1
    assert damerau_levenshtein("RESO", "RES") == 1


def test_empty_operands():
    assert damerau_levenshtein("", "") == 0
    assert damerau_levenshtein("", "ABC") == 3
    assert damerau_levenshtein("ABC", "") == 3


def test_distance_is_symmetric():
    assert damerau_levenshtein("0412/2024", "0413/2024") == damerau_levenshtein(
        "0413/2024", "0412/2024"
    )
