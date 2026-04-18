"""agent7_osgop_parser/runner.py"""
from __future__ import annotations
import json
from typing import Any

import config
from shared.email_sender import send_email
from shared.logger import setup_logger
from shared.runner_base import BaseEmailRunner
from .agent import create_osgop_agent

logger = setup_logger("runner_osgop")


class OsgopParserRunner(BaseEmailRunner):
    """Runner для агента разбора полисов ОСГОП."""

    @property
    def agent_id(self) -> str:
        return "osgop"

    @property
    def imap_config(self) -> dict:
        return {
            "host": config.IMAP_HOST,
            "user": getattr(config, "OSGOP_IMAP_USER", config.IMAP_USER),
            "password": getattr(config, "OSGOP_IMAP_PASSWORD", config.IMAP_PASSWORD),
            "port": config.IMAP_PORT,
            "folder": getattr(config, "OSGOP_IMAP_FOLDER", "INBOX"),
        }

    def create_agent(self) -> Any:
        return create_osgop_agent()

    def build_chat_input(self, mail: dict, attachment_texts: list[str]) -> str:
        body = "\n".join(attachment_texts) or mail.get("body", "")
        sep = "=" * 60
        return (
            f"ВХОДЯЩИЙ ПОЛИС ОСГОП\n"
            f"От: {mail.get('from', '')}\n"
            f"Тема: {mail.get('subject', '')}\n"
            f"{sep}\n"
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
                artifacts["osgop_data"] = obs.get("data", {})
            elif obs.get("valid") is False:
                decision = "Требуется проверка"
                artifacts["validation_errors"] = obs.get("errors", [])
                artifacts["osgop_data"] = obs.get("data", {})
            if obs.get("error"):
                decision = "Ошибка разбора"
                artifacts["error"] = obs["error"]
        if not decision:
            output = result.get("output", "")
            decision = "Разбор завершён" if "разбор завершён" in output.lower() else "Требуется проверка"
        data = artifacts.get("osgop_data", {})
        policy = data.get("policy_number", "") if isinstance(data, dict) else ""
        reply_subject = f"Результат разбора ОСГОП: {policy}" if policy else "Результат разбора ОСГОП"
        return decision, artifacts, reply_subject

    def send_reply(self, sender, subject, reply_subject, decision, artifacts) -> None:
        data = artifacts.get("osgop_data", {})
        errors = artifacts.get("validation_errors", [])
        error_msg = artifacts.get("error", "")
        div_style = "font-family:Arial;font-size:14px"
        if error_msg:
            html = f'<div style="{div_style}"><p><strong>Ошибка: {error_msg}</strong></p></div>'
        elif errors:
            eb = "\n".join(f"  - {e}" for e in errors)
            html = (
                f'<div style="{div_style}">'
                f"<p><strong>Решение: {decision}</strong></p>"
                f'<pre style="background:#fff3cd;padding:10px">{eb}</pre>'
                f"<pre>{json.dumps(data, ensure_ascii=False, indent=2)}</pre></div>"
            )
        else:
            html = (
                f'<div style="{div_style}">'
                f"<p><strong>Разбор ОСГОП завершён.</strong></p>"
                f"<pre>{json.dumps(data, ensure_ascii=False, indent=2)}</pre></div>"
            )
        send_email(to=sender, subject=reply_subject or f"Re: {subject}", html_body=html)
        logger.info("Ответ агента ОСГОП отправлен: %s", sender)
