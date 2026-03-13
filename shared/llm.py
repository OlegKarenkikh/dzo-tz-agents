"""Фабрика LLM — единая точка создания ChatOpenAI для всех агентов.

Поддерживаемые бэкенды (LLM_BACKEND):
  openai        — OpenAI API (по умолчанию)
  ollama        — локальный Ollama
  deepseek      — DeepSeek API
  vllm          — vLLM (self-hosted)
  lmstudio      — LM Studio
  github_models — GitHub Models (https://models.inference.ai.azure.com)
"""
from langchain_openai import ChatOpenAI

from config import LLM_BACKEND, MODEL_NAME, OPENAI_API_BASE, OPENAI_API_KEY

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
        # GitHub Models: OPENAI_API_KEY = GitHub PAT, endpoint фиксирован
        base_url = _GITHUB_MODELS_BASE_URL
    else:
        base_url = OPENAI_API_BASE or None

    return ChatOpenAI(
        model=MODEL_NAME,
        temperature=temperature,
        max_tokens=8192,
        api_key=OPENAI_API_KEY or "ollama",
        base_url=base_url,
    )
