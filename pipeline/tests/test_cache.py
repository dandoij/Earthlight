"""Tests for the download cache. They use file:// URLs, so they need no network."""

import http.client
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from earthlight_pipeline.cache import (
    DEFAULT_CACHE_DIR,
    DownloadError,
    cache_path,
    cached_download,
    is_transient,
)


@pytest.fixture
def source_file(tmp_path: Path) -> Path:
    path = tmp_path / "source.txt"
    path.write_text("first version", encoding="utf-8")
    return path


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "nested"  # does not exist yet


def test_default_cache_dir_is_pipeline_cache() -> None:
    assert DEFAULT_CACHE_DIR.name == ".cache"
    assert DEFAULT_CACHE_DIR.parent.name == "pipeline"


def test_download_creates_the_cache_dir_and_stores_the_file(
    source_file: Path, cache_dir: Path
) -> None:
    path = cached_download(source_file.as_uri(), "data.txt", cache_dir=cache_dir)
    assert path == cache_dir / "data.txt"
    assert path.read_text(encoding="utf-8") == "first version"


def test_a_cached_file_is_reused_without_downloading_again(
    source_file: Path, cache_dir: Path
) -> None:
    cached_download(source_file.as_uri(), "data.txt", cache_dir=cache_dir)
    source_file.write_text("second version", encoding="utf-8")
    path = cached_download(source_file.as_uri(), "data.txt", cache_dir=cache_dir)
    assert path.read_text(encoding="utf-8") == "first version"


def test_a_cached_file_is_reused_even_if_the_source_has_vanished(
    source_file: Path, cache_dir: Path
) -> None:
    url = source_file.as_uri()
    cached_download(url, "data.txt", cache_dir=cache_dir)
    source_file.unlink()
    assert cached_download(url, "data.txt", cache_dir=cache_dir).exists()


def test_refresh_downloads_again(source_file: Path, cache_dir: Path) -> None:
    cached_download(source_file.as_uri(), "data.txt", cache_dir=cache_dir)
    source_file.write_text("second version", encoding="utf-8")
    path = cached_download(source_file.as_uri(), "data.txt", cache_dir=cache_dir, refresh=True)
    assert path.read_text(encoding="utf-8") == "second version"


def test_a_failed_download_raises_and_leaves_nothing_behind(
    tmp_path: Path, cache_dir: Path
) -> None:
    missing = (tmp_path / "does-not-exist.txt").as_uri()
    with pytest.raises(DownloadError, match="could not download"):
        cached_download(missing, "data.txt", cache_dir=cache_dir)
    assert list(cache_dir.iterdir()) == []  # no data file and no half-written .part file


def test_a_failed_refresh_keeps_the_previous_file(source_file: Path, cache_dir: Path) -> None:
    url = source_file.as_uri()
    cached_download(url, "data.txt", cache_dir=cache_dir)
    source_file.unlink()
    with pytest.raises(DownloadError):
        cached_download(url, "data.txt", cache_dir=cache_dir, refresh=True)
    assert (cache_dir / "data.txt").read_text(encoding="utf-8") == "first version"
    assert [p.name for p in cache_dir.iterdir()] == ["data.txt"]


def test_no_temporary_files_are_left_after_success(source_file: Path, cache_dir: Path) -> None:
    cached_download(source_file.as_uri(), "data.txt", cache_dir=cache_dir)
    assert [p.name for p in cache_dir.iterdir()] == ["data.txt"]


def test_large_files_are_copied_completely(tmp_path: Path, cache_dir: Path) -> None:
    big = tmp_path / "big.bin"
    payload = bytes(range(256)) * 20_000  # about 5 MB
    big.write_bytes(payload)
    assert cached_download(big.as_uri(), "big.bin", cache_dir=cache_dir).read_bytes() == payload


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../escape.txt",
        "folder/file.txt",
        "folder\\file.txt",
        "/absolute.txt",
        "C:\\windows\\file.txt",
        "C:file.txt",
        "file.txt:stream",
    ],
)
def test_cache_names_must_be_plain_file_names(name: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="plain file name"):
        cache_path(name, tmp_path)


@pytest.mark.parametrize("name", ["data.csv", "gaia-dr3.parquet", "HYG v4.2.csv", ".hidden"])
def test_plain_names_are_accepted(name: str, tmp_path: Path) -> None:
    assert cache_path(name, tmp_path) == tmp_path / name


@pytest.mark.parametrize(
    "url",
    ["ftp://example.org/x", "javascript:alert(1)", "data:text/plain,hi", "gopher://x/y", "x", ""],
)
def test_only_http_https_and_file_urls_are_allowed(
    url: str, tmp_path: Path, cache_dir: Path
) -> None:
    with pytest.raises(ValueError, match="unsupported URL scheme"):
        cached_download(url, "data.txt", cache_dir=cache_dir)
    assert not cache_dir.exists()


