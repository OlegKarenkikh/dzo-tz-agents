# REST API — Документация

## Базовый URL

```
http://localhost:8000
```

Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)

## Аутентификация

Все эндпоинты `/api/v1/*` требуют заголовка:

```
X-API-Key: <ваш_секретный_ключ>
```

Ключ задаётся в переменной `API_KEY` файла `.env`.

Публичные эндпоинты (`/health`, `/status`, `/agents`, `/metrics`) не требуют аутентификации.

---

## Эндпоинты — сводная таблица

| Метод | Путь | Авт. | Описание |
|---|---|:---:|---|
| GET | `/health` | — | Статус, uptime, версия, модель |
| GET | `/status` | — | Последние N запусков агентов |
| GET | `/agents` | — | Список агентов с описаниями |
| GET | `/metrics` | — | Prometheus scrape |
| POST | `/api/v1/process/dzo` | ✅ | Обработать заявку ДЗО |
| POST | `/api/v1/process/tz` | ✅ | Обработать ТЗ |
| POST | `/api/v1/process/tender` | ✅ | Парсинг тендерной документации |
| POST | `/api/v1/process/{agent}` | ✅ | Универсальный запуск агента по ID из `/agents` |
| POST | `/api/v1/resolve-agent` | ✅ | Определить ID агента по содержимому |
| POST | `/api/v1/process/auto` | ✅ | Автоопределение типа агента |
| GET | `/api/v1/check-duplicate` | ✅ | Проверить дубликат без запуска агента |
| GET | `/api/v1/jobs` | ✅ | Список заданий (с фильтрацией) |
| GET | `/api/v1/jobs/{job_id}` | ✅ | Статус и результат задания |
| DELETE | `/api/v1/jobs/{job_id}` | ✅ | Удалить задание |
| GET | `/api/v1/history` | ✅ | История обработок (фильтры + пагинация) |
| GET | `/api/v1/stats` | ✅ | Агрегированная статистика |

---

## Публичные эндпоинты

### `GET /health`

Статус сервиса, uptime, версия.

**curl:**
```bash
curl http://localhost:8000/health
```

**Ответ:**
```json
{
    "status": "ok",
    "uptime_sec": 3600,
    "version": "1.2.0",
    "agent_mode": "both",
    "model": "gpt-4o",
    "timestamp": "2026-03-13T11:00:00"
}
```

---

### `GET /status`

Последние N запусков агентов.

**Параметры:** `limit` (int, 1–100, default: 10)

**curl:**
```bash
curl "http://localhost:8000/status?limit=20"
```

---

### `GET /agents`

Список доступных агентов с описаниями.

Публичный контракт ответа: `id`, `name`, `description`, `decisions`.

**curl:**
```bash
curl http://localhost:8000/agents
```

**Ответ:**
```json
{
    "agents": [
        {
            "id": "dzo",
            "name": "Инспектор заявок ДЗО",
            "description": "...",
            "decisions": ["Заявка полная", "Требуется доработка", "Требуется эскалация"]
        },
        {
            "id": "tz",
            "name": "Инспектор технических заданий",
            "description": "...",
            "decisions": ["Соответствует", "Требует доработки", "Не соответствует"]
        },
        {
          "id": "tender",
          "name": "Парсер тендерной документации",
          "description": "...",
          "decisions": ["documents_found", "tool_error"]
        }
    ]
}
```

---

## Эндпоинты /api/v1/*

### `POST /api/v1/process/dzo`

Обработать заявку ДЗО. Запуск асинхронный — возвращает `job_id`.

**Тело запроса:** см. `ProcessRequest` ниже.

**curl:**
```bash
curl -X POST http://localhost:8000/api/v1/process/dzo \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"text": "Заявка на закупку оборудования", "subject": "Закупка серверов"}'
```

**Ответ:**
```json
{
    "duplicate": false,
    "existing_job_id": null,
    "message": "Задание создано",
    "job": {
        "job_id": "550e8400-e29b-41d4-a716-446655440000",
        "status": "pending",
        "agent": "dzo",
        "created_at": "2026-03-13T11:00:00"
    }
}
```

> Если `duplicate: true` — в `existing_job_id` будет UUID существующего задания, `job` будет `null`. Передайте `"force": true` для принудительной переобработки.

