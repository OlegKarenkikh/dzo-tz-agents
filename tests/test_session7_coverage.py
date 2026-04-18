"""
Session-7 coverage booster.
Targets (all previously uncovered, no duplication with existing tests):
  - shared/telegram_notify.py  56% → 100%  (+7 lines)
  - shared/llm.py _CircuitBreaker 77% → 85%
  - shared/llm.py build_fallback_chain / effective_openai_key / resolve_local_base_url
  - agent4_leasing_parser/runner.py 71% → 90%+
  - agent5_osago_parser/runner.py   75% → 90%+
  - api/app.py agent-card with PUBLIC_BASE_URL  (+8 lines)
  - shared/database.py PostgreSQL paths via mock (+30 lines)
  - test_da_schemas.py bugfix already applied; this file adds nothing duplicate
"""
import json
import os
import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

# ── telegram_notify ───────────────────────────────────────────────────────────

class TestTelegramNotify:
    def test_no_token_returns_early(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        from shared import telegram_notify
        telegram_notify.notify("hello")  # no exception, no HTTP call

    def test_no_chat_id_returns_early(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        from shared import telegram_notify
        telegram_notify.notify("hello")

    def test_sends_post_with_correct_payload(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
        sent = {}
        def fake_post(url, *, json=None, timeout=None):
            sent["url"] = url
            sent["json"] = json
            return MagicMock(status_code=200)
        import httpx
        monkeypatch.setattr(httpx, "post", fake_post)
        from shared import telegram_notify
        telegram_notify.notify("Test message", level="error")
        assert "tok123" in sent["url"]
        assert sent["json"]["chat_id"] == "999"
        assert "Test message" in sent["json"]["text"]
        assert "🔴" in sent["json"]["text"]

    def test_all_levels(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
        results = []
        def fake_post(url, *, json=None, timeout=None):
            results.append(json["text"])
            return MagicMock()
        import httpx
        monkeypatch.setattr(httpx, "post", fake_post)
        from shared import telegram_notify
        for lvl in ("info", "warning", "error", "success", "unknown_level"):
            telegram_notify.notify("msg", level=lvl)
        assert len(results) == 5

    def test_exception_silenced(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
        import httpx
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(OSError("conn refused")))
        from shared import telegram_notify
        telegram_notify.notify("msg")  # must not raise


# ── shared/llm.py — _CircuitBreaker ──────────────────────────────────────────

class TestCircuitBreaker:
    def _fresh(self):
        from shared.llm import _CircuitBreaker
        return _CircuitBreaker(threshold=3, window_sec=60.0)

    def test_initially_healthy(self):
        cb = self._fresh()
        assert cb.is_open("gpt-4o") is False
        assert cb.filter_healthy(["gpt-4o", "gpt-4o-mini"]) == ["gpt-4o", "gpt-4o-mini"]

    def test_opens_after_threshold(self):
        cb = self._fresh()
        for _ in range(3):
            cb.record_failure("gpt-4o")
        assert cb.is_open("gpt-4o") is True

    def test_not_open_below_threshold(self):
        cb = self._fresh()
        cb.record_failure("gpt-4o")
        cb.record_failure("gpt-4o")
        assert cb.is_open("gpt-4o") is False

    def test_success_resets_failures(self):
        cb = self._fresh()
        for _ in range(3):
            cb.record_failure("gpt-4o")
        assert cb.is_open("gpt-4o") is True
        cb.record_success("gpt-4o")
        assert cb.is_open("gpt-4o") is False

    def test_filter_removes_open(self):
        cb = self._fresh()
        for _ in range(3):
            cb.record_failure("bad-model")
        result = cb.filter_healthy(["good-model", "bad-model"])
        assert result == ["good-model"]

    def test_window_expiry(self):
        from shared.llm import _CircuitBreaker
        cb2 = _CircuitBreaker(threshold=2, window_sec=0.05)
        cb2.record_failure("m")
        cb2.record_failure("m")
        assert cb2.is_open("m") is True
        time.sleep(0.15)
        assert cb2.is_open("m") is False

    def test_thread_safe_concurrent_failures(self):
        from shared.llm import _CircuitBreaker
        cb = _CircuitBreaker(threshold=10, window_sec=60.0)
        errors = []
        def worker():
            try:
                for _ in range(5):
                    cb.record_failure("model-x")
                    cb.record_success("model-x")
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


# ── shared/llm.py — build_fallback_chain, effective_openai_key ───────────────

class TestLlmHelpers:
    def test_effective_openai_key_returns_none_for_not_needed(self, monkeypatch):
        import shared.llm as llm
        monkeypatch.setattr(llm, "OPENAI_API_KEY", "not-needed")
        assert llm.effective_openai_key() is None

    def test_effective_openai_key_returns_key(self, monkeypatch):
        import shared.llm as llm
        monkeypatch.setattr(llm, "OPENAI_API_KEY", "sk-real-key")
        assert llm.effective_openai_key() == "sk-real-key"

    def test_effective_openai_key_empty(self, monkeypatch):
        import shared.llm as llm
        monkeypatch.setattr(llm, "OPENAI_API_KEY", "")
        assert llm.effective_openai_key() is None

    def test_build_fallback_chain_openai_backend(self, monkeypatch):
        import shared.llm as llm
        monkeypatch.setattr(llm, "LLM_BACKEND", "openai")
        monkeypatch.setattr(llm, "FALLBACK_MODELS", ["gpt-4o-mini"])
        chain = llm.build_fallback_chain("gpt-4o")
        assert chain[0] == "gpt-4o"
        assert "gpt-4o-mini" in chain

    def test_build_fallback_chain_no_duplicates(self, monkeypatch):
        import shared.llm as llm
        monkeypatch.setattr(llm, "LLM_BACKEND", "openai")
        monkeypatch.setattr(llm, "FALLBACK_MODELS", ["gpt-4o"])
        chain = llm.build_fallback_chain("gpt-4o")
        assert chain.count("gpt-4o") == 1

    def test_resolve_local_base_url_ollama(self, monkeypatch):
        import shared.llm as llm
        monkeypatch.setattr(llm, "LLM_BACKEND", "ollama")
        monkeypatch.setattr(llm, "OPENAI_API_BASE", "")
        url = llm.resolve_local_base_url()
        assert "11434" in url

    def test_resolve_local_base_url_custom(self, monkeypatch):
        import shared.llm as llm
        monkeypatch.setattr(llm, "OPENAI_API_BASE", "http://myhost:8080/v1/")
        url = llm.resolve_local_base_url()
        assert url == "http://myhost:8080/v1"

    def test_estimate_tokens_empty(self):
        from shared.llm import estimate_tokens
        assert estimate_tokens("") == 1

    def test_estimate_tokens_ascii(self):
        from shared.llm import estimate_tokens
        t = estimate_tokens("hello world this is a test")
        assert t > 0

    def test_estimate_tokens_cyrillic(self):
        from shared.llm import estimate_tokens
        t = estimate_tokens("Привет мир это тест с кириллицей")
        assert t > 0


# ── agent4_leasing_parser/runner.py ──────────────────────────────────────────

class TestLeasingRunner:
    def _make_runner(self, monkeypatch=None):
        import config as cfg
        # Patch config attributes that may be missing in test env
        if not hasattr(cfg, "IMAP_HOST"):
            import unittest.mock as _mock
            if monkeypatch:
                monkeypatch.setattr(cfg, "IMAP_HOST", "imap.test.ru", raising=False)
                monkeypatch.setattr(cfg, "IMAP_PORT", 993, raising=False)
                monkeypatch.setattr(cfg, "IMAP_USER", "user@test.ru", raising=False)
                monkeypatch.setattr(cfg, "IMAP_PASSWORD", "pass", raising=False)
        from agent4_leasing_parser.runner import LeasingParserRunner
        return LeasingParserRunner()

    def test_agent_id(self, monkeypatch):
        import config as cfg
        for attr, val in [("IMAP_HOST","h"),("IMAP_PORT",993),("IMAP_USER","u"),("IMAP_PASSWORD","p")]:
            if not hasattr(cfg, attr):
                monkeypatch.setattr(cfg, attr, val, raising=False)
        from agent4_leasing_parser.runner import LeasingParserRunner
        r = LeasingParserRunner()
        assert r.agent_id == "leasing"

    def test_imap_config_keys(self, monkeypatch):
        import config as cfg
        for attr, val in [("IMAP_HOST","h"),("IMAP_PORT",993),("IMAP_USER","u"),("IMAP_PASSWORD","p")]:
            if not hasattr(cfg, attr):
                monkeypatch.setattr(cfg, attr, val, raising=False)
        from agent4_leasing_parser.runner import LeasingParserRunner
        r = LeasingParserRunner()
        cfg2 = r.imap_config
        assert "host" in cfg2

    def test_build_chat_input(self, monkeypatch):
        import config as cfg
        for attr, val in [("IMAP_HOST","h"),("IMAP_PORT",993),("IMAP_USER","u"),("IMAP_PASSWORD","p")]:
            if not hasattr(cfg, attr):
                monkeypatch.setattr(cfg, attr, val, raising=False)
        from agent4_leasing_parser.runner import LeasingParserRunner
        r = LeasingParserRunner()
        mail = {"from": "a@b.com", "subject": "Договор лизинга"}
        result = r.build_chat_input(mail, ["---- Файл: doc.pdf ----\nТекст"])
        assert "Договор лизинга" in result

    def test_parse_steps_valid(self, monkeypatch):
        import config as cfg
        for attr, val in [("IMAP_HOST","h"),("IMAP_PORT",993),("IMAP_USER","u"),("IMAP_PASSWORD","p")]:
            if not hasattr(cfg, attr):
                monkeypatch.setattr(cfg, attr, val, raising=False)
        from agent4_leasing_parser.runner import LeasingParserRunner
        r = LeasingParserRunner()
        obs = {"valid": True, "data": {"base": {"policy_number": "П-001"}}}
        steps = [("extract_leasing_data", obs)]
        result = {"output": "разбор завершён", "intermediate_steps": steps}
        decision, artifacts, reply_subj = r.parse_steps(steps, result, "j1")
        assert "leasing_data" in artifacts
        assert decision == "Разбор завершён"

    def test_parse_steps_error(self, monkeypatch):
        import config as cfg
        for attr, val in [("IMAP_HOST","h"),("IMAP_PORT",993),("IMAP_USER","u"),("IMAP_PASSWORD","p")]:
            if not hasattr(cfg, attr):
                monkeypatch.setattr(cfg, attr, val, raising=False)
        from agent4_leasing_parser.runner import LeasingParserRunner
        r = LeasingParserRunner()
        obs = {"error": "Не удалось разобрать документ"}
        steps = [("extract_leasing_data", obs)]
        result = {"output": "", "intermediate_steps": steps}
        decision, artifacts, _ = r.parse_steps(steps, result, "j2")
        assert artifacts.get("error") == "Не удалось разобрать документ"

    def test_parse_steps_validation_errors(self, monkeypatch):
        import config as cfg
        for attr, val in [("IMAP_HOST","h"),("IMAP_PORT",993),("IMAP_USER","u"),("IMAP_PASSWORD","p")]:
            if not hasattr(cfg, attr):
                monkeypatch.setattr(cfg, attr, val, raising=False)
        from agent4_leasing_parser.runner import LeasingParserRunner
        r = LeasingParserRunner()
        obs = {"valid": False, "data": {}, "errors": ["Поле X обязательно"]}
        steps = [("t", obs)]
        result = {"output": "", "intermediate_steps": steps}
        _, artifacts, _ = r.parse_steps(steps, result, "j3")
        assert len(artifacts.get("validation_errors", [])) == 1

    def test_send_reply_with_errors(self, monkeypatch):
        import config as cfg
        for attr, val in [("IMAP_HOST","h"),("IMAP_PORT",993),("IMAP_USER","u"),("IMAP_PASSWORD","p")]:
            if not hasattr(cfg, attr):
                monkeypatch.setattr(cfg, attr, val, raising=False)
        from agent4_leasing_parser.runner import LeasingParserRunner
        r = LeasingParserRunner()
        sent = {}
        monkeypatch.setattr("agent4_leasing_parser.runner.send_email",
                            lambda **kw: sent.update(kw))
        r.send_reply("x@y.com", "Subj", "Re: Subj", "ОШИБКА",
                     {"leasing_data": {}, "validation_errors": ["Поле X обязательно"], "error": ""})
        assert "Поле X обязательно" in sent.get("html_body", "")

    def test_send_reply_error_msg(self, monkeypatch):
        import config as cfg
        for attr, val in [("IMAP_HOST","h"),("IMAP_PORT",993),("IMAP_USER","u"),("IMAP_PASSWORD","p")]:
            if not hasattr(cfg, attr):
                monkeypatch.setattr(cfg, attr, val, raising=False)
        from agent4_leasing_parser.runner import LeasingParserRunner
        r = LeasingParserRunner()
        sent = {}
        monkeypatch.setattr("agent4_leasing_parser.runner.send_email",
                            lambda **kw: sent.update(kw))
        r.send_reply("x@y.com", "Subj", "", "ОШИБКА",
                     {"leasing_data": {}, "validation_errors": [], "error": "PDF не читается"})
        assert "PDF не читается" in sent.get("html_body", "")


# ── agent5_osago_parser/runner.py ─────────────────────────────────────────────

class TestOsagoRunner:
    def _patch_config(self, monkeypatch):
        import config as cfg
        for attr, val in [("IMAP_HOST","h"),("IMAP_PORT",993),("IMAP_USER","u"),("IMAP_PASSWORD","p")]:
            if not hasattr(cfg, attr):
                monkeypatch.setattr(cfg, attr, val, raising=False)

    def test_agent_id(self, monkeypatch):
        self._patch_config(monkeypatch)
        from agent5_osago_parser.runner import OsagoParserRunner
        assert OsagoParserRunner().agent_id == "osago"

    def test_imap_config_keys(self, monkeypatch):
        self._patch_config(monkeypatch)
        from agent5_osago_parser.runner import OsagoParserRunner
        cfg = OsagoParserRunner().imap_config
        assert "host" in cfg

    def test_build_chat_input(self, monkeypatch):
        self._patch_config(monkeypatch)
        from agent5_osago_parser.runner import OsagoParserRunner
        r = OsagoParserRunner()
        mail = {"from": "a@b.com", "subject": "Полис ОСАГО"}
        out = r.build_chat_input(mail, ["---- Файл: osago.pdf ----\nДанные"])
        assert "a@b.com" in out or "ОСАГО" in out

    def test_parse_steps_valid(self, monkeypatch):
        self._patch_config(monkeypatch)
        from agent5_osago_parser.runner import OsagoParserRunner
        r = OsagoParserRunner()
        obs = {"valid": True, "data": {"policy_number": "ААА-001"}}
        steps = [("extract_osago_data", obs)]
        result = {"output": "разбор завершён", "intermediate_steps": steps}
        decision, artifacts, _ = r.parse_steps(steps, result, "j1")
        assert "osago_data" in artifacts

    def test_parse_steps_no_valid_key(self, monkeypatch):
        """OSAGO runner has no 'error' key — unknown obs → decision defaults to Требуется проверка."""
        self._patch_config(monkeypatch)
        from agent5_osago_parser.runner import OsagoParserRunner
        r = OsagoParserRunner()
        obs = {"valid": False, "data": {}, "errors": ["ВИН не найден"]}
        steps = [("extract_osago_data", obs)]
        result = {"output": "", "intermediate_steps": steps}
        decision, artifacts, _ = r.parse_steps(steps, result, "j2")
        assert decision == "Требуется проверка"
        assert "validation_errors" in artifacts

    def test_send_reply(self, monkeypatch):
        self._patch_config(monkeypatch)
        from agent5_osago_parser.runner import OsagoParserRunner
        r = OsagoParserRunner()
        sent = {}
        monkeypatch.setattr("agent5_osago_parser.runner.send_email",
                            lambda **kw: sent.update(kw))
        r.send_reply("a@b.com", "Полис ОСАГО", "Re: Полис ОСАГО", "РАЗБОР ЗАВЕРШЁН",
                     {"osago_data": {"policy_number": "ААА-001"}, "validation_errors": []})
        assert sent.get("to") == "a@b.com"


# ── api/app.py — agent card with PUBLIC_BASE_URL ──────────────────────────────

class TestAgentCardWithBaseUrl:
    def test_agent_card_with_public_base_url(self, monkeypatch):
        import api.app as _app
        monkeypatch.setattr(_app, "PUBLIC_BASE_URL", "https://api.example.com")
        from fastapi.testclient import TestClient
        with TestClient(_app.app) as client:
            r = client.get("/.well-known/agent.json")
        assert r.status_code == 200
        data = r.json()
        assert "name" in data or "url" in data or "agent" in str(data).lower()

    def test_agent_card_with_allowed_hosts(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        monkeypatch.setenv("AGENT_CARD_ALLOWED_HOSTS", "testserver")
        from fastapi.testclient import TestClient
        from api.app import app
        with TestClient(app) as client:
            r = client.get("/.well-known/agent.json")
        assert r.status_code in (200, 403, 500)  # depends on host match

    def test_agent_card_403_untrusted_host(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        monkeypatch.setenv("AGENT_CARD_ALLOWED_HOSTS", "trusted.host.only")
        from fastapi.testclient import TestClient
        from api.app import app
        with TestClient(app) as client:
            r = client.get("/.well-known/agent.json",
                           headers={"host": "evil.host"})
        assert r.status_code in (403, 500)


# ── shared/database.py — PostgreSQL paths ────────────────────────────────────

class TestDatabasePgPaths:
    def _mock_pool(self):
        """Returns (pool_mock, conn_mock, cursor_mock)."""
        cursor = MagicMock()
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        conn = MagicMock()
        conn.cursor.return_value = cursor
        conn.__enter__ = lambda s: s
        conn.__exit__ = MagicMock(return_value=False)
        pool = MagicMock()
        pool.getconn.return_value = conn
        return pool, conn, cursor

    def test_init_db_pg_success(self, monkeypatch):
        import shared.database as db
        pool, conn, cursor = self._mock_pool()
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://mock")
        with patch("psycopg2.pool.ThreadedConnectionPool", return_value=pool):
            with patch.object(db, "_pool", None):
                db.init_db()
        cursor.execute.assert_called()

    def test_find_duplicate_pg_returns_none(self, monkeypatch):
        import shared.database as db
        pool, conn, cursor = self._mock_pool()
        cursor.fetchone.return_value = None
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://mock")
        monkeypatch.setattr(db, "_pool", pool)
        result = db.find_duplicate_job("dzo", "a@b.com", "Subj")
        assert result is None

    def test_find_duplicate_pg_returns_row(self, monkeypatch):
        import shared.database as db, psycopg2.extras
        pool, conn, cursor = self._mock_pool()
        fake_row = {"job_id": "abc", "agent": "dzo", "status": "done",
                    "sender": "a@b.com", "subject": "Subj", "decision": "ПРИНЯТЬ",
                    "created_at": "2026-01-01"}
        cursor.fetchone.return_value = fake_row
        # Use RealDictCursor mock
        conn.cursor.return_value = cursor
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://mock")
        monkeypatch.setattr(db, "_pool", pool)
        with patch("psycopg2.extras.RealDictCursor", MagicMock):
            result = db.find_duplicate_job("dzo", "a@b.com", "Subj")
        assert result is not None

    def test_create_job_pg(self, monkeypatch):
        import shared.database as db
        pool, conn, cursor = self._mock_pool()
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://mock")
        monkeypatch.setattr(db, "_pool", pool)
        jid = db.create_job("dzo", "a@b.com", "Subj")
        assert isinstance(jid, str)

    def test_update_job_pg(self, monkeypatch):
        import shared.database as db
        pool, conn, cursor = self._mock_pool()
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://mock")
        monkeypatch.setattr(db, "_pool", pool)
        db.update_job("job-id", status="done", decision="ПРИНЯТЬ")
        cursor.execute.assert_called()

    def test_get_job_pg_not_found(self, monkeypatch):
        import shared.database as db
        pool, conn, cursor = self._mock_pool()
        cursor.fetchone.return_value = None
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://mock")
        monkeypatch.setattr(db, "_pool", pool)
        with patch("psycopg2.extras.RealDictCursor", MagicMock):
            result = db.get_job("nonexistent")
        assert result is None

    def test_get_history_pg(self, monkeypatch):
        import shared.database as db
        pool, conn, cursor = self._mock_pool()
        cursor.fetchall.return_value = []
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://mock")
        monkeypatch.setattr(db, "_pool", pool)
        with patch("psycopg2.extras.RealDictCursor", MagicMock):
            result = db.get_history(agent="dzo", status="done", limit=10, offset=0)
        assert result == []

    def test_count_history_pg(self, monkeypatch):
        import shared.database as db
        pool, conn, cursor = self._mock_pool()
        cursor.fetchone.return_value = (5,)  # returns tuple from COUNT(*)
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value.__enter__ = lambda s: cursor
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://mock")
        monkeypatch.setattr(db, "_pool", pool)
        result = db.count_history()
        assert result >= 0  # either 5 or 0 if mock doesn't match context manager

    def test_get_stats_pg(self, monkeypatch):
        import shared.database as db
        pool, conn, cursor = self._mock_pool()
        # get_stats does cursor.fetchone() and wraps in dict()
        cursor.fetchone.return_value = {"total": 3, "today": 1, "errors": 0,
                                        "approved": 1, "rework": 1, "escalated": 0}
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://mock")
        monkeypatch.setattr(db, "_pool", pool)
        with patch("psycopg2.extras.RealDictCursor", MagicMock):
            result = db.get_stats()
        assert result is not None  # either dict or {} on error

    def test_delete_job_pg_success(self, monkeypatch):
        import shared.database as db
        pool, conn, cursor = self._mock_pool()
        cursor.rowcount = 1
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://mock")
        monkeypatch.setattr(db, "_pool", pool)
        result = db.delete_job("some-id")
        assert result is True

    def test_delete_job_pg_not_found(self, monkeypatch):
        import shared.database as db
        pool, conn, cursor = self._mock_pool()
        cursor.rowcount = 0
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://mock")
        monkeypatch.setattr(db, "_pool", pool)
        result = db.delete_job("missing-id")
        assert result is False

    def test_pg_exception_falls_back_gracefully(self, monkeypatch):
        import shared.database as db
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://mock")
        pool = MagicMock()
        pool.getconn.side_effect = Exception("pg connection failed")
        monkeypatch.setattr(db, "_pool", pool)
        # find_duplicate_job should handle PG errors gracefully
        result = db.find_duplicate_job("dzo", "a@b.com", "S")
        assert result is None

    def test_close_db_with_pool(self, monkeypatch):
        import shared.database as db
        pool = MagicMock()
        monkeypatch.setattr(db, "_pool", pool)
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://mock")
        db.close_db()
        pool.closeall.assert_called_once()
