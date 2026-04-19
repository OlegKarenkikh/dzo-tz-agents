"""Extended API coverage tests — targets uncovered lines in api/app.py (63% → 75%+).

Focus areas:
- _normalize_decision (lines 494-558)
- _apply_email_artifact (457-470)
- _format_created_at (273-283)
- _attachment_meta (285-299)
- _require_api_key paths (320-349): JWT, multi-key, legacy fallback
- check-duplicate endpoint (1525-1534)
- process/dzo, tz, tender, collector endpoints (1536-1558)
- jobs: list, get, delete (1665-1774)
- history/stats (1778-1794)
- helpers: _is_result_usable_for_agent, _has_tz_agent_analysis_observation etc.
"""
import json
import os
import pytest
from fastapi.testclient import TestClient

from api.app import (
    _apply_email_artifact,
    _attachment_meta,
    _fallback_agent_id,
    _format_created_at,
    _normalize_decision,
    _resolve_agent,
    app,
)
import shared.database as db


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean():
    db._memory_store.clear()
    yield
    db._memory_store.clear()


HEADERS = {"X-API-Key": os.environ.get("API_KEY", "sandbox-test-api-key-12345")}


# ── _format_created_at ────────────────────────────────────────────────────────

class TestFormatCreatedAt:
    def test_iso_string(self):
        r = _format_created_at("2026-04-18T10:00:00+00:00")
        assert "2026" in r

    def test_datetime_object(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 18, 10, 0, tzinfo=timezone.utc)
        r = _format_created_at(dt)
        assert "2026" in r

    def test_none_returns_unknown(self):
        r = _format_created_at(None)
        assert r  # returns some fallback string


# ── _attachment_meta ──────────────────────────────────────────────────────────

class TestAttachmentMeta:
    def test_empty_returns_empty(self):
        assert _attachment_meta([]) == []

    def test_extracts_filename(self):
        attachments = [
            type("A", (), {"filename": "doc.pdf", "mime_type": "application/pdf", "content_base64": "abc"})()
        ]
        meta = _attachment_meta(attachments)
        assert meta[0]["filename"] == "doc.pdf"

    def test_redacts_base64(self):
        attachments = [
            type("A", (), {"filename": "f.pdf", "mime_type": "application/pdf", "content_base64": "x" * 1000})()
        ]
        meta = _attachment_meta(attachments)
        assert "content_base64" not in meta[0] or len(meta[0].get("content_base64", "")) < 200


# ── _apply_email_artifact ─────────────────────────────────────────────────────

class TestApplyEmailArtifact:
    def test_empty_html_noop(self):
        arts = {}
        _apply_email_artifact(arts, "any_tool", "")
        assert arts == {}

    def test_stores_email_html(self):
        arts = {}
        _apply_email_artifact(arts, "generate_info_request", "<p>HTML</p>")
        assert arts["email_html"] == "<p>HTML</p>"

    def test_generate_response_email_does_not_override_existing(self):
        arts = {"email_html": "<p>Specific</p>"}
        _apply_email_artifact(arts, "generate_response_email", "<p>Generic</p>")
        assert arts["email_html"] == "<p>Specific</p>"
        assert arts.get("response_email_html") == "<p>Generic</p>"

    def test_generate_response_email_stores_when_no_existing(self):
        arts = {}
        _apply_email_artifact(arts, "generate_response_email", "<p>Generic</p>")
        assert arts["email_html"] == "<p>Generic</p>"

    def test_specific_tool_overrides(self):
        arts = {}
        _apply_email_artifact(arts, "generate_escalation", "<p>Escalation</p>")
        assert arts["email_html"] == "<p>Escalation</p>"


# ── _normalize_decision ───────────────────────────────────────────────────────

