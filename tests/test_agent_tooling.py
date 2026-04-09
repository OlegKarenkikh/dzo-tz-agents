from __future__ import annotations

from unittest.mock import patch

import pytest

from shared.agent_tooling import extract_observations, invoke_agent_as_tool


class _FakeRunner:
    def invoke(self, payload, config=None):
        assert "input" in payload
        return {
            "output": "ok",
            "intermediate_steps": [
                ("tool_a", {"overall_status": "Соответствует"}),
                ("tool_b", "{\"emailHtml\":\"<p>ok</p>\"}"),
            ],
        }


def test_extract_observations_normalizes_dict_and_json_string():
    result = {
        "intermediate_steps": [
            ("x", {"a": 1}),
            ("y", '{"b":2}'),
            ("z", "not-json"),
        ]
    }
    obs = extract_observations(result)
    assert {"a": 1} in obs
    assert {"b": 2} in obs
    assert {"raw": "not-json"} in obs


@patch("shared.agent_tooling._get_agent_runner", return_value=_FakeRunner())
@patch("shared.agent_tooling._get_permissions", return_value={"dzo": ["tz"]})
@patch("shared.agent_tooling.config.AGENT_TOOL_ENABLED", True)
@patch("shared.agent_tooling._get_registry", return_value={"dzo": "x", "tz": "y"})
def test_invoke_agent_as_tool_success(_mock_registry, _mock_perm, _mock_runner):
    out = invoke_agent_as_tool(
        source_agent="dzo",
        target_agent="tz",
        chat_input="hello",
        metadata={"session_id": "1"},
    )
    assert out["target_agent"] == "tz"
    assert out["output"] == "ok"
    assert any(o.get("overall_status") == "Соответствует" for o in out["observations"])


@patch("shared.agent_tooling._get_permissions", return_value={"dzo": []})
@patch("shared.agent_tooling.config.AGENT_TOOL_ENABLED", True)
@patch("shared.agent_tooling._get_registry", return_value={"dzo": "x", "tz": "y"})
def test_invoke_agent_as_tool_permission_denied(_mock_registry, _mock_perm):
    with pytest.raises(PermissionError):
        invoke_agent_as_tool(source_agent="dzo", target_agent="tz", chat_input="x")


@patch("shared.agent_tooling.config.AGENT_TOOL_ENABLED", False)
def test_invoke_agent_as_tool_disabled():
    with pytest.raises(RuntimeError):
        invoke_agent_as_tool(source_agent="dzo", target_agent="tz", chat_input="x")


@patch("shared.agent_tooling._get_agent_runner", return_value=_FakeRunner())
@patch("shared.agent_tooling._get_permissions", return_value={"*": ["*"]})
@patch("shared.agent_tooling._get_registry", return_value={"dzo": "x", "tz": "y", "tender": "z"})
@patch("shared.agent_tooling.config.AGENT_TOOL_ENABLED", True)
def test_invoke_agent_as_tool_wildcard_policy(_mock_registry, _mock_perm, _mock_runner):
    out = invoke_agent_as_tool(source_agent="dzo", target_agent="tender", chat_input="hello")
    assert out["target_agent"] == "tender"


@patch("shared.agent_tooling._get_permissions", return_value={"*": ["*"]})
@patch("shared.agent_tooling._get_registry", return_value={"dzo": "x", "tz": "y"})
@patch("shared.agent_tooling.config.AGENT_TOOL_ENABLED", True)
def test_invoke_agent_as_tool_self_call_denied(_mock_registry, _mock_perm):
    with pytest.raises(PermissionError):
        invoke_agent_as_tool(source_agent="dzo", target_agent="dzo", chat_input="x")


class _NoToolRunner:
    def invoke(self, payload, config=None):
        return {"output": "x", "intermediate_steps": []}


class _RetryableFailRunner:
    def __init__(self, msg: str):
        self.msg = msg

    def invoke(self, payload, config=None):
        raise RuntimeError(self.msg)


class _OkRunner:
    def invoke(self, payload, config=None):
        return {"output": "ok", "intermediate_steps": [("tool", {"k": 1})]}


@patch("shared.agent_tooling._get_permissions", return_value={"*": ["*"]})
@patch("shared.agent_tooling._get_registry", return_value={"dzo": "x", "tz": "y"})
@patch("shared.agent_tooling.config.AGENT_TOOL_ENABLED", True)
@patch("shared.agent_tooling._build_tool_fallback_chain", return_value=["gpt-4o", "gpt-4o-mini"])
def test_invoke_agent_as_tool_fallback_between_models(_mock_chain, _mock_reg, _mock_perm):
    def _runner_side_effect(agent_id, model_name_override=None):
        if model_name_override == "gpt-4o":
            return _NoToolRunner()
        return _OkRunner()

    with patch("shared.agent_tooling._get_agent_runner", side_effect=_runner_side_effect):
        out = invoke_agent_as_tool(source_agent="dzo", target_agent="tz", chat_input="x")
    assert out["output"] == "ok"


@patch("shared.agent_tooling._get_permissions", return_value={"*": ["*"]})
@patch("shared.agent_tooling._get_registry", return_value={"dzo": "x", "tz": "y"})
@patch("shared.agent_tooling.config.AGENT_TOOL_ENABLED", True)
@patch("shared.agent_tooling._build_tool_fallback_chain", return_value=["gpt-4o", "gpt-4o-mini"])
def test_invoke_agent_as_tool_marks_cooldown_on_retryable_error(_mock_chain, _mock_reg, _mock_perm):
    with patch("shared.agent_tooling._model_cooldown_until", {}):
        with patch("shared.agent_tooling._get_agent_runner") as mock_runner:
            mock_runner.side_effect = [
                _RetryableFailRunner("Error code: 429 - RateLimitReached, wait 120 seconds"),
                _OkRunner(),
            ]
            out = invoke_agent_as_tool(source_agent="dzo", target_agent="tz", chat_input="x")
            assert out["output"] == "ok"

            # Второй вызов должен пропустить gpt-4o по cooldown и сразу взять next model.
            mock_runner.reset_mock()
            mock_runner.side_effect = [_OkRunner()]
            out2 = invoke_agent_as_tool(source_agent="dzo", target_agent="tz", chat_input="x")
            assert out2["output"] == "ok"
            called_models = [c.kwargs.get("model_name_override") for c in mock_runner.call_args_list]
            assert called_models == ["gpt-4o-mini"]
