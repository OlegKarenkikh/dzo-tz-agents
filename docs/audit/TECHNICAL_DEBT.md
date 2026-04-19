# TECHNICAL_DEBT.md — dzo-tz-agents

> Реестр намеренно отложенных задач по итогам аудита 2026-04-19.

| ID | Файл | Описание | Severity | Причина отложения | Плановый спринт |
|----|------|----------|----------|--------------------|-----------------|
| TD-01 | `api/app.py` | Декомпозиция: 1799 строк, 10+ обязанностей → `api/routes/`, `api/services/` | Major | Требует 2–3 недели, breaking changes для mountpoint | Sprint 2 |
| TD-02 | `shared/llm.py` | `probe_local_max_context` синхронный вызов из async-контекста | Minor | Требует async refactor + тесты | Sprint 2 |
| TD-03 | `shared/agent_tooling.py` | `_DECISION_SYNONYMS` дублирует логику `_normalize_decision` | Minor | Требует unit-тестов до изменения | Sprint 2 |
| TD-04 | все `.py` | Смешанные языки в docstrings (рус/англ) | Minor | Постепенная миграция при правках файлов | Ongoing |
| TD-05 | `shared/schemas.py` | `additional: dict[str, Any]` в `LeasingParseResult` и `InsuranceParseResult` — DA API не типизирован | Minor | Ждём стабилизацию DA API контракта | Sprint 3 |
| TD-06 | `tests/` | Покрытие <80% для `api/app.py` (фоновая обработка) | Minor | Требует async test infrastructure | Sprint 2 |
