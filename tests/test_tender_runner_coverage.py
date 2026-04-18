"""Coverage tests for agent21_tender_inspector/runner.py (48% → 75%+)."""
import json
import pathlib
from unittest.mock import MagicMock
import pytest
import agent21_tender_inspector.runner as tr


def _f(tmp_path, content=b"%PDF fake", name="doc.pdf"):
    p = tmp_path / name; p.write_bytes(content); return p


class TestIsUrl:
    def test_http(self): assert tr._is_url("http://x.com/f.pdf")
    def test_https(self): assert tr._is_url("https://x.com/f.pdf")
    def test_path_not_url(self): assert not tr._is_url("/tmp/f.pdf")
    def test_relative_not_url(self): assert not tr._is_url("docs/f.pdf")


class TestBuildOutputPath:
    def test_no_dir_sibling(self, tmp_path):
        r = tr._build_output_path(str(tmp_path / "t.pdf"), "")
        assert r.suffix == ".json" and "pdf" in r.name

    def test_with_dir_creates(self, tmp_path):
        out = str(tmp_path / "out")
        r = tr._build_output_path(str(tmp_path / "t.pdf"), out)
        assert r.parent.exists()

    def test_hash_source_override(self, tmp_path):
        src = str(tmp_path / "t.pdf")
        r1 = tr._build_output_path(src, "", hash_source="a")
        r2 = tr._build_output_path(src, "", hash_source="b")
        assert r1.name != r2.name


class TestSaveJsonResult:
    def test_writes_json(self, tmp_path):
        p = tmp_path / "r.json"
        tr._save_json_result({"docs": ["Устав"], "n": 1}, p)
        assert json.loads(p.read_text("utf-8"))["n"] == 1


class TestExtractDocumentListFromSteps:
    def test_empty(self): assert tr._extract_document_list_from_steps([]) == {}
    def test_wrong_tool(self):
        assert tr._extract_document_list_from_steps([("other", json.dumps({"documents": ["A"]}))]) == {}
    def test_extracts_documents(self):
        r = tr._extract_document_list_from_steps([
            ("generate_document_list", json.dumps({"documents": ["Устав"]}))])
        assert r["documents"][0] == "Устав"
    def test_extracts_error(self):
        r = tr._extract_document_list_from_steps([
            ("generate_document_list", json.dumps({"error": "No reqs"}))])
        assert r["error"]
    def test_malformed_skipped(self):
        r = tr._extract_document_list_from_steps([
            ("generate_document_list", "BAD{"),
            ("generate_document_list", json.dumps({"documents": ["Doc"]}))])
        assert r["documents"] == ["Doc"]
    def test_non_list_step_skipped(self):
        r = tr._extract_document_list_from_steps([
            "str-step",
            ("generate_document_list", json.dumps({"documents": ["X"]}))])
        assert r["documents"] == ["X"]
    def test_dict_obs(self):
        r = tr._extract_document_list_from_steps([("generate_document_list", {"documents": ["Y"]})])
        assert r["documents"] == ["Y"]


class TestProcessSingleDocumentErrors:
    def test_unsupported_ext(self, tmp_path):
        r = tr.process_single_document(str(_f(tmp_path, name="d.txt")))
        assert r["status"] == "error"

    def test_oversized(self, tmp_path, monkeypatch):
        p = _f(tmp_path)
        monkeypatch.setattr(pathlib.Path, "stat",
                            lambda self: type("S",(),{"st_size": 60*1024*1024})())
        r = tr.process_single_document(str(p))
        assert r["status"] == "error"


