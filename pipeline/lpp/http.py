"""Polite HTTP client shared by every source adapter.

* Per-host rate limit (SEC asks for at most 10 requests/second).
* Retries with exponential backoff on 429 and 5xx, honouring Retry-After.
* A descriptive User-Agent (SEC rejects requests without one).
"""

import os
import threading
import time
from urllib.parse import urlparse

import requests

DEFAULT_UA = os.environ.get("LPP_USER_AGENT", "LinkedIn++ research pipeline (set LPP_USER_AGENT to 'name email')")

RATE_LIMITS = {  # requests per second
    "data.sec.gov": 8,
    "www.sec.gov": 8,
    "api.crunchbase.com": 3,
    "api.builtwith.com": 1,
}
DEFAULT_RATE = 5


class NotFound(Exception):
    """The resource doesn't exist (bad board token, unknown permalink...)."""


class HttpClient:
    def __init__(self, user_agent: str = DEFAULT_UA, session: requests.Session | None = None,
                 max_retries: int = 4, sleep=time.sleep):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.max_retries = max_retries
        self.sleep = sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _throttle(self, host: str):
        gap = 1.0 / RATE_LIMITS.get(host, DEFAULT_RATE)
        with self._lock:
            wait = self._last.get(host, 0) + gap - time.monotonic()
            if wait > 0:
                self.sleep(wait)
            self._last[host] = time.monotonic()

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None):
        host = urlparse(url).netloc
        for attempt in range(self.max_retries + 1):
            self._throttle(host)
            resp = self.session.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 404:
                raise NotFound(url)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    resp.raise_for_status()
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                self.sleep(min(delay, 60))
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("unreachable")
