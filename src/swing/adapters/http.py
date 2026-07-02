"""Polite HTTP client for NSE endpoints.

NSE serves two kinds of hosts:
- nsearchives.nseindia.com — static daily archives (bhavcopies, index closes).
  Plain GETs with browser headers work.
- www.nseindia.com/api/* — JSON APIs that require a session cookie obtained by
  first visiting the homepage with the same session.

Every successful download of an immutable artifact (anything for a past date)
is cached on disk forever; 404s for past dates are cached too (they mean
holiday/no-data and will never change). This makes backfills resumable and
re-runs free.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

NSE_HOME = "https://www.nseindia.com"


class NotAvailable(Exception):
    """Resource does not exist (404) — for dated artifacts this means holiday/no data."""


@dataclass
class CachedResponse:
    content: bytes
    from_cache: bool


class NSEClient:
    def __init__(
        self,
        cache_dir: Path,
        request_gap_seconds: float = 1.0,
        max_retries: int = 4,
        timeout: float = 30.0,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.request_gap = request_gap_seconds
        self.max_retries = max_retries
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(BROWSER_HEADERS)
        self._last_request_ts = 0.0
        self._has_api_cookies = False

    # ---------- cache ----------

    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode()).hexdigest()[:32]
        return self.cache_dir / f"{key}.bin", self.cache_dir / f"{key}.meta.json"

    def _cache_read(self, url: str) -> bytes | None:
        blob, meta = self._cache_paths(url)
        if not meta.exists():
            return None
        info = json.loads(meta.read_text())
        if info.get("status") == 404:
            raise NotAvailable(url)
        return blob.read_bytes()

    def _cache_write(self, url: str, status: int, content: bytes | None) -> None:
        blob, meta = self._cache_paths(url)
        if content is not None:
            blob.write_bytes(content)
        meta.write_text(json.dumps({"url": url, "status": status}))

    # ---------- politeness / retries ----------

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_request_ts
        if gap < self.request_gap:
            time.sleep(self.request_gap - gap)
        self._last_request_ts = time.monotonic()

    def _request(self, url: str) -> requests.Response:
        delay = 2.0
        last_exc: Exception | None = None
        for _ in range(self.max_retries):
            self._throttle()
            try:
                resp = self._session.get(url, timeout=self.timeout)
                if resp.status_code in (404, 403) or resp.ok:
                    return resp
                last_exc = RuntimeError(f"HTTP {resp.status_code} for {url}")
            except requests.RequestException as exc:
                last_exc = exc
            time.sleep(delay)
            delay *= 2
        raise RuntimeError(f"Failed after {self.max_retries} retries: {url}") from last_exc

    def _bootstrap_api_cookies(self) -> None:
        """www.nseindia.com/api/* rejects sessions that never visited the site."""
        if self._has_api_cookies:
            return
        self._request(NSE_HOME)
        self._has_api_cookies = True

    # ---------- public API ----------

    def get(self, url: str, cacheable: bool = True) -> CachedResponse:
        """GET an archive URL. Raises NotAvailable on 404."""
        if cacheable:
            try:
                cached = self._cache_read(url)
            except NotAvailable:
                raise
            if cached is not None:
                return CachedResponse(cached, from_cache=True)

        if url.startswith(NSE_HOME + "/api"):
            self._bootstrap_api_cookies()
        resp = self._request(url)
        if resp.status_code == 404:
            if cacheable:
                self._cache_write(url, 404, None)
            raise NotAvailable(url)
        if resp.status_code == 403:
            # NSE occasionally rotates session requirements; re-bootstrap once
            self._has_api_cookies = False
            self._bootstrap_api_cookies()
            resp = self._request(url)
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status_code} for {url}")
        if cacheable:
            self._cache_write(url, resp.status_code, resp.content)
        return CachedResponse(resp.content, from_cache=False)

    def get_json(self, url: str, cacheable: bool = True) -> dict | list:
        return json.loads(self.get(url, cacheable=cacheable).content)
