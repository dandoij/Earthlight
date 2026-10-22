"""Distances to star clusters from the Hunt and Reffert (2023) catalogue.

Pure logic like ``deep_sky.py``. The catalogue (VizieR ``J/A+A/673/A114/clusters``, see
``docs/data-sources.md``) gives a maximum-likelihood distance for each cluster as its 16th, 50th,
and 84th percentile. Those cover only the random error of the Gaia parallaxes, so a systematic
floor is added in parallax, and the range is turned into years of light travel.

A cluster at distance d is seen as it was d light-years ago, so the distance in light-years is
the lookback in years.
"""

import csv
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from earthlight.lookback import LookbackRange
from earthlight_pipeline.parsing import integer as _integer
from earthlight_pipeline.parsing import number as _number
from earthlight_pipeline.parsing import words as _words

SPEED_OF_LIGHT_M_S = 299_792_458
"""Exact, by the definition of the metre."""

ASTRONOMICAL_UNIT_M = 149_597_870_700
"""Exact, by the 2012 IAU definition."""

LIGHT_YEAR_M = SPEED_OF_LIGHT_M_S * 365.25 * 86_400
"""The distance light travels in a Julian year (365.25 days)."""

PARSEC_M = ASTRONOMICAL_UNIT_M * 648_000 / math.pi
"""The distance at which one astronomical unit spans one arcsecond (IAU 2015 definition)."""

LIGHT_YEARS_PER_PARSEC = PARSEC_M / LIGHT_YEAR_M
"""About 3.2616, derived from the definitions above rather than typed in."""

SYSTEMATIC_PARALLAX_MAS = 0.010
"""A floor for the parallax error, in milliarcseconds, added in quadrature to the catalogue's
own range. Gaia's parallaxes carry a systematic error that does not shrink with more stars:
a study of globular clusters (Vasiliev and Baumgardt 2021, arXiv:2102.09568) gives 0.01 mas as
its lower limit for a cluster's average parallax, and Maiz Apellaniz et al. (2021, A&A 649,
A13) find a minimum of 10.3 microarcseconds for individual stars or compact clusters. At
100 pc this is a 0.1 percent error and at 10 kpc it is 10 percent."""

CLUSTER_TYPES = {"o": "open", "g": "globular"}
"""The catalogue's ``Type`` letters that Earthlight uses. ``m`` (moving group) is not used."""


@dataclass(frozen=True)
class ClusterRecord:
    """The row of one cluster. Distances are in parsecs; missing numbers are None."""

    name: str
    all_names: tuple[str, ...]
    cluster_type: str
    ra_deg: float | None
    dec_deg: float | None
    dist16_pc: float | None
    dist50_pc: float | None
    dist84_pc: float | None
    member_stars: int | None
    global_parallax: bool


def read_hunt_reffert(paths: Iterable[Path]) -> dict[str, ClusterRecord]:
    """The cluster rows by catalogue name, from the downloaded files."""
    records: dict[str, ClusterRecord] = {}
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                name = _words(row["Name"])
                if not name:
                    continue
                records[name] = ClusterRecord(
                    name=name,
                    all_names=tuple(n for n in _words(row["AllNames"]).split(",") if n),
                    cluster_type=_words(row["Type"]),
                    ra_deg=_number(row["RA_ICRS"]),
                    dec_deg=_number(row["DE_ICRS"]),
                    dist16_pc=_number(row["dist16"]),
                    dist50_pc=_number(row["dist50"]),
                    dist84_pc=_number(row["dist84"]),
                    member_stars=_integer(row["Ndist"]),
                    global_parallax=_words(row["globalPlx"]) == "1",
                )
    return records


def parallax_range_mas(record: ClusterRecord) -> tuple[float, float, float]:
    """The parallax (largest, best, smallest) in mas, with the systematic floor added.

    A nearer distance is a larger parallax, so the near end of the range comes first. Raises
    ValueError if the distances are missing or out of order, or if the floor makes the smallest
    parallax zero or negative (the cluster would have no far limit).
    """
    near, best, far = record.dist16_pc, record.dist50_pc, record.dist84_pc
    if near is None or best is None or far is None:
        raise ValueError(f"{record.name}: the catalogue has no distance")
    if not 0 < near <= best <= far:
        raise ValueError(f"{record.name}: the distances {near}, {best}, {far} pc are out of order")
    best_parallax = 1000.0 / best
    up = math.hypot(1000.0 / near - best_parallax, SYSTEMATIC_PARALLAX_MAS)
    down = math.hypot(best_parallax - 1000.0 / far, SYSTEMATIC_PARALLAX_MAS)
    if best_parallax - down <= 0:
        raise ValueError(
            f"{record.name}: at {best:.0f} pc the systematic parallax error leaves no far limit"
        )
    return best_parallax + up, best_parallax, best_parallax - down


def distance_range_pc(record: ClusterRecord) -> tuple[float, float, float]:
    """The distance (nearest, best, farthest) in parsecs, with the systematic floor added."""
    largest, best, smallest = parallax_range_mas(record)
    return 1000.0 / largest, 1000.0 / best, 1000.0 / smallest


def cluster_lookback(record: ClusterRecord) -> LookbackRange:
    """The lookback in years for a cluster: its distance in light-years."""
    near, best, far = (d * LIGHT_YEARS_PER_PARSEC for d in distance_range_pc(record))
    return LookbackRange(near, best, far)
