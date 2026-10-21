"""The SQLite schema that the data pipeline builds and the engine reads.

``schema.sql`` is the single source of truth for the tables and their rules. This module
loads it, applies it to a connection, and holds the version and the list of expected tables
so that the build and the engine can check a database against them.
"""

import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 1
"""Bumped whenever the tables change in a way that older engine code cannot read."""

MIN_SQLITE_VERSION = (3, 38, 0)
"""STRICT tables need 3.37, built-in JSON 3.38, and the FTS5 trigram tokenizer 3.34."""

TABLES = (
    "meta",
    "vantage_points",
    "exoplanets",
    "events",
    "periods",
    "landmarks",
    "population",
    "search_entries",
)
"""Ordinary tables, in the order the build can fill them (parents before children)."""

SEARCH_INDEXES = ("search_fts", "search_trigram")
"""FTS5 virtual tables over ``search_entries``."""


def schema_sql() -> str:
    """The text of ``schema.sql``."""
    return resources.files("earthlight").joinpath("schema.sql").read_text(encoding="utf-8")


def check_sqlite_version() -> None:
    """Raise RuntimeError if the SQLite library is too old for the schema."""
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        needed = ".".join(str(n) for n in MIN_SQLITE_VERSION)
        raise RuntimeError(
            f"Earthlight needs SQLite {needed} or newer, "
            f"but this Python has {sqlite3.sqlite_version}"
        )


def apply_schema(connection: sqlite3.Connection) -> None:
    """Create every table and index on ``connection`` and record the schema version.

    The version is stored twice, in ``meta`` and in SQLite's ``user_version``, so that a
    database can be identified without querying it. Raises RuntimeError if SQLite is too
    old, and sqlite3.OperationalError if the connection already has these tables.
    """
    check_sqlite_version()
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(schema_sql())
    connection.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
    )
    connection.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
    connection.commit()


def rebuild_search_index(connection: sqlite3.Connection) -> None:
    """Rebuild both search indexes from ``search_entries``.

    The indexes are external-content tables, so they must be rebuilt after
    ``search_entries`` is filled and before the database is finished.
    """
    for index in SEARCH_INDEXES:
        connection.execute(f"INSERT INTO {index} ({index}) VALUES ('rebuild')")
    connection.commit()


def create_empty_database(path: Path, *, overwrite: bool = False) -> None:
    """Write a new database file that has the schema and no data.

    Raises FileExistsError if ``path`` exists and ``overwrite`` is false.
    """
    path = Path(path)
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"{path} already exists")
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        apply_schema(connection)
    finally:
        connection.close()
