# 🔍 Глубокий аудит кода: dzo-tz-agents

> Дата: 2026-04-08 | Ветка: main (SHA: 95175804)

---

## 📁 Карта репозитория

| Файл / Директория | Тип | Размер | Назначение |
|---|---|---|---|
| `main.py` | Entry point | 2.3 KB | Запуск poll-loop агентов DZO/TZ |
| `config.py` | Конфиг | 5.3 KB | Все env-переменные; auto-switch LLM_BACKEND |
| `health_check.py` | CLI-утилита | 2.5 KB | Проверка импортов и создания агентов |
| `api/app.py` | REST API | 40.5 KB | FastAPI: все эндпоинты, _run_job, AGENT_REGISTRY |
| `api/healthcheck.py` | Эндпоинт | 2.3 KB | GET /health |
| `api/metrics.py` | Prometheus | 2.7 KB | Counter/Histogram метрики |
| `api/rate_limit.py` | Middleware | 1.3 KB | slowapi лимитер по IP |
| `agent1_dzo_inspector/agent.py` | LLM-агент | 7.1 KB | AgentRunner + SYSTEM_PROMPT + create_dzo_agent |
| `agent1_dzo_inspector/runner.py` | Email-runner | 8.6 KB | process_dzo_emails() |
| `agent1_dzo_inspector/tools.py` | LangChain tools | 15.1 KB | 6 @tool: validation_report, tezis_form, info_request, escalation, response_email, corrected_app |
| `agent2_tz_inspector/agent.py` | LLM-агент | 8.1 KB | AgentRunner + SYSTEM_PROMPT + create_tz_agent |
| `agent2_tz_inspector/runner.py` | Email-runner | 6.6 KB | process_tz_emails() |
| `agent2_tz_inspector/tools.py` | LangChain tools | 10.9 KB | 3 @tool: json_report, corrected_tz, email_to_dzo |
| `agent21_tender_inspector/agent.py` | LLM-агент | 8.9 KB | AgentRunner + create_tender_agent |
| `agent21_tender_inspector/runner.py` | File-runner | 26.6 KB | process_single_document, process_tender_documents |
| `agent21_tender_inspector/tools.py` | LangChain tools | 7.6 KB | generate_document_list |
| `shared/database.py` | DB layer | 16.2 KB | psycopg2 ThreadedConnectionPool + in-memory fallback |
| `shared/llm.py` | LLM factory | 23.3 KB | build_llm, build_github_fallback_chain, probe_max_* |
| `shared/chunked_analysis.py` | Map-reduce | 18.8 KB | Chunkify + LLM per-chunk + reduce |
| `shared/email_client.py` | IMAP client | 3.9 KB | fetch_unseen_emails() |
| `shared/email_sender.py` | SMTP client | 1.97 KB | send_email() |
| `shared/file_extractor.py` | Extractor | 7.4 KB | PDF/DOCX/XLSX → text |
| `shared/logger.py` | Logging | 1.1 KB | setup_logger() |
| `shared/telegram_notify.py` | Telegram | 1.2 KB | notify() |
| `shared/tracing.py` | Langfuse | 5.0 KB | get_langfuse_callback(), log_agent_steps() |
| `shared/migrations/001_init.sql` | SQL | 1.1 KB | CREATE TABLE jobs + триггер updated_at |
| `shared/migrations/001_create_jobs.sql` | SQL | 1.4 KB | CREATE TABLE jobs + COMMENT (ДУБЛЬ!) |
| `ui/app.py` | Streamlit UI | ~30 KB | Dashboard, Testing, Settings, History |
| `ui/config.py` | UI конфиг | 0.9 KB | API_URL, AUTH_HEADERS, AUTO_REFRESH |
| `nginx/nginx.conf` | Nginx | 1.3 KB | Reverse proxy config |
| `nginx/conf.d/default.conf` | Nginx sites | ~2 KB | Upstream, rate limit, SSL |
| `docker-compose.yml` | Docker | 6.1 KB | API + UI + Postgres + Redis сервисы |
| `Dockerfile` | Docker | 2.4 KB | Multi-stage Python build |
| `pyproject.toml` | Deps | 4.3 KB | hatch + ruff + mypy конфигурация |
| `tests/` | Tests | ~120 KB | 17 тест-файлов |

