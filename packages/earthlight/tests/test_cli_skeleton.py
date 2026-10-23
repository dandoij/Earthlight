"""Tests for the command line skeleton: help, version, and error handling."""

import re
import subprocess
import sys
from importlib.metadata import entry_points

import pytest
import typer
from typer.testing import CliRunner

from earthlight.cli import app, friendly_errors
from earthlight.errors import EarthlightError

runner = CliRunner()

# CI forces colour and a narrow terminal, which would split option names and add codes.
PLAIN_ENV = {"NO_COLOR": "1", "TERMINAL_WIDTH": "200"}
ANSI_CODES = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    return ANSI_CODES.sub("", text)


def test_version_flag_prints_the_package_version() -> None:
    result = runner.invoke(app, ["--version"], env=PLAIN_ENV)
    assert result.exit_code == 0
    assert re.fullmatch(r"earthlight \S+\n", plain(result.output))


def test_help_describes_the_tool_and_the_version_flag() -> None:
    result = runner.invoke(app, ["--help"], env=PLAIN_ENV)
    assert result.exit_code == 0
    output = plain(result.output)
    assert "light" in output
    assert "--version" in output


def test_the_console_script_points_at_the_app() -> None:
    scripts = {entry.name: entry.value for entry in entry_points(group="console_scripts")}
    assert scripts["earthlight"] == "earthlight.cli:app"


def test_python_dash_m_runs_the_command_line() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "earthlight", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0
    assert done.stdout.startswith("earthlight ")


def test_importing_the_main_module_does_not_run_the_command_line() -> None:
    done = subprocess.run(
        [sys.executable, "-c", "import earthlight.__main__"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0
    assert done.stdout == ""


def failing_app(error: Exception) -> typer.Typer:
    """A throwaway app whose only command raises ``error`` inside ``friendly_errors``."""
    test_app = typer.Typer()

    @test_app.command()
    def boom() -> None:  # pyright: ignore[reportUnusedFunction]
        with friendly_errors():
            raise error

    @test_app.command()
    def fine() -> None:  # pyright: ignore[reportUnusedFunction]
        with friendly_errors():
            typer.echo("fine")

    return test_app


def test_a_deliberate_error_becomes_a_message_and_exit_code_one() -> None:
    result = runner.invoke(
        failing_app(EarthlightError("That has not happened yet.")), ["boom"], env=PLAIN_ENV
    )
    assert result.exit_code == 1
    assert "Error: That has not happened yet." in plain(result.stderr)
    assert "Traceback" not in result.output
    assert result.stdout == ""


def test_square_brackets_in_an_error_are_not_read_as_markup() -> None:
    result = runner.invoke(
        failing_app(EarthlightError('Nothing called "[bold]x[/bold]".')), ["boom"], env=PLAIN_ENV
    )
    assert 'Nothing called "[bold]x[/bold]".' in plain(result.stderr)


def test_emoji_codes_in_an_error_are_not_replaced() -> None:
    result = runner.invoke(
        failing_app(EarthlightError("Nothing called :star: x.")), ["boom"], env=PLAIN_ENV
    )
    assert "Nothing called :star: x." in plain(result.stderr)


def test_a_bug_is_not_hidden_by_the_error_handler() -> None:
    result = runner.invoke(failing_app(RuntimeError("bug")), ["boom"], env=PLAIN_ENV)
    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)


def test_success_passes_through_the_handler() -> None:
    result = runner.invoke(failing_app(EarthlightError("x")), ["fine"], env=PLAIN_ENV)
    assert result.exit_code == 0
    assert result.stdout == "fine\n"


def test_a_mistyped_command_is_a_usage_error_with_exit_code_two() -> None:
    result = runner.invoke(app, ["--nonsense"], env=PLAIN_ENV)
    assert result.exit_code == 2


@pytest.mark.parametrize("arguments", [[], ["--help"]])
def test_no_arguments_shows_help(arguments: list[str]) -> None:
    result = runner.invoke(app, arguments, env=PLAIN_ENV)
    assert "Usage" in plain(result.output)
