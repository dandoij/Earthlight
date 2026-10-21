"""Turn downloaded Hipparcos, Gaia, and IAU data into Earthlight star vantage points.

This module is pure logic: it reads files that ``sources.py`` has already downloaded and
builds ``VantagePoint`` objects. It never touches the network or the database, so every rule
here can be tested on small fixtures. The rules come from the decisions in
``docs/data-sources.md`` (step 2.2):

* The star universe is the Hipparcos catalogue.
* A star's distance comes from Gaia DR3 with Bailer-Jones geometric distances when it has a
  Gaia match, and otherwise from the Hipparcos new-reduction parallax. Which one was used is
  recorded in the star's ``distance_source`` fact.
* Proper names come from the IAU Catalog of Star Names, and other stars are named "HIP n".
"""

import csv
import math
import re
from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from earthlight.lookback import (
    LookbackRange,
    lookback_range_from_parallax,
    parsecs_to_light_years,
)
from earthlight.models import FactValue, VantageKind, VantagePoint
from earthlight_pipeline.parsing import integer as _integer
from earthlight_pipeline.parsing import number as _number
from earthlight_pipeline.parsing import words as _words

DistanceSource = Literal["gaia", "hipparcos"]

MIN_HIPPARCOS_PARALLAX_OVER_ERROR = 5.0
"""A Hipparcos parallax must be at least this many times its error. Simple parallax inversion
is only trustworthy for precise parallaxes."""

MIN_NAMED_PARALLAX_OVER_ERROR = 3.0
"""The lower bar for stars that have an IAU name. Famous stars matter more than precision:
Alnilam (3.7) and Aludra (4.1) would otherwise be missing. Their ranges are wide but honest."""

