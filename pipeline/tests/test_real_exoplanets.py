"""Tests on real data: 19 planets cut from the Exoplanet Archive and the Gaia archive.

The fixtures in ``tests/data/`` are excerpts, in the services' own formats, retrieved on
2026-10-21 (see docs/data-sources.md):

* ``exoplanet_archive_sample.csv``: rows of the archive's Planetary Systems table
* ``gaia_hosts_sample.csv``: Bailer-Jones distances for planet host stars

They hold the well-known planets (Proxima Cen b, TRAPPIST-1 e, 51 Peg b, HD 209458 b,
Kepler-22 b), a very close planet and a very distant one, planets hosted by the stars Belenos
and Monch from the star fixtures (so linking is tested with real names), and one real
example of each reason a planet is left out or rescued. Expected values are what the pipeline
produced from them and were checked by hand against the archive and against known distances.
"""

from collections import Counter
from pathlib import Path

import pytest

from earthlight.models import VantagePoint
from earthlight_pipeline.exoplanets import (
    ArchivePlanet,
    ExoplanetBuild,
    ExoplanetRecord,
    StarIndex,
    build_exoplanets,
    exoplanet_host_hips,
    host_gaia_ids_needed,
    read_archive,
    read_host_distances,
)
from earthlight_pipeline.stars import (
    build_stars,
    parse_iau_names,
    read_gaia_matches,
    read_hipparcos,
)

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def planets() -> list[ArchivePlanet]:
    return read_archive(DATA / "exoplanet_archive_sample.csv")


@pytest.fixture(scope="module")
def stars() -> list[VantagePoint]:
    names = parse_iau_names((DATA / "iau_csn_sample.txt").read_text(encoding="utf-8"))
    hipparcos = read_hipparcos(DATA / "hip_main_sample.csv", DATA / "hip2_sample.csv")
    matches = read_gaia_matches([DATA / "gaia_sample.csv"])
    return build_stars(hipparcos, matches, names).stars


@pytest.fixture(scope="module")
def built(planets: list[ArchivePlanet], stars: list[VantagePoint]) -> ExoplanetBuild:
    host_distances = read_host_distances([DATA / "gaia_hosts_sample.csv"])
    return build_exoplanets(planets, host_distances, StarIndex.from_stars(stars))


def by_name(built: ExoplanetBuild) -> dict[str, ExoplanetRecord]:
    return {record.point.name: record for record in built.records}


# name, ly min, best, max, distance source, host star id, fame
EXPECTED = [
    ("Proxima Cen b", 4.2438, 4.2438, 4.2439, "exoplanet_archive", "hip-70890", 4),
    ("Proxima Cen d", 4.2438, 4.2438, 4.2439, "exoplanet_archive", "hip-70890", 3),
    ("Teegarden's Star d", 12.48, 12.49, 12.51, "exoplanet_archive", None, 0),
    ("51 Peg b", 50.33, 50.43, 50.53, "exoplanet_archive", None, 4),
    ("TRAPPIST-1 b", 40.58, 40.62, 40.66, "bailer_jones_host", None, 0),
    ("TRAPPIST-1 e", 40.58, 40.62, 40.66, "bailer_jones_host", None, 4),
    ("HD 209458 b", 157.14, 157.54, 157.94, "exoplanet_archive", None, 4),
    ("Kepler-22 b", 631.84, 634.84, 637.86, "exoplanet_archive", None, 3),
    ("WASP-103 b", 1664.72, 1778.83, 1867.45, "bailer_jones_host", None, 0),
    ("KMT-2024-BLG-0176L b", 23515.87, 27201.44, 30495.62, "exoplanet_archive", None, 0),
]


@pytest.mark.parametrize(
    ("name", "low", "best", "high", "source", "host", "fame"),
    EXPECTED,
    ids=[e[0] for e in EXPECTED],
)
def test_known_planets_have_the_right_distance_source_and_fame(
    built: ExoplanetBuild,
    name: str,
    low: float,
    best: float,
    high: float,
    source: str,
    host: str | None,
    fame: int,
) -> None:
    point = by_name(built)[name].point
    assert point.lookback.minimum == pytest.approx(low, abs=0.01)
    assert point.lookback.best == pytest.approx(best, abs=0.01)
    assert point.lookback.maximum == pytest.approx(high, abs=0.01)
    assert point.facts["distance_source"] == source
    assert point.fame == fame
    if host is not None:
        assert point.host_id == host


