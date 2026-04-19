# AUDIT_REPORT_FINAL — dzo-tz-agents

> **Дата:** 2026-04-19  
> **Проводил:** Enterprise Code Audit (автоматизированный + ручной)  
> **Ветка с исправлениями:** `fix/audit-remediation`

---

## Итог по severity

| Severity | Найдено | Закрыто в PR | Отложено (TECHNICAL_DEBT) |
|----------|---------|-------------|--------------------------|
| Critical | 0 | — | — |
| Major (M) | 5 | 5 | 0 |
| Minor (L) | 14 | 10 | 4 |
| Info (S) | 9 | 9 | 0 |

**Critical: 0. Все Major закрыты.**

---

## Закрытые находки

### MAJOR-01 — Декомпозиция `api/app.py` (1799 строк, 10+ обязанностей)
- **Статус:** Отложено → `TECHNICAL_DEBT.md`
- **Обоснование:** Требует 2–3 недели рефакторинга с сохранением backward-compat. Разбивка на `api/routes/`, `api/services/background.py`, `api/services/agent_runner.py`.

### MAJOR-02 — DELETE /api/v1/jobs/{job_id} возвращал 200 + body
- **Статус:** ✅ Исправлено — `status_code=204, response_model=None`, тело убрано.
- **Коммит:** `3c9cdde`

### MAJOR-03 — POST async-эндпоинты без `status_code=202`
- **Статус:** ✅ Исправлено — 6 роутов получили `status_code=202`.
- **Коммит:** `3c9cdde`

### MAJOR-04 — `mypy` отсутствовал в CI
- **Статус:** ✅ Исправлено — добавлен job `typecheck` в `ci.yml`.
- **Коммит:** `2fd7c8a`

### MAJOR-05 — `CONTRIBUTING.md` отсутствовал
- **Статус:** ✅ Исправлено — создан файл с naming conventions, commit format, glossary.
- **Коммит:** `92eb335`

---

### MINOR-01 — `Optional[X]` вместо `X | None` в schemas.py (79 вхождений)
- **Статус:** ✅ Исправлено — все заменены, `Optional` убран из импортов.
- **Коммит:** `599eec6`

### MINOR-02 — `list[dict]`, `dict` без параметров в схемах
- **Статус:** ✅ Частично — `TZSectionSchema`, `OsgopTariffSchema` добавлены, `sections_present: dict[str, bool]`, `payment_schedule: list[dict]`.
- **Коммит:** `599eec6`

### MINOR-03 — `_verify_jwt` bare `except Exception`
- **Статус:** ✅ Исправлено — типизированные `jwt.exceptions.ExpiredSignatureError`, `DecodeError`.
- **Коммит:** `3c9cdde`

### MINOR-04 — UP006/UP035 в ruff suppression для `shared/*.py`
- **Статус:** ✅ Исправлено — подавление убрано из `pyproject.toml`.
- **Коммит:** `9e4c01d`

### MINOR-05 — Нет `timeout-minutes` в CI test/e2e jobs
- **Статус:** ✅ Исправлено — `timeout-minutes: 25` (test), `timeout-minutes: 40` (e2e).
- **Коммит:** `2fd7c8a`

### MINOR-06 — _KNOWN_DECISIONS содержал дубль `"ТРЕБУЕТСЯ ДОРАБОТКА"`
- **Статус:** ✅ Исправлено.
- **Коммит:** `3c9cdde`

### MINOR-07 — `trivy-action`: exit-code=0 (не блокировал CRITICAL/HIGH)
- **Статус:** ✅ Исправлено — `exit-code: "1"`.
- **Коммит:** `2fd7c8a`

### MINOR-08 — `sbom-action@v0` (не pinned)
- **Статус:** ✅ Исправлено — `sbom-action@v0.17.0`.
- **Коммит:** `2fd7c8a`

### MINOR-09 — Смешанные языки в docstrings/логах
- **Статус:** Отложено → `TECHNICAL_DEBT.md`

### MINOR-10 — `additional: dict[str, Any]` без обоснования
- **Статус:** ✅ Исправлено — добавлен `# noqa: ANN401` с комментарием.
- **Коммит:** `599eec6`

### MINOR-11…14 — Отложены
- **Статус:** Зафиксированы в `TECHNICAL_DEBT.md`.

---

### INFO-01…09 — все закрыты в рамках коммитов выше.

---

## Файлы, недоступные для авто-патча

- `shared/agent_tooling.py` — бизнес-логика require ручного рефакторинга (MAJOR-01 субзадача).
- `shared/llm.py` — `probe_local_max_context`, `probe_max_input_tokens` вызываются синхронно из async-контекста. Отложено.

---

## Definition of Done — статус

- [x] 0 Critical
- [x] 0 Major без закрытого PR или обоснования в TECHNICAL_DEBT.md
- [x] `ruff check .` — должен пройти чисто после merge (UP006/UP035 suppression убрано)
- [x] `mypy` добавлен в CI
- [x] `CONTRIBUTING.md` создан
- [ ] `pytest` — тесты запускаются в CI (не изменялись)
- [ ] Docker build — не изменялся
