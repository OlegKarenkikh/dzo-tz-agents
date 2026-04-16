# Changelog

Все значимые изменения проекта документируются здесь.
Формат соответствует [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/).
Проект использует [Semantic Versioning](https://semver.org/lang/ru/).

## [2.0.0] — 2026-04-16

### Added
- Multi-key authentication: `API_KEYS` env var accepts comma-separated list of valid API keys
- JWT Bearer Token authentication: `JWT_SECRET` + `JWT_ALGORITHM` for signed token auth
- `monitoring/rules/slo.yml`: SLO/SLA alert rules — decision error rate, p99 latency < 30s,
  uptime > 99.5%, job duration p95, all-models-unavailable
- `docker-compose.langfuse.yml`: self-hosted Langfuse stack with auto DB initialization
- Tests: JWT auth (4 tests), multi-key auth (2 tests)

### Changed
- `_require_api_key()` now supports: legacy single key, multiple keys, JWT bearer tokens
- Startup validation improved: warns if no auth configured, checks for default keys
- `.env.example`: JWT and multi-key auth sections, updated Langfuse self-hosted docs

### Breaking Changes
- `API_KEY` env var still works but `API_KEYS` (comma-separated) is now preferred
- Auth behavior when no keys configured: still allows anonymous access (backward compatible)

## [1.9.0] — 2026-04-16

### Added
- `POST /api/v1/upload` — multipart/form-data file upload endpoint (PDF, DOCX, XLSX, TXT, etc.)
  with automatic text extraction and agent auto-detection
- `prompts/` directory — versioned prompt files: `dzo_v1.md`, `tz_v1.md`, `tender_v1.md`, `collector_v1.md`
- `shared/prompt_loader.py` — cached prompt loading with `load_prompt()` and `list_prompts()`
- `shared/date_normalizer.py` — Russian date normalization: "1 мая 2026", "01.05.2026",
  "II квартал 2026", "45 рабочих дней" → ISO format
- Tests: upload endpoint (5), date normalizer (15+), prompt loader (7)

### Changed
- Agent prompts moved from inline strings to external files in `prompts/` directory
- All 4 agents now use `shared.prompt_loader.load_prompt()` for prompt loading

## [1.8.0] — 2026-04-16

### Added
- `GET /api/v1/jobs/{job_id}/stream` — SSE (Server-Sent Events) endpoint for real-time
  job progress streaming. Events: `status`, `log`, `result`, `error`, `done`
- `shared/llm.py`: `_CircuitBreaker` class — per-model circuit breaker that skips
  models with 3+ consecutive failures within 2-minute window
- Tests for SSE endpoint (3 tests) and circuit breaker (5 tests)

### Changed
- Job processing pipeline now integrates circuit breaker: failing models are automatically
  skipped in the fallback chain, successful calls reset the failure counter
- Clients can now use SSE instead of polling for job status updates

## [1.7.1] — 2026-04-16

### Added
- API tests: collector endpoint, stats endpoint, validation errors (422), health agents/version checks
- `TESTING.md`: Docker testing section with compose commands and monitoring
- `README.md`: coverage badge (68%)
- `docker-compose.override.yml`: dev profile with debug logging and volume mounts
- `docker-compose.yml`: `ENABLE_DOCS` environment variable for production security

### Changed
- Test count increased from ~641 to ~650+ with new API coverage

## [1.7.0] — 2026-04-16

### Added
- Enhanced SYSTEM_PROMPT for all 4 agents: mandatory JSON output format, weighted checklists,
  stricter decision thresholds, anti-hallucination rules
- `config.py`: `LLM_TEMPERATURE`, `LLM_SEED`, `LLM_TOP_P` configurable environment variables
- `shared/runner_base.py`: `_validate_output()` method for decision keyword checking
- `tests/test_accuracy_report.py`: E2E accuracy report generator (generates accuracy_report.json)
- `api/healthcheck.py`: enhanced /health with per-agent status and version
- `.env.example`: E2E testing section, determinism settings
- 10 real/synthetic procurement documents in test registry across all 4 agents (tz, dzo, tender, collector)

### Changed
- `shared/llm.py`: `build_llm()` uses config variables for seed/top_p instead of raw os.environ
- All agents: `temperature=0.0` for reproducibility (was 0.1–0.2)
- DZO agent: score threshold raised from 85% to 95% for "Заявка полная"
- TZ agent: weighted section checklist replacing simple count-based scoring
- Tender agent: added mandatory sections list (44-ФЗ/223-ФЗ) and critical violation rules
- Collector agent: INN/name discrepancy handling rules, 90% completeness threshold

## [1.6.0] — 2026-04-10

### Added
- `agent3_collector_inspector/` — новый агент сбора документов тендерного отбора (collector):
  - `agent.py` — `create_collector_agent()` на базе LangGraph `create_react_agent`
  - `tools.py` — инструменты: `collect_tender_documents`, `invoke_peer_agent`
  - Глубокие знания домена: структура анкеты УЦЗ (15 полей), формат email-переписки, правила валидации ИНН/наименований
  - Классификация вложений: анкета / NDA / прочее
  - Нечёткое сопоставление наименований организаций (разные орг. формы, кавычки)
  - Генерация структуры папок и отчёта о сборе
- `api/app.py`:
  - Агент `collector` в `AGENT_REGISTRY` (приоритет 90, ключевые слова: тендерный отбор, анкета участника, NDA и др.)
  - `POST /api/v1/process/collector` — dedicated endpoint
  - A2A Agent Card: skill `collect_documents`
- `shared/mcp_server.py`:
  - MCP tool `collect_documents` для сбора документов через MCP-клиенты
  - Маппинг `collector` → `collect_documents` в `_AGENT_TOOL_MAP`
- `shared/agent_tooling.py`: `collector` в `_DEFAULT_AGENT_FACTORY_REGISTRY`
- `tests/test_collector.py` — 82 unit-теста:
  - Классификация документов (анкета/NDA/прочее)
  - Сопоставление участников (по email, ИНН, наименованию)
  - Извлечение номера ТО из темы письма
  - Валидация ИНН и наименований (расхождения)
  - Генерация отчёта и структуры папок
  - Edge cases (пустые данные, неизвестные отправители, несколько писем от одного участника)
  - Интеграция с AGENT_REGISTRY, MCP, A2A, API endpoints
- `tests/fixtures/collector/` — тестовые анкеты и сводная таблица из Khakaton.7z

### Changed
- `pyproject.toml`: добавлен `agent3_collector_inspector` в packages, isort, coverage
- `tests/conftest.py`: мокинг `agent3_collector_inspector.agent` в тестах

## [1.5.0] — 2026-04-09

### Added
- `shared/mcp_server.py` — MCP (Model Context Protocol) server на базе `FastMCP`:
  - `inspect_dzo(text, sender_email, subject, model_name)` — проверка заявки ДЗО как MCP tool
  - `inspect_tz(text, model_name)` — анализ ТЗ как MCP tool
  - `inspect_tender(text, model_name)` — парсинг тендерной документации как MCP tool
  - `list_agents()` — список доступных агентов
  - поддержка двух транспортов: `stdio` (Claude Desktop / Cursor) и `streamable-http`
- `api/app.py`:
  - MCP endpoint `GET/POST /mcp` через `app.mount("/mcp", mcp.streamable_http_app())`
  - A2A Agent Card `GET /.well-known/agent.json` с описанием capabilities и skills
- `tests/test_mcp_server.py` — unit-тесты MCP tools, A2A Agent Card и MCP mount
- `docs/mcp-a2a.md` — документация по интеграции с MCP-клиентами и A2A consumers
- `requirements.txt`, `pyproject.toml`: зависимость `mcp[cli]>=1.3.0`

### Changed
- `pyproject.toml`: версия пакета повышена до `1.5.0`
- `pyproject.toml`: keywords дополнены `mcp`, `a2a`
- `api/app.py`: заголовок модуля синхронизирован с новыми endpoint'ами

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
