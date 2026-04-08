# Архитектура системы DZO/TZ Agents

## Обзор

Система состоит из нескольких независимых компонентов, взаимодействующих через REST API и почтовые протоколы (IMAP/SMTP).

## Схема компонентов

```mermaid
graph TD
    subgraph "Внешние источники"
        EMAIL[📧 Почтовый сервер<br/>IMAP/SMTP]
        CLIENT[👤 Пользователь / Внешняя система]
    end

    subgraph "Агенты-поллеры (main.py)"
        DZO_RUNNER[🏢 Runner ДЗО<br/>agent1_dzo_inspector/runner.py]
        TZ_RUNNER[📋 Runner ТЗ<br/>agent2_tz_inspector/runner.py]
        TENDER_RUNNER[📑 Runner Тендер<br/>agent21_tender_inspector/runner.py]
    end

    subgraph "LLM-агенты"
        DZO_AGENT[🤖 Agent ДЗО<br/>agent1_dzo_inspector/agent.py]
        TZ_AGENT[🤖 Agent ТЗ<br/>agent2_tz_inspector/agent.py]
        TENDER_AGENT[🤖 Agent Тендер<br/>agent21_tender_inspector/agent.py]
        OPENAI[☁️ OpenAI API<br/>gpt-4o]
    end

    subgraph "Межагентная оркестрация"
        AGENT_TOOLING[🧩 shared/agent_tooling.py]
    end

    subgraph "REST API (api/app.py)"
        FASTAPI[⚡ FastAPI Server<br/>:8000]
        JOBS[💾 Jobs Store<br/>PostgreSQL / in-memory fallback]
    end

    subgraph "Web UI (ui/app.py)"
        STREAMLIT[🖥️ Streamlit<br/>:8501]
    end

    subgraph "Общие модули (shared/)"
        EMAIL_CLIENT[📥 email_client.py]
        EMAIL_SENDER[📤 email_sender.py]
        FILE_EXTRACTOR[📄 file_extractor.py]
        LOGGER[📝 logger.py]
        TELEGRAM[📱 telegram_notify.py]
    end

    CLIENT --> FASTAPI
    FASTAPI --> JOBS
    FASTAPI --> DZO_AGENT
    FASTAPI --> TZ_AGENT
    FASTAPI --> TENDER_AGENT

    DZO_RUNNER --> EMAIL_CLIENT
    DZO_RUNNER --> FILE_EXTRACTOR
    DZO_RUNNER --> EMAIL_SENDER
    DZO_RUNNER --> DZO_AGENT

    TZ_RUNNER --> EMAIL_CLIENT
    TZ_RUNNER --> FILE_EXTRACTOR
    TZ_RUNNER --> EMAIL_SENDER
    TZ_RUNNER --> TZ_AGENT

    TENDER_RUNNER --> FILE_EXTRACTOR
    TENDER_RUNNER --> TENDER_AGENT

    DZO_AGENT --> OPENAI
    TZ_AGENT --> OPENAI
    TENDER_AGENT --> OPENAI

    DZO_AGENT --> AGENT_TOOLING
    TZ_AGENT --> AGENT_TOOLING
    TENDER_AGENT --> AGENT_TOOLING
    AGENT_TOOLING --> DZO_AGENT
    AGENT_TOOLING --> TZ_AGENT
    AGENT_TOOLING --> TENDER_AGENT

    EMAIL_CLIENT --> EMAIL
    EMAIL_SENDER --> EMAIL

    DZO_RUNNER --> TELEGRAM
    TZ_RUNNER --> TELEGRAM

    STREAMLIT --> FASTAPI
```

## Поток данных

### Режим поллера (main.py)

```
1. Планировщик (schedule) → вызывает runner каждые N секунд
2. Runner → fetch_unseen_emails() → IMAP-сервер
3. Runner → extract_text_from_attachment() → извлечение текста из PDF/DOCX/XLSX/IMG
4. Runner → agent.invoke(chat_input) → LLM (OpenAI)
5. LLM → вызов tool-функций (generate_validation_report, generate_tezis_form, ...)
6. Runner → send_email() → SMTP-сервер → Получатель
7. Runner → notify() → Telegram (опционально)
```

### Режим REST API (api/app.py)

```
1. Клиент → POST /api/v1/process/{agent} (с X-API-Key)
2. API → создаёт job в PostgreSQL или in-memory fallback (UUID), возвращает job_id
3. BackgroundTask → _process_with_agent()
4. → extract_text_from_attachment() → текст из вложений
5. → agent.invoke(chat_input) → LLM (OpenAI)
6. → сохраняет результат в jobs[job_id]
7. Клиент → GET /api/v1/jobs/{job_id} → получает статус/результат
```

## Описание модулей

### `api/app.py` — REST API

FastAPI-приложение с полным набором эндпоинтов. Обеспечивает:
- Асинхронную обработку заданий через `BackgroundTasks`
- Хранение заданий в PostgreSQL с fallback в in-memory store
- API-ключ аутентификацию (заголовок `X-API-Key`)
- CORS middleware
- Swagger UI по адресу `/docs`

### `ui/app.py` — Web UI

Streamlit-приложение с 5 страницами навигации. Обращается к API через `httpx`.
Поддерживает динамический список агентов из `/agents`, автоопределение агента,
просмотр тендерных артефактов и результатов межагентных вызовов.

### `ui/config.py` — Конфигурация UI

Читает `UI_API_URL` и `UI_API_KEY` из переменных окружения.

### `agent1_dzo_inspector/`

| Файл | Описание |
|------|----------|
| `agent.py` | Создание LangChain AgentExecutor с системным промптом и инструментами |
| `runner.py` | Оркестратор: IMAP → текст → агент → SMTP |
| `tools.py` | Инструменты агента: отчёты, формы, письма, вызов peer-агентов |

### `agent2_tz_inspector/`

| Файл | Описание |
|------|----------|
| `agent.py` | Создание LangChain AgentExecutor для проверки ТЗ |
| `runner.py` | Оркестратор: IMAP → текст → агент → SMTP |
| `tools.py` | Инструменты: JSON-отчёт, исправленное ТЗ, письмо ДЗО, вызов peer-агентов |

### `agent21_tender_inspector/`

| Файл | Описание |
|------|----------|
| `agent.py` | Создание агента парсинга тендерной документации |
| `runner.py` | Обработка локальных документов/URL и сохранение JSON-результата |
| `tools.py` | Инструменты: список документов и вызов peer-агентов |

### `shared/`

| Файл | Описание |
|------|----------|
| `email_client.py` | Получение UNSEEN писем с вложениями через imaplib |
| `email_sender.py` | Отправка HTML-писем с вложениями через smtplib |
| `file_extractor.py` | Извлечение текста из PDF/DOCX/XLSX/XLS/IMG через pdfplumber, python-docx, openpyxl, GPT-4o Vision |
| `logger.py` | Настройка структурированного логирования |
| `telegram_notify.py` | Уведомления в Telegram (опционально) |

### `config.py`

Централизованная конфигурация из переменных окружения с fallback-значениями,
включая настройки межагентной оркестрации (`AGENT_TOOL_*`).

### `main.py`

Точка входа для агентов-поллеров. Запускает планировщик `schedule`.
