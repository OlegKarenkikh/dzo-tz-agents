-- Миграция 002: добавить колонку trace (если её нет)
-- Идемпотентная, безопасна для повторного применения.
-- Нужна потому что database.py добавляет trace через inline ALTER при init_db(),
-- но миграции 001_* не содержат эту колонку.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS trace JSONB;

COMMENT ON COLUMN jobs.trace IS 'Структурированный трейс шагов агента (tool_name, tool_input, latency_ms)';
