"""The Sun, the Moon, and the seven other planets as places you can look from.

Every other place has a distance that does not change, so it is stored once in the database. These
bodies are close enough that their distance from Earth changes from day to day, so their
lookback is worked out for the date asked about and nothing is stored.

The lookback range is how far apart the two bodies can ever be (the planets: from the sizes of the
two orbits; the Sun: perihelion to aphelion; the Moon: NASA's quoted range), and the best estimate
is the distance on the date. See ``docs/data-sources.md`` for where each number comes from.
"""

import re
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


@dataclass(frozen=True)
class SolarBody:
    """One body of the solar system that can be looked from."""

    id: str
    name: str
    kind: VantageKind
    fame: int
    wikipedia: str
    description: str
    other_names: tuple[str, ...] = ()


SOLAR_BODIES: Final[tuple[SolarBody, ...]] = (
    SolarBody("sun", "Sun", VantageKind.STAR, 5, "Sun", "The star at the centre", ("Sol",)),
    SolarBody("moon", "Moon", VantageKind.MOON, 5, "Moon", "Earth's natural satellite", ("Luna",)),
    SolarBody("mercury", "Mercury", VantageKind.PLANET, 3, "Mercury (planet)", "Planet", ()),
    SolarBody("venus", "Venus", VantageKind.PLANET, 4, "Venus", "Planet", ()),
    SolarBody("mars", "Mars", VantageKind.PLANET, 4, "Mars", "Planet", ()),
    SolarBody("jupiter", "Jupiter", VantageKind.PLANET, 4, "Jupiter", "Planet", ()),
    SolarBody("saturn", "Saturn", VantageKind.PLANET, 4, "Saturn", "Planet", ()),
    SolarBody("uranus", "Uranus", VantageKind.PLANET, 3, "Uranus", "Planet", ()),
    SolarBody("neptune", "Neptune", VantageKind.PLANET, 3, "Neptune", "Planet", ()),
)

SOLAR_BODY_IDS: Final[tuple[str, ...]] = tuple(body.id for body in SOLAR_BODIES)
PLANET_IDS: Final[tuple[str, ...]] = tuple(
    body.id for body in SOLAR_BODIES if body.kind is VantageKind.PLANET
)

_ORBIT_SIZE_MOMENT = 2000.0
"""The date whose orbit sizes stand in for dates outside 1800 to 2050 AD. Orbit sizes change
by parts per million per century, so it is a sound stand-in; only the place on the orbit is
unknown."""

_EARTH_NAMES = frozenset({"earth", "planet earth"})
_BY_NAME: Final[dict[str, SolarBody]] = {
    name.casefold(): body
    for body in SOLAR_BODIES
    for name in (body.id, body.name, *body.other_names)
} | {
    "earth's moon": SOLAR_BODIES[1],
    "earths moon": SOLAR_BODIES[1],
}


def _normalised(text: str) -> str:
    """Lower case with spaces tidied and a leading "the " dropped ("The Sun" is "sun")."""
    cleaned = " ".join(text.casefold().split())
    return re.sub(r"^the ", "", cleaned)


def find_solar_body(text: str) -> SolarBody | None:
    """The body that ``text`` names exactly (ignoring case and a leading "the"), if any."""
    return _BY_NAME.get(_normalised(text))


def is_earth(text: str) -> bool:
    """True when ``text`` names the Earth, which is where every light starts, not a place."""
    return _normalised(text) in _EARTH_NAMES


def solar_body_names() -> list[str]:
    """Every name and other name, for did-you-mean guesses."""
    return [name for body in SOLAR_BODIES for name in (body.name, *body.other_names)]


def solar_body(body_id: str, now_year: DecimalYear) -> VantagePoint | None:
    """The place for a solar system body on the date ``now_year``, or ``None`` for another id.

    Outside 1800 to 2050 AD, where the orbit formulas are not valid, the best estimate is the
    middle of the range and the ``distance_source`` fact says so.
    """
    body = next((b for b in SOLAR_BODIES if b.id == body_id), None)
    if body is None:
        return None
    facts: dict[str, FactValue]
    in_table = TABLE_FIRST_MOMENT <= now_year < TABLE_END_MOMENT
    if body.id == "moon":
        low_au, best_au, high_au = (
            km_to_au(MOON_NEAREST_KM),
            km_to_au(MOON_MEAN_KM),
            km_to_au(MOON_FARTHEST_KM),
        )
        facts = {"distance_source": "nasa_moon_fact_sheet", "mean_distance_km": MOON_MEAN_KM}
    elif not in_table:
        low_au, high_au = _bounds_outside_table(body)
        best_au = (low_au + high_au) / 2
        facts = {"distance_source": "orbit_range_midpoint"}
    else:
        if body.id == "sun":
            low_au, high_au = earth_sun_distance_bounds_au(now_year)
            best_au = earth_sun_distance_au(now_year)
        else:
            planet = _as_planet(body.id)
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


def _as_planet(body_id: str) -> Planet:
    for planet in PLANETS:
        if planet == body_id:
            return planet
    raise ValueError(f"{body_id!r} is not a planet")


def _bounds_outside_table(body: SolarBody) -> tuple[float, float]:
    """Range for a date the orbit formulas do not cover, from the orbit sizes at J2000."""
    if body.id == "sun":
        return earth_sun_distance_bounds_au(_ORBIT_SIZE_MOMENT)
    return planet_distance_bounds_au(_as_planet(body.id), _ORBIT_SIZE_MOMENT)
