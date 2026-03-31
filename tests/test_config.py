"""Tests for config.py safe integer/float parsing."""
import os

import pytest


class TestSafeInt:
    def test_default_when_not_set(self, monkeypatch):
        monkeypatch.delenv("TEST_SAFE_INT_PORT", raising=False)
        from config import _safe_int

        assert _safe_int("TEST_SAFE_INT_PORT", 993) == 993

    def test_valid_int(self, monkeypatch):
        monkeypatch.setenv("TEST_SAFE_INT_PORT", "8080")
        from config import _safe_int

        assert _safe_int("TEST_SAFE_INT_PORT", 993) == 8080

    def test_invalid_value_falls_back(self, monkeypatch):
        monkeypatch.setenv("TEST_SAFE_INT_PORT", "not_a_number")
        from config import _safe_int

        assert _safe_int("TEST_SAFE_INT_PORT", 993) == 993

    def test_empty_string_falls_back(self, monkeypatch):
        monkeypatch.setenv("TEST_SAFE_INT_PORT", "")
        from config import _safe_int

        assert _safe_int("TEST_SAFE_INT_PORT", 993) == 993


class TestSafeFloat:
    def test_default_when_not_set(self, monkeypatch):
        monkeypatch.delenv("TEST_SAFE_FLOAT_VAL", raising=False)
        from config import _safe_float

        assert _safe_float("TEST_SAFE_FLOAT_VAL", 3.0) == 3.0

    def test_valid_float(self, monkeypatch):
        monkeypatch.setenv("TEST_SAFE_FLOAT_VAL", "5.5")
        from config import _safe_float

        assert _safe_float("TEST_SAFE_FLOAT_VAL", 3.0) == 5.5

    def test_invalid_value_falls_back(self, monkeypatch):
        monkeypatch.setenv("TEST_SAFE_FLOAT_VAL", "abc")
        from config import _safe_float

        assert _safe_float("TEST_SAFE_FLOAT_VAL", 3.0) == 3.0
