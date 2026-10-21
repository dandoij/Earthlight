"""Turn the NASA Exoplanet Archive into Earthlight exoplanet vantage points.

Pure logic like ``stars.py``: it reads files that ``sources.py`` has downloaded and builds
``VantagePoint`` objects plus the typed details for the ``exoplanets`` table. The rules come
from the findings in ``docs/data-sources.md`` (steps 2.2 and 2.5):

* A planet's distance is the archive's ``sy_dist`` with its asymmetric error bounds. Where
  the archive has no distance, or no error bounds, the host star's Bailer-Jones distance
  range is used instead. A planet with neither is left out, because a range of zero width
  would make it look perfectly precise.
* A planet is linked to its host star (``host_id``) when that star is in the database,
  through its Hipparcos number or its Gaia source id.
"""

import csv
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import ValidationError

from earthlight.lookback import LookbackRange, parsecs_to_light_years
from earthlight.models import FactValue, VantageKind, VantagePoint
from earthlight_pipeline.parsing import integer as _integer
from earthlight_pipeline.parsing import number as _number
from earthlight_pipeline.parsing import positive as _positive
from earthlight_pipeline.parsing import prefixed_integer as _prefixed_integer
from earthlight_pipeline.parsing import words as _words
from earthlight_pipeline.stars import GaiaMatch, SearchEntry, constellation_names

PlanetDistanceSource = Literal["exoplanet_archive", "bailer_jones_host"]

NEARBY_LIGHT_YEARS = 12.0
"""Planets this close are treated as notable, however little is known about them."""

FAMOUS_EXOPLANETS: dict[str, int] = {
    "51 Peg b": 4,  # the first planet found around a Sun-like star (1995)
    "HD 209458 b": 4,  # the first planet seen crossing its star
    "Proxima Cen b": 4,  # a planet at the nearest star to the Sun
    "TRAPPIST-1 e": 4,  # one of seven planets in a famous nearby system
    "Kepler-22 b": 3,  # an early planet in a habitable-zone orbit
}
"""Editorial fame scores for a few well-known planets, by archive name."""

_MAX_ID_LENGTH = 100


# --- reading the files -----------------------------------------------------------------------


@dataclass(frozen=True)
class ArchivePlanet:
    """One planet from the archive's default parameter set. Missing values are None."""

    name: str
    host_name: str
    controversial: bool
    distance_pc: float | None
    error_upper_pc: float | None
    error_lower_pc: float | None
    vmag: float | None
    ra_deg: float | None
    dec_deg: float | None
    gaia_host_id: int | None
    hip: int | None
    discovery_year: int | None
    discovery_method: str | None
    planets_in_system: int | None
    radius_earth: float | None
    mass_earth: float | None
    orbital_period_days: float | None


def read_archive(csv_path: Path) -> list[ArchivePlanet]:
    """Read the downloaded Planetary Systems table."""
    planets: list[ArchivePlanet] = []
    with csv_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = _words(row["pl_name"])
            host = _words(row["hostname"])
            if not name or not host:
                continue
            planets.append(
                ArchivePlanet(
                    name=name,
                    host_name=host,
                    controversial=_words(row["pl_controv_flag"]) == "1",
                    distance_pc=_positive(row["sy_dist"]),
                    error_upper_pc=_number(row["sy_disterr1"]),
                    error_lower_pc=_number(row["sy_disterr2"]),
                    vmag=_number(row["sy_vmag"]),
                    ra_deg=_number(row["ra"]),
                    dec_deg=_number(row["dec"]),
                    gaia_host_id=_prefixed_integer(row["gaia_dr3_id"], "Gaia DR3 "),
                    hip=_prefixed_integer(row["hip_name"], "HIP "),
                    discovery_year=_integer(row["disc_year"]),
                    discovery_method=_words(row["discoverymethod"]) or None,
                    planets_in_system=_integer(row["sy_pnum"]),
                    radius_earth=_positive(row["pl_rade"]),
                    mass_earth=_positive(row["pl_bmasse"]),
                    orbital_period_days=_positive(row["pl_orbper"]),
                )
            )
    return planets


def read_host_distances(paths: Iterable[Path]) -> dict[int, tuple[float, float, float]]:
    """Bailer-Jones (16th percentile, median, 84th percentile) distances in parsecs, by Gaia id."""
    distances: dict[int, tuple[float, float, float]] = {}
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                source_id = _integer(row["source_id"])
                low, median, high = (_number(row[k]) for k in ("r_lo_geo", "r_med_geo", "r_hi_geo"))
                if (
                    source_id is not None
                    and low is not None
                    and median is not None
                    and high is not None
                ):
                    distances[source_id] = (low, median, high)
    return distances


