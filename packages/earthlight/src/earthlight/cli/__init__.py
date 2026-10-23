"""The ``earthlight`` command line.

A thin layer over the public Python interface: each command calls one function from
``earthlight`` and shows the result.
"""

# Importing a command module registers its commands on ``app``.
from earthlight.cli import place_commands, search_command, when_command
from earthlight.cli.app import app
from earthlight.cli.errors import friendly_errors

__all__ = ["app", "friendly_errors", "place_commands", "search_command", "when_command"]
