"""The engine: answers the two questions the project exists for.

``when(moment)`` answers "where in the universe is the light from this moment arriving right
now?". ``from_vantage(vantage_id)`` answers the reverse: "what did Earth look like in the
light arriving at this place?".

Both read the clock once and use that one "now" for every calculation, so a single answer never
mixes two slightly different present moments.
"""

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from earthlight.errors import EarthlightError
from earthlight.lookback import MomentRange
from earthlight.models import (
    EarthSnapshot,
    HistoryEvent,
    HistoryPeriod,
    Landmark,
    LandmarkStatus,
    Match,
    MomentResult,
    PopulationEstimate,
    SnapshotLandmark,
    VantageKind,
    VantagePoint,
    ZoneInfo,
)
from earthlight.repository import Repository, default_repository
from earthlight.solar_system import (
    AU_IN_LIGHT_YEARS,
    PLANETS,
    PROXIMA_CENTAURI_AU,
    TABLE_END_MOMENT,
    TABLE_FIRST_MOMENT,
    VOYAGER1_FIRST_MOMENT,
    VOYAGER1_LAST_MOMENT,
    Zone,
    au_to_light_years,
    planet_distance_au,
    voyager1_distance_au,
    zone_for_lookback,
)
from earthlight.time import (
    SECONDS_PER_JULIAN_YEAR,
    DecimalYear,
    format_year,
    now,
    seconds_between,
    subtract_seconds,
)

NEAR_MISS_FRACTION = 0.05
"""When no place has a range that contains the moment, the best place whose range comes
within this fraction of the lookback is shown instead, marked as approximate."""

MAX_LOOKBACK_YEARS = 1e15
"""Moments further back than this are rejected (the database cannot hold a lookback this large)."""

NAKED_EYE_MAGNITUDE = 6.0
"""The faintest star a person with good eyesight and a dark sky can see."""

_PROXIMA_LIGHT_YEARS = au_to_light_years(PROXIMA_CENTAURI_AU)

EARTH_AGE_YEARS = 4.54e9
"""Earth formed about 4.54 billion years ago (the same figure as the ``earth-forms`` history
entry, https://en.wikipedia.org/wiki/Age_of_Earth). Light older than this left a place where
Earth did not exist yet."""

MAX_ITEMS_PER_LIST = 10
"""A snapshot lists at most this many events, periods, and landmarks (the most important)."""

WIDE_SPAN_YEARS = 1000.0
"""A span of Earth's history wider than this is flagged as very wide."""

POPULATION_GRACE_YEARS = 5.0
"""A population estimate is shown up to this many years after the newest one in the database."""


class MomentError(EarthlightError, ValueError):
    """The moment cannot be answered. The message is written for the person who typed it."""


class FutureMomentError(MomentError):
    """The moment has not happened yet, so no light from it exists."""


class UnknownVantageError(EarthlightError, LookupError):
    """No place in the database has this id."""


def lookback_years(moment: DecimalYear, now_year: DecimalYear) -> float:
    """Years of lookback for ``moment`` seen from ``now_year``, using real elapsed seconds.

    Subtracting two decimal years is off by seconds for recent moments (a decimal fraction is
    a fraction of *that* calendar year), so this counts seconds and divides by a Julian year.
    """
    return seconds_between(moment, now_year) / SECONDS_PER_JULIAN_YEAR


def when(
    moment: DecimalYear,
    *,
    now_year: DecimalYear | None = None,
    repository: Repository | None = None,
) -> MomentResult:
    """Where in the universe is the light from ``moment`` arriving right now?

    Pass ``now_year`` to fix the present moment (tests do), and ``repository`` to use a
    database other than the bundled one. Raises ``MomentError`` for a moment that is not a
    finite number, and ``FutureMomentError`` for one that has not happened yet.
    """
    reference = now() if now_year is None else now_year  # the one and only clock read
    if not (math.isfinite(moment) and math.isfinite(reference)):
        raise MomentError("that moment is not a real point in time")
    if reference - moment > MAX_LOOKBACK_YEARS:
        raise MomentError("that moment is far older than the universe, so no light from it exists")
    if moment > reference:
        raise FutureMomentError(
            f"{format_year(moment, now_year=reference)} has not happened yet, so no light "
            "from it exists. Pick a moment in the past."
        )
    repo = default_repository() if repository is None else repository
    lookback = lookback_years(moment, reference)
    notes: list[str] = []

    zone_info: ZoneInfo | None = None
    zone = zone_for_lookback(lookback)
    if zone is not None:
        zone_info = _zone_info(zone, lookback)
        notes += _solar_system_notes(lookback, reference)

    oldest_light = repo.max_lookback()
    exact = repo.vantage_points_overlapping(lookback, lookback)
    winners: dict[str, Match | None] = {
        category.key: _best(category, exact, lookback) for category in _CATEGORIES
    }
    near_miss_notes: list[str] = []
    # Near misses make no sense inside the solar system (they would grab Proxima Centauri) or
    # beyond the oldest light (they would pretend there is something to see). The wider query
    # is only made when some category has no exact match, because it is the slow part.
    if None in winners.values() and zone is None and lookback <= oldest_light:
        near = repo.vantage_points_overlapping(
            lookback * (1 - NEAR_MISS_FRACTION), lookback * (1 + NEAR_MISS_FRACTION)
        )
        for category in _CATEGORIES:
            if winners[category.key] is None:
                match = _best(category, near, lookback)
                if match is not None:
                    winners[category.key] = match
                    near_miss_notes.append(_near_miss_note(category, match))

    notes += _empty_notes(winners, lookback, zone, oldest_light)
    notes += near_miss_notes
    return MomentResult(
        moment=moment,
        moment_label=format_year(moment, now_year=reference),
        lookback_years=lookback,
        zone=zone_info,
        famous=winners["famous"],
        exoplanet=winners["exoplanet"],
        visible_tonight=winners["visible_tonight"],
        most_precise=winners["most_precise"],
        notes=tuple(notes),
    )


