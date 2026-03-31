import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
from shared.logger import setup_logger

logger = setup_logger("email_sender")

_SMTP_TIMEOUT = 30


def send_email(
    to: str,
    subject: str,
    html_body: str,
    from_addr: str | None = None,
    attachment_bytes: bytes | None = None,
    attachment_name: str | None = None,
) -> bool:
    """Отправляет HTML-письмо с опциональным вложением.

    Returns:
        True если отправка успешна, False при ошибке.
    """
    sender = from_addr or config.DZO_SMTP_FROM
    msg = MIMEMultipart("mixed")
    msg["From"] = sender
    msg["To"] = to
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
        smtp_host = config.SMTP_HOST
        smtp_port = config.SMTP_PORT
        smtp_user = config.SMTP_USER
        smtp_password = config.SMTP_PASSWORD
        if not smtp_user or not smtp_password:
            logger.error("SMTP_USER или SMTP_PASSWORD не настроены — отправка невозможна")
            return False
        with smtplib.SMTP(smtp_host, smtp_port, timeout=_SMTP_TIMEOUT) as s:
            s.starttls()
            s.login(smtp_user, smtp_password)
            s.send_message(msg)
        logger.info(f"Письмо отправлено: {to} / {subject}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки письма: {e}")
        return False
