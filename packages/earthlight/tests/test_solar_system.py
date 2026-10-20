"""Tests for the solar system module.

Reference values come from two cited sources, copied here so the tests run offline:

* NASA JPL Horizons (https://ssd.jpl.nasa.gov/api/horizons.api), retrieved 2026-10-20.
  Planets: the position vectors in data/horizons_planets.json, which records the exact
  query (geocentric, geometric, not light-time corrected). Voyager 1: COMMAND = -31,
  CENTER = 500@10 (the Sun), EPHEM_TYPE = VECTORS, VEC_CORR = NONE, TIME_TYPE = TDB;
  the distance is the length of the returned vector.
* "Approximate Positions of the Planets", NASA JPL Solar System Dynamics,
  https://ssd.jpl.nasa.gov/planets/approx_pos.html: Table 1 elements, and its table of
  nominal errors for 1800 AD to 2050 AD, used to set the tolerances below.
"""

import dataclasses
import itertools
import json
import math
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from earthlight.lookback import PARSEC_M
from earthlight.solar_system import _ELEMENTS as ELEMENTS  # pyright: ignore[reportPrivateUsage]
from earthlight.solar_system import (
    AU_LIGHT_TIME_SECONDS,
    HELIOPAUSE_AU,
    INNER_OORT_CLOUD_AU,
    OORT_CLOUD_END_AU,
    OUTER_OORT_CLOUD_AU,
    PLANETS,
    PROXIMA_CENTAURI_AU,
    PROXIMA_CENTAURI_DISTANCE_PC,
    TABLE_END_MOMENT,
    TABLE_FIRST_MOMENT,
    ZONES,
    Planet,
    au_to_light_years,
    julian_date,
    light_time_seconds,
    planet_distance_au,
    planet_position_au,
    voyager1_distance_au,
    zone_for_lookback,
)
from earthlight.time import from_calendar

AU_KM = 149_597_870.7
ARCSECOND = math.pi / (180 * 3600)

# --- Julian date ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("date", "expected"),
    [
        ((2000, 1, 1, 12), 2451545.0),  # J2000.0, by definition
        ((1858, 11, 17, 0), 2400000.5),  # Modified Julian Date zero, by definition
        ((1900, 1, 1, 0), 2415020.5),  # Horizons JD list
        ((1950, 1, 1, 0), 2433282.5),
        ((2026, 1, 1, 0), 2461041.5),
        ((2050, 1, 1, 0), 2469807.5),
        ((2024, 7, 2, 0), 2460493.5),  # mid-leap-year check: JD of 2024-01-01 is 2460310.5
    ],
)
def test_julian_date(date: tuple[int, int, int, int], expected: float) -> None:
    assert julian_date(from_calendar(*date)) == pytest.approx(expected, abs=1e-6)


# --- orbital elements against JPL's Table 1 -------------------------------------------------


def parse_jpl_table1() -> dict[str, tuple[float, ...]]:
    """Read data/jpl_table1.txt into {name: (a, a_rate, e, e_rate, ...)}, interleaving each
    planet's row of J2000 values with its row of rates, in the order the code stores them."""
    text = (Path(__file__).parent / "data" / "jpl_table1.txt").read_text("utf-8")
    rows = [line.split() for line in text.splitlines() if line and not line.startswith("#")]
    table: dict[str, tuple[float, ...]] = {}
    for values_row, rates_row in zip(rows[0::2], rows[1::2], strict=True):
        name = " ".join(values_row[:-6])
        values = [float(v) for v in values_row[-6:]]
        rates = [float(r) for r in rates_row]
        table[name] = tuple(x for pair in zip(values, rates, strict=True) for x in pair)
    return table


def test_orbital_elements_match_a_verbatim_copy_of_jpl_table_1() -> None:
    # Catches a typo in any of the 72 constants, including ones too small for the
    # comparison against Horizons to notice.
    table = parse_jpl_table1()
    assert len(table) == len(ELEMENTS) == 8
    for page_name, numbers in table.items():
        key = "earth" if page_name == "EM Bary" else page_name.lower()
        assert dataclasses.astuple(ELEMENTS[key]) == numbers, page_name


