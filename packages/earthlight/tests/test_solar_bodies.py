"""Tests for the Sun, the Moon, and the planets as places, and the orbit bounds behind them.

Reference values come from cited sources, copied here so the tests run offline:

* NASA JPL Horizons geocentric vectors for the planets (data/horizons_planets.json).
* "Approximate Positions of the Planets", NASA JPL Solar System Dynamics: the Table 1 elements,
  used by hand below to re-derive the orbit bounds from perihelion and aphelion.
* NASA Moon Fact Sheet: the Moon is "roughly" 357,000 km to 407,000 km from Earth, mean
  distance (semimajor axis) 384,400 km.
"""

import json
import math
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from earthlight.models import VantageKind
from earthlight.solar_bodies import (
    PLANET_IDS,
    SOLAR_BODIES,
    SOLAR_BODY_IDS,
    find_solar_body,
    is_earth,
    solar_body,
    solar_body_names,
)
from earthlight.solar_system import (
    PLANETS,
    TABLE_END_MOMENT,
    TABLE_FIRST_MOMENT,
    Planet,
    earth_sun_distance_au,
    earth_sun_distance_bounds_au,
    planet_distance_au,
    planet_distance_bounds_au,
)
from earthlight.time import SECONDS_PER_JULIAN_YEAR, from_calendar

HORIZONS = json.loads((Path(__file__).parent / "data" / "horizons_planets.json").read_text("utf-8"))
REFERENCE_MOMENTS = [from_calendar(*date) for date in HORIZONS["dates"]]
SECONDS_PER_YEAR = SECONDS_PER_JULIAN_YEAR
SPEED_OF_LIGHT_KM_S = 299_792.458
moments = st.floats(min_value=TABLE_FIRST_MOMENT, max_value=TABLE_END_MOMENT - 0.01)


# --- the bounds ------------------------------------------------------------------------------


@pytest.mark.parametrize("planet", PLANETS)
def test_every_real_distance_from_horizons_lies_inside_the_bounds(planet: Planet) -> None:
    for moment, vector in zip(REFERENCE_MOMENTS, HORIZONS["vectors_au"][planet], strict=True):
        nearest, farthest = planet_distance_bounds_au(planet, moment)
        assert nearest <= math.hypot(*vector) <= farthest, (planet, moment)


@pytest.mark.parametrize("planet", PLANETS)
@given(moment=moments)
def test_the_modelled_distance_always_lies_inside_the_bounds(planet: Planet, moment: float) -> None:
    nearest, farthest = planet_distance_bounds_au(planet, moment)
    assert 0 <= nearest <= planet_distance_au(planet, moment) <= farthest


@pytest.mark.parametrize(
    ("planet", "nearest", "farthest"),
    [
        # Worked by hand from the Table 1 elements at J2000 (Earth: a 1.00000261, e 0.01671123,
        # so it is 0.98329 to 1.01671 au from the Sun):
        # Mercury (a 0.38709927, e 0.20563593): the Earth's closest minus Mercury's farthest
        # 0.98329 - 0.46670, and Mercury's farthest plus the Earth's farthest 0.46670 + 1.01671.
        ("mercury", 0.5166, 1.4834),
        # Mars (a 1.52371034, e 0.09339410): Mars's closest 1.38139 minus the Earth's farthest
        # 1.01671, and Mars's farthest 1.66603 plus 1.01671.
        ("mars", 0.3647, 2.6827),
        # Jupiter (a 5.20288700, e 0.04838624): 4.95115 - 1.01671 and 5.45462 + 1.01671.
        ("jupiter", 3.9344, 6.4713),
    ],
)
def test_bounds_agree_with_the_hand_worked_orbits(
    planet: Planet, nearest: float, farthest: float
) -> None:
    low, high = planet_distance_bounds_au(planet, 2000.0)
    assert low == pytest.approx(nearest, abs=0.003)
    assert high == pytest.approx(farthest, abs=0.003)


def test_the_bounds_do_not_depend_on_where_the_planet_is_today() -> None:
    early = planet_distance_bounds_au("saturn", 2026.0)
    late = planet_distance_bounds_au("saturn", 2026.5)
    assert early == pytest.approx(late, abs=0.001)


def test_the_earth_is_nearest_the_sun_in_early_january_and_farthest_in_early_july() -> None:
    assert earth_sun_distance_au(2026.01) == pytest.approx(0.9833, abs=0.0015)
    assert earth_sun_distance_au(2026.5) == pytest.approx(1.0166, abs=0.0015)
    nearest, farthest = earth_sun_distance_bounds_au(2026.0)
    assert (nearest, farthest) == pytest.approx((0.98329, 1.01671), abs=0.0005)


@pytest.mark.parametrize("function", [earth_sun_distance_au, earth_sun_distance_bounds_au])
@pytest.mark.parametrize("moment", [1799.0, 2051.0])
def test_orbit_functions_refuse_dates_outside_the_table(function, moment: float) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="1800 to 2050"):
        function(moment)


def test_planet_bounds_refuse_unknown_planets_and_dates_outside_the_table() -> None:
    with pytest.raises(ValueError, match="unknown planet"):
        planet_distance_bounds_au("pluto", 2026.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="1800 to 2050"):
        planet_distance_bounds_au("mars", 2100.0)


# --- the bodies ------------------------------------------------------------------------------


