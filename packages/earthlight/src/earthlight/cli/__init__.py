"""The ``earthlight`` command line.

A thin layer over the public Python interface: each command calls one function from
``earthlight`` and shows the result.
"""

# Importing a command module registers the command on ``app``.
from earthlight.cli import when_command  # noqa: F401  # pyright: ignore[reportUnusedImport]
from earthlight.cli.app import app
from earthlight.cli.errors import friendly_errors

__all__ = ["app", "friendly_errors"]
