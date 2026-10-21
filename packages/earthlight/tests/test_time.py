"""Tests for the decimal-year time model."""

import contextlib
import math
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from earthlight.time import (
    MAX_CALENDAR_YEAR,
    SECONDS_PER_JULIAN_YEAR,
    CalendarDate,
    Era,
    astronomical_year,
    days_in_year,
    format_year,
    from_calendar,
    from_datetime,
    is_leap_year,
    now,
    seconds_between,
    subtract_seconds,
    to_calendar,
)

# A fixed "now" (15 June 2026, noon UTC) so formatting tests are deterministic.
NOW_DT = datetime(2026, 6, 15, 12, 0, 0)
NOW_YEAR = from_datetime(NOW_DT)

# Written out here on purpose, so the tests do not share code with the module under test.
MONTH_LENGTHS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def ago(**kwargs: float) -> float:
    """Decimal year for a moment some time before the fixed "now"."""
    return from_datetime(NOW_DT - timedelta(**kwargs))


# --- calendar rules ---------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2000, True),
        (1900, False),
        (2024, True),
        (2023, False),
        (0, True),  # 1 BCE is a leap year in the proleptic Gregorian calendar
        (-4, True),
        (-1, False),
        (-100, False),
        (-400, True),
    ],
)
def test_is_leap_year(year: int, expected: bool) -> None:
    assert is_leap_year(year) is expected
    assert days_in_year(year) == (366 if expected else 365)


@pytest.mark.parametrize(
    ("number", "era", "expected"),
    [
        (1, "CE", 1),
        (1492, "CE", 1492),
        (1, "BCE", 0),
        (2, "BCE", -1),
        (500, "BCE", -499),
    ],
)
def test_astronomical_year(number: int, era: Era, expected: int) -> None:
    assert astronomical_year(number, era) == expected


@pytest.mark.parametrize("era", ["CE", "BCE"])
@pytest.mark.parametrize("number", [0, -1])
def test_astronomical_year_rejects_non_positive(number: int, era: Era) -> None:
    with pytest.raises(ValueError, match="start at 1"):
        astronomical_year(number, era)


# --- calendar to decimal year ----------------------------------------------


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((2000,), 2000.0),
        ((0,), 0.0),
        ((-499,), -499.0),
        ((2024, 7, 2), 2024.5),  # day 184 of 366: exactly halfway
        ((2023, 7, 2, 12), 2023.5),  # noon of day 183 of 365: exactly halfway
        ((2024, 12, 31, 23, 59, 59), 2024 + (366 * 86_400 - 1) / (366 * 86_400)),
    ],
)
def test_from_calendar_known_values(args: tuple[int, ...], expected: float) -> None:
    assert from_calendar(*args) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize(
    "args",
    [
        (2000, 0, 1),
        (2000, 13, 1),
        (2023, 2, 29),  # not a leap year
        (2000, 4, 31),
        (2000, 1, 0),
        (2000, 1, 1, 24),
        (2000, 1, 1, 0, 60),
        (2000, 1, 1, 0, 0, 60),
        (2000, 1, 1, 0, 0, -1),
    ],
)
def test_from_calendar_rejects_invalid(args: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        from_calendar(*args)


def test_leap_day_exists_in_year_zero_but_not_year_minus_one() -> None:
    assert from_calendar(0, 2, 29) > 0.0
    with pytest.raises(ValueError):
        from_calendar(-1, 2, 29)


# --- decimal year to calendar ----------------------------------------------


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (2000.0, CalendarDate(2000, 1, 1)),
        (0.0, CalendarDate(0, 1, 1)),
        (2024.5, CalendarDate(2024, 7, 2)),
        (-0.5, CalendarDate(-1, 7, 2, 12)),  # the fraction counts forward from year -1
        (-1.0, CalendarDate(-1, 1, 1)),
        (1492.0, CalendarDate(1492, 1, 1)),
    ],
)
def test_to_calendar_known_values(moment: float, expected: CalendarDate) -> None:
    assert to_calendar(moment) == expected


def test_to_calendar_rolls_over_when_rounding_reaches_next_year() -> None:
    assert to_calendar(2000.0 - 1e-12) == CalendarDate(2000, 1, 1)


