"""The ``history`` build: read the curated history files and store them. It needs no downloads."""

from dataclasses import dataclass
from pathlib import Path

from earthlight_pipeline.history import (
    category_counts,
    has_ongoing_period,
    load_aliases,
    load_curated_history,
    years_covered,
)
from earthlight_pipeline.sources import Progress
from earthlight_pipeline.store import open_database, replace_history

HISTORY_DIR = Path(__file__).resolve().parents[2] / "curated" / "history"
"""The curated files, which live in the repository next to the pipeline code."""

ALIASES_NAME = "history_aliases.yaml"
"""Other names people use for entries, so that search finds them (see the file's header). It sits
next to the ``history`` folder, so a different folder (a test's) uses its own file or none."""


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
    reaches_present: bool = False
    """True when a period is ongoing; the report then ends at "present", not a year."""
    aliases: int = 0
    """How many other names for entries were added to search."""


def run_history(
    *,
    database: Path,
    progress: Progress,
    history_dir: Path = HISTORY_DIR,
    aliases_file: Path | None = None,
) -> HistoryReport:
    """Store every curated event, period, and landmark in ``database``, replacing any there."""
    data = load_curated_history(history_dir)
    progress(f"Read {data.total} history entries from {history_dir.name}/")
    earliest, latest = years_covered(data)  # before the database is opened, in case it raises
    if aliases_file is None:
        aliases_file = history_dir.parent / ALIASES_NAME  # may not exist, e.g. in a test folder
    aliases = load_aliases(aliases_file, data) if aliases_file.is_file() else {}
    alias_count = sum(len(names) for names in aliases.values())
    progress(f"Read {alias_count} other names for search from {ALIASES_NAME}")
    connection = open_database(database)
    try:
        progress(f"Writing {data.total:,} history entries to {database}")
        replace_history(connection, data, aliases)
    finally:
        connection.close()
    return HistoryReport(
        events=len(data.events),
        periods=len(data.periods),
        landmarks=len(data.landmarks),
        by_category=category_counts(data),
        earliest_year=earliest,
        latest_year=latest,
        database=database,
        database_bytes=database.stat().st_size,
        reaches_present=has_ongoing_period(data),
        aliases=alias_count,
    )


def format_history_report(report: HistoryReport) -> str:
    """A plain-text summary of a history build."""
    total = report.events + report.periods + report.landmarks
    latest = "present" if report.reaches_present else f"{report.latest_year:,.0f}"
    return "\n".join(
        [
            f"History entries built: {total:,} "
            f"({report.events:,} events, {report.periods:,} periods, "
            f"{report.landmarks:,} landmarks)",
            "By category: "
            + ", ".join(f"{name} {count:,}" for name, count in report.by_category.items()),
            f"Years covered: {report.earliest_year:,.0f} to {latest} "
            "(astronomical numbering, 1 BCE is 0)",
            f"Other names for search: {report.aliases:,}",
            f"Database: {report.database} ({report.database_bytes / 1_000_000:.1f} MB)",
        ]
    )