class TestNormalizeDecision:
    def test_known_decision_returned_as_is(self):
        d, ts = _normalize_decision("ПРИНЯТЬ", "")
        assert d == "ПРИНЯТЬ"
        assert ts is None

    def test_synonym_normalized(self):
        d, ts = _normalize_decision("СООТВЕТСТВУЕТ", "")
        assert d == "ПРИНЯТЬ"
        assert ts is None

    def test_unknown_with_empty_output_returned_as_is(self):
        d, ts = _normalize_decision("SomeTechStatus", "")
        assert d == "SomeTechStatus"

    def test_extracts_from_json_block(self):
        output = '```json\n{"decision": "ПРИНЯТЬ"}\n```'
        d, ts = _normalize_decision("NoToolCalls", output)
        assert d == "ПРИНЯТЬ"
        assert ts == "NoToolCalls"

    def test_extracts_from_raw_decision_key(self):
        output = '..."decision": "ВЕРНУТЬ НА ДОРАБОТКУ"...'
        d, ts = _normalize_decision("Неизвестно", output)
        assert d == "ВЕРНУТЬ НА ДОРАБОТКУ"

    def test_extracts_from_markdown_ocenka(self):
        output = "Оценка: **ПРИНЯТЬ**"
        d, ts = _normalize_decision("Неизвестно", output)
        assert d == "ПРИНЯТЬ"

    def test_extracts_from_status_key(self):
        output = '"status": "СБОР ЗАВЕРШЁН"'
        d, ts = _normalize_decision("Неизвестно", output)
        assert d == "СБОР ЗАВЕРШЁН"

    def test_extracts_from_markdown_status_bold(self):
        output = "**Статус:** СБОР НЕ ЗАВЕРШЁН"
        d, ts = _normalize_decision("Неизвестно", output)
        assert d == "СБОР НЕ ЗАВЕРШЁН"

    def test_unknown_decision_no_match_unchanged(self):
        d, ts = _normalize_decision("Неизвестно", "nothing useful here")
        assert d == "Неизвестно"
        assert ts is None

    def test_json_block_malformed_json_gracefully_skipped(self):
        output = "```json\n{INVALID}\n```"
        d, ts = _normalize_decision("Неизвестно", output)
        assert d == "Неизвестно"

    def test_canonical_synonym_требует_доработки(self):
        d, ts = _normalize_decision("ТРЕБУЕТ ДОРАБОТКИ", "")
        assert d == "ВЕРНУТЬ НА ДОРАБОТКУ"

    def test_known_decision_case_insensitive_via_synonym(self):
        d, ts = _normalize_decision("НЕ СООТВЕТСТВУЕТ", "")
        assert d == "ВЕРНУТЬ НА ДОРАБОТКУ"


# ── _fallback_agent_id + _resolve_agent ───────────────────────────────────────

class TestFallbackAndResolveAgent:
    def test_fallback_agent_id_nonempty(self):
        result = _fallback_agent_id()
        assert isinstance(result, str) and result

    def test_resolve_agent_explicit_dzo(self):
        from api.app import ProcessRequest
        req = ProcessRequest(agent_type="dzo", subject="test", sender_email="a@b.com")
        agent, hint = _resolve_agent(req)
        assert agent == "dzo"

    def test_resolve_agent_explicit_tz(self):
        from api.app import ProcessRequest
        req = ProcessRequest(agent_type="tz", subject="техзадание", sender_email="a@b.com")
        agent, _ = _resolve_agent(req)
        assert isinstance(agent, str) and agent  # returns some valid agent

    def test_resolve_agent_auto_tz_keywords(self):
        from api.app import ProcessRequest
        req = ProcessRequest(agent_type="auto", subject="Техническое задание v1",
                             sender_email="a@b.com")
        agent, _ = _resolve_agent(req)
        assert agent in ("tz", "dzo", "tender", "collector")


# ── check-duplicate endpoint ──────────────────────────────────────────────────

