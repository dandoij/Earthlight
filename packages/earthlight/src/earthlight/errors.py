"""Every error Earthlight raises on purpose, under one base class.

Callers (the command line, the web API, a script) can catch ``EarthlightError`` to handle any
of them and show ``str(error)``, which is always written for the person who made the request.
The subclasses also keep their older, more specific parents (``ValueError`` or ``LookupError``),
so code that catches those still works.
"""

from earthlight.models import SearchResult, Suggestion

MAX_ECHOED_CHARS = 40
"""The longest stretch of the person's own text an error message repeats back."""


def shown(text: str) -> str:
    """Shorten user text before it goes into an error message."""
    if len(text) <= MAX_ECHOED_CHARS:
        return text
    return text[: MAX_ECHOED_CHARS - 3] + "..."


class EarthlightError(Exception):
    """The base class of every error Earthlight raises on purpose."""


class UnresolvedNameError(EarthlightError, LookupError):
    """Text that was meant to name a place or an event matched nothing usable.

    ``results`` holds things the text partly matched (such as places whose names start with
    it) and ``suggestions`` holds did-you-mean guesses, so a caller can offer them.
    """

    def __init__(
        self,
        message: str,
        *,
        text: str,
        results: tuple[SearchResult, ...] = (),
        suggestions: tuple[Suggestion, ...] = (),
    ) -> None:
        super().__init__(message)
        self.text = text
        self.results = results
        self.suggestions = suggestions
