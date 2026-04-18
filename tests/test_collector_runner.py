"""Coverage tests for agent3_collector_inspector/runner.py (0% → 80%+)."""
import json
import pathlib
from unittest.mock import MagicMock
import pytest
import agent3_collector_inspector.runner as cr


def _make_json_file(tmp_path, data: dict, name="tender.json") -> pathlib.Path:
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


class TestBuildOutputPath:
    def test_no_output_dir_returns_sibling(self, tmp_path):
        src = str(tmp_path / "input.json")
        result = cr._build_output_path(src, output_dir="")
        assert result.parent == tmp_path
        assert result.suffix == ".json"
        assert "result" in result.name

    def test_with_output_dir_creates_dir(self, tmp_path):
        src = str(tmp_path / "input.json")
        out_dir = str(tmp_path / "results")
        result = cr._build_output_path(src, output_dir=out_dir)
        assert result.parent.exists()
        assert result.parent == pathlib.Path(out_dir)

    def test_hash_suffix_in_filename(self, tmp_path):
        src = str(tmp_path / "tender42.json")
        result = cr._build_output_path(src, output_dir="")
        parts = result.stem.replace("_result", "").split("_")
        assert any(len(p) == 8 for p in parts)


class TestSaveJsonResult:
    def test_writes_valid_json(self, tmp_path):
        p = tmp_path / "out.json"
        cr._save_json_result({"foo": "бар", "n": 42}, p)
        data = json.loads(p.read_text("utf-8"))
        assert data["foo"] == "бар"


class TestExtractCollectorResult:
    def test_returns_empty_on_empty_steps(self):
        assert cr._extract_collector_result([]) == {}

    def test_returns_empty_when_wrong_tool(self):
        steps = [("some_other_tool", json.dumps({"tender_id": "T1"}))]
        assert cr._extract_collector_result(steps) == {}

    def test_extracts_correct_tool_result(self):
        payload = {"tender_id": "T1", "received_count": 3, "total_expected_participants": 5}
        steps = [("collect_tender_documents", json.dumps(payload))]
        result = cr._extract_collector_result(steps)
        assert result["tender_id"] == "T1"
        assert result["received_count"] == 3

    def test_extracts_error_result(self):
        payload = {"error": "Участник не ответил"}
        steps = [("collect_tender_documents", json.dumps(payload))]
        assert cr._extract_collector_result(steps)["error"] == "Участник не ответил"

    def test_skips_malformed_step(self):
        steps = [
            "not-a-list",
            ("only_one_element",),
            ("collect_tender_documents", "INVALID_JSON{{{"),
            ("collect_tender_documents", json.dumps({"tender_id": "T2"})),
        ]
        result = cr._extract_collector_result(steps)
        assert result["tender_id"] == "T2"

    def test_obs_dict_without_tender_id_or_error_skipped(self):
        steps = [("collect_tender_documents", json.dumps({"other_key": "val"}))]
        assert cr._extract_collector_result(steps) == {}

    def test_dict_obs_not_string(self):
        payload = {"tender_id": "T3", "received_count": 1, "total_expected_participants": 2}
        steps = [("collect_tender_documents", payload)]
        result = cr._extract_collector_result(steps)
        assert result["tender_id"] == "T3"


