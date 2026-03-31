import json

import pytest

from agent1_dzo_inspector.tools import (
    generate_corrected_application,
    generate_escalation,
    generate_info_request,
    generate_response_email,
    generate_tezis_form,
    generate_validation_report,
)


class TestGenerateValidationReport:
    def test_full_report(self):
        payload = json.dumps({
            "decision": "Заявка полная",
            "checklist_attachments": [{"item": "ТЗ", "status": "Да"}],
            "checklist_required": [{"item": "Наименование", "status": "ОК"}],
            "checklist_additional": [{"item": "Бюджет", "status": "ОК"}],
            "missing_fields": [],
        })
        result = json.loads(generate_validation_report.invoke(payload))
        assert result["decision"] == "Заявка полная"
        assert result["stats"]["attachments_ok"] == 1
        assert result["stats"]["required_ok"] == 1
        assert result["stats"]["additional_ok"] == 1

    def test_empty_input(self):
        result = json.loads(generate_validation_report.invoke("{}"))
        assert result["decision"] == "Не определено"
        assert result["stats"]["attachments_ok"] == 0

    def test_invalid_json(self):
        result = json.loads(generate_validation_report.invoke("not-json"))
        assert "error" in result


class TestGenerateTezisForm:
    def test_filled_form(self):
        payload = json.dumps({
            "procurement_subject": "Поставка СИЗО",
            "justification": "Производственная необходимость",
            "budget": "500000",
            "initiator_name": "Иванов И..И.",
            "initiator_contacts": "+7-900-000-00-00",
            "budget_manager": "Петров П.П.",
            "recommended_suppliers": [{"name": "ООО Ромашка", "inn": "7701234567"}],
            "additional_info": "Нет",
            "tz_filename": "tz.docx",
        })
        result = json.loads(generate_tezis_form.invoke(payload))
        assert "tezisFormHtml" in result
        assert "ТЕЗИС" in result["tezisFormHtml"]
        assert "filled" in result["tezisFormHtml"]

    def test_partial_form_has_empty_class(self):
        payload = json.dumps({"procurement_subject": "Тест"})
        result = json.loads(generate_tezis_form.invoke(payload))
        assert "empty" in result["tezisFormHtml"]

    def test_invalid_json(self):
        result = json.loads(generate_tezis_form.invoke("bad"))
        assert "error" in result

    def test_html_escapes_user_input(self):
        payload = json.dumps({
            "procurement_subject": '<script>alert("xss")</script>',
            "justification": '<img onerror="alert(1)" src=x>',
            "budget": "500000",
            "initiator_name": "<b>Hacker</b>",
            "initiator_contacts": "a]\" onclick=alert(1)",
            "budget_manager": "&admin",
            "recommended_suppliers": [{"name": "<em>Evil Corp</em>", "inn": "<script>0</script>"}],
            "additional_info": "ok",
            "tz_filename": "file.html\"><img src=x>",
        })
        result = json.loads(generate_tezis_form.invoke(payload))
        html = result["tezisFormHtml"]
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert '<img onerror' not in html
        assert "<b>Hacker</b>" not in html


class TestGenerateInfoRequest:
    def test_basic(self):
        payload = json.dumps({
            "dzo_name": "ООО Тест",
            "subject": "Закупка Тест",
            "missing_fields": [{"field": "Инициатор", "description": "Укажите ФИО"}],
            "has_corrected_form": False,
        })
        result = json.loads(generate_info_request.invoke(payload))
        assert result["decision"] == "Требуется доработка"
        assert "Инициатор" in result["emailHtml"]
        assert "Запрос" in result["subject"]

    def test_html_escapes_user_input(self):
        payload = json.dumps({
            "dzo_name": '<script>alert("xss")</script>',
            "subject": '<img onerror="alert(1)" src=x>',
            "missing_fields": [{"field": "<b>bold</b>", "description": "&amp; special"}],
        })
        result = json.loads(generate_info_request.invoke(payload))
        html = result["emailHtml"]
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert '<img onerror' not in html


class TestGenerateEscalation:
    def test_escalation(self):
        payload = json.dumps({
            "subject": "Непонятная заявка",
            "reason": "Противоречие данных",
            "details": "Бюджет превышает лимит",
        })
        result = json.loads(generate_escalation.invoke(payload))
        assert result["decision"] == "Требуется эскалация"
        assert "ЭСКАЛАЦИЯ" in result["escalationHtml"]
        assert "⚠️" in result["subject"]


class TestGenerateResponseEmail:
    def test_response(self):
        payload = json.dumps({
            "decision": "Заявка полная",
            "subject": "Закупка оборудования",
            "agent_summary": "Все реквизиты заполнены.",
        })
        result = json.loads(generate_response_email.invoke(payload))
        assert "emailHtml" in result
        assert "Заявка полная" in result["emailHtml"]


class TestGenerateCorrectedApplication:
    def test_changed_field(self):
        payload = json.dumps({
            "fields": [
                {"name": "Бюджет", "old_value": "100", "new_value": "200", "status": "changed"},
                {"name": "Новое поле", "old_value": "", "new_value": "Значение", "status": "added"},
            ]
        })
        result = json.loads(generate_corrected_application.invoke(payload))
        assert "correctedHtml" in result
        assert "БЫЛО" in result["correctedHtml"]
        assert "ДОБАВЛЕНО" in result["correctedHtml"]

    def test_html_escapes_user_input(self):
        payload = json.dumps({
            "fields": [
                {"name": '<script>alert("xss")</script>', "old_value": "<b>old</b>", "new_value": "<img src=x>", "status": "changed"},
                {"name": "Field2", "old_value": "", "new_value": "&evil<tag>", "status": "added"},
            ]
        })
        result = json.loads(generate_corrected_application.invoke(payload))
        html = result["correctedHtml"]
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "<b>old</b>" not in html
        assert "<img src=x>" not in html
        assert "&amp;evil&lt;tag&gt;" in html
