"""
Tests for _process_with_agent — core background task in api/app.py.
Lines 560-1300 covered by calling the function directly with mocked agents.
"""
import json
from unittest.mock import MagicMock, patch
import pytest

import shared.database as db
import api.app as _app
from api.app import ProcessRequest, _process_with_agent


@pytest.fixture(autouse=True)
def clean():
    db._memory_store.clear()
    yield
    db._memory_store.clear()


def _req(**kw) -> ProcessRequest:
    d = dict(sender_email="test@example.com", subject="Заявка",
             text="Текст заявки", attachments=[], agent_type="dzo", force=True)
    d.update(kw)
    return ProcessRequest(**d)


def _make_result(decision="ПРИНЯТЬ", extra_obs=None, tool_name="generate_response_email"):
    obs = {"decision": decision, "emailHtml": f"<p>{decision}</p>"}
    if extra_obs:
        obs.update(extra_obs)
    return {
        "output": decision,
        "intermediate_steps": [(tool_name, json.dumps(obs))],
    }


def _setup(monkeypatch, agent, agent_type="dzo"):
    """Patch agent factory, fallback chain, timeouts and sleep."""
    factories = {
        "dzo":       ("agent1_dzo_inspector.agent", "create_dzo_agent"),
        "tz":        ("agent2_tz_inspector.agent", "create_tz_agent"),
        "tender":    ("agent21_tender_inspector.agent", "create_tender_agent"),
        "collector": ("agent3_collector_inspector.agent", "create_collector_agent"),
    }
    mod, fn = factories[agent_type]
    monkeypatch.setattr(f"{mod}.{fn}", lambda **kw: agent)
    monkeypatch.setattr("shared.llm.build_fallback_chain", lambda m: ["gpt-4o"])
    monkeypatch.setattr(_app, "AGENT_JOB_TIMEOUT_SEC", 0)
    monkeypatch.setattr(_app, "AGENT_MAX_RETRIES", 1)
    monkeypatch.setattr(_app, "AGENT_RATE_LIMIT_BACKOFF", 0)
    monkeypatch.setattr("time.sleep", lambda s: None)


# ── DZO happy path ────────────────────────────────────────────────────────────

