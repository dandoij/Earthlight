"""Tests for turning distance moduli of nearby galaxies into lookback ranges."""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from earthlight_pipeline.galaxy_distances import (
    COSMICFLOWS,
    MCCONNACHIE,
    GalaxyRecord,
    distance_range_pc,
    galaxy_lookback,
    pgc_name,
    pgc_number,
    read_cosmicflows,
    read_mcconnachie,
)
from earthlight_pipeline.star_clusters import LIGHT_YEARS_PER_PARSEC

DATA = Path(__file__).parent / "data"


def record(
    modulus: float | None, plus: float | None = 0.1, minus: float | None = 0.1
) -> GalaxyRecord:
    return GalaxyRecord(
        catalogue=MCCONNACHIE,
        name="Test",
        ra_deg=10.0,
        dec_deg=20.0,
        modulus=modulus,
        error_plus=plus,
        error_minus=minus,
    )


def test_a_modulus_of_25_is_one_megaparsec() -> None:
    near, best, far = distance_range_pc(record(25.0, 0.0, 0.0))
    assert near == pytest.approx(1e6) and best == pytest.approx(1e6) and far == pytest.approx(1e6)


def test_five_magnitudes_of_modulus_is_ten_times_the_distance() -> None:
    assert distance_range_pc(record(30.0))[1] == pytest.approx(
        10 * distance_range_pc(record(25.0))[1]
    )


def test_the_errors_set_the_two_ends_of_the_range() -> None:
    near, best, far = distance_range_pc(record(25.0, plus=0.5, minus=0.2))
    assert near == pytest.approx(10 ** ((25.0 - 0.2) / 5 + 1))  # the negative error is nearer
    assert far == pytest.approx(10 ** ((25.0 + 0.5) / 5 + 1))  # the positive error is farther
    assert near < best < far


def test_the_lookback_is_the_distance_in_light_years() -> None:
    lookback = galaxy_lookback(record(25.0, 0.0, 0.0))
    assert lookback.best == pytest.approx(1e6 * LIGHT_YEARS_PER_PARSEC)
    assert lookback.minimum == lookback.best == lookback.maximum


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (record(None), "no distance modulus"),
        (record(25.0, None, 0.1), "no distance modulus"),
        (record(25.0, 0.1, None), "no distance modulus"),
        (record(25.0, -0.1, 0.1), "negative error"),
        (record(25.0, 0.1, -0.1), "negative error"),
        (record(0.0), "not a distance"),
        (record(-3.0), "not a distance"),
    ],
)
def test_a_missing_or_impossible_modulus_is_refused(bad: GalaxyRecord, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        galaxy_lookback(bad)


@given(
    modulus=st.floats(min_value=14.0, max_value=40.0),
    plus=st.floats(min_value=0.0, max_value=2.0),
    minus=st.floats(min_value=0.0, max_value=2.0),
)
def test_the_range_is_ordered_and_contains_the_best_value(
    modulus: float, plus: float, minus: float
) -> None:
    lookback = galaxy_lookback(record(modulus, plus, minus))
    assert 0 < lookback.minimum <= lookback.best <= lookback.maximum


@given(
    first=st.floats(min_value=14.0, max_value=39.0), step=st.floats(min_value=0.01, max_value=1.0)
)
def test_a_larger_modulus_is_always_farther_back(first: float, step: float) -> None:
    assert galaxy_lookback(record(first + step)).best > galaxy_lookback(record(first)).best


def test_pgc_names_round_trip() -> None:
    assert pgc_name(28655) == "PGC 28655"
    assert pgc_number("PGC 28655") == 28655
    for not_a_pgc in ("M 82", "PGC", "PGC 12a", "PGC -4", "PGC 1 2", "pgc 5", ""):
        assert pgc_number(not_a_pgc) is None, not_a_pgc


def test_the_mcconnachie_snapshot_is_read_with_asymmetric_errors(tmp_path: Path) -> None:
    records = read_mcconnachie([DATA / "mcconnachie_snapshot.csv"])
    assert len(records) == 16
    lmc = records[(MCCONNACHIE, "LMC")]
    assert (lmc.modulus, lmc.error_plus, lmc.error_minus) == (18.52, 0.09, 0.09)
    assert lmc.ra_deg == pytest.approx(80.894, abs=0.001)
    assert lmc.dec_deg == pytest.approx(-69.756, abs=0.001)
    # Positive and negative errors are different columns: check they are not swapped.
    path = tmp_path / "m.csv"
    path.write_text(
        'Name,RAJ2000,DEJ2000,(m-M),E_(m-M),e_(m-M)\n"Andromeda XIII",10.0,20.0,24.8,0.1,0.4\n',
        encoding="utf-8",
    )
    xiii = read_mcconnachie([path])[(MCCONNACHIE, "Andromeda XIII")]
    assert (xiii.error_plus, xiii.error_minus) == (0.1, 0.4)
    near, best, far = distance_range_pc(xiii)
    assert best / near > far / best  # the larger negative error stretches the near side


def test_the_cosmicflows_snapshot_is_read_by_pgc_number() -> None:
    records = read_cosmicflows([DATA / "cosmicflows4_snapshot.csv"])
    assert len(records) == 20
    m82 = records[(COSMICFLOWS, "PGC 28655")]
    assert (m82.modulus, m82.error_plus, m82.error_minus) == (27.74, 0.02, 0.02)
    assert m82.ra_deg == pytest.approx(148.968, abs=0.001)
    assert m82.dec_deg == pytest.approx(69.680, abs=0.001)


def test_the_famous_galaxies_have_the_distances_astronomers_know() -> None:
    records = {
        **read_mcconnachie([DATA / "mcconnachie_snapshot.csv"]),
        **read_cosmicflows([DATA / "cosmicflows4_snapshot.csv"]),
    }

    def lookback(catalogue: str, name: str) -> float:
        return galaxy_lookback(records[(catalogue, name)]).best

    assert lookback(MCCONNACHIE, "LMC") == pytest.approx(165_000, rel=0.02)  # about 50.6 kpc
    assert lookback(MCCONNACHIE, "SMC") == pytest.approx(209_000, rel=0.02)  # about 64 kpc
    assert lookback(MCCONNACHIE, "Andromeda") == pytest.approx(2.5e6, rel=0.05)
    assert lookback(MCCONNACHIE, "Triangulum") == pytest.approx(2.7e6, rel=0.05)
    assert lookback(COSMICFLOWS, "PGC 46957") == pytest.approx(11.9e6, rel=0.03)  # Centaurus A
    assert lookback(COSMICFLOWS, "PGC 47404") == pytest.approx(27e6, rel=0.05)  # Whirlpool
    assert lookback(COSMICFLOWS, "PGC 41361") == pytest.approx(55e6, rel=0.05)  # Messier 87


def test_andromeda_is_nearer_than_triangulum_which_is_nearer_than_the_whirlpool() -> None:
    records = {
        **read_mcconnachie([DATA / "mcconnachie_snapshot.csv"]),
        **read_cosmicflows([DATA / "cosmicflows4_snapshot.csv"]),
    }
    order = [(MCCONNACHIE, "LMC"), (MCCONNACHIE, "Andromeda"), (COSMICFLOWS, "PGC 47404")]
    values = [galaxy_lookback(records[key]).best for key in order]
    assert values == sorted(values)
