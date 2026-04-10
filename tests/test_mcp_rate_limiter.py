"""Tests for shared/mcp_rate_limiter.py — MCP rate limiting."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from shared.mcp_rate_limiter import MCPRateLimiter, MCPRateLimitError, _parse_rate


class TestParseRate:
    def test_per_minute(self):
        assert _parse_rate("20/minute") == (20, 60.0)

    def test_per_second(self):
        assert _parse_rate("5/second") == (5, 1.0)

    def test_per_hour(self):
        assert _parse_rate("100/hour") == (100, 3600.0)

    def test_per_day(self):
        assert _parse_rate("1000/day") == (1000, 86400.0)

    def test_short_forms(self):
        assert _parse_rate("10/s") == (10, 1.0)
        assert _parse_rate("10/m") == (10, 60.0)
        assert _parse_rate("10/h") == (10, 3600.0)
        assert _parse_rate("10/d") == (10, 86400.0)

    def test_invalid_format_returns_defaults(self):
        assert _parse_rate("bad") == (20, 60.0)

    def test_invalid_count_returns_default(self):
        assert _parse_rate("abc/minute") == (20, 60.0)

    def test_unknown_period_defaults_to_60(self):
        count, window = _parse_rate("5/fortnight")
        assert count == 5
        assert window == 60.0


class TestMCPRateLimiter:
    def test_allows_within_limit(self):
        limiter = MCPRateLimiter("3/second")
        allowed1, _ = limiter.check("client1")
        allowed2, _ = limiter.check("client1")
        allowed3, _ = limiter.check("client1")
        assert allowed1 is True
        assert allowed2 is True
        assert allowed3 is True

    def test_blocks_over_limit(self):
        limiter = MCPRateLimiter("2/minute")
        limiter.check("client1")
        limiter.check("client1")
        allowed, retry_after = limiter.check("client1")
        assert allowed is False
        assert retry_after > 0

    def test_separate_keys_tracked_independently(self):
        limiter = MCPRateLimiter("1/minute")
        allowed1, _ = limiter.check("client1")
        allowed2, _ = limiter.check("client2")
        assert allowed1 is True
        assert allowed2 is True
        # client1 is now blocked
        allowed3, _ = limiter.check("client1")
        assert allowed3 is False

    def test_reset_single_key(self):
        limiter = MCPRateLimiter("1/minute")
        limiter.check("client1")
        allowed, _ = limiter.check("client1")
        assert allowed is False
        limiter.reset("client1")
        allowed, _ = limiter.check("client1")
        assert allowed is True

    def test_reset_all(self):
        limiter = MCPRateLimiter("1/minute")
        limiter.check("client1")
        limiter.check("client2")
        limiter.reset()
        allowed1, _ = limiter.check("client1")
        allowed2, _ = limiter.check("client2")
        assert allowed1 is True
        assert allowed2 is True

    def test_window_expiry(self):
        limiter = MCPRateLimiter("1/second")
        limiter.check("client1")
        allowed, _ = limiter.check("client1")
        assert allowed is False
        # Simulate time passing by manipulating internal state
        with limiter._lock:
            limiter._buckets["client1"] = [time.monotonic() - 2.0]
        allowed, _ = limiter.check("client1")
        assert allowed is True

    def test_properties(self):
        limiter = MCPRateLimiter("10/minute")
        assert limiter.max_calls == 10
        assert limiter.window == 60.0


class TestMCPRateLimitError:
    def test_error_message(self):
        err = MCPRateLimitError(30.5)
        assert err.retry_after == 30.5
        assert "30.5s" in str(err)

    def test_is_exception(self):
        with pytest.raises(MCPRateLimitError):
            raise MCPRateLimitError(1.0)
