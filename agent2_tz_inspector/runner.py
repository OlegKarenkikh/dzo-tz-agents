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
    logger.info("Proverjayu vhodyaschie pisma (Inspektor TZ)...")
    POLL_CYCLES.labels(agent="tz").inc()

    emails = fetch_unseen_emails(
        imap_host=config.TZ_IMAP_HOST,
        imap_user=config.TZ_IMAP_USER,
        imap_password=config.TZ_IMAP_PASSWORD,
        imap_port=config.TZ_IMAP_PORT,
        folder=config.TZ_IMAP_FOLDER,
    )

    if not emails:
        logger.info("Novyh pisem net.")
        return

    for mail in emails:
        # fix #2: agent is created inside the loop so each email gets
        # its own isolated ConversationBufferWindowMemory instance.
        # Creating it outside caused history to leak between emails.
        agent = create_tz_agent()

        sender  = mail["from"]
        subject = mail["subject"]
        logger.info(f"Obrabatyvayu: '{subject}' ot {sender}")

        if not FORCE_REPROCESS:
            dup = db.find_duplicate_job("tz", sender, subject)
            if dup:
                logger.info(
                    f"[dedup] Propuskaem dubl: '{subject}' ot {sender} "
                    f"(ranee obrabotano {dup['created_at'][:10]}, reshenie: {dup.get('decision', '?')})"
                )
                continue

        job_id = db.create_job("tz", sender=sender, subject=subject)
        try:
            attachment_texts = []
            for att in mail["attachments"]:
                text = extract_text_from_attachment(att)
                attachment_texts.append(f"---- Fajl: {att['filename']} ----\n{text}")

            chat_input = (
                f"VHODYASCHEE TEHNICHESKOE ZADANIE\n"
                f"===========================================\n"
                f"Ot: {sender}\nTema: {subject}\n"
                f"Data: {mail['date']}\nVremya: {datetime.now(UTC).isoformat()}\n\n"
                f"-- TELO PISMA --\n{mail['body']}\n\n"
                f"-- TEKST TZ ({len(mail['attachments'])} vlozhenij) --\n"
                + "\n\n".join(attachment_texts)
            )

            with JobTimer("tz"):
                result = agent.invoke({"input": chat_input})

            email_html = corrected_tz_html = ""
            decision = "Trebuet dorabotki"
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

            if "sootvetstvuet" in decision.lower():
                send_email(
                    to=sender,
                    subject=reply_subject or f"TZ prinyato: {subject}",
                    html_body=email_html,
                    from_addr=config.TZ_SMTP_FROM,
                )
                notify(f"TZ prinyato ot {sender}", level="success")
            else:
                send_email(
                    to=sender,
                    subject=reply_subject or f"Zamechaniya po TZ: {subject}",
                    html_body=email_html,
                    from_addr=config.TZ_SMTP_FROM,
                    attachment_bytes=corrected_tz_html.encode("utf-8") if corrected_tz_html else None,
                    attachment_name="TZ_s_zamechaniyami.html" if corrected_tz_html else None,
                )
                notify(f"TZ otpravleno na dorabotku {sender}", level="info")

            db.update_job(
                job_id, status="done", decision=decision,
                result={
                    "attachments": len(mail["attachments"]),
                    "overall_status": json_report.get("overall_status", ""),
                    "sections_found": json_report.get("sections_found", []),
                },
            )
            EMAILS_PROCESSED.labels(agent="tz").inc()
            logger.info(f"Obrabotano. Reshenie: {decision}")

        except Exception as e:
            EMAILS_ERRORS.labels(agent="tz", error_type=type(e).__name__).inc()
            db.update_job(job_id, status="error", error=str(e))
            logger.error(f"Kriticheskaya oshibka: {e}")
            notify(f"Oshibka Agent-TZ\nOt: {sender}\n{e}", level="error")


if __name__ == "__main__":
    process_tz_emails()
