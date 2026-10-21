"""Tests for lookback math."""

import math

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from earthlight.lookback import (
    ASTRONOMICAL_UNIT_M,
    LIGHT_YEAR_M,
    PARSEC_IN_LIGHT_YEARS,
    PARSEC_M,
    LookbackRange,
    MomentRange,
    intervals_overlap,
    lookback_of,
    lookback_range_from_parallax,
    moment_of,
    overlap_width,
    parallax_to_parsecs,
    parsecs_to_light_years,
)

NOW = 2026.5

# --- constants (from definitions, not from datasets) ------------------------


def test_light_year_is_speed_of_light_times_a_julian_year() -> None:
    speed_of_light_m_per_s = 299_792_458  # exact by definition of the metre
    julian_year_s = 365.25 * 86_400
    assert speed_of_light_m_per_s * julian_year_s == LIGHT_YEAR_M


def test_astronomical_unit_matches_iau_2012_definition() -> None:
    assert ASTRONOMICAL_UNIT_M == 149_597_870_700


def test_parsec_matches_iau_2015_nominal_value() -> None:
    # IAU 2015 Resolution B2 gives the parsec as 648000/pi au, about 3.0857e16 m.
    assert pytest.approx(3.085677581e16, rel=1e-9) == PARSEC_M


def test_parsec_in_light_years_is_about_3_26() -> None:
    assert pytest.approx(3.26156, rel=1e-5) == PARSEC_IN_LIGHT_YEARS


# --- LookbackRange -----------------------------------------------------------


@pytest.mark.parametrize(
    ("minimum", "best", "maximum"),
    [(0, 0, 0), (0, 1, 2), (4.2, 4.2, 4.2), (1e9, 13.8e9, 14e9)],
)
def test_lookback_range_accepts_ordered_values(minimum: float, best: float, maximum: float) -> None:
    result = LookbackRange(minimum, best, maximum)
    assert (result.minimum, result.best, result.maximum) == (minimum, best, maximum)


@pytest.mark.parametrize(
    ("minimum", "best", "maximum"),
    [
        (2, 1, 3),  # best below minimum
        (1, 3, 2),  # best above maximum
        (3, 2, 1),  # fully reversed
        (-1, 0, 1),  # negative lookback is not a vantage point
        (math.nan, 1, 2),
        (0, 1, math.inf),
        (0, -math.inf, 1),
    ],
)
def test_lookback_range_rejects_bad_values(minimum: float, best: float, maximum: float) -> None:
    with pytest.raises(ValueError):
        LookbackRange(minimum, best, maximum)


def test_lookback_range_contains_includes_bounds() -> None:
    r = LookbackRange(100, 150, 200)
    assert r.contains(100)
    assert r.contains(150)
    assert r.contains(200)
    assert not r.contains(99.999)
    assert not r.contains(200.001)


def test_lookback_range_overlaps_an_interval() -> None:
    r = LookbackRange(100, 150, 200)
    assert r.overlaps(0, 100)  # touching at the minimum counts
    assert r.overlaps(180, 500)
    assert r.overlaps(120, 130)
    assert not r.overlaps(0, 99)
    assert not r.overlaps(201, 300)


# --- LookbackRange <-> MomentRange -------------------------------------------


def test_place_to_moment_range() -> None:
    moments = LookbackRange(100, 150, 200).to_moments(now_year=NOW)
    assert moments == MomentRange(earliest=1826.5, best=1876.5, latest=1926.5)


def test_moment_to_place_range() -> None:
    lookback = MomentRange(1826.5, 1876.5, 1926.5).to_lookback(now_year=NOW)
    assert lookback == LookbackRange(100, 150, 200)


def test_a_range_that_reaches_the_future_has_no_lookback() -> None:
    with pytest.raises(ValueError):
        MomentRange(2000, 2030, 2040).to_lookback(now_year=NOW)


def test_moment_range_rejects_bad_values() -> None:
    with pytest.raises(ValueError):
        MomentRange(2, 1, 3)
    with pytest.raises(ValueError):
        MomentRange(1, 2, math.nan)


def test_moment_range_overlaps_an_interval() -> None:
    r = MomentRange(1400, 1450, 1500)
    assert r.overlaps(1492, 1492)
    assert r.overlaps(1500, 1600)  # touching counts
    assert not r.overlaps(1501, 1600)


