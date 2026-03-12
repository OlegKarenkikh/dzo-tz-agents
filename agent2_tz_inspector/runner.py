import json
import os
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()

import config  # noqa: E402
import shared.database as db  # noqa: E402
from agent2_tz_inspector.agent import create_tz_agent  # noqa: E402
from api.metrics import EMAILS_ERRORS, EMAILS_PROCESSED, JobTimer, POLL_CYCLES  # noqa: E402
from shared.email_client import fetch_unseen_emails  # noqa: E402
from shared.email_sender import send_email  # noqa: E402
from shared.file_extractor import extract_text_from_attachment  # noqa: E402
from shared.logger import setup_logger  # noqa: E402
from shared.telegram_notify import notify  # noqa: E402

logger = setup_logger("agent_tz")

FORCE_REPROCESS = os.getenv("FORCE_REPROCESS", "false").lower() == "true"


def process_tz_emails():
    logger.info(
        "\u041f\u0440\u043e\u0432\u0435\u0440\u044f\u044e "
        "\u0432\u0445\u043e\u0434\u044f\u0449\u0438\u0435 "
        "\u043f\u0438\u0441\u044c\u043c\u0430 "
        "(\u0418\u043d\u0441\u043f\u0435\u043a\u0442\u043e\u0440 "
        "\u0422\u0417)..."
    )
    POLL_CYCLES.labels(agent="tz").inc()

    emails = fetch_unseen_emails(
        imap_host=config.TZ_IMAP_HOST,
        imap_user=config.TZ_IMAP_USER,
        imap_password=config.TZ_IMAP_PASSWORD,
        imap_port=config.TZ_IMAP_PORT,
        folder=config.TZ_IMAP_FOLDER,
    )

    if not emails:
        logger.info("\u041d\u043e\u0432\u044b\u0445 \u043f\u0438\u0441\u0435\u043c \u043d\u0435\u0442.")
        return

    for mail in emails:
        # fix #2: agent created inside loop - each email gets its own
        # isolated ConversationBufferWindowMemory instance.
        agent = create_tz_agent()

        sender  = mail["from"]
        subject = mail["subject"]
        logger.info("Processing: '%s' from %s", subject, sender)

        if not FORCE_REPROCESS:
            dup = db.find_duplicate_job("tz", sender, subject)
            if dup:
                logger.info(
                    "[dedup] Skipping duplicate: '%s' from %s "
                    "(processed %s, decision: %s)",
                    subject, sender,
                    dup["created_at"][:10], dup.get("decision", "?"),
                )
                continue

        job_id = db.create_job("tz", sender=sender, subject=subject)
        try:
            attachment_texts = []
            for att in mail["attachments"]:
                text = extract_text_from_attachment(att)
                attachment_texts.append(f"---- File: {att['filename']} ----\n{text}")

            chat_input = (
                "INCOMING TECHNICAL SPECIFICATION\n"
                "===========================================\n"
                f"From: {sender}\nSubject: {subject}\n"
                f"Date: {mail['date']}\nTime: {datetime.now(UTC).isoformat()}\n\n"
                f"-- EMAIL BODY --\n{mail['body']}\n\n"
                f"-- TZ TEXT ({len(mail['attachments'])} attachments) --\n"
                + "\n\n".join(attachment_texts)
            )

            with JobTimer("tz"):
                result = agent.invoke({"input": chat_input})

            email_html = corrected_tz_html = ""
            # Keep Cyrillic decision value so test assertion
            # 'sootvetstvuet' / '\u0441\u043e\u043e\u0442\u0432\u0435\u0442\u0441\u0442\u0432\u0443\u0435\u0442'
            # works against decision.lower()
            decision = "\u0422\u0440\u0435\u0431\u0443\u0435\u0442 \u0434\u043e\u0440\u0430\u0431\u043e\u0442\u043a\u0438"
            reply_subject = ""
            json_report: dict = {}

            for step in result.get("intermediate_steps", []):
                try:
                    obs = json.loads(step[1]) if isinstance(step[1], str) else step[1]
                    if obs.get("emailHtml"):
                        email_html = obs["emailHtml"]
                        decision = obs.get("decision", decision)
                        reply_subject = obs.get("subject", "")
                    if obs.get("html"):
                        corrected_tz_html = obs["html"]
                    if obs.get("overall_status"):
                        json_report = obs
                except Exception:
                    pass

            if not email_html:
                email_html = f"<div style='font-family:Arial'>{result['output'].replace(chr(10), '<br>')}</div>"

            # decision from agent contains '\u0441\u043e\u043e\u0442\u0432\u0435\u0442\u0441\u0442\u0432\u0443\u0435\u0442'
            if "\u0441\u043e\u043e\u0442\u0432\u0435\u0442\u0441\u0442\u0432\u0443\u0435\u0442" in decision.lower():
                send_email(
                    to=sender,
                    subject=reply_subject or f"\u0422\u0417 \u043f\u0440\u0438\u043d\u044f\u0442\u043e: {subject}",
                    html_body=email_html,
                    from_addr=config.TZ_SMTP_FROM,
                )
                notify(f"\u2705 \u0422\u0417 \u043f\u0440\u0438\u043d\u044f\u0442\u043e \u043e\u0442 {sender}", level="success")
            else:
                send_email(
                    to=sender,
                    subject=reply_subject or f"\u0417\u0430\u043c\u0435\u0447\u0430\u043d\u0438\u044f \u043f\u043e \u0422\u0417: {subject}",
                    html_body=email_html,
                    from_addr=config.TZ_SMTP_FROM,
                    attachment_bytes=corrected_tz_html.encode("utf-8") if corrected_tz_html else None,
                    attachment_name="\u0422\u0417_\u0441_\u0437\u0430\u043c\u0435\u0447\u0430\u043d\u0438\u044f\u043c\u0438.html" if corrected_tz_html else None,
                )
                notify(f"\u2139\ufe0f \u0422\u0417 \u043d\u0430 \u0434\u043e\u0440\u0430\u0431\u043e\u0442\u043a\u0443 {sender}", level="info")

            db.update_job(
                job_id, status="done", decision=decision,
                result={
                    "attachments": len(mail["attachments"]),
                    "overall_status": json_report.get("overall_status", ""),
                    "sections_found": json_report.get("sections_found", []),
                },
            )
            EMAILS_PROCESSED.labels(agent="tz").inc()
            logger.info("Processed. Decision: %s", decision)

        except Exception as e:
            EMAILS_ERRORS.labels(agent="tz", error_type=type(e).__name__).inc()
            db.update_job(job_id, status="error", error=str(e))
            logger.error("Critical error: %s", e)
            notify(f"Agent-TZ error\nFrom: {sender}\n{e}", level="error")


if __name__ == "__main__":
    process_tz_emails()