def test_proxima_cen_b_is_linked_to_proxima_centauri_and_has_its_details(
    built: ExoplanetBuild,
) -> None:
    record = by_name(built)["Proxima Cen b"]
    assert record.point.id == "proxima-cen-b"
    assert record.point.host_id == "hip-70890"
    assert record.point.constellation == "Centaurus"
    assert record.details.host_name == "Proxima Cen"
    assert record.details.discovery_year == 2016
    assert record.details.discovery_method == "Radial Velocity"
    assert record.details.mass_earth == pytest.approx(1.055)
    assert record.details.orbital_period_days == pytest.approx(11.18465)
    assert record.details.radius_earth is None  # the archive has no radius for it


def test_trappist_1_has_no_distance_in_the_archive_and_uses_its_hosts(
    built: ExoplanetBuild,
) -> None:
    # The host (Gaia DR3 2635476908753563008) is 12.454 pc away: about 40.6 light-years.
    trappist = by_name(built)["TRAPPIST-1 b"]
    assert trappist.point.facts["distance_source"] == "bailer_jones_host"
    assert trappist.point.facts["gaia_dr3_host_id"] == "2635476908753563008"
    assert trappist.point.lookback.best == pytest.approx(12.454126 * 3.26156, abs=0.01)
    assert trappist.point.facts["planets_in_system"] == 7
    assert trappist.details.radius_earth == pytest.approx(1.116)


def test_planets_hosted_by_named_stars_in_the_database_are_linked(built: ExoplanetBuild) -> None:
    records = by_name(built)
    assert records["HD 8574 b"].point.host_id == "hip-6643"  # Belenos
    assert records["HD 130322 b"].point.host_id == "hip-72339"  # Monch
    assert records["HD 209458 b"].point.host_id is None  # HIP 108859 is not in the star fixtures


def test_a_controversial_planet_is_flagged_but_kept(built: ExoplanetBuild) -> None:
    k2_18c = by_name(built)["K2-18 c"]
    assert k2_18c.details.controversial is True
    assert by_name(built)["Proxima Cen b"].details.controversial is False


def test_a_planet_with_no_error_bars_takes_its_hosts_range(built: ExoplanetBuild) -> None:
    wasp_20 = by_name(built)["WASP-20 b"]  # the archive gives 211.9 pc and no error bounds
    assert wasp_20.point.facts["distance_source"] == "bailer_jones_host"
    assert wasp_20.point.lookback.minimum < wasp_20.point.lookback.maximum


def test_planets_that_cannot_be_built_are_left_out_for_the_right_reason(
    built: ExoplanetBuild,
) -> None:
    names = set(by_name(built))
    assert "K2-65 b" not in names  # no distance and no host id
    assert "Kepler-1064 b" not in names  # no distance and the host has no Bailer-Jones distance
    assert "Kepler-400 b" not in names  # a distance but no error bounds and no host id
    assert built.skipped == Counter({"no_distance": 2, "no_distance_error": 1})
    assert len(built.records) == 16
    assert built.sources == Counter({"exoplanet_archive": 12, "bailer_jones_host": 4})
    assert built.linked == 4  # Proxima b and d, HD 8574 b, HD 130322 b


def test_no_planet_has_a_range_of_zero_width(built: ExoplanetBuild) -> None:
    assert all(r.point.lookback.minimum < r.point.lookback.maximum for r in built.records)


def test_ids_are_slugs_of_the_archive_names(built: ExoplanetBuild) -> None:
    ids = {r.point.name: r.point.id for r in built.records}
    assert ids["Teegarden's Star d"] == "teegarden-s-star-d"
    assert ids["TOI-836.01"] == "toi-836-01"
    assert ids["KMT-2024-BLG-0176L b"] == "kmt-2024-blg-0176l-b"
    assert len(set(ids.values())) == len(ids)


def test_the_hosts_the_star_build_must_keep(planets: list[ArchivePlanet]) -> None:
    matches = read_gaia_matches([DATA / "gaia_sample.csv"])
    hosts = exoplanet_host_hips(planets, matches)
    assert {70890, 6643, 72339, 108859, 113357, 73427, 109656} <= hosts
    # TRAPPIST-1 and Kepler-22 are not Hipparcos stars, so they add nothing.
    assert all(isinstance(h, int) for h in hosts)


def test_which_hosts_need_a_bailer_jones_lookup(planets: list[ArchivePlanet]) -> None:
    needed = host_gaia_ids_needed(planets)
    assert 2635476908753563008 in needed  # TRAPPIST-1: no archive distance
    assert 5853498713190525696 not in needed  # Proxima: the archive range is complete
    assert needed == sorted(set(needed))
