"""Coverage boost for shared/llm.py — probe functions, backends, fallback chains.

conftest.py patches shared.llm.build_llm → MagicMock globally.
build_llm tests use a shadow-module approach: re-exec llm.py after setting
os.environ so that `from config import ...` reads correct values.
"""
import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
import shared.llm as _llm_mod


def _shadow_build_llm(env_overrides: dict, **kwargs):
    """Execute real build_llm in a fresh shadow module with given env."""
    with patch.dict(os.environ, env_overrides):
        # Also reload config so it re-reads env
        if "config" in sys.modules:
            _saved_config = sys.modules.pop("config")
        else:
            _saved_config = None
        try:
            spec = importlib.util.spec_from_file_location(
                "_llm_shadow_" + env_overrides.get("LLM_BACKEND", "x"),
                _llm_mod.__file__.replace(".pyc", ".py"),
            )
            shadow = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(shadow)
            return shadow.build_llm(**kwargs)
        finally:
            if _saved_config is not None:
                sys.modules["config"] = _saved_config


# ── _extract_max_tokens_from_error ─────────────────────────────────────────
class TestExtractMaxTokens:
    def test_max_size_pattern(self):
        assert _llm_mod._extract_max_tokens_from_error("Max size: 32768 tokens") == 32768

    def test_maximum_context_length_pattern(self):
        assert _llm_mod._extract_max_tokens_from_error(
            "This model's maximum context length is 4096 tokens"
        ) == 4096

    def test_at_most_pattern(self):
        assert _llm_mod._extract_max_tokens_from_error("at most 16384 input tokens") == 16384

    def test_input_limit_pattern(self):
        assert _llm_mod._extract_max_tokens_from_error("input limit: 8192 tokens") == 8192

    def test_returns_none_on_no_match(self):
        assert _llm_mod._extract_max_tokens_from_error("unknown error message") is None

    def test_handles_empty_string(self):
        assert _llm_mod._extract_max_tokens_from_error("") is None

    def test_case_insensitive(self):
        assert _llm_mod._extract_max_tokens_from_error(
            "MAXIMUM CONTEXT LENGTH IS 8192 TOKENS"
        ) == 8192


# ── probe_max_input_tokens ─────────────────────────────────────────────────
class TestProbeMaxInputTokens:
    def setup_method(self):
        _llm_mod._MAX_INPUT_TOKENS_CACHE.clear()

    def test_cache_hit(self):
        _llm_mod._MAX_INPUT_TOKENS_CACHE["cached-model"] = 99999
        assert _llm_mod.probe_max_input_tokens("key", "cached-model") == 99999

    def test_413_extracts_limit(self):
        r = MagicMock(status_code=413, text="at most 65536 tokens")
        with patch("shared.llm.httpx.post", return_value=r):
            assert _llm_mod.probe_max_input_tokens("key", "m413") == 65536

    def test_400_extracts_limit(self):
        r = MagicMock(status_code=400, text="maximum context length is 16384 tokens")
        with patch("shared.llm.httpx.post", return_value=r):
            assert _llm_mod.probe_max_input_tokens("key", "m400") == 16384

    def test_exception_uses_default(self):
        with patch("shared.llm.httpx.post", side_effect=Exception("timeout")):
            assert _llm_mod.probe_max_input_tokens("key", "merr") == _llm_mod._DEFAULT_GITHUB_MAX_INPUT_TOKENS

    def test_200_uses_default(self):
        r = MagicMock(status_code=200, text="ok")
        with patch("shared.llm.httpx.post", return_value=r):
            assert _llm_mod.probe_max_input_tokens("key", "m200") == _llm_mod._DEFAULT_GITHUB_MAX_INPUT_TOKENS

    def test_413_no_extractable_limit_uses_default(self):
        r = MagicMock(status_code=413, text="request too large, no count")
        with patch("shared.llm.httpx.post", return_value=r):
            assert _llm_mod.probe_max_input_tokens("key", "m413b") == _llm_mod._DEFAULT_GITHUB_MAX_INPUT_TOKENS


