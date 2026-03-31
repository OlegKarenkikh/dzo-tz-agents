"""Tests for shared/email_sender.py."""
import os
from unittest.mock import MagicMock, patch

import pytest

from shared.email_sender import send_email


class TestSendEmail:
    @patch("shared.email_sender.smtplib.SMTP")
    def test_returns_true_on_success(self, mock_smtp_class, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.test.ru")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USER", "user@test.ru")
        monkeypatch.setenv("SMTP_PASSWORD", "secret")

        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email(
            to="recipient@test.ru",
            subject="Test",
            html_body="<p>Hello</p>",
        )
        assert result is True

    @patch("shared.email_sender.smtplib.SMTP")
    def test_returns_false_on_smtp_error(self, mock_smtp_class, monkeypatch):
        monkeypatch.setenv("SMTP_USER", "user@test.ru")
        monkeypatch.setenv("SMTP_PASSWORD", "secret")

        mock_smtp_class.side_effect = ConnectionRefusedError("Connection refused")

        result = send_email(
            to="recipient@test.ru",
            subject="Test",
            html_body="<p>Hello</p>",
        )
        assert result is False

    def test_returns_false_when_credentials_missing(self, monkeypatch):
        monkeypatch.delenv("SMTP_USER", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)

        result = send_email(
            to="recipient@test.ru",
            subject="Test",
            html_body="<p>Hello</p>",
        )
        assert result is False

    def test_returns_false_when_password_missing(self, monkeypatch):
        monkeypatch.setenv("SMTP_USER", "user@test.ru")
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)

        result = send_email(
            to="recipient@test.ru",
            subject="Test",
            html_body="<p>Hello</p>",
        )
        assert result is False
