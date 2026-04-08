"""
Тесты FastAPI REST API (api/app.py).
Используется TestClient из fastapi.testclient.
"""
import os

import pytest
from fastapi.testclient import TestClient

# API_KEY устанавлен в conftest.py (значение: "test-secret")
from api.app import (  # noqa: E402
    _has_tz_agent_analysis_observation,
    _is_result_usable_for_agent,
    _looks_like_tz_content,
    app,
)
from shared.database import _memory_store  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clear_jobs():
    _memory_store.clear()
    yield
    _memory_store.clear()


HEADERS = {"X-API-Key": "test-secret"}


class TestHealth:
    def test_health_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_fields(self, client):
        data = client.get("/health").json()
        assert data["status"] == "ok"
        assert "uptime_sec" in data
        assert "version" in data

    def test_health_no_auth_required(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200


class TestAgents:
    def test_list_agents(self, client):
        resp = client.get("/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        ids = [a["id"] for a in data["agents"]]
        assert "dzo" in ids
        assert "tz" in ids
        assert "tender" in ids

    def test_list_agents_does_not_expose_internal_auto_detect(self, client):
        resp = client.get("/agents")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        assert agents
        for agent in agents:
            assert "auto_detect" not in agent


class TestProcessDzo:
    def test_process_dzo_returns_job_id(self, client):
        resp = client.post(
            "/api/v1/process/dzo",
            json={"text": "Заявка на закупку оборудования", "subject": "Тест"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job" in data
        job = data["job"]
        assert "job_id" in job
        assert job["agent"] == "dzo"
        assert job["status"] in ("pending", "running", "done")

    def test_process_dzo_without_api_key_returns_401(self, client):
        resp = client.post("/api/v1/process/dzo", json={"text": "Тест"})
        assert resp.status_code == 401


class TestProcessTz:
    def test_process_tz_returns_job_id(self, client):
        resp = client.post(
            "/api/v1/process/tz",
            json={"text": "Техническое задание на поставку серверов", "subject": "ТЗ тест"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job" in data
        job = data["job"]
        assert "job_id" in job
        assert job["agent"] == "tz"

    def test_process_tz_without_api_key_returns_401(self, client):
        resp = client.post("/api/v1/process/tz", json={"text": "Тест"})
        assert resp.status_code == 401


class TestProcessAuto:
    def test_auto_detects_tz_by_keyword(self, client):
        resp = client.post(
            "/api/v1/process/auto",
            json={"text": "Техническое задание на поставку", "subject": "ТЗ"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["job"]["agent"] == "tz"

    def test_auto_detects_tz_by_bare_tz_token(self, client):
        resp = client.post(
            "/api/v1/process/auto",
            json={"text": "ТЗ на разработку ПО", "subject": "ТЗ"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["job"]["agent"] == "tz"

    def test_auto_defaults_to_dzo(self, client):
        resp = client.post(
            "/api/v1/process/auto",
            json={"text": "Заявка на закупку", "subject": "Тест"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["job"]["agent"] == "dzo"

    def test_auto_detects_tender_by_keyword(self, client):
        resp = client.post(
            "/api/v1/process/auto",
            json={"text": "Просим проверить тендерную документацию", "subject": "Тендер"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["job"]["agent"] == "tender"


class TestProcessGeneric:
    def test_process_generic_tender_returns_job_id(self, client):
        resp = client.post(
            "/api/v1/process/tender",
            json={"text": "Тендерная документация", "subject": "Тендер"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["job"]["agent"] == "tender"

    def test_process_generic_unknown_agent_returns_400(self, client):
        resp = client.post(
            "/api/v1/process/unknown",
            json={"text": "Тест", "subject": "Тест"},
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_process_generic_without_api_key_returns_401(self, client):
        resp = client.post(
            "/api/v1/process/dzo",
            json={"text": "Тест", "subject": "Тест"},
        )
        assert resp.status_code == 401


class TestResolveAgent:
    def test_resolve_agent_returns_tz(self, client):
        resp = client.post(
            "/api/v1/resolve-agent",
            json={"text": "Техническое задание на поставку", "subject": "ТЗ"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent"] == "tz"
        assert "available_agents" in data

    def test_resolve_agent_without_api_key_returns_401(self, client):
        resp = client.post(
            "/api/v1/resolve-agent",
            json={"text": "Заявка", "subject": "Тест"},
        )
        assert resp.status_code == 401


class TestJobs:
    def test_get_nonexistent_job_returns_404(self, client):
        resp = client.get("/api/v1/jobs/nonexistent-uuid", headers=HEADERS)
        assert resp.status_code == 404

    def test_list_jobs_empty(self, client):
        resp = client.get("/api/v1/jobs", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_jobs_after_create(self, client):
        client.post("/api/v1/process/dzo", json={"text": "Тест"}, headers=HEADERS)
        resp = client.get("/api/v1/jobs", headers=HEADERS)
        assert resp.json()["total"] == 1

    def test_get_job_after_create(self, client):
        create_resp = client.post("/api/v1/process/dzo", json={"text": "Тест"}, headers=HEADERS)
        job_id = create_resp.json()["job"]["job_id"]
        resp = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["job_id"] == job_id

    def test_delete_job(self, client):
        create_resp = client.post("/api/v1/process/dzo", json={"text": "Тест"}, headers=HEADERS)
        job_id = create_resp.json()["job"]["job_id"]
        del_resp = client.delete(f"/api/v1/jobs/{job_id}", headers=HEADERS)
        assert del_resp.status_code == 200
        assert client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).status_code == 404

    def test_delete_nonexistent_job_returns_404(self, client):
        resp = client.delete("/api/v1/jobs/no-such-id", headers=HEADERS)
        assert resp.status_code == 404

    def test_jobs_without_api_key_returns_401(self, client):
        assert client.get("/api/v1/jobs").status_code == 401


class TestHistory:
    def test_history_returns_list(self, client):
        resp = client.get("/api/v1/history", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_history_without_api_key_returns_401(self, client):
        assert client.get("/api/v1/history").status_code == 401

    def test_history_filter_by_agent(self, client):
        client.post("/api/v1/process/dzo", json={"text": "ДЗО тест"}, headers=HEADERS)
        client.post("/api/v1/process/tz", json={"text": "ТЗ тест"}, headers=HEADERS)
        resp = client.get("/api/v1/history", params={"agent": "dzo"}, headers=HEADERS)
        for item in resp.json()["items"]:
            assert item["agent"] == "dzo"


class TestStatus:
    def test_status_endpoint(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert "last_runs" in data


class TestModelResultUsability:
    def test_tool_agents_require_tool_steps(self):
        ok, reason = _is_result_usable_for_agent("dzo", {"output": "ok", "intermediate_steps": []})
        assert ok is False
        assert reason == "NoToolCalls"

    def test_tool_agents_accept_non_empty_steps(self):
        ok, reason = _is_result_usable_for_agent("tz", {"output": "ok", "intermediate_steps": [["tool", "{}"]]})
        assert ok is True
        assert reason == ""

    def test_any_agent_requires_tool_steps(self):
        ok, reason = _is_result_usable_for_agent("custom", {"output": "ok", "intermediate_steps": []})
        assert ok is False
        assert reason == "NoToolCalls"

    def test_invalid_result_type_rejected(self):
        ok, reason = _is_result_usable_for_agent("dzo", "not-a-dict")
        assert ok is False
        assert reason == "InvalidResultType"


class TestDzoTzSignalHeuristics:
    def test_detects_tz_signal_by_attachment_name(self):
        assert _looks_like_tz_content(
            text="",
            subject="",
            attachment_names=["ТЗ на ноутбук.docx"],
        )

    def test_detects_tz_signal_by_text_and_subject(self):
        assert _looks_like_tz_content(
            text="Во вложении technical specification",
            subject="Проверка TZ",
            attachment_names=[],
        )

    def test_no_tz_signal_for_unrelated_content(self):
        assert not _looks_like_tz_content(
            text="Счет на оплату",
            subject="Коммерческое предложение",
            attachment_names=["invoice.pdf"],
        )

    def test_observation_contains_tz_agent_analysis(self):
        result = {
            "intermediate_steps": [
                ("generate_validation_report", {"decision": "Требуется доработка"}),
                ("analyze_tz_with_agent", {"tzAgentAnalysis": {"overall_status": "ОК"}}),
            ]
        }
        assert _has_tz_agent_analysis_observation(result)

    def test_observation_handles_json_tool_output(self):
        result = {
            "intermediate_steps": [
                ("analyze_tz_with_agent", '{"tzAgentAnalysis": {"overall_status": "ОК"}}'),
            ]
        }
        assert _has_tz_agent_analysis_observation(result)

    def test_observation_returns_false_when_missing(self):
        result = {"intermediate_steps": [("tool", {"emailHtml": "<p>x</p>"})]}
        assert not _has_tz_agent_analysis_observation(result)


class TestDeduplicate:
    """Tests for deduplication: GET /api/v1/check-duplicate and force-reprocessing."""

    def test_check_duplicate_no_dup(self, client):
        resp = client.get(
            "/api/v1/check-duplicate",
            params={"agent": "dzo", "sender": "a@b.com", "subject": "Тест"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["duplicate"] is False
        assert data["existing_job_id"] is None

    def test_check_duplicate_without_api_key_returns_401(self, client):
        resp = client.get(
            "/api/v1/check-duplicate",
            params={"agent": "dzo", "sender": "a@b.com", "subject": "Тест"},
        )
        assert resp.status_code == 401

    def test_process_returns_duplicate_on_second_call(self, client):
        from shared.database import update_job

        payload = {"text": "Заявка", "sender_email": "x@y.com", "subject": "Закупка"}

        r1 = client.post("/api/v1/process/dzo", json=payload, headers=HEADERS)
        assert r1.status_code == 200
        job_id = r1.json()["job"]["job_id"]
        update_job(job_id, status="done", decision="Заявка полная",
                   result={"decision": "Заявка полная", "email_html": ""})

        r2 = client.post("/api/v1/process/dzo", json=payload, headers=HEADERS)
        assert r2.status_code == 200
        data = r2.json()
        assert data["duplicate"] is True
        assert data["existing_job_id"] == job_id
        assert data["job"]["job_id"] == job_id

        jobs_resp = client.get("/api/v1/jobs", headers=HEADERS)
        assert jobs_resp.json()["total"] == 1

    def test_check_duplicate_reflects_done_job(self, client):
        from shared.database import update_job

        payload = {"text": "ТЗ", "sender_email": "tz@co.ru", "subject": "Поставка серверов"}
        r = client.post("/api/v1/process/tz", json=payload, headers=HEADERS)
        job_id = r.json()["job"]["job_id"]
        update_job(job_id, status="done", decision="Соответствует",
                   result={"decision": "Соответствует", "email_html": ""})

        resp = client.get(
            "/api/v1/check-duplicate",
            params={"agent": "tz", "sender": "tz@co.ru", "subject": "Поставка серверов"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["duplicate"] is True
        assert data["existing_job_id"] == job_id

    def test_force_creates_new_job_despite_duplicate(self, client):
        from shared.database import update_job

        payload = {"text": "Заявка", "sender_email": "f@g.com", "subject": "Форс-тест"}

        r1 = client.post("/api/v1/process/dzo", json=payload, headers=HEADERS)
        job_id_1 = r1.json()["job"]["job_id"]
        update_job(job_id_1, status="done", decision="Заявка полная",
                   result={"decision": "Заявка полная", "email_html": ""})

        r2 = client.post(
            "/api/v1/process/dzo",
            json={**payload, "force": True},
            headers=HEADERS,
        )
        assert r2.status_code == 200
        data = r2.json()
        assert data["duplicate"] is False
        job_id_2 = data["job"]["job_id"]
        assert job_id_2 != job_id_1

        jobs_resp = client.get("/api/v1/jobs", headers=HEADERS)
        assert jobs_resp.json()["total"] == 2

    def test_dedup_isolated_by_agent_type(self, client):
        from shared.database import update_job

        payload = {"text": "Документ", "sender_email": "iso@test.ru", "subject": "Общая тема"}

        r_dzo = client.post("/api/v1/process/dzo", json=payload, headers=HEADERS)
        job_id_dzo = r_dzo.json()["job"]["job_id"]
        update_job(job_id_dzo, status="done", decision="Заявка полная",
                   result={"decision": "Заявка полная", "email_html": ""})

        r_tz = client.post("/api/v1/process/tz", json=payload, headers=HEADERS)
        assert r_tz.status_code == 200
        data = r_tz.json()
        assert data["duplicate"] is False
        assert data["job"]["agent"] == "tz"
