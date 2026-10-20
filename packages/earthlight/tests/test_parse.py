"""Tests for the input parser."""

from datetime import datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from earthlight.parse import (
    MAX_BARE_YEAR,
    EmptyInputError,
    EventQuery,
    InvalidMomentError,
    MomentQuery,
    ParseError,
    parse,
)
from earthlight.time import format_year, from_calendar, from_datetime

# A fixed "now" (15 June 2026, noon UTC) so relative inputs are deterministic.
NOW_YEAR = from_datetime(datetime(2026, 6, 15, 12))
DAYS_PER_YEAR = 365.25


def moment_of(text: str) -> float:
    result = parse(text, now_year=NOW_YEAR)
    assert isinstance(result, MomentQuery), f"{text!r} parsed as {result!r}"
    return result.moment


# --- calendar years ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1492", 1492.0),
        ("1", 1.0),
        ("9999", 9999.0),
        ("2026", 2026.0),
        ("1492.5", 1492.5),  # a decimal bare year is a decimal year
        ("  1492  ", 1492.0),
        ("0001492", 1492.0),
    ],
)
def test_bare_numbers_are_calendar_years(text: str, expected: float) -> None:
    assert moment_of(text) == expected


@pytest.mark.parametrize(
    ("text", "expected_astronomical_year"),
    [
        ("1492 CE", 1492),
        ("1492 ce", 1492),
        ("1492 AD", 1492),
        ("1492ad", 1492),
        ("1 CE", 1),
        ("1 BCE", 0),  # there is no year 0, so 1 BCE is astronomical year 0
        ("2 BCE", -1),
        ("500 BCE", -499),
        ("500 BC", -499),
        ("500 bc", -499),
        ("500bce", -499),
        ("  500    BCE ", -499),
        ("10,000 BCE", -9999),
        ("1,492 CE", 1492),
    ],
)
def test_years_with_era(text: str, expected_astronomical_year: int) -> None:
    assert moment_of(text) == float(expected_astronomical_year)


# --- ISO dates --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2004-06-15", from_calendar(2004, 6, 15)),
        ("2004-6-5", from_calendar(2004, 6, 5)),
        ("+2004-06-15", from_calendar(2004, 6, 15)),
        ("2024-02-29", from_calendar(2024, 2, 29)),
        ("0000-01-01", 0.0),
        ("-0043-03-15", from_calendar(-43, 3, 15)),  # ISO 8601: sign means astronomical year
        ("0001-01-01", 1.0),
    ],
)
def test_iso_dates(text: str, expected: float) -> None:
    assert moment_of(text) == expected


# --- relative times ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "years_ago"),
    [
        ("0 days ago", 0.0),
        ("30 seconds ago", 30 / (DAYS_PER_YEAR * 86_400)),
        ("1 minute ago", 1 / (DAYS_PER_YEAR * 1_440)),
        ("3 hours ago", 3 / (DAYS_PER_YEAR * 24)),
        ("1 hour ago", 1 / (DAYS_PER_YEAR * 24)),
        ("3 days ago", 3 / DAYS_PER_YEAR),
        ("3 Days Ago", 3 / DAYS_PER_YEAR),
        ("1 day ago", 1 / DAYS_PER_YEAR),
        ("2 weeks ago", 14 / DAYS_PER_YEAR),
        ("6 months ago", 0.5),
        ("1 year ago", 1.0),
        ("500 years ago", 500.0),
        ("12,000 years ago", 12_000.0),
        ("1.5 years ago", 1.5),
        ("65 thousand years ago", 65_000.0),
        ("65 kya", 65_000.0),
        ("66 million years ago", 66e6),
        ("66 Million Years Ago", 66e6),
        ("1 million year ago", 1e6),
        ("66 mya", 66e6),
        ("66 Mya", 66e6),
        ("66mya", 66e6),
        ("541 mya", 541e6),
        ("4.5 gya", 4.5e9),
        ("4.54 billion years ago", 4.54e9),
        ("13.8 gya", 13.8e9),
        ("  3   days   ago  ", 3 / DAYS_PER_YEAR),
    ],
)
def test_relative_times(text: str, years_ago: float) -> None:
    assert moment_of(text) == pytest.approx(NOW_YEAR - years_ago, abs=1e-6)


