"""Where the star data comes from, and how it is downloaded and cached.

Every function here returns the path of a cached file and does no interpretation of it; that
is ``stars.py``'s job. Queries and table names are documented, with what was found when each
service was checked, in ``docs/data-sources.md``.
"""

import csv
import hashlib
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlencode

from earthlight_pipeline.cache import cached_download

VIZIER_TAP = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
EXOPLANET_ARCHIVE_TAP = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
SIMBAD_TAP = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"
IAU_CSN_URL = "https://www.pas.rochester.edu/~emamajek/WGSN/IAU-CSN.txt"

TAP_TIMEOUT_SECONDS = 900
"""A Gaia query for 20,000 Hipparcos numbers takes about a minute, and can be slower."""

TAP_RETRIES = 3
TAP_RETRY_WAIT_SECONDS = 15.0
"""Dropped connections are retried this many times, waiting 15 s and then double each time."""

GAIA_BATCH_SIZE = 20_000
"""Hipparcos numbers per Gaia query. The archive returns at most 50,000 rows per query."""

SIMBAD_BATCH_SIZE = 90
"""Identifier spellings per SIMBAD query, which keeps the URL well under 8 kB."""

Progress = Callable[[str], None]


def _ignore(_: str) -> None:
    return None


def tap_url(endpoint: str, query: str) -> str:
    """The GET URL that runs ``query`` (ADQL) on a TAP service and returns CSV."""
    parameters = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}
    return f"{endpoint}?{urlencode(parameters)}"


def fetch_hipparcos_main(
    cache_dir: Path | None, refresh: bool, progress: Progress = _ignore
) -> Path:
    """Hipparcos main catalogue (VizieR I/239/hip_main): V magnitude, position, spectral type."""
    progress("Downloading the Hipparcos main catalogue (VizieR I/239/hip_main)")
    query = 'SELECT "HIP", "Vmag", "RAICRS", "DEICRS", "SpType", "HD" FROM "I/239/hip_main"'
    return cached_download(
        tap_url(VIZIER_TAP, query),
        "vizier_hip_main.csv",
        cache_dir=cache_dir,
        refresh=refresh,
        timeout=TAP_TIMEOUT_SECONDS,
        retries=TAP_RETRIES,
        retry_wait=TAP_RETRY_WAIT_SECONDS,
        notify=progress,
    )


def fetch_hipparcos_parallaxes(
    cache_dir: Path | None, refresh: bool, progress: Progress = _ignore
) -> Path:
    """Hipparcos new reduction (VizieR I/311/hip2): parallax and its error, in milliarcseconds."""
    progress("Downloading the Hipparcos new-reduction parallaxes (VizieR I/311/hip2)")
    query = 'SELECT "HIP", "Plx", "e_Plx" FROM "I/311/hip2"'
    return cached_download(
        tap_url(VIZIER_TAP, query),
        "vizier_hip2.csv",
        cache_dir=cache_dir,
        refresh=refresh,
        timeout=TAP_TIMEOUT_SECONDS,
        retries=TAP_RETRIES,
        retry_wait=TAP_RETRY_WAIT_SECONDS,
        notify=progress,
    )


def gaia_batches(max_hip: int, size: int = GAIA_BATCH_SIZE) -> list[tuple[int, int]]:
    """Inclusive ranges of Hipparcos numbers that together cover 1 to ``max_hip``."""
    if max_hip < 1 or size < 1:
        raise ValueError("max_hip and size must be positive")
    return [(low, min(low + size - 1, max_hip)) for low in range(1, max_hip + 1, size)]


def gaia_match_query(low: int, high: int) -> str:
    """ADQL for the Gaia matches of Hipparcos stars ``low`` to ``high``, with distances.

    Only plain ``WHERE``, ``JOIN``, and ``LEFT JOIN`` are used: the Gaia archive rejects
    parenthesized AND/OR groups (see docs/data-sources.md).
    """
    return (
        "SELECT h.original_ext_source_id AS hip, h.source_id, g.parallax, g.parallax_error, "
        "g.phot_g_mean_mag, d.r_med_geo, d.r_lo_geo, d.r_hi_geo "
        "FROM gaiadr3.hipparcos2_best_neighbour AS h "
        "JOIN gaiadr3.gaia_source AS g ON g.source_id = h.source_id "
        "LEFT JOIN external.gaiaedr3_distance AS d ON d.source_id = h.source_id "
        f"WHERE h.original_ext_source_id BETWEEN {int(low)} AND {int(high)}"
    )


