"""Tests for the async EmailClient in shared/email_client.py."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from shared.email_client import EmailClient, EmailMessage


class TestEmailClientInit:
    def test_default_backend_is_imap(self):
        client = EmailClient(host="test", user="u", password="p")
        assert client.backend == "imap"

    def test_exchange_backend(self):
        client = EmailClient(backend="exchange", host="test", user="u", password="p")
        assert client.backend == "exchange"

    def test_graph_backend(self):
        client = EmailClient(backend="graph", host="test", user="u", password="p")
        assert client.backend == "graph"

    def test_invalid_backend_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            EmailClient(backend="invalid", host="test", user="u", password="p")

    def test_ssl_default_true(self):
        client = EmailClient(host="test", user="u", password="p")
        assert client.use_ssl is True

    def test_ssl_explicit_false(self):
        client = EmailClient(host="test", user="u", password="p", use_ssl=False)
        assert client.use_ssl is False

    def test_env_vars(self, monkeypatch):
        monkeypatch.setenv("EMAIL_BACKEND", "exchange")
        monkeypatch.setenv("EMAIL_HOST", "mail.test.com")
        monkeypatch.setenv("EMAIL_PORT", "143")
        monkeypatch.setenv("EMAIL_USER", "user@test.com")
        monkeypatch.setenv("EMAIL_PASSWORD", "secret")
        monkeypatch.setenv("EMAIL_USE_SSL", "false")
        client = EmailClient()
        assert client.backend == "exchange"
        assert client.host == "mail.test.com"
        assert client.port == 143
        assert client.user == "user@test.com"
        assert client.password == "secret"
        assert client.use_ssl is False


class TestEmailClientFetchImap:
    @patch("shared.email_client.imaplib.IMAP4_SSL")
    def test_fetch_imap_empty_inbox(self, mock_imap_class):
        mock_imap = MagicMock()
        mock_imap_class.return_value = mock_imap
        mock_imap.login.return_value = ("OK", [b"Logged in"])
        mock_imap.select.return_value = ("OK", [b"0"])
        mock_imap.search.return_value = ("OK", [b""])
        client = EmailClient(host="imap.test.ru", user="u", password="p")
        result = asyncio.get_event_loop().run_until_complete(client.fetch_emails("INBOX"))
        assert result == []

    @patch("shared.email_client.imaplib.IMAP4_SSL")
    def test_fetch_imap_with_subject_filter(self, mock_imap_class):
        """Subject filter should be applied after fetch."""
        from email.mime.text import MIMEText

        mock_imap = MagicMock()
        mock_imap_class.return_value = mock_imap
        msg = MIMEText("body")
        msg["Subject"] = "ТО 3115-ДИТ-Сервер"
        msg["From"] = "test@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        mock_imap.login.return_value = ("OK", [b"Logged in"])
        mock_imap.select.return_value = ("OK", [b"1"])
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {100})", msg.as_bytes())])
        client = EmailClient(host="imap.test.ru", user="u", password="p")
        result = asyncio.get_event_loop().run_until_complete(
            client.fetch_emails("INBOX", subject_filter="3115")
        )
        assert len(result) == 1
        assert "3115" in result[0].subject

    @patch("shared.email_client.imaplib.IMAP4_SSL")
    def test_fetch_imap_filter_excludes_non_matching(self, mock_imap_class):
        from email.mime.text import MIMEText

        mock_imap = MagicMock()
        mock_imap_class.return_value = mock_imap
        msg = MIMEText("body")
        msg["Subject"] = "Unrelated email"
        msg["From"] = "test@example.com"
        msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
        mock_imap.login.return_value = ("OK", [b"Logged in"])
        mock_imap.select.return_value = ("OK", [b"1"])
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {100})", msg.as_bytes())])
        client = EmailClient(host="imap.test.ru", user="u", password="p")
        result = asyncio.get_event_loop().run_until_complete(
            client.fetch_emails("INBOX", subject_filter="3115")
        )
        assert len(result) == 0

    @patch("shared.email_client.imaplib.IMAP4_SSL")
    def test_connection_error_returns_empty(self, mock_imap_class):
        import imaplib

        mock_imap_class.side_effect = imaplib.IMAP4.error("Connection refused")
        client = EmailClient(host="imap.test.ru", user="u", password="p")
        result = asyncio.get_event_loop().run_until_complete(client.fetch_emails())
        assert result == []


class TestEmailClientExchangeGraph:
    def test_exchange_returns_empty(self):
        client = EmailClient(backend="exchange", host="test", user="u", password="p")
        result = asyncio.get_event_loop().run_until_complete(client.fetch_emails())
        assert result == []

    def test_graph_returns_empty(self):
        client = EmailClient(backend="graph", host="test", user="u", password="p")
        result = asyncio.get_event_loop().run_until_complete(client.fetch_emails())
        assert result == []


class TestEmailMessage:
    def test_defaults(self):
        msg = EmailMessage()
        assert msg.uid == ""
        assert msg.from_email == ""
        assert msg.attachments == []

    def test_with_values(self):
        msg = EmailMessage(
            uid="123",
            from_email="test@example.com",
            subject="Test Subject",
        )
        assert msg.uid == "123"
        assert msg.from_email == "test@example.com"
        assert msg.subject == "Test Subject"
