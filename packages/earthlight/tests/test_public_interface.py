"""Tests for the top-level functions people call: when, from_vantage, info, search."""

import doctest
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

import earthlight
from earthlight import (
    EarthlightError,
    EmptyInputError,
    FutureMomentError,
    InvalidMomentError,
    MomentError,
    ParseError,
    UnknownVantageError,
    UnresolvedNameError,
    from_vantage,
    info,
    search,
    when,
)
from earthlight import engine as engine_module
from earthlight.models import VantageKind
from earthlight.repository import Repository, default_repository
from earthlight.schema import create_empty_database, rebuild_search_index
from earthlight.time import from_calendar

NOW = from_calendar(2026, 6, 15, 12)


def test_the_examples_in_the_docstrings_are_true() -> None:
    results = doctest.testmod(earthlight, optionflags=doctest.ELLIPSIS)
    assert results.attempted >= 15
    assert results.failed == 0


# --- when ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("1492", "1492 CE"),
        ("500 BCE", "500 BCE"),
        ("500 bc", "500 BCE"),
        ("66 mya", "66 million years ago"),
        ("66 million years ago", "66 million years ago"),
        ("2004-06-15", "2004 CE"),
        ("3 days ago", "3 days ago"),
    ],
)
def test_when_understands_the_text_formats(text: str, label: str) -> None:
    assert when(text, now_year=NOW).moment_label == label


def test_when_text_and_the_same_moment_as_a_number_agree() -> None:
    assert when("1492", now_year=NOW) == when(1492.0, now_year=NOW)
    assert when(1492, now_year=NOW) == when(1492.0, now_year=NOW)


def test_when_accepts_a_datetime_and_treats_a_naive_one_as_utc() -> None:
    aware = datetime(1492, 10, 12, 12, tzinfo=UTC)
    naive = datetime(1492, 10, 12, 12)
    assert when(aware, now_year=NOW) == when(naive, now_year=NOW)
    shifted = datetime(1492, 10, 12, 14, tzinfo=timezone(timedelta(hours=2)))
    assert when(shifted, now_year=NOW) == when(aware, now_year=NOW)


def test_a_datetime_becomes_the_matching_decimal_year() -> None:
    result = when(datetime(1492, 10, 12, 12, tzinfo=UTC), now_year=NOW)
    assert result.moment == pytest.approx(1492.78, abs=0.01)


def test_when_rejects_a_bool_rather_than_calling_it_the_year_one() -> None:
    with pytest.raises(TypeError, match="not a bool"):
        when(True, now_year=NOW)


def test_the_future_is_rejected_whatever_the_input_form() -> None:
    for moment in (NOW + 1, "2100", datetime(2100, 1, 1, tzinfo=UTC)):
        with pytest.raises(FutureMomentError, match="has not happened yet"):
            when(moment, now_year=NOW)


