# DZO / TZ Agents

[![CI](https://img.shields.io/github/actions/workflow/status/OlegKarenkikh/dzo-tz-agents/ci.yml?label=CI&logo=github)](https://github.com/OlegKarenkikh/dzo-tz-agents/actions/workflows/ci.yml)
[![Security](https://img.shields.io/github/actions/workflow/status/OlegKarenkikh/dzo-tz-agents/security.yml?label=Security&logo=github)](https://github.com/OlegKarenkikh/dzo-tz-agents/actions/workflows/security.yml)
[![PyPI](https://img.shields.io/pypi/v/dzo-tz-agents?logo=pypi)](https://pypi.org/project/dzo-tz-agents/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-supported-purple)](docs/mcp-a2a.md)
[![A2A](https://img.shields.io/badge/A2A-agent%20card-blueviolet)](docs/mcp-a2a.md)

LLM-агенты на базе **LangGraph + LangChain + GPT-4o** для автоматической проверки заявок ДЗО, технических заданий и тендерной документации по электронной почте.
Портировано из n8n-сценариев (`n8n-application-inspector-dzo-v3.1`, `n8n-tz-inspector-v4.1`).

## Документация

| Руководство | Для кого | Цель |
|---|---|---|
| [📖 Архитектура](docs/architecture.md) | разработчики, DevOps | Компоненты, сети, потоки данных |
| [🔌 API справочник](docs/api.md) | интеграторы, фронтенд | Все эндпоинты, форматы запросов/ответов, коды ошибок |
| [🔗 MCP / A2A](docs/mcp-a2a.md) | интеграторы, AI platform engineers | Подключение через MCP-клиенты и A2A Agent Card |
| [🤖 Агенты](docs/agents.md) | разработчики | Промпты, инструменты, логика агентов ДЗО и ТЗ |
| [🚀 Деплоймент](docs/deployment.md) | DevOps | Docker Compose, TLS, мониторинг, CI/CD |
| [🧪 Локальное тестирование](TESTING.md) | разработчики | Как тестировать агентов локально с полным логированием |
| [➕ Добавление нового агента](docs/adding_new_agent.md) | разработчики | Полный путь портирования n8n → Python |
| [📋 Алгоритм Агента ДЗО](agent1_dzo_inspector/ALGORITHM.md) | все | Бизнес-правила работы Инспектора заявок ДЗО |
| [📋 Алгоритм Агента ТЗ](agent2_tz_inspector/ALGORITHM.md) | все | Бизнес-правила работы Инспектора технических заданий |

> Если вы портируете новый n8n-сценарий — начните с [docs/adding_new_agent.md](docs/adding_new_agent.md).

## Архитектура

```
┌──────────────────────────────────────────────────────────┐
│               Internet / Пользователь / AI Host         │
└───────────────┬───────────────────────┬───────────┬─────┘
                │ :443 (HTTPS)          │ :443      │ MCP/A2A
     ┌──────────┴───────────────────────┴───────────┴─────┐
     │               Nginx (reverse proxy)                 │
     │            TLS • rate limit • sec headers           │
     └──────────┬────────────────┬──────────────────┬─────┘
                │ /api/*         │ /               │ /mcp /.well-known
       ┌────────┴────────┐   ┌───┴──────────┐   ┌──┴────────────────┐
       │  FastAPI :8000  │   │ Streamlit :8501│   │ MCP / A2A Adapters │
       │  /metrics       │   └───────────────┘   └───────────────────┘
       └────────┬────────┘
                │ (backend network, internal)
   ┌────────────┴────────────┬──────────────────┬──────────────┐
   │ Агент ДЗО               │ Агент ТЗ         │ Агент Тендер │
   └─────────────────────────┴──────────────────┴──────────────┘
                           │
                     ┌─────┴─────┐
                     │ PostgreSQL │
                     └────────────┘
```

## Быстрый старт

### Установка через pip

```bash
pip install dzo-tz-agents
pip install "dzo-tz-agents[ui]"
pip install "dzo-tz-agents[ui,dev]"
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
make tender-only              # Только агент Тендер
```

### GitHub Codespaces

На GitHub Codespaces `GITHUB_TOKEN` доступен автоматически. Конфигурация автоматически переключится на `LLM_BACKEND=github_models` без необходимости устанавливать `OPENAI_API_KEY`:

```bash
git clone https://github.com/OlegKarenkikh/dzo-tz-agents.git
cd dzo-tz-agents
cp .env.example .env

pip install -e ".[ui,dev]"

make api
make ui
make dzo-only
```

### MCP / A2A

После запуска API доступны:

- `http://localhost:8000/mcp` — MCP streamable HTTP endpoint
- `http://localhost:8000/.well-known/agent.json` — A2A Agent Card

Запуск stdio MCP-сервера:

```bash
python -m shared.mcp_server
```

Подробная настройка — в [docs/mcp-a2a.md](docs/mcp-a2a.md).

### Docker (рекомендуется)

```bash
cp .env.example .env
make build && make up
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
| `MCP_LOG_LEVEL` | ➞ | Уровень логирования stdio MCP-сервера |
| `TELEGRAM_BOT_TOKEN` | ➞ | Уведомления + алерты |
| `TELEGRAM_CHAT_ID` | ➞ | Chat ID Telegram |
| `CORS_ORIGINS` | ➞ | Допустимые origins |
| `PUBLIC_BASE_URL` | ➞ | Публичный базовый URL сервиса (A2A Agent Card, внешние ссылки) |
| `AGENT_CARD_ALLOWED_HOSTS` | ➞ | Допустимые hostname для A2A Agent Card (обязателен если `PUBLIC_BASE_URL` не задан) |
| `ENABLE_DOCS` | ➞ | `false` — скрыть Swagger в продакшене |
| `AGENT_MODE` | ➞ | `dzo` \| `tz` \| `tender` \| `both` (default) |
| `POLL_INTERVAL_SEC` | ➞ | Интервал IMAP-опроса (default: 300) |
| `FORCE_REPROCESS` | ➞ | `true` — глобальный обход дедупликации для IMAP-демонов |
| `AGENT_TOOL_ENABLED` | ➞ | `true/false` — разрешить межагентные tool-вызовы |
| `AGENT_TOOL_REGISTRY` | ➞ | JSON-реестр фабрик агентов: `{"dzo":"...:create_dzo_agent"}` |
| `AGENT_TOOL_PERMISSIONS` | ➞ | JSON-matrix маршрутов: `{"dzo":["tz"],"tz":["dzo"]}` |

По умолчанию межагентные вызовы работают по политике `all_except_self`: каждый агент может
вызвать любой другой агент из реестра. `AGENT_TOOL_PERMISSIONS` используйте только если нужно
ограничить маршруты.

## API и открытые протоколы

| Метод | Путь | Аутентификация | Описание |
|---|---|:---:|---|
| GET | `/health` | — | Статус сервиса |
| GET | `/agents` | — | Список агентов |
| GET | `/.well-known/agent.json` | — | A2A Agent Card |
| GET/POST | `/mcp` | ✅¹ | MCP streamable HTTP endpoint |
| POST | `/api/v1/process/dzo` | ✅ | Обработать заявку ДЗО |
| POST | `/api/v1/process/tz` | ✅ | Обработать ТЗ |
| POST | `/api/v1/process/tender` | ✅ | Парсинг тендерной документации |
| POST | `/api/v1/process/{agent}` | ✅ | Универсальный запуск агента |
| POST | `/api/v1/resolve-agent` | ✅ | Определить агента по содержимому |
| POST | `/api/v1/process/auto` | ✅ | Автоопределение типа |
| GET | `/api/v1/check-duplicate` | ✅ | Проверить дубликат |
| GET | `/api/v1/jobs` | ✅ | Список заданий |
| GET | `/api/v1/jobs/{job_id}` | ✅ | Статус задания |
| DELETE | `/api/v1/jobs/{job_id}` | ✅ | Удалить задание |
| GET | `/api/v1/history` | ✅ | История с фильтрами |
| GET | `/api/v1/stats` | ✅ | Аггрегированная статистика |
| GET | `/metrics` | — | Prometheus scrape |

> ¹ Если `API_KEY` задан — требуется `X-API-Key: <key>` или `Authorization: Bearer <key>`. Если `API_KEY` не задан или MCP не установлен — эндпоинт открыт / недоступен.

## Разработка

```bash
make test
make lint
make fmt
make clean
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
| `@n8n/langchain.agent` | `langgraph.prebuilt.create_react_agent` |
| `memoryBufferWindow` | Управление контекстом через лимиты токенов/поблочный анализ в `api/app.py` |
| `toolCode` | `@tool`-декоратор LangChain |
| `emailSend` | `smtplib.SMTP` |
| `switch` / `if` | Python `if/elif` |

## Безопасность

- Непривилегированный `appuser` во всех контейнерах
- `cap_drop: ALL` + минимальные capabilities
- `read_only: true` FS + tmpfs `/tmp`
- `no-new-privileges:true` на всех сервисах
- `backend` сеть `internal: true`
- CORS ограничен через `CORS_ORIGINS`
- Trivy CVE-скан блокирует merge при CRITICAL/HIGH
- Еженедельный `pip-audit` + Trivy FS scan
