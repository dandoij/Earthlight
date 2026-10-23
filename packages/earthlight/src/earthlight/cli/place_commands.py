"""The ``earthlight from`` and ``earthlight info`` commands: questions about one place."""

from typing import Annotated

import typer
from rich.console import Console

import earthlight
from earthlight.cli.app import app
from earthlight.cli.errors import friendly_errors
from earthlight.cli.output import JsonOption, emit_json
from earthlight.cli.render import info_view, snapshot_view
from earthlight.time import now

PlaceArgument = Annotated[
    str,
    typer.Argument(
        help='A place: a name ("Betelgeuse", "M31"), an alias, or an id ("hip-27989").',
        metavar="PLACE",
        show_default=False,
    ),
]


@app.command("from")
def from_command(place: PlaceArgument, json_output: JsonOption = False) -> None:
    """What did Earth look like in the light arriving at a star, planet, or galaxy right now?

    The light reaching a place at distance D light-years left Earth D years ago, so standing
    there you would see Earth as it was then.
    """
    reference = now()
    with friendly_errors(json_output=json_output):
        snapshot = earthlight.from_vantage(place, now_year=reference)
    if json_output:
        emit_json(snapshot)
    else:
        Console().print(snapshot_view(snapshot, reference))


@app.command()
def info(place: PlaceArgument, json_output: JsonOption = False) -> None:
    """Show what is known about one place: distance, position, and catalogue facts."""
    with friendly_errors(json_output=json_output):
        details = earthlight.info(place)
    if json_output:
        emit_json(details)
    else:
        Console().print(info_view(details))
