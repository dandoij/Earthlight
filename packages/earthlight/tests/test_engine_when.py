"""Tests for moment to place: ``engine.when``."""

import math
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from earthlight import engine
from earthlight.engine import FutureMomentError, MomentError, lookback_years, when
from earthlight.models import MomentResult
from earthlight.repository import Repository, default_repository
from earthlight.schema import create_empty_database
from earthlight.solar_system import PROXIMA_CENTAURI_AU, au_to_light_years
from earthlight.time import from_calendar

NOW = from_calendar(2026, 6, 15, 12)
YEAR = 365.25  # days


def ago(years: float = 0.0, *, days: float = 0.0, hours: float = 0.0) -> float:
    """The moment this long before NOW."""
    return NOW - years - days / YEAR - hours / (YEAR * 24)


def categories(result: MomentResult) -> dict[str, object]:
    return {
        "famous": result.famous,
        "exoplanet": result.exoplanet,
        "visible_tonight": result.visible_tonight,
        "most_precise": result.most_precise,
    }


# --- errors ----------------------------------------------------------------------------------


def test_a_moment_in_the_future_is_rejected_with_a_friendly_message() -> None:
    with pytest.raises(FutureMomentError, match="has not happened yet"):
        when(NOW + 0.5, now_year=NOW)


def test_the_future_error_is_a_moment_error_and_a_value_error() -> None:
    assert issubclass(FutureMomentError, MomentError) and issubclass(MomentError, ValueError)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_moment_that_is_not_a_finite_number_is_rejected(bad: float) -> None:
    with pytest.raises(MomentError, match="not a real point in time"):
        when(bad, now_year=NOW)


def test_the_moment_this_instant_is_not_the_future() -> None:
    result = when(NOW, now_year=NOW)
    assert result.lookback_years == 0 and result.zone is not None


# --- one clock read --------------------------------------------------------------------------


def test_the_clock_is_read_exactly_once_per_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[float] = []

    def fake_now() -> float:
        reads.append(NOW)
        return NOW

    monkeypatch.setattr(engine, "now", fake_now)
    when(ago(500), repository=default_repository())
    assert reads == [NOW]


def test_the_same_question_gets_the_same_answer() -> None:
    assert when(ago(500), now_year=NOW) == when(ago(500), now_year=NOW)


# --- inside the solar system -----------------------------------------------------------------


def test_light_from_three_hours_ago_is_among_the_planets() -> None:
    result = when(ago(hours=3), now_year=NOW)
    assert result.zone is not None and result.zone.id == "heliosphere"
    assert result.lookback_years == pytest.approx(3 / (24 * YEAR), rel=1e-3)
    assert all(match is None for match in categories(result).values())
    text = " ".join(result.notes)
    assert "light-hours" in text and "Mercury" in text and "Neptune" in text
    assert "No star is this close" in text


def test_light_from_a_day_ago_has_passed_voyager_1() -> None:
    result = when(ago(days=1), now_year=NOW)
    assert result.zone is not None and result.zone.id == "beyond-heliopause"
    assert any("Voyager 1" in note and "has passed" in note for note in result.notes)


def test_light_from_two_hours_ago_has_not_reached_voyager_1() -> None:
    result = when(ago(hours=2), now_year=NOW)
    assert not any("Voyager 1" in note for note in result.notes)  # far too close to compare


def test_light_from_a_month_and_two_years_ago_is_in_the_oort_cloud_and_beyond() -> None:
    month = when(ago(days=30), now_year=NOW)
    two_years = when(ago(2), now_year=NOW)
    assert month.zone is not None and month.zone.id == "inner-oort-cloud"
    assert two_years.zone is not None and two_years.zone.id == "interstellar-space"
    assert month.zone.percent_to_proxima is not None
    assert two_years.zone.percent_to_proxima is not None
    assert 0 < month.zone.percent_to_proxima < two_years.zone.percent_to_proxima < 100
    assert two_years.zone.percent_to_proxima == pytest.approx(100 * 2 / 4.2441, rel=0.01)


