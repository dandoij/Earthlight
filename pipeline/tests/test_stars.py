"""Tests for turning Hipparcos, Gaia, and IAU data into star vantage points."""

from collections import Counter
from pathlib import Path

import pytest

from earthlight.lookback import PARSEC_IN_LIGHT_YEARS, lookback_range_from_parallax
from earthlight.models import VantageKind
from earthlight_pipeline.stars import (
    MIN_HIPPARCOS_PARALLAX_OVER_ERROR,
    MIN_NAMED_PARALLAX_OVER_ERROR,
    PARALLAX_OVERRIDES,
    GaiaMatch,
    HipparcosStar,
    SkipStar,
    build_stars,
    choose_distance,
    constellation_names,
    fame_for,
    parse_iau_names,
    read_gaia_matches,
    read_hipparcos,
    search_entry,
)


def star(**overrides: object) -> HipparcosStar:
    values: dict[str, object] = {
        "hip": 1,
        "ra_deg": 10.0,
        "dec_deg": 20.0,
        "vmag": 5.0,
        "spectral_type": "A0V",
        "hd": 123,
        "parallax_mas": 100.0,
        "parallax_error_mas": 1.0,
    }
    return HipparcosStar(**(values | overrides))  # type: ignore[arg-type]


def match(**overrides: object) -> GaiaMatch:
    values: dict[str, object] = {
        "hip": 1,
        "source_id": 4_000_000_000_000_000_001,
        "parallax_mas": 100.0,
        "parallax_error_mas": 0.1,
        "geo_distance_pc": (9.0, 10.0, 11.0),
    }
    return GaiaMatch(**(values | overrides))  # type: ignore[arg-type]


# --- choosing a distance ---------------------------------------------------------------------


def test_gaia_with_bailer_jones_is_preferred() -> None:
    result = choose_distance(star(), match())
    assert result.source == "gaia"
    assert result.lookback.minimum == pytest.approx(9.0 * PARSEC_IN_LIGHT_YEARS)
    assert result.lookback.best == pytest.approx(10.0 * PARSEC_IN_LIGHT_YEARS)
    assert result.lookback.maximum == pytest.approx(11.0 * PARSEC_IN_LIGHT_YEARS)
    assert result.parallax_mas == 100.0
    assert result.gaia_source_id == 4_000_000_000_000_000_001


@pytest.mark.parametrize(
    "geo",
    [None, (0.0, 10.0, 11.0), (-1.0, 10.0, 11.0), (11.0, 10.0, 9.0), (9.0, 12.0, 11.0)],
)
def test_a_missing_or_impossible_bailer_jones_range_falls_back_to_hipparcos(
    geo: tuple[float, float, float] | None,
) -> None:
    result = choose_distance(star(), match(geo_distance_pc=geo))
    assert result.source == "hipparcos"
    assert result.gaia_source_id is None
    assert result.lookback == lookback_range_from_parallax(100.0, 1.0)


def test_no_gaia_match_uses_hipparcos() -> None:
    result = choose_distance(star(parallax_mas=7.54, parallax_error_mas=0.11), None)
    assert result.source == "hipparcos"
    assert result.parallax_mas == 7.54
    # Polaris, from its Hipparcos parallax: about 433 light-years (see docs/data-sources.md).
    assert result.lookback.minimum == pytest.approx(426.3, abs=0.2)
    assert result.lookback.maximum == pytest.approx(439.0, abs=0.2)


def test_the_parallax_precision_threshold_is_inclusive() -> None:
    assert MIN_HIPPARCOS_PARALLAX_OVER_ERROR == 5.0
    assert (
        choose_distance(star(parallax_mas=5.0, parallax_error_mas=1.0), None).source == "hipparcos"
    )
    with pytest.raises(SkipStar) as skip:
        choose_distance(star(parallax_mas=4.99, parallax_error_mas=1.0), None)
    assert skip.value.reason == "parallax_not_precise"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"parallax_mas": None}, "no_parallax"),
        ({"parallax_error_mas": None}, "no_parallax"),
        ({"parallax_error_mas": 0.0}, "no_parallax"),
        ({"parallax_error_mas": -1.0}, "no_parallax"),
        ({"parallax_mas": 0.0}, "non_positive_parallax"),
        ({"parallax_mas": -3.0}, "non_positive_parallax"),
        ({"parallax_mas": 2.0, "parallax_error_mas": 2.0}, "parallax_not_precise"),
    ],
)
def test_untrustworthy_hipparcos_parallaxes_are_skipped(
    changes: dict[str, object], reason: str
) -> None:
    with pytest.raises(SkipStar) as skip:
        choose_distance(star(**changes), None)
    assert skip.value.reason == reason


