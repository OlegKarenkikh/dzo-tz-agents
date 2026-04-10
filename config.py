import json
import logging
import os

from dotenv import load_dotenv

load_dotenv()

_logger = logging.getLogger("config")


def _safe_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        _logger.warning("Некорректное целое число для %s=%r, используется %d", name, raw, default)
        return default


def _safe_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        _logger.warning("Некорректное число для %s=%r, используется %s", name, raw, default)
        return default


OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")

_VALID_BACKENDS = {"openai", "ollama", "deepseek", "vllm", "lmstudio", "github_models"}
LLM_BACKEND = os.getenv("LLM_BACKEND", "openai").lower()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")

# FIX MU-03 + DU-04: централизуем FORCE_REPROCESS в config.py (удалён из 3 runners)
FORCE_REPROCESS: bool = os.getenv("FORCE_REPROCESS", "false").lower() == "true"

_auto_switched = False
if (
    LLM_BACKEND == "openai"
    and not OPENAI_API_KEY
    and GITHUB_TOKEN
    and not os.getenv("LLM_BACKEND")
):
    LLM_BACKEND = "github_models"
    _auto_switched = True

if LLM_BACKEND not in _VALID_BACKENDS:
    raise ValueError(
        f"LLM_BACKEND='{LLM_BACKEND}' — недопустимое значение. "
        f"Допустимые: {sorted(_VALID_BACKENDS)}"
    )

# FIX SE-01: заменили print() на logger.info()
if _auto_switched:
    _logger.info(
        "Auto-switched to LLM_BACKEND=github_models "
        "(OPENAI_API_KEY не задан, но доступен GITHUB_TOKEN)"
    )

DZO_IMAP_HOST     = os.getenv("DZO_IMAP_HOST", os.getenv("IMAP_HOST", "imap.company.ru"))
DZO_IMAP_PORT     = _safe_int("DZO_IMAP_PORT", 993)
DZO_IMAP_USER     = os.getenv("DZO_IMAP_USER", os.getenv("IMAP_USER"))
DZO_IMAP_PASSWORD = os.getenv("DZO_IMAP_PASSWORD", os.getenv("IMAP_PASSWORD"))
DZO_IMAP_FOLDER   = os.getenv("DZO_IMAP_FOLDER", "INBOX")
DZO_SMTP_FROM     = os.getenv("DZO_SMTP_FROM", os.getenv("SENDER_EMAIL", "ucz@company.ru"))

TZ_IMAP_HOST      = os.getenv("TZ_IMAP_HOST", os.getenv("IMAP_HOST", "imap.company.ru"))
TZ_IMAP_PORT      = _safe_int("TZ_IMAP_PORT", 993)
TZ_IMAP_USER      = os.getenv("TZ_IMAP_USER", os.getenv("IMAP_USER"))
TZ_IMAP_PASSWORD  = os.getenv("TZ_IMAP_PASSWORD", os.getenv("IMAP_PASSWORD"))
TZ_IMAP_FOLDER    = os.getenv("TZ_IMAP_FOLDER", "INBOX")
TZ_SMTP_FROM      = os.getenv("TZ_SMTP_FROM", os.getenv("SENDER_EMAIL", "ucz@company.ru"))

SMTP_HOST         = os.getenv("SMTP_HOST", "smtp.company.ru")
SMTP_PORT         = _safe_int("SMTP_PORT", 587)
SMTP_USER         = os.getenv("SMTP_USER")
SMTP_PASSWORD     = os.getenv("SMTP_PASSWORD")
MANAGER_EMAIL     = os.getenv("MANAGER_EMAIL", "manager@company.ru")

MODEL_NAME        = os.getenv("MODEL_NAME", "gpt-4o")
POLL_INTERVAL_SEC = _safe_int("POLL_INTERVAL_SEC", 300)

AGENT_JOB_TIMEOUT_SEC    = _safe_int("AGENT_JOB_TIMEOUT_SEC", 300)
AGENT_MAX_RETRIES        = _safe_int("AGENT_MAX_RETRIES", 1)
AGENT_RATE_LIMIT_BACKOFF = _safe_float("AGENT_RATE_LIMIT_BACKOFF", 3.0)

FALLBACK_MODELS: list[str] = [
    m.strip() for m in os.getenv("FALLBACK_MODELS", "").split(",") if m.strip()
]


def _safe_json_dict(name: str, default: dict) -> dict:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        _logger.warning("Некорректный JSON для %s, используется значение по умолчанию", name)
        return default
    if not isinstance(value, dict):
        _logger.warning("%s должен быть JSON-объектом, используется значение по умолчанию", name)
        return default
    return value


AGENT_TOOL_ENABLED: bool = os.getenv("AGENT_TOOL_ENABLED", "true").lower() == "true"
AGENT_TOOL_REGISTRY: dict = _safe_json_dict("AGENT_TOOL_REGISTRY", {})
AGENT_TOOL_PERMISSIONS: dict = _safe_json_dict("AGENT_TOOL_PERMISSIONS", {})

# Явный публичный URL сервиса (используется в A2A Agent Card).
# Если задан — снимает зависимость от Host-заголовка.
# Пример: PUBLIC_BASE_URL=https://agents.company.ru
PUBLIC_BASE_URL: str | None = os.getenv("PUBLIC_BASE_URL") or None
