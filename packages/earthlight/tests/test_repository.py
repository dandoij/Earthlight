"""Tests for the read-only repository, run against the real bundled database."""

import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from earthlight.models import VantageKind
from earthlight.repository import (
    Repository,
    RepositoryError,
    bundled_database_path,
    default_repository,
)
from earthlight.schema import SCHEMA_VERSION, create_empty_database


@pytest.fixture(scope="module")
def repo() -> Iterator[Repository]:
    with Repository() as repository:
        yield repository


# --- opening -----------------------------------------------------------------------------------


def test_the_bundled_database_opens_at_the_current_schema_version(repo: Repository) -> None:
    assert repo.path == bundled_database_path()
    assert repo.schema_version == SCHEMA_VERSION
    assert repo.meta()["data_license"] == "CC BY-NC 3.0 IGO"


def test_a_missing_file_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(RepositoryError, match="no database at"):
        Repository(tmp_path / "nope.db")


def test_a_file_that_is_not_a_database_is_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "junk.db"
    path.write_bytes(b"this is not sqlite" * 100)
    with pytest.raises(RepositoryError, match="not an Earthlight database"):
        Repository(path)


def test_a_database_of_another_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    create_empty_database(path)
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    connection.close()
    with pytest.raises(RepositoryError, match=f"schema version {SCHEMA_VERSION + 1}"):
        Repository(path)


def test_a_path_with_spaces_opens(tmp_path: Path) -> None:
    path = tmp_path / "a folder" / "my db.db"
    path.parent.mkdir()
    create_empty_database(path)
    with Repository(path) as empty:
        assert empty.vantage_point("anything") is None


def test_the_database_cannot_be_written_through_the_repository(repo: Repository) -> None:
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        repo._connection.execute("DELETE FROM events")  # pyright: ignore[reportPrivateUsage]


def test_the_default_repository_is_opened_once() -> None:
    assert default_repository() is default_repository()


def test_a_closed_repository_can_be_closed_again(tmp_path: Path) -> None:
    path = tmp_path / "e.db"
    create_empty_database(path)
    repository = Repository(path)
    repository.close()
    repository.close()


# --- vantage points ----------------------------------------------------------------------------


def test_a_vantage_point_is_read_back_as_a_model(repo: Repository) -> None:
    proxima = repo.vantage_point("hip-70890")
    assert proxima is not None
    assert proxima.kind is VantageKind.STAR
    assert proxima.lookback.best == pytest.approx(4.2465, abs=0.0005)
    assert proxima.constellation == "Centaurus"
    assert proxima.facts["distance_source"] == "gaia"


def test_an_unknown_id_is_none(repo: Repository) -> None:
    assert repo.vantage_point("not-a-place") is None


def test_an_exoplanet_keeps_its_host_link(repo: Repository) -> None:
    planet = repo.vantage_point("proxima-cen-b")
    assert planet is not None and planet.host_id == "hip-70890"
    assert planet.kind is VantageKind.EXOPLANET


def test_overlap_finds_places_whose_range_contains_the_lookback(repo: Repository) -> None:
    found = repo.vantage_points_overlapping(8.6, 8.6)
    assert "hip-32349" in [p.id for p in found]  # Sirius is 8.6 light-years away
    assert all(p.lookback.minimum <= 8.6 <= p.lookback.maximum for p in found)
    assert [p.id for p in found] == sorted(p.id for p in found)


def test_overlap_can_be_limited_to_some_kinds(repo: Repository) -> None:
    galaxies = repo.vantage_points_overlapping(2.5e6, 2.6e6, kinds=[VantageKind.GALAXY])
    assert "andromeda-galaxy" in [p.id for p in galaxies]
    assert {p.kind for p in galaxies} == {VantageKind.GALAXY}
    assert repo.vantage_points_overlapping(0, 1e12, kinds=[]) == []


def test_overlap_includes_the_edges(repo: Repository) -> None:
    proxima = repo.vantage_point("hip-70890")
    assert proxima is not None
    edge = repo.vantage_points_overlapping(proxima.lookback.maximum, proxima.lookback.maximum)
    assert "hip-70890" in [p.id for p in edge]


def test_nothing_overlaps_a_lookback_older_than_the_universe(repo: Repository) -> None:
    assert repo.vantage_points_overlapping(2e10, 3e10) == []
    assert 1.38e10 < repo.max_lookback() < 1.39e10


