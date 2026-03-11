-- Миграция 001: создание таблицы jobs
-- Запуск: psql $DATABASE_URL -f shared/migrations/001_create_jobs.sql

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

COMMENT ON TABLE  jobs              IS 'История обработок документов агентами';
COMMENT ON COLUMN jobs.job_id      IS 'UUID задания';
COMMENT ON COLUMN jobs.agent       IS 'dzo | tz | auto';
COMMENT ON COLUMN jobs.status      IS 'pending | running | done | error';
COMMENT ON COLUMN jobs.decision    IS 'Решение агента';
COMMENT ON COLUMN jobs.sender      IS 'Email отправителя';
COMMENT ON COLUMN jobs.subject     IS 'Тема письма';
COMMENT ON COLUMN jobs.result      IS 'JSON-отчёт агента';
COMMENT ON COLUMN jobs.error       IS 'Текст ошибки если status=error';
