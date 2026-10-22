"""Tests for turning Hunt and Reffert cluster distances into lookback ranges."""

import math
from pathlib import Path

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from earthlight_pipeline.star_clusters import (
    LIGHT_YEARS_PER_PARSEC,
    SYSTEMATIC_PARALLAX_MAS,
    ClusterRecord,
    cluster_lookback,
    distance_range_pc,
    parallax_range_mas,
    read_hunt_reffert,
)

SNAPSHOT = Path(__file__).parent / "data" / "hunt_reffert_snapshot.csv"


def record(near: float | None, best: float | None, far: float | None) -> ClusterRecord:
    return ClusterRecord(
        name="Test",
        all_names=("Test",),
        cluster_type="o",
        ra_deg=10.0,
        dec_deg=20.0,
        dist16_pc=near,
        dist50_pc=best,
        dist84_pc=far,
        member_stars=100,
        global_parallax=False,
    )


def test_a_parsec_is_about_three_and_a_quarter_light_years() -> None:
    # Derived from the definitions of the metre, the astronomical unit, and the Julian year.
    assert pytest.approx(3.26156, abs=1e-5) == LIGHT_YEARS_PER_PARSEC


def test_the_floor_widens_a_perfectly_known_distance() -> None:
    near, best, far = distance_range_pc(record(1000.0, 1000.0, 1000.0))  # a parallax of 1 mas
    assert best == pytest.approx(1000.0)
    assert near == pytest.approx(1000.0 / 1.01) and far == pytest.approx(1000.0 / 0.99)


def test_the_lookback_is_the_distance_in_light_years() -> None:
    lookback = cluster_lookback(record(1000.0, 1000.0, 1000.0))
    assert lookback.best == pytest.approx(1000.0 * LIGHT_YEARS_PER_PARSEC)
    assert lookback.minimum < lookback.best < lookback.maximum


def test_the_floor_matters_more_for_distant_clusters() -> None:
    nearby = distance_range_pc(record(100.0, 100.0, 100.0))
    distant = distance_range_pc(record(10_000.0, 10_000.0, 10_000.0))
    assert (nearby[2] - nearby[0]) / nearby[1] < 0.003  # about 0.2 percent at 100 pc
    assert 0.15 < (distant[2] - distant[0]) / distant[1] < 0.25  # about 20 percent at 10 kpc


def test_the_catalogue_range_and_the_floor_combine_in_quadrature() -> None:
    near, best, far = 990.0, 1000.0, 1010.0
    largest, parallax, smallest = parallax_range_mas(record(near, best, far))
    up = 1000 / near - 1000 / best
    down = 1000 / best - 1000 / far
    assert largest - parallax == pytest.approx(math.hypot(up, SYSTEMATIC_PARALLAX_MAS))
    assert parallax - smallest == pytest.approx(math.hypot(down, SYSTEMATIC_PARALLAX_MAS))
    assert parallax == pytest.approx(1.0)


@pytest.mark.parametrize(
    "bad",
    [
        record(None, 100.0, 110.0),
        record(90.0, None, 110.0),
        record(90.0, 100.0, None),
        record(0.0, 100.0, 110.0),
        record(110.0, 100.0, 90.0),  # out of order
        record(90.0, 100.0, 95.0),
    ],
)
def test_a_missing_or_disordered_distance_is_refused(bad: ClusterRecord) -> None:
    with pytest.raises(ValueError, match="Test"):
        cluster_lookback(bad)


def test_a_cluster_too_far_for_the_floor_is_refused() -> None:
    # At 100 kpc the parallax (0.01 mas) is no larger than the floor, so there is no far limit.
    with pytest.raises(ValueError, match="no far limit"):
        cluster_lookback(record(100_000.0, 100_000.0, 100_000.0))


@given(
    best=st.floats(min_value=10.0, max_value=40_000.0),
    below=st.floats(min_value=0.0, max_value=0.3),
    above=st.floats(min_value=0.0, max_value=0.3),
)
def test_the_range_always_contains_the_best_value_and_the_catalogue_range(
    best: float, below: float, above: float
) -> None:
    assume(1000.0 / best > SYSTEMATIC_PARALLAX_MAS * 1.5)  # the floor leaves a far limit
    near, far = best * (1 - below), best * (1 + above)
    lookback = cluster_lookback(record(near, best, far))
    assert 0 < lookback.minimum <= lookback.best <= lookback.maximum
    assert lookback.minimum <= near * LIGHT_YEARS_PER_PARSEC * (1 + 1e-9)
    assert lookback.maximum >= far * LIGHT_YEARS_PER_PARSEC * (1 - 1e-9)


def test_the_snapshot_rows_are_read_with_their_numbers() -> None:
    records = read_hunt_reffert([SNAPSHOT])
    assert len(records) == 33
    pleiades = records["Melotte_22"]
    assert pleiades.cluster_type == "o" and "M45" in pleiades.all_names
    assert pleiades.dist50_pc == pytest.approx(134.84, abs=0.01)
    assert pleiades.member_stars == 907 and not pleiades.global_parallax
    assert records["NGC_5139"].cluster_type == "g"


def test_the_famous_clusters_have_the_distances_astronomers_know() -> None:
    lookback = {name: cluster_lookback(r).best for name, r in read_hunt_reffert([SNAPSHOT]).items()}
    assert lookback["Melotte_22"] == pytest.approx(440, rel=0.03)  # Pleiades: about 440 ly
    assert lookback["Melotte_25"] == pytest.approx(154, rel=0.03)  # Hyades: about 150 ly
    assert lookback["NGC_2632"] == pytest.approx(600, rel=0.03)  # Praesepe: about 600 ly
    assert lookback["NGC_5139"] == pytest.approx(17_200, rel=0.05)  # Omega Centauri
    assert lookback["NGC_6121"] == pytest.approx(5_800, rel=0.05)  # Messier 4


def test_omega_centauri_range_covers_the_independent_distance() -> None:
    # Baumgardt and Vasiliev (2021) give 5.43 kpc; the catalogue alone says about 5.27 kpc. The
    # parallax floor is what makes the range include it.
    omega = read_hunt_reffert([SNAPSHOT])["NGC_5139"]
    low, _, high = distance_range_pc(omega)
    assert low < 5430 < high
    assert omega.dist84_pc is not None and omega.dist84_pc < 5430  # the catalogue range alone
