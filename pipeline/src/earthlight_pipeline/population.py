"""World population estimates from Our World in Data.

Pure logic like ``stars.py``: it reads the CSV that ``sources.py`` downloaded and returns
``PopulationEstimate`` models. Findings about the real file are in ``docs/data-sources.md``
(step 2.14). In short: one row per entity and year (``Entity``, ``Code``, ``Year``,
``Population``), 58,824 rows for about 250 countries and regions, and the world is the entity
with code ``OWID_WRL``. Years are labelled with negative numbers for BCE (``-10000`` is
10000 BCE), and the world series runs 10000 BCE to 2023 with steps of 1000, 100, 10, and 1
years as the evidence gets better. A BCE label is stored in astronomical numbering like
everything else in Earthlight (N BCE is 1 - N), so ``-10000`` becomes -9999; the label ``0`` is
kept as 0. The estimates are far too coarse for that one year to matter, but the rule is the
same everywhere.
"""

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from earthlight.models import PopulationEstimate
from earthlight_pipeline.parsing import words as _words

WORLD_CODE = "OWID_WRL"
"""The code of the world in the Our World in Data files."""

COLUMNS = ("Entity", "Code", "Year", "Population")

CHART_URL = "https://ourworldindata.org/grapher/population"
"""The chart the numbers come from, stored as each estimate's source."""


class PopulationError(ValueError):
    """The population file is not what was expected. The message lists every problem."""


@dataclass(frozen=True)
class PopulationSource:
    """One of the data sets that Our World in Data combines into the world series."""

    name: str
    version: str
    covers: str
    license: str


UNDERLYING_SOURCES = (
    PopulationSource(
        "History Database of the Global Environment (HYDE), PBL Netherlands Environmental "
        "Assessment Agency",
        "3.3",
        "10000 BCE to 1799",
        "CC BY 4.0",
    ),
    PopulationSource("Gapminder, Population", "v7", "1800 to 1949", "CC BY 4.0"),
    PopulationSource(
        "United Nations, World Population Prospects", "2024", "1950 to 2023", "CC BY 3.0 IGO"
    ),
)
"""What Our World in Data's metadata says the world series is made from."""


def astronomical_year(label: int) -> int:
    """The year for one of Our World in Data's labels: BCE labels are 1 - N, others unchanged."""
    return label + 1 if label < 0 else label


def _whole_number(text: str) -> int | None:
    """An integer written with an optional minus sign and the digits 0 to 9, or None."""
    digits = text.removeprefix("-")
    return int(text) if digits.isascii() and digits.isdigit() else None


def read_population(path: Path, last_year: int | None = None) -> list[PopulationEstimate]:
    """The world population estimates in ``path``, oldest first.

    Raises PopulationError listing every problem: a missing column, no world rows, a row that
    is not a whole year and a whole positive number of people, a repeated year, a year after
    ``last_year`` (it defaults to this year; later years would be projections, not estimates),
    or years out of order.
    """
    last_year = datetime.now(tz=UTC).year if last_year is None else last_year
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise PopulationError(f"{path.name} has no column {', '.join(missing)}")
        rows = [row for row in reader if _words(row["Code"]) == WORLD_CODE]
    if not rows:
        raise PopulationError(f"{path.name} has no rows for the world ({WORLD_CODE})")

    problems: list[str] = []
    estimates: list[PopulationEstimate] = []
    seen: set[int] = set()
    for row in rows:
        written = _words(row["Year"])
        shown = _words(row["Population"])
        label = _whole_number(written)
        people = _whole_number(shown)
        where = f"year {written}"
        if label is None:
            problems.append(f"{where}: not a whole year")
        elif people is None or people <= 0:
            problems.append(f"{where}: population '{shown}' is not a whole number above zero")
        elif label > last_year:
            problems.append(f"{where}: is after {last_year}, so it is a projection")
        elif astronomical_year(label) in seen:
            problems.append(f"{where}: appears more than once")
        else:
            year = astronomical_year(label)
            seen.add(year)
            estimates.append(PopulationEstimate(year=year, people=people, source=CHART_URL))
    if problems:
        raise PopulationError("\n".join(problems))
    years = [estimate.year for estimate in estimates]
    if years != sorted(years):
        raise PopulationError(f"{path.name}: the world rows are not in year order")
    return estimates


def span_text(estimates: Sequence[PopulationEstimate]) -> str:
    """The first and last estimate for people, such as "4.5 million in 10000 BCE"."""
    first, last = estimates[0], estimates[-1]
    return (
        f"{_people_text(first.people)} in {_year_text(first.year)} to "
        f"{_people_text(last.people)} in {_year_text(last.year)}"
    )


def _people_text(people: int) -> str:
    if people >= 1e9:
        return f"{people / 1e9:.2f} billion"
    return f"{people / 1e6:.1f} million"


def _year_text(year: float) -> str:
    return f"{int(year)} CE" if year >= 1 else f"{1 - int(year)} BCE"
