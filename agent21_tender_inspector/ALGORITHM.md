# Алгоритм Agent 21 — Парсер тендерной документации (`agent21_tender_inspector`)

> **Версия:** 1.0.0 · **Дата:** 2026-04-10  
> **Файлы модуля:** `agent.py`, `runner.py`, `tools.py`

---

## Назначение

Агент `agent21_tender_inspector` анализирует тендерную документацию (PDF / DOCX / XLSX) и извлекает **полный перечень документов**, которые участник закупки обязан предоставить в составе заявки.

Агент работает **как вспомогательный (peer agent)**: `agent1_dzo_inspector` может вызывать его через `invoke_peer_agent`, чтобы получить перечень документов для конкретной закупки.

---

## Архитектура

```
runner.py (process_single_document / process_tender_documents)
    │
    ├─ Загрузка файла (локально / HTTP(S))
    ├─ Извлечение текста: shared.file_extractor.extract_text_from_attachment
    ├─ [Опционально] Поблочный анализ: shared.chunked_analysis.analyze_document_in_chunks
    │       └─ если estimate_tokens(text) > threshold → разбить на чанки → собрать summary
    │
    └─ agent.py → create_react_agent (LangGraph ReAct)
            │
            ├─ Инструменты:
            │   ├─ generate_document_list  (tools.py)
            │   └─ invoke_peer_agent       (tools.py, из shared.agent_tooling)
            │
            └─ SYSTEM_PROMPT (встроенный в agent.py)
```

---

## Пошаговый алгоритм

### Шаг 0 — Входные данные

| Параметр        | Откуда берётся                                   |
|-----------------|--------------------------------------------------|
| `source`        | Путь к файлу (`.pdf`, `.docx`, `.xlsx`, `.xls`) или HTTP(S)-URL |
| `output_dir`    | Опционально, для сохранения результата `.json`   |
| `TENDER_DOCS_DIR` | Env-переменная; используется при пакетном режиме без явного `sources` |

---

### Шаг 1 — Загрузка и валидация файла (`runner.py`)

1. Определить тип источника (`_is_url` / локальный путь).
2. **URL:** скачать через `httpx.stream`, проверить ≤ 50 МБ, определить имя файла из `Content-Disposition` или URL.
3. **Локальный файл:** прочитать, проверить размер ≤ 50 МБ.
4. Проверить расширение: `{.pdf, .docx, .xlsx, .xls}` — отклонить прочие.
5. **Дедупликация:** `db.find_duplicate_job("tender", "", subject)` — если уже обработан и `FORCE_REPROCESS=False`, вернуть кешированный результат.
6. Создать запись в БД: `db.create_job("tender", sender="", subject=dedup_subject)`.

---

### Шаг 2 — Извлечение текста (`shared/file_extractor.py`)

```
extract_text_from_attachment(attachment_dict)
    ├─ PDF   → pdfminer / pypdf (текстовый слой)
    ├─ DOCX  → python-docx → base64 → LLM-vision (если нет текста)
    ├─ XLSX  → openpyxl → построчный текст
    └─ OCR fallback (если текстовый слой пуст)
```

Результат: строка с содержимым документа, переданная в агент как `chat_input`.

---

### Шаг 3 — Оценка размера и поблочный анализ (опционально)

```
estimate_tokens(chat_input)
    └─ если > threshold (зависит от контекстного окна модели):
        └─ analyze_document_in_chunks(chat_input, api_key, best_model, "tender")
               ├─ разбить на чанки с перекрытием
               ├─ по каждому чанку: LLM → промежуточное резюме
               └─ собрать финальное summary (≪ исходного текста)
```

Порог `threshold` рассчитывается динамически:
```python
threshold = max(1, (min(best_ctx, model_ctx) - TOOLS_TOKEN_OVERHEAD) // 2)
```
где `_TOOLS_TOKEN_OVERHEAD = 3000` — запас на системный промпт и инструменты.

> **Кеширование:** конфигурация `_fallback_chain_cache` потокобезопасна (double-checked locking через `threading.Lock`).

---

### Шаг 4 — Запуск ReAct-агента (`agent.py`)

Агент создаётся через `langgraph.prebuilt.create_react_agent`:

```python
graph_agent = create_react_agent(
    model=llm,              # build_llm(temperature=0.1)
    tools=[invoke_peer_agent, generate_document_list],
    prompt=SYSTEM_PROMPT,
)
```

**Параметры LLM:** `temperature=0.1` — низкая температура для детерминированного извлечения.

#### Логика ReAct-цикла (SYSTEM_PROMPT → инструкции агенту)

