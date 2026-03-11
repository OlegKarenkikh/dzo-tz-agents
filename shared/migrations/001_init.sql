-- Миграция 001: инициальная схема
-- Запускается автоматически через docker-entrypoint-initdb.d

CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT        PRIMARY KEY,
    agent       TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'pending',
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

-- Триггер: автообновление updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