# --- event queries ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_text"),
    [
        ("fall of rome", "fall of rome"),
        ("Fall   of  Rome ", "Fall of Rome"),  # whitespace is collapsed, case is kept
        ("Betelgeuse", "Betelgeuse"),
        ("apollo 11", "apollo 11"),
        ("1969 moon landing", "1969 moon landing"),
        ("july 20 1969", "july 20 1969"),  # month names are not supported as dates
        ("3 days", "3 days"),  # "ago" is required
        ("in 3 days", "in 3 days"),
        ("ago 3 days", "ago 3 days"),
        ("2004/06/15", "2004/06/15"),
        ("mya", "mya"),
        ("bce", "bce"),
        ("12:30", "12:30"),
    ],
)
def test_other_text_is_an_event_query(text: str, expected_text: str) -> None:
    assert parse(text, now_year=NOW_YEAR) == EventQuery(expected_text)


# --- errors -----------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "\t\n"])
def test_empty_input(text: str) -> None:
    with pytest.raises(EmptyInputError):
        parse(text)


@pytest.mark.parametrize(
    ("text", "message_part"),
    [
        ("0", "no year 0"),
        ("0.5", "no year 0"),
        ("-500", "BCE"),
        ("-1.5", "BCE"),
        (str(MAX_BARE_YEAR + 1), "years ago"),
        ("66000000", "66000000 years ago"),
        ("0 BCE", "start at 1"),
        ("0 CE", "start at 1"),
        ("0 bc", "start at 1"),
        ("2023-02-29", "not a valid date"),
        ("2023-02-30", "not a valid date"),
        ("2004-13-01", "not a valid date"),
        ("2004-00-10", "not a valid date"),
        ("2004-04-31", "not a valid date"),
        ("2004-06-00", "not a valid date"),
        ("9" * 5000 + " CE", "not a valid year"),
        ("9" * 400 + " years ago", "too large"),
        ("9" * 400 + " gya", "too large"),
    ],
)
def test_impossible_moments_raise_with_a_helpful_message(text: str, message_part: str) -> None:
    with pytest.raises(InvalidMomentError, match=message_part):
        parse(text, now_year=NOW_YEAR)


def test_all_errors_share_one_base_class() -> None:
    assert issubclass(EmptyInputError, ParseError)
    assert issubclass(InvalidMomentError, ParseError)
    assert issubclass(ParseError, ValueError)


def test_current_time_is_used_when_now_year_is_not_given() -> None:
    result = parse("0 days ago")
    assert isinstance(result, MomentQuery)
    assert result.moment == pytest.approx(NOW_YEAR, abs=100)  # sanity only: real clock


# --- properties -------------------------------------------------------------


@given(st.text())
def test_parse_only_ever_raises_parse_errors(text: str) -> None:
    try:
        result = parse(text, now_year=NOW_YEAR)
    except ParseError:
        return
    assert isinstance(result, MomentQuery | EventQuery)


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=1).filter(lambda t: t.strip()))
def test_text_without_digits_is_always_an_event_query(text: str) -> None:
    assert parse(text, now_year=NOW_YEAR) == EventQuery(" ".join(text.split()))


@given(st.integers(1, 10_000))
def test_bce_years_round_trip_through_the_formatter(year: int) -> None:
    text = f"{year} BCE"
    assert format_year(moment_of(text), now_year=NOW_YEAR) == text


@given(st.integers(1, MAX_BARE_YEAR))
def test_ce_years_round_trip_through_the_formatter(year: int) -> None:
    assert format_year(moment_of(f"{year} CE"), now_year=NOW_YEAR) == f"{year} CE"
    assert moment_of(str(year)) == moment_of(f"{year} CE")


@pytest.mark.parametrize(
    "text",
    [
        "1 minute ago",
        "45 minutes ago",
        "1 hour ago",
        "23 hours ago",
        "1 day ago",
        "59 days ago",
        "66 million years ago",
        "541 million years ago",
        "4.54 billion years ago",
        "13.8 billion years ago",
    ],
)
def test_parser_accepts_what_the_formatter_prints(text: str) -> None:
    assert format_year(moment_of(text), now_year=NOW_YEAR) == text
