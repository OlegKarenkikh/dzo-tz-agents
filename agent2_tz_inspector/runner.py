import json
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()

import config  # noqa: E402
from agent2_tz_inspector.agent import create_tz_agent  # noqa: E402
from shared.email_sender import send_email  # noqa: E402
from shared.logger import setup_logger  # noqa: E402
from shared.runner_base import BaseEmailRunner  # noqa: E402
from shared.telegram_notify import notify  # noqa: E402

_runner_logger = setup_logger("agent_tz_runner")


class TzEmailRunner(BaseEmailRunner):
    """Конкретный runner для агента ТЗ — реализует BaseEmailRunner."""

    @property
    def agent_id(self) -> str:
        return "tz"

    @property
    def imap_config(self) -> dict:
        return {
            "host": config.TZ_IMAP_HOST,
            "user": config.TZ_IMAP_USER,
            "password": config.TZ_IMAP_PASSWORD,
            "port": config.TZ_IMAP_PORT,
            "folder": config.TZ_IMAP_FOLDER,
        }

    def create_agent(self):
        return create_tz_agent()

    def build_chat_input(self, mail: dict, attachment_texts: list[str]) -> str:
        return (
            "INCOMING TECHNICAL SPECIFICATION\n"
            "===========================================\n"
            f"От: {mail['from']}\nТема: {mail['subject']}\n"
            f"Дата: {mail['date']}\nВремя: {datetime.now(UTC).isoformat()}\n\n"
            f"-- ТЕЛО ПИСЬМА --\n{mail['body']}\n\n"
            f"-- ТЕКСТ ТЗ ({len(mail.get('attachments', []))} вложений) --\n"
            + "\n\n".join(attachment_texts)
        )

    def parse_steps(self, steps: list, result: dict, job_id: str) -> tuple[str, dict, str]:
        email_html = corrected_tz_html = ""
        decision = "Требует доработки"
        reply_subject = ""
        json_report: dict = {}
        for step_idx, step in enumerate(steps, start=1):
            try:
                obs = json.loads(step[1]) if isinstance(step[1], str) else step[1]
                if not isinstance(obs, dict):
                    continue
                if obs.get("emailHtml"):
                    email_html = obs["emailHtml"]
                    decision = obs.get("decision", decision)
                    reply_subject = obs.get("subject", "")
                if obs.get("html"):
                    corrected_tz_html = obs["html"]
                if obs.get("overall_status"):
                    json_report = obs
            except (json.JSONDecodeError, TypeError, KeyError, IndexError) as exc:
                _runner_logger.warning(
                    "[%s] parse_steps: ошибка разбора шага %d: %s",
                    job_id, step_idx, exc,
                )
        if not email_html:
            email_html = (
                "<div style='font-family:Arial'>"
                + result.get("output", "").replace(chr(10), "<br>")
                + "</div>"
            )
        return decision, {
            "email_html": email_html,
            "corrected_tz_html": corrected_tz_html,
            "json_report": json_report,
        }, reply_subject

    def send_reply(
        self,
        sender: str,
        subject: str,
        reply_subject: str,
        decision: str,
        artifacts: dict,
    ) -> None:
        email_html = artifacts.get("email_html", "")
        corrected_tz_html = artifacts.get("corrected_tz_html", "")
        if "соответствует" in decision.lower():
            send_email(
                to=sender,
                subject=reply_subject or f"ТЗ принято: {subject}",
                html_body=email_html,
                from_addr=config.TZ_SMTP_FROM,
            )
            notify("ТЗ принято от " + sender, level="success")
        else:
            send_email(
                to=sender,
                subject=reply_subject or f"Замечания по ТЗ: {subject}",
                html_body=email_html,
                from_addr=config.TZ_SMTP_FROM,
                attachment_bytes=corrected_tz_html.encode("utf-8") if corrected_tz_html else None,
                attachment_name="ТЗ_с_замечаниями.html" if corrected_tz_html else None,
            )
            notify("ТЗ на доработку: " + sender, level="info")

    def db_result_fields(self, mail: dict, artifacts: dict) -> dict:
        json_report = artifacts.get("json_report", {})
        return {
            "attachments": len(mail.get("attachments", [])),
            "overall_status": json_report.get("overall_status", ""),
            "sections_found": json_report.get("sections_found", []),
        }


def process_tz_emails() -> None:
    """Точка входа для агента ТЗ — делегирует в TzEmailRunner."""
    TzEmailRunner().process_emails()


if __name__ == "__main__":
    process_tz_emails()