def test_relative_text_and_the_engine_share_one_clock_read(monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[float] = []

    def counting_now() -> float:
        reads.append(NOW)
        return NOW

    monkeypatch.setattr(earthlight, "now", counting_now)
    monkeypatch.setattr(engine_module, "now", counting_now)
    result = when("3 days ago")
    assert reads == [NOW] and result.zone is not None


def test_bad_text_raises_the_parse_errors() -> None:
    with pytest.raises(EmptyInputError):
        when("   ", now_year=NOW)
    with pytest.raises(InvalidMomentError):
        when("-5", now_year=NOW)


# --- when, with names --------------------------------------------------------------------------


def test_an_event_name_uses_that_events_date_and_says_so() -> None:
    result = when("Columbus", now_year=NOW)
    assert result.moment == pytest.approx(1492.78, abs=0.01)
    assert result.notes[0] == "Using Columbus reaches the Americas (1492 CE) for 'Columbus'."
    assert result.moment_label == "1492 CE"


def test_a_period_name_uses_its_start_and_a_landmark_the_year_it_was_finished() -> None:
    period = when("world war ii", now_year=NOW)
    assert "the start of the period" in period.notes[0] and "1939" in period.notes[0]
    landmark = when("great pyramid", now_year=NOW)
    assert "construction finished" in landmark.notes[0] and landmark.moment == -2574


def test_an_unfinished_event_name_still_finds_the_event() -> None:
    result = when("fall of rom", now_year=NOW)
    assert "The fall of the Western Roman Empire" in result.notes[0]
    assert result.moment_label == "476 CE"


def test_the_note_comes_first_and_the_engine_notes_follow() -> None:
    result = when("Colosseum", now_year=NOW)
    assert result.notes[0].startswith("Using The Colosseum")
    assert len(result.notes) >= 1


def test_the_rest_of_the_answer_is_the_same_as_for_the_date() -> None:
    by_name = when("Columbus", now_year=NOW)
    by_date = when(by_name.moment, now_year=NOW)
    assert by_name.model_copy(update={"notes": ()}) == by_date.model_copy(update={"notes": ()})


def test_names_people_actually_use_find_the_right_entry() -> None:
    expected = {
        "fall of rome": "The fall of the Western Roman Empire",
        "moon landing": "Apollo 11 lands on the Moon",
        "Titanic": "The Titanic sinks",
        "French Revolution": "The storming of the Bastille",
        "WW2": "World War II",
        "pyramids": "Great Pyramid of Giza",
        "Ice Age": "Pleistocene Epoch",
        "dinosaur extinction": "The end of the dinosaurs",
    }
    for text, name in expected.items():
        assert f"Using {name}" in when(text, now_year=NOW).notes[0], text


def test_a_name_with_no_match_raises_with_guesses() -> None:
    with pytest.raises(UnresolvedNameError, match="Did you mean") as caught:
        when("colosseun", now_year=NOW)
    assert "The Colosseum" in [s.name for s in caught.value.suggestions]
    assert caught.value.text == "colosseun"


def test_gibberish_raises_without_guesses() -> None:
    with pytest.raises(UnresolvedNameError, match="No event, period, or landmark") as caught:
        when("zzzzqqqq", now_year=NOW)
    assert caught.value.suggestions == () and caught.value.results == ()


def test_the_name_of_a_place_is_not_a_moment_and_the_message_says_so() -> None:
    with pytest.raises(UnresolvedNameError, match="name of a place, not a moment"):
        when("Betelgeuse", now_year=NOW)


# --- from_vantage and info ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "place", ["hip-27989", "HIP-27989", "Betelgeuse", "betelgeuse", "  BETELGEUSE ", "HIP 27989"]
)
def test_a_place_can_be_given_by_id_name_or_alias(place: str) -> None:
    assert from_vantage(place, now_year=NOW).vantage_point.id == "hip-27989"


def test_an_alias_finds_the_place() -> None:
    assert from_vantage("M31", now_year=NOW).vantage_point.id == "andromeda-galaxy"


def test_an_unknown_place_raises_with_guesses() -> None:
    with pytest.raises(UnresolvedNameError, match="No place called 'Betelguese'") as caught:
        from_vantage("Betelguese", now_year=NOW)
    assert caught.value.suggestions[0].id == "hip-27989"
    assert "Did you mean Betelgeuse?" in str(caught.value)


def test_a_partial_name_lists_what_it_could_mean_but_does_not_guess() -> None:
    with pytest.raises(UnresolvedNameError) as caught:
        from_vantage("androm", now_year=NOW)
    assert caught.value.results[0].id == "andromeda-galaxy"


def test_a_history_name_is_not_a_place() -> None:
    with pytest.raises(UnresolvedNameError, match="No place called 'Stonehenge'"):
        from_vantage("Stonehenge", now_year=NOW)


def test_blank_text_asks_for_a_name() -> None:
    with pytest.raises(UnresolvedNameError, match="Enter the name of a place"):
        from_vantage("  ", now_year=NOW)


def test_info_for_an_exoplanet_has_the_archive_details() -> None:
    result = info("Proxima Cen b")
    assert result.vantage_point.id == "proxima-cen-b"
    assert result.exoplanet is not None
    assert result.exoplanet.discovery_year == 2016
    assert result.exoplanet.host_name == "Proxima Cen"
    assert result.exoplanet.controversial is False
    assert result.planet_ids == ()


def test_info_for_a_star_lists_its_planets() -> None:
    result = info("Proxima Centauri")
    assert result.vantage_point.kind is VantageKind.STAR
    assert result.exoplanet is None
    assert "proxima-cen-b" in result.planet_ids
    assert list(result.planet_ids) == sorted(result.planet_ids)


