"""Tests for the ``earthlight search`` command and the did-you-mean lines in errors."""

import io
import re

import pytest
from rich.console import Console
from typer.testing import CliRunner, Result

import earthlight
from earthlight.cli import app, friendly_errors
from earthlight.cli.render import search_view
from earthlight.errors import UnresolvedNameError
from earthlight.models import SearchResponse, SearchResult, SearchType, Suggestion

ANSI_CODES = re.compile(r"\x1b\[[0-9;]*m")
ENV = {"NO_COLOR": "1", "COLUMNS": "120", "TERMINAL_WIDTH": "200"}

runner = CliRunner()


def run(*arguments: str) -> Result:
    return runner.invoke(app, list(arguments), env=ENV)


def out(result: Result) -> str:
    return ANSI_CODES.sub("", result.stdout)


def err(result: Result) -> str:
    return ANSI_CODES.sub("", result.stderr)


# --- search ---------------------------------------------------------------------------------


def test_search_lists_hits_with_their_type_detail_and_id() -> None:
    result = run("search", "androm")
    text = out(result)
    assert result.exit_code == 0
    assert "Andromeda Galaxy (Messier 31)" in text
    assert "andromeda-galaxy" in text
    assert "galaxy" in text
    assert "Star in Andromeda" in text


def test_each_row_starts_with_what_the_hit_is() -> None:
    rows = [line for line in out(run("search", "androm")).splitlines() if line.startswith("│")]
    assert any(re.match(r"│ galaxy\s+│ Andromeda Galaxy", row) for row in rows)
    assert any(re.match(r"│ star\s+│ Almach", row) for row in rows)


def test_search_finds_history_and_labels_it_by_type() -> None:
    text = out(run("search", "fall of rom"))
    assert "The fall of the Western Roman Empire" in text
    assert "event" in text
    assert "fall-of-the-western-roman-empire" in text


def test_limit_caps_the_rows() -> None:
    def data_rows(text: str) -> int:
        return sum(1 for line in text.splitlines() if line.startswith("│") and "Type" not in line)

    assert data_rows(out(run("search", "androm", "--limit", "3"))) == 3
    assert data_rows(out(run("search", "androm", "-n", "1"))) == 1


@pytest.mark.parametrize("limit", ["0", "101", "-1", "many"])
def test_a_bad_limit_is_a_usage_error(limit: str) -> None:
    assert run("search", "androm", "--limit", limit).exit_code == 2


def test_a_typo_gets_did_you_mean_with_the_id_and_still_exits_zero() -> None:
    result = run("search", "Betelguese")
    text = out(result)
    assert result.exit_code == 0
    assert "Nothing found for 'Betelguese'." in text
    assert "Did you mean:" in text
    assert "Betelgeuse  (place, id hip-27989)" in text


def test_nothing_found_and_no_guess_just_says_so() -> None:
    result = run("search", "qqqq zzzz")
    assert result.exit_code == 0
    assert out(result).strip() == "Nothing found for 'qqqq zzzz'."


def test_search_needs_text() -> None:
    assert run("search").exit_code == 2


def test_search_text_that_looks_like_markup_is_shown_literally() -> None:
    assert "Nothing found for '[red]x[/red]'." in out(run("search", "[red]x[/red]"))


def test_a_table_cell_that_looks_like_markup_is_shown_literally() -> None:
    response = SearchResponse(
        query="alpha",
        results=(
            SearchResult(
                type=SearchType.EVENT,
                id="an-id",
                name="[bold]Alpha[/bold] :star:",
                description="[red]note[/red] :rocket:",
            ),
        ),
    )
    printed = io.StringIO()
    Console(file=printed, width=120, color_system=None).print(search_view(response))
    assert "[bold]Alpha[/bold] :star:" in printed.getvalue()
    assert "[red]note[/red] :rocket:" in printed.getvalue()


# --- did-you-mean in the errors of the other commands ---------------------------------------


@pytest.mark.parametrize(
    "arguments",
    [["from", "Betelguese"], ["info", "Betelguese"]],
)
def test_a_misspelt_place_lists_guesses_with_ids(arguments: list[str]) -> None:
    result = run(*arguments)
    assert result.exit_code == 1
    assert err(result).startswith("Error:")
    assert "Try one of these ids:" in err(result)
    assert "Betelgeuse  (place, id hip-27989)" in err(result)
    assert err(result).count("Did you mean") == 1  # the engine's sentence, not repeated
    assert result.stdout == ""


def test_a_misspelt_event_name_lists_guesses() -> None:
    result = run("when", "--event", "fall of rom1")
    assert result.exit_code == 1
    assert "The fall of the Western Roman Empire  (event, id fall-of-the-western-roman-empire)" in (
        err(result)
    )


def test_a_name_with_only_partial_matches_lists_them_in_a_table() -> None:
    result = run("from", "sun")
    assert result.exit_code == 1
    assert "Partial matches" in err(result)
    assert "messier-63" in err(result)


def test_an_unresolved_name_with_nothing_to_offer_is_just_the_message() -> None:
    result = run("info", "qqqq zzzz")
    assert result.exit_code == 1
    assert "Did you mean" not in err(result)
    assert "Partial matches" not in err(result)


def test_the_handler_lists_whatever_the_error_carries() -> None:
    import typer

    test_app = typer.Typer()

    @test_app.command()
    def boom() -> None:  # pyright: ignore[reportUnusedFunction]
        with friendly_errors():
            raise UnresolvedNameError(
                "No luck.",
                text="x",
                suggestions=(
                    Suggestion(type=SearchType.EVENT, id="an-id", name="A Name", similarity=0.8),
                ),
            )

    result = runner.invoke(test_app, [], env=ENV)
    assert result.exit_code == 1
    assert "A Name  (event, id an-id)" in err(result)


def test_other_errors_do_not_get_a_suggestion_block() -> None:
    result = run("when", "2999")
    assert result.exit_code == 1
    assert "Did you mean" not in err(result)


def test_the_python_search_agrees_with_the_command() -> None:
    names = [hit.name for hit in earthlight.search("androm", limit=5).results]
    text = out(run("search", "androm", "-n", "5"))
    for name in names:
        assert name in text