class TestProcessSingleInputErrors:
    def test_missing_file_returns_error(self, tmp_path):
        result = cr.process_single_input(str(tmp_path / "ghost.json"))
        assert result["status"] == "error"

    def test_non_json_file_returns_error(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(b"fake-pdf")
        result = cr.process_single_input(str(p))
        assert result["status"] == "error"

    def test_invalid_json_returns_error(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("NOT JSON{{{", encoding="utf-8")
        result = cr.process_single_input(str(p))
        assert result["status"] == "error"

    def test_missing_tender_id_returns_error(self, tmp_path):
        p = _make_json_file(tmp_path, {"emails": ["a@b.com"]})
        result = cr.process_single_input(str(p))
        assert result["status"] == "error"
        assert "tender_id" in result["error"].lower()


class TestProcessSingleInputDedup:
    def test_dedup_no_result_key_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.FORCE_REPROCESS", False)
        monkeypatch.setattr("shared.database.find_duplicate_job",
                            lambda *a, **k: {"tender_id": "T1", "received_count": 2})
        p = _make_json_file(tmp_path, {"tender_id": "T1"})
        result = cr.process_single_input(str(p))
        assert result == {}

    def test_dedup_with_result_key_returns_it(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.FORCE_REPROCESS", False)
        monkeypatch.setattr("shared.database.find_duplicate_job",
                            lambda *a, **k: {"created_at": None,
                                             "result": {"tender_id": "T1", "received_count": 5}})
        p = _make_json_file(tmp_path, {"tender_id": "T1"})
        result = cr.process_single_input(str(p))
        assert result["received_count"] == 5


class TestProcessSingleInputHappy:
    def _patch(self, monkeypatch, agent):
        monkeypatch.setattr("config.FORCE_REPROCESS", True)
        monkeypatch.setattr("shared.database.create_job", lambda *a, **k: "j")
        monkeypatch.setattr("shared.database.update_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.database.find_duplicate_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.tracing.get_langfuse_callback", lambda: None)
        monkeypatch.setattr("shared.tracing.log_agent_steps", lambda **k: "")
        monkeypatch.setattr("shared.telegram_notify.notify", lambda *a, **k: None)
        monkeypatch.setattr("agent3_collector_inspector.runner.create_collector_agent",
                            lambda: agent)

    def test_success_extracts_result(self, tmp_path, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = {
            "output": "OK",
            "intermediate_steps": [
                ("collect_tender_documents", json.dumps(
                    {"tender_id": "T1", "received_count": 3,
                     "total_expected_participants": 5}))
            ],
        }
        self._patch(monkeypatch, agent)
        p = _make_json_file(tmp_path, {"tender_id": "T1"})
        result = cr.process_single_input(str(p), save_to_file=False)
        assert result["tender_id"] == "T1"

    def test_tool_error_recorded(self, tmp_path, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = {
            "output": "",
            "intermediate_steps": [
                ("collect_tender_documents", json.dumps({"error": "Нет ответа"}))
            ],
        }
        self._patch(monkeypatch, agent)
        p = _make_json_file(tmp_path, {"tender_id": "T2"})
        result = cr.process_single_input(str(p), save_to_file=False)
        assert result["error"] == "Нет ответа"

    def test_no_tool_result_uses_raw_output(self, tmp_path, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = {"output": "raw text", "intermediate_steps": []}
        self._patch(monkeypatch, agent)
        p = _make_json_file(tmp_path, {"tender_id": "T3"})
        result = cr.process_single_input(str(p), save_to_file=False)
        assert result.get("raw_output") == "raw text"

    def test_saves_to_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent3_collector_inspector.runner.COLLECTOR_OUTPUT_DIR", "")
        agent = MagicMock()
        agent.invoke.return_value = {
            "output": "",
            "intermediate_steps": [
                ("collect_tender_documents", json.dumps(
                    {"tender_id": "T4", "received_count": 1,
                     "total_expected_participants": 1}))
            ],
        }
        self._patch(monkeypatch, agent)
        p = _make_json_file(tmp_path, {"tender_id": "T4"})
        cr.process_single_input(str(p), save_to_file=True)
        assert len(list(tmp_path.glob("*_result.json"))) >= 1

    def test_exception_re_raised(self, tmp_path, monkeypatch):
        agent = MagicMock()
        agent.invoke.side_effect = RuntimeError("crash")
        self._patch(monkeypatch, agent)
        p = _make_json_file(tmp_path, {"tender_id": "T5"})
        with pytest.raises(RuntimeError, match="crash"):
            cr.process_single_input(str(p), save_to_file=False)


class TestProcessCollectorInputs:
    def test_empty_sources_returns_empty(self):
        assert cr.process_collector_inputs(sources=[]) == []

    def test_none_sources_missing_dir_creates_it(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent3_collector_inspector.runner.COLLECTOR_INPUT_DIR",
                            str(tmp_path / "no_such"))
        assert cr.process_collector_inputs(sources=None) == []
        assert (tmp_path / "no_such").exists()

    def test_none_sources_empty_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent3_collector_inspector.runner.COLLECTOR_INPUT_DIR",
                            str(tmp_path))
        assert cr.process_collector_inputs(sources=None) == []

    def _patch_ok(self, monkeypatch, agent):
        monkeypatch.setattr("config.FORCE_REPROCESS", True)
        monkeypatch.setattr("shared.database.create_job", lambda *a, **k: "j")
        monkeypatch.setattr("shared.database.update_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.database.find_duplicate_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.tracing.get_langfuse_callback", lambda: None)
        monkeypatch.setattr("shared.tracing.log_agent_steps", lambda **k: "")
        monkeypatch.setattr("shared.telegram_notify.notify", lambda *a, **k: None)
        monkeypatch.setattr("agent3_collector_inspector.runner.create_collector_agent",
                            lambda: agent)

    def test_batch_processes_multiple(self, tmp_path, monkeypatch):
        agent = MagicMock()
        agent.invoke.return_value = {
            "output": "", "intermediate_steps": [
                ("collect_tender_documents", json.dumps(
                    {"tender_id": "TX", "received_count": 1,
                     "total_expected_participants": 1}))
            ]
        }
        self._patch_ok(monkeypatch, agent)
        p1 = _make_json_file(tmp_path, {"tender_id": "B1"}, "t1.json")
        p2 = _make_json_file(tmp_path, {"tender_id": "B2"}, "t2.json")
        results = cr.process_collector_inputs(
            sources=[str(p1), str(p2)], save_to_file=False)
        assert len(results) == 2

    def test_batch_catches_per_source_exception(self, tmp_path, monkeypatch):
        agent = MagicMock()
        agent.invoke.side_effect = RuntimeError("crash")
        self._patch_ok(monkeypatch, agent)
        p = _make_json_file(tmp_path, {"tender_id": "TX"})
        results = cr.process_collector_inputs(sources=[str(p)], save_to_file=False)
        assert results[0]["error"] == "crash"

    def test_scans_json_from_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent3_collector_inspector.runner.COLLECTOR_INPUT_DIR",
                            str(tmp_path))
        agent = MagicMock()
        agent.invoke.return_value = {
            "output": "", "intermediate_steps": [
                ("collect_tender_documents", json.dumps(
                    {"tender_id": "DIR", "received_count": 0,
                     "total_expected_participants": 1}))
            ]
        }
        self._patch_ok(monkeypatch, agent)
        _make_json_file(tmp_path, {"tender_id": "DIR"}, "d.json")
        (tmp_path / "skip.txt").write_text("ignored")
        results = cr.process_collector_inputs(sources=None, save_to_file=False)
        assert len(results) == 1


class TestCollectorEmailRunner:
    def _r(self):
        return cr.CollectorEmailRunner()

    def test_agent_id(self):
        assert self._r().agent_id == "collector"

    def test_imap_config_keys(self):
        for k in ("host", "user", "password", "port"):
            assert k in self._r().imap_config

    def test_build_chat_input(self):
        mail = {"from": "a@b.com", "subject": "ТО-1", "date": "2026-01-01",
                "body": "Письмо", "attachments": []}
        txt = self._r().build_chat_input(mail, ["---- Файл: f.pdf ----\ntext"])
        assert "ТО-1" in txt and "a@b.com" in txt

    def test_parse_steps_no_result(self):
        d, a, _ = self._r().parse_steps([], {"output": "raw"}, "j")
        assert d == "Требуется доработка"

    def test_parse_steps_with_result(self):
        steps = [("collect_tender_documents", json.dumps(
            {"tender_id": "T", "received_count": 2, "total_expected_participants": 3}))]
        d, _, _ = self._r().parse_steps(steps, {}, "j")
        assert "2/3" in d

    def test_send_reply(self, monkeypatch):
        sent = []
        monkeypatch.setattr("agent3_collector_inspector.runner.send_email",
                            lambda **kw: sent.append(kw))
        self._r().send_reply("a@b.com", "S", "Re:S", "Собрано 1/2", {"report_text": "Отчёт"})
        assert sent
