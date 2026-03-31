import base64
import email
import imaplib
import logging
from email.header import decode_header

from shared.logger import setup_logger  # noqa: F401 - keep logger consistent

logger = logging.getLogger("email_client")


def _decode_str(raw) -> str:
    parts = decode_header(raw or "")
    out = []
    for part, charset in parts:
        if isinstance(part, bytes):
            out.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(str(part))
    return "".join(out)


def fetch_unseen_emails(
    imap_host: str,
    imap_user: str,
    imap_password: str,
    imap_port: int = 993,
    folder: str = "INBOX",
) -> list[dict]:
    """
    Подключается к IMAP, забирает UNSEEN письма с вложениями.
    Помечает письма как прочитанные после обработки.
    Соединение гарантированно закрывается через finally.
    """
    emails = []
    M: imaplib.IMAP4_SSL | None = None
    try:
        M = imaplib.IMAP4_SSL(imap_host, imap_port)
        M.login(imap_user, imap_password)
        status, _ = M.select(folder)
        if status != "OK":
            logger.error("Не удалось выбрать IMAP-папку %r (status=%s)", folder, status)
            return emails
        _, uids = M.search(None, "UNSEEN")

        for uid in uids[0].split():
            try:
                _, data = M.fetch(uid, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])

                subject = _decode_str(msg.get("Subject", ""))
                from_ = _decode_str(msg.get("From", ""))
                date_str = msg.get("Date", "")

                body = ""
                attachments = []

                for part in msg.walk():
                    ct = part.get_content_type()
                    cd = str(part.get("Content-Disposition", ""))

                    if ct == "text/plain" and "attachment" not in cd:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="ignore")
                    elif ct == "text/html" and "attachment" not in cd and not body:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="ignore")
                    elif "attachment" in cd or part.get_filename():
                        filename = _decode_str(part.get_filename() or "unknown")
                        payload = part.get_payload(decode=True)
                        if payload:
                            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                            attachments.append({
                                "filename": filename,
                                "ext": ext,
                                "data": payload,
                                "mime": part.get_content_type(),
                                "b64": base64.b64encode(payload).decode(),
                            })

                M.store(uid, "+FLAGS", "\\\\Seen")
                emails.append({
                    "uid": uid.decode(),
                    "from": from_,
                    "subject": subject,
                    "date": date_str,
                    "body": body,
                    "attachments": attachments,
                })
            except Exception as e:
                logger.error(f"Ошибка обработки письма uid={uid}: {e}")

    except Exception as e:
        logger.error(f"IMAP подключение не удалось ({imap_host}): {e}")
    finally:
        if M is not None:
            try:
                M.logout()
            except Exception:
                pass

    return emails
