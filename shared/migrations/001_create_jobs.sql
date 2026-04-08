-- 001_create_jobs.sql
-- Основная миграция: создание таблицы jobs со всеми индексами.
-- FIX DU-03: объединяет 001_init.sql и 001_create_jobs.sql в один файл.

CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT        PRIMARY KEY,
    agent       TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'pending',
    decision    TEXT,
    sender      TEXT,
    subject     TEXT,
    result      JSONB,
    trace       JSONB,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE jobs IS 'История обработок агентами (ДЗО / ТЗ / Тендер)';

CREATE INDEX IF NOT EXISTS idx_jobs_agent      ON jobs(agent);
CREATE INDEX IF NOT EXISTS idx_jobs_status     ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_decision   ON jobs(decision);
CREATE INDEX IF NOT EXISTS idx_jobs_sender     ON jobs(sender);

-- Автообновление updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_jobs_updated_at ON jobs;
CREATE TRIGGER trg_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
