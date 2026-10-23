"""Earthlight: map moments in time to places in the universe by light travel time.

Light travels one light-year per year, so a star 66 light-years away is receiving, right now,
the light that left Earth 66 years ago. Earthlight turns that into two questions:

* ``when(moment)``: where in the universe is the light from this moment arriving right now?
* ``from_vantage(place)``: what did Earth look like in the light arriving at this place?

plus ``info(place)`` for the details of one place, and ``search(text)`` to find places and
history by name, with did-you-mean for typos.

Every example below passes ``now_year`` so that the answer does not depend on today's date.

>>> import earthlight
>>> answer = earthlight.when("1492", now_year=2026.0)
>>> answer.moment_label, round(answer.lookback_years)
('1492 CE', 534)
>>> answer.famous.vantage_point.name
'Antares'
>>> snapshot = earthlight.from_vantage("Betelgeuse", now_year=2026.0)
>>> snapshot.moments_label
'1455 CE to 1584 CE'
>>> [event.name for event in snapshot.events][:2]
['Columbus reaches the Americas', 'Vasco da Gama reaches India by sea']
>>> earthlight.search("Betelguese").suggestions[0].name
'Betelgeuse'

Anything that goes wrong on purpose raises a subclass of ``EarthlightError``, with a message
written for the person who asked.
"""

from datetime import datetime

from earthlight import engine as _engine
from earthlight.errors import EarthlightError, UnresolvedNameError
from earthlight.models import (
    EarthSnapshot,
    ExoplanetDetails,
    MomentResult,
    PlaceInfo,
    SearchResponse,
    VantageKind,
    VantagePoint,
)
from earthlight.parse import (
    EmptyInputError,
    EventQuery,
    InvalidMomentError,
    MomentQuery,
    ParseError,
    ParseResult,
    clean_event_name,
    parse,
)
from earthlight.repository import Repository, default_repository
from earthlight.resolve import resolve_history, resolve_place
from earthlight.search import search as _search
from earthlight.time import DecimalYear, from_datetime, now

FutureMomentError = _engine.FutureMomentError
MomentError = _engine.MomentError
UnknownVantageError = _engine.UnknownVantageError


def when(
    moment: str | float | datetime,
    *,
    as_event: bool = False,
    now_year: DecimalYear | None = None,
    repository: Repository | None = None,
) -> MomentResult:
    """Where in the universe is the light from ``moment`` arriving right now?

    ``moment`` can be text (``"1492"``, ``"500 BCE"``, ``"2004-06-15"``, ``"3 days ago"``,
    ``"66 million years ago"``, ``"66 mya"``, or the name of an event such as
    ``"apollo 11"``), a number (a decimal year, where 2026.5 is the middle of 2026), or a
    ``datetime`` (naive ones count as UTC). An event name uses the best match: an event's date,
    a period's start, or the year a landmark was finished, and a note says which one.

    The result has one winner for each of four categories (famous, exoplanet, visible tonight,
    most precise) and plain-language ``notes``. Pass ``as_event=True`` to treat text as an event
    name even if it looks like a moment (``"1492"`` would then search for an event called
    that). Pass ``now_year`` to fix the present moment and ``repository`` to use a database
    other than the bundled one.

    Raises ``FutureMomentError`` for a moment that has not happened yet, ``ParseError`` for
    text that is not a moment, and ``UnresolvedNameError`` for an event name that matches
    nothing (its ``suggestions`` hold did-you-mean guesses).

    >>> result = when("66 million years ago", now_year=2026.0)
    >>> result.moment_label
    '66 million years ago'
    >>> result.famous is None
    True
    >>> when("3 hours ago", now_year=2026.0).zone.name
    'Inside the heliosphere'
    """
    reference = now() if now_year is None else now_year  # the one and only clock read
    repo = default_repository() if repository is None else repository
    note: str | None = None
    if as_event and not isinstance(moment, str):
        raise TypeError("as_event needs the name of an event as text")
    if isinstance(moment, str):
        if as_event:
            parsed: ParseResult = EventQuery(clean_event_name(moment))
        else:
            parsed = parse(moment, now_year=reference)
        if isinstance(parsed, MomentQuery):
            year = parsed.moment
        else:
            resolved = resolve_history(parsed.text, repo, now_year=reference)
            year, note = resolved.moment, resolved.note
    elif isinstance(moment, datetime):
        try:
            year = from_datetime(moment)
        except ValueError as error:
            raise MomentError(str(error)) from error
    elif isinstance(moment, bool):
        raise TypeError("a moment must be text, a number, or a datetime, not a bool")
    else:
        year = float(moment)
    result = _engine.when(year, now_year=reference, repository=repo)
    if note is None:
        return result
    return result.model_copy(update={"notes": (note, *result.notes)})


