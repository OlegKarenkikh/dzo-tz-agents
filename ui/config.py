"""Конфигурация Streamlit UI из переменных окружения."""

import os

from dotenv import load_dotenv

load_dotenv()

# URL REST API
API_URL: str = os.getenv("UI_API_URL", "http://localhost:8000")

# API-ключ для запросов к REST API
API_KEY: str = os.getenv("UI_API_KEY", os.getenv("API_KEY", ""))

# Заголовки авторизации
AUTH_HEADERS: dict[str, str] = {"X-API-Key": API_KEY} if API_KEY else {}

# Интервал авто-обновления дашборда (секунды)
AUTO_REFRESH_SEC: int = int(os.getenv("UI_AUTO_REFRESH_SEC", "30"))
