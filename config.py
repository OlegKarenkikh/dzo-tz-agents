import logging
import os

from dotenv import load_dotenv

load_dotenv()

_logger = logging.getLogger("config")


def _safe_int(name: str, default: int) -> int:
    """Parse env var as int, falling back to *default* on invalid values."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        _logger.warning("Некорректное целое число для %s=%r, используется %d", name, raw, default)
        return default


def _safe_float(name: str, default: float) -> float:
    """Parse env var as float, falling back to *default* on invalid values."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        _logger.warning("Некорректное число для %s=%r, используется %s", name, raw, default)
        return default


OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")  # None → дефолт langchain (api.openai.com/v1)

# LLM backend: openai | ollama | deepseek | vllm | lmstudio | github_models
_VALID_BACKENDS = {"openai", "ollama", "deepseek", "vllm", "lmstudio", "github_models"}
LLM_BACKEND = os.getenv("LLM_BACKEND", "openai").lower()

# GitHub Token — используется как API-ключ для LLM_BACKEND=github_models,
# когда OPENAI_API_KEY не задан (GitHub Actions / Copilot Workspace / Codespaces
# автоматически предоставляют этот токен через переменную окружения GITHUB_TOKEN).
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")

# Автопереключение: если явно задан openai, но OPENAI_API_KEY отсутствует
# и доступен GITHUB_TOKEN (CodeSpaces/GitHub Actions), переключаемся на github_models
_auto_switched = False
if (
    LLM_BACKEND == "openai"
    and not OPENAI_API_KEY
    and GITHUB_TOKEN
    and not os.getenv("LLM_BACKEND")  # переключаем только если LLM_BACKEND не был явно задан
):
    LLM_BACKEND = "github_models"
    _auto_switched = True

if LLM_BACKEND not in _VALID_BACKENDS:
    raise ValueError(
        f"LLM_BACKEND='{LLM_BACKEND}' — недопустимое значение. "
        f"Допустимые: {sorted(_VALID_BACKENDS)}"
    )

if _auto_switched:
    import sys
    print(
        "[config] Auto-switched to LLM_BACKEND=github_models "
        "(OPENAI_API_KEY не задан, но доступен GITHUB_TOKEN)",
        file=sys.stderr,
    )

# IMAP — Агент ДЗО
DZO_IMAP_HOST     = os.getenv("DZO_IMAP_HOST", os.getenv("IMAP_HOST", "imap.company.ru"))
DZO_IMAP_PORT     = _safe_int("DZO_IMAP_PORT", 993)
DZO_IMAP_USER     = os.getenv("DZO_IMAP_USER", os.getenv("IMAP_USER"))
DZO_IMAP_PASSWORD = os.getenv("DZO_IMAP_PASSWORD", os.getenv("IMAP_PASSWORD"))
DZO_IMAP_FOLDER   = os.getenv("DZO_IMAP_FOLDER", "INBOX")
DZO_SMTP_FROM     = os.getenv("DZO_SMTP_FROM", os.getenv("SENDER_EMAIL", "ucz@company.ru"))

# IMAP — Агент ТЗ
TZ_IMAP_HOST      = os.getenv("TZ_IMAP_HOST", os.getenv("IMAP_HOST", "imap.company.ru"))
TZ_IMAP_PORT      = _safe_int("TZ_IMAP_PORT", 993)
TZ_IMAP_USER      = os.getenv("TZ_IMAP_USER", os.getenv("IMAP_USER"))
TZ_IMAP_PASSWORD  = os.getenv("TZ_IMAP_PASSWORD", os.getenv("IMAP_PASSWORD"))
TZ_IMAP_FOLDER    = os.getenv("TZ_IMAP_FOLDER", "INBOX")
TZ_SMTP_FROM      = os.getenv("TZ_SMTP_FROM", os.getenv("SENDER_EMAIL", "ucz@company.ru"))

# SMTP
SMTP_HOST         = os.getenv("SMTP_HOST", "smtp.company.ru")
SMTP_PORT         = _safe_int("SMTP_PORT", 587)
SMTP_USER         = os.getenv("SMTP_USER")
SMTP_PASSWORD     = os.getenv("SMTP_PASSWORD")
MANAGER_EMAIL     = os.getenv("MANAGER_EMAIL", "manager@company.ru")

# LLM
MODEL_NAME        = os.getenv("MODEL_NAME", "gpt-4o")
POLL_INTERVAL_SEC = _safe_int("POLL_INTERVAL_SEC", 300)

# Защита от зависаний и зацикливания
# AGENT_JOB_TIMEOUT_SEC    — максимальное время выполнения одного job (сек), 0 = без ограничения
# AGENT_MAX_RETRIES        — максимум попыток на одну модель перед переключением
# AGENT_RATE_LIMIT_BACKOFF — пауза (сек) перед переключением на следующую модель при 429
AGENT_JOB_TIMEOUT_SEC    = _safe_int("AGENT_JOB_TIMEOUT_SEC", 300)
AGENT_MAX_RETRIES        = _safe_int("AGENT_MAX_RETRIES", 1)
AGENT_RATE_LIMIT_BACKOFF = _safe_float("AGENT_RATE_LIMIT_BACKOFF", 3.0)
