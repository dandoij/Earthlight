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