def fetch_gaia_matches(
    max_hip: int, cache_dir: Path | None, refresh: bool, progress: Progress = _ignore
) -> list[Path]:
    """Gaia DR3 matches and Bailer-Jones distances for every Hipparcos star, in batches."""
    paths: list[Path] = []
    batches = gaia_batches(max_hip)
    for number, (low, high) in enumerate(batches, start=1):
        progress(
            f"Downloading Gaia matches for Hipparcos {low} to {high} ({number} of {len(batches)})"
        )
        paths.append(
            cached_download(
                tap_url(GAIA_TAP, gaia_match_query(low, high)),
                f"gaia_hip_{low:06d}_{high:06d}.csv",
                cache_dir=cache_dir,
                refresh=refresh,
                timeout=TAP_TIMEOUT_SECONDS,
                retries=TAP_RETRIES,
                retry_wait=TAP_RETRY_WAIT_SECONDS,
                notify=progress,
            )
        )
    return paths


def fetch_iau_names(cache_dir: Path | None, refresh: bool, progress: Progress = _ignore) -> Path:
    """The IAU Catalog of Star Names (IAU Working Group on Star Names)."""
    progress("Downloading the IAU Catalog of Star Names")
    return cached_download(IAU_CSN_URL, "iau_csn.txt", cache_dir=cache_dir, refresh=refresh)


def max_hipparcos_number(hip_main_csv: Path) -> int:
    """The largest Hipparcos number in the downloaded main catalogue."""
    with hip_main_csv.open(encoding="utf-8", newline="") as handle:
        numbers = [int(row["HIP"]) for row in csv.DictReader(handle) if row["HIP"].strip()]
    if not numbers:
        raise ValueError(f"{hip_main_csv} has no Hipparcos stars")
    return max(numbers)


EXOPLANET_COLUMNS = (
    "pl_name",
    "hostname",
    "pl_controv_flag",
    "sy_dist",
    "sy_disterr1",
    "sy_disterr2",
    "sy_vmag",
    "ra",
    "dec",
    "gaia_dr3_id",
    "hip_name",
    "disc_year",
    "discoverymethod",
    "sy_pnum",
    "pl_rade",
    "pl_bmasse",
    "pl_orbper",
)
"""The Planetary Systems columns the build reads (see docs/data-sources.md)."""

HOST_DISTANCE_BATCH_SIZE = 100
"""Gaia source ids per Bailer-Jones query, to keep the URL short."""


def exoplanet_query() -> str:
    """ADQL for one row per planet (the archive's default parameter set)."""
    return f"select {', '.join(EXOPLANET_COLUMNS)} from ps where default_flag = 1"


def fetch_exoplanet_archive(
    cache_dir: Path | None, refresh: bool, progress: Progress = _ignore
) -> Path:
    """The NASA Exoplanet Archive's Planetary Systems table, one row per planet."""
    progress("Downloading the NASA Exoplanet Archive planets")
    return cached_download(
        tap_url(EXOPLANET_ARCHIVE_TAP, exoplanet_query()),
        "exoplanet_archive_ps.csv",
        cache_dir=cache_dir,
        refresh=refresh,
        timeout=TAP_TIMEOUT_SECONDS,
        retries=TAP_RETRIES,
        retry_wait=TAP_RETRY_WAIT_SECONDS,
        notify=progress,
    )


def host_distance_query(source_ids: Sequence[int]) -> str:
    """ADQL for the Bailer-Jones distances of the given Gaia source ids.

    Only a plain ``IN`` list is used (the Gaia archive rejects parenthesized AND/OR groups).
    """
    if not source_ids:
        raise ValueError("at least one Gaia source id is needed")
    ids = ", ".join(str(int(source_id)) for source_id in source_ids)
    return (
        "SELECT source_id, r_lo_geo, r_med_geo, r_hi_geo "
        f"FROM external.gaiaedr3_distance WHERE source_id IN ({ids})"
    )