# --- the four categories ---------------------------------------------------------------------


@dataclass(frozen=True)
class _Category:
    """One kind of answer: who may win, and how the contenders are ranked (smaller is better)."""

    key: str
    label: str
    eligible: Callable[[VantagePoint], bool]
    rank: Callable[[VantagePoint, float], tuple[float, ...]]


def _width(point: VantagePoint) -> float:
    return point.lookback.maximum - point.lookback.minimum


def _famous_rank(point: VantagePoint, lookback: float) -> tuple[float, ...]:
    return (-point.fame, abs(point.lookback.best - lookback), _width(point))


def _closest_rank(point: VantagePoint, lookback: float) -> tuple[float, ...]:
    return (abs(point.lookback.best - lookback), _width(point))


def _visible_rank(point: VantagePoint, lookback: float) -> tuple[float, ...]:
    return (abs(point.lookback.best - lookback), point.magnitude if point.magnitude else 0.0)


def _precise_rank(point: VantagePoint, lookback: float) -> tuple[float, ...]:
    return (_width(point), abs(point.lookback.best - lookback))


def _is_visible_star(point: VantagePoint) -> bool:
    return (
        point.kind is VantageKind.STAR
        and point.magnitude is not None
        and point.magnitude <= NAKED_EYE_MAGNITUDE
        and point.constellation is not None
    )


_CATEGORIES: tuple[_Category, ...] = (
    _Category("famous", "famous place", lambda p: p.fame > 0, _famous_rank),
    _Category("exoplanet", "exoplanet", lambda p: p.kind is VantageKind.EXOPLANET, _closest_rank),
    _Category("visible_tonight", "naked-eye star", _is_visible_star, _visible_rank),
    _Category("most_precise", "precisely measured place", lambda _p: True, _precise_rank),
)


def _best(category: _Category, candidates: Iterable[VantagePoint], lookback: float) -> Match | None:
    """The winner of ``category`` among ``candidates``, or None if nobody is eligible.

    Ties are broken by id, so the same database always gives the same answer.
    """
    eligible = [p for p in candidates if category.eligible(p)]
    if not eligible:
        return None
    winner = min(eligible, key=lambda p: (*category.rank(p, lookback), p.id))
    return Match(
        vantage_point=winner,
        offset_years=winner.lookback.best - lookback,
        approximate=not winner.lookback.contains(lookback),
    )


# --- zones and notes ------------------------------------------------------------------------


def _zone_info(zone: Zone, lookback: float) -> ZoneInfo:
    return ZoneInfo(
        id=zone.id,
        name=zone.name,
        description=zone.description,
        inner_au=zone.inner_au,
        outer_au=zone.outer_au,
        lookback=zone.lookback_range,
        percent_to_proxima=min(100.0, 100.0 * lookback / _PROXIMA_LIGHT_YEARS),
    )


def _light_distance_text(lookback: float) -> str:
    """How far the light has travelled, in the unit people can picture."""
    seconds = lookback * SECONDS_PER_JULIAN_YEAR
    au = lookback / AU_IN_LIGHT_YEARS
    if seconds < 120:
        return f"{seconds:.0f} light-seconds"
    if seconds < 7200:
        return f"{seconds / 60:.0f} light-minutes ({au:.1f} au)"
    if seconds < 172_800:
        return f"{seconds / 3600:.1f} light-hours ({au:,.0f} au)"
    if au < 10_000:
        return f"{seconds / 86_400:.0f} light-days ({au:,.0f} au)"
    return f"{lookback:.2f} light-years ({au:,.0f} au)"


