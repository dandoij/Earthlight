"""Tests for reading the Our World in Data world population series."""

from itertools import pairwise
from pathlib import Path

import pytest

from earthlight.models import PopulationEstimate
from earthlight_pipeline.population import (
    CHART_URL,
    UNDERLYING_SOURCES,
    PopulationError,
    astronomical_year,
    read_population,
    span_text,
)

SNAPSHOT = Path(__file__).parent / "data" / "owid_population_snapshot.csv"
HEADER = "Entity,Code,Year,Population\n"


def write(tmp_path: Path, rows: str, header: str = HEADER) -> Path:
    path = tmp_path / "population.csv"
    path.write_text(header + rows, encoding="utf-8")
    return path


def world(year: str, people: str) -> str:
    return f"World,OWID_WRL,{year},{people}\n"


def problems(path: Path, **kwargs: int) -> str:
    with pytest.raises(PopulationError) as error:
        read_population(path, **kwargs)
    return str(error.value)


# --- the real file -----------------------------------------------------------------------------


def test_the_world_series_is_read_from_the_snapshot() -> None:
    estimates = read_population(SNAPSHOT)
    assert len(estimates) == 261  # the snapshot also holds Africa, Asia, Europe, and the UK
    years = [e.year for e in estimates]
    assert years == sorted(set(years))
    assert estimates[0] == PopulationEstimate(year=-9999, people=4_501_152, source=CHART_URL)
    assert estimates[-1].year == 2023 and estimates[-1].people == 8_091_734_933


def test_the_spacing_is_a_thousand_then_a_hundred_then_ten_then_one_year() -> None:
    years = [e.year for e in read_population(SNAPSHOT)]
    steps = [b - a for a, b in pairwise(years)]
    # The labels step by 1000 up to -1000; shifting the BCE ones by one year makes the step to the
    # label 0 equal to 999.
    assert steps.count(1000) == 9 and steps.count(999) == 1 and steps.count(100) == 17
    assert steps.count(10) == 10 and steps.count(1) == 223
    assert len(steps) == 260 and set(steps) == {1, 10, 100, 999, 1000}


@pytest.mark.parametrize(
    ("year", "people"),
    [
        (-9999, 4_501_152),  # 10000 BCE: a few million people
        (-999, 110_530_464),  # 1000 BCE
        (0, 232_268_832),  # the start of the common era
        (1000, 323_462_624),
        (1800, 983_104_755),  # about a billion
        (1950, 2_493_092_852),
        (2000, 6_171_702_992),
        (2023, 8_091_734_933),
    ],
)
def test_known_points_of_the_series(year: int, people: int) -> None:
    by_year = {e.year: e.people for e in read_population(SNAPSHOT)}
    assert by_year[year] == people


def test_population_grew_over_the_long_run_but_not_every_century() -> None:
    by_year = {e.year: e.people for e in read_population(SNAPSHOT)}
    assert by_year[-9999] < by_year[-999] < by_year[0] < by_year[1000] < by_year[1800]
    assert by_year[1800] < by_year[1950] < by_year[2023]
    assert by_year[1400] < by_year[1200]  # the fall after the Black Death era is in the data


def test_every_estimate_points_at_the_chart_it_came_from() -> None:
    assert {e.source for e in read_population(SNAPSHOT)} == {CHART_URL}
    assert CHART_URL.startswith("https://")


def test_the_combined_sources_are_named_with_their_licenses() -> None:
    assert [s.version for s in UNDERLYING_SOURCES] == ["3.3", "v7", "2024"]
    assert [s.license for s in UNDERLYING_SOURCES] == ["CC BY 4.0", "CC BY 4.0", "CC BY 3.0 IGO"]


# --- the BCE rule ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "year"), [(-10000, -9999), (-1000, -999), (-1, 0), (0, 0), (1, 1), (1800, 1800)]
)
def test_bce_labels_are_stored_as_one_minus_n(label: int, year: int) -> None:
    assert astronomical_year(label) == year


def test_a_bce_label_and_year_zero_cannot_collide(tmp_path: Path) -> None:
    text = problems(write(tmp_path, world("-1", "100") + world("0", "200")))
    assert "year 0: appears more than once" in text


# --- bad files ---------------------------------------------------------------------------------


def test_a_missing_column_is_reported(tmp_path: Path) -> None:
    path = write(tmp_path, "World,OWID_WRL,1900,1\n", header="Entity,Code,Year,People\n")
    assert "has no column Population" in problems(path)


def test_a_file_without_the_world_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path, "Africa,OWID_AFR,1900,100\n")
    assert "no rows for the world (OWID_WRL)" in problems(path)


def test_only_the_world_rows_are_read(tmp_path: Path) -> None:
    path = write(tmp_path, "Africa,OWID_AFR,1900,100\n" + world("1900", "1600000000"))
    (estimate,) = read_population(path)
    assert estimate.people == 1_600_000_000


@pytest.mark.parametrize(
    ("year", "people", "message"),
    [
        ("19x0", "100", "year 19x0: not a whole year"),
        ("1900.5", "100", "not a whole year"),
        ("", "100", "not a whole year"),
        ("1900", "", "population '' is not a whole number above zero"),
        ("1900", "1.5e9", "is not a whole number above zero"),
        ("1900", "-5", "is not a whole number above zero"),
        ("1900", "0", "is not a whole number above zero"),
        ("1900", "12.5", "is not a whole number above zero"),
    ],
)
def test_a_row_that_is_not_a_whole_year_and_a_whole_positive_population_is_refused(
    tmp_path: Path, year: str, people: str, message: str
) -> None:
    assert message in problems(write(tmp_path, world(year, people)))


def test_a_repeated_year_is_refused(tmp_path: Path) -> None:
    text = problems(write(tmp_path, world("1900", "1") + world("1900", "2")))
    assert "year 1900: appears more than once" in text


def test_a_year_after_the_last_one_is_a_projection_and_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path, world("2023", "8") + world("2024", "9") + world("2100", "10"))
    text = problems(path, last_year=2023)
    assert "year 2024: is after 2023, so it is a projection" in text
    assert "year 2100: is after 2023" in text
    assert [e.year for e in read_population(path, last_year=2100)] == [2023, 2024, 2100]


def test_by_default_this_year_is_the_last_allowed(tmp_path: Path) -> None:
    assert "projection" in problems(write(tmp_path, world("2100", "10")))


def test_rows_out_of_order_are_refused(tmp_path: Path) -> None:
    assert "not in year order" in problems(write(tmp_path, world("1900", "2") + world("1800", "1")))


def test_every_bad_row_is_reported_together(tmp_path: Path) -> None:
    path = write(tmp_path, world("a", "1") + world("1900", "-1") + world("2200", "5"))
    assert len(problems(path, last_year=2023).splitlines()) == 3


# --- the report text ---------------------------------------------------------------------------


def test_the_span_text_names_the_first_and_last_estimate() -> None:
    assert span_text(read_population(SNAPSHOT)) == (
        "4.5 million in 10000 BCE to 8.09 billion in 2023 CE"
    )