@pytest.mark.parametrize("moment", [math.nan, math.inf, -math.inf, MAX_CALENDAR_YEAR + 1.0])
def test_to_calendar_rejects_unrepresentable(moment: float) -> None:
    with pytest.raises(ValueError, match="cannot express"):
        to_calendar(moment)


def test_calendar_limit_applies_to_the_year_not_the_raw_float() -> None:
    # Regression: Hypothesis found that moments inside the last allowed year were rejected.
    moment = from_calendar(MAX_CALENDAR_YEAR, 1, 1, 0, 0, 1)
    assert to_calendar(moment) == CalendarDate(MAX_CALENDAR_YEAR, 1, 1, 0, 0, 1)
    assert to_calendar(from_calendar(-MAX_CALENDAR_YEAR)).year == -MAX_CALENDAR_YEAR


@pytest.mark.parametrize("year", [MAX_CALENDAR_YEAR + 1, -MAX_CALENDAR_YEAR - 1])
def test_from_calendar_rejects_years_beyond_the_limit(year: int) -> None:
    with pytest.raises(ValueError, match="within"):
        from_calendar(year)


@st.composite
def calendar_dates(draw: st.DrawFn) -> CalendarDate:
    year = draw(st.integers(-MAX_CALENDAR_YEAR, MAX_CALENDAR_YEAR))
    month = draw(st.integers(1, 12))
    last_day = MONTH_LENGTHS[month - 1] + (month == 2 and is_leap_year(year))
    return CalendarDate(
        year,
        month,
        draw(st.integers(1, last_day)),
        draw(st.integers(0, 23)),
        draw(st.integers(0, 59)),
        draw(st.integers(0, 59)),
    )


@given(calendar_dates())
def test_calendar_round_trip(date: CalendarDate) -> None:
    moment = from_calendar(date.year, date.month, date.day, date.hour, date.minute, date.second)
    assert to_calendar(moment) == date


@given(calendar_dates(), calendar_dates())
def test_later_dates_have_larger_decimal_years(a: CalendarDate, b: CalendarDate) -> None:
    def key(d: CalendarDate) -> tuple[int, ...]:
        return (d.year, d.month, d.day, d.hour, d.minute, d.second)

    def moment(d: CalendarDate) -> float:
        return from_calendar(d.year, d.month, d.day, d.hour, d.minute, d.second)

    if key(a) < key(b):
        assert moment(a) < moment(b)
    elif key(a) == key(b):
        assert moment(a) == moment(b)


@given(calendar_dates())
def test_moment_stays_inside_its_own_year(date: CalendarDate) -> None:
    moment = from_calendar(date.year, date.month, date.day, date.hour, date.minute, date.second)
    assert math.floor(moment) == date.year


# --- datetime and now() ------------------------------------------------------

_datetimes = st.datetimes(
    min_value=datetime(1, 1, 1), max_value=datetime(9999, 12, 31, 23, 59, 59)
).map(lambda dt: dt.replace(microsecond=0))


@given(_datetimes)
def test_datetime_round_trip(value: datetime) -> None:
    result = to_calendar(from_datetime(value))
    assert result == CalendarDate(
        value.year, value.month, value.day, value.hour, value.minute, value.second
    )


def test_from_datetime_converts_aware_datetimes_to_utc() -> None:
    plus_five = timezone(timedelta(hours=5))
    aware = datetime(2000, 1, 1, 12, tzinfo=plus_five)
    assert from_datetime(aware) == from_calendar(2000, 1, 1, 7)


def test_from_datetime_treats_naive_as_utc() -> None:
    assert from_datetime(datetime(2000, 1, 1, 12)) == from_datetime(
        datetime(2000, 1, 1, 12, tzinfo=UTC)
    )


def test_now_is_between_two_clock_readings() -> None:
    before = from_datetime(datetime.now(UTC))
    reading = now()
    after = from_datetime(datetime.now(UTC))
    assert before <= reading <= after


