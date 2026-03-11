import os
import schedule
import time
from dotenv import load_dotenv
load_dotenv()

from shared.logger import setup_logger

logger = setup_logger("main")


def run():
    mode = os.getenv("AGENT_MODE", "both").lower()
    interval = int(os.getenv("POLL_INTERVAL_SEC", 300))
    logger.info(f"Запуск в режиме: {mode}, интервал: {interval} сек.")

    if mode in ("dzo", "both"):
        from agent1_dzo_inspector.runner import process_dzo_emails
        schedule.every(interval).seconds.do(process_dzo_emails)
        logger.info("Агент ДЗО подключён.")

    if mode in ("tz", "both"):
        from agent2_tz_inspector.runner import process_tz_emails
        schedule.every(interval).seconds.do(process_tz_emails)
        logger.info("Агент ТЗ подключён.")

    logger.info("Polling запущен. Нажмите Ctrl+C для остановки.")
    # Выполнить сразу при старте
    schedule.run_all()
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    run()
