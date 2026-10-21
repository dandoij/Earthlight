"""The ``stars`` build: download, read, build, and store the star vantage points."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from earthlight_pipeline.sources import (
    Progress,
    fetch_gaia_matches,
    fetch_hipparcos_main,
    fetch_hipparcos_parallaxes,
    fetch_iau_names,
    max_hipparcos_number,
)
from earthlight_pipeline.stars import (
    build_stars,
    parse_iau_names,
    read_gaia_matches,
    read_hipparcos,
    search_entry,
)
from earthlight_pipeline.store import open_database, replace_stars, set_meta

DEFAULT_MAX_VMAG = 8.0
"""Unnamed stars fainter than this are left out. Measured with the real data (see
docs/data-sources.md): V <= 7.5 is 25,161 stars (9.4 MB), V <= 8.5 is 58,860 (21.8 MB), and the
whole catalogue is 109,640 (40.4 MB), against a budget of about 20 MB for the full database."""


@dataclass(frozen=True)
class StarsReport:
    """What the stars build did, for printing."""

    hipparcos_total: int
    built: int
    by_source: dict[str, int]
    skipped: dict[str, int]
    searchable: int
    named: int
    fame_counts: dict[int, int]
    database: Path
    database_bytes: int


def _retrieved(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).date().isoformat()


def run_stars(
    *,
    cache_dir: Path,
    refresh: bool,
    database: Path,
    max_vmag: float | None,
    progress: Progress,
) -> StarsReport:
    """Build every star and store it in ``database``, replacing any stars already there."""
    main_csv = fetch_hipparcos_main(cache_dir, refresh, progress)
    parallax_csv = fetch_hipparcos_parallaxes(cache_dir, refresh, progress)
    gaia_csvs = fetch_gaia_matches(max_hipparcos_number(main_csv), cache_dir, refresh, progress)
    iau_txt = fetch_iau_names(cache_dir, refresh, progress)

    progress("Reading the downloaded files")
    hipparcos = read_hipparcos(main_csv, parallax_csv)
    matches = read_gaia_matches(gaia_csvs)
    iau_names = parse_iau_names(iau_txt.read_text(encoding="utf-8"))

    progress(f"Building stars from {len(hipparcos):,} Hipparcos entries")
    result = build_stars(hipparcos, matches, iau_names, max_vmag=max_vmag)
    entries = [entry for star in result.stars if (entry := search_entry(star)) is not None]

    progress(f"Writing {len(result.stars):,} stars to {database}")
    connection = open_database(database)
    try:
        replace_stars(connection, result.stars, entries)
        for key, name, files in (
            (
                "hipparcos",
                "Hipparcos main catalogue and new reduction (via VizieR)",
                [main_csv, parallax_csv],
            ),
            ("gaia_dr3", "Gaia DR3 and Hipparcos cross-match", gaia_csvs[:1]),
            ("bailer_jones_2021", "Bailer-Jones et al. 2021 geometric distances", gaia_csvs[:1]),
            ("iau_csn", "IAU Catalog of Star Names", [iau_txt]),
        ):
            set_meta(
                connection,
                f"source.{key}",
                json.dumps({"name": name, "retrieved": _retrieved(files[0])}, sort_keys=True),
            )
        set_meta(connection, "stars.max_vmag", "none" if max_vmag is None else str(max_vmag))
    finally:
        connection.close()

    fame_counts: dict[int, int] = {}
    for star in result.stars:
        fame_counts[star.fame] = fame_counts.get(star.fame, 0) + 1
    return StarsReport(
        hipparcos_total=len(hipparcos),
        built=len(result.stars),
        by_source=dict(result.sources),
        skipped=dict(result.skipped),
        searchable=len(entries),
        named=sum(1 for star in result.stars if not star.name.startswith("HIP ")),
        fame_counts=dict(sorted(fame_counts.items())),
        database=database,
        database_bytes=database.stat().st_size,
    )


def format_stars_report(report: StarsReport) -> str:
    """A plain-text summary of a stars build."""
    lines = [
        f"Stars built: {report.built:,} of {report.hipparcos_total:,} Hipparcos entries",
        "Distance source: "
        + ", ".join(f"{name} {count:,}" for name, count in sorted(report.by_source.items())),
        "Left out: "
        + (
            ", ".join(f"{reason} {count:,}" for reason, count in sorted(report.skipped.items()))
            or "nothing"
        ),
        f"IAU-named stars: {report.named:,}; searchable: {report.searchable:,}",
        "Fame: " + ", ".join(f"{score}: {count:,}" for score, count in report.fame_counts.items()),
        f"Database: {report.database} ({report.database_bytes / 1_000_000:.1f} MB)",
    ]
    return "\n".join(lines)
