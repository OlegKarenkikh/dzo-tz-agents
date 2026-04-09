"""Unit-тесты для shared/llm.py — проверка фабрики LLM и приоритета API-ключей."""

import importlib
from unittest.mock import MagicMock, patch

import pytest


class TestEstimateTokens:
    def test_ascii_estimate(self):
        import shared.llm as llm_module

        assert llm_module.estimate_tokens("x" * 40) == 10

    def test_cyrillic_is_more_conservative(self):
        import shared.llm as llm_module

        ascii_est = llm_module.estimate_tokens("x" * 20)
        cyr_est = llm_module.estimate_tokens("т" * 20)
        assert cyr_est > ascii_est
        assert cyr_est == 10

    def test_empty_text_minimum_one(self):
        import shared.llm as llm_module

        assert llm_module.estimate_tokens("") == 1


class TestGithubModelsApiKeyPriority:
    """Проверяет приоритет API-ключей для LLM_BACKEND=github_models."""

    def _build_with_env(self, monkeypatch, env: dict) -> dict:
        """Перезагрузить config и shared.llm с env, вызвать build_llm и вернуть kwargs."""
        for k, v in env.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)

        # Patch at source so the reload of config picks up the mock before re-executing from dotenv import load_dotenv
        with patch("dotenv.load_dotenv"):
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

    def test_github_token_takes_priority_over_openai_api_key(self, monkeypatch):
        """GITHUB_TOKEN имеет приоритет над OPENAI_API_KEY для github_models."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "github_models",
            "OPENAI_API_KEY": "sk-different-key",  # чужой ключ — должен быть проигнорирован
            "GITHUB_TOKEN": "ghu_github_token",
            "GH_TOKEN": None,
        })
        assert kwargs.get("api_key") == "ghu_github_token"
        assert kwargs.get("base_url") == "https://models.github.ai/inference"

    def test_openai_api_key_used_when_github_token_absent(self, monkeypatch):
        """Если GITHUB_TOKEN не задан — используется OPENAI_API_KEY как fallback."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "github_models",
            "OPENAI_API_KEY": "ghp_explicit_pat",
            "GITHUB_TOKEN": None,
            "GH_TOKEN": None,
        })
        assert kwargs.get("api_key") == "ghp_explicit_pat"
        assert kwargs.get("base_url") == "https://models.github.ai/inference"

    def test_github_token_used_when_set(self, monkeypatch):
        """GITHUB_TOKEN используется когда задан."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "github_models",
            "OPENAI_API_KEY": None,
            "GITHUB_TOKEN": "ghs_session_token",
            "GH_TOKEN": None,
        })
        assert kwargs.get("api_key") == "ghs_session_token"
        assert kwargs.get("base_url") == "https://models.github.ai/inference"

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

        with patch("dotenv.load_dotenv"):
            import config
            import shared.llm as llm_module

            importlib.reload(config)
            importlib.reload(llm_module)

            with pytest.raises(ValueError, match="GITHUB_TOKEN"):
                llm_module.build_llm()

    def test_endpoint_always_github_models(self, monkeypatch):
        """При github_models endpoint всегда https://models.github.ai/inference,
        даже если задан OPENAI_API_BASE."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "github_models",
            "OPENAI_API_KEY": "ghp_pat",
            "OPENAI_API_BASE": "http://custom.endpoint/v1",
            "GITHUB_TOKEN": None,
            "GH_TOKEN": None,
        })
        assert kwargs.get("base_url") == "https://models.github.ai/inference"

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


