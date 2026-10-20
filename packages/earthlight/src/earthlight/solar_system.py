"""The nearby universe: planets, Voyager 1, and the zones beyond the planets.

Everything here is for lookbacks from about a second to a few years, where light
is crossing the solar system and the space just beyond it. See ``docs/data-sources.md``
for where each number comes from.

Planets
    Positions use the approximate Keplerian elements and rates from Table 1 of
    "Approximate Positions of the Planets" (NASA JPL Solar System Dynamics,
    https://ssd.jpl.nasa.gov/planets/approx_pos.html), valid for 1800 AD to 2050 AD,
    with the page's step-by-step algorithm. The Earth is represented by the
    Earth-Moon barycenter, as the page does; the Earth sits within about 4700 km of
    it, which is far below the accuracy of the method.

Voyager 1
    A straight-line model of its distance from the Sun, fitted to JPL Horizons
    positions. It is accurate to about 0.2 AU between 2012 and 2035.

Zones
    Distance bands from the Sun out to Proxima Centauri. Their edges are
    conventional, not sharp: the heliopause moves with the solar cycle, and
    published Oort Cloud boundaries disagree by large factors.
"""

import math
from dataclasses import dataclass
from typing import Literal, get_args

from earthlight.lookback import (
    ASTRONOMICAL_UNIT_M,
    LIGHT_YEAR_M,
    PARSEC_M,
    LookbackRange,
)
from earthlight.time import DecimalYear, days_in_year

SPEED_OF_LIGHT_M_PER_S = 299_792_458
"""Exact, by the definition of the metre."""

AU_IN_LIGHT_YEARS = ASTRONOMICAL_UNIT_M / LIGHT_YEAR_M
"""About 1.58e-5 light-years per astronomical unit."""

AU_LIGHT_TIME_SECONDS = ASTRONOMICAL_UNIT_M / SPEED_OF_LIGHT_M_PER_S
"""Light takes about 499 seconds to cross one astronomical unit."""

Planet = Literal["mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune"]
PLANETS: tuple[Planet, ...] = get_args(Planet)

TABLE_FIRST_MOMENT = 1800.0
"""Start of the interval over which JPL's Table 1 elements were fitted (1800 AD)."""

TABLE_END_MOMENT = 2051.0
"""End of that interval, exclusive (it runs to the end of 2050 AD)."""

_JD_J2000 = 2451545.0
_DAYS_PER_CENTURY = 36525.0


def au_to_light_years(distance_au: float) -> float:
    """Convert astronomical units to light-years (which equals years of lookback)."""
    return distance_au * AU_IN_LIGHT_YEARS


def light_time_seconds(distance_au: float) -> float:
    """Seconds light takes to travel ``distance_au`` astronomical units."""
    return distance_au * AU_LIGHT_TIME_SECONDS


# --- planets -------------------------------------------------------------------


@dataclass(frozen=True)
class _Elements:
    """Keplerian elements at J2000 and their rates per Julian century (JPL Table 1).

    Distances in au, angles in degrees (eccentricity is dimensionless).
    """

    a: float
    a_rate: float
    e: float
    e_rate: float
    inclination: float
    inclination_rate: float
    mean_longitude: float
    mean_longitude_rate: float
    perihelion_longitude: float
    perihelion_longitude_rate: float
    node_longitude: float
    node_longitude_rate: float


# Copied from Table 1 of https://ssd.jpl.nasa.gov/planets/approx_pos.html (retrieved
# 2026-10-20). "earth" is the page's "EM Bary" row (Earth-Moon barycenter).
_ELEMENTS: dict[str, _Elements] = {
    "mercury": _Elements(
        0.38709927, 0.00000037, 0.20563593, 0.00001906, 7.00497902, -0.00594749,
        252.25032350, 149472.67411175, 77.45779628, 0.16047689, 48.33076593, -0.12534081,
    ),
    "venus": _Elements(
        0.72333566, 0.00000390, 0.00677672, -0.00004107, 3.39467605, -0.00078890,
        181.97909950, 58517.81538729, 131.60246718, 0.00268329, 76.67984255, -0.27769418,
    ),
    "earth": _Elements(
        1.00000261, 0.00000562, 0.01671123, -0.00004392, -0.00001531, -0.01294668,
        100.46457166, 35999.37244981, 102.93768193, 0.32327364, 0.0, 0.0,
    ),
    "mars": _Elements(
        1.52371034, 0.00001847, 0.09339410, 0.00007882, 1.84969142, -0.00813131,
        -4.55343205, 19140.30268499, -23.94362959, 0.44441088, 49.55953891, -0.29257343,
    ),
    "jupiter": _Elements(
        5.20288700, -0.00011607, 0.04838624, -0.00013253, 1.30439695, -0.00183714,
        34.39644051, 3034.74612775, 14.72847983, 0.21252668, 100.47390909, 0.20469106,
    ),
    "saturn": _Elements(
        9.53667594, -0.00125060, 0.05386179, -0.00050991, 2.48599187, 0.00193609,
        49.95424423, 1222.49362201, 92.59887831, -0.41897216, 113.66242448, -0.28867794,
    ),
    "uranus": _Elements(
        19.18916464, -0.00196176, 0.04725744, -0.00004397, 0.77263783, -0.00242939,
        313.23810451, 428.48202785, 170.95427630, 0.40805281, 74.01692503, 0.04240589,
    ),
    "neptune": _Elements(
        30.06992276, 0.00026291, 0.00859048, 0.00005105, 1.77004347, 0.00035372,
        -55.12002969, 218.45945325, 44.96476227, -0.32241464, 131.78422574, -0.00508664,
    ),
}  # fmt: skip


