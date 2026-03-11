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
from agent2_tz_inspector.agent import create_tz_agent
import config

logger = setup_logger("agent_tz")


def process_tz_emails():
    logger.info("Проверяю входящие письма (Инспектор ТЗ)...")
    emails = fetch_unseen_emails(
        imap_host=config.TZ_IMAP_HOST,
        imap_user=config.TZ_IMAP_USER,
        imap_password=config.TZ_IMAP_PASSWORD,
        imap_port=config.TZ_IMAP_PORT,
        folder=config.TZ_IMAP_FOLDER,
    )

    if not emails:
        logger.info("Новых писем нет.")
        return

    agent = create_tz_agent()

    for mail in emails:
        logger.info(f"Обрабатываю ТЗ: '{mail['subject']}' от {mail['from']}")
        try:
            if not mail["attachments"]:
                continue

            attachment_texts = []
            for att in mail["attachments"]:
                text = extract_text_from_attachment(att)
                attachment_texts.append(f"──── Файл: {att['filename']} ────\n{text}")

            chat_input = (
                f"📧 МЕТАДАННЫЕ ПИСЬМА:\n"
                f"От: {mail['from']}\n"
                f"Тема: {mail['subject']}\n"
                f"Дата: {mail['date']}\n"
                f"Тело письма: {mail['body']}\n\n"
                f"═══════════════════════════════════════════\n"
                f"📎 ВЛОЖЕНИЯ ({len(mail['attachments'])} шт.):\n"
                f"═══════════════════════════════════════════\n\n"
                + "\n\n".join(attachment_texts)
            )

            result         = agent.invoke({"input": chat_input})
            email_html     = ""
            corrected_html = ""
            decision       = "Требует доработки"
            reply_subject  = ""

            for step in result.get("intermediate_steps", []):
                try:
                    obs = json.loads(step[1]) if isinstance(step[1], str) else step[1]
                    if obs.get("emailHtml"): email_html = obs["emailHtml"]; decision = obs.get("decision", decision); reply_subject = obs.get("subject", "")
                    if obs.get("html"):      corrected_html = obs["html"]
                except Exception:
                    pass

            if not email_html:
                email_html = f"<div style='font-family:Arial'>{result['output'].replace(chr(10), '<br>')}</div>"

            send_email(
                to=mail["from"],
                subject=reply_subject or f"Результат проверки ТЗ: {mail['subject']}",
                html_body=email_html,
                from_addr=config.TZ_SMTP_FROM,
                attachment_bytes=corrected_html.encode("utf-8") if corrected_html else None,
                attachment_name="Исправленное_ТЗ.html" if corrected_html else None,
            )

            notify(f"{'✅' if 'Соответствует' in decision else 'ℹ️'} ТЗ проверено\nОт: {mail['from']}\nРешение: {decision}", level="success" if "Соответствует" in decision else "info")
            logger.info(f"ТЗ обработано. Решение: {decision}")

        except Exception as e:
            logger.error(f"Критическая ошибка при обработке ТЗ: {e}")
            notify(f"🔴 Ошибка Агент-ТЗ\nОт: {mail['from']}\n{e}", level="error")


if __name__ == "__main__":
    process_tz_emails()
