# Модули пакета `shared/`

> Справочник всех общих модулей, используемых агентами проекта.

---

## Сводная таблица

| Модуль | Назначение | Ключевые классы/функции | Зависимости |
|--------|-----------|------------------------|-------------|
| `__init__.py` | Инициализация пакета, версия | `__version__` | — |
| `agent_tooling.py` | Межагентное взаимодействие — вызов агента как инструмента | `invoke_agent_as_tool`, `AGENT_TOOL_REGISTRY`, `_discover_agents` | `importlib`, `threading`, `config` |
| `chunked_analysis.py` | Поблочный анализ больших документов (map-reduce) | `analyze_document_in_chunks`, `_split_into_chunks`, `_analyze_chunk` | `httpx`, `config`, `shared.llm` |
| `database.py` | Хранение истории обработки (PostgreSQL / in-memory fallback) | `create_job`, `update_job`, `find_duplicate_job`, `get_pool` | `psycopg2`, `threading`, `uuid` |
| `document_parser.py` | Парсинг анкет участников ТО (PDF/DOCX → структурированные данные) | `parse_anketa`, `AnketaData` | `pdfplumber`, `python-docx`, `re` |
| `email_client.py` | Получение писем (IMAP / Exchange / MS Graph) | `fetch_unseen_emails`, `EmailClient` | `imaplib`, `asyncio`, `config` |
| `email_sender.py` | Отправка писем по SMTP | `send_email` | `smtplib`, `email.mime`, `config` |
| `file_extractor.py` | Извлечение текста из файлов различных форматов | `extract_text_from_attachment` | `pdfplumber`, `openpyxl`, `xlrd`, `python-docx`, `openai` |
| `file_storage.py` | Файловое хранилище документов ТО | `save_document`, `create_folder_structure` | `pathlib`, `asyncio` |
| `insurance_domain.py` | Справочник страховой отрасли РФ (виды страхования, ОКПД 2, НПА) | `InsuranceType`, `classify_insurance_type` | `re`, `dataclasses` |
| `llm.py` | Фабрика LLM для всех агентов | `build_llm`, `build_github_fallback_chain`, `estimate_tokens`, `probe_max_input_tokens` | `langchain_openai`, `httpx`, `threading`, `config` |
| `logger.py` | Настройка логирования | `setup_logger` | `logging`, `logging.handlers` |
| `mcp_rate_limiter.py` | Rate-limiting для MCP-вызовов (token bucket) | `MCPRateLimiter`, `check_rate_limit` | `threading`, `time` |
| `mcp_server.py` | MCP-сервер для интеграции с Claude Desktop / Cursor / Copilot | `create_mcp_server`, MCP-обёртки агентов | `mcp`, `asyncio` |
| `runner_base.py` | Базовые классы: адаптер агента и email-раннер | `BaseAgentRunner`, `BaseEmailRunner` | `abc`, `json`, `config`, `api.metrics`, `shared.email_client`, `shared.tracing` |
| `telegram_notify.py` | Уведомления в Telegram | `notify` | `httpx`, `os` |
| `tracing.py` | Трассировка шагов агентов через Langfuse | `get_langfuse_callback`, `log_agent_steps` | `langfuse`, `functools`, `json` |

---

## Подробное описание модулей

### `__init__.py`
Инициализация пакета `shared`. Содержит строку версии `__version__ = "1.0.0"`.

### `agent_tooling.py`
Универсальный мост для межагентного взаимодействия. Позволяет одному агенту вызывать другого как LangChain tool. Поддерживает: реестр фабрик агентов (`AGENT_TOOL_REGISTRY`), систему прав доступа (`AGENT_TOOL_PERMISSIONS`), кеширование экземпляров, автоматическое обнаружение агентов по naming convention.

### `chunked_analysis.py`
Map-reduce обработка документов, превышающих контекстное окно модели. Фаза 1: разбиение на чанки ~5K символов с перекрытием, анализ каждого чанка отдельным LLM-вызовом. Фаза 2: синтез промежуточных результатов в итоговое резюме. Используется agent21 для обработки больших тендерных документов.

### `database.py`
PostgreSQL-хранилище с `ThreadedConnectionPool` (psycopg2). Fallback на in-memory dict при отсутствии `DATABASE_URL`. Потокобезопасный доступ через `threading.RLock`. Основные операции: создание записи о задаче, обновление статуса, поиск дубликатов, хранение трассировки.

### `document_parser.py`
Структурированное извлечение данных из анкет участников ТО. Парсит 15-польную анкету из PDF (pdfplumber) и DOCX (python-docx) в датакласс `AnketaData`. Используется `agent3_collector_inspector/tools.py` для автоматической валидации анкет (опциональный импорт с graceful degradation при отсутствии зависимостей).

### `email_client.py`
Поддержка нескольких бэкендов получения почты: IMAP (основной), Exchange Web Services, Microsoft Graph API. Основной интерфейс — `fetch_unseen_emails()` для синхронной работы и `EmailClient` для асинхронной. Декодирование RFC 2047, извлечение вложений с base64.

