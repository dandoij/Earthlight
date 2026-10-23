"""What every command shares about machine-readable output.

With ``--json`` a command prints exactly one JSON document to standard output and nothing else,
so it can be piped into ``jq`` or read by a script. The documents are the same models the web
API will return, written with ``model_dump_json``.
"""

from typing import Annotated

import typer
from pydantic import BaseModel

JsonOption = Annotated[
    bool, typer.Option("--json", help="Print the result as JSON instead of a layout.")
]
"""The ``--json`` flag, declared once so every command words and behaves it the same way."""


def emit_json(model: BaseModel) -> None:
    """Print a result model as an indented JSON document."""
    typer.echo(model.model_dump_json(indent=2))
