"""
FastAPI REST API для обработки документов агентами ДЗО и ТЗ.

Эндпоинты:
  GET  /health                     — статус сервиса
  GET  /status                     — последние N запусков агентов
  GET  /agents                     — список доступных агентов
  GET  /metrics                    — Prometheus scrape
  POST /api/v1/process/dzo         — обработать заявку ДЗО
  POST /api/v1/process/tz          — обработать ТЗ
  POST /api/v1/process/auto        — автоопределение типа
  GET  /api/v1/jobs                — список всех заданий
  GET  /api/v1/jobs/{job_id}       — статус конкретного задания
  DELETE /api/v1/jobs/{job_id}     — удалить задание
  GET  /api/v1/history             — история обработок
"""

import logging
import os
import time
import uuid
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from api.metrics import (
    API_LATENCY, API_REQUESTS,
    DECISIONS_TOTAL, JOBS_TOTAL,
    JobTimer, metrics_router,
)
from shared.database import init_db, create_job, update_job, get_job as db_get_job, get_history as db_get_history, delete_job as db_delete_job

load_dotenv()

logger = logging.getLogger("api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(
    title="DZO/TZ Agents API",
    description="REST API для обработки заявок ДЗО и технических заданий агентами на базе LLM",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(metrics_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = datetime.now()
_run_log: list[dict] = []

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_API_KEY = os.getenv("API_KEY", "")


@app.on_event("startup")
def on_startup():
    init_db()


def _require_api_key(key: Optional[str] = Depends(_api_key_header)) -> str:
    if not _API_KEY:
        return ""
    if key != _API_KEY:
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий API-ключ")
    return key


# ---------------------------------------------------------------------------
# Модели данных
# ---------------------------------------------------------------------------

class AttachmentData(BaseModel):
    filename: str
    content_base64: str
    mime_type: str


class ProcessRequest(BaseModel):
    text: str = Field(default="", description="Текст документа")
    filename: str = Field(default="", description="Имя исходного файла")
    sender_email: str = Field(default="", description="Email отправителя")
    subject: str = Field(default="", description="Тема письма")
    attachments: list[AttachmentData] = Field(default_factory=list, description="Вложения в base64")


class JobResponse(BaseModel):
    job_id: str
    status: str
    agent: str
    created_at: str
    result: Optional[dict] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Фоновая обработка
# ---------------------------------------------------------------------------

def _process_with_agent(job_id: str, agent_type: str, request: ProcessRequest) -> None:
    job = db_get_job(job_id)
    if not job:
        return

    update_job(job_id, status="running")
    ts = datetime.now().isoformat()
    logger.info(f"[{job_id}] Запуск агента {agent_type.upper()}")

    with JobTimer(agent_type):
        try:
            import base64
            from shared.file_extractor import extract_text_from_attachment

            attachment_texts: list[str] = []
            for att in request.attachments:
                try:
                    raw = base64.b64decode(att.content_base64)
                    ext = att.filename.rsplit(".", 1)[-1].lower() if "." in att.filename else ""
                    text = extract_text_from_attachment({
                        "filename": att.filename, "ext": ext,
                        "data": raw, "b64": att.content_base64, "mime": att.mime_type,
                    })
                    attachment_texts.append(f"──── Файл: {att.filename} ────\n{text}")
                except Exception as e:
                    logger.warning(f"[{job_id}] Ошибка извлечения {att.filename}: {e}")

            parts: list[str] = []
            if request.sender_email: parts.append(f"От: {request.sender_email}")
            if request.subject:      parts.append(f"Тема: {request.subject}")
            if request.text:         parts.append(f"\n── ТЕКСТ ──\n{request.text}")
            if attachment_texts:     parts.append(f"\n── ВЛОЖЕНИЯ ──\n" + "\n\n".join(attachment_texts))
            chat_input = "\n".join(parts) if parts else "(пустой запрос)"

            if agent_type == "dzo":
                from agent1_dzo_inspector.agent import create_dzo_agent
                agent = create_dzo_agent()
            else:
                from agent2_tz_inspector.agent import create_tz_agent
                agent = create_tz_agent()

            result = agent.invoke({"input": chat_input})

            decision = ""
            email_html = ""
            for step in result.get("intermediate_steps", []):
                try:
                    import json
                    obs = json.loads(step[1]) if isinstance(step[1], str) else step[1]
                    if obs.get("decision"):  decision   = obs["decision"]
                    if obs.get("emailHtml"): email_html = obs["emailHtml"]
                except Exception:
                    pass

            # Метрики
            if decision:
                DECISIONS_TOTAL.labels(agent=agent_type, decision=decision).inc()

            update_job(job_id, status="done", decision=decision,
                       result={"output": result.get("output", ""),
                               "decision": decision, "email_html": email_html})
            _run_log.append({"agent": agent_type, "ts": ts, "status": "ok", "job_id": job_id})
            logger.info(f"[{job_id}] Завершено. Решение: {decision or 'нет'}")

        except Exception as e:
            update_job(job_id, status="error", error=str(e))
            _run_log.append({"agent": agent_type, "ts": ts, "status": "error",
                             "job_id": job_id, "error": str(e)})
            logger.error(f"[{job_id}] Ошибка: {e}")
            raise  # перебросить для JobTimer.__exit__


def _detect_agent_type(request: ProcessRequest) -> str:
    combined = (request.text + " " + request.subject + " " + request.filename).lower()
    for kw in ["техническое задание", "тз", "tor", "техзадание", "требования к"]:
        if kw in combined:
            return "tz"
    return "dzo"


# ---------------------------------------------------------------------------
# Middleware: логирование + метрики латентности
# ---------------------------------------------------------------------------

@app.middleware("http")
async def _log_and_measure(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    path = request.url.path
    # Не измеряем /metrics сам себя
    if path != "/metrics":
        API_LATENCY.labels(method=request.method, endpoint=path).observe(duration)
        API_REQUESTS.labels(
            method=request.method, endpoint=path,
            status_code=str(response.status_code)
        ).inc()
    logger.info(f"{request.method} {path} [{response.status_code}] {duration:.3f}s")
    return response


# ---------------------------------------------------------------------------
# Публичные эндпоинты
# ---------------------------------------------------------------------------

@app.get("/health", summary="Статус сервиса")
def health():
    return {
        "status": "ok",
        "uptime_sec": int((datetime.now() - _start_time).total_seconds()),
        "version": "1.0.0",
        "agent_mode": os.getenv("AGENT_MODE", "both"),
        "model": os.getenv("MODEL_NAME", "gpt-4o"),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status", summary="Последние запуски агентов")
def status(limit: int = Query(default=10, ge=1, le=100)):
    return {"runs": len(_run_log), "last_runs": _run_log[-limit:]}


@app.get("/agents", summary="Список агентов")
def list_agents():
    return {"agents": [
        {"id": "dzo", "name": "Инспектор заявок ДЗО",
         "description": "Проверяет входящие заявки от ДЗО на полноту и корректность",
         "decisions": ["Заявка полная", "Требуется доработка", "Требуется эскалация"]},
        {"id": "tz",  "name": "Инспектор технических заданий",
         "description": "Проверяет ТЗ на соответствие стандартам",
         "decisions": ["Соответствует", "Требует доработки", "Не соответствует"]},
    ]}


# ---------------------------------------------------------------------------
# Защищённые эндпоинты
# ---------------------------------------------------------------------------

@app.post("/api/v1/process/dzo", response_model=JobResponse, summary="Обработать заявку ДЗО")
def process_dzo(request: ProcessRequest, background_tasks: BackgroundTasks,
               _: str = Depends(_require_api_key)):
    job_id = create_job("dzo", sender=request.sender_email, subject=request.subject)
    background_tasks.add_task(_process_with_agent, job_id, "dzo", request)
    return JobResponse(**{**db_get_job(job_id), "result": None, "error": None})


@app.post("/api/v1/process/tz", response_model=JobResponse, summary="Обработать ТЗ")
def process_tz(request: ProcessRequest, background_tasks: BackgroundTasks,
              _: str = Depends(_require_api_key)):
    job_id = create_job("tz", sender=request.sender_email, subject=request.subject)
    background_tasks.add_task(_process_with_agent, job_id, "tz", request)
    return JobResponse(**{**db_get_job(job_id), "result": None, "error": None})


@app.post("/api/v1/process/auto", response_model=JobResponse, summary="Автоопределение типа")
def process_auto(request: ProcessRequest, background_tasks: BackgroundTasks,
                _: str = Depends(_require_api_key)):
    agent_type = _detect_agent_type(request)
    job_id = create_job(agent_type, sender=request.sender_email, subject=request.subject)
    background_tasks.add_task(_process_with_agent, job_id, agent_type, request)
    return JobResponse(**{**db_get_job(job_id), "result": None, "error": None})


@app.get("/api/v1/jobs", summary="Список всех заданий")
def list_jobs(agent: Optional[str] = Query(default=None),
             status: Optional[str] = Query(default=None),
             _: str = Depends(_require_api_key)):
    jobs = db_get_history(agent=agent)
    if status:
        jobs = [j for j in jobs if j.get("status") == status]
    return {"total": len(jobs), "jobs": jobs}


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse, summary="Статус задания")
def get_job(job_id: str, _: str = Depends(_require_api_key)):
    job = db_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Задание {job_id!r} не найдено")
    return JobResponse(**job)


@app.delete("/api/v1/jobs/{job_id}", summary="Удалить задание")
def delete_job(job_id: str, _: str = Depends(_require_api_key)):
    if not db_delete_job(job_id):
        raise HTTPException(status_code=404, detail=f"Задание {job_id!r} не найдено")
    return {"message": f"Задание {job_id!r} удалено"}


@app.get("/api/v1/history", summary="История обработок")
def history(agent: Optional[str] = Query(default=None),
           status: Optional[str] = Query(default=None),
           limit: int = Query(default=50, ge=1, le=500),
           _: str = Depends(_require_api_key)):
    jobs = db_get_history(agent=agent, limit=limit)
    if status:
        jobs = [j for j in jobs if j.get("status") == status]
    return {"total": len(jobs), "items": jobs}


@app.exception_handler(Exception)
async def _generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Необработанная ошибка: {exc}")
    return JSONResponse(status_code=500,
                        content={"деталь": "Внутренняя ошибка", "error": str(exc)})
