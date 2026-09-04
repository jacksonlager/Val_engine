"""The one place HTTP happens in the connector layer.

`fetch_text(url, headers, timeout_s)` and `fetch_json(...)` are the whole seam: every client
takes an optional `fetch_text` callable and defaults to the module-level one, so tests inject
recorded responses (or a failure) as a plain function and never touch httpx internals.

`httpx` is the optional `live` extra; importing it is deferred to the first real call so the
package imports without it and the stub path never needs it.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

DEFAULT_TIMEOUT_S = 8.0

FetchText = Callable[[str, Mapping[str, str] | None, float], str]


class FetchError(RuntimeError):
    """Any transport, status or decoding failure — wrapped so a caller has one thing to catch."""


class LiveFeedError(FetchError):
    """Anything that stops the live path (kept for callers of the previous live module)."""


_HTML_HEAD_CHARS = 200
_CHALLENGE_WORDS = ("verify", "javascript", "challenge")


def is_browser_challenge(text: str) -> bool:
    """True when a body is an HTML page asking the client to prove it is a browser (a
    JavaScript proof-of-work or "verify you are human" interstitial). Such a page can come
    with any status — Stooq serves one with 404 — so it is checked before the status."""
    if not text:
        return False
    head = text[:_HTML_HEAD_CHARS].lower()
    if "<!doctype html" not in head and "<html" not in head:
        return False
    body = text.lower()
    return any(w in body for w in _CHALLENGE_WORDS)


def browser_challenge_message(url: str) -> str:
    return (f"{urlsplit(url).hostname or url} answered with a browser-verification page; "
            "this source cannot be read by an automated client")


def _one_line(ex: BaseException) -> str:
    """The first line of an exception's text — httpx appends a 'For more information check:
    https://developer.mozilla.org/...' line that only adds noise to a report."""
    return (str(ex).strip().splitlines() or [type(ex).__name__])[0].strip()


def fetch_text(url: str, headers: Mapping[str, str] | None = None, timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    """GET `url` and return the body as text. Raises `FetchError` on any failure — a transport
    error, a browser-verification page (any status), or a status ≥ 400 (`HTTP 404 for <url>`)."""
    try:
        import httpx  # optional dependency: the `live` extra
    except ImportError as ex:  # pragma: no cover
        raise FetchError("httpx is not installed (pip install 'hc-valuation[live]')") from ex
    try:
        r = httpx.get(url, headers=dict(headers or {}), timeout=timeout_s, follow_redirects=True)
    except Exception as ex:  # noqa: BLE001 — every transport failure means "fall back"
        raise FetchError(f"{type(ex).__name__}: {_one_line(ex)}") from ex
    text = r.text
    if is_browser_challenge(text):
        raise FetchError(browser_challenge_message(url))
    if r.status_code >= 400:
        raise FetchError(f"HTTP {r.status_code} for {url}")
    return text


def fetch_json(url: str, headers: Mapping[str, str] | None = None, timeout_s: float = DEFAULT_TIMEOUT_S,
               fetch: FetchText | None = None) -> Any:
    """`fetch_text` then `json.loads`; a body that is not JSON (an HTML error page) is a FetchError."""
    text = (fetch or fetch_text)(url, headers, timeout_s)
    try:
        return json.loads(text)
    except ValueError as ex:
        raise FetchError(f"response is not JSON ({text[:60]!r})") from ex


class RateLimiter:
    """Sleep so that consecutive calls stay at or under `max_per_s`. Thread-safe, cheap."""

    def __init__(self, max_per_s: float, sleep: Callable[[float], None] = time.sleep) -> None:
        self._interval = 1.0 / max_per_s if max_per_s > 0 else 0.0
        self._sleep = sleep
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            gap = self._last + self._interval - now
            if gap > 0:
                self._sleep(gap)
                now = time.monotonic()
            self._last = now
