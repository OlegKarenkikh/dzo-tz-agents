# ИИ-Агенты: Инспектор Заявок ДЗО + Инспектор ТЗ

![CI](https://img.shields.io/github/actions/workflow/status/OlegKarenkikh/dzo-tz-agents/ci.yml?label=CI)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Docker](https://img.shields.io/badge/docker-supported-blue)

Полноценные Python-агенты на базе LangChain + GPT-4o, конвертированные из n8n-сценариев:
- `n8n-application-inspector-dzo-v3.1-cloud.json`
- `n8n-tz-inspector-v4.1-cloud.json`

> 📸 UI Screenshot (Web UI доступен после запуска на http://localhost:8501)

## Компоненты

| Компонент | Путь | Порт | Описание |
|-----------|------|------|----------|
| 🤖 Агент ДЗО | `agent1_dzo_inspector/` | — | Проверка заявок ДЗО через IMAP |
| 🤖 Агент ТЗ | `agent2_tz_inspector/` | — | Проверка техзаданий через IMAP |
| ⚡ REST API | `api/app.py` | 8000 | FastAPI — обработка документов через HTTP |
| 🖥️ Web UI | `ui/app.py` | 8501 | Streamlit — управление и тестирование |

## Быстрый старт

### Локально

```bash
git clone https://github.com/OlegKarenkikh/dzo-tz-agents.git
cd dzo-tz-agents

# Настройка окружения
cp .env.example .env
# Отредактируйте .env: OPENAI_API_KEY, API_KEY, IMAP/SMTP-параметры

# Установка зависимостей
pip install -r requirements.txt

# Запуск REST API
make api        # http://localhost:8000/docs

# Запуск Web UI (в отдельном терминале)
make ui         # http://localhost:8501

# Запуск агентов-поллеров
python main.py
```

### Docker

```bash
cp .env.example .env
# Заполните .env

docker-compose up -d --build
# API:    http://localhost:8000
# UI:     http://localhost:8501
# Docs:   http://localhost:8000/docs

docker-compose logs -f api
docker-compose logs -f ui
```

## Примеры API

```bash
# Статус сервиса
curl http://localhost:8000/health

# Обработать заявку ДЗО
curl -X POST http://localhost:8000/api/v1/process/dzo \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"text": "Заявка на закупку серверов", "subject": "Закупка"}'

# Получить результат
curl -H "X-API-Key: your-secret-key" \
  http://localhost:8000/api/v1/jobs/<job_id>
```

## Архитектура

```
agents/
├── api/
│   └── app.py                      # FastAPI REST API
├── ui/
│   ├── app.py                      # Streamlit Web UI
│   └── config.py                   # Конфигурация UI
├── config.py                       # Настройки, env-переменные
├── main.py                         # Точка входа, scheduler
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
├── shared/
│   ├── email_client.py             # IMAP: получение писем с вложениями
│   ├── file_extractor.py           # PDF/DOCX/XLSX/Image → текст + OCR Vision
│   ├── email_sender.py             # SMTP: отправка ответов
│   ├── telegram_notify.py          # Уведомления в Telegram
│   └── logger.py                   # Ротируемые логи
├── agent1_dzo_inspector/
│   ├── agent.py                    # LangChain AgentExecutor (GPT-4o)
│   ├── tools.py                    # generate_validation_report, tezis_form и др.
│   └── runner.py                   # Логика обработки писем
├── agent2_tz_inspector/
│   ├── agent.py                    # LangChain AgentExecutor (GPT-4o)
│   ├── tools.py                    # generate_json_report, corrected_tz и др.
│   └── runner.py                   # Логика обработки писем
├── tests/
│   ├── test_api.py                 # Тесты FastAPI
│   ├── test_email_client.py        # Тесты email клиента
│   ├── test_integration.py         # Интеграционные тесты
│   ├── test_tools_dzo.py           # Тесты инструментов ДЗО
│   └── test_tools_tz.py            # Тесты инструментов ТЗ
└── docs/
    ├── architecture.md             # Схема компонентов
    ├── api.md                      # Документация API
    ├── deployment.md               # Инструкция деплоя
    └── agents.md                   # Описание агентов
```

## Документация

- 📐 [Архитектура](docs/architecture.md)
- 🔌 [REST API](docs/api.md)
- 🚀 [Деплой](docs/deployment.md)
- 🤖 [Агенты](docs/agents.md)

## Маппинг n8n → Python

| n8n-нода | Python |
|---|---|
| `emailReadImap` | `imaplib.IMAP4_SSL` |
| `extractFromFile (pdf)` | `pdfplumber` |
| HTTP OCR → GPT-4o Vision | `openai.chat.completions.create` |
| `spreadsheetFile` | `openpyxl` / `xlrd` |
| `@n8n/langchain.agent` | `create_openai_tools_agent` + `AgentExecutor` |
| `memoryBufferWindow` | `ConversationBufferWindowMemory(k=20)` |
| `toolCode` | `@tool`-декоратор LangChain |
| `emailSend` | `smtplib.SMTP` |
| `switch` / `if` | Python `if/elif` |

## Переменные окружения

| Переменная | Описание |
|---|---|
| `OPENAI_API_KEY` | Ключ OpenAI API |
| `API_KEY` | Секретный ключ для REST API |
| `AGENT_MODE` | `dzo` \| `tz` \| `both` |
| `POLL_INTERVAL_SEC` | Интервал опроса IMAP (сек, по умолчанию 300) |
| `DZO_IMAP_HOST/USER/PASSWORD` | IMAP для агента ДЗО |
| `TZ_IMAP_HOST/USER/PASSWORD` | IMAP для агента ТЗ |
| `SMTP_HOST/PORT/USER/PASSWORD` | Настройки SMTP |
| `MANAGER_EMAIL` | Email для эскалаций |
| `UI_API_URL` | URL REST API для Web UI |
| `UI_API_KEY` | API-ключ для Web UI |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram-бота (опционально) |
| `TELEGRAM_CHAT_ID` | Chat ID для уведомлений (опционально) |

## Требования

- Python 3.11+
- Docker + Docker Compose (для контейнерного запуска)
- OpenAI API key с доступом к GPT-4o
- IMAP/SMTP-доступ к почтовому серверу

