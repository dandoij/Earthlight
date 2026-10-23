"""Tests for the per-format parse functions that the command line flags use."""

from datetime import datetime

import pytest

from earthlight.parse import (
    MAX_BARE_YEAR,
    EmptyInputError,
    InvalidMomentError,
    MomentQuery,
    parse,
    parse_ago,
    parse_date,
    parse_year,
)
from earthlight.time import MAX_CALENDAR_YEAR, from_calendar, from_datetime, now

NOW_YEAR = from_datetime(datetime(2026, 6, 15, 12))


def parsed_moment(text: str) -> float:
    result = parse(text, now_year=NOW_YEAR)
    assert isinstance(result, MomentQuery)
    return result.moment


@pytest.mark.parametrize("text", ["1492", "1492.5", "500 BCE", "44 B.C.", "1492 AD", "9999"])
def test_parse_year_agrees_with_parse(text: str) -> None:
    assert parse_year(text) == parsed_moment(text)


@pytest.mark.parametrize("text", ["2004-06-15", "-0043-03-15", "0000-01-01"])
def test_parse_date_agrees_with_parse(text: str) -> None:
    assert parse_date(text) == parsed_moment(text)


@pytest.mark.parametrize(
    ("text", "equivalent"),
    [
        ("3 days", "3 days ago"),
        ("3 days ago", "3 days ago"),
        ("66 million years", "66 million years ago"),
        ("12,000 years", "12,000 years ago"),
        ("66 mya", "66 mya"),
        ("1.5 hours", "1.5 hours ago"),
    ],
)
def test_parse_ago_agrees_with_parse_and_makes_ago_optional(text: str, equivalent: str) -> None:
    assert parse_ago(text, now_year=NOW_YEAR) == parsed_moment(equivalent)


def test_an_explicit_year_may_exceed_the_limit_that_guards_a_guess() -> None:
    # parse() reads a bare 12000 as probably meant "years ago"; a flag that says "year" is explicit.
    assert MAX_BARE_YEAR < 12_000
    with pytest.raises(InvalidMomentError, match="too large"):
        parse("12000")
    assert parse_year("12000") == 12_000.0


def test_an_explicit_year_has_the_same_limit_as_iso_dates() -> None:
    assert parse_year(str(MAX_CALENDAR_YEAR)) == float(MAX_CALENDAR_YEAR)
    assert parse_date("999999-01-01") == from_calendar(999_999)
    with pytest.raises(InvalidMomentError, match="too large"):
        parse_year(str(MAX_CALENDAR_YEAR + 1))


@pytest.mark.parametrize(
    "text", ["fall of rome", "2004-06-15", "3 days ago", "1.5 bce", "-43", "0", "0 BCE", "BCE"]
)
def test_parse_year_rejects_everything_that_is_not_a_year(text: str) -> None:
    with pytest.raises(InvalidMomentError):
        parse_year(text)


@pytest.mark.parametrize(
    "text", ["1492", "500 BCE", "2004-6", "2023-02-30", "2004-13-01", "June 15 2004", "apollo 11"]
)
def test_parse_date_rejects_everything_that_is_not_a_real_iso_date(text: str) -> None:
    with pytest.raises(InvalidMomentError):
        parse_date(text)


@pytest.mark.parametrize(
    "text", ["3", "days", "1492", "3 days from now", "3 days ago ago", "66 mya ago", "apollo 11"]
)
def test_parse_ago_rejects_everything_that_is_not_an_amount_of_time(text: str) -> None:
    with pytest.raises(InvalidMomentError):
        parse_ago(text, now_year=NOW_YEAR)


@pytest.mark.parametrize("function", [parse_year, parse_date, parse_ago])
def test_blank_input_is_an_empty_input_error(function: object) -> None:
    assert callable(function)
    with pytest.raises(EmptyInputError):
        function("   ")


def test_parse_ago_uses_the_current_time_when_not_told_otherwise() -> None:
    before = now()
    moment = parse_ago("1 year")
    after = now()
    assert before - 1.0 <= moment <= after - 1.0
