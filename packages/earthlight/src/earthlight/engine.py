"""The engine: answers the two questions the project exists for.

``when(moment)`` answers "where in the universe is the light from this moment arriving right
now?". ``from_vantage(vantage_id)`` (added in the next step) answers the reverse.

Both read the clock once and use that one "now" for every calculation, so a single answer never
mixes two slightly different present moments.
"""

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from earthlight.models import Match, MomentResult, VantageKind, VantagePoint, ZoneInfo
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
)

NEAR_MISS_FRACTION = 0.05
"""When no place has a range that contains the moment, the nearest place whose best estimate is
within this fraction of the lookback is shown instead, marked as approximate."""

NAKED_EYE_MAGNITUDE = 6.0
"""The faintest star a person with good eyesight and a dark sky can see."""

_PROXIMA_LIGHT_YEARS = au_to_light_years(PROXIMA_CENTAURI_AU)


class MomentError(ValueError):
    """The moment cannot be answered. The message is written for the person who typed it."""


class FutureMomentError(MomentError):
    """The moment has not happened yet, so no light from it exists."""


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
    # Near misses make no sense inside the solar system (they would grab Proxima Centauri) or
    # beyond the oldest light (they would pretend there is something to see).
    near = (
        []
        if zone is not None or lookback > oldest_light
        else repo.vantage_points_overlapping(
            lookback * (1 - NEAR_MISS_FRACTION), lookback * (1 + NEAR_MISS_FRACTION)
        )
    )
    winners: dict[str, Match | None] = {}
    near_miss_notes: list[str] = []
    for category in _CATEGORIES:
        match = _best(category, exact, lookback)
        if match is None:
            match = _best(category, near, lookback)
            if match is not None:
                near_miss_notes.append(_near_miss_note(category, match))
        winners[category.key] = match

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
    return (abs(point.lookback.best - lookback), point.magnitude or 0.0)


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
    return Match(vantage_point=winner, offset_years=winner.lookback.best - lookback)


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
    direction = "nearer" if match.offset_years < 0 else "farther"
    return (
        f"No {category.label} has a range that contains this moment, so the nearest one is "
        f"shown: {point.name}, about {abs(match.offset_years):,.3g} years {direction} than "
        f"this moment (an approximate match)."
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
