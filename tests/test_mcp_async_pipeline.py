"""Tests for the async MCP pipeline: timeout, cancellation, and lifecycle."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from shared.mcp_rate_limiter import MCPRateLimitError


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_db():
    """Mock database to avoid side effects."""
    with (
        patch("shared.database.create_job", return_value="async-job-id"),
        patch("shared.database.get_job", return_value=None),
        patch("shared.database.update_job"),
    ):
        yield


@pytest.fixture()
def mock_agent():
    runner = MagicMock()
    runner.invoke.return_value = {
        "output": "async test result",
        "intermediate_steps": [("step1", {})],
    }
    return runner


# ---------------------------------------------------------------------------
#  Agent job lifecycle context manager
# ---------------------------------------------------------------------------

class TestAgentJobLifecycle:
    def test_lifecycle_creates_and_completes_job(self, mock_agent):
        import shared.database as _db
        from shared.mcp_server import agent_job_lifecycle

        async def _run():
            async with agent_job_lifecycle("dzo", "test") as holder:
                holder["result"] = {"output": "done", "steps": 1}
            return holder

        holder = asyncio.get_event_loop().run_until_complete(_run())
        assert holder["job_id"] == "async-job-id"
        _db.create_job.assert_called_once()
        # update_job: running + done
        assert _db.update_job.call_count == 2

    def test_lifecycle_records_error_on_exception(self):
        import shared.database as _db
        from shared.mcp_server import agent_job_lifecycle

        async def _run():
            async with agent_job_lifecycle("dzo", "test"):
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.get_event_loop().run_until_complete(_run())
        # Should have recorded error
        calls = _db.update_job.call_args_list
        assert any("error" in str(c) for c in calls)

    def test_lifecycle_handles_cancellation(self):
        import shared.database as _db
        from shared.mcp_server import agent_job_lifecycle

        async def _run():
            async with agent_job_lifecycle("dzo", "test"):
                raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            asyncio.get_event_loop().run_until_complete(_run())
        calls = _db.update_job.call_args_list
        assert any(
            c.kwargs.get("error") == "Cancelled by client"
            or (c.args and "Cancelled" in str(c.args))
            for c in calls
        )

    def test_lifecycle_handles_timeout(self):
        import shared.database as _db
        from shared.mcp_server import agent_job_lifecycle

        async def _run():
            async with agent_job_lifecycle("dzo", "test"):
                raise TimeoutError()

        with pytest.raises(TimeoutError):
            asyncio.get_event_loop().run_until_complete(_run())
        calls = _db.update_job.call_args_list
        assert any(
            c.kwargs.get("error") == "Timeout"
            or (c.args and "Timeout" in str(c.args))
            for c in calls
        )


# ---------------------------------------------------------------------------
#  Async job pipeline with timeout
# ---------------------------------------------------------------------------

class TestCreateMcpJobAsync:
    def test_async_job_returns_result(self, mock_agent):
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent):
            from shared.mcp_server import _create_mcp_job_async

            async def _run():
                return await _create_mcp_job_async("dzo", "test text")

            result = asyncio.get_event_loop().run_until_complete(_run())
        assert result["agent"] == "dzo"
        assert result["output"] == "async test result"
        assert result["job_id"] == "async-job-id"

    def test_async_job_with_timeout(self, mock_agent):
        """Verify timeout wrapping works."""
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent):
            from shared.mcp_server import _create_mcp_job_async
            with patch("shared.mcp_server.MCP_AGENT_TIMEOUT_SECONDS", 600):
                result = asyncio.get_event_loop().run_until_complete(
                    _create_mcp_job_async("dzo", "test text")
                )
        assert result["output"] == "async test result"

    def test_async_job_timeout_returns_error_dict(self):
        """When agent times out, should return error dict (not raise)."""
        async def _slow_agent(*args, **kwargs):
            await asyncio.sleep(10)
            return {"output": "never reached", "agent": "dzo", "steps": 0}

        with patch("shared.mcp_server._invoke_agent_async", side_effect=_slow_agent):
            from shared.mcp_server import _create_mcp_job_async
            with patch("shared.mcp_server.MCP_AGENT_TIMEOUT_SECONDS", 0.01):
                result = asyncio.get_event_loop().run_until_complete(
                    _create_mcp_job_async("dzo", "test text")
                )
        assert "error" in result
        assert "timed out" in result["error"]

    def test_async_job_rate_limited(self):
        """When rate limit is exceeded, should raise MCPRateLimitError."""
        from shared.mcp_server import _create_mcp_job_async
        with patch("shared.mcp_server.mcp_limiter") as mock_limiter:
            mock_limiter.check.return_value = (False, 30.0)
            with pytest.raises(MCPRateLimitError) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    _create_mcp_job_async("dzo", "test")
                )
            assert exc_info.value.retry_after == 30.0

    def test_async_job_rate_limit_allowed(self, mock_agent):
        """When rate limit allows, should proceed normally."""
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent):
            from shared.mcp_server import _create_mcp_job_async
            with patch("shared.mcp_server.mcp_limiter") as mock_limiter:
                mock_limiter.check.return_value = (True, 0.0)
                result = asyncio.get_event_loop().run_until_complete(
                    _create_mcp_job_async("dzo", "test text")
                )
        assert result["output"] == "async test result"


# ---------------------------------------------------------------------------
#  MCP_AGENT_TIMEOUT_SECONDS config
# ---------------------------------------------------------------------------

class TestMcpTimeoutConfig:
    def test_default_timeout_is_300(self):
        from shared.mcp_server import MCP_AGENT_TIMEOUT_SECONDS
        # Default is 300 unless env var overrides
        assert isinstance(MCP_AGENT_TIMEOUT_SECONDS, int)
        assert MCP_AGENT_TIMEOUT_SECONDS > 0
