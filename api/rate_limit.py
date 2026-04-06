"""
Rate limiting middleware для FastAPI.

Использует slowapi (обёртка над limits/ratelimit).
Зависимость: pip install slowapi

Лимиты по умолчанию (переопределяются через .env):
  RATE_LIMIT_PROCESS  — POST /api/v1/process/*   (дорогие LLM-вызовы)
  RATE_LIMIT_DEFAULT  — все остальные защищённые эндпоинты

Ключ идентификации клиента: IP-адрес (X-Forwarded-For за nginx).
Для аутентифицированных клиентов можно заменить на API-ключ:
  key_func=lambda req: req.headers.get("X-API-Key") or get_remote_address(req)
"""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# Лимиты: «N/period», где period = second | minute | hour | day
_PROCESS_LIMIT = os.getenv("RATE_LIMIT_PROCESS", "20/minute")
_DEFAULT_LIMIT = os.getenv("RATE_LIMIT_DEFAULT", "120/minute")

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[_DEFAULT_LIMIT],
)

# Лимит для тяжёлых LLM-эндпоинтов (process/*)
PROCESS_RATE_LIMIT = _PROCESS_LIMIT
