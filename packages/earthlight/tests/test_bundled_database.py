"""Checks on the database that ships inside the package (built by ``earthlight-build all``).

SQLite cannot express a few of the rules, so they are checked here. If one of these tests
fails after a rebuild, the build or a source file changed in a way the engine cannot rely on.
"""

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import cast

import pytest

from earthlight.schema import SCHEMA_VERSION, SEARCH_INDEXES, TABLES

DATABASE = Path(str(resources.files("earthlight").joinpath("data", "earthlight.db")))
LICENSE_DATA = Path(__file__).resolve().parents[3] / "LICENSE-DATA"
SIZE_LIMIT_BYTES = 20 * 1024 * 1024
"""The wheel has to stay small enough to install quickly; the plan budgets about 20 MB."""

THIS_YEAR = datetime.now(UTC).year


@pytest.fixture(scope="module")
def db() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA foreign_keys = ON")
    yield connection
    connection.close()


def scalar(db: sqlite3.Connection, sql: str, *args: object) -> int:
    row = db.execute(sql, args).fetchone()
    return int(row[0])


# --- the file itself ---------------------------------------------------------------------------


def test_the_database_is_bundled_and_within_the_size_limit() -> None:
    assert DATABASE.is_file()
    assert DATABASE.stat().st_size <= SIZE_LIMIT_BYTES


def test_the_schema_version_is_the_current_one(db: sqlite3.Connection) -> None:
    assert scalar(db, "PRAGMA user_version") == SCHEMA_VERSION
    assert scalar(db, "SELECT value FROM meta WHERE key = 'schema_version'") == SCHEMA_VERSION


def test_the_file_is_sound(db: sqlite3.Connection) -> None:
    assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("table", [t for t in TABLES if t != "meta"])
def test_every_table_has_rows(db: sqlite3.Connection, table: str) -> None:
    assert scalar(db, f"SELECT count(*) FROM {table}") > 0


def test_the_license_is_recorded_and_the_license_file_exists(db: sqlite3.Connection) -> None:
    meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
    assert meta["data_license"] == "CC BY-NC 3.0 IGO"
    assert meta["data_license_url"] == "https://creativecommons.org/licenses/by-nc/3.0/igo/"
    assert "CC BY-NC 3.0 IGO" in LICENSE_DATA.read_text(encoding="utf-8")


def test_every_source_is_recorded_with_a_name(db: sqlite3.Connection) -> None:
    sources: list[tuple[str, str]] = db.execute(
        "SELECT key, value FROM meta WHERE key LIKE 'source.%'"
    ).fetchall()
    assert {key for key, _ in sources} == {
        f"source.{name}"
        for name in (
            "hipparcos",
            "gaia_dr3",
            "bailer_jones_2021",
            "iau_csn",
            "nasa_exoplanet_archive",
            "simbad",
            "hunt_reffert_2023",
            "mcconnachie_2012",
            "cosmicflows_4",
            "population",
        )
    }
    for key, value in sources:
        assert json.loads(value)["name"], key


# --- vantage points ----------------------------------------------------------------------------


def test_ids_are_unique_across_every_kind(db: sqlite3.Connection) -> None:
    # The schema already enforces this; the test guards against schema drift.
    assert scalar(db, "SELECT count(*) - count(DISTINCT id) FROM vantage_points") == 0
    assert scalar(db, "SELECT count(*) - count(DISTINCT lower(id)) FROM vantage_points") == 0


def test_every_lookback_range_is_in_order_and_finite(db: sqlite3.Connection) -> None:
    # The schema already has CHECKs for this; the test guards against schema drift.
    bad = scalar(
        db,
        "SELECT count(*) FROM vantage_points WHERE NOT "
        "(0 <= lookback_min AND lookback_min <= lookback_best "
        "AND lookback_best <= lookback_max AND lookback_max < 1e15)",
    )
    assert bad == 0


def test_every_planet_row_belongs_to_a_planet_vantage_point(db: sqlite3.Connection) -> None:
    assert scalar(db, "SELECT count(*) FROM exoplanets") == scalar(
        db, "SELECT count(*) FROM vantage_points WHERE kind = 'exoplanet'"
    )


