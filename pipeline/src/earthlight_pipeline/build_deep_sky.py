"""The ``deep-sky`` build: read the curated list, fetch SIMBAD, build, and store the objects."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from earthlight_pipeline.deep_sky import (
    build_deep_sky,
    catalogue_names,
    cluster_names,
    cosmicflows_numbers,
    load_curated,
    read_simbad,
    simbad_identifiers,
)
from earthlight_pipeline.galaxy_distances import (
    MCCONNACHIE,
    read_cosmicflows,
    read_mcconnachie,
)
from earthlight_pipeline.sources import (
    Progress,
    fetch_cosmicflows,
    fetch_hunt_reffert,
    fetch_mcconnachie,
    fetch_simbad,
)
from earthlight_pipeline.star_clusters import read_hunt_reffert
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


def _sources_used(
    simbad: list[Path], clusters: list[Path], mcconnachie: list[Path], cosmicflows: list[Path]
) -> list[tuple[str, str, list[Path]]]:
    """The ``meta`` key, display name, and downloaded files of every source that was used."""
    everything = [
        ("simbad", "SIMBAD astronomical database, CDS Strasbourg", simbad),
        (
            "hunt_reffert_2023",
            "Hunt and Reffert (2023) Gaia DR3 cluster catalogue, via VizieR",
            clusters,
        ),
        (
            "mcconnachie_2012",
            "McConnachie (2012) catalogue of nearby dwarf galaxies, via VizieR",
            mcconnachie,
        ),
        (
            "cosmicflows_4",
            "Cosmicflows-4 (Tully et al. 2023) galaxy distances, via VizieR",
            cosmicflows,
        ),
    ]
    return [(key, name, paths) for key, name, paths in everything if paths]


def _retrieved(paths: list[Path]) -> str:
    """The date, as YYYY-MM-DD, that the newest of the downloaded files was fetched."""
    return datetime.fromtimestamp(max(p.stat().st_mtime for p in paths), tz=UTC).date().isoformat()


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
    wanted_clusters = cluster_names(objects)
    cluster_csvs = (
        [fetch_hunt_reffert(wanted_clusters, cache_dir, refresh, progress)]
        if wanted_clusters
        else []
    )
    mcconnachie_names = catalogue_names(objects, MCCONNACHIE)
    mcconnachie_csvs = (
        [fetch_mcconnachie(mcconnachie_names, cache_dir, refresh, progress)]
        if mcconnachie_names
        else []
    )
    cosmicflows_pgcs = cosmicflows_numbers(objects)
    cosmicflows_csvs = (
        [fetch_cosmicflows(cosmicflows_pgcs, cache_dir, refresh, progress)]
        if cosmicflows_pgcs
        else []
    )
    result = build_deep_sky(
        objects,
        read_simbad(simbad_csvs),
        read_hunt_reffert(cluster_csvs),
        {**read_mcconnachie(mcconnachie_csvs), **read_cosmicflows(cosmicflows_csvs)},
    )

    connection = open_database(database)
    try:
        progress(f"Writing {len(result.records):,} deep-sky objects to {database}")
        replace_deep_sky(connection, result.records)
        for key, name, paths in _sources_used(
            simbad_csvs, cluster_csvs, mcconnachie_csvs, cosmicflows_csvs
        ):
            set_meta(
                connection,
                f"source.{key}",
                json.dumps({"name": name, "retrieved": _retrieved(paths)}),
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


def _span_text(years: float) -> str:
    """A span of years for people: "441 years", "17 thousand years", "185 million years"."""
    if years >= 1e9:
        return f"{years / 1e9:,.2f} billion years"
    if years >= 1e6:
        return f"{years / 1e6:,.0f} million years"
    if years >= 1e4:
        return f"{years / 1e3:,.0f} thousand years"
    return f"{years:,.0f} years"


def format_deep_sky_report(report: DeepSkyReport) -> str:
    """A plain-text summary of a deep-sky build."""
    return "\n".join(
        [
            f"Deep-sky objects built: {report.built:,}",
            "By kind: "
            + ", ".join(f"{kind} {count:,}" for kind, count in sorted(report.by_kind.items())),
            "Numbers from: "
            + ", ".join(f"{name} {count:,}" for name, count in sorted(report.by_source.items())),
            f"Lookback: {_span_text(report.nearest_years)} (nearest) to "
            f"{_span_text(report.farthest_years)} (farthest)",
            f"Database: {report.database} ({report.database_bytes / 1_000_000:.1f} MB)",
        ]
    )