---

### `POST /api/v1/process/tz`

Обработать техническое задание. Аналогично `/api/v1/process/dzo`.

---

### `POST /api/v1/process/tender`

Обработать тендерную документацию. Аналогично `/api/v1/process/dzo`.

---

### `POST /api/v1/process/{agent}`

Универсальный запуск агента по его ID из `GET /agents`.

Если агент не зарегистрирован, API вернёт `400`.

**curl:**
```bash
curl -X POST http://localhost:8000/api/v1/process/tender \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"text": "Тендерная документация", "subject": "Проверка"}'
```

---

### `POST /api/v1/resolve-agent`

Определить целевого агента по содержимому запроса.

Использует auto-detect профили из зарегистрированных агентов (`GET /agents`).

**curl:**
```bash
curl -X POST http://localhost:8000/api/v1/resolve-agent \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"text": "Тендерная документация", "subject": "Проверка"}'
```

**Ответ:**
```json
{
  "agent": "tender",
  "matched_keyword": "тендерная документация",
  "method": "keyword-profile",
  "available_agents": ["dzo", "tz", "tender"]
}
```

---

### `POST /api/v1/process/auto`

Автоматическое определение типа агента по содержимому запроса.

**Логика:** используется динамический профиль `auto_detect` зарегистрированных агентов.
Порядок определяется приоритетом (`priority`) в реестре агентов.

**curl:**
```bash
curl -X POST http://localhost:8000/api/v1/process/auto \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"text": "Техническое задание на поставку", "subject": "ТЗ на серверы"}'
```

---

### `GET /api/v1/check-duplicate`

Проверить наличие ранее обработанного задания **без** запуска агента.

**Параметры:**

| Параметр | Тип | Описание |
|---|---|---|
| `agent` | str | ID агента из `GET /agents` |
| `sender` | str | Email отправителя |
| `subject` | str | Тема письма |

**curl:**
```bash
curl -H "X-API-Key: your-secret-key" \
  "http://localhost:8000/api/v1/check-duplicate?agent=dzo&sender=dzo@company.ru&subject=Закупка"
```

**Ответ:**
```json
{ "duplicate": true, "job": { "job_id": "...", "status": "done", "decision": "Заявка полная" } }
```

---

### `GET /api/v1/jobs`

Список всех заданий с опциональной фильтрацией.

**Параметры:** `agent` (ID из `GET /agents`), `status` (`pending`/`running`/`done`/`error`)

**curl:**
```bash
curl -H "X-API-Key: your-secret-key" \
  "http://localhost:8000/api/v1/jobs?agent=dzo&status=done"
```

---

### `GET /api/v1/jobs/{job_id}`

Статус и результат конкретного задания.

**curl:**
```bash
curl -H "X-API-Key: your-secret-key" \
  http://localhost:8000/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000
```

**Ответ (после завершения):**
```json
{
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "done",
    "agent": "dzo",
    "created_at": "2026-03-13T11:00:00",
    "result": {
        "output": "Решение агента: Заявка полная",
        "decision": "Заявка полная",
        "email_html": "<p>Заявка принята...</p>"
    },
    "error": null
}
```

---

### `DELETE /api/v1/jobs/{job_id}`

Удалить задание из хранилища.

**curl:**
```bash
curl -X DELETE -H "X-API-Key: your-secret-key" \
  http://localhost:8000/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000
```

---

### `GET /api/v1/history`

История всех обработок с фильтрацией и пагинацией.

**Параметры:**

| Параметр | Тип | Описание |
|---|---|---|
| `agent` | str | `dzo`, `tz` или `tender` |
| `status` | str | `pending`, `running`, `done`, `error` |
| `decision` | str | Фильтр по тексту решения |
| `date_from` | str | ISO 8601, начало периода |
| `date_to` | str | ISO 8601, конец периода |
| `page` | int | Номер страницы (default: 1) |
| `per_page` | int | Записей на странице (1–500, default: 50) |

**curl:**
```bash
curl -H "X-API-Key: your-secret-key" \
  "http://localhost:8000/api/v1/history?agent=tz&page=1&per_page=20"
```

**Ответ:**
```json
{ "total": 142, "pages": 8, "page": 1, "per_page": 20, "items": [ ... ] }
```

---

### `GET /api/v1/stats`