# --- planets against Horizons --------------------------------------------------------

# Geocentric position vectors in au from Horizons at five dates (data/horizons_planets.json
# records the exact query). Whole vectors are compared, not just distances: a distance alone
# is blind to sideways errors when a planet is near opposition or conjunction.
HORIZONS = json.loads((Path(__file__).parent / "data" / "horizons_planets.json").read_text("utf-8"))
REFERENCE_DATES: list[tuple[int, int, int, int]] = [tuple(d) for d in HORIZONS["dates"]]
HORIZONS_VECTORS_AU: dict[str, list[tuple[float, float, float]]] = {
    name: [tuple(v) for v in vectors] for name, vectors in HORIZONS["vectors_au"].items()
}

# Nominal errors for 1800 AD to 2050 AD from the JPL page:
# (distance in thousands of km, longitude in arcsec, latitude in arcsec).
NOMINAL_ERRORS: dict[str, tuple[float, float, float]] = {
    "mercury": (1, 15, 1),
    "venus": (4, 20, 1),
    "earth": (6, 20, 8),  # the page's "EM Bary" row
    "mars": (25, 40, 2),
    "jupiter": (600, 400, 10),
    "saturn": (1500, 600, 25),
    "uranus": (1000, 50, 2),
    "neptune": (200, 10, 1),
}

# Rounded mean distance from the Sun in au, to turn angular errors into kilometres.
MEAN_SUN_DISTANCE_AU = {
    "mercury": 0.39,
    "venus": 0.72,
    "earth": 1.0,
    "mars": 1.52,
    "jupiter": 5.20,
    "saturn": 9.54,
    "uranus": 19.19,
    "neptune": 30.07,
}

# The Sun wobbles around the solar system barycenter. JPL's outer-planet elements
# behave like orbits around that barycenter, so a heliocentric use of them carries the
# wobble as extra error. Horizons (Sun relative to barycenter 500@0, sampled every
# ~5 years across 1800-2050, retrieved 2026-10-20) gives a maximum of 1.45 million km.
SUN_BARYCENTER_WOBBLE_KM = 1.6e6
OUTER_PLANETS = {"jupiter", "saturn", "uranus", "neptune"}


def nominal_error_km(body: str) -> float:
    distance_k, longitude, latitude = NOMINAL_ERRORS[body]
    r_km = MEAN_SUN_DISTANCE_AU[body] * AU_KM
    return math.sqrt(
        (distance_k * 1000) ** 2
        + (r_km * longitude * ARCSECOND) ** 2
        + (r_km * latitude * ARCSECOND) ** 2
    )


# JPL calls its errors "nominal", meaning typical sizes rather than guaranteed bounds,
# and they grow towards the ends of the fitted interval. Across the 35 comparisons below
# the worst case (Mars in 2050) is 1.01 times the nominal combined error and all others
# are at most 0.73, so a 1.5 times allowance covers the method's real behaviour.
NOMINAL_ERROR_ALLOWANCE = 1.5


def tolerance_km(planet: Planet) -> float:
    """Allowed error: JPL's nominal error for the planet plus the Earth (times the
    allowance), plus the Sun's wobble for the outer planets."""
    wobble = SUN_BARYCENTER_WOBBLE_KM if planet in OUTER_PLANETS else 0.0
    nominal = nominal_error_km(planet) + nominal_error_km("earth")
    return NOMINAL_ERROR_ALLOWANCE * nominal + wobble


@pytest.mark.parametrize("planet", PLANETS)
@pytest.mark.parametrize("index", range(len(REFERENCE_DATES)))
def test_planet_position_matches_horizons(planet: Planet, index: int) -> None:
    moment = from_calendar(*REFERENCE_DATES[index])
    reference = HORIZONS_VECTORS_AU[planet][index]
    error_km = math.dist(planet_position_au(planet, moment), reference) * AU_KM
    assert error_km <= tolerance_km(planet)


