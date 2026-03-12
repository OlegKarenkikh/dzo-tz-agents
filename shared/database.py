"""
PostgreSQL хранилище для истории обработок.
Использует psycopg2 с ThreadedConnectionPool.
Fallback: если DATABASE_URL не задан — хранит в памяти (in-memory dict).
"""
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, UTC
from uuid import uuid4

logger = logging.getLogger("database")

DATABASE_URL = os.getenv("DATABASE_URL", "")

# In-memory фоллбэк (если нет PostgreSQL)
_memory_store: dict[str, dict] = {}

# Пул соединений — инициализируется при первом обращении (lazy)
_pool = None


def _pg_available() -> bool:
    return bool(DATABASE_URL)


def _get_pool():
    global _pool
    if _pool is None:
        import psycopg2.pool
        _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, DATABASE_URL)
        logger.info("Пул psycopg2-соединений инициализирован (min=2, max=10).")
    return _pool


@contextmanager
def _get_conn():
    """Context manager: берёт соединение из пула и возвращает в пул через finally."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


def init_db():
    """Создаёт таблицу jobs если она не существует."""
    if not _pg_available():
        logger.info("ПостгреСЖЛ не настроен, используется in-memory хранилище.")
        return
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id      TEXT PRIMARY KEY,
                    agent       TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'pending',
                    decision    TEXT,
                    sender      TEXT,
                    subject     TEXT,
                    result      JSONB,
                    error       TEXT,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_agent      ON jobs(agent);
                CREATE INDEX IF NOT EXISTS idx_jobs_status     ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_decision   ON jobs(decision);
            """)
            conn.commit()
            cur.close()
        logger.info("Таблица jobs готова.")
    except Exception as e:
        logger.error(f"init_db ошибка: {e}")


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def create_job(agent: str, sender: str = "", subject: str = "") -> str:
    """Создаёт новое задание, возвращает job_id."""
    job_id = str(uuid4())
    now = _now_utc()
    record = {
        "job_id":     job_id,
        "agent":      agent,
        "status":     "pending",
        "decision":   None,
        "sender":     sender,
        "subject":    subject,
        "result":     None,
        "error":      None,
        "created_at": now,
        "updated_at": now,
    }
    if _pg_available():
        try:
            with _get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO jobs (job_id, agent, status, sender, subject, created_at, updated_at)
                    VALUES (%s, %s, 'pending', %s, %s, NOW(), NOW())
                """, (job_id, agent, sender, subject))
                conn.commit()
                cur.close()
        except Exception as e:
            logger.error(f"create_job ошибка: {e}")
    else:
        _memory_store[job_id] = record
    return job_id


def update_job(
    job_id: str,
    status: str,
    decision: str | None = None,
    result: dict | None = None,
    error: str | None = None,
):
    """Обновляет статус задания."""
    if _pg_available():
        try:
            with _get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE jobs
                    SET status = %s, decision = %s, result = %s, error = %s, updated_at = NOW()
                    WHERE job_id = %s
                """, (status, decision, json.dumps(result) if result else None, error, job_id))
                conn.commit()
                cur.close()
        except Exception as e:
            logger.error(f"update_job ошибка: {e}")
    else:
        if job_id in _memory_store:
            _memory_store[job_id].update({
                "status":     status,
                "decision":   decision,
                "result":     result,
                "error":      error,
                "updated_at": _now_utc(),
            })


def get_job(job_id: str) -> dict | None:
    """Возвращает задание по job_id или None."""
    if _pg_available():
        try:
            import psycopg2.extras
            with _get_conn() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("SELECT * FROM jobs WHERE job_id = %s", (job_id,))
                row = cur.fetchone()
                cur.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_job ошибка: {e}")
            return None
    return _memory_store.get(job_id)


def get_history(
    agent: str | None = None,
    decision: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Возвращает историю с фильтрами, включая фильтрацию по status в SQL."""
    if _pg_available():
        try:
            import psycopg2.extras
            with _get_conn() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                filters: list[str] = []
                params: list = []
                if agent:
                    filters.append("agent = %s")
                    params.append(agent)
                if decision:
                    filters.append("decision = %s")
                    params.append(decision)
                if status:
                    filters.append("status = %s")
                    params.append(status)
                if date_from:
                    filters.append("created_at >= %s")
                    params.append(date_from)
                if date_to:
                    filters.append("created_at <= %s")
                    params.append(date_to)
                where = ("WHERE " + " AND ".join(filters)) if filters else ""
                params += [limit, offset]
                cur.execute(
                    f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    params,
                )
                rows = cur.fetchall()
                cur.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_history ошибка: {e}")
            return []
    # In-memory фильтрация
    rows = list(_memory_store.values())
    if agent:
        rows = [r for r in rows if r.get("agent") == agent]
    if decision:
        rows = [r for r in rows if r.get("decision") == decision]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows[offset:offset + limit]


def get_stats() -> dict[str, int]:
    """Аггрегированная статистика для Dashboard."""
    if _pg_available():
        try:
            import psycopg2.extras
            with _get_conn() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("""
                    SELECT
                        COUNT(*)                                          AS total,
                        COUNT(*) FILTER (WHERE DATE(created_at) = CURRENT_DATE) AS today,
                        COUNT(*) FILTER (WHERE status = 'error')          AS errors,
                        COUNT(*) FILTER (WHERE decision ILIKE '%полная%')  AS approved,
                        COUNT(*) FILTER (WHERE decision ILIKE '%доработ%') AS rework,
                        COUNT(*) FILTER (WHERE decision ILIKE '%эскал%')   AS escalated
                    FROM jobs
                """)
                row = dict(cur.fetchone())
                cur.close()
            return row
        except Exception as e:
            logger.error(f"get_stats ошибка: {e}")
            return {}
    rows = list(_memory_store.values())
    today = datetime.now(UTC).date().isoformat()
    return {
        "total":     len(rows),
        "today":     sum(1 for r in rows if r.get("created_at", "")[:10] == today),
        "errors":    sum(1 for r in rows if r.get("status") == "error"),
        "approved":  sum(1 for r in rows if "полная" in (r.get("decision") or "").lower()),
        "rework":    sum(1 for r in rows if "доработ" in (r.get("decision") or "").lower()),
        "escalated": sum(1 for r in rows if "эскал" in (r.get("decision") or "").lower()),
    }


def delete_job(job_id: str) -> bool:
    """Удаляет задание. Возвращает True если задание существовало."""
    if _pg_available():
        try:
            with _get_conn() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM jobs WHERE job_id = %s", (job_id,))
                deleted = cur.rowcount
                conn.commit()
                cur.close()
            return deleted > 0
        except Exception as e:
            logger.error(f"delete_job ошибка: {e}")
            return False
    if job_id in _memory_store:
        del _memory_store[job_id]
        return True
    return False
