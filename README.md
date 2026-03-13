# DZO / TZ Agents

[![CI](https://img.shields.io/github/actions/workflow/status/OlegKarenkikh/dzo-tz-agents/ci.yml?label=CI&logo=github)](https://github.com/OlegKarenkikh/dzo-tz-agents/actions/workflows/ci.yml)
[![Security](https://img.shields.io/github/actions/workflow/status/OlegKarenkikh/dzo-tz-agents/security.yml?label=Security&logo=github)](https://github.com/OlegKarenkikh/dzo-tz-agents/actions/workflows/security.yml)
[![PyPI](https://img.shields.io/pypi/v/dzo-tz-agents?logo=pypi)](https://pypi.org/project/dzo-tz-agents/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

LLM-агенты на базе **LangChain + GPT-4o** для автоматической проверки заявок ДЗО и ТЗ по электронной почте.
Портировано из n8n-сценариев (`n8n-application-inspector-dzo-v3.1`, `n8n-tz-inspector-v4.1`).

## Документация

| Руководство | Для кого | Цель |
|---|---|---|
| [📖 Архитектура](docs/architecture.md) | разработчики, DevOps | Компоненты, сети, потоки данных |
| [🔌 API справочник](docs/api.md) | интеграторы, фронтенд | Все эндпоинты, форматы запросов/ответов, коды ошибок |
| [🤖 Агенты](docs/agents.md) | разработчики | Промпты, инструменты, логика агентов ДЗО и ТЗ |
| [🚀 Деплоймент](docs/deployment.md) | DevOps | Docker Compose, TLS, мониторинг, CI/CD |
| [➕ Добавление нового агента](docs/adding_new_agent.md) | **разработчики** | Полный путь портирования n8n → Python: маппинг, шаблоны agent/tools/runner, регистрация в API, Docker, тесты, чек-лист PR |

> Если вы портируете новый n8n-сценарий — начните с [docs/adding\_new\_agent.md](docs/adding_new_agent.md).

## Архитектура

```
┌──────────────────────────────────────────────────┐
│              Internet / Пользователь               │
└───────────────┬───────────────────────┬───────┘
               │ :443 (HTTPS)          │ :443
     ┌────────┴──────────────────┴─────┐
     │       Nginx (reverse proxy)        │
     │  TLS • rate limit • sec headers   │
     └─────┬───────────────────┬─────┘
           │ /api/*                │ /
  ┌───────┴───────┐       ┌─────┴───────┐
  │  FastAPI :8000  │       │ Streamlit :8501│
  │  /metrics       │       └───────────────┘
  └─────┬─────────┘
           │ (backend network, internal)
  ┌──────┴──────┐  ┌─────────────────┐  ┌───────────┐
  │ Агент ДЗО  │  │   Агент ТЗ    │  │ PostgreSQL │
  └─────────────┘  └─────────────────┘  └───────────┘

  ┌─────────────────────────────────────────────┐
  │  Monitoring (docker-compose.monitoring.yml)  │
  │  Prometheus • Alertmanager • Grafana        │
  │  postgres-exporter • node-exporter • nginx  │
  └─────────────────────────────────────────────┘
```

## Быстрый старт

### Установка через pip

```bash
pip install dzo-tz-agents              # базовый пакет
pip install "dzo-tz-agents[ui]"        # + Streamlit UI
pip install "dzo-tz-agents[ui,dev]"    # + UI + инструменты разработки
```

### Локальная разработка

```bash
git clone https://github.com/OlegKarenkikh/dzo-tz-agents.git
cd dzo-tz-agents
cp .env.example .env          # заполнить: OPENAI_API_KEY, API_KEY, IMAP/SMTP

pip install -e ".[ui,dev]"    # редактируемый режим

make api                      # FastAPI  → http://localhost:8000/docs
make ui                       # Streamlit → http://localhost:8501
make dzo-only                 # Только агент ДЗО
```

### Docker (рекомендуется)

```bash
cp .env.example .env
# Обязательно: OPENAI_API_KEY, API_KEY, POSTGRES_PASSWORD

make build && make up

# https://your-domain/         — Web UI
# https://your-domain/docs     — Swagger API
# https://your-domain/health   — healthcheck
```

### Мониторинг

```bash
make monitoring    # Prometheus + Grafana + Alertmanager

# http://localhost:3000   — Grafana (GRAFANA_PASSWORD из .env)
# http://localhost:9090   — Prometheus
```

## Переменные окружения

| Переменная | Обязательная | Описание |
|---|:---:|---|
| `OPENAI_API_KEY` | ✅ | Ключ OpenAI |
| `API_KEY` | ✅ | Секретный ключ REST API (`X-API-Key`) |
| `POSTGRES_PASSWORD` | ✅ | Пароль PostgreSQL |
| `DZO_IMAP_HOST/USER/PASSWORD` | ✅ | IMAP для агента ДЗО |
| `TZ_IMAP_HOST/USER/PASSWORD` | ✅ | IMAP для агента ТЗ |
| `SMTP_HOST/PORT/USER/PASSWORD` | ✅ | Отправка ответов |
| `MANAGER_EMAIL` | ✅ | Email для эскалаций |
| `GRAFANA_PASSWORD` | ✅ | Пароль Grafana |
| `TELEGRAM_BOT_TOKEN` | ➞ | Уведомления + алерты |
| `TELEGRAM_CHAT_ID` | ➞ | Chat ID Telegram |
| `CORS_ORIGINS` | ➞ | Допустимые origins (default: `localhost:8501`) |
| `ENABLE_DOCS` | ➞ | `false` — скрыть Swagger в продакшене |
| `AGENT_MODE` | ➞ | `dzo` \| `tz` \| `both` (default) |
| `POLL_INTERVAL_SEC` | ➞ | Интервал IMAP-опроса (default: 300) |
| `FORCE_REPROCESS` | ➞ | `true` — глобальный обход дедупликации для IMAP-демонов |

## API эндпоинты

| Метод | Путь | Аутентификация | Описание |
|---|---|:---:|---|
| GET | `/health` | — | Статус сервиса |
| GET | `/agents` | — | Список агентов |
| POST | `/api/v1/process/dzo` | ✅ | Обработать заявку ДЗО |
| POST | `/api/v1/process/tz` | ✅ | Обработать ТЗ |
| POST | `/api/v1/process/auto` | ✅ | Автоопределение типа |
| GET | `/api/v1/check-duplicate` | ✅ | Проверить дубликат без запуска агента |
| GET | `/api/v1/jobs` | ✅ | Список заданий |
| GET | `/api/v1/jobs/{job_id}` | ✅ | Статус задания |
| DELETE | `/api/v1/jobs/{job_id}` | ✅ | Удалить задание |
| GET | `/api/v1/history` | ✅ | История с фильтрами |
| GET | `/api/v1/stats` | ✅ | Аггрегированная статистика |
| GET | `/metrics` | — | Prometheus scrape |

## API примеры

```bash
# Статус (без ключа)
curl https://your-domain/health

# Обработать заявку ДЗО
curl -X POST https://your-domain/api/v1/process/dzo \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "Заявка на закупку серверов", "subject": "Закупка"}'

# Проверить дубликат перед отправкой
curl -H "X-API-Key: $API_KEY" \
  "https://your-domain/api/v1/check-duplicate?agent=dzo&sender=dzo@company.ru&subject=Закупка"

# Переобработать принудительно (если дубликат есть)
curl -X POST https://your-domain/api/v1/process/dzo \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "Заявка", "subject": "Закупка", "force": true}'

# Получить результат
curl -H "X-API-Key: $API_KEY" \
  https://your-domain/api/v1/jobs/<job_id>

# Удалить задание
curl -X DELETE -H "X-API-Key: $API_KEY" \
  https://your-domain/api/v1/jobs/<job_id>
```

## Разработка

```bash
make test          # тесты + coverage
make lint          # ruff check
make fmt           # ruff format
make clean         # очистка
```

## Релиз PyPI

```bash
# 1. Обновить version в pyproject.toml и CHANGELOG.md
# 2. Создать тэг:
git tag v1.1.0
git push origin v1.1.0
# → GitHub Actions автоматически опубликует на PyPI
```

## Маппинг n8n → Python

Подробный маппинг и шаблоны для портирования — в [руководстве по добавлению агента](docs/adding_new_agent.md).

| n8n-нода | Python |
|---|---|
| `emailReadImap` | `imaplib.IMAP4_SSL` |
| `extractFromFile (pdf)` | `pdfplumber` |
| HTTP OCR → GPT-4o Vision | `openai.chat.completions.create` |
| `@n8n/langchain.agent` | `create_openai_tools_agent` + `AgentExecutor` |
| `memoryBufferWindow` | `ConversationBufferWindowMemory(k=20)` |
| `toolCode` | `@tool`-декоратор LangChain |
| `emailSend` | `smtplib.SMTP` |
| `switch` / `if` | Python `if/elif` |

## Безопасность

- Непривилегированный `appuser` (UID 1001) во всех контейнерах
- `cap_drop: ALL` + явные `cap_add` только нужных капабилитес
- `read_only: true` FS + tmpfs `/tmp`
- `no-new-privileges:true` на всех сервисах
- `backend` сеть `internal: true` — PostgreSQL недоступен снаружи
- CORS ограничен через `CORS_ORIGINS`
- Trivy CVE-скан блокирует merge при CRITICAL/HIGH
- Еженедельный `pip-audit` + Trivy FS скан репозитория
- Docker-образ запинен по SHA256 digest