---

## 🔗 Граф зависимостей

```
main.py
  └── agent1_dzo_inspector/runner.py → shared/email_client, email_sender, database, llm, tracing
  └── agent2_tz_inspector/runner.py  → shared/email_client, email_sender, database, llm, tracing

api/app.py
  ├── config.py
  ├── shared/database.py  ← ThreadedConnectionPool или in-memory dict
  ├── api/metrics.py      ← Prometheus counters
  ├── api/rate_limit.py   ← slowapi
  └── agent*/agent.py     ← create_*_agent()

agent*/agent.py
  ├── shared/llm.py       ← build_llm(), probe_max_*
  └── agent*/tools.py     ← @tool definitions

shared/llm.py
  ├── config.py
  └── langchain_openai.ChatOpenAI

shared/database.py
  └── psycopg2.pool.ThreadedConnectionPool (optional)

agent21_tender_inspector/runner.py
  ├── shared/chunked_analysis.py
  ├── shared/file_extractor.py
  └── shared/llm.py
```

---

## 🐛 Каталог проблем (27 проблем)

### ⛔ CRITICAL: Гонки данных (Race Conditions) — 5 проблем

#### RC-01 — `shared/database.py:67-71` — double-init _pool
```python
# ПРОБЛЕМА: check-then-act без блокировки
global _pool
if _pool is None:                          # ← поток A и поток B одновременно видят None
    _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, DATABASE_URL)  # ← оба создают пул
```
**Последствие:** Два пула соединений, утечка соединений, непредсказуемое поведение.

**Исправление:**
```python
_pool_lock = threading.Lock()

def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:  # double-checked locking
                _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, DATABASE_URL)
    return _pool
```

#### RC-02 — `api/app.py:152,643,728` — _run_log deque без блокировки
```python
_run_log: deque[dict] = deque(maxlen=500)  # глобал без lock

# В фоновой задаче (другой поток):
_run_log.append({...})  # ← не атомарно при concurrent list()

# В /status handler:
log_list = list(_run_log)  # ← читает одновременно с append
```
**Исправление:** Добавить `_run_log_lock = threading.Lock()` вокруг чтения и записи.

#### RC-03 — `shared/llm.py:61-80` — 4 глобальных кеша без блокировки
```python
_MAX_OUTPUT_TOKENS_CACHE: dict[str, int] = {}
_MAX_INPUT_TOKENS_CACHE:  dict[str, int] = {}
_LOCAL_MAX_CTX_CACHE:     dict[tuple, int] = {}
_LOCAL_MODELS_CACHE:      dict[str, list] = {}
# Запись без Lock в многопоточном окружении!
```
**Исправление:** `_llm_cache_lock = threading.RLock()` или `functools.lru_cache`.

#### RC-04 — `shared/database.py:17` — _memory_store dict без блокировки
```python
_memory_store: dict[str, dict] = {}  # без Lock
# create_job, update_job, delete_job — все мутируют из параллельных BackgroundTasks
```

#### RC-05 — `agent21_tender_inspector/runner.py:56` — _fallback_chain_cache без блокировки
```python
_fallback_chain_cache: dict[tuple, tuple] = {}  # global, без Lock
if _cache_key not in _fallback_chain_cache:      # ← race condition при concurrent miss
    _fallback_chain_cache[_cache_key] = (...)
```

---

### 🔴 HIGH: Мутации и данные — 8 проблем

#### MU-01 — `api/app.py:553,573` — time.sleep() в async-контексте
```python
time.sleep(AGENT_RATE_LIMIT_BACKOFF)  # ← блокирует event loop uvicorn!
```
**Исправление:** `await asyncio.sleep(AGENT_RATE_LIMIT_BACKOFF)` + `async def _run_job`.

