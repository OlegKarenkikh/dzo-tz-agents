"""
Streamlit Web UI для управления и тестирования агентов ДЗО/ТЗ.

Страницы:
  📊 Дашборд       — статистика и последние обработки
  🧪 Тестирование  — загрузка документов и ручная проверка
  ⚙️ Настройки     — конфигурация агентов
  📋 История       — таблица обработок с фильтрами
  📖 Документация  — описание агентов
"""

import base64
import csv
import io
import os
import time

import httpx
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from ui.config import API_URL, AUTH_HEADERS, AUTO_REFRESH_SEC

load_dotenv()

# ---------------------------------------------------------------------------
# Конфигурация страницы
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Агенты ДЗО/ТЗ",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Кастомные стили
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    .metric-card {
        background: #f0f2f6;
        border-radius: 8px;
        padding: 16px;
        text-align: center;
        margin-bottom: 8px;
    }
    .metric-card h2 { margin: 0; font-size: 2rem; }
    .metric-card p  { margin: 0; color: #555; font-size: 0.9rem; }
    .badge-green  { background: #d4edda; color: #155724; padding: 2px 10px; border-radius: 12px; font-size: 0.8rem; }
    .badge-yellow { background: #fff3cd; color: #856404; padding: 2px 10px; border-radius: 12px; font-size: 0.8rem; }
    .badge-red    { background: #f8d7da; color: #721c24; padding: 2px 10px; border-radius: 12px; font-size: 0.8rem; }
    .stAlert { border-radius: 8px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Вспомогательные функции для API
# ---------------------------------------------------------------------------


def _api_get(path: str, params: dict | None = None) -> dict | None:
    """ГЕТ-запрос к REST API."""
    try:
        resp = httpx.get(f"{API_URL}{path}", headers=AUTH_HEADERS, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        st.error(f"Ошибка API ({e.response.status_code}): {e.response.text}")
    except Exception as e:
        st.error(f"Ошибка соединения с API: {e}")
    return None


def _api_post(path: str, payload: dict) -> dict | None:
    """ПОСТ-запрос к REST API."""
    try:
        resp = httpx.post(f"{API_URL}{path}", headers=AUTH_HEADERS, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        st.error(f"Ошибка API ({e.response.status_code}): {e.response.text}")
    except Exception as e:
        st.error(f"Ошибка соединения с API: {e}")
    return None


def _decision_badge(decision: str) -> str:
    """Возвращает HTML-бейдж с цветовой кодировкой решения."""
    d = (decision or "").lower()
    if any(k in d for k in ["полная", "соответствует", "принята"]):
        return f'<span class="badge-green">✅ {decision}</span>'
    if any(k in d for k in ["доработка", "требует"]):
        return f'<span class="badge-yellow">⚠️ {decision}</span>'
    if any(k in d for k in ["эскалация", "не соответствует", "ошибка"]):
        return f'<span class="badge-red">🔴 {decision}</span>'
    return f'<span class="badge-yellow">{decision or "—"}</span>'


def _status_icon(status: str) -> str:
    icons = {"done": "✅", "running": "⏳", "pending": "🕐", "error": "❌"}
    return icons.get(status, "❓")


# ---------------------------------------------------------------------------
# Боковая панель навигации
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🤖 Агенты ДЗО/ТЗ")
    st.caption(f"API: `{API_URL}`")
    st.divider()
    page = st.radio(
        "Навигация",
        options=["📊 Дашборд", "🧪 Тестирование", "⚙️ Настройки", "📋 История", "📖 Документация"],
        label_visibility="collapsed",
    )
    st.divider()
    health = _api_get("/health")
    if health:
        st.success("🟢 Сервис работает")
        st.caption(f"Uptime: {health.get('uptime_sec', 0)} сек.")
    else:
        st.error("🔴 Сервис недоступен")

# ---------------------------------------------------------------------------
# 📊 ДАШБОРД
# ---------------------------------------------------------------------------

if page == "📊 Дашборд":
    st.header("📊 Дашборд")

    history_data = _api_get("/api/v1/history", {"limit": 100}) or {"total": 0, "items": []}
    items = history_data.get("items", [])

    total = len(items)
    errors = sum(1 for i in items if i["status"] == "error")
    done = sum(1 for i in items if i["status"] == "done")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f'<div class="metric-card"><h2>{total}</h2><p>Всего обработок</p></div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div class="metric-card"><h2>{done}</h2><p>Завершено</p></div>',
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f'<div class="metric-card"><h2>{errors}</h2><p>Ошибок</p></div>',
            unsafe_allow_html=True,
        )
    with col4:
        dzo_count = sum(1 for i in items if i["agent"] == "dzo")
        tz_count = sum(1 for i in items if i["agent"] == "tz")
        st.markdown(
            f'<div class="metric-card"><h2>ДЗО: {dzo_count} / ТЗ: {tz_count}</h2><p>По агентам</p></div>',
            unsafe_allow_html=True,
        )

    st.subheader("Последние 20 обработок")
    if items:
        rows = []
        for item in items[:20]:
            decision = (item.get("result") or {}).get("decision", "—")
            rows.append({
                "Время": item["created_at"][:19].replace("T", " "),
                "Агент": item["agent"].upper(),
                "Решение": decision,
                "Статус": f"{_status_icon(item['status'])} {item['status']}",
                "ID": item["job_id"][:8] + "…",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Нет данных. Запустите обработку документа.")

    st.subheader("Ручной запуск")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("▶️ Запустить ДЗО", use_container_width=True):
            result = _api_post("/api/v1/process/dzo", {"text": "(ручной запуск)", "subject": "Тестовый запуск"})
            if result:
                st.success(f"Задание создано: `{result['job_id']}`")
    with col_b:
        if st.button("▶️ Запустить ТЗ", use_container_width=True):
            result = _api_post("/api/v1/process/tz", {"text": "(ручной запуск)", "subject": "Тестовый запуск"})
            if result:
                st.success(f"Задание создано: `{result['job_id']}`")
    with col_c:
        if st.button("▶️ Запустить оба", use_container_width=True):
            for agent_path in ["/api/v1/process/dzo", "/api/v1/process/tz"]:
                result = _api_post(agent_path, {"text": "(ручной запуск)", "subject": "Тестовый запуск"})
                if result:
                    st.success(f"Задание создано: `{result['job_id']}`")

    if st.button("🔄 Обновить", key="refresh_dashboard"):
        st.rerun()
    st.caption(f"Страница обновляется каждые {AUTO_REFRESH_SEC} сек. при нажатии кнопки.")

# ---------------------------------------------------------------------------
# 🧪 ТЕСТИРОВАНИЕ АГЕНТОВ
# ---------------------------------------------------------------------------

elif page == "🧪 Тестирование":
    st.header("🧪 Тестирование агентов")

    agent_choice = st.selectbox("Выберите агента", ["ДЗО — Инспектор заявок", "ТЗ — Инспектор техзаданий"])
    agent_key = "dzo" if "ДЗО" in agent_choice else "tz"

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("Входные данные")
        sender_email = st.text_input("Email отправителя", placeholder="dzo@company.ru")
        subject_input = st.text_input("Тема письма", placeholder="Заявка на закупку оборудования")
        text_input = st.text_area(
            "Текст документа",
            height=200,
            placeholder="Вставьте текст заявки или ТЗ...",
        )
        uploaded_files = st.file_uploader(
            "Вложения (PDF, DOCX, XLSX, PNG, JPG)",
            accept_multiple_files=True,
            type=["pdf", "docx", "xlsx", "xls", "png", "jpg", "jpeg"],
        )

    with col_right:
        st.subheader("Результат")
        if st.button("🔍 Проверить", type="primary", use_container_width=True):
            attachments = []
            for f in (uploaded_files or []):
                raw = f.read()
                attachments.append({
                    "filename": f.name,
                    "content_base64": base64.b64encode(raw).decode(),
                    "mime_type": f.type or "application/octet-stream",
                })

            payload = {
                "text": text_input,
                "filename": uploaded_files[0].name if uploaded_files else "",
                "sender_email": sender_email,
                "subject": subject_input,
                "attachments": attachments,
            }

            with st.spinner("Отправляем запрос к агенту..."):
                job = _api_post(f"/api/v1/process/{agent_key}", payload)

            if job:
                job_id = job["job_id"]
                st.info(f"Задание создано: `{job_id}`")

                with st.spinner("Ожидаем результат..."):
                    result = None
                    for _ in range(30):
                        time.sleep(2)
                        result = _api_get(f"/api/v1/jobs/{job_id}")
                        if result and result["status"] in ("done", "error"):
                            break

                if result:
                    if result["status"] == "done":
                        r = result.get("result") or {}
                        decision = r.get("decision", "")
                        st.markdown(
                            f"**Решение:** {_decision_badge(decision)}",
                            unsafe_allow_html=True,
                        )
                        with st.expander("📄 JSON-отчёт", expanded=False):
                            st.json(r)

                        email_html = r.get("email_html", "")
                        if email_html:
                            with st.expander("📧 HTML-письмо", expanded=True):
                                components.html(email_html, height=400, scrolling=True)
                            st.download_button(
                                "💾 Скачать HTML",
                                data=email_html.encode("utf-8"),
                                file_name="result.html",
                                mime="text/html",
                            )
                    else:
                        st.error(f"Ошибка: {result.get('error', 'неизвестная ошибка')}")

# ---------------------------------------------------------------------------
# ⚙️ НАСТРОЙКИ
# ---------------------------------------------------------------------------

elif page == "⚙️ Настройки":
    st.header("⚙️ Настройки")

    # ── Читаем реальные значения из окружения ─────────────────────────────
    current_api_url    = os.getenv("UI_API_URL", "http://localhost:8000")
    current_model      = os.getenv("MODEL_NAME", "gpt-4o")
    current_llm_base   = os.getenv("OPENAI_API_BASE", "")
    current_agent_type = os.getenv("AGENT_TYPE", "openai_tools")
    current_agent_mode = os.getenv("AGENT_MODE", "both")
    current_poll       = int(os.getenv("POLL_INTERVAL_SEC", "300"))
    current_manager    = os.getenv("MANAGER_EMAIL", "")

    # ── Текущая конфигурация (только чтение) ──────────────────────────────
    st.subheader("🔍 Текущая конфигурация")
    st.info("Значения загружены из переменных окружения (.env). Для изменения отредактируйте .env и перезапустите сервис.")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**🌐 API эндпоинт (UI_API_URL)**")
        st.code(current_api_url, language=None)

        st.markdown("**🤖 Модель LLM (MODEL_NAME)**")
        st.code(current_model, language=None)

        st.markdown("**🔗 Эндпоинт LLM (OPENAI_API_BASE)**")
        st.code(current_llm_base if current_llm_base else "(по умолчанию: api.openai.com/v1)", language=None)

    with col2:
        st.markdown("**⚙️ Тип агента (AGENT_TYPE)**")
        st.code(current_agent_type, language=None)

        st.markdown("**🎛️ Режим агента (AGENT_MODE)**")
        st.code(current_agent_mode, language=None)

        st.markdown("**📧 Email менеджера (MANAGER_EMAIL)**")
        st.code(current_manager if current_manager else "(не задан)", language=None)

    st.divider()

    # ── Справочник моделей и эндпоинтов ───────────────────────────────────
    st.subheader("📋 Поддерживаемые модели и эндпоинты")
    tab_openai, tab_ollama, tab_deepseek, tab_vllm = st.tabs(
        ["☁️ OpenAI", "🦙 Ollama (локально)", "🌊 DeepSeek", "⚡ vLLM / LM Studio"]
    )

    with tab_openai:
        st.markdown("**OPENAI_API_BASE** — оставить пустым (использует `api.openai.com/v1`)")
        st.markdown("**AGENT_TYPE** = `openai_tools`")
        st.table([
            {"MODEL_NAME": "gpt-4o",      "Описание": "Флагман, лучшее качество"},
            {"MODEL_NAME": "gpt-4o-mini", "Описание": "Быстрый и дешёвый"},
            {"MODEL_NAME": "gpt-4-turbo", "Описание": "Предыдущее поколение"},
        ])

    with tab_ollama:
        st.markdown("**OPENAI_API_BASE** = `http://localhost:11434/v1`")
        st.markdown("**AGENT_TYPE** = `react` (ReAct prompting, работает без function-calling)")
        st.table([
            {"MODEL_NAME": "llama3",         "Описание": "Meta Llama 3 8B/70B"},
            {"MODEL_NAME": "mistral",         "Описание": "Mistral 7B"},
            {"MODEL_NAME": "qwen2.5",         "Описание": "Qwen 2.5 7B/14B/72B"},
            {"MODEL_NAME": "deepseek-r1:8b",  "Описание": "DeepSeek R1 (локально)"},
            {"MODEL_NAME": "phi4",            "Описание": "Microsoft Phi-4"},
        ])
        st.info("Убедитесь что модель загружена: `ollama pull <model_name>`")

    with tab_deepseek:
        st.markdown("**OPENAI_API_BASE** = `https://api.deepseek.com/v1`")
        st.markdown("**AGENT_TYPE** = `openai_tools` (DeepSeek V3+ поддерживает function-calling)")
        st.table([
            {"MODEL_NAME": "deepseek-chat",     "Описание": "DeepSeek V3 (рекомендуется)"},
            {"MODEL_NAME": "deepseek-reasoner",  "Описание": "DeepSeek R1 (reasoning)"},
        ])

    with tab_vllm:
        st.markdown("**OPENAI_API_BASE** = `http://localhost:8000/v1` (vLLM) или `http://localhost:1234/v1` (LM Studio)")
        st.markdown("**AGENT_TYPE** = `openai_tools` если модель поддерживает tools, иначе `react`")
        st.table([
            {"MODEL_NAME": "microsoft/phi-4",            "Описание": "Phi-4 через vLLM"},
            {"MODEL_NAME": "Qwen/Qwen2.5-72B-Instruct",  "Описание": "Qwen 2.5 72B через vLLM"},
        ])

    st.divider()

    # ── Тест соединения ───────────────────────────────────────────────────
    st.subheader("🔌 Тест соединения")
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        if st.button("🔌 Проверить API", use_container_width=True):
            health = _api_get("/health")
            if health:
                st.success(f"API доступен. Uptime: {health.get('uptime_sec')} сек.")
            else:
                st.error("API недоступен")
    with col_t2:
        if st.button("📋 Список агентов", use_container_width=True):
            agents = _api_get("/agents")
            if agents:
                for a in agents.get("agents", []):
                    st.info(f"**{a['name']}** (`{a['id']}`): {a.get('description', '')}")

    st.divider()

    # ── Пример .env ───────────────────────────────────────────────────────
    with st.expander("📄 Пример .env для быстрого старта"):
        st.code(
            """# OpenAI\nOPENAI_API_KEY=sk-...\nMODEL_NAME=gpt-4o\nOPENAI_API_BASE=\nAGENT_TYPE=openai_tools\n\n# Ollama (локально)\n# MODEL_NAME=qwen2.5\n# OPENAI_API_BASE=http://localhost:11434/v1\n# AGENT_TYPE=react\n\n# DeepSeek\n# OPENAI_API_KEY=sk-...\n# MODEL_NAME=deepseek-chat\n# OPENAI_API_BASE=https://api.deepseek.com/v1\n# AGENT_TYPE=openai_tools\n\nAGENT_MODE=both\nPOLL_INTERVAL_SEC=300\nMANAGER_EMAIL=manager@company.ru\nAPI_KEY=change-me-strong-api-key\nUI_API_URL=http://localhost:8000\nUI_API_KEY=change-me-strong-api-key\n""",
            language="bash",
        )

# ---------------------------------------------------------------------------
# 📋 ИСТОРИЯ
# ---------------------------------------------------------------------------

elif page == "📋 История":
    st.header("📋 История обработок")

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filter_agent = st.selectbox("Агент", ["Все", "ДЗО", "ТЗ"])
    with col_f2:
        filter_status = st.selectbox("Статус", ["Все", "done", "error", "running", "pending"])
    with col_f3:
        filter_limit = st.number_input("Макс. записей", min_value=10, max_value=500, value=50, step=10)

    params: dict = {"limit": filter_limit}
    if filter_agent != "Все":
        params["agent"] = filter_agent.lower()
    if filter_status != "Все":
        params["status"] = filter_status

    data = _api_get("/api/v1/history", params) or {"total": 0, "items": []}
    items = data.get("items", [])

    st.caption(f"Найдено записей: {data.get('total', 0)}")

    if items:
        rows = []
        for item in items:
            r = item.get("result") or {}
            rows.append({
                "Время": item["created_at"][:19].replace("T", " "),
                "Агент": item["agent"].upper(),
                "Решение": r.get("decision", "—"),
                "Статус": f"{_status_icon(item['status'])} {item['status']}",
                "Ошибка": item.get("error") or "",
                "job_id": item["job_id"],
            })

        df_display = [{k: v for k, v in row.items() if k != "job_id"} for row in rows]
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        st.download_button(
            "📥 Экспорт CSV",
            data=buf.getvalue().encode("utf-8-sig"),
            file_name="history.csv",
            mime="text/csv",
        )
    else:
        st.info("История пуста. Запустите обработку документа через страницу «Тестирование».")

# ---------------------------------------------------------------------------
# 📖 ДОКУМЕНТАЦИЯ
# ---------------------------------------------------------------------------

elif page == "📖 Документация":
    st.header("📖 Документация")

    tab1, tab2, tab3 = st.tabs(["Агент ДЗО", "Агент ТЗ", "API"])

    with tab1:
        st.markdown(
            """
## 🏢 Агент ДЗО — Инспектор заявок дочерних обществ

**Назначение:** Автоматическая проверка входящих заявок от ДЗО на полноту и корректность
перед регистрацией в системе ЭДО «Тезис».

### SLA
| Операция | Срок |
|---|---|
| Реакция на входящее письмо | 2 часа |
| Запрос недостающих данных | 1 час |
| Эскалация при отсутствии ответа | 2 дня |

### Чек-лист №1: Комплектность вложений
- Наличие файла ТЗ
- Наличие спецификации (для сложных закупок)
- Файлы открываются и не защищены паролем

### Чек-лист №2: Обязательные реквизиты
- Наименование закупки
- Количество с единицами измерения
- Желаемый срок поставки (конкретная дата)
- Инициатор — ФИО и контакты
- Место поставки — точный адрес

### Возможные решения
| Решение | Описание |
|---|---|
| ✅ Заявка полная | Все реквизиты заполнены, формируется форма Тезис |
| ⚠️ Требуется доработка | Отсутствуют обязательные поля, отправляется запрос |
| 🔴 Требуется эскалация | Критические противоречия, передаётся руководителю |
            """
        )

    with tab2:
        st.markdown(
            """
## 📋 Агент ТЗ — Инспектор технических заданий

**Назначение:** Проверка технических заданий на соответствие стандартам и
полноту разделов перед закупочной процедурой.

### Разделы ТЗ (чек-лист)
1. Цель и задачи закупки
2. Технические требования
3. Функциональные требования
4. Требования к качеству
5. Объём и сроки поставки
6. Место поставки
7. Порядок приёмки
8. Гарантийные обязательства

### Возможные решения
| Решение | Описание |
|---|---|
| ✅ Соответствует | ТЗ полное и корректное |
| ⚠️ Требует доработки | Некоторые разделы отсутствуют или неполные |
| 🔴 Не соответствует | Критические нарушения требований |
            """
        )

    with tab3:
        st.markdown(
            f"""
## 🔌 REST API

**Базовый URL:** `{API_URL}`

### Аутентификация
Все запросы к `/api/v1/*` требуют заголовка:
```
X-API-Key: <ваш ключ>
```

### Основные эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| GET | `/health` | Статус сервиса |
| GET | `/agents` | Список агентов |
| POST | `/api/v1/process/dzo` | Обработать заявку ДЗО |
| POST | `/api/v1/process/tz` | Обработать ТЗ |
| POST | `/api/v1/process/auto` | Автоопределение типа |
| GET | `/api/v1/jobs` | Список заданий |
| GET | `/api/v1/jobs/{{job_id}}` | Статус задания |
| GET | `/api/v1/history` | История обработок |

### Пример запроса
```bash
curl -X POST {API_URL}/api/v1/process/dzo \\
  -H "X-API-Key: your-key" \\
  -H "Content-Type: application/json" \\
  -d '{{"text": "Заявка на закупку", "subject": "Закупка оборудования"}}'
```

Полная документация API: [{API_URL}/docs]({API_URL}/docs)
            """
        )
