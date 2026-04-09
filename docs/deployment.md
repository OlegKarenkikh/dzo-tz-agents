# Руководство по развёртыванию

## Требования

- Python 3.11+
- Docker и Docker Compose (для контейнерного деплоя)
- Доступ к IMAP/SMTP серверу
- Доступ к одному из LLM backend: OpenAI API key, GitHub token или локальный OpenAI-compatible endpoint

---

## Переменные окружения

Скопируйте `.env.example` в `.env` и заполните значения:

```bash
cp .env.example .env
```

### Полный список переменных

| Переменная | Обязательная | Описание | Пример |
|------------|:---:|---------|--------|
| `OPENAI_API_KEY` | ➞ | Ключ OpenAI API | `sk-...` |
| `GITHUB_TOKEN` | ➞ | Токен GitHub Models | `github_pat_...` |
| `API_KEY` | ✅ | Секретный ключ для REST API | `strong-random-secret` |
| `AGENT_MODE` | | Режим запуска: `dzo`, `tz`, `tender`, `both` | `both` |
| `MODEL_NAME` | | Модель OpenAI | `gpt-4o` |
| `LLM_BACKEND` | | Бэкенд LLM | `openai` |
| `POLL_INTERVAL_SEC` | | Интервал опроса почты (сек) | `300` |
| `RUN_ON_START` | | Немедленный запуск poller при старте | `true` |
| `MANAGER_EMAIL` | ✅ | Email для эскалаций | `manager@company.ru` |
| `DZO_IMAP_HOST` | ✅ | IMAP-сервер агента ДЗО | `mail.company.ru` |
| `DZO_IMAP_USER` | ✅ | Логин IMAP агента ДЗО | `dzo@company.ru` |
| `DZO_IMAP_PASSWORD` | ✅ | Пароль IMAP агента ДЗО | `secret` |
| `DZO_SMTP_FROM` | ✅ | Email отправителя ДЗО | `dzo@company.ru` |
| `TZ_IMAP_HOST` | ✅ | IMAP-сервер агента ТЗ | `mail.company.ru` |
| `TZ_IMAP_USER` | ✅ | Логин IMAP агента ТЗ | `tz@company.ru` |
| `TZ_IMAP_PASSWORD` | ✅ | Пароль IMAP агента ТЗ | `secret` |
| `TZ_SMTP_FROM` | ✅ | Email отправителя ТЗ | `tz@company.ru` |
| `SMTP_HOST` | ✅ | SMTP-сервер | `smtp.company.ru` |
| `SMTP_PORT` | | SMTP-порт | `587` |
| `SMTP_USER` | ✅ | Логин SMTP | `user@company.ru` |
| `SMTP_PASSWORD` | ✅ | Пароль SMTP | `secret` |
| `TELEGRAM_BOT_TOKEN` | | Токен Telegram-бота | `123456:ABC...` |
| `TELEGRAM_CHAT_ID` | | ID чата Telegram | `-100123456789` |
| `UI_API_URL` | | URL REST API для UI | `http://localhost:8000` |
| `UI_API_KEY` | | API-ключ для UI | `strong-random-secret` |
| `AGENT_TOOL_ENABLED` | | Разрешить межагентные вызовы | `true` |
| `AGENT_TOOL_REGISTRY` | | JSON-реестр фабрик агентов | `{}` |
| `AGENT_TOOL_PERMISSIONS` | | JSON-матрица маршрутов | `{"*":["*"]}` |

---

## Локальный запуск

### 1. Установка зависимостей

```bash
git clone https://github.com/OlegKarenkikh/dzo-tz-agents.git
cd dzo-tz-agents
make install
# эквивалентно: pip install -e ".[ui,dev]"
```

Образ Docker по-прежнему собирается из `requirements.txt` (см. `Dockerfile`); для разработки и CI используется editable-установка с extras, как в README и `AGENTS.md`.

### 2. Настройка окружения

```bash
cp .env.example .env
# Отредактируйте .env, заполнив все значения
```

### 3. Запуск REST API

```bash
uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload
# или через Makefile:
make api
```

API будет доступен на http://localhost:8000  
Swagger UI: http://localhost:8000/docs

### 4. Запуск Web UI

```bash
streamlit run ui/app.py --server.port 8501
# или через Makefile:
make ui
```

UI будет доступен на http://localhost:8501

### 5. Запуск агентов-поллеров

```bash
python main.py
# или отдельно:
make dzo-only   # только агент ДЗО
make tz-only    # только агент ТЗ
make tender-only # только агент Тендер
```

### 6. Запуск API и UI одновременно

```bash
make api-ui
```

---

## Docker

### Сборка образа

```bash
docker build -t dzo-tz-agents .
```

### Запуск контейнеров

```bash
docker-compose up -d
```

Сервисы:
- `agent-dzo` — агент-поллер ДЗО
- `agent-tz` — агент-поллер ТЗ
- `agent-tender` — агент-парсер тендерной документации
- `api` — REST API на порту 8000
- `ui` — Streamlit UI на порту 8501

### Просмотр логов

```bash
docker-compose logs -f api
docker-compose logs -f ui
```

### Остановка

```bash
docker-compose down
```

---

## Nginx Reverse Proxy

Пример конфигурации `/etc/nginx/sites-available/dzo-agents`:

```nginx
server {
    listen 80;
    server_name agents.company.ru;

    # Редирект на HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name agents.company.ru;

    ssl_certificate     /etc/ssl/certs/agents.company.ru.crt;
    ssl_certificate_key /etc/ssl/private/agents.company.ru.key;

    # REST API
    location /api/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    location ~ ^/(health|status|agents|docs|redoc|openapi.json) {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
    }

    # Streamlit UI
    location / {
        proxy_pass         http://127.0.0.1:8501;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
    }
}
```

Активация:
```bash
ln -s /etc/nginx/sites-available/dzo-agents /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

---

## systemd Unit

### REST API — `/etc/systemd/system/dzo-api.service`

```ini
[Unit]
Description=DZO/TZ Agents REST API
After=network.target

[Service]
Type=simple
User=appuser
WorkingDirectory=/opt/dzo-tz-agents
EnvironmentFile=/opt/dzo-tz-agents/.env
ExecStart=/opt/dzo-tz-agents/venv/bin/uvicorn api.app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Web UI — `/etc/systemd/system/dzo-ui.service`

```ini
[Unit]
Description=DZO/TZ Agents Web UI
After=dzo-api.service

[Service]
Type=simple
User=appuser
WorkingDirectory=/opt/dzo-tz-agents
EnvironmentFile=/opt/dzo-tz-agents/.env
ExecStart=/opt/dzo-tz-agents/venv/bin/streamlit run ui/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Агенты-поллеры — `/etc/systemd/system/dzo-agents.service`

```ini
[Unit]
Description=DZO/TZ Email Polling Agents
After=network.target

[Service]
Type=simple
User=appuser
WorkingDirectory=/opt/dzo-tz-agents
EnvironmentFile=/opt/dzo-tz-agents/.env
ExecStart=/opt/dzo-tz-agents/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Активация:
```bash
systemctl daemon-reload
systemctl enable --now dzo-api dzo-ui dzo-agents
systemctl status dzo-api
```

---

## Запуск тестов

```bash
make test
# или вручную:
OPENAI_API_KEY=sk-test pytest tests/ -v --cov=. --cov-report=term-missing
```