def test_every_host_id_points_at_a_star(db: sqlite3.Connection) -> None:
    linked = scalar(db, "SELECT count(*) FROM vantage_points WHERE host_id IS NOT NULL")
    assert linked > 0
    wrong = scalar(
        db,
        "SELECT count(*) FROM vantage_points AS p "
        "LEFT JOIN vantage_points AS h ON h.id = p.host_id "
        "WHERE p.host_id IS NOT NULL AND (h.id IS NULL OR h.kind != 'star')",
    )
    assert wrong == 0


def test_every_facts_value_is_a_plain_scalar(db: sqlite3.Connection) -> None:
    for point_id, text in db.execute("SELECT id, facts FROM vantage_points"):
        facts: object = json.loads(text)
        assert isinstance(facts, dict), point_id
        for key, value in cast(dict[str, object], facts).items():
            assert value is None or isinstance(value, str | int | float | bool), (point_id, key)


def test_sky_positions_are_on_the_sky(db: sqlite3.Connection) -> None:
    bad = scalar(
        db,
        "SELECT count(*) FROM vantage_points WHERE "
        "(ra_deg IS NOT NULL AND (ra_deg < 0 OR ra_deg >= 360)) OR "
        "(dec_deg IS NOT NULL AND (dec_deg < -90 OR dec_deg > 90))",
    )
    assert bad == 0


# --- coverage ----------------------------------------------------------------------------------


def test_every_century_of_recent_lookback_has_a_vantage_point(db: sqlite3.Connection) -> None:
    """Light from every century back to 3000 BCE (about 5,000 years) arrives at something."""
    empty = [
        start
        for start in range(0, THIS_YEAR + 3000, 100)
        if scalar(
            db,
            "SELECT count(*) FROM vantage_points WHERE lookback_best >= ? AND lookback_best < ?",
            start,
            start + 100,
        )
        == 0
    ]
    assert empty == []


def test_every_power_of_ten_of_deep_time_has_a_vantage_point(db: sqlite3.Connection) -> None:
    """From 10 years to 10 billion years, each factor of ten has at least one place."""
    empty = [
        exponent
        for exponent in range(1, 10)
        if scalar(
            db,
            "SELECT count(*) FROM vantage_points WHERE lookback_best >= ? AND lookback_best < ?",
            10**exponent,
            10 ** (exponent + 1),
        )
        == 0
    ]
    assert empty == []
    assert scalar(db, "SELECT max(lookback_best) FROM vantage_points") > 1e10


KNOWN_HISTORY_GAPS = [-2999, -2899, -2799, -2099, -1999, -1899, -1699, -999, -899]
"""Start years of the centuries since 3000 BCE that have no history entry.

Ian must decide whether to add entries for these (history data is never invented). When one
is added, remove its century from this list: the test below demands the exact set.
"""


def test_the_centuries_without_a_history_entry_are_the_known_ones(db: sqlite3.Connection) -> None:
    """Counts what happened in a century: events, periods that ended in or after it (ongoing
    periods and landmarks that still stand would match every century, so they do not count),
    and landmarks whose construction started in it."""
    empty = [
        start
        for start in range(-2999, THIS_YEAR, 100)
        if scalar(
            db,
            "SELECT (SELECT count(*) FROM events WHERE year >= ?1 AND year < ?2) "
            "+ (SELECT count(*) FROM periods WHERE end_year IS NOT NULL "
            "AND start_year < ?2 AND end_year >= ?1) "
            "+ (SELECT count(*) FROM landmarks WHERE built_start >= ?1 AND built_start < ?2)",
            start,
            start + 100,
        )
        == 0
    ]
    assert empty == KNOWN_HISTORY_GAPS