def test_default_reference_time_is_the_current_year() -> None:
    result = LookbackRange(0, 0, 0).to_moments()
    assert 2026 <= result.best < 2200


# --- lookback_of / moment_of -------------------------------------------------


@pytest.mark.parametrize(
    ("moment", "expected"),
    [(2026.5, 0.0), (1492.0, 534.5), (0.0, 2026.5), (-499.0, 2525.5), (2030.0, -3.5)],
)
def test_lookback_of(moment: float, expected: float) -> None:
    assert lookback_of(moment, now_year=NOW) == expected


def test_moment_of_inverts_lookback_of() -> None:
    assert moment_of(534.5, now_year=NOW) == 1492.0
    assert moment_of(-3.5, now_year=NOW) == 2030.0


@given(st.floats(min_value=-1e10, max_value=1e4), st.floats(min_value=1e3, max_value=1e4))
def test_lookback_and_moment_round_trip(moment: float, now_year: float) -> None:
    result = moment_of(lookback_of(moment, now_year=now_year), now_year=now_year)
    assert result == pytest.approx(moment, abs=1e-5)


# --- interval helpers --------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "overlap", "width"),
    [
        ((0, 10), (20, 30), False, 0.0),  # disjoint
        ((0, 10), (10, 30), True, 0.0),  # touching at one point
        ((0, 10), (5, 30), True, 5.0),  # partial
        ((0, 10), (2, 4), True, 2.0),  # nested
        ((0, 10), (0, 10), True, 10.0),  # identical
        ((5, 5), (5, 5), True, 0.0),  # two points
        ((5, 5), (6, 7), False, 0.0),
        ((-10, -5), (-7, 3), True, 2.0),  # negative values
    ],
)
def test_interval_overlap_table(
    a: tuple[float, float], b: tuple[float, float], overlap: bool, width: float
) -> None:
    assert intervals_overlap(*a, *b) is overlap
    assert intervals_overlap(*b, *a) is overlap
    assert overlap_width(*a, *b) == width
    assert overlap_width(*b, *a) == width


@pytest.mark.parametrize("bad", [(2, 1), (math.nan, 1), (1, math.nan)])
def test_reversed_or_nan_intervals_are_rejected(bad: tuple[float, float]) -> None:
    with pytest.raises(ValueError):
        intervals_overlap(*bad, 0, 1)
    with pytest.raises(ValueError):
        intervals_overlap(0, 1, *bad)
    with pytest.raises(ValueError):
        overlap_width(*bad, 0, 1)


_bounds = st.floats(min_value=-1e6, max_value=1e6)


@st.composite
def intervals(draw: st.DrawFn) -> tuple[float, float]:
    low, high = sorted((draw(_bounds), draw(_bounds)))
    return low, high


@given(intervals(), intervals())
def test_overlap_is_symmetric_and_width_is_bounded(
    a: tuple[float, float], b: tuple[float, float]
) -> None:
    assert intervals_overlap(*a, *b) == intervals_overlap(*b, *a)
    width = overlap_width(*a, *b)
    assert 0 <= width <= min(a[1] - a[0], b[1] - b[0])
    if width > 0:
        assert intervals_overlap(*a, *b)


@given(intervals(), intervals(), st.floats(min_value=0, max_value=1))
def test_a_shared_point_means_overlap(
    a: tuple[float, float], b: tuple[float, float], fraction: float
) -> None:
    point = a[0] + fraction * (a[1] - a[0])
    assume(b[0] <= point <= b[1])
    assert intervals_overlap(*a, *b)


@given(intervals(), intervals())
def test_overlap_means_a_shared_point_exists(
    a: tuple[float, float], b: tuple[float, float]
) -> None:
    if intervals_overlap(*a, *b):
        shared = max(a[0], b[0])
        assert a[0] <= shared <= a[1]
        assert b[0] <= shared <= b[1]


@given(st.floats(min_value=0, max_value=1e10), st.floats(min_value=0, max_value=1e10))
def test_contains_agrees_with_a_zero_width_overlap(lookback: float, centre: float) -> None:
    r = LookbackRange(max(0, centre - 5), centre, centre + 5)
    assert r.contains(lookback) == r.overlaps(lookback, lookback)


