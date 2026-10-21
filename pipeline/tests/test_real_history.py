"""Tests on the shipped history files in pipeline/curated/history."""

from pathlib import Path

import pytest

from earthlight_pipeline.build_history import HISTORY_DIR, run_history
from earthlight_pipeline.history import ONGOING_END_YEAR, HistoryData, load_curated_history


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


def test_the_eras_follow_each_other_and_the_ice_ages_sit_inside_the_cenozoic(
    shipped: HistoryData,
) -> None:
    periods = {p.id: p for p in shipped.periods}
    assert periods["proterozoic-eon"].end == periods["paleozoic-era"].start
    assert periods["paleozoic-era"].end == periods["mesozoic-era"].start
    assert periods["mesozoic-era"].end == periods["cenozoic-era"].start
    pleistocene, cenozoic = periods["pleistocene-epoch"], periods["cenozoic-era"]
    assert cenozoic.start < pleistocene.start < pleistocene.end < cenozoic.end


def test_the_extinctions_mark_the_edges_of_the_eras(shipped: HistoryData) -> None:
    events = {e.id: e for e in shipped.events}
    periods = {p.id: p for p in shipped.periods}
    assert events["permian-triassic-extinction"].year == periods["mesozoic-era"].start
    assert events["end-cretaceous-extinction"].year == periods["mesozoic-era"].end


def test_the_human_story_is_in_time_order(shipped: HistoryData) -> None:
    years = {e.id: e.year for e in shipped.events}
    order = [
        "sahelanthropus",
        "lomekwi-stone-tools",
        "lucy",
        "earliest-homo",
        "homo-erectus",
        "early-controlled-fire",
    ]
    assert [years[i] for i in order] == sorted(years[i] for i in order)


def test_no_event_is_dated_after_its_own_era_ends(shipped: HistoryData) -> None:
    events = {e.id: e for e in shipped.events}
    assert events["first-dinosaurs"].year < events["end-cretaceous-extinction"].year
    assert events["first-mammals"].year < events["end-cretaceous-extinction"].year
    assert events["tiktaalik"].year < events["permian-triassic-extinction"].year


def test_the_ongoing_periods_are_still_going(shipped: HistoryData) -> None:
    periods = {p.id: p for p in shipped.periods}
    assert periods["cenozoic-era"].end == periods["holocene-epoch"].end == ONGOING_END_YEAR
    assert periods["pleistocene-epoch"].end == periods["holocene-epoch"].start
    assert periods["younger-dryas"].end == periods["holocene-epoch"].start


def test_the_prehistory_events_are_in_a_sensible_order(shipped: HistoryData) -> None:
    years = {e.id: e.year for e in shipped.events}
    order = [
        "first-homo-sapiens",
        "toba-eruption",
        "out-of-africa",
        "neanderthals-disappear",
        "chauvet-cave-paintings",
        "first-pottery",
        "humans-reach-the-americas",
        "farming-begins",
        "wheeled-vehicles",
        "otzi-the-iceman",
    ]
    assert [years[i] for i in order] == sorted(years[i] for i in order)
    assert years["earliest-writing"] < years["otzi-the-iceman"]


def test_the_landmarks_are_real_places_and_built_in_prehistory(shipped: HistoryData) -> None:
    sites = {m.id: m for m in shipped.landmarks}
    assert 36 < sites["gobekli-tepe"].lat < 38 and 38 < sites["gobekli-tepe"].lon < 40
    assert 51 < sites["stonehenge"].lat < 52 and -2 < sites["stonehenge"].lon < -1
    assert sites["gobekli-tepe"].built_end < sites["stonehenge"].built_start < -3000
