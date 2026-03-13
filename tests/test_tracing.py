"""Unit-тесты для shared/tracing.py."""
# ruff: noqa: I001
import json
import logging
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# get_langfuse_callback
# ---------------------------------------------------------------------------

class TestGetLangfuseCallback:
    def test_returns_none_when_no_key(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        # перезагружаем модуль чтобы _init_langfuse() перевычислился
        import importlib
        import shared.tracing as tracing
        importlib.reload(tracing)
        assert tracing.get_langfuse_callback() is None

    def test_returns_none_when_langfuse_not_installed(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        import importlib
        import sys
        # убираем langfuse из sys.modules если есть
        sys.modules.pop("langfuse", None)
        sys.modules.pop("langfuse.callback", None)
        import shared.tracing as tracing
        with patch.dict(sys.modules, {"langfuse.callback": None}):
            importlib.reload(tracing)
            # при ImportError должно вернуть None
            assert tracing.get_langfuse_callback() is None

    def test_returns_handler_when_configured(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        import importlib
        import sys
        mock_handler = MagicMock()
        mock_cb_class = MagicMock(return_value=mock_handler)
        mock_module = MagicMock()
        mock_module.CallbackHandler = mock_cb_class
        sys.modules["langfuse"] = MagicMock()
        sys.modules["langfuse.callback"] = mock_module
        import shared.tracing as tracing
        importlib.reload(tracing)
        result = tracing.get_langfuse_callback()
        assert result is mock_handler
        # cleanup
        sys.modules.pop("langfuse", None)
        sys.modules.pop("langfuse.callback", None)


# ---------------------------------------------------------------------------
# log_agent_steps
# ---------------------------------------------------------------------------

class TestLogAgentSteps:
    def _make_action(self, tool: str = "my_tool", tool_input: object = None):
        action = MagicMock()
        action.tool = tool
        action.tool_input = tool_input or {"query": "тест"}
        return action

    def test_empty_steps_returns_empty_list(self):
        from shared.tracing import log_agent_steps
        result = log_agent_steps("job-1", "dzo", [])
        assert result == []

    def test_single_step_json_observation(self):
        from shared.tracing import log_agent_steps
        obs = {"decision": "Заявка полная", "emailHtml": "<p>ok</p>"}
        action = self._make_action("generate_report", {"data": "x"})
        steps = [(action, json.dumps(obs))]
        trace = log_agent_steps("job-1", "dzo", steps)
        assert len(trace) == 1
        assert trace[0]["step"] == 1
        assert trace[0]["tool"] == "generate_report"
        assert trace[0]["decision"] == "Заявка полная"
        assert "emailHtml" in trace[0]["output_keys"]
        assert "latency_ms" in trace[0]
        assert isinstance(trace[0]["latency_ms"], float)

    def test_multiple_steps(self):
        from shared.tracing import log_agent_steps
        steps = [
            (self._make_action("tool_a"), json.dumps({"result": "a"})),
            (self._make_action("tool_b"), json.dumps({"result": "b", "decision": "Да"})),
        ]
        trace = log_agent_steps("job-2", "tz", steps)
        assert len(trace) == 2
        assert trace[0]["step"] == 1
        assert trace[1]["step"] == 2
        assert trace[1]["decision"] == "Да"

    def test_non_json_observation_stored_as_raw(self):
        from shared.tracing import log_agent_steps
        action = self._make_action()
        steps = [(action, "not a json string {{{" )]
        trace = log_agent_steps("job-3", "dzo", steps)
        assert trace[0]["output_keys"] == ["raw"]
        assert trace[0]["decision"] is None

    def test_dict_observation(self):
        from shared.tracing import log_agent_steps
        action = self._make_action()
        obs = {"decision": "Требует доработки"}
        steps = [(action, obs)]
        trace = log_agent_steps("job-4", "dzo", steps)
        assert trace[0]["decision"] == "Требует доработки"

    def test_magicmock_action_does_not_raise(self):
        """MagicMock action (as in integration tests) must not crash the runner."""
        from shared.tracing import log_agent_steps
        action = MagicMock()  # не устанавливаем .tool и .tool_input — чистый MagicMock
        steps = [(action, json.dumps({"decision": "ok"}))]
        trace = log_agent_steps("job-5", "dzo", steps)
        assert len(trace) == 1
        assert trace[0]["decision"] == "ok"
        # tool_name должен быть str
        assert isinstance(trace[0]["tool"], str)
        assert isinstance(trace[0]["tool_input"], str)

    def test_long_tool_input_truncated(self):
        from shared.tracing import log_agent_steps
        long_input = "x" * 500
        action = self._make_action("tool", long_input)
        steps = [(action, json.dumps({}))]
        trace = log_agent_steps("job-6", "dzo", steps)
        assert len(trace[0]["tool_input"]) <= 303  # 300 + "..."

    def test_returns_list_of_dicts_for_db(self):
        from shared.tracing import log_agent_steps
        steps = [(self._make_action(), json.dumps({"k": "v"}))]
        trace = log_agent_steps("job-7", "dzo", steps)
        assert isinstance(trace, list)
        assert isinstance(trace[0], dict)
        # все ключи JSON-сериализуемы
        json.dumps(trace)  # не должно бросать исключение

    def test_logger_called(self, caplog):
        from shared.tracing import log_agent_steps
        action = self._make_action("my_tool", {"q": "test"})
        steps = [(action, json.dumps({"decision": "Да"}))]
        with caplog.at_level(logging.INFO, logger="agent_trace"):
            log_agent_steps("job-8", "dzo", steps)
        assert any("job-8" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------

class TestTruncate:
    def test_short_string_unchanged(self):
        from shared.tracing import _truncate
        assert _truncate("hello") == "hello"

    def test_long_string_truncated(self):
        from shared.tracing import _truncate
        result = _truncate("a" * 400)
        assert result == "a" * 300 + "..."

    def test_dict_values_truncated(self):
        from shared.tracing import _truncate
        result = _truncate({"key": "b" * 400})
        assert result["key"].endswith("...")
        assert len(result["key"]) == 303

    def test_non_string_passthrough(self):
        from shared.tracing import _truncate
        assert _truncate(42) == 42
        assert _truncate(None) is None
        assert _truncate([1, 2, 3]) == [1, 2, 3]

    def test_custom_max_len(self):
        from shared.tracing import _truncate
        result = _truncate("hello world", max_len=5)
        assert result == "hello..."
