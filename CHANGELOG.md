# Changelog

Все значимые изменения проекта документируются здесь.
Формат соответствует [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/).
Проект использует [Semantic Versioning](https://semver.org/lang/ru/).

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
