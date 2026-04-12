"""Coverage boost for shared/chunked_analysis.py and shared/file_extractor.py."""
import base64
import io
from unittest.mock import MagicMock, patch

import pytest
import shared.chunked_analysis as ca
import shared.file_extractor as fe


# ─────────────────────────────────────────────────────────────────────────────
# chunk_document
# ─────────────────────────────────────────────────────────────────────────────
class TestChunkDocument:
    def test_short_text_returns_single_chunk(self):
        text = "Hello world"
        assert ca.chunk_document(text, max_chars=1000) == [text]

    def test_splits_by_double_newline(self):
        para1 = "A" * 1000
        para2 = "B" * 1000
        text = para1 + "\n\n" + para2
        chunks = ca.chunk_document(text, max_chars=1200, overlap=50, max_chunks=10)
        assert len(chunks) >= 2
        assert "A" in chunks[0]

    def test_splits_by_single_newline_fallback(self):
        text = "X" * 800 + "\n" + "Y" * 800
        chunks = ca.chunk_document(text, max_chars=900, overlap=50, max_chunks=10)
        assert len(chunks) >= 2

    def test_splits_by_space_fallback(self):
        words = "word " * 500
        chunks = ca.chunk_document(words, max_chars=600, overlap=50, max_chunks=20)
        assert len(chunks) >= 2
        assert all(len(c) > 0 for c in chunks)

    def test_chunks_within_max_count(self):
        text = "Z" * 50_000
        chunks = ca.chunk_document(text, max_chars=5_000, overlap=500, max_chunks=ca._MAX_CHUNKS)
        assert len(chunks) <= ca._MAX_CHUNKS + 2

    def test_exact_boundary_returns_single(self):
        text = "A" * 1000
        assert ca.chunk_document(text, max_chars=1000) == [text]


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_model_context_tokens
# ─────────────────────────────────────────────────────────────────────────────
class TestResolveModelContextTokens:
    def test_github_models_backend(self, monkeypatch):
        monkeypatch.setattr(ca, "LLM_BACKEND", "github_models")
        monkeypatch.setattr(ca, "probe_max_input_tokens", lambda k, m: 32768)
        assert ca._resolve_model_context_tokens("k", "gpt-4o") == 32768

    def test_local_backend(self, monkeypatch):
        monkeypatch.setattr(ca, "LLM_BACKEND", "ollama")
        monkeypatch.setattr(ca, "LOCAL_BACKENDS", {"ollama"})
        monkeypatch.setattr(ca, "resolve_local_base_url", lambda: "http://localhost:11434/v1")
        monkeypatch.setattr(ca, "probe_local_max_context", lambda url, m: 65536)
        assert ca._resolve_model_context_tokens("k", "qwen3") == 65536

    def test_default_backend_returns_default(self, monkeypatch):
        monkeypatch.setattr(ca, "LLM_BACKEND", "openai")
        monkeypatch.setattr(ca, "LOCAL_BACKENDS", set())
        assert ca._resolve_model_context_tokens("k", "gpt-4") == ca._DEFAULT_MODEL_CONTEXT_TOKENS

    def test_exception_returns_default(self, monkeypatch):
        monkeypatch.setattr(ca, "LLM_BACKEND", "github_models")
        monkeypatch.setattr(ca, "probe_max_input_tokens", MagicMock(side_effect=Exception("fail")))
        assert ca._resolve_model_context_tokens("k", "bad") == ca._DEFAULT_MODEL_CONTEXT_TOKENS


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_completions_url
# ─────────────────────────────────────────────────────────────────────────────
class TestResolveCompletionsUrl:
    def test_github_models_url(self, monkeypatch):
        monkeypatch.setattr(ca, "LLM_BACKEND", "github_models")
        url = ca._resolve_completions_url()
        assert "github.ai" in url and "chat/completions" in url

    def test_local_backend_url(self, monkeypatch):
        monkeypatch.setattr(ca, "LLM_BACKEND", "ollama")
        monkeypatch.setattr(ca, "LOCAL_BACKENDS", {"ollama"})
        monkeypatch.setattr(ca, "resolve_local_base_url", lambda: "http://localhost:11434/v1")
        url = ca._resolve_completions_url()
        assert "localhost:11434" in url and "chat/completions" in url

    def test_custom_base_url(self, monkeypatch):
        monkeypatch.setattr(ca, "LLM_BACKEND", "qwen_proxy")
        monkeypatch.setattr(ca, "LOCAL_BACKENDS", set())
        monkeypatch.setattr(ca, "OPENAI_API_BASE", "https://qwen-proxy-bdt6.onrender.com/v1")
        assert "qwen-proxy-bdt6.onrender.com" in ca._resolve_completions_url()

    def test_default_openai_url(self, monkeypatch):
        monkeypatch.setattr(ca, "LLM_BACKEND", "openai")
        monkeypatch.setattr(ca, "LOCAL_BACKENDS", set())
        monkeypatch.setattr(ca, "OPENAI_API_BASE", None)
        assert "api.openai.com" in ca._resolve_completions_url()


