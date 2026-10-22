"""Tests for writing stars into the database."""

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from earthlight.lookback import LookbackRange
from earthlight.models import PopulationEstimate, VantageKind, VantagePoint
from earthlight.schema import SCHEMA_VERSION, create_empty_database, rebuild_search_index
from earthlight_pipeline import store
from earthlight_pipeline.deep_sky import CuratedObject, DeepSkyRecord, build_deep_sky
from earthlight_pipeline.exoplanets import (
    ArchivePlanet,
    ExoplanetRecord,
    StarIndex,
    build_exoplanets,
)
from earthlight_pipeline.history import load_curated_history
from earthlight_pipeline.stars import HipparcosStar, SearchEntry, build_stars, search_entry
from earthlight_pipeline.store import (
    finish_database,
    load_deep_sky,
    load_exoplanets,
    load_history,
    load_population,
    load_stars,
    open_database,
    record_build_info,
    replace_deep_sky,
    replace_exoplanets,
    replace_history,
    replace_population,
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


# --- exoplanets ------------------------------------------------------------------------------


def make_planet_records(host_id: str | None = None) -> list[ExoplanetRecord]:
    planets = [
        ArchivePlanet(
            name=name,
            host_name="Test",
            controversial=name == "Test c",
            distance_pc=10.0,
            error_upper_pc=1.0,
            error_lower_pc=-1.0,
            vmag=9.5,
            ra_deg=100.0,
            dec_deg=20.0,
            gaia_host_id=None,
            hip=27989 if host_id else None,
            discovery_year=2010,
            discovery_method="Transit",
            planets_in_system=3,
            radius_earth=1.5,
            mass_earth=None,
            orbital_period_days=12.0,
        )
        for name in ("Test b", "Test c")
    ]
    index = StarIndex({27989: host_id} if host_id else {}, {})
    return build_exoplanets(planets, {}, index).records


def test_exoplanets_are_stored_with_their_details_and_search_entries(
    database: sqlite3.Connection,
) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    records = make_planet_records(host_id="hip-27989")
    replace_exoplanets(database, records)
    loaded = {p.id: p for p in load_exoplanets(database)}
    assert sorted(loaded) == ["test-b", "test-c"]
    assert loaded["test-b"].host_id == "hip-27989"
    assert loaded["test-b"] == records[0].point
    rows = database.execute(
        "SELECT vantage_id, nasa_name, host_name, discovery_year, discovery_method, radius_earth, "
        "mass_earth, orbital_period_days, controversial FROM exoplanets ORDER BY vantage_id"
    ).fetchall()
    assert rows == [
        ("test-b", "Test b", "Test", 2010, "Transit", 1.5, None, 12.0, 0),
        ("test-c", "Test c", "Test", 2010, "Transit", 1.5, None, 12.0, 1),
    ]
    found = database.execute(
        "SELECT e.id FROM search_fts JOIN search_entries e ON e.entry_id = search_fts.rowid "
        "WHERE search_fts MATCH 'test' ORDER BY e.id"
    ).fetchall()
    assert ("test-b",) in found and ("test-c",) in found


def test_replacing_exoplanets_twice_gives_the_same_result(database: sqlite3.Connection) -> None:
    records = make_planet_records()
    replace_exoplanets(database, records)
    replace_exoplanets(database, records)
    assert database.execute("SELECT count(*) FROM exoplanets").fetchone() == (2,)
    assert database.execute("SELECT count(*) FROM vantage_points").fetchone() == (2,)
    assert database.execute("SELECT count(*) FROM search_entries").fetchone() == (2,)


def test_replacing_exoplanets_leaves_stars_alone(database: sqlite3.Connection) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    replace_exoplanets(database, make_planet_records(host_id="hip-27989"))
    replace_exoplanets(database, [])
    assert [s.id for s in load_stars(database)] == sorted(s.id for s in stars)
    assert load_exoplanets(database) == []
    assert database.execute("SELECT count(*) FROM exoplanets").fetchone() == (0,)
    assert database.execute("SELECT count(*) FROM search_entries").fetchone() == (1,)  # the star


def test_the_file_shrinks_when_fewer_exoplanets_are_stored(tmp_path: Path) -> None:
    planets = [
        ArchivePlanet(
            name=f"Many {n} b",
            host_name=f"Many {n}",
            controversial=False,
            distance_pc=10.0,
            error_upper_pc=1.0,
            error_lower_pc=-1.0,
            vmag=9.5,
            ra_deg=100.0,
            dec_deg=20.0,
            gaia_host_id=None,
            hip=None,
            discovery_year=2010,
            discovery_method="Transit",
            planets_in_system=1,
            radius_earth=1.5,
            mass_earth=None,
            orbital_period_days=12.0,
        )
        for n in range(3000)
    ]
    many = build_exoplanets(planets, {}, StarIndex({}, {})).records
    path = tmp_path / "earthlight.db"
    connection = open_database(path)
    try:
        replace_exoplanets(connection, many)
        big = path.stat().st_size
        replace_exoplanets(connection, many[:10])
        small = path.stat().st_size
    finally:
        connection.close()
    assert big > 5 * small  # without VACUUM the file would stay as large as it was


def test_a_planet_with_a_missing_host_changes_nothing(database: sqlite3.Connection) -> None:
    replace_exoplanets(database, make_planet_records())
    with pytest.raises(RuntimeError, match="could not store the exoplanets"):
        replace_exoplanets(database, make_planet_records(host_id="hip-no-such-star"))
    assert [p.id for p in load_exoplanets(database)] == ["test-b", "test-c"]  # the old ones remain


def test_stars_are_replaced_only_if_no_planet_depends_on_them(database: sqlite3.Connection) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    replace_exoplanets(database, make_planet_records(host_id="hip-27989"))
    with pytest.raises(RuntimeError, match="rebuild the whole database"):
        replace_stars(database, stars, entries_for(stars))
    assert len(load_exoplanets(database)) == 2


# --- deep-sky objects ------------------------------------------------------------------------


def make_deep_sky_records(count: int = 3) -> list[DeepSkyRecord]:
    objects = [
        CuratedObject.model_validate(
            {
                "id": f"object-{n}",
                "name": f"Object {n}",
                "kind": ("galaxy", "quasar", "galaxy_cluster")[n % 3],
                "fame": 2,
                "aliases": [f"Alias {n}"],
                "inline": {"redshift": 1.0 + n / 1000, "error": 0.01, "source": "https://a.org/x"},
            }
        )
        for n in range(count)
    ]
    return build_deep_sky(objects, {}).records


def test_deep_sky_objects_are_stored_and_searchable(database: sqlite3.Connection) -> None:
    records = make_deep_sky_records()
    replace_deep_sky(database, records)
    loaded = load_deep_sky(database)
    assert [p.id for p in loaded] == ["object-0", "object-1", "object-2"]
    assert loaded[1] == records[1].point
    found = database.execute(
        "SELECT e.id FROM search_fts JOIN search_entries e ON e.entry_id = search_fts.rowid "
        "WHERE search_fts MATCH 'alias' ORDER BY e.id"
    ).fetchall()
    assert found == [("object-0",), ("object-1",), ("object-2",)]


def test_replacing_deep_sky_twice_gives_the_same_result(database: sqlite3.Connection) -> None:
    records = make_deep_sky_records()
    replace_deep_sky(database, records)
    replace_deep_sky(database, records)
    assert database.execute("SELECT count(*) FROM vantage_points").fetchone() == (3,)
    assert database.execute("SELECT count(*) FROM search_entries").fetchone() == (3,)


def test_replacing_deep_sky_leaves_stars_and_planets_alone(database: sqlite3.Connection) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    replace_exoplanets(database, make_planet_records(host_id="hip-27989"))
    replace_deep_sky(database, make_deep_sky_records())
    replace_deep_sky(database, [])
    assert load_deep_sky(database) == []
    assert [s.id for s in load_stars(database)] == sorted(s.id for s in stars)
    assert [p.id for p in load_exoplanets(database)] == ["test-b", "test-c"]
    assert database.execute("SELECT count(*) FROM search_entries").fetchone() == (3,)


def test_replacing_stars_or_planets_leaves_deep_sky_alone(database: sqlite3.Connection) -> None:
    replace_deep_sky(database, make_deep_sky_records())
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    replace_exoplanets(database, make_planet_records())
    replace_exoplanets(database, [])
    assert len(load_deep_sky(database)) == 3


def test_the_file_shrinks_when_fewer_deep_sky_objects_are_stored(tmp_path: Path) -> None:
    many = make_deep_sky_records(3000)
    path = tmp_path / "earthlight.db"
    connection = open_database(path)
    try:
        replace_deep_sky(connection, many)
        big = path.stat().st_size
        replace_deep_sky(connection, many[:10])
        small = path.stat().st_size
    finally:
        connection.close()
    assert big > 5 * small  # without VACUUM the file would stay as large as it was


HISTORY_SAMPLE = Path(__file__).parent / "data" / "history_sample"


def test_history_round_trips_through_the_database(database: sqlite3.Connection) -> None:
    data = load_curated_history(HISTORY_SAMPLE)
    replace_history(database, data)
    stored = load_history(database)
    assert stored.events == tuple(sorted(data.events, key=lambda e: e.year))
    assert stored.periods == data.periods and stored.landmarks == data.landmarks
    assert database.execute(
        "SELECT type, count(*) FROM search_entries GROUP BY type"
    ).fetchall() == [
        ("event", 2),
        ("landmark", 1),
        ("period", 1),
    ]


def test_replacing_history_removes_what_was_there(database: sqlite3.Connection) -> None:
    data = load_curated_history(HISTORY_SAMPLE)
    replace_history(database, data)
    replace_history(database, type(data)(data.events[:1], (), ()))
    assert len(load_history(database).events) == 1
    assert load_history(database).landmarks == ()
    assert database.execute("SELECT count(*) FROM search_entries").fetchone() == (1,)
    found = database.execute(
        "SELECT count(*) FROM search_fts WHERE search_fts MATCH 'pyramid*'"
    ).fetchone()
    assert found == (0,)  # the index was rebuilt, so removed entries cannot be found


def test_replacing_history_leaves_vantage_points_alone(database: sqlite3.Connection) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    replace_history(database, load_curated_history(HISTORY_SAMPLE))
    assert [s.id for s in load_stars(database)] == sorted(s.id for s in stars)
    assert database.execute(
        "SELECT count(*) FROM search_entries WHERE type = 'vantage_point'"
    ).fetchone() == (len(entries_for(stars)),)


def test_a_failed_history_replacement_changes_nothing(database: sqlite3.Connection) -> None:
    data = load_curated_history(HISTORY_SAMPLE)
    replace_history(database, data)
    bad = type(data)(data.events + data.events[:1], (), ())  # the same id twice
    with pytest.raises(RuntimeError, match="could not store the history"):
        replace_history(database, bad)
    assert load_history(database).events == tuple(sorted(data.events, key=lambda e: e.year))
    assert len(load_history(database).landmarks) == 1


def test_replacing_history_shrinks_the_file(tmp_path: Path) -> None:
    path = tmp_path / "earthlight.db"
    connection = open_database(path)
    try:
        data = load_curated_history(HISTORY_SAMPLE)
        big = type(data)(
            tuple(
                e.model_copy(
                    update={"id": f"event-{n}", "name": f"Event {n}", "summary": "x" * 900}
                )
                for n in range(300)
                for e in data.events[:1]
            ),
            (),
            (),
        )
        replace_history(connection, big)
        before = path.stat().st_size
        replace_history(connection, type(data)((), (), ()))
        assert path.stat().st_size < before
    finally:
        connection.close()


def test_an_ongoing_period_is_stored_without_an_end_year(database: sqlite3.Connection) -> None:
    data = load_curated_history(HISTORY_SAMPLE)
    holocene = data.periods[0].model_copy(
        update={"id": "holocene-epoch", "name": "Holocene Epoch", "end": None, "ongoing": True}
    )
    replace_history(database, type(data)(data.events, (*data.periods, holocene), data.landmarks))
    assert database.execute(
        "SELECT ongoing, end_year FROM periods WHERE id = 'holocene-epoch'"
    ).fetchone() == (1, None)
    assert database.execute(
        "SELECT ongoing, end_year IS NULL FROM periods WHERE id = 'cambrian'"
    ).fetchone() == (0, 0)
    stored = {p.id: p for p in load_history(database).periods}
    assert stored["holocene-epoch"] == holocene
    assert stored["cambrian"].ongoing is False and stored["cambrian"].end is not None


def estimates(*pairs: tuple[float, int]) -> list[PopulationEstimate]:
    return [
        PopulationEstimate(year=year, people=people, source="https://example.org/population")
        for year, people in pairs
    ]


def test_population_round_trips_through_the_database(database: sqlite3.Connection) -> None:
    data = estimates((-9999, 4_500_000), (0, 232_000_000), (2023, 8_091_734_933))
    replace_population(database, data)
    assert load_population(database) == data


def test_replacing_population_removes_what_was_there(database: sqlite3.Connection) -> None:
    replace_population(database, estimates((0, 232_000_000), (1000, 323_000_000)))
    replace_population(database, estimates((1800, 983_000_000)))
    assert load_population(database) == estimates((1800, 983_000_000))


def test_a_failed_population_replacement_changes_nothing(database: sqlite3.Connection) -> None:
    replace_population(database, estimates((0, 232_000_000)))
    twice = estimates((1, 5), (1, 6))  # the same year twice
    with pytest.raises(RuntimeError, match="could not store the population estimates"):
        replace_population(database, twice)
    assert load_population(database) == estimates((0, 232_000_000))


def test_population_does_not_touch_the_other_tables(database: sqlite3.Connection) -> None:
    stars = make_stars()
    replace_stars(database, stars, entries_for(stars))
    replace_history(database, load_curated_history(HISTORY_SAMPLE))
    replace_population(database, estimates((0, 232_000_000)))
    assert [s.id for s in load_stars(database)] == sorted(s.id for s in stars)
    assert len(load_history(database).events) == 2


def test_replacing_population_shrinks_the_file(tmp_path: Path) -> None:
    path = tmp_path / "earthlight.db"
    connection = open_database(path)
    try:
        replace_population(connection, estimates(*((float(n), 1_000 + n) for n in range(60_000))))
        before = path.stat().st_size
        replace_population(connection, estimates((0, 1)))
        assert path.stat().st_size < before
    finally:
        connection.close()


def test_record_build_info_writes_the_license_and_build_date_into_meta(
    database: sqlite3.Connection,
) -> None:
    record_build_info(database)
    meta = dict(database.execute("SELECT key, value FROM meta").fetchall())
    assert meta["data_license"] == "CC BY-NC 3.0 IGO"
    assert meta["data_license_url"].startswith("https://creativecommons.org/")
    assert meta["build_date"] == datetime.now(UTC).date().isoformat()


def test_finish_database_rejects_a_host_that_is_not_a_star(database: sqlite3.Connection) -> None:
    replace_stars(database, make_stars(), entries_for(make_stars()))
    insert = (
        "INSERT INTO vantage_points (id, name, kind, lookback_min, lookback_best, lookback_max, "
        "host_id) VALUES (?, ?, ?, 1, 1, 1, ?)"
    )
    database.execute(insert, ("planet-a", "A", "exoplanet", "hip-27989"))
    database.execute(insert, ("planet-b", "B", "exoplanet", "planet-a"))
    database.commit()
    with pytest.raises(ValueError, match="do not point at a star"):
        finish_database(database)


def test_finish_database_rejects_a_search_index_that_disagrees_with_its_table(
    database: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    def damaged_rebuild(connection: sqlite3.Connection) -> None:
        rebuild_search_index(connection)
        connection.execute("INSERT INTO search_fts(search_fts) VALUES('delete-all')")
        connection.commit()

    replace_stars(database, make_stars(), entries_for(make_stars()))
    monkeypatch.setattr(store, "rebuild_search_index", damaged_rebuild)
    with pytest.raises(ValueError, match="search_fts failed its integrity check"):
        finish_database(database)


def test_finish_database_accepts_a_sound_database(database: sqlite3.Connection) -> None:
    finish_database(database)
    assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_finish_database_rejects_a_row_without_its_parent(database: sqlite3.Connection) -> None:
    database.execute("PRAGMA foreign_keys = OFF")
    database.execute(
        "INSERT INTO vantage_points (id, name, kind, lookback_min, lookback_best, lookback_max, "
        "host_id) VALUES ('p', 'P', 'exoplanet', 1, 1, 1, 'missing-host')"
    )
    database.commit()
    with pytest.raises(ValueError, match="missing parent"):
        finish_database(database)
