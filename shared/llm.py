"""LLM factory — единая точка создания ChatOpenAI для всех агентов.

Поддерживаемые бэкенды (LLM_BACKEND):
  openai        — OpenAI API (по умолчанию)
  ollama        — локальный Ollama
  deepseek      — DeepSeek API
  vllm          — vLLM (self-hosted)
  lmstudio      — LM Studio
  github_models — GitHub Models (https://models.inference.ai.azure.com)
"""
import logging
import re
import threading

import httpx
from langchain_openai import ChatOpenAI

from config import (
    FALLBACK_MODELS,
    GITHUB_TOKEN,
    LLM_BACKEND,
    MODEL_NAME,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
)

logger = logging.getLogger("llm")

_GITHUB_MODELS_BASE_URL = "https://models.inference.ai.azure.com"

_GITHUB_MODELS_PRIORITY: list[str] = [
    "gpt-4o-mini",
    "Meta-Llama-3.1-405B-Instruct",
    "gpt-4o",
    "Meta-Llama-3.1-8B-Instruct",
]

# RC-03 fix: единый RLock для всех 4 кешей — защищает от concurrent read-modify-write
_llm_cache_lock = threading.RLock()

_MAX_OUTPUT_TOKENS_CACHE: dict[str, int] = {}
_DEFAULT_MAX_OUTPUT_TOKENS = 4096

_MAX_INPUT_TOKENS_CACHE: dict[str, int] = {}
_DEFAULT_MAX_INPUT_TOKENS = 128_000
_DEFAULT_GITHUB_MAX_INPUT_TOKENS = 8_192

_LOCAL_MAX_CTX_CACHE: dict[tuple[str, str], int] = {}
_LOCAL_MODELS_CACHE: dict[str, list] = {}


def estimate_tokens(text: str) -> int:
    """Грубая оценка числа токенов (1 токен ≈ 4 символа)."""
    return max(1, len(text) // 4)


def _extract_max_tokens_from_error(error_text: str) -> int | None:
    """Пытается извлечь лимит токенов из текста ошибки провайдера."""
    patterns = [
        r"Max size[:\s]+(\d+)\s+tokens",
        r"maximum context length is\s*(\d+)\s*tokens",
        r"at most\s*(\d+)\s*(?:input\s*)?tokens",
        r"(?:input|context)\s*limit[:\s]+(\d+)\s*tokens",
    ]
    for p in patterns:
        m = re.search(p, error_text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except (TypeError, ValueError):
                continue
    return None


def probe_max_input_tokens(api_key: str, model_name: str) -> int:
    """RC-03: чтение и запись кеша под RLock."""
    with _llm_cache_lock:
        if model_name in _MAX_INPUT_TOKENS_CACHE:
            return _MAX_INPUT_TOKENS_CACHE[model_name]

    try:
        resp = httpx.post(
            f"{_GITHUB_MODELS_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_name,
                "messages": [{"role": "user", "content": "x" * 100_000}],
                "max_tokens": 1,
            },
            timeout=15,
        )
        if resp.status_code == 413:
            limit = _extract_max_tokens_from_error(resp.text)
            if limit:
                with _llm_cache_lock:
                    _MAX_INPUT_TOKENS_CACHE[model_name] = limit
                logger.info("📐 Модель %s: max_input_tokens = %d", model_name, limit)
                return limit
        elif resp.status_code == 400:
            limit = _extract_max_tokens_from_error(resp.text)
            if limit:
                with _llm_cache_lock:
                    _MAX_INPUT_TOKENS_CACHE[model_name] = limit
                logger.info("📐 Модель %s: max_input_tokens = %d (из 400)", model_name, limit)
                return limit
    except Exception as exc:
        logger.warning(
            "⚠️ Не удалось определить max_input_tokens для %s: %s. Используется %d (консервативно для GitHub Models).",
            model_name, exc, _DEFAULT_GITHUB_MAX_INPUT_TOKENS,
        )

    with _llm_cache_lock:
        return _MAX_INPUT_TOKENS_CACHE.setdefault(model_name, _DEFAULT_GITHUB_MAX_INPUT_TOKENS)


def probe_max_output_tokens(api_key: str, model_name: str) -> int:
    """RC-03: чтение и запись кеша под RLock."""
    with _llm_cache_lock:
        if model_name in _MAX_OUTPUT_TOKENS_CACHE:
            return _MAX_OUTPUT_TOKENS_CACHE[model_name]

    try:
        resp = httpx.post(
            f"{_GITHUB_MODELS_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_name,
                "messages": [{"role": "user", "content": "x"}],
                "max_tokens": 999_999,
            },
            timeout=10,
        )
        if resp.status_code == 400:
            m = re.search(r"at most (\d+) completion tokens", resp.text)
            if m:
                limit = int(m.group(1))
                with _llm_cache_lock:
                    _MAX_OUTPUT_TOKENS_CACHE[model_name] = limit
                logger.info("📐 Модель %s: max_output_tokens = %d", model_name, limit)
                return limit
            m2 = re.search(r"(\d{3,6})\s+completion tokens", resp.text)
            if m2:
                limit = int(m2.group(1))
                with _llm_cache_lock:
                    _MAX_OUTPUT_TOKENS_CACHE[model_name] = limit
                logger.info("📐 Модель %s: max_output_tokens = %d (паттерн 2)", model_name, limit)
                return limit
    except Exception as exc:
        logger.warning(
            "⚠️ Не удалось определить max_output_tokens для %s: %s. Используется %d.",
            model_name, exc, _DEFAULT_MAX_OUTPUT_TOKENS,
        )

    with _llm_cache_lock:
        return _MAX_OUTPUT_TOKENS_CACHE.setdefault(model_name, _DEFAULT_MAX_OUTPUT_TOKENS)


