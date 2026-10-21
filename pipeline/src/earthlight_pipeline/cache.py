"""A download cache, so re-running the pipeline does not hit remote servers again.

Files live in ``pipeline/.cache/`` (ignored by git). A file that is already cached is
reused; pass ``refresh=True`` to download it again. A download goes to a temporary file
first and is moved into place only when it is complete, so an interrupted download never
leaves a half-written file that later runs would trust. Because each finished file stays
cached, a build that fails partway resumes where it stopped.

Dropped connections, timeouts, and "try again" responses (HTTP 429, 502, 503, 504) are retried
with a growing pause. Anything that cannot succeed by waiting, such as a missing file or a
rejected query, fails at once.
"""

import http.client
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache"
"""``pipeline/.cache``, found relative to this file (the pipeline is built from a checkout)."""

ALLOWED_SCHEMES = frozenset({"http", "https", "file"})
"""``file`` is allowed so tests and local copies of datasets work without a network."""

DOWNLOAD_TIMEOUT_SECONDS = 60
"""Default limit for one download. Slow queries (such as the Gaia archive) pass a longer one."""

RETRYABLE_HTTP_STATUS = frozenset({429, 502, 503, 504})
USER_AGENT = "earthlight-pipeline (https://github.com/dandoij/Earthlight)"


class DownloadError(RuntimeError):
    """A file could not be downloaded."""


def cache_path(name: str, cache_dir: Path | None = None) -> Path:
    """Where the cached file called ``name`` lives.

    ``name`` must be a plain file name: no folders, no ``..``, nothing absolute, so a
    cache entry can never point outside the cache directory. Raises ValueError otherwise.
    """
    if not name or name in {".", ".."} or name != Path(name).name or "\\" in name or ":" in name:
        raise ValueError(f"cache name must be a plain file name, got {name!r}")
    return (DEFAULT_CACHE_DIR if cache_dir is None else cache_dir) / name


def is_transient(error: BaseException) -> bool:
    """True if trying the same download again later might work."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code in RETRYABLE_HTTP_STATUS
    if isinstance(error, urllib.error.URLError):
        return is_transient(error.reason) if isinstance(error.reason, BaseException) else False
    if isinstance(error, FileNotFoundError | PermissionError):
        return False
    return isinstance(error, ConnectionError | TimeoutError | http.client.HTTPException)


def cached_download(
    url: str,
    name: str,
    *,
    cache_dir: Path | None = None,
    refresh: bool = False,
    timeout: float = DOWNLOAD_TIMEOUT_SECONDS,
    retries: int = 0,
    retry_wait: float = 5.0,
    notify: Callable[[str], None] | None = None,
) -> Path:
    """Return the path of ``url``'s content cached as ``name``, downloading it if needed.

    ``timeout`` is the longest, in seconds, to wait on the server. A transient failure is
    retried up to ``retries`` times, waiting ``retry_wait`` seconds and then double that
    each time, and ``notify`` (if given) is told about each retry. Raises ValueError for a
    bad ``name`` or a URL scheme other than http, https, or file, and ``DownloadError`` if
    the download fails for good.
    """
    scheme = urlparse(url).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"unsupported URL scheme {scheme!r}; use http, https, or file")
    target = cache_path(name, cache_dir)
    if target.exists() and not refresh:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        handle, temp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{name}.", suffix=".part")
        try:
            with (
                os.fdopen(handle, "wb") as out,
                urllib.request.urlopen(request, timeout=timeout) as response,
            ):
                shutil.copyfileobj(response, out)
            os.replace(temp_name, target)
            return target
        except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
            Path(temp_name).unlink(missing_ok=True)
            if attempt < retries and is_transient(error):
                wait = retry_wait * 2**attempt
                if notify is not None:
                    notify(
                        f"  {type(error).__name__}: retrying in {wait:g} s "
                        f"({attempt + 1} of {retries})"
                    )
                time.sleep(wait)
                continue
            raise DownloadError(f"could not download {url}: {error}") from error
    raise AssertionError("unreachable: the loop always returns or raises")  # pragma: no cover
