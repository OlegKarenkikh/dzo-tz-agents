# 🗺️ Roadmap исправлений (27 проблем)

## Приоритет 1 — CRITICAL (Гонки данных): RC-01..RC-05

### RC-01: shared/database.py — double-init _pool
```python
# ИСПРАВИТЬ: добавить перед _get_pool()
_pool_lock = threading.Lock()

def _get_pool():
    global _pool
    if _pool is None:           # fast path без блокировки
        with _pool_lock:
            if _pool is None:   # double-checked locking
                _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, DATABASE_URL)
    return _pool
```

### RC-02: api/app.py — _run_log без lock
```python
# ДОБАВИТЬ после строки 152:
_run_log_lock = threading.Lock()

# ОБЕРНУТЬ каждый append:
with _run_log_lock:
    _run_log.append({...})

# ОБЕРНУТЬ чтение в /status:
with _run_log_lock:
    log_list = list(_run_log)
```

### RC-03: shared/llm.py — 4 кеша без lock
```python
# ДОБАВИТЬ в начало файла:
_llm_cache_lock = threading.RLock()

# ОБЕРНУТЬ все операции записи в кеши:
with _llm_cache_lock:
    _MAX_INPUT_TOKENS_CACHE[model_name] = limit
```

### RC-04: shared/database.py — _memory_store без lock
```python
# ДОБАВИТЬ:
_memory_lock = threading.RLock()

# ОБЕРНУТЬ все create_job / update_job / delete_job:
with _memory_lock:
    _memory_store[job_id] = record
```

### RC-05: agent21_tender_inspector/runner.py — _fallback_chain_cache без lock
```python
# ДОБАВИТЬ:
_chain_cache_lock = threading.Lock()

with _chain_cache_lock:
    if _cache_key not in _fallback_chain_cache:
        _fallback_chain_cache[_cache_key] = (_chain, _model_ctx)
```

---

## Приоритет 2 — HIGH (Async + Data)

### MU-01: api/app.py — time.sleep → asyncio.sleep
```python
# БЫЛО:
time.sleep(AGENT_RATE_LIMIT_BACKOFF)
# СТАЛО:
await asyncio.sleep(AGENT_RATE_LIMIT_BACKOFF)
# + сделать _run_job async def + BackgroundTask передавать coroutine
```

### DA-01: Создать shared/migrations/002_add_trace_column.sql ✅ (этот PR)

### DA-02, DA-03: Заменить bare except pass
```python
# БЫЛО:
except Exception:
    pass
# СТАЛО:
except Exception as _step_err:
    logger.warning("[%s] step parse error: %s", job_id, _step_err)
```

### DA-05: Проверить decision после цикла
```python
if not decision:
    logger.warning("[%s] decision не установлен агентом — intermediate_steps пусты", job_id)
    decision = "Неизвестно"
```

---

## Приоритет 3 — MEDIUM (Дубли + Заглушки)

### DU-01: Создать shared/agent_runner.py
```python
# shared/agent_runner.py
class BaseAgentRunner:
    def __init__(self, graph_agent):
        self._agent = graph_agent

    def invoke(self, payload, **kwargs):
        # общая логика (90% кода из agent1/2/21)
        ...

# agent1/agent.py:
from shared.agent_runner import BaseAgentRunner
class AgentRunner(BaseAgentRunner):
    pass  # специфика если нужна
```

### DU-02: Создать shared/runner_base.py
```python
# shared/runner_base.py
def process_agent_emails(agent_type: str, cfg, create_agent_fn):
    """Общая логика для process_dzo_emails и process_tz_emails."""
    ...

# agent1/runner.py:
def process_dzo_emails():
    return process_agent_emails("dzo", config.DZO_CONFIG, create_dzo_agent)
```

### DU-03: Актуализировать описание миграций 001_init.sql / 001_create_jobs.sql
Зафиксировать текущее состояние: схема живёт в `001_create_jobs.sql`,
а `001_init.sql` является redirect-комментарием для обратной совместимости.
`002_add_trace_column.sql` ✅

### MU-03 + DU-04: Централизовать FORCE_REPROCESS
```python
# config.py — добавить:
FORCE_REPROCESS: bool = os.getenv("FORCE_REPROCESS", "false").lower() == "true"

# agent*/runner.py — удалить:
# FORCE_REPROCESS = os.getenv(...)  ← убрать из 3 файлов
# Заменить на: from config import FORCE_REPROCESS
```

### ST-02: Исправить импорт create_agent
```python
# БЫЛО (некорректно):
from langchain.agents import create_agent

# СТАЛО (нужно проверить какой тип агента используется):
from langgraph.prebuilt import create_react_agent
# или:
from langchain.agents import create_openai_tools_agent
```

---

## Приоритет 4 — HIGH Security

### SE-01: config.py
```python
# БЫЛО:
print("[config] Auto-switched ...", file=sys.stderr)
# СТАЛО:
_logger.info("Auto-switched to LLM_BACKEND=github_models")
```

### SE-03: api/rate_limit.py
```python
# СТАЛО:
def _get_rate_key(request: Request) -> str:
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"apikey:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
    return get_remote_address(request)

limiter = Limiter(key_func=_get_rate_key)
```
