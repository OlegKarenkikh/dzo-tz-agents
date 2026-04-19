"""
shared/email_client.py
Email integration for fetching emails from IMAP/Exchange/MS Graph backends.

Provides:
- Legacy ``fetch_unseen_emails()`` for IMAP (used by DZO/TZ runners)
- New ``EmailClient`` with async support and configurable backend

Env vars (for EmailClient):
  EMAIL_BACKEND  — imap | exchange | graph  (default: imap)
  EMAIL_HOST     — IMAP/Exchange host
  EMAIL_PORT     — port (default: 993)
  EMAIL_USER     — username / email
  EMAIL_PASSWORD — password or app token
  EMAIL_USE_SSL  — true/false (default: true)
"""
from __future__ import annotations

import asyncio
import base64
import email
import imaplib
import logging
import os
from dataclasses import dataclass, field
from email.header import decode_header
from typing import Any

from shared.logger import setup_logger  # noqa: F401 - keep logger consistent

logger = logging.getLogger("email_client")


# ---------------------------------------------------------------------------
#  Helpers (legacy)
# ---------------------------------------------------------------------------

def _decode_str(raw) -> str:
    parts = decode_header(raw or "")
    out = []
    for part, charset in parts:
        if isinstance(part, bytes):
            out.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(str(part))
    return "".join(out)


# ---------------------------------------------------------------------------
#  Legacy IMAP function (used by runner_base.py)
# ---------------------------------------------------------------------------

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
    emails: list[dict] = []
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
                raw_part = data[0][1] if isinstance(data[0][1], (bytes, bytearray)) else b""
                msg = email.message_from_bytes(raw_part)

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
                        if payload and isinstance(payload, (bytes, bytearray)):
                            body = payload.decode("utf-8", errors="ignore")
                    elif ct == "text/html" and "attachment" not in cd and not body:
                        payload = part.get_payload(decode=True)
                        if payload and isinstance(payload, (bytes, bytearray)):
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
                                "b64": base64.b64encode(payload if isinstance(payload, (bytes, bytearray)) else b"").decode(),
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


# ---------------------------------------------------------------------------
#  New async EmailClient with configurable backend
# ---------------------------------------------------------------------------

@dataclass
class EmailMessage:
    """Parsed email message with metadata and attachments."""
    uid: str = ""
    from_email: str = ""
    from_name: str = ""
    subject: str = ""
    date: str = ""
    body: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)


