"""The ``history`` build: read the curated history files and store them. It needs no downloads."""

from dataclasses import dataclass
from pathlib import Path

from earthlight_pipeline.history import (
    category_counts,
    load_curated_history,
    years_covered,
)
from earthlight_pipeline.sources import Progress
from earthlight_pipeline.store import open_database, replace_history

HISTORY_DIR = Path(__file__).resolve().parents[2] / "curated" / "history"
"""The curated files, which live in the repository next to the pipeline code."""


@dataclass(frozen=True)
class HistoryReport:
    """What the history build did, for printing."""

    events: int
    periods: int
    landmarks: int
    by_category: dict[str, int]
    earliest_year: float
    latest_year: float
    database: Path
    database_bytes: int


def run_history(
    *, database: Path, progress: Progress, history_dir: Path = HISTORY_DIR
) -> HistoryReport:
    """Store every curated event, period, and landmark in ``database``, replacing any there."""
    data = load_curated_history(history_dir)
    progress(f"Read {data.total} history entries from {history_dir.name}/")
    connection = open_database(database)
    try:
        progress(f"Writing {data.total:,} history entries to {database}")
        replace_history(connection, data)
    finally:
        connection.close()
    earliest, latest = years_covered(data)
    return HistoryReport(
        events=len(data.events),
        periods=len(data.periods),
        landmarks=len(data.landmarks),
        by_category=category_counts(data),
        earliest_year=earliest,
        latest_year=latest,
        database=database,
        database_bytes=database.stat().st_size,
    )


def format_history_report(report: HistoryReport) -> str:
    """A plain-text summary of a history build."""
    total = report.events + report.periods + report.landmarks
    return "\n".join(
        [
            f"History entries built: {total:,} "
            f"({report.events:,} events, {report.periods:,} periods, "
            f"{report.landmarks:,} landmarks)",
            "By category: "
            + ", ".join(f"{name} {count:,}" for name, count in report.by_category.items()),
            f"Years covered: {report.earliest_year:,.0f} to {report.latest_year:,.0f} "
            "(astronomical numbering, 1 BCE is 0)",
            f"Database: {report.database} ({report.database_bytes / 1_000_000:.1f} MB)",
        ]
    )
