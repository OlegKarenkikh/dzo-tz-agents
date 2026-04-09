# Руководство: добавление нового агента (портирование с n8n)

Документ описывает полный путь портирования n8n-сценария в Python-агент,
включая архитектуру, готовые промпты и тесты.

---

## 1. Маппинг n8n → Python

| n8n-нода | Python-эквивалент | Куда поместить |
|---|---|---|
| `emailReadImap` | `imaplib.IMAP4_SSL` | `runner.py` → `_poll_once()` |
| `extractFromFile (pdf/docx/xlsx)` | `pdfplumber` / `python-docx` / `openpyxl` | `runner.py` → `_extract_text()` |
| HTTP → GPT-4o Vision (OCR) | `openai.chat.completions.create` | `runner.py` → `_ocr_image()` |
| `@n8n/langchain.agent` | `langgraph.prebuilt.create_react_agent` | `agent.py` → `create_<name>_agent()` |
| `memoryBufferWindow (k=20)` | обычно не требуется, агент stateless | `agent.py` |
| `toolCode` (inline JS) | `@tool`-декоратор LangChain | `tools.py` |
| `switch` / `if` | Python `if/elif` | `runner.py` → `_process_email()` |
| `emailSend` | `smtplib.SMTP` | `runner.py` → `_send_reply()` |
| System Message (Chat node) | `SYSTEM_PROMPT` строка | `agent.py` |
| Чек-лист в System Message | Те же чек-листы в `SYSTEM_PROMPT` | `agent.py` |
| Webhook / Schedule trigger | `schedule.every(N).seconds.do(...)` | `runner.py` → `run_forever()` |

---

## 2. Структура пакета

Создайте папку `agent3_<name>_inspector/` с трёмя файлами и `__init__.py`:

```
agent3_<name>_inspector/
    __init__.py       — экспорт run_forever, process_text
    agent.py          — SYSTEM_PROMPT + create_<name>_agent()
    tools.py          — @tool функции
    runner.py         — IMAP-петля + отправка ответов
```

> **Правило:** номер 3, 4, 5... сохраняет порядок в `docker-compose.yml` и naming-convention модулей.
>
> **Важно для межагентных вызовов:** соблюдайте naming-convention
> `agentN_<id>_inspector` и фабрику `create_<id>_agent` в `agent.py`.
> Тогда агент автоматически попадёт в межагентный реестр и будет доступен
> для `invoke_peer_agent` из других агентов.

---

## 3. `agent.py` — шаблон с промптом

```python
# agent3_<name>_inspector/agent.py
from typing import Any

from langgraph.prebuilt import create_react_agent

from agent3_<name>_inspector.tools import (
    invoke_peer_agent,
    generate_validation_report,
    generate_response_email,
)
from shared.llm import build_llm

# Системный промпт: портируйте System Message вашего n8n Chat-нода.
# Структура разделов (SLA / Чек-листы / Инструкции) остаётся прежней —
# шаблон смотри в agent1_dzo_inspector/agent.py:SYSTEM_PROMPT.
SYSTEM_PROMPT = """Ты — ИИ-инспектор «<Название>». Твоя задача — ...

═══════════════════════════════════════════
SLA
═══════════════════════════════════════════
• Время реакции: N часов
• Эскалация при отсутствии ответа: N дней

═══════════════════════════════════════════
ЧЕК-ЛИСТ №1: ...
═══════════════════════════════════════════
1.1 ...
1.2 ...

═══════════════════════════════════════════
ИНСТРУКЦИИ
═══════════════════════════════════════════
ШАГ 1 — Проверь ...
ШАГ 2 — Прими решение:
  • «Полное» → вызови generate_...
  • «Требует доработки» → вызови generate_info_request
  • «Эскалация» → вызови generate_escalation
ШАГ 3 — generate_validation_report
ШАГ 4 — generate_response_email

ОГРАНИЧЕНИЯ: вежливый деловой тон."""

class AgentRunner:
    """Adapter for legacy invoke({"input": ...}) contract."""

    def __init__(self, graph_agent: Any):
        self._agent = graph_agent

    def invoke(self, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        chat_input = payload.get("input", "")
        return self._agent.invoke(
            {"messages": [{"role": "user", "content": chat_input}]},
            **kwargs,
        )


def create_<name>_agent(model_name: str | None = None) -> AgentRunner:
    llm = build_llm(temperature=0.2, model_name_override=model_name)
    tools = [
        invoke_peer_agent,
        generate_validation_report,
        generate_response_email,
        # добавьте свои инструменты
    ]
    graph_agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SYSTEM_PROMPT,
    )
    return AgentRunner(graph_agent)
```