def test_progress_toward_proxima_reaches_100_at_the_star() -> None:
    proxima_years = au_to_light_years(PROXIMA_CENTAURI_AU)
    result = when(ago(proxima_years), now_year=NOW)
    assert result.zone is not None and result.zone.percent_to_proxima == pytest.approx(
        100, rel=1e-3
    )


def test_just_past_proxima_the_stars_take_over() -> None:
    result = when(ago(4.2465), now_year=NOW)
    assert result.zone is None
    assert result.famous is not None and result.famous.vantage_point.id == "hip-70890"


def test_planet_notes_are_left_out_when_the_present_is_outside_the_planet_table() -> None:
    far_future_now = 2100.0
    result = when(far_future_now - 3 / (24 * YEAR), now_year=far_future_now)
    assert not any("Mercury" in note for note in result.notes)


# --- the stars --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("moment", "label"),
    [(1492.5, "1492 CE"), (476.7, "476 CE"), (ago(500), "1526 CE"), (-999.0, "1000 BCE")],
)
def test_historic_moments_get_all_four_categories(moment: float, label: str) -> None:
    result = when(moment, now_year=NOW)
    assert result.moment_label == label
    assert result.zone is None
    matches = categories(result)
    assert all(m is not None for m in matches.values()), result.notes


def test_a_winner_that_contains_the_moment_has_a_range_around_it() -> None:
    result = when(1492.5, now_year=NOW)
    for match in (result.famous, result.exoplanet, result.visible_tonight, result.most_precise):
        assert match is not None
        point = match.vantage_point
        exact = point.lookback.contains(result.lookback_years)
        approximate = any("approximate match" in note for note in result.notes)
        assert exact or approximate
        assert match.offset_years == pytest.approx(point.lookback.best - result.lookback_years)


def test_famous_is_the_best_known_place_that_contains_the_moment() -> None:
    result = when(1492.5, now_year=NOW)
    assert result.famous is not None
    candidates = default_repository().vantage_points_overlapping(
        result.lookback_years, result.lookback_years
    )
    assert result.famous.vantage_point.fame == max(p.fame for p in candidates)


def test_most_precise_is_the_narrowest_range_that_contains_the_moment() -> None:
    result = when(1492.5, now_year=NOW)
    assert result.most_precise is not None
    candidates = default_repository().vantage_points_overlapping(
        result.lookback_years, result.lookback_years
    )
    narrowest = min(p.lookback.maximum - p.lookback.minimum for p in candidates)
    assert result.most_precise.range_width_years == pytest.approx(narrowest)


def test_visible_tonight_is_a_naked_eye_star_with_a_constellation() -> None:
    result = when(1492.5, now_year=NOW)
    assert result.visible_tonight is not None
    star = result.visible_tonight.vantage_point
    assert star.kind.value == "star" and star.constellation is not None
    assert star.magnitude is not None and star.magnitude <= engine.NAKED_EYE_MAGNITUDE


def test_the_exoplanet_category_only_holds_exoplanets() -> None:
    result = when(1492.5, now_year=NOW)
    assert result.exoplanet is not None
    assert result.exoplanet.vantage_point.kind.value == "exoplanet"


# --- deep time -------------------------------------------------------------------------------


@pytest.mark.parametrize("years_ago", [66e6, 4.5e9])
def test_deep_time_with_nothing_nearby_explains_each_empty_category(years_ago: float) -> None:
    result = when(NOW - years_ago, now_year=NOW)
    assert result.zone is None
    assert all(match is None for match in categories(result).values())
    assert len(result.notes) == 4
    assert all("comes within 5%" in note for note in result.notes)


def test_the_moment_label_for_deep_time_is_in_years_ago() -> None:
    assert when(NOW - 66e6, now_year=NOW).moment_label == "66 million years ago"


def test_a_moment_before_the_oldest_light_says_so_and_shows_no_near_misses() -> None:
    result = when(NOW - 20e9, now_year=NOW)
    assert all(match is None for match in categories(result).values())
    assert len(result.notes) == 1 and "older than the oldest light" in result.notes[0]


