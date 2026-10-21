"""Tests for the whole exoplanets build, run on real-data fixtures with downloads replaced."""

import json
import sqlite3
from pathlib import Path

import pytest

from earthlight_pipeline import build_exoplanets, build_stars
from earthlight_pipeline.build_exoplanets import (
    ExoplanetsReport,
    format_exoplanets_report,
    run_exoplanets,
)
from earthlight_pipeline.build_stars import run_stars
from earthlight_pipeline.store import load_exoplanets, load_stars, open_database

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def fixtures_instead_of_downloads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every download is replaced by a real-data excerpt, so no test uses the network."""
    calls: list[str] = []

    def one(name: str, path: Path) -> object:
        def fetch(*_args: object, **_kwargs: object) -> Path:
            calls.append(name)
            return path

        return fetch

    def many(name: str, paths: list[Path]) -> object:
        def fetch(*_args: object, **_kwargs: object) -> list[Path]:
            calls.append(name)
            return paths

        return fetch

    archive = DATA / "exoplanet_archive_sample.csv"
    monkeypatch.setattr(
        build_stars, "fetch_hipparcos_main", one("main", DATA / "hip_main_sample.csv")
    )
    monkeypatch.setattr(
        build_stars, "fetch_hipparcos_parallaxes", one("hip2", DATA / "hip2_sample.csv")
    )
    monkeypatch.setattr(build_stars, "fetch_gaia_matches", many("gaia", [DATA / "gaia_sample.csv"]))
    monkeypatch.setattr(build_stars, "fetch_iau_names", one("iau", DATA / "iau_csn_sample.txt"))
    monkeypatch.setattr(build_stars, "fetch_exoplanet_archive", one("archive", archive))
    monkeypatch.setattr(build_exoplanets, "fetch_exoplanet_archive", one("archive", archive))
    monkeypatch.setattr(
        build_exoplanets, "fetch_host_distances", many("hosts", [DATA / "gaia_hosts_sample.csv"])
    )
    return calls


def build_stars_first(tmp_path: Path) -> None:
    run_stars(
        cache_dir=tmp_path,
        refresh=False,
        database=tmp_path / "earthlight.db",
        max_vmag=None,
        progress=lambda _message: None,
    )


def run(tmp_path: Path) -> tuple[ExoplanetsReport, list[str]]:
    messages: list[str] = []
    report = run_exoplanets(
        cache_dir=tmp_path,
        refresh=False,
        database=tmp_path / "earthlight.db",
        progress=messages.append,
    )
    return report, messages


def test_planets_are_built_and_linked_to_the_stars_already_stored(tmp_path: Path) -> None:
    build_stars_first(tmp_path)
    report, messages = run(tmp_path)
    assert report.archive_total == 19
    assert report.built == 16
    assert report.by_source == {"exoplanet_archive": 12, "bailer_jones_host": 4}
    assert report.skipped == {"no_distance": 2, "no_distance_error": 1}
    assert report.linked == 4
    assert report.stars_in_database == 20
    assert report.controversial == 1
    assert report.database_bytes == (tmp_path / "earthlight.db").stat().st_size > 0
    assert any("20 stars to link" in m for m in messages) and any(
        "Writing 16" in m for m in messages
    )


def test_the_stored_planets_can_be_read_back_and_point_at_real_stars(tmp_path: Path) -> None:
    build_stars_first(tmp_path)
    run(tmp_path)
    connection = open_database(tmp_path / "earthlight.db")
    try:
        planets = {p.id: p for p in load_exoplanets(connection)}
        star_ids = {s.id for s in load_stars(connection)}
        assert len(planets) == 16
        assert planets["proxima-cen-b"].host_id == "hip-70890"
        assert {p.host_id for p in planets.values() if p.host_id} <= star_ids
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT count(*) FROM exoplanets").fetchone() == (16,)
        found = connection.execute(
            "SELECT e.id FROM search_fts JOIN search_entries e ON e.entry_id = search_fts.rowid "
            "WHERE search_fts MATCH 'trappist*' ORDER BY e.id"
        ).fetchall()
        assert found == [("trappist-1-b",), ("trappist-1-e",)]
        near_the_host = connection.execute(
            "SELECT id FROM vantage_points "
            "WHERE kind = 'exoplanet' AND host_id = 'hip-70890' ORDER BY id"
        ).fetchall()
        assert near_the_host == [("proxima-cen-b",), ("proxima-cen-d",)]
    finally:
        connection.close()


def test_the_database_records_the_archive_as_a_source(tmp_path: Path) -> None:
    build_stars_first(tmp_path)
    run(tmp_path)
    connection = open_database(tmp_path / "earthlight.db")
    try:
        value = connection.execute(
            "SELECT value FROM meta WHERE key = 'source.nasa_exoplanet_archive'"
        ).fetchone()[0]
    finally:
        connection.close()
    info = json.loads(value)
    assert "Exoplanet Archive" in info["name"] and info["retrieved"].count("-") == 2


def test_running_twice_gives_the_same_database(tmp_path: Path) -> None:
    build_stars_first(tmp_path)
    first, _ = run(tmp_path)
    second, _ = run(tmp_path)
    assert first.built == second.built == 16
    connection = open_database(tmp_path / "earthlight.db")
    try:
        assert connection.execute("SELECT count(*) FROM vantage_points").fetchone() == (36,)
        assert connection.execute("SELECT count(*) FROM search_entries").fetchone() == (32,)
    finally:
        connection.close()


def test_without_stars_the_planets_are_built_but_not_linked(tmp_path: Path) -> None:
    report, _ = run(tmp_path)
    assert report.built == 16 and report.linked == 0 and report.stars_in_database == 0


def test_the_stars_build_can_be_run_again_only_before_planets_exist(tmp_path: Path) -> None:
    build_stars_first(tmp_path)
    run(tmp_path)
    with pytest.raises(RuntimeError, match="rebuild the whole database"):
        build_stars_first(tmp_path)  # Proxima b and others depend on their host stars


def test_every_source_is_fetched_once(
    tmp_path: Path, fixtures_instead_of_downloads: list[str]
) -> None:
    fixtures_instead_of_downloads.clear()
    run(tmp_path)
    assert sorted(fixtures_instead_of_downloads) == ["archive", "hosts"]


def test_the_database_file_is_a_valid_sqlite_database(tmp_path: Path) -> None:
    build_stars_first(tmp_path)
    run(tmp_path)
    connection = sqlite3.connect(tmp_path / "earthlight.db")
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        connection.close()


def test_the_report_text_is_readable() -> None:
    report = ExoplanetsReport(
        archive_total=6_451,
        built=6_356,
        by_source={"exoplanet_archive": 6_215, "bailer_jones_host": 141},
        skipped={"no_distance": 51, "no_distance_error": 44},
        linked=1_236,
        stars_in_database=40_346,
        controversial=58,
        database=Path("earthlight.db"),
        database_bytes=19_600_000,
    )
    text = format_exoplanets_report(report)
    assert "Planets built: 6,356 of 6,451 archive rows" in text
    assert "Distance source: bailer_jones_host 141, exoplanet_archive 6,215" in text
    assert "Left out: no_distance 51, no_distance_error 44" in text
    assert "Linked to a host star: 1,236 (of 40,346 stars in the database)" in text
    assert "controversial: 58" in text
    assert "(19.6 MB)" in text


def test_a_report_with_nothing_left_out_says_so() -> None:
    report = ExoplanetsReport(1, 1, {"exoplanet_archive": 1}, {}, 0, 0, 0, Path("x.db"), 10)
    assert "Left out: nothing" in format_exoplanets_report(report)