class TestProcessSingleDocumentDedup:
    def test_cached(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.FORCE_REPROCESS", False)
        monkeypatch.setattr("shared.database.find_duplicate_job",
                            lambda *a, **k: {"result": {"documents": ["A"]}})
        assert tr.process_single_document(str(_f(tmp_path)))["documents"] == ["A"]

    def test_no_result_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.FORCE_REPROCESS", False)
        monkeypatch.setattr("shared.database.find_duplicate_job",
                            lambda *a, **k: {"created_at": None})
        assert tr.process_single_document(str(_f(tmp_path))) == {}


class TestProcessSingleDocumentHappy:
    def _patch(self, monkeypatch, agent):
        monkeypatch.setattr("config.FORCE_REPROCESS", True)
        monkeypatch.setattr("config.LLM_BACKEND", "openai")
        monkeypatch.setattr("shared.database.create_job", lambda *a, **k: "j")
        monkeypatch.setattr("shared.database.update_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.database.find_duplicate_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.tracing.get_langfuse_callback", lambda: None)
        monkeypatch.setattr("shared.tracing.log_agent_steps", lambda **k: "")
        monkeypatch.setattr("shared.telegram_notify.notify", lambda *a, **k: None)
        monkeypatch.setattr("agent21_tender_inspector.runner._extract_text",
                            lambda d, fn: "Текст тендерного документа достаточной длины")
        monkeypatch.setattr("agent21_tender_inspector.runner.create_tender_agent", lambda: agent)

    def test_success(self, tmp_path, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = {"output": "OK", "intermediate_steps": [
            ("generate_document_list", json.dumps({"documents": ["Устав"]}))]}
        self._patch(monkeypatch, agent)
        r = tr.process_single_document(str(_f(tmp_path)), save_to_file=False)
        assert "documents" in r

    def test_no_tool_result_raw_output(self, tmp_path, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = {"output": "raw", "intermediate_steps": []}
        self._patch(monkeypatch, agent)
        r = tr.process_single_document(str(_f(tmp_path)), save_to_file=False)
        assert r.get("raw_output") == "raw"

    def test_saves_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent21_tender_inspector.runner.TENDER_OUTPUT_DIR", "")
        agent = MagicMock()
        agent.invoke.return_value = {"output": "OK", "intermediate_steps": [
            ("generate_document_list", json.dumps({"documents": ["A"]}))]}
        self._patch(monkeypatch, agent)
        tr.process_single_document(str(_f(tmp_path, name="t3.pdf")), save_to_file=True)
        assert list(tmp_path.glob("*.json"))

    def test_exception_re_raised(self, tmp_path, monkeypatch):
        agent = MagicMock()
        agent.invoke.side_effect = RuntimeError("crash")
        self._patch(monkeypatch, agent)
        with pytest.raises(RuntimeError):
            tr.process_single_document(str(_f(tmp_path, name="t4.pdf")), save_to_file=False)


class TestProcessTenderDocuments:
    def test_empty_returns_empty(self):
        assert tr.process_tender_documents(sources=[]) == []

    def test_missing_dir_created(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent21_tender_inspector.runner.TENDER_DOCS_DIR",
                            str(tmp_path / "no"))
        assert tr.process_tender_documents(sources=None) == []
        assert (tmp_path / "no").exists()

    def test_empty_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent21_tender_inspector.runner.TENDER_DOCS_DIR", str(tmp_path))
        assert tr.process_tender_documents(sources=None) == []

    def test_exception_per_source_caught(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.FORCE_REPROCESS", True)
        monkeypatch.setattr("config.LLM_BACKEND", "openai")
        monkeypatch.setattr("shared.database.create_job", lambda *a, **k: "j")
        monkeypatch.setattr("shared.database.update_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.database.find_duplicate_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.tracing.get_langfuse_callback", lambda: None)
        monkeypatch.setattr("shared.tracing.log_agent_steps", lambda **k: "")
        monkeypatch.setattr("shared.telegram_notify.notify", lambda *a, **k: None)
        monkeypatch.setattr("agent21_tender_inspector.runner._extract_text", lambda d, fn: "t")
        agent = MagicMock()
        agent.invoke.side_effect = RuntimeError("crash")
        monkeypatch.setattr("agent21_tender_inspector.runner.create_tender_agent", lambda: agent)
        results = tr.process_tender_documents(
            sources=[str(_f(tmp_path, name="e.pdf"))], save_to_file=False)
        assert results[0]["error"] == "crash"