# --- which stars and distances we need -------------------------------------------------------


def archive_range(planet: ArchivePlanet) -> LookbackRange | None:
    """The planet's lookback range from the archive's own distance and error bounds, or None
    if it has no distance, is missing a bound, or the bounds are not usable."""
    best, upper, lower = planet.distance_pc, planet.error_upper_pc, planet.error_lower_pc
    if best is None or upper is None or lower is None or upper < 0 or lower > 0:
        return None
    low = best + lower
    if low <= 0:
        return None
    return LookbackRange(
        parsecs_to_light_years(low),
        parsecs_to_light_years(best),
        parsecs_to_light_years(best + upper),
    )


def host_gaia_ids_needed(planets: Iterable[ArchivePlanet]) -> list[int]:
    """Gaia ids of hosts whose Bailer-Jones distance is needed: planets that have no usable
    archive range. Sorted and without duplicates."""
    return sorted(
        {
            planet.gaia_host_id
            for planet in planets
            if planet.gaia_host_id is not None and archive_range(planet) is None
        }
    )


def exoplanet_host_hips(
    planets: Iterable[ArchivePlanet], gaia_matches: Mapping[int, GaiaMatch]
) -> set[int]:
    """Hipparcos numbers of stars that host planets, by the archive's HIP name or by a Gaia id
    that the Gaia cross-match ties to a Hipparcos star."""
    by_gaia = {match.source_id: hip for hip, match in gaia_matches.items()}
    hips: set[int] = set()
    for planet in planets:
        if planet.hip is not None:
            hips.add(planet.hip)
        if planet.gaia_host_id is not None and planet.gaia_host_id in by_gaia:
            hips.add(by_gaia[planet.gaia_host_id])
    return hips


# --- building --------------------------------------------------------------------------------


class SkipPlanet(Exception):
    """A planet cannot be built. ``reason`` is a short code that is counted in the report."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class StarIndex:
    """The stars already in the database, for linking planets to their hosts."""

    by_hip: Mapping[int, str]
    by_gaia_id: Mapping[int, str]

    @classmethod
    def from_stars(cls, stars: Iterable[VantagePoint]) -> Self:
        by_hip: dict[int, str] = {}
        by_gaia: dict[int, str] = {}
        for star in stars:
            hip = star.facts.get("hip")
            if isinstance(hip, int):
                by_hip[hip] = star.id
            gaia = star.facts.get("gaia_dr3_source_id")
            if isinstance(gaia, str) and gaia.isdigit():
                by_gaia[int(gaia)] = star.id
        return cls(by_hip, by_gaia)

    def host_of(self, planet: ArchivePlanet) -> str | None:
        """The id of the planet's host star, if that star is in the database."""
        if planet.hip is not None and planet.hip in self.by_hip:
            return self.by_hip[planet.hip]
        if planet.gaia_host_id is not None:
            return self.by_gaia_id.get(planet.gaia_host_id)
        return None


@dataclass(frozen=True)
class ExoplanetDetails:
    """The typed columns of the ``exoplanets`` table for one planet."""

    vantage_id: str
    nasa_name: str
    host_name: str
    discovery_year: int | None
    discovery_method: str | None
    radius_earth: float | None
    mass_earth: float | None
    orbital_period_days: float | None
    controversial: bool


@dataclass(frozen=True)
class ExoplanetRecord:
    """A planet as a vantage point, with its table details and its search entry."""

    point: VantagePoint
    details: ExoplanetDetails
    search: SearchEntry


@dataclass
class ExoplanetBuild:
    """The result of building planets: the planets, and how many were left out and why."""

    records: list[ExoplanetRecord]
    skipped: Counter[str]
    sources: Counter[str]
    linked: int


