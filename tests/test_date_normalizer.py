"""Tests for Russian date normalization."""
from datetime import date

import pytest

from shared.date_normalizer import normalize_date


class TestDateNormalizer:
    def test_dd_mm_yyyy_dot(self):
        assert normalize_date("01.05.2026") == "2026-05-01"

    def test_dd_mm_yyyy_slash(self):
        assert normalize_date("15/06/2026") == "2026-06-15"

    def test_russian_full_date(self):
        assert normalize_date("1 мая 2026") == "2026-05-01"

    def test_russian_full_date_with_year_suffix(self):
        assert normalize_date("1 мая 2026 г.") == "2026-05-01"

    def test_russian_month_year(self):
        assert normalize_date("май 2026") == "2026-05-01"

    def test_iso_format_passthrough(self):
        assert normalize_date("2026-05-01") == "2026-05-01"

    def test_quarter_roman(self):
        assert normalize_date("II квартал 2026") == "2026-06-30"

    def test_quarter_arabic(self):
        assert normalize_date("3 квартал 2026") == "2026-09-30"

    def test_working_days(self):
        result = normalize_date("45 рабочих дней", reference_date=date(2026, 1, 1))
        assert result == "2026-02-15"

    def test_calendar_days(self):
        result = normalize_date("30 календарных дней", reference_date=date(2026, 1, 1))
        assert result == "2026-01-31"

    def test_empty_string_returns_none(self):
        assert normalize_date("") is None

    def test_none_input_returns_none(self):
        assert normalize_date(None) is None

    def test_unparseable_returns_none(self):
        assert normalize_date("когда-нибудь потом") is None

    def test_various_months(self):
        assert normalize_date("15 января 2026") == "2026-01-15"
        assert normalize_date("28 февраля 2026") == "2026-02-28"
        assert normalize_date("10 марта 2026") == "2026-03-10"
        assert normalize_date("20 апреля 2026") == "2026-04-20"
        assert normalize_date("5 июня 2026") == "2026-06-05"
        assert normalize_date("31 июля 2026") == "2026-07-31"
        assert normalize_date("15 августа 2026") == "2026-08-15"
        assert normalize_date("1 сентября 2026") == "2026-09-01"
        assert normalize_date("10 октября 2026") == "2026-10-10"
        assert normalize_date("30 ноября 2026") == "2026-11-30"
        assert normalize_date("25 декабря 2026") == "2026-12-25"