| Шаг | Действие агента |
|-----|-----------------|
| 1 | Прочитать всю документацию; учесть OCR-артефакты |
| 2 | Найти разделы: «Состав заявки», «Квалификационные требования», «Требования к участнику» |
| 3 | Выявить **прямые** требования — явно перечисленные документы |
| 4 | Выявить **косвенные** требования — лицензии, СРО, страховки, вытекающие из условий допуска |
| 5 | Вызвать `generate_document_list` со структурированным JSON |
| 6 | При необходимости вызвать `invoke_peer_agent` для смежной проверки |

**Критическое ограничение:** агенту запрещено передавать оригинальный текст в аргументы инструментов. В `query` → только структурированный JSON-результат анализа.

---

### Шаг 5 — Инструмент `generate_document_list` (`tools.py`)

Принимает структурированный JSON:

```json
{
  "procurement_subject": "Строительство объекта",
  "documents": [
    {
      "name": "Копия лицензии на строительную деятельность",
      "type": "лицензия",
      "mandatory": true,
      "section_reference": "Раздел 3.2, п. 3.2.1",
      "requirements": "Нотариально заверенная копия, действующая на дату подачи",
      "basis": "Прямое требование"
    }
  ]
}
```

**Поля каждого документа:**

| Поле               | Тип     | Описание |
|--------------------|---------|----------|
| `name`             | string  | Точное название документа |
| `type`             | string  | лицензия / свидетельство / копия / оригинал / форма / декларация / гарантия / выписка / справка / сертификат / договор / протокол / приказ / устав / иное |
| `mandatory`        | boolean | `true` = обязательный; `false` = условный |
| `section_reference`| string  | Ссылка на раздел/пункт документации |
| `requirements`     | string  | Требования к содержанию и оформлению |
| `basis`            | string  | Прямое требование / Вытекает из квалификационных требований / Вытекает из предмета закупки |

Инструмент возвращает объект с полем `summary`:
```json
{
  "status": "success",
  "documents": [...],
  "summary": {
    "total": 12,
    "mandatory": 9,
    "conditional": 3
  }
}
```

---

### Шаг 6 — Постобработка результата (`runner.py`)

```
_extract_document_list_from_steps(intermediate_steps)
    └─ ищет вызов generate_document_list в steps
           ├─ найден  → использовать как document_list
           └─ не найден → fallback: raw_output из текстового ответа агента
```

Добавление метаданных в результат:
- `source_document` — имя исходного файла
- `timestamp` — ISO-8601 UTC

---

### Шаг 7 — Сохранение результата

1. **Файл JSON:** `_build_output_path` → `{stem}_{ext}_{hash8}.json` рядом с исходником (или в `TENDER_OUTPUT_DIR`).
2. **База данных:** `db.update_job(job_id, status="done"|"error", decision=..., result=..., trace=...)`.
3. **Метрики (Prometheus):** `EMAILS_PROCESSED.labels(agent="tender").inc()` или `EMAILS_ERRORS`.
4. **Telegram-уведомление** при критической ошибке.

---

## Пакетный режим (`process_tender_documents`)

```
process_tender_documents(sources=None, output_dir="", save_to_file=True)
    ├─ sources=None → сканировать TENDER_DOCS_DIR на файлы {pdf,docx,xlsx,xls}
    └─ для каждого source → process_single_document(source, ...)
           ├─ успех → append result
           └─ ошибка → append {"source_document": ..., "error": ...}  (не прерывает пакет)
```

---

## Схема взаимодействия с другими агентами

```
agent1_dzo_inspector
        │
        │ invoke_peer_agent("tender", text)
        ▼
agent21_tender_inspector  ←── работает как peer / вызывается напрямую через runner.py
        │
        │ [при необходимости] invoke_peer_agent("tz", text)
        ▼
agent2_tz_inspector
```

---

## Конфигурация (env-переменные)

| Переменная          | По умолчанию   | Описание |
|---------------------|----------------|----------|
| `TENDER_DOCS_DIR`   | `tender_docs`  | Папка для пакетного сканирования |
| `TENDER_OUTPUT_DIR` | `""`           | Папка для результатов JSON |
| `LLM_BACKEND`       | —              | `openai` / `github_models` |
| `MODEL_NAME`        | —              | Имя модели LLM |
| `FORCE_REPROCESS`   | `false`        | Игнорировать дедупликацию |
| `OPENAI_API_KEY`    | —              | API-ключ OpenAI |
| `GITHUB_TOKEN`      | —              | Токен GitHub Models |

---

## Ограничения и известные особенности

1. **Нет собственного email-polling**: агент21 обрабатывает только файлы, переданные через `runner.py`. Email-интеграция — ответственность agent1.
2. **OCR не встроен**: качество извлечения текста из отсканированных PDF зависит от `shared/document_parser.py`.
3. **Косвенные требования** — нечёткое понятие; агент может пропустить специфичные отраслевые требования.
4. **Лимит размера файла:** 50 МБ. Файлы большего размера — ошибка.
5. **Нет runner.py-аналога в agent3** — агент3 (collector) имеет собственную логику обработки email без общего base-runner.