class TestBuildFallbackChain:
    """Проверяет build_fallback_chain для разных бэкендов."""

    def _reload_with_env(self, monkeypatch, env: dict):
        for k, v in env.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        with patch("dotenv.load_dotenv"):
            import config
            import shared.llm as llm_module
            importlib.reload(config)
            importlib.reload(llm_module)
        return llm_module

    def test_github_models_delegates_to_github_chain(self, monkeypatch):
        """github_models бэкенд использует build_github_fallback_chain."""
        llm_mod = self._reload_with_env(monkeypatch, {
            "LLM_BACKEND": "github_models",
            "OPENAI_API_KEY": "test-key",
            "GITHUB_TOKEN": None,
            "GH_TOKEN": None,
            "FALLBACK_MODELS": "",
        })
        with patch.object(llm_mod, "build_github_fallback_chain", return_value=["gpt-4o", "gpt-4o-mini"]) as mock_gh:
            chain = llm_mod.build_fallback_chain("gpt-4o")
            mock_gh.assert_called_once_with("test-key", "gpt-4o")
            assert chain == ["gpt-4o", "gpt-4o-mini"]

    def test_ollama_discovers_local_models(self, monkeypatch):
        """ollama бэкенд обнаруживает модели через API."""
        llm_mod = self._reload_with_env(monkeypatch, {
            "LLM_BACKEND": "ollama",
            "OPENAI_API_KEY": None,
            "OPENAI_API_BASE": "http://localhost:11434/v1",
            "FALLBACK_MODELS": "",
        })
        with patch.object(llm_mod, "fetch_local_models", return_value=["qwen2.5", "llama3.1", "mistral"]):
            chain = llm_mod.build_fallback_chain("qwen2.5")
            assert chain[0] == "qwen2.5"
            assert "llama3.1" in chain
            assert "mistral" in chain

    def test_ollama_explicit_fallback_models_first(self, monkeypatch):
        """FALLBACK_MODELS задан — автообнаружение пропускается, используются только явные модели."""
        llm_mod = self._reload_with_env(monkeypatch, {
            "LLM_BACKEND": "ollama",
            "OPENAI_API_KEY": None,
            "OPENAI_API_BASE": "http://localhost:11434/v1",
            "FALLBACK_MODELS": "mistral,codellama",
        })
        with patch.object(llm_mod, "fetch_local_models") as mock_fetch:
            chain = llm_mod.build_fallback_chain("qwen2.5")
            mock_fetch.assert_not_called()
            assert chain[0] == "qwen2.5"
            assert chain[1] == "mistral"
            assert chain[2] == "codellama"
            assert "llama3.1" not in chain

    def test_openai_no_fallback_single_model(self, monkeypatch):
        """openai без FALLBACK_MODELS — одна модель."""
        llm_mod = self._reload_with_env(monkeypatch, {
            "LLM_BACKEND": "openai",
            "OPENAI_API_KEY": "sk-test",
            "FALLBACK_MODELS": "",
        })
        chain = llm_mod.build_fallback_chain("gpt-4o")
        assert chain == ["gpt-4o"]

    def test_openai_with_explicit_fallback(self, monkeypatch):
        """openai с FALLBACK_MODELS — несколько моделей."""
        llm_mod = self._reload_with_env(monkeypatch, {
            "LLM_BACKEND": "openai",
            "OPENAI_API_KEY": "sk-test",
            "FALLBACK_MODELS": "gpt-4o-mini,gpt-3.5-turbo",
        })
        chain = llm_mod.build_fallback_chain("gpt-4o")
        assert chain == ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]

    def test_primary_not_duplicated(self, monkeypatch):
        """Основная модель не дублируется если она есть и в FALLBACK_MODELS."""
        llm_mod = self._reload_with_env(monkeypatch, {
            "LLM_BACKEND": "openai",
            "OPENAI_API_KEY": "sk-test",
            "FALLBACK_MODELS": "gpt-4o,gpt-4o-mini",
        })
        chain = llm_mod.build_fallback_chain("gpt-4o")
        assert chain.count("gpt-4o") == 1

    def test_github_models_not_needed_sentinel_falls_back_to_github_token(self, monkeypatch):
        """OPENAI_API_KEY='not-needed' sentinel должен игнорироваться для github_models,
        и API-ключ должен браться из GITHUB_TOKEN."""
        llm_mod = self._reload_with_env(monkeypatch, {
            "LLM_BACKEND": "github_models",
            "OPENAI_API_KEY": "not-needed",
            "GITHUB_TOKEN": "ghs_real_token",
            "GH_TOKEN": None,
            "FALLBACK_MODELS": "",
        })
        with patch.object(llm_mod, "build_github_fallback_chain", return_value=["gpt-4o"]) as mock_gh:
            llm_mod.build_fallback_chain("gpt-4o")
            # Sentinel must NOT be forwarded; real GITHUB_TOKEN must be used.
            mock_gh.assert_called_once_with("ghs_real_token", "gpt-4o")


class TestFetchLocalModels:
    """Проверяет обнаружение моделей через /v1/models."""

    def test_successful_fetch(self):
        import shared.llm as llm_module

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"id": "qwen2.5", "object": "model"},
                {"id": "llama3.1", "object": "model"},
            ]
        }
        with patch.object(llm_module, "_LOCAL_MODELS_CACHE", {}):
            with patch.object(llm_module.httpx, "get", return_value=mock_resp):
                models = llm_module.fetch_local_models("http://localhost:11434/v1")
        assert models == ["qwen2.5", "llama3.1"]

    def test_connection_error_returns_empty(self):
        import shared.llm as llm_module

        with patch.object(llm_module, "_LOCAL_MODELS_CACHE", {}):
            with patch.object(llm_module.httpx, "get", side_effect=Exception("Connection refused")):
                models = llm_module.fetch_local_models("http://localhost:11434/v1")
        assert models == []