def from_vantage(
    place: str,
    *,
    now_year: DecimalYear | None = None,
    repository: Repository | None = None,
) -> EarthSnapshot:
    """What did Earth look like in the light that is arriving at ``place`` right now?

    ``place`` is an id (``"hip-27989"``) or a name or alias (``"Betelgeuse"``, ``"M31"``). The
    snapshot lists the most important events, periods, and landmarks in that span of Earth's
    history (at most ten of each, oldest first), the world population, and notes about
    anything unusual, such as a span so wide that it is uncertain, or light older than Earth.

    Raises ``UnresolvedNameError`` if no place has that id or name (its ``suggestions`` hold
    did-you-mean guesses).

    >>> from_vantage("hip-70890", now_year=2026.0).moments_label
    '2021 CE'
    >>> from_vantage("GN-z11", now_year=2026.0).earth_exists
    False
    """
    reference = now() if now_year is None else now_year
    repo = default_repository() if repository is None else repository
    point = resolve_place(place, repo)
    return _engine.from_vantage(point.id, now_year=reference, repository=repo)


def info(place: str, *, repository: Repository | None = None) -> PlaceInfo:
    """Everything known about one place: the place itself, the archive details if it is an
    exoplanet, and the ids of its planets if it is a star.

    ``place`` is an id or a name, as for ``from_vantage``.

    >>> details = info("proxima-cen-b")
    >>> details.vantage_point.host_id, details.exoplanet.discovery_year
    ('hip-70890', 2016)
    >>> "proxima-cen-b" in info("Proxima Centauri").planet_ids
    True
    """
    repo = default_repository() if repository is None else repository
    point = resolve_place(place, repo)
    if point.kind is VantageKind.EXOPLANET:
        return PlaceInfo(vantage_point=point, exoplanet=repo.exoplanet_details(point.id))
    if point.kind is VantageKind.STAR:
        return PlaceInfo(vantage_point=point, planet_ids=tuple(repo.planet_ids_of(point.id)))
    return PlaceInfo(vantage_point=point)


def search(text: str, *, limit: int = 10, repository: Repository | None = None) -> SearchResponse:
    """Find places and history entries by name.

    Exact names and aliases come first, then word matches (the last word may be unfinished, so
    ``"androm"`` finds the Andromeda Galaxy). When nothing matches, ``suggestions`` holds
    did-you-mean guesses.

    >>> [hit.name for hit in search("Sirius").results]
    ['Sirius']
    >>> search("Sirus").suggestions[0].name
    'Sirius'
    """
    return _search(text, limit=limit, repository=repository)


__all__ = [
    "EarthSnapshot",
    "EarthlightError",
    "EmptyInputError",
    "ExoplanetDetails",
    "FutureMomentError",
    "InvalidMomentError",
    "MomentError",
    "MomentResult",
    "ParseError",
    "PlaceInfo",
    "SearchResponse",
    "UnknownVantageError",
    "UnresolvedNameError",
    "VantageKind",
    "VantagePoint",
    "from_vantage",
    "info",
    "search",
    "when",
]
