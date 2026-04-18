"""
agent8_responsibility_parser/runner.py
Email-раннер для агента разбора договоров ответственности (431/432/433).
"""
from __future__ import annotations

import json
from typing import Any

import config
from shared.email_sender import send_email
from shared.logger import setup_logger
from shared.runner_base import BaseEmailRunner

from .agent import create_responsibility_agent

logger = setup_logger("runner_responsibility")


class ResponsibilityParserRunner(BaseEmailRunner):
    """Runner для агента разбора договоров ответственности.

    Workflow:
    1. Получает письмо с вложением (договор 431/432/433)
    2. Агент: detect_type → extract_base → extract_objects/fid → validate → fix
    3. Отправляет JSON-результат с типом договора
    """

    @property
    def agent_id(self) -> str:
        return "responsibility"

    @property
    def imap_config(self) -> dict:
        return {
            "host": config.IMAP_HOST,
            "user": getattr(config, "RESP_IMAP_USER", config.IMAP_USER),
            "password": getattr(config, "RESP_IMAP_PASSWORD", config.IMAP_PASSWORD),
            "port": config.IMAP_PORT,
            "folder": getattr(config, "RESP_IMAP_FOLDER", "INBOX"),
        }

    def create_agent(self) -> Any:
        return create_responsibility_agent()

    def build_chat_input(self, mail: dict, attachment_texts: list[str]) -> str:
        body = "
".join(attachment_texts) or mail.get("body", "")
        sep = "=" * 60
        return (
            f"ВХОДЯЩИЙ ДОГОВОР СТРАХОВАНИЯ ОТВЕТСТВЕННОСТИ
"
            f"От: {mail.get('from', '')}
"
            f"Тема: {mail.get('subject', '')}
"
            f"{sep}
"
            f"{body}"
        )

    def parse_steps(self, steps: list, result: dict, job_id: str) -> tuple[str, dict, str]:
        decision = ""
        artifacts: dict = {}

        for _tool_name, obs in steps:
            if not isinstance(obs, dict):
                continue
            if obs.get("valid") is True:
                decision = "Разбор завершён"
                artifacts["responsibility_data"] = obs.get("data", {})
                artifacts["subtype"] = obs.get("subtype", "")
            elif obs.get("valid") is False:
                decision = "Требуется проверка"
                artifacts["validation_errors"] = obs.get("errors", [])
                artifacts["responsibility_data"] = obs.get("data", {})
                artifacts["subtype"] = obs.get("subtype", "")
            if obs.get("error"):
                decision = "Ошибка разбора"
                artifacts["error"] = obs["error"]
            if obs.get("subtype") and not artifacts.get("subtype"):
                artifacts["subtype"] = obs["subtype"]

        if not decision:
            output = result.get("output", "")
            decision = "Разбор завершён" if "разбор завершён" in output.lower() else "Требуется проверка"

        subtype = artifacts.get("subtype", "")
        label = f"Тип {subtype}" if subtype else "Ответственность"
        data = artifacts.get("responsibility_data", {})
        num = data.get("contract_number", "") if isinstance(data, dict) else ""
        reply_subject = (
            f"Результат разбора {label}: {num}" if num
            else f"Результат разбора {label}"
        )
        return decision, artifacts, reply_subject

    def send_reply(self, sender, subject, reply_subject, decision, artifacts) -> None:
        data = artifacts.get("responsibility_data", {})
        errors = artifacts.get("validation_errors", [])
        error_msg = artifacts.get("error", "")
        subtype = artifacts.get("subtype", "")
        div_style = "font-family:Arial;font-size:14px"
        label = f"ответственности тип {subtype}" if subtype else "ответственности"

        if error_msg:
            html = f'<div style="{div_style}"><p><strong>Ошибка: {error_msg}</strong></p></div>'
        elif errors:
            eb = chr(10).join(f"  - {e}" for e in errors)
            html = (
                f'<div style="{div_style}">'
                f"<p><strong>Решение: {decision}</strong></p>"
                f'<pre style="background:#fff3cd;padding:10px">{eb}</pre>'
                f"<pre>{json.dumps(data, ensure_ascii=False, indent=2)}</pre></div>"
            )
        else:
            html = (
                f'<div style="{div_style}">'
                f"<p><strong>Разбор договора {label} завершён.</strong></p>"
                f"<pre>{json.dumps(data, ensure_ascii=False, indent=2)}</pre></div>"
            )

        send_email(to=sender, subject=reply_subject or f"Re: {subject}", html_body=html)
        logger.info("Ответ агента ответственности отправлен → %s", sender)
