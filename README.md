# ИИ-Агенты: Инспектор Заявок ДЗО + Инспектор ТЗ

Полноценные Python-агенты на базе LangChain + GPT-4o, конвертированные из n8n-сценариев:
- `n8n-application-inspector-dzo-v3.1-cloud.json`
- `n8n-tz-inspector-v4.1-cloud.json`

## Архитектура

```
agents/
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
└── agent2_tz_inspector/
    ├── agent.py                    # LangChain AgentExecutor (GPT-4o)
    ├── tools.py                    # generate_json_report, corrected_tz и др.
    └── runner.py                   # Логика обработки писем
```

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

## Быстрый старт

### Локально

```bash
cp .env.example .env
# Заполнить .env своими данными
pip install -r requirements.txt
python main.py
```

### Docker

```bash
cp .env.example .env
# Заполнить .env своими данными
docker-compose up -d --build

# Логи
docker-compose logs -f agent-dzo
docker-compose logs -f agent-tz
```

## Переменные окружения

| Переменная | Описание |
|---|---|
| `OPENAI_API_KEY` | Ключ OpenAI API |
| `AGENT_MODE` | `dzo` \| `tz` \| `both` |
| `POLL_INTERVAL_SEC` | Интервал опроса IMAP (сек, по умолчанию 300) |
| `DZO_IMAP_HOST/USER/PASSWORD` | IMAP для агента ДЗО |
| `TZ_IMAP_HOST/USER/PASSWORD` | IMAP для агента ТЗ |
| `SMTP_HOST/PORT/USER/PASSWORD` | Настройки SMTP |
| `MANAGER_EMAIL` | Email для эскалаций |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram-бота (опционально) |
| `TELEGRAM_CHAT_ID` | Chat ID для уведомлений (опционально) |

## Агент 1 — Инспектор Заявок ДЗО

Проверяет входящие заявки от дочерних обществ на полноту перед регистрацией в ЭДО «Тезис».

**Чек-листы:**
- №1: Комплектность вложений (ТЗ, спецификация)
- №2: Обязательные реквизиты (наименование, количество, срок, инициатор, адрес)
- №3: Дополнительные поля (бюджет, обоснование, поставщики)

**Решения:** `Заявка полная` → форма Тезис | `Требуется доработка` → запрос данных | `Требуется эскалация` → письмо руководителю

## Агент 2 — Инспектор ТЗ

Проверяет технические задания на соответствие корпоративному шаблону (8 разделов).

**Решения:** `Соответствует` | `Требует доработки` → исправленное ТЗ с цветовой разметкой | `Не пригодно`

## Требования

- Python 3.11+
- Docker + Docker Compose (для контейнерного запуска)
- OpenAI API key с доступом к GPT-4o
- IMAP/SMTP-доступ к почтовому серверу
