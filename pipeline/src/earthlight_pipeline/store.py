"""Writing the pipeline's results into the Earthlight SQLite database.

The schema itself belongs to the ``earthlight`` package (``earthlight.schema``); this module
only opens a database that has it and fills it.
"""

import json
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path

from earthlight.lookback import LookbackRange
from earthlight.models import VantagePoint
from earthlight.schema import SCHEMA_VERSION, create_empty_database, rebuild_search_index
from earthlight_pipeline.stars import SearchEntry


def open_database(path: Path) -> sqlite3.Connection:
    """Open the database at ``path`` for writing, creating it with the schema if it is missing.

    Foreign keys are switched on. Raises ValueError if the file has a different schema version.
    """
    path = Path(path)
    if not path.exists():
        create_empty_database(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None or row[0] != str(SCHEMA_VERSION):
        connection.close()
        found = "none" if row is None else row[0]
        raise ValueError(f"{path} has schema version {found}, expected {SCHEMA_VERSION}")
    return connection


def set_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
    """Set a ``meta`` value, replacing any earlier one."""
    with connection:
        connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def vantage_row(point: VantagePoint) -> dict[str, object]:
    """The ``vantage_points`` columns for a model, ready to insert."""
    return {
        "id": point.id,
        "name": point.name,
        "kind": point.kind.value,
        "lookback_min": point.lookback.minimum,
        "lookback_best": point.lookback.best,
        "lookback_max": point.lookback.maximum,
        "magnitude": point.magnitude,
        "constellation": point.constellation,
        "ra_deg": point.ra_deg,
        "dec_deg": point.dec_deg,
        "fame": point.fame,
        "host_id": point.host_id,
        "wikipedia": point.wikipedia,
        "facts": json.dumps(dict(point.facts), separators=(",", ":"), sort_keys=True),
    }


def replace_stars(
    connection: sqlite3.Connection, stars: Sequence[VantagePoint], entries: Iterable[SearchEntry]
) -> None:
    """Replace every star in the database with ``stars``, then rebuild the search indexes.

    The replacement is one transaction: either all the stars are replaced or none are. The
    file is then vacuumed, because SQLite does not shrink a file when rows are deleted, so
    without it a rebuilt database would keep the size of the old one. Raises RuntimeError if
    other rows (such as exoplanets) still depend on the existing stars.
    """
    columns = list(vantage_row(stars[0])) if stars else []
    insert_star = (
        f"INSERT INTO vantage_points ({', '.join(columns)}) "
        f"VALUES ({', '.join(':' + column for column in columns)})"
    )
    try:
        with connection:
            connection.execute(
                "DELETE FROM search_entries WHERE type = 'vantage_point' "
                "AND id IN (SELECT id FROM vantage_points WHERE kind = 'star')"
            )
            connection.execute("DELETE FROM vantage_points WHERE kind = 'star'")
            if stars:
                connection.executemany(insert_star, [vantage_row(star) for star in stars])
            connection.executemany(
                "INSERT INTO search_entries (type, id, name, aliases, description) "
                "VALUES (?, ?, ?, ?, ?)",
                [(e.type, e.id, e.name, e.aliases, e.description) for e in entries],
            )
    except sqlite3.IntegrityError as error:
        raise RuntimeError(
            f"could not replace the stars ({error}). Other data depends on them; "
            "rebuild the whole database instead."
        ) from error
    rebuild_search_index(connection)
    connection.execute("VACUUM")


def load_stars(connection: sqlite3.Connection) -> list[VantagePoint]:
    """Read every star back as a model, ordered by id."""
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute("SELECT * FROM vantage_points WHERE kind = 'star' ORDER BY id")
        return [
            VantagePoint(
                id=row["id"],
                name=row["name"],
                kind=row["kind"],
                lookback=LookbackRange(
                    row["lookback_min"], row["lookback_best"], row["lookback_max"]
                ),
                magnitude=row["magnitude"],
                constellation=row["constellation"],
                ra_deg=row["ra_deg"],
                dec_deg=row["dec_deg"],
                fame=row["fame"],
                host_id=row["host_id"],
                wikipedia=row["wikipedia"],
                facts=json.loads(row["facts"]),
            )
            for row in rows
        ]
    finally:
        connection.row_factory = None
