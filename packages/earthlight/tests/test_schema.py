"""Tests for the database schema: its objects, its constraints, and its agreement with models.py."""

import json
import re
import sqlite3
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, TypeAdapter, ValidationError

from earthlight import schema
from earthlight.lookback import LookbackRange
from earthlight.models import (
    HistoryEvent,
    HistoryPeriod,
    Landmark,
    Name,
    PopulationEstimate,
    SearchType,
    Slug,
    VantageKind,
    VantagePoint,
)
from earthlight.schema import (
    SCHEMA_VERSION,
    TABLES,
    apply_schema,
    create_empty_database,
    rebuild_search_index,
    schema_sql,
)

SOURCE = "https://example.org/source"

EXPECTED_INDEXES = {
    "idx_vantage_points_lookback",
    "idx_vantage_points_kind_lookback",
    "idx_vantage_points_host",
    "idx_vantage_points_fame",
    "idx_vantage_points_magnitude",
    "idx_events_year",
    "idx_periods_span",
    "idx_landmarks_built",
    "idx_landmarks_destroyed",
}

VANTAGE = {
    "id": "vega",
    "name": "Vega",
    "kind": "star",
    "lookback_min": 24.9,
    "lookback_best": 25.0,
    "lookback_max": 25.1,
}
HISTORY = {
    "category": "politics",
    "region": "Europe",
    "summary": "The Ottoman army captured the capital of the Byzantine Empire.",
    "importance": 5,
    "source": SOURCE,
}
EVENT = {"id": "fall-of-constantinople", "name": "Fall of Constantinople", "year": 1453.4} | HISTORY
PERIOD = {
    "id": "ming-dynasty",
    "name": "Ming dynasty",
    "start_year": 1368.0,
    "end_year": 1644.0,
} | HISTORY
LANDMARK = {
    "id": "great-pyramid",
    "name": "Great Pyramid of Giza",
    "built_start": -2560.0,
    "built_end": -2540.0,
    "lat": 29.98,
    "lon": 31.13,
} | HISTORY


@pytest.fixture
def db() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    apply_schema(connection)
    yield connection
    connection.close()


