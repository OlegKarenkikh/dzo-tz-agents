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


def _api_delete(path: str) -> bool:
    """ДЕЛЕТЕ-запрос к REST API."""
    try:
        resp = httpx.delete(f"{API_URL}{path}", headers=AUTH_HEADERS, timeout=10)
        resp.raise_for_status()
        return True
    except httpx.HTTPStatusError as e:
        st.error(f"Ошибка API ({e.response.status_code}): {e.response.text}")
    except Exception as e:
        st.error(f"Ошибка соединения с API: {e}")
    return False


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

    if "test_result" not in st.session_state:
        st.session_state.test_result = None
    if "test_duplicate" not in st.session_state:
        st.session_state.test_duplicate = None
    if "test_payload" not in st.session_state:
        st.session_state.test_payload = None

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

    def _poll_job(job_id):
        with st.spinner("Ожидаем результат..."):
            for _ in range(30):
                time.sleep(2)
                res = _api_get(f"/api/v1/jobs/{job_id}")
                if res and res["status"] in ("done", "error"):
                    return res
        return None

    def _show_job_result(result):
        if not result:
            return
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

    with col_right:
        st.subheader("Результат")
        if st.button("🔍 Проверить", type="primary", use_container_width=True):
            st.session_state.test_result = None
            st.session_state.test_duplicate = None

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
            st.session_state.test_payload = payload

            # Проверка дубликата
            dup = _api_get("/api/v1/check-duplicate", {
                "agent": agent_key,
                "sender": sender_email,
                "subject": subject_input
            })

            if dup and dup.get("duplicate"):
                st.session_state.test_duplicate = dup["job"]
            else:
                with st.spinner("Отправляем запрос к агенту..."):
                    job = _api_post(f"/api/v1/process/{agent_key}", payload)
                if job and "job" in job:
                    st.session_state.test_result = _poll_job(job["job"]["job_id"])

        if st.session_state.test_duplicate:
            dup = st.session_state.test_duplicate
            st.warning("⚠️ Найдена предыдущая обработка этого письма")

            c1, c2, c3 = st.columns([2, 2, 1])
            c1.caption(f"**Дата:** {dup['created_at'][:19].replace('T', ' ')}")
            decision = dup.get("decision") or (dup.get("result") or {}).get("decision")
            c2.markdown(f"**Решение:** {_decision_badge(decision)}", unsafe_allow_html=True)
            c3.caption(f"ID: `{dup['job_id'][:8]}`")

            b1, b2 = st.columns(2)
            if b1.button("Использовать старый результат", use_container_width=True):
                st.session_state.test_result = dup
                st.session_state.test_duplicate = None
                st.rerun()
            if b2.button("Переобработать", use_container_width=True):
                payload = st.session_state.test_payload
                payload["force"] = True
                with st.spinner("Повторная отправка..."):
                    job = _api_post(f"/api/v1/process/{agent_key}", payload)
                if job and "job" in job:
                    st.session_state.test_result = _poll_job(job["job"]["job_id"])
                st.session_state.test_duplicate = None
                st.rerun()

        if st.session_state.test_result:
            _show_job_result(st.session_state.test_result)

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

    if "selected_jobs" not in st.session_state:
        st.session_state.selected_jobs = set()
    if "pending_delete" not in st.session_state:
        st.session_state.pending_delete = False
    # Флаг предыдущего состояния «Выбрать всё» для корректного снятия выделения
    if "select_all_prev" not in st.session_state:
        st.session_state.select_all_prev = False

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
        all_job_ids = [i["job_id"] for i in items]

        # ── Чекбокс «Выбрать всё» — стабильная логика через session_state ──
        col_all, _ = st.columns([1, 4])
        select_all = col_all.checkbox(
            "Выбрать всё",
            value=st.session_state.select_all_prev,
            key="select_all_cb",
        )
        if select_all and not st.session_state.select_all_prev:
            # Переход False → True: добавляем все ID текущей страницы
            st.session_state.selected_jobs.update(all_job_ids)
        elif not select_all and st.session_state.select_all_prev:
            # Переход True → False: снимаем только ID текущей страницы
            st.session_state.selected_jobs.difference_update(all_job_ids)
        st.session_state.select_all_prev = select_all

        # Массовые действия
        if st.session_state.selected_jobs:
            st.write(f"Выбрано: **{len(st.session_state.selected_jobs)}**")
            act_col1, act_col2, _ = st.columns([2, 2, 4])

            if act_col1.button("🔁 Переобработать выбранные", use_container_width=True):
                new_jobs = []
                for jid in st.session_state.selected_jobs:
                    j_info = _api_get(f"/api/v1/jobs/{jid}")
                    if j_info:
                        res = _api_post(f"/api/v1/process/{j_info['agent']}", {
                            "sender_email": j_info.get("sender", ""),
                            "subject": j_info.get("subject", ""),
                            "force": True,
                        })
                        if res and "job" in res:
                            new_jobs.append(res["job"]["job_id"])
                st.success(f"Запущено {len(new_jobs)} новых заданий.")
                st.session_state.selected_jobs.clear()
                st.session_state.select_all_prev = False
                time.sleep(1)
                st.rerun()

            if not st.session_state.pending_delete:
                if act_col2.button("🗑 Удалить выбранные", use_container_width=True):
                    st.session_state.pending_delete = True
                    st.rerun()
            else:
                st.warning("Вы уверены, что хотите удалить выбранные записи?")
                del_c1, del_c2 = st.columns(2)
                if del_c1.button("✅ Подтвердить удаление", type="primary", use_container_width=True):
                    deleted_count = 0
                    for jid in list(st.session_state.selected_jobs):
                        if _api_delete(f"/api/v1/jobs/{jid}"):
                            deleted_count += 1
                    st.success(f"Удалено {deleted_count} записей.")
                    st.session_state.selected_jobs.clear()
                    st.session_state.pending_delete = False
                    st.session_state.select_all_prev = False
                    time.sleep(1)
                    st.rerun()
                if del_c2.button("❌ Отмена", use_container_width=True):
                    st.session_state.pending_delete = False
                    st.rerun()

        rows = []
        for item in items:
            r = item.get("result") or {}
            rows.append({
                "Выбор": item["job_id"] in st.session_state.selected_jobs,
                "Время": item["created_at"][:19].replace("T", " "),
                "Агент": item["agent"].upper(),
                "Отправитель": item.get("sender") or "—",
                "Тема": item.get("subject") or "—",
                "Решение": r.get("decision", "—"),
                "Статус": f"{_status_icon(item['status'])} {item['status']}",
                "job_id": item["job_id"],
            })

        # Используем data_editor для чекбоксов
        edited_df = st.data_editor(
            rows,
            column_config={
                "Выбор": st.column_config.CheckboxColumn("Выбор", default=False),
                "job_id": None,  # Скрываем ID
            },
            disabled=["Время", "Агент", "Отправитель", "Тема", "Решение", "Статус"],
            use_container_width=True,
            hide_index=True,
            key="history_editor",
        )

        # Синхронизация стейта после редактирования чекбоксов в таблице
        current_selected = {r["job_id"] for r in edited_df if r["Выбор"]}
        current_page_ids = {r["job_id"] for r in rows}
        st.session_state.selected_jobs = (st.session_state.selected_jobs - current_page_ids) | current_selected
        # Синхронизируем флаг select_all с реальным состоянием
        if current_page_ids and current_selected == current_page_ids:
            st.session_state.select_all_prev = True
        elif not current_selected:
            st.session_state.select_all_prev = False

        # Построчные действия через экспандер
        st.write("---")
        st.subheader("Детальный просмотр и действия")
        for item in items:
            with st.expander(f"{item['created_at'][:19].replace('T', ' ')} | {item['agent'].upper()} | {item.get('subject') or '(без темы)'}"):
                c1, c2, c3 = st.columns([4, 1, 1])
                c1.write(f"**ID:** `{item['job_id']}` | **Отправитель:** {item.get('sender') or '—'}")
                if c2.button("🔁 Переобработать", key=f"reproc_{item['job_id']}", use_container_width=True):
                    res = _api_post(f"/api/v1/process/{item['agent']}", {
                        "sender_email": item.get("sender", ""),
                        "subject": item.get("subject", ""),
                        "force": True,
                    })
                    if res and "job" in res:
                        st.success(f"Создано новое задание: `{res['job']['job_id']}`")
                        time.sleep(0.5)
                        st.rerun()  # fix: обновить таблицу после строчной переобработки
                if c3.button("🗑 Удалить", key=f"del_{item['job_id']}", use_container_width=True):
                    if _api_delete(f"/api/v1/jobs/{item['job_id']}"):
                        st.success("Удалено")
                        time.sleep(0.5)
                        st.rerun()

        # Экспорт CSV (без служебных колонок «Выбор» и «job_id»)
        buf = io.StringIO()
        if rows:
            export_keys = [k for k in rows[0].keys() if k not in ("Выбор", "job_id")]
            export_rows = [{k: r[k] for k in export_keys} for r in rows]
            writer = csv.DictWriter(buf, fieldnames=export_keys)
            writer.writeheader()
            writer.writerows(export_rows)
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
| GET | `/api/v1/check-duplicate` | Проверить дубликат |
| GET | `/api/v1/jobs` | Список заданий |
| GET | `/api/v1/jobs/{{job_id}}` | Статус задания |
| DELETE | `/api/v1/jobs/{{job_id}}` | Удалить задание |
| GET | `/api/v1/history` | История обработок |

### Дедупликация
Система автоматически ищет дубликаты по комбинации `(агент, отправитель, тема)`.
Если найдено успешное задание с такими же параметрами, API вернёт `duplicate: true`.

Чтобы форсировать повторную обработку, передайте параметр `"force": true` в теле POST-запроса.

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
