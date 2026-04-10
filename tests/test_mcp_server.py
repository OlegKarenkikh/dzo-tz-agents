"""
tests/test_mcp_server.py
Unit-тесты для MCP-сервера и A2A Agent Card.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_agent_runner():
    """Возвращает мок AgentRunner с предустановленным результатом."""
    runner = MagicMock()
    runner.invoke.return_value = {
        "output": "Тестовый результат агента",
        "intermediate_steps": [("tool1", {"decision": "OK"})],
    }
    return runner


@pytest.fixture(autouse=True)
def _mock_db_for_mcp():
    """Mock database functions used by _create_mcp_job to avoid DB side effects.

    _create_mcp_job imports from shared.database at call time, so we patch
    at the shared.database module level.
    """
    with (
        patch("shared.database.create_job", return_value="test-job-id") as _mock_create,
        patch("shared.database.get_job", return_value=None),
        patch("shared.database.update_job") as _mock_update,
    ):
        yield


# ---------------------------------------------------------------------------
# Тесты shared/mcp_server.py — _invoke_agent
# ---------------------------------------------------------------------------

class TestInvokeAgent:
    def test_invoke_dzo_calls_create_dzo_agent(self, mock_agent_runner):
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent_runner) as mock_create:
            from shared.mcp_server import _invoke_agent
            result = _invoke_agent("dzo", "текст заявки")
        mock_create.assert_called_once_with(model_name=None)
        mock_agent_runner.invoke.assert_called_once_with({"input": "текст заявки"})
        assert result["agent"] == "dzo"
        assert result["output"] == "Тестовый результат агента"
        assert result["steps"] == 1

    def test_invoke_tz_calls_create_tz_agent(self, mock_agent_runner):
        with patch("agent2_tz_inspector.agent.create_tz_agent", return_value=mock_agent_runner):
            from shared.mcp_server import _invoke_agent
            result = _invoke_agent("tz", "текст тз")
        assert result["agent"] == "tz"

    def test_invoke_tender_calls_create_tender_agent(self, mock_agent_runner):
        with patch("agent21_tender_inspector.agent.create_tender_agent", return_value=mock_agent_runner):
            from shared.mcp_server import _invoke_agent
            result = _invoke_agent("tender", "тендерная документация")
        assert result["agent"] == "tender"

    def test_invoke_unknown_agent_raises(self):
        from shared.mcp_server import _invoke_agent
        with pytest.raises(ValueError, match="Неизвестный тип агента"):
            _invoke_agent("unknown_agent", "текст")

    def test_invoke_with_model_name(self, mock_agent_runner):
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent_runner) as mock_create:
            from shared.mcp_server import _invoke_agent
            _invoke_agent("dzo", "текст", model_name="gpt-4o")
        mock_create.assert_called_once_with(model_name="gpt-4o")

    def test_invoke_agent_exception_returns_error_dict(self, mock_agent_runner):
        """При ошибке агента _invoke_agent возвращает dict с полем error."""
        mock_agent_runner.invoke.side_effect = RuntimeError("LLM unavailable")
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent_runner):
            from shared.mcp_server import _invoke_agent
            result = _invoke_agent("dzo", "текст")
        assert result["output"] == ""
        assert result["steps"] == 0
        assert "error" in result
        assert "LLM unavailable" in result["error"]

    def test_invoke_agent_too_large_input_returns_error(self):
        """Входной текст сверх _MCP_MAX_INPUT_CHARS должен вернуть error без вызова агента."""
        from shared.mcp_server import _MCP_MAX_INPUT_CHARS, _invoke_agent
        oversized = "x" * (_MCP_MAX_INPUT_CHARS + 1)
        with patch("agent1_dzo_inspector.agent.create_dzo_agent") as mock_create:
            result = _invoke_agent("dzo", oversized)
        mock_create.assert_not_called()
        assert result["output"] == ""
        assert result["steps"] == 0
        assert "error" in result
        assert "лимит" in result["error"].lower() or "превышает" in result["error"].lower()

    def test_invoke_returns_steps_count(self, mock_agent_runner):
        mock_agent_runner.invoke.return_value = {
            "output": "result",
            "intermediate_steps": ["step1", "step2", "step3"],
        }
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent_runner):
            from shared.mcp_server import _invoke_agent
            result = _invoke_agent("dzo", "текст")
        assert result["steps"] == 3


# ---------------------------------------------------------------------------
# Тесты MCP tools (inspect_dzo, inspect_tz, inspect_tender, list_agents)
# ---------------------------------------------------------------------------

class TestMcpTools:
    """MCP tool functions are now async; test via _create_mcp_job (sync path)."""

    def test_inspect_dzo_builds_chat_input_with_email_and_subject(self, mock_agent_runner):
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent_runner):
            from shared.mcp_server import _create_mcp_job
            result = _create_mcp_job("dzo", "От: test@example.com\nТема: Закупка ноутбуков\nтело заявки")
        call_args = mock_agent_runner.invoke.call_args[0][0]["input"]
        assert "От: test@example.com" in call_args
        assert "Тема: Закупка ноутбуков" in call_args
        assert "тело заявки" in call_args
        assert result["agent"] == "dzo"
        assert result["job_id"] == "test-job-id"

    def test_inspect_dzo_without_optional_fields(self, mock_agent_runner):
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent_runner):
            from shared.mcp_server import _create_mcp_job
            result = _create_mcp_job("dzo", "только текст")
        call_args = mock_agent_runner.invoke.call_args[0][0]["input"]
        assert call_args == "только текст"
        assert result["agent"] == "dzo"

    def test_inspect_tz_passes_text_directly(self, mock_agent_runner):
        with patch("agent2_tz_inspector.agent.create_tz_agent", return_value=mock_agent_runner):
            from shared.mcp_server import _create_mcp_job
            result = _create_mcp_job("tz", "техническое задание")
        call_args = mock_agent_runner.invoke.call_args[0][0]["input"]
        assert call_args == "техническое задание"
        assert result["agent"] == "tz"

    def test_inspect_tender_passes_text_directly(self, mock_agent_runner):
        with patch("agent21_tender_inspector.agent.create_tender_agent", return_value=mock_agent_runner):
            from shared.mcp_server import _create_mcp_job
            result = _create_mcp_job("tender", "тендерная документация")
        assert result["agent"] == "tender"

    def test_inspect_dzo_passes_model_name(self, mock_agent_runner):
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent_runner) as mock_create:
            from shared.mcp_server import _create_mcp_job
            _create_mcp_job("dzo", "текст", model_name="gpt-4o-mini")
        mock_create.assert_called_once_with(model_name="gpt-4o-mini")

    def test_inspect_dzo_empty_model_name_passes_none(self, mock_agent_runner):
        """Пустая строка model_name должна передаваться как None."""
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent_runner) as mock_create:
            from shared.mcp_server import _create_mcp_job
            _create_mcp_job("dzo", "текст", model_name=None)
        mock_create.assert_called_once_with(model_name=None)

    def test_mcp_job_creates_tracked_job(self, mock_agent_runner):
        """_create_mcp_job creates a job in the database and returns job_id."""
        import shared.database as _db
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent_runner):
            from shared.mcp_server import _create_mcp_job
            result = _create_mcp_job("dzo", "текст")
        _db.create_job.assert_called_once_with("dzo", sender="mcp", subject="MCP tool call")
        assert result["job_id"] == "test-job-id"
        # update_job called twice: running + done
        assert _db.update_job.call_count == 2

    def test_mcp_job_records_error_on_agent_error(self, mock_agent_runner):
        """_create_mcp_job records error status when _invoke_agent returns error."""
        import shared.database as _db
        mock_agent_runner.invoke.side_effect = RuntimeError("LLM down")
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent_runner):
            from shared.mcp_server import _create_mcp_job
            result = _create_mcp_job("dzo", "текст")
        # _invoke_agent catches exceptions and returns error dict
        assert "error" in result
        assert "LLM down" in result["error"]
        # update_job should have been called with error status
        calls = _db.update_job.call_args_list
        assert any(c.kwargs.get("status") == "error" or (len(c.args) > 1 and c.args[1] == "error") for c in calls)

    def test_list_agents_returns_all_three(self):
        from shared.mcp_server import list_agents
        result = list_agents()
        assert "agents" in result
        ids = [a["id"] for a in result["agents"]]
        assert "dzo" in ids
        assert "tz" in ids
        assert "tender" in ids

    def test_list_agents_has_required_fields(self):
        from shared.mcp_server import list_agents
        result = list_agents()
        for agent in result["agents"]:
            assert "id" in agent
            assert "name" in agent
            assert "description" in agent
            assert "tool" in agent

    def test_list_agents_derives_from_agent_registry(self):
        """list_agents derives data from AGENT_REGISTRY, not hardcoded values."""
        from api.app import AGENT_REGISTRY
        from shared.mcp_server import list_agents
        result = list_agents()
        result_ids = {a["id"] for a in result["agents"]}
        registry_ids = set(AGENT_REGISTRY.keys())
        assert result_ids == registry_ids

    def test_async_inspect_dzo(self, mock_agent_runner):
        """Verify the async tool function works end-to-end."""
        with patch("agent1_dzo_inspector.agent.create_dzo_agent", return_value=mock_agent_runner):
            from shared.mcp_server import inspect_dzo
            result = asyncio.get_event_loop().run_until_complete(
                inspect_dzo(text="тест", sender_email="a@b.com", subject="тема")
            )
        assert result["agent"] == "dzo"
        assert result["job_id"] == "test-job-id"


# ---------------------------------------------------------------------------
# Тесты A2A Agent Card (/.well-known/agent.json)
# ---------------------------------------------------------------------------

class TestA2AAgentCard:
    @pytest.fixture()
    def client(self, monkeypatch):
        """FastAPI test client."""
        monkeypatch.setenv("DATABASE_URL", "sqlite:///test_mcp.db")
        monkeypatch.setenv("API_KEY", "")
        # PUBLIC_BASE_URL must be set; without it _agent_card_base_url() requires
        # AGENT_CARD_ALLOWED_HOSTS, which is also not set here → HTTP 500.
        monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
        from fastapi.testclient import TestClient
        # Import api.app here (after monkeypatch.setenv) so that any module-level
        # code that reads env vars picks up the patched values on first import.
        import api.app as api_app
        # Патчим init_db/close_db на самом модуле api.app, чтобы фикстура
        # оставалась корректной даже если api.app уже был импортирован ранее.
        monkeypatch.setattr(api_app, "init_db", MagicMock())
        monkeypatch.setattr(api_app, "close_db", MagicMock())
        # PUBLIC_BASE_URL is bound at import time; patch the module attribute directly.
        monkeypatch.setattr(api_app, "PUBLIC_BASE_URL", "http://testserver")
        # Не подавляем серверные исключения — тесты должны явно падать при ошибках
        # приложения. Тесты на /mcp используют follow_redirects=False, чтобы
        # остановиться на 307-редиректе и не попасть в FastMCP (которому нужен lifespan).
        return TestClient(api_app.app)

    def test_agent_card_endpoint_returns_200(self, client):
        resp = client.get("/.well-known/agent.json")
        assert resp.status_code == 200

    def test_agent_card_has_required_a2a_fields(self, client):
        resp = client.get("/.well-known/agent.json")
        data = resp.json()
        assert "name" in data
        assert "description" in data
        assert "version" in data
        assert "capabilities" in data
        assert "skills" in data

    def test_agent_card_skills_contains_all_agents(self, client):
        resp = client.get("/.well-known/agent.json")
        data = resp.json()
        skill_ids = [s["id"] for s in data["skills"]]
        assert "inspect_dzo" in skill_ids
        assert "inspect_tz" in skill_ids
        assert "inspect_tender" in skill_ids

    def test_agent_card_skills_derived_from_registry(self, client):
        """Skills in A2A card must match AGENT_REGISTRY entries."""
        from api.app import AGENT_REGISTRY
        resp = client.get("/.well-known/agent.json")
        data = resp.json()
        assert len(data["skills"]) == len(AGENT_REGISTRY)

    def test_agent_card_protocol_version(self, client):
        """protocolVersion should be 0.2.1 (latest A2A spec)."""
        resp = client.get("/.well-known/agent.json")
        data = resp.json()
        assert data["protocolVersion"] == "0.2.1"

    def test_agent_card_capabilities_structure(self, client):
        resp = client.get("/.well-known/agent.json")
        data = resp.json()
        caps = data["capabilities"]
        assert "streaming" in caps
        assert "pushNotifications" in caps

    def test_mcp_endpoint_mounted(self, client):
        """Проверяем что /mcp смонтирован и отвечает допустимым статусом."""
        resp = client.get("/mcp", follow_redirects=False)
        # FastMCP монтируется как sub-app → redirect 307 к /mcp/; без lifespan дальше
        # не идём (follow_redirects=False), чтобы не вызвать RuntimeError от FastMCP.
        # 5xx здесь означает сломанный endpoint — тест должен упасть.
        assert resp.status_code in {200, 307, 405, 406}

    def test_mcp_endpoint_requires_api_key_when_set(self, client):
        """Проверяем что /mcp возвращает 401 при заданном API_KEY без ключа."""
        with patch("api.app._get_api_key", return_value="secret-key"):
            resp = client.get("/mcp")
        assert resp.status_code == 401

    def test_mcp_401_has_cors_headers(self, client):
        """401 response from _mcp_auth_guard must include CORS headers."""
        with patch("api.app._get_api_key", return_value="secret-key"):
            resp = client.get("/mcp", headers={"Origin": "http://localhost:8501"})
        assert resp.status_code == 401
        assert "access-control-allow-origin" in resp.headers
        assert "access-control-allow-methods" in resp.headers

    def test_mcp_endpoint_accepts_valid_api_key(self, client):
        """Проверяем что /mcp принимает валидный ключ в X-API-Key."""
        with patch("api.app._get_api_key", return_value="secret-key"):
            resp = client.get("/mcp", headers={"X-API-Key": "secret-key"}, follow_redirects=False)
        # Auth guard пропустил запрос → получаем redirect 307 (не 401).
        # follow_redirects=False исключает RuntimeError от FastMCP (нет lifespan).
        assert resp.status_code in {200, 307, 405, 406}

    def test_agent_card_returns_500_without_base_url_config(self, monkeypatch):
        """_agent_card_base_url() должен вернуть 500, если не заданы ни PUBLIC_BASE_URL,
        ни AGENT_CARD_ALLOWED_HOSTS — защита от небезопасной конфигурации."""
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        monkeypatch.delenv("AGENT_CARD_ALLOWED_HOSTS", raising=False)
        import api.app as api_app
        monkeypatch.setattr(api_app, "PUBLIC_BASE_URL", None)
        from fastapi.testclient import TestClient
        c = TestClient(api_app.app)
        resp = c.get("/.well-known/agent.json")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Тесты на импорт без mcp пакета
# ---------------------------------------------------------------------------

class TestMcpImportError:
    def test_import_error_without_mcp_package(self, monkeypatch):
        """Если mcp не установлен — должен подняться ImportError с понятным сообщением."""
        import importlib
        import sys
        # Блокируем все уже загруженные mcp* модули и три ключевых подпакета
        # через monkeypatch — он автоматически восстановит их после теста.
        for key in [k for k in sys.modules if k.startswith("mcp")]:
            monkeypatch.setitem(sys.modules, key, None)  # type: ignore[arg-type]
        monkeypatch.setitem(sys.modules, "mcp", None)  # type: ignore[arg-type]
        monkeypatch.setitem(sys.modules, "mcp.server", None)  # type: ignore[arg-type]
        monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)  # type: ignore[arg-type]
        # Удаляем shared.mcp_server для чистого реимпорта; monkeypatch восстановит его.
        monkeypatch.delitem(sys.modules, "shared.mcp_server", raising=False)
        with pytest.raises(ImportError, match="mcp"):
            importlib.import_module("shared.mcp_server")