def insert(db: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
    columns = ", ".join(values)
    marks = ", ".join(f":{name}" for name in values)
    db.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", values)


def rejected(db: sqlite3.Connection, table: str, values: dict[str, Any]) -> bool:
    """True if the database refuses the row. Leaves the database unchanged either way."""
    db.execute("SAVEPOINT attempt")
    try:
        insert(db, table, values)
    except sqlite3.IntegrityError:
        return True
    finally:
        db.execute("ROLLBACK TO attempt")
        db.execute("RELEASE attempt")
    return False


# --- objects ----------------------------------------------------------------------------


def test_every_table_and_index_exists(db: sqlite3.Connection) -> None:
    rows = db.execute("SELECT type, name FROM sqlite_master").fetchall()
    tables = {name for kind, name in rows if kind == "table"}
    indexes = {
        name for kind, name in rows if kind == "index" and not name.startswith("sqlite_autoindex")
    }
    assert set(TABLES) <= tables
    assert set(schema.SEARCH_INDEXES) <= tables
    assert indexes == EXPECTED_INDEXES


def index_columns(db: sqlite3.Connection, index: str) -> list[str]:
    return [row[2] for row in db.execute(f"PRAGMA index_info({index})")]


def test_indexes_cover_the_columns_the_queries_use(db: sqlite3.Connection) -> None:
    assert index_columns(db, "idx_vantage_points_lookback") == ["lookback_min", "lookback_max"]
    assert index_columns(db, "idx_vantage_points_kind_lookback") == [
        "kind",
        "lookback_min",
        "lookback_max",
    ]
    assert index_columns(db, "idx_vantage_points_host") == ["host_id"]
    assert index_columns(db, "idx_vantage_points_fame") == ["fame"]
    assert index_columns(db, "idx_vantage_points_magnitude") == ["magnitude"]
    assert index_columns(db, "idx_events_year") == ["year"]
    assert index_columns(db, "idx_periods_span") == ["start_year", "end_year"]
    assert index_columns(db, "idx_landmarks_built") == ["built_start"]
    assert index_columns(db, "idx_landmarks_destroyed") == ["destroyed"]


def test_sparse_columns_get_partial_indexes(db: sqlite3.Connection) -> None:
    # A partial index skips the many rows with no value, which keeps the database small.
    partial = {
        name
        for table in ("vantage_points", "events", "periods", "landmarks")
        for _, name, _, _, is_partial in db.execute(f"PRAGMA index_list({table})")
        if is_partial
    }
    assert partial == {
        "idx_vantage_points_host",
        "idx_vantage_points_fame",
        "idx_vantage_points_magnitude",
        "idx_landmarks_destroyed",
    }


def test_ordinary_tables_are_strict(db: sqlite3.Connection) -> None:
    strict = {row[0] for row in db.execute("SELECT name FROM pragma_table_list WHERE strict = 1")}
    assert set(TABLES) <= strict


def test_a_new_database_has_only_its_version(db: sqlite3.Connection) -> None:
    for table in TABLES:
        expected = 1 if table == "meta" else 0
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == expected, table
    assert db.execute("SELECT key, value FROM meta").fetchall() == [
        ("schema_version", str(SCHEMA_VERSION))
    ]


def test_the_version_is_stored_twice(db: sqlite3.Connection) -> None:
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_applying_the_schema_twice_fails(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.OperationalError):
        apply_schema(db)


def test_a_too_old_sqlite_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 37, 2))
    monkeypatch.setattr(sqlite3, "sqlite_version", "3.37.2")
    with pytest.raises(RuntimeError, match=r"needs SQLite 3\.38\.0 or newer.*3\.37\.2"):
        apply_schema(sqlite3.connect(":memory:"))


def test_the_schema_text_is_packaged() -> None:
    text = schema_sql()
    assert text.startswith("-- Earthlight database schema, version 1")
    assert "CREATE TABLE vantage_points" in text


def test_create_empty_database_writes_a_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "earthlight.db"
    create_empty_database(path)
    assert path.exists()
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
        assert connection.execute("SELECT count(*) FROM vantage_points").fetchone() == (0,)
    finally:
        connection.close()


def test_create_empty_database_will_not_overwrite_by_default(tmp_path: Path) -> None:
    path = tmp_path / "earthlight.db"
    path.write_text("precious", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_empty_database(path)
    assert path.read_text(encoding="utf-8") == "precious"
    create_empty_database(path, overwrite=True)
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)


# --- vantage_points constraints ---------------------------------------------------------


def test_a_valid_vantage_point_is_accepted(db: sqlite3.Connection) -> None:
    insert(db, "vantage_points", VANTAGE)
    assert db.execute("SELECT fame, facts, host_id FROM vantage_points").fetchone() == (
        0,
        "{}",
        None,
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"id": ""},
        {"id": "Vega"},
        {"id": "-vega"},
        {"id": "vega-"},
        {"id": "ve--ga"},
        {"id": "ve ga"},
        {"id": "ve_ga"},
        {"id": "vega\n"},
        {"id": "véga"},
        {"id": "a" * 101},
        {"name": ""},
        {"name": " Vega"},
        {"name": "Vega\n"},
        {"name": "x" * 201},
        {"kind": "comet"},
        {"kind": "Star"},
        {"lookback_min": 26.0},  # min above best
        {"lookback_max": 24.0},  # max below best
        {"lookback_min": -1.0, "lookback_best": 0.0},
        {"lookback_max": float("inf")},
        {"lookback_max": 1e15},
        {"lookback_min": None},
        {"lookback_best": float("nan")},  # SQLite stores NaN as NULL
        {"ra_deg": 10.0},  # needs dec_deg too
        {"dec_deg": 10.0},
        {"ra_deg": 360.0, "dec_deg": 0.0},
        {"ra_deg": -0.1, "dec_deg": 0.0},
        {"ra_deg": 10.0, "dec_deg": 90.1},
        {"ra_deg": 10.0, "dec_deg": -90.1},
        {"fame": -1},
        {"fame": 6},
        {"magnitude": float("inf")},
        {"constellation": ""},
        {"constellation": " Orion"},
        {"wikipedia": ""},
        {"facts": "not json"},
        {"facts": "[1, 2]"},
        {"facts": "42"},
        {"facts": "null"},
        {"host_id": "vega"},  # a star cannot have a host
        {"kind": "exoplanet", "host_id": "vega"},  # an exoplanet cannot host itself
        {"kind": "exoplanet", "host_id": "no-such-star"},  # the host must exist
    ],
)
def test_bad_vantage_points_are_rejected(db: sqlite3.Connection, bad: dict[str, Any]) -> None:
    assert rejected(db, "vantage_points", VANTAGE | bad)


