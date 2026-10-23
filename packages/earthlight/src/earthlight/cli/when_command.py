"""The ``earthlight when`` command: where is the light from a moment arriving right now?"""

from typing import Annotated

import typer

import earthlight
from earthlight.cli.app import app
from earthlight.cli.errors import friendly_errors
from earthlight.cli.output import JsonOption, emit_json, print_view
from earthlight.cli.render import moment_view
from earthlight.parse import parse_ago, parse_date, parse_year
from earthlight.time import now

_OVERRIDES = ("--year", "--date", "--ago", "--event")


@app.command()
def when(
    moment: Annotated[
        str | None,
        typer.Argument(
            help='A year ("1492", "500 BCE"), a date ("2004-06-15"), a time ago ("3 days ago", '
            '"66 mya"), or an event name ("apollo 11"). The kind is guessed from the text.',
            show_default=False,
        ),
    ] = None,
    year: Annotated[
        str | None, typer.Option("--year", help='Treat the input as a calendar year: "1492".')
    ] = None,
    date: Annotated[
        str | None, typer.Option("--date", help='Treat the input as an ISO date: "2004-06-15".')
    ] = None,
    ago: Annotated[
        str | None, typer.Option("--ago", help='Treat the input as a time ago: "66 million years".')
    ] = None,
    event: Annotated[
        str | None,
        typer.Option("--event", help='Treat the input as an event name: "fall of rome".'),
    ] = None,
    json_output: JsonOption = False,
) -> None:
    """Where in the universe is the light from a moment arriving right now?

    Give the moment as one argument and Earthlight works out what kind it is, or force the
    kind with exactly one of --year, --date, --ago, or --event.
    """
    given = {
        name: value
        for name, value in (
            ("MOMENT", moment),
            ("--year", year),
            ("--date", date),
            ("--ago", ago),
            ("--event", event),
        )
        if value is not None
    }
    if len(given) != 1:
        raise typer.BadParameter(
            "give a moment, or exactly one of " + ", ".join(_OVERRIDES) + ".",
            param_hint="MOMENT",
        )
    reference = now()  # read the clock once, so "3 days ago" and the answer agree
    with friendly_errors(json_output=json_output):
        if year is not None:
            result = earthlight.when(parse_year(year), now_year=reference)
        elif date is not None:
            result = earthlight.when(parse_date(date), now_year=reference)
        elif ago is not None:
            result = earthlight.when(parse_ago(ago, now_year=reference), now_year=reference)
        elif event is not None:
            result = earthlight.when(event, as_event=True, now_year=reference)
        else:
            assert moment is not None
            result = earthlight.when(moment, now_year=reference)
    if json_output:
        emit_json(result)
    else:
        print_view(moment_view(result))
