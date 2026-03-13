"""Конфигурация Streamlit UI из переменных окружения."""

import os

from dotenv import load_dotenv

load_dotenv()

# URL REST API (FastAPI backend)
API_URL: str = os.getenv("UI_API_URL", "http://localhost:8000")

# API-ключ для запросов к REST API
API_KEY: str = os.getenv("UI_API_KEY", os.getenv("API_KEY", ""))

# Заголовки авторизации
AUTH_HEADERS: dict[str, str] = {"X-API-Key": API_KEY} if API_KEY else {}

# Интервал авто-обновления дашборда (секунды)
AUTO_REFRESH_SEC: int = int(os.getenv("UI_AUTO_REFRESH_SEC", "30"))

# Бэкенд LLM (только для отображения в сайдбаре; реальное значение — OPENAI_API_BASE)
# Возможные значения: openai | ollama | deepseek | vllm | lmstudio | custom
LLM_BACKEND: str = os.getenv("LLM_BACKEND", "openai")

# Форсировать повторную обработку (обходить дедупликацию) — только для отладки
FORCE_REPROCESS: bool = os.getenv("FORCE_REPROCESS", "false").lower() == "true"
