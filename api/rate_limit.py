"""
Rate limiting middleware для FastAPI.

Использует slowapi (обёртка над limits/ratelimit).

FIX SE-03: key_func с приоритетом X-API-Key → IP.
При наличии X-API-Key лимит считается по хешу ключа,
иначе — по IP-адресу.
"""
import hashlib
import os

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

_PROCESS_LIMIT = os.getenv("RATE_LIMIT_PROCESS", "20/minute")
_DEFAULT_LIMIT = os.getenv("RATE_LIMIT_DEFAULT", "120/minute")
# Cached once at startup; API_KEY does not change at runtime
_CONFIGURED_API_KEY = os.getenv("API_KEY", "")


def _rate_key(request: Request) -> str:
    """FIX SE-03: rate limit по хешу API-ключа (если валиден) или по IP.

    Хеш API-ключа используется только тогда, когда присланный заголовок
    X-API-Key совпадает с настроенным API_KEY. Для отсутствующего или
    невалидного ключа возвращается IP-адрес клиента, чтобы нельзя было
    обойти IP-лимит, отправляя случайные значения X-API-Key.
    """
    api_key = request.headers.get("X-API-Key", "")
    if api_key and _CONFIGURED_API_KEY and api_key == _CONFIGURED_API_KEY:
        # Не храним ключ целиком — только его хеш (первые 16 сим. SHA-256)
        return "apikey:" + hashlib.sha256(api_key.encode()).hexdigest()[:16]
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_key)

PROCESS_RATE_LIMIT = _PROCESS_LIMIT
DEFAULT_RATE_LIMIT = _DEFAULT_LIMIT
