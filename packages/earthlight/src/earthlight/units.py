"""Words for distances and spans of time that people can picture.

Light-travel times run from a second to billions of years, so one number format cannot serve them
all. These helpers pick the unit (seconds, minutes, hours, days, or years) and the number of
decimals so that the count stays short: the Moon is "1.3 light-seconds" away, the Sun "8.2
light-minutes", Saturn "1.3 light-hours", and Andromeda "2.56 million light-years".

Both the engine's notes and the command line use these, so they always agree.
"""

from typing import Literal

from earthlight.lookback import LookbackRange
from earthlight.time import SECONDS_PER_DAY, SECONDS_PER_JULIAN_YEAR

Unit = Literal["second", "minute", "hour", "day", "year"]


def big_number(value: float) -> str:
    """A count of years for people: ``4.2``, ``534``, ``12,000``, ``66 million``.

    The value is rounded before its unit is chosen, so 999.6 million reads ``1 billion``.
    """
    if value >= 1e6:
        millions = float(f"{value / 1e6:.3g}")
        if millions >= 1000:
            return f"{millions / 1000:g} billion"
        return f"{millions:g} million"
    if value >= 100:
        rounded = round(value)
        return "1 million" if rounded >= 1_000_000 else f"{rounded:,}"
    tenths = round(value, 1)
    return f"{tenths:.0f}" if tenths >= 100 else f"{tenths:.1f}"


def is_within_a_day(lookback: LookbackRange) -> bool:
    """True when every end of the range is under one light-day away.

    Such a place sees Earth almost exactly as it is now (only the Sun, the Moon, and the planets
    are this close), so the engine says so and the command line words the span as "about N
    minutes ago" instead of two dates.
    """
    return lookback.maximum * SECONDS_PER_JULIAN_YEAR < SECONDS_PER_DAY


def _in_unit(years: float) -> tuple[Unit, float]:
    """The unit that suits a length of time, and the length in it.

    The unit is chosen on the rounded value, so 3,599 seconds is "1.0 hours", not "60 minutes".
    """
    seconds = years * SECONDS_PER_JULIAN_YEAR
    if round(seconds) < 120:
        return "second", seconds
    if round(seconds / 60) < 60:
        return "minute", seconds / 60
    if round(seconds / 3600) < 48:
        return "hour", seconds / 3600
    if years < 1:
        return "day", seconds / SECONDS_PER_DAY
    return "year", years


def _decimals(unit: Unit, value: float) -> int:
    """One decimal for seconds and minutes under ten and for hours, none otherwise."""
    if unit == "hour":
        return 1
    if unit in ("second", "minute") and round(value, 1) < 10:
        return 1
    return 0


def _count(unit: Unit, value: float, decimals: int) -> str:
    return big_number(value) if unit == "year" else f"{value:.{decimals}f}"


def _span(years: float) -> tuple[str, Unit]:
    """A length of time as a count and a unit, such as ``("8.2", "minute")``."""
    unit, value = _in_unit(years)
    return _count(unit, value, _decimals(unit, value)), unit


def light_travel(years: float) -> str:
    """A light-travel time as the distance it covers, such as ``534 light-years``."""
    count, unit = _span(years)
    return f"{count} light-{unit}s"


def time_span(years: float) -> str:
    """A length of time in plain units, such as ``71 minutes`` or ``534 years``."""
    count, unit = _span(years)
    return f"{count} {unit}s"


def light_range(low: float, high: float) -> str | None:
    """A range of light-travel times, such as ``473 to 667 light-years``.

    Both ends use the same unit and the same number of decimals when they can (``4.3 to 12.0
    light-minutes``). Returns ``None`` when both ends read the same, since a range that rounds to
    one value tells the reader nothing.
    """
    (low_unit, low_value), (high_unit, high_value) = _in_unit(low), _in_unit(high)
    if low_unit != high_unit:
        low_text, high_text = light_travel(low), light_travel(high)
        return None if low_text == high_text else f"{low_text} to {high_text}"
    decimals = _decimals(low_unit, low_value)  # the smaller end is the one that needs a decimal
    low_count = _count(low_unit, low_value, decimals)
    high_count = _count(high_unit, high_value, decimals)
    if low_count == high_count:
        return None
    return f"{low_count} to {high_count} light-{low_unit}s"
