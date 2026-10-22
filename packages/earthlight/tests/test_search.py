"""Tests for search and did-you-mean, run against the real bundled database."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from earthlight.models import SearchResponse, SearchType, VantageKind
from earthlight.repository import Repository
from earthlight.schema import create_empty_database, rebuild_search_index
from earthlight.search import (
    MAX_QUERY_CHARS,
    MAX_SUGGESTIONS,
    MIN_SIMILARITY,
    search,
)


def names(response: SearchResponse) -> list[str]:
    return [result.name for result in response.results]


def guesses(response: SearchResponse) -> list[str]:
    return [suggestion.name for suggestion in response.suggestions]


# --- finding things --------------------------------------------------------------------------


def test_an_exact_name_finds_that_place_first() -> None:
    response = search("Betelgeuse")
    assert names(response)[0] == "Betelgeuse"
    first = response.results[0]
    assert (first.type, first.id, first.kind) == (
        SearchType.VANTAGE_POINT,
        "hip-27989",
        VantageKind.STAR,
    )
    assert first.description == "Star in Orion"
    assert response.suggestions == ()


@pytest.mark.parametrize("text", ["betelgeuse", "BETELGEUSE", "  Betelgeuse  ", "Betelgeuse!"])
def test_case_spaces_and_punctuation_do_not_matter(text: str) -> None:
    assert search(text).results[0].id == "hip-27989"


@pytest.mark.parametrize(
    ("text", "expected_id"),
    [("M31", "andromeda-galaxy"), ("NGC 224", "andromeda-galaxy"), ("HIP 27989", "hip-27989")],
)
def test_catalogue_names_find_the_place(text: str, expected_id: str) -> None:
    assert search(text).results[0].id == expected_id


def test_an_unfinished_word_finds_things_as_you_type() -> None:
    assert search("androm").results[0].id == "andromeda-galaxy"
    assert search("betel").results[0].id == "hip-27989"


def test_every_word_must_match() -> None:
    assert search("andromeda galaxy").results[0].id == "andromeda-galaxy"
    assert search("andromeda zebra").results == ()


def test_history_entries_are_found_with_their_type() -> None:
    stonehenge = search("stonehenge").results[0]
    assert (stonehenge.type, stonehenge.id, stonehenge.kind) == (
        SearchType.LANDMARK,
        "stonehenge",
        None,
    )
    event = search("fall of the western roman empire").results[0]
    assert (event.type, event.id) == (SearchType.EVENT, "fall-of-the-western-roman-empire")
    period = next(r for r in search("holocene").results if r.type is SearchType.PERIOD)
    assert period.id == "holocene-epoch"


def test_the_exact_name_beats_other_words_that_mention_it() -> None:
    response = search("Sirius")
    assert response.results[0].id == "hip-32349"


def test_results_are_limited_and_the_limit_is_respected() -> None:
    assert len(search("a", limit=3).results) == 3
    assert len(search("a").results) == 10
    assert search("Betelgeuse", limit=0).results == ()


def test_the_response_remembers_the_tidied_query() -> None:
    assert search("  fall   of  rome ").query == "fall of rome"


# --- text that should not hurt ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "!!!",
        "***",
        '"',
        '""',
        "AND",
        "OR",
        "NOT",
        "NEAR(",
        '"AND" OR * NEAR(',
        "a AND (b",
        "name:Sirius",
        "-Sirius",
        "Sirius*",
        "'; DROP TABLE events; --",
        "\x00",
        "‮",
        "x" * 5000,
    ],
)
def test_odd_text_never_raises_and_never_changes_the_database(text: str) -> None:
    response = search(text)
    assert isinstance(response, SearchResponse)
    assert len(response.query) <= MAX_QUERY_CHARS


def test_empty_and_symbol_only_text_find_nothing() -> None:
    for text in ("", "   ", "!!!", '"'):
        response = search(text)
        assert response.results == () and response.suggestions == ()


def test_query_operators_are_treated_as_plain_words() -> None:
    assert search("Sirius OR Betelgeuse").results == ()  # all of these words must be present
    assert search("Sirius*").results[0].id == "hip-32349"


def test_a_very_long_query_is_cut_not_rejected() -> None:
    assert len(search("Betelgeuse " + "x" * 500).query) == MAX_QUERY_CHARS


# --- did you mean -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typo", "expected"),
    [
        ("Betelguese", "Betelgeuse"),
        ("betelgeuze", "Betelgeuse"),
        ("andromedia", "Andromeda Galaxy (Messier 31)"),
        ("Sirus", "Sirius"),
        ("trapist", "TRAPPIST-1 e"),
        ("Stonehenje", "Stonehenge"),
        ("Colossus of Rodes", "Colossus of Rhodes"),
    ],
)
def test_a_typo_gets_a_did_you_mean_for_the_right_thing(typo: str, expected: str) -> None:
    response = search(typo)
    assert response.results == ()
    assert expected in guesses(response)


def test_an_unfinished_phrase_finds_the_event_directly() -> None:
    response = search("fall of rom")
    assert names(response)[0] == "The fall of the Western Roman Empire"


def test_a_misspelled_phrase_is_guessed_word_by_word() -> None:
    response = search("fal of the romn empire")
    assert response.results == ()
    assert "The fall of the Western Roman Empire" in guesses(response)


def test_suggestions_are_best_first_scored_and_limited() -> None:
    response = search("Betelguese")
    scores = [s.similarity for s in response.suggestions]
    assert scores == sorted(scores, reverse=True)
    assert all(MIN_SIMILARITY <= score <= 1 for score in scores)
    assert len(scores) <= MAX_SUGGESTIONS
    assert response.suggestions[0].id == "hip-27989"


def test_suggestions_carry_the_type_and_id_to_open() -> None:
    first = search("Stonehenje").suggestions[0]
    assert (first.type, first.id) == (SearchType.LANDMARK, "stonehenge")


def test_gibberish_gets_no_suggestions_rather_than_bad_ones() -> None:
    response = search("zzzzqqqq")
    assert response.results == () and response.suggestions == ()


def test_text_too_short_for_letter_triples_gets_no_suggestions() -> None:
    assert search("zq").suggestions == ()


def test_accents_do_not_stop_a_guess() -> None:
    assert "Betelgeuse" in guesses(search("Bétélguese"))


# --- ranking rules, on a tiny hand-made database ----------------------------------------------


@pytest.fixture
def small(tmp_path: Path) -> Iterator[tuple[sqlite3.Connection, Path]]:
    path = tmp_path / "small.db"
    create_empty_database(path)
    connection = sqlite3.connect(path)
    yield connection, path
    connection.close()


def add(
    connection: sqlite3.Connection,
    place_id: str,
    name: str,
    *,
    aliases: str = "",
    description: str = "",
    fame: int = 0,
) -> None:
    connection.execute(
        "INSERT INTO vantage_points (id, name, kind, lookback_min, lookback_best, lookback_max, "
        "fame) VALUES (?, ?, 'star', 1, 2, 3, ?)",
        (place_id, name, fame),
    )
    connection.execute(
        "INSERT INTO search_entries (type, id, name, aliases, description) "
        "VALUES ('vantage_point', ?, ?, ?, ?)",
        (place_id, name, aliases, description),
    )


def ask(small: tuple[sqlite3.Connection, Path], text: str) -> SearchResponse:
    connection, path = small
    connection.commit()
    rebuild_search_index(connection)
    with Repository(path) as repo:
        return search(text, repository=repo)


def test_a_name_match_beats_a_match_in_the_description(
    small: tuple[sqlite3.Connection, Path],
) -> None:
    connection, _ = small
    add(connection, "in-description", "Zeta", description="A star near Vega")
    add(connection, "in-name", "Vega")
    assert [r.id for r in ask(small, "vega").results] == ["in-name", "in-description"]


def test_the_better_known_comes_first_when_matches_tie(
    small: tuple[sqlite3.Connection, Path],
) -> None:
    connection, _ = small
    add(connection, "obscure", "Alpha One", fame=0)
    add(connection, "famous", "Alpha Two", fame=5)
    add(connection, "middling", "Alpha Three", fame=2)
    assert [r.id for r in ask(small, "alpha").results] == ["famous", "middling", "obscure"]


def test_an_exact_alias_comes_before_a_better_ranked_word_match(
    small: tuple[sqlite3.Connection, Path],
) -> None:
    connection, _ = small
    add(connection, "word-match", "Orion Orion Orion", fame=5)
    add(connection, "alias-match", "Rigel", aliases="Orion\nBeta Orionis", fame=0)
    assert ask(small, "orion").results[0].id == "alias-match"


def test_the_same_entry_is_listed_once(small: tuple[sqlite3.Connection, Path]) -> None:
    connection, _ = small
    add(connection, "once", "Vega")
    assert [r.id for r in ask(small, "vega").results] == ["once"]


def test_an_empty_index_returns_nothing_not_an_error(
    small: tuple[sqlite3.Connection, Path],
) -> None:
    response = ask(small, "anything")
    assert response.results == () and response.suggestions == ()


# --- the response is a model ------------------------------------------------------------------


def test_responses_survive_a_round_trip_through_json() -> None:
    for text in ("Betelgeuse", "Betelguese", ""):
        response = search(text)
        assert SearchResponse.model_validate_json(response.model_dump_json()) == response


def test_unrelated_words_that_share_a_few_letters_are_not_suggested() -> None:
    assert guesses(search("Betelguese")) == ["Betelgeuse"]


def test_no_more_than_five_suggestions_are_given() -> None:
    assert len(search("trapist").suggestions) == MAX_SUGGESTIONS  # seven planets tie


def test_equally_alike_guesses_put_the_better_known_first(
    small: tuple[sqlite3.Connection, Path],
) -> None:
    connection, _ = small
    add(connection, "obscure-deneb", "Deneb", fame=0)
    add(connection, "famous-deneb", "Deneb", fame=5)
    assert [s.id for s in ask(small, "Denub").suggestions] == ["famous-deneb", "obscure-deneb"]


def test_several_exact_matches_put_the_better_known_first(
    small: tuple[sqlite3.Connection, Path],
) -> None:
    connection, _ = small
    add(connection, "obscure", "Orion Minor", aliases="Hunter", fame=0)
    add(connection, "famous", "Orion Major", aliases="Hunter", fame=5)
    assert [r.id for r in ask(small, "hunter").results] == ["famous", "obscure"]
