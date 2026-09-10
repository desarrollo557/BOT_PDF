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

    # Con tope, sólo se calcula la banda diagonal.
    #
    # Un alineamiento que se aparta más de `ceiling` celdas de la diagonal ya
    # ha gastado más de `ceiling` inserciones o borrados, así que su resultado
    # excede el tope se calcule o no. Fuera de la banda se deja un valor mayor
    # que el tope, que es lo único que hace falta saber de esas celdas.
    #
    # Es lo que convierte esto de O(n*m) en O(n*k), y aquí importa: comparar
    # el catálogo con una hoja son miles de llamadas, y esta función era el
    # 64 % de lo que quedaba del recorrido tras optimizar el resto.
    if ceiling is None:
        return _completa(a, b)

    fuera = ceiling + 1
    ancho = len(b)
    previous_previous: list[int] = []
    previous = [j if j <= ceiling else fuera for j in range(ancho + 1)]

    for i, char_a in enumerate(a, start=1):
        desde, hasta = max(1, i - ceiling), min(ancho, i + ceiling)
        current = [fuera] * (ancho + 1)
        current[0] = i if i <= ceiling else fuera
        mejor = current[0]
        for j in range(desde, hasta + 1):
            char_b = b[j - 1]
            cost = 0 if char_a == char_b else 1
            valor = min(
                current[j - 1] + 1,  # insertion
                previous[j] + 1,  # deletion
                previous[j - 1] + cost,  # substitution
            )
            if i > 1 and j > 1 and char_a == b[j - 2] and a[i - 2] == char_b:
                valor = min(valor, previous_previous[j - 2] + cost)
            current[j] = valor
            if valor < mejor:
                mejor = valor

        if mejor > ceiling:
            return ceiling + 1

        previous_previous, previous = previous, current

    return previous[ancho]


def _completa(a: str, b: str) -> int:
    """La matriz entera, para quien pregunta sin tope cuánto difieren."""
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
            if i > 1 and j > 1 and char_a == b[j - 2] and a[i - 2] == char_b:
                current[j] = min(current[j], previous_previous[j - 2] + cost)

        previous_previous, previous = previous, current

    return previous[len(b)]


def within(a: str, b: str, max_distance: int) -> bool:
    """True when ``a`` and ``b`` differ by at most ``max_distance`` edits."""
    return damerau_levenshtein(a, b, ceiling=max_distance) <= max_distance