def test_just_inside_the_oldest_light_the_microwave_background_can_be_a_near_miss() -> None:
    result = when(NOW - 13.7e9, now_year=NOW)
    assert result.famous is not None
    assert result.famous.vantage_point.id == "cosmic-microwave-background"
    assert any("approximate match" in note for note in result.notes)


def test_a_near_miss_is_marked_approximate_and_says_which_way_it_is_off() -> None:
    result = when(ago(20_000), now_year=NOW)
    assert result.exoplanet is not None
    point = result.exoplanet.vantage_point
    if not point.lookback.contains(result.lookback_years):
        assert any(point.name in note and "approximate match" in note for note in result.notes)


# --- the lookback arithmetic -----------------------------------------------------------------


def test_lookback_counts_real_seconds_in_a_leap_year() -> None:
    now_in_leap_year = from_calendar(2024, 12, 31, 12)
    earlier = from_calendar(2024, 12, 31, 9)
    assert lookback_years(earlier, now_in_leap_year) == pytest.approx(3 / (24 * YEAR), rel=1e-6)


# --- ranking rules, on a tiny hand-made database ----------------------------------------------


def add_place(
    connection: sqlite3.Connection,
    place_id: str,
    kind: str,
    low: float,
    best: float,
    high: float,
    *,
    magnitude: float | None = None,
    constellation: str | None = None,
    fame: int = 0,
) -> None:
    connection.execute(
        "INSERT INTO vantage_points (id, name, kind, lookback_min, lookback_best, lookback_max, "
        "magnitude, constellation, fame) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (place_id, place_id.upper(), kind, low, best, high, magnitude, constellation, fame),
    )


@pytest.fixture
def small(tmp_path: Path) -> Iterator[tuple[sqlite3.Connection, Path]]:
    path = tmp_path / "small.db"
    create_empty_database(path)
    connection = sqlite3.connect(path)
    yield connection, path
    connection.close()


def small_answer(small: tuple[sqlite3.Connection, Path], lookback: float = 100.0) -> MomentResult:
    connection, path = small
    connection.commit()
    with Repository(path) as repo:
        return when(NOW - lookback, now_year=NOW, repository=repo)


def test_famous_prefers_the_higher_fame_then_the_closer_best_estimate(
    small: tuple[sqlite3.Connection, Path],
) -> None:
    connection, _ = small
    add_place(connection, "dim-but-close", "star", 90, 100, 110, fame=2)
    add_place(connection, "bright-and-off", "star", 90, 108, 130, fame=4)
    add_place(connection, "bright-and-on", "star", 80, 101, 130, fame=4)
    result = small_answer(small)
    assert result.famous is not None and result.famous.vantage_point.id == "bright-and-on"


def test_places_with_no_fame_are_never_famous(small: tuple[sqlite3.Connection, Path]) -> None:
    connection, _ = small
    add_place(connection, "nobody", "star", 90, 100, 110, fame=0)
    result = small_answer(small)
    assert result.famous is None and result.most_precise is not None


def test_most_precise_takes_the_narrowest_range(small: tuple[sqlite3.Connection, Path]) -> None:
    connection, _ = small
    add_place(connection, "wide", "galaxy", 50, 100, 150)
    add_place(connection, "narrow", "galaxy", 99, 105, 101.5 + 5)
    add_place(connection, "narrowest", "galaxy", 98, 99, 102)
    result = small_answer(small)
    assert result.most_precise is not None and result.most_precise.vantage_point.id == "narrowest"


def test_visible_tonight_needs_a_bright_star_with_a_constellation(
    small: tuple[sqlite3.Connection, Path],
) -> None:
    connection, _ = small
    add_place(connection, "too-faint", "star", 90, 100, 110, magnitude=6.5, constellation="Lyra")
    add_place(connection, "no-constellation", "star", 90, 100, 110, magnitude=3.0)
    add_place(connection, "a-galaxy", "galaxy", 90, 100, 110, magnitude=3.0, constellation="Lyra")
    assert small_answer(small).visible_tonight is None
    add_place(
        connection, "just-bright-enough", "star", 90, 101, 110, magnitude=6.0, constellation="X"
    )
    add_place(connection, "closer", "star", 90, 100.5, 110, magnitude=5.0, constellation="Y")
    result = small_answer(small)
    assert result.visible_tonight is not None
    assert result.visible_tonight.vantage_point.id == "closer"