def slugify(name: str) -> str:
    """A lowercase hyphenated id for a planet name: "Teegarden's Star d" is "teegarden-s-star-d"."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:_MAX_ID_LENGTH].rstrip("-")


def choose_planet_distance(
    planet: ArchivePlanet, host_distances: Mapping[int, tuple[float, float, float]]
) -> tuple[LookbackRange, PlanetDistanceSource]:
    """The archive's own range if it is complete, otherwise the host star's Bailer-Jones range.

    Raises SkipPlanet if neither exists.
    """
    own = archive_range(planet)
    if own is not None:
        return own, "exoplanet_archive"
    if planet.gaia_host_id is not None:
        host = host_distances.get(planet.gaia_host_id)
        if host is not None:
            low, median, high = host
            if 0 < low <= median <= high:
                return (
                    LookbackRange(
                        parsecs_to_light_years(low),
                        parsecs_to_light_years(median),
                        parsecs_to_light_years(high),
                    ),
                    "bailer_jones_host",
                )
    raise SkipPlanet("no_distance" if planet.distance_pc is None else "no_distance_error")


def fame_for_planet(name: str, light_years: float) -> int:
    """Fame from 0 to 5. An editorial rule: a short list of well-known planets, and any planet
    within 12 light-years scores at least 3."""
    score = FAMOUS_EXOPLANETS.get(name, 0)
    if light_years <= NEARBY_LIGHT_YEARS:
        score = max(score, 3)
    return score


def build_exoplanets(
    planets: Iterable[ArchivePlanet],
    host_distances: Mapping[int, tuple[float, float, float]],
    stars: StarIndex,
) -> ExoplanetBuild:
    """Build a vantage point for every planet that has a usable distance and position."""
    skipped: Counter[str] = Counter()
    chosen: list[tuple[ArchivePlanet, LookbackRange, PlanetDistanceSource, str]] = []
    seen_ids: set[str] = set()
    for planet in planets:
        if planet.ra_deg is None or planet.dec_deg is None:
            skipped["no_position"] += 1
            continue
        if not (0.0 <= planet.ra_deg <= 360.0 and -90.0 <= planet.dec_deg <= 90.0):
            skipped["invalid_position"] += 1  # astropy raises for a whole batch otherwise
            continue
        try:
            lookback, source = choose_planet_distance(planet, host_distances)
        except SkipPlanet as why:
            skipped[why.reason] += 1
            continue
        planet_id = slugify(planet.name)
        if not planet_id or planet_id in seen_ids:
            skipped["duplicate_id"] += 1
            continue
        seen_ids.add(planet_id)
        chosen.append((planet, lookback, source, planet_id))

    constellations = constellation_names(
        [p.ra_deg % 360.0 for p, *_ in chosen if p.ra_deg is not None],
        [p.dec_deg for p, *_ in chosen if p.dec_deg is not None],
    )
    records: list[ExoplanetRecord] = []
    sources: Counter[str] = Counter()
    linked = 0
    for (planet, lookback, source, planet_id), constellation in zip(
        chosen, constellations, strict=True
    ):
        host_id = stars.host_of(planet)
        try:
            point = _vantage_point(planet, planet_id, lookback, source, constellation, host_id)
        except ValidationError:
            skipped["invalid"] += 1
            continue
        records.append(
            ExoplanetRecord(point, _details(planet, planet_id), _search_entry(planet, planet_id))
        )
        sources[source] += 1
        linked += host_id is not None
    return ExoplanetBuild(records=records, skipped=skipped, sources=sources, linked=linked)


def _vantage_point(
    planet: ArchivePlanet,
    planet_id: str,
    lookback: LookbackRange,
    source: PlanetDistanceSource,
    constellation: str,
    host_id: str | None,
) -> VantagePoint:
    facts: dict[str, FactValue] = {"distance_source": source}
    if planet.planets_in_system is not None:
        facts["planets_in_system"] = planet.planets_in_system
    if planet.gaia_host_id is not None:
        facts["gaia_dr3_host_id"] = str(planet.gaia_host_id)  # too large for a JSON number
    assert planet.ra_deg is not None and planet.dec_deg is not None  # checked by the caller
    return VantagePoint(
        id=planet_id,
        name=planet.name,
        kind=VantageKind.EXOPLANET,
        lookback=lookback,
        magnitude=planet.vmag,
        constellation=constellation,
        ra_deg=planet.ra_deg % 360.0,
        dec_deg=planet.dec_deg,
        fame=fame_for_planet(planet.name, lookback.best),
        host_id=host_id,
        facts=facts,
    )


def _details(planet: ArchivePlanet, planet_id: str) -> ExoplanetDetails:
    return ExoplanetDetails(
        vantage_id=planet_id,
        nasa_name=planet.name,
        host_name=planet.host_name,
        discovery_year=planet.discovery_year,
        discovery_method=planet.discovery_method,
        radius_earth=planet.radius_earth,
        mass_earth=planet.mass_earth,
        orbital_period_days=planet.orbital_period_days,
        controversial=planet.controversial,
    )


def _search_entry(planet: ArchivePlanet, planet_id: str) -> SearchEntry:
    """Every planet is searchable by name, host name, and the host's HIP name."""
    aliases = [planet.host_name]
    if planet.hip is not None:
        aliases.append(f"HIP {planet.hip}")
    return SearchEntry(
        type="vantage_point",
        id=planet_id,
        name=planet.name,
        aliases="\n".join(aliases),
        description=f"Exoplanet orbiting {planet.host_name}",
    )
