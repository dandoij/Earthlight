"""Turn user text into a moment or an event-name query.

Input is matched, case-insensitively and ignoring extra whitespace, against these
moment formats in order (digits are ASCII only):

==========================  ======================================  ==============
Format                      Examples                                Meaning
==========================  ======================================  ==============
Calendar year (bare)        ``1492``  ``1492.5``                    Calendar year CE
Year with era               ``500 BCE``  ``500 B.C.``  ``1492 AD``  Calendar year
ISO date                    ``2004-06-15``  ``-0043-03-15``         Proleptic Gregorian
Relative time               ``3 days ago``  ``12,000 years ago``    Before ``now``
Scaled relative time        ``66 million years ago``  ``66 mya``    Before ``now``
==========================  ======================================  ==============

A bare number is always a calendar year, never a count of years ago. The first
instant of a calendar year is used as its moment. ISO dates follow ISO 8601, where
a sign means an astronomical year (so ``-0043`` is 44 BCE). Eras are ``BCE``, ``BC``,
``CE``, and ``AD``, with or without dots.

Text that matches one of these formats but has an impossible value (``2023-02-30``,
``0 BCE``) is an error, so a mistyped date is not silently searched as a name. Anything
that matches no format, including text that merely looks like a moment (``1.5 bce``,
``+1992``), is an event-name query (``fall of rome``).

Relative times up to a month are counted in real calendar seconds, so "1 day ago" on
1 March 2024 is exactly midnight on 29 February. A month is 1/12 of a Julian year
(about 30.44 days), and years and longer use the Julian year of 365.25 days.

Parsing is hand-written on purpose: no date library understands BCE or deep time.
"""

import math
import re
from dataclasses import dataclass

from earthlight.errors import EarthlightError
from earthlight.time import (
    MAX_CALENDAR_YEAR,
    SECONDS_PER_DAY,
    SECONDS_PER_JULIAN_YEAR,
    DecimalYear,
    Era,
    astronomical_year,
    from_calendar,
    now,
    subtract_seconds,
)

MAX_BARE_YEAR = 9999
"""Largest bare calendar year. Larger numbers are probably a mistake for "N years ago"."""

_MAX_ECHOED_CHARS = 40


class ParseError(EarthlightError, ValueError):
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

# re.ASCII keeps \d to 0-9, so Arabic-Indic or fullwidth digits are not moments.
_BARE_YEAR = re.compile(r"\d+(?:\.\d+)?", re.ASCII)
_NEGATIVE_BARE_YEAR = re.compile(r"-\d+(?:\.\d+)?", re.ASCII)
_ERA_YEAR = re.compile(
    r"(\d+(?:,\d{3})*)\s*(b\.c\.e\.|b\.c\.|c\.e\.|a\.d\.|bce|bc|ce|ad)", re.ASCII
)
_ISO_DATE = re.compile(r"([+-]?\d{1,6})-(\d{1,2})-(\d{1,2})", re.ASCII)
_RELATIVE = re.compile(
    rf"({_COUNT})\s*"
    r"((?:thousand|million|billion)\s+years?|seconds?|minutes?|hours?|days?|weeks?|months?|years?)"
    r"\s+ago",
    re.ASCII,
)
_ABBREVIATED = re.compile(rf"({_COUNT})\s*(kya|mya|gya)", re.ASCII)

_SECONDS_PER_UNIT: dict[str, float] = {
    "second": 1.0,
    "minute": 60.0,
    "hour": 3600.0,
    "day": float(SECONDS_PER_DAY),
    "week": 7.0 * SECONDS_PER_DAY,
    "month": SECONDS_PER_JULIAN_YEAR / 12,
}
_YEARS_PER_UNIT: dict[str, float] = {
    "year": 1.0,
    "thousand year": 1e3,
    "million year": 1e6,
    "billion year": 1e9,
    "kya": 1e3,
    "mya": 1e6,
    "gya": 1e9,
}


def _shown(text: str) -> str:
    """Shorten user text before it goes into an error message."""
    if len(text) <= _MAX_ECHOED_CHARS:
        return text
    return text[: _MAX_ECHOED_CHARS - 3] + "..."


def _clean(text: str) -> tuple[str, str]:
    """The text with spaces tidied, and the same in lower case. Blank input is an error."""
    cleaned = " ".join(text.split())
    if not cleaned:
        raise EmptyInputError("Enter a year, a date, a time ago, or an event name.")
    return cleaned, cleaned.lower()


def _negative_year_error(text: str) -> InvalidMomentError:
    return InvalidMomentError(
        f'"{_shown(text)}" is not a calendar year. Write "N BCE" for years before 1 CE.'
    )


def parse(text: str, *, now_year: DecimalYear | None = None) -> ParseResult:
    """Parse ``text`` into a ``MomentQuery`` or an ``EventQuery``.

    ``now_year`` overrides the current time for relative inputs, which makes the
    result deterministic in tests.

    Raises ``EmptyInputError`` for blank input and ``InvalidMomentError`` when the
    text matches a moment format but cannot be a moment.
    """
    cleaned, lowered = _clean(text)

    if _NEGATIVE_BARE_YEAR.fullmatch(lowered):
        raise _negative_year_error(cleaned)
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


