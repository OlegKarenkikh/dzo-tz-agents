-- 002_add_trace_column.sql
-- Идемпотентное добавление колонки trace (если ещё не существует).
-- FIX DA-01: фиксирует отсутствие колонки trace в старых инстансах.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS trace JSONB;
