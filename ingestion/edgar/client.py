"""HTTP client for SEC EDGAR: declared User-Agent, rate limiting and retries."""

from __future__ import annotations

import time
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RetryableError(Exception):
    """A temporary failure worth retrying (rate limited or server error)."""


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (RetryableError, httpx.TransportError))


class SecClient:
    """Fetches EDGAR URLs no faster than `requests_per_second`, retrying temporary errors."""

    def __init__(
        self,
        user_agent: str,
        requests_per_second: float = 8.0,
        timeout: float = 30.0,
    ) -> None:
        self._min_interval = 1.0 / requests_per_second
        self._last_request = 0.0
        self._http = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=timeout,
            follow_redirects=True,
        )
        self.request_count = 0

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _get(self, url: str) -> httpx.Response:
        self._throttle()
        self.request_count += 1
        response = self._http.get(url)
        if response.status_code in RETRYABLE_STATUS:
            raise RetryableError(f"HTTP {response.status_code} for {url}")
        response.raise_for_status()
        return response

    def get_json(self, url: str) -> Any:
        return self._get(url).json()

    def get_text(self, url: str) -> str:
        return self._get(url).text

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "SecClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