> **Правило промпта:** всегда добавляйте SLA, чек-листы и пошаговые инструкции.
> Отделяйте разделы полосой `═══` — это значительно улучшает следование модели чек-листам.

---

## 4. `tools.py` — шаблон инструментов

Каждая нода `toolCode` из n8n — это один `@tool`.

```python
# agent3_<name>_inspector/tools.py
from langchain_core.tools import tool


@tool
def generate_validation_report(analysis: str) -> str:
    """Сформирует отчёт по результатам проверки.

    Args:
        analysis: текстовый анализ со статусом каждого пункта чек-листа.
    """
    return f"=== ОТЧЄТ ПО ПРОВЕРКЕ ===\n{analysis}"


@tool
def generate_response_email(content: str) -> str:
    """Формирует HTML письма для отправки отправителю.

    Args:
        content: текст ответа для получателя.
    """
    return (
        "<html><body>"
        f"<p>{content}</p>"
        "<p>С уважением, ИИ-инспектор</p>"
        "</body></html>"
    )


@tool
def generate_info_request(missing_fields: str) -> str:
    """Формирует запрос недостающих данных.

    Args:
        missing_fields: перечень отсутствующих полей.
    """
    return f"Запрос дополнительных сведений:\n{missing_fields}"


@tool
def generate_escalation(reason: str) -> str:
    """Отправляет эскалацию руководителю.

    Args:
        reason: причина эскалации.
    """
    return f"ЭСКАЛАЦИЯ РУКОВОДИТЕЛЮ: {reason}"
```

> **Правило docstring:** первая строка docstring — это то, что видит LLM.
> Описывайте `Args:` детально — это то же что `parameters.description` в n8n-инструменте.

---

## 5. `runner.py` — шаблон IMAP-петли

```python
# agent3_<name>_inspector/runner.py
import imaplib
import os
import smtplib
from email import message_from_bytes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import schedule
from dotenv import load_dotenv

load_dotenv()

from agent3_<name>_inspector.agent import create_<name>_agent  # noqa: E402

IMAP_HOST = os.getenv("<NAME>_IMAP_HOST", "")
IMAP_PORT = int(os.getenv("<NAME>_IMAP_PORT", "993"))
IMAP_USER = os.getenv("<NAME>_IMAP_USER", "")
IMAP_PASS = os.getenv("<NAME>_IMAP_PASSWORD", "")
IMAP_FOLDER = os.getenv("<NAME>_IMAP_FOLDER", "INBOX")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SEC", "300"))
FORCE_REPROCESS = os.getenv("FORCE_REPROCESS", "false").lower() == "true"


def process_text(text: str, subject: str = "", sender: str = "") -> dict:
    """API-вход: обрабатывает произвольный текст, возвращает decision + email_html."""
    agent = create_<name>_agent()
    query = f"[Sender: {sender}] [Subject: {subject}]\n\n{text}"
    result = agent.invoke({"input": query})
    output = result.get("output", "")
    email_html = _extract_html(result)
    return {"decision": output, "email_html": email_html}


def _extract_html(result: dict) -> str:
    """Extract HTML from intermediate_steps if present."""
    for _, observation in result.get("intermediate_steps", []):
        if isinstance(observation, str) and "<html" in observation.lower():
            return observation
    return ""


def _poll_once() -> None:
    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as conn:
        conn.login(IMAP_USER, IMAP_PASS)
        conn.select(IMAP_FOLDER)
        _, data = conn.search(None, "UNSEEN")
        uids = data[0].split()
        if not uids:
            return
        for uid in uids:
            _, msg_data = conn.fetch(uid, "(RFC822)")
            msg = message_from_bytes(msg_data[0][1])
            sender = msg.get("From", "")
            subject = msg.get("Subject", "")
            body = _extract_body(msg)
            result = process_text(body, subject=subject, sender=sender)
            _send_reply(
                to=sender,
                subject=f"Re: {subject}",
                html=result["email_html"] or result["decision"],
            )
            conn.store(uid, "+FLAGS", "\\Seen")


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(errors="replace")
    return msg.get_payload(decode=True).decode(errors="replace")


def _send_reply(to: str, subject: str, html: str) -> None:
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.sendmail(smtp_user, [to], msg.as_string())


def run_forever() -> None:
    schedule.every(POLL_INTERVAL).seconds.do(_poll_once)
    import time
    while True:
        schedule.run_pending()
        time.sleep(5)
```

