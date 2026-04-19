Строк: 541
TTL functions present: True
probe_max_input patched: True
�я всех агентов.

Поддерживаемые бэкенды (LLM_BACKEND):
  openai        — OpenAI API (по умолчанию)
  ollama        — локальный Ollama
  deepseek      — DeepSeek API
  vllm          — vLLM (self-hosted)
  lmstudio      — LM Studio
  github_models — GitHub Models (https://models.github.ai/inference)
"""
import logging
import re
import json
import os
import threading
import time as _time
from pathlib import Path

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

_GITHUB_MODELS_BASE_URL = "https://models.github.ai/inference"

_GITHUB_MODELS_PRIORITY: list[str] = [
    "openai/gpt-4.1",
    "openai/gpt-4.1-mini",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
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

# TTL-кеш для probe_max_input_tokens / probe_max_output_tokens
# Хранит {model_name: {"value": int, "ts": float}} в файле и памяти
_TOKEN_LIMITS_TTL: int = 86_400  # 24 часа
_TOKEN_LIMITS_CACHE_FILE = Path(os.getenv("LLM_CACHE_DIR", "/tmp")) / "llm_token_limits.json"
_TOKEN_LIMITS_MEM: dict[str, dict] = {}


def _tlc_load_file() -> dict[str, dict]:
    """Загружает TTL-кеш из файла (вызывается под _llm_cache_lock)."""
    try:
        if _TOKEN_LIMITS_CACHE_FILE.exists():
            return json.loads(_TOKEN_LIMITS_CACHE_FILE.read_text())
    except Exception as exc:
        logger.warning("Не удалось прочитать TTL-кеш из %s: %s", _TOKEN_LIMITS_CACHE_FILE, exc)
    return {}


def _tlc_save_file(data: dict[str, dict]) -> None:
    """Сохраняет TTL-кеш в файл (вызывается под _llm_cache_lock)."""
    try:
        _TOKEN_LIMITS_CACHE_FILE.write_text(json.dumps(data))
    except Exception as exc:
        logger.warning("Не удалось сохранить TTL-кеш в %s: %s", _TOKEN_LIMITS_CACHE_FILE, exc)


def _tlc_get(model_name: str) -> int | None:
    """Возвращает кешированное значение или None если устарело/отсутствует."""
    now = _time.time()
    with _llm_cache_lock:
        entry = _TOKEN_LIMITS_MEM.get(model_name)
        if entry and now - entry["ts"] < _TOKEN_LIMITS_TTL:
            return entry["value"]
        # Пробуем файловый кеш
        file_data = _tlc_load_file()
        fentry = file_data.get(model_name)
        if fentry and now - fentry["ts"] < _TOKEN_LIMITS_TTL:
            _TOKEN_LIMITS_MEM[model_name] = fentry
            return fentry["value"]
    return None


def _tlc_set(model_name: str, value: int) -> None:
    """Сохраняет значение в память и файл с текущим timestamp."""
    now = _time.time()
    entry = {"value": value, "ts": now}
    with _llm_cache_lock:
        _TOKEN_LIMITS_MEM[model_name] = entry
        file_data = _tlc_load_file()
        file_data[model_name] = entry
        _tlc_save_file(file_data)


def estimate_tokens(text: str) -> int:
    """Консервативная оценка токенов для mixed ASCII/Unicode текста.

    Для кириллицы и иных non-ASCII символов плотность токенов обычно выше,
    чем 1 токен на 4 символа, поэтому считаем их как ~1 токен на 2 символа.
    """
    if not text:
        return 1
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii_chars = len(text) - ascii_chars
    est = (ascii_chars // 4) + (non_ascii_chars // 2)
    return max(1, est)


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
    """RC-03 + TTL-кеш: чтение из памяти/файла (24h), иначе HTTP-проб."""
    cached = _tlc_get(f"input:{model_name}")
    if cached is not None:
        return cached
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
                _tlc_set(f"input:{model_name}", limit)
                logger.info("📐 Модель %s: max_input_tokens = %d", model_name, limit)
                return limit
        elif resp.status_code == 400:
            limit = _extract_max_tokens_from_error(resp.text)
            if limit:
                with _llm_cache_lock:
                    _MAX_INPUT_TOKENS_CACHE[model_name] = limit
                _tlc_set(f"input:{model_name}", limit)
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


# ---------------------------------------------------------------------------
# Circuit Breaker — пропуск моделей с последовательными ошибками
# ---------------------------------------------------------------------------


class _CircuitBreaker:
    """Simple per-model circuit breaker.

    Tracks consecutive failures per model. If a model has failed
    ``threshold`` times in a row within ``window_sec``, it is considered
    "open" (unhealthy) and should be skipped in the fallback chain.

    Thread-safe via a lock.
    """

    def __init__(self, threshold: int = 3, window_sec: float = 120.0):
        self._threshold = threshold
        self._window = window_sec
        self._failures: dict[str, list[float]] = {}  # model → list of failure timestamps
        self._lock = threading.Lock()

    def record_failure(self, model: str) -> None:
        """Record a failure for the given model."""
        with self._lock:
            now = _time.monotonic()
            if model not in self._failures:
                self._failures[model] = []
            self._failures[model].append(now)
            # Keep only failures within the window
            cutoff = now - self._window
            self._failures[model] = [t for t in self._failures[model] if t > cutoff]

    def record_success(self, model: str) -> None:
        """Reset failure count on success."""
        with self._lock:
            self._failures.pop(model, None)

    def is_open(self, model: str) -> bool:
        """Check if the circuit is open (model should be skipped)."""
        with self._lock:
            failures = self._failures.get(model, [])
            if len(failures) < self._threshold:
                return False
            cutoff = _time.monotonic() - self._window
            recent = [t for t in failures if t > cutoff]
            return len(recent) >= self._threshold

    def filter_healthy(self, models: list[str]) -> list[str]:
        """Return only models whose circuit is closed (healthy)."""
        return [m for m in models if not self.is_open(m)]


# Global circuit breaker instance
llm_circuit_breaker = _CircuitBreaker(
    threshold=3,
    window_sec=120.0,
)


def build_fallback_chain(primary: str) -> list[str]:
    if LLM_BACKEND == "github_models":
        # Приоритет GITHUB_TOKEN → effective_openai_key() — совпадает с build_llm().
        api_key = GITHUB_TOKEN or effective_openai_key() or ""
        return build_github_fallback_chain(api_key, primary)
    if LLM_BACKEND in LOCAL_BACKENDS:
        return build_local_fallback_chain(primary)
    # openai / deepseek / any custom OpenAI-compatible endpoint
    chain: list[str] = [primary]
    for m in FALLBACK_MODELS:
        if m not in chain:
            chain.append(m)
    return chain


def build_llm(temperature: float = 0.0, model_name_override: str | None = None) -> ChatOpenAI:
    model = model_name_override or MODEL_NAME
    if LLM_BACKEND == "github_models":
        api_key = GITHUB_TOKEN or effective_openai_key()
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
    elif LLM_BACKEND == "qwen_proxy":
        # Собственный Qwen прокси (https://qwen-proxy-bdt6.onrender.com)
        # OpenAI-совместимый, поддерживает tool calling, модели: qwen3-32b, qwen-coder
        _QWEN_PROXY_BASE = "https://qwen-proxy-bdt6.onrender.com/v1"
        api_key = OPENAI_API_KEY
        if not api_key:
            raise ValueError(
                "Для LLM_BACKEND='qwen_proxy' необходимо задать OPENAI_API_KEY."
            )
        base_url = (OPENAI_API_BASE or _QWEN_PROXY_BASE).rstrip("/")
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

    from config import LLM_TEMPERATURE, LLM_SEED, LLM_TOP_P

    effective_temp = temperature if temperature != 0.0 else LLM_TEMPERATURE

    model_kwargs = {}
    if LLM_SEED is not None:
        model_kwargs["seed"] = LLM_SEED
    if LLM_TOP_P != 1.0:
        model_kwargs["top_p"] = LLM_TOP_P

    logger.info("🤖 Инициализация LLM: backend=%s, model=%s, max_tokens=%d",
                LLM_BACKEND, model, max_tokens_out)

    kwargs: dict = dict(
        model=model,
        temperature=effective_temp,
        max_tokens=max_tokens_out,
        api_key=api_key,
        base_url=base_url,
        max_retries=max_retries,
    )
    if model_kwargs:
        kwargs["model_kwargs"] = model_kwargs

    return ChatOpenAI(**kwargs)
