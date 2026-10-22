"""Distances to nearby galaxies from McConnachie (2012) and Cosmicflows-4.

Pure logic like ``star_clusters.py``. Both catalogues give a distance as a *distance modulus*,
the difference between a galaxy's apparent and absolute magnitude. A modulus ``m`` is a distance
of ``10 ** (m / 5 + 1)`` parsecs. The catalogues' own errors on ``m`` make the range, so a
nearer end comes from ``m`` minus its negative error and a farther end from ``m`` plus its
positive error. A galaxy at distance d is seen as it was d light-years ago, so the distance in
light-years is the lookback in years.

* McConnachie (2012, AJ 144, 4; VizieR ``J/AJ/144/4/catalog``): the Magellanic Clouds,
  Andromeda, and the other dwarf galaxies in and around the Local Group. It has its own
  positive and negative errors.
* Cosmicflows-4 (Tully et al. 2023, ApJ 944, 94; VizieR ``J/ApJ/944/94/table2``): individual
  galaxies out to hundreds of millions of light-years, one distance modulus and one error from
  all the methods that measured it.
"""

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from earthlight.lookback import LookbackRange
from earthlight_pipeline.parsing import integer as _integer
from earthlight_pipeline.parsing import number as _number
from earthlight_pipeline.parsing import words as _words
from earthlight_pipeline.star_clusters import LIGHT_YEARS_PER_PARSEC

MCCONNACHIE = "mcconnachie_2012"
COSMICFLOWS = "cosmicflows_4"


@dataclass(frozen=True)
class GalaxyRecord:
    """The row of one galaxy. Errors are in magnitudes of distance modulus; None if missing."""

    catalogue: str
    name: str
    ra_deg: float | None
    dec_deg: float | None
    modulus: float | None
    error_plus: float | None
    error_minus: float | None


GalaxyRecords = dict[tuple[str, str], GalaxyRecord]
"""Rows by (catalogue, name), so the two catalogues can share one mapping."""


def read_mcconnachie(paths: Iterable[Path]) -> GalaxyRecords:
    """The McConnachie rows by name, from the downloaded files."""
    records: GalaxyRecords = {}
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                name = _words(row["Name"])
                if name:
                    records[(MCCONNACHIE, name)] = GalaxyRecord(
                        catalogue=MCCONNACHIE,
                        name=name,
                        ra_deg=_number(row["RAJ2000"]),
                        dec_deg=_number(row["DEJ2000"]),
                        modulus=_number(row["(m-M)"]),
                        error_plus=_number(row["E_(m-M)"]),
                        error_minus=_number(row["e_(m-M)"]),
                    )
    return records


def read_cosmicflows(paths: Iterable[Path]) -> GalaxyRecords:
    """The Cosmicflows-4 rows by name ("PGC 28655"), from the downloaded files."""
    records: GalaxyRecords = {}
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                number = _integer(_words(row["PGC"]))
                if number is None:
                    continue
                error = _number(row["e_DM"])
                name = pgc_name(number)
                records[(COSMICFLOWS, name)] = GalaxyRecord(
                    catalogue=COSMICFLOWS,
                    name=name,
                    ra_deg=_number(row["RAJ2000"]),
                    dec_deg=_number(row["DEJ2000"]),
                    modulus=_number(row["DM"]),
                    error_plus=error,
                    error_minus=error,
                )
    return records


def pgc_name(number: int) -> str:
    """How a Principal Galaxies Catalogue number is written in the curated list."""
    return f"PGC {number}"


def pgc_number(name: str) -> int | None:
    """The number in a curated name such as "PGC 28655", or None if it is not one."""
    prefix, _, rest = name.partition(" ")
    return _integer(rest) if prefix == "PGC" else None


def distance_range_pc(record: GalaxyRecord) -> tuple[float, float, float]:
    """The distance (nearest, best, farthest) in parsecs from the distance modulus and errors.

    Raises ValueError if the modulus or an error is missing or negative.
    """
    if record.modulus is None or record.error_plus is None or record.error_minus is None:
        raise ValueError(f"{record.name}: the catalogue has no distance modulus and errors")
    if record.error_plus < 0 or record.error_minus < 0:
        raise ValueError(f"{record.name}: a negative error on the distance modulus")
    if record.modulus <= 0:
        raise ValueError(f"{record.name}: the distance modulus {record.modulus} is not a distance")

    def parsecs(modulus: float) -> float:
        return 10 ** (modulus / 5 + 1)

    return (
        parsecs(record.modulus - record.error_minus),
        parsecs(record.modulus),
        parsecs(record.modulus + record.error_plus),
    )


def galaxy_lookback(record: GalaxyRecord) -> LookbackRange:
    """The lookback in years for a galaxy: its distance in light-years."""
    near, best, far = (d * LIGHT_YEARS_PER_PARSEC for d in distance_range_pc(record))
    return LookbackRange(near, best, far)
