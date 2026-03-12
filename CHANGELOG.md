# Changelog

Все значимые изменения проекта документируются здесь.
Формат соответствует [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/).
Проект использует [Semantic Versioning](https://semver.org/lang/ru/).

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
