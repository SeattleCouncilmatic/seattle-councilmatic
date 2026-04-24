"""HTTP helpers for scraping municode HTML + associated blob-storage assets.

Scope: one-off reference-data scrapes (zoning maps, historic landmarks, the
ordinance codification table). Not a framework. Pupa scrapers have their
own session machinery via `pupa.scrape.Scraper` and should not import from
this module — mixing the two concerns caused confusion historically.

Design notes:
  - One process-wide `requests.Session` so connection reuse works across
    many calls in a single management command.
  - Rate limiting is enforced as a minimum gap BETWEEN requests, not a
    fixed sleep before each one, so the first call in a batch is fast.
  - Responses are returned raw; callers pick BeautifulSoup / PIL / json
    based on what they're doing. Keeps this module free of parsing deps.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import Lock
from typing import Optional

import requests

logger = logging.getLogger(__name__)

USER_AGENT = (
    "SeattleCouncilmatic/1.0 "
    "(+https://github.com/SeattleCouncilmatic/seattle_councilmatic)"
)
DEFAULT_MIN_DELAY_SEC = 1.0
DEFAULT_TIMEOUT_SEC = 30

_session: Optional[requests.Session] = None
_last_request_at: float = 0.0
_lock = Lock()


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": USER_AGENT})
    return _session


def get(
    url: str,
    *,
    min_delay: float = DEFAULT_MIN_DELAY_SEC,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> requests.Response:
    """GET a URL, honoring a minimum gap since the previous call.

    Raises requests.HTTPError on non-2xx responses — callers decide whether
    to retry, skip, or bubble up.
    """
    global _last_request_at
    with _lock:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)
        resp = _get_session().get(url, timeout=timeout)
        _last_request_at = time.monotonic()
    resp.raise_for_status()
    return resp


def download_asset(
    url: str,
    dest: Path,
    *,
    min_delay: float = DEFAULT_MIN_DELAY_SEC,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> Path:
    """Fetch a binary asset and write it to `dest`, creating parents as needed.

    Overwrites any existing file at `dest` — caching is the caller's call
    (e.g. skip if `dest.exists()` and you don't care about freshness).
    """
    resp = get(url, min_delay=min_delay, timeout=timeout)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    logger.info("Downloaded %s -> %s (%d bytes)", url, dest, len(resp.content))
    return dest