# ── probe_max_output_tokens ────────────────────────────────────────────────
class TestProbeMaxOutputTokens:
    def setup_method(self):
        _llm_mod._MAX_OUTPUT_TOKENS_CACHE.clear()

    def test_cache_hit(self):
        _llm_mod._MAX_OUTPUT_TOKENS_CACHE["out"] = 4096
        assert _llm_mod.probe_max_output_tokens("k", "out") == 4096

    def test_exception_returns_positive(self):
        with patch("shared.llm.httpx.post", side_effect=OSError("refused")):
            assert _llm_mod.probe_max_output_tokens("k", "oerr") > 0

    def test_200_returns_positive(self):
        r = MagicMock(status_code=200, text="input limit: 8192 tokens")
        with patch("shared.llm.httpx.post", return_value=r):
            assert _llm_mod.probe_max_output_tokens("k", "o200") > 0


# ── fetch_local_models ─────────────────────────────────────────────────────
class TestFetchLocalModels:
    def setup_method(self):
        _llm_mod._LOCAL_MODELS_CACHE.clear()

    def test_list_response(self):
        r = MagicMock(status_code=200)
        r.json.return_value = [{"id": "qwen3-32b"}, {"id": "llama3"}]
        with patch("shared.llm.httpx.get", return_value=r):
            ids = _llm_mod.fetch_local_models("http://localhost:11434/v1")
        assert "qwen3-32b" in ids and "llama3" in ids

    def test_data_key_response(self):
        r = MagicMock(status_code=200)
        r.json.return_value = {"data": [{"id": "mistral"}]}
        with patch("shared.llm.httpx.get", return_value=r):
            ids = _llm_mod.fetch_local_models("http://localhost:11435/v1")
        assert "mistral" in ids

    def test_exception_returns_empty(self):
        with patch("shared.llm.httpx.get", side_effect=Exception("no server")):
            assert _llm_mod.fetch_local_models("http://localhost:54321/v1") == []

    def test_result_is_cached(self):
        r = MagicMock(status_code=200)
        r.json.return_value = {"data": [{"id": "x"}]}
        with patch("shared.llm.httpx.get", return_value=r) as m:
            _llm_mod.fetch_local_models("http://localhost:7001/v1")
            _llm_mod.fetch_local_models("http://localhost:7001/v1")
        assert m.call_count == 1


# ── probe_local_max_context ────────────────────────────────────────────────
class TestProbeLocalMaxContext:
    def setup_method(self):
        _llm_mod._LOCAL_MODELS_CACHE.clear()
        _llm_mod._LOCAL_MAX_CTX_CACHE.clear()

    def test_cache_hit(self):
        _llm_mod._LOCAL_MAX_CTX_CACHE[("http://h:8000", "m")] = 131072
        assert _llm_mod.probe_local_max_context("http://h:8000", "m") == 131072

    def test_extracts_context_length(self):
        r = MagicMock(status_code=200)
        r.raise_for_status = MagicMock()
        r.json.return_value = {"data": [{"id": "ctx-m", "context_length": 32768}]}
        with patch("shared.llm.httpx.get", return_value=r):
            assert _llm_mod.probe_local_max_context("http://h:9001", "ctx-m") == 32768

    def test_max_model_len_field(self):
        r = MagicMock(status_code=200)
        r.raise_for_status = MagicMock()
        r.json.return_value = {"data": [{"id": "vm", "max_model_len": 65536}]}
        with patch("shared.llm.httpx.get", return_value=r):
            assert _llm_mod.probe_local_max_context("http://h:9003", "vm") == 65536

    def test_exception_returns_default(self):
        with patch("shared.llm.httpx.get", side_effect=Exception("no conn")):
            assert _llm_mod.probe_local_max_context("http://bad:1", "m") == _llm_mod._DEFAULT_MAX_INPUT_TOKENS

    def test_model_not_in_list_returns_default(self):
        r = MagicMock(status_code=200)
        r.raise_for_status = MagicMock()
        r.json.return_value = {"data": [{"id": "other", "context_length": 8192}]}
        with patch("shared.llm.httpx.get", return_value=r):
            assert _llm_mod.probe_local_max_context("http://h:9002", "unknown") == _llm_mod._DEFAULT_MAX_INPUT_TOKENS


