"""The ``earthlight search`` command: find places and history entries by name."""

from typing import Annotated

import typer

import earthlight
from earthlight.cli.app import app
from earthlight.cli.errors import friendly_errors
from earthlight.cli.output import JsonOption, emit_json, print_view
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
    json_output: JsonOption = False,
) -> None:
    """Find stars, planets, galaxies, and history entries by name.

    Use an id from the results with the from and info commands.
    """
    with friendly_errors(json_output=json_output):
        response = earthlight.search(text, limit=limit)
    if json_output:
        emit_json(response)
    else:
        print_view(search_view(response))
