"""Tests for the download layer. No test here uses the network: downloads are replaced."""

import itertools
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from hypothesis import given
from hypothesis import strategies as st

from earthlight_pipeline import sources
from earthlight_pipeline.sources import (
    GAIA_BATCH_SIZE,
    GAIA_TAP,
    TAP_RETRIES,
    TAP_RETRY_WAIT_SECONDS,
    TAP_TIMEOUT_SECONDS,
    VIZIER_TAP,
    gaia_batches,
    gaia_match_query,
    max_hipparcos_number,
    tap_url,
)


def test_tap_url_encodes_the_query() -> None:
    url = tap_url(VIZIER_TAP, 'SELECT "HIP" FROM "I/239/hip_main" WHERE x > 1 & y')
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == VIZIER_TAP
    query = parse_qs(parsed.query)
    assert query["REQUEST"] == ["doQuery"]
    assert query["LANG"] == ["ADQL"]
    assert query["FORMAT"] == ["csv"]
    assert query["QUERY"] == ['SELECT "HIP" FROM "I/239/hip_main" WHERE x > 1 & y']


def test_gaia_batches_cover_everything_without_overlap() -> None:
    assert gaia_batches(10, size=4) == [(1, 4), (5, 8), (9, 10)]
    assert gaia_batches(8, size=4) == [(1, 4), (5, 8)]
    assert gaia_batches(1, size=4) == [(1, 1)]


@given(st.integers(1, 200_000), st.integers(1, 50_000))
def test_gaia_batches_are_contiguous_and_complete(max_hip: int, size: int) -> None:
    batches = gaia_batches(max_hip, size)
    assert batches[0][0] == 1
    assert batches[-1][1] == max_hip
    for (_, high), (low, _) in itertools.pairwise(batches):
        assert low == high + 1
    assert all(0 < high - low + 1 <= size for low, high in batches)


@pytest.mark.parametrize(("max_hip", "size"), [(0, 5), (-1, 5), (5, 0)])
def test_gaia_batches_reject_bad_sizes(max_hip: int, size: int) -> None:
    with pytest.raises(ValueError):
        gaia_batches(max_hip, size)


def test_the_batch_size_stays_below_the_gaia_row_limit() -> None:
    assert GAIA_BATCH_SIZE <= 50_000  # the archive returns at most 50,000 rows per query


def test_the_gaia_query_avoids_what_the_archive_rejects() -> None:
    query = gaia_match_query(1, 20_000)
    assert "(" not in query  # parenthesized AND/OR groups return HTTP 500 (docs/data-sources.md)
    assert " OR " not in query
    assert "BETWEEN 1 AND 20000" in query
    for name in ("hipparcos2_best_neighbour", "gaia_source", "gaiaedr3_distance"):
        assert name in query
    assert "LEFT JOIN external.gaiaedr3_distance" in query  # keep stars with no distance


def test_the_gaia_query_only_accepts_integers() -> None:
    with pytest.raises((TypeError, ValueError)):
        gaia_match_query("1; DROP TABLE x", 5)  # type: ignore[arg-type]


