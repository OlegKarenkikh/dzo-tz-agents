# 🧠 Урок 5: LLM — мозг агента

![LLM с инструментами](images/lesson_05_llm_tools.png)

---

## 🤔 Что такое LLM?

**LLM** (Large Language Model, большая языковая модель) — это нейросеть, обученная на огромном количестве текстов.
Она умеет читать текст, понимать контекст и генерировать ответы.

Примеры LLM:
- **GPT-4o** (OpenAI) — используется в нашем проекте
- **Claude** (Anthropic)
- **Qwen** (Alibaba) — поддерживается как альтернатива

В проекте `dzo-tz-agents` модель создаётся в `shared/llm.py`:

```python
from shared.llm import build_llm

llm = build_llm(temperature=0.0)
# temperature=0.0 — модель даёт детерминированные ответы (без «фантазии»)
```

---

## 🔄 Как LLM работает в цикле ReAct?

Агенты проекта используют паттерн **ReAct** (Reason + Act):

```
1. Думать (Reason)  → модель анализирует задачу
2. Действовать (Act) → вызывает инструмент
3. Наблюдать (Observe) → получает результат инструмента
4. Повторить         → пока задача не решена
```

Пример ReAct-цикла для Агента ДЗО:

```
Мысль: Нужно проверить наличие ТЗ в письме.
Действие: analyze_tz_with_agent(tz_text="...")
Наблюдение: {"overall_status": "Соответствует", ...}
Мысль: ТЗ в порядке. Проверяю реквизиты...
Действие: generate_validation_report(decision="Заявка полная", ...)
Наблюдение: {"stats": {"required_ok": 5}, ...}
Мысль: Всё заполнено. Формирую форму Тезис.
Действие: generate_tezis_form(...)
Финальный ответ: Заявка принята.
```

---

## 🏗️ Как создаётся агент в коде?

```python
from langgraph.prebuilt import create_react_agent
from shared.llm import build_llm
from agent1_dzo_inspector.tools import generate_validation_report, analyze_tz_with_agent

llm = build_llm(temperature=0.0)

tools = [
    generate_validation_report,
    analyze_tz_with_agent,
    # ... другие инструменты
]

# Создаём ReAct-агент: модель + инструменты + системный промпт
agent = create_react_agent(
    model=llm,
    tools=tools,
    prompt="Ты — инспектор заявок ДЗО..."
)
```

---

## 📍 Что запомнить

| Понятие | Значение |
|---|---|
| LLM | Большая языковая модель (GPT-4o, Claude, Qwen) |
| ReAct | Паттерн: думать → действовать → наблюдать |
| `temperature=0.0` | Детерминированные ответы без «творчества» |
| `create_react_agent` | Функция LangGraph для создания агента |
| Системный промпт | Инструкции для модели: кто она и что делает |

---

## ➡️ Следующий урок

[🔧 Урок 6: Инструмент — как его создать](lesson_06_what_is_tool.md)
