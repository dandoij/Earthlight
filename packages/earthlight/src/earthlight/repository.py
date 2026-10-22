"""Read-only access to the bundled Earthlight database.

``Repository`` wraps one SQLite connection and turns rows into the shared models, so the
engine never writes SQL. The file is opened in read-only mode (SQLite refuses every write),
and its schema version is checked on open so that an engine never reads a database built for
a different layout.

Most code uses ``default_repository()``, which opens the bundled file once and reuses it,
the way a NestJS provider is created once and injected everywhere. Tests and the API can
build their own ``Repository`` for another file.
"""

import json
import sqlite3
import threading
from collections.abc import Collection
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from earthlight.lookback import LookbackRange
from earthlight.models import (
    ExoplanetDetails,
    HistoryEvent,
    HistoryPeriod,
    Landmark,
    PopulationEstimate,
    VantageKind,
    VantagePoint,
)
from earthlight.schema import SCHEMA_VERSION, check_sqlite_version
from earthlight.time import DecimalYear

BUNDLED_DATABASE = ("data", "earthlight.db")
"""Where the built database lives inside the package."""

_ENTRY_COLUMNS = (
    "id",
    "name",
    "category",
    "region",
    "summary",
    "importance",
    "wikipedia",
    "source",
)


@dataclass(frozen=True)
class SearchRow:
    """One searchable thing as stored: what it is, its names, and how well known it is."""

    type: str
    id: str
    name: str
    aliases: tuple[str, ...]
    description: str
    kind: str | None
    """For a vantage point, what kind of object it is; None for history entries."""
    weight: int
    """Fame (0 to 5) for a vantage point, importance (1 to 5) for a history entry."""


@dataclass(frozen=True)
class HistoryMoment:
    """The moment that stands for a history entry, and what that moment is."""

    name: str
    moment: float
    role: str
    """'date' for an event, 'start' for a period, 'completion' for a landmark."""


_HISTORY_MOMENTS = {
    "event": ("events", "year", "date"),
    "period": ("periods", "start_year", "start"),
    "landmark": ("landmarks", "built_end", "completion"),
}
"""For each kind of history entry: its table, the column that gives its moment, and the role."""

_SEARCH_SELECT = (
    "SELECT s.type, s.id, s.name, s.aliases, s.description, v.kind AS kind, "
    "COALESCE(v.fame, e.importance, p.importance, l.importance, 0) AS weight "
    "FROM {source} "
    "LEFT JOIN vantage_points v ON s.type = 'vantage_point' AND v.id = s.id "
    "LEFT JOIN events e ON s.type = 'event' AND e.id = s.id "
    "LEFT JOIN periods p ON s.type = 'period' AND p.id = s.id "
    "LEFT JOIN landmarks l ON s.type = 'landmark' AND l.id = s.id "
)


class RepositoryError(RuntimeError):
    """The database is missing, unreadable, or built for a different schema version."""


def bundled_database_path() -> Path:
    """The path of the database that ships inside the package."""
    return Path(str(resources.files("earthlight").joinpath(*BUNDLED_DATABASE)))


