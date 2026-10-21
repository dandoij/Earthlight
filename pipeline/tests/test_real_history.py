"""Tests on the shipped history files in pipeline/curated/history."""

from pathlib import Path

import pytest

from earthlight_pipeline.build_history import HISTORY_DIR, run_history
from earthlight_pipeline.history import HistoryData, load_curated_history


@pytest.fixture(scope="module")
def shipped() -> HistoryData:
    return load_curated_history(HISTORY_DIR)


def test_the_shipped_folder_exists_and_has_files() -> None:
    assert HISTORY_DIR.is_dir() and any(HISTORY_DIR.glob("*.yaml"))


def test_the_shipped_files_load_and_build_a_database(shipped: HistoryData, tmp_path: Path) -> None:
    report = run_history(database=tmp_path / "earthlight.db", progress=lambda _message: None)
    assert report.events == len(shipped.events)
    assert report.periods == len(shipped.periods)
    assert report.landmarks == len(shipped.landmarks)
    assert report.database_bytes > 0


def test_every_entry_has_a_web_source_and_a_summary_in_a_sensible_length(
    shipped: HistoryData,
) -> None:
    entries = [*shipped.events, *shipped.periods, *shipped.landmarks]
    assert entries
    for entry in entries:
        assert entry.source.startswith("https://"), entry.id
        assert 40 <= len(entry.summary) <= 400, entry.id


def test_no_text_uses_a_dash_that_the_project_forbids(shipped: HistoryData) -> None:
    for entry in [*shipped.events, *shipped.periods, *shipped.landmarks]:
        text = f"{entry.name} {entry.region} {entry.summary}"
        assert chr(0x2014) not in text and chr(0x2013) not in text, entry.id


def test_the_eons_follow_each_other_without_gaps(shipped: HistoryData) -> None:
    periods = {p.id: p for p in shipped.periods}
    assert periods["hadean-eon"].end == periods["archean-eon"].start
    assert periods["archean-eon"].end == periods["proterozoic-eon"].start
    assert periods["ediacaran-period"].end == periods["proterozoic-eon"].end


def test_the_universe_is_older_than_the_solar_system_which_is_older_than_earth(
    shipped: HistoryData,
) -> None:
    years = {e.id: e.year for e in shipped.events}
    assert (
        years["big-bang"]
        < years["first-stars"]
        < years["solar-system-forms"]
        < years["earth-forms"]
    )
    assert years["earth-forms"] < years["moon-forming-impact"] < years["oldest-fossil-life"]