NEARBY_LIGHT_YEARS = 12.0
"""Stars this close are treated as notable, however faint."""

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class SkipStar(Exception):
    """A star cannot be built. ``reason`` is a short code that is counted in the report."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --- reading the downloaded files ------------------------------------------------------------


@dataclass(frozen=True)
class HipparcosStar:
    """One Hipparcos star: position and magnitude from the main catalogue, parallax from the
    new reduction. Any value the catalogues do not have is None."""

    hip: int
    ra_deg: float | None
    dec_deg: float | None
    vmag: float | None
    spectral_type: str | None
    hd: int | None
    parallax_mas: float | None
    parallax_error_mas: float | None


@dataclass(frozen=True)
class GaiaMatch:
    """A Hipparcos star's best match in Gaia DR3, with its Bailer-Jones geometric distance.

    ``geo_distance_pc`` is (16th percentile, median, 84th percentile) in parsecs, or None."""

    hip: int
    source_id: int
    parallax_mas: float | None
    parallax_error_mas: float | None
    geo_distance_pc: tuple[float, float, float] | None


def read_hipparcos(main_csv: Path, parallax_csv: Path) -> list[HipparcosStar]:
    """Join the main catalogue (position, magnitude) and the new reduction (parallax) by HIP."""
    parallaxes: dict[int, tuple[float | None, float | None]] = {}
    with parallax_csv.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            hip = _integer(row["HIP"])
            if hip is not None:
                parallaxes[hip] = (_number(row["Plx"]), _number(row["e_Plx"]))
    stars: list[HipparcosStar] = []
    with main_csv.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            hip = _integer(row["HIP"])
            if hip is None:
                continue
            parallax, error = parallaxes.get(hip, (None, None))
            stars.append(
                HipparcosStar(
                    hip=hip,
                    ra_deg=_number(row["RAICRS"]),
                    dec_deg=_number(row["DEICRS"]),
                    vmag=_number(row["Vmag"]),
                    spectral_type=_words(row["SpType"]) or None,
                    hd=_integer(row["HD"]),
                    parallax_mas=parallax,
                    parallax_error_mas=error,
                )
            )
    return stars


def read_gaia_matches(paths: Iterable[Path]) -> dict[int, GaiaMatch]:
    """Read the Gaia batch files into a dict keyed by Hipparcos number."""
    matches: dict[int, GaiaMatch] = {}
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                hip, source_id = _integer(row["hip"]), _integer(row["source_id"])
                if hip is None or source_id is None:
                    continue
                low = _number(row["r_lo_geo"])
                median = _number(row["r_med_geo"])
                high = _number(row["r_hi_geo"])
                distance = (
                    (low, median, high)
                    if low is not None and median is not None and high is not None
                    else None
                )
                matches[hip] = GaiaMatch(
                    hip=hip,
                    source_id=source_id,
                    parallax_mas=_number(row["parallax"]),
                    parallax_error_mas=_number(row["parallax_error"]),
                    geo_distance_pc=distance,
                )
    return matches


def parse_iau_names(text: str) -> dict[int, str]:
    """Hipparcos number to proper name, from the text of the IAU Catalog of Star Names.

    The name columns are cut out by the header's own column positions (24 names contain a
    space, such as "Alula Australis"), and the Hipparcos number is found relative to the date
    column, because the Greek-letter columns in between do not line up in fixed-width text.
    The name is the diacritic form ("Chason" with a hacek), which is the correct spelling.
    Raises ValueError if the text is not that file.
    """
    lines = text.splitlines()
    header = next((line for line in lines if line.startswith("#Name/ASCII")), None)
    if header is None:
        raise ValueError("this is not the IAU Catalog of Star Names (no header line)")
    header = header[1:]  # data lines have no leading '#', so the columns shift by one
    ascii_end = header.index("Name/Diacritics")
    names_end = header.index("Designation")
    names: dict[int, str] = {}
    for line in lines:
        if not line.strip() or line.startswith(("#", "$")):
            continue
        tokens = line.split()
        date_at = next((i for i, token in enumerate(tokens) if _ISO_DATE.fullmatch(token)), None)
        if date_at is None or date_at < 4:
            continue
        hip = _integer(tokens[date_at - 4])  # then HD, RA, Dec, date
        name = line[ascii_end:names_end].strip() or line[:ascii_end].strip()
        if hip is not None and name:
            names.setdefault(hip, name)
    return names


# --- the rules -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Distance:
    """The distance chosen for a star, and where it came from."""

    lookback: LookbackRange
    source: DistanceSource
    parallax_mas: float | None
    gaia_source_id: int | None


def choose_distance(
    star: HipparcosStar,
    match: GaiaMatch | None,
    *,
    min_parallax_over_error: float = MIN_HIPPARCOS_PARALLAX_OVER_ERROR,
) -> Distance:
    """Pick Gaia with Bailer-Jones if the star has them, otherwise the Hipparcos parallax.

    A Hipparcos parallax must be at least ``min_parallax_over_error`` times its error.
    Raises SkipStar when neither source gives a trustworthy distance.
    """
    if match is not None and match.geo_distance_pc is not None:
        low, median, high = match.geo_distance_pc
        if 0 < low <= median <= high:
            return Distance(
                lookback=LookbackRange(
                    parsecs_to_light_years(low),
                    parsecs_to_light_years(median),
                    parsecs_to_light_years(high),
                ),
                source="gaia",
                parallax_mas=match.parallax_mas,
                gaia_source_id=match.source_id,
            )
    parallax, error = star.parallax_mas, star.parallax_error_mas
    if parallax is None or error is None or error <= 0:
        raise SkipStar("no_parallax")
    if parallax <= 0:
        raise SkipStar("non_positive_parallax")
    if parallax / error < min_parallax_over_error:
        raise SkipStar("parallax_not_precise")
    return Distance(
        lookback=lookback_range_from_parallax(parallax, error),
        source="hipparcos",
        parallax_mas=parallax,
        gaia_source_id=None,
    )


def fame_for(*, has_iau_name: bool, vmag: float | None, light_years: float) -> int:
    """How well known a star is, from 0 (not curated) to 5. An editorial rule, not a measurement.

    A star with an IAU name starts at 2 and rises with brightness: 3 if it is visible to the
    naked eye (V <= 6), 4 if V <= 3, and 5 if V <= 1.5. Any star within 12 light-years
    scores at least 3, so the nearest stars are always kept.
    """
    score = 0
    if has_iau_name:
        score = 2
        if vmag is not None:
            if vmag <= 1.5:
                score = 5
            elif vmag <= 3.0:
                score = 4
            elif vmag <= 6.0:
                score = 3
    if light_years <= NEARBY_LIGHT_YEARS:
        score = max(score, 3)
    return score


_ASTROPY_SPELLING_FIXES = {
    "Chamaleon": "Chamaeleon",
    "Ophiucus": "Ophiuchus",
    "Pisces Austrinus": "Piscis Austrinus",
}
"""Names that astropy's constellation table spells differently from the IAU."""


def constellation_names(ra_deg: Sequence[float], dec_deg: Sequence[float]) -> list[str]:
    """Full IAU constellation names for positions in degrees, using astropy (no download).

    astropy misspells three of the 88 names and pads one with a space; those are corrected.
    """
    if not ra_deg:
        return []
    import astropy.units as u
    from astropy.coordinates import SkyCoord, get_constellation

    coordinates = SkyCoord(ra=list(ra_deg) * u.deg, dec=list(dec_deg) * u.deg, frame="icrs")
    names = (str(name).strip() for name in get_constellation(coordinates))
    return [_ASTROPY_SPELLING_FIXES.get(name, name) for name in names]


# --- building --------------------------------------------------------------------------------


