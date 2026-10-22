"""Turning typed text into a place or a moment.

People type names ("Betelgeuse", "apollo 11"), and the engine wants ids and decimal years.
This module does that translation with the help of ``search``, and says so plainly when it
cannot: the error carries the closest guesses.
"""

import re
from dataclasses import dataclass

from earthlight.errors import UnresolvedNameError
from earthlight.models import SearchResponse, SearchType, VantagePoint
from earthlight.repository import Repository, SearchRow
from earthlight.search import search, search_rows, tidy
from earthlight.time import DecimalYear, format_year

_HISTORY_TYPES = frozenset({SearchType.EVENT, SearchType.PERIOD, SearchType.LANDMARK})

_HISTORY_NAMES = frozenset(t.value for t in _HISTORY_TYPES)

_ROLE_TEXT = {
    "date": "",
    "start": ", the start of the period",
    "completion": ", the year its construction finished",
}


@dataclass(frozen=True)
class ResolvedMoment:
    """A history entry found by name, the moment standing for it, and a note saying so."""

    moment: DecimalYear
    note: str


def resolve_place(text: str, repo: Repository) -> VantagePoint:
    """The place named by ``text``: an exact id first, otherwise an exact name or alias.

    Raises ``UnresolvedNameError`` (with did-you-mean guesses) when no place matches.
    """
    cleaned = " ".join(text.split())
    if cleaned:
        point = repo.vantage_point(cleaned) or repo.vantage_point(cleaned.lower())
        if point is not None:
            return point
        for row in repo.search_exact(cleaned):  # best known first
            if row.type == SearchType.VANTAGE_POINT:
                found = repo.vantage_point(row.id)
                if found is not None:
                    return found
    response = search(cleaned, repository=repo)
    places = _only(response, {SearchType.VANTAGE_POINT})
    raise UnresolvedNameError(
        _not_found_message(cleaned, "place", places),
        text=cleaned,
        results=places.results,
        suggestions=places.suggestions,
    )


def resolve_history(text: str, repo: Repository, *, now_year: DecimalYear) -> ResolvedMoment:
    """The moment for an event, period, or landmark named by ``text`` (the best search hit).

    An event gives its date, a period its start, and a landmark the year it was finished.
    Raises ``UnresolvedNameError`` when nothing in history matches; if the text names a place
    instead, the message says so.
    """
    query = tidy(text)
    for row in search_rows(text, limit=10, repository=repo):
        entry = repo.history_moment(row.type, row.id) if row.type in _HISTORY_NAMES else None
        if entry is not None:
            label = format_year(entry.moment, now_year=now_year)
            detail = f"{entry.name} ({label}{_ROLE_TEXT[entry.role]})"
            if _names_every_word(row, query):
                note = f"Using {detail} for '{query}'."
            else:
                note = f"Closest match for '{query}': {detail}."
            return ResolvedMoment(moment=entry.moment, note=note)
    response = search(text, limit=10, repository=repo)
    history = _only(response, _HISTORY_TYPES)
    places = _only(response, {SearchType.VANTAGE_POINT})
    if places.results:
        message = (
            f"'{response.query}' is the name of a place, not a moment. "
            "Use from_vantage to see Earth as it looks from there."
        )
    else:
        message = _not_found_message(response.query, "event, period, or landmark", history)
    raise UnresolvedNameError(
        message, text=response.query, results=history.results, suggestions=history.suggestions
    )


def _names_every_word(row: SearchRow, query: str) -> bool:
    """True when the entry's name or one of its other names has every word of ``query`` (the
    last word may be unfinished). A hit that matched only through its description is weaker."""
    words = re.findall(r"\w+", query.lower())
    for name in (row.name, *row.aliases):
        tokens = re.findall(r"\w+", name.lower())
        if all(w in tokens for w in words[:-1]) and any(t.startswith(words[-1]) for t in tokens):
            return True
    return False


def _only(
    response: SearchResponse, types: frozenset[SearchType] | set[SearchType]
) -> SearchResponse:
    """The part of ``response`` about the given types of thing."""
    return SearchResponse(
        query=response.query,
        results=tuple(r for r in response.results if r.type in types),
        suggestions=tuple(s for s in response.suggestions if s.type in types),
    )


def _not_found_message(text: str, noun: str, found: SearchResponse) -> str:
    if not text:
        return f"Enter the name of a {noun}."
    message = f"No {noun} called '{text}' was found."
    guesses = [s.name for s in found.suggestions] or [r.name for r in found.results]
    if guesses:
        message += " Did you mean " + ", ".join(guesses[:3]) + "?"
    return message
