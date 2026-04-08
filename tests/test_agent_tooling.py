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
