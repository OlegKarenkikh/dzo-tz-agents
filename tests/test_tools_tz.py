import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agent2_tz_inspector.tools import (
    generate_corrected_tz,
    generate_email_to_dzo,
    generate_json_report,
    invoke_peer_agent,
)


class TestGenerateJsonReport:
    def test_validates_schema(self):
        """Valid kwargs -> output passes TZInspectionResult validation."""
        from shared.schemas import TZInspectionResult

        result = generate_json_report.invoke({
            "overall_status": "Вернуть на доработку",
            "category": "Поставка оборудования",
            "sections": [],
            "critical_issues": ["Отсутствует раздел 'Цель закупки'"],
            "recommendations": ["Добавить цель закупки"],
            "score_pct": 50.0,
        })
        data = json.loads(result)
        validated = TZInspectionResult.model_validate(data)
        assert validated.overall_status == "Вернуть на доработку"

    def test_normalizes_status(self):
        """Uppercase status -> normalized to title case."""
        from shared.schemas import TZInspectionResult

        result = generate_json_report.invoke({
            "overall_status": "ВЕРНУТЬ НА ДОРАБОТКУ",
            "score_pct": 40.0,
        })
        data = json.loads(result)
        validated = TZInspectionResult.model_validate(data)
        assert validated.overall_status == "Вернуть на доработку"


class TestGenerateCorrectedTz:
    def test_with_modifications(self):
        payload = json.dumps({
            "title": "ТЗ на поставку",
            "original_sections": [
                {"name": "Цель закупки", "content": "Купить оборудование", "status": "ОК"},
            ],
            "added_sections": [
                {"name": "Место поставки", "content": ""},
            ],
            "modifications": [
                {"section": "Цель закупки", "old_text": "купить", "new_text": "приобрести"}
            ]
        })
        result = json.loads(generate_corrected_tz.invoke(json.loads(payload)))
        assert "html" in result
        assert "ДОБАВЛЕНО" in result["html"]
        assert "БЫЛО" in result["html"]

    def test_empty_sections(self):
        payload = json.dumps({"title": "empty", "original_sections": [], "added_sections": [], "modifications": []})
        result = json.loads(generate_corrected_tz.invoke(json.loads(payload)))
        assert "html" in result


class TestGenerateEmailToDzo:
    def test_with_issues(self):
        payload = json.dumps({
            "decision": "Требует доработки",
            "dzo_name": "ООО Тест",
            "tz_subject": "Поставка оборудования",
            "issues": ["Отсутствует раздел 3"],
            "recommendations": ["Добавьте количество"],
            "has_corrected_tz": True,
        })
        result = json.loads(generate_email_to_dzo.invoke(json.loads(payload)))
        assert result["decision"] == "Требует доработки"
        # generate_email_to_dzo не содержит слово "ДОБАВЛЕНО" — проверяем реальное содержимое
        assert "Отсутствует раздел 3" in result["emailHtml"]
        assert "Добавьте количество" in result["emailHtml"]
        assert "приложен" in result["emailHtml"]  # corrected_note при has_corrected_tz=True

    def test_approved(self):
        payload = json.dumps({
            "decision": "Соответствует",
            "dzo_name": "ООО Тест",
            "tz_subject": "Тест",
            "issues": [],
            "recommendations": [],
            "has_corrected_tz": False,
        })
        result = json.loads(generate_email_to_dzo.invoke(json.loads(payload)))
        assert "Соответствует" in result["emailHtml"]

    def test_html_escapes_user_input(self):
        payload = json.dumps({
            "decision": "Требует доработки",
            "dzo_name": '<script>alert("xss")</script>',
            "tz_subject": '<img onerror="alert(1)" src=x>',
            "issues": ['<b>bold</b>'],
            "recommendations": ['&amp; special'],
            "has_corrected_tz": False,
        })
        result = json.loads(generate_email_to_dzo.invoke(json.loads(payload)))
        html = result["emailHtml"]
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert '<img onerror' not in html


class TestInvokePeerAgent:
    @patch("agent2_tz_inspector.tools.invoke_agent_as_tool")
    def test_success(self, mock_invoke):
        mock_invoke.return_value = {
            "output": "ok",
            "observations": [{"decision": "Заявка полная"}],
            "intermediate_steps": [],
        }
        result = json.loads(invoke_peer_agent.invoke({
            "target_agent": "dzo",
            "query_text": "Проверь заявку",
            "subject": "Тема",
            "sender": "a@b.com",
        }))
        assert result["peerAgentResult"]["target_agent"] == "dzo"
        assert result["peerAgentResult"]["output"] == "ok"

    @patch("agent2_tz_inspector.tools.invoke_agent_as_tool", side_effect=RuntimeError("boom"))
    def test_error_payload(self, _mock_invoke):
        result = json.loads(invoke_peer_agent.invoke({
            "target_agent": "dzo",
            "query_text": "Проверь заявку",
        }))
        assert "error" in result["peerAgentResult"]

    def test_validation_error_on_missing_fields(self):
        with pytest.raises(ValidationError):
            invoke_peer_agent.invoke({"target_agent": "dzo"})