# --- formatting --------------------------------------------------------------


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (1492.5, "1492 CE"),
        (1.0, "1 CE"),
        (1.99, "1 CE"),
        (0.0, "1 BCE"),
        (0.5, "1 BCE"),
        (-0.5, "2 BCE"),
        (-499.0, "500 BCE"),
        (-9999.0, "10000 BCE"),
        (2026.0, "2026 CE"),
        (2027.5, "2027 CE"),  # the future is shown as a calendar year
    ],
)
def test_format_calendar_years(moment: float, expected: str) -> None:
    assert format_year(moment, now_year=NOW_YEAR) == expected


@pytest.mark.parametrize(
    ("lookback", "expected"),
    [
        (12_026, "12,000 years ago"),  # just past 10000 BCE
        (123_456, "123,000 years ago"),
        (999_600, "1 million years ago"),  # rounds up into the next unit
        (1_000_000, "1 million years ago"),
        (66_000_000, "66 million years ago"),
        (541_000_000, "541 million years ago"),
        (999_600_000, "1 billion years ago"),
        (4_540_000_000, "4.54 billion years ago"),
        (13_800_000_000, "13.8 billion years ago"),
    ],
)
def test_format_deep_time(lookback: float, expected: str) -> None:
    assert format_year(NOW_YEAR - lookback, now_year=NOW_YEAR) == expected


@pytest.mark.parametrize("now_dt", [datetime(2026, 6, 15, 12), datetime(2024, 6, 15, 12)])
@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(0), "just now"),
        (timedelta(seconds=20), "just now"),
        (timedelta(minutes=1), "1 minute ago"),
        (timedelta(minutes=45), "45 minutes ago"),
        (timedelta(hours=1), "1 hour ago"),
        (timedelta(hours=3), "3 hours ago"),
        (timedelta(days=1), "1 day ago"),
        (timedelta(days=12), "12 days ago"),
        (timedelta(days=59), "59 days ago"),
    ],
)
def test_format_recent_moments_in_leap_and_common_years(
    now_dt: datetime, delta: timedelta, expected: str
) -> None:
    reference = from_datetime(now_dt)
    assert format_year(from_datetime(now_dt - delta), now_year=reference) == expected


def test_format_just_over_two_months_ago_falls_back_to_calendar_year() -> None:
    assert format_year(ago(days=61), now_year=NOW_YEAR) == "2026 CE"


def test_format_uses_current_time_by_default() -> None:
    assert format_year(now() - 1e-9) == "just now"


@given(st.floats(min_value=-1e11, max_value=1e11))
def test_format_never_fails_and_never_uses_dashes(moment: float) -> None:
    text = format_year(moment, now_year=NOW_YEAR)
    assert text
    assert "-" not in text


# --- exact short spans ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("earlier", "later", "expected"),
    [
        ((2024, 2, 29, 0), (2024, 3, 1, 0), 86_400.0),
        ((2023, 12, 31, 23), (2024, 1, 1, 0), 3_600.0),  # across New Year
        ((2023, 3, 1, 0), (2024, 3, 1, 0), 366 * 86_400.0),  # includes 29 February 2024
        ((2024, 3, 1, 0), (2025, 3, 1, 0), 365 * 86_400.0),
        ((2024, 1, 1, 0), (2024, 1, 1, 0), 0.0),
        ((2020, 1, 1, 0), (2024, 1, 1, 0), (366 + 365 + 365 + 365) * 86_400.0),
        ((-1, 12, 31, 0), (0, 1, 1, 0), 86_400.0),  # across year 0, a leap year
    ],
)
def test_seconds_between_counts_real_calendar_seconds(
    earlier: tuple[int, int, int, int], later: tuple[int, int, int, int], expected: float
) -> None:
    a, b = from_calendar(*earlier), from_calendar(*later)
    assert seconds_between(a, b) == pytest.approx(expected, abs=1e-3)
    assert seconds_between(b, a) == pytest.approx(-expected, abs=1e-3)