@pytest.mark.parametrize(
    "good",
    [
        {"id": "m31"},
        {"id": "proxima-cen-b", "kind": "exoplanet"},
        {"id": "a" * 100},
        {"name": "x" * 200},
        {"lookback_min": 0.0, "lookback_best": 0.0, "lookback_max": 0.0},
        {"lookback_max": 13.8e9},
        {"ra_deg": 0.0, "dec_deg": -90.0},
        {"ra_deg": 359.999999, "dec_deg": 90.0},
        {"fame": 5},
        {"magnitude": -1.44},
        {"constellation": "Ursa Minor"},
        {"facts": '{"spectral_type": "A0V", "planets": 1, "mass": 2.1, "ok": false, "x": null}'},
    ],
)
def test_edge_vantage_points_are_accepted(db: sqlite3.Connection, good: dict[str, Any]) -> None:
    assert not rejected(db, "vantage_points", VANTAGE | good)


def test_ids_are_unique(db: sqlite3.Connection) -> None:
    insert(db, "vantage_points", VANTAGE)
    assert rejected(db, "vantage_points", VANTAGE)


def test_an_exoplanet_can_point_at_its_host(db: sqlite3.Connection) -> None:
    insert(db, "vantage_points", VANTAGE | {"id": "proxima-cen"})
    planet = VANTAGE | {"id": "proxima-cen-b", "kind": "exoplanet", "host_id": "proxima-cen"}
    assert not rejected(db, "vantage_points", planet)


def test_only_exoplanets_can_have_a_host_even_when_the_host_exists(db: sqlite3.Connection) -> None:
    insert(db, "vantage_points", VANTAGE | {"id": "a-star"})
    # The host exists, so only the kind rule can reject this.
    assert rejected(db, "vantage_points", VANTAGE | {"id": "b-star", "host_id": "a-star"})
    assert rejected(
        db, "vantage_points", VANTAGE | {"id": "b-gal", "kind": "galaxy", "host_id": "a-star"}
    )
    assert not rejected(
        db, "vantage_points", VANTAGE | {"id": "b-planet", "kind": "exoplanet", "host_id": "a-star"}
    )


