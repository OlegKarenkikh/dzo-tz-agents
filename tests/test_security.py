"""
Тесты безопасности API — по результатам аудита.
Проверяют: CORS, API key, metrics endpoint, error masking.
"""
import os
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("API_KEY", "test-secret")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:8501")

from api.app import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


# ─── CORS ───────────────────────────────────────────────────────────
class TestCORS:
    def test_allowed_origin_returns_cors_header(self):
        resp = client.get("/health", headers={"Origin": "http://localhost:8501"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:8501"

    def test_disallowed_origin_no_cors_header(self):
        resp = client.get("/health", headers={"Origin": "https://evil.com"})
        # Нет заголовка ACAO — значит браузер заблокирует запрос
        assert "access-control-allow-origin" not in resp.headers

    def test_wildcard_not_used(self):
        resp = client.get("/health", headers={"Origin": "http://localhost:8501"})
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao != "*", "Нельзя использовать wildcard CORS"

    def test_preflight_allowed_methods(self):
        resp = client.options(
            "/api/v1/process/dzo",
            headers={
                "Origin": "http://localhost:8501",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key",
            },
        )
        allowed = resp.headers.get("access-control-allow-methods", "")
        # PATCH и PUT не должны быть разрешены
        assert "PATCH" not in allowed
        assert "PUT" not in allowed


# ─── API Key auth ───────────────────────────────────────────────
class TestAPIKeyAuth:
    def test_no_key_returns_401(self):
        resp = client.get("/api/v1/jobs")
        assert resp.status_code == 401

    def test_wrong_key_returns_401(self):
        resp = client.get("/api/v1/jobs", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_correct_key_returns_200(self):
        resp = client.get("/api/v1/jobs", headers={"X-API-Key": "test-secret"})
        assert resp.status_code == 200

    def test_public_endpoints_no_key_needed(self):
        for path in ["/health", "/agents", "/status"]:
            resp = client.get(path)
            assert resp.status_code == 200, f"{path} должен быть публичным"

    def test_process_endpoints_require_key(self):
        for path in ["/api/v1/process/dzo", "/api/v1/process/tz", "/api/v1/process/auto"]:
            resp = client.post(path, json={"text": "test"})
            assert resp.status_code == 401, f"{path} должен требовать ключ"

    def test_delete_requires_key(self):
        resp = client.delete("/api/v1/jobs/fake-id")
        assert resp.status_code == 401


# ─── Error masking ──────────────────────────────────────────────
class TestErrorMasking:
    def test_404_does_not_leak_internals(self):
        resp = client.get(
            "/api/v1/jobs/nonexistent-id",
            headers={"X-API-Key": "test-secret"},
        )
        assert resp.status_code == 404
        body = resp.text
        # Стек-трейс не должен просочиться
        assert "Traceback" not in body
        assert "psycopg2" not in body

    def test_500_does_not_expose_exception(self):
        # Imitate broken request body
        resp = client.post(
            "/api/v1/process/dzo",
            headers={"X-API-Key": "test-secret", "Content-Type": "application/json"},
            content=b"{invalid json",
        )
        assert resp.status_code in (422, 500)
        body = resp.text
        assert "Traceback" not in body


# ─── Metrics endpoint ────────────────────────────────────────────
class TestMetrics:
    def test_metrics_endpoint_accessible(self):
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type(self):
        resp = client.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]

    def test_metrics_contains_expected_names(self):
        resp = client.get("/metrics")
        body = resp.text
        for metric in [
            "dzo_tz_api_requests_total",
            "dzo_tz_api_latency_seconds",
        ]:
            assert metric in body, f"Метрика {metric} отсутствует"

    def test_metrics_not_counted_in_api_requests(self):
        """Запросы к /metrics не должны попадать в dzo_tz_api_requests_total."""
        client.get("/metrics")
        resp = client.get("/metrics")
        body = resp.text
        # Проверяем что путь /metrics не записан в метрике запросов
        assert 'endpoint="/metrics"' not in body


# ─── Health endpoint ────────────────────────────────────────────
class TestHealth:
    def test_health_returns_ok(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_health_contains_required_fields(self):
        data = client.get("/health").json()
        for field in ["status", "uptime_sec", "version", "timestamp"]:
            assert field in data

    def test_health_no_sensitive_data(self):
        body = client.get("/health").text
        # API ключ не должен утекаться
        assert "test-secret" not in body
        assert "OPENAI" not in body