def _solar_system_notes(lookback: float, reference: DecimalYear) -> list[str]:
    """Where the light is in our own neighbourhood: its distance, the planets, Voyager 1."""
    light_au = lookback / AU_IN_LIGHT_YEARS
    if lookback * SECONDS_PER_JULIAN_YEAR < 1:
        notes = ["This light has only just left Earth."]
    else:
        notes = [f"This light has travelled about {_light_distance_text(lookback)} from Earth."]
    if TABLE_FIRST_MOMENT <= reference < TABLE_END_MOMENT and light_au < 60:
        passed = [p for p in PLANETS if planet_distance_au(p, reference) <= light_au]
        ahead = [p for p in PLANETS if p not in passed]
        text = (
            f"Right now it has passed {_names(passed)}"
            if passed
            else "It has not yet reached any planet"
        )
        if passed and ahead:
            text += f" and is still on its way to {_names(ahead[:1])}"
        notes.append(text + ".")
    if VOYAGER1_FIRST_MOMENT <= reference <= VOYAGER1_LAST_MOMENT:
        voyager = voyager1_distance_au(reference)
        if voyager / 3 < light_au < voyager * 3:
            verb = "has passed" if light_au >= voyager else "has not yet reached"
            notes.append(f"Voyager 1 is about {voyager:.0f} au from the Sun; this light {verb} it.")
    return notes


def _names(planets: list[str]) -> str:
    names = [p.capitalize() for p in planets]
    return ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1]


def _near_miss_note(category: _Category, match: Match) -> str:
    point = match.vantage_point
    direction = "more recent" if match.offset_years < 0 else "older"
    return (
        f"No {category.label} has a range that contains this moment, so {point.name}, whose "
        f"range comes within {NEAR_MISS_FRACTION:.0%}, is shown instead. Its best estimate is "
        f"about {_years_text(abs(match.offset_years))} {direction} than this moment "
        "(an approximate match)."
    )


def _empty_notes(
    winners: dict[str, Match | None], lookback: float, zone: Zone | None, oldest_light: float
) -> list[str]:
    """Explain why categories are empty, so a blank is never a mystery."""
    notes: list[str] = []
    if lookback > oldest_light:
        notes.append(
            "This is older than the oldest light we can see. The cosmic microwave background, "
            "about 13.8 billion years old, is the earliest glow, and nothing earlier can be "
            "observed."
        )
        return notes
    if zone is not None:
        if any(match is not None for match in winners.values()):
            return notes  # a planet's range can start just inside the last zone
        notes.append(
            "No star is this close: the light is still crossing the Sun's own surroundings, "
            f"about {100 * lookback / _PROXIMA_LIGHT_YEARS:.3g}% of the way to the nearest star."
        )
        return notes
    for category in _CATEGORIES:
        if winners[category.key] is None:
            notes.append(
                f"No {category.label} has a range that comes within {NEAR_MISS_FRACTION:.0%} "
                "of this moment."
            )
    return notes


# --- place to moment ------------------------------------------------------------------------


def from_vantage(
    vantage_id: str,
    *,
    now_year: DecimalYear | None = None,
    repository: Repository | None = None,
) -> EarthSnapshot:
    """What did Earth look like in the light that is arriving at this place right now?

    The place's lookback range becomes a span of Earth's history. The snapshot lists the most
    important events, periods, and landmarks in that span (at most ten of each, oldest first),
    the world population nearest the middle of the span, and notes about anything unusual.
    Raises ``UnknownVantageError`` if no place has this id.
    """
    reference = now() if now_year is None else now_year  # the one and only clock read
    repo = default_repository() if repository is None else repository
    point = repo.vantage_point(vantage_id)
    if point is None:
        raise UnknownVantageError(f"there is no place with the id '{vantage_id}'")

    moments = _moments_for(point, reference)
    label = _span_label(moments, reference)
    notes: list[str] = []

    if point.lookback.best > EARTH_AGE_YEARS:
        notes.append(
            f"The light arriving at {point.name} left about {_years_text(point.lookback.best)} "
            f"ago. Earth formed only about {_years_text(EARTH_AGE_YEARS)} ago, so in this light "
            "Earth does not exist yet."
        )
        return EarthSnapshot(
            vantage_point=point,
            moments=moments,
            moments_label=label,
            earth_exists=False,
            notes=tuple(notes),
        )

    width = moments.latest - moments.earliest
    wide = width > WIDE_SPAN_YEARS
    if wide:
        notes.append(
            f"This place's distance is uncertain by about {_years_text(width)}, so the span of "
            "Earth's history is very wide."
        )

    earliest = moments.earliest
    earth_formed = subtract_seconds(reference, EARTH_AGE_YEARS * SECONDS_PER_JULIAN_YEAR)
    if earliest < earth_formed:
        earliest = earth_formed
        notes.append(
            "Part of this span is older than Earth, so only the time since Earth formed is shown."
        )

    events, periods, landmarks = _history(repo, earliest, moments)
    notes += _truncation_notes(events, periods, landmarks)
    population, population_notes = _population(repo, moments.best, reference)
    notes += population_notes
    return EarthSnapshot(
        vantage_point=point,
        moments=moments,
        moments_label=label,
        events=tuple(_chronological(events.shown, lambda e: e.year)),
        periods=tuple(_chronological(periods.shown, lambda p: p.start)),
        landmarks=tuple(_chronological(landmarks.shown, lambda m: m.built_start)),
        event_total=events.total,
        period_total=periods.total,
        landmark_total=landmarks.total,
        wide_span=wide,
        population=population,
        notes=tuple(notes),
    )


