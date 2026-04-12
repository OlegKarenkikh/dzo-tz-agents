"""
shared/mcp_rate_limiter.py
Rate limiting for MCP tool invocations.

Uses the same limits and key-function logic as the REST API (api/rate_limit.py)
but implemented as an in-process token-bucket for MCP tool calls (which bypass
the SlowAPI/Starlette middleware stack).

Thread-safe: multiple asyncio.to_thread workers may call check() concurrently.
"""

from __future__ import annotations

import os
import threading
import time

from shared.logger import setup_logger

logger = setup_logger("mcp_rate_limiter")

# Same defaults as REST API (api/rate_limit.py)
_MCP_RATE_LIMIT = os.getenv("RATE_LIMIT_PROCESS", "20/minute")


def _parse_rate(rate_str: str) -> tuple[int, float]:
    """Parse rate string like '20/minute' into (max_calls, window_seconds)."""
    parts = rate_str.strip().split("/")
    if len(parts) != 2:
        return 20, 60.0
    try:
        count = int(parts[0])
    except ValueError:
        count = 20
    period = parts[1].lower().strip()
    if period in ("second", "sec", "s"):
        window = 1.0
    elif period in ("minute", "min", "m"):
        window = 60.0
    elif period in ("hour", "hr", "h"):
        window = 3600.0
    elif period in ("day", "d"):
        window = 86400.0
    else:
        window = 60.0
    return count, window


class MCPRateLimiter:
    """Sliding-window rate limiter for MCP tool invocations.

    Tracks calls per client key (API key hash or IP) with the same
    identification logic as the REST API.
    """

    def __init__(self, rate_str: str | None = None):
        self._max_calls, self._window = _parse_rate(rate_str or _MCP_RATE_LIMIT)
        self._lock = threading.Lock()
        # key -> list of timestamps
        self._buckets: dict[str, list[float]] = {}

    @property
    def max_calls(self) -> int:
        return self._max_calls

    @property
    def window(self) -> float:
        return self._window

    def check(self, client_key: str) -> tuple[bool, float]:
        """Check if a request is allowed for the given client key.

        Returns:
            (allowed, retry_after) — if not allowed, retry_after is seconds
            until the oldest entry expires from the window.
        """
        now = time.monotonic()
        with self._lock:
            timestamps = self._buckets.get(client_key, [])
            # Prune expired entries
            cutoff = now - self._window
            timestamps = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= self._max_calls:
                # Calculate when the oldest entry will expire
                retry_after = timestamps[0] - cutoff
                self._buckets[client_key] = timestamps
                return False, max(0.1, retry_after)

            timestamps.append(now)
            self._buckets[client_key] = timestamps
            return True, 0.0

    def reset(self, client_key: str | None = None) -> None:
        """Reset rate limit state. If client_key is None, reset all."""
        with self._lock:
            if client_key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(client_key, None)


# Module-level singleton — shared across all MCP tool calls.
mcp_limiter = MCPRateLimiter()


class MCPRateLimitError(Exception):
    """Raised when an MCP tool call exceeds the rate limit."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after:.1f}s")
