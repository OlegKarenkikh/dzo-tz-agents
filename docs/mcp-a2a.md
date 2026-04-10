# MCP и A2A интеграция

Начиная с версии **1.5.0** проект поддерживает два открытых протокола для агент-агентного взаимодействия:

- **MCP** (Model Context Protocol) — позволяет вызывать агентов из любого MCP-совместимого клиента
- **A2A** (Agent-to-Agent) — декларирует возможности сервиса через стандартную карточку агента

---

## MCP (Model Context Protocol)

### Что это даёт

MCP-сервер превращает агентов проекта в **инструменты**, доступные из:
- Claude Desktop
- Cursor / Continue
- VS Code Copilot (с MCP-расширением)
- Любого кастомного MCP-хоста

### Доступные инструменты

| Инструмент | Описание |
|---|---|
| `inspect_dzo` | Проверяет заявку ДЗО на полноту и соответствие требованиям |
| `inspect_tz` | Анализирует техническое задание по ГОСТ |
| `inspect_tender` | Извлекает список документов из тендерной документации |
| `list_agents` | Возвращает список доступных агентов |

### Режим 1: HTTP-стрим (встроен в API)

MCP-сервер автоматически монтируется по адресу `/mcp` при запуске FastAPI.

```
GET/POST http://localhost:8000/mcp
```

Добавьте в конфигурацию MCP-клиента:

```json
{
  "mcpServers": {
    "dzo-tz-agents": {
      "url": "http://localhost:8000/mcp",
      "transport": "streamable-http"
    }
  }
}
```

### Режим 2: stdio (для Claude Desktop)

```bash
pip install 'mcp[cli]>=1.3.0'
python -m shared.mcp_server
```

Конфигурация `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "dzo-tz-agents": {
      "command": "python",
      "args": ["-m", "shared.mcp_server"],
      "cwd": "/path/to/dzo-tz-agents",
      "env": {
        "OPENAI_API_KEY": "sk-...",
        "LLM_BACKEND": "openai",
        "MODEL_NAME": "gpt-4o"
      }
    }
  }
}
```

### Переменные окружения

| Переменная | Описание | По умолчанию |
|---|---|---|
| `MCP_LOG_LEVEL` | Уровень логирования MCP stdio-сервера | `WARNING` |

---

## A2A (Agent-to-Agent Protocol)

### Agent Card

Стандартная карточка агента доступна по адресу:

```
GET /.well-known/agent.json
```

Пример ответа:

```json
{
  "name": "DZO/TZ Inspector",
  "description": "Инспектор заявок ДЗО и технических заданий",
  "version": "1.5.0",
  "url": "http://localhost:8000",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false
  },
  "skills": [
    {"id": "inspect_dzo", "name": "Проверка заявок ДЗО"},
    {"id": "inspect_tz", "name": "Проверка технических заданий"},
    {"id": "inspect_tender", "name": "Парсинг тендерной документации"}
  ]
}
```

### Использование с ADK (Google Agent Development Kit)

```python
from google.adk.agents import RemoteAgent

dzo_inspector = RemoteAgent(
    agent_card_url="http://localhost:8000/.well-known/agent.json",
)
```

### Безопасность

**В проде обязательно задайте `PUBLIC_BASE_URL` или `AGENT_CARD_ALLOWED_HOSTS`**, иначе поле `url` в Agent Card будет формироваться из Host-заголовка входящего запроса (риск подмены).

| Переменная | Описание | Поведение без неё |
|---|---|---|
| `PUBLIC_BASE_URL` | Явный базовый URL сервиса (приоритет) | Используется `AGENT_CARD_ALLOWED_HOSTS` |
| `AGENT_CARD_ALLOWED_HOSTS` | Через запятую допустимые hostname | HTTP 500, если и `PUBLIC_BASE_URL` не задан |

Пример:
```bash
# Рекомендуется:
PUBLIC_BASE_URL=https://agents.company.ru

# Или allowlist (когда PUBLIC_BASE_URL не задан):
AGENT_CARD_ALLOWED_HOSTS=agents.company.ru,localhost
```

---



MCP и A2A реализованы как тонкий адаптерный слой поверх существующих агентов — без изменения их внутренней логики. Это соответствует принципу единственной ответственности:

```
┌────────────────────────────────────────────────┐
│                 Транспортный слой               │
│  REST API (/api/v1/*)  MCP (/mcp)  A2A (/.well-known) │
└───────────────────────┬────────────────────────┘
                        │
┌───────────────────────▼────────────────────────┐
│              AgentRunner (адаптер)              │
│    invoke({"input": ...}) → {output, steps}     │
└───────────────────────┬────────────────────────┘
                        │
┌───────────────────────▼────────────────────────┐
│           LangGraph create_react_agent          │
│         (ReAct + tool-calling + logging)        │
└────────────────────────────────────────────────┘
```