@pytest.mark.parametrize("planet", PLANETS)
@pytest.mark.parametrize("index", range(len(REFERENCE_DATES)))
def test_planet_distance_matches_horizons(planet: Planet, index: int) -> None:
    moment = from_calendar(*REFERENCE_DATES[index])
    reference = math.hypot(*HORIZONS_VECTORS_AU[planet][index])
    error_km = abs(planet_distance_au(planet, moment) - reference) * AU_KM
    assert error_km <= tolerance_km(planet)
    assert planet_distance_au(planet, moment) == math.hypot(*planet_position_au(planet, moment))


def test_inner_planet_tolerances_are_tight() -> None:
    # Guards against a tolerance so loose that real mistakes pass: for the planets
    # where JPL's errors are small, we hold the code to about 100,000 km.
    for planet in ("mercury", "venus", "mars"):
        assert tolerance_km(planet) < 110_000


# Orbital elements from JPL Table 1 (a in au, e), for the geometry check below.
ORBITS = {
    "mercury": (0.38709927, 0.20563593),
    "venus": (0.72333566, 0.00677672),
    "mars": (1.52371034, 0.09339410),
    "jupiter": (5.20288700, 0.04838624),
    "saturn": (9.53667594, 0.05386179),
    "uranus": (19.18916464, 0.04725744),
    "neptune": (30.06992276, 0.00859048),
}
EARTH_ORBIT = (1.00000261, 0.01671123)


@given(st.sampled_from(PLANETS), st.floats(min_value=TABLE_FIRST_MOMENT, max_value=2050.99))
def test_distance_respects_orbital_geometry(planet: Planet, moment: float) -> None:
    a, e = ORBITS[planet]
    earth_a, earth_e = EARTH_ORBIT
    planet_min, planet_max = a * (1 - e), a * (1 + e)
    earth_min, earth_max = earth_a * (1 - earth_e), earth_a * (1 + earth_e)
    nearest = max(0.0, planet_min - earth_max, earth_min - planet_max)
    farthest = planet_max + earth_max
    slack = 0.01  # element drift over the centuries
    assert nearest - slack <= planet_distance_au(planet, moment) <= farthest + slack


@given(st.sampled_from(PLANETS), st.floats(min_value=TABLE_FIRST_MOMENT, max_value=2049.99))
def test_distance_changes_smoothly(planet: Planet, moment: float) -> None:
    one_day = 1 / 365.25
    change = abs(planet_distance_au(planet, moment + one_day) - planet_distance_au(planet, moment))
    # Earth and a planet cannot close at more than about 60 km/s, which is 0.035 au a day.
    assert change < 0.04


@pytest.mark.parametrize("moment", [TABLE_FIRST_MOMENT - 0.01, TABLE_END_MOMENT, 0.0, 3000.0])
def test_planets_outside_the_fitted_interval_are_rejected(moment: float) -> None:
    with pytest.raises(ValueError, match="1800 to 2050"):
        planet_distance_au("mars", moment)


@pytest.mark.parametrize("moment", [TABLE_FIRST_MOMENT, 2050.99])
def test_interval_edges_are_included(moment: float) -> None:
    assert planet_distance_au("jupiter", moment) > 0


# --- light time ------------------------------------------------------------------------


def test_light_takes_about_499_seconds_to_cross_one_au() -> None:
    # IAU: the light-time for unit distance is 499.004 783 836 s.
    assert pytest.approx(499.004783836, rel=1e-9) == AU_LIGHT_TIME_SECONDS
    assert light_time_seconds(1.0) == AU_LIGHT_TIME_SECONDS
    assert light_time_seconds(0.0) == 0.0
    assert light_time_seconds(10.0) == pytest.approx(10 * AU_LIGHT_TIME_SECONDS)