#### MU-02 — `api/app.py:596-623` — dict артефактов перезаписывается без предупреждения
Если два шага возвращают `email_html` — первый теряется без лога.

#### MU-03 — FORCE_REPROCESS продублирован в трёх runner-файлах
`FORCE_REPROCESS = os.getenv('FORCE_REPROCESS', 'false').lower() == 'true'` — строка идентична в agent1/runner, agent2/runner, agent21/runner. Должен быть в `config.py`.

#### DA-01 — SQL-миграции не содержат колонку `trace`
`shared/database.py` создаёт `trace JSONB` через `ALTER TABLE` в `init_db()`, но обе SQL-миграции `001_*` не имеют этой колонки. При ручном применении миграций → runtime KeyError.

#### DA-02 — `agent1/runner.py:132-133` — bare `except Exception: pass` при разборе steps
```python
except Exception:
    pass  # ← решение агента (decision, artifacts) теряется без лога!
```

#### DA-03 — `api/app.py:623-624` — аналогичный bare `except Exception: pass`

#### DA-04 — `shared/email_client.py` — ошибка письма не имеет retry/метрики
Письмо пропускается навсегда при ошибке разбора, нет счётчика.

#### DA-05 — `api/app.py:580` — `decision` может остаться `''` при пустых steps
```python
decision = ""
for step in result.get("intermediate_steps", []):  # ← пустой → decision = ""
    ...
update_job(job_id, decision=decision, ...)  # ← записывает "" в БД
```

---

### 🟠 MEDIUM: Дубли — 4 проблемы

#### DU-01 — Класс `AgentRunner` трижды (agent1, agent2, agent21)
90%+ кода идентично. Нужен `shared/agent_runner.py::BaseAgentRunner`.

#### DU-02 — `process_dzo_emails()` / `process_tz_emails()` — структурные клоны
Извлечь в `shared/runner_base.py::process_agent_emails(agent_type, cfg)`.

#### DU-03 — Два SQL-файла `001_*` с разным содержанием
- `001_create_jobs.sql` — CREATE TABLE + COMMENT (без триггера)
- `001_init.sql` — CREATE TABLE + триггер updated_at (без COMMENT)
Неизвестно какой активен; риск неполной схемы.

#### DU-04 — `FORCE_REPROCESS` объявлен в трёх файлах (→ MU-03)

---

### 🟡 MEDIUM: Заглушки — 3 проблемы

#### ST-01 — `agent21_tender_inspector/tools.py:29,40,48` — bare `pass`
Пустые блоки в Pydantic-моделях. Требует проверки.

#### ST-02 — `from langchain.agents import create_agent` — нестандартный импорт
```python
# В agent1/agent.py и agent2/agent.py:
from langchain.agents import create_agent  # ← публичной create_agent нет в langchain!
```
Должно быть `create_openai_tools_agent` или `create_react_agent`.

#### ST-03 — Mock-заглушки в conftest скрывают API-несоответствия
MagicMock для AgentExecutor позволяет тестам проходить при полностью сломанном langchain API.

---

### 🔵 HIGH: Безопасность — 3 проблемы

#### SE-01 — `config.py:67-70` — `print()` вместо `logger` для события с GITHUB_TOKEN
#### SE-02 — `ui/config.py:14-16` — API_KEY в module-level переменной AUTH_HEADERS
#### SE-03 — `api/rate_limit.py` — rate limit только по IP, обходится через разные IP

---

### 🟢 LOW: Качество кода — 4 проблемы

#### CQ-01 — 23 вызова `print()` в `health_check.py` вместо `logger`
#### CQ-02 — 11 `except Exception` без re-raise в production-коде
#### CQ-03 — Нет circuit breaker для LLM-вызовов (каскадные 429)
#### CQ-04 — Логгер дважды инициализируется в agent1/agent2 agent.py + runner.py

---

## ✅ Чек-лист приёмки и тестирования

### Блок A: Гонки данных (CRITICAL)