def test_exoplanet_takes_the_closest_best_estimate(small: tuple[sqlite3.Connection, Path]) -> None:
    connection, _ = small
    add_place(connection, "far-planet", "exoplanet", 80, 90, 120)
    add_place(connection, "near-planet", "exoplanet", 80, 99, 120)
    add_place(connection, "a-star", "star", 99, 100, 101)
    result = small_answer(small)
    assert result.exoplanet is not None and result.exoplanet.vantage_point.id == "near-planet"


def test_equal_contenders_are_split_by_id_so_answers_are_stable(
    small: tuple[sqlite3.Connection, Path],
) -> None:
    connection, _ = small
    add_place(connection, "b-twin", "star", 90, 100, 110, fame=3)
    add_place(connection, "a-twin", "star", 90, 100, 110, fame=3)
    result = small_answer(small)
    assert result.famous is not None and result.famous.vantage_point.id == "a-twin"


def test_the_near_miss_window_is_five_percent_of_the_lookback(
    small: tuple[sqlite3.Connection, Path],
) -> None:
    connection, _ = small
    add_place(connection, "just-inside", "star", 104, 104.5, 105, fame=3)  # 4% away
    add_place(connection, "just-outside", "star", 106, 106.5, 107, fame=5)  # 6% away
    result = small_answer(small)
    assert result.famous is not None and result.famous.vantage_point.id == "just-inside"
    assert result.famous.offset_years == pytest.approx(4.5)
    assert any("just-inside".upper() in note and "farther" in note for note in result.notes)


def test_an_exact_match_beats_a_closer_best_estimate_that_does_not_contain_the_moment(
    small: tuple[sqlite3.Connection, Path],
) -> None:
    connection, _ = small
    add_place(connection, "contains", "star", 50, 60, 150, fame=1)
    add_place(connection, "misses", "star", 100.5, 100.6, 100.7, fame=5)
    result = small_answer(small)
    assert result.famous is not None and result.famous.vantage_point.id == "contains"
    assert not any("approximate match" in note for note in result.notes)


# --- the answer is a model --------------------------------------------------------------------


def test_the_result_survives_a_round_trip_through_json() -> None:
    result = when(ago(500), now_year=NOW)
    assert MomentResult.model_validate_json(result.model_dump_json()) == result


def test_inside_the_solar_system_there_are_no_near_misses_even_though_proxima_is_close() -> None:
    result = when(ago(4.1), now_year=NOW)  # 4% short of Proxima Centauri
    assert result.zone is not None
    assert all(match is None for match in categories(result).values())
    assert not any("approximate match" in note for note in result.notes)


def test_light_older_than_the_oldest_light_has_no_near_misses_either() -> None:
    result = when(NOW - 13.85e9, now_year=NOW)  # within 5% of the microwave background
    assert all(match is None for match in categories(result).values())
    assert not any("approximate match" in note for note in result.notes)


def test_ties_are_broken_by_id_whatever_order_the_candidates_arrive_in(
    small: tuple[sqlite3.Connection, Path],
) -> None:
    connection, path = small
    add_place(connection, "a-twin", "star", 90, 100, 110, fame=3)
    add_place(connection, "b-twin", "star", 90, 100, 110, fame=3)
    connection.commit()
    with Repository(path) as repo:
        twins = repo.vantage_points_overlapping(100, 100)
    category = engine._CATEGORIES[0]  # pyright: ignore[reportPrivateUsage]
    for order in (twins, twins[::-1]):
        match = engine._best(category, order, 100.0)  # pyright: ignore[reportPrivateUsage]
        assert match is not None and match.vantage_point.id == "a-twin"