def test_a_light_year_is_about_63241_au() -> None:
    # IAU: 1 light-year = 63 241.077 au.
    assert 1 / au_to_light_years(1.0) == pytest.approx(63_241.077, rel=1e-8)
    assert au_to_light_years(0.0) == 0.0


def test_jupiter_is_a_little_over_half_an_hour_away_in_light() -> None:
    minutes = light_time_seconds(planet_distance_au("jupiter", from_calendar(2026, 1, 1))) / 60
    assert 30 < minutes < 55  # Jupiter is 4.2 to 6.4 au from Earth


# --- Voyager 1 ---------------------------------------------------------------------------

# Distance from the Sun in au, from Horizons (see module docstring). The 2026 and 2030
# points were used to build the model; the others are independent checks.
VOYAGER1_HORIZONS_AU = [
    ((2012, 8, 25), 121.602494),
    ((2015, 1, 1), 130.016826),
    ((2018, 1, 1), 140.742565),
    ((2020, 1, 1), 147.875719),
    ((2022, 1, 1), 155.009341),
    ((2024, 1, 1), 162.127785),
    ((2026, 1, 1), 169.255256),
    ((2028, 1, 1), 176.372463),
    ((2030, 1, 1), 183.495820),
    ((2032, 12, 31), 194.153902),
]


@pytest.mark.parametrize(("date", "expected"), VOYAGER1_HORIZONS_AU)
def test_voyager1_matches_horizons_within_a_fifth_of_an_au(
    date: tuple[int, int, int], expected: float
) -> None:
    assert voyager1_distance_au(from_calendar(*date)) == pytest.approx(expected, abs=0.2)


def test_voyager1_anchor_points_are_exact() -> None:
    assert voyager1_distance_au(2026.0) == pytest.approx(169.255256, abs=1e-9)
    assert voyager1_distance_au(2030.0) == pytest.approx(183.495820, abs=1e-9)


def test_voyager1_radial_speed_is_close_to_nasas_figure() -> None:
    # NASA quotes 17.0 km/s relative to the Sun (total speed; the radial part is a little less).
    au_per_year = voyager1_distance_au(2031.0) - voyager1_distance_au(2030.0)
    km_per_second = au_per_year * AU_KM / (365.25 * 86_400)
    assert 16.5 < km_per_second < 17.1


def test_voyager1_crossed_the_heliopause_where_the_zone_table_says() -> None:
    # NASA: left the heliosphere on 25 August 2012. Horizons: 121.6 au from the Sun then.
    assert voyager1_distance_au(from_calendar(2012, 8, 25)) == pytest.approx(HELIOPAUSE_AU, abs=0.2)


@pytest.mark.parametrize("moment", [2011.99, 2035.01, 1977.0, 2100.0])
def test_voyager1_outside_the_modelled_years_is_rejected(moment: float) -> None:
    with pytest.raises(ValueError, match="2012 to 2035"):
        voyager1_distance_au(moment)


@given(st.floats(min_value=2012.0, max_value=2034.9))
def test_voyager1_keeps_moving_away(moment: float) -> None:
    assert voyager1_distance_au(moment + 0.1) > voyager1_distance_au(moment)


# --- zones -------------------------------------------------------------------------------


def test_zones_are_contiguous_and_ordered() -> None:
    assert ZONES[0].inner_au == 0.0
    for previous, following in itertools.pairwise(ZONES):
        assert previous.outer_au == following.inner_au
    for zone in ZONES:
        assert zone.inner_au < zone.outer_au


