import json
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

import config  # noqa: E402
from agent2_tz_inspector.agent import create_tz_agent  # noqa: E402
from api.metrics import EMAILS_ERRORS, EMAILS_PROCESSED, JobTimer, POLL_CYCLES  # noqa: E402
from shared.email_client import fetch_unseen_emails  # noqa: E402
from shared.email_sender import send_email  # noqa: E402
from shared.file_extractor import extract_text_from_attachment  # noqa: E402
from shared.logger import setup_logger  # noqa: E402
from shared.telegram_notify import notify  # noqa: E402

logger = setup_logger("agent_tz")


def process_tz_emails():
    logger.info("Проверяю входящие письма (Инспектор ТЗ)...")
    POLL_CYCLES.labels(agent="tz").inc()

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
        logger.info(f"Обрабатываю: '{mail['subject']}' от {mail['from']}")
        try:
            attachment_texts = []
            for att in mail["attachments"]:
                text = extract_text_from_attachment(att)
                attachment_texts.append(f"──── Файл: {att['filename']} ────\n{text}")

            chat_input = (
                f"📝 ВХОДЯЩЕЕ ТЕХНИЧЕСКОЕ ЗАДАНИЕ\n"
                f"═══════════════════════════════════════════\n"
                f"От: {mail['from']}\nТема: {mail['subject']}\n"
                f"Дата: {mail['date']}\nВремя: {datetime.now().isoformat()}\n\n"
                f"── ТЕЛО ПИСЬМА ──\n{mail['body']}\n\n"
                f"── ТЕКСТ ТЗ ({len(mail['attachments'])} вложений) ──\n"
                + "\n\n".join(attachment_texts)
            )

            with JobTimer("tz"):
                result = agent.invoke({"input": chat_input})

            # Структура ответов инструментов:
            #   generate_email_to_dzo   -> {emailHtml, decision, subject}
            #   generate_corrected_tz   -> {html, title}       <-- ключ 'html', не 'correctedHtml'!
            #   generate_json_report    -> {timestamp, overall_status, ...}
            email_html = corrected_tz_html = ""
            decision = "Требует доработки"
            reply_subject = ""

            for step in result.get("intermediate_steps", []):
                try:
                    obs = json.loads(step[1]) if isinstance(step[1], str) else step[1]
                    if obs.get("emailHtml"):
                        email_html = obs["emailHtml"]
                        decision = obs.get("decision", decision)
                        reply_subject = obs.get("subject", "")
                    # generate_corrected_tz возвращает поле 'html' (не 'correctedHtml')
                    if obs.get("html"):
                        corrected_tz_html = obs["html"]
                except Exception:
                    pass

            if not email_html:
                email_html = f"<div style='font-family:Arial'>{result['output'].replace(chr(10), '<br>')}</div>"

            if "соответствует" in decision.lower():
                send_email(
                    to=mail["from"],
                    subject=reply_subject or f"ТЗ принято: {mail['subject']}",
                    html_body=email_html,
                    from_addr=config.TZ_SMTP_FROM,
                )
                notify(f"✅ ТЗ принято от {mail['from']}", level="success")
            else:
                send_email(
                    to=mail["from"],
                    subject=reply_subject or f"Замечания по ТЗ: {mail['subject']}",
                    html_body=email_html,
                    from_addr=config.TZ_SMTP_FROM,
                    attachment_bytes=corrected_tz_html.encode("utf-8") if corrected_tz_html else None,
                    attachment_name="ТЗ_с_замечаниями.html" if corrected_tz_html else None,
                )
                notify(f"ℹ️ ТЗ отправлено на доработку {mail['from']}", level="info")

            EMAILS_PROCESSED.labels(agent="tz").inc()
            logger.info(f"Обработано. Решение: {decision}")

        except Exception as e:
            EMAILS_ERRORS.labels(agent="tz", error_type=type(e).__name__).inc()
            logger.error(f"Критическая ошибка: {e}")
            notify(f"🔴 Ошибка Агент-ТЗ\nОт: {mail['from']}\n{e}", level="error")


if __name__ == "__main__":
    process_tz_emails()