class TestBuildLlmLocalBackend:
    """Проверяет build_llm для локальных бэкендов."""

    def _build_with_env(self, monkeypatch, env: dict) -> dict:
        for k, v in env.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)

        with patch("dotenv.load_dotenv"):
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

    def test_ollama_uses_default_base_url(self, monkeypatch):
        """Ollama без OPENAI_API_BASE использует localhost:11434."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "ollama",
            "OPENAI_API_KEY": None,
            "OPENAI_API_BASE": None,
            "MODEL_NAME": "qwen2.5",
            "FALLBACK_MODELS": "",
        })
        assert kwargs.get("base_url") == "http://localhost:11434/v1"
        assert kwargs.get("max_retries") == 0

    def test_vllm_uses_default_base_url(self, monkeypatch):
        """vLLM без OPENAI_API_BASE использует localhost:8000."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "vllm",
            "OPENAI_API_KEY": None,
            "OPENAI_API_BASE": None,
            "MODEL_NAME": "Qwen/Qwen2.5-72B-Instruct",
            "FALLBACK_MODELS": "",
        })
        assert kwargs.get("base_url") == "http://localhost:8000/v1"
        assert kwargs.get("max_retries") == 0

    def test_lmstudio_uses_default_base_url(self, monkeypatch):
        """LM Studio без OPENAI_API_BASE использует localhost:1234."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "lmstudio",
            "OPENAI_API_KEY": None,
            "OPENAI_API_BASE": None,
            "MODEL_NAME": "local-model",
            "FALLBACK_MODELS": "",
        })
        assert kwargs.get("base_url") == "http://localhost:1234/v1"
        assert kwargs.get("max_retries") == 0

    def test_ollama_custom_base_url(self, monkeypatch):
        """Ollama с OPENAI_API_BASE использует кастомный URL."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "ollama",
            "OPENAI_API_KEY": None,
            "OPENAI_API_BASE": "http://gpu-server:11434/v1",
            "MODEL_NAME": "qwen2.5",
            "FALLBACK_MODELS": "",
        })
        assert kwargs.get("base_url") == "http://gpu-server:11434/v1"

    def test_openai_with_fallback_disables_retries(self, monkeypatch):
        """OpenAI с FALLBACK_MODELS отключает SDK ретрай."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "openai",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_API_BASE": None,
            "FALLBACK_MODELS": "gpt-4o-mini",
        })
        assert kwargs.get("max_retries") == 0

    def test_openai_without_fallback_has_retries(self, monkeypatch):
        """OpenAI без FALLBACK_MODELS сохраняет SDK ретрай."""
        kwargs = self._build_with_env(monkeypatch, {
            "LLM_BACKEND": "openai",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_API_BASE": None,
            "FALLBACK_MODELS": "",
        })
        assert kwargs.get("max_retries") == 2


class TestProbeMaxInputTokens:
    def test_extracts_limit_from_context_length_phrase(self):
        import shared.llm as llm_module

        mock_resp = MagicMock()
        mock_resp.status_code = 413
        mock_resp.text = "This model's maximum context length is 8192 tokens"

        with patch.object(llm_module.httpx, "post", return_value=mock_resp):
            with patch.object(llm_module, "_MAX_INPUT_TOKENS_CACHE", {}):
                limit = llm_module.probe_max_input_tokens("k", "gpt-4o")

        assert limit == 8192

    def test_falls_back_to_conservative_default_when_unparsable(self):
        import shared.llm as llm_module

        mock_resp = MagicMock()
        mock_resp.status_code = 413
        mock_resp.text = "payload too large"

        with patch.object(llm_module.httpx, "post", return_value=mock_resp):
            with patch.object(llm_module, "_MAX_INPUT_TOKENS_CACHE", {}):
                limit = llm_module.probe_max_input_tokens("k", "unknown-model")

        assert limit == 8192


class TestGithubTokenInConfig:
    """Проверяет, что config.py корректно читает GITHUB_TOKEN / GH_TOKEN."""

    def test_github_token_read(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_config_test")
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with patch("dotenv.load_dotenv"):
            import config

            importlib.reload(config)
        assert config.GITHUB_TOKEN == "ghs_config_test"

    def test_gh_token_fallback(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "ghs_gh_fallback")
        with patch("dotenv.load_dotenv"):
            import config

            importlib.reload(config)
        assert config.GITHUB_TOKEN == "ghs_gh_fallback"

    def test_github_token_none_when_absent(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with patch("dotenv.load_dotenv"):
            import config

            importlib.reload(config)
        assert config.GITHUB_TOKEN is None
