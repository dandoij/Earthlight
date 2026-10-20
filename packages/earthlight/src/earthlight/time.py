"""Decimal years: the time model used everywhere in Earthlight.

A *moment* is a decimal year: a float where the integer part is the astronomical
year and the fraction is how far through that year the moment falls. So 2026.5 is
roughly the middle of 2026.

Astronomical numbering is used, so there is a year 0: 1 BCE is 0, 2 BCE is -1, and
so on. Python's ``datetime`` cannot represent years before 1, so this module has
its own small proleptic Gregorian calendar (the Gregorian leap rules applied to
all years, as in ISO 8601). Historical dates that were originally recorded in the
Julian calendar are not converted; the difference (days) is far below the
precision of anything Earthlight reports.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

DecimalYear = float
"""A moment in time as a decimal astronomical year (for example 1492.25)."""

Era = Literal["CE", "BCE"]

SECONDS_PER_DAY = 86_400
SECONDS_PER_JULIAN_YEAR = 365.25 * SECONDS_PER_DAY
"""Used only to turn a span of years into minutes, hours, and days for display."""

MAX_CALENDAR_YEAR = 1_000_000
"""Largest absolute year the calendar functions accept. Beyond this a float cannot
hold a moment to the second, so a calendar date would be meaningless."""

_OLDEST_CALENDAR_YEAR = -9_999
"""Moments from this astronomical year (10000 BCE) onward are shown as calendar years.
Older moments are shown as "N years ago"."""

_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_RECENT_LIMIT_DAYS = 60


@dataclass(frozen=True)
class CalendarDate:
    """A proleptic Gregorian date and time of day, using astronomical years."""

    year: int
    month: int
    day: int
    hour: int = 0
    minute: int = 0
    second: int = 0


def is_leap_year(year: int) -> bool:
    """Return True if the astronomical year is a leap year (year 0 is a leap year)."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_year(year: int) -> int:
    """Return 366 for leap years and 365 otherwise."""
    return 366 if is_leap_year(year) else 365


def _days_in_month(year: int, month: int) -> int:
    if month == 2 and is_leap_year(year):
        return 29
    return _DAYS_IN_MONTH[month - 1]


def astronomical_year(number: int, era: Era) -> int:
    """Convert a historical year such as 500 BCE to an astronomical year (-499).

    Raises ValueError for ``number < 1``: there is no year 0 in the BCE/CE system.
    """
    if number < 1:
        raise ValueError(f"{era} years start at 1, got {number}")
    return number if era == "CE" else 1 - number


def from_calendar(
    year: int,
    month: int = 1,
    day: int = 1,
    hour: int = 0,
    minute: int = 0,
    second: float = 0.0,
) -> DecimalYear:
    """Convert a calendar date (astronomical year) to a decimal year.

    Raises ValueError if any field is out of range for that date, or if the year is
    beyond ``MAX_CALENDAR_YEAR``.
    """
    if abs(year) > MAX_CALENDAR_YEAR:
        raise ValueError(f"year must be within {MAX_CALENDAR_YEAR} of year 0, got {year}")
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1 to 12, got {month}")
    if not 1 <= day <= _days_in_month(year, month):
        raise ValueError(f"day {day} is out of range for month {month} of year {year}")
    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be 0 to 23, got {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"minute must be 0 to 59, got {minute}")
    if not 0 <= second < 60:
        raise ValueError(f"second must be at least 0 and below 60, got {second}")

    day_of_year = sum(_days_in_month(year, m) for m in range(1, month)) + day
    seconds_in = (day_of_year - 1) * SECONDS_PER_DAY + hour * 3600 + minute * 60 + second
    return year + seconds_in / (days_in_year(year) * SECONDS_PER_DAY)


def to_calendar(moment: DecimalYear) -> CalendarDate:
    """Convert a decimal year to a calendar date, rounded to the nearest second.

    Raises ValueError if the moment is not finite or its year is beyond
    ``MAX_CALENDAR_YEAR``.
    """
    if not math.isfinite(moment):
        raise ValueError(f"cannot express {moment} as a calendar date")
    year = math.floor(moment)
    if abs(year) > MAX_CALENDAR_YEAR:
        raise ValueError(f"cannot express {moment} as a calendar date")

    total_seconds = round((moment - year) * days_in_year(year) * SECONDS_PER_DAY)
    if total_seconds >= days_in_year(year) * SECONDS_PER_DAY:
        year += 1
        total_seconds = 0

    day_index, seconds_of_day = divmod(total_seconds, SECONDS_PER_DAY)
    month = 1
    while day_index >= _days_in_month(year, month):
        day_index -= _days_in_month(year, month)
        month += 1
    hour, remainder = divmod(seconds_of_day, 3600)
    minute, second = divmod(remainder, 60)
    return CalendarDate(year, month, day_index + 1, hour, minute, second)


def from_datetime(value: datetime) -> DecimalYear:
    """Convert a datetime to a decimal year. Naive datetimes are treated as UTC."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return from_calendar(
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second + value.microsecond / 1_000_000,
    )


def now() -> DecimalYear:
    """Return the current UTC time as a decimal year."""
    return from_datetime(datetime.now(UTC))


def _plural(count: int, unit: str) -> str:
    return f"{count} {unit}{'' if count == 1 else 's'}"


def _format_recent(seconds: float) -> str | None:
    """Describe a span as minutes, hours, or days ago, or None if it is not recent."""
    minutes = round(seconds / 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{_plural(minutes, 'minute')} ago"
    hours = round(seconds / 3600)
    if hours < 24:
        return f"{_plural(hours, 'hour')} ago"
    days = round(seconds / SECONDS_PER_DAY)
    if days < _RECENT_LIMIT_DAYS:
        return f"{_plural(days, 'day')} ago"
    return None


def _format_calendar_year(year: int) -> str:
    if year >= 1:
        return f"{year} CE"
    return f"{1 - year} BCE"


def _format_deep_time(lookback: float) -> str:
    """Describe a very large lookback in years, to three significant figures."""
    rounded = float(f"{lookback:.3g}")
    if rounded >= 1e9:
        return f"{rounded / 1e9:g} billion years ago"
    if rounded >= 1e6:
        return f"{rounded / 1e6:g} million years ago"
    return f"{round(rounded):,} years ago"


def format_year(moment: DecimalYear, *, now_year: DecimalYear | None = None) -> str:
    """Format a moment for people.

    Recent moments are relative ("3 hours ago", "12 days ago"). Moments from
    10000 BCE onward are calendar years ("1492 CE", "500 BCE"). Older moments are
    "N years ago" rounded to three significant figures ("66 million years ago").

    ``now_year`` overrides the current time, which makes the output deterministic
    for tests.
    """
    reference = now() if now_year is None else now_year
    lookback = reference - moment

    if lookback >= 0:
        recent = _format_recent(lookback * SECONDS_PER_JULIAN_YEAR)
        if recent is not None:
            return recent

    year = math.floor(moment)
    if year >= _OLDEST_CALENDAR_YEAR:
        return _format_calendar_year(year)
    return _format_deep_time(lookback)
