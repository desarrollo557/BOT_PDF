class DomainError(Exception):
    """Base class for every rule violation raised by the domain layer."""


class InvalidResolutionCode(DomainError):
    """The token captured next to an anchor cannot be a resolution number."""


class IntegrityError(DomainError):
    """Pages went missing or were duplicated while grouping.

    This is deliberately fatal. Shipping a partially correct split of a 400 page
    document is worse than shipping nothing, because nobody notices.
    """