---

## 6. `__init__.py`

```python
# agent3_<name>_inspector/__init__.py
from agent3_<name>_inspector.runner import process_text, run_forever

__all__ = ["process_text", "run_forever"]
```

---

## 7. Регистрация агента в API

### 7.1 `shared/database.py` — ничего менять не нужно

База данных хранит `job.agent` как строку — новое значение `"<name>"` сразу попадёт в хранилище.

### 7.2 `api/app.py` — добавить агент в `AGENT_REGISTRY`

В текущей архитектуре UI и автоопределение работают динамически через `GET /agents`.
Достаточно зарегистрировать нового агента в `AGENT_REGISTRY`.

```python
AGENT_REGISTRY = {
    "<name>": {
        "name": "<Человекочитаемое имя>",
        "description": "<Описание>",
        "decisions": ["<decision1>", "<decision2>"],
        "auto_detect": {
            "priority": 70,
            "keywords": ["ключевая фраза", "синоним", "термин"]
        },
    },
    # ... существующие агенты
}
```

После этого:
- агент автоматически появится в `GET /agents`;
- агент автоматически попадёт в селектор на странице тестирования UI;
- универсальный запуск через `POST /api/v1/process/{agent}` начнёт принимать новый ID без добавления отдельного route;
- `POST /api/v1/process/auto` и `POST /api/v1/resolve-agent` начнут учитывать его профиль `auto_detect`.

### 7.3 Межагентные вызовы (по умолчанию)

- Встроенный bridge `shared/agent_tooling.py` автоматически обнаруживает новых агентов
    по naming-convention и добавляет их в реестр вызовов.
- Политика по умолчанию: `all_except_self` (любой агент может вызвать любой другой).
- Чтобы ограничить маршруты, задайте `AGENT_TOOL_PERMISSIONS`.
- Для явного переопределения import path используйте `AGENT_TOOL_REGISTRY`.

---

## 8. Docker Compose — новый сервис

```yaml
# docker-compose.yml: добавить параллельно существующим agent1/agent2
agent3-<name>:
  build: .
  image: dzo-tz-agents:latest
  command: python -c "from agent3_<name>_inspector import run_forever; run_forever()"
  env_file: .env
  environment:
    AGENT_MODE: "<name>"
  depends_on:
    postgres:
      condition: service_healthy
  networks: [backend]
  restart: unless-stopped
  deploy:
    resources:
      limits: { cpus: "1", memory: "512m" }
```

---

## 9. Тесты — шаблон `tests/test_agent_<name>.py`

