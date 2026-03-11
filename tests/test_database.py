import pytest
from unittest.mock import patch  # noqa: F401
import shared.database as db


@pytest.fixture(autouse=True)
def clear_memory_store():
    """Oчищает in-memory хранилище до каждого теста."""
    db._memory_store.clear()
    yield
    db._memory_store.clear()


@pytest.fixture(autouse=False)
def no_postgres(monkeypatch):
    monkeypatch.setattr(db, "DATABASE_URL", "")


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
        db.update_job(job_id, status="done", decision="Соответствует",
                      result={"sections": 8})
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
        rows = db.get_history()
        assert len(rows) == 3

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

    def test_get_history_limit(self, no_postgres):
        for _ in range(10):
            db.create_job("dzo")
        rows = db.get_history(limit=3)
        assert len(rows) == 3

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
