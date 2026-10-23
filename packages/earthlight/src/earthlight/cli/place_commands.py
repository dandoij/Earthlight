"""The ``earthlight from`` and ``earthlight info`` commands: questions about one place."""

from typing import Annotated

import typer

import earthlight
from earthlight.cli.app import app
from earthlight.cli.errors import friendly_errors
from earthlight.cli.output import JsonOption, emit_json, print_view
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


_FROM_HELP = (
    "What did Earth look like in the light arriving at a star, planet, or galaxy right now?\n\n"
    "The light reaching a place at distance D light-years left Earth D years ago, so standing "
    "there you would see Earth as it was then."
)


@app.command("from", help=_FROM_HELP)
def from_command(place: PlaceArgument, json_output: JsonOption = False) -> None:
    reference = now()
    with friendly_errors(json_output=json_output):
        snapshot = earthlight.from_vantage(place, now_year=reference)
    if json_output:
        emit_json(snapshot)
    else:
        print_view(snapshot_view(snapshot, reference))


@app.command(help="Show what is known about one place: distance, position, and catalogue facts.")
def info(place: PlaceArgument, json_output: JsonOption = False) -> None:
    reference = now()  # the Sun, Moon, and planets are as far away as the date says
    with friendly_errors(json_output=json_output):
        details = earthlight.info(place, now_year=reference)
    if json_output:
        emit_json(details)
    else:
        print_view(info_view(details))
