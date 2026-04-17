# 🤝 Урок 7: Агент как инструмент

![Агент ДЗО вызывает Агент ТЗ](images/lesson_07_agent_as_tool.png)

---

## 🤔 Зачем одному агенту вызывать другого?

В проекте есть несколько специализированных агентов:
- **Агент ДЗО** — проверяет заявки от дочерних обществ
- **Агент ТЗ** — специализируется на анализе технических заданий
- **Агент Тендер** — разбирает тендерную документацию
- **Агент Collector** — собирает анкеты участников

Каждый агент — эксперт в своей области. Когда Агент ДЗО встречает техническое задание в письме — он не анализирует его сам, а **делегирует** эту работу специалисту — Агенту ТЗ.

---

## 🔗 Как это работает в проекте?

В заявке ДЗО может быть приложено техническое задание (ТЗ).
Согласно промпту (`prompts/dzo_v1.md`):

```
ШАГ 1.1 — Если найдено ТЗ (или текст ТЗ в теле/вложении),
           вызови analyze_tz_with_agent.
           Результат анализа ТЗ обязательно включи в итоговое резюме.
```

Инструмент `analyze_tz_with_agent` в `agent1_dzo_inspector/tools.py`:

```python
@tool("analyze_tz_with_agent")
def analyze_tz_with_agent(tz_text: str, email_subject: str, source_sender: str) -> dict:
    # Делегирует анализ ТЗ агенту ТЗ и возвращает сводку.
    # Используй, если в письме ДЗО есть вложение с техническим заданием.
    result = invoke_agent_as_tool(
        source_agent="dzo",
        target_agent="tz",
        query=tz_text,
    )
    return result
```

---

## ⚙️ Как устроен bridge `shared/agent_tooling.py`?

Файл `shared/agent_tooling.py` — это универсальный мост между агентами:

```
AGENT_TOOL_REGISTRY = {
    "dzo":       "agent1_dzo_inspector.agent:create_dzo_agent",
    "tz":        "agent2_tz_inspector.agent:create_tz_agent",
    "tender":    "agent21_tender_inspector.agent:create_tender_agent",
    "collector": "agent3_collector_inspector.agent:create_collector_agent",
}
```

Когда `dzo` вызывает `tz`:
1. `agent_tooling` находит фабрику `create_tz_agent` в реестре
2. Создаёт экземпляр агента ТЗ (или берёт из кэша)
3. Передаёт текст ТЗ как запрос
4. Возвращает результат обратно в агент ДЗО

---

## 🔐 Разрешения (permissions)

Можно ограничить, какой агент кого может вызывать:

```bash
# .env — разрешить всем вызывать всех (по умолчанию)
AGENT_TOOL_PERMISSIONS={"*":["*"]}

# Только ДЗО может вызывать ТЗ и Тендер
AGENT_TOOL_PERMISSIONS={"dzo":["tz","tender"]}

# Полностью отключить межагентные вызовы
AGENT_TOOL_ENABLED=false
```

---

## ✅ Практика: проверить межагентный вызов

```bash
# Отправляем заявку ДЗО с текстом ТЗ — агент ДЗО должен вызвать агент ТЗ
curl -X POST http://localhost:8000/api/v1/dzo/inspect \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "document": "Заявка на закупку серверов.\n\nТЕХНИЧЕСКОЕ ЗАДАНИЕ:\n1. Цель: приобретение серверов\n2. Требования: CPU Intel Xeon\n3. Объём: 5 шт.\n4. Место поставки: г. Москва"
  }'
```

В логах вы увидите вызов обоих агентов:
```
INFO agent_dzo: Запуск агента...
INFO agent_tooling: dzo → tz (межагентный вызов)
INFO agent_tz: Запуск агента ТЗ...
```

---

## 📍 Что запомнить

| Понятие | Значение |
|---|---|
| `analyze_tz_with_agent` | Инструмент ДЗО для делегирования анализа ТЗ |
| `invoke_agent_as_tool` | Универсальная функция вызова агента как инструмента |
| `AGENT_TOOL_REGISTRY` | Реестр доступных агентов |
| `AGENT_TOOL_PERMISSIONS` | Разрешения: кто кого может вызывать |
| `AGENT_TOOL_ENABLED` | Включить/выключить межагентные вызовы |

---

## ➡️ Следующий урок

[🌐 Урок 8: MCP и A2A — как подключить агентов к внешнему миру](lesson_08_mcp_a2a.md)
