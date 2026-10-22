"""Tests for turning archive rows into exoplanet vantage points (handmade data)."""

from collections import Counter
from pathlib import Path

import pytest

from earthlight.lookback import PARSEC_IN_LIGHT_YEARS, LookbackRange
from earthlight.models import VantageKind, VantagePoint
from earthlight_pipeline.exoplanets import (
    FAMOUS_EXOPLANETS,
    ArchivePlanet,
    SkipPlanet,
    StarIndex,
    archive_range,
    build_exoplanets,
    choose_planet_distance,
    exoplanet_host_hips,
    fame_for_planet,
    host_gaia_ids_needed,
    read_archive,
    read_host_distances,
    slugify,
)
from earthlight_pipeline.stars import GaiaMatch

LY = PARSEC_IN_LIGHT_YEARS


def planet(**overrides: object) -> ArchivePlanet:
    values: dict[str, object] = {
        "name": "Test b",
        "host_name": "Test",
        "controversial": False,
        "distance_pc": 10.0,
        "error_upper_pc": 1.0,
        "error_lower_pc": -2.0,
        "vmag": 8.5,
        "ra_deg": 100.0,
        "dec_deg": 20.0,
        "gaia_host_id": 4_000_000_000_000_000_001,
        "hip": None,
        "discovery_year": 2010,
        "discovery_method": "Transit",
        "planets_in_system": 2,
        "radius_earth": 1.5,
        "mass_earth": 3.0,
        "orbital_period_days": 12.0,
    }
    return ArchivePlanet(**(values | overrides))  # type: ignore[arg-type]


NO_STARS = StarIndex({}, {})


# --- the archive's own range -----------------------------------------------------------------


def test_the_archive_range_uses_asymmetric_error_bounds() -> None:
    result = archive_range(planet())
    assert result is not None
    assert result.minimum == pytest.approx(8.0 * LY)  # 10 - 2
    assert result.best == pytest.approx(10.0 * LY)
    assert result.maximum == pytest.approx(11.0 * LY)  # 10 + 1


@pytest.mark.parametrize(
    "changes",
    [
        {"distance_pc": None},
        {"error_upper_pc": None},
        {"error_lower_pc": None},
        {"error_upper_pc": -1.0},  # signs the wrong way round
        {"error_lower_pc": 1.0},
        {"distance_pc": 2.0, "error_lower_pc": -2.0},  # the lower bound reaches zero
        {"distance_pc": 2.0, "error_lower_pc": -3.0},  # and below
    ],
)
def test_an_unusable_archive_range_is_none(changes: dict[str, object]) -> None:
    assert archive_range(planet(**changes)) is None


def test_an_error_of_zero_is_a_valid_range_of_zero_width_only_if_the_archive_says_so() -> None:
    result = archive_range(planet(error_upper_pc=0.0, error_lower_pc=0.0))
    assert result is not None and result.minimum == result.best == result.maximum


# --- which hosts we need ---------------------------------------------------------------------


def test_only_planets_without_a_usable_range_need_their_host_distance() -> None:
    planets = [
        planet(name="a", gaia_host_id=5),  # complete range: not needed
        planet(name="b", gaia_host_id=3, error_upper_pc=None),
        planet(name="c", gaia_host_id=2, distance_pc=None),
        planet(name="d", gaia_host_id=3, distance_pc=None),  # same host as b: once
        planet(name="e", gaia_host_id=None, distance_pc=None),  # no host id to ask about
    ]
    assert host_gaia_ids_needed(planets) == [2, 3]


def test_host_stars_are_found_by_hip_name_and_by_gaia_id() -> None:
    planets = [
        planet(name="a", hip=100, gaia_host_id=None),
        planet(name="b", hip=None, gaia_host_id=777),
        planet(name="c", hip=None, gaia_host_id=888),  # Gaia id of a non-Hipparcos star
        planet(name="d", hip=100, gaia_host_id=777),
    ]
    matches = {
        200: GaiaMatch(
            hip=200, source_id=777, parallax_mas=1.0, parallax_error_mas=0.1, geo_distance_pc=None
        )
    }
    assert exoplanet_host_hips(planets, matches) == {100, 200}


# --- names and ids ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Proxima Cen b", "proxima-cen-b"),
        ("Teegarden's Star d", "teegarden-s-star-d"),
        ("TOI-836.01", "toi-836-01"),
        ("WISEP J121756.91+162640.2 A b", "wisep-j121756-91-162640-2-a-b"),
        ("KMT-2024-BLG-0176L b", "kmt-2024-blg-0176l-b"),
        ("  ", ""),
        ("---", ""),
        ("Étoile b", "toile-b"),  # non-ASCII letters are dropped, never kept
    ],
)
def test_slugify(name: str, expected: str) -> None:
    assert slugify(name) == expected


