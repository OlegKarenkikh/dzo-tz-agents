import os
import signal
import sys
import time

import schedule
from dotenv import load_dotenv

load_dotenv()

from shared.logger import setup_logger  # noqa: E402

logger = setup_logger("main")

_shutdown_requested = False


def _handle_signal(signum: int, _frame) -> None:
    """Graceful shutdown on SIGTERM / SIGINT."""
    global _shutdown_requested
    sig_name = signal.Signals(signum).name
    logger.info("Получен сигнал %s, завершаю работу…", sig_name)
    _shutdown_requested = True


def run():
    global _shutdown_requested

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    mode = os.getenv("AGENT_MODE", "both").lower()
    interval = int(os.getenv("POLL_INTERVAL_SEC", 300))
    # RUN_ON_START=false позволяет отключить немедленный запуск всех агентов при старте
    run_on_start = os.getenv("RUN_ON_START", "true").lower() != "false"
    logger.info(f"Запуск в режиме: {mode}, интервал: {interval} сек., RUN_ON_START={run_on_start}")

    if mode in ("dzo", "both"):
        from agent1_dzo_inspector.runner import process_dzo_emails
        schedule.every(interval).seconds.do(process_dzo_emails)
        logger.info("Агент ДЗО подключён.")

    if mode in ("tz", "both"):
        from agent2_tz_inspector.runner import process_tz_emails
        schedule.every(interval).seconds.do(process_tz_emails)
        logger.info("Агент ТЗ подключён.")

    if mode in ("tender", "both"):
        from agent21_tender_inspector.runner import process_tender_documents
        schedule.every(interval).seconds.do(process_tender_documents)
        logger.info("Агент Тендер подключён.")

    logger.info("Polling запущен. Нажмите Ctrl+C для остановки.")
    if run_on_start:
        logger.info("Немедленный запуск всех агентов (RUN_ON_START=true).")
        schedule.run_all()
    while not _shutdown_requested:
        schedule.run_pending()
        time.sleep(30)

    logger.info("Завершение работы.")
    sys.exit(0)


if __name__ == "__main__":
    run()