def test_seconds_between_uses_the_julian_year_for_long_spans() -> None:
    assert seconds_between(1900.0, 2000.0) == 100 * SECONDS_PER_JULIAN_YEAR
    assert seconds_between(-1e9, 0.0) == 1e9 * SECONDS_PER_JULIAN_YEAR


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_second_counting_rejects_non_finite_moments(bad: float) -> None:
    with pytest.raises(ValueError):
        seconds_between(bad, 2000.0)
    with pytest.raises(ValueError):
        seconds_between(2000.0, bad)
    with pytest.raises(ValueError):
        subtract_seconds(bad, 1.0)
    with pytest.raises(ValueError):
        subtract_seconds(2000.0, bad)


_recent_datetimes = st.datetimes(
    min_value=datetime(1900, 1, 1), max_value=datetime(2100, 1, 1)
).map(lambda dt: dt.replace(microsecond=0))


@given(_recent_datetimes, st.integers(0, 99 * 365 * 86_400))
def test_subtracting_seconds_matches_datetime_arithmetic(start: datetime, seconds: int) -> None:
    expected = from_datetime(start - timedelta(seconds=seconds))
    assert subtract_seconds(from_datetime(start), seconds) == pytest.approx(expected, abs=1e-9)


@given(_recent_datetimes, st.integers(-50 * 365 * 86_400, 50 * 365 * 86_400))
def test_subtracting_then_measuring_gives_the_seconds_back(start: datetime, seconds: int) -> None:
    moment = from_datetime(start)
    earlier = subtract_seconds(moment, seconds)
    assert seconds_between(earlier, moment) == pytest.approx(seconds, abs=1e-2)


@given(_recent_datetimes, st.integers(-99 * 365 * 86_400, 99 * 365 * 86_400))
def test_seconds_between_matches_datetime_subtraction(a: datetime, seconds: int) -> None:
    # Spans under 100 years are exact; longer ones deliberately use the Julian year.
    b = a + timedelta(seconds=seconds)
    assert seconds_between(from_datetime(a), from_datetime(b)) == pytest.approx(seconds, abs=1e-2)


def test_spans_of_a_century_or_more_may_differ_slightly_from_real_seconds() -> None:
    a, b = datetime(1924, 1, 1), datetime(2024, 1, 1, 0, 1)
    difference = abs(seconds_between(from_datetime(b), from_datetime(a)) + (b - a).total_seconds())
    assert difference < 86_400


def test_subtracting_a_very_long_span_uses_the_julian_year() -> None:
    assert subtract_seconds(2000.0, 66e6 * SECONDS_PER_JULIAN_YEAR) == pytest.approx(2000.0 - 66e6)


def test_three_hours_ago_is_three_hours_in_a_leap_year() -> None:
    # Regression: a fixed 365.25-day year made this 2 hours 59 minutes and 38 seconds.
    reference = from_calendar(2024, 3, 1)
    assert format_year(subtract_seconds(reference, 3 * 3600), now_year=reference) == "3 hours ago"
    assert to_calendar(subtract_seconds(reference, 3 * 3600)) == CalendarDate(2024, 2, 29, 21, 0, 0)


# --- edge inputs ------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_format_year_rejects_non_finite_values_with_value_error(bad: float) -> None:
    with pytest.raises(ValueError, match="cannot format"):
        format_year(bad, now_year=NOW_YEAR)
    with pytest.raises(ValueError, match="cannot format"):
        format_year(2000.0, now_year=bad)


def test_format_year_rejects_a_span_too_large_to_measure() -> None:
    # Both values are finite, but their difference overflows to infinity.
    with pytest.raises(ValueError, match="cannot format"):
        format_year(-1.7e308, now_year=1.7e308)


@given(st.floats())
def test_format_year_only_ever_raises_value_error(moment: float) -> None:
    with contextlib.suppress(ValueError):
        assert format_year(moment, now_year=NOW_YEAR)


def test_from_datetime_rejects_aware_datetimes_that_leave_the_range_in_utc() -> None:
    # Year 1 at +05:00 is year 0 in UTC, and the end of 9999 at -05:00 is year 10000.
    with pytest.raises(ValueError, match="supported range"):
        from_datetime(datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=5))))
    with pytest.raises(ValueError, match="supported range"):
        from_datetime(datetime(9999, 12, 31, 23, tzinfo=timezone(timedelta(hours=-5))))
