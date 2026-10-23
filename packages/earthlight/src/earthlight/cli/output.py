"""What every command shares about machine-readable output.

With ``--json`` a command prints exactly one JSON document to standard output and nothing else,
so it can be piped into ``jq`` or read by a script. The documents are the same models the web
API will return. Non-ASCII characters are written as escapes (the JSON way), so the output is valid
on any terminal or pipe, whatever encoding it uses.
"""

import json
from typing import Annotated

import typer
from pydantic import BaseModel
from rich.console import Console, RenderableType

JsonOption = Annotated[
    bool, typer.Option("--json", help="Print the result as JSON instead of a layout.")
]
"""The ``--json`` flag, declared once so every command words and behaves it the same way."""


def emit_json(model: BaseModel) -> None:
    """Print a result model as an indented JSON document."""
    typer.echo(json.dumps(model.model_dump(mode="json"), indent=2))


def make_console() -> Console:
    """The console that layouts are printed to. Tests replace this to fix width and colour."""
    return Console()


def print_view(view: RenderableType) -> None:
    """Print a layout to standard output."""
    make_console().print(view)