def test_the_precision_threshold_can_be_lowered_per_star() -> None:
    alnilam_like = star(parallax_mas=1.65, parallax_error_mas=0.45)  # 3.67 times its error
    with pytest.raises(SkipStar):
        choose_distance(alnilam_like, None)
    result = choose_distance(alnilam_like, None, min_parallax_over_error=3.0)
    assert result.lookback.minimum == pytest.approx(1553, abs=2)
    assert result.lookback.maximum == pytest.approx(2718, abs=2)


def test_a_good_gaia_distance_rescues_a_star_with_a_poor_hipparcos_parallax() -> None:
    poor = star(parallax_mas=1.0, parallax_error_mas=5.0)
    assert choose_distance(poor, match()).source == "gaia"


# --- fame ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("named", "vmag", "light_years", "expected"),
    [
        (False, 5.0, 100.0, 0),
        (False, None, 100.0, 0),
        (True, None, 100.0, 2),
        (True, 12.0, 100.0, 2),
        (True, 6.0, 100.0, 3),
        (True, 6.01, 100.0, 2),
        (True, 3.0, 100.0, 4),
        (True, 1.5, 100.0, 5),
        (True, -1.44, 8.6, 5),
        (False, 11.0, 12.0, 3),  # nearby but unnamed
        (False, 11.0, 12.01, 0),
        (True, 11.0, 4.2, 3),  # Proxima: named, faint, very close
        (True, 0.5, 4.2, 5),  # nearby never lowers a higher score
    ],
)
def test_fame_rules(named: bool, vmag: float | None, light_years: float, expected: int) -> None:
    assert fame_for(has_iau_name=named, vmag=vmag, light_years=light_years) == expected


# --- constellations --------------------------------------------------------------------------


def test_constellation_names_come_from_astropy() -> None:
    names = constellation_names([88.7929, 37.9546, 101.2872], [7.4071, 89.2641, -16.7161])
    assert names == ["Orion", "Ursa Minor", "Canis Major"]
    assert constellation_names([], []) == []


IAU_CONSTELLATIONS = frozenset(
    [
        "Andromeda",
        "Antlia",
        "Apus",
        "Aquarius",
        "Aquila",
        "Ara",
        "Aries",
        "Auriga",
        "Boötes",
        "Caelum",
        "Camelopardalis",
        "Cancer",
        "Canes Venatici",
        "Canis Major",
        "Canis Minor",
        "Capricornus",
        "Carina",
        "Cassiopeia",
        "Centaurus",
        "Cepheus",
        "Cetus",
        "Chamaeleon",
        "Circinus",
        "Columba",
        "Coma Berenices",
        "Corona Australis",
        "Corona Borealis",
        "Corvus",
        "Crater",
        "Crux",
        "Cygnus",
        "Delphinus",
        "Dorado",
        "Draco",
        "Equuleus",
        "Eridanus",
        "Fornax",
        "Gemini",
        "Grus",
        "Hercules",
        "Horologium",
        "Hydra",
        "Hydrus",
        "Indus",
        "Lacerta",
        "Leo",
        "Leo Minor",
        "Lepus",
        "Libra",
        "Lupus",
        "Lynx",
        "Lyra",
        "Mensa",
        "Microscopium",
        "Monoceros",
        "Musca",
        "Norma",
        "Octans",
        "Ophiuchus",
        "Orion",
        "Pavo",
        "Pegasus",
        "Perseus",
        "Phoenix",
        "Pictor",
        "Pisces",
        "Piscis Austrinus",
        "Puppis",
        "Pyxis",
        "Reticulum",
        "Sagitta",
        "Sagittarius",
        "Scorpius",
        "Sculptor",
        "Scutum",
        "Serpens",
        "Sextans",
        "Taurus",
        "Telescopium",
        "Triangulum",
        "Triangulum Australe",
        "Tucana",
        "Ursa Major",
        "Ursa Minor",
        "Vela",
        "Virgo",
        "Volans",
        "Vulpecula",
    ]
)


