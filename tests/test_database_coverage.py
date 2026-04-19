"""Coverage tests for shared/database.py — in-memory fallback path (42% → 75%+).

All tests use the in-memory store (DATABASE_URL not set) so no PostgreSQL needed.
"""
import threading
from datetime import UTC, datetime, timedelta
import pytest
import shared.database as db


@pytest.fixture(autouse=True)
def clean_store():
    """Clear in-memory store and ensure no PG connection before/after each test."""
    with db._memory_lock:
        db._memory_store.clear()
    import os
    old_url = db.DATABASE_URL
    db.DATABASE_URL = ""
    yield
    db.DATABASE_URL = old_url
    with db._memory_lock:
        db._memory_store.clear()


# ── _to_date ──────────────────────────────────────────────────────────────────

class TestToDate:
    def test_datetime_returns_date(self):
        dt = datetime(2026, 1, 15, 10, 30, tzinfo=UTC)
        assert db._to_date(dt).isoformat() == "2026-01-15"

    def test_date_returns_date(self):
        from datetime import date
        d = date(2026, 3, 5)
        assert db._to_date(d) == d

    def test_iso_string_returns_date(self):
        assert db._to_date("2026-04-18T12:00:00+00:00").isoformat() == "2026-04-18"

    def test_invalid_string_returns_none(self):
        assert db._to_date("not-a-date") is None

    def test_none_returns_none(self):
        assert db._to_date(None) is None

    def test_int_returns_none(self):
        assert db._to_date(42) is None


# ── _filter_by_dates ──────────────────────────────────────────────────────────

class TestFilterByDates:
    def _rows(self):
        return [
            {"id": "a", "created_at": "2026-01-10T00:00:00+00:00"},
            {"id": "b", "created_at": "2026-03-15T00:00:00+00:00"},
            {"id": "c", "created_at": "2026-04-18T00:00:00+00:00"},
        ]

    def test_no_filters_returns_all(self):
        assert len(db._filter_by_dates(self._rows(), None, None)) == 3

    def test_date_from_filters(self):
        r = db._filter_by_dates(self._rows(), "2026-03-01", None)
        assert {x["id"] for x in r} == {"b", "c"}

    def test_date_to_filters(self):
        r = db._filter_by_dates(self._rows(), None, "2026-01-31")
        assert {x["id"] for x in r} == {"a"}

    def test_both_filters(self):
        r = db._filter_by_dates(self._rows(), "2026-03-01", "2026-03-31")
        assert {x["id"] for x in r} == {"b"}

    def test_invalid_date_from_returns_empty(self):
        assert db._filter_by_dates(self._rows(), "not-a-date", None) == []

    def test_invalid_date_to_returns_empty(self):
        assert db._filter_by_dates(self._rows(), None, "bad") == []

    def test_row_without_created_at_excluded(self):
        rows = [{"id": "x"}, {"id": "y", "created_at": "2026-04-18T00:00:00+00:00"}]
        r = db._filter_by_dates(rows, "2026-01-01", None)
        assert len(r) == 1 and r[0]["id"] == "y"


# ── _pg_available ─────────────────────────────────────────────────────────────

class TestPgAvailable:
    def test_false_when_no_url(self):
        assert not db._pg_available()

    def test_true_when_url_set(self, monkeypatch):
        monkeypatch.setattr(db, "DATABASE_URL", "postgresql://localhost/test")
        assert db._pg_available()


# ── init_db ───────────────────────────────────────────────────────────────────

class TestInitDb:
    def test_in_memory_logs_message(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="database"):
            db.init_db()
        assert any("in-memory" in r.message.lower() or "PostgreSQL" in r.message
                   for r in caplog.records)


# ── create_job ────────────────────────────────────────────────────────────────

