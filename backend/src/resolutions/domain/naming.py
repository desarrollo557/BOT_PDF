from __future__ import annotations

from .resolution_code import ResolutionCode
from .title import slugify

CODE_SLUG_LENGTH = 40
TITLE_SLUG_LENGTH = 60
SEPARATOR = "__"

#: Shortest a title fragment may be squeezed to before it is dropped entirely.
#: Below this it has stopped being a title and is just noise in the name.
MIN_TITLE_SLUG = 12


def code_fragment(code: ResolutionCode) -> str:
    return slugify(code.value, max_length=CODE_SLUG_LENGTH) or "sin-codigo"


def output_filename(
    code: ResolutionCode,
    title: str | None,
    extension: str = ".pdf",
    budget: int | None = None,
) -> str:
    """Name a generated file after its resolution and, when known, its subject.

    One function owns this decision so the file on disk and the row in the
    inventory can never disagree about what something is called.

    ``budget`` caps the whole name. Windows refuses a path over 260 characters,
    and a refusal at save time costs the entire resolution -- so the title is
    squeezed, then dropped, and the code is never touched: a file named after
    its number and nothing else is still findable, a file that was never
    written is not.
    """
    fragment = code_fragment(code)
    title_slug = slugify(title or "", max_length=TITLE_SLUG_LENGTH)

    if budget is not None:
        room = budget - len(fragment) - len(SEPARATOR) - len(extension)
        if room < MIN_TITLE_SLUG:
            title_slug = ""
        elif len(title_slug) > room:
            title_slug = slugify(title_slug, max_length=room)

    if title_slug:
        return f"{fragment}{SEPARATOR}{title_slug}{extension}"
    return f"{fragment}{extension}"