def test_constellation_names_are_the_88_iau_names_exactly() -> None:
    # astropy misspells Chamaeleon, Ophiuchus, and Piscis Austrinus and pads Crux with a
    # space. A one degree grid over the whole sky reaches every constellation.
    ra = [float(r) for r in range(360) for _ in range(181)]
    dec = [float(d) for _ in range(360) for d in range(-90, 91)]
    assert len(IAU_CONSTELLATIONS) == 88
    assert set(constellation_names(ra, dec)) == IAU_CONSTELLATIONS


# --- building --------------------------------------------------------------------------------


def test_build_stars_applies_every_rule() -> None:
    stars = [
        star(hip=1, vmag=0.5, hd=1111, spectral_type="A0V"),  # named, bright, Gaia matched
        star(hip=2, vmag=8.0),  # unnamed, Hipparcos distance
        star(hip=3, parallax_mas=1.0, parallax_error_mas=1.0),  # imprecise, no Gaia: skipped
        star(hip=4, ra_deg=None),  # no position: skipped
        star(hip=5, vmag=11.0),  # unnamed and faint
        star(
            hip=6,
            vmag=11.0,
            parallax_mas=800.0,
            parallax_error_mas=1.0,
            hd=None,
            spectral_type=None,
        ),
        star(hip=7, vmag=None),  # unnamed, no magnitude
    ]
    result = build_stars(
        stars, {1: match(hip=1)}, {1: "Alpha Test", 6: "Nearby Test"}, max_vmag=9.0
    )
    assert [s.id for s in result.stars] == ["hip-1", "hip-2", "hip-6"]
    assert result.skipped == Counter({"parallax_not_precise": 1, "no_position": 1, "too_faint": 2})
    assert result.sources == Counter({"gaia": 1, "hipparcos": 2})

    alpha, plain, nearby = result.stars
    assert alpha.name == "Alpha Test"
    assert alpha.fame == 5
    assert alpha.kind is VantageKind.STAR
    assert alpha.facts == {
        "hip": 1,
        "distance_source": "gaia",
        "hd": 1111,
        "spectral_type": "A0V",
        "parallax_mas": 100.0,
        "gaia_dr3_source_id": "4000000000000000001",
    }
    assert plain.name == "HIP 2"
    assert plain.fame == 0
    assert plain.facts["distance_source"] == "hipparcos"
    assert "gaia_dr3_source_id" not in plain.facts
    assert nearby.fame == 3  # named, faint, but within 12 light-years: kept despite max_vmag
    assert "hd" not in nearby.facts and "spectral_type" not in nearby.facts
    assert all(s.constellation for s in result.stars)
    assert all(s.ra_deg is not None and s.dec_deg is not None for s in result.stars)


def test_named_stars_get_a_lower_precision_bar() -> None:
    assert MIN_NAMED_PARALLAX_OVER_ERROR == 3.0
    stars = [
        star(hip=1, parallax_mas=1.65, parallax_error_mas=0.45),  # 3.67: named, kept
        star(hip=2, parallax_mas=1.65, parallax_error_mas=0.45),  # 3.67: unnamed, skipped
        star(hip=3, parallax_mas=1.4, parallax_error_mas=0.5),  # 2.8: named but too imprecise
        star(hip=4, parallax_mas=1.5, parallax_error_mas=0.5),  # 3.0 exactly: named, kept
    ]
    result = build_stars(stars, {}, {1: "Alnilam", 3: "Imprecise", 4: "Edge"})
    assert [s.id for s in result.stars] == ["hip-1", "hip-4"]
    assert result.skipped == Counter({"parallax_not_precise": 2})


def test_without_a_magnitude_limit_every_usable_star_is_kept() -> None:
    result = build_stars([star(hip=1, vmag=15.0), star(hip=2, vmag=None)], {}, {})
    assert [s.id for s in result.stars] == ["hip-1", "hip-2"]
    assert result.skipped == Counter()