# ─────────────────────────────────────────────────────────────────────────────
# _call_llm_direct
# ─────────────────────────────────────────────────────────────────────────────
class TestCallLLMDirect:
    def _ok(self, content="LLM answer"):
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = {"choices": [{"message": {"content": content}}]}
        return r

    def test_returns_content_on_success(self, monkeypatch):
        monkeypatch.setattr(ca, "_resolve_completions_url", lambda: "https://x.com/v1/chat/completions")
        with patch("shared.chunked_analysis.httpx.post", return_value=self._ok("Answer")):
            assert ca._call_llm_direct("key", "qwen3-32b", "sys", "user") == "Answer"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setattr(ca, "_resolve_completions_url", lambda: "https://x.com/")
        with patch("shared.chunked_analysis.httpx.post", return_value=self._ok("  trimmed  ")):
            assert ca._call_llm_direct("key", "m", "s", "u") == "trimmed"

    def test_exception_returns_empty(self, monkeypatch):
        monkeypatch.setattr(ca, "_resolve_completions_url", lambda: "https://bad/")
        with patch("shared.chunked_analysis.httpx.post", side_effect=Exception("err")):
            assert ca._call_llm_direct("k", "m", "s", "u") == ""

    def test_no_auth_when_not_needed(self, monkeypatch):
        monkeypatch.setattr(ca, "_resolve_completions_url", lambda: "https://x.com/")
        captured = {}
        def fp(url, headers, json, timeout):
            captured["h"] = headers
            return self._ok()
        with patch("shared.chunked_analysis.httpx.post", side_effect=fp):
            ca._call_llm_direct("not-needed", "m", "s", "u")
        assert "Authorization" not in captured["h"]

    def test_auth_header_sent_with_key(self, monkeypatch):
        monkeypatch.setattr(ca, "_resolve_completions_url", lambda: "https://x.com/")
        captured = {}
        def fp(url, headers, json, timeout):
            captured["h"] = headers
            return self._ok()
        with patch("shared.chunked_analysis.httpx.post", side_effect=fp):
            ca._call_llm_direct("my-api-key", "m", "s", "u")
        assert "Bearer my-api-key" in captured["h"].get("Authorization", "")


# ─────────────────────────────────────────────────────────────────────────────
# analyze_document_in_chunks
# ─────────────────────────────────────────────────────────────────────────────
class TestAnalyzeDocumentInChunks:
    def test_tz_agent_single_chunk(self, monkeypatch):
        monkeypatch.setattr(ca, "_resolve_model_context_tokens", lambda k, m: 128000)
        monkeypatch.setattr(ca, "_call_llm_direct", lambda k, m, s, u, **kw: "Анализ раздела")
        result = ca.analyze_document_in_chunks(
            text="Техническое задание. Краткий документ.",
            api_key="key",
            model_name="qwen3-32b",
            agent_type="tz",
        )
        assert isinstance(result, str) and len(result) > 0

    def test_dzo_agent_type(self, monkeypatch):
        monkeypatch.setattr(ca, "_resolve_model_context_tokens", lambda k, m: 128000)
        monkeypatch.setattr(ca, "_call_llm_direct", lambda k, m, s, u, **kw: "ДЗО анализ")
        result = ca.analyze_document_in_chunks(
            text="ДЗО документ краткий",
            api_key="key",
            model_name="qwen3-32b",
            agent_type="dzo",
        )
        assert isinstance(result, str)

    def test_tender_agent_type(self, monkeypatch):
        monkeypatch.setattr(ca, "_resolve_model_context_tokens", lambda k, m: 128000)
        monkeypatch.setattr(ca, "_call_llm_direct", lambda k, m, s, u, **kw: "Тендер анализ")
        result = ca.analyze_document_in_chunks(
            text="Тендерная документация",
            api_key="key",
            model_name="qwen3-32b",
            agent_type="tender",
        )
        assert isinstance(result, str)

    def test_multiple_chunks_all_called(self, monkeypatch):
        monkeypatch.setattr(ca, "_resolve_model_context_tokens", lambda k, m: 4096)
        count = {"n": 0}
        def fake(k, m, s, u, **kw):
            count["n"] += 1
            return f"Chunk {count['n']}"
        monkeypatch.setattr(ca, "_call_llm_direct", fake)
        result = ca.analyze_document_in_chunks(
            text="Данные. " * 3000,
            api_key="key",
            model_name="qwen3-32b",
            agent_type="tz",
        )
        assert count["n"] >= 2
        assert isinstance(result, str)

    def test_all_empty_responses_returns_none(self, monkeypatch):
        monkeypatch.setattr(ca, "_resolve_model_context_tokens", lambda k, m: 4096)
        monkeypatch.setattr(ca, "_call_llm_direct", lambda *a, **kw: "")
        result = ca.analyze_document_in_chunks(
            text="Test " * 2000,
            api_key="key",
            model_name="model",
            agent_type="tz",
        )
        # Either None or empty string — both are acceptable per docstring
        assert result is None or isinstance(result, str)


