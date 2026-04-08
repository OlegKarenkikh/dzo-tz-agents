"""
shared/runner_base.py
Базовый класс email-раннера для агентов ДЗО и ТЗ.

FIX DU-01, DU-02: устраняет 90% идентичного кода в process_dzo_emails()
и process_tz_emails().

Агент-специфичная логика (создание агента, формирование chat_input,
разбор результата, отправка ответов) передаётся в шаблонных методах
`build_chat_input`, `parse_steps`, `send_reply`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import config
import shared.database as db
from api.metrics import EMAILS_ERRORS, EMAILS_PROCESSED, JobTimer, POLL_CYCLES
from shared.email_client import fetch_unseen_emails
from shared.file_extractor import extract_text_from_attachment
from shared.logger import setup_logger
from shared.telegram_notify import notify
from shared.tracing import get_langfuse_callback, log_agent_steps


class BaseEmailRunner(ABC):
    """Абстрактный базовый класс email-раннера.

    Наследник должен реализовать:
      - agent_id: str           — идентификатор агента (для логов и БД)
      - imap_config: dict       — параметры IMAP (ключи: host, user, password, port, folder)
      - create_agent()          — создаёт и возвращает экземпляр LangGraph-агента
      - build_chat_input()      — формирует строку входных данных для агента
      - parse_steps()           — извлекает артефакты из intermediate_steps
      - send_reply()            — отправляет итоговое письмо

    Опциональные хуки (переопределять при необходимости):
      - handle_no_attachments() — специальная обработка писем без вложений
      - db_result_fields()      — контролирует набор полей, сохраняемых в БД
    """

    @property
    @abstractmethod
    def agent_id(self) -> str:
        ...

    @property
    @abstractmethod
    def imap_config(self) -> dict:
        """{'host', 'user', 'password', 'port', 'folder'}"""
        ...

    @abstractmethod
    def create_agent(self) -> Any:
        ...

    @abstractmethod
    def build_chat_input(self, mail: dict, attachment_texts: list[str]) -> str:
        ...

    @abstractmethod
    def parse_steps(
        self,
        steps: list,
        result: dict,
        job_id: str,
    ) -> tuple[str, dict, str]:
        """Возвращает (decision: str, artifacts: dict, reply_subject: str)."""
        ...

    @abstractmethod
    def send_reply(
        self,
        sender: str,
        subject: str,
        reply_subject: str,
        decision: str,
        artifacts: dict,
    ) -> None:
        """Отправляет ответное письмо.

        Args:
            sender:        адрес отправителя входящего письма
            subject:       тема оригинального письма
            reply_subject: тема, сгенерированная агентом (может быть пустой)
            decision:      решение агента
            artifacts:     артефакты из parse_steps
        """
        ...

    # ------------------------------------------------------------------
    # Опциональные хуки
    # ------------------------------------------------------------------

    def handle_no_attachments(self, sender: str, subject: str, job_id: str) -> bool:
        """Вызывается, когда в письме нет вложений.

        Переопределите для агент-специфичного поведения.
        Верните True, чтобы пропустить LLM-обработку для этого письма.
        """
        return False

    def db_result_fields(self, mail: dict, artifacts: dict) -> dict:
        """Возвращает dict для поля result при сохранении в БД.

        Переопределите, чтобы контролировать, какие данные хранятся в БД.
        """
        return {
            "attachments": len(mail.get("attachments", [])),
            **{k: v for k, v in artifacts.items() if not isinstance(v, bytes)},
        }

    # ------------------------------------------------------------------
    # Общая логика обработки
    # ------------------------------------------------------------------

    def process_emails(self) -> None:
        """DU-01/02: единая точка обработки email-потока для всех email-агентов."""
        logger = setup_logger(f"agent_{self.agent_id}")
        logger.info("Проверяю входящие письма (%s)...", self.agent_id.upper())
        POLL_CYCLES.labels(agent=self.agent_id).inc()

        imap = self.imap_config
        emails = fetch_unseen_emails(
            imap_host=imap["host"],
            imap_user=imap["user"],
            imap_password=imap["password"],
            imap_port=imap["port"],
            folder=imap.get("folder", "INBOX"),
        )

        if not emails:
            logger.info("Новых писем нет.")
            return

        force_reprocess = getattr(config, "FORCE_REPROCESS", False)

        for mail in emails:
            sender = mail["from"]
            subject = mail["subject"]
            logger.info("Обрабатываю: '%s' от %s", subject, sender)

            if not force_reprocess:
                dup = db.find_duplicate_job(self.agent_id, sender, subject)
                if dup:
                    logger.info(
                        "[dedup] Пропускаем дубль: '%s' от %s "
                        "(ранее обработано %s, решение: %s)",
                        subject, sender,
                        dup["created_at"][:10], dup.get("decision", "?"),
                    )
                    continue

            job_id = db.create_job(self.agent_id, sender=sender, subject=subject)
            try:
                if not mail.get("attachments"):
                    if self.handle_no_attachments(sender, subject, job_id):
                        EMAILS_PROCESSED.labels(agent=self.agent_id).inc()
                        continue

                attachment_texts: list[str] = []
                for att in mail.get("attachments", []):
                    text = extract_text_from_attachment(att)
                    attachment_texts.append(f"---- Файл: {att['filename']} ----\n{text}")

                chat_input = self.build_chat_input(mail, attachment_texts)

                agent = self.create_agent()

                lf_cb = get_langfuse_callback()
                callbacks = [lf_cb] if lf_cb is not None else []

                with JobTimer(self.agent_id):
                    result = agent.invoke(
                        {"input": chat_input},
                        config={
                            "callbacks": callbacks,
                            "metadata": {"session_id": job_id},
                        } if callbacks else {},
                    )

                steps = result.get("intermediate_steps", [])
                trace = log_agent_steps(job_id=job_id, agent=self.agent_id, steps=steps)

                decision, artifacts, reply_subject = self.parse_steps(steps, result, job_id)

                # DA-05: предупреждаем о пустом decision
                if not decision:
                    logger.warning(
                        "[%s] decision не установлен агентом — intermediate_steps пусты",
                        job_id,
                    )
                    decision = "Требуется доработка"

                self.send_reply(sender, subject, reply_subject, decision, artifacts)

                db.update_job(
                    job_id,
                    status="done",
                    decision=decision,
                    result=self.db_result_fields(mail, artifacts),
                    trace=trace,
                )
                EMAILS_PROCESSED.labels(agent=self.agent_id).inc()
                logger.info("Обработано. Решение: %s", decision)

            except Exception as e:
                EMAILS_ERRORS.labels(agent=self.agent_id, error_type=type(e).__name__).inc()
                db.update_job(job_id, status="error", error=str(e))
                logger.error("Критическая ошибка: %s", e)
                notify(
                    f"🔴 Ошибка Агент-{self.agent_id.upper()}\nОт: {sender}\n{e}",
                    level="error",
                )
