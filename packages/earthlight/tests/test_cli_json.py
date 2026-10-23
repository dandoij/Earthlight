"""Tests for ``--json``: every command, the error documents, and the committed output snapshot."""

import json
import os
from pathlib import Path
from typing import Any

import pytest
import typer.main
from pydantic import BaseModel
from typer.testing import CliRunner, Result

import earthlight
from earthlight.cli import app, place_commands, when_command
from earthlight.cli.errors import error_title
from earthlight.errors import EarthlightError
from earthlight.models import EarthSnapshot, MomentResult, PlaceInfo, SearchResponse

NOW = 2026.0
ENV = {"NO_COLOR": "1", "COLUMNS": "120", "TERMINAL_WIDTH": "200"}
SNAPSHOT_FILE = Path(__file__).parent / "data" / "cli_json_snapshot.json"

runner = CliRunner()


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(when_command, "now", lambda: NOW)
    monkeypatch.setattr(place_commands, "now", lambda: NOW)


def run(*arguments: str) -> Result:
    return runner.invoke(app, list(arguments), env=ENV)


# (command line, the model its JSON must read back as, the Python call that gives the same answer)
CASES: list[tuple[list[str], type[BaseModel], BaseModel]] = [
    (["when", "1492"], MomentResult, earthlight.when("1492", now_year=NOW)),
    (["when", "--ago", "3 hours"], MomentResult, earthlight.when("3 hours ago", now_year=NOW)),
    (["from", "Betelgeuse"], EarthSnapshot, earthlight.from_vantage("Betelgeuse", now_year=NOW)),
    (["info", "proxima-cen-b"], PlaceInfo, earthlight.info("proxima-cen-b")),
    (["search", "androm"], SearchResponse, earthlight.search("androm")),
    (["search", "Betelguese"], SearchResponse, earthlight.search("Betelguese")),
]


@pytest.mark.parametrize(("arguments", "model", "expected"), CASES, ids=lambda v: str(v)[:40])
def test_json_output_is_the_python_result_and_nothing_else(
    arguments: list[str], model: type[BaseModel], expected: BaseModel
) -> None:
    result = run(*arguments, "--json")
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert "\x1b" not in result.stdout
    json.loads(result.stdout)  # one document, nothing before or after it
    assert model.model_validate_json(result.stdout) == expected


def test_every_command_takes_json() -> None:
    commands = typer.main.get_group(app).commands
    assert set(commands) == {"when", "from", "info", "search"}
    for name, command in commands.items():
        options = {option for param in command.params for option in param.opts}
        assert "--json" in options, f"earthlight {name} has no --json"


# --- error documents ------------------------------------------------------------------------


def error_of(*arguments: str) -> dict[str, Any]:
    result = run(*arguments, "--json")
    assert result.exit_code == 1, result.output
    assert result.stderr == ""  # a script reads stdout only
    document = json.loads(result.stdout)
    assert set(document) == {"title", "detail", "suggestions", "results"}
    return document


@pytest.mark.parametrize("command", ["from", "info"])
def test_an_unknown_place_is_a_not_found_document_with_guesses(command: str) -> None:
    document = error_of(command, "Betelguese")
    assert document["title"] == "Not found"
    assert "Betelguese" in document["detail"]
    assert document["suggestions"][0]["id"] == "hip-27989"
    assert document["results"] == []


def test_partial_matches_are_in_the_results_key() -> None:
    document = error_of("from", "sun")
    assert [hit["id"] for hit in document["results"]] == ["messier-63"]


def test_an_unknown_event_is_a_not_found_document() -> None:
    document = error_of("when", "--event", "fall of rom1")
    assert document["title"] == "Not found"
    assert document["suggestions"][0]["id"] == "fall-of-the-western-roman-empire"


@pytest.mark.parametrize(
    "arguments",
    [["2999"], ["0"], ["--year", "soon"], ["--date", "2023-02-30"], ["--ago", "soon"]],
)
def test_a_bad_moment_is_an_invalid_moment_document(arguments: list[str]) -> None:
    document = error_of("when", *arguments)
    assert document["title"] == "Invalid moment"
    assert document["suggestions"] == []
    assert document["results"] == []


def test_error_titles_by_kind_of_problem() -> None:
    assert error_title(earthlight.UnknownVantageError("x")) == "Not found"
    assert error_title(earthlight.FutureMomentError("x")) == "Invalid moment"
    assert error_title(earthlight.InvalidMomentError("x")) == "Invalid moment"
    assert error_title(EarthlightError("x")) == "Error"


def test_a_mistyped_command_stays_a_text_usage_error() -> None:
    result = run("when", "--json")  # no moment: Typer's own usage error, exit code 2
    assert result.exit_code == 2
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout or "text")


def test_without_json_an_error_is_text_on_stderr_and_stdout_is_empty() -> None:
    result = run("from", "Betelguese")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith("Error:")


# --- the committed output ------------------------------------------------------------------

SNAPSHOT_COMMANDS: list[list[str]] = [
    ["when", "1492"],
    ["when", "3 hours ago"],
    ["when", "4.5 gya"],
    ["from", "Betelgeuse"],
    ["from", "GN-z11"],
    ["info", "proxima-cen-b"],
    ["info", "Proxima Centauri"],
    ["search", "androm", "--limit", "3"],
    ["search", "Betelguese"],
    ["from", "Betelguese"],
    ["when", "2999"],
]


def current_outputs() -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    for arguments in SNAPSHOT_COMMANDS:
        result = run(*arguments, "--json")
        outputs["earthlight " + " ".join(arguments)] = {
            "exit_code": result.exit_code,
            "output": json.loads(result.stdout),
        }
    return outputs


def test_json_output_matches_the_committed_snapshot() -> None:
    """Fails when the JSON a command prints changes. If the change is intended, regenerate with
    ``$env:UPDATE_SNAPSHOTS = "1"; uv run pytest packages/earthlight/tests/test_cli_json.py``
    and review the diff of ``tests/data/cli_json_snapshot.json``: it is the CLI contract.
    """
    outputs = current_outputs()
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT_FILE.write_text(
            json.dumps(outputs, indent=1, sort_keys=True) + "\n", "utf-8", newline="\n"
        )
    committed = json.loads(SNAPSHOT_FILE.read_text("utf-8"))
    assert json.loads(json.dumps(outputs, sort_keys=True)) == committed
