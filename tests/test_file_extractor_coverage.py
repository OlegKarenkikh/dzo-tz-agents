"""Coverage tests for shared/file_extractor.py — uncovered branches (68% → 90%+)."""
import base64
import io
from unittest.mock import MagicMock, patch
import pytest
import shared.file_extractor as fe


def _att(ext, data=b"", b64="", mime="application/octet-stream", filename=None):
    if isinstance(data, str):
        data = data.encode()
    if not b64 and data:
        b64 = base64.b64encode(data).decode()
    return {"ext": ext, "data": data, "b64": b64, "mime": mime,
            "filename": filename or f"file.{ext}"}


class TestGetClientCache:
    def test_same_key_returns_cached(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k1")
        monkeypatch.setenv("OPENAI_API_BASE", "")
        fe._client = None; fe._client_key = ""
        assert fe._get_client() is fe._get_client()

    def test_changed_key_new_client(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "key-a")
        monkeypatch.setenv("OPENAI_API_BASE", "")
        fe._client = None; fe._client_key = ""
        c1 = fe._get_client()
        monkeypatch.setenv("OPENAI_API_KEY", "key-b")
        assert fe._get_client() is not c1

    def test_base_url_change_new_client(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("OPENAI_API_BASE", "http://old")
        fe._client = None; fe._client_key = ""
        c1 = fe._get_client()
        monkeypatch.setenv("OPENAI_API_BASE", "http://new")
        assert fe._get_client() is not c1


class TestOCRVision:
    def test_returns_error_string_on_exception(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")
        monkeypatch.setattr(fe, "_get_client", lambda: mock_client)
        assert "[OCR error:" in fe._ocr_vision("b64", "image/png", "DOC")

    def test_returns_text_on_success(self, monkeypatch):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "OCR result text"
        mock_client.chat.completions.create.return_value = mock_resp
        monkeypatch.setattr(fe, "_get_client", lambda: mock_client)
        assert fe._ocr_vision("b64", "image/png", "DOC") == "OCR result text"


class TestExtractDocxFallback:
    def test_falls_back_to_ocr_when_short(self, monkeypatch):
        monkeypatch.setattr(fe, "_ocr_vision", MagicMock(return_value="OCR fallback"))
        with patch("docx.Document") as mock_doc:
            mock_doc.return_value.paragraphs = [MagicMock(text="Short")]
            result = fe.extract_text_from_attachment(_att("docx", b"x"))
        assert result == "OCR fallback"

    def test_returns_long_text_directly(self, monkeypatch):
        long_text = "A" * 100
        monkeypatch.setattr(fe, "_extract_docx", lambda d, b, m: long_text)
        assert fe.extract_text_from_attachment(_att("docx", b"x")) == long_text

    def test_falls_back_to_ocr_on_exception(self, monkeypatch):
        monkeypatch.setattr(fe, "_ocr_vision", MagicMock(return_value="OCR after exc"))
        with patch("docx.Document", side_effect=Exception("bad")):
            assert fe.extract_text_from_attachment(_att("docx", b"x")) == "OCR after exc"


class TestExtractSpreadsheet:
    def test_xls_uses_xlrd(self):
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.name = "Sheet1"; mock_ws.nrows = 1; mock_ws.ncols = 1
        mock_ws.cell_value.return_value = "val"
        mock_wb.nsheets = 1; mock_wb.sheet_by_index.return_value = mock_ws
        with patch("xlrd.open_workbook", return_value=mock_wb):
            result = fe.extract_text_from_attachment(_att("xls", b"x"))
        assert "Sheet1" in result

    def test_exception_returns_error_string(self):
        with patch("openpyxl.load_workbook", side_effect=Exception("corrupt")):
            with patch("xlrd.open_workbook", side_effect=Exception("corrupt")):
                result = fe.extract_text_from_attachment(_att("xlsx", b"bad"))
        assert "error" in result.lower()
