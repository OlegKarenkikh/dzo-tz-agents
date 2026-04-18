"""
agent6_transportation_parser/runner.py
Email-раннер для агента разбора заявок на страхование грузоперевозок.
"""
from __future__ import annotations

import json
from typing import Any

import config
from shared.email_sender import send_email
from shared.logger import setup_logger
from shared.runner_base import BaseEmailRunner

from .agent import create_transportation_agent

logger = setup_logger("runner_transportation")


class TransportationParserRunner(BaseEmailRunner):
    """Runner для агента разбора заявок на грузоперевозки.

    Workflow:
    1. Получает письмо с вложением (заявка на перевозку)
    2. Формирует chat_input с текстом документа
    3. Агент: extract_base → extract_route → extract_additional
              → resolve_type → validate → fix (при ошибках)
    4. Отправляет JSON-результат в ответном письме
    """

    @property
    def agent_id(self) -> str:
        return "transportation"

    @property
    def imap_config(self) -> dict:
        return {
            "host": config.IMAP_HOST,
            "user": getattr(config, "TRANSPORT_IMAP_USER", config.IMAP_USER),
            "password": getattr(config, "TRANSPORT_IMAP_PASSWORD", config.IMAP_PASSWORD),
            "port": config.IMAP_PORT,
            "folder": getattr(config, "TRANSPORT_IMAP_FOLDER", "INBOX"),
        }

    def create_agent(self) -> Any:
        return create_transportation_agent()

    def build_chat_input(self, mail: dict, attachment_texts: list[str]) -> str:
        body = "\n".join(attachment_texts) or mail.get("body", "")
        return (
            f"ВХОДЯЩАЯ ЗАЯВКА НА СТРАХОВАНИЕ ПЕРЕВОЗКИ\n"
            f"От: {mail.get(\'from\', \'\')}\n"
            f"Тема: {mail.get(\'subject\', \'\')}\n"
            f"{\'=\' * 60}\n"
            f"{body}"
        )

    def parse_steps(
        self, steps: list, result: dict, job_id: str
    ) -> tuple[str, dict, str]:
        decision = ""
        artifacts: dict = {}

        for _tool_name, obs in steps:
            if not isinstance(obs, dict):
                continue
            if obs.get("valid") is True:
                decision = "Разбор завершён"
                artifacts["transport_data"] = obs.get("data", {})
            elif obs.get("valid") is False:
                decision = "Требуется проверка"
                artifacts["validation_errors"] = obs.get("errors", [])
                artifacts["transport_data"] = obs.get("data", {})
            if obs.get("error"):
                decision = "Ошибка разбора"
                artifacts["error"] = obs["error"]

        if not decision:
            output = result.get("output", "")
            if "разбор завершён" in output.lower():
                decision = "Разбор завершён"
            else:
                decision = "Требуется проверка"

        # Формируем тему ответа по маршруту
        route = ""
        if isinstance(artifacts.get("transport_data"), dict):
            d = artifacts["transport_data"]
            dep = d.get("departure_point", "")
            dst = d.get("destination_point", "")
            if dep and dst:
                route = f"{dep} → {dst}"
            elif d.get("cargo_name"):
                route = d["cargo_name"]

        reply_subject = (
            f"Результат разбора перевозки: {route}" if route
            else "Результат разбора перевозки"
        )
        return decision, artifacts, reply_subject

    def send_reply(
        self, sender, subject, reply_subject, decision, artifacts
    ) -> None:
        data = artifacts.get("transport_data", {})
        errors = artifacts.get("validation_errors", [])
        error_msg = artifacts.get("error", "")

        if error_msg:
            html = (
                f"<div style=\'font-family:Arial;font-size:14px\'>"
                f"<p><strong>Ошибка разбора: {error_msg}</strong></p></div>"
            )
        elif errors:
            error_block = "\n".join(f"  - {e}" for e in errors)
            html = (
                f"<div style=\'font-family:Arial;font-size:14px\'>"
                f"<p><strong>Решение: {decision}</strong></p>"
                f"<p>Обнаружены ошибки валидации:</p>"
                f"<pre style=\'background:#fff3cd;padding:10px\'>{error_block}</pre>"
                f"<p>Данные для ручной проверки:</p>"
                f"<pre>{json.dumps(data, ensure_ascii=False, indent=2)}</pre>"
                f"</div>"
            )
        else:
            html = (
                f"<div style=\'font-family:Arial;font-size:14px\'>"
                f"<p><strong>Разбор успешно завершён.</strong></p>"
                f"<pre>{json.dumps(data, ensure_ascii=False, indent=2)}</pre>"
                f"</div>"
            )

        send_email(
            to=sender,
            subject=reply_subject or f"Re: {subject}",
            html_body=html,
        )
        logger.info("✅ Ответ агента перевозки отправлен: %s → %s", reply_subject, sender)
