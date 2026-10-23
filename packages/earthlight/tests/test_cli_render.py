"""Tests for the layouts in ``earthlight.cli.render`` that are not tied to one command."""

import io
import json
import os
import re
import subprocess
import sys

import pytest
from rich.console import Console
from typer.testing import CliRunner

import earthlight
from earthlight.cli import app
from earthlight.cli.render import (
    info_view,
    light_travel,
    match_panel,
    percent_text,
    snapshot_view,
    zone_panel,
)
from earthlight.lookback import MomentRange

NOW = 2026.0
ANSI_CODES = re.compile(r"\x1b\[[0-9;]*m")

runner = CliRunner()


def render_text(renderable: object) -> str:
    printed = io.StringIO()
    Console(file=printed, width=140, color_system=None).print(renderable)
    return printed.getvalue()


# --- table cells are literal text -----------------------------------------------------------


def test_history_table_cells_that_look_like_markup_are_shown_literally() -> None:
    snapshot = earthlight.from_vantage("Betelgeuse", now_year=NOW)
    event = snapshot.events[0].model_copy(
        update={"name": "[bold]Alpha[/bold] :star:", "region": "[red]Here[/red] :rocket:"}
    )
    period = snapshot.periods[0].model_copy(update={"name": "[b]Era[/b] :fire:"})
    landmark = snapshot.landmarks[0].model_copy(
        update={"name": "[i]Tower[/i] :tada:", "region": "[u]Land[/u]"}
    )
    changed = snapshot.model_copy(
        update={"events": (event,), "periods": (period,), "landmarks": (landmark,)}
    )
    text = render_text(snapshot_view(changed, NOW))
    for literal in (
        "[bold]Alpha[/bold] :star:",
        "[red]Here[/red] :rocket:",
        "[b]Era[/b] :fire:",
        "[i]Tower[/i] :tada:",
        "[u]Land[/u]",
    ):
        assert literal in text


def test_a_fact_value_that_looks_like_markup_is_shown_literally() -> None:
    details = earthlight.info("Proxima Centauri")
    point = details.vantage_point.model_copy(
        update={"facts": {"other_names": "[b]HMT84[/b] 1413 :star:"}}
    )
    text = render_text(info_view(details.model_copy(update={"vantage_point": point})))
    assert "[b]HMT84[/b] 1413 :star:" in text


# --- the match panel and the left-Earth wording -------------------------------------------------


def test_a_tiny_offset_is_not_called_a_best_estimate() -> None:
    match = earthlight.when(1492.0, now_year=NOW).famous
    assert match is not None
    tiny = match.model_copy(update={"offset_years": 0.04, "approximate": False})
    assert "best estimate" not in render_text(match_panel("Famous", tiny))
    visible = match.model_copy(update={"offset_years": 0.06, "approximate": False})
    assert "best estimate 0.1 years farther" in render_text(match_panel("Famous", visible))


def test_a_single_old_moment_reads_as_ago_not_in_ago() -> None:
    snapshot = earthlight.from_vantage("GN-z11", now_year=NOW)
    earliest = snapshot.moments.earliest
    moments = MomentRange(earliest=earliest, best=earliest, latest=earliest)
    text = render_text(snapshot_view(snapshot.model_copy(update={"moments": moments}), NOW))
    assert "left Earth 13.4 billion years ago" in text.replace("\n", " ")
    assert "in 13.4 billion" not in text


# --- percentages in the zone panel ------------------------------------------------------------


@pytest.mark.parametrize(
    ("percent", "expected"),
    [
        (0.00806, "0.00806"),
        (7.5e-07, "0.000000750"),
        (0.0081234, "0.00812"),
        (1.234, "1.23"),
        (12.34, "12.3"),
        (123.4, "123"),
        (0.0, "0"),
    ],
)
def test_percent_text_never_uses_exponent_notation(percent: float, expected: str) -> None:
    assert percent_text(percent) == expected


def test_a_very_recent_moment_has_no_exponent_in_the_zone_panel() -> None:
    result = earthlight.when("1 second ago", now_year=NOW)
    assert result.zone is not None
    text = render_text(zone_panel(result.zone))
    assert "e-" not in text
    assert "% of the way to Proxima Centauri" in text


def test_the_zone_panel_agrees_with_the_note() -> None:
    result = earthlight.when("3 hours ago", now_year=NOW)
    assert result.zone is not None
    assert "0.00806% of the way" in render_text(zone_panel(result.zone))


def test_naming_a_place_where_a_moment_is_expected_points_at_the_from_command() -> None:
    with pytest.raises(earthlight.UnresolvedNameError, match="the from command"):
        earthlight.when("Betelgeuse", as_event=True, now_year=NOW)


def test_light_travel_singular() -> None:
    assert light_travel(1 / 31_557_600) == "1 light-second"


# --- help text ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "paragraph"),
    [
        (
            "when",
            "Give the moment as one argument and Earthlight works out what kind it is, or force "
            "the kind with exactly one of --year, --date, --ago, or --event.",
        ),
        (
            "from",
            "The light reaching a place at distance D light-years left Earth D years ago, so "
            "standing there you would see Earth as it was then.",
        ),
        ("search", "Use an id from the results with the from and info commands."),
        (
            "info",
            "Show what is known about one place: distance, position, and catalogue facts.",
        ),
    ],
)
def test_help_paragraphs_are_not_broken_by_hard_line_breaks(command: str, paragraph: str) -> None:
    wide = {"NO_COLOR": "1", "COLUMNS": "400", "TERMINAL_WIDTH": "400"}
    result = runner.invoke(app, [command, "--help"], env=wide)
    assert result.exit_code == 0
    assert paragraph in [line.strip() for line in ANSI_CODES.sub("", result.output).splitlines()]


def test_the_when_help_says_how_to_write_a_date_with_a_leading_minus() -> None:
    wide = {"NO_COLOR": "1", "COLUMNS": "400", "TERMINAL_WIDTH": "400"}
    output = ANSI_CODES.sub("", runner.invoke(app, ["when", "--help"], env=wide).output)
    assert "--date -0043-03-15" in output


def test_the_when_usage_names_the_argument_moment() -> None:
    wide = {"NO_COLOR": "1", "COLUMNS": "200", "TERMINAL_WIDTH": "200"}
    output = runner.invoke(app, ["when", "--help"], env=wide).output
    assert "[MOMENT]" in output


# --- text the output encoding cannot hold ------------------------------------------------------


def _legacy_encoding_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUTF8"}
    env["PYTHONIOENCODING"] = "cp1252"
    env["NO_COLOR"] = "1"
    return env


def _earthlight(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "earthlight", *arguments],
        capture_output=True,
        env=_legacy_encoding_env(),
        check=False,
    )


def test_json_with_a_non_cp1252_name_is_valid_ascii_json() -> None:
    done = _earthlight("info", "hip-48711", "--json")
    assert done.returncode == 0, done.stderr
    document = json.loads(done.stdout.decode("ascii"))
    assert document["vantage_point"]["name"] == "Bibhā"


@pytest.mark.parametrize("arguments", [("info", "hip-48711"), ("search", "bibh")])
def test_layouts_do_not_crash_on_names_the_encoding_cannot_hold(arguments: tuple[str, ...]) -> None:
    done = _earthlight(*arguments)
    assert done.returncode == 0, done.stderr
    assert b"Traceback" not in done.stderr
