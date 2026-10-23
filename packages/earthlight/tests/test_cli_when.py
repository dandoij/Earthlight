"""Tests for the ``earthlight when`` command and its layouts."""

import json
import re

import pytest
from typer.testing import CliRunner, Result

import earthlight
from earthlight.cli import app, when_command
from earthlight.cli.render import big_number, light_travel
from earthlight.models import MomentResult

NOW = 2026.0
ANSI_CODES = re.compile(r"\x1b\[[0-9;]*m")
# CI forces colour; Rich reads COLUMNS for its width and click reads TERMINAL_WIDTH for help.
WIDE = {"NO_COLOR": "1", "COLUMNS": "140", "TERMINAL_WIDTH": "200"}
NARROW = {"NO_COLOR": "1", "COLUMNS": "70", "TERMINAL_WIDTH": "200"}

runner = CliRunner()


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every command reads the clock once, through ``when_command.now``."""
    monkeypatch.setattr(when_command, "now", lambda: NOW)


def run(*arguments: str, env: dict[str, str] | None = None) -> Result:
    result = runner.invoke(app, ["when", *arguments], env=env or WIDE)
    return result


def text_of(result: Result) -> str:
    return ANSI_CODES.sub("", result.stdout)


def json_of(*arguments: str) -> MomentResult:
    result = run(*arguments, "--json")
    assert result.exit_code == 0, result.output
    return MomentResult.model_validate_json(result.stdout)


# --- layout -------------------------------------------------------------------------------


def test_a_year_shows_the_hero_line_and_all_four_categories() -> None:
    result = run("1492")
    output = text_of(result)
    assert result.exit_code == 0
    assert "1492 CE" in output
    assert "has travelled 534 light-years" in output
    for title in ("Famous", "Exoplanet", "Visible tonight", "Most precise"):
        assert title in output
    assert "Antares" in output


def test_a_wide_terminal_shows_panels_two_by_two() -> None:
    output = text_of(run("1492", env=WIDE))
    titles = [line for line in output.splitlines() if "Famous" in line]
    assert len(titles) == 1
    assert "Exoplanet" in titles[0]  # same row as Famous


def test_a_narrow_terminal_stacks_the_panels() -> None:
    output = text_of(run("1492", env=NARROW))
    famous = [line for line in output.splitlines() if "Famous" in line]
    assert len(famous) == 1
    assert "Exoplanet" not in famous[0]
    assert "Exoplanet" in output
    assert max(len(line) for line in output.splitlines()) <= 70


def test_a_recent_moment_shows_the_zone_and_no_empty_category_panels() -> None:
    output = text_of(run("3 hours ago"))
    assert "Inside the heliosphere" in output
    assert "au from the Sun" in output
    assert "Famous" not in output
    assert "light-hours" in output


def test_deep_time_with_no_match_says_so_in_each_panel_and_notes() -> None:
    output = text_of(run("4.5 gya"))
    assert output.count("Nothing close enough") >= 1
    assert "within 5%" in output


def test_an_approximate_match_is_marked() -> None:
    # 1988 has a category whose best place lies just outside every range (within 5%).
    result = earthlight.when(1988.0, now_year=NOW)
    matches = (result.famous, result.exoplanet, result.visible_tonight, result.most_precise)
    assert any(m is not None and m.approximate for m in matches)
    assert "approximate: just outside its range" in text_of(run("1988"))


# --- the smart argument and the overrides ---------------------------------------------------


def test_the_smart_argument_and_each_override_agree() -> None:
    expected = earthlight.when("1492", now_year=NOW)
    assert json_of("1492") == expected
    assert json_of("--year", "1492") == expected
    assert json_of("--date", "1492-01-01") == expected
    assert json_of("--ago", "534 years") == earthlight.when("534 years ago", now_year=NOW)


def test_ago_is_measured_from_the_same_clock_reading_as_the_answer() -> None:
    result = json_of("--ago", "1 year")
    assert result.moment == pytest.approx(NOW - 1.0)
    assert result.lookback_years == pytest.approx(1.0, abs=0.01)


def test_a_year_flag_accepts_eras() -> None:
    assert json_of("--year", "500 BCE").moment_label == "500 BCE"


def test_a_year_flag_beyond_the_present_is_a_future_error_not_a_parse_error() -> None:
    result = run("--year", "12000")
    assert result.exit_code == 1
    assert "not happened yet" in ANSI_CODES.sub("", result.stderr)


def test_the_event_flag_forces_a_name_even_for_text_that_looks_like_a_year() -> None:
    # Without the flag, "1492" is the year. With it, it is searched as an event name, and
    # the note says which entry was used.
    forced = json_of("--event", "1492")
    assert any("'1492'" in note for note in forced.notes)
    assert not any("'1492'" in note for note in json_of("1492").notes)


def test_an_event_name_is_resolved_and_the_note_says_so() -> None:
    result = run("--event", "apollo 11")
    assert result.exit_code == 0
    assert "Apollo 11" in text_of(result)


def test_smart_argument_resolves_event_names_too() -> None:
    assert json_of("apollo 11") == json_of("--event", "apollo 11")


# --- choosing exactly one input -------------------------------------------------------------


def test_no_input_is_a_usage_error() -> None:
    result = run()
    assert result.exit_code == 2
    assert "exactly one of" in ANSI_CODES.sub("", result.output)


@pytest.mark.parametrize(
    "arguments",
    [
        ["1492", "--year", "1492"],
        ["--year", "1492", "--date", "1492-01-01"],
        ["--ago", "1 day", "--event", "apollo 11"],
    ],
)
def test_more_than_one_input_is_a_usage_error(arguments: list[str]) -> None:
    assert run(*arguments).exit_code == 2


# --- errors -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["2999"], "not happened yet"),
        (["0"], "no year 0"),
        (["--year", "fall of rome"], "not a year"),
        (["--date", "2023-02-30"], "not a valid date"),
        (["--date", "1492"], "not a date"),
        (["--ago", "soon"], "not an amount of time"),
        (["--event", "qwertyzxcv"], "qwertyzxcv"),
        (["--event", "   "], "name of an event"),
    ],
)
def test_unanswerable_requests_exit_one_with_a_message_and_no_traceback(
    arguments: list[str], message: str
) -> None:
    result = run(*arguments)
    assert result.exit_code == 1
    error = ANSI_CODES.sub("", result.stderr)
    assert error.startswith("Error:")
    assert message in error
    assert result.stdout == ""


# --- JSON -------------------------------------------------------------------------------------


def test_json_output_is_only_the_json_document() -> None:
    result = run("1492", "--json")
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)  # fails if anything else is mixed in
    assert parsed["moment_label"] == "1492 CE"
    assert "\x1b" not in result.stdout


# --- number formatting ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (4.24, "4.2"),
        (99.9, "99.9"),
        (534.4, "534"),
        (12_000.0, "12,000"),
        (66e6, "66 million"),
        (1.5e6, "1.5 million"),
        (13.79e9, "13.8 billion"),
        (9.996e8, "1 billion"),
        (999_999.9, "1 million"),
        (99.96, "100"),
        (999.4e6, "999 million"),
        (1e9, "1 billion"),
    ],
)
def test_big_number(value: float, expected: str) -> None:
    assert big_number(value) == expected


@pytest.mark.parametrize(
    ("years", "expected"),
    [
        (30 / 31_557_600, "30 light-seconds"),
        (1 / 31_557_600, "1 light-second"),
        (600 / 31_557_600, "10 light-minutes"),
        (10_800 / 31_557_600, "3.0 light-hours"),
        (5 * 86_400 / 31_557_600, "5 light-days"),
        (4.24, "4.2 light-years"),
        (534.0, "534 light-years"),
    ],
)
def test_light_travel_picks_a_sensible_unit(years: float, expected: str) -> None:
    assert light_travel(years) == expected
