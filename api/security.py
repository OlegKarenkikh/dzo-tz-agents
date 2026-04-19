"""
Аутентификация и security-утилиты API.

Перенесено из api/app.py (TD-01).
"""
import logging
import os
import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

logger = logging.getLogger("api")

_DEFAULT_API_KEYS = {"change-me-strong-api-key", "my-test-api-key-12345", ""}
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_api_key() -> str:
    """Legacy: return first configured API key (backward compat)."""
    return os.getenv("API_KEY", "")


def verify_jwt(token: str) -> dict | None:
    """Verify a JWT bearer token. Returns payload or None."""
    from config import JWT_SECRET, JWT_ALGORITHM
    if not JWT_SECRET:
        return None
    try:
        import jwt
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.exceptions.ExpiredSignatureError:
        logger.debug("JWT expired")
        return None
    except jwt.exceptions.DecodeError:
        logger.debug("JWT decode error")
        return None
    except Exception:
        logger.warning("JWT unexpected error")
        return None


def require_api_key(key: str | None = Depends(_api_key_header)) -> str:
    from config import API_KEYS, JWT_SECRET

    if not API_KEYS and not JWT_SECRET:
        return ""

    if not key:
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий API-ключ")

    if JWT_SECRET and (key.startswith("eyJ") or key.count(".") == 2):
        payload = verify_jwt(key)
        if payload:
            return payload.get("sub", "jwt-user")
        raise HTTPException(status_code=401, detail="Невалидный JWT токен")

    if API_KEYS:
        for valid_key in API_KEYS:
            if secrets.compare_digest(key, valid_key):
                return key
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий API-ключ")

    api_key = get_api_key()
    if api_key and not secrets.compare_digest(key, api_key):
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий API-ключ")

    return key


def make_mcp_auth_guard(mcp_available: bool, cors_origins: list[str]):
    """Фабрика middleware для защиты /mcp endpoint."""

    async def _mcp_auth_guard(request: Request, call_next):
        path = request.url.path
        if mcp_available and (path == "/mcp" or path.startswith("/mcp/")) and request.method != "OPTIONS":
            api_key = get_api_key()
            if api_key:
                provided = (request.headers.get("X-API-Key") or "").strip()
                if not provided:
                    auth_header = request.headers.get("Authorization", "").strip()
                    scheme, _, credentials = auth_header.partition(" ")
                    if scheme.lower() == "bearer":
                        provided = credentials.strip()
                if not provided or not secrets.compare_digest(provided, api_key):
                    response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
                    origin = request.headers.get("origin", "")
                    if origin and (origin in cors_origins or "*" in cors_origins):
                        response.headers["Access-Control-Allow-Origin"] = origin
                        response.headers["Access-Control-Allow-Credentials"] = "true"
                    elif cors_origins:
                        response.headers["Access-Control-Allow-Origin"] = cors_origins[0]
                        response.headers["Access-Control-Allow-Credentials"] = "true"
                    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE"
                    response.headers["Access-Control-Allow-Headers"] = "X-API-Key, Authorization, Content-Type, Accept, X-Requested-With"
                    return response
        return await call_next(request)

    return _mcp_auth_guard
