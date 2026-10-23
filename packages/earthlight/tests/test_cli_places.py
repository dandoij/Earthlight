"""Tests for the ``earthlight from`` and ``earthlight info`` commands and their layouts."""

import re

import pytest
from rich.console import Console
from typer.testing import CliRunner, Result

import earthlight
from earthlight.cli import app, place_commands
from earthlight.cli.render import info_view, snapshot_view
from earthlight.models import LandmarkStatus

NOW = 2026.0
ANSI_CODES = re.compile(r"\x1b\[[0-9;]*m")
ENV = {"NO_COLOR": "1", "COLUMNS": "120", "TERMINAL_WIDTH": "200"}

runner = CliRunner()


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(place_commands, "now", lambda: NOW)


def run(*arguments: str) -> Result:
    return runner.invoke(app, list(arguments), env=ENV)


def out(result: Result) -> str:
    return ANSI_CODES.sub("", result.stdout)


def render_text(renderable: object) -> str:
    console = Console(width=120, color_system=None, record=True, file=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


# --- from -----------------------------------------------------------------------------------


def test_from_shows_the_header_tables_and_population() -> None:
    result = run("from", "Betelgeuse")
    text = out(result)
    assert result.exit_code == 0
    assert "Betelgeuse" in text
    assert "id hip-27989" in text
    assert "498 light-years away" in text
    assert "left Earth between 1455 CE and 1584 CE" in text
    assert "Events (6)" in text
    assert "Columbus reaches the Americas" in text
    assert "Periods (5)" in text
    assert "Landmarks (10 of 13)" in text
    assert "World population: about 503 million (1500 CE)" in text


def test_from_accepts_ids_names_and_aliases() -> None:
    by_name = out(run("from", "Betelgeuse"))
    assert out(run("from", "hip-27989")) == by_name
    assert out(run("from", "betelgeuse")) == by_name
    assert "Andromeda" in out(run("from", "M31"))


def test_from_a_place_whose_light_is_older_than_earth_shows_only_the_note() -> None:
    result = run("from", "GN-z11")
    text = out(result)
    assert result.exit_code == 0
    assert "Earth does not exist yet" in text
    for heading in ("Events", "Periods", "Landmarks", "World population"):
        assert heading not in text


def test_from_a_nearby_place_uses_a_single_year() -> None:
    assert "left Earth in 2021 CE." in out(run("from", "hip-70890"))


def test_from_an_unknown_place_exits_one_and_offers_a_guess() -> None:
    result = run("from", "Betelguese")
    assert result.exit_code == 1
    assert "Did you mean Betelgeuse" in ANSI_CODES.sub("", result.stderr)
    assert result.stdout == ""


def test_from_needs_a_place() -> None:
    assert run("from").exit_code == 2


def test_snapshot_view_words_each_landmark_status_and_open_ended_periods() -> None:
    snapshot = earthlight.from_vantage("Betelgeuse", now_year=NOW)
    landmark = snapshot.landmarks[0]
    period = snapshot.periods[0]
    changed = snapshot.model_copy(
        update={
            "landmarks": (
                landmark.model_copy(update={"status": LandmarkStatus.UNDER_CONSTRUCTION}),
                landmark.model_copy(update={"status": LandmarkStatus.DESTROYED, "name": "Gone"}),
            ),
            "periods": (
                period.model_copy(update={"end": None, "ongoing": True}),
                period.model_copy(update={"end": None, "ongoing": False, "name": "Open"}),
            ),
            "population": None,
        }
    )
    text = render_text(snapshot_view(changed, NOW))
    assert "under construction" in text
    assert "destroyed" in text
    assert "ongoing" in text
    assert "unknown" in text
    assert "World population" not in text


def test_snapshot_view_shows_all_when_nothing_was_cut() -> None:
    text = render_text(snapshot_view(earthlight.from_vantage("Betelgeuse", now_year=NOW), NOW))
    assert "Events (6)" in text  # 6 shown of 6: no "of"
    assert "Events (6 of" not in text


# --- info -----------------------------------------------------------------------------------


def test_info_for_an_exoplanet_shows_discovery_and_host() -> None:
    result = run("info", "proxima-cen-b")
    text = out(result)
    assert result.exit_code == 0
    assert "Proxima Cen b" in text
    assert "Orbits Proxima Cen" in text
    assert "Discovered in 2016 by radial velocity" in text
    assert "Mass 1.055 Earths" in text
    assert "Host star: hip-70890" in text
    assert "earthlight from proxima-cen-b" in text


def test_info_for_a_star_lists_its_planets_and_catalogue_facts() -> None:
    text = out(run("info", "Proxima Centauri"))
    assert "Planets: proxima-cen-b" in text
    assert "spectral type" in text
    assert "M5Ve" in text
    assert "Magnitude 11.01" in text
    assert "RA 217.45 deg, Dec -62.68 deg" in text


def test_info_leaves_out_a_range_that_rounds_to_one_number() -> None:
    assert "range" not in out(run("info", "Proxima Centauri"))
    assert "(range 442 to 570 light-years)" in out(run("info", "Betelgeuse"))


def test_info_for_a_galaxy_has_no_exoplanet_lines() -> None:
    text = out(run("info", "M31"))
    assert "Andromeda" in text
    assert "Orbits" not in text
    assert "Host star" not in text
    assert "Wikipedia: Andromeda Galaxy" in text


def test_info_for_an_unknown_place_exits_one() -> None:
    result = run("info", "qwertyzxcv")
    assert result.exit_code == 1
    assert result.stderr.startswith("Error:")


def test_info_view_marks_a_disputed_planet() -> None:
    details = earthlight.info("proxima-cen-b")
    assert details.exoplanet is not None
    disputed = details.model_copy(
        update={"exoplanet": details.exoplanet.model_copy(update={"controversial": True})}
    )
    assert "Its existence is disputed." in render_text(info_view(disputed))
    assert "disputed" not in render_text(info_view(details))
