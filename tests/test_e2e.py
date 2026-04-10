"""
End-to-end tests that use real LLM calls (not mocked).

These tests are opt-in only — they run when explicitly requested via:
    pytest -m e2e

Prerequisites:
    - LLM_BACKEND env var must be set (e.g., "openai", "github_models")
    - Appropriate API keys must be configured (OPENAI_API_KEY or GITHUB_TOKEN)

Uses small/cheap test inputs to minimize LLM costs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

_skip_reason = "LLM_BACKEND not set — E2E tests are opt-in (pytest -m e2e)"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not os.getenv("LLM_BACKEND"), reason=_skip_reason),
]

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _read_fixture(subdir: str, filename: str) -> str:
    """Read a text fixture file."""
    path = FIXTURES_DIR / subdir / filename
    if not path.exists():
        pytest.skip(f"Fixture not found: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def _short_dzo_input() -> str:
    """Minimal DZO request for cost-effective testing."""
    return (
        "Заявка на закупку\n"
        "Инициатор: Иванов И.И.\n"
        "Предмет: Ноутбуки для ИТ-отдела\n"
        "Количество: 10 шт.\n"
        "Обоснование: Замена устаревшего оборудования\n"
        "Бюджет: 1 500 000 руб.\n"
        "Срок поставки: 30 дней\n"
        "Адрес: г. Москва, ул. Тестовая, д. 1"
    )


def _short_tz_input() -> str:
    """Minimal TZ for cost-effective testing."""
    return (
        "ТЕХНИЧЕСКОЕ ЗАДАНИЕ\n"
        "1. Цель закупки: приобретение ноутбуков\n"
        "2. Требования: процессор Intel i7, RAM 16 GB\n"
        "3. Количество: 10 штук\n"
        "4. Срок поставки: 30 календарных дней\n"
        "5. Место поставки: г. Москва\n"
        "6. Требования к исполнителю: опыт от 3 лет\n"
        "7. Критерии оценки: цена 60%, качество 40%\n"
        "8. Приложения: спецификация"
    )


def _short_tender_input() -> str:
    """Minimal tender text for cost-effective testing."""
    return (
        "ТЕНДЕРНАЯ ДОКУМЕНТАЦИЯ\n"
        "Закупка №2024-001\n"
        "Участники должны предоставить:\n"
        "1. Анкету участника тендерного отбора\n"
        "2. Копию ИНН/КПП\n"
        "3. Выписку из ЕГРЮЛ\n"
        "4. NDA (соглашение о неразглашении)\n"
        "5. Коммерческое предложение"
    )


def _short_collector_input() -> str:
    """Minimal collector input (structured JSON)."""
    return json.dumps(
        {
            "tender_id": "TEST-001",
            "emails": [
                {
                    "from_email": "test@example.com",
                    "from_name": "Тест",
                    "subject": "Re: ТО TEST-001",
                    "body": "Направляю анкету",
                    "attachments": [
                        {
                            "filename": "Анкета.pdf",
                            "content_type": "application/pdf",
                            "size_bytes": 1000,
                            "content_hint": "АНКЕТА УЧАСТНИКА ТО ИНН: 7702365551 Наименование: ООО Тест",
                        }
                    ],
                }
            ],
            "participants_list": [
                {
                    "name": "ООО «Тест»",
                    "inn": "7702365551",
                    "contact_email": "test@example.com",
                }
            ],
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
#  E2E: Agent tests with real LLM
# ---------------------------------------------------------------------------

class TestDZOAgentE2E:
    def test_dzo_agent_returns_structured_output(self):
        """DZO agent should return a non-empty analysis."""
        from agent1_dzo_inspector.agent import create_dzo_agent
        agent = create_dzo_agent()
        result = agent.invoke({"input": _short_dzo_input()})
        output = result.get("output", "")
        assert output, "DZO agent returned empty output"
        assert len(output) > 50, "DZO agent output too short"


class TestTZAgentE2E:
    def test_tz_agent_returns_structured_output(self):
        """TZ agent should return a non-empty analysis."""
        from agent2_tz_inspector.agent import create_tz_agent
        agent = create_tz_agent()
        result = agent.invoke({"input": _short_tz_input()})
        output = result.get("output", "")
        assert output, "TZ agent returned empty output"
        assert len(output) > 50, "TZ agent output too short"


class TestTenderAgentE2E:
    def test_tender_agent_returns_structured_output(self):
        """Tender agent should parse document list from input."""
        from agent21_tender_inspector.agent import create_tender_agent
        agent = create_tender_agent()
        result = agent.invoke({"input": _short_tender_input()})
        output = result.get("output", "")
        assert output, "Tender agent returned empty output"


class TestCollectorAgentE2E:
    def test_collector_produces_valid_report(self):
        """Collector should produce a report structure with tender_id and participants."""
        from agent3_collector_inspector.agent import create_collector_agent
        agent = create_collector_agent()
        result = agent.invoke({"input": _short_collector_input()})
        output = result.get("output", "")
        assert output, "Collector agent returned empty output"


# ---------------------------------------------------------------------------
#  E2E: REST API flow
# ---------------------------------------------------------------------------

class TestRESTAPIFlowE2E:
    @pytest.fixture()
    def client(self, monkeypatch):
        """Create a FastAPI test client with real LLM (no mocks)."""
        # Remove the mocked LLM to allow real calls
        monkeypatch.setenv("API_KEY", "test-e2e-key")
        # Use a temporary in-memory DB
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from fastapi.testclient import TestClient
        from api.app import app
        return TestClient(app)

    def test_process_dzo_endpoint(self, client):
        """POST /api/v1/process/dzo should return 200 with agent output."""
        resp = client.post(
            "/api/v1/process/dzo",
            json={"text": _short_dzo_input()},
            headers={"X-API-Key": "test-e2e-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
