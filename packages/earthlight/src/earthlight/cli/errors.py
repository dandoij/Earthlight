"""Turn deliberate Earthlight errors into a short message and an exit code.

Exit codes: 0 for success, 1 for a request Earthlight could not answer (a bad date, an unknown
name, a moment in the future), and 2 for a mistake in how the command itself was typed (Typer
reports that one, always as text). Anything else is a bug, and is left to show its traceback.

When a name matches nothing, the error also lists the did-you-mean guesses and partial matches
(with their ids), so the next command can be typed from the message.

With ``--json`` the error is a JSON document on standard output instead (still exit code 1), laid
out like an RFC 9457 problem document, which is what the web API will use too:
``{"title": ..., "detail": ..., "suggestions": [...], "results": [...]}``.
"""

import json
from collections.abc import Generator
from contextlib import contextmanager

import typer
from rich.console import Console
from rich.markup import escape

from earthlight.cli.render import suggestions_view
from earthlight.engine import MomentError
from earthlight.errors import EarthlightError, UnresolvedNameError
from earthlight.parse import EmptyInputError, ParseError

EXIT_UNANSWERABLE = 1


def error_console() -> Console:
    """A console that writes to standard error, created on use so tests can capture it."""
    return Console(stderr=True)


def error_title(error: EarthlightError) -> str:
    """A short, stable name for the kind of problem, for the ``title`` of a JSON error."""
    if isinstance(error, EmptyInputError) or (
        isinstance(error, UnresolvedNameError) and not error.text.strip()
    ):
        return "Empty input"
    if isinstance(error, ParseError | MomentError):
        return "Invalid moment"
    if isinstance(error, LookupError):
        return "Not found"
    return "Error"


def error_document(error: EarthlightError) -> dict[str, object]:
    """The JSON form of an error: always the same four keys."""
    suggestions = error.suggestions if isinstance(error, UnresolvedNameError) else ()
    results = error.results if isinstance(error, UnresolvedNameError) else ()
    return {
        "title": error_title(error),
        "detail": str(error),
        "suggestions": [guess.model_dump(mode="json") for guess in suggestions],
        "results": [result.model_dump(mode="json") for result in results],
    }


@contextmanager
def friendly_errors(*, json_output: bool = False) -> Generator[None]:
    """Run a command body, and report any ``EarthlightError`` instead of a traceback.

    This works like an exception filter in NestJS: the command body raises, and one place
    decides how the person sees it. With ``json_output`` the report is a JSON document on
    standard output, so a script reading ``--json`` output can parse failures too.
    """
    try:
        yield
    except EarthlightError as error:
        if json_output:
            typer.echo(json.dumps(error_document(error), indent=2))
            raise typer.Exit(EXIT_UNANSWERABLE) from error
        console = error_console()
        # Error messages echo what the person typed: no markup, no emoji codes.
        console.print(f"[bold red]Error:[/] {escape(str(error))}", highlight=False, emoji=False)
        if isinstance(error, UnresolvedNameError):
            guesses = suggestions_view(
                error.suggestions, error.results, header="Try one of these ids:"
            )
            if guesses is not None:
                console.print(guesses)
        raise typer.Exit(EXIT_UNANSWERABLE) from error
