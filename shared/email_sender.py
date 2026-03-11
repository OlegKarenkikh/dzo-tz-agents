import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from shared.logger import setup_logger

logger = setup_logger("email_sender")


def send_email(
    to: str,
    subject: str,
    html_body: str,
    from_addr: str = None,
    attachment_bytes: bytes = None,
    attachment_name: str = None,
):
    """Отправляет HTML-письмо с опциональным вложением."""
    sender = from_addr or os.getenv("SENDER_EMAIL", "ucz@company.ru")
    msg = MIMEMultipart("mixed")
    msg["From"]    = sender
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if attachment_bytes and attachment_name:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment_bytes)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{attachment_name}"',
        )
        msg.attach(part)

    try:
        with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", 587))) as s:
            s.starttls()
            s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD"))
            s.send_message(msg)
        logger.info(f"Письмо отправлено: {to} / {subject}")
    except Exception as e:
        logger.error(f"Ошибка отправки письма: {e}")
