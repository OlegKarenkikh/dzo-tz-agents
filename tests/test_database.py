# ruff: noqa: I001
import pytest
from unittest.mock import patch  # noqa: F401

import shared.database as db


@pytest.fixture(autouse=True)
def clear_memory_store():
    db._memory_store.clear()
    yield
    db._memory_store.clear()


@pytest.fixture(autouse=False)
def no_postgres(monkeypatch):
    monkeypatch.setattr(db, "DATABASE_URL", "")
    # Сбрасываем кешированный пул — иначе _get_pool() вернёт старый объект
    # и _pg_available() == False не предотвратит обращение к реальному PG
    original_pool = db._pool
    db._pool = None
    yield
    db._pool = original_pool


class TestInMemoryStorage:
    def test_create_job(self, no_postgres):
        job_id = db.create_job("dzo", sender="test@test.com", subject="Test")
        assert job_id
        job = db.get_job(job_id)
        assert job["agent"] == "dzo"
        assert job["status"] == "pending"
        assert job["sender"] == "test@test.com"

    def test_update_job(self, no_postgres):
        job_id = db.create_job("tz")
        db.update_job(job_id, status="done", decision="Соответствует", result={"sections": 8})
        job = db.get_job(job_id)
        assert job["status"] == "done"
        assert job["decision"] == "Соответствует"
        assert job["result"]["sections"] == 8

    def test_update_job_error(self, no_postgres):
        job_id = db.create_job("dzo")
        db.update_job(job_id, status="error", error="LLM timeout")
        job = db.get_job(job_id)
        assert job["status"] == "error"
        assert job["error"] == "LLM timeout"

    def test_get_nonexistent_job(self, no_postgres):
        assert db.get_job("nonexistent-id") is None

    def test_delete_job(self, no_postgres):
        job_id = db.create_job("dzo")
        assert db.delete_job(job_id) is True
        assert db.get_job(job_id) is None

    def test_delete_nonexistent(self, no_postgres):
        assert db.delete_job("no-such-id") is False

    def test_get_history_all(self, no_postgres):
        db.create_job("dzo", subject="Заявка 1")
        db.create_job("tz", subject="ТЗ 1")
        db.create_job("dzo", subject="Заявка 2")
        assert len(db.get_history()) == 3

    def test_get_history_filter_agent(self, no_postgres):
        db.create_job("dzo")
        db.create_job("tz")
        db.create_job("dzo")
        rows = db.get_history(agent="dzo")
        assert len(rows) == 2
        assert all(r["agent"] == "dzo" for r in rows)

    def test_get_history_filter_decision(self, no_postgres):
        j1 = db.create_job("dzo")
        j2 = db.create_job("dzo")
        db.update_job(j1, status="done", decision="Заявка полная")
        db.update_job(j2, status="done", decision="Требуется доработка")
        rows = db.get_history(decision="Требуется доработка")
        assert len(rows) == 1
        assert rows[0]["decision"] == "Требуется доработка"

    def test_get_history_filter_status(self, no_postgres):
        j1 = db.create_job("dzo")
        j2 = db.create_job("dzo")
        db.update_job(j1, status="done", decision="Заявка полная")
        db.update_job(j2, status="error", error="timeout")
        rows = db.get_history(status="error")
        assert len(rows) == 1
        assert rows[0]["status"] == "error"

    def test_get_history_limit(self, no_postgres):
        for _ in range(10):
            db.create_job("dzo")
        assert len(db.get_history(limit=3)) == 3

    def test_get_stats(self, no_postgres):
        j1 = db.create_job("dzo")
        j2 = db.create_job("tz")
        j3 = db.create_job("dzo")
        db.update_job(j1, status="done", decision="Заявка полная")
        db.update_job(j2, status="done", decision="Требуется доработка")
        db.update_job(j3, status="error", error="timeout")
        stats = db.get_stats()
        assert stats["total"] == 3
        assert stats["errors"] == 1
        assert stats["approved"] == 1
        assert stats["rework"] == 1

    def test_count_history_no_filters(self, no_postgres):
        db.create_job("dzo")
        db.create_job("tz")
        db.create_job("dzo")
        assert db.count_history() == 3

    def test_count_history_filter_agent(self, no_postgres):
        db.create_job("dzo")
        db.create_job("tz")
        db.create_job("dzo")
        assert db.count_history(agent="dzo") == 2
        assert db.count_history(agent="tz") == 1

    def test_count_history_filter_status(self, no_postgres):
        j1 = db.create_job("dzo")
        j2 = db.create_job("dzo")
        db.update_job(j1, status="done", decision="Заявка полная")
        db.update_job(j2, status="error", error="timeout")
        assert db.count_history(status="done") == 1
        assert db.count_history(status="error") == 1

    def test_count_history_filter_decision(self, no_postgres):
        j1 = db.create_job("dzo")
        j2 = db.create_job("dzo")
        db.update_job(j1, status="done", decision="Заявка полная")
        db.update_job(j2, status="done", decision="Требуется доработка")
        assert db.count_history(decision="Заявка полная") == 1

    def test_count_history_filter_date_range(self, no_postgres):
        j1 = db.create_job("dzo")
        j2 = db.create_job("dzo")
        # Manually set created_at for testing date filters
        db._memory_store[j1]["created_at"] = "2024-01-01T00:00:00"
        db._memory_store[j2]["created_at"] = "2024-06-15T00:00:00"
        assert db.count_history(date_from="2024-03-01") == 1
        assert db.count_history(date_to="2024-03-01") == 1
        assert db.count_history(date_from="2024-01-01", date_to="2024-12-31") == 2
        assert db.count_history(date_from="2025-01-01") == 0

    def test_date_filter_same_day_datetime_vs_date(self, no_postgres):
        """Records with ISO datetime created_at should match plain date filters for the same day."""
        j1 = db.create_job("dzo")
        db._memory_store[j1]["created_at"] = "2024-01-01T12:30:00"
        # date_to="2024-01-01" must include records from that day
        assert db.count_history(date_to="2024-01-01") == 1
        assert db.get_history(date_to="2024-01-01") == [db._memory_store[j1]]

    def test_invalid_date_returns_empty(self, no_postgres):
        """Invalid date_from/date_to must return empty results (match PG error behaviour)."""
        j1 = db.create_job("dzo")
        db._memory_store[j1]["created_at"] = "2024-06-15T00:00:00"
        assert db.get_history(date_from="not-a-date") == []
        assert db.get_history(date_to="garbage") == []
        assert db.count_history(date_from="not-a-date") == 0
        assert db.count_history(date_to="garbage") == 0

    def test_close_db_no_error_when_no_pool(self, no_postgres):
        db.close_db()  # should not raise
