"""
PostgreSQL хранилище для истории обработок.
Использует psycopg2 с ThreadedConnectionPool.
Fallback: если DATABASE_URL не задан — хранит в памяти (in-memory dict).
"""
import json
import logging
import os
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, date as _date
from uuid import uuid4

logger = logging.getLogger("database")

DATABASE_URL = os.getenv("DATABASE_URL", "")

_memory_store: dict[str, dict] = {}
_memory_lock = threading.RLock()  # FIX RC-04: защита _memory_store от concurrent mutation

_pool = None
_pool_lock = threading.Lock()  # FIX RC-01: защита от double-init ThreadedConnectionPool


def _to_date(value) -> _date | None:
    """Convert a datetime, date, or ISO-format string to a date object."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


def _filter_by_dates(rows: list[dict], date_from: str | None, date_to: str | None) -> list[dict]:
    """Filter in-memory rows by date_from / date_to using proper date comparison."""
    date_from_obj = _to_date(date_from) if date_from else None
    date_to_obj = _to_date(date_to) if date_to else None
    if date_from and date_from_obj is None:
        return []
    if date_to and date_to_obj is None:
        return []
    if date_from_obj:
        rows = [
            r for r in rows
            if (d := _to_date(r.get("created_at"))) is not None and d >= date_from_obj
        ]
    if date_to_obj:
        rows = [
            r for r in rows
            if (d := _to_date(r.get("created_at"))) is not None and d <= date_to_obj
        ]
    return rows


def _pg_available() -> bool:
    return bool(DATABASE_URL)


def _get_pool():
    """FIX RC-01: double-checked locking — безопасная инициализация пула."""
    global _pool
    if _pool is None:              # fast path без блокировки
        with _pool_lock:
            if _pool is None:      # double-checked locking
                import psycopg2.pool
                _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, DATABASE_URL)
                logger.info("Пул psycopg2-соединений инициализирован (min=2, max=10).")
    return _pool


@contextmanager
def _get_conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        try:
            pool.putconn(conn)
        except Exception:
            logger.warning("Не удалось вернуть соединение в пул, закрываем принудительно")
            try:
                conn.close()
            except Exception:
                pass


def close_db():
    """Закрывает пул соединений (для graceful shutdown)."""
    global _pool
    if _pool is not None:
        try:
            _pool.closeall()
            logger.info("Пул соединений PostgreSQL закрыт.")
        except Exception as e:
            logger.error("Ошибка при закрытии пула: %s", e)
        finally:
            _pool = None


def init_db():
    """Создаёт таблицу jobs если она не существует.
    Добавляет колонку trace если она ещё не существует (идемпотентная миграция).
    """
    if not _pg_available():
        logger.info("PostgreSQL не настроен, используется in-memory хранилище.")
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
                    trace       JSONB,
                    error       TEXT,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_agent      ON jobs(agent);
                CREATE INDEX IF NOT EXISTS idx_jobs_status     ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_decision   ON jobs(decision);
                CREATE INDEX IF NOT EXISTS idx_jobs_sender     ON jobs(sender);
                ALTER TABLE jobs ADD COLUMN IF NOT EXISTS trace JSONB;
            """)
            conn.commit()
            cur.close()
        logger.info("Таблица jobs готова (включая trace-колонку).")
    except Exception as e:
        logger.error("init_db ошибка: %s", e)


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def find_duplicate_job(
    agent: str,
    sender: str,
    subject: str,
) -> dict | None:
    """Ищет последнее завершённое задание с тем же (agent, sender, subject)."""
    if not sender and not subject:
        return None
    if _pg_available():
        try:
            import psycopg2.extras
            with _get_conn() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("""
                    SELECT * FROM jobs
                    WHERE agent = %s
                      AND sender = %s
                      AND subject = %s
                      AND status = 'done'
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (agent, sender, subject))
                row = cur.fetchone()
                cur.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error("find_duplicate_job ошибка: %s", e)
            return None
    # FIX RC-04: in-memory fallback с блокировкой
    with _memory_lock:
        rows = [
            r for r in _memory_store.values()
            if r.get("agent") == agent
            and r.get("sender") == sender
            and r.get("subject") == subject
            and r.get("status") == "done"
        ]
    if not rows:
        return None
    return max(rows, key=lambda r: r.get("created_at", ""))


def create_job(agent: str, sender: str = "", subject: str = "") -> str:
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
        "trace":      None,
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
            logger.error("create_job ошибка: %s", e)
    else:
        # FIX RC-04: защита _memory_store
        with _memory_lock:
            _memory_store[job_id] = record
    return job_id


def update_job(
    job_id: str,
    status: str,
    decision: str | None = None,
    result: dict | None = None,
    error: str | None = None,
    trace: list | None = None,
):
    if _pg_available():
        try:
            with _get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE jobs
                    SET status = %s, decision = %s, result = %s, trace = %s,
                        error = %s, updated_at = NOW()
                    WHERE job_id = %s
                """, (
                    status,
                    decision,
                    json.dumps(result) if result else None,
                    json.dumps(trace) if trace else None,
                    error,
                    job_id,
                ))
                conn.commit()
                cur.close()
        except Exception as e:
            logger.error("update_job ошибка: %s", e)
    else:
        # FIX RC-04: защита _memory_store
        with _memory_lock:
            if job_id in _memory_store:
                _memory_store[job_id].update({
                    "status":     status,
                    "decision":   decision,
                    "result":     result,
                    "trace":      trace,
                    "error":      error,
                    "updated_at": _now_utc(),
                })