def test_a_very_long_name_is_cut_without_a_trailing_hyphen() -> None:
    result = slugify("a " * 80)
    assert len(result) <= 100 and not result.endswith("-") and result.startswith("a-a")


# --- choosing a distance ---------------------------------------------------------------------

HOSTS = {4_000_000_000_000_000_001: (9.0, 10.0, 12.0)}


def test_the_archive_range_wins_when_it_is_complete() -> None:
    lookback, source = choose_planet_distance(planet(), HOSTS)
    assert source == "exoplanet_archive"
    assert lookback.best == pytest.approx(10.0 * LY)


@pytest.mark.parametrize("changes", [{"error_upper_pc": None}, {"distance_pc": None}])
def test_the_hosts_bailer_jones_range_is_the_fallback(changes: dict[str, object]) -> None:
    lookback, source = choose_planet_distance(planet(**changes), HOSTS)
    assert source == "bailer_jones_host"
    assert (lookback.minimum, lookback.best, lookback.maximum) == pytest.approx(
        (9.0 * LY, 10.0 * LY, 12.0 * LY)
    )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"distance_pc": None, "gaia_host_id": None}, "no_distance"),
        ({"distance_pc": None, "gaia_host_id": 99}, "no_distance"),  # host not in the table
        ({"error_upper_pc": None, "gaia_host_id": None}, "no_distance_error"),
        ({"error_upper_pc": None, "gaia_host_id": 99}, "no_distance_error"),
    ],
)
def test_a_planet_without_any_trustworthy_range_is_skipped(
    changes: dict[str, object], reason: str
) -> None:
    with pytest.raises(SkipPlanet) as skip:
        choose_planet_distance(planet(**changes), HOSTS)
    assert skip.value.reason == reason


@pytest.mark.parametrize("host", [(0.0, 10.0, 12.0), (11.0, 10.0, 12.0), (9.0, 13.0, 12.0)])
def test_an_impossible_host_range_is_not_used(host: tuple[float, float, float]) -> None:
    with pytest.raises(SkipPlanet):
        choose_planet_distance(planet(distance_pc=None), {4_000_000_000_000_000_001: host})


def test_a_zero_width_range_is_never_invented() -> None:
    # The danger this guards against: a planet with no error bars looking perfectly precise.
    built = build_exoplanets(
        [planet(error_upper_pc=None, gaia_host_id=None), planet(name="Ok b")], HOSTS, NO_STARS
    )
    assert [r.point.name for r in built.records] == ["Ok b"]
    assert built.skipped == Counter({"no_distance_error": 1})
    for record in built.records:
        assert record.point.lookback.minimum < record.point.lookback.maximum


# --- fame ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "light_years", "expected"),
    [
        ("Nobody b", 100.0, 0),
        ("Nobody b", 12.0, 3),
        ("Nobody b", 12.01, 0),
        ("51 Peg b", 50.4, 4),
        ("Kepler-22 b", 634.8, 3),
        ("Proxima Cen b", 4.2, 4),  # famous and near: the higher score stays
    ],
)
def test_planet_fame(name: str, light_years: float, expected: int) -> None:
    assert fame_for_planet(name, light_years) == expected


def test_the_famous_list_uses_archive_names() -> None:
    assert set(FAMOUS_EXOPLANETS) == {
        "51 Peg b",
        "HD 209458 b",
        "Proxima Cen b",
        "TRAPPIST-1 e",
        "Kepler-22 b",
    }
    assert all(0 < score <= 5 for score in FAMOUS_EXOPLANETS.values())


# --- linking to stars ------------------------------------------------------------------------


def make_star(id_: str, hip: int | None, gaia: str | None) -> VantagePoint:
    from earthlight.lookback import LookbackRange

    facts: dict[str, int | str] = {}
    if hip is not None:
        facts["hip"] = hip
    if gaia is not None:
        facts["gaia_dr3_source_id"] = gaia
    return VantagePoint(
        id=id_, name=id_, kind=VantageKind.STAR, lookback=LookbackRange(1.0, 1.0, 1.0), facts=facts
    )


def test_the_star_index_reads_hip_and_gaia_ids_from_facts() -> None:
    index = StarIndex.from_stars(
        [make_star("hip-1", 1, "111"), make_star("hip-2", 2, None), make_star("odd", None, "x1")]
    )
    assert index.by_hip == {1: "hip-1", 2: "hip-2"}
    assert index.by_gaia_id == {111: "hip-1"}  # "x1" is not a number


