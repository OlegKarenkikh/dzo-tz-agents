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

Публичные эндпоинты (`/health`, `/status`, `/agents`) не требуют аутентификации.

---

## Эндпоинты

### `GET /health`

Статус сервиса, uptime, версия.

**Ответ:**
```json
{
    "status": "ok",
    "uptime_sec": 3600,
    "version": "1.0.0",
    "agent_mode": "both",
    "model": "gpt-4o",
    "timestamp": "2024-01-01T12:00:00"
}
```

**curl:**
```bash
curl http://localhost:8000/health
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
        }
    ]
}
```

---

### `POST /api/v1/process/dzo`

Обработать заявку ДЗО. Запуск асинхронный — возвращает `job_id`.

**Тело запроса:**
```json
{
    "text": "Заявка на закупку оборудования. Инициатор: Иванов И.И.",
    "filename": "zayavka.docx",
    "sender_email": "dzo@company.ru",
    "subject": "Заявка на закупку серверов",
    "attachments": [
        {
            "filename": "tz.docx",
            "content_base64": "base64-encoded-content",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        }
    ]
}
```

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
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "pending",
    "agent": "dzo",
    "created_at": "2024-01-01T12:00:00",
    "result": null,
    "error": null
}
```

---

### `POST /api/v1/process/tz`

Обработать техническое задание.

**curl:**
```bash
curl -X POST http://localhost:8000/api/v1/process/tz \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"text": "Техническое задание на поставку серверов", "subject": "ТЗ"}'
```

---

### `POST /api/v1/process/auto`

Автоматическое определение типа агента (ДЗО или ТЗ) по содержимому запроса.

**Логика определения:** если в тексте/теме/имени файла есть слова «техническое задание», «тз», «tor», «техзадание» — используется агент ТЗ. В остальных случаях — агент ДЗО.

**curl:**
```bash
curl -X POST http://localhost:8000/api/v1/process/auto \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"text": "Техническое задание на поставку", "subject": "ТЗ на серверы"}'
```

---

### `GET /api/v1/jobs`

Список всех заданий с опциональной фильтрацией.

**Параметры:**
- `agent`: `dzo` | `tz`
- `status`: `pending` | `running` | `done` | `error`

**curl:**
```bash
# Все задания
curl -H "X-API-Key: your-secret-key" http://localhost:8000/api/v1/jobs

# Только завершённые задания ДЗО
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
    "created_at": "2024-01-01T12:00:00",
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

Удалить задание из истории.

**curl:**
```bash
curl -X DELETE -H "X-API-Key: your-secret-key" \
  http://localhost:8000/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000
```

---

### `GET /api/v1/history`

История всех обработок с фильтрацией.

**Параметры:**
- `agent`: `dzo` | `tz`
- `status`: `pending` | `running` | `done` | `error`
- `limit`: int (1–500, default: 50)

**curl:**
```bash
curl -H "X-API-Key: your-secret-key" \
  "http://localhost:8000/api/v1/history?agent=tz&limit=20"
```

---

## Модели данных

### `ProcessRequest`

| Поле | Тип | Описание |
|------|-----|----------|
| `text` | `str` | Текст документа (если уже извлечён) |
| `filename` | `str` | Имя исходного файла |
| `sender_email` | `str` | Email отправителя |
| `subject` | `str` | Тема письма |
| `attachments` | `list[AttachmentData]` | Вложения в base64 |

### `AttachmentData`

| Поле | Тип | Описание |
|------|-----|----------|
| `filename` | `str` | Имя файла |
| `content_base64` | `str` | Содержимое в base64 |
| `mime_type` | `str` | MIME-тип (например `application/pdf`) |

### `JobResponse`

| Поле | Тип | Описание |
|------|-----|----------|
| `job_id` | `str` | UUID задания |
| `status` | `str` | `pending` \| `running` \| `done` \| `error` |
| `agent` | `str` | `dzo` \| `tz` |
| `created_at` | `str` | ISO 8601 timestamp |
| `result` | `dict \| null` | Результат (после завершения) |
| `error` | `str \| null` | Описание ошибки |

### `result` в `JobResponse`

| Поле | Тип | Описание |
|------|-----|----------|
| `output` | `str` | Текстовый вывод агента |
| `decision` | `str` | Решение (например "Заявка полная") |
| `email_html` | `str` | HTML-письмо для отправки |

---

## Коды ответов HTTP

| Код | Описание |
|-----|----------|
| `200` | Успешно |
| `401` | Неверный или отсутствующий API-ключ |
| `404` | Задание не найдено |
| `422` | Ошибка валидации входных данных |
| `500` | Внутренняя ошибка сервера |