def test_a_host_cannot_be_deleted_while_it_has_planets(db: sqlite3.Connection) -> None:
    insert(db, "vantage_points", VANTAGE | {"id": "proxima-cen"})
    insert(
        db, "vantage_points", VANTAGE | {"id": "b", "kind": "exoplanet", "host_id": "proxima-cen"}
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM vantage_points WHERE id = 'proxima-cen'")


# --- exoplanets -------------------------------------------------------------------------


def test_exoplanet_details_need_an_exoplanet_vantage_point(db: sqlite3.Connection) -> None:
    insert(db, "vantage_points", VANTAGE | {"id": "a-star"})
    insert(db, "vantage_points", VANTAGE | {"id": "a-planet", "kind": "exoplanet"})
    details = {"nasa_name": "Proxima Cen b", "host_name": "Proxima Cen"}
    assert not rejected(db, "exoplanets", {"vantage_id": "a-planet"} | details)
    assert rejected(db, "exoplanets", {"vantage_id": "a-star"} | details)  # not an exoplanet
    assert rejected(db, "exoplanets", {"vantage_id": "missing"} | details)
    assert rejected(db, "exoplanets", {"vantage_id": "a-planet", "kind": "star"} | details)


@pytest.mark.parametrize(
    "bad",
    [
        {"nasa_name": ""},
        {"host_name": ""},
        {"discovery_year": 1800},
        {"discovery_year": 2300},
        {"radius_earth": 0.0},
        {"radius_earth": -1.0},
        {"mass_earth": 0.0},
        {"orbital_period_days": 0.0},
        {"orbital_period_days": float("inf")},
        {"controversial": 2},
        {"discovery_method": ""},
    ],
)
def test_bad_exoplanet_details_are_rejected(db: sqlite3.Connection, bad: dict[str, Any]) -> None:
    insert(db, "vantage_points", VANTAGE | {"id": "a-planet", "kind": "exoplanet"})
    row = {"vantage_id": "a-planet", "nasa_name": "X b", "host_name": "X"} | bad
    assert rejected(db, "exoplanets", row)


def test_deleting_an_exoplanet_removes_its_details(db: sqlite3.Connection) -> None:
    insert(db, "vantage_points", VANTAGE | {"id": "a-planet", "kind": "exoplanet"})
    insert(db, "exoplanets", {"vantage_id": "a-planet", "nasa_name": "X b", "host_name": "X"})
    db.execute("DELETE FROM vantage_points WHERE id = 'a-planet'")
    assert db.execute("SELECT count(*) FROM exoplanets").fetchone() == (0,)


# --- history and population constraints -------------------------------------------------

_BAD_HISTORY = [
    {"id": "Bad Id"},
    {"name": ""},
    {"category": ""},
    {"region": " Europe"},
    {"summary": ""},
    {"summary": "x" * 1001},
    {"importance": 0},
    {"importance": 6},
    {"wikipedia": ""},
    {"source": "ftp://example.org/x"},
    {"source": "http://"},
    {"source": "https://"},
    {"source": "example.org"},
    {"source": "https://example.org/a b"},
    {"source": "https://example.org/a\tb"},
    {"source": "https://example.org/" + "x" * 500},
    {"source": None},
]


@pytest.mark.parametrize("bad", [*_BAD_HISTORY, {"year": float("inf")}, {"year_uncertainty": -1.0}])
def test_bad_events_are_rejected(db: sqlite3.Connection, bad: dict[str, Any]) -> None:
    assert rejected(db, "events", EVENT | bad)


@pytest.mark.parametrize(
    "good", [{"year": -4.5e9}, {"year_uncertainty": 0.0}, {"wikipedia": "Fall"}]
)
def test_edge_events_are_accepted(db: sqlite3.Connection, good: dict[str, Any]) -> None:
    assert not rejected(db, "events", EVENT | good)


@pytest.mark.parametrize("bad", [*_BAD_HISTORY, {"start_year": 1700.0}, {"end_year": 1000.0}])
def test_bad_periods_are_rejected(db: sqlite3.Connection, bad: dict[str, Any]) -> None:
    assert rejected(db, "periods", PERIOD | bad)


def test_a_period_may_start_and_end_together(db: sqlite3.Connection) -> None:
    assert not rejected(db, "periods", PERIOD | {"start_year": 1500.0, "end_year": 1500.0})


@pytest.mark.parametrize(
    "bad",
    [
        *_BAD_HISTORY,
        {"built_start": -2500.0},  # started after it finished
        {"destroyed": -3000.0},  # destroyed before it was finished
        {"lat": 90.1},
        {"lat": -91.0},
        {"lon": 180.1},
        {"lon": -181.0},
        {"lat": None},
    ],
)
def test_bad_landmarks_are_rejected(db: sqlite3.Connection, bad: dict[str, Any]) -> None:
    assert rejected(db, "landmarks", LANDMARK | bad)


@pytest.mark.parametrize(
    "good",
    [
        {"destroyed": None},
        {"destroyed": 1301.0},
        {"built_start": -2550.0, "built_end": -2550.0, "destroyed": -2550.0},
        {"lat": -90.0, "lon": -180.0},
    ],
)
def test_edge_landmarks_are_accepted(db: sqlite3.Connection, good: dict[str, Any]) -> None:
    assert not rejected(db, "landmarks", LANDMARK | good)


def test_population_rules(db: sqlite3.Connection) -> None:
    assert not rejected(db, "population", {"year": 1800.0, "people": 1_000_000_000})
    assert not rejected(db, "population", {"year": 1900.0, "people": 0, "source": SOURCE})
    insert(db, "population", {"year": 2000.0, "people": 6_100_000_000})
    assert rejected(db, "population", {"year": 2000.0, "people": 1})  # one estimate per year
    assert rejected(db, "population", {"year": 2010.0, "people": -1})
    assert rejected(db, "population", {"year": float("inf"), "people": 1})
    assert rejected(db, "population", {"year": 2010.0, "people": 1, "source": "not a url"})


# --- search -----------------------------------------------------------------------------


def add_entries(db: sqlite3.Connection) -> None:
    entries = [
        ("vantage_point", "betelgeuse", "Betelgeuse", "alf Ori\nHIP 27989", "Star in Orion"),
        ("vantage_point", "chason", "Chasoň", "", "Star in Corvus"),
        ("event", "fall-of-rome", "Fall of Rome", "", "476 CE"),
        ("period", "ming-dynasty", "Ming dynasty", "", "1368 to 1644 CE"),
    ]
    db.executemany(
        "INSERT INTO search_entries (type, id, name, aliases, description) VALUES (?, ?, ?, ?, ?)",
        entries,
    )
    rebuild_search_index(db)


def search(db: sqlite3.Connection, index: str, query: str) -> list[str]:
    rows = db.execute(
        f"SELECT e.name FROM {index} JOIN search_entries e ON e.entry_id = {index}.rowid "
        f"WHERE {index} MATCH ? ORDER BY e.entry_id",
        (query,),
    ).fetchall()
    return [name for (name,) in rows]


def test_word_search_folds_case_and_accents(db: sqlite3.Connection) -> None:
    add_entries(db)
    assert search(db, "search_fts", "betelgeuse") == ["Betelgeuse"]
    assert search(db, "search_fts", "BETELGEUSE") == ["Betelgeuse"]
    assert search(db, "search_fts", "Chason") == ["Chasoň"]
    assert search(db, "search_fts", "chasoň") == ["Chasoň"]


def test_word_search_supports_prefixes_aliases_and_descriptions(db: sqlite3.Connection) -> None:
    add_entries(db)
    assert search(db, "search_fts", "bet*") == ["Betelgeuse"]
    assert search(db, "search_fts", "be*") == ["Betelgeuse"]
    assert search(db, "search_fts", "aliases: alf") == ["Betelgeuse"]
    assert search(db, "search_fts", "HIP 27989") == ["Betelgeuse"]
    assert search(db, "search_fts", "description: orion") == ["Betelgeuse"]
    assert search(db, "search_fts", "fall rome") == ["Fall of Rome"]


def test_trigram_search_finds_substrings_and_typos(db: sqlite3.Connection) -> None:
    add_entries(db)
    assert search(db, "search_trigram", "telgeu") == ["Betelgeuse"]
    assert search(db, "search_trigram", "alf Ori") == ["Betelgeuse"]
    # Did-you-mean: a misspelling shares most of its three-letter pieces with the real name.
    typo = "Betelguese"
    pieces = " OR ".join(f'"{typo[i : i + 3].lower()}"' for i in range(len(typo) - 2))
    assert "Betelgeuse" in search(db, "search_trigram", pieces)
    assert "Ming dynasty" not in search(db, "search_trigram", pieces)


def test_searches_find_nothing_until_the_index_is_rebuilt(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO search_entries (type, id, name) "
        "VALUES ('event', 'fall-of-rome', 'Fall of Rome')"
    )
    assert search(db, "search_fts", "rome") == []
    rebuild_search_index(db)
    assert search(db, "search_fts", "rome") == ["Fall of Rome"]
    rebuild_search_index(db)  # safe to repeat
    assert search(db, "search_fts", "rome") == ["Fall of Rome"]


def test_search_entry_rules(db: sqlite3.Connection) -> None:
    base = {"type": "event", "id": "fall-of-rome", "name": "Fall of Rome"}
    assert not rejected(db, "search_entries", base)
    insert(db, "search_entries", base)
    assert rejected(db, "search_entries", base)  # (type, id) is unique
    assert not rejected(db, "search_entries", base | {"type": "period"})  # same id, other type
    assert rejected(db, "search_entries", base | {"type": "star"})
    assert rejected(db, "search_entries", base | {"id": "Bad Id"})
    assert rejected(db, "search_entries", base | {"id": "x", "name": ""})


# --- agreement with models.py -----------------------------------------------------------


def columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def check_list(db: sqlite3.Connection, table: str, column: str) -> set[str]:
    sql = db.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
    match = re.search(rf"{column}\s+IN\s*\(([^)]*)\)", sql)
    assert match, f"no IN list for {table}.{column}"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_vantage_kinds_match_the_models(db: sqlite3.Connection) -> None:
    assert check_list(db, "vantage_points", "kind") == {k.value for k in VantageKind}


def test_search_types_match_the_models(db: sqlite3.Connection) -> None:
    assert check_list(db, "search_entries", "type") == {t.value for t in SearchType}


def model_columns(model: type[BaseModel], renames: dict[str, list[str]] | None = None) -> set[str]:
    renames = renames or {}
    result: set[str] = set()
    for name in model.model_fields:
        result.update(renames.get(name, [name]))
    return result


def test_every_model_field_has_a_column_and_the_reverse(db: sqlite3.Connection) -> None:
    lookback = ["lookback_min", "lookback_best", "lookback_max"]
    assert columns(db, "vantage_points") == model_columns(VantagePoint, {"lookback": lookback})
    assert columns(db, "events") == model_columns(HistoryEvent)
    assert columns(db, "periods") == model_columns(
        HistoryPeriod, {"start": ["start_year"], "end": ["end_year"]}
    )
    assert columns(db, "landmarks") == model_columns(Landmark)
    assert columns(db, "population") == model_columns(PopulationEstimate)


def test_models_survive_a_round_trip_through_the_database(db: sqlite3.Connection) -> None:
    point = VantagePoint(
        id="vega",
        name="Vega",
        kind=VantageKind.STAR,
        lookback=LookbackRange(24.9, 25.0, 25.1),
        magnitude=0.03,
        constellation="Lyra",
        ra_deg=279.23,
        dec_deg=38.78,
        fame=4,
        wikipedia="Vega",
        facts={"spectral_type": "A0V", "planets": 1, "mass": 2.1, "variable": False, "x": None},
    )
    insert(
        db,
        "vantage_points",
        {
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
            "wikipedia": point.wikipedia,
            "facts": json.dumps(dict(point.facts)),
        },
    )
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM vantage_points WHERE id = 'vega'").fetchone()
    loaded = VantagePoint(
        id=row["id"],
        name=row["name"],
        kind=row["kind"],
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
    assert loaded == point
    assert type(loaded.facts["planets"]) is int
    assert type(loaded.facts["variable"]) is bool


def test_history_models_survive_a_round_trip(db: sqlite3.Connection) -> None:
    event = HistoryEvent.model_validate(
        {k: v for k, v in EVENT.items()} | {"year_uncertainty": 0.5, "wikipedia": "Fall"}
    )
    period = HistoryPeriod.model_validate(
        {k: v for k, v in PERIOD.items() if k not in ("start_year", "end_year")}
        | {"start": PERIOD["start_year"], "end": PERIOD["end_year"]}
    )
    landmark = Landmark.model_validate(LANDMARK | {"destroyed": 1301.0})
    insert(db, "events", event.model_dump())
    insert(
        db,
        "periods",
        period.model_dump(exclude={"start", "end"})
        | {"start_year": period.start, "end_year": period.end},
    )
    insert(db, "landmarks", landmark.model_dump())
    db.row_factory = sqlite3.Row
    assert HistoryEvent.model_validate(dict(db.execute("SELECT * FROM events").fetchone())) == event
    stored = dict(db.execute("SELECT * FROM periods").fetchone())
    stored["start"], stored["end"] = stored.pop("start_year"), stored.pop("end_year")
    assert HistoryPeriod.model_validate(stored) == period
    assert (
        Landmark.model_validate(dict(db.execute("SELECT * FROM landmarks").fetchone())) == landmark
    )


# The next tests compare the models' rules with the database's rules on random input. They share
# one connection and roll back each attempt, so they stay fast.


@cache
def property_db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    apply_schema(connection)
    return connection


def database_accepts(table: str, values: dict[str, Any]) -> bool:
    db = property_db()
    db.execute("BEGIN")
    try:
        insert(db, table, values)
    except sqlite3.IntegrityError:
        return False
    finally:
        db.execute("ROLLBACK")
    return True


def model_accepts(adapter: TypeAdapter[str], value: str) -> bool:
    try:
        return adapter.validate_python(value) == value
    except ValidationError:
        return False


@given(st.text(alphabet="ab-0_ AZ\né", max_size=8))
def test_slug_rules_agree(candidate: str) -> None:
    assert database_accepts("vantage_points", VANTAGE | {"id": candidate}) == model_accepts(
        TypeAdapter(Slug), candidate
    )


@given(st.text(alphabet="ab \t\n.", max_size=6))
def test_name_rules_agree(candidate: str) -> None:
    # The model strips whitespace on the way in; the database requires the value already stripped.
    assert database_accepts("vantage_points", VANTAGE | {"name": candidate}) == model_accepts(
        TypeAdapter(Name), candidate
    )


_lookback_number = st.one_of(
    st.floats(min_value=-5, max_value=100), st.sampled_from([0.0, 1e14, float("inf"), 1e15])
)


@given(_lookback_number, _lookback_number, _lookback_number)
def test_lookback_rules_agree(low: float, best: float, high: float) -> None:
    row = VANTAGE | {"lookback_min": low, "lookback_best": best, "lookback_max": high}
    try:
        LookbackRange(low, best, high)
        model_ok = high < 1e15
    except ValueError:
        model_ok = False
    assert database_accepts("vantage_points", row) == model_ok


@given(
    st.one_of(st.none(), st.floats(-5, 365)),
    st.one_of(st.none(), st.floats(-95, 95)),
    st.integers(-2, 7),
)
def test_sky_position_and_fame_rules_agree(ra: float | None, dec: float | None, fame: int) -> None:
    row = VANTAGE | {"ra_deg": ra, "dec_deg": dec, "fame": fame}
    try:
        VantagePoint.model_validate(
            {
                "id": "vega",
                "name": "Vega",
                "kind": "star",
                "lookback": {"minimum": 24.9, "best": 25.0, "maximum": 25.1},
                "ra_deg": ra,
                "dec_deg": dec,
                "fame": fame,
            }
        )
        model_ok = True
    except ValidationError:
        model_ok = False
    assert database_accepts("vantage_points", row) == model_ok
