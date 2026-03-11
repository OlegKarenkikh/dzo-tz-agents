import httpx
import os
from shared.logger import setup_logger

logger = setup_logger("telegram")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")


def notify(message: str, level: str = "info"):
    """Отправляет уведомление в Telegram. Используется для эскалаций и ошибок."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    icons = {"info": "ℹ️", "warning": "⚠️", "error": "🔴", "success": "✅"}
    icon = icons.get(level, "ℹ️")
    text = f"{icon} *Агент-Инспектор*\n{message}"
    try:
        httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Telegram уведомление не отправлено: {e}")
