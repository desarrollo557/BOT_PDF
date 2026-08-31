from __future__ import annotations

from .resolution_code import ResolutionCode
from .title import slugify

CODE_SLUG_LENGTH = 40
TITLE_SLUG_LENGTH = 60
SEPARATOR = "__"


def code_fragment(code: ResolutionCode) -> str:
    return slugify(code.value, max_length=CODE_SLUG_LENGTH) or "sin-codigo"


def output_filename(code: ResolutionCode, title: str | None, extension: str = ".pdf") -> str:
    """Name a generated file after its resolution and, when known, its subject.

    One function owns this decision so the file on disk and the row in the
    inventory can never disagree about what something is called.
    """
    fragment = code_fragment(code)
    title_slug = slugify(title or "", max_length=TITLE_SLUG_LENGTH)
    if title_slug:
        return f"{fragment}{SEPARATOR}{title_slug}{extension}"
    return f"{fragment}{extension}"
