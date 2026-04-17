# 🔧 Урок 6: Инструмент — что это и как создать

![Что такое инструмент для LLM](images/lesson_06_what_is_tool.png)

---

## 🤔 Что такое инструмент (tool)?

**Инструмент** — это обычная Python-функция, которую LLM может вызвать самостоятельно.

Модель не выполняет Python-код напрямую — она **описывает вызов** (имя + аргументы),
а фреймворк (LangChain/LangGraph) выполняет реальный вызов и возвращает результат.

Ключевое: LLM выбирает инструмент по его **описанию** (docstring).
Если описание понятное — модель использует инструмент правильно.
Если описание плохое — модель может выбрать не тот инструмент или не вызвать его вовсе.

---

## 📦 Как выглядит инструмент в коде?

Вот реальный инструмент из `agent1_dzo_inspector/tools.py`:

```python
from langchain.tools import tool
from pydantic import BaseModel, Field

class InfoRequestInput(BaseModel):
    dzo_name: str = Field(description="Название ДЗО (компании)")
    missing_fields: list[str] = Field(description="Список отсутствующих полей")

@tool("generate_info_request", args_schema=InfoRequestInput)
def generate_info_request(dzo_name: str, missing_fields: list[str]) -> dict:
    # Используй этот инструмент, когда в заявке отсутствуют обязательные поля
    # и нужно запросить их у отправителя.
    subject = f"Запрос недостающих данных: {dzo_name}"
    body = "<p>Уважаемый партнёр,</p>"
    body += "<p>В вашей заявке не хватает следующих данных:</p><ul>"
    for field in missing_fields:
        body += f"<li>{field}</li>"
    body += "</ul>"
    return {"subject": subject, "email_html": body}
```

Что здесь важно:
- `@tool` — декоратор, превращающий функцию в инструмент
- `args_schema` — схема входных данных (Pydantic)
- **Docstring** — именно его читает LLM, чтобы решить, нужен ли этот инструмент
- Функция возвращает `dict` — результат уходит обратно в LLM

---

## ✅ Практика: создайте свой инструмент

Добавим простой инструмент — счётчик слов в тексте:

```python
from langchain.tools import tool
from pydantic import BaseModel, Field

class WordCountInput(BaseModel):
    text: str = Field(description="Текст для подсчёта слов")

@tool("count_words", args_schema=WordCountInput)
def count_words(text: str) -> dict:
    # Используй, если нужно определить объём документа
    words = len(text.split())
    return {"word_count": words, "text_length": len(text)}
```

Теперь добавьте его в список `tools` при создании агента — и LLM сможет его вызывать!

---

## 🔄 Жизненный цикл вызова инструмента

```
1. LLM получает запрос пользователя
2. LLM читает описания всех доступных инструментов
3. LLM решает: "Мне нужен generate_info_request"
4. LLM формирует JSON: {"dzo_name": "ООО Ромашка", "missing_fields": ["адрес"]}
5. LangGraph вызывает реальную функцию с этими аргументами
6. Функция выполняется и возвращает результат
7. Результат возвращается в LLM как "наблюдение"
8. LLM продолжает рассуждение
```

---

## 📍 Что запомнить

| Понятие | Значение |
|---|---|
| `@tool` | Декоратор LangChain для создания инструмента |
| `args_schema` | Pydantic-модель с описанием параметров |
| Docstring | Описание инструмента — главное для LLM |
| `BaseModel` | Базовый класс Pydantic для схем данных |
| `Field(description=...)` | Описание параметра — LLM читает его |

---

## ➡️ Следующий урок

[🤝 Урок 7: Агент как инструмент — как ДЗО вызывает ТЗ](lesson_07_agent_as_tool.md)
