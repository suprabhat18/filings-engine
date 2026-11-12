"""Two layers of protection for the Gemini and Vertex AI bill.

1. A per-user sliding window (default 10 searches/minute), kept in memory. It stops
   bursts and scripts. Each Cloud Run instance keeps its own window, so the service
   is deployed with a small max-instances setting.
2. Daily quotas (per user and across all users), stored in Firestore so they hold
   across instances and restarts. See Store.consume_quota.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, max_calls: int, period_seconds: float = 60.0, clock=time.monotonic) -> None:
        self.max_calls = max_calls
        self.period = period_seconds
        self._clock = clock
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> float:
        """Record a call. Returns 0 if allowed, otherwise seconds until the next free slot."""
        now = self._clock()
        with self._lock:
            calls = self._calls[key]
            while calls and now - calls[0] >= self.period:
                calls.popleft()
            if len(calls) >= self.max_calls:
                return self.period - (now - calls[0])
            calls.append(now)
            return 0.0
