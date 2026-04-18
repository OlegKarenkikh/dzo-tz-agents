"""Coverage tests for shared/runner_base.py (59% → 80%+)."""
import json
from unittest.mock import MagicMock
import pytest
from shared.runner_base import BaseAgentRunner, BaseEmailRunner


class TestBaseAgentRunner:
    def _runner(self, agent=None):
        return BaseAgentRunner(graph_agent=agent or MagicMock(), agent_label="test")

    def test_invoke_returns_output(self):
        from langchain_core.messages import AIMessage
        agent = MagicMock()
        agent.invoke.return_value = {"messages": [AIMessage(content="ПРИНЯТЬ")],
                                     "intermediate_steps": []}
        result = self._runner(agent).invoke({"input": "x"})
        assert "ПРИНЯТЬ" in result["output"]

    def test_content_list_joined(self):
        from langchain_core.messages import AIMessage
        agent = MagicMock()
        agent.invoke.return_value = {
            "messages": [AIMessage(content=["Part1", "Part2"])], "intermediate_steps": []}
        result = self._runner(agent).invoke({"input": "x"})
        assert "Part1" in result["output"]

    def test_fallback_from_tool_messages(self):
        from langchain_core.messages import AIMessage, ToolMessage
        agent = MagicMock()
        tm = ToolMessage(content=json.dumps({"decision": "ЭСКАЛАЦИЯ"}), tool_call_id="t1")
        agent.invoke.return_value = {
            "messages": [AIMessage(content=""), tm], "intermediate_steps": []}
        result = self._runner(agent).invoke({"input": "x"})
        assert "ЭСКАЛАЦИЯ" in result["output"] or "decision" in result["output"].lower()

    def test_tool_messages_extracted_as_steps(self):
        from langchain_core.messages import AIMessage, ToolMessage
        agent = MagicMock()
        tm = ToolMessage(content=json.dumps({"d": "X"}), tool_call_id="tc", name="my_tool")
        agent.invoke.return_value = {"messages": [AIMessage(content="ok"), tm],
                                     "intermediate_steps": []}
        result = self._runner(agent).invoke({"input": "x"})
        assert any(s[0] == "my_tool" for s in result["intermediate_steps"])

    def test_validate_output_false_empty(self):
        assert not self._runner()._validate_output("")
        assert not self._runner()._validate_output("gibberish")

    def test_validate_output_true_for_keywords(self):
        runner = self._runner()
        for kw in ["принять", "вернуть на доработку", "decision", "требуется доработка"]:
            assert runner._validate_output(kw)

    def test_non_dict_result_returns_empty_output(self):
        agent = MagicMock()
        agent.invoke.return_value = "just a string"
        result = self._runner(agent).invoke({"input": "x"})
        assert result["output"] == ""


class ConcreteEmailRunner(BaseEmailRunner):
    @property
    def agent_id(self): return "tst"
    @property
    def imap_config(self): return {"host": "h", "user": "u", "password": "p", "port": 993}
    def create_agent(self): return MagicMock()
    def build_chat_input(self, mail, texts): return f"FROM:{mail['from']}"
    def parse_steps(self, steps, result, job_id): return "ПРИНЯТЬ", {}, "Re:"
    def send_reply(self, sender, subject, rs, decision, arts): pass


class TestBaseEmailRunnerHooks:
    def test_handle_no_attachments_default(self):
        assert not ConcreteEmailRunner().handle_no_attachments("a@b", "S", "j")

    def test_db_result_fields_excludes_bytes(self):
        r = ConcreteEmailRunner().db_result_fields(
            {"attachments": ["a", "b"]}, {"text": "ok", "raw": b"skip"})
        assert r["attachments"] == 2
        assert r["text"] == "ok"
        assert "raw" not in r


