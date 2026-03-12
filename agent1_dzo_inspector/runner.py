import json
import os
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()

import config  # noqa: E402
import shared.database as db  # noqa: E402
from agent1_dzo_inspector.agent import create_dzo_agent  # noqa: E402
from api.metrics import EMAILS_ERRORS, EMAILS_PROCESSED, JobTimer, POLL_CYCLES  # noqa: E402
from shared.email_client import fetch_unseen_emails  # noqa: E402
from shared.email_sender import send_email  # noqa: E402
from shared.file_extractor import extract_text_from_attachment  # noqa: E402
from shared.logger import setup_logger  # noqa: E402
from shared.telegram_notify import notify  # noqa: E402

logger = setup_logger("agent_dzo")

# Если FORCE_REPROCESS=true — игнорировать дубликаты и обрабатывать всегда заново
FORCE_REPROCESS = os.getenv("FORCE_REPROCESS", "false").lower() == "true"


def process_dzo_emails():
    logger.info("Проверяю входящие письма (Инспектор Заявок ДЗО)...")
    POLL_CYCLES.labels(agent="dzo").inc()

    emails = fetch_unseen_emails(
        imap_host=config.DZO_IMAP_HOST,
        imap_user=config.DZO_IMAP_USER,
        imap_password=config.DZO_IMAP_PASSWORD,
        imap_port=config.DZO_IMAP_PORT,
        folder=config.DZO_IMAP_FOLDER,
    )

    if not emails:
        logger.info("Новых писем нет.")
        return

    agent = create_dzo_agent()

    for mail in emails:
        sender  = mail["from"]
        subject = mail["subject"]
        logger.info(f"Обрабатываю: '{subject}' от {sender}")

        # Дедупликация: daemon не интерактивен, поэтому дубликаты пропускаем автоматически
        if not FORCE_REPROCESS:
            dup = db.find_duplicate_job("dzo", sender, subject)
            if dup:
                logger.info(
                    f"[dedup] Пропускаем дубль: '{subject}' от {sender} "
                    f"(ранее обработано {dup['created_at'][:10]}, решение: {dup.get('decision', '?')})"
                )
                continue

        job_id = db.create_job("dzo", sender=sender, subject=subject)
        try:
            if not mail["attachments"]:
                send_email(
                    to=sender,
                    subject=f"Re: {subject} — требуются вложения",
                    html_body="<p>В вашем письме не обнаружено вложений. Пожалуйста, приложите заявку.</p>",
                    from_addr=config.DZO_SMTP_FROM,
                )
                db.update_job(job_id, status="done", decision="Требуется доработка",
                              result={"reason": "no_attachments"})
                EMAILS_PROCESSED.labels(agent="dzo").inc()
                continue

            attachment_texts = []
            has_tz   = False
            has_spec = False
            for att in mail["attachments"]:
                name_lower = att["filename"].lower()
                if any(k in name_lower for k in ["тз", "tz", "техзадание", "tor", "техническое"]):
                    has_tz = True
                if any(k in name_lower for k in ["спец", "spec", "перечень", "ведомость"]):
                    has_spec = True
                text = extract_text_from_attachment(att)
                attachment_texts.append(f"──── Файл: {att['filename']} ────\n{text}")

            chat_input = (
                f"📧 ВХОДЯЩАЯ ЗАЯВКА ОТ ДЗО\n"
                f"═══════════════════════════════════════════\n"
                f"От: {sender}\nТема: {subject}\n"
                f"Дата: {mail['date']}\nВремя: {datetime.now(UTC).isoformat()}\n\n"
                f"── ТЕЛО ПИСЬМА ──\n{mail['body']}\n\n"
                f"── ПРЕДВАРИТЕЛЬНАЯ ПРОВЕРКА ──\n"
                f"Всего вложений: {len(mail['attachments'])}\n"
                f"Файл ТЗ: {'DA' if has_tz else 'НЕТ'}\n"
                f"Спецификация: {'DA' if has_spec else 'НЕТ'}\n\n"
                + "\n\n".join(attachment_texts)
            )

            with JobTimer("dzo"):
                result = agent.invoke({"input": chat_input})

            email_html = corrected_html = tezis_html = escalation_html = ""
            decision = "Требуется доработка"
            reply_subject = ""

            for step in result.get("intermediate_steps", []):
                try:
                    obs = json.loads(step[1]) if isinstance(step[1], str) else step[1]
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
                except Exception:
                    pass

            if not email_html and not escalation_html:
                email_html = f"<div style='font-family:Arial'>{result['output'].replace(chr(10), '<br>')}</div>"

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

            db.update_job(
                job_id, status="done", decision=decision,
                result={"has_tz": has_tz, "has_spec": has_spec, "attachments": len(mail["attachments"])},
            )
            EMAILS_PROCESSED.labels(agent="dzo").inc()
            logger.info(f"Обработано. Решение: {decision}")

        except Exception as e:
            EMAILS_ERRORS.labels(agent="dzo", error_type=type(e).__name__).inc()
            db.update_job(job_id, status="error", error=str(e))
            logger.error(f"Критическая ошибка: {e}")
            notify(f"🔴 Ошибка Агент-ДЗО\nОт: {sender}\n{e}", level="error")


if __name__ == "__main__":
    process_dzo_emails()