# ── build_local_fallback_chain ─────────────────────────────────────────────
class TestBuildLocalFallbackChain:
    def test_primary_is_first(self):
        assert _llm_mod.build_local_fallback_chain("qwen3-32b")[0] == "qwen3-32b"

    def test_no_duplicates(self):
        c = _llm_mod.build_local_fallback_chain("qwen3-32b")
        assert len(c) == len(set(c))

    def test_fallback_appended(self, monkeypatch):
        monkeypatch.setattr(_llm_mod, "FALLBACK_MODELS", ["llama3", "mistral"])
        c = _llm_mod.build_local_fallback_chain("phi3")
        assert c[0] == "phi3" and "llama3" in c and "mistral" in c


# ── build_llm real — shadow module with env patch ─────────────────────────
class TestBuildLLMReal:
    _BASE_ENV = {
        "OPENAI_API_KEY": "sk-test-coverage-placeholder",
        "LLM_BACKEND": "qwen_proxy",
        "MODEL_NAME": "qwen3-32b",
        "OPENAI_API_BASE": "",
    }

    def test_qwen_proxy_model_name(self):
        llm = _shadow_build_llm({**self._BASE_ENV})
        assert llm.model_name == "qwen3-32b"

    def test_qwen_proxy_no_key_raises(self):
        env = {**self._BASE_ENV, "OPENAI_API_KEY": ""}
        with pytest.raises(ValueError, match="qwen_proxy"):
            _shadow_build_llm(env)

    def test_qwen_proxy_custom_base_url(self):
        env = {**self._BASE_ENV, "OPENAI_API_BASE": "https://custom.example.com/v1"}
        llm = _shadow_build_llm(env)
        assert "custom.example.com" in str(llm.openai_api_base)

    def test_qwen_proxy_zero_retries(self):
        llm = _shadow_build_llm({**self._BASE_ENV})
        assert llm.max_retries == 0

    def test_model_name_override(self):
        llm = _shadow_build_llm({**self._BASE_ENV}, model_name_override="qwen3-coder")
        assert llm.model_name == "qwen3-coder"

    def test_openai_no_key_raises(self):
        env = {"OPENAI_API_KEY": "", "LLM_BACKEND": "openai", "MODEL_NAME": "gpt-4o",
               "OPENAI_API_BASE": "", "GITHUB_TOKEN": ""}
        with pytest.raises(ValueError, match="openai"):
            _shadow_build_llm(env)

    def test_deepseek_backend(self):
        env = {"OPENAI_API_KEY": "ds-key", "LLM_BACKEND": "deepseek",
               "MODEL_NAME": "deepseek-chat",
               "OPENAI_API_BASE": "https://api.deepseek.com/v1",
               "FALLBACK_MODELS": ""}
        llm = _shadow_build_llm(env)
        assert llm.model_name == "deepseek-chat"

    def test_ollama_backend(self):
        env = {"OPENAI_API_KEY": "not-needed", "LLM_BACKEND": "ollama",
               "MODEL_NAME": "qwen3-32b",
               "OPENAI_API_BASE": "http://localhost:11434/v1"}
        llm = _shadow_build_llm(env)
        assert llm.model_name == "qwen3-32b"

    def test_temperature_applied(self):
        llm = _shadow_build_llm({**self._BASE_ENV}, temperature=0.7)
        assert llm.temperature == 0.7