def parse_year(text: str) -> DecimalYear:
    """Parse text that is known to be a calendar year: ``1492``, ``500 BCE``, ``44 B.C.``.

    This is the entry point for a command line flag that says "this is a year", so no guessing
    is needed and the guard that stops ``parse`` from reading ``12000`` as a year does not
    apply: any year up to ``MAX_CALENDAR_YEAR`` is accepted, the same range as ISO dates.
    Raises ``InvalidMomentError`` for anything that is not a year.
    """
    cleaned, lowered = _clean(text)
    if _NEGATIVE_BARE_YEAR.fullmatch(lowered):
        raise _negative_year_error(cleaned)
    if _BARE_YEAR.fullmatch(lowered):
        return _parse_bare_year(cleaned, limit=MAX_CALENDAR_YEAR).moment
    if match := _ERA_YEAR.fullmatch(lowered):
        return _parse_era_year(cleaned, match.group(1), match.group(2)).moment
    raise InvalidMomentError(
        f'"{_shown(cleaned)}" is not a year. Write for example "1492" or "500 BCE".'
    )


def parse_date(text: str) -> DecimalYear:
    """Parse an ISO 8601 date, ``YYYY-MM-DD`` (a sign means an astronomical year).

    Raises ``InvalidMomentError`` if the text is not a real date in that form.
    """
    cleaned, lowered = _clean(text)
    if match := _ISO_DATE.fullmatch(lowered):
        return _parse_iso_date(cleaned, match.group(1), match.group(2), match.group(3)).moment
    raise InvalidMomentError(f'"{_shown(cleaned)}" is not a date. Write it as YYYY-MM-DD.')


def parse_ago(text: str, *, now_year: DecimalYear | None = None) -> DecimalYear:
    """Parse an amount of time before ``now_year``: ``3 days``, ``66 million years``, ``66 mya``.

    The word "ago" is optional, so ``3 days`` and ``3 days ago`` mean the same.
    Raises ``InvalidMomentError`` if the text is not an amount of time.
    """
    cleaned, lowered = _clean(text)
    if match := _ABBREVIATED.fullmatch(lowered):
        return _parse_relative(cleaned, match.group(1), match.group(2), now_year).moment
    with_ago = lowered if lowered.endswith(" ago") else f"{lowered} ago"
    if match := _RELATIVE.fullmatch(with_ago):
        unit = match.group(2).rstrip("s")
        return _parse_relative(cleaned, match.group(1), unit, now_year).moment
    raise InvalidMomentError(
        f'"{_shown(cleaned)}" is not an amount of time. Try "3 days", "12000 years", or "66 mya".'
    )


def _parse_bare_year(text: str, *, limit: int = MAX_BARE_YEAR) -> MomentQuery:
    value = float(text)
    if value < 1:
        raise InvalidMomentError(
            f'"{_shown(text)}" is not a calendar year: there is no year 0. '
            'Write "1 BCE" for the year before 1 CE.'
        )
    if value >= limit + 1:
        raise InvalidMomentError(
            f'"{_shown(text)}" is too large for a calendar year (the limit is {limit}). '
            f'For a long time ago, write for example "{_shown(text)} years ago".'
        )
    return MomentQuery(value)


def _parse_era_year(text: str, number: str, era: str) -> MomentQuery:
    era_name: Era = "BCE" if era.replace(".", "") in ("bce", "bc") else "CE"
    try:
        year = int(number.replace(",", ""))
        return MomentQuery(from_calendar(astronomical_year(year, era_name)))
    except ValueError as error:
        raise InvalidMomentError(f'"{_shown(text)}" is not a valid year: {error}') from error


def _parse_iso_date(text: str, year: str, month: str, day: str) -> MomentQuery:
    try:
        return MomentQuery(from_calendar(int(year), int(month), int(day)))
    except ValueError as error:
        raise InvalidMomentError(f'"{_shown(text)}" is not a valid date: {error}') from error


def _parse_relative(text: str, count: str, unit: str, now_year: DecimalYear | None) -> MomentQuery:
    reference = now() if now_year is None else now_year
    amount = float(count.replace(",", ""))
    if unit in _SECONDS_PER_UNIT:
        seconds = amount * _SECONDS_PER_UNIT[unit]
        if not math.isfinite(seconds):
            raise InvalidMomentError(f'"{_shown(text)}" is too large to be a moment in time.')
        moment = subtract_seconds(reference, seconds)
    else:
        years = amount * _YEARS_PER_UNIT[unit]
        if not math.isfinite(years):
            raise InvalidMomentError(f'"{_shown(text)}" is too large to be a moment in time.')
        moment = reference - years
    if not math.isfinite(moment):
        raise InvalidMomentError(f'"{_shown(text)}" is too large to be a moment in time.')
    return MomentQuery(moment)
