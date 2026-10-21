"""Tests for the whole history build."""

import sqlite3
from pathlib import Path

import pytest

from earthlight_pipeline.build_history import (
    HISTORY_DIR,
    HistoryReport,
    format_history_report,
    run_history,
)
from earthlight_pipeline.history import HistoryError, load_curated_history
from earthlight_pipeline.store import load_history, open_database

SAMPLE = Path(__file__).parent / "data" / "history_sample"


def run(tmp_path: Path, directory: Path = SAMPLE) -> tuple[HistoryReport, list[str]]:
    messages: list[str] = []
    report = run_history(
        database=tmp_path / "earthlight.db", progress=messages.append, history_dir=directory
    )
    return report, messages


def test_the_sample_is_built_and_stored(tmp_path: Path) -> None:
    report, messages = run(tmp_path)
    assert (report.events, report.periods, report.landmarks) == (2, 1, 1)
    assert report.by_category == {"geological": 2, "civilization": 1, "technology": 1}
    assert (report.earliest_year, report.latest_year) == (-4.54e9, 1969.5)
    assert report.database_bytes == (tmp_path / "earthlight.db").stat().st_size > 0
    assert messages[0] == "Read 4 history entries from history_sample/"
    assert any("Writing 4 history entries" in m for m in messages)


def test_the_stored_entries_read_back_equal(tmp_path: Path) -> None:
    run(tmp_path)
    connection = open_database(tmp_path / "earthlight.db")
    try:
        stored = load_history(connection)
    finally:
        connection.close()
    original = load_curated_history(SAMPLE)
    assert stored.events == tuple(sorted(original.events, key=lambda e: e.year))
    assert stored.periods == original.periods
    assert stored.landmarks == original.landmarks


def test_the_entries_are_searchable(tmp_path: Path) -> None:
    run(tmp_path)
    connection = open_database(tmp_path / "earthlight.db")
    try:
        found = connection.execute(
            "SELECT e.type, e.id FROM search_fts JOIN search_entries e "
            "ON e.entry_id = search_fts.rowid WHERE search_fts MATCH 'pyramid*'"
        ).fetchall()
        assert found == [("landmark", "great-pyramid-of-giza")]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        connection.close()


def test_running_twice_gives_the_same_database(tmp_path: Path) -> None:
    run(tmp_path)
    run(tmp_path)
    connection = sqlite3.connect(tmp_path / "earthlight.db")
    try:
        for table in ("events", "periods", "landmarks"):
            (count,) = connection.execute(f"SELECT count(*) FROM {table}").fetchone()
            assert count == {"events": 2, "periods": 1, "landmarks": 1}[table]
        assert connection.execute("SELECT count(*) FROM search_entries").fetchone() == (4,)
    finally:
        connection.close()


def test_a_bad_file_stops_the_build_and_writes_nothing(tmp_path: Path) -> None:
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "era.yaml").write_text("events: [{id: x}]\n", encoding="utf-8")
    with pytest.raises(HistoryError, match="events 1 \\(x\\)"):
        run(tmp_path, bad)
    assert not (tmp_path / "earthlight.db").exists()


def test_the_shipped_directory_is_where_the_build_looks() -> None:
    assert HISTORY_DIR.name == "history" and HISTORY_DIR.parent.name == "curated"


def test_the_report_text_is_readable() -> None:
    report = HistoryReport(
        events=10,
        periods=3,
        landmarks=2,
        by_category={"cosmic": 4, "science": 11},
        earliest_year=-13_800_000_000.0,
        latest_year=2025.0,
        database=Path("earthlight.db"),
        database_bytes=300_000,
    )
    text = format_history_report(report)
    assert "History entries built: 15 (10 events, 3 periods, 2 landmarks)" in text
    assert "By category: cosmic 4, science 11" in text
    assert "Years covered: -13,800,000,000 to 2,025" in text
    assert "(0.3 MB)" in text
