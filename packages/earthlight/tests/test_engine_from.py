"""Tests for place to moment: ``engine.from_vantage``."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from earthlight import engine
from earthlight.engine import (
    EARTH_AGE_YEARS,
    MAX_ITEMS_PER_LIST,
    UnknownVantageError,
    from_vantage,
)
from earthlight.models import EarthSnapshot, LandmarkStatus
from earthlight.repository import Repository, default_repository
from earthlight.schema import create_empty_database
from earthlight.time import from_calendar

NOW = from_calendar(2026, 6, 15, 12)
SOURCE = "https://example.org/x"


def snapshot(vantage_id: str) -> EarthSnapshot:
    return from_vantage(vantage_id, now_year=NOW)


# --- the real database, at every scale ----------------------------------------------------------


def test_an_unknown_place_is_a_clear_error() -> None:
    with pytest.raises(UnknownVantageError, match="no place with the id 'nowhere'"):
        snapshot("nowhere")
    assert issubclass(UnknownVantageError, LookupError)


def test_a_nearby_star_sees_earth_a_few_years_ago() -> None:
    result = snapshot("hip-70890")  # Proxima Centauri, 4.2 light-years away
    assert result.earth_exists and result.moments_label == "2022 CE"
    assert result.moments.latest - result.moments.earliest < 0.1
    assert result.population is not None and result.population.year == 2022
    assert any(p.id == "space-age" for p in result.periods)
    assert not result.events  # nothing in the database happened in those few weeks
    assert result.notes and all("very wide" not in note for note in result.notes)


def test_a_star_five_centuries_away_sees_the_age_of_exploration() -> None:
    result = snapshot("hip-27989")  # Betelgeuse, about 500 light-years
    ids = [e.id for e in result.events]
    assert "columbus-reaches-the-americas" in ids
    years = [e.year for e in result.events]
    assert years == sorted(years)  # oldest first
    assert result.population is not None and result.population.year == 1500
    assert any("nearest estimate" in note for note in result.notes)


def test_a_nearby_galaxy_sees_the_ice_age_and_says_the_span_is_wide() -> None:
    result = snapshot("large-magellanic-cloud")  # about 160,000 light-years
    assert result.earth_exists and result.population is None  # long before 10000 BCE
    assert result.landmarks == ()
    assert any("very wide" in note for note in result.notes)
    assert result.moments_label.endswith("years ago")


def test_a_distant_galaxy_sees_an_earth_that_does_not_exist_yet() -> None:
    result = snapshot("gn-z11")
    assert not result.earth_exists
    assert result.events == () and result.periods == () and result.landmarks == ()
    assert result.population is None
    assert any("Earth does not exist yet" in note for note in result.notes)
    assert not any("very wide" in note for note in result.notes)


def test_the_microwave_background_sees_no_earth_either() -> None:
    result = snapshot("cosmic-microwave-background")
    assert not result.earth_exists
    assert result.vantage_point.id == "cosmic-microwave-background"


def test_a_wide_span_lists_only_the_most_important_few_and_says_how_many_there_were() -> None:
    result = snapshot("hip-27989")
    assert len(result.landmarks) == MAX_ITEMS_PER_LIST
    assert any("most important of" in note and "landmarks" in note for note in result.notes)
    assert all(m.importance >= 3 for m in result.landmarks)


def test_the_span_matches_the_lookback_range() -> None:
    result = snapshot("hip-27989")
    point = result.vantage_point
    assert NOW - result.moments.earliest == pytest.approx(point.lookback.maximum, rel=1e-6)
    assert NOW - result.moments.best == pytest.approx(point.lookback.best, rel=1e-6)
    assert NOW - result.moments.latest == pytest.approx(point.lookback.minimum, rel=1e-6)


def test_the_same_question_gets_the_same_answer() -> None:
    assert snapshot("hip-27989") == snapshot("hip-27989")


def test_the_clock_is_read_exactly_once_per_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[float] = []

    def fake_now() -> float:
        reads.append(NOW)
        return NOW

    monkeypatch.setattr(engine, "now", fake_now)
    from_vantage("hip-27989", repository=default_repository())
    assert reads == [NOW]


def test_the_snapshot_survives_a_round_trip_through_json() -> None:
    result = snapshot("hip-27989")
    assert EarthSnapshot.model_validate_json(result.model_dump_json()) == result


# --- rules, on a tiny hand-made world ---------------------------------------------------------


class World:
    """A small database with one place and whatever history a test inserts."""

    def __init__(self, path: Path) -> None:
        create_empty_database(path)
        self.path = path
        self.connection = sqlite3.connect(path)

    def place(self, low: float, best: float, high: float, place_id: str = "spot") -> None:
        """A place with this lookback range, in years."""
        self.connection.execute(
            "INSERT INTO vantage_points (id, name, kind, lookback_min, lookback_best, "
            "lookback_max) VALUES (?, ?, 'star', ?, ?, ?)",
            (place_id, "Spot", low, best, high),
        )

    def spot(self, earliest: float, best: float, latest: float) -> None:
        """A place whose light left Earth at these moments (calendar years)."""
        self.place(NOW - latest, NOW - best, NOW - earliest)

    def event(
        self, event_id: str, year: float, importance: int = 3, uncertainty: float = 0
    ) -> None:
        self.connection.execute(
            "INSERT INTO events (id, name, category, region, summary, importance, source, year, "
            "year_uncertainty) VALUES (?, ?, 'x', 'y', 'z', ?, ?, ?, ?)",
            (event_id, event_id.upper(), importance, SOURCE, year, uncertainty),
        )

    def period(self, period_id: str, start: float, end: float | None, importance: int = 3) -> None:
        self.connection.execute(
            "INSERT INTO periods (id, name, category, region, summary, importance, source, "
            "start_year, end_year, ongoing) VALUES (?, ?, 'x', 'y', 'z', ?, ?, ?, ?, ?)",
            (period_id, period_id.upper(), importance, SOURCE, start, end, int(end is None)),
        )

    def landmark(
        self, landmark_id: str, start: float, end: float, destroyed: float | None = None
    ) -> None:
        self.connection.execute(
            "INSERT INTO landmarks (id, name, category, region, summary, importance, source, "
            "built_start, built_end, destroyed, lat, lon) "
            "VALUES (?, ?, 'x', 'y', 'z', 3, ?, ?, ?, ?, 0, 0)",
            (landmark_id, landmark_id.upper(), SOURCE, start, end, destroyed),
        )

    def population(self, year: float, people: int) -> None:
        self.connection.execute(
            "INSERT INTO population (year, people) VALUES (?, ?)", (year, people)
        )

    def answer(self) -> EarthSnapshot:
        self.connection.commit()
        with Repository(self.path) as repo:
            return from_vantage("spot", now_year=NOW, repository=repo)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    built = World(tmp_path / "world.db")
    yield built
    built.connection.close()


def test_landmark_status_follows_the_middle_of_the_span(world: World) -> None:
    # The light left in 1000 CE (a 100-year span around it), so the middle moment is 1000.
    world.spot(950, 1000, 1050)
    world.landmark("under-way", 990, 1020)  # still being built in 1000
    world.landmark("finished", 900, 950)  # standing in 1000
    world.landmark("fallen", 800, 850, destroyed=990)  # destroyed before 1000
    world.landmark("falls-later", 800, 850, destroyed=1010)  # still there in 1000
    world.landmark("not-yet", 1100, 1160)  # begun after the span: left out
    world.landmark("begins-late", 1030, 1060)  # begun after the middle of the span: left out
    world.landmark("long-gone", 100, 150, destroyed=900)  # gone before the span: left out
    status = {m.id: m.status for m in world.answer().landmarks}
    assert status == {
        "under-way": LandmarkStatus.UNDER_CONSTRUCTION,
        "finished": LandmarkStatus.STANDING,
        "fallen": LandmarkStatus.DESTROYED,
        "falls-later": LandmarkStatus.STANDING,
    }


def test_a_landmark_destroyed_exactly_at_the_middle_counts_as_destroyed(world: World) -> None:
    world.spot(900, 1000, 1100)
    world.landmark("edge", 800, 850, destroyed=1000)
    (only,) = world.answer().landmarks
    assert only.status is LandmarkStatus.DESTROYED


def test_a_landmark_keeps_all_its_details_when_given_a_status(world: World) -> None:
    world.spot(900, 1000, 1100)
    world.landmark("tower", 800, 850)
    (tower,) = world.answer().landmarks
    assert (tower.name, tower.built_start, tower.built_end, tower.lat) == ("TOWER", 800, 850, 0)


def test_periods_include_ongoing_ones_and_exclude_those_that_ended_before(world: World) -> None:
    world.spot(900, 1000, 1100)
    world.period("ongoing-age", 500, None)
    world.period("overlapping", 950, 1200)
    world.period("ended-before", 100, 800)
    world.period("starts-after", 1200, 1300)
    ids = [p.id for p in world.answer().periods]
    assert ids == ["ongoing-age", "overlapping"]


def test_events_are_limited_to_the_most_important_and_listed_oldest_first(world: World) -> None:
    world.spot(900, 1000, 1100)
    for number in range(15):  # 15 events, importance rises with the number
        world.event(f"event-{number:02d}", 900 + number * 10, importance=1 + number // 3)
    result = world.answer()
    assert len(result.events) == MAX_ITEMS_PER_LIST
    shown = [e.id for e in result.events]
    assert shown == sorted(shown)  # the years rise with the number, so oldest first
    # importance 1 (0 to 2) and two of the 2s (4 and 5) are dropped; event 3 is the oldest 2
    assert shown[0] == "event-03" and shown[-1] == "event-14" and "event-04" not in shown
    assert any("10 most important of 15 events" in note for note in result.notes)


def test_nothing_is_cut_when_there_are_few(world: World) -> None:
    world.spot(900, 1000, 1100)
    world.event("only", 1000)
    result = world.answer()
    assert [e.id for e in result.events] == ["only"]
    assert not any("most important of" in note for note in result.notes)


def test_a_span_of_a_thousand_years_or_less_is_not_called_wide(world: World) -> None:
    world.spot(500, 1000, 1500)  # exactly 1,000 years wide
    assert not any("very wide" in note for note in world.answer().notes)
    world.connection.execute("DELETE FROM vantage_points")
    world.spot(499, 1000, 1500)
    assert any("very wide" in note for note in world.answer().notes)


def test_a_span_that_reaches_back_before_earth_is_clipped_to_the_time_since_it_formed(
    world: World,
) -> None:
    near_formation = EARTH_AGE_YEARS - 1e6
    world.place(near_formation, near_formation + 1e6, near_formation + 3e6)
    world.event("after-formation", NOW - near_formation - 5e5)
    world.event("before-formation", NOW - EARTH_AGE_YEARS - 1e6)
    result = world.answer()
    assert result.earth_exists
    assert [e.id for e in result.events] == ["after-formation"]
    assert any("older than Earth" in note for note in result.notes)


def test_light_older_than_earth_has_nothing_to_show_even_if_history_exists(world: World) -> None:
    world.place(5e9, 5.1e9, 5.2e9)
    world.event("big-bang", NOW - 13.8e9)
    world.event("before-earth", NOW - 5.1e9)
    result = world.answer()
    assert not result.earth_exists and result.events == ()


def test_light_exactly_as_old_as_earth_still_shows_earth(world: World) -> None:
    world.place(EARTH_AGE_YEARS - 1, EARTH_AGE_YEARS, EARTH_AGE_YEARS + 1)
    assert world.answer().earth_exists


@pytest.mark.parametrize(
    ("best_year", "expected_year"),
    [(1450, 1400), (-5000, -5000), (2024, 2020)],
)
def test_population_is_the_nearest_estimate(
    world: World, best_year: float, expected_year: float
) -> None:
    for year, people in ((-5000, 5), (1400, 400), (2020, 7800)):
        world.population(year, people)
    world.spot(best_year - 0.1, best_year, best_year + 0.1)
    result = world.answer()
    assert result.population is not None and result.population.year == expected_year


@pytest.mark.parametrize("best_year", [-6000, 2026.2])
def test_population_is_left_out_beyond_the_ends_of_the_data(world: World, best_year: float) -> None:
    world.population(-5000, 5)
    world.population(2020, 7800)
    world.spot(best_year - 0.1, best_year, best_year + 0.1)
    assert world.answer().population is None


def test_population_is_shown_a_few_years_after_the_newest_estimate(world: World) -> None:
    world.population(2020, 7800)
    world.spot(2024.7, 2024.8, 2024.9)
    result = world.answer()
    assert result.population is not None and result.population.year == 2020


def test_no_population_table_is_not_an_error(world: World) -> None:
    world.spot(2015.5, 2016.5, 2017.5)
    assert world.answer().population is None


def test_a_snapshot_of_an_empty_stretch_of_history_is_still_a_valid_answer(world: World) -> None:
    world.spot(2015.5, 2016.5, 2017.5)
    result = world.answer()
    assert (result.events, result.periods, result.landmarks) == ((), (), ())
    assert result.earth_exists


def test_every_scale_of_lookback_gives_a_valid_snapshot() -> None:
    """One place in every 200, from the nearest star to the microwave background."""
    repo = default_repository()
    with sqlite3.connect(f"{repo.path.as_uri()}?mode=ro", uri=True) as connection:
        ids = [
            row[0]
            for row in connection.execute("SELECT id FROM vantage_points ORDER BY lookback_best")
        ]
    sample = ids[::200] + ids[-1:]
    assert len(sample) > 200
    for vantage_id in sample:
        result = snapshot(vantage_id)
        assert result.vantage_point.id == vantage_id
        assert result.moments.earliest <= result.moments.best <= result.moments.latest
        assert result.earth_exists == (result.vantage_point.lookback.best <= EARTH_AGE_YEARS)
        assert len(result.events) <= MAX_ITEMS_PER_LIST
        assert len(result.periods) <= MAX_ITEMS_PER_LIST
        assert len(result.landmarks) <= MAX_ITEMS_PER_LIST
        assert EarthSnapshot.model_validate_json(result.model_dump_json()) == result
