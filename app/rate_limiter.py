import math
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple


class SlidingWindowRateLimiter:
    """
    간단한 Sliding Window Rate Limiter (메모리 기반).

    - key(예: anon_id) 별로 최근 window_seconds 동안의 hit 횟수를 기록합니다.
    - window_seconds: 기본 60초 (분당 제한)
    - 주의: 멀티 프로세스/멀티 서버 환경에서는 프로세스별로 따로 계산됩니다.
      (사내 1차 방어 목적에는 충분한 경우가 많습니다.)
    """

    def __init__(self, max_per_window: int, window_seconds: int = 60, max_keys: int = 5000):
        self.max_per_window = max(0, int(max_per_window))
        self.window_seconds = max(1, int(window_seconds))
        self.max_keys = max(100, int(max_keys))
        self._lock = threading.RLock()
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._last_gc = 0.0

    def _prune(self, q: Deque[float], now: float) -> None:
        cutoff = now - float(self.window_seconds)
        while q and q[0] <= cutoff:
            q.popleft()

    def _gc(self, now: float) -> None:
        # Best-effort: prevent unbounded growth
        if len(self._hits) <= self.max_keys and (now - self._last_gc) < 300:
            return
        self._last_gc = now
        try:
            keys = list(self._hits.keys())
        except Exception:
            keys = []
        # Remove queues that are empty or very old
        for k in keys:
            q = self._hits.get(k)
            if not q:
                try:
                    self._hits.pop(k, None)
                except Exception:
                    pass
                continue
            try:
                # If last hit is far outside window, drop the key
                if (now - float(q[-1])) > float(self.window_seconds) * 3:
                    self._hits.pop(k, None)
            except Exception:
                continue

    def take(self, key: str) -> Tuple[bool, int, int]:
        """
        Attempt to consume one token for key.

        Returns:
          - allowed: bool
          - remaining: int (0 when blocked)
          - retry_after_sec: int (0 when allowed)
        """
        if not isinstance(key, str) or not key:
            key = "anon-guest"

        # Disabled
        if self.max_per_window <= 0:
            return True, 10**9, 0

        now = time.time()
        with self._lock:
            q = self._hits[key]
            self._prune(q, now)
            if len(q) >= self.max_per_window:
                oldest = q[0] if q else now
                retry = max(1, int(math.ceil(float(self.window_seconds) - (now - float(oldest)))))
                return False, 0, retry

            q.append(now)
            remaining = max(0, int(self.max_per_window) - len(q))
            self._gc(now)
            return True, remaining, 0

