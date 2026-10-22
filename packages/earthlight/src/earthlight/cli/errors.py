"""Turn deliberate Earthlight errors into a short message and an exit code.

Exit codes: 0 for success, 1 for a request Earthlight could not answer (a bad date, an unknown
name, a moment in the future), and 2 for a mistake in how the command itself was typed (Typer
reports that one). Anything else is a bug, and is left to show its traceback.
"""

from collections.abc import Generator
from contextlib import contextmanager

import typer
from rich.console import Console
from rich.markup import escape

from earthlight.errors import EarthlightError

EXIT_UNANSWERABLE = 1


def error_console() -> Console:
    """A console that writes to standard error, created on use so tests can capture it."""
    return Console(stderr=True)


@contextmanager
def friendly_errors() -> Generator[None]:
    """Run a command body, and report any ``EarthlightError`` instead of a traceback.

    This works like an exception filter in NestJS: the command body raises, and one place
    decides how the person sees it.
    """
    try:
        yield
    except EarthlightError as error:
        # Error messages echo what the person typed, so it must not be read as markup.
        error_console().print(f"[bold red]Error:[/] {escape(str(error))}", highlight=False)
        raise typer.Exit(EXIT_UNANSWERABLE) from error