def fetch_host_distances(
    source_ids: Sequence[int],
    cache_dir: Path | None,
    refresh: bool,
    progress: Progress = _ignore,
) -> list[Path]:
    """Bailer-Jones distances for planet host stars, in batches of 100 ids.

    The file name depends on the ids in the batch, so a different set of hosts is never read
    from an old file.
    """
    ordered = sorted(set(source_ids))
    paths: list[Path] = []
    for start in range(0, len(ordered), HOST_DISTANCE_BATCH_SIZE):
        batch = ordered[start : start + HOST_DISTANCE_BATCH_SIZE]
        digest = hashlib.sha256(",".join(map(str, batch)).encode()).hexdigest()[:12]
        progress(f"Downloading Bailer-Jones distances for {len(batch)} planet host stars")
        paths.append(
            cached_download(
                tap_url(GAIA_TAP, host_distance_query(batch)),
                f"gaia_hosts_{digest}.csv",
                cache_dir=cache_dir,
                refresh=refresh,
                timeout=TAP_TIMEOUT_SECONDS,
                retries=TAP_RETRIES,
                retry_wait=TAP_RETRY_WAIT_SECONDS,
                notify=progress,
            )
        )
    return paths


def simbad_query(identifiers: Sequence[str]) -> str:
    """ADQL for the SIMBAD rows of the given identifiers (exact spellings).

    ``asked`` is the identifier as it was asked for, so the caller can match the answer to
    the question however SIMBAD pads the main identifier.
    """
    if not identifiers:
        raise ValueError("at least one identifier is needed")
    names = ", ".join("'" + name.replace("'", "''") + "'" for name in identifiers)
    return (
        "SELECT i.id AS asked, b.main_id, b.otype, b.ra, b.dec, b.rvz_redshift, b.rvz_err, "
        "b.rvz_type, b.rvz_qual, b.rvz_bibcode "
        f"FROM ident AS i JOIN basic AS b ON b.oid = i.oidref WHERE i.id IN ({names})"
    )


def fetch_simbad(
    identifiers: Sequence[str],
    cache_dir: Path | None,
    refresh: bool,
    progress: Progress = _ignore,
) -> list[Path]:
    """SIMBAD position and redshift rows for the given identifiers, in batches.

    The file name depends on the identifiers in the batch, so a changed list is never read
    from an old file.
    """
    ordered = sorted(set(identifiers))
    paths: list[Path] = []
    for start in range(0, len(ordered), SIMBAD_BATCH_SIZE):
        batch = ordered[start : start + SIMBAD_BATCH_SIZE]
        digest = hashlib.sha256("|".join(batch).encode()).hexdigest()[:12]
        progress(f"Downloading {len(batch)} identifiers from SIMBAD")
        paths.append(
            cached_download(
                tap_url(SIMBAD_TAP, simbad_query(batch)),
                f"simbad_{digest}.csv",
                cache_dir=cache_dir,
                refresh=refresh,
                timeout=TAP_TIMEOUT_SECONDS,
                retries=TAP_RETRIES,
                retry_wait=TAP_RETRY_WAIT_SECONDS,
                notify=progress,
            )
        )
    return paths


HUNT_REFFERT_TABLE = "J/A+A/673/A114/clusters"
"""The main catalogue of Hunt and Reffert (2023) on VizieR (Table 3 of the paper)."""


def hunt_reffert_query(names: Sequence[str]) -> str:
    """ADQL for the Hunt and Reffert rows of the given catalogue names (exact spellings)."""
    if not names:
        raise ValueError("at least one cluster name is needed")
    listed = ", ".join("'" + name.replace("'", "''") + "'" for name in names)
    return (
        "SELECT Name, AllNames, Type, RA_ICRS, DE_ICRS, dist16, dist50, dist84, Ndist, globalPlx "
        f'FROM "{HUNT_REFFERT_TABLE}" WHERE Name IN ({listed})'
    )


def fetch_hunt_reffert(
    names: Sequence[str], cache_dir: Path | None, refresh: bool, progress: Progress = _ignore
) -> Path:
    """The Hunt and Reffert rows for the given cluster names, as one cached file.

    The file name depends on the names, so a changed list is never read from an old file.
    """
    ordered = sorted(set(names))
    digest = hashlib.sha256("|".join(ordered).encode()).hexdigest()[:12]
    progress(f"Downloading {len(ordered)} clusters from Hunt and Reffert (VizieR)")
    return cached_download(
        tap_url(VIZIER_TAP, hunt_reffert_query(ordered)),
        f"hunt_reffert_{digest}.csv",
        cache_dir=cache_dir,
        refresh=refresh,
        timeout=TAP_TIMEOUT_SECONDS,
        retries=TAP_RETRIES,
        retry_wait=TAP_RETRY_WAIT_SECONDS,
        notify=progress,
    )
