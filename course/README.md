# 📚 Курс: DZO/TZ Agents для новичков

Пошаговый курс по проекту **DZO/TZ Agents** — от первого запуска до понимания архитектуры агентов и промптов.

> 💡 Все незнакомые слова — в [Глоссарии](glossary.md)

---

## Уроки

### 🚀 Часть 0: Подготовка (если вы новичок)

| № | Тема | Файл и иллюстрации |
|---|------|--------------------|
| 0 | 🖥️ Терминал и Git — с чего начать | [lesson_00_terminal.md](lesson_00_terminal.md) · `lesson_00_terminal.jpg`, `lesson_01_git.jpg` |

### 🧱 Часть 1: Основы

| № | Тема | Иллюстрации |
|---|------|------------|
| 1 | 🖥️ Изолированное окружение (venv) | `lesson_01_venv.jpg`, `lesson_01_git.jpg` |
| 2 | 🐛 Баг — что это и как искать | `lesson_02_bug.jpg` |
| 3 | 🌐 curl — разговариваем с агентом | `lesson_03_http.jpg` |
| 4 | 🔑 Токен — ваш ключ к агентам | `lesson_04_token.jpg` |

👉 Файлы: [lesson_01](lesson_01_venv.md) · [lesson_02](lesson_02_bug.md) · [lesson_03](lesson_03_curl.md) · [lesson_04](lesson_04_token.md)

### 🤖 Часть 2: Агенты и инструменты

| № | Тема | Иллюстрации |
|---|------|------------|
| 5 | 🧠 LLM — мозг агента, паттерн ReAct | `lesson_05_llm_tools.jpg`, `lesson_05_temperature.jpg` |
| 6 | 🔧 Инструмент — что это и как создать | `lesson_06_what_is_tool.jpg`, `lesson_06_docstring.jpg` |
| 7 | 🤝 Агент как инструмент — межагентные вызовы | `lesson_07_agent_as_tool.jpg` |
| 8 | 🌐 MCP и A2A — интеграция с внешним миром | `lesson_08_mcp_a2a.jpg` |

👉 Файлы: [lesson_05](lesson_05_llm.md) · [lesson_06](lesson_06_what_is_tool.md) · [lesson_07](lesson_07_agent_as_tool.md) · [lesson_08](lesson_08_mcp_a2a.md)

### 🔬 Часть 3: Агенты проекта

| № | Тема | Иллюстрации |
|---|------|------------|
| 9 | 🤖 Агент ДЗО — инспектор заявок | `lesson_09_agent_dzo.jpg` |
| 10 | 📄 Агент ТЗ — инспектор технических заданий | `lesson_10_agent_tz.jpg` |
| 11 | 📊 Агент Тендер и Collector | `lesson_11_agents_tender_collector.jpg`, `lesson_14_agent21_tender.jpg`, `lesson_15_agent3_collector.jpg` |

👉 Файлы: [lesson_09](lesson_09_agent_dzo.md) · [lesson_10](lesson_10_agent_tz.md) · [lesson_11](lesson_11_agents_tender_collector.md)

### 🧬 Часть 4: Промпты и качество

| № | Тема | Иллюстрации |
|---|------|------------|
| 12 | 📝 Промпты — анатомия и правила | `lesson_12_prompt_dzo.jpg` |
| 13 | 🛡️ Безопасность LLM и защита промптов | `lesson_13_llm_protection.jpg`, `lesson_13_defense_levels.jpg` |
| 14 | 🤝 Межагентные вызовы: peer и Тендер | `lesson_14_peer_call.jpg`, `lesson_14_tender_lifecycle.jpg` |
| 15 | 🔍 Агент Collector: сбор и проверка ИНН | `lesson_15_inn_check.jpg` |
| 16 | ✍️ Шаблоны промптов и версионирование | `lesson_16_prompt_template.jpg`, `lesson_16_versioning.jpg`, `lesson_16_7sections.jpg` |

👉 Файлы: [lesson_12](lesson_12_prompts.md) · [lesson_13](lesson_13.md) · [lesson_14](lesson_14.md) · [lesson_15](lesson_15.md) · [lesson_16](lesson_16.md)

### 🧪 Часть 5: Тестирование и CI/CD

| № | Тема | Иллюстрации |
|---|------|------------|
| 17 | 🧪 Тестирование агентов: unit, mock, e2e | `lesson_17_test_pyramid.jpg`, `lesson_17_mock_vs_real.jpg`, `lesson_17_pytest_markers.jpg` |
| 18 | 🚀 CI/CD: GitHub Actions и деплой | `lesson_18_ci_pipeline.jpg`, `lesson_18_ci_jobs.jpg`, `lesson_18_deploy_flow.jpg` |

👉 Файлы: [lesson_17](lesson_17_testing.md) · [lesson_18](lesson_18_ci.md)

### 🛠️ Часть 6: Навыки агента

| № | Тема | Иллюстрации |
|---|------|------------|
| 19 | 🔧 Навыки агента — инструменты, схемы и docstring | `lesson_19_tool_anatomy.jpg`, `lesson_19_tools_registry.jpg`, `lesson_19_docstring_rules.jpg` |
| 20 | [Страховые тендеры: лицензия ЦБ РФ и CBR Post-Check](lesson_20_insurance_cbr.md) | Закон 4015-1, False-Positive, CBR post-check в pipeline |

👉 Файл: [lesson_19](lesson_19_skills.md)

---

## 📖 Справочник

- [Глоссарий всех терминов](glossary.md) — ДЗО, ТЗ, НМЦ, СРО, IMAP, LLM и другие · `glossary_terms.jpg`
- [Все иллюстрации курса](images/) — картинки курса в едином стиле

---

## Для кого этот курс?

- Вы первый раз открываете терминал
- Вы хотите понять, что такое LLM, агенты, инструменты и промпты
- Вы хотите запустить агентов ДЗО/ТЗ и не знаете, с чего начать

## Как учиться?

1. Читайте уроки по порядку — каждый следующий опирается на предыдущий.
2. Выполняйте команды прямо в терминале после каждого раздела.
3. Встретили незнакомое слово — загляните в [Глоссарий](glossary.md).
4. Если что-то не работает — в [Уроке 2](lesson_02_bug.md) есть алгоритм отладки.

> 💡 **Совет:** открывайте [README.md](../README.md) проекта рядом с уроком — там быстрый старт.