class Recorder:
    """Stands in for cached_download and remembers how it was called."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls: list[tuple[str, str, Path | None, bool, float]] = []
        self.retry_settings: list[tuple[int, float, object]] = []

    def __call__(
        self,
        url: str,
        name: str,
        *,
        cache_dir: Path | None = None,
        refresh: bool = False,
        timeout: float = 60,
        retries: int = 0,
        retry_wait: float = 5.0,
        notify: object = None,
    ) -> Path:
        self.calls.append((url, name, cache_dir, refresh, timeout))
        self.retry_settings.append((retries, retry_wait, notify))
        path = self.tmp_path / name
        path.write_text("x", encoding="utf-8")
        return path


@pytest.fixture
def recorder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder(tmp_path)
    monkeypatch.setattr(sources, "cached_download", recorder)
    return recorder


def test_hipparcos_downloads_use_vizier_and_a_long_timeout(
    recorder: Recorder, tmp_path: Path
) -> None:
    messages: list[str] = []
    sources.fetch_hipparcos_main(tmp_path, True, messages.append)
    sources.fetch_hipparcos_parallaxes(tmp_path, False)
    (main_url, main_name, directory, refresh, timeout), (plx_url, plx_name, *_rest) = recorder.calls
    assert main_url.startswith(VIZIER_TAP) and plx_url.startswith(VIZIER_TAP)
    assert (main_name, plx_name) == ("vizier_hip_main.csv", "vizier_hip2.csv")
    assert (directory, refresh, timeout) == (tmp_path, True, TAP_TIMEOUT_SECONDS)
    assert "I%2F239%2Fhip_main" in main_url and "I%2F311%2Fhip2" in plx_url
    assert len(messages) == 1


def test_gaia_downloads_are_one_file_per_batch(recorder: Recorder, tmp_path: Path) -> None:
    messages: list[str] = []
    paths = sources.fetch_gaia_matches(45_000, tmp_path, False, messages.append)
    assert [p.name for p in paths] == [
        "gaia_hip_000001_020000.csv",
        "gaia_hip_020001_040000.csv",
        "gaia_hip_040001_045000.csv",
    ]
    assert all(call[0].startswith(GAIA_TAP) for call in recorder.calls)
    assert all(call[4] == TAP_TIMEOUT_SECONDS for call in recorder.calls)
    assert len(messages) == 3 and "3 of 3" in messages[-1]
    # Every batch is retried, and told the same progress function so retries are visible.
    assert all(
        retries == TAP_RETRIES and wait == TAP_RETRY_WAIT_SECONDS and notify == messages.append
        for retries, wait, notify in recorder.retry_settings
    )


def test_the_iau_download_uses_the_default_timeout(recorder: Recorder, tmp_path: Path) -> None:
    sources.fetch_iau_names(tmp_path, False)
    url, name, _directory, _refresh, timeout = recorder.calls[0]
    assert url == sources.IAU_CSN_URL and name == "iau_csn.txt" and timeout == 60


def test_the_largest_hipparcos_number_is_found(tmp_path: Path) -> None:
    csv_path = tmp_path / "main.csv"
    csv_path.write_text("HIP,Vmag\n5,1\n120404,2\n  ,3\n17,4\n", encoding="utf-8")
    assert max_hipparcos_number(csv_path) == 120404


def test_an_empty_catalogue_has_no_largest_number(tmp_path: Path) -> None:
    csv_path = tmp_path / "main.csv"
    csv_path.write_text("HIP,Vmag\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no Hipparcos stars"):
        max_hipparcos_number(csv_path)


# --- exoplanet archive and host distances ----------------------------------------------------


def test_the_exoplanet_query_asks_for_the_default_parameter_set_only() -> None:
    query = sources.exoplanet_query()
    assert query.startswith("select pl_name, hostname")
    assert query.endswith("from ps where default_flag = 1")
    for column in (
        "sy_dist",
        "sy_disterr1",
        "sy_disterr2",
        "gaia_dr3_id",
        "hip_name",
        "pl_controv_flag",
    ):
        assert column in sources.EXOPLANET_COLUMNS


def test_the_exoplanet_archive_download_is_retried_and_cached_by_name(
    recorder: Recorder, tmp_path: Path
) -> None:
    messages: list[str] = []
    path = sources.fetch_exoplanet_archive(tmp_path, False, messages.append)
    url, name, directory, refresh, timeout = recorder.calls[0]
    assert path.name == name == "exoplanet_archive_ps.csv"
    assert url.startswith(sources.EXOPLANET_ARCHIVE_TAP)
    assert (directory, refresh, timeout) == (tmp_path, False, TAP_TIMEOUT_SECONDS)
    assert recorder.retry_settings[0][:2] == (TAP_RETRIES, TAP_RETRY_WAIT_SECONDS)
    assert len(messages) == 1


def test_the_host_distance_query_is_a_plain_in_list() -> None:
    query = sources.host_distance_query([30, 10, 20])
    assert query.endswith("WHERE source_id IN (30, 10, 20)")
    assert query.count("(") == 1  # no AND/OR groups, which the Gaia archive rejects
    assert "external.gaiaedr3_distance" in query


def test_the_host_distance_query_only_accepts_integers_and_something_to_ask() -> None:
    with pytest.raises(ValueError):
        sources.host_distance_query([])
    with pytest.raises((TypeError, ValueError)):
        sources.host_distance_query(["1); DROP TABLE x; --"])  # type: ignore[list-item]


def test_host_distances_are_fetched_in_batches_with_names_that_depend_on_the_ids(
    recorder: Recorder, tmp_path: Path
) -> None:
    ids = list(range(1_000_000, 1_000_250))
    paths = sources.fetch_host_distances(ids, tmp_path, False)
    assert len(paths) == 3 == len(recorder.calls)  # 100 + 100 + 50
    names = [p.name for p in paths]
    assert len(set(names)) == 3 and all(
        n.startswith("gaia_hosts_") and n.endswith(".csv") for n in names
    )
    again = sources.fetch_host_distances(list(reversed(ids)) + ids[:5], tmp_path, False)
    assert [p.name for p in again] == names  # order and duplicates do not matter
    other = sources.fetch_host_distances([*ids[:99], 5], tmp_path, False)
    assert other[0].name != names[0]  # a different set of hosts is a different file
    assert all(call[0].startswith(GAIA_TAP) for call in recorder.calls)
    assert all(settings[0] == TAP_RETRIES for settings in recorder.retry_settings)


def test_no_hosts_means_no_downloads(recorder: Recorder, tmp_path: Path) -> None:
    assert sources.fetch_host_distances([], tmp_path, False) == []
    assert recorder.calls == []
