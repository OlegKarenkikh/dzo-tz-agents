import json
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()

import config  # noqa: E402
import shared.database as db  # noqa: E402
from agent1_dzo_inspector.agent import create_dzo_agent  # noqa: E402
from shared.email_sender import send_email  # noqa: E402
from shared.logger import setup_logger  # noqa: E402
from shared.runner_base import BaseEmailRunner  # noqa: E402
from shared.telegram_notify import notify  # noqa: E402

_runner_logger = setup_logger("agent_dzo_runner")


class DzoEmailRunner(BaseEmailRunner):
    """Конкретный runner для агента ДЗО — реализует BaseEmailRunner."""

    def __init__(self) -> None:
        self._has_tz: bool = False
        self._has_spec: bool = False

    @property
    def agent_id(self) -> str:
        return "dzo"

    @property
    def imap_config(self) -> dict:
        return {
            "host": config.DZO_IMAP_HOST,
            "user": config.DZO_IMAP_USER,
            "password": config.DZO_IMAP_PASSWORD,
            "port": config.DZO_IMAP_PORT,
            "folder": config.DZO_IMAP_FOLDER,
        }

    def create_agent(self):
        return create_dzo_agent()

    def handle_no_attachments(self, sender: str, subject: str, job_id: str) -> bool:
        send_email(
            to=sender,
            subject=f"Re: {subject} — требуются вложения",
            html_body="<p>В вашем письме не обнаружено вложений. Пожалуйста, приложите заявку.</p>",
            from_addr=config.DZO_SMTP_FROM,
        )
        db.update_job(job_id, status="done", decision="Требуется доработка",
                      result={"reason": "no_attachments"})
        return True

    def build_chat_input(self, mail: dict, attachment_texts: list[str]) -> str:
        has_tz = has_spec = False
        for att in mail.get("attachments", []):
            name_lower = att["filename"].lower()
            if any(k in name_lower for k in ["тз", "tz", "техзадание", "tor", "техническое"]):
                has_tz = True
            if any(k in name_lower for k in ["спец", "spec", "перечень", "ведомость"]):
                has_spec = True
        self._has_tz = has_tz
        self._has_spec = has_spec
        return (
            f"📧 ВХОДЯЩАЯ ЗАЯВКА ОТ ДЗО\n"
            f"═══════════════════════════════════════════\n"
            f"От: {mail['from']}\nТема: {mail['subject']}\n"
            f"Дата: {mail['date']}\nВремя: {datetime.now(UTC).isoformat()}\n\n"
            f"── ТЕЛО ПИСЬМА ──\n{mail['body']}\n\n"
            f"── ПРЕДВАРИТЕЛЬНАЯ ПРОВЕРКА ──\n"
            f"Всего вложений: {len(mail.get('attachments', []))}\n"
            f"Файл ТЗ: {'ДА' if has_tz else 'НЕТ'}\n"
            f"Спецификация: {'ДА' if has_spec else 'НЕТ'}\n\n"
            + "\n\n".join(attachment_texts)
        )

    def parse_steps(self, steps: list, result: dict, job_id: str) -> tuple[str, dict, str]:
        email_html = corrected_html = tezis_html = escalation_html = ""
        decision = "Требуется доработка"
        reply_subject = ""
        for step_idx, step in enumerate(steps, start=1):
            try:
                obs = json.loads(step[1]) if isinstance(step[1], str) else step[1]
                if not isinstance(obs, dict):
                    continue
                if obs.get("emailHtml"):
                    email_html = obs["emailHtml"]
                    decision = obs.get("decision", decision)
                    reply_subject = obs.get("subject", "")
                if obs.get("correctedHtml"):
                    corrected_html = obs["correctedHtml"]
                if obs.get("tezisFormHtml"):
                    tezis_html = obs["tezisFormHtml"]
                if obs.get("escalationHtml"):
                    escalation_html = obs["escalationHtml"]
                    decision = obs.get("decision", decision)
            except (json.JSONDecodeError, TypeError, KeyError, IndexError) as exc:
                _runner_logger.warning(
                    "[%s] parse_steps: ошибка разбора шага %d: %s",
                    job_id, step_idx, exc,
                )
        if not email_html and not escalation_html:
            email_html = (
                f"<div style='font-family:Arial'>"
                f"{result.get('output', '').replace(chr(10), '<br>')}</div>"
            )
        return decision, {
            "email_html": email_html,
            "corrected_html": corrected_html,
            "tezis_html": tezis_html,
            "escalation_html": escalation_html,
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
        corrected_html = artifacts.get("corrected_html", "")
        tezis_html = artifacts.get("tezis_html", "")
        escalation_html = artifacts.get("escalation_html", "")
        if "эскалация" in decision.lower():
            send_email(
                to=config.MANAGER_EMAIL,
                subject=reply_subject or "⚠️ Эскалация заявки ДЗО",
                html_body=escalation_html or email_html,
                from_addr=config.DZO_SMTP_FROM,
            )
            notify(f"⚠️ Эскалация от {sender}\nТема: {subject}", level="warning")
        elif "полная" in decision.lower():
            send_email(
                to=sender,
                subject=f"Заявка принята: {subject}",
                html_body=email_html,
                from_addr=config.DZO_SMTP_FROM,
                attachment_bytes=tezis_html.encode("utf-8") if tezis_html else None,
                attachment_name="Заявка_Тезис.html" if tezis_html else None,
            )
            notify(f"✅ Заявка принята от {sender}", level="success")
        else:
            send_email(
                to=sender,
                subject=reply_subject or f"Запрос информации: {subject}",
                html_body=email_html,
                from_addr=config.DZO_SMTP_FROM,
                attachment_bytes=corrected_html.encode("utf-8") if corrected_html else None,
                attachment_name="Проект_исправленной_заявки.html" if corrected_html else None,
            )
            notify(f"ℹ️ Запрошены данные от {sender}", level="info")

    def db_result_fields(self, mail: dict, artifacts: dict) -> dict:
        return {
            "has_tz": self._has_tz,
            "has_spec": self._has_spec,
            "attachments": len(mail.get("attachments", [])),
        }


def process_dzo_emails() -> None:
    """Точка входа для агента ДЗО — делегирует в DzoEmailRunner."""
    DzoEmailRunner().process_emails()


if __name__ == "__main__":
    process_dzo_emails()