```python
# tests/test_agent_<name>.py
"""
Тесты агента <name>:
  - ответ API (через TestClient)
  - process_text с моком AgentExecutor
  - tools (унит)
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app import app
from shared.database import _memory_store

HEADERS = {"X-API-Key": "test-secret"}


@pytest.fixture(autouse=True)
def clear_jobs():
    _memory_store.clear()
    yield
    _memory_store.clear()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ─── API-тесты ─────────────────────────────────────────────────────────────
class TestProcess<Name>Api:
    def test_process_returns_job_id(self, client):
        resp = client.post(
            "/api/v1/process/<name>",
            json={"text": "Тестовое содержание", "subject": "Тест"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job" in data
        assert data["job"]["agent"] == "<name>"
        assert data["job"]["status"] in ("pending", "running", "done")

    def test_process_without_api_key_returns_401(self, client):
        resp = client.post("/api/v1/process/<name>", json={"text": "Тест"})
        assert resp.status_code == 401

    def test_agent_in_list(self, client):
        resp = client.get("/agents")
        ids = [a["id"] for a in resp.json()["agents"]]
        assert "<name>" in ids


# ─── process_text с mock ───────────────────────────────────────────────────────
class TestProcess<Name>Unit:
    @patch("agent3_<name>_inspector.agent.create_<name>_agent")
    def test_process_text_returns_decision(self, mock_factory):
        mock_executor = MagicMock()
        mock_executor.invoke.return_value = {
            "output": "Документ полный",
            "intermediate_steps": [],
        }
        mock_factory.return_value = mock_executor

        from agent3_<name>_inspector.runner import process_text
        result = process_text("Тест", subject="Тест", sender="a@b.com")

        assert "decision" in result
        assert result["decision"] == "Документ полный"
        assert "email_html" in result

    @patch("agent3_<name>_inspector.agent.create_<name>_agent")
    def test_process_text_extracts_html_from_tools(self, mock_factory):
        mock_executor = MagicMock()
        mock_executor.invoke.return_value = {
            "output": "Отчёт",
            "intermediate_steps": [
                (MagicMock(), "<html><body>Ответ</body></html>"),
            ],
        }
        mock_factory.return_value = mock_executor

        from agent3_<name>_inspector.runner import process_text
        result = process_text("Тест")
        assert "<html" in result["email_html"]


# ─── Унит-тесты tools ─────────────────────────────────────────────────────────
class TestTools<Name>:
    def test_generate_validation_report_returns_string(self):
        from agent3_<name>_inspector.tools import generate_validation_report
        result = generate_validation_report.invoke({"analysis": "Полное"})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_response_email_returns_html(self):
        from agent3_<name>_inspector.tools import generate_response_email
        result = generate_response_email.invoke({"content": "Текст"})
        assert "<html" in result.lower()

    def test_generate_info_request_contains_fields(self):
        from agent3_<name>_inspector.tools import generate_info_request
        result = generate_info_request.invoke({"missing_fields": "Бюджет, Дата"})
        assert "Бюджет" in result

    def test_generate_escalation_contains_reason(self):
        from agent3_<name>_inspector.tools import generate_escalation
        result = generate_escalation.invoke({"reason": "Отсутствие ответа"})
        assert "Отсутствие" in result
```

---

## 10. Чек-лист интеграции

Перед pull request выполните проверку:

```
[ ] agent3_<name>_inspector/__init__.py  — экспорт process_text, run_forever
[ ] agent3_<name>_inspector/agent.py     — SYSTEM_PROMPT с SLA/чек-листами
[ ] agent3_<name>_inspector/tools.py     — все @tool с полными docstring
[ ] agent3_<name>_inspector/runner.py    — process_text + run_forever + FORCE_REPROCESS
[ ] api/app.py                           — агент в AGENTS[] и _run_agent()
[ ] docker-compose.yml                  — новый сервис agent3-<name>
[ ] shared/agent_tooling.py             — naming-convention соблюдён для auto-discovery
[ ] .env.example                         — <NAME>_IMAP_* переменные
[ ] tests/test_agent_<name>.py           — минимум: API + unit process_text + tools
[ ] CHANGELOG.md                         — версия поднята
[ ] pyproject.toml                       — agent3* включён в packages.find.include
[ ] make test — все тесты зелёны
[ ] make lint — ruff без ошибок
```

---

## 11. Полный пример: портирование `n8n-contract-inspector-v1.0`

Предположим, есть n8n-сценарий проверки договоров. Соответствие n8n → Python:

| n8n | Python |
|---|---|
| System Message: «Проверяй договор на сроки, стороны, реквизиты» | `SYSTEM_PROMPT` в `agent.py` |
| toolCode: `generate_contract_summary` | `@tool generate_contract_summary` в `tools.py` |
| toolCode: `flag_missing_clauses` | `@tool flag_missing_clauses` в `tools.py` |
| emailReadImap (`CONTRACT_IMAP_*`) | `runner.py` с `CONTRACT_IMAP_*` |
| IMAP фольдер `CONTRACTS` | `CONTRACT_IMAP_FOLDER=CONTRACTS` в `.env.example` |
| Папка | `agent3_contract_inspector/` |
| Регистрация | `{"id": "contract", ...}` в `AGENTS[]` |