def test_a_planet_links_by_hip_name_first_then_by_gaia_id() -> None:
    index = StarIndex({7: "hip-7"}, {555: "hip-9"})
    assert index.host_of(planet(hip=7, gaia_host_id=555)) == "hip-7"
    assert index.host_of(planet(hip=None, gaia_host_id=555)) == "hip-9"
    assert index.host_of(planet(hip=8, gaia_host_id=555)) == "hip-9"  # HIP 8 is not in the database
    assert index.host_of(planet(hip=8, gaia_host_id=1)) is None
    assert index.host_of(planet(hip=None, gaia_host_id=None)) is None


# --- building --------------------------------------------------------------------------------


def test_build_exoplanets_applies_every_rule() -> None:
    index = StarIndex({7: "hip-7"}, {555: "hip-9"})
    planets = [
        planet(name="Alpha b", hip=7),  # linked by HIP
        planet(name="Beta b", gaia_host_id=555),  # linked by Gaia id
        planet(name="Gamma b", distance_pc=None, gaia_host_id=4_000_000_000_000_000_001),  # BJ host
        planet(name="Delta b", distance_pc=None, gaia_host_id=None),  # no distance: skipped
        planet(name="Eps b", ra_deg=None),  # no position
        planet(name="Zeta b", dec_deg=91.0),  # impossible position
        planet(name="Eta b", ra_deg=361.0),
        planet(name="Same b"),
        planet(name="same-b"),  # the same id as the one before
        planet(name="x" * 300),  # a name the models reject
    ]
    result = build_exoplanets(planets, HOSTS, index)
    assert [r.point.id for r in result.records] == [
        "alpha-b",
        "beta-b",
        "gamma-b",
        "same-b",
    ]
    assert result.skipped == Counter(
        {"no_distance": 1, "no_position": 1, "invalid_position": 2, "duplicate_id": 1, "invalid": 1}
    )
    assert result.sources == Counter({"exoplanet_archive": 3, "bailer_jones_host": 1})
    assert result.linked == 2
    alpha, beta, gamma, _same = (r.point for r in result.records)
    assert alpha.host_id == "hip-7" and beta.host_id == "hip-9" and gamma.host_id is None
    assert alpha.kind is VantageKind.EXOPLANET
    assert alpha.constellation  # from astropy
    assert alpha.magnitude == 8.5
    assert alpha.facts == {
        "distance_source": "exoplanet_archive",
        "planets_in_system": 2,
        "gaia_dr3_host_id": "4000000000000000001",
    }
    assert gamma.facts["distance_source"] == "bailer_jones_host"


def test_planet_details_and_search_entries_are_built_with_the_planet() -> None:
    result = build_exoplanets([planet(name="Test b", hip=42, controversial=True)], HOSTS, NO_STARS)
    (record,) = result.records
    details = record.details
    assert (details.vantage_id, details.nasa_name, details.host_name) == (
        "test-b",
        "Test b",
        "Test",
    )
    assert (details.discovery_year, details.discovery_method) == (2010, "Transit")
    assert (details.radius_earth, details.mass_earth, details.orbital_period_days) == (
        1.5,
        3.0,
        12.0,
    )
    assert details.controversial is True
    entry = record.search
    assert (entry.type, entry.id, entry.name) == ("vantage_point", "test-b", "Test b")
    assert entry.aliases == "Test\nHIP 42"
    assert entry.description == "Exoplanet orbiting Test"


def test_a_planet_without_a_hip_host_has_only_the_host_name_alias() -> None:
    (record,) = build_exoplanets([planet(hip=None)], HOSTS, NO_STARS).records
    assert record.search.aliases == "Test"


def test_right_ascension_is_wrapped_and_empty_input_builds_nothing() -> None:
    (record,) = build_exoplanets([planet(ra_deg=360.0)], HOSTS, NO_STARS).records
    assert record.point.ra_deg == 0.0
    empty = build_exoplanets([], HOSTS, NO_STARS)
    assert empty.records == [] and empty.linked == 0 and empty.skipped == Counter()


# --- reading the files -----------------------------------------------------------------------


