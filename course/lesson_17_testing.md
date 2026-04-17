# Урок 17 — Тестирование агентов: от unit до реальной LLM

## Зачем тестировать агентов?

Агент — это не просто функция. Он вызывает LLM, запускает инструменты, работает с базой данных.
Без тестов любое изменение промпта или кода может сломать всю цепочку — и вы узнаете об этом только в продакшне.

---

## Три уровня тестирования

В проекте `dzo-tz-agents` используется **пирамида тестирования**:

![Пирамида тестирования](images/lesson_17_test_pyramid.png)

| Уровень | Файлы | Когда запускать |
|---------|-------|----------------|
| **Unit** | ~35 файлов `test_*.py` | При каждом push — автоматически в CI |
| **Integration** | `test_integration.py`, `test_api.py` | После unit, с запущенным сервером |
| **E2E** | `test_e2e.py`, `test_real_*.py` | Вручную, с реальным API-ключом |

---

## Mock LLM vs Реальная LLM

Большинство тестов запускаются **без реального вызова LLM**.
Вместо этого `conftest.py` подставляет заглушку — это быстро, бесплатно, детерминировано.

![Mock vs Real LLM](images/lesson_17_mock_vs_real.png)

### Как работает mock в conftest.py

```python
# tests/conftest.py — выполняется до всех тестов
def _fake_build_llm(*args, **kwargs):
    llm = MagicMock()
    llm.model_name = "gpt-mock"
    return llm

import shared.llm as _shared_llm
_shared_llm.build_llm = _fake_build_llm  # патчим до импорта агентов
```

### Когда нужна реальная LLM

```bash
# E2E через OpenAI
OPENAI_API_KEY=sk-ваш-ключ LLM_BACKEND=openai pytest tests/test_e2e.py -m e2e -v

# E2E через GitHub Models (бесплатно с GITHUB_TOKEN)
GITHUB_TOKEN=ghp_токен LLM_BACKEND=github_models pytest tests/test_e2e.py -m e2e -v
```

E2E-тесты используют **минимальный input** (7–8 строк) — экономия токенов.

---

## Маркеры pytest

![Маркеры pytest](images/lesson_17_pytest_markers.png)

```python
@pytest.mark.e2e
def test_full_dzo_pipeline():
    ...
```

```bash
pytest tests/ -v                          # только unit
pytest tests/ -m integration -v          # только integration
LLM_BACKEND=openai pytest -m e2e -v      # e2e с реальной LLM
pytest tests/ -m "not slow" -v           # всё кроме медленных
```

---

## Запуск тестов локально

```bash
make api         # убеждаемся что API запущен
make test        # pytest tests/ -v --tb=short --cov=. --cov-report=term-missing

# Тест конкретного агента с отладкой:
make test-agent-dzo
# AGENT_DEBUG=1 python test_agent_local.py dzo "Заявка..."
```

Вывод при `AGENT_DEBUG=1`:
```
[DEBUG] 🔧 generate_validation_report вызван
[INFO]  ✅ generate_validation_report: отчёт готов (decision=Заявка полная)
[DEBUG] 🔧 generate_tezis_form вызван
[INFO]  ✅ generate_tezis_form: HTML-форма готова
```

---

## Что покрывает `tests/`

```
tests/
├── conftest.py                     # Mock-и — работают автоматически
├── test_agent_tooling.py           # Инструменты агентов
├── test_api.py                     # HTTP-эндпоинты
├── test_collector.py               # Сборщик ответов тендера
├── test_e2e.py                     # E2E с реальной LLM (opt-in)
├── test_llm.py                     # Фабрика LLM, приоритет ключей
├── test_mcp_server.py              # MCP-сервер
├── test_real_procurement_docs.py   # Реальные закупочные документы
├── test_security.py                # Безопасность API
├── test_tools_dzo.py               # Инструменты агента ДЗО
└── ...
```

> **Совет:** Начните с `test_tools_dzo.py` — короткий, понятный, показывает
> как тестировать отдельный `@tool` без запуска всего агента.