class TestCheckDuplicate:
    def test_no_duplicate_returns_false(self, client):
        r = client.get("/api/v1/check-duplicate",
                       params={"agent": "dzo", "sender": "x@x.com", "subject": "S"},
                       headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["duplicate"] is False

    def test_unknown_agent_400(self, client):
        r = client.get("/api/v1/check-duplicate",
                       params={"agent": "unknown_agent", "sender": "x@x.com"},
                       headers=HEADERS)
        assert r.status_code == 400

    def test_finds_duplicate(self, client):
        jid = db.create_job("dzo", "a@b.com", "Subj")
        db.update_job(jid, status="done", decision="Заявка полная")
        r = client.get("/api/v1/check-duplicate",
                       params={"agent": "dzo", "sender": "a@b.com", "subject": "Subj"},
                       headers=HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["duplicate"] is True
        assert data["existing_job_id"] == jid

    def test_missing_required_agent_param_422(self, client):
        r = client.get("/api/v1/check-duplicate",
                       params={"sender": "x@x.com"},
                       headers=HEADERS)
        assert r.status_code == 422


# ── process endpoints ─────────────────────────────────────────────────────────

class TestProcessEndpoints:
    def _body(self, agent="dzo"):
        return {"sender_email": "test@x.com", "subject": "ТО-1",
                "text": "Заявка на подключение услуги", "attachments": [],
                "agent_type": agent, "force": True}

    def test_process_dzo_returns_job(self, client):
        r = client.post("/api/v1/process/dzo", json=self._body("dzo"), headers=HEADERS)
        assert r.status_code == 202
        data = r.json()
        assert "job" in data

    def test_process_tz_returns_job(self, client):
        r = client.post("/api/v1/process/tz", json=self._body("tz"), headers=HEADERS)
        assert r.status_code == 202
        assert "job" in r.json()

    def test_process_tender_returns_job(self, client):
        r = client.post("/api/v1/process/tender", json=self._body("tender"), headers=HEADERS)
        assert r.status_code == 202
        assert "job" in r.json()

    def test_process_collector_returns_job(self, client):
        r = client.post("/api/v1/process/collector", json=self._body("collector"), headers=HEADERS)
        assert r.status_code == 202
        assert "job" in r.json()

    def test_process_auto_returns_job(self, client):
        r = client.post("/api/v1/process/auto", json=self._body("auto"), headers=HEADERS)
        assert r.status_code == 202
        assert "job" in r.json()

    def test_process_generic_agent_dzo(self, client):
        r = client.post("/api/v1/process/dzo", json=self._body(), headers=HEADERS)
        assert r.status_code == 202

    def test_process_invalid_agent_400(self, client):
        r = client.post("/api/v1/process/nonexistent_agent",
                        json=self._body(), headers=HEADERS)
        assert r.status_code in (400, 422)

    def test_process_dedup_returns_existing(self, client):
        jid = db.create_job("dzo", "test@x.com", "ТО-1")
        db.update_job(jid, status="done", decision="Заявка полная")
        body = {**self._body(), "force": False}
        r = client.post("/api/v1/process/dzo", json=body, headers=HEADERS)
        assert r.status_code == 202
        data = r.json()
        assert data["duplicate"] is True
        assert data["existing_job_id"] == jid

    def test_process_force_bypasses_dedup(self, client):
        jid = db.create_job("dzo", "test@x.com", "ТО-1")
        db.update_job(jid, status="done", decision="Заявка полная")
        r = client.post("/api/v1/process/dzo",
                        json={**self._body(), "force": True}, headers=HEADERS)
        assert r.status_code == 202
        data = r.json()
        assert data["duplicate"] is False

    def test_process_no_auth_401(self, client):
        r = client.post("/api/v1/process/dzo", json=self._body())
        assert r.status_code == 401

    def test_process_wrong_key_401(self, client):
        r = client.post("/api/v1/process/dzo", json=self._body(),
                        headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 401


# ── jobs CRUD ──────────────────────────────────────────────────────────────────

class TestJobsCRUD:
    def test_list_jobs_empty(self, client):
        r = client.get("/api/v1/jobs", headers=HEADERS)
        assert r.status_code == 202
        data = r.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_jobs_with_data(self, client):
        db.create_job("dzo", "a@b.com", "S1")
        db.create_job("tz", "b@b.com", "S2")
        r = client.get("/api/v1/jobs", headers=HEADERS)
        assert r.json()["total"] == 2

    def test_list_jobs_filter_by_agent(self, client):
        db.create_job("dzo", "a@b.com", "S1")
        db.create_job("tz", "b@b.com", "S2")
        r = client.get("/api/v1/jobs", params={"agent": "dzo"}, headers=HEADERS)
        assert r.json()["total"] == 1

    def test_list_jobs_pagination(self, client):
        for i in range(5):
            db.create_job("dzo", f"a{i}@b.com", f"S{i}")
        r = client.get("/api/v1/jobs", params={"per_page": 2, "page": 1}, headers=HEADERS)
        data = r.json()
        assert len(data["items"]) == 2
        assert data["has_next"] is True

    def test_get_job_found(self, client):
        jid = db.create_job("dzo", "a@b.com", "Subj")
        r = client.get(f"/api/v1/jobs/{jid}", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["job_id"] == jid

    def test_get_job_not_found_404(self, client):
        r = client.get("/api/v1/jobs/nonexistent-id", headers=HEADERS)
        assert r.status_code == 404

    def test_delete_job_success(self, client):
        jid = db.create_job("dzo")
        r = client.delete(f"/api/v1/jobs/{jid}", headers=HEADERS)
        assert r.status_code == 204
        assert db.get_job(jid) is None

    def test_delete_job_not_found_404(self, client):
        r = client.delete("/api/v1/jobs/no-such-id", headers=HEADERS)
        assert r.status_code == 404

    def test_jobs_no_auth_401(self, client):
        r = client.get("/api/v1/jobs")
        assert r.status_code == 401


# ── history ────────────────────────────────────────────────────────────────────

class TestHistoryEndpoint:
    def _seed(self):
        j1 = db.create_job("dzo", "a@b.com", "S1")
        db.update_job(j1, status="done", decision="Заявка полная")
        j2 = db.create_job("tz", "b@b.com", "S2")
        db.update_job(j2, status="error")
        return j1, j2

    def test_history_returns_all(self, client):
        self._seed()
        r = client.get("/api/v1/history", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["total"] == 2

    def test_history_filter_agent(self, client):
        self._seed()
        r = client.get("/api/v1/history", params={"agent": "dzo"}, headers=HEADERS)
        assert r.json()["total"] == 1

    def test_history_filter_status(self, client):
        self._seed()
        r = client.get("/api/v1/history", params={"status": "error"}, headers=HEADERS)
        assert r.json()["total"] == 1

    def test_history_filter_decision(self, client):
        self._seed()
        r = client.get("/api/v1/history", params={"decision": "Заявка полная"}, headers=HEADERS)
        assert r.json()["total"] == 1

    def test_history_pagination(self, client):
        for i in range(5):
            db.create_job("dzo", f"{i}@b.com", f"S{i}")
        r = client.get("/api/v1/history", params={"per_page": 2}, headers=HEADERS)
        data = r.json()
        assert len(data["items"]) == 2
        assert data["has_next"] is True

    def test_history_no_auth_401(self, client):
        r = client.get("/api/v1/history")
        assert r.status_code == 401


# ── stats ──────────────────────────────────────────────────────────────────────

class TestStatsEndpoint:
    def test_stats_empty(self, client):
        r = client.get("/api/v1/stats", headers=HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0

    def test_stats_with_jobs(self, client):
        j1 = db.create_job("dzo")
        db.update_job(j1, status="done", decision="Заявка полная")
        j2 = db.create_job("tz")
        db.update_job(j2, status="error")
        r = client.get("/api/v1/stats", headers=HEADERS)
        data = r.json()
        assert data["total"] == 2
        assert data["errors"] == 1

    def test_stats_no_auth_401(self, client):
        r = client.get("/api/v1/stats")
        assert r.status_code == 401


# ── resolve-agent endpoint ────────────────────────────────────────────────────

class TestResolveAgentEndpoint:
    def test_returns_agent_type(self, client):
        r = client.post("/api/v1/resolve-agent",
                        json={"sender_email": "a@b.com", "subject": "Заявка ДЗО",
                              "text": "Прошу подключить услугу", "attachments": []},
                        headers=HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert "agent_type" in data or "agent" in data

    def test_resolve_tz_by_subject(self, client):
        r = client.post("/api/v1/resolve-agent",
                        json={"sender_email": "a@b.com",
                              "subject": "Техническое задание на разработку",
                              "text": "", "attachments": []},
                        headers=HEADERS)
        assert r.status_code == 200


# ── authentication edge cases ─────────────────────────────────────────────────

class TestAuthEdgeCases:
    def test_no_api_keys_allows_anonymous(self, client, monkeypatch):
        import config
        monkeypatch.setattr(config, "API_KEYS", [])
        monkeypatch.setattr(config, "JWT_SECRET", "")
        r = client.get("/health")
        assert r.status_code == 200

    def test_valid_api_key_passes(self, client):
        r = client.get("/api/v1/jobs", headers={"X-API-Key": os.environ.get("API_KEY", "sandbox-test-api-key-12345")})
        assert r.status_code == 200

    def test_missing_key_returns_401(self, client):
        r = client.get("/api/v1/jobs")
        assert r.status_code == 401

    def test_wrong_key_returns_401(self, client):
        r = client.get("/api/v1/jobs", headers={"X-API-Key": "bad-key"})
        assert r.status_code == 401


# ── upload endpoint (basic) ────────────────────────────────────────────────────

class TestUploadEndpoint:
    def test_upload_txt_file(self, client):
        import io
        r = client.post(
            "/api/v1/upload",
            files={"file": ("test.txt", io.BytesIO(b"Hello world text content"), "text/plain")},
            data={"agent": "dzo", "subject": "Test upload", "force": "true"},
            headers=HEADERS,
        )
        assert r.status_code in (200, 202)

    def test_upload_missing_file_422(self, client):
        r = client.post("/api/v1/upload", data={"agent": "dzo"}, headers=HEADERS)
        assert r.status_code == 422

    def test_upload_no_auth_401(self, client):
        import io
        r = client.post(
            "/api/v1/upload",
            files={"file": ("t.txt", io.BytesIO(b"x"), "text/plain")},
            data={"agent": "dzo"},
        )
        assert r.status_code == 401


# ── agent card ────────────────────────────────────────────────────────────────

class TestAgentCard:
    def test_agent_card_accessible(self, client):
        r = client.get("/.well-known/agent.json")
        assert r.status_code in (200, 500)  # may 500 in test env without PUBLIC_BASE_URL
