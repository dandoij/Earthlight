"""The ``deep-sky`` build: read the curated list, fetch SIMBAD, build, and store the objects."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from earthlight_pipeline.deep_sky import (
    build_deep_sky,
    load_curated,
    read_simbad,
    simbad_identifiers,
)
from earthlight_pipeline.sources import Progress, fetch_simbad
from earthlight_pipeline.store import open_database, replace_deep_sky, set_meta

CURATED_DIR = Path(__file__).resolve().parents[2] / "curated"
DEEP_SKY_FILE = CURATED_DIR / "deep_sky.yaml"
"""The curated list, which lives in the repository next to the pipeline code."""


@dataclass(frozen=True)
class DeepSkyReport:
    """What the deep-sky build did, for printing."""

    built: int
    by_kind: dict[str, int]
    by_source: dict[str, int]
    nearest_years: float
    farthest_years: float
    database: Path
    database_bytes: int


def run_deep_sky(
    *,
    cache_dir: Path,
    refresh: bool,
    database: Path,
    progress: Progress,
    curated_file: Path = DEEP_SKY_FILE,
) -> DeepSkyReport:
    """Build every curated deep-sky object and store it in ``database``, replacing any there."""
    objects = load_curated(curated_file)
    progress(f"Read {len(objects)} curated objects from {curated_file.name}")
    simbad_csvs = fetch_simbad(simbad_identifiers(objects), cache_dir, refresh, progress)
    result = build_deep_sky(objects, read_simbad(simbad_csvs))

    connection = open_database(database)
    try:
        progress(f"Writing {len(result.records):,} deep-sky objects to {database}")
        replace_deep_sky(connection, result.records)
        retrieved = (
            datetime.fromtimestamp(max(p.stat().st_mtime for p in simbad_csvs), tz=UTC)
            .date()
            .isoformat()
        )
        set_meta(
            connection,
            "source.simbad",
            json.dumps(
                {"name": "SIMBAD astronomical database, CDS Strasbourg", "retrieved": retrieved}
            ),
        )
    finally:
        connection.close()

    points = [record.point for record in result.records]
    by_kind: dict[str, int] = {}
    for point in points:
        by_kind[point.kind.value] = by_kind.get(point.kind.value, 0) + 1
    return DeepSkyReport(
        built=len(points),
        by_kind=by_kind,
        by_source=dict(result.sources),
        nearest_years=min(p.lookback.best for p in points),
        farthest_years=max(p.lookback.best for p in points),
        database=database,
        database_bytes=database.stat().st_size,
    )


def format_deep_sky_report(report: DeepSkyReport) -> str:
    """A plain-text summary of a deep-sky build."""
    return "\n".join(
        [
            f"Deep-sky objects built: {report.built:,}",
            "By kind: "
            + ", ".join(f"{kind} {count:,}" for kind, count in sorted(report.by_kind.items())),
            "Numbers from: "
            + ", ".join(f"{name} {count:,}" for name, count in sorted(report.by_source.items())),
            f"Lookback: {report.nearest_years / 1e6:,.0f} million years (nearest) to "
            f"{report.farthest_years / 1e9:,.2f} billion years (farthest)",
            f"Database: {report.database} ({report.database_bytes / 1_000_000:.1f} MB)",
        ]
    )
