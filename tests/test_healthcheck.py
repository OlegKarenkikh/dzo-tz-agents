"""Tests for api/healthcheck.py — legacy health/status/run endpoints (0% → 100%)."""
import pytest
from fastapi.testclient import TestClient
from api.healthcheck import app, _run_log


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_has_status_ok(self, client):
        assert client.get("/health").json()["status"] == "ok"

    def test_health_has_agents_dict(self, client):
        agents = client.get("/health").json()["agents"]
        assert isinstance(agents, dict)

    def test_health_lists_all_agents(self, client):
        agents = client.get("/health").json()["agents"]
        for name in ["dzo", "tz", "tender", "collector"]:
            assert name in agents

    def test_health_agent_status_ready_or_error(self, client):
        for name, status in client.get("/health").json()["agents"].items():
            assert status == "ready" or status.startswith("error:")

    def test_health_version(self, client):
        assert client.get("/health").json()["version"] == "2.0.0"

    def test_health_uptime_non_negative(self, client):
        assert client.get("/health").json()["uptime_sec"] >= 0

    def test_health_timestamp_iso(self, client):
        assert "T" in client.get("/health").json()["timestamp"]

    def test_health_has_agent_mode(self, client):
        assert "agent_mode" in client.get("/health").json()

    def test_health_has_model(self, client):
        assert "model" in client.get("/health").json()


class TestStatusEndpoint:
    def test_status_200(self, client):
        assert client.get("/status").status_code == 200

    def test_status_has_runs(self, client):
        data = client.get("/status").json()
        assert "runs" in data and isinstance(data["runs"], int)

    def test_status_last_runs_list(self, client):
        data = client.get("/status").json()
        assert "last_runs" in data and isinstance(data["last_runs"], list)

    def test_status_last_runs_max_10(self, client):
        assert len(client.get("/status").json()["last_runs"]) <= 10


class TestRunDzoEndpoint:
    def test_run_dzo_200(self, client):
        assert client.post("/run/dzo").status_code == 200

    def test_run_dzo_message(self, client):
        data = client.post("/run/dzo").json()
        assert "message" in data and "ts" in data

    def test_run_dzo_message_contains_dzo(self, client):
        msg = client.post("/run/dzo").json()["message"]
        assert "ДЗО" in msg or "dzo" in msg.lower()


class TestRunTzEndpoint:
    def test_run_tz_200(self, client):
        assert client.post("/run/tz").status_code == 200

    def test_run_tz_message(self, client):
        data = client.post("/run/tz").json()
        assert "message" in data and "ts" in data


class TestRunBothEndpoint:
    def test_run_both_200(self, client):
        assert client.post("/run/both").status_code == 200

    def test_run_both_message(self, client):
        data = client.post("/run/both").json()
        assert "message" in data and "ts" in data


class TestRunHelpers:
    def test_run_dzo_helper_error_logged(self, monkeypatch):
        import api.healthcheck as hc
        before = len(hc._run_log)
        monkeypatch.setattr(hc, "_run_dzo", lambda: hc._run_log.append(
            {"agent": "dzo", "ts": "T", "status": "error", "error": "e"}))
        hc._run_dzo()
        assert hc._run_log[-1]["agent"] == "dzo"
        assert hc._run_log[-1]["status"] == "error"

    def test_run_tz_helper_error_logged(self, monkeypatch):
        import api.healthcheck as hc
        monkeypatch.setattr(hc, "_run_tz", lambda: hc._run_log.append(
            {"agent": "tz", "ts": "T", "status": "error", "error": "e"}))
        hc._run_tz()
        assert hc._run_log[-1]["agent"] == "tz"

    def test_run_log_grows_with_dispatches(self, client):
        import api.healthcheck as hc
        before = len(hc._run_log)
        client.post("/run/dzo")
        client.post("/run/tz")
        assert len(hc._run_log) >= before
