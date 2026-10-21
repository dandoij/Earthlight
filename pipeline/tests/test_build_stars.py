"""Tests for the whole stars build, run on the real-data fixtures with downloads replaced."""

import json
import re
from pathlib import Path

import pytest

from earthlight_pipeline import build_stars
from earthlight_pipeline.build_stars import (
    DEFAULT_MAX_VMAG,
    StarsReport,
    format_stars_report,
    run_stars,
)
from earthlight_pipeline.store import load_stars, open_database

DATA = Path(__file__).parent / "data"

ARCHIVE_HEADER = (
    "pl_name,hostname,pl_controv_flag,sy_dist,sy_disterr1,sy_disterr2,sy_vmag,ra,dec,gaia_dr3_id,"
    "hip_name,disc_year,discoverymethod,sy_pnum,pl_rade,pl_bmasse,pl_orbper\n"
)


@pytest.fixture(autouse=True)
def fixtures_instead_of_downloads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every download is replaced by a real-data excerpt, so no test uses the network."""
    calls: list[str] = []

    def record(name: str, path: Path) -> object:
        def fetch(*_args: object, **_kwargs: object) -> Path:
            calls.append(name)
            return path

        return fetch

    def fetch_gaia(*_args: object, **_kwargs: object) -> list[Path]:
        calls.append("gaia")
        return [DATA / "gaia_sample.csv"]

    monkeypatch.setattr(
        build_stars, "fetch_hipparcos_main", record("main", DATA / "hip_main_sample.csv")
    )
    monkeypatch.setattr(
        build_stars, "fetch_hipparcos_parallaxes", record("hip2", DATA / "hip2_sample.csv")
    )
    monkeypatch.setattr(build_stars, "fetch_gaia_matches", fetch_gaia)
    monkeypatch.setattr(build_stars, "fetch_iau_names", record("iau", DATA / "iau_csn_sample.txt"))
    monkeypatch.setattr(
        build_stars,
        "fetch_exoplanet_archive",
        record("archive", DATA / "exoplanet_archive_sample.csv"),
    )
    return calls


def run(tmp_path: Path, max_vmag: float | None = None) -> tuple[StarsReport, list[str]]:
    messages: list[str] = []
    report = run_stars(
        cache_dir=tmp_path,
        refresh=False,
        database=tmp_path / "earthlight.db",
        max_vmag=max_vmag,
        progress=messages.append,
    )
    return report, messages


def test_the_build_stores_every_star_and_reports_what_it_did(tmp_path: Path) -> None:
    report, messages = run(tmp_path)
    assert report.hipparcos_total == 25
    assert report.built == 20
    assert report.by_source == {"gaia": 5, "hipparcos": 15}
    assert report.skipped == {
        "parallax_not_precise": 2,
        "no_position": 2,
        "non_positive_parallax": 1,
    }
    assert report.named == 16 and report.searchable == 16
    assert report.planet_hosts == 3  # Proxima Centauri, Belenos, and Monch host fixture planets
    assert report.fame_counts == {0: 4, 2: 2, 3: 1, 4: 3, 5: 10}
    assert report.database == tmp_path / "earthlight.db"
    assert report.database_bytes == (tmp_path / "earthlight.db").stat().st_size > 0
    assert any("Reading" in m for m in messages) and any("Writing 20" in m for m in messages)


def test_the_stored_stars_can_be_read_back(tmp_path: Path) -> None:
    run(tmp_path)
    connection = open_database(tmp_path / "earthlight.db")
    try:
        stars = {s.id: s for s in load_stars(connection)}
        assert len(stars) == 20
        assert stars["hip-27989"].name == "Betelgeuse"
        assert stars["hip-6643"].name == "Bélénos"
        found = connection.execute(
            "SELECT e.id FROM search_fts JOIN search_entries e ON e.entry_id = search_fts.rowid "
            "WHERE search_fts MATCH 'belenos'"
        ).fetchall()
        assert found == [("hip-6643",)]  # accents are folded in search
    finally:
        connection.close()


def test_a_star_that_hosts_a_planet_is_kept_however_faint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # HIP 2 is unnamed and V 9.27, so the magnitude limit would drop it.
    without, _ = run(tmp_path / "without", max_vmag=8.0)
    row = ARCHIVE_HEADER + "Faint b,Faint,0,10,1,-1,12,0.01,-19.5,,HIP 2,2020,Transit,1,1,1,1\n"
    archive = tmp_path / "faint.csv"
    archive.write_text(row, encoding="utf-8")
    monkeypatch.setattr(build_stars, "fetch_exoplanet_archive", lambda *_a, **_k: archive)
    kept, _ = run(tmp_path / "with", max_vmag=8.0)
    assert kept.built == without.built + 1
    assert kept.planet_hosts == 1 and without.planet_hosts == 3

    connection = open_database(tmp_path / "with" / "earthlight.db")
    try:
        star = {s.id: s for s in load_stars(connection)}["hip-2"]
        assert star.fame == 1  # a host is notable enough to be searchable
        found = connection.execute("SELECT id FROM search_entries WHERE id = 'hip-2'").fetchall()
        assert found == [("hip-2",)]
    finally:
        connection.close()


def test_the_database_records_where_its_data_came_from(tmp_path: Path) -> None:
    run(tmp_path, max_vmag=8.0)
    connection = open_database(tmp_path / "earthlight.db")
    try:
        meta = dict(connection.execute("SELECT key, value FROM meta").fetchall())
    finally:
        connection.close()
    keys = ("source.hipparcos", "source.gaia_dr3", "source.bailer_jones_2021", "source.iau_csn")
    assert set(keys) <= set(meta)
    for key in keys:
        info = json.loads(meta[key])
        assert info["name"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", info["retrieved"])
    assert meta["stars.max_vmag"] == "8.0"


def test_running_twice_gives_the_same_database(tmp_path: Path) -> None:
    first, _ = run(tmp_path, max_vmag=DEFAULT_MAX_VMAG)
    second, _ = run(tmp_path, max_vmag=DEFAULT_MAX_VMAG)
    assert first.built == second.built == 18
    connection = open_database(tmp_path / "earthlight.db")
    try:
        assert connection.execute("SELECT count(*) FROM vantage_points").fetchone() == (18,)
        assert connection.execute("SELECT count(*) FROM search_entries").fetchone() == (16,)
    finally:
        connection.close()


def test_no_limit_is_recorded_as_none(tmp_path: Path) -> None:
    run(tmp_path, max_vmag=None)
    connection = open_database(tmp_path / "earthlight.db")
    try:
        row = connection.execute("SELECT value FROM meta WHERE key = 'stars.max_vmag'").fetchone()
    finally:
        connection.close()
    assert row == ("none",)


def test_every_source_is_fetched_once(
    tmp_path: Path, fixtures_instead_of_downloads: list[str]
) -> None:
    run(tmp_path)
    assert sorted(fixtures_instead_of_downloads) == ["archive", "gaia", "hip2", "iau", "main"]


def test_the_report_text_is_readable() -> None:
    report = StarsReport(
        hipparcos_total=118_218,
        built=40_346,
        by_source={"gaia": 34_160, "hipparcos": 6_186},
        skipped={"too_faint": 69_295, "no_position": 263},
        searchable=1_171,
        named=409,
        planet_hosts=862,
        fame_counts={0: 39_175, 1: 751},
        database=Path("earthlight.db"),
        database_bytes=14_800_000,
    )
    text = format_stars_report(report)
    assert "Stars built: 40,346 of 118,218 Hipparcos entries" in text
    assert "Distance source: gaia 34,160, hipparcos 6,186" in text
    assert "Left out: no_position 263, too_faint 69,295" in text
    assert "IAU-named stars: 409; planet hosts: 862; searchable: 1,171" in text
    assert "Fame: 0: 39,175, 1: 751" in text
    assert "(14.8 MB)" in text


def test_a_report_with_nothing_left_out_says_so() -> None:
    report = StarsReport(1, 1, {"gaia": 1}, {}, 0, 0, 0, {0: 1}, Path("x.db"), 1000)
    assert "Left out: nothing" in format_stars_report(report)