### `email_sender.py`
Отправка писем по SMTP с поддержкой HTML-тела и вложений (байтовый поток). Используется agent1 (DZO) и agent2 (TZ) для отправки ответов.

### `file_extractor.py`
Универсальный извлекатель текста. Поддерживает: PDF (pdfplumber), DOCX (python-docx), XLSX/XLS (openpyxl/xlrd), изображения (OpenAI Vision OCR). Fallback на OCR при пустом текстовом слое в PDF.

### `file_storage.py`
Файловое хранилище для документов тендерного отбора. Создаёт структуру папок по участникам (`ТО {id}/Предложения/Участник N/...`). Поддерживает асинхронные операции ввода-вывода. Базовый путь задаётся через `STORAGE_BASE_PATH`.

### `insurance_domain.py`
База знаний по страховой отрасли РФ. Содержит: классификатор видов страхования (Закон 4015-1, ст. 32.9), коды ОКПД 2 (раздел 65), ссылки на нормативные акты, ключевые слова для классификации тендеров в страховой сфере.

### `llm.py`
Единая точка создания `ChatOpenAI` для всех агентов. Поддерживает бэкенды: OpenAI, Ollama, DeepSeek, vLLM, LM Studio, GitHub Models. Функции оценки токенов (`estimate_tokens`), построения fallback-цепочки моделей, определения контекстного окна (`probe_max_input_tokens`). Потокобезопасное кеширование через `threading.Lock`.

### `logger.py`
Утилита настройки логирования с `RotatingFileHandler`. Формат: ISO-timestamp, имя логгера, уровень. Вызов `setup_logger("name")` возвращает готовый логгер.

### `mcp_rate_limiter.py`
Rate-limiting для MCP-вызовов инструментов. Алгоритм token bucket с настраиваемым лимитом запросов. Потокобезопасная реализация для concurrent `asyncio.to_thread`.

### `mcp_server.py`
MCP (Model Context Protocol) сервер. Экспонирует агентов DZO, TZ, Tender и Collector как инструменты для MCP-совместимых клиентов (Claude Desktop, Cursor, Copilot, Continue). Поддерживает stdio и HTTP streaming.

### `runner_base.py`
Содержит два базовых класса:
- **`BaseAgentRunner`** — адаптер, приводящий LangGraph ReAct-агент к контракту `invoke({"input": ...})`. Используется всеми агентами.
- **`BaseEmailRunner`** — абстрактный email-раннер с шаблонным методом `process_emails()`. Наследуется agent1 (`DzoEmailRunner`) и agent2 (`TzEmailRunner`).

### `telegram_notify.py`
Отправка уведомлений в Telegram-канал. Функция `notify(message, level)` с уровнями: info, warning, error, success. Динамическое чтение `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` из окружения.

### `tracing.py`
Интеграция с Langfuse для трассировки шагов агентов. Обеспечивает callback для LangChain (`get_langfuse_callback`), логирование промежуточных шагов (`log_agent_steps`), усечение длинных строк для хранения в БД.

---

## Модуль `config.py` (корень проекта)

Центральный модуль конфигурации. Все параметры читаются из переменных окружения с безопасными значениями по умолчанию.

### LLM-конфигурация

| Переменная | По умолчанию | Описание | Используется |
|-----------|-------------|----------|-------------|
| `OPENAI_API_KEY` | — | API-ключ OpenAI | `shared/llm.py`, `agent21/runner.py` |
| `OPENAI_API_BASE` | — | Базовый URL OpenAI-совместимого API | `shared/llm.py` |
| `LLM_BACKEND` | `openai` | Бэкенд LLM: `openai`, `ollama`, `deepseek`, `vllm`, `lmstudio`, `github_models` | `shared/llm.py`, `agent21/runner.py` |
| `GITHUB_TOKEN` / `GH_TOKEN` | — | Токен GitHub Models | `shared/llm.py`, `agent21/runner.py` |
| `MODEL_NAME` | `gpt-4o` | Имя модели LLM | `shared/llm.py`, все агенты |
| `FALLBACK_MODELS` | `""` | Список fallback-моделей через запятую | `shared/llm.py` |

### Email-конфигурация (DZO)

| Переменная | По умолчанию | Описание | Используется |
|-----------|-------------|----------|-------------|
| `DZO_IMAP_HOST` | `imap.company.ru` | IMAP-хост ДЗО | `agent1/runner.py` |
| `DZO_IMAP_PORT` | `993` | IMAP-порт ДЗО | `agent1/runner.py` |
| `DZO_IMAP_USER` | — | IMAP-логин ДЗО | `agent1/runner.py` |
| `DZO_IMAP_PASSWORD` | — | IMAP-пароль ДЗО | `agent1/runner.py` |
| `DZO_IMAP_FOLDER` | `INBOX` | Папка IMAP ДЗО | `agent1/runner.py` |
| `DZO_SMTP_FROM` | `ucz@company.ru` | Адрес отправителя ДЗО | `agent1/runner.py` |

