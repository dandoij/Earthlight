"""Search over places and history, with did-you-mean for typos.

``search(text)`` tries three things in order:

1. Exact names: a name or alias that is the text (ignoring case) comes first.
2. Word search (SQLite FTS5): every word must appear, and the last word may be unfinished, so
   "androm" finds the Andromeda Galaxy as you type. Name matches rank above matches in other
   names or descriptions, and better known things rank above obscure ones on a tie.
3. Did-you-mean, only when nothing matched: the letter triples of the text find candidates
   (the trigram index finds near-misses that word search cannot), and Python's ``difflib``
   scores how alike each candidate's name really is.

The text a person types is never put into SQL or into FTS5 syntax as written: it is cut into
plain words, and each word is quoted, so characters like ``"`` or ``*`` or ``AND`` cannot change
the meaning of the query.
"""

import re
import unicodedata
from collections.abc import Iterable
from difflib import SequenceMatcher

from earthlight.models import SearchResponse, SearchResult, SearchType, Suggestion, VantageKind
from earthlight.repository import Repository, SearchRow, default_repository

DEFAULT_LIMIT = 10
"""How many results a search returns unless asked for another number."""

MAX_QUERY_CHARS = 100
"""Longer text is cut to this length: no name is longer than a short sentence."""

MAX_SUGGESTIONS = 5
"""How many did-you-mean guesses to offer."""

MIN_SIMILARITY = 0.7
"""A guess must be at least this alike (0 to 1) to be offered. 0.6 (the ``difflib`` default)
let through unrelated words that share a few letters, such as "telescope" for "betelguese"."""

_CANDIDATES = 60
"""How many trigram candidates are scored with ``difflib`` for each did-you-mean."""

_MAX_TRIGRAM_WORDS = 8
_WORD = re.compile(r"\w+", re.UNICODE)


def search(
    text: str, *, limit: int = DEFAULT_LIMIT, repository: Repository | None = None
) -> SearchResponse:
    """Find places and history entries for ``text``.

    Returns the hits best first (at most ``limit``). When there are none, ``suggestions`` holds
    up to five did-you-mean guesses. Text with no letters or digits finds nothing.
    """
    repo = default_repository() if repository is None else repository
    query = tidy(text)
    words = _WORD.findall(query)
    rows = search_rows(text, limit=limit, repository=repo)
    if rows or not words or limit < 1:
        return SearchResponse(query=query, results=tuple(_result(row) for row in rows))
    return SearchResponse(query=query, suggestions=_suggestions(repo, query, words))


def tidy(text: str) -> str:
    """The text with spaces tidied up and cut to ``MAX_QUERY_CHARS``."""
    return " ".join(text.split())[:MAX_QUERY_CHARS].strip()


def search_rows(
    text: str, *, limit: int = DEFAULT_LIMIT, repository: Repository | None = None
) -> list[SearchRow]:
    """The stored entries that match ``text``, best first (at most ``limit``): the exact names,
    then the word matches. This is ``search`` before it is turned into models, and it carries
    each entry's other names, which a caller may want to check.
    """
    repo = default_repository() if repository is None else repository
    query = tidy(text)
    words = _WORD.findall(query)
    if not words or limit < 1:
        return []
    found = [*repo.search_exact(query), *repo.search_words(_expression(words), limit)]
    return _unique(found)[:limit]


def _unique(rows: Iterable[SearchRow]) -> list[SearchRow]:
    """Drop repeats (an exact hit is usually a word hit as well), keeping the first of each."""
    seen: set[tuple[str, str]] = set()
    kept: list[SearchRow] = []
    for row in rows:
        if (row.type, row.id) not in seen:
            seen.add((row.type, row.id))
            kept.append(row)
    return kept


def _expression(words: list[str]) -> str:
    """FTS5 text for 'all these words, the last one possibly unfinished'."""
    quoted = [f'"{word}"' for word in words]
    quoted[-1] += "*"
    return " ".join(quoted)


def _result(row: SearchRow) -> SearchResult:
    kind = VantageKind(row.kind) if row.type == SearchType.VANTAGE_POINT else None
    return SearchResult(
        type=SearchType(row.type),
        id=row.id,
        name=row.name,
        kind=kind,
        description=row.description or None,
    )


# --- did you mean ----------------------------------------------------------------------------


def _fold(text: str) -> str:
    """Lowercase and drop accents, so 'Cafe' and 'Café' compare as equal."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _triples(words: list[str]) -> list[str]:
    """The distinct three-letter pieces of each word, in order."""
    seen: dict[str, None] = {}
    for word in words[:_MAX_TRIGRAM_WORDS]:
        folded = _fold(word)
        for start in range(len(folded) - 2):
            seen[folded[start : start + 3]] = None
    return list(seen)


def _suggestions(repo: Repository, query: str, words: list[str]) -> tuple[Suggestion, ...]:
    triples = _triples(words)
    if not triples:
        return ()
    expression = " OR ".join(f'"{triple}"' for triple in triples)
    candidates = _unique(repo.search_trigrams(expression, _CANDIDATES))
    wanted = _fold(" ".join(words))
    scored = [(_similarity(wanted, row), row) for row in candidates]
    best = sorted(
        (pair for pair in scored if pair[0] >= MIN_SIMILARITY),
        key=lambda pair: (-pair[0], -pair[1].weight, pair[1].name),
    )
    return tuple(
        Suggestion(
            type=SearchType(row.type),
            id=row.id,
            name=row.name,
            similarity=round(score, 3),
        )
        for score, row in best[:MAX_SUGGESTIONS]
    )


def _similarity(wanted: str, row: SearchRow) -> float:
    """How alike ``wanted`` is to the entry: its best match over every name it has.

    A name is compared whole and also in runs of the same number of words, so "fall of rom"
    can match the start of "The fall of the Western Roman Empire".
    """
    count = len(wanted.split())
    best = 0.0
    for name in (row.name, *row.aliases):
        folded = _fold(name)
        pieces = folded.split()
        windows = {" ".join(pieces[i : i + count]) for i in range(max(1, len(pieces) - count + 1))}
        for candidate in (folded, *windows):
            best = max(best, SequenceMatcher(None, wanted, candidate).ratio())
    return best
