"""
Интеграционные тесты полного pipeline обработки документов.
LLM и SMTP/IMAP заменены mock-объектами.
"""
import json
import os
from unittest.mock import MagicMock, patch

import pytest

os_environ_patch = {
    "OPENAI_API_KEY": "sk-test",
    "MODEL_NAME": "gpt-4o",
    "DZO_IMAP_HOST": "imap.test.ru",
    "DZO_IMAP_USER": "dzo@test.ru",
    "DZO_IMAP_PASSWORD": "secret",
    "DZO_SMTP_FROM": "dzo@test.ru",
    "TZ_IMAP_HOST": "imap.test.ru",
    "TZ_IMAP_USER": "tz@test.ru",
    "TZ_IMAP_PASSWORD": "secret",
    "TZ_SMTP_FROM": "tz@test.ru",
    "SMTP_HOST": "smtp.test.ru",
    "SMTP_PORT": "587",
    "SMTP_USER": "user@test.ru",
    "SMTP_PASSWORD": "secret",
    "MANAGER_EMAIL": "manager@test.ru",
    "AGENT_MODE": "both",
    "POLL_INTERVAL_SEC": "300",
}

os.environ.setdefault("OPENAI_API_KEY", "sk-test")

# Явный импорт submodules необходим для корректной работы unittest.mock.patch  # noqa: I001
import agent1_dzo_inspector.runner  # noqa: E402
import agent2_tz_inspector.runner  # noqa: E402


