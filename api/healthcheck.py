"""
FastAPI сервер для:
- /health    — статус агентов
- /run/dzo   — ручной запуск Агента ДЗО
- /run/tz    — ручной запуск Агента ТЗ
- /run/both  — запустить оба агента
"""
from fastapi import FastAPI, BackgroundTasks
from datetime import datetime
import os

app = FastAPI(
    title="DZO/TZ Agents",
    description="ИНСПекторы ЗАЯВОК ДЗО и ТЗ",
    version="1.0.0"
)

start_time = datetime.now()
_run_log: list = []


@app.get("/health")
def health():
    return {
        "status": "ok",
        "uptime_sec": (datetime.now() - start_time).seconds,
        "agent_mode": os.getenv("AGENT_MODE", "both"),
        "model": os.getenv("MODEL_NAME", "gpt-4o"),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
def status():
    return {
        "runs": len(_run_log),
        "last_runs": _run_log[-10:],  # последние 10
    }


def _run_dzo():
    from agent1_dzo_inspector.runner import process_dzo_emails
    ts = datetime.now().isoformat()
    try:
        process_dzo_emails()
        _run_log.append({"agent": "dzo", "ts": ts, "status": "ok"})
    except Exception as e:
        _run_log.append({"agent": "dzo", "ts": ts, "status": "error", "error": str(e)})


def _run_tz():
    from agent2_tz_inspector.runner import process_tz_emails
    ts = datetime.now().isoformat()
    try:
        process_tz_emails()
        _run_log.append({"agent": "tz", "ts": ts, "status": "ok"})
    except Exception as e:
        _run_log.append({"agent": "tz", "ts": ts, "status": "error", "error": str(e)})


@app.post("/run/dzo")
def run_dzo(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_dzo)
    return {"message": "Агент ДЗО запущен", "ts": datetime.now().isoformat()}


@app.post("/run/tz")
def run_tz(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_tz)
    return {"message": "Агент ТЗ запущен", "ts": datetime.now().isoformat()}


@app.post("/run/both")
def run_both(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_dzo)
    background_tasks.add_task(_run_tz)
    return {"message": "Оба агента запущены", "ts": datetime.now().isoformat()}