def test_there_are_nine_bodies_with_the_right_kinds() -> None:
    assert SOLAR_BODY_IDS == (
        "sun",
        "moon",
        "mercury",
        "venus",
        "mars",
        "jupiter",
        "saturn",
        "uranus",
        "neptune",
    )
    assert SOLAR_BODY_IDS[2:] == PLANET_IDS
    kinds = {body.id: body.kind for body in SOLAR_BODIES}
    assert kinds["sun"] is VantageKind.STAR
    assert kinds["moon"] is VantageKind.MOON
    assert {kinds[i] for i in PLANET_IDS} == {VantageKind.PLANET}


@pytest.mark.parametrize("body_id", SOLAR_BODY_IDS)
@given(moment=moments)
def test_every_body_has_an_ordered_lookback_range_with_the_best_inside(
    body_id: str, moment: float
) -> None:
    point = solar_body(body_id, moment)
    assert point is not None
    lookback = point.lookback
    assert 0 < lookback.minimum <= lookback.best <= lookback.maximum
    assert point.id == body_id
    assert point.name == body_id.capitalize()


def test_an_id_that_is_not_a_solar_body_gives_nothing() -> None:
    assert solar_body("hip-27989", 2026.0) is None
    assert solar_body("earth", 2026.0) is None
    assert solar_body("", 2026.0) is None


def seconds(years: float) -> float:
    return years * SECONDS_PER_YEAR


def test_the_moon_is_a_second_or_so_away() -> None:
    point = solar_body("moon", 2026.0)
    assert point is not None
    assert seconds(point.lookback.minimum) == pytest.approx(357_000 / SPEED_OF_LIGHT_KM_S, rel=1e-4)
    assert seconds(point.lookback.best) == pytest.approx(384_400 / SPEED_OF_LIGHT_KM_S, rel=1e-4)
    assert seconds(point.lookback.maximum) == pytest.approx(407_000 / SPEED_OF_LIGHT_KM_S, rel=1e-4)
    assert point.facts == {
        "distance_source": "nasa_moon_fact_sheet",
        "mean_distance_km": 384_400.0,
    }


@given(moment=moments)
def test_the_moon_does_not_depend_on_the_date(moment: float) -> None:
    assert solar_body("moon", moment) == solar_body("moon", 2026.0)


def test_the_sun_is_about_eight_light_minutes_away_and_a_star() -> None:
    point = solar_body("sun", 2026.0)
    assert point is not None
    assert point.kind is VantageKind.STAR
    assert seconds(point.lookback.best) / 60 == pytest.approx(8.18, abs=0.05)  # January: nearest
    july = solar_body("sun", 2026.5)
    assert july is not None
    assert seconds(july.lookback.best) / 60 == pytest.approx(8.46, abs=0.05)


@pytest.mark.parametrize("planet", PLANETS)
def test_a_planet_is_where_horizons_says_on_the_reference_dates(planet: Planet) -> None:
    for moment, vector in zip(REFERENCE_MOMENTS, HORIZONS["vectors_au"][planet], strict=True):
        point = solar_body(planet, moment)
        assert point is not None
        light_seconds = seconds(point.lookback.best)
        # JPL's own error for these elements reaches ~1.5 million km (Saturn): 0.02 au is 10 s.
        assert light_seconds == pytest.approx(math.hypot(*vector) * 499.00478, abs=10)


def test_saturn_today_is_over_an_hour_away() -> None:
    point = solar_body("saturn", 2026.0)
    assert point is not None
    minutes = seconds(point.lookback.best) / 60
    assert 65 < minutes < 95
    assert point.facts["distance_source"] == "jpl_approximate_elements"
    assert point.facts["distance_au"] == pytest.approx(minutes * 60 / 499.00478, abs=0.001)


@pytest.mark.parametrize("moment", [1500.0, 1799.9, 2051.0, 2500.0])
def test_outside_the_orbit_table_the_best_is_the_middle_of_the_range(moment: float) -> None:
    point = solar_body("jupiter", moment)
    assert point is not None
    lookback = point.lookback
    assert lookback.best == pytest.approx((lookback.minimum + lookback.maximum) / 2)
    assert point.facts == {"distance_source": "orbit_range_midpoint"}
    edge = solar_body("jupiter", 2000.0)
    assert edge is not None
    assert lookback.minimum == pytest.approx(edge.lookback.minimum, rel=0.01)
    sun = solar_body("sun", moment)
    assert sun is not None
    assert sun.facts == {"distance_source": "orbit_range_midpoint"}


# --- names -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "body_id"),
    [
        ("Saturn", "saturn"),
        ("saturn", "saturn"),
        ("  SATURN  ", "saturn"),
        ("the sun", "sun"),
        ("The Sun", "sun"),
        ("Sol", "sun"),
        ("sun", "sun"),
        ("The Moon", "moon"),
        ("Luna", "moon"),
        ("earth's moon", "moon"),
        ("mercury", "mercury"),
    ],
)
def test_bodies_are_found_by_name(text: str, body_id: str) -> None:
    body = find_solar_body(text)
    assert body is not None
    assert body.id == body_id


@pytest.mark.parametrize(
    "text", ["Sunflower Galaxy", "Saturnia", "sun and moon", "", "earth", "pluto", "Sir"]
)
def test_other_text_is_not_a_body(text: str) -> None:
    assert find_solar_body(text) is None


def test_the_earth_is_recognised_so_it_can_be_explained() -> None:
    assert is_earth("Earth")
    assert is_earth("the earth")
    assert is_earth("planet Earth")
    assert not is_earth("moon")
    assert not is_earth("Earthrise")


def test_did_you_mean_names_include_the_other_names() -> None:
    names = solar_body_names()
    assert {"Sun", "Sol", "Moon", "Luna", "Saturn", "Neptune"} <= set(names)
    assert len(names) == len(set(names))
