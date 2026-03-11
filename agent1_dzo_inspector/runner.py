import json
import os
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from shared.email_client import fetch_unseen_emails
from shared.file_extractor import extract_text_from_attachment
from shared.email_sender import send_email
from shared.telegram_notify import notify
from shared.logger import setup_logger
from agent1_dzo_inspector.agent import create_dzo_agent
from api.metrics import EMAILS_PROCESSED, EMAILS_ERRORS, POLL_CYCLES, JobTimer
import config

logger = setup_logger("agent_dzo")


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
        logger.info(f"Обрабатываю: '{mail['subject']}' от {mail['from']}")
        try:
            if not mail["attachments"]:
                send_email(
                    to=mail["from"],
                    subject=f"Re: {mail['subject']} — требуются вложения",
                    html_body="<p>В вашем письме не обнаружено вложений. Пожалуйста, приложите заявку.</p>",
                    from_addr=config.DZO_SMTP_FROM,
                )
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
                f"От: {mail['from']}\nТема: {mail['subject']}\n"
                f"Дата: {mail['date']}\nВремя: {datetime.now().isoformat()}\n\n"
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
                    if obs.get("emailHtml"):      email_html      = obs["emailHtml"]; decision = obs.get("decision", decision); reply_subject = obs.get("subject", "")
                    if obs.get("correctedHtml"): corrected_html  = obs["correctedHtml"]
                    if obs.get("tezisFormHtml"): tezis_html      = obs["tezisFormHtml"]
                    if obs.get("escalationHtml"): escalation_html = obs["escalationHtml"]; decision = obs.get("decision", decision)
                except Exception:
                    pass

            if not email_html and not escalation_html:
                email_html = f"<div style='font-family:Arial'>{result['output'].replace(chr(10), '<br>')}</div>"

            if "эскалация" in decision.lower():
                send_email(to=config.MANAGER_EMAIL, subject=reply_subject or "⚠️ Эскалация заявки ДЗО",
                           html_body=escalation_html or email_html, from_addr=config.DZO_SMTP_FROM)
                notify(f"⚠️ Эскалация от {mail['from']}\nТема: {mail['subject']}", level="warning")
            elif "полная" in decision.lower():
                send_email(to=mail["from"], subject=f"Заявка принята: {mail['subject']}",
                           html_body=email_html, from_addr=config.DZO_SMTP_FROM,
                           attachment_bytes=tezis_html.encode("utf-8") if tezis_html else None,
                           attachment_name="Заявка_Тезис.html" if tezis_html else None)
                notify(f"✅ Заявка принята от {mail['from']}", level="success")
            else:
                send_email(to=mail["from"],
                           subject=reply_subject or f"Запрос информации: {mail['subject']}",
                           html_body=email_html, from_addr=config.DZO_SMTP_FROM,
                           attachment_bytes=corrected_html.encode("utf-8") if corrected_html else None,
                           attachment_name="Проект_исправленной_заявки.html" if corrected_html else None)
                notify(f"ℹ️ Запрошены данные от {mail['from']}", level="info")

            EMAILS_PROCESSED.labels(agent="dzo").inc()
            logger.info(f"Обработано. Решение: {decision}")

        except Exception as e:
            EMAILS_ERRORS.labels(agent="dzo", error_type=type(e).__name__).inc()
            logger.error(f"Критическая ошибка: {e}")
            notify(f"🔴 Ошибка Агент-ДЗО\nОт: {mail['from']}\n{e}", level="error")


if __name__ == "__main__":
    process_dzo_emails()
