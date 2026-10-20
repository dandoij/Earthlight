"""Turn user text into a moment or an event-name query.

Input is matched, case-insensitively and ignoring extra whitespace, against these
moment formats in order:

==========================  ======================================  ==============
Format                      Examples                                Meaning
==========================  ======================================  ==============
Calendar year (bare)        ``1492``  ``1492.5``                    Calendar year CE
Year with era               ``500 BCE``  ``500 BC``  ``1492 AD``    Calendar year
ISO date                    ``2004-06-15``  ``-0043-03-15``         Proleptic Gregorian
Relative time               ``3 days ago``  ``12,000 years ago``    Before ``now``
Scaled relative time        ``66 million years ago``  ``66 mya``    Before ``now``
==========================  ======================================  ==============

A bare number is always a calendar year, never a count of years ago. The first
instant of a calendar year is used as its moment. ISO dates follow ISO 8601, where
a sign means an astronomical year (so ``-0043`` is 44 BCE).

Anything else is treated as an event-name query (``fall of rome``). Text that has
the *shape* of a moment but an impossible value (``2023-02-30``, ``0 BCE``) is an
error, not an event query, so typos in dates are not silently searched as names.

Parsing is hand-written on purpose: no date library understands BCE or deep time.
"""

import math
import re
from dataclasses import dataclass

from earthlight.time import (
    SECONDS_PER_DAY,
    SECONDS_PER_JULIAN_YEAR,
    DecimalYear,
    Era,
    astronomical_year,
    from_calendar,
    now,
)

MAX_BARE_YEAR = 9999
"""Largest bare calendar year. Larger numbers are probably a mistake for "N years ago"."""


class ParseError(ValueError):
    """Base class for every error raised by ``parse``."""


class EmptyInputError(ParseError):
    """The input was empty or only whitespace."""


class InvalidMomentError(ParseError):
    """The input looked like a moment but its value is impossible or unsupported."""


@dataclass(frozen=True)
class MomentQuery:
    """The input named a moment in time."""

    moment: DecimalYear


@dataclass(frozen=True)
class EventQuery:
    """The input is free text to look up as an event, period, or place name."""

    text: str


ParseResult = MomentQuery | EventQuery

_COUNT = r"\d+(?:,\d{3})*(?:\.\d+)?"

_BARE_YEAR = re.compile(r"\d+(?:\.\d+)?")
_NEGATIVE_BARE_YEAR = re.compile(r"-\d+(?:\.\d+)?")
_ERA_YEAR = re.compile(r"(\d+(?:,\d{3})*)\s*(bce|bc|ce|ad)")
_ISO_DATE = re.compile(r"([+-]?\d{1,6})-(\d{1,2})-(\d{1,2})")
_RELATIVE = re.compile(
    rf"({_COUNT})\s*"
    r"((?:thousand|million|billion)\s+years?|seconds?|minutes?|hours?|days?|weeks?|months?|years?)"
    r"\s+ago"
)
_ABBREVIATED = re.compile(rf"({_COUNT})\s*(kya|mya|gya)")

_YEARS_PER_UNIT: dict[str, float] = {
    "second": 1 / SECONDS_PER_JULIAN_YEAR,
    "minute": 60 / SECONDS_PER_JULIAN_YEAR,
    "hour": 3600 / SECONDS_PER_JULIAN_YEAR,
    "day": SECONDS_PER_DAY / SECONDS_PER_JULIAN_YEAR,
    "week": 7 * SECONDS_PER_DAY / SECONDS_PER_JULIAN_YEAR,
    "month": 1 / 12,
    "year": 1.0,
    "thousand year": 1e3,
    "million year": 1e6,
    "billion year": 1e9,
    "kya": 1e3,
    "mya": 1e6,
    "gya": 1e9,
}


def parse(text: str, *, now_year: DecimalYear | None = None) -> ParseResult:
    """Parse ``text`` into a ``MomentQuery`` or an ``EventQuery``.

    ``now_year`` overrides the current time for relative inputs, which makes the
    result deterministic in tests.

    Raises ``EmptyInputError`` for blank input and ``InvalidMomentError`` when the
    text has the shape of a moment but cannot be one.
    """
    cleaned = " ".join(text.split())
    if not cleaned:
        raise EmptyInputError("Enter a year, a date, a time ago, or an event name.")
    lowered = cleaned.lower()

    if _NEGATIVE_BARE_YEAR.fullmatch(lowered):
        raise InvalidMomentError(
            f'"{cleaned}" is not a calendar year. Write "N BCE" for years before 1 CE.'
        )
    if _BARE_YEAR.fullmatch(lowered):
        return _parse_bare_year(cleaned)
    if match := _ERA_YEAR.fullmatch(lowered):
        return _parse_era_year(cleaned, match.group(1), match.group(2))
    if match := _ISO_DATE.fullmatch(lowered):
        return _parse_iso_date(cleaned, match.group(1), match.group(2), match.group(3))
    if match := _RELATIVE.fullmatch(lowered):
        unit = match.group(2).rstrip("s")  # "million years" -> "million year"
        return _parse_relative(cleaned, match.group(1), unit, now_year)
    if match := _ABBREVIATED.fullmatch(lowered):
        return _parse_relative(cleaned, match.group(1), match.group(2), now_year)
    return EventQuery(cleaned)


def _parse_bare_year(text: str) -> MomentQuery:
    value = float(text)
    if value < 1:
        raise InvalidMomentError(
            f'"{text}" is not a calendar year: there is no year 0. '
            'Write "1 BCE" for the year before 1 CE.'
        )
    if value >= MAX_BARE_YEAR + 1:
        raise InvalidMomentError(
            f'"{text}" is too large for a calendar year (the limit is {MAX_BARE_YEAR}). '
            f'For a long time ago, write for example "{text} years ago".'
        )
    return MomentQuery(value)


def _parse_era_year(text: str, number: str, era: str) -> MomentQuery:
    era_name: Era = "BCE" if era in ("bce", "bc") else "CE"
    try:
        year = int(number.replace(",", ""))
        return MomentQuery(from_calendar(astronomical_year(year, era_name)))
    except ValueError as error:
        raise InvalidMomentError(f'"{text}" is not a valid year: {error}') from error


def _parse_iso_date(text: str, year: str, month: str, day: str) -> MomentQuery:
    try:
        return MomentQuery(from_calendar(int(year), int(month), int(day)))
    except ValueError as error:
        raise InvalidMomentError(f'"{text}" is not a valid date: {error}') from error


def _parse_relative(text: str, count: str, unit: str, now_year: DecimalYear | None) -> MomentQuery:
    reference = now() if now_year is None else now_year
    years_ago = float(count.replace(",", "")) * _YEARS_PER_UNIT[unit]
    moment = reference - years_ago
    if not math.isfinite(moment):
        raise InvalidMomentError(f'"{text}" is too large to be a moment in time.')
    return MomentQuery(moment)
