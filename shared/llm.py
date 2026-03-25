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
"""
from langchain_openai import ChatOpenAI

from config import GITHUB_TOKEN, LLM_BACKEND, MODEL_NAME, OPENAI_API_BASE, OPENAI_API_KEY

# Endpoint GitHub Models фиксирован и не переопределяется через OPENAI_API_BASE
_GITHUB_MODELS_BASE_URL = "https://models.inference.ai.azure.com"


def build_llm(temperature: float = 0.2) -> ChatOpenAI:
    """Создать ChatOpenAI-инстанс в соответствии с LLM_BACKEND.

    Args:
        temperature: температура генерации (по умолчанию 0.2).

    Returns:
        Настроенный экземпляр ChatOpenAI.
    """
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
    else:
        api_key = OPENAI_API_KEY or "ollama"
        base_url = OPENAI_API_BASE or None

    return ChatOpenAI(
        model=MODEL_NAME,
        temperature=temperature,
        max_tokens=8192,
        api_key=api_key,
        base_url=base_url,
    )