def test_zone_ids_are_unique_and_boundaries_match_the_agreed_values() -> None:
    assert len({zone.id for zone in ZONES}) == len(ZONES)
    assert [z.id for z in ZONES] == [
        "heliosphere",
        "beyond-heliopause",
        "inner-oort-cloud",
        "outer-oort-cloud",
        "interstellar-space",
    ]
    edges = [zone.outer_au for zone in ZONES[:-1]]
    assert edges == [HELIOPAUSE_AU, INNER_OORT_CLOUD_AU, OUTER_OORT_CLOUD_AU, OORT_CLOUD_END_AU]
    assert (HELIOPAUSE_AU, INNER_OORT_CLOUD_AU, OUTER_OORT_CLOUD_AU, OORT_CLOUD_END_AU) == (
        121.6,
        2_000.0,
        20_000.0,
        100_000.0,
    )


def test_proxima_centauri_is_about_4_24_light_years_away() -> None:
    # NASA Exoplanet Archive: sy_dist = 1.30119 pc for Proxima Cen (retrieved 2026-10-20).
    assert PROXIMA_CENTAURI_DISTANCE_PC == 1.30119
    assert au_to_light_years(PROXIMA_CENTAURI_AU) == pytest.approx(4.2438, abs=1e-3)
    assert pytest.approx(1.30119 * PARSEC_M / 149_597_870_700) == PROXIMA_CENTAURI_AU


def test_zone_light_travel_times() -> None:
    hours = light_time_seconds(HELIOPAUSE_AU) / 3600
    assert hours == pytest.approx(16.85, abs=0.05)  # 121.6 au is about 17 light-hours
    days = light_time_seconds(INNER_OORT_CLOUD_AU) / 86_400
    assert days == pytest.approx(11.55, abs=0.05)
    assert au_to_light_years(OORT_CLOUD_END_AU) == pytest.approx(1.58, abs=0.005)


@pytest.mark.parametrize(
    ("lookback_years", "zone_id"),
    [
        (0.0, "heliosphere"),
        (au_to_light_years(HELIOPAUSE_AU) * 0.999, "heliosphere"),
        (au_to_light_years(HELIOPAUSE_AU), "beyond-heliopause"),  # inner edge belongs to the zone
        (1 / 365.25, "beyond-heliopause"),  # one day: about 173 au
        (au_to_light_years(INNER_OORT_CLOUD_AU), "inner-oort-cloud"),
        (0.2, "inner-oort-cloud"),  # about 12,600 au
        (au_to_light_years(OUTER_OORT_CLOUD_AU), "outer-oort-cloud"),
        (1.0, "outer-oort-cloud"),  # about 63,000 au
        (au_to_light_years(OORT_CLOUD_END_AU), "interstellar-space"),
        (2.0, "interstellar-space"),
        (4.2, "interstellar-space"),
        (au_to_light_years(PROXIMA_CENTAURI_AU), "interstellar-space"),  # last edge is included
    ],
)
def test_zone_for_lookback(lookback_years: float, zone_id: str) -> None:
    zone = zone_for_lookback(lookback_years)
    assert zone is not None
    assert zone.id == zone_id


@pytest.mark.parametrize("lookback_years", [-0.001, -1.0, 4.25, 10.0, 1e6])
def test_no_zone_for_negative_or_beyond_proxima(lookback_years: float) -> None:
    assert zone_for_lookback(lookback_years) is None


@given(st.floats(min_value=0, max_value=au_to_light_years(PROXIMA_CENTAURI_AU)))
def test_every_lookback_out_to_proxima_is_in_exactly_one_zone(lookback_years: float) -> None:
    zone = zone_for_lookback(lookback_years)
    assert zone is not None
    assert zone.lookback_range.contains(lookback_years)
    containing = [z for z in ZONES if z.lookback_range.contains(lookback_years)]
    assert zone in containing
    assert len(containing) <= 2  # only a shared edge can be in two ranges


def test_zone_lookback_ranges_are_valid() -> None:
    for zone in ZONES:
        r = zone.lookback_range
        assert 0 <= r.minimum <= r.best <= r.maximum
        assert r.minimum == au_to_light_years(zone.inner_au)
        assert r.maximum == au_to_light_years(zone.outer_au)