class EmailClient:
    """Async email client with configurable backend (IMAP, Exchange, Graph).

    Usage::

        client = EmailClient()
        emails = await client.fetch_emails("INBOX", subject_filter="ТО 3115")
        for msg in emails:
            for att in msg.attachments:
                data = await client.download_attachment(msg.uid, att["filename"])
    """

    def __init__(
        self,
        backend: str | None = None,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        use_ssl: bool | None = None,
    ):
        self.backend = (backend or os.getenv("EMAIL_BACKEND", "imap")).lower()
        self.host = host or os.getenv("EMAIL_HOST", "")
        self.port = port or int(os.getenv("EMAIL_PORT", "993"))
        self.user = user or os.getenv("EMAIL_USER", "")
        self.password = password or os.getenv("EMAIL_PASSWORD", "")
        if use_ssl is not None:
            self.use_ssl = use_ssl
        else:
            self.use_ssl = os.getenv("EMAIL_USE_SSL", "true").lower() == "true"

        if self.backend not in ("imap", "exchange", "graph"):
            raise ValueError(
                f"Unsupported EMAIL_BACKEND={self.backend!r}. "
                f"Supported: imap, exchange, graph"
            )

    async def fetch_emails(
        self,
        folder: str = "INBOX",
        subject_filter: str | None = None,
        since_date: str | None = None,
    ) -> list[EmailMessage]:
        """Fetch emails from the configured backend.

        Args:
            folder: Mailbox folder name
            subject_filter: Optional subject substring filter
            since_date: Optional ISO date string (YYYY-MM-DD) to filter by date
        """
        if self.backend == "imap":
            return await self._fetch_imap(folder, subject_filter, since_date)
        elif self.backend == "exchange":
            return await self._fetch_exchange(folder, subject_filter, since_date)
        elif self.backend == "graph":
            return await self._fetch_graph(folder, subject_filter, since_date)
        raise ValueError(f"Unsupported backend: {self.backend!r}")

    async def download_attachment(
        self, email_uid: str, attachment_id: str,
    ) -> bytes:
        """Download a specific attachment by email UID and attachment identifier."""
        if self.backend == "imap":
            return await self._download_imap(email_uid, attachment_id)
        logger.warning(
            "download_attachment not fully implemented for backend=%s", self.backend,
        )
        return b""

    # -- IMAP backend -------------------------------------------------------

    async def _fetch_imap(
        self, folder: str, subject_filter: str | None, since_date: str | None,
    ) -> list[EmailMessage]:
        """Fetch emails via IMAP (runs in thread to avoid blocking event loop)."""
        return await asyncio.to_thread(
            self._fetch_imap_sync, folder, subject_filter, since_date,
        )

    def _fetch_imap_sync(
        self, folder: str, subject_filter: str | None, since_date: str | None,
    ) -> list[EmailMessage]:
        """Synchronous IMAP fetch with connection pooling."""
        messages: list[EmailMessage] = []
        conn: imaplib.IMAP4_SSL | None = None
        try:
            conn = imaplib.IMAP4_SSL(self.host, self.port)
            conn.login(self.user, self.password)
            status, _ = conn.select(folder)
            if status != "OK":
                logger.error("IMAP folder select failed: %s", folder)
                return messages

            criteria = "UNSEEN"
            if since_date:
                # Convert ISO date to IMAP format: DD-Mon-YYYY
                from datetime import datetime
                dt = datetime.fromisoformat(since_date)
                imap_date = dt.strftime("%d-%b-%Y")
                criteria = f'(UNSEEN SINCE {imap_date})'

            _, uids = conn.search(None, criteria)
            for uid in uids[0].split():
                if not uid:
                    continue
                try:
                    _, data = conn.fetch(uid, "(RFC822)")
                    raw_part_fetch = data[0][1] if isinstance(data[0][1], (bytes, bytearray)) else b""
                    raw_msg = email.message_from_bytes(raw_part_fetch)
                    msg = self._parse_email_message(uid.decode(), raw_msg)
                    if subject_filter and subject_filter.lower() not in msg.subject.lower():
                        continue
                    messages.append(msg)
                except Exception as e:
                    logger.error("Error processing email uid=%s: %s", uid, e)

        except Exception as e:
            logger.error("IMAP connection failed (%s): %s", self.host, e)
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass
        return messages

    async def _download_imap(self, email_uid: str, attachment_id: str) -> bytes:
        """Download attachment by re-fetching the email via IMAP."""
        return await asyncio.to_thread(
            self._download_imap_sync, email_uid, attachment_id,
        )

    def _download_imap_sync(self, email_uid: str, attachment_id: str) -> bytes:
        conn: imaplib.IMAP4_SSL | None = None
        try:
            conn = imaplib.IMAP4_SSL(self.host, self.port)
            conn.login(self.user, self.password)
            conn.select("INBOX")
            _, data = conn.fetch(email_uid, "(RFC822)")
            raw_bytes_att = data[0][1] if isinstance(data[0][1], (bytes, bytearray)) else b""
            raw_msg = email.message_from_bytes(raw_bytes_att)
            for part in raw_msg.walk():
                fn = _decode_str(part.get_filename() or "")
                if fn == attachment_id:
                    payload = part.get_payload(decode=True)
                    return payload if isinstance(payload, (bytes, bytearray)) else b""
        except Exception as e:
            logger.error("Error downloading attachment: %s", e)
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass
        return b""

    # -- Exchange backend (stub) -------------------------------------------

    async def _fetch_exchange(
        self, folder: str, subject_filter: str | None, since_date: str | None,
    ) -> list[EmailMessage]:
        """Exchange/EWS backend — requires exchangelib (not included in core deps)."""
        logger.warning("Exchange backend not yet implemented; returning empty list")
        return []

    # -- MS Graph backend (stub) -------------------------------------------

    async def _fetch_graph(
        self, folder: str, subject_filter: str | None, since_date: str | None,
    ) -> list[EmailMessage]:
        """MS Graph backend — requires httpx + OAuth2 token (not included in core deps)."""
        logger.warning("MS Graph backend not yet implemented; returning empty list")
        return []

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _parse_email_message(uid: str, raw_msg: email.message.Message) -> EmailMessage:
        """Parse a raw email.message.Message into an EmailMessage dataclass."""
        subject = _decode_str(raw_msg.get("Subject", ""))
        from_raw = _decode_str(raw_msg.get("From", ""))
        date_str = raw_msg.get("Date", "")

        # Extract email and name from From header
        from_email = from_raw
        from_name = ""
        if "<" in from_raw and ">" in from_raw:
            from_name = from_raw[:from_raw.index("<")].strip().strip('"')
            from_email = from_raw[from_raw.index("<") + 1:from_raw.index(">")]

        body = ""
        attachments: list[dict[str, Any]] = []
        for part in raw_msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                payload = part.get_payload(decode=True)
                if payload and isinstance(payload, (bytes, bytearray)):
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
                        "mime": ct,
                        "b64": base64.b64encode(payload if isinstance(payload, (bytes, bytearray)) else b"").decode(),
                        "size_bytes": len(payload),
                    })

        return EmailMessage(
            uid=uid,
            from_email=from_email,
            from_name=from_name,
            subject=subject,
            date=date_str,
            body=body,
            attachments=attachments,
        )