def fetch_github_chat_models(api_key: str) -> list[str]:
    try:
        resp = httpx.get(
            f"{_GITHUB_MODELS_BASE_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        models = data if isinstance(data, list) else data.get("data", data.get("models", []))
        return [
            m["name"]
            for m in models
            if m.get("task") == "chat-completion" and m.get("name")
        ]
    except Exception as exc:
        logger.warning(
            "Не удалось получить список GitHub Models: %s. Используется встроенный список.", exc
        )
        return _GITHUB_MODELS_PRIORITY[:]


def build_github_fallback_chain(api_key: str, primary: str) -> list[str]:
    available = set(fetch_github_chat_models(api_key))
    chain: list[str] = [primary]
    for m in _GITHUB_MODELS_PRIORITY:
        if m != primary and m in available:
            chain.append(m)
    for m in available:
        if m not in chain:
            chain.append(m)
    return chain


LOCAL_BACKENDS = {"ollama", "vllm", "lmstudio"}
_LOCAL_BACKENDS = LOCAL_BACKENDS


def resolve_local_base_url() -> str:
    if OPENAI_API_BASE:
        return OPENAI_API_BASE.rstrip("/")
    defaults = {
        "ollama": "http://localhost:11434/v1",
        "vllm": "http://localhost:8000/v1",
        "lmstudio": "http://localhost:1234/v1",
    }
    return defaults.get(LLM_BACKEND, "http://localhost:11434/v1")


_resolve_local_base_url = resolve_local_base_url


def _model_ids_from_raw(raw: list) -> list[str]:
    return [m.get("id") or m.get("name", "") for m in raw if m.get("id") or m.get("name")]


def fetch_local_models(base_url: str | None = None) -> list[str]:
    url = (base_url or resolve_local_base_url()).rstrip("/")
    # RC-03: чтение кеша под замком
    with _llm_cache_lock:
        if url in _LOCAL_MODELS_CACHE:
            try:
                return _model_ids_from_raw(_LOCAL_MODELS_CACHE[url])
            except Exception as exc:
                logger.warning("Некорректные данные в кеше моделей для %s, сброс: %s", url, exc)
                del _LOCAL_MODELS_CACHE[url]
    headers: dict[str, str] = {}
    if OPENAI_API_KEY and OPENAI_API_KEY != "not-needed":
        headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"
    try:
        resp = httpx.get(f"{url}/models", timeout=10, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        models = data if isinstance(data, list) else data.get("data", data.get("models", []))
        model_ids = _model_ids_from_raw(models)
        with _llm_cache_lock:
            _LOCAL_MODELS_CACHE[url] = models
        return model_ids
    except Exception as exc:
        logger.warning("Не удалось получить список локальных моделей от %s: %s", url, exc)
        return []


def probe_local_max_context(base_url: str, model_name: str) -> int:
    """RC-03: чтение/запись кеша под RLock."""
    normalized_url = base_url.rstrip("/")
    cache_key = (normalized_url, model_name)
    with _llm_cache_lock:
        if cache_key in _LOCAL_MAX_CTX_CACHE:
            return _LOCAL_MAX_CTX_CACHE[cache_key]

    try:
        with _llm_cache_lock:
            has_models_cache = normalized_url in _LOCAL_MODELS_CACHE

        if not has_models_cache:
            _auth_headers: dict[str, str] = {}
            if OPENAI_API_KEY and OPENAI_API_KEY != "not-needed":
                _auth_headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"
            resp = httpx.get(f"{normalized_url}/models", timeout=10, headers=_auth_headers)
            resp.raise_for_status()
            data = resp.json()
            models: list[dict] = []
            if isinstance(data, list):
                models = [m for m in data if isinstance(m, dict)]
            elif isinstance(data, dict):
                raw_models = data.get("data", data.get("models", []))
                if isinstance(raw_models, dict):
                    raw_iter = raw_models.values()
                else:
                    raw_iter = raw_models
                try:
                    models = [m for m in raw_iter if isinstance(m, dict)]
                except TypeError:
                    models = []
            with _llm_cache_lock:
                _LOCAL_MODELS_CACHE[normalized_url] = models

        with _llm_cache_lock:
            models_list = _LOCAL_MODELS_CACHE.get(normalized_url, [])

        if not isinstance(models_list, list):
            with _llm_cache_lock:
                _LOCAL_MODELS_CACHE.pop(normalized_url, None)
            raise TypeError("Cached /models payload is not a list")

        for m in models_list:
            if not isinstance(m, dict):
                continue
            mid = m.get("id") or m.get("name", "")
            if mid == model_name:
                ctx = (
                    m.get("context_length")
                    or m.get("max_model_len")
                    or m.get("details", {}).get("context_length")
                )
                if ctx and isinstance(ctx, int) and ctx > 0:
                    with _llm_cache_lock:
                        _LOCAL_MAX_CTX_CACHE[cache_key] = ctx
                    logger.info("📐 Локальная модель %s: context_length = %d", model_name, ctx)
                    return ctx
    except Exception as exc:
        logger.debug("Не удалось определить контекст для %s: %s", model_name, exc)

    with _llm_cache_lock:
        return _LOCAL_MAX_CTX_CACHE.setdefault(cache_key, _DEFAULT_MAX_INPUT_TOKENS)


def build_local_fallback_chain(primary: str, base_url: str | None = None) -> list[str]:
    chain: list[str] = [primary]
    for m in FALLBACK_MODELS:
        if m not in chain:
            chain.append(m)
    if not FALLBACK_MODELS:
        url = (base_url or resolve_local_base_url()).rstrip("/")
        available = fetch_local_models(url)
        for m in available:
            if m not in chain:
                chain.append(m)
    return chain


def effective_openai_key() -> str | None:
    return OPENAI_API_KEY if OPENAI_API_KEY and OPENAI_API_KEY != "not-needed" else None


_effective_openai_key = effective_openai_key


def build_fallback_chain(primary: str) -> list[str]:
    if LLM_BACKEND == "github_models":
        api_key = effective_openai_key() or GITHUB_TOKEN or ""
        return build_github_fallback_chain(api_key, primary)
    if LLM_BACKEND in LOCAL_BACKENDS:
        return build_local_fallback_chain(primary)
    chain: list[str] = [primary]
    for m in FALLBACK_MODELS:
        if m not in chain:
            chain.append(m)
    return chain


def build_llm(temperature: float = 0.2, model_name_override: str | None = None) -> ChatOpenAI:
    model = model_name_override or MODEL_NAME
    if LLM_BACKEND == "github_models":
        api_key = effective_openai_key() or GITHUB_TOKEN
        if not api_key:
            raise ValueError(
                "Для LLM_BACKEND='github_models' необходимо задать OPENAI_API_KEY "
                "или предоставить токен в переменной окружения GITHUB_TOKEN/GH_TOKEN."
            )
        base_url = _GITHUB_MODELS_BASE_URL
        max_retries = 0
        max_tokens_out = probe_max_output_tokens(api_key, model)
    elif LLM_BACKEND in LOCAL_BACKENDS:
        api_key = OPENAI_API_KEY or "not-needed"
        base_url = resolve_local_base_url()
        max_retries = 0
        max_tokens_out = 8192
    else:
        effective_key = effective_openai_key()
        if LLM_BACKEND == "openai" and not effective_key:
            raise ValueError(
                "Для LLM_BACKEND='openai' необходимо задать OPENAI_API_KEY."
            )
        api_key = effective_key
        base_url = OPENAI_API_BASE or None
        has_fallback = len(FALLBACK_MODELS) > 0
        max_retries = 0 if has_fallback else 2
        max_tokens_out = 8192

    logger.info("🤖 Инициализация LLM: backend=%s, model=%s, max_tokens=%d", LLM_BACKEND, model, max_tokens_out)
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens_out,
        api_key=api_key,
        base_url=base_url,
        max_retries=max_retries,
    )