class Repository:
    """Typed, read-only queries over one Earthlight database file."""

    def __init__(self, path: Path | None = None) -> None:
        """Open ``path`` (default: the bundled database) read-only.

        Raises RepositoryError if the file does not exist, is not an Earthlight database, or
        has a schema version other than the one this code reads.
        """
        check_sqlite_version()
        self.path = bundled_database_path() if path is None else Path(path)
        if not self.path.is_file():
            raise RepositoryError(f"no database at {self.path}")
        # check_same_thread is off because a web server may hand one connection to several
        # threads; the database is read-only and every query takes the lock below.
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(
            f"{self.path.as_uri()}?mode=ro", uri=True, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        try:
            self.schema_version = self._read_schema_version()
        except sqlite3.DatabaseError as error:
            self._connection.close()
            raise RepositoryError(f"{self.path} is not an Earthlight database ({error})") from error
        if self.schema_version != SCHEMA_VERSION:
            self._connection.close()
            raise RepositoryError(
                f"{self.path} has schema version {self.schema_version}, "
                f"but this Earthlight reads version {SCHEMA_VERSION}"
            )

    def _read_schema_version(self) -> int:
        row = self._connection.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def close(self) -> None:
        """Close the connection. Safe to call twice."""
        with self._lock:
            self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _rows(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(sql, params).fetchall()

    # --- meta ----------------------------------------------------------------------------

    def meta(self) -> dict[str, str]:
        """Every ``meta`` entry (schema version, license, build date, sources)."""
        return {row["key"]: row["value"] for row in self._rows("SELECT key, value FROM meta")}

    # --- vantage points ------------------------------------------------------------------

    def vantage_point(self, vantage_id: str) -> VantagePoint | None:
        """The vantage point with this id, or None."""
        rows = self._rows("SELECT * FROM vantage_points WHERE id = ?", (vantage_id,))
        return _vantage_point(rows[0]) if rows else None

    def vantage_points_overlapping(
        self, low: float, high: float, *, kinds: Collection[VantageKind] | None = None
    ) -> list[VantagePoint]:
        """Vantage points whose lookback range overlaps ``[low, high]`` (bounds included).

        ``kinds`` limits the result to those kinds. The order is by id, so results are stable.
        """
        sql = "SELECT * FROM vantage_points WHERE lookback_min <= :high AND lookback_max >= :low"
        params: dict[str, Any] = {"low": low, "high": high}
        if kinds is not None:
            names = [kind.value for kind in kinds]
            if not names:
                return []
            marks = ", ".join(f":kind{i}" for i in range(len(names)))
            sql += f" AND kind IN ({marks})"
            params |= {f"kind{i}": name for i, name in enumerate(names)}
        return [_vantage_point(row) for row in self._rows(sql + " ORDER BY id", params)]

    def max_lookback(self) -> float:
        """The largest lookback in the database: the oldest light there is anything to see."""
        return float(self._rows("SELECT max(lookback_max) AS m FROM vantage_points")[0]["m"])

    def exoplanet_details(self, vantage_id: str) -> ExoplanetDetails | None:
        """The archive details of an exoplanet, or None if ``vantage_id`` is not one."""
        rows = self._rows("SELECT * FROM exoplanets WHERE vantage_id = ?", (vantage_id,))
        if not rows:
            return None
        row = rows[0]
        return ExoplanetDetails(
            nasa_name=row["nasa_name"],
            host_name=row["host_name"],
            discovery_year=row["discovery_year"],
            discovery_method=row["discovery_method"],
            radius_earth=row["radius_earth"],
            mass_earth=row["mass_earth"],
            orbital_period_days=row["orbital_period_days"],
            controversial=bool(row["controversial"]),
        )

    def planet_ids_of(self, host_id: str) -> list[str]:
        """The ids of the planets whose host is this star, ordered by id."""
        rows = self._rows("SELECT id FROM vantage_points WHERE host_id = ? ORDER BY id", (host_id,))
        return [row["id"] for row in rows]

    # --- history -------------------------------------------------------------------------

    def history_moment(self, entry_type: str, entry_id: str) -> HistoryMoment | None:
        """The moment that stands for a history entry: an event's date, a period's start, or the
        year a landmark was finished. None if there is no such entry.
        """
        table = _HISTORY_MOMENTS.get(entry_type)
        if table is None:
            return None
        sql = f"SELECT name, {table[1]} AS moment FROM {table[0]} WHERE id = ?"  # fixed names
        rows = self._rows(sql, (entry_id,))
        if not rows:
            return None
        return HistoryMoment(name=rows[0]["name"], moment=rows[0]["moment"], role=table[2])

    def events_between(self, earliest: DecimalYear, latest: DecimalYear) -> list[HistoryEvent]:
        """Events dated inside ``[earliest, latest]``, counting each event's own uncertainty.

        Most important first, then by date.
        """
        rows = self._rows(
            "SELECT * FROM events WHERE year + year_uncertainty >= :earliest "
            "AND year - year_uncertainty <= :latest ORDER BY importance DESC, year, id",
            {"earliest": earliest, "latest": latest},
        )
        return [
            HistoryEvent(
                **_entry_fields(row), year=row["year"], year_uncertainty=row["year_uncertainty"]
            )
            for row in rows
        ]

    def periods_overlapping(
        self, earliest: DecimalYear, latest: DecimalYear
    ) -> list[HistoryPeriod]:
        """Periods that overlap ``[earliest, latest]``. An ongoing period has no end.

        Most important first, then by start.
        """
        rows = self._rows(
            "SELECT * FROM periods WHERE start_year <= :latest "
            "AND (ongoing = 1 OR end_year >= :earliest) "
            "ORDER BY importance DESC, start_year, id",
            {"earliest": earliest, "latest": latest},
        )
        return [
            HistoryPeriod(
                **_entry_fields(row),
                start=row["start_year"],
                end=row["end_year"],
                ongoing=bool(row["ongoing"]),
            )
            for row in rows
        ]

    def landmarks_overlapping(self, earliest: DecimalYear, latest: DecimalYear) -> list[Landmark]:
        """Landmarks whose construction began by ``latest`` and that were not destroyed before
        ``earliest`` (so they were being built, standing, or just destroyed in the span).

        Most important first, then by construction start.
        """
        rows = self._rows(
            "SELECT * FROM landmarks WHERE built_start <= :latest "
            "AND (destroyed IS NULL OR destroyed >= :earliest) "
            "ORDER BY importance DESC, built_start, id",
            {"earliest": earliest, "latest": latest},
        )
        return [
            Landmark(
                **_entry_fields(row),
                built_start=row["built_start"],
                built_end=row["built_end"],
                destroyed=row["destroyed"],
                lat=row["lat"],
                lon=row["lon"],
            )
            for row in rows
        ]

    # --- search --------------------------------------------------------------------------

    def search_exact(self, text: str) -> list[SearchRow]:
        """Entries whose name, or one of whose other names, is ``text`` (ignoring case)."""
        wanted = text.lower()
        sql = _SEARCH_SELECT.format(source="search_entries s") + (
            "WHERE lower(s.name) = :text "
            "OR instr(char(10) || lower(s.aliases) || char(10), char(10) || :text || char(10)) > 0 "
            "ORDER BY weight DESC, s.name, s.id"
        )
        return [_search_row(row) for row in self._rows(sql, {"text": wanted})]

    def search_words(self, expression: str, limit: int) -> list[SearchRow]:
        """Word search. ``expression`` is FTS5 syntax built by ``earthlight.search``.

        Best match first (name matches count most), then the better known.
        """
        sql = _SEARCH_SELECT.format(
            source="search_fts f JOIN search_entries s ON s.entry_id = f.rowid"
        ) + (
            "WHERE search_fts MATCH :expression "
            "ORDER BY bm25(search_fts, 10.0, 4.0, 1.0), weight DESC, s.name, s.id LIMIT :limit"
        )
        return [
            _search_row(row) for row in self._rows(sql, {"expression": expression, "limit": limit})
        ]

    def search_trigrams(self, expression: str, limit: int) -> list[SearchRow]:
        """Entries sharing letter triples with the query: candidates for did-you-mean.

        ``expression`` is FTS5 syntax built by ``earthlight.search``. Entries sharing the
        most triples come first.
        """
        sql = _SEARCH_SELECT.format(
            source="search_trigram t JOIN search_entries s ON s.entry_id = t.rowid"
        ) + ("WHERE search_trigram MATCH :expression ORDER BY t.rank, s.id LIMIT :limit")
        return [
            _search_row(row) for row in self._rows(sql, {"expression": expression, "limit": limit})
        ]

    # --- population ----------------------------------------------------------------------

    def population_years(self) -> tuple[DecimalYear, DecimalYear] | None:
        """The first and last year with a population estimate, or None if there are none."""
        row = self._rows("SELECT min(year) AS first, max(year) AS last FROM population")[0]
        return None if row["first"] is None else (row["first"], row["last"])

    def population_nearest(self, year: DecimalYear) -> PopulationEstimate | None:
        """The stored world population estimate closest in time to ``year``, or None.

        Nothing is interpolated: the estimate keeps its own year so callers can say how far
        it is from the year asked about.
        """
        rows = self._rows(
            "SELECT year, people, source FROM population ORDER BY abs(year - ?), year LIMIT 1",
            (year,),
        )
        if not rows:
            return None
        row = rows[0]
        return PopulationEstimate(year=row["year"], people=row["people"], source=row["source"])


def _entry_fields(row: sqlite3.Row) -> dict[str, Any]:
    return {column: row[column] for column in _ENTRY_COLUMNS}


def _search_row(row: sqlite3.Row) -> SearchRow:
    return SearchRow(
        type=row["type"],
        id=row["id"],
        name=row["name"],
        aliases=tuple(line for line in row["aliases"].splitlines() if line),
        description=row["description"],
        kind=row["kind"],
        weight=row["weight"],
    )


def _vantage_point(row: sqlite3.Row) -> VantagePoint:
    return VantagePoint(
        id=row["id"],
        name=row["name"],
        kind=VantageKind(row["kind"]),
        lookback=LookbackRange(row["lookback_min"], row["lookback_best"], row["lookback_max"]),
        magnitude=row["magnitude"],
        constellation=row["constellation"],
        ra_deg=row["ra_deg"],
        dec_deg=row["dec_deg"],
        fame=row["fame"],
        host_id=row["host_id"],
        wikipedia=row["wikipedia"],
        facts=json.loads(row["facts"]),
    )


@lru_cache(maxsize=1)
def default_repository() -> Repository:
    """The bundled database, opened on first use and shared afterwards."""
    return Repository()