def julian_date(moment: DecimalYear) -> float:
    """Julian date of a moment in the proleptic Gregorian calendar (valid from year 1)."""
    year = math.floor(moment)
    # Meeus, "Astronomical Algorithms", ch. 7, for midnight on 1 January of `year`.
    prior = year - 1
    century = prior // 100
    gregorian_correction = 2 - century + century // 4
    start_of_year = (
        math.floor(365.25 * (prior + 4716))
        + math.floor(30.6001 * 14)
        + 1
        + gregorian_correction
        - 1524.5
    )
    return start_of_year + (moment - year) * days_in_year(year)


def _solve_kepler(mean_anomaly: float, eccentricity: float) -> float:
    """Solve M = E - e sin E for E (radians), by the iteration given on the JPL page."""
    m = math.remainder(mean_anomaly, math.tau)
    eccentric = m + eccentricity * math.sin(m)
    for _ in range(50):
        delta_m = m - (eccentric - eccentricity * math.sin(eccentric))
        delta_e = delta_m / (1 - eccentricity * math.cos(eccentric))
        eccentric += delta_e
        if abs(delta_e) < 1e-12:
            return eccentric
    raise ArithmeticError("Kepler's equation did not converge")


def _heliocentric_au(elements: _Elements, centuries: float) -> tuple[float, float, float]:
    """Position in the J2000 ecliptic frame, in au, relative to the Sun."""
    t = centuries
    a = elements.a + elements.a_rate * t
    e = elements.e + elements.e_rate * t
    inclination = math.radians(elements.inclination + elements.inclination_rate * t)
    perihelion = elements.perihelion_longitude + elements.perihelion_longitude_rate * t
    node = math.radians(elements.node_longitude + elements.node_longitude_rate * t)
    mean_longitude = elements.mean_longitude + elements.mean_longitude_rate * t

    argument = math.radians(perihelion) - node
    eccentric = _solve_kepler(math.radians(mean_longitude - perihelion), e)

    x_orbit = a * (math.cos(eccentric) - e)
    y_orbit = a * math.sqrt(1 - e * e) * math.sin(eccentric)

    cos_w, sin_w = math.cos(argument), math.sin(argument)
    cos_n, sin_n = math.cos(node), math.sin(node)
    cos_i, sin_i = math.cos(inclination), math.sin(inclination)
    x = (cos_w * cos_n - sin_w * sin_n * cos_i) * x_orbit + (
        -sin_w * cos_n - cos_w * sin_n * cos_i
    ) * y_orbit
    y = (cos_w * sin_n + sin_w * cos_n * cos_i) * x_orbit + (
        -sin_w * sin_n + cos_w * cos_n * cos_i
    ) * y_orbit
    z = (sin_w * sin_i) * x_orbit + (cos_w * sin_i) * y_orbit
    return x, y, z


def planet_position_au(planet: Planet, moment: DecimalYear) -> tuple[float, float, float]:
    """Vector from Earth to ``planet`` at ``moment``, in astronomical units.

    The frame is the mean ecliptic and equinox of J2000: x points to the March
    equinox of J2000, z to the north ecliptic pole. The moment is treated as
    Terrestrial/Dynamical time; the difference from UTC (about a minute) is far below
    the accuracy of the method. Accuracy is set by JPL's published errors for these
    elements: a few thousand km for Mercury and Venus, tens of thousands for Mars, and
    up to a few million km for Jupiter through Neptune (their orbits are fitted about
    the solar system's barycenter, so using them from the Sun adds the Sun's wobble).

    Raises ValueError for a moment outside 1800 AD to 2050 AD, where the elements
    are not valid.
    """
    if not TABLE_FIRST_MOMENT <= moment < TABLE_END_MOMENT:
        raise ValueError(
            f"planet positions are only available from 1800 to 2050 AD, got {moment:.2f}"
        )
    centuries = (julian_date(moment) - _JD_J2000) / _DAYS_PER_CENTURY
    ex, ey, ez = _heliocentric_au(_ELEMENTS["earth"], centuries)
    px, py, pz = _heliocentric_au(_ELEMENTS[planet], centuries)
    return px - ex, py - ey, pz - ez


def planet_distance_au(planet: Planet, moment: DecimalYear) -> float:
    """Distance from Earth to ``planet`` at ``moment``, in astronomical units.

    Same accuracy and range as ``planet_position_au``, which raises ValueError for a
    moment outside 1800 AD to 2050 AD.
    """
    return math.hypot(*planet_position_au(planet, moment))


