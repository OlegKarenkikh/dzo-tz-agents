"""
agent5_osago_parser/runner.py
Email-раннер для агента разбора документов ОСАГО.
"""
from __future__ import annotations

import json
from typing import Any

import config
from shared.email_sender import send_email
from shared.logger import setup_logger
from shared.runner_base import BaseEmailRunner

from .agent import create_osago_agent

logger = setup_logger("runner_osago")


class OsagoParserRunner(BaseEmailRunner):
    """Runner для агента разбора документов ОСАГО.

    Workflow:
    1. Получает письмо с заявлением/вложением ОСАГО
    2. Формирует chat_input с текстом
    3. Агент: extract_osago_base → extract_osago_additional → validate_osago_result
    4. Отправляет JSON-результат в ответном письме
    """

    @property
    def agent_id(self) -> str:
        return "osago"

    @property
    def imap_config(self) -> dict:
        return {
            "host": config.IMAP_HOST,
            "user": getattr(config, "OSAGO_IMAP_USER", config.IMAP_USER),
            "password": getattr(config, "OSAGO_IMAP_PASSWORD", config.IMAP_PASSWORD),
            "port": config.IMAP_PORT,
            "folder": getattr(config, "OSAGO_IMAP_FOLDER", "INBOX"),
        }

    def create_agent(self) -> Any:
        return create_osago_agent()

    def build_chat_input(self, mail: dict, attachment_texts: list[str]) -> str:
        body = "\n".join(attachment_texts) or mail.get("body", "")
        return (
            f"ВХОДЯЩИЙ ДОКУМЕНТ ОСАГО\n"
            f"От: {mail.get('from', '')}\n"
            f"Тема: {mail.get('subject', '')}\n"
            f"{'=' * 60}\n"
            f"{body}"
        )

    def parse_steps(self, steps: list, result: dict, job_id: str) -> tuple[str, dict, str]:
        decision = ""
        artifacts: dict = {}
        reply_subject = ""
        for _tool_name, obs in steps:
            if not isinstance(obs, dict):
                continue
            if obs.get("valid") is True:
                decision = "Разбор завершён"
                artifacts["osago_data"] = obs.get("data", {})
            elif obs.get("valid") is False:
                decision = "Требуется проверка"
                artifacts["validation_errors"] = obs.get("errors", [])
                artifacts["osago_data"] = obs.get("data", {})
        if not decision:
            decision = "Требуется проверка"
        vehicle = ""
        if isinstance(artifacts.get("osago_data"), dict):
            d = artifacts["osago_data"]
            vehicle = f"{d.get('vehicle_brand', '')} {d.get('vehicle_number', '')}".strip()
        reply_subject = f"Результат разбора ОСАГО: {vehicle}" if vehicle else "Результат разбора ОСАГО"
        return decision, artifacts, reply_subject

    def send_reply(self, sender, subject, reply_subject, decision, artifacts) -> None:
        data = artifacts.get("osago_data", {})
        errors = artifacts.get("validation_errors", [])
        if errors:
            error_block = "\n".join(f"  - {e}" for e in errors)
            html = (
                f"<div style='font-family:Arial;font-size:14px'>"
                f"<p><strong>Решение: {decision}</strong></p>"
                f"<p>Ошибки валидации:</p><pre>{error_block}</pre>"
                f"<p>Данные:</p><pre>{json.dumps(data, ensure_ascii=False, indent=2)}</pre></div>"
            )
        else:
            html = (
                f"<div style='font-family:Arial;font-size:14px'>"
                f"<p><strong>Разбор завершён.</strong></p>"
                f"<pre>{json.dumps(data, ensure_ascii=False, indent=2)}</pre></div>"
            )
        send_email(to=sender, subject=reply_subject or f"Re: {subject}", html_body=html)
        logger.info("✅ Ответ АГЕНТ ОСАГО отправлен: %s", reply_subject)
