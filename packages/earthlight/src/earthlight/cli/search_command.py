"""The ``earthlight search`` command: find places and history entries by name."""

from typing import Annotated

import typer
from rich.console import Console

import earthlight
from earthlight.cli.app import app
from earthlight.cli.errors import friendly_errors
from earthlight.cli.render import search_view


@app.command()
def search(
    text: Annotated[
        str,
        typer.Argument(
            help='Part of a name: "androm", "apollo", "fall of rome". Typos get guesses.',
            metavar="TEXT",
            show_default=False,
        ),
    ],
    limit: Annotated[
        int, typer.Option("--limit", "-n", min=1, max=100, help="The most results to show.")
    ] = 10,
) -> None:
    """Find stars, planets, galaxies, and history entries by name.

    Use an id from the results with the from and info commands.
    """
    with friendly_errors():
        response = earthlight.search(text, limit=limit)
    Console().print(search_view(response))
