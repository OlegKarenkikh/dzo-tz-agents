"""Coverage tests for agent1_dzo_inspector/runner.py and agent2_tz_inspector/runner.py."""
import json
from unittest.mock import MagicMock, patch
import pytest

from agent1_dzo_inspector.runner import DzoEmailRunner
from agent2_tz_inspector.runner import TzEmailRunner


# ─────────────────────────── DZO runner ──────────────────────────────────────

class TestDzoEmailRunner:
    def _r(self): return DzoEmailRunner()

    def test_agent_id(self):
        assert self._r().agent_id == "dzo"

    def test_imap_config_keys(self):
        cfg = self._r().imap_config
        for k in ("host", "user", "password", "port", "folder"):
            assert k in cfg

    # build_chat_input ─────────────────────────────────────────────────────────

    def test_build_chat_input_no_attachments(self):
        mail = {"from": "a@b.com", "subject": "Заявка", "date": "2026-01-01",
                "body": "Текст", "attachments": []}
        txt = self._r().build_chat_input(mail, [])
        assert "a@b.com" in txt
        assert "Файл ТЗ: НЕТ" in txt
        assert "Спецификация: НЕТ" in txt

    def test_build_chat_input_detects_tz_by_filename(self):
        mail = {"from": "a@b.com", "subject": "S", "date": "D", "body": "",
                "attachments": [{"filename": "техзадание.pdf"}]}
        r = self._r()
        r.build_chat_input(mail, [])
        assert r._has_tz is True
        assert r._has_spec is False

    def test_build_chat_input_detects_spec_by_filename(self):
        mail = {"from": "a@b.com", "subject": "S", "date": "D", "body": "",
                "attachments": [{"filename": "спецификация.xlsx"}]}
        r = self._r()
        r.build_chat_input(mail, [])
        assert r._has_spec is True

    def test_build_chat_input_detects_both(self):
        mail = {"from": "a@b.com", "subject": "S", "date": "D", "body": "",
                "attachments": [{"filename": "TZ_v2.docx"}, {"filename": "spec.xlsx"}]}
        r = self._r()
        r.build_chat_input(mail, [])
        assert r._has_tz is True and r._has_spec is True

    # handle_no_attachments ─────────────────────────────────────────────────────

    def test_handle_no_attachments_sends_email_and_returns_true(self, monkeypatch):
        sent = []
        monkeypatch.setattr("agent1_dzo_inspector.runner.send_email",
                            lambda **kw: sent.append(kw))
        monkeypatch.setattr("shared.database.update_job", lambda *a, **k: None)
        result = self._r().handle_no_attachments("a@b.com", "Subj", "jid")
        assert result is True
        assert sent

    # parse_steps ──────────────────────────────────────────────────────────────

    def test_parse_steps_empty_uses_raw_output(self):
        decision, arts, _ = self._r().parse_steps([], {"output": "Ответ"}, "j")
        assert "Ответ" in arts["email_html"]

    def test_parse_steps_extracts_email_html(self):
        step = MagicMock()
        steps = [("tool", json.dumps({"emailHtml": "<p>OK</p>", "decision": "Заявка полная"}))]
        decision, arts, _ = self._r().parse_steps(steps, {}, "j")
        assert arts["email_html"] == "<p>OK</p>"
        assert decision == "Заявка полная"

    def test_parse_steps_extracts_reply_subject(self):
        steps = [("tool", json.dumps({"emailHtml": "h", "subject": "Re: ТО-1",
                                       "decision": "Требуется доработка"}))]
        _, _, reply_subject = self._r().parse_steps(steps, {}, "j")
        assert reply_subject == "Re: ТО-1"

    def test_parse_steps_extracts_escalation_html(self):
        steps = [("tool", json.dumps({"escalationHtml": "<b>Эскалация</b>",
                                       "decision": "Требуется эскалация"}))]
        decision, arts, _ = self._r().parse_steps(steps, {}, "j")
        assert arts["escalation_html"] == "<b>Эскалация</b>"
        assert "эскалация" in decision.lower()

    def test_parse_steps_appends_tz_summary(self):
        analysis = {"summary": "ТЗ содержит критические ошибки",
                    "overall_status": "fail", "critical_issues": ["err1"]}
        steps = [("tool", json.dumps({"emailHtml": "<p>Base</p>",
                                       "decision": "Требуется доработка",
                                       "tzAgentAnalysis": analysis}))]
        _, arts, _ = self._r().parse_steps(steps, {}, "j")
        assert "ТЗ содержит критические ошибки" in arts["email_html"]

    def test_parse_steps_malformed_step_skipped(self):
        steps = [("tool", "INVALID_JSON"), ("tool2", json.dumps({"emailHtml": "<p>X</p>",
                                                                    "decision": "OK"}))]
        decision, arts, _ = self._r().parse_steps(steps, {}, "j")
        assert arts["email_html"] == "<p>X</p>"

    # send_reply ───────────────────────────────────────────────────────────────

    def test_send_reply_escalation(self, monkeypatch):
        sent = []; notified = []
        monkeypatch.setattr("agent1_dzo_inspector.runner.send_email",
                            lambda **kw: sent.append(kw))
        monkeypatch.setattr("agent1_dzo_inspector.runner.notify",
                            lambda *a, **k: notified.append(a))
        self._r().send_reply("a@b.com", "S", "Re:", "Требуется эскалация",
                             {"email_html": "<h>", "escalation_html": "<e>",
                              "tezis_html": "", "corrected_html": ""})
        assert sent and notified

    def test_send_reply_approved(self, monkeypatch):
        sent = []; notified = []
        monkeypatch.setattr("agent1_dzo_inspector.runner.send_email",
                            lambda **kw: sent.append(kw))
        monkeypatch.setattr("agent1_dzo_inspector.runner.notify",
                            lambda *a, **k: notified.append(a))
        self._r().send_reply("a@b.com", "S", "", "Заявка полная",
                             {"email_html": "<h>", "escalation_html": "",
                              "tezis_html": "<t>", "corrected_html": ""})
        assert sent and notified

    def test_send_reply_dorabotka(self, monkeypatch):
        sent = []; notified = []
        monkeypatch.setattr("agent1_dzo_inspector.runner.send_email",
                            lambda **kw: sent.append(kw))
        monkeypatch.setattr("agent1_dzo_inspector.runner.notify",
                            lambda *a, **k: notified.append(a))
        self._r().send_reply("a@b.com", "S", "", "Требуется доработка",
                             {"email_html": "<h>", "escalation_html": "",
                              "tezis_html": "", "corrected_html": "<c>"})
        assert sent and notified

    # db_result_fields ─────────────────────────────────────────────────────────

    def test_db_result_fields(self):
        r = self._r()
        r._has_tz = True; r._has_spec = False
        analysis = {"overall_status": "pass", "critical_issues": ["a", "b"]}
        result = r.db_result_fields(
            {"attachments": ["f1", "f2"]},
            {"tz_agent_analysis": analysis}
        )
        assert result["has_tz"] is True
        assert result["has_spec"] is False
        assert result["attachments"] == 2
        assert result["tz_agent_overall_status"] == "pass"
        assert result["tz_agent_critical_issues"] == 2

    def test_db_result_fields_no_analysis(self):
        r = self._r()
        result = r.db_result_fields({"attachments": []}, {"tz_agent_analysis": None})
        assert result["tz_agent_overall_status"] == ""
        assert result["tz_agent_critical_issues"] == 0