- [ ] **A-1** `shared/database.py` — добавить `_pool_lock = threading.Lock()` + double-checked locking в `_get_pool()`
- [ ] **A-2** `shared/database.py` — добавить `_memory_lock = threading.RLock()` вокруг всех операций `_memory_store`
- [ ] **A-3** `api/app.py` — добавить `_run_log_lock = threading.Lock()` вокруг `_run_log.append()` и `list(_run_log)`
- [ ] **A-4** `shared/llm.py` — добавить `_llm_cache_lock = threading.RLock()` вокруг записи во все четыре кеша
- [ ] **A-5** `agent21_tender_inspector/runner.py` — добавить `_chain_cache_lock = threading.Lock()` для `_fallback_chain_cache`

**Тест приёмки A:**
```python
# pytest tests/test_database.py::test_concurrent_create_job
import threading
def test_concurrent_create_job():
    threads = [threading.Thread(target=db.create_job, args=("dzo",)) for _ in range(20)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert len(db._memory_store) == 20  # нет потерь
```

### Блок B: Async/sync (HIGH)

- [ ] **B-1** `api/app.py` — заменить `time.sleep()` на `asyncio.sleep()` в `_run_job`; сделать функцию `async def`
- [ ] **B-2** Убедиться что все `BackgroundTasks` корректно работают в async-контексте

**Тест приёмки B:**
```bash
# Проверить отсутствие блокировки event loop под нагрузкой
ab -n 100 -c 10 http://localhost:8000/health  # не должно быть timeouts
```

### Блок C: Данные и миграции (HIGH)

- [ ] **C-1** Создать `shared/migrations/002_add_trace_column.sql`
- [ ] **C-2** Удалить или отметить `001_create_jobs.sql` как deprecated
- [ ] **C-3** Заменить `except Exception: pass` в agent1/runner:132, agent2/runner:112, api/app:623 на `logger.warning`
- [ ] **C-4** Добавить проверку `if not decision: logger.warning(...)` после цикла steps
- [ ] **C-5** Добавить `EMAILS_ERRORS` метрику на каждый потерянный IMAP-email

**Тест приёмки C:**
```python
def test_step_parse_error_is_logged(caplog):
    with caplog.at_level(logging.WARNING):
        process_steps([(None, "invalid{json")])
    assert "step parse error" in caplog.text
```

### Блок D: Дубли и рефакторинг (MEDIUM)

- [ ] **D-1** Создать `shared/agent_runner.py::BaseAgentRunner`; рефакторить agent1, agent2, agent21
- [ ] **D-2** Создать `shared/runner_base.py::process_agent_emails()`; рефакторить runners
- [ ] **D-3** Вынести `FORCE_REPROCESS` в `config.py`
- [ ] **D-4** Проверить `from langchain.agents import create_agent` — убедиться в корректности

### Блок E: Безопасность (HIGH)

- [ ] **E-1** `config.py:67` — заменить `print()` на `logger.info()`
- [ ] **E-2** `api/rate_limit.py` — реализовать `key_func` с приоритетом X-API-Key → IP
- [ ] **E-3** `ui/config.py` — убедиться что API_KEY не попадает в logs/session_state

### Блок F: Заглушки (MEDIUM)

- [ ] **F-1** Проверить `agent21_tender_inspector/tools.py:29,40,48` — убрать `pass` или добавить raise
- [ ] **F-2** Разделить тесты: `@pytest.mark.unit` (mock) и `@pytest.mark.integration` (real LLM)
- [ ] **F-3** Документировать `create_agent` — откуда импортируется и что возвращает

### Финальный smoke test

```bash
make lint          # ruff check . --select=ALL
make type-check    # mypy .
make test          # pytest tests/ -v
docker compose up --build
curl http://localhost:8000/health  # {"status": "ok"}
```

---

## 📊 Машиночитаемые данные

См. файлы:
- `analysis/issues_catalog.json` — полный каталог 27 проблем
- `analysis/file_analysis.json` — метаданные 29 файлов
