import json
import pytest
from agent2_tz_inspector.tools import (
    generate_json_report,
    generate_corrected_tz,
    generate_email_to_dzo,
)


class TestGenerateJsonReport:
    def test_full_report(self):
        sections = [
            {"id": i, "name": f"Раздел {i}", "status": "ОК", "comment": ""}
            for i in range(1, 9)
        ]
        payload = json.dumps({
            "overall_status": "Соответствует",
            "category": "Товары",
            "sections": sections,
            "critical_issues": [],
            "recommendations": [],
        })
        result = json.loads(generate_json_report.invoke(payload))
        assert result["overall_status"] == "Соответствует"
        assert result["stats"]["ok"] == 8
        assert result["stats"]["issues"] == 0

    def test_partial_report(self):
        sections = [
            {"id": 1, "name": "Цель", "status": "ОК", "comment": ""},
            {"id": 2, "name": "Требования", "status": "Отсутствует", "comment": "Нет раздела"},
        ]
        payload = json.dumps({
            "overall_status": "Требует доработки",
            "sections": sections,
        })
        result = json.loads(generate_json_report.invoke(payload))
        assert result["stats"]["ok"] == 1
        assert result["stats"]["issues"] == 1

    def test_invalid_json(self):
        result = json.loads(generate_json_report.invoke("!!!"))
        assert "error" in result


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
        result = json.loads(generate_corrected_tz.invoke(payload))
        assert "html" in result
        assert "ДОБАВЛЕНО" in result["html"]
        assert "БЫЛО" in result["html"]

    def test_empty_sections(self):
        payload = json.dumps({"title": "empty", "original_sections": [], "added_sections": [], "modifications": []})
        result = json.loads(generate_corrected_tz.invoke(payload))
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
        result = json.loads(generate_email_to_dzo.invoke(payload))
        assert result["decision"] == "Требует доработки"
        assert "ДОБАВЛЕНО" in result["emailHtml"]
        assert "Отсутствует" in result["emailHtml"]

    def test_approved(self):
        payload = json.dumps({
            "decision": "Соответствует",
            "dzo_name": "ООО Тест",
            "tz_subject": "Тест",
            "issues": [],
            "recommendations": [],
            "has_corrected_tz": False,
        })
        result = json.loads(generate_email_to_dzo.invoke(payload))
        assert "Соответствует" in result["emailHtml"]
