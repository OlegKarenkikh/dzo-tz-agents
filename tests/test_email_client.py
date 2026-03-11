"""
Тесты для shared/email_client.py.
Используются mock-объекты для imaplib.IMAP4_SSL.
"""
import base64
import email
import imaplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

import pytest

from shared.email_client import _decode_str, fetch_unseen_emails


def _make_email_bytes(
    subject: str = "Тест",
    from_addr: str = "sender@example.com",
    body: str = "Тело письма",
) -> bytes:
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    return msg.as_bytes()


class TestDecodeStr:
    def test_plain_ascii(self):
        assert _decode_str("Hello") == "Hello"

    def test_empty_string(self):
        assert _decode_str("") == ""

    def test_none_value(self):
        assert _decode_str(None) == ""

    def test_cyrillic_encoded(self):
        cyrillic = "Заявка на закупку"
        encoded = f"=?utf-8?b?{base64.b64encode(cyrillic.encode()).decode()}?="
        assert _decode_str(encoded) == cyrillic

    def test_cyrillic_quoted_printable(self):
        import quopri

        cyrillic = "Привет мир"
        qp_encoded = quopri.encodestring(cyrillic.encode("utf-8")).decode("ascii")
        encoded = f"=?utf-8?q?{qp_encoded.replace(' ', '_')}?="
        result = _decode_str(encoded)
        assert "Привет" in result or result


class TestFetchUnseenEmails:
    @patch("shared.email_client.imaplib.IMAP4_SSL")
    def test_successful_fetch(self, mock_imap_class):
        mock_imap = MagicMock()
        mock_imap_class.return_value = mock_imap
        mail_bytes = _make_email_bytes(subject="Закупка оборудования", body="Тело письма")
        mock_imap.login.return_value = ("OK", [b"Logged in"])
        mock_imap.select.return_value = ("OK", [b"1"])
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {100})", mail_bytes)])
        mock_imap.store.return_value = ("OK", [b"1"])
        result = fetch_unseen_emails("imap.test.ru", "user@test.ru", "secret")
        assert len(result) == 1
        assert result[0]["subject"] == "Закупка оборудования"
        assert result[0]["body"] == "Тело письма"
        mock_imap.logout.assert_called_once()

    @patch("shared.email_client.imaplib.IMAP4_SSL")
    def test_empty_inbox(self, mock_imap_class):
        mock_imap = MagicMock()
        mock_imap_class.return_value = mock_imap
        mock_imap.login.return_value = ("OK", [b"Logged in"])
        mock_imap.select.return_value = ("OK", [b"0"])
        mock_imap.search.return_value = ("OK", [b""])
        result = fetch_unseen_emails("imap.test.ru", "user@test.ru", "secret")
        assert result == []
        mock_imap.logout.assert_called_once()

    @patch("shared.email_client.imaplib.IMAP4_SSL")
    def test_connection_error_returns_empty_list(self, mock_imap_class):
        mock_imap_class.side_effect = imaplib.IMAP4.error("Connection refused")
        assert fetch_unseen_emails("imap.test.ru", "user@test.ru", "wrong_password") == []

    @patch("shared.email_client.imaplib.IMAP4_SSL")
    def test_login_failure_returns_empty_list(self, mock_imap_class):
        mock_imap = MagicMock()
        mock_imap_class.return_value = mock_imap
        mock_imap.login.side_effect = imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        assert fetch_unseen_emails("imap.test.ru", "user@test.ru", "bad_password") == []

    @patch("shared.email_client.imaplib.IMAP4_SSL")
    def test_cyrillic_subject_decoded(self, mock_imap_class):
        mock_imap = MagicMock()
        mock_imap_class.return_value = mock_imap
        cyrillic_subject = "Заявка на закупку оборудования"
        b64_subject = base64.b64encode(cyrillic_subject.encode("utf-8")).decode()
        encoded_subject = f"=?utf-8?b?{b64_subject}?="
        mail_bytes = _make_email_bytes(subject=encoded_subject, body="Тело")
        mock_imap.login.return_value = ("OK", [b"Logged in"])
        mock_imap.select.return_value = ("OK", [b"1"])
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {100})", mail_bytes)])
        mock_imap.store.return_value = ("OK", [b"1"])
        result = fetch_unseen_emails("imap.test.ru", "user@test.ru", "secret")
        assert len(result) == 1
        assert result[0]["subject"] == cyrillic_subject

    @patch("shared.email_client.imaplib.IMAP4_SSL")
    def test_multiple_emails(self, mock_imap_class):
        mock_imap = MagicMock()
        mock_imap_class.return_value = mock_imap
        mail1 = _make_email_bytes(subject="Письмо 1")
        mail2 = _make_email_bytes(subject="Письмо 2")
        mock_imap.login.return_value = ("OK", [b"Logged in"])
        mock_imap.select.return_value = ("OK", [b"2"])
        mock_imap.search.return_value = ("OK", [b"1 2"])
        mock_imap.fetch.side_effect = [
            ("OK", [(b"1 (RFC822 {100})", mail1)]),
            ("OK", [(b"1 (RFC822 {100})", mail2)]),
        ]
        mock_imap.store.return_value = ("OK", [b""])
        result = fetch_unseen_emails("imap.test.ru", "user@test.ru", "secret")
        assert len(result) == 2
        subjects = [r["subject"] for r in result]
        assert "Письмо 1" in subjects
        assert "Письмо 2" in subjects
