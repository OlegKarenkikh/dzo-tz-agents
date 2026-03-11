"""
PostgreSQL хранилище для истории обработок.
Использует asyncpg (напрямую) через asyncio или psycopg2 (синхронно).
Fallback: если DATABASE_URL не задан — хранит в памяти (in-memory dict).
"""
import os
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4

logger = logging.getLogger("database")

DATABASE_URL = os.getenv("DATABASE_URL", "")

# In-memory фоллбэк (если нет PostgreSQL)
_memory_store: Dict[str, Dict] = {}


def _pg_available() -> bool:
    return bool(DATABASE_URL)


def _get_conn():
    import psycopg2
    import psycopg2.extras
    return psycopg2.connect(DATABASE_URL)


def init_db():
    """Создаёт таблицу jobs если она не существует."""
    if not _pg_available():
        logger.info("ПостгреSQL не настроен, используется in-memory хранилище.")
        return
    try:
        conn = _get_conn()
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
        conn.close()
        logger.info("Таблица jobs готова.")
    except Exception as e:
        logger.error(f"init_db ошибка: {e}")


def create_job(agent: str, sender: str = "", subject: str = "") -> str:
    """Cоздаёт новое задание, возвращает job_id."""
    job_id = str(uuid4())
    now = datetime.utcnow().isoformat()
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
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO jobs (job_id, agent, status, sender, subject, created_at, updated_at)
                VALUES (%s, %s, 'pending', %s, %s, NOW(), NOW())
            """, (job_id, agent, sender, subject))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"create_job ошибка: {e}")
    else:
        _memory_store[job_id] = record
    return job_id


def update_job(
    job_id: str,
    status: str,
    decision: Optional[str] = None,
    result: Optional[Dict] = None,
    error: Optional[str] = None,
):
    """Oбновляет статус задания."""
    if _pg_available():
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""
                UPDATE jobs
                SET status = %s, decision = %s, result = %s, error = %s, updated_at = NOW()
                WHERE job_id = %s
            """, (status, decision, json.dumps(result) if result else None, error, job_id))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"update_job ошибка: {e}")
    else:
        if job_id in _memory_store:
            _memory_store[job_id].update({
                "status":     status,
                "decision":   decision,
                "result":     result,
                "error":      error,
                "updated_at": datetime.utcnow().isoformat(),
            })


def get_job(job_id: str) -> Optional[Dict]:
    """Vозвращает задание по job_id или None."""
    if _pg_available():
        try:
            import psycopg2.extras
            conn = _get_conn()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM jobs WHERE job_id = %s", (job_id,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_job ошибка: {e}")
            return None
    return _memory_store.get(job_id)


def get_history(
    agent: Optional[str] = None,
    decision: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict]:
    """Vозвращает историю с фильтрами."""
    if _pg_available():
        try:
            import psycopg2.extras
            conn = _get_conn()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            filters = []
            params = []
            if agent:     filters.append("agent = %s");      params.append(agent)
            if decision:  filters.append("decision = %s");   params.append(decision)
            if date_from: filters.append("created_at >= %s"); params.append(date_from)
            if date_to:   filters.append("created_at <= %s"); params.append(date_to)
            where = ("WHERE " + " AND ".join(filters)) if filters else ""
            params += [limit, offset]
            cur.execute(
                f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                params
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_history ошибка: {e}")
            return []
    # In-memory фильтрация
    rows = list(_memory_store.values())
    if agent:    rows = [r for r in rows if r.get("agent") == agent]
    if decision: rows = [r for r in rows if r.get("decision") == decision]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows[offset:offset + limit]


def get_stats() -> Dict[str, Any]:
    """Aггрегированная статистика для Dashboard."""
    if _pg_available():
        try:
            import psycopg2.extras
            conn = _get_conn()
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
            conn.close()
            return row
        except Exception as e:
            logger.error(f"get_stats ошибка: {e}")
            return {}
    rows = list(_memory_store.values())
    today = datetime.utcnow().date().isoformat()
    return {
        "total":     len(rows),
        "today":     sum(1 for r in rows if r.get("created_at", "")[:10] == today),
        "errors":    sum(1 for r in rows if r.get("status") == "error"),
        "approved":  sum(1 for r in rows if "полная" in (r.get("decision") or "").lower()),
        "rework":    sum(1 for r in rows if "доработ" in (r.get("decision") or "").lower()),
        "escalated": sum(1 for r in rows if "эскал" in (r.get("decision") or "").lower()),
    }


def delete_job(job_id: str) -> bool:
    """Uдаляет задание. Возвращает True если задание существовало."""
    if _pg_available():
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("DELETE FROM jobs WHERE job_id = %s", (job_id,))
            deleted = cur.rowcount
            conn.commit()
            cur.close()
            conn.close()
            return deleted > 0
        except Exception as e:
            logger.error(f"delete_job ошибка: {e}")
            return False
    if job_id in _memory_store:
        del _memory_store[job_id]
        return True
    return False