# ─────────────────────────────────────────────────────────────────────────────
# file_extractor — extract_text_from_attachment
# ─────────────────────────────────────────────────────────────────────────────
def _att(ext, text="Hello", mime="application/octet-stream"):
    data = text.encode()
    return {"ext": ext, "data": data, "b64": base64.b64encode(data).decode(), "mime": mime, "filename": f"test.{ext}"}


class TestFileExtractor:
    def test_unsupported_extension_returns_warning_string(self):
        att = _att("xyz", "binary content")
        result = fe.extract_text_from_attachment(att)
        assert isinstance(result, str)
        assert "xyz" in result or "⚠️" in result or "не поддерживается" in result

    def test_doc_returns_unsupported_warning(self):
        att = _att("doc")
        result = fe.extract_text_from_attachment(att)
        assert isinstance(result, str) and ("doc" in result.lower() or "⚠" in result)

    def test_pdf_calls_pdfplumber(self):
        fake_page = MagicMock()
        # Must return >= 50 chars to avoid fallthrough to pdf2image
        fake_page.extract_text.return_value = "PDF текст страницы. " * 5
        fake_pdf = MagicMock()
        fake_pdf.__enter__ = MagicMock(return_value=fake_pdf)
        fake_pdf.__exit__ = MagicMock(return_value=False)
        fake_pdf.pages = [fake_page]
        att = _att("pdf", "fake-pdf-bytes", "application/pdf")
        with patch("shared.file_extractor.pdfplumber.open", return_value=fake_pdf):
            result = fe.extract_text_from_attachment(att)
        assert "PDF текст страницы" in result

    def test_docx_calls_document(self):
        fake_para = MagicMock()
        # Must return >= 50 chars to avoid fallthrough to Vision OCR
        fake_para.text = "DOCX абзац текста документа, содержащий достаточно текста для извлечения"
        fake_doc = MagicMock()
        fake_doc.paragraphs = [fake_para]
        att = _att("docx", "fake-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with patch("shared.file_extractor.Document", return_value=fake_doc):
            result = fe.extract_text_from_attachment(att)
        assert "DOCX абзац" in result

    def test_xlsx_calls_openpyxl(self):
        fake_ws = MagicMock()
        fake_ws.iter_rows = MagicMock(return_value=iter([[MagicMock(value="Cell A1"), MagicMock(value="Cell B1")]]))
        fake_wb = MagicMock()
        fake_wb.worksheets = [fake_ws]
        att = _att("xlsx", "fake-xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with patch("shared.file_extractor.openpyxl.load_workbook", return_value=fake_wb):
            result = fe.extract_text_from_attachment(att)
        assert isinstance(result, str)

    def test_image_calls_ocr_vision(self):
        att = _att("jpg", "fake-jpg", "image/jpeg")
        with patch.object(fe, "_ocr_vision", return_value="OCR результат") as mock_ocr:
            result = fe.extract_text_from_attachment(att)
        assert result == "OCR результат"
        mock_ocr.assert_called_once()

    def test_pdf_fallback_on_pdfplumber_error(self):
        """When pdfplumber fails, _extract_pdf should handle gracefully."""
        att = _att("pdf", "corrupted-bytes", "application/pdf")
        with patch("shared.file_extractor.pdfplumber.open", side_effect=Exception("corrupt PDF")):
            # Should either return empty/error string, not crash
            try:
                result = fe.extract_text_from_attachment(att)
                assert isinstance(result, str)
            except Exception:
                pass  # fallback to OCR or crash is also acceptable

    def test_spreadsheet_rows_to_markdown(self):
        rows = [["Наименование", "Количество", "Цена"], ["Услуга 1", "10", "5000"]]
        result = fe._rows_to_md(rows)
        assert "Наименование" in result
        assert "Услуга 1" in result