def _moments_for(point: VantagePoint, reference: DecimalYear) -> MomentRange:
    """The span of moments whose light is arriving at ``point`` (older light, larger lookback)."""

    def moment(lookback: float) -> DecimalYear:
        return subtract_seconds(reference, lookback * SECONDS_PER_JULIAN_YEAR)

    return MomentRange(
        earliest=moment(point.lookback.maximum),
        best=moment(point.lookback.best),
        latest=moment(point.lookback.minimum),
    )


def _span_label(moments: MomentRange, reference: DecimalYear) -> str:
    first = format_year(moments.earliest, now_year=reference)
    last = format_year(moments.latest, now_year=reference)
    return first if first == last else f"{first} to {last}"


def _years_text(years: float) -> str:
    """A span of years for people: '3 years', '12,000 years', '4.54 billion years'."""
    for size, unit in ((1e9, "billion"), (1e6, "million")):
        if years >= size:
            return f"{years / size:.3g} {unit} years"
    return f"{years:,.0f} years" if years >= 10 else f"{years:.3g} years"


@dataclass(frozen=True)
class _Listed[T]:
    """Everything found in a span (``total``), and the most important few that are shown."""

    shown: list[T]
    total: int


def _top[T](found: list[T]) -> _Listed[T]:
    """``found`` arrives most important first, so the shown ones are its first few."""
    return _Listed(found[:MAX_ITEMS_PER_LIST], len(found))


def _chronological[T: HistoryEvent | HistoryPeriod | SnapshotLandmark](
    items: Iterable[T], moment_of: Callable[[T], float]
) -> list[T]:
    return sorted(items, key=lambda item: (moment_of(item), item.id))


def _history(
    repo: Repository, earliest: DecimalYear, moments: MomentRange
) -> tuple[_Listed[HistoryEvent], _Listed[HistoryPeriod], _Listed[SnapshotLandmark]]:
    events = _top(repo.events_between(earliest, moments.latest))
    periods = _top(repo.periods_overlapping(earliest, moments.latest))
    begun = [
        m
        for m in repo.landmarks_overlapping(earliest, moments.latest)
        if m.built_start <= moments.best
    ]
    landmarks = _top(begun)
    return (
        events,
        periods,
        _Listed([_with_status(m, moments.best) for m in landmarks.shown], landmarks.total),
    )


def _with_status(landmark: Landmark, best_moment: DecimalYear) -> SnapshotLandmark:
    """Where the landmark stood at the middle of the span: destroyed, still being built, or
    standing."""
    if landmark.destroyed is not None and landmark.destroyed <= best_moment:
        status = LandmarkStatus.DESTROYED
    elif landmark.built_end > best_moment:
        status = LandmarkStatus.UNDER_CONSTRUCTION
    else:
        status = LandmarkStatus.STANDING
    return SnapshotLandmark(**landmark.model_dump(), status=status)


def _truncation_notes(
    events: _Listed[HistoryEvent],
    periods: _Listed[HistoryPeriod],
    landmarks: _Listed[SnapshotLandmark],
) -> list[str]:
    notes: list[str] = []
    for label, listed in (("events", events), ("periods", periods), ("landmarks", landmarks)):
        if listed.total > len(listed.shown):
            notes.append(
                f"Showing the {len(listed.shown)} most important of {listed.total:,} {label} "
                "in this span."
            )
    return notes


def _population(
    repo: Repository, best_moment: DecimalYear, reference: DecimalYear
) -> tuple[PopulationEstimate | None, list[str]]:
    """The world population nearest the middle of the span, if the data reaches that far."""
    years = repo.population_years()
    if years is None or not years[0] <= best_moment <= years[1] + POPULATION_GRACE_YEARS:
        return None, []
    estimate = repo.population_nearest(best_moment)
    if estimate is None:
        return None, []
    notes: list[str] = []
    if abs(estimate.year - best_moment) > 1:
        notes.append(
            "The world population shown is the nearest estimate, for "
            f"{format_year(estimate.year, now_year=reference)}; there is none for the exact year."
        )
    return estimate, notes
