# Changelog

Все значимые изменения проекта документируются здесь.
Формат соответствует [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/).
Проект использует [Semantic Versioning](https://semver.org/lang/ru/).

## [1.4.0] — 2026-03-26

### Added
- `shared/chunked_analysis.py` — поблочный (map-reduce) анализ больших документов:
  - `chunk_document()` — разбивает текст на ≤14 перекрывающихся чанков, разбивая по абзацам
  - `analyze_document_in_chunks()` — Phase 1 (Map): каждый чанк анализируется прямым LLM-вызовом без агента; Phase 2 (Reduce): краткие результаты склеиваются в структурированное резюме; итог ~3900 токенов вместо 36 000+
  - Отдельные системные промпты для агентов `tz` и `dzo`; в конце резюме — явные инструкции для агента
- `shared/llm.py`: функции `probe_max_input_tokens()` и `estimate_tokens()`
  - `probe_max_input_tokens()` — зондирует лимит входных токенов через 413-ответ API (100k символов), кеширует в `_MAX_INPUT_TOKENS_CACHE`
  - `estimate_tokens()` — быстрая оценка объёма: `len(text) // 4`

### Changed
- `shared/llm.py`: `Meta-Llama-3.1-8B-Instruct` перенесён в конец fallback-цепочки (8 000 токенов суммарного контекста — наименьший)
- `api/app.py`: поблочный анализ запускается когда вход > половины доступного контекста лучшей модели (порог динамический)
- `api/app.py`: `TOOLS_OVERHEAD` увеличен до 3 000 токенов; финальная обрезка остаётся как последний fallback
- `api/app.py`: надёжная детекция 413 — строковый матчинг (`tokens_limit_reached`, `too large`) дополняет `isinstance`; для 413 `break` из retry-цикла немедленно

### Fixed
- Ошибка `Error code: 413 — tokens_limit_reached` для `meta-llama-3.1-8b-instruct` и `gpt-4o` на GitHub Models бесплатном тире
- `agent2_tz_inspector/tools.py`: `generate_json_report` падал на JSON с хвостовым мусором (`}}]}]}`); добавлен `JSONDecoder().raw_decode()` как fallback
- `shared/llm.py`: `probe_max_output_tokens()` — `max_tokens` для github_models определяется динамически через API вместо хардкода 4 096 (gpt-4o-mini: 16 384)

## [1.3.0] — 2026-03-13

### Added
- `shared/tracing.py` — новый модуль трейсинга агентов:
  - `get_langfuse_callback()` — кэшированный Langfuse `CallbackHandler` (один экземпляр на процесс); если `LANGFUSE_PUBLIC_KEY` не задан — трейсинг отключён без ошибок
  - `log_agent_steps()` — структурированное логирование каждого шага агента (номер, tool, tool_input, output_keys, decision, latency_ms) в `logs/agent_trace.log`
  - возвращает trace-список для сохранения в БД; безопасная сериализация (MagicMock/non-JSON объекты не приводят к ошибке)
- `shared/database.py`: колонка `trace JSONB` в таблице `jobs`; идемпотентная миграция `ALTER TABLE jobs ADD COLUMN IF NOT EXISTS trace JSONB`
- `agent1_dzo_inspector/runner.py`, `agent2_tz_inspector/runner.py`: интеграция с `shared.tracing`; `session_id` передаётся через `config={"metadata": {"session_id": job_id}}`; trace сохраняется в `db.update_job()`
- `.env.example`: секция `# Langfuse` (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`)
- `tests/test_tracing.py`: 14 unit-тестов для `get_langfuse_callback`, `log_agent_steps`, `_truncate`

### Changed
- `pyproject.toml`: в `per-file-ignores` добавлен `I001` для `shared/*.py` (блок `TYPE_CHECKING` после stdlib-импортов)

## [1.2.0] — 2026-03-13

### Added
- UI (страница «⚙️ Настройки»): полностью переработана
  - selectbox «Бэкенд LLM» (OpenAI / Ollama / DeepSeek / vLLM / LM Studio / Произвольный)
  - автоподстановка `OPENAI_API_BASE` и списка моделей при выборе бэкенда
  - radio `AGENT_TYPE` (`openai_tools` / `react`) с подсказкой о различиях
  - кнопка «Сгенерировать .env сниппет» + скачивание `.env.generated`
  - вкладки справочника моделей: OpenAI / Ollama / DeepSeek / vLLM+LM Studio
  - блок «Тест соединения»: `/health`, `/agents`, `/stats`
- `ui/config.py`: переменные `LLM_BACKEND`, `FORCE_REPROCESS`, `AUTO_REFRESH_SEC`
- `.env.example`: полные секции OpenAI / Ollama / DeepSeek / vLLM / LM Studio / IMAP / SMTP / UI
- `docs/ui-settings.md`: документация страницы «Настройки» (4 блока, таблица переменных)
- `docs/api.md`: синхронизированы все эндпоинты; добавлены `/api/v1/check-duplicate`, `/api/v1/stats`, `DELETE /api/v1/jobs/{id}`, `force` в `ProcessRequest`, пагинация `/api/v1/history`
- `tests/test_ui_config.py`: unit-тесты переменных окружения `ui/config.py`
- UI (дашборд): метрики из `/api/v1/stats` (total / today / approved / rework / errors)
- UI (история): параметр `per_page`/`page` вместо `limit`; прогресс-бар в `_poll_job`
- агент `auto` в UI тестировании (автоопределение типа)

### Fixed
- W605 ruff: невалидная escape-последовательность `\|` в f-строке markdown-таблицы (`ui/app.py` стр. 931–932)

## [1.1.0] — 2026-03-12

### Added
- Дедупликация писем: `GET /api/v1/check-duplicate` проверяет наличие обработанного задания по ключу `(agent, sender, subject)` без запуска агента
- Параметр `force: bool` в теле POST-запросов `/api/v1/process/*` — принудительная повторная обработка даже при наличии дубликата
- `DELETE /api/v1/jobs/{job_id}` — удаление задания из хранилища
- UI (страница «🧪 Тестирование»): перед запуском показывается предупреждение о дубле с кнопками «Использовать старый результат» / «Переобработать»
- UI (страница «📋 История»): чекбоксы выбора строк, пакетная переобработка и удаление с диалогом подтверждения, построчные кнопки в expander
- `FORCE_REPROCESS=true` в окружении — глобальный override дедупликации для IMAP-демонов
- Тесты: покрытие `check-duplicate`, `force`-переобработки, `DELETE /api/v1/jobs/{job_id}`

### Changed
- Ответ эндпоинтов `/api/v1/process/*` изменён: вместо плоского объекта возвращается `{duplicate, existing_job_id, job, message}`
- Страница «📖 Документация» → вкладка «API»: обновлена таблица эндпоинтов, добавлен раздел «Дедупликация»

### Fixed
- `select_all` на странице «История» не сбрасывал выбор при частичном выборе через `data_editor`
- Строчная кнопка «Переобработать» не обновляла таблицу (`st.rerun()` отсутствовал)
- Экспорт CSV включал служебные колонки «Выбор» и `job_id`

## [1.0.0] — 2026-03-11

### Added
- Агент ДЗО: автоматическая проверка заявок от ДзО на полноту и корректность
- Агент ТЗ: автоматическая проверка ТЗ на соответствие стандартам
- REST API на FastAPI с асинхронной очередью заданий
- Web UI на Streamlit
- PostgreSQL хранилище с in-memory фоллбэком
- Nginx reverse proxy с TLS, rate limiting, заголовками безопасности
- Docker Compose с healthchecks, network isolation, resource limits
- CI/CD: GitHub Actions с matrix-тестами, Trivy CVE scan, SBOM, zero-downtime deploy
- Prometheus метрики (8 шт.) + Grafana дашборд + Alertmanager уведомления в Telegram
- Еженедельный security scan (Trivy FS + pip-audit)
