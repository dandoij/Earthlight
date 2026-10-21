"""Tests on real data: 25 stars cut from the files the pipeline actually downloads.

The fixtures in ``tests/data/`` are excerpts, in the services' own formats, of:

* ``hip_main_sample.csv``: VizieR I/239/hip_main (Hipparcos main catalogue)
* ``hip2_sample.csv``: VizieR I/311/hip2 (Hipparcos new reduction)
* ``gaia_sample.csv``: the Gaia DR3 matches and Bailer-Jones distances for those stars
* ``iau_csn_sample.txt``: the IAU Catalog of Star Names

They hold the twelve famous stars from step 2.2, four named stars that needed special care
(Alnilam and Aludra have imprecise parallaxes, Alula Australis has none, Polis is too uncertain),
two named stars with accented names, and one real example of each reason a star is skipped.
All were retrieved on 2026-10-20 (see docs/data-sources.md). Expected values below are what
the pipeline produced from them and were checked by hand against the known distances.
"""

from collections import Counter
from pathlib import Path

import pytest

from earthlight.models import VantagePoint
from earthlight_pipeline.stars import (
    StarBuild,
    build_stars,
    parse_iau_names,
    read_gaia_matches,
    read_hipparcos,
    search_entry,
)

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def names() -> dict[int, str]:
    return parse_iau_names((DATA / "iau_csn_sample.txt").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def built(names: dict[int, str]) -> StarBuild:
    stars = read_hipparcos(DATA / "hip_main_sample.csv", DATA / "hip2_sample.csv")
    matches = read_gaia_matches([DATA / "gaia_sample.csv"])
    return build_stars(stars, matches, names)


def by_id(built: StarBuild) -> dict[str, VantagePoint]:
    return {star.id: star for star in built.stars}


# (hip, name, light-years min, best, max, distance source, fame, constellation)
FAMOUS = [
    (32349, "Sirius", 8.565, 8.601, 8.637, "hipparcos", 5, "Canis Major"),
    (70890, "Proxima Centauri", 4.246, 4.246, 4.247, "gaia", 3, "Centaurus"),
    (37279, "Procyon", 11.411, 11.462, 11.513, "hipparcos", 5, "Canis Minor"),
    (91262, "Vega", 24.976, 25.045, 25.114, "hipparcos", 5, "Lyra"),
    (37826, "Pollux", 33.690, 33.785, 33.879, "hipparcos", 5, "Gemini"),
    (69673, "Arcturus", 36.495, 36.717, 36.941, "hipparcos", 5, "Boötes"),
    (21421, "Aldebaran", 65.612, 66.644, 67.709, "hipparcos", 5, "Taurus"),
    (11767, "Polaris", 426.348, 432.568, 438.972, "hipparcos", 4, "Ursa Minor"),
    (27989, "Betelgeuse", 441.946, 497.949, 570.203, "hipparcos", 5, "Orion"),
    (80763, "Antares", 473.376, 553.746, 666.986, "hipparcos", 5, "Scorpius"),
    (24436, "Rigel", 791.642, 862.848, 948.129, "hipparcos", 5, "Orion"),
    (102098, "Deneb", 1240.138, 1411.932, 1638.977, "hipparcos", 5, "Cygnus"),
]


@pytest.mark.parametrize(
    ("hip", "name", "low", "best", "high", "source", "fame", "constellation"),
    FAMOUS,
    ids=[row[1] for row in FAMOUS],
)
def test_famous_stars_have_the_right_distance_name_and_constellation(
    built: StarBuild,
    hip: int,
    name: str,
    low: float,
    best: float,
    high: float,
    source: str,
    fame: int,
    constellation: str,
) -> None:
    star = by_id(built)[f"hip-{hip}"]
    assert star.name == name
    assert star.lookback.minimum == pytest.approx(low, abs=0.002)
    assert star.lookback.best == pytest.approx(best, abs=0.002)
    assert star.lookback.maximum == pytest.approx(high, abs=0.002)
    assert star.facts["distance_source"] == source
    assert star.fame == fame
    assert star.constellation == constellation
    assert star.facts["hip"] == hip


def test_proxima_centauri_is_4_2465_light_years_from_gaia(built: StarBuild) -> None:
    # Bailer-Jones: 1.3019 pc, a little different from the Exoplanet Archive's 1.30119 pc.
    proxima = by_id(built)["hip-70890"]
    assert proxima.lookback.best == pytest.approx(4.2465, abs=0.0005)
    assert proxima.facts["gaia_dr3_source_id"] == "5853498713190525696"
    assert proxima.facts["parallax_mas"] == pytest.approx(768.0665, abs=0.0001)


def test_the_famous_stars_agree_with_what_step_2_2_found(built: StarBuild) -> None:
    # docs/data-sources.md: Polaris 426 to 439 ly, Betelgeuse 442 to 570 ly.
    stars = by_id(built)
    assert stars["hip-11767"].lookback.minimum == pytest.approx(426.3, abs=0.1)
    assert stars["hip-11767"].lookback.maximum == pytest.approx(439.0, abs=0.1)
    assert stars["hip-27989"].lookback.minimum == pytest.approx(441.9, abs=0.1)
    assert stars["hip-27989"].lookback.maximum == pytest.approx(570.2, abs=0.1)


def test_named_stars_with_imprecise_parallaxes_are_kept(built: StarBuild) -> None:
    stars = by_id(built)
    alnilam, aludra = stars["hip-26311"], stars["hip-35904"]
    assert alnilam.lookback.best == pytest.approx(1976.7, abs=0.5)  # about 2,000 light-years
    assert alnilam.lookback.minimum < 1600 and alnilam.lookback.maximum > 2700
    assert aludra.lookback.best == pytest.approx(1988.8, abs=0.5)
    assert aludra.facts["distance_source"] == "hipparcos"  # Gaia matched it but has no distance


def test_stars_that_cannot_be_built_are_left_out_for_the_right_reason(
    built: StarBuild,
) -> None:
    ids = set(by_id(built))
    assert "hip-55203" not in ids  # Alula Australis: no Hipparcos parallax or position
    assert "hip-89341" not in ids  # Polis: parallax 0.09 +/- 0.28
    assert built.skipped == Counter(
        {"parallax_not_precise": 2, "no_position": 2, "non_positive_parallax": 1}
    )
    assert built.sources == Counter({"gaia": 5, "hipparcos": 15})
    assert len(built.stars) == 20


def test_a_gaia_match_with_no_distance_falls_back_to_hipparcos(built: StarBuild) -> None:
    star = by_id(built)["hip-210"]  # Gaia lists it but with no parallax or distance
    assert star.facts["distance_source"] == "hipparcos"
    assert "gaia_dr3_source_id" not in star.facts


def test_accented_iau_names_keep_their_spelling(built: StarBuild) -> None:
    stars = by_id(built)
    assert stars["hip-6643"].name == "Bélénos"
    assert stars["hip-72339"].name == "Mönch"
    assert stars["hip-6643"].fame == 2 and stars["hip-6643"].facts["distance_source"] == "gaia"


def test_iau_names_in_the_real_file_format(names: dict[int, str]) -> None:
    assert len(names) == 22  # 24 data lines, two of them (Absolutno, Chason) have no HIP
    assert names[70890] == "Proxima Centauri"
    assert names[55203] == "Alula Australis"
    assert names[107556] == "Deneb Algedi"
    assert names[104382] == "Polaris Australis"
    assert names[72339] == "Mönch" and names[6643] == "Bélénos"
    assert "Absolutno" not in names.values()
    assert "Chasoň" not in names.values()


def test_the_magnitude_limit_drops_faint_unnamed_stars_only(names: dict[int, str]) -> None:
    stars = read_hipparcos(DATA / "hip_main_sample.csv", DATA / "hip2_sample.csv")
    matches = read_gaia_matches([DATA / "gaia_sample.csv"])
    result = build_stars(stars, matches, names, max_vmag=8.0)
    ids = {star.id for star in result.stars}
    assert "hip-2" not in ids and "hip-210" not in ids  # V 9.27 and 9.05, unnamed
    assert {"hip-3", "hip-25", "hip-70890", "hip-72339"} <= ids  # bright, or named (Mönch is 8.04)
    assert result.skipped["too_faint"] == 2
    assert len(result.stars) == 18


def test_search_entries_exist_for_exactly_the_stars_with_fame(built: StarBuild) -> None:
    entries = [e for star in built.stars if (e := search_entry(star)) is not None]
    assert len(entries) == sum(1 for star in built.stars if star.fame > 0) == 16
    betelgeuse = next(e for e in entries if e.id == "hip-27989")
    assert betelgeuse.name == "Betelgeuse"
    assert betelgeuse.aliases == "HIP 27989\nHD 39801"
    assert betelgeuse.description == "Star in Orion"
    assert all(e.id != "hip-2" for e in entries)


def test_every_built_star_satisfies_the_model_rules(built: StarBuild) -> None:
    for star in built.stars:
        assert 0 <= star.lookback.minimum <= star.lookback.best <= star.lookback.maximum
        assert star.ra_deg is not None and 0 <= star.ra_deg < 360
        assert star.dec_deg is not None and -90 <= star.dec_deg <= 90
        assert star.constellation
        assert star.facts["distance_source"] in ("gaia", "hipparcos")