# ─────────────────────────── TZ runner ───────────────────────────────────────

class TestTzEmailRunner:
    def _r(self): return TzEmailRunner()

    def test_agent_id(self):
        assert self._r().agent_id == "tz"

    def test_imap_config_keys(self):
        cfg = self._r().imap_config
        for k in ("host", "user", "password", "port", "folder"):
            assert k in cfg

    def test_build_chat_input(self):
        mail = {"from": "a@b.com", "subject": "ТЗ-1", "date": "2026-01-01",
                "body": "Текст ТЗ", "attachments": []}
        txt = self._r().build_chat_input(mail, ["---- Файл ----\ntext"])
        assert "ТЗ-1" in txt and "a@b.com" in txt

    # parse_steps ──────────────────────────────────────────────────────────────

    def test_parse_steps_empty_uses_raw_output(self):
        _, arts, _ = self._r().parse_steps([], {"output": "Анализ ТЗ"}, "j")
        assert "Анализ ТЗ" in arts["email_html"]

    def test_parse_steps_extracts_email_html(self):
        steps = [("tool", json.dumps({"emailHtml": "<p>ТЗ OK</p>",
                                       "decision": "Соответствует требованиям"}))]
        decision, arts, _ = self._r().parse_steps(steps, {}, "j")
        assert arts["email_html"] == "<p>ТЗ OK</p>"
        assert "соответствует" in decision.lower()

    def test_parse_steps_extracts_corrected_html(self):
        steps = [("tool", json.dumps({"emailHtml": "h", "html": "<b>corrected</b>",
                                       "decision": "Требует доработки"}))]
        _, arts, _ = self._r().parse_steps(steps, {}, "j")
        assert arts["corrected_tz_html"] == "<b>corrected</b>"

    def test_parse_steps_extracts_json_report(self):
        steps = [("tool", json.dumps({
            "overall_status": "pass",
            "sections_found": ["Цели", "Требования"]
        }))]
        _, arts, _ = self._r().parse_steps(steps, {}, "j")
        assert arts["json_report"]["overall_status"] == "pass"

    def test_parse_steps_reply_subject(self):
        steps = [("tool", json.dumps({"emailHtml": "h", "subject": "Re: ТЗ",
                                       "decision": "ok"}))]
        _, _, rs = self._r().parse_steps(steps, {}, "j")
        assert rs == "Re: ТЗ"

    def test_parse_steps_malformed_skipped(self):
        steps = [("t", "BAD_JSON"), ("t2", json.dumps({"emailHtml": "<p>OK</p>",
                                                          "decision": "ok"}))]
        _, arts, _ = self._r().parse_steps(steps, {}, "j")
        assert arts["email_html"] == "<p>OK</p>"

    # send_reply ───────────────────────────────────────────────────────────────

    def test_send_reply_accepted(self, monkeypatch):
        sent = []; notified = []
        monkeypatch.setattr("agent2_tz_inspector.runner.send_email",
                            lambda **kw: sent.append(kw))
        monkeypatch.setattr("agent2_tz_inspector.runner.notify",
                            lambda *a, **k: notified.append(a))
        self._r().send_reply("a@b.com", "S", "Re:", "Соответствует требованиям",
                             {"email_html": "<h>", "corrected_tz_html": ""})
        assert sent and notified

    def test_send_reply_dorabotka_with_corrected_html(self, monkeypatch):
        sent = []; notified = []
        monkeypatch.setattr("agent2_tz_inspector.runner.send_email",
                            lambda **kw: sent.append(kw))
        monkeypatch.setattr("agent2_tz_inspector.runner.notify",
                            lambda *a, **k: notified.append(a))
        self._r().send_reply("a@b.com", "S", "", "Требует доработки",
                             {"email_html": "<h>", "corrected_tz_html": "<c>"})
        assert sent
        # attachment should be set
        assert any(kw.get("attachment_bytes") for kw in sent)

    def test_send_reply_dorabotka_without_corrected(self, monkeypatch):
        sent = []
        monkeypatch.setattr("agent2_tz_inspector.runner.send_email",
                            lambda **kw: sent.append(kw))
        monkeypatch.setattr("agent2_tz_inspector.runner.notify",
                            lambda *a, **k: None)
        self._r().send_reply("a@b.com", "S", "", "Требует доработки",
                             {"email_html": "<h>", "corrected_tz_html": ""})
        # no attachment when corrected_tz_html is empty
        assert sent[0].get("attachment_bytes") is None

    # db_result_fields ─────────────────────────────────────────────────────────

    def test_db_result_fields_with_report(self):
        report = {"overall_status": "pass", "sections_found": ["A", "B"]}
        result = self._r().db_result_fields(
            {"attachments": ["a", "b", "c"]}, {"json_report": report}
        )
        assert result["attachments"] == 3
        assert result["overall_status"] == "pass"
        assert result["sections_found"] == ["A", "B"]

    def test_db_result_fields_empty_report(self):
        result = self._r().db_result_fields({"attachments": []}, {"json_report": {}})
        assert result["overall_status"] == ""
        assert result["sections_found"] == []