def test_right_ascension_is_wrapped_into_zero_to_360() -> None:
    result = build_stars([star(hip=1, ra_deg=360.0), star(hip=2, ra_deg=-0.5)], {}, {})
    assert [s.ra_deg for s in result.stars] == [0.0, 359.5]


def test_stars_are_ordered_by_hipparcos_number_not_by_text() -> None:
    result = build_stars([star(hip=n) for n in (100, 20, 3)], {}, {})
    assert [s.id for s in result.stars] == ["hip-3", "hip-20", "hip-100"]


@pytest.mark.parametrize(
    "position",
    [
        {"dec_deg": 95.0},
        {"dec_deg": -90.1},
        {"ra_deg": float("inf")},
        {"dec_deg": float("nan")},
    ],
)
def test_impossible_positions_are_skipped_without_breaking_the_rest(
    position: dict[str, float],
) -> None:
    # astropy raises for a whole batch when one declination is out of range.
    result = build_stars([star(hip=1, **position), star(hip=2)], {}, {})
    assert [s.id for s in result.stars] == ["hip-2"]
    assert result.skipped == Counter({"invalid_position": 1})


def test_a_star_the_models_reject_is_counted_not_crashed() -> None:
    too_long = "x" * 300  # a name longer than the models allow
    result = build_stars([star(hip=1), star(hip=2)], {}, {1: too_long})
    assert [s.id for s in result.stars] == ["hip-2"]
    assert result.skipped == Counter({"invalid": 1})


def test_empty_input_builds_nothing() -> None:
    result = build_stars([], {}, {})
    assert result.stars == []
    assert result.skipped == Counter() and result.sources == Counter()


# --- search entries --------------------------------------------------------------------------


def test_only_stars_with_fame_are_searchable() -> None:
    result = build_stars(
        [star(hip=1, vmag=0.5, hd=77), star(hip=2, vmag=8.0)], {}, {1: "Alpha Test"}
    )
    named, plain = result.stars
    entry = search_entry(named)
    assert entry is not None
    assert (entry.type, entry.id, entry.name) == ("vantage_point", "hip-1", "Alpha Test")
    assert entry.aliases == "HIP 1\nHD 77"
    assert entry.description.startswith("Star in ")
    assert search_entry(plain) is None


def test_a_searchable_star_without_a_hd_number_has_only_its_hip_alias() -> None:
    result = build_stars([star(hip=5, hd=None, vmag=0.5)], {}, {5: "Alpha Test"})
    entry = search_entry(result.stars[0])
    assert entry is not None and entry.aliases == "HIP 5"


# --- reading the files -----------------------------------------------------------------------


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_read_hipparcos_joins_the_two_tables_and_tolerates_blanks(tmp_path: Path) -> None:
    main = write(
        tmp_path / "main.csv",
        "HIP,Vmag,RAICRS,DEICRS,SpType,HD\n"
        "1,9.1,9.1185E-4,1.08901332,F5,224700\n"
        "2,,0.0,0.0,  K0   III ,\n"
        "3,5.0,,10.0,,\n"
        "x,5.0,1,1,,\n"
        "4,not-a-number,1,1,,12abc\n",
    )
    parallaxes = write(tmp_path / "hip2.csv", "HIP,Plx,e_Plx\n1,3.54,1.39\n2,,\n4,inf,nan\n")
    stars = {s.hip: s for s in read_hipparcos(main, parallaxes)}
    assert sorted(stars) == [1, 2, 3, 4]
    assert stars[1].vmag == 9.1 and stars[1].hd == 224700 and stars[1].spectral_type == "F5"
    assert stars[1].parallax_mas == 3.54 and stars[1].parallax_error_mas == 1.39
    assert stars[1].ra_deg == pytest.approx(9.1185e-4)
    assert stars[2].vmag is None and stars[2].hd is None
    assert stars[2].spectral_type == "K0 III"  # whitespace is tidied
    assert stars[2].parallax_mas is None
    assert stars[3].ra_deg is None and stars[3].dec_deg == 10.0
    assert stars[3].parallax_mas is None  # not in the parallax table at all
    assert stars[4].vmag is None and stars[4].hd is None
    assert stars[4].parallax_mas is None  # inf and nan are not numbers we accept