@dataclass
class StarBuild:
    """The result of building stars: the stars, and how many were left out and why."""

    stars: list[VantagePoint]
    skipped: Counter[str]
    sources: Counter[str]


@dataclass(frozen=True)
class _Candidate:
    star: HipparcosStar
    ra: float
    dec: float
    distance: Distance
    name: str
    fame: int


def build_stars(
    hipparcos: Iterable[HipparcosStar],
    matches: dict[int, GaiaMatch],
    iau_names: dict[int, str],
    *,
    max_vmag: float | None = None,
    keep_hips: Collection[int] = (),
) -> StarBuild:
    """Build a vantage point for every usable Hipparcos star.

    Stars fainter than ``max_vmag`` (or with no magnitude) are left out, unless they have a
    fame above 0. Stars in ``keep_hips`` (the hosts of exoplanets) are always kept: they get
    a fame of at least 1, so they are searchable, and the lower precision bar of named stars.
    Everything left out is counted by reason in ``skipped``.
    """
    skipped: Counter[str] = Counter()
    candidates: list[_Candidate] = []
    for star in hipparcos:
        if star.ra_deg is None or star.dec_deg is None:
            skipped["no_position"] += 1
            continue
        if not (math.isfinite(star.ra_deg) and -90.0 <= star.dec_deg <= 90.0):
            # astropy raises for the whole batch on one impossible declination.
            skipped["invalid_position"] += 1
            continue
        iau_name = iau_names.get(star.hip)
        wanted = iau_name is not None or star.hip in keep_hips
        try:
            distance = choose_distance(
                star,
                matches.get(star.hip),
                min_parallax_over_error=(
                    MIN_NAMED_PARALLAX_OVER_ERROR if wanted else MIN_HIPPARCOS_PARALLAX_OVER_ERROR
                ),
            )
        except SkipStar as why:
            skipped[why.reason] += 1
            continue
        fame = fame_for(
            has_iau_name=iau_name is not None,
            vmag=star.vmag,
            light_years=distance.lookback.best,
        )
        if star.hip in keep_hips:
            fame = max(fame, 1)
        if fame == 0 and max_vmag is not None and (star.vmag is None or star.vmag > max_vmag):
            skipped["too_faint"] += 1
            continue
        candidates.append(
            _Candidate(
                star=star,
                ra=star.ra_deg % 360.0,
                dec=star.dec_deg,
                distance=distance,
                name=iau_name or f"HIP {star.hip}",
                fame=fame,
            )
        )

    constellations = constellation_names([c.ra for c in candidates], [c.dec for c in candidates])
    stars: list[VantagePoint] = []
    sources: Counter[str] = Counter()
    for candidate, constellation in zip(candidates, constellations, strict=True):
        try:
            stars.append(_vantage_point(candidate, constellation))
        except ValidationError:
            skipped["invalid"] += 1
            continue
        sources[candidate.distance.source] += 1
    stars.sort(key=lambda s: int(s.id.removeprefix("hip-")))
    return StarBuild(stars=stars, skipped=skipped, sources=sources)


def _vantage_point(candidate: _Candidate, constellation: str) -> VantagePoint:
    star, distance = candidate.star, candidate.distance
    facts: dict[str, FactValue] = {"hip": star.hip, "distance_source": distance.source}
    if star.hd is not None:
        facts["hd"] = star.hd
    if star.spectral_type:
        facts["spectral_type"] = star.spectral_type
    if distance.parallax_mas is not None:
        facts["parallax_mas"] = round(distance.parallax_mas, 4)
    if distance.gaia_source_id is not None:
        facts["gaia_dr3_source_id"] = str(distance.gaia_source_id)  # too large for a JSON number
    return VantagePoint(
        id=f"hip-{star.hip}",
        name=candidate.name,
        kind=VantageKind.STAR,
        lookback=distance.lookback,
        magnitude=star.vmag,
        constellation=constellation,
        ra_deg=candidate.ra,
        dec_deg=candidate.dec,
        fame=candidate.fame,
        facts=facts,
    )


# --- search ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchEntry:
    """A row for the ``search_entries`` table."""

    type: str
    id: str
    name: str
    aliases: str
    description: str


def search_entry(star: VantagePoint) -> SearchEntry | None:
    """The search entry for a star, or None if it should not be searchable.

    Only stars with a fame above 0 (IAU-named or nearby) are searchable, which keeps the
    search indexes small. Every other star can still be reached by its id.
    """
    if star.fame == 0:
        return None
    aliases = [f"HIP {star.facts['hip']}"]
    if "hd" in star.facts:
        aliases.append(f"HD {star.facts['hd']}")
    description = f"Star in {star.constellation}" if star.constellation else "Star"
    return SearchEntry(
        type="vantage_point",
        id=star.id,
        name=star.name,
        aliases="\n".join(aliases),
        description=description,
    )
