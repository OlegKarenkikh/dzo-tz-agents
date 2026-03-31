"""Фабрика LLM — единая точка создания ChatOpenAI для всех агентов.

Поддерживаемые бэкенды (LLM_BACKEND):
  openai        — OpenAI API (по умолчанию)
  ollama        — локальный Ollama
  deepseek      — DeepSeek API
  vllm          — vLLM (self-hosted)
  lmstudio      — LM Studio
  github_models — GitHub Models (https://models.inference.ai.azure.com)
                  Токен берётся из OPENAI_API_KEY, либо автоматически из
                  GITHUB_TOKEN / GH_TOKEN (доступен в GitHub Actions,
                  Copilot Workspace и Codespaces без дополнительной настройки).

Автопереключение моделей при 429/413:
  При RateLimitError (429) или превышении лимита токенов (413) агент
  автоматически переключается на следующую модель из fallback-цепочки.

  github_models:
    Встроенная цепочка: gpt-4o-mini → Meta-Llama-3.1-405B-Instruct → gpt-4o → ...
    Модели и лимиты актуализируются через GitHub Models API при старте.

  ollama / vllm / lmstudio:
    Доступные модели обнаруживаются автоматически через /v1/models.
    Можно задать явный порядок через FALLBACK_MODELS в .env.

  openai / deepseek:
    Fallback только при явно заданном FALLBACK_MODELS в .env.
"""
import logging
import re

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

# Endpoint GitHub Models фиксирован и не переопределяется через OPENAI_API_BASE
_GITHUB_MODELS_BASE_URL = "https://models.inference.ai.azure.com"

# Приоритетный порядок fallback-моделей GitHub Models.
# Llama-3.1-405B имеет мягкие rate limits; Llama-3.1-8B идёт последней — её суммарный
# контекст составляет всего 8 000 токенов, что меньше большинства входящих документов.
_GITHUB_MODELS_PRIORITY: list[str] = [
    "gpt-4o-mini",
    "Meta-Llama-3.1-405B-Instruct",
    "gpt-4o",
    "Meta-Llama-3.1-8B-Instruct",  # последней: 8 000 токенов суммарного контекста
]

# Кеш max_output_tokens, заполняется при первом запросе к каждой модели.
# Хранится на весь срок жизни процесса — перезапрос не нужен.
_MAX_OUTPUT_TOKENS_CACHE: dict[str, int] = {}

# Fallback, если зондирование output-токенов не удалось
_DEFAULT_MAX_OUTPUT_TOKENS = 4096

# Кеш максимального доступного INPUT-контекста (input tokens)
_MAX_INPUT_TOKENS_CACHE: dict[str, int] = {}

# Fallback, если зондирование input-контекста не удалось
_DEFAULT_MAX_INPUT_TOKENS = 128_000

# Отдельный кеш для локальных бэкендов: ключ (base_url, model_name)
# чтобы избежать коллизий при совпадении имён моделей между бэкендами
_LOCAL_MAX_CTX_CACHE: dict[tuple[str, str], int] = {}

# Кеш списка моделей для локальных бэкендов: ключ — нормализованный base_url.
# Заполняется при первом обращении к probe_local_max_context для данного хоста,
# чтобы не делать N HTTP-запросов при оценке N моделей из fallback-цепочки.
_LOCAL_MODELS_CACHE: dict[str, list] = {}