SAMPLE_DZO_EMAIL = {
    "uid": "1",
    "from": "dzo_company@example.com",
    "subject": "Заявка на закупку оборудования",
    "date": "Mon, 01 Jan 2024 12:00:00 +0000",
    "body": "Просим согласовать закупку серверов. Инициатор: Иванов И.И. Количество: 5 шт.",
    "attachments": [{
        "filename": "tz.docx", "ext": "docx", "data": b"fake-docx-content",
        "b64": "ZmFrZS1kb2N4LWNvbnRlbnQ=",
        "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }],
}

SAMPLE_TZ_EMAIL = {
    "uid": "2",
    "from": "tz_company@example.com",
    "subject": "Техническое задание на поставку серверов",
    "date": "Mon, 01 Jan 2024 12:00:00 +0000",
    "body": "ТЗ на поставку серверного оборудования.",
    "attachments": [{
        "filename": "техзадание.pdf", "ext": "pdf", "data": b"%PDF-1.4 fake content",
        "b64": "JVBER...fake", "mime": "application/pdf",
    }],
}


def _make_agent_result(decision: str, email_html: str = "", tezis_html: str = "") -> dict:
    steps = []
    if email_html:
        steps.append((
            MagicMock(),
            json.dumps({"decision": decision, "emailHtml": email_html, "subject": "Re: Тест"}),
        ))
    if tezis_html:
        steps.append((MagicMock(), json.dumps({"tezisFormHtml": tezis_html})))
    return {"output": f"Решение агента: {decision}", "intermediate_steps": steps}


class TestDzoPipeline:
    @patch.dict("os.environ", os_environ_patch)
    @patch("agent1_dzo_inspector.runner.send_email")
    @patch("agent1_dzo_inspector.runner.notify")
    @patch("agent1_dzo_inspector.runner.extract_text_from_attachment")
    @patch("agent1_dzo_inspector.runner.fetch_unseen_emails")
    @patch("agent1_dzo_inspector.runner.create_dzo_agent")
    def test_full_pipeline_approved(self, mock_create_agent, mock_fetch, mock_extract, mock_notify, mock_send):
        mock_fetch.return_value = [SAMPLE_DZO_EMAIL]
        mock_extract.return_value = "Текст ТЗ из вложения"
        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        mock_agent.invoke.return_value = _make_agent_result(
            "Заявка полная", "<p>Заявка принята</p>", "<html>Тезис</html>"
        )
        from agent1_dzo_inspector.runner import process_dzo_emails
        process_dzo_emails()
        mock_agent.invoke.assert_called_once()
        mock_send.assert_called_once()
        kw = mock_send.call_args.kwargs
        assert kw["to"] == SAMPLE_DZO_EMAIL["from"]
        assert "принята" in kw["subject"] or "принята" in kw["html_body"].lower()

    @patch.dict("os.environ", os_environ_patch)
    @patch("agent1_dzo_inspector.runner.send_email")
    @patch("agent1_dzo_inspector.runner.notify")
    @patch("agent1_dzo_inspector.runner.extract_text_from_attachment")
    @patch("agent1_dzo_inspector.runner.fetch_unseen_emails")
    @patch("agent1_dzo_inspector.runner.create_dzo_agent")
    def test_pipeline_requires_revision(self, mock_create_agent, mock_fetch, mock_extract, mock_notify, mock_send):
        mock_fetch.return_value = [SAMPLE_DZO_EMAIL]
        mock_extract.return_value = "Неполный текст"
        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        mock_agent.invoke.return_value = _make_agent_result("Требуется доработка", "<p>Доработка</p>")
        from agent1_dzo_inspector.runner import process_dzo_emails
        process_dzo_emails()
        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["to"] == SAMPLE_DZO_EMAIL["from"]

    @patch.dict("os.environ", os_environ_patch)
    @patch("agent1_dzo_inspector.runner.config")
    @patch("agent1_dzo_inspector.runner.send_email")
    @patch("agent1_dzo_inspector.runner.notify")
    @patch("agent1_dzo_inspector.runner.extract_text_from_attachment")
    @patch("agent1_dzo_inspector.runner.fetch_unseen_emails")
    @patch("agent1_dzo_inspector.runner.create_dzo_agent")
    def test_pipeline_escalation_sends_to_manager(
        self, mock_create_agent, mock_fetch, mock_extract, mock_notify, mock_send, mock_config
    ):
        mock_config.MANAGER_EMAIL = os_environ_patch["MANAGER_EMAIL"]
        mock_config.DZO_SMTP_FROM = os_environ_patch["DZO_SMTP_FROM"]
        mock_config.DZO_IMAP_HOST = os_environ_patch["DZO_IMAP_HOST"]
        mock_config.DZO_IMAP_USER = os_environ_patch["DZO_IMAP_USER"]
        mock_config.DZO_IMAP_PASSWORD = os_environ_patch["DZO_IMAP_PASSWORD"]
        mock_config.DZO_IMAP_PORT = 993
        mock_config.DZO_IMAP_FOLDER = "INBOX"
        mock_fetch.return_value = [SAMPLE_DZO_EMAIL]
        mock_extract.return_value = "Противоречивые данные"
        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        mock_agent.invoke.return_value = _make_agent_result("Требуется эскалация", "<p>Эскалация</p>")
        from agent1_dzo_inspector.runner import process_dzo_emails
        process_dzo_emails()
        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["to"] == os_environ_patch["MANAGER_EMAIL"]

    @patch.dict("os.environ", os_environ_patch)
    @patch("agent1_dzo_inspector.runner.send_email")
    @patch("agent1_dzo_inspector.runner.notify")
    @patch("agent1_dzo_inspector.runner.fetch_unseen_emails")
    def test_no_emails_does_nothing(self, mock_fetch, mock_notify, mock_send):
        mock_fetch.return_value = []
        from agent1_dzo_inspector.runner import process_dzo_emails
        process_dzo_emails()
        mock_send.assert_not_called()

    @patch.dict("os.environ", os_environ_patch)
    @patch("agent1_dzo_inspector.runner.send_email")
    @patch("agent1_dzo_inspector.runner.notify")
    @patch("agent1_dzo_inspector.runner.fetch_unseen_emails")
    def test_email_without_attachments_requests_resend(self, mock_fetch, mock_notify, mock_send):
        no_att_email = dict(SAMPLE_DZO_EMAIL)
        no_att_email["attachments"] = []
        mock_fetch.return_value = [no_att_email]
        from agent1_dzo_inspector.runner import process_dzo_emails
        process_dzo_emails()
        mock_send.assert_called_once()
        assert "вложени" in mock_send.call_args.kwargs["html_body"].lower()


class TestTzPipeline:
    @patch.dict("os.environ", os_environ_patch)
    @patch("agent2_tz_inspector.runner.send_email")
    @patch("agent2_tz_inspector.runner.notify")
    @patch("agent2_tz_inspector.runner.extract_text_from_attachment")
    @patch("agent2_tz_inspector.runner.fetch_unseen_emails")
    @patch("agent2_tz_inspector.runner.create_tz_agent")
    def test_tz_pipeline_compliant(self, mock_create_agent, mock_fetch, mock_extract, mock_notify, mock_send):
        mock_fetch.return_value = [SAMPLE_TZ_EMAIL]
        mock_extract.return_value = "Текст технического задания"
        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        mock_agent.invoke.return_value = _make_agent_result("Соответствует", "<p>ТЗ одобрено</p>")
        from agent2_tz_inspector.runner import process_tz_emails
        process_tz_emails()
        mock_agent.invoke.assert_called_once()
        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["to"] == SAMPLE_TZ_EMAIL["from"]

    @patch.dict("os.environ", os_environ_patch)
    @patch("agent2_tz_inspector.runner.send_email")
    @patch("agent2_tz_inspector.runner.notify")
    @patch("agent2_tz_inspector.runner.fetch_unseen_emails")
    def test_tz_no_emails(self, mock_fetch, mock_notify, mock_send):
        mock_fetch.return_value = []
        from agent2_tz_inspector.runner import process_tz_emails
        process_tz_emails()
        mock_send.assert_not_called()

    @patch.dict("os.environ", os_environ_patch)
    @patch("agent2_tz_inspector.runner.send_email")
    @patch("agent2_tz_inspector.runner.notify")
    @patch("agent2_tz_inspector.runner.extract_text_from_attachment")
    @patch("agent2_tz_inspector.runner.fetch_unseen_emails")
    @patch("agent2_tz_inspector.runner.create_tz_agent")
    def test_tz_extract_called_for_each_attachment(
        self, mock_create_agent, mock_fetch, mock_extract, mock_notify, mock_send
    ):
        email_with_two_att = dict(SAMPLE_TZ_EMAIL)
        email_with_two_att["attachments"] = [
            {"filename": "tz1.pdf", "ext": "pdf", "data": b"%PDF", "b64": "abc", "mime": "application/pdf"},
            {"filename": "tz2.docx", "ext": "docx", "data": b"PK", "b64": "xyz",
             "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        ]
        mock_fetch.return_value = [email_with_two_att]
        mock_extract.return_value = "Текст"
        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        mock_agent.invoke.return_value = _make_agent_result("Соответствует", "<p>ok</p>")
        from agent2_tz_inspector.runner import process_tz_emails
        process_tz_emails()
        assert mock_extract.call_count == 2