def test_every_factor_of_ten_of_deep_time_has_a_history_event(db: sqlite3.Connection) -> None:
    """From 1,000 years to 100 billion years before now, each factor of ten has an event."""
    empty = [
        exponent
        for exponent in range(3, 11)
        if scalar(
            db,
            "SELECT count(*) FROM events WHERE year > ? AND year <= ?",
            THIS_YEAR - 10 ** (exponent + 1),
            THIS_YEAR - 10**exponent,
        )
        == 0
    ]
    assert empty == []


def test_history_reaches_back_to_the_first_stars(db: sqlite3.Connection) -> None:
    assert scalar(db, "SELECT min(year) FROM events") < -13_000_000_000


# --- search ------------------------------------------------------------------------------------


def test_the_search_indexes_are_filled_and_find_famous_names(db: sqlite3.Connection) -> None:
    entries = scalar(db, "SELECT count(*) FROM search_entries")
    assert entries > 0
    for index in SEARCH_INDEXES:
        # count(*) on an external-content table reads the content table, so it proves nothing;
        # the _docsize shadow table has one row per document that was actually indexed.
        assert scalar(db, f"SELECT count(*) FROM {index}_docsize") == entries
    found = db.execute(
        "SELECT name FROM search_entries WHERE entry_id IN "
        "(SELECT rowid FROM search_fts WHERE search_fts MATCH 'sirius')"
    ).fetchall()
    assert any("Sirius" in name for (name,) in found)


def test_the_trigram_index_finds_a_misspelled_name(db: sqlite3.Connection) -> None:
    assert scalar(db, "SELECT count(*) FROM search_trigram WHERE search_trigram MATCH 'etelg'") >= 1


def test_unnamed_stars_are_not_searchable(db: sqlite3.Connection) -> None:
    stars = scalar(db, "SELECT count(*) FROM vantage_points WHERE kind = 'star'")
    searchable = scalar(db, "SELECT count(*) FROM search_entries WHERE type = 'vantage_point'")
    assert searchable < stars
    unnamed_and_searchable = scalar(
        db,
        "SELECT count(*) FROM search_entries AS s JOIN vantage_points AS v ON v.id = s.id "
        "WHERE s.type = 'vantage_point' AND v.kind = 'star' AND v.fame = 0",
    )
    assert unnamed_and_searchable == 0


def test_planets_sit_where_their_gaia_host_star_sits(db: sqlite3.Connection) -> None:
    """A planet may differ a little from its star, but never by more than 5% unless the ranges
    overlap (the build replaces a clearly disagreeing archive distance with the star's)."""
    rows = db.execute(
        "SELECT p.id, p.lookback_min, p.lookback_best, p.lookback_max, "
        "h.lookback_min, h.lookback_best, h.lookback_max "
        "FROM vantage_points p JOIN vantage_points h ON h.id = p.host_id "
        "WHERE p.kind = 'exoplanet' AND json_extract(h.facts, '$.distance_source') = 'gaia'"
    ).fetchall()
    assert len(rows) > 500
    bad = [
        row[0]
        for row in rows
        if not (row[1] <= row[6] and row[4] <= row[3]) and abs(row[2] - row[5]) > 0.05 * row[5]
    ]
    assert bad == []


def test_alpha_centauri_is_farther_than_proxima(db: sqlite3.Connection) -> None:
    proxima = scalar(db, "SELECT lookback_best FROM vantage_points WHERE id = 'hip-70890'")
    for star in ("hip-71681", "hip-71683"):
        best = db.execute("SELECT lookback_best FROM vantage_points WHERE id = ?", (star,))
        assert best.fetchone()[0] > proxima
    assert (
        4.3
        < db.execute("SELECT lookback_best FROM vantage_points WHERE id = 'hip-71681'").fetchone()[
            0
        ]
        < 4.45
    )


def test_the_inline_redshift_objects_with_published_positions_have_them(
    db: sqlite3.Connection,
) -> None:
    for point_id in ("j0313-1806", "jades-gs-z14-0", "mom-z14"):
        row = db.execute(
            "SELECT ra_deg, dec_deg, constellation FROM vantage_points WHERE id = ?", (point_id,)
        ).fetchone()
        assert row[0] is not None and row[1] is not None and row[2], point_id
