"""The Typer application object and its top-level options.

Commands live in their own modules and register themselves on ``app`` when imported (see
``earthlight.cli``). Keeping the object here avoids a circular import between the two.
"""

from importlib.metadata import PackageNotFoundError, version
from typing import Annotated

import typer


def _installed_version() -> str:
    try:
        return version("earthlight")
    except PackageNotFoundError:  # running from a source tree that was never installed
        return "unknown"


def _show_version(show: bool) -> None:
    if show:
        typer.echo(f"earthlight {_installed_version()}")
        raise typer.Exit()


app = typer.Typer(
    name="earthlight",
    help="Where in the universe is the light from a moment arriving right now?",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)


@app.callback()
def main(
    show_version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_show_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Where in the universe is the light from a moment arriving right now?"""
