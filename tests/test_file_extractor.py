import base64
import io
from unittest.mock import MagicMock, patch

import openpyxl
import pytest

from shared.file_extractor import _rows_to_md, extract_text_from_attachment


class TestRowsToMd:
    def test_basic_table(self):
        rows = [["A", "B"], ["1", "2"], ["3", "4"]]
        result = _rows_to_md(rows)
        assert "| A | B |" in result
        assert "| 1 | 2 |" in result
        assert "---" in result

    def test_empty_rows(self):
        assert _rows_to_md([]) == ""


class TestExtractTextFromAttachment:
    def test_unsupported_format(self):
        att = {"filename": "test.xyz", "ext": "xyz", "data": b"", "b64": "", "mime": ""}
        result = extract_text_from_attachment(att)
        assert "не поддерживается" in result

    def test_xlsx_empty(self):
        wb = openpyxl.Workbook()
        buf = io.BytesIO()
        wb.save(buf)
        data = buf.getvalue()
        att = {
            "filename": "test.xlsx",
            "ext": "xlsx",
            "data": data,
            "b64": base64.b64encode(data).decode(),
            "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        result = extract_text_from_attachment(att)
        assert isinstance(result, str)

    @patch("shared.file_extractor.pdfplumber")
    def test_pdf_text_extraction(self, mock_pdfplumber):
        pdf_text = "Тестовый текст PDF " + "x" * 50
        mock_page = MagicMock()
        mock_page.extract_text.return_value = pdf_text
        mock_pdfplumber.open.return_value.__enter__.return_value.pages = [mock_page]
        att = {
            "filename": "test.pdf",
            "ext": "pdf",
            "data": b"%PDF-1.4",
            "b64": base64.b64encode(b"%PDF-1.4").decode(),
            "mime": "application/pdf",
        }
        result = extract_text_from_attachment(att)
        assert "Тестовый текст PDF" in result
