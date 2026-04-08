"""
shared/base_runner.py
Базовый миксин для обработки email-потока агентами.

FIX DU-01: удаляет 90%+ дублирующегося кода между
  agent1_dzo_inspector/runner.py и agent2_tz_inspector/runner.py.

FIX DU-02: process_emails для DZO и TZ являются структурными клонами —
  вынесены в process_emails_base().
"""
from __future__ import annotations

from typing import Callable

import shared.database as db
from api.metrics import EMAILS_ERRORS, EMAILS_PROCESSED, JobTimer, POLL_CYCLES
from config import FORCE_REPROCESS
from shared.email_client import fetch_unseen_emails
from shared.file_extractor import extract_text_from_attachment
from shared.logger import setup_logger
from shared.telegram_notify import notify
from shared.tracing import get_langfuse_callback, log_agent_steps


def process_emails_base(
    *,
    agent_name: str,
    agent_label: str,
    imap_host: str,
    imap_user: str,
    imap_password: str,
    imap_port: int,
    imap_folder: str,
    smtp_from: str,
    create_agent_fn: Callable,
    extract_extra_fields_fn: Callable[[list], tuple[bool, bool]],
    build_chat_input_fn: Callable[[dict, list[str], bool, bool], str],
    extract_artifacts_fn: Callable[[list, str], dict],
    send_reply_fn: Callable[[str, str, dict, str], None],
    build_db_result_fn: Callable[[dict, bool, bool, int], dict],
) -> None:
    """Общая логика IMAP-поллинга + LLM-вызова + отправки ответа.

    Каждый агент передаёт callback-функции для агент-специфичных действий.
    smtp_from используется в send_reply_fn — передаётся как аргумент.
    """
    logger = setup_logger(f"agent_{agent_name}")
    logger.info("Проверяю входящие письма (%s)...", agent_label)
    POLL_CYCLES.labels(agent=agent_name).inc()

    emails = fetch_unseen_emails(
        imap_host=imap_host,
        imap_user=imap_user,
        imap_password=imap_password,
        imap_port=imap_port,
        folder=imap_folder,
    )

    if not emails:
        logger.info("Новых писем нет.")
        return

    for mail in emails:
        # Агент создаётся внутри цикла — изолированная память ConversationBufferWindowMemory
        agent = create_agent_fn()

        sender = mail["from"]
        subject = mail["subject"]
        logger.info("Обрабатываю: '%s' от %s", subject, sender)

        if not FORCE_REPROCESS:
            dup = db.find_duplicate_job(agent_name, sender, subject)
            if dup:
                logger.info(
                    "[dedup] Пропускаем дубль: '%s' от %s "
                    "(ранее %s, решение: %s)",
                    subject, sender,
                    dup["created_at"][:10], dup.get("decision", "?"),
                )
                continue

        job_id = db.create_job(agent_name, sender=sender, subject=subject)
        try:
            attachment_texts = []
            for att in mail["attachments"]:
                text = extract_text_from_attachment(att)
                attachment_texts.append(f"──── Файл: {att['filename']} ────\n{text}")

            extra_flag1, extra_flag2 = extract_extra_fields_fn(mail["attachments"])
            chat_input = build_chat_input_fn(mail, attachment_texts, extra_flag1, extra_flag2)

            lf_cb = get_langfuse_callback()
            callbacks = [lf_cb] if lf_cb is not None else []

            with JobTimer(agent_name):
                result = agent.invoke(
                    {"input": chat_input},
                    config={
                        "callbacks": callbacks,
                        "metadata": {"session_id": job_id},
                    } if callbacks else {},
                )

            steps = result.get("intermediate_steps", [])
            trace = log_agent_steps(job_id=job_id, agent=agent_name, steps=steps)

            artifacts = extract_artifacts_fn(steps, job_id)

            send_reply_fn(sender, subject, artifacts, smtp_from)

            decision = artifacts.get("decision", "Требуется доработка")
            if not decision:
                logger.warning(
                    "[%s] decision не установлен — промежуточный результат",
                    job_id,
                )
                decision = "Требуется доработка"

            db_result = build_db_result_fn(artifacts, extra_flag1, extra_flag2, len(mail["attachments"]))
            db.update_job(job_id, status="done", decision=decision, result=db_result, trace=trace)
            EMAILS_PROCESSED.labels(agent=agent_name).inc()
            logger.info("Обработано. Решение: %s", decision)

        except Exception as e:
            EMAILS_ERRORS.labels(agent=agent_name, error_type=type(e).__name__).inc()
            db.update_job(job_id, status="error", error=str(e))
            logger.error("Критическая ошибка: %s", e)
            notify(f"🔴 Ошибка {agent_label}\nОт: {sender}\n{e}", level="error")
