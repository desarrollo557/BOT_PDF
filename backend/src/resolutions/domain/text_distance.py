"""Edit distance tuned for OCR noise."""


def damerau_levenshtein(a: str, b: str, *, ceiling: int | None = None) -> int:
    """Optimal string alignment distance between ``a`` and ``b``.

    Adjacent transpositions cost a single edit, which matters because OCR
    engines swap neighbouring glyphs far more often than they invent characters.

    ``ceiling`` short-circuits the computation once every cell in a row exceeds
    it. Callers only ever ask "is this within 2 edits?", so bailing out early
    turns the hot path from O(n*m) into a couple of rows for unrelated strings.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    if ceiling is not None and abs(len(a) - len(b)) > ceiling:
        return ceiling + 1

    previous_previous: list[int] = []
    previous = list(range(len(b) + 1))

    for i, char_a in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            current[j] = min(
                current[j - 1] + 1,  # insertion
                previous[j] + 1,  # deletion
                previous[j - 1] + cost,  # substitution
            )
            if (
                i > 1
                and j > 1
                and char_a == b[j - 2]
                and a[i - 2] == char_b
            ):
                current[j] = min(current[j], previous_previous[j - 2] + cost)

        if ceiling is not None and min(current) > ceiling:
            return ceiling + 1

        previous_previous, previous = previous, current

    return previous[len(b)]


def within(a: str, b: str, max_distance: int) -> bool:
    """True when ``a`` and ``b`` differ by at most ``max_distance`` edits."""
    return damerau_levenshtein(a, b, ceiling=max_distance) <= max_distance
