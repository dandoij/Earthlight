"""Tests for the unit words shared by the engine's notes and the command line."""

import pytest

from earthlight.lookback import LookbackRange
from earthlight.units import big_number, is_within_a_day, light_range, light_travel, time_span

SECOND = 1 / 31_557_600


def seconds(count: float) -> float:
    return count * SECOND


@pytest.mark.parametrize(
    ("years", "expected"),
    [
        (seconds(1.28), "1.3 light-seconds"),
        (seconds(9.96), "10 light-seconds"),  # no "10.0": the rounded value picks the decimals
        (seconds(45), "45 light-seconds"),
        (seconds(119.6), "2.0 light-minutes"),  # rounds to 120 seconds, so it is minutes
        (seconds(498), "8.3 light-minutes"),
        (seconds(599.7), "10 light-minutes"),
        (seconds(3_000), "50 light-minutes"),
        (seconds(3_599), "1.0 light-hours"),  # not "60 light-minutes"
        (seconds(4_846), "1.3 light-hours"),
        (seconds(47.9 * 3600), "2 light-days"),  # rounds to 48 hours
        (seconds(5 * 86_400), "5 light-days"),
        (4.24, "4.2 light-years"),
        (534.0, "534 light-years"),
        (66e6, "66 million light-years"),
    ],
)
def test_light_travel_picks_the_unit_and_decimals_on_the_rounded_value(
    years: float, expected: str
) -> None:
    assert light_travel(years) == expected


def test_time_span_uses_plain_units() -> None:
    assert time_span(seconds(4_846)) == "1.3 hours"
    assert time_span(seconds(1.28)) == "1.3 seconds"
    assert time_span(534.0) == "534 years"


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        (seconds(257.8), seconds(740.2), "4.3 to 12.3 light-minutes"),  # one precision for both
        (seconds(490.7), seconds(507.3), "8.2 to 8.5 light-minutes"),
        (seconds(1.19), seconds(1.36), "1.2 to 1.4 light-seconds"),
        (seconds(30), seconds(100), "30 to 100 light-seconds"),
        (seconds(3_000), seconds(3 * 3600), "50 light-minutes to 3.0 light-hours"),
        (473.4, 667.0, "473 to 667 light-years"),
        (4.2428, 4.2450, None),
        (seconds(490.7), seconds(490.9), None),
    ],
)
def test_light_range(low: float, high: float, expected: str | None) -> None:
    assert light_range(low, high) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (4.24, "4.2"),
        (534.4, "534"),
        (12_000.0, "12,000"),
        (9.996e8, "1 billion"),
        (66e6, "66 million"),
    ],
)
def test_big_number(value: float, expected: str) -> None:
    assert big_number(value) == expected


@pytest.mark.parametrize(
    ("minimum", "best", "maximum", "expected"),
    [
        (0, seconds(100), seconds(86_399), True),
        (0, seconds(100), seconds(86_401), False),
        (0, seconds(100), seconds(2 * 86_400), False),  # the best is close, the far end is not
        (seconds(1), seconds(1.3), seconds(1.4), True),
    ],
)
def test_a_place_is_about_now_when_even_its_far_end_is_under_a_light_day(
    minimum: float, best: float, maximum: float, expected: bool
) -> None:
    assert is_within_a_day(LookbackRange(minimum, best, maximum)) is expected