def test_read_gaia_matches_reads_batches_and_missing_distances(tmp_path: Path) -> None:
    header = "hip,source_id,parallax,parallax_error,phot_g_mean_mag,r_med_geo,r_lo_geo,r_hi_geo\n"
    first = write(
        tmp_path / "a.csv",
        header + "703,4616474464582858368,0.68,0.06,9.24,1418.5,1312.6,1548.0\n"
        "704,4616474464582858369,,,,,,\n"
        "bad,1,1,1,1,1,1,1\n",
    )
    second = write(
        tmp_path / "b.csv", header + "70890,5853498713190525696,768.067,0.05,8.98,1.3,1.29,1.31\n"
    )
    matches = read_gaia_matches([first, second])
    assert sorted(matches) == [703, 704, 70890]
    assert matches[703].source_id == 4616474464582858368  # larger than a float can hold exactly
    assert matches[703].geo_distance_pc == (1312.6, 1418.5, 1548.0)
    assert matches[704].geo_distance_pc is None and matches[704].parallax_mas is None
    assert matches[70890].parallax_mas == 768.067


# --- IAU names -------------------------------------------------------------------------------
# The real-file tests are in test_real_stars.py. These check the edges of the parser.

IAU_FIXTURE = Path(__file__).parent / "data" / "iau_csn_sample.txt"


def iau_header() -> str:
    text = IAU_FIXTURE.read_text(encoding="utf-8")
    return next(line for line in text.splitlines() if line.startswith("#Name/ASCII"))


def iau_row(name: str, hip: str) -> str:
    """A data line in the file's layout, with every field after the name filled in."""
    layout = f"{name:18}{name:18}HR 1         _     _     Ori _    _           1.0  V "
    return f"{layout}{hip:>6} 99 1.0 2.0 2016-07-20"


def test_something_that_is_not_the_iau_file_is_rejected() -> None:
    with pytest.raises(ValueError, match="not the IAU Catalog"):
        parse_iau_names("hello\nworld\n")


def test_a_file_with_only_the_header_gives_no_names() -> None:
    assert parse_iau_names(iau_header() + "\n") == {}


def test_lines_that_do_not_fit_the_format_are_ignored() -> None:
    lines = [
        iau_header(),
        iau_row("Short", "")[:75],  # cut off before the date
        "no date on this line at all",
        "# a comment 2016-07-20",
        "$ another comment 2016-07-20",
        "",
        "   ",
    ]
    assert parse_iau_names("\n".join(lines)) == {}


def test_a_name_needs_a_numeric_hipparcos_number() -> None:
    text = "\n".join([iau_header(), iau_row("Odd", "x12"), iau_row("Fine", "12")])
    assert parse_iau_names(text) == {12: "Fine"}


def test_the_first_name_wins_when_a_star_appears_twice() -> None:
    text = "\n".join([iau_header(), iau_row("First", "5"), iau_row("Second", "5")])
    assert parse_iau_names(text) == {5: "First"}


def test_a_name_with_a_space_is_kept_whole() -> None:
    text = "\n".join([iau_header(), iau_row("Alula Australis", "55203")])
    assert parse_iau_names(text) == {55203: "Alula Australis"}


# --- published overrides for bad catalogue parallaxes ------------------------------------------


@pytest.mark.parametrize("hip", [71681, 71683])
def test_alpha_centauri_uses_the_published_parallax_not_the_hipparcos_one(hip: int) -> None:
    result = choose_distance(star(hip=hip, parallax_mas=796.92, parallax_error_mas=25.90), None)
    assert result.source == "literature"
    assert result.parallax_mas == 747.17
    # 1 / 0.74717 arcsec = 1.3384 parsecs = about 4.365 light-years; Proxima is nearer (4.246).
    assert result.lookback.best == pytest.approx(4.365, abs=0.002)
    assert result.lookback.minimum < result.lookback.best < result.lookback.maximum
    assert result.lookback.best > 4.2465


def test_every_override_cites_a_reference_and_has_a_positive_parallax() -> None:
    for override in PARALLAX_OVERRIDES.values():
        assert override.reference and override.parallax_mas > 0 and override.error_mas > 0