@given(
    st.floats(min_value=0, max_value=1e9),
    st.floats(min_value=0, max_value=1e9),
    st.floats(min_value=0, max_value=1e9),
)
def test_lookback_moment_ranges_round_trip(a: float, b: float, c: float) -> None:
    low, best, high = sorted((a, b, c))
    original = LookbackRange(low, best, high)
    back = original.to_moments(now_year=NOW).to_lookback(now_year=NOW)
    assert back.minimum == pytest.approx(original.minimum, abs=1e-5)
    assert back.best == pytest.approx(original.best, abs=1e-5)
    assert back.maximum == pytest.approx(original.maximum, abs=1e-5)


# --- distances and parallax --------------------------------------------------


def test_one_parsec_is_a_thousand_milliarcseconds() -> None:
    assert parallax_to_parsecs(1000.0) == 1.0
    assert parallax_to_parsecs(100.0) == 10.0
    assert parallax_to_parsecs(0.5) == 2000.0


def test_parsecs_to_light_years() -> None:
    assert parsecs_to_light_years(0.0) == 0.0
    assert parsecs_to_light_years(1.0) == PARSEC_IN_LIGHT_YEARS
    assert parsecs_to_light_years(10.0) == pytest.approx(32.6156, rel=1e-5)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_parallax_must_be_positive_and_finite(bad: float) -> None:
    with pytest.raises(ValueError):
        parallax_to_parsecs(bad)
    with pytest.raises(ValueError):
        lookback_range_from_parallax(bad, 0.1)


def test_parallax_range_without_error_is_a_single_value() -> None:
    r = lookback_range_from_parallax(100.0, 0.0)
    assert r.minimum == r.best == r.maximum == parsecs_to_light_years(10.0)


def test_parallax_range_brackets_the_best_estimate() -> None:
    r = lookback_range_from_parallax(10.0, 1.0)
    assert r.minimum == pytest.approx(parsecs_to_light_years(1000 / 11))
    assert r.best == pytest.approx(parsecs_to_light_years(100))
    assert r.maximum == pytest.approx(parsecs_to_light_years(1000 / 9))


def test_more_sigmas_widen_the_range() -> None:
    one = lookback_range_from_parallax(10.0, 1.0, sigmas=1)
    three = lookback_range_from_parallax(10.0, 1.0, sigmas=3)
    assert three.minimum < one.minimum
    assert three.maximum > one.maximum
    assert three.best == one.best


def test_zero_sigmas_collapses_the_range() -> None:
    r = lookback_range_from_parallax(10.0, 1.0, sigmas=0)
    assert r.minimum == r.best == r.maximum


@pytest.mark.parametrize(
    ("error", "sigmas"),
    [(10.0, 1.0), (4.0, 3.0), (11.0, 1.0)],  # the low parallax reaches or crosses zero
)
def test_unbounded_distance_is_an_error(error: float, sigmas: float) -> None:
    with pytest.raises(ValueError, match="no upper limit"):
        lookback_range_from_parallax(10.0, error, sigmas=sigmas)


@pytest.mark.parametrize(
    ("error", "sigmas"), [(-1.0, 1.0), (math.nan, 1.0), (1.0, -1.0), (1.0, math.nan)]
)
def test_negative_or_nan_error_inputs_are_rejected(error: float, sigmas: float) -> None:
    with pytest.raises(ValueError):
        lookback_range_from_parallax(10.0, error, sigmas=sigmas)


@given(
    st.floats(min_value=1e-3, max_value=1e4),
    st.floats(min_value=0, max_value=0.99),
    st.floats(min_value=0, max_value=1),
)
def test_parallax_ranges_are_always_ordered(
    parallax: float, error_fraction: float, sigmas: float
) -> None:
    r = lookback_range_from_parallax(parallax, error_fraction * parallax, sigmas=sigmas)
    assert 0 <= r.minimum <= r.best <= r.maximum


@given(st.floats(min_value=1e-3, max_value=1e4), st.floats(min_value=1e-3, max_value=1e4))
def test_a_larger_parallax_is_always_nearer(a: float, b: float) -> None:
    assume(a < b)
    near = lookback_range_from_parallax(b, 0).best
    far = lookback_range_from_parallax(a, 0).best
    assert near <= far
