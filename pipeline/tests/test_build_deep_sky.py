"""Tests for the whole deep-sky build, run on the real SIMBAD snapshot with downloads replaced."""

import json
import sqlite3
from pathlib import Path

import pytest

from earthlight_pipeline import build_deep_sky
from earthlight_pipeline.build_deep_sky import (
    DEEP_SKY_FILE,
    DeepSkyReport,
    format_deep_sky_report,
    run_deep_sky,
)
from earthlight_pipeline.deep_sky import CuratedError
from earthlight_pipeline.store import load_deep_sky, open_database

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def snapshot_instead_of_download(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """SIMBAD is replaced by a real-data snapshot, so no test uses the network."""
    asked: list[list[str]] = []

    def fetch(identifiers: list[str], *_args: object, **_kwargs: object) -> list[Path]:
        asked.append(list(identifiers))
        return [DATA / "simbad_snapshot.csv"]

    monkeypatch.setattr(build_deep_sky, "fetch_simbad", fetch)
    return asked


@pytest.fixture(autouse=True)
def clusters_snapshot_instead_of_download(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Hunt and Reffert (VizieR) is replaced by a real-data snapshot as well."""
    asked: list[list[str]] = []

    def fetch(names: list[str], *_args: object, **_kwargs: object) -> Path:
        asked.append(list(names))
        return DATA / "hunt_reffert_snapshot.csv"

    monkeypatch.setattr(build_deep_sky, "fetch_hunt_reffert", fetch)
    return asked


def run(tmp_path: Path, **overrides: object) -> tuple[DeepSkyReport, list[str]]:
    messages: list[str] = []
    report = run_deep_sky(
        cache_dir=tmp_path,
        refresh=False,
        database=tmp_path / "earthlight.db",
        progress=messages.append,
        **overrides,  # type: ignore[arg-type]
    )
    return report, messages


def test_the_list_is_built_and_stored(tmp_path: Path) -> None:
    report, messages = run(tmp_path)
    assert report.built == 85
    assert report.by_kind == {
        "cosmic_background": 1,
        "galaxy": 24,
        "galaxy_cluster": 13,
        "quasar": 14,
        "star_cluster": 33,
    }
    assert report.by_source == {"simbad": 45, "inline": 7, "hunt_reffert_2023": 33}
    assert report.database_bytes == (tmp_path / "earthlight.db").stat().st_size > 0
    assert 100 < report.nearest_years < 200 and 13.7e9 < report.farthest_years < 13.8e9
    assert messages[0] == "Read 85 curated objects from deep_sky.yaml"
    assert any("Writing 85 deep-sky objects" in m for m in messages)


def test_the_stored_objects_read_back_and_are_searchable(tmp_path: Path) -> None:
    run(tmp_path)
    connection = open_database(tmp_path / "earthlight.db")
    try:
        points = {p.id: p for p in load_deep_sky(connection)}
        assert len(points) == 85
        assert points["3c-273"].facts["redshift_source"] == "2022ApJS..261....2K"
        pleiades = points["pleiades"]
        assert pleiades.kind.value == "star_cluster" and pleiades.constellation == "Taurus"
        assert pleiades.facts["distance_source"] == "hunt_reffert_2023"
        assert 430 < pleiades.lookback.best < 450
        alias_hits = connection.execute(
            "SELECT e.id FROM search_fts JOIN search_entries e ON e.entry_id = search_fts.rowid "
            "WHERE search_fts MATCH 'seven sisters'"
        ).fetchall()
        assert alias_hits == [("pleiades",)]
        pleiades = points["pleiades"]
        assert pleiades.kind.value == "star_cluster" and pleiades.constellation == "Taurus"
        assert pleiades.facts["distance_source"] == "hunt_reffert_2023"
        assert 430 < pleiades.lookback.best < 450
        alias_hits = connection.execute(
            "SELECT e.id FROM search_fts JOIN search_entries e ON e.entry_id = search_fts.rowid "
            "WHERE search_fts MATCH 'seven sisters'"
        ).fetchall()
        assert alias_hits == [("pleiades",)]
        found = connection.execute(
            "SELECT e.id FROM search_fts JOIN search_entries e ON e.entry_id = search_fts.rowid "
            "WHERE search_fts MATCH 'abell*' ORDER BY e.id"
        ).fetchall()
        assert ("coma-cluster",) in found  # found by its alias, Abell 1656
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        connection.close()


def test_the_database_records_simbad_as_a_source(tmp_path: Path) -> None:
    run(tmp_path)
    connection = sqlite3.connect(tmp_path / "earthlight.db")
    try:
        value = connection.execute("SELECT value FROM meta WHERE key = 'source.simbad'").fetchone()[
            0
        ]
    finally:
        connection.close()
    info = json.loads(value)
    assert "SIMBAD" in info["name"] and info["retrieved"].count("-") == 2


def test_running_twice_gives_the_same_database(tmp_path: Path) -> None:
    first, _ = run(tmp_path)
    second, _ = run(tmp_path)
    assert first.built == second.built
    connection = open_database(tmp_path / "earthlight.db")
    try:
        assert connection.execute("SELECT count(*) FROM vantage_points").fetchone() == (
            first.built,
        )
        assert connection.execute("SELECT count(*) FROM search_entries").fetchone() == (
            first.built,
        )
    finally:
        connection.close()


def test_only_simbad_objects_are_asked_for(
    tmp_path: Path, snapshot_instead_of_download: list[list[str]]
) -> None:
    run(tmp_path)
    (asked,) = snapshot_instead_of_download
    assert "3C 273" in asked and "ACO  1656" in asked  # every padding of a catalogue name
    assert not any("Planck" in name or "JADES" in name for name in asked)


def test_only_the_curated_clusters_are_asked_of_hunt_and_reffert(
    tmp_path: Path, clusters_snapshot_instead_of_download: list[list[str]]
) -> None:
    run(tmp_path)
    (asked,) = clusters_snapshot_instead_of_download
    assert len(asked) == 33 and "Melotte_22" in asked and "NGC_5139" in asked
    assert not any(" " in name for name in asked)  # catalogue names use underscores


def test_the_database_records_hunt_and_reffert_as_a_source(tmp_path: Path) -> None:
    run(tmp_path)
    connection = sqlite3.connect(tmp_path / "earthlight.db")
    try:
        value = connection.execute(
            "SELECT value FROM meta WHERE key = 'source.hunt_reffert_2023'"
        ).fetchone()[0]
    finally:
        connection.close()
    info = json.loads(value)
    assert "Hunt and Reffert" in info["name"] and info["retrieved"].count("-") == 2


def test_a_cluster_missing_from_the_catalogue_stops_the_build(tmp_path: Path) -> None:
    only_one = tmp_path / "one.yaml"
    only_one.write_text(
        "objects:\n  - id: ghost\n    name: Ghost\n    kind: star_cluster\n    fame: 1\n"
        "    distance: {catalogue: hunt_reffert_2023, name: Not_A_Cluster}\n",
        encoding="utf-8",
    )
    with pytest.raises(CuratedError, match="has no cluster 'Not_A_Cluster'"):
        run(tmp_path, curated_file=only_one)
    assert not (tmp_path / "earthlight.db").exists()


def test_a_bad_curated_file_stops_the_build_and_names_the_problem(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "objects:\n  - {id: x, name: X, kind: galaxy, fame: 9, simbad: NGC 1275}\n",
        encoding="utf-8",
    )
    with pytest.raises(CuratedError, match="fame"):
        run(tmp_path, curated_file=bad)
    assert not (tmp_path / "earthlight.db").exists()  # nothing was written


def test_the_shipped_file_is_where_the_build_looks() -> None:
    assert DEEP_SKY_FILE.name == "deep_sky.yaml" and DEEP_SKY_FILE.parent.name == "curated"
    assert DEEP_SKY_FILE.exists()


def test_the_report_text_is_readable() -> None:
    report = DeepSkyReport(
        built=52,
        by_kind={"galaxy": 24, "quasar": 14},
        by_source={"simbad": 45, "inline": 7},
        nearest_years=184_670_000.0,
        farthest_years=13_786_510_000.0,
        database=Path("earthlight.db"),
        database_bytes=200_000,
    )
    text = format_deep_sky_report(report)
    assert "Deep-sky objects built: 52" in text
    assert "By kind: galaxy 24, quasar 14" in text
    assert "Numbers from: inline 7, simbad 45" in text
    assert "185 million years (nearest) to 13.79 billion years (farthest)" in text
    assert "(0.2 MB)" in text


@pytest.mark.parametrize(
    ("years", "text"),
    [
        (153.0, "153 years"),
        (9_999.0, "9,999 years"),
        (17_400.0, "17 thousand years"),
        (999_000.0, "999 thousand years"),
        (185_000_000.0, "185 million years"),
        (13_787_000_000.0, "13.79 billion years"),
    ],
)
def test_spans_are_written_in_the_unit_that_fits(years: float, text: str) -> None:
    assert build_deep_sky._span_text(years) == text