Агрегированная статистика по всем обработкам.

**curl:**
```bash
curl -H "X-API-Key: your-secret-key" http://localhost:8000/api/v1/stats
```

**Ответ:**
```json
{
    "total": 142,
    "today": 12,
    "approved": 89,
    "rework": 38,
    "errors": 15
}
```

---

## Модели данных

### `ProcessRequest`

| Поле | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `text` | `str` | — | Текст документа |
| `filename` | `str` | — | Имя исходного файла |
| `sender_email` | `str` | — | Email отправителя |
| `subject` | `str` | — | Тема письма |
| `attachments` | `list[AttachmentData]` | — | Вложения в base64 |
| `force` | `bool` | — | `true` — переобработать даже при найденном дубликате |

### `AttachmentData`

| Поле | Тип | Описание |
|---|---|---|
| `filename` | `str` | Имя файла |
| `content_base64` | `str` | Содержимое в base64 |
| `mime_type` | `str` | MIME-тип (например `application/pdf`) |

### `JobResponse`

| Поле | Тип | Описание |
|---|---|---|
| `job_id` | `str` | UUID задания |
| `status` | `str` | `pending`, `running`, `done`, `error` |
| `agent` | `str` | `dzo`, `tz` или `tender` |
| `created_at` | `str` | ISO 8601 timestamp |
| `result` | `dict или null` | Результат (после завершения) |
| `error` | `str или null` | Описание ошибки |

### `result` в `JobResponse`

| Поле | Тип | Описание |
|---|---|---|
| `output` | `str` | Текстовый вывод агента |
| `decision` | `str` | Решение (например «Заявка полная») |
| `email_html` | `str` | HTML-письмо для отправки |
| `request_payload` | `dict` | Исходный payload запроса (для корректной переобработки из истории) |
| `request_payload_preview` | `dict` | Безопасный preview payload без base64-вложений (метаданные файлов) |
| `processing_log` | `dict` | Пошаговый журнал обработки (этапы, tool-вызовы, маршрутизация, итог) |
| `model_error` | `dict` | Техническая причина деградации модели (например `NoToolCalls`) |
| `missing_recommended_tool` | `dict` | Мягкое предупреждение: рекомендуемый tool не вызван (например `analyze_tz_with_agent`) |
| `tz_agent_analysis` | `dict` | Результат делегированного анализа ТЗ |
| `peer_agent_results` | `list[dict]` | Результаты вызовов других агентов |
| `document_list` | `dict` | Структурированный список документов по тендеру |
| `document_list_error` | `dict` | Ошибка построения списка документов |

Примечание по `decision`:
- `tool_calls_missing` — все модели из fallback-цепочки вернули ответ без обязательных tool-вызовов (универсально для любого агента API-пайплайна).

Примечание по `processing_log.events` (stage=`routing`):
- `estimated_input_tokens` — оценка размера входа в токенах.
- `tools_overhead_tokens` — заложенный budget под system/tool schema overhead.
- `model_context_tokens` — карта лимитов контекста по моделям fallback-цепочки.
- `chunking_threshold_tokens` — порог, после которого включается поблочный анализ.

Дополнительные этапы `processing_log.events`:
- `chunking_applied` — документ был преобразован в map-reduce резюме (поля `before_*` / `after_*`).
- `token_limit_compaction` — после `413 TokenLimit` выполнено экстренное сжатие input и повтор на той же модели.
- `postcheck_warning` — мягкое предупреждение о пропуске рекомендуемого tool.

---

## Дедупликация

Система автоматически ищет дубликаты по ключу `(agent, sender_email, subject)`.

- Если найдено завершённое задание — POST `/api/v1/process/*` вернёт `duplicate: true` и `existing_job_id`
- Чтобы проверить без запуска: `GET /api/v1/check-duplicate`
- Чтобы принудительно переобработать: передайте `"force": true` в теле запроса
- Глобальный обход: `FORCE_REPROCESS=true` в `.env` (только для отладки)

---

## Коды ответов HTTP

| Код | Описание |
|---|---|
| `200` | Успешно |
| `401` | Неверный или отсутствующий API-ключ |
| `404` | Задание не найдено |
| `422` | Ошибка валидации входных данных |
| `500` | Внутренняя ошибка сервера |