HEADER = (
    "pl_name,hostname,pl_controv_flag,sy_dist,sy_disterr1,sy_disterr2,sy_vmag,ra,dec,gaia_dr3_id,"
    "hip_name,disc_year,discoverymethod,sy_pnum,pl_rade,pl_bmasse,pl_orbper\n"
)


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_read_archive_parses_every_column_and_tolerates_blanks(tmp_path: Path) -> None:
    rows = (
        "  Alpha   b ,Alpha,1,10.5,0.5,-0.4,8.1,100.5,-20.25,Gaia DR3 123,HIP 77,2015,"
        " Radial Velocity ,3,1.5,4.5,9.5\n"
        "Beta b,Beta,0,,,,,,,,,,,,,,\n"
        "Gamma b,Gamma,0,-5,x,inf,nan,1,1,Gaia DR2 9,not a hip,2020x,Transit,two,0,-1,0\n"
        ",Nameless,0,1,1,1,1,1,1,,,,,,,,\n"
        "Delta b,,0,1,1,1,1,1,1,,,,,,,,\n"
    )
    planets = {p.name: p for p in read_archive(write(tmp_path / "ps.csv", HEADER + rows))}
    assert sorted(planets) == [
        "Alpha b",
        "Beta b",
        "Gamma b",
    ]  # rows without a name or host are dropped
    alpha = planets["Alpha b"]
    assert alpha.controversial is True
    assert (alpha.distance_pc, alpha.error_upper_pc, alpha.error_lower_pc) == (10.5, 0.5, -0.4)
    assert (alpha.ra_deg, alpha.dec_deg, alpha.vmag) == (100.5, -20.25, 8.1)
    assert (alpha.gaia_host_id, alpha.hip) == (123, 77)
    assert (alpha.discovery_year, alpha.discovery_method, alpha.planets_in_system) == (
        2015,
        "Radial Velocity",
        3,
    )
    assert (alpha.radius_earth, alpha.mass_earth, alpha.orbital_period_days) == (1.5, 4.5, 9.5)
    beta = planets["Beta b"]
    assert beta.distance_pc is None and beta.ra_deg is None and beta.gaia_host_id is None
    assert beta.controversial is False
    gamma = planets["Gamma b"]
    assert gamma.distance_pc is None  # a distance must be positive
    assert gamma.error_upper_pc is None and gamma.error_lower_pc is None  # "x" and "inf"
    assert gamma.gaia_host_id is None and gamma.hip is None  # only "Gaia DR3 n" and "HIP n"
    assert gamma.discovery_year is None and gamma.planets_in_system is None
    assert gamma.radius_earth is None and gamma.mass_earth is None  # not positive
    assert gamma.orbital_period_days is None


def test_read_host_distances_skips_incomplete_rows(tmp_path: Path) -> None:
    first = write(
        tmp_path / "a.csv",
        "source_id,r_lo_geo,r_med_geo,r_hi_geo\n123,9.5,10.0,10.6\n124,,,\n125,1,2\nx,1,2,3\n",
    )
    second = write(tmp_path / "b.csv", "source_id,r_lo_geo,r_med_geo,r_hi_geo\n999,1,2,3\n")
    assert read_host_distances([first, second]) == {123: (9.5, 10.0, 10.6), 999: (1.0, 2.0, 3.0)}


# --- a planet should sit where its own star sits ------------------------------------------------


def gaia_star(star_id: str, low: float, best: float, high: float) -> VantagePoint:
    return VantagePoint(
        id=star_id,
        name=star_id,
        kind=VantageKind.STAR,
        lookback=LookbackRange(low, best, high),
        facts={"hip": 7, "distance_source": "gaia"},
    )


def test_a_planet_far_from_its_gaia_host_takes_the_hosts_range() -> None:
    index = StarIndex.from_stars([gaia_star("hip-7", 8.2, 8.3, 8.4)])
    result = build_exoplanets([planet(hip=7)], {}, index)
    (record,) = result.records
    assert record.point.lookback.best == 8.3
    assert record.point.facts["distance_source"] == "host_star"
    assert result.sources == Counter({"host_star": 1})


def test_a_planet_that_agrees_with_its_host_keeps_the_archive_range() -> None:
    own = archive_range(planet())
    assert own is not None
    index = StarIndex.from_stars([gaia_star("hip-7", own.minimum, own.best, own.maximum)])
    (record,) = build_exoplanets([planet(hip=7)], {}, index).records
    assert record.point.facts["distance_source"] == "exoplanet_archive"
    assert record.point.lookback == own


def test_a_host_whose_distance_is_not_from_gaia_never_overrides_the_planet() -> None:
    star = gaia_star("hip-7", 8.2, 8.3, 8.4).model_copy(
        update={"facts": {"hip": 7, "distance_source": "hipparcos"}}
    )
    (record,) = build_exoplanets([planet(hip=7)], {}, StarIndex.from_stars([star])).records
    assert record.point.facts["distance_source"] == "exoplanet_archive"


def test_a_tiny_gap_between_precise_ranges_is_not_a_disagreement() -> None:
    precise = planet(hip=7, error_upper_pc=0.001, error_lower_pc=-0.001)
    own = archive_range(precise)
    assert own is not None
    just_above = own.maximum * 1.001
    index = StarIndex.from_stars([gaia_star("hip-7", just_above, just_above, just_above * 1.0001)])
    (record,) = build_exoplanets([precise], {}, index).records
    assert record.point.facts["distance_source"] == "exoplanet_archive"