### Email-конфигурация (ТЗ)

| Переменная | По умолчанию | Описание | Используется |
|-----------|-------------|----------|-------------|
| `TZ_IMAP_HOST` | `imap.company.ru` | IMAP-хост ТЗ | `agent2/runner.py` |
| `TZ_IMAP_PORT` | `993` | IMAP-порт ТЗ | `agent2/runner.py` |
| `TZ_IMAP_USER` | — | IMAP-логин ТЗ | `agent2/runner.py` |
| `TZ_IMAP_PASSWORD` | — | IMAP-пароль ТЗ | `agent2/runner.py` |
| `TZ_IMAP_FOLDER` | `INBOX` | Папка IMAP ТЗ | `agent2/runner.py` |
| `TZ_SMTP_FROM` | `ucz@company.ru` | Адрес отправителя ТЗ | `agent2/runner.py` |

### SMTP-конфигурация

| Переменная | По умолчанию | Описание | Используется |
|-----------|-------------|----------|-------------|
| `SMTP_HOST` | `smtp.company.ru` | SMTP-хост для отправки | `shared/email_sender.py` |
| `SMTP_PORT` | `587` | SMTP-порт | `shared/email_sender.py` |
| `SMTP_USER` | — | SMTP-логин | `shared/email_sender.py` |
| `SMTP_PASSWORD` | — | SMTP-пароль | `shared/email_sender.py` |
| `MANAGER_EMAIL` | `manager@company.ru` | Email руководителя (для эскалаций) | `agent1/runner.py` |

### Email-конфигурация (Collector)

| Переменная | По умолчанию | Описание | Используется |
|-----------|-------------|----------|-------------|
| `EMAIL_BACKEND` | `imap` | Бэкенд email: `imap`, `exchange`, `graph` | `shared/email_client.py` |
| `EMAIL_HOST` | `""` | Хост для получения писем | `shared/email_client.py`, `agent3/runner.py` |
| `EMAIL_PORT` | `993` | Порт для получения писем | `shared/email_client.py`, `agent3/runner.py` |
| `EMAIL_USER` | `""` | Логин для получения писем | `shared/email_client.py`, `agent3/runner.py` |
| `EMAIL_PASSWORD` | `""` | Пароль для получения писем | `shared/email_client.py`, `agent3/runner.py` |
| `EMAIL_USE_SSL` | `true` | Использовать SSL | `shared/email_client.py` |

### Файловое хранилище

| Переменная | По умолчанию | Описание | Используется |
|-----------|-------------|----------|-------------|
| `STORAGE_BASE_PATH` | `./storage` | Базовый путь для хранения документов | `shared/file_storage.py` |

### Агент — общие настройки

| Переменная | По умолчанию | Описание | Используется |
|-----------|-------------|----------|-------------|
| `FORCE_REPROCESS` | `false` | Игнорировать дедупликацию | все runner'ы |
| `POLL_INTERVAL_SEC` | `300` | Интервал опроса почты (сек) | `main.py` |
| `AGENT_JOB_TIMEOUT_SEC` | `300` | Таймаут задачи агента | `config.py` |
| `AGENT_MAX_RETRIES` | `1` | Макс. число повторов | `config.py` |
| `AGENT_RATE_LIMIT_BACKOFF` | `3.0` | Backoff при rate limit | `config.py` |
| `AGENT_INVOKE_TIMEOUT_SECONDS` | `300` | Таймаут вызова `agent.invoke()` | `shared/runner_base.py` |

### Межагентное взаимодействие

| Переменная | По умолчанию | Описание | Используется |
|-----------|-------------|----------|-------------|
| `AGENT_TOOL_ENABLED` | `true` | Включить межагентные вызовы | `shared/agent_tooling.py` |
| `AGENT_TOOL_REGISTRY` | `{}` | JSON-реестр фабрик агентов | `shared/agent_tooling.py` |
| `AGENT_TOOL_PERMISSIONS` | `{}` | JSON-матрица прав доступа | `shared/agent_tooling.py` |
| `PUBLIC_BASE_URL` | — | Публичный URL сервиса (A2A Agent Card) | `api/app.py` |

### Тендерный агент (agent21)

| Переменная | По умолчанию | Описание | Используется |
|-----------|-------------|----------|-------------|
| `TENDER_DOCS_DIR` | `tender_docs` | Папка для пакетного сканирования | `agent21/runner.py` |
| `TENDER_OUTPUT_DIR` | `""` | Папка для результатов JSON | `agent21/runner.py` |

### MCP-конфигурация

| Переменная | По умолчанию | Описание | Используется |
|-----------|-------------|----------|-------------|
| `MCP_AGENT_TIMEOUT_SECONDS` | `300` | Таймаут MCP-вызова | `shared/mcp_server.py` |

---

## Директория `migrations/`

SQL-миграции для PostgreSQL:
- `001_create_jobs.sql` — создание таблицы `jobs` для хранения истории обработки
- `002_add_trace_column.sql` — добавление колонки `trace` для хранения трассировки шагов
