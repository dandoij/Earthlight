"""Tests for the whole population build, with the download replaced by a real-data snapshot."""

import json
import sqlite3
from pathlib import Path

import pytest

from earthlight_pipeline import build_population
from earthlight_pipeline.build_population import (
    PopulationReport,
    format_population_report,
    run_population,
)
from earthlight_pipeline.population import PopulationError
from earthlight_pipeline.store import load_population, open_database

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def snapshot_instead_of_download(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Our World in Data is replaced by a real-data snapshot, so no test uses the network."""
    calls: list[object] = []

    def fetch(*args: object, **_kwargs: object) -> Path:
        calls.append(args)
        return DATA / "owid_population_snapshot.csv"

    monkeypatch.setattr(build_population, "fetch_owid_population", fetch)
    return calls


def run(tmp_path: Path) -> tuple[PopulationReport, list[str]]:
    messages: list[str] = []
    report = run_population(
        cache_dir=tmp_path,
        refresh=False,
        database=tmp_path / "earthlight.db",
        progress=messages.append,
    )
    return report, messages


def test_the_series_is_built_and_stored(tmp_path: Path) -> None:
    report, messages = run(tmp_path)
    assert report.built == 261
    assert report.span == "4.5 million in 10000 BCE to 8.09 billion in 2023 CE"
    assert report.database_bytes == (tmp_path / "earthlight.db").stat().st_size > 0
    assert "Read 261 world population estimates" in messages


def test_the_stored_estimates_read_back_equal(tmp_path: Path) -> None:
    run(tmp_path)
    connection = open_database(tmp_path / "earthlight.db")
    try:
        stored = load_population(connection)
        assert len(stored) == 261 and stored[0].year == -9999 and stored[-1].year == 2023
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        connection.close()


def test_the_database_records_the_sources_and_their_licenses(tmp_path: Path) -> None:
    run(tmp_path)
    connection = sqlite3.connect(tmp_path / "earthlight.db")
    try:
        value = connection.execute(
            "SELECT value FROM meta WHERE key = 'source.population'"
        ).fetchone()[0]
    finally:
        connection.close()
    info = json.loads(value)
    assert info["url"] == "https://ourworldindata.org/grapher/population"
    assert info["retrieved"].count("-") == 2
    assert [s["license"] for s in info["combines"]] == ["CC BY 4.0", "CC BY 4.0", "CC BY 3.0 IGO"]


def test_running_twice_gives_the_same_database(tmp_path: Path) -> None:
    run(tmp_path)
    run(tmp_path)
    connection = sqlite3.connect(tmp_path / "earthlight.db")
    try:
        assert connection.execute("SELECT count(*) FROM population").fetchone() == (261,)
    finally:
        connection.close()


def test_a_bad_file_stops_the_build_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("Entity,Code,Year,Population\nWorld,OWID_WRL,1900,oops\n", encoding="utf-8")
    monkeypatch.setattr(build_population, "fetch_owid_population", lambda *_a, **_k: bad)
    with pytest.raises(PopulationError, match="year 1900"):
        run(tmp_path)
    assert not (tmp_path / "earthlight.db").exists()


def test_the_report_text_is_readable() -> None:
    report = PopulationReport(
        built=261,
        span="4.5 million in 10000 BCE to 8.09 billion in 2023 CE",
        database=Path("earthlight.db"),
        database_bytes=250_000,
    )
    text = format_population_report(report)
    assert "Population estimates built: 261" in text
    assert "World population: 4.5 million in 10000 BCE to 8.09 billion in 2023 CE" in text
    assert "(0.2 MB)" in text
