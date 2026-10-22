"""The ``population`` build: read Our World in Data's world population series and store it."""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from earthlight_pipeline.population import (
    CHART_URL,
    UNDERLYING_SOURCES,
    read_population,
    span_text,
)
from earthlight_pipeline.sources import Progress, fetch_owid_population
from earthlight_pipeline.store import open_database, replace_population, set_meta


@dataclass(frozen=True)
class PopulationReport:
    """What the population build did, for printing."""

    built: int
    span: str
    database: Path
    database_bytes: int


def run_population(
    *, cache_dir: Path, refresh: bool, database: Path, progress: Progress
) -> PopulationReport:
    """Store the world population estimates in ``database``, replacing any there."""
    path = fetch_owid_population(cache_dir, refresh, progress)
    estimates = read_population(path)
    progress(f"Read {len(estimates)} world population estimates")
    connection = open_database(database)
    try:
        progress(f"Writing {len(estimates)} population estimates to {database}")
        replace_population(connection, estimates)
        retrieved = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).date().isoformat()
        set_meta(
            connection,
            "source.population",
            json.dumps(
                {
                    "name": "Our World in Data, Population (HYDE, Gapminder, UN WPP)",
                    "url": CHART_URL,
                    "retrieved": retrieved,
                    "combines": [asdict(source) for source in UNDERLYING_SOURCES],
                }
            ),
        )
    finally:
        connection.close()
    return PopulationReport(
        built=len(estimates),
        span=span_text(estimates),
        database=database,
        database_bytes=database.stat().st_size,
    )


def format_population_report(report: PopulationReport) -> str:
    """A plain-text summary of a population build."""
    return "\n".join(
        [
            f"Population estimates built: {report.built:,}",
            f"World population: {report.span}",
            f"Database: {report.database} ({report.database_bytes / 1_000_000:.1f} MB)",
        ]
    )
