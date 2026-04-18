"""
agent4_leasing_parser/runner.py
Email-раннер для агента разбора договоров лизинга.
Наследует BaseEmailRunner и реализует все абстрактные методы.
"""
from __future__ import annotations

import json
from typing import Any

import config
from shared.email_sender import send_email
from shared.logger import setup_logger
from shared.runner_base import BaseEmailRunner

from .agent import create_leasing_agent

logger = setup_logger("runner_leasing")


class LeasingParserRunner(BaseEmailRunner):
    """Runner для агента разбора договоров лизинга.

    Workflow:
    1. Получает письмо с вложением (docx/pdf с договором лизинга)
    2. Формирует chat_input с текстом документа
    3. Агент последовательно вызывает инструменты extract_* → validate_leasing_result
    4. Отправляет JSON-результат в ответном письме
    """

    @property
    def agent_id(self) -> str:
        return "leasing"

    @property
    def imap_config(self) -> dict:
        return {
            "host": config.IMAP_HOST,
            "user": getattr(config, "LEASING_IMAP_USER", config.IMAP_USER),
            "password": getattr(config, "LEASING_IMAP_PASSWORD", config.IMAP_PASSWORD),
            "port": config.IMAP_PORT,
            "folder": getattr(config, "LEASING_IMAP_FOLDER", "INBOX"),
        }

    def create_agent(self) -> Any:
        return create_leasing_agent()

    def build_chat_input(self, mail: dict, attachment_texts: list[str]) -> str:
        subject = mail.get("subject", "")
        sender = mail.get("from", "")
        body = "\n".join(attachment_texts)
        return (
            f"ВХОДЯЩИЙ ДОКУМЕНТ ЛИЗИНГА\n"
            f"От: {sender}\n"
            f"Тема: {subject}\n"
            f"{'=' * 60}\n"
            f"{body}"
        )

    def parse_steps(
        self, steps: list, result: dict, job_id: str
    ) -> tuple[str, dict, str]:
        decision = ""
        artifacts: dict = {}
        reply_subject = ""

        for _tool_name, obs in steps:
            if not isinstance(obs, dict):
                continue
            if obs.get("valid") is True:
                decision = "Разбор завершён"
                artifacts["leasing_data"] = obs.get("data", {})
            elif obs.get("valid") is False:
                decision = "Требуется проверка"
                artifacts["validation_errors"] = obs.get("errors", [])
                artifacts["leasing_data"] = obs.get("data", {})
            if obs.get("error"):
                decision = "Ошибка разбора"
                artifacts["error"] = obs["error"]

        if not decision:
            output = result.get("output", "")
            if "разбор завершён" in output.lower() or "валидация прошла" in output.lower():
                decision = "Разбор завершён"
            else:
                decision = "Требуется проверка"

        policy_num = ""
        if isinstance(artifacts.get("leasing_data"), dict):
            base = artifacts["leasing_data"].get("base", {})
            policy_num = base.get("policy_number", "")

        reply_subject = f"Результат разбора лизинга: {policy_num}" if policy_num else "Результат разбора лизинга"
        return decision, artifacts, reply_subject

    def send_reply(
        self,
        sender: str,
        subject: str,
        reply_subject: str,
        decision: str,
        artifacts: dict,
    ) -> None:
        leasing_data = artifacts.get("leasing_data", {})
        errors = artifacts.get("validation_errors", [])
        error_msg = artifacts.get("error", "")

        if errors:
            error_block = "\n".join(f"  - {e}" for e in errors)
            html = (
                f"<div style='font-family:Arial;font-size:14px'>"
                f"<p><strong>Решение: {decision}</strong></p>"
                f"<p>Обнаружены ошибки валидации:</p>"
                f"<pre style='background:#fff3cd;padding:10px'>{error_block}</pre>"
                f"<p>Данные для ручной проверки:</p>"
                f"<pre>{json.dumps(leasing_data, ensure_ascii=False, indent=2)}</pre>"
                f"</div>"
            )
        elif error_msg:
            html = (
                f"<div style='font-family:Arial;font-size:14px'>"
                f"<p><strong>Ошибка разбора: {error_msg}</strong></p></div>"
            )
        else:
            html = (
                f"<div style='font-family:Arial;font-size:14px'>"
                f"<p><strong>Разбор успешно завершён.</strong></p>"
                f"<pre>{json.dumps(leasing_data, ensure_ascii=False, indent=2)}</pre>"
                f"</div>"
            )

        send_email(
            to=sender,
            subject=reply_subject or f"Re: {subject}",
            html_body=html,
        )
        logger.info("✅ Ответ отправлен: %s → %s", reply_subject, sender)