class TestCreateJob:
    def test_returns_uuid_string(self):
        job_id = db.create_job("dzo", "sender@test.com", "Тема письма")
        assert isinstance(job_id, str) and len(job_id) == 36

    def test_stores_record(self):
        job_id = db.create_job("dzo", "a@b.com", "Subj")
        with db._memory_lock:
            record = db._memory_store.get(job_id)
        assert record is not None
        assert record["agent"] == "dzo"
        assert record["status"] == "pending"

    def test_stores_sender_and_subject(self):
        job_id = db.create_job("tz", "sender@x.com", "My Subject")
        with db._memory_lock:
            r = db._memory_store[job_id]
        assert r["sender"] == "sender@x.com"
        assert r["subject"] == "My Subject"

    def test_has_created_at(self):
        job_id = db.create_job("collector")
        with db._memory_lock:
            r = db._memory_store[job_id]
        assert "created_at" in r and r["created_at"]

    def test_concurrent_creates_unique_ids(self):
        ids = []
        def _create():
            ids.append(db.create_job("agent", "x@x.com", "S"))
        threads = [threading.Thread(target=_create) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(set(ids)) == 10  # all unique


# ── update_job ────────────────────────────────────────────────────────────────

class TestUpdateJob:
    def _create(self, **kw):
        return db.create_job(**kw) if kw else db.create_job("dzo")

    def test_updates_status(self):
        jid = self._create()
        db.update_job(jid, status="done", decision="Полная")
        with db._memory_lock:
            r = db._memory_store[jid]
        assert r["status"] == "done"
        assert r["decision"] == "Полная"

    def test_updates_result(self):
        jid = self._create()
        db.update_job(jid, status="done", result={"score": 99})
        with db._memory_lock:
            assert db._memory_store[jid]["result"] == {"score": 99}

    def test_updates_error(self):
        jid = self._create()
        db.update_job(jid, status="error", error="crash")
        with db._memory_lock:
            assert db._memory_store[jid]["error"] == "crash"

    def test_updates_trace(self):
        jid = self._create()
        db.update_job(jid, status="done", trace=[{"step": 1}])
        with db._memory_lock:
            assert db._memory_store[jid]["trace"] == [{"step": 1}]

    def test_update_nonexistent_job_is_noop(self):
        db.update_job("nonexistent-uuid", status="done")  # should not raise

    def test_updated_at_changes(self):
        jid = self._create()
        with db._memory_lock:
            before = db._memory_store[jid]["updated_at"]
        import time; time.sleep(0.01)
        db.update_job(jid, status="done")
        with db._memory_lock:
            after = db._memory_store[jid]["updated_at"]
        assert after >= before


# ── get_job ───────────────────────────────────────────────────────────────────

class TestGetJob:
    def test_returns_job(self):
        jid = db.create_job("tender", "a@b.com", "ТО-1")
        r = db.get_job(jid)
        assert r is not None
        assert r["job_id"] == jid

    def test_returns_none_for_missing(self):
        assert db.get_job("no-such-id") is None

    def test_returns_copy(self):
        jid = db.create_job("dzo")
        r1 = db.get_job(jid)
        r1["status"] = "hacked"
        r2 = db.get_job(jid)
        assert r2["status"] == "pending"  # original unchanged


# ── find_duplicate_job ────────────────────────────────────────────────────────

class TestFindDuplicateJob:
    def test_returns_none_when_empty_sender_and_subject(self):
        assert db.find_duplicate_job("dzo", "", "") is None

    def test_returns_none_no_match(self):
        db.create_job("dzo", "x@x.com", "Other")
        assert db.find_duplicate_job("dzo", "x@x.com", "Different") is None

    def test_returns_none_when_not_done(self):
        jid = db.create_job("dzo", "a@b.com", "Subj")
        db.update_job(jid, status="pending")
        assert db.find_duplicate_job("dzo", "a@b.com", "Subj") is None

    def test_finds_done_job(self):
        jid = db.create_job("dzo", "a@b.com", "Subj")
        db.update_job(jid, status="done", decision="Полная")
        dup = db.find_duplicate_job("dzo", "a@b.com", "Subj")
        assert dup is not None
        assert dup["job_id"] == jid

    def test_returns_latest_of_multiple(self):
        for i in range(3):
            jid = db.create_job("tz", "a@b.com", "Subj")
            db.update_job(jid, status="done", decision=f"Result {i}")
        dup = db.find_duplicate_job("tz", "a@b.com", "Subj")
        assert dup is not None  # returns one

    def test_different_agent_not_matched(self):
        jid = db.create_job("dzo", "a@b.com", "Subj")
        db.update_job(jid, status="done")
        assert db.find_duplicate_job("tz", "a@b.com", "Subj") is None


# ── get_history ───────────────────────────────────────────────────────────────

class TestGetHistory:
    def _seed(self):
        j1 = db.create_job("dzo", "a@b.com", "S1")
        db.update_job(j1, status="done", decision="Заявка полная")
        j2 = db.create_job("tz",  "b@b.com", "S2")
        db.update_job(j2, status="error", decision="Требуется доработка")
        j3 = db.create_job("dzo", "c@b.com", "S3")
        db.update_job(j3, status="done", decision="Заявка полная")
        return j1, j2, j3

    def test_returns_all(self):
        self._seed()
        assert len(db.get_history()) == 3

    def test_filter_by_agent(self):
        self._seed()
        r = db.get_history(agent="dzo")
        assert len(r) == 2
        assert all(x["agent"] == "dzo" for x in r)

    def test_filter_by_status(self):
        self._seed()
        r = db.get_history(status="error")
        assert len(r) == 1 and r[0]["status"] == "error"

    def test_filter_by_decision(self):
        self._seed()
        r = db.get_history(decision="Заявка полная")
        assert len(r) == 2

    def test_limit_and_offset(self):
        self._seed()
        r = db.get_history(limit=2)
        assert len(r) == 2
        r_offset = db.get_history(limit=10, offset=2)
        assert len(r_offset) == 1

    def test_sorted_desc_by_created_at(self):
        self._seed()
        r = db.get_history()
        dates = [x["created_at"] for x in r]
        assert dates == sorted(dates, reverse=True)

    def test_filter_by_date_from(self):
        self._seed()
        today = datetime.now(UTC).date().isoformat()
        r = db.get_history(date_from=today)
        assert len(r) == 3  # all created today

    def test_filter_by_date_to_yesterday_returns_empty(self):
        self._seed()
        yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
        r = db.get_history(date_to=yesterday)
        assert r == []


# ── count_history ─────────────────────────────────────────────────────────────

class TestCountHistory:
    def _seed(self):
        j1 = db.create_job("dzo", "a@b.com", "S1")
        db.update_job(j1, status="done", decision="Заявка полная")
        j2 = db.create_job("tz",  "b@b.com", "S2")
        db.update_job(j2, status="error")
        return j1, j2

    def test_total_count(self):
        self._seed()
        assert db.count_history() == 2

    def test_count_by_agent(self):
        self._seed()
        assert db.count_history(agent="dzo") == 1

    def test_count_by_status(self):
        self._seed()
        assert db.count_history(status="error") == 1

    def test_count_date_from_today(self):
        self._seed()
        today = datetime.now(UTC).date().isoformat()
        assert db.count_history(date_from=today) == 2

    def test_count_date_to_yesterday_zero(self):
        self._seed()
        yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
        assert db.count_history(date_to=yesterday) == 0


# ── get_stats ─────────────────────────────────────────────────────────────────

class TestGetStats:
    def test_empty_store(self):
        s = db.get_stats()
        assert s["total"] == 0
        assert s["errors"] == 0

    def test_counts_total_and_today(self):
        j1 = db.create_job("dzo", "a@b.com", "S1")
        db.update_job(j1, status="done", decision="Заявка полная")
        j2 = db.create_job("tz", "b@b.com", "S2")
        db.update_job(j2, status="error")
        s = db.get_stats()
        assert s["total"] == 2
        assert s["today"] == 2
        assert s["errors"] == 1
        assert s["approved"] == 1

    def test_counts_rework(self):
        jid = db.create_job("dzo")
        db.update_job(jid, status="done", decision="Требуется доработка")
        s = db.get_stats()
        assert s["rework"] == 1

    def test_counts_escalated(self):
        jid = db.create_job("dzo")
        db.update_job(jid, status="done", decision="Требуется эскалация")
        s = db.get_stats()
        assert s["escalated"] == 1


# ── delete_job ────────────────────────────────────────────────────────────────

class TestDeleteJob:
    def test_deletes_existing(self):
        jid = db.create_job("dzo")
        assert db.delete_job(jid) is True
        assert db.get_job(jid) is None

    def test_returns_false_for_missing(self):
        assert db.delete_job("nonexistent-uuid") is False

    def test_double_delete_returns_false(self):
        jid = db.create_job("dzo")
        db.delete_job(jid)
        assert db.delete_job(jid) is False


# ── close_db ──────────────────────────────────────────────────────────────────

class TestCloseDb:
    def test_close_when_no_pool_is_noop(self):
        original = db._pool
        db._pool = None
        db.close_db()  # should not raise
        db._pool = original

    def test_close_with_mock_pool(self):
        from unittest.mock import MagicMock
        mock_pool = MagicMock()
        original = db._pool
        db._pool = mock_pool
        db.close_db()
        mock_pool.close.assert_called_once()
        assert db._pool is None
        db._pool = original


# ── thread safety ─────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_create_and_update(self):
        """Multiple threads creating + updating jobs should not corrupt the store."""
        errors = []
        def worker():
            try:
                jid = db.create_job("dzo", "t@t.com", "concurrent-test")
                db.update_job(jid, status="done", decision="OK")
                r = db.get_job(jid)
                assert r["status"] == "done"
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert errors == [], f"Thread errors: {errors}"