# --- history -----------------------------------------------------------------------------------


def test_events_in_a_span_are_most_important_first(repo: Repository) -> None:
    events = repo.events_between(1490, 1500)
    assert [e.id for e in events] == ["columbus-reaches-the-americas", "da-gama-reaches-india"]
    assert events[0].importance >= events[1].importance


def test_an_events_own_uncertainty_counts_toward_the_span(repo: Repository) -> None:
    # The Cambrian explosion is dated 530 million years ago, plus or minus 10 million.
    assert "cambrian-explosion" in [e.id for e in repo.events_between(-535_000_000, -535_000_000)]
    assert "cambrian-explosion" not in [
        e.id for e in repo.events_between(-545_000_000, -541_000_000)
    ]


def test_an_ongoing_period_overlaps_every_later_span(repo: Repository) -> None:
    periods = repo.periods_overlapping(2020, 2025)
    ids = [p.id for p in periods]
    assert "holocene-epoch" in ids and "space-age" in ids
    holocene = next(p for p in periods if p.id == "holocene-epoch")
    assert holocene.ongoing and holocene.end is None


def test_an_ended_period_does_not_overlap_a_later_span(repo: Repository) -> None:
    periods = repo.periods_overlapping(2020, 2025)
    assert all(p.ongoing or (p.end is not None and p.end >= 2020) for p in periods)


def test_landmarks_include_those_under_construction_standing_and_just_destroyed(
    repo: Repository,
) -> None:
    ids = [m.id for m in repo.landmarks_overlapping(-2590, -2580)]
    assert "great-pyramid-of-giza" in ids  # being built then
    assert "stonehenge" in ids  # standing, and still being worked on
    after_fall = [m.id for m in repo.landmarks_overlapping(-200, -190)]
    assert "colossus-of-rhodes" not in after_fall  # destroyed in -225
    assert "colossus-of-rhodes" in [m.id for m in repo.landmarks_overlapping(-230, -220)]


def test_a_landmark_not_yet_begun_is_left_out(repo: Repository) -> None:
    assert "colosseum" not in [m.id for m in repo.landmarks_overlapping(0, 50)]


# --- population --------------------------------------------------------------------------------


def test_population_gives_the_nearest_estimate_with_its_own_year(repo: Repository) -> None:
    exact = repo.population_nearest(2000)
    assert exact is not None and exact.year == 2000
    between = repo.population_nearest(1450)
    assert between is not None and between.year == 1400 and between.people > 0
    oldest = repo.population_nearest(-50_000)
    assert oldest is not None and oldest.year == -9999
    newest = repo.population_nearest(2500)
    assert newest is not None and newest.year == 2023


# --- threads -----------------------------------------------------------------------------------


def test_several_threads_can_query_at_once(repo: Repository) -> None:
    errors: list[BaseException] = []

    def work() -> None:
        try:
            for _ in range(20):
                assert repo.vantage_point("hip-70890") is not None
                assert repo.events_between(1490, 1500)
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def test_importance_beats_date_when_ordering_events(repo: Repository) -> None:
    # Da Gama (1498, importance 4) is earlier than Luther's theses (1517, importance 5).
    ids = [e.id for e in repo.events_between(1495, 1520)]
    assert ids.index("luther-ninety-five-theses") < ids.index("da-gama-reaches-india")


# --- review fixes -----------------------------------------------------------------------------


def test_a_relative_path_opens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    create_empty_database(tmp_path / "rel.db")
    monkeypatch.chdir(tmp_path)
    with Repository(Path("rel.db")) as repository:
        assert repository.path.is_absolute()


def test_a_closed_repository_says_so(tmp_path: Path) -> None:
    create_empty_database(tmp_path / "c.db")
    repository = Repository(tmp_path / "c.db")
    repository.close()
    assert repository.closed
    with pytest.raises(RepositoryError, match="has been closed"):
        repository.vantage_point("x")


def test_closing_the_shared_repository_does_not_break_the_next_caller() -> None:
    first = default_repository()
    first.close()
    second = default_repository()
    assert second is not first and second.vantage_point("hip-70890") is not None


def test_a_database_with_no_places_has_a_zero_oldest_light(tmp_path: Path) -> None:
    create_empty_database(tmp_path / "none.db")
    with Repository(tmp_path / "none.db") as repository:
        assert repository.max_lookback() == 0.0