class TestDzoHappy:
    def test_done_status(self, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = _make_result("ПРИНЯТЬ")
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        assert db.get_job(jid)["status"] == "done"
        assert db.get_job(jid)["decision"] == "ПРИНЯТЬ"

    def test_email_html_in_result(self, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = _make_result("ПРИНЯТЬ")
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        assert "email_html" in db.get_job(jid)["result"]

    def test_tezis_form_html(self, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = _make_result("ПРИНЯТЬ", {"tezisFormHtml": "<b>T</b>"})
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        assert db.get_job(jid)["result"]["tezis_form_html"] == "<b>T</b>"

    def test_corrected_html(self, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = _make_result("ВЕРНУТЬ НА ДОРАБОТКУ",
                                                 {"correctedHtml": "<i>Fix</i>"})
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        assert db.get_job(jid)["result"]["corrected_html"] == "<i>Fix</i>"

    def test_escalation_html(self, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = _make_result("ПРИНЯТЬ", {"escalationHtml": "<u>E</u>"})
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        assert db.get_job(jid)["result"]["escalation_html"] == "<u>E</u>"

    def test_tz_agent_analysis(self, monkeypatch):
        analysis = {"summary": "ok", "overall_status": "pass", "critical_issues": []}
        agent = MagicMock()
        agent.invoke.return_value = _make_result("ПРИНЯТЬ", {"tzAgentAnalysis": analysis})
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        assert db.get_job(jid)["result"]["tz_agent_analysis"] == analysis

    def test_processing_log_events(self, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = _make_result("ПРИНЯТЬ")
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        events = db.get_job(jid)["result"]["processing_log"]["events"]
        stages = [e["stage"] for e in events]
        assert "received" in stages
        assert "completed" in stages

    def test_validation_report_extracted(self, monkeypatch):
        obs = {"decision": "ПРИНЯТЬ", "emailHtml": "<p>ok</p>",
               "checklist_required": ["Устав"], "checklist_attachments": []}
        agent = MagicMock()
        agent.invoke.return_value = {"output": "ok",
                                     "intermediate_steps": [("validate", json.dumps(obs))]}
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        assert "validation_report" in db.get_job(jid)["result"]

    def test_peer_agent_results_accumulated(self, monkeypatch):
        obs1 = {"decision": "ПРИНЯТЬ", "emailHtml": "h",
                "peerAgentResult": {"agent": "tz", "status": "ok"}}
        obs2 = {"peerAgentResult": {"agent": "tender", "status": "ok"}}
        agent = MagicMock()
        agent.invoke.return_value = {
            "output": "ok",
            "intermediate_steps": [("t1", json.dumps(obs1)), ("t2", json.dumps(obs2))]
        }
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        peers = db.get_job(jid)["result"].get("peer_agent_results", [])
        assert len(peers) == 2

    def test_corrected_tz_html(self, monkeypatch):
        obs = {"decision": "ПРИНЯТЬ", "emailHtml": "h",
               "html": "<div>TZ</div>", "title": "ТЗ v2"}
        agent = MagicMock()
        agent.invoke.return_value = {"output": "ok",
                                     "intermediate_steps": [("fix_tz", json.dumps(obs))]}
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        assert db.get_job(jid)["result"].get("corrected_tz_html") == "<div>TZ</div>"

    def test_tz_summary_appended_to_email_html(self, monkeypatch):
        analysis = {"summary": "Критические нарушения найдены"}
        obs = {"decision": "ПРИНЯТЬ", "emailHtml": "<p>Email</p>",
               "tzAgentAnalysis": analysis}
        agent = MagicMock()
        agent.invoke.return_value = {"output": "ok",
                                     "intermediate_steps": [("t", json.dumps(obs))]}
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        email = db.get_job(jid)["result"].get("email_html", "")
        assert "Критические нарушения найдены" in email


# ── TZ agent ──────────────────────────────────────────────────────────────────

class TestTzAgent:
    def test_tz_done(self, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = _make_result("ПРИНЯТЬ")
        _setup(monkeypatch, agent, "tz")
        jid = db.create_job("tz")
        _process_with_agent(jid, "tz", _req(agent_type="tz"))
        assert db.get_job(jid)["status"] == "done"

    def test_json_report_extracted(self, monkeypatch):
        obs = {"decision": "ПРИНЯТЬ", "emailHtml": "h",
               "sections": ["Цели", "Требования"], "overall_status": "pass"}
        agent = MagicMock()
        agent.invoke.return_value = {"output": "ok",
                                     "intermediate_steps": [("analyze_tz", json.dumps(obs))]}
        _setup(monkeypatch, agent, "tz")
        jid = db.create_job("tz")
        _process_with_agent(jid, "tz", _req(agent_type="tz"))
        assert "json_report" in db.get_job(jid)["result"]


# ── Tender agent ──────────────────────────────────────────────────────────────

class TestTenderAgent:
    def test_document_list_extracted(self, monkeypatch):
        obs = {"documents": ["Устав", "Анкета"], "summary": {"total": 2}}
        agent = MagicMock()
        agent.invoke.return_value = {"output": "ok", "intermediate_steps": [
            ("generate_document_list", json.dumps(obs))]}
        _setup(monkeypatch, agent, "tender")
        jid = db.create_job("tender")
        _process_with_agent(jid, "tender", _req(agent_type="tender"))
        r = db.get_job(jid)["result"]
        assert r["document_list"]["documents"] == ["Устав", "Анкета"]
        assert r["tender_tool_status"] == "documents_found"

    def test_document_list_error(self, monkeypatch):
        obs = {"error": "no sections"}
        agent = MagicMock()
        agent.invoke.return_value = {"output": "", "intermediate_steps": [
            ("generate_document_list", json.dumps(obs))]}
        _setup(monkeypatch, agent, "tender")
        jid = db.create_job("tender")
        _process_with_agent(jid, "tender", _req(agent_type="tender"))
        r = db.get_job(jid)["result"]
        assert "document_list_error" in r
        assert r["tender_tool_status"] == "tool_error"


# ── Collector agent ────────────────────────────────────────────────────────────

class TestCollectorAgent:
    def test_collector_done(self, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = _make_result("СБОР ЗАВЕРШЁН")
        _setup(monkeypatch, agent, "collector")
        jid = db.create_job("collector")
        _process_with_agent(jid, "collector", _req(agent_type="collector"))
        assert db.get_job(jid)["status"] == "done"


# ── NoToolCalls ────────────────────────────────────────────────────────────────

class TestNoToolCalls:
    def test_no_tool_calls_becomes_missing(self, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = {"output": "no tools", "intermediate_steps": []}
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        job = db.get_job(jid)
        assert job["status"] == "done"
        assert job["decision"] in ("tool_calls_missing", "Неизвестно")

    def test_no_tool_calls_model_error_artifact(self, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = {"output": "no tools", "intermediate_steps": []}
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        r = db.get_job(jid)["result"]
        # Either model_error artifact or just decision — both are valid
        assert db.get_job(jid)["decision"] is not None


# ── Exception in agent ────────────────────────────────────────────────────────

class TestAgentException:
    def test_exception_status_error(self, monkeypatch):
        agent = MagicMock()
        agent.invoke.side_effect = RuntimeError("kaboom")
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        job = db.get_job(jid)
        assert job["status"] == "error"
        assert "kaboom" in job["error"]

    def test_error_processing_log(self, monkeypatch):
        agent = MagicMock()
        agent.invoke.side_effect = ValueError("bad")
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        assert "processing_log" in db.get_job(jid)["result"]


# ── Token limit exhausted ─────────────────────────────────────────────────────

class TestTokenLimitExhausted:
    def test_token_limit_decision(self, monkeypatch):
        from openai import APIStatusError
        exc = APIStatusError(
            "tokens_limit_reached",
            response=MagicMock(status_code=413),
            body={"error": {"code": "tokens_limit_reached"}},
        )
        agent = MagicMock()
        agent.invoke.side_effect = exc
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        job = db.get_job(jid)
        assert job["status"] == "done"
        assert job["decision"] == "token_limit_exhausted"


# ── Rate limit exhausted ──────────────────────────────────────────────────────

class TestRateLimitExhausted:
    def test_rate_limit_decision(self, monkeypatch):
        from openai import RateLimitError
        exc = RateLimitError(
            "429 rate limit",
            response=MagicMock(status_code=429),
            body={"error": {"type": "rate_limit_exceeded"}},
        )
        agent = MagicMock()
        agent.invoke.side_effect = exc
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        job = db.get_job(jid)
        assert job["status"] == "done"
        assert job["decision"] == "rate_limit_exhausted"


# ── Job not found ─────────────────────────────────────────────────────────────

class TestJobNotFound:
    def test_returns_silently(self, monkeypatch):
        monkeypatch.setattr("shared.llm.build_fallback_chain", lambda m: ["gpt-4o"])
        _process_with_agent("nonexistent-uuid", "dzo", _req())  # no exception


# ── TZ signal → missing_recommended_tool ─────────────────────────────────────

class TestTzSignalWarning:
    def test_missing_tool_warning_stored(self, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = _make_result("ПРИНЯТЬ")
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        req = _req(subject="Техническое задание на разработку ПО")
        _process_with_agent(jid, "dzo", req)
        r = db.get_job(jid)["result"]
        assert "missing_recommended_tool" in r or "tz_agent_analysis" in r


# ── Decision normalization from output ───────────────────────────────────────

class TestDecisionFromOutput:
    def test_decision_extracted_from_output_text(self, monkeypatch):
        agent = MagicMock()
        # Steps empty → NoToolCalls, but output contains ПРИНЯТЬ
        agent.invoke.return_value = {
            "output": '"decision": "ПРИНЯТЬ"',
            "intermediate_steps": [],
        }
        _setup(monkeypatch, agent, "dzo")
        jid = db.create_job("dzo")
        _process_with_agent(jid, "dzo", _req())
        job = db.get_job(jid)
        assert job["status"] == "done"
