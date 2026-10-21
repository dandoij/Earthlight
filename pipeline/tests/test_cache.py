"""Tests for the download cache. They use file:// URLs, so they need no network."""

from pathlib import Path

import pytest

from earthlight_pipeline.cache import (
    DEFAULT_CACHE_DIR,
    DownloadError,
    cache_path,
    cached_download,
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
