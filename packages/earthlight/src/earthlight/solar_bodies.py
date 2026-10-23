"""The Sun, the Moon, and the seven other planets as places you can look from.

Every other place has a distance that does not change, so it is stored once in the database. These
bodies are close enough that their distance from Earth changes from day to day, so their
lookback is worked out for the date asked about and nothing is stored.

The lookback range is how far apart the two bodies can ever be (the planets: from the sizes of the
two orbits; the Sun: perihelion to aphelion; the Moon: NASA's quoted range), and the best estimate
is the distance on the date. See ``docs/data-sources.md`` for where each number comes from.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

from earthlight.lookback import LookbackRange
from earthlight.models import FactValue, VantageKind, VantagePoint
from earthlight.solar_system import (
    MOON_FARTHEST_KM,
    MOON_MEAN_KM,
    MOON_NEAREST_KM,
    PLANETS,
    TABLE_END_MOMENT,
    TABLE_FIRST_MOMENT,
    Planet,
    au_to_light_years,
    earth_sun_distance_au,
    earth_sun_distance_bounds_au,
    km_to_au,
    planet_distance_au,
    planet_distance_bounds_au,
)
from earthlight.time import DecimalYear

ORBIT_RANGE_MIDPOINT: Final = "orbit_range_midpoint"
"""The ``distance_source`` fact of a body asked about outside 1800 to 2050 AD."""

OUT_OF_TABLE_NOTE: Final = (
    "This date is outside 1800 to 2050 AD, where the orbit formulas stop, so only the range is "
    "reliable, not the exact distance."
)


@dataclass(frozen=True)
class SolarBody:
    """One body of the solar system that can be looked from.

    ``other_names`` are alternative names that also match when only the start is typed ("lun"
    finds the Moon). ``exact_names`` match only when typed in full, so "ear" does not find the
    Moon through "Earth's Moon".
    """

    id: str
    name: str
    kind: VantageKind
    fame: int
    wikipedia: str
    description: str
    other_names: tuple[str, ...] = ()
    exact_names: tuple[str, ...] = ()


_PLANET_DESCRIPTION: Final = "Planet of the solar system"

SOLAR_BODIES: Final[tuple[SolarBody, ...]] = (
    SolarBody(
        "sun", "Sun", VantageKind.STAR, 5, "Sun", "Star at the centre of the solar system", ("Sol",)
    ),
    SolarBody(
        "moon",
        "Moon",
        VantageKind.MOON,
        5,
        "Moon",
        "Natural satellite of the Earth",
        ("Luna",),
        ("Earth's Moon",),
    ),
    SolarBody("mercury", "Mercury", VantageKind.PLANET, 3, "Mercury (planet)", _PLANET_DESCRIPTION),
    SolarBody("venus", "Venus", VantageKind.PLANET, 4, "Venus", _PLANET_DESCRIPTION),
    SolarBody("mars", "Mars", VantageKind.PLANET, 4, "Mars", _PLANET_DESCRIPTION),
    SolarBody("jupiter", "Jupiter", VantageKind.PLANET, 4, "Jupiter", _PLANET_DESCRIPTION),
    SolarBody("saturn", "Saturn", VantageKind.PLANET, 4, "Saturn", _PLANET_DESCRIPTION),
    SolarBody("uranus", "Uranus", VantageKind.PLANET, 3, "Uranus", _PLANET_DESCRIPTION),
    SolarBody("neptune", "Neptune", VantageKind.PLANET, 3, "Neptune", _PLANET_DESCRIPTION),
)

_BY_ID: Final[dict[str, SolarBody]] = {body.id: body for body in SOLAR_BODIES}
SOLAR_BODY_IDS: Final[tuple[str, ...]] = tuple(_BY_ID)
PLANET_IDS: Final[tuple[str, ...]] = tuple(
    body.id for body in SOLAR_BODIES if body.kind is VantageKind.PLANET
)
_PLANET_BY_ID: Final[dict[str, Planet]] = {planet: planet for planet in PLANETS}


def _normalised(text: str) -> str:
    """Words only, lower case, without accents or a leading "the".

    "The Sun.", "SUN", and "Säturn" become "sun", "sun", and "saturn". An apostrophe, straight or
    typographic, splits a word: "Earth's Moon" becomes "earth s moon", the same form the names
    of the bodies take.
    """
    folded = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in folded if not unicodedata.combining(char))
    words = re.findall(r"\w+", plain)
    if words and words[0] == "the":
        words = words[1:]
    return " ".join(words)


_BY_NAME: Final[dict[str, SolarBody]] = {
    _normalised(name): body
    for body in SOLAR_BODIES
    for name in (body.id, body.name, *body.other_names, *body.exact_names)
}

_EARTH_NAMES: Final = frozenset({"earth", "planet earth"})

MIN_PREFIX_CHARS = 3
"""The shortest start of a name that finds a body ("sat" finds Saturn, "s" finds nothing)."""


def find_solar_body(text: str) -> SolarBody | None:
    """The body that ``text`` names exactly (ignoring case, accents, punctuation, and a leading
    "the"), if any."""
    return _BY_NAME.get(_normalised(text))


def matching_solar_bodies(text: str) -> list[SolarBody]:
    """The bodies that ``text`` names exactly or starts to name, the exact one first.

    This is what a search for the text should offer. Typing "mar" finds Mars, and "the sun" finds
    the Sun, but two letters find nothing: too many things start with them.
    """
    wanted = _normalised(text)
    exact = find_solar_body(text)
    found = [exact] if exact else []
    if len(wanted) >= MIN_PREFIX_CHARS:
        found += [
            body
            for body in SOLAR_BODIES
            if body not in found
            and any(_normalised(name).startswith(wanted) for name in (body.name, *body.other_names))
        ]
    return found


def solar_name_forms(body: SolarBody) -> tuple[str, ...]:
    """Every name of ``body`` in the plain form that ``find_solar_body`` compares, for scoring
    did-you-mean guesses."""
    names = (body.name, *body.other_names, *body.exact_names)
    return tuple(dict.fromkeys(_normalised(name) for name in names))


def is_earth(text: str) -> bool:
    """True when ``text`` names the Earth, which is where every light starts, not a place."""
    return _normalised(text) in _EARTH_NAMES


def solar_body(body_id: str, now_year: DecimalYear) -> VantagePoint | None:
    """The place for a solar system body on the date ``now_year``, or ``None`` for another id.

    Outside 1800 to 2050 AD, where the orbit formulas are not valid, the best estimate is the
    middle of the range and the ``distance_source`` fact says so.
    """
    body = _BY_ID.get(body_id)
    if body is None:
        return None
    facts: dict[str, FactValue]
    if body.id == "moon":
        low_au, best_au, high_au = (
            km_to_au(MOON_NEAREST_KM),
            km_to_au(MOON_MEAN_KM),
            km_to_au(MOON_FARTHEST_KM),
        )
        facts = {
            "distance_source": "nasa_moon_fact_sheet",
            "distance_au": round(best_au, 5),
            "mean_distance_km": round(MOON_MEAN_KM),
        }
    elif not TABLE_FIRST_MOMENT <= now_year < TABLE_END_MOMENT:
        low_au, high_au = _bounds_outside_table(body)
        best_au = (low_au + high_au) / 2
        facts = {"distance_source": ORBIT_RANGE_MIDPOINT}
    else:
        if body.id == "sun":
            low_au, high_au = earth_sun_distance_bounds_au(now_year)
            best_au = earth_sun_distance_au(now_year)
        else:
            planet = _PLANET_BY_ID[body.id]
            low_au, high_au = planet_distance_bounds_au(planet, now_year)
            best_au = planet_distance_au(planet, now_year)
        facts = {
            "distance_source": "jpl_approximate_elements",
            "distance_au": round(best_au, 4),
        }
    return VantagePoint(
        id=body.id,
        name=body.name,
        kind=body.kind,
        lookback=LookbackRange(
            au_to_light_years(low_au), au_to_light_years(best_au), au_to_light_years(high_au)
        ),
        fame=body.fame,
        wikipedia=body.wikipedia,
        facts=facts,
    )


_ORBIT_SIZE_MOMENT = 2000.0
"""The date whose orbit sizes stand in for dates outside 1800 to 2050 AD. Orbit sizes change
by parts per million per century, so it is a sound stand-in; only the place on the orbit is
unknown."""


def _bounds_outside_table(body: SolarBody) -> tuple[float, float]:
    """Range for a date the orbit formulas do not cover, from the orbit sizes at J2000."""
    if body.id == "sun":
        return earth_sun_distance_bounds_au(_ORBIT_SIZE_MOMENT)
    return planet_distance_bounds_au(_PLANET_BY_ID[body.id], _ORBIT_SIZE_MOMENT)
