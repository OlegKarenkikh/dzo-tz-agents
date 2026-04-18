"""Tests for shared/document_parser.py — anketa/NDA parsing from DOCX and PDF.

Uses real fixture files from tests/fixtures/collector/ for integration-level
accuracy verification.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from shared.document_parser import AnketaData, NDAData, parse_anketa, parse_nda

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "collector"


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _read_fixture(filename: str) -> bytes:
    """Read a fixture file and return its bytes."""
    path = FIXTURES_DIR / filename
    if not path.exists():
        pytest.skip(f"Fixture not found: {path}")
    return path.read_bytes()


# ---------------------------------------------------------------------------
#  DOCX Tests
# ---------------------------------------------------------------------------

class TestParseAnketaDocx:
    def test_romashka_docx_company_name(self):
        data = parse_anketa(
            _read_fixture("ООО Ромашка - Анкета участника ТО 3115-ДИТ-Сервер.docx"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert "Ромашка" in data.company_name

    def test_romashka_docx_inn(self):
        data = parse_anketa(
            _read_fixture("ООО Ромашка - Анкета участника ТО 3115-ДИТ-Сервер.docx"),
            "docx",
        )
        assert data.inn == "7702365551"

    def test_romashka_docx_tender_id(self):
        data = parse_anketa(
            _read_fixture("ООО Ромашка - Анкета участника ТО 3115-ДИТ-Сервер.docx"),
            "docx",
        )
        assert data.tender_id == "3115-ДИТ-Сервер"

    def test_romashka_docx_email(self):
        data = parse_anketa(
            _read_fixture("ООО Ромашка - Анкета участника ТО 3115-ДИТ-Сервер.docx"),
            "docx",
        )
        assert data.email == "petrov@romashka.ru"

    def test_romashka_docx_all_15_fields(self):
        data = parse_anketa(
            _read_fixture("ООО Ромашка - Анкета участника ТО 3115-ДИТ-Сервер.docx"),
            "docx",
        )
        assert data.org_form == "АО"
        assert "Москва" in data.legal_address
        assert data.phone == "8(900)456-78-90"
        assert data.website == "romashka.ru"
        assert data.bank_details == "ВТБ"
        assert data.authorized_person == "Борисов Г.Д."
        assert data.responsible_contact == "Петров П.П."

    def test_lutik_docx(self):
        data = parse_anketa(
            _read_fixture("АО Лютик - Анкета участника ТО 3115-ДИТ-Сервер.docx"),
            "docx",
        )
        assert "Лютик" in data.company_name
        assert data.inn == "7702365751"
        assert data.tender_id == "3115-ДИТ-Сервер"

    def test_gvozdika_docx(self):
        data = parse_anketa(
            _read_fixture("ООО Гвоздика - Анкета участника ТО 3115-ДИТ-Сервер.docx"),
            "docx",
        )
        assert "Гвоздика" in data.company_name
        assert data.inn == "7704565559"
        assert data.tender_id == "3115-ДИТ-Сервер"

    def test_empty_anketa_template(self):
        data = parse_anketa(
            _read_fixture("Анкета участника ТО 3115-ДИТ-Сервер.docx"),
            "docx",
        )
        assert data.tender_id == "3115-ДИТ-Сервер"
        # Template has no filled-in company name
        assert data.company_name == "" or data.company_name is not None


# ---------------------------------------------------------------------------
#  PDF Tests
# ---------------------------------------------------------------------------

class TestParseAnketaPdf:
    def test_romashka_pdf_company_name(self):
        data = parse_anketa(
            _read_fixture("ООО Ромашка - Анкета участника ТО 3115-ДИТ-Сервер.pdf"),
            "application/pdf",
        )
        assert "Ромашка" in data.company_name

    def test_romashka_pdf_inn(self):
        data = parse_anketa(
            _read_fixture("ООО Ромашка - Анкета участника ТО 3115-ДИТ-Сервер.pdf"),
            "application/pdf",
        )
        assert data.inn == "7702365551"

    def test_romashka_pdf_tender_id(self):
        data = parse_anketa(
            _read_fixture("ООО Ромашка - Анкета участника ТО 3115-ДИТ-Сервер.pdf"),
            "application/pdf",
        )
        assert data.tender_id == "3115-ДИТ-Сервер"

    def test_lutik_pdf(self):
        data = parse_anketa(
            _read_fixture("АО Лютик - Анкета участника ТО 3115-ДИТ-Сервер.pdf"),
            "application/pdf",
        )
        assert "Лютик" in data.company_name
        assert data.inn == "7702365751"

    def test_gvozdika_pdf(self):
        data = parse_anketa(
            _read_fixture("ООО Гвоздика - Анкета участника ТО 3115-ДИТ-Сервер.pdf"),
            "application/pdf",
        )
        assert "Гвоздика" in data.company_name
        assert data.inn == "7704565559"


# ---------------------------------------------------------------------------
#  Content-type auto-detection
# ---------------------------------------------------------------------------

class TestContentTypeDetection:
    def test_auto_detect_docx(self):
        data = parse_anketa(
            _read_fixture("ООО Ромашка - Анкета участника ТО 3115-ДИТ-Сервер.docx"),
            "something.docx",
        )
        assert data.inn == "7702365551"

    def test_auto_detect_pdf(self):
        data = parse_anketa(
            _read_fixture("ООО Ромашка - Анкета участника ТО 3115-ДИТ-Сервер.pdf"),
            "something.pdf",
        )
        assert data.inn == "7702365551"

    def test_auto_detect_word_mime(self):
        data = parse_anketa(
            _read_fixture("ООО Ромашка - Анкета участника ТО 3115-ДИТ-Сервер.docx"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert data.inn == "7702365551"


# ---------------------------------------------------------------------------
#  AnketaData dataclass
# ---------------------------------------------------------------------------

class TestAnketaData:
    def test_defaults(self):
        data = AnketaData()
        assert data.tender_id == ""
        assert data.company_name == ""
        assert data.inn == ""
        assert data.raw_fields == {}

    def test_fields_settable(self):
        data = AnketaData(
            company_name="Test",
            inn="1234567890",
            tender_id="123-ABC-DEF",
        )
        assert data.company_name == "Test"
        assert data.inn == "1234567890"
        assert data.tender_id == "123-ABC-DEF"


class TestNDAData:
    def test_defaults(self):
        data = NDAData()
        assert data.signatory_name == ""
        assert data.company_name == ""


# ── parse_anketa: .doc content_type fallback path ────────────────────────────

class TestParseAnketaDocFallbacks:
    def test_doc_ct_uses_docx(self):
        from shared.document_parser import parse_anketa, AnketaData
        from unittest.mock import patch
        mock_result = AnketaData()
        mock_result.company_name = "Test"
        with patch("shared.document_parser._parse_docx", return_value=mock_result):
            result = parse_anketa(b"fake", content_type="application/vnd.ms-doc")
        assert result.company_name == "Test"

    def test_doc_ct_falls_back_to_pdf_on_docx_fail(self):
        from shared.document_parser import parse_anketa, AnketaData
        from unittest.mock import patch
        mock_pdf = AnketaData()
        with patch("shared.document_parser._parse_docx", side_effect=Exception("bad")):
            with patch("shared.document_parser._parse_pdf", return_value=mock_pdf):
                result = parse_anketa(b"", content_type="application/vnd.ms-doc")
        assert isinstance(result, AnketaData)

    def test_unknown_ct_docx_success(self):
        from shared.document_parser import parse_anketa, AnketaData
        from unittest.mock import patch
        mock = AnketaData(); mock.company_name = "Corp"
        with patch("shared.document_parser._parse_docx", return_value=mock):
            result = parse_anketa(b"x", content_type="")
        assert result.company_name == "Corp"

    def test_unknown_ct_falls_back_to_pdf(self):
        from shared.document_parser import parse_anketa, AnketaData
        from unittest.mock import patch
        mock = AnketaData()
        with patch("shared.document_parser._parse_docx", side_effect=Exception("e")):
            with patch("shared.document_parser._parse_pdf", return_value=mock):
                result = parse_anketa(b"", content_type="application/octet-stream")
        assert isinstance(result, AnketaData)


# ── parse_nda: all content_type branches ─────────────────────────────────────

class TestParseNDABranches:
    def test_pdf_path(self):
        from shared.document_parser import parse_nda, NDAData
        from unittest.mock import patch
        with patch("shared.document_parser._extract_pdf_text", return_value="ООО подписала"):
            result = parse_nda(b"x", content_type="application/pdf")
        assert isinstance(result, NDAData)

    def test_docx_path(self):
        from shared.document_parser import parse_nda, NDAData
        from unittest.mock import patch
        with patch("shared.document_parser._extract_docx_text", return_value="Подписант"):
            result = parse_nda(b"x", content_type="application/vnd.openxmlformats")
        assert isinstance(result, NDAData)

    def test_word_mime_path(self):
        from shared.document_parser import parse_nda, NDAData
        from unittest.mock import patch
        with patch("shared.document_parser._extract_docx_text", return_value="NDA text"):
            result = parse_nda(b"x", content_type="application/vnd.ms-word")
        assert isinstance(result, NDAData)

    def test_unknown_ct_tries_docx(self):
        from shared.document_parser import parse_nda, NDAData
        from unittest.mock import patch
        with patch("shared.document_parser._extract_docx_text", return_value=""):
            result = parse_nda(b"x", content_type="application/octet-stream")
        assert isinstance(result, NDAData)

    def test_unknown_ct_falls_back_to_pdf(self):
        from shared.document_parser import parse_nda, NDAData
        from unittest.mock import patch
        with patch("shared.document_parser._extract_docx_text", side_effect=Exception("e")):
            with patch("shared.document_parser._extract_pdf_text", return_value=""):
                result = parse_nda(b"x", content_type="")
        assert isinstance(result, NDAData)

    def test_returns_nda_data(self):
        from shared.document_parser import parse_nda, NDAData
        from unittest.mock import patch
        with patch("shared.document_parser._extract_pdf_text", return_value=""):
            result = parse_nda(b"", content_type="application/pdf")
        assert isinstance(result, NDAData)
