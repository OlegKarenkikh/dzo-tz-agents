"""
Тесты FastAPI REST API (api/app.py).
Используется TestClient из fastapi.testclient.
"""
import os

import pytest
from fastapi.testclient import TestClient

# Задаём API-ключ до импорта приложения
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ["API_KEY"] = "test-key-12345"

from api.app import app  # noqa: E402
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


HEADERS = {"X-API-Key": "test-key-12345"}


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


class TestProcessDzo:
    def test_process_dzo_returns_job_id(self, client):
        resp = client.post(
            "/api/v1/process/dzo",
            json={"text": "Заявка на закупку оборудования", "subject": "Тест"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["agent"] == "dzo"
        assert data["status"] in ("pending", "running", "done")

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
        assert "job_id" in data
        assert data["agent"] == "tz"

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
        assert resp.json()["agent"] == "tz"

    def test_auto_defaults_to_dzo(self, client):
        resp = client.post(
            "/api/v1/process/auto",
            json={"text": "Заявка на закупку", "subject": "Тест"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["agent"] == "dzo"


class TestJobs:
    def test_get_nonexistent_job_returns_404(self, client):
        resp = client.get("/api/v1/jobs/nonexistent-uuid", headers=HEADERS)
        assert resp.status_code == 404

    def test_list_jobs_empty(self, client):
        resp = client.get("/api/v1/jobs", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["jobs"] == []

    def test_list_jobs_after_create(self, client):
        client.post("/api/v1/process/dzo", json={"text": "Тест"}, headers=HEADERS)
        resp = client.get("/api/v1/jobs", headers=HEADERS)
        assert resp.json()["total"] == 1

    def test_get_job_after_create(self, client):
        create_resp = client.post("/api/v1/process/dzo", json={"text": "Тест"}, headers=HEADERS)
        job_id = create_resp.json()["job_id"]
        resp = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["job_id"] == job_id

    def test_delete_job(self, client):
        create_resp = client.post("/api/v1/process/dzo", json={"text": "Тест"}, headers=HEADERS)
        job_id = create_resp.json()["job_id"]
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