def test_a_bad_name_is_rejected_before_any_download(source_file: Path, cache_dir: Path) -> None:
    with pytest.raises(ValueError, match="plain file name"):
        cached_download(source_file.as_uri(), "../evil.txt", cache_dir=cache_dir)
    assert not cache_dir.exists()


def test_the_timeout_is_passed_to_the_download(
    source_file: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.request

    seen: list[float] = []
    real_urlopen = urllib.request.urlopen

    def spy(request: object, timeout: float = 0.0) -> object:
        seen.append(timeout)
        return real_urlopen(request, timeout=timeout)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", spy)
    cached_download(source_file.as_uri(), "a.txt", cache_dir=cache_dir)
    cached_download(source_file.as_uri(), "b.txt", cache_dir=cache_dir, timeout=600)
    assert seen == [60, 600]


# --- retries ---------------------------------------------------------------------------------


class Flaky:
    """A replacement for urlopen that fails with the given errors, then really downloads."""

    def __init__(self, errors: list[BaseException]) -> None:
        self.errors = list(errors)
        self.calls = 0
        self.real = urllib.request.urlopen

    def __call__(self, request: urllib.request.Request, timeout: float = 0.0) -> object:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.real(request, timeout=timeout)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(time, "sleep", recorded.append)
    return recorded


def install(monkeypatch: pytest.MonkeyPatch, errors: list[BaseException]) -> Flaky:
    flaky = Flaky(errors)
    monkeypatch.setattr(urllib.request, "urlopen", flaky)
    return flaky


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "msg", {}, None)  # type: ignore[arg-type]


def test_a_dropped_connection_is_retried_with_growing_pauses(
    source_file: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    flaky = install(monkeypatch, [http.client.RemoteDisconnected("closed"), TimeoutError("slow")])
    messages: list[str] = []
    path = cached_download(
        source_file.as_uri(),
        "data.txt",
        cache_dir=cache_dir,
        retries=3,
        retry_wait=10,
        notify=messages.append,
    )
    assert path.read_text(encoding="utf-8") == "first version"
    assert flaky.calls == 3
    assert sleeps == [10, 20]
    assert len(messages) == 2 and "RemoteDisconnected" in messages[0] and "1 of 3" in messages[0]
    assert [p.name for p in cache_dir.iterdir()] == ["data.txt"]  # no half-written files


@pytest.mark.parametrize("code", [429, 502, 503, 504])
def test_try_again_responses_are_retried(
    code: int,
    source_file: Path,
    cache_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    sleeps: list[float],
) -> None:
    flaky = install(monkeypatch, [http_error(code)])
    cached_download(source_file.as_uri(), "d.txt", cache_dir=cache_dir, retries=1)
    assert flaky.calls == 2 and sleeps == [5.0]


@pytest.mark.parametrize(
    "error",
    [
        http_error(404),
        http_error(500),  # a rejected query: waiting will not help
        http_error(403),
        urllib.error.URLError(FileNotFoundError("gone")),
        FileNotFoundError("gone"),
        PermissionError("no"),
    ],
)
def test_errors_that_cannot_succeed_are_not_retried(
    error: BaseException,
    source_file: Path,
    cache_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    sleeps: list[float],
) -> None:
    flaky = install(monkeypatch, [error])
    with pytest.raises(DownloadError):
        cached_download(source_file.as_uri(), "d.txt", cache_dir=cache_dir, retries=3)
    assert flaky.calls == 1 and sleeps == []


def test_a_wrapped_connection_error_counts_as_transient() -> None:
    assert is_transient(urllib.error.URLError(ConnectionResetError("reset")))
    assert is_transient(urllib.error.URLError(TimeoutError("slow")))
    assert not is_transient(urllib.error.URLError("some text reason"))
    assert not is_transient(ValueError("bad"))


def test_giving_up_after_the_last_retry_raises(
    source_file: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    flaky = install(monkeypatch, [ConnectionResetError("a")] * 5)
    with pytest.raises(DownloadError, match="could not download"):
        cached_download(source_file.as_uri(), "d.txt", cache_dir=cache_dir, retries=2, retry_wait=1)
    assert flaky.calls == 3 and sleeps == [1, 2]
    assert list(cache_dir.iterdir()) == []


def test_by_default_nothing_is_retried(
    source_file: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    flaky = install(monkeypatch, [ConnectionResetError("a")])
    with pytest.raises(DownloadError):
        cached_download(source_file.as_uri(), "d.txt", cache_dir=cache_dir)
    assert flaky.calls == 1 and sleeps == []
