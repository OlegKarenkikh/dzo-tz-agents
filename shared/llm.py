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

Автопереключение моделей при 429 (только для github_models):
  При получении RateLimitError агент автоматически переключается на следующую
  модель из цепочки: gpt-4o-mini → Meta-Llama-3.1-405B-Instruct →
  Meta-Llama-3.1-8B-Instruct → gpt-4o. Список актуализируется через API.
"""
import logging

import httpx
from langchain_openai import ChatOpenAI

from config import GITHUB_TOKEN, LLM_BACKEND, MODEL_NAME, OPENAI_API_BASE, OPENAI_API_KEY

logger = logging.getLogger("llm")

# Endpoint GitHub Models фиксирован и не переопределяется через OPENAI_API_BASE
_GITHUB_MODELS_BASE_URL = "https://models.inference.ai.azure.com"

# Приоритетный порядок fallback-моделей GitHub Models.
# Llama-модели от Meta имеют более мягкие rate limits, поэтому стоят выше gpt-4o.
_GITHUB_MODELS_PRIORITY: list[str] = [
    "gpt-4o-mini",
    "Meta-Llama-3.1-405B-Instruct",
    "Meta-Llama-3.1-8B-Instruct",
    "gpt-4o",
]


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
        # GitHub Models: gpt-4o-mini ограничен 8 k токенов суммарно (input + output).
        # Оставляем запас для истории инструментов — просим не более 4096 токенов вывода.
        max_tokens_out = 4096
    else:
        if LLM_BACKEND == "openai" and not OPENAI_API_KEY:
            raise ValueError(
                "Для LLM_BACKEND='openai' необходимо задать OPENAI_API_KEY. "
                "Для CodeSpaces рекомендуется использовать LLM_BACKEND=github_models "
                "(автоматически использует GITHUB_TOKEN)."
            )
        api_key = OPENAI_API_KEY  # for ollama, deepseek, etc., api_key may be ignored or set differently
        base_url = OPENAI_API_BASE or None
        max_retries = 2  # стандартный ретрай для остальных бэкендов
        max_tokens_out = 8192

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens_out,
        api_key=api_key,
        base_url=base_url,
        max_retries=max_retries,
    )
