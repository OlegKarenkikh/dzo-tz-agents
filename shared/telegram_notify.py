import os

import httpx

from shared.logger import setup_logger

logger = setup_logger("telegram")


def notify(message: str, level: str = "info") -> None:
    """Отправляет уведомление в Telegram. Используется для эскалаций и ошибок.

    Токен и chat_id читаются динамически через os.getenv() —
    изменение переменных среды в runtime сразу вступает в силу без перезапуска.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    icons = {"info": "ℹ️", "warning": "⚠️", "error": "🔴", "success": "✅"}
    icon = icons.get(level, "ℹ️")
    text = f"{icon} *Агент-Инспектор*\n{message}"
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Telegram уведомление не отправлено: {e}")
