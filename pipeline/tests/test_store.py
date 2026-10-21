"""Tests for writing stars into the database."""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from earthlight.lookback import LookbackRange
from earthlight.models import VantageKind, VantagePoint
from earthlight.schema import SCHEMA_VERSION, create_empty_database
from earthlight_pipeline.stars import HipparcosStar, SearchEntry, build_stars, search_entry
from earthlight_pipeline.store import (
    load_stars,
    open_database,
    replace_stars,
    set_meta,
    vantage_row,
)


def make_stars() -> list[VantagePoint]:
    base = {
        "ra_deg": 88.79,
        "dec_deg": 7.41,
        "vmag": 0.45,
        "spectral_type": "M2Ib",
        "hd": 39801,
        "parallax_mas": 6.55,
        "parallax_error_mas": 0.83,
    }
    stars = [
        HipparcosStar(hip=27989, **base),  # type: ignore[arg-type]
        HipparcosStar(hip=1, **(base | {"vmag": 9.0, "hd": None})),  # type: ignore[arg-type]
    ]
    return build_stars(stars, {}, {27989: "Betelgeuse"}).stars


def entries_for(stars: list[VantagePoint]) -> list[SearchEntry]:
    return [entry for star in stars if (entry := search_entry(star)) is not None]


@pytest.fixture
def database(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = open_database(tmp_path / "earthlight.db")
    yield connection
    connection.close()


def test_open_database_creates_the_file_with_the_schema(tmp_path: Path) -> None:
    path = tmp_path / "new" / "earthlight.db"
    connection = open_database(path)
    try:
        assert path.exists()
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM vantage_points").fetchone() == (0,)
    finally:
        connection.close()


def test_open_database_reuses_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "earthlight.db"
    first = open_database(path)
    set_meta(first, "note", "kept")
    first.close()
    second = open_database(path)
    try:
        assert second.execute("SELECT value FROM meta WHERE key = 'note'").fetchone() == ("kept",)
    finally:
        second.close()


def test_open_database_refuses_another_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "earthlight.db"
    create_empty_database(path)
    connection = sqlite3.connect(path)
    connection.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
    connection.commit()
    connection.close()
    with pytest.raises(ValueError, match=f"schema version 999, expected {SCHEMA_VERSION}"):
        open_database(path)


def test_set_meta_adds_and_replaces(database: sqlite3.Connection) -> None:
    set_meta(database, "data_license", "CC BY-NC 3.0 IGO")
    set_meta(database, "data_license", "changed")
    assert database.execute("SELECT value FROM meta WHERE key = 'data_license'").fetchone() == (
        "changed",
    )


def test_vantage_row_has_one_value_per_column(database: sqlite3.Connection) -> None:
    star = make_stars()[0]
    row = vantage_row(star)
    columns = {r[1] for r in database.execute("PRAGMA table_info(vantage_points)")}
    assert set(row) == columns
    assert row["kind"] == "star"
    assert row["lookback_min"] == star.lookback.minimum
    assert json.loads(str(row["facts"])) == dict(star.facts)


def test_stars_round_trip_through_the_database(database: sqlite3.Connection) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    assert load_stars(database) == sorted(stars, key=lambda s: s.id)


def test_replacing_stars_twice_gives_the_same_result(database: sqlite3.Connection) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    replace_stars(database, stars, entries_for(stars))
    assert database.execute("SELECT count(*) FROM vantage_points").fetchone() == (2,)
    assert database.execute("SELECT count(*) FROM search_entries").fetchone() == (1,)


def test_replacing_stars_removes_stars_that_are_no_longer_built(
    database: sqlite3.Connection,
) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    replace_stars(database, stars[:1], entries_for(stars[:1]))
    assert [s.id for s in load_stars(database)] == [stars[0].id]


def test_replacing_stars_leaves_other_vantage_points_alone(database: sqlite3.Connection) -> None:
    planet = VantagePoint(
        id="mars",
        name="Mars",
        kind=VantageKind.PLANET,
        lookback=LookbackRange(0.00002, 0.00003, 0.00004),
    )
    database.execute(
        "INSERT INTO vantage_points (id, name, kind, lookback_min, lookback_best, lookback_max) "
        "VALUES (?, ?, 'planet', ?, ?, ?)",
        (planet.id, planet.name, 0.00002, 0.00003, 0.00004),
    )
    database.commit()
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    kinds = dict(database.execute("SELECT id, kind FROM vantage_points").fetchall())
    assert kinds["mars"] == "planet" and kinds["hip-27989"] == "star"


def test_search_finds_a_stored_star_by_name_and_alias(database: sqlite3.Connection) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    for query in ("betelgeuse", "BETEL*", "HD 39801", "aliases: HIP"):
        rows = database.execute(
            "SELECT e.id FROM search_fts JOIN search_entries e ON e.entry_id = search_fts.rowid "
            "WHERE search_fts MATCH ?",
            (query,),
        ).fetchall()
        assert rows == [("hip-27989",)], query
    typo = database.execute(
        "SELECT e.id FROM search_trigram "
        "JOIN search_entries e ON e.entry_id = search_trigram.rowid "
        "WHERE search_trigram MATCH 'telgeu'"
    ).fetchall()
    assert typo == [("hip-27989",)]


def test_unnamed_stars_are_stored_but_not_searchable(database: sqlite3.Connection) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    assert database.execute(
        "SELECT count(*) FROM vantage_points WHERE id = 'hip-1'"
    ).fetchone() == (1,)
    assert database.execute(
        "SELECT count(*) FROM search_entries WHERE id = 'hip-1'"
    ).fetchone() == (0,)


def test_a_failed_replacement_changes_nothing(database: sqlite3.Connection) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    duplicate = entries_for(stars) * 2  # the same search entry twice breaks a unique rule
    with pytest.raises(RuntimeError, match="could not replace the stars"):
        replace_stars(database, stars[:1], duplicate)
    assert [s.id for s in load_stars(database)] == sorted(s.id for s in stars)  # all still there
    assert database.execute("SELECT count(*) FROM search_entries").fetchone() == (1,)


def test_stars_with_planets_cannot_be_replaced(database: sqlite3.Connection) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    database.execute(
        "INSERT INTO vantage_points "
        "(id, name, kind, lookback_min, lookback_best, lookback_max, host_id) "
        "VALUES ('hip-27989-b', 'Planet', 'exoplanet', 1, 1, 1, 'hip-27989')"
    )
    database.commit()
    with pytest.raises(RuntimeError, match="rebuild the whole database"):
        replace_stars(database, stars, entries_for(stars))
    assert len(load_stars(database)) == 2


def test_replacing_with_no_stars_empties_the_star_tables(database: sqlite3.Connection) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    replace_stars(database, [], [])
    assert load_stars(database) == []
    assert database.execute("SELECT count(*) FROM search_entries").fetchone() == (0,)


def test_the_file_shrinks_when_fewer_stars_are_stored(tmp_path: Path) -> None:
    path = tmp_path / "earthlight.db"
    connection = open_database(path)
    try:
        many = build_stars(
            [
                HipparcosStar(
                    hip=n,
                    ra_deg=10.0,
                    dec_deg=20.0,
                    vmag=5.0,
                    spectral_type="A0V",
                    hd=n,
                    parallax_mas=50.0,
                    parallax_error_mas=1.0,
                )
                for n in range(1, 3001)
            ],
            {},
            {},
        ).stars
        replace_stars(connection, many, [])
        big = path.stat().st_size
        replace_stars(connection, many[:10], [])
        small = path.stat().st_size
    finally:
        connection.close()
    assert big > 5 * small  # without VACUUM the file would stay as large as it was