# --- Voyager 1 -------------------------------------------------------------------

# Distance from the Sun, from JPL Horizons (target -31, center 500@10, geometric
# vectors, retrieved 2026-10-20): 169.255256 au on 2026-01-01 and 183.495820 au on
# 2030-01-01, four years apart.
_VOYAGER1_ANCHOR_MOMENT = 2026.0
_VOYAGER1_ANCHOR_AU = 169.255256
_VOYAGER1_SPEED_AU_PER_YEAR = (183.495820 - 169.255256) / 4.0

VOYAGER1_FIRST_MOMENT = 2012.0
VOYAGER1_LAST_MOMENT = 2035.0


def voyager1_distance_au(moment: DecimalYear) -> float:
    """Approximate distance of Voyager 1 from the Sun, in astronomical units.

    This is a straight-line fit, accurate to about 0.2 AU between 2012 and 2035. The
    distance from *Earth* differs from this by up to 1 au (Earth's orbit), under
    1 percent. Raises ValueError outside 2012 to 2035.
    """
    if not VOYAGER1_FIRST_MOMENT <= moment <= VOYAGER1_LAST_MOMENT:
        raise ValueError(f"Voyager 1 distance is only modelled for 2012 to 2035, got {moment:.2f}")
    return _VOYAGER1_ANCHOR_AU + _VOYAGER1_SPEED_AU_PER_YEAR * (moment - _VOYAGER1_ANCHOR_MOMENT)


# --- zones -------------------------------------------------------------------------

HELIOPAUSE_AU = 121.6
"""Voyager 1 left the heliosphere on 25 August 2012 (NASA); JPL Horizons puts it
121.6 au from the Sun then. The boundary varies with direction and the solar cycle."""

INNER_OORT_CLOUD_AU = 2_000.0
OUTER_OORT_CLOUD_AU = 20_000.0
OORT_CLOUD_END_AU = 100_000.0
"""Conventional, approximate Oort Cloud boundaries. Published values differ by large
factors (inner edge 250 to 5000 au, outer edge 50000 to 200000 au); these are the
commonly quoted middle values, chosen with the project owner."""

PROXIMA_CENTAURI_DISTANCE_PC = 1.30119
"""Distance to Proxima Centauri in parsecs: ``sy_dist`` for the host star in the NASA
Exoplanet Archive, retrieved 2026-10-20."""

PROXIMA_CENTAURI_AU = PROXIMA_CENTAURI_DISTANCE_PC * PARSEC_M / ASTRONOMICAL_UNIT_M
"""About 268,000 au, or 4.24 light-years."""


@dataclass(frozen=True)
class Zone:
    """A band of distance from the Sun, with an id that is stable across releases."""

    id: str
    name: str
    inner_au: float
    outer_au: float
    description: str

    @property
    def lookback_range(self) -> LookbackRange:
        """Years of lookback across the zone. ``best`` is the midpoint, which is only a
        placeholder: the zones span orders of magnitude and have no single typical value."""
        inner = au_to_light_years(self.inner_au)
        outer = au_to_light_years(self.outer_au)
        return LookbackRange(minimum=inner, best=(inner + outer) / 2, maximum=outer)


ZONES: tuple[Zone, ...] = (
    Zone(
        "heliosphere",
        "Inside the heliosphere",
        0.0,
        HELIOPAUSE_AU,
        "The bubble of solar wind around the Sun, from the planets out to the heliopause.",
    ),
    Zone(
        "beyond-heliopause",
        "Beyond the heliopause",
        HELIOPAUSE_AU,
        INNER_OORT_CLOUD_AU,
        "Interstellar space still firmly inside the Sun's gravity, before the Oort Cloud.",
    ),
    Zone(
        "inner-oort-cloud",
        "Inner Oort Cloud",
        INNER_OORT_CLOUD_AU,
        OUTER_OORT_CLOUD_AU,
        "The dense inner part of the shell of icy bodies that surrounds the Sun.",
    ),
    Zone(
        "outer-oort-cloud",
        "Outer Oort Cloud",
        OUTER_OORT_CLOUD_AU,
        OORT_CLOUD_END_AU,
        "The sparse outer part of that shell, where passing stars can nudge comets inward.",
    ),
    Zone(
        "interstellar-space",
        "Interstellar space",
        OORT_CLOUD_END_AU,
        PROXIMA_CENTAURI_AU,
        "The gap between the Sun's own surroundings and the nearest star, Proxima Centauri.",
    ),
)


def zone_for_lookback(lookback_years: float) -> Zone | None:
    """Return the zone whose light-travel distance contains ``lookback_years``.

    Each zone includes its inner edge and excludes its outer edge, except that the
    last zone includes Proxima Centauri's distance. Returns None for a negative
    lookback or one beyond Proxima Centauri (where stars take over).
    """
    for index, zone in enumerate(ZONES):
        inner = au_to_light_years(zone.inner_au)
        outer = au_to_light_years(zone.outer_au)
        is_last = index == len(ZONES) - 1
        if inner <= lookback_years < outer or (is_last and lookback_years == outer):
            return zone
    return None
