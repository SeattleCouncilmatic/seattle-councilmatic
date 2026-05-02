"""Shared HTTP helper for the pupa scrapers.

Legistar's API drops connections at random — historical cron logs show
~1-2 `RemoteDisconnected` hits per daily run. Without retry these cause
silent partial data on per-record fetches (sponsors / attachments /
histories arrive empty for one bill, and the run continues with that
record incomplete) and a hard `ScrapeError: no objects returned` on
the bulk events list (which kills the entire daily sync).

`request_with_retry` is a thin wrapper around `requests.get` that
retries on `RequestException` with exponential backoff. Final failure
re-raises so callers can decide whether to swallow + log (for
per-record helpers, where partial data is preferable to dropping the
whole record) or let the exception bubble (for bulk fetches that we'd
rather have crash visibly than silently produce nothing).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


def request_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 30,
    retries: int = 3,
    backoff_base: float = 1.0,
) -> requests.Response:
    """GET `url` with exponential-backoff retries on transient failures.

    Backoff schedule with defaults: 1s, 2s, 4s between attempts. Re-raises
    the last `RequestException` if all attempts fail.

    Retries cover `ConnectionError` (which is what `RemoteDisconnected`
    surfaces as), `Timeout`, `ChunkedEncodingError`, and `HTTPError` from
    `raise_for_status`. The 4xx case is rare in practice — Legistar
    matter/event IDs we hit always exist — and retrying a permanent 4xx
    just delays the inevitable, not a correctness issue.
    """
    last_exc: requests.RequestException | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_exc = e
            if attempt < retries:
                delay = backoff_base * (2 ** (attempt - 1))
                logger.info(
                    f"Request to {url} failed (attempt {attempt}/{retries}); "
                    f"retrying in {delay:.1f}s: {e}"
                )
                time.sleep(delay)
    assert last_exc is not None
    raise last_exc
