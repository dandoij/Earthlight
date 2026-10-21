"""A download cache, so re-running the pipeline does not hit remote servers again.

Files live in ``pipeline/.cache/`` (ignored by git). A file that is already cached is
reused; pass ``refresh=True`` to download it again. A download goes to a temporary file
first and is moved into place only when it is complete, so an interrupted download never
leaves a half-written file that later runs would trust.
"""

import http.client
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache"
"""``pipeline/.cache``, found relative to this file (the pipeline is built from a checkout)."""

ALLOWED_SCHEMES = frozenset({"http", "https", "file"})
"""``file`` is allowed so tests and local copies of datasets work without a network."""

DOWNLOAD_TIMEOUT_SECONDS = 60
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


def cached_download(
    url: str, name: str, *, cache_dir: Path | None = None, refresh: bool = False
) -> Path:
    """Return the path of ``url``'s content cached as ``name``, downloading it if needed.

    Raises ValueError for a bad ``name`` or a URL scheme other than http, https, or
    file, and ``DownloadError`` if the download fails.
    """
    scheme = urlparse(url).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"unsupported URL scheme {scheme!r}; use http, https, or file")
    target = cache_path(name, cache_dir)
    if target.exists() and not refresh:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    handle, temp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{name}.", suffix=".part")
    try:
        with (
            os.fdopen(handle, "wb") as out,
            urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response,
        ):
            shutil.copyfileobj(response, out)
        os.replace(temp_name, target)
    except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
        Path(temp_name).unlink(missing_ok=True)
        raise DownloadError(f"could not download {url}: {error}") from error
    return target