def estimate_tokens(text: str) -> int:
    """Грубая оценка числа токенов в строке (1 токен ≈ 4 символа)."""
    return max(1, len(text) // 4)


def probe_max_input_tokens(api_key: str, model_name: str) -> int:
    """Определить суммарный лимит входных токенов модели через 413-ответ API.

    Отправляет намеренно большое сообщение (~100 000 символов), чтобы получить
    ошибку 413 вида «Request body too large … Max size: N tokens». Результат
    кешируется в ``_MAX_INPUT_TOKENS_CACHE``.

    Args:
        api_key:    Bearer-токен для GitHub Models API.
        model_name: Имя модели.

    Returns:
        Максимально допустимое число входных токенов для данной модели.
    """
    if model_name in _MAX_INPUT_TOKENS_CACHE:
        return _MAX_INPUT_TOKENS_CACHE[model_name]

    try:
        # ~100 000 символов ≈ 25 000 токенов — гарантированно превышает
        # лимит Llama-3.1-8B (8 000) и других малоконтекстных моделей.
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
            # «Request body too large for meta-llama-3.1-8b-instruct model. Max size: 8000 tokens.»
            m = re.search(r"Max size[:\s]+(\d+)\s+tokens", resp.text, re.IGNORECASE)
            if m:
                limit = int(m.group(1))
                _MAX_INPUT_TOKENS_CACHE[model_name] = limit
                logger.info(
                    "📐 Модель %s: max_input_tokens = %d (из 413 ответа API)",
                    model_name, limit,
                )
                return limit
        # 200 / другой код — модель приняла 100k, у неё большой контекст
    except Exception as exc:
        logger.warning(
            "⚠️ Не удалось определить max_input_tokens для %s: %s. "
            "Используется значение по умолчанию %d.",
            model_name, exc, _DEFAULT_MAX_INPUT_TOKENS,
        )

    _MAX_INPUT_TOKENS_CACHE[model_name] = _DEFAULT_MAX_INPUT_TOKENS
    return _DEFAULT_MAX_INPUT_TOKENS


def probe_max_output_tokens(api_key: str, model_name: str) -> int:
    """Определить реальный лимит output-токенов модели через API.

    Отправляет запрос с намеренно завышенным ``max_tokens=999999``.
    GitHub Models / Azure AI Inference API возвращает ошибку 400 с текстом
    вида «This model supports at most N completion tokens» — парсим N.

    Результат кешируется в ``_MAX_OUTPUT_TOKENS_CACHE`` на весь срок жизни
    процесса, поэтому повторных запросов не происходит.

    Args:
        api_key:    Bearer-токен для GitHub Models API.
        model_name: Имя модели (например ``"gpt-4o-mini"``).

    Returns:
        Максимальное число output-токенов для данной модели.
    """
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
            # "max_tokens is too large: 999999.
            #  This model supports at most 16384 completion tokens, whereas you provided 999999."
            m = re.search(r"at most (\d+) completion tokens", resp.text)
            if m:
                limit = int(m.group(1))
                _MAX_OUTPUT_TOKENS_CACHE[model_name] = limit
                logger.info(
                    "📐 Модель %s: max_output_tokens = %d (из ответа API)",
                    model_name, limit,
                )
                return limit
            # API изменил формат ошибки — пробуем другой паттерн
            m2 = re.search(r"(\d{3,6})\s+completion tokens", resp.text)
            if m2:
                limit = int(m2.group(1))
                _MAX_OUTPUT_TOKENS_CACHE[model_name] = limit
                logger.info(
                    "📐 Модель %s: max_output_tokens = %d (из ответа API, паттерн 2)",
                    model_name, limit,
                )
                return limit
    except Exception as exc:
        logger.warning(
            "⚠️ Не удалось определить max_output_tokens для %s: %s. "
            "Используется значение по умолчанию %d.",
            model_name, exc, _DEFAULT_MAX_OUTPUT_TOKENS,
        )

    _MAX_OUTPUT_TOKENS_CACHE[model_name] = _DEFAULT_MAX_OUTPUT_TOKENS
    return _DEFAULT_MAX_OUTPUT_TOKENS


def fetch_github_chat_models(api_key: str) -> list[str]:
    """Получить список chat-completion моделей из GitHub Models API.

    При недоступности API возвращает встроенный приоритетный список.

    Args:
        api_key: Bearer-токен для GitHub Models API.

    Returns:
        Список имён моделей (поле ``name``).
    """
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
    """Построить упорядоченную цепочку fallback-моделей.

    Primary-модель всегда идёт первой. Остальные — в порядке
    `_GITHUB_MODELS_PRIORITY`, затем все прочие доступные.

    Args:
        api_key: Bearer-токен для GitHub Models API.
        primary: Имя основной модели.

    Returns:
        Упорядоченный список имён моделей для последовательного перебора.
    """
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
# Backward-compatible private alias
_LOCAL_BACKENDS = LOCAL_BACKENDS


def resolve_local_base_url() -> str:
    """Return base URL for the local backend, falling back to common defaults.

    The returned URL is normalized to have no trailing slash.
    """
    if OPENAI_API_BASE:
        return OPENAI_API_BASE.rstrip("/")
    defaults = {
        "ollama": "http://localhost:11434/v1",
        "vllm": "http://localhost:8000/v1",
        "lmstudio": "http://localhost:1234/v1",
    }
    return defaults.get(LLM_BACKEND, "http://localhost:11434/v1")


# Backward-compatible private alias
_resolve_local_base_url = resolve_local_base_url


def fetch_local_models(base_url: str | None = None) -> list[str]:
    """Fetch available model names from a local OpenAI-compatible /v1/models endpoint.

    Args:
        base_url: The base URL of the local server (e.g. ``http://localhost:11434/v1``).
                  If None, resolves from config.

    Returns:
        List of model IDs. Empty list on failure.
    """
    url = (base_url or resolve_local_base_url()).rstrip("/")
    try:
        resp = httpx.get(
            f"{url}/models",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        models = data if isinstance(data, list) else data.get("data", data.get("models", []))
        return [
            m.get("id") or m.get("name", "")
            for m in models
            if m.get("id") or m.get("name")
        ]
    except Exception as exc:
        logger.warning(
            "Не удалось получить список локальных моделей от %s: %s",
            url, exc,
        )
        return []


def probe_local_max_context(base_url: str, model_name: str) -> int:
    """Probe max context window for a local model via /v1/models endpoint metadata.

    Many local servers (Ollama, vLLM) expose ``context_length`` or similar
    fields in the model info.  Falls back to the default.

    Args:
        base_url:   Base URL of the local server.
        model_name: Model identifier.

    Returns:
        Estimated max input tokens for the model.
    """
    normalized_url = base_url.rstrip("/")
    cache_key = (normalized_url, model_name)
    if cache_key in _LOCAL_MAX_CTX_CACHE:
        return _LOCAL_MAX_CTX_CACHE[cache_key]

    try:
        if normalized_url not in _LOCAL_MODELS_CACHE:
            resp = httpx.get(f"{normalized_url}/models", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            _LOCAL_MODELS_CACHE[normalized_url] = (
                data if isinstance(data, list) else data.get("data", data.get("models", []))
            )
        models_list = _LOCAL_MODELS_CACHE[normalized_url]
        for m in models_list:
            mid = m.get("id") or m.get("name", "")
            if mid == model_name:
                ctx = (
                    m.get("context_length")
                    or m.get("max_model_len")
                    or m.get("details", {}).get("context_length")
                )
                if ctx and isinstance(ctx, int) and ctx > 0:
                    _LOCAL_MAX_CTX_CACHE[cache_key] = ctx
                    logger.info(
                        "📐 Локальная модель %s: context_length = %d (из /v1/models)",
                        model_name, ctx,
                    )
                    return ctx
    except Exception as exc:
        logger.debug("Не удалось определить контекст для %s: %s", model_name, exc)

    _LOCAL_MAX_CTX_CACHE[cache_key] = _DEFAULT_MAX_INPUT_TOKENS
    return _DEFAULT_MAX_INPUT_TOKENS


def build_local_fallback_chain(primary: str, base_url: str | None = None) -> list[str]:
    """Build an ordered fallback chain for local backends (ollama/vllm/lmstudio).

    Priority order:
      1. ``primary`` model (always first).
      2. Explicitly configured ``FALLBACK_MODELS`` from env.
      3. Auto-discovered models from the local server (only when ``FALLBACK_MODELS``
         is empty, to avoid a ~10 s HTTP timeout per job when the backend is down).

    Args:
        primary:  Primary model name.
        base_url: Base URL of the local server.

    Returns:
        Ordered list of model names for sequential fallback.
    """
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


def build_fallback_chain(primary: str) -> list[str]:
    """Build an ordered fallback chain for ANY backend.

    - ``github_models``: uses GitHub Models API discovery + built-in priority.
    - ``ollama``/``vllm``/``lmstudio``: auto-discovers via /v1/models + FALLBACK_MODELS.
    - ``openai``/``deepseek``: uses FALLBACK_MODELS if configured, otherwise single model.

    Args:
        primary: Primary model name (usually MODEL_NAME).

    Returns:
        Ordered list of model names.
    """
    if LLM_BACKEND == "github_models":
        api_key = OPENAI_API_KEY or GITHUB_TOKEN or ""
        return build_github_fallback_chain(api_key, primary)

    if LLM_BACKEND in LOCAL_BACKENDS:
        return build_local_fallback_chain(primary)

    # openai / deepseek: explicit fallback only
    chain: list[str] = [primary]
    for m in FALLBACK_MODELS:
        if m not in chain:
            chain.append(m)
    return chain


def build_llm(temperature: float = 0.2, model_name_override: str | None = None) -> ChatOpenAI:
    """Создать ChatOpenAI-инстанс в соответствии с LLM_BACKEND.

    Args:
        temperature: температура генерации (по умолчанию 0.2).
        model_name_override: явное имя модели; если None — используется MODEL_NAME из env.

    Returns:
        Настроенный экземпляр ChatOpenAI.
    """
    model = model_name_override or MODEL_NAME

    if LLM_BACKEND == "github_models":
        # GitHub Models: endpoint фиксирован.
        # API-ключ: OPENAI_API_KEY → GITHUB_TOKEN → GH_TOKEN.
        # В GitHub Actions / Copilot Workspace / Codespaces GITHUB_TOKEN
        # предоставляется автоматически, поэтому отдельный PAT не нужен.
        api_key = OPENAI_API_KEY or GITHUB_TOKEN
        if not api_key:
            raise ValueError(
                "Для LLM_BACKEND='github_models' необходимо задать OPENAI_API_KEY "
                "или предоставить токен в переменной окружения GITHUB_TOKEN/GH_TOKEN."
            )
        base_url = _GITHUB_MODELS_BASE_URL
        # Отключаем авто-ретрай SDK: 429 / 413 обрабатываются на уровне fallback-логики
        # агента, чтобы сразу переключиться на другую модель без ожидания backoff внутри SDK.
        max_retries = 0
        # Определяем реальный лимит output-токенов через API
        max_tokens_out = probe_max_output_tokens(api_key, model)
    elif LLM_BACKEND in LOCAL_BACKENDS:
        api_key = OPENAI_API_KEY or "not-needed"
        base_url = resolve_local_base_url()
        max_retries = 0
        max_tokens_out = 8192
    else:
        if LLM_BACKEND == "openai" and not OPENAI_API_KEY:
            raise ValueError(
                "Для LLM_BACKEND='openai' необходимо задать OPENAI_API_KEY. "
                "Для CodeSpaces рекомендуется использовать LLM_BACKEND=github_models "
                "(автоматически использует GITHUB_TOKEN)."
            )
        api_key = OPENAI_API_KEY
        base_url = OPENAI_API_BASE or None
        has_fallback = len(FALLBACK_MODELS) > 0
        max_retries = 0 if has_fallback else 2
        max_tokens_out = 8192

    logger.info(
        "🤖 Инициализация LLM: backend=%s, model=%s, max_tokens=%d",
        LLM_BACKEND, model, max_tokens_out,
    )
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens_out,
        api_key=api_key,
        base_url=base_url,
        max_retries=max_retries,
    )