def get_job(job_id: str) -> dict | None:
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
            logger.error("get_job ошибка: %s", e)
            return None
    # FIX RC-04
    with _memory_lock:
        return dict(_memory_store[job_id]) if job_id in _memory_store else None


def get_history(
    agent: str | None = None,
    decision: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
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
                    filters.append("created_at >= %s::date")
                    params.append(date_from)
                if date_to:
                    filters.append("created_at < (%s::date + interval '1 day')")
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
            logger.error("get_history ошибка: %s", e)
            return []
    # FIX RC-04: snapshot под блокировкой
    with _memory_lock:
        rows = list(_memory_store.values())
    if agent:
        rows = [r for r in rows if r.get("agent") == agent]
    if decision:
        rows = [r for r in rows if r.get("decision") == decision]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows = _filter_by_dates(rows, date_from, date_to)
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows[offset:offset + limit]


def count_history(
    agent: str | None = None,
    decision: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    if _pg_available():
        try:
            with _get_conn() as conn:
                with conn.cursor() as cur:
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
                        filters.append("created_at >= %s::date")
                        params.append(date_from)
                    if date_to:
                        filters.append("created_at < (%s::date + interval '1 day')")
                        params.append(date_to)
                    where = ("WHERE " + " AND ".join(filters)) if filters else ""
                    cur.execute(f"SELECT COUNT(*) FROM jobs {where}", params)
                    total = cur.fetchone()[0]
            return total
        except Exception as e:
            logger.error("count_history ошибка: %s", e)
            return 0
    # FIX RC-04
    with _memory_lock:
        rows = list(_memory_store.values())
    if agent:
        rows = [r for r in rows if r.get("agent") == agent]
    if decision:
        rows = [r for r in rows if r.get("decision") == decision]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows = _filter_by_dates(rows, date_from, date_to)
    return len(rows)


def get_stats() -> dict[str, int]:
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
            logger.error("get_stats ошибка: %s", e)
            return {}
    # FIX RC-04
    with _memory_lock:
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
            logger.error("delete_job ошибка: %s", e)
            return False
    # FIX RC-04
    with _memory_lock:
        if job_id in _memory_store:
            del _memory_store[job_id]
            return True
    return False
