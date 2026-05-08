"""Robust HTTP fetcher: retries, backoff, friendly errors, on-disk cache.

We keep this dependency-free (stdlib only) so the package stays small.
"""
from __future__ import annotations

import json
import logging
import socket
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

USER_AGENT = "pl-winner/0.2.0 (+https://github.com/t-rhex/pl-winner)"
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 1.5  # seconds; doubles each retry


class FetchError(RuntimeError):
    """Raised when a remote fetch finally fails."""


def fetch_bytes(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
    headers: dict[str, str] | None = None,
) -> bytes:
    """GET `url` with retries and exponential backoff. Returns response bytes.

    Raises:
        FetchError: after `retries` consecutive failures.
    """
    h = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        h.update(headers)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers=h)
            with urlopen(req, timeout=timeout) as r:
                return r.read()
        except HTTPError as e:
            last_error = e
            if e.code in (429, 502, 503, 504) and attempt < retries - 1:
                wait = backoff * (2 ** attempt)
                log.warning(f"HTTP {e.code} on {url}; retrying in {wait:.1f}s ({attempt + 1}/{retries})")
                time.sleep(wait)
                continue
            break
        except (URLError, socket.timeout, ConnectionError) as e:
            last_error = e
            if attempt < retries - 1:
                wait = backoff * (2 ** attempt)
                log.warning(f"Network error on {url}: {e}; retrying in {wait:.1f}s ({attempt + 1}/{retries})")
                time.sleep(wait)
                continue
    msg = f"Failed to fetch {url} after {retries} attempts: {last_error}"
    raise FetchError(msg) from last_error


def fetch_json(url: str, **kwargs) -> Any:
    """GET a JSON endpoint. Returns parsed object."""
    raw = fetch_bytes(url, **kwargs)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise FetchError(f"Invalid JSON from {url}: {e}") from e


def fetch_text(url: str, encoding: str = "utf-8", **kwargs) -> str:
    return fetch_bytes(url, **kwargs).decode(encoding)


def cached_fetch_json(
    url: str,
    cache_path: Path,
    force: bool = False,
    ttl_seconds: int | None = None,
    **kwargs,
) -> Any:
    """Fetch JSON and persist to `cache_path`. Returns cached value when fresh.

    Args:
        ttl_seconds: if set, refresh when cache is older than this many seconds.
        force: bypass the cache and re-fetch.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if not force and cache_path.exists():
        if ttl_seconds is None or _age_seconds(cache_path) < ttl_seconds:
            try:
                return json.loads(cache_path.read_text())
            except (json.JSONDecodeError, OSError):
                log.warning(f"Cache at {cache_path} is corrupt; refetching")
    data = fetch_json(url, **kwargs)
    try:
        cache_path.write_text(json.dumps(data))
    except OSError as e:
        log.warning(f"Could not write cache {cache_path}: {e}")
    return data


def _age_seconds(path: Path) -> float:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return float("inf")