def test_info_for_a_galaxy_is_just_the_place() -> None:
    result = info("andromeda-galaxy")
    assert result.exoplanet is None and result.planet_ids == ()


def test_info_for_an_unknown_place_raises() -> None:
    with pytest.raises(UnresolvedNameError):
        info("nowhere at all")


def test_every_planet_of_a_star_points_back_at_it() -> None:
    star = info("hip-70890")
    repo = default_repository()
    for planet_id in star.planet_ids:
        planet = repo.vantage_point(planet_id)
        assert planet is not None and planet.host_id == "hip-70890"


# --- search ----------------------------------------------------------------------------------


def test_search_is_the_same_as_the_search_module() -> None:
    assert search("Sirius").results[0].id == "hip-32349"
    assert search("Betelguese").suggestions[0].id == "hip-27989"
    assert len(search("a", limit=2).results) == 2


# --- errors ----------------------------------------------------------------------------------


def test_every_error_shares_one_base_class_and_keeps_its_older_parent() -> None:
    assert issubclass(ParseError, EarthlightError) and issubclass(ParseError, ValueError)
    assert issubclass(MomentError, EarthlightError) and issubclass(MomentError, ValueError)
    assert issubclass(FutureMomentError, MomentError)
    assert issubclass(UnknownVantageError, EarthlightError)
    assert issubclass(UnknownVantageError, LookupError)
    assert issubclass(UnresolvedNameError, EarthlightError)
    assert issubclass(UnresolvedNameError, LookupError)


@pytest.mark.parametrize(
    "call",
    [
        lambda: when("   ", now_year=NOW),
        lambda: when("2100", now_year=NOW),
        lambda: when("zzzzqqqq", now_year=NOW),
        lambda: from_vantage("nowhere", now_year=NOW),
        lambda: info("nowhere"),
    ],
)
def test_one_except_clause_catches_every_failure(call: object) -> None:
    assert callable(call)
    with pytest.raises(EarthlightError) as caught:
        call()
    assert str(caught.value)


def test_the_public_names_are_all_importable() -> None:
    for name in earthlight.__all__:
        assert hasattr(earthlight, name), name


def test_an_extreme_datetime_is_a_moment_error_not_a_bare_value_error() -> None:
    extreme = datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=5)))
    with pytest.raises(MomentError):
        when(extreme, now_year=NOW)


def test_a_hit_that_does_not_name_every_word_is_called_the_closest_match(tmp_path: Path) -> None:
    path = tmp_path / "weak.db"
    create_empty_database(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO events (id, name, category, region, summary, importance, source, year) "
        "VALUES ('zed', 'Founding of Zed', 'x', 'y', 'z', 3, 'https://example.org/x', 100)"
    )
    connection.execute(
        "INSERT INTO search_entries (type, id, name, aliases, description) "
        "VALUES ('event', 'zed', 'Founding of Zed', 'Zed begins', 'Event, 100 CE, the Quux affair')"
    )
    connection.commit()
    rebuild_search_index(connection)
    connection.close()
    with Repository(path) as repo:
        by_name = when("founding zed", now_year=NOW, repository=repo).notes[0]
        by_alias = when("zed begins", now_year=NOW, repository=repo).notes[0]
        by_description = when("quux", now_year=NOW, repository=repo).notes[0]
    assert by_name.startswith("Using ") and by_alias.startswith("Using ")
    assert by_description.startswith("Closest match for 'quux': Founding of Zed")


def test_an_unfinished_word_counts_as_naming_it() -> None:
    assert when("fall of rom", now_year=NOW).notes[0].startswith("Using ")


def test_as_event_searches_a_name_even_when_the_text_looks_like_a_year() -> None:
    forced = when("1492", as_event=True, now_year=2026.0)
    plain = when("1492", now_year=2026.0)
    assert any("'1492'" in note for note in forced.notes)
    assert not any("'1492'" in note for note in plain.notes)


def test_as_event_needs_text_that_is_not_blank() -> None:
    with pytest.raises(EmptyInputError):
        when("   ", as_event=True, now_year=2026.0)
    with pytest.raises(TypeError, match="as_event"):
        when(1492.0, as_event=True, now_year=2026.0)
