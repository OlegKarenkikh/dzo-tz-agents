"""Unit-тесты для shared/llm.py — проверка фабрики LLM и приоритета API-ключей."""

import importlib
from unittest.mock import MagicMock, patch

import pytest


class TestGithubModelsApiKeyPriority:
    """Проверяет приоритет API-ключей для LLM_BACKEND=github_models."""

    def _build_with_env(self, monkeypatch, env: dict) -> dict:
        """Перезагрузить config и shared.llm с env, вызвать build_llm и вернуть kwargs."""
        for k, v in env.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)

        # Мокируем load_dotenv, чтобы локальный .env не перезаписывал env-переменные
        with patch("config.load_dotenv"):
            import config
            import shared.llm as llm_module

            importlib.reload(config)
            importlib.reload(llm_module)

            captured: dict = {}

            def fake_chat(**kwargs):
                captured.update(kwargs)
                return MagicMock()

            with patch.object(llm_module, "ChatOpenAI", side_effect=fake_chat):
                llm_module.build_llm()

        return captured

    def test_openai_api_key_used_when_set(self, monkeypatch):
        """OPENAI_API_KEY имеет приоритет над GITHUB_TOKEN."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "github_models",
            "OPENAI_API_KEY": "ghp_explicit_pat",
            "GITHUB_TOKEN": None,
            "GH_TOKEN": None,
        })
        assert kwargs.get("api_key") == "ghp_explicit_pat"
        assert kwargs.get("base_url") == "https://models.inference.ai.azure.com"

    def test_github_token_used_as_fallback(self, monkeypatch):
        """Если OPENAI_API_KEY не задан — используется GITHUB_TOKEN."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "github_models",
            "OPENAI_API_KEY": None,
            "GITHUB_TOKEN": "ghs_session_token",
            "GH_TOKEN": None,
        })
        assert kwargs.get("api_key") == "ghs_session_token"
        assert kwargs.get("base_url") == "https://models.inference.ai.azure.com"

    def test_gh_token_used_as_fallback(self, monkeypatch):
        """Если OPENAI_API_KEY и GITHUB_TOKEN не заданы — используется GH_TOKEN."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "github_models",
            "OPENAI_API_KEY": None,
            "GITHUB_TOKEN": None,
            "GH_TOKEN": "ghs_gh_token",
        })
        assert kwargs.get("api_key") == "ghs_gh_token"

    def test_no_token_raises_value_error(self, monkeypatch):
        """Если ни один токен не задан — выбрасывается ValueError с понятным сообщением."""
        for k, v in {
            "LLM_BACKEND": "github_models",
            "OPENAI_API_KEY": None,
            "GITHUB_TOKEN": None,
            "GH_TOKEN": None,
        }.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)

        with patch("config.load_dotenv"):
            import config
            import shared.llm as llm_module

            importlib.reload(config)
            importlib.reload(llm_module)

            with pytest.raises(ValueError, match="GITHUB_TOKEN"):
                llm_module.build_llm()

    def test_endpoint_always_github_models(self, monkeypatch):
        """При github_models endpoint всегда https://models.inference.ai.azure.com,
        даже если задан OPENAI_API_BASE."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "github_models",
            "OPENAI_API_KEY": "ghp_pat",
            "OPENAI_API_BASE": "http://custom.endpoint/v1",
            "GITHUB_TOKEN": None,
            "GH_TOKEN": None,
        })
        assert kwargs.get("base_url") == "https://models.inference.ai.azure.com"

    def test_openai_backend_uses_openai_api_key(self, monkeypatch):
        """Обычный openai-бэкенд использует OPENAI_API_KEY."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "openai",
            "OPENAI_API_KEY": "sk-regular",
            "OPENAI_API_BASE": None,
            "GITHUB_TOKEN": None,
            "GH_TOKEN": None,
        })
        assert kwargs.get("api_key") == "sk-regular"
        assert kwargs.get("base_url") is None


class TestGithubTokenInConfig:
    """Проверяет, что config.py корректно читает GITHUB_TOKEN / GH_TOKEN."""

    def test_github_token_read(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_config_test")
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with patch("config.load_dotenv"):
            import config

            importlib.reload(config)
        assert config.GITHUB_TOKEN == "ghs_config_test"

    def test_gh_token_fallback(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "ghs_gh_fallback")
        with patch("config.load_dotenv"):
            import config

            importlib.reload(config)
        assert config.GITHUB_TOKEN == "ghs_gh_fallback"

    def test_github_token_none_when_absent(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with patch("config.load_dotenv"):
            import config

            importlib.reload(config)
        assert config.GITHUB_TOKEN is None
