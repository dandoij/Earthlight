"""Keeps the README honest: its examples must run and print what the README says they print."""

import contextlib
import io
import re
import shlex
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from earthlight.cli import app, errors, output, place_commands, when_command

README = Path(__file__).resolve().parents[3] / "README.md"
README_NOW = 2026.0  # the examples are shown "as of 1 January 2026"
README_WIDTH = 100


def _block(language: str) -> str:
    match = re.search(rf"```{language}\n(.*?)```", README.read_text("utf-8"), re.DOTALL)
    assert match, f"README.md has no ```{language} block"
    return match.group(1)


def test_readme_example_prints_exactly_what_the_readme_shows() -> None:
    output_ = io.StringIO()
    with contextlib.redirect_stdout(output_):
        exec(compile(_block("python"), "README.md example", "exec"), {})
    assert output_.getvalue() == _block("text")


def _console_examples() -> list[tuple[str, str]]:
    """Each ```console block as (the command typed after "$ ", the output shown)."""
    examples: list[tuple[str, str]] = []
    for body in re.findall(r"```console\n(.*?)```", README.read_text("utf-8"), re.DOTALL):
        command, _, shown = body.partition("\n")
        assert command.startswith("$ earthlight "), command
        examples.append((command.removeprefix("$ "), shown))
    return examples


def _trimmed(text: str) -> list[str]:
    return [line.rstrip() for line in text.rstrip("\n").splitlines()]


def test_readme_has_command_line_examples() -> None:
    commands = {command.split()[1] for command, _ in _console_examples()}
    assert commands >= {"when", "from", "search"}


@pytest.mark.parametrize(("command", "shown"), _console_examples(), ids=lambda v: str(v)[:40])
def test_readme_command_line_examples_print_exactly_what_the_readme_shows(
    command: str, shown: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Fix the clock, the width, and the box characters, which otherwise depend on the machine.
    monkeypatch.setattr(when_command, "now", lambda: README_NOW)
    monkeypatch.setattr(place_commands, "now", lambda: README_NOW)

    def screen() -> Console:
        return Console(width=README_WIDTH, legacy_windows=False, color_system=None)

    def error_screen() -> Console:
        return Console(width=README_WIDTH, legacy_windows=False, color_system=None, stderr=True)

    monkeypatch.setattr(output, "make_console", screen)
    monkeypatch.setattr(errors, "error_console", error_screen)
    result = CliRunner().invoke(app, shlex.split(command)[1:])
    assert _trimmed(result.output) == _trimmed(shown)
