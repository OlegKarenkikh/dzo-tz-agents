"""Unit-тесты для ui/config.py — проверка чтения переменных окружения."""

import importlib
import os

import pytest


def _reload_config(env: dict):
    """Перезагрузить ui.config с заданными переменными окружения."""
    with pytest.MonkeyPatch().context() as mp:
        for k, v in env.items():
            mp.setenv(k, v)
        import ui.config as cfg
        importlib.reload(cfg)
        return cfg


class TestApiUrl:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("UI_API_URL", raising=False)
        import ui.config as cfg
        importlib.reload(cfg)
        assert cfg.API_URL == "http://localhost:8000"

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("UI_API_URL", "http://api.internal:9000")
        import ui.config as cfg
        importlib.reload(cfg)
        assert cfg.API_URL == "http://api.internal:9000"


class TestApiKey:
    def test_empty_by_default(self, monkeypatch):
        # reload() заново импортирует load_dotenv; патчим модуль dotenv, а не ui.config.
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
        monkeypatch.delenv("UI_API_KEY", raising=False)
        monkeypatch.delenv("API_KEY", raising=False)
        import ui.config as cfg
        importlib.reload(cfg)
        assert cfg.API_KEY == ""
        assert cfg.AUTH_HEADERS == {}

    def test_ui_api_key_takes_priority(self, monkeypatch):
        monkeypatch.setenv("UI_API_KEY", "ui-key")
        monkeypatch.setenv("API_KEY", "fallback-key")
        import ui.config as cfg
        importlib.reload(cfg)
        assert cfg.API_KEY == "ui-key"
        assert cfg.AUTH_HEADERS == {"X-API-Key": "ui-key"}

    def test_fallback_to_api_key(self, monkeypatch):
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
        monkeypatch.delenv("UI_API_KEY", raising=False)
        monkeypatch.setenv("API_KEY", "fallback-key")
        import ui.config as cfg
        importlib.reload(cfg)
        assert cfg.API_KEY == "fallback-key"
        assert cfg.AUTH_HEADERS == {"X-API-Key": "fallback-key"}

    def test_auth_headers_populated(self, monkeypatch):
        monkeypatch.setenv("UI_API_KEY", "secret-123")
        import ui.config as cfg
        importlib.reload(cfg)
        assert "X-API-Key" in cfg.AUTH_HEADERS
        assert cfg.AUTH_HEADERS["X-API-Key"] == "secret-123"


class TestAutoRefreshSec:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("UI_AUTO_REFRESH_SEC", raising=False)
        import ui.config as cfg
        importlib.reload(cfg)
        assert cfg.AUTO_REFRESH_SEC == 30

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("UI_AUTO_REFRESH_SEC", "60")
        import ui.config as cfg
        importlib.reload(cfg)
        assert cfg.AUTO_REFRESH_SEC == 60

    def test_type_is_int(self, monkeypatch):
        monkeypatch.setenv("UI_AUTO_REFRESH_SEC", "120")
        import ui.config as cfg
        importlib.reload(cfg)
        assert isinstance(cfg.AUTO_REFRESH_SEC, int)


class TestLlmBackend:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("LLM_BACKEND", raising=False)
        import ui.config as cfg
        importlib.reload(cfg)
        assert cfg.LLM_BACKEND == "openai"

    @pytest.mark.parametrize("backend", ["openai", "ollama", "deepseek", "vllm", "lmstudio", "custom"])
    def test_known_backends(self, monkeypatch, backend):
        monkeypatch.setenv("LLM_BACKEND", backend)
        import ui.config as cfg
        importlib.reload(cfg)
        assert cfg.LLM_BACKEND == backend


class TestForceReprocess:
    def test_default_false(self, monkeypatch):
        monkeypatch.delenv("FORCE_REPROCESS", raising=False)
        import ui.config as cfg
        importlib.reload(cfg)
        assert cfg.FORCE_REPROCESS is False

    def test_true(self, monkeypatch):
        monkeypatch.setenv("FORCE_REPROCESS", "true")
        import ui.config as cfg
        importlib.reload(cfg)
        assert cfg.FORCE_REPROCESS is True

    def test_false_explicit(self, monkeypatch):
        monkeypatch.setenv("FORCE_REPROCESS", "false")
        import ui.config as cfg
        importlib.reload(cfg)
        assert cfg.FORCE_REPROCESS is False

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("FORCE_REPROCESS", "TRUE")
        import ui.config as cfg
        importlib.reload(cfg)
        assert cfg.FORCE_REPROCESS is True

    def test_type_is_bool(self, monkeypatch):
        monkeypatch.setenv("FORCE_REPROCESS", "false")
        import ui.config as cfg
        importlib.reload(cfg)
        assert isinstance(cfg.FORCE_REPROCESS, bool)