class TestProcessSingleMail:
    def _m(self, **kw):
        b = {"from": "s@x.com", "subject": "Subj", "body": "b", "attachments": []}
        b.update(kw)
        return b

    def test_dedup_skipped(self, monkeypatch):
        monkeypatch.setattr("shared.database.find_duplicate_job",
                            lambda *a, **k: {"decision": "X", "created_at": None})
        logger = MagicMock()
        ConcreteEmailRunner()._process_single_mail(self._m(), MagicMock(), logger, False)
        logger.info.assert_called()

    def test_force_reprocess_bypasses_dedup(self, monkeypatch):
        monkeypatch.setattr("shared.database.find_duplicate_job",
                            lambda *a, **k: {"decision": "X"})
        monkeypatch.setattr("shared.database.create_job", lambda *a, **k: "j")
        monkeypatch.setattr("shared.database.update_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.tracing.get_langfuse_callback", lambda: None)
        monkeypatch.setattr("shared.tracing.log_agent_steps", lambda **k: "")
        monkeypatch.setattr("shared.file_extractor.extract_text_from_attachment", lambda a: "t")
        monkeypatch.setattr("shared.telegram_notify.notify", lambda *a, **k: None)
        agent = MagicMock()
        agent.invoke.return_value = {"output": "ПРИНЯТЬ", "intermediate_steps": [], "messages": []}
        ConcreteEmailRunner()._process_single_mail(self._m(), agent, MagicMock(), True)
        assert agent.invoke.called

    def test_no_attachments_skip(self, monkeypatch):
        monkeypatch.setattr("shared.database.find_duplicate_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.database.create_job", lambda *a, **k: "j")
        monkeypatch.setattr("shared.database.update_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.telegram_notify.notify", lambda *a, **k: None)
        class NoAtt(ConcreteEmailRunner):
            def handle_no_attachments(self, *a): return True
        agent = MagicMock()
        NoAtt()._process_single_mail(self._m(attachments=[]), agent, MagicMock(), True)
        agent.invoke.assert_not_called()

    def test_timeout_recorded(self, monkeypatch):
        import concurrent.futures
        monkeypatch.setattr("shared.database.find_duplicate_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.database.create_job", lambda *a, **k: "j")
        monkeypatch.setattr("shared.file_extractor.extract_text_from_attachment", lambda a: "t")
        monkeypatch.setattr("shared.telegram_notify.notify", lambda *a, **k: None)
        updates = []
        monkeypatch.setattr("shared.database.update_job", lambda jid, **kw: updates.append(kw))
        agent = MagicMock()
        agent.invoke.side_effect = concurrent.futures.TimeoutError()
        ConcreteEmailRunner()._process_single_mail(self._m(), agent, MagicMock(), True)
        assert any(u.get("status") == "error" for u in updates)

    def test_generic_exception_recorded(self, monkeypatch):
        monkeypatch.setattr("shared.database.find_duplicate_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.database.create_job", lambda *a, **k: "j")
        monkeypatch.setattr("shared.file_extractor.extract_text_from_attachment", lambda a: "t")
        monkeypatch.setattr("shared.telegram_notify.notify", lambda *a, **k: None)
        updates = []
        monkeypatch.setattr("shared.database.update_job", lambda jid, **kw: updates.append(kw))
        agent = MagicMock()
        agent.invoke.side_effect = Exception("boom")
        ConcreteEmailRunner()._process_single_mail(self._m(), agent, MagicMock(), True)
        assert any(u.get("status") == "error" for u in updates)

    def test_empty_decision_defaults(self, monkeypatch):
        monkeypatch.setattr("shared.database.find_duplicate_job", lambda *a, **k: None)
        monkeypatch.setattr("shared.database.create_job", lambda *a, **k: "j")
        monkeypatch.setattr("shared.tracing.get_langfuse_callback", lambda: None)
        monkeypatch.setattr("shared.tracing.log_agent_steps", lambda **k: "")
        monkeypatch.setattr("shared.file_extractor.extract_text_from_attachment", lambda a: "t")
        monkeypatch.setattr("shared.telegram_notify.notify", lambda *a, **k: None)
        updates = []
        monkeypatch.setattr("shared.database.update_job", lambda jid, **kw: updates.append(kw))
        agent = MagicMock()
        agent.invoke.return_value = {"output": "", "intermediate_steps": [], "messages": []}
        class Empty(ConcreteEmailRunner):
            def parse_steps(self, *a): return "", {}, ""
        Empty()._process_single_mail(self._m(), agent, MagicMock(), True)
        assert any(u.get("decision") == "Требуется доработка" for u in updates)
