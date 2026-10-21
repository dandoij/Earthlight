"""The ``exoplanets`` build: download, read, build, and store the exoplanet vantage points."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from earthlight_pipeline.exoplanets import (
    StarIndex,
    build_exoplanets,
    host_gaia_ids_needed,
    read_archive,
    read_host_distances,
)
from earthlight_pipeline.sources import Progress, fetch_exoplanet_archive, fetch_host_distances
from earthlight_pipeline.store import (
    load_stars,
    open_database,
    replace_exoplanets,
    set_meta,
)


@dataclass(frozen=True)
class ExoplanetsReport:
    """What the exoplanets build did, for printing."""

    archive_total: int
    built: int
    by_source: dict[str, int]
    skipped: dict[str, int]
    linked: int
    stars_in_database: int
    controversial: int
    database: Path
    database_bytes: int


def run_exoplanets(
    *,
    cache_dir: Path,
    refresh: bool,
    database: Path,
    progress: Progress,
) -> ExoplanetsReport:
    """Build every planet and store it in ``database``, replacing any planets already there.

    Run the ``stars`` build first: planets are linked to the host stars that are in the
    database at this moment.
    """
    archive_csv = fetch_exoplanet_archive(cache_dir, refresh, progress)
    planets = read_archive(archive_csv)
    host_csvs = fetch_host_distances(host_gaia_ids_needed(planets), cache_dir, refresh, progress)
    host_distances = read_host_distances(host_csvs)

    connection = open_database(database)
    try:
        stars = load_stars(connection)
        progress(
            f"Building planets from {len(planets):,} archive rows ({len(stars):,} stars to link)"
        )
        result = build_exoplanets(planets, host_distances, StarIndex.from_stars(stars))
        progress(f"Writing {len(result.records):,} planets to {database}")
        replace_exoplanets(connection, result.records)
        retrieved = datetime.fromtimestamp(archive_csv.stat().st_mtime, tz=UTC).date().isoformat()
        set_meta(
            connection,
            "source.nasa_exoplanet_archive",
            json.dumps(
                {"name": "NASA Exoplanet Archive, Planetary Systems", "retrieved": retrieved}
            ),
        )
    finally:
        connection.close()

    return ExoplanetsReport(
        archive_total=len(planets),
        built=len(result.records),
        by_source=dict(result.sources),
        skipped=dict(result.skipped),
        linked=result.linked,
        stars_in_database=len(stars),
        controversial=sum(1 for record in result.records if record.details.controversial),
        database=database,
        database_bytes=database.stat().st_size,
    )


def format_exoplanets_report(report: ExoplanetsReport) -> str:
    """A plain-text summary of an exoplanets build."""
    return "\n".join(
        [
            f"Planets built: {report.built:,} of {report.archive_total:,} archive rows",
            "Distance source: "
            + ", ".join(f"{name} {count:,}" for name, count in sorted(report.by_source.items())),
            "Left out: "
            + (
                ", ".join(f"{reason} {count:,}" for reason, count in sorted(report.skipped.items()))
                or "nothing"
            ),
            f"Linked to a host star: {report.linked:,} (of {report.stars_in_database:,} stars "
            f"in the database); marked controversial: {report.controversial:,}",
            f"Database: {report.database} ({report.database_bytes / 1_000_000:.1f} MB)",
        ]
    )
