"""
FastAPI REST API для обработки документов агентами ДЗО и ТЗ.

Эндпоинты:
  GET  /health                     — статус сервиса
  GET  /status                     — последние N запусков агентов
  GET  /agents                     — список доступных агентов
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
import uuid
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = datetime.now()

# Хранилище заданий в памяти
_jobs: dict[str, dict] = {}

# Журнал последних запусков (совместимость с /status)
_run_log: list[dict] = []

# Аутентификация через API-ключ
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_API_KEY = os.getenv("API_KEY", "")


def _require_api_key(key: Optional[str] = Depends(_api_key_header)) -> str:
    """Проверяет API-ключ из заголовка X-API-Key."""
    if not _API_KEY:
        # Если ключ не задан в .env — аутентификация отключена
        return ""
    if key != _API_KEY:
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий API-ключ")
    return key


# ---------------------------------------------------------------------------
# Модели данных
# ---------------------------------------------------------------------------


class AttachmentData(BaseModel):
    """Вложение в формате base64."""
    filename: str
    content_base64: str
    mime_type: str


class ProcessRequest(BaseModel):
    """Запрос на обработку документа."""
    text: str = Field(default="", description="Текст документа (если уже извлечён)")
    filename: str = Field(default="", description="Имя исходного файла")
    sender_email: str = Field(default="", description="Email отправителя")
    subject: str = Field(default="", description="Тема письма")
    attachments: list[AttachmentData] = Field(default_factory=list, description="Вложения в base64")


class JobResponse(BaseModel):
    """Ответ с информацией о задании."""
    job_id: str
    status: str          # pending | running | done | error
    agent: str
    created_at: str
    result: Optional[dict] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _new_job(agent: str) -> dict:
    """Создаёт новое задание и добавляет его в хранилище."""
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "status": "pending",
        "agent": agent,
        "created_at": datetime.now().isoformat(),
        "result": None,
        "error": None,
    }
    _jobs[job_id] = job
    return job


def _process_with_agent(job_id: str, agent_type: str, request: ProcessRequest) -> None:
    """Фоновая задача: запускает агент и сохраняет результат в хранилище."""
    job = _jobs.get(job_id)
    if not job:
        return

    job["status"] = "running"
    ts = datetime.now().isoformat()
    logger.info(f"[{job_id}] Запуск агента {agent_type.upper()}")

    try:
        import base64

        from shared.file_extractor import extract_text_from_attachment

        # Собираем текст из вложений
        attachment_texts: list[str] = []
        for att in request.attachments:
            try:
                raw = base64.b64decode(att.content_base64)
                ext = att.filename.rsplit(".", 1)[-1].lower() if "." in att.filename else ""
                att_dict = {
                    "filename": att.filename,
                    "ext": ext,
                    "data": raw,
                    "b64": att.content_base64,
                    "mime": att.mime_type,
                }
                text = extract_text_from_attachment(att_dict)
                attachment_texts.append(f"──── Файл: {att.filename} ────\n{text}")
            except Exception as e:
                logger.warning(f"[{job_id}] Ошибка извлечения текста из {att.filename}: {e}")

        # Формируем входной текст для агента
        parts: list[str] = []
        if request.sender_email:
            parts.append(f"От: {request.sender_email}")
        if request.subject:
            parts.append(f"Тема: {request.subject}")
        if request.text:
            parts.append(f"\n── ТЕКСТ ──\n{request.text}")
        if attachment_texts:
            parts.append(f"\n── ВЛОЖЕНИЯ ──\n" + "\n\n".join(attachment_texts))

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
                if obs.get("decision"):
                    decision = obs["decision"]
                if obs.get("emailHtml"):
                    email_html = obs["emailHtml"]
            except Exception:
                pass

        job["status"] = "done"
        job["result"] = {
            "output": result.get("output", ""),
            "decision": decision,
            "email_html": email_html,
        }
        _run_log.append({"agent": agent_type, "ts": ts, "status": "ok", "job_id": job_id})
        logger.info(f"[{job_id}] Завершено. Решение: {decision or 'нет'}")

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        _run_log.append({"agent": agent_type, "ts": ts, "status": "error", "job_id": job_id, "error": str(e)})
        logger.error(f"[{job_id}] Ошибка: {e}")


def _detect_agent_type(request: ProcessRequest) -> str:
    """Автоматически определяет тип агента по содержимому запроса."""
    combined = (request.text + " " + request.subject + " " + request.filename).lower()
    tz_keywords = ["техническое задание", "тз", "tor", "техзадание", "требования к"]
    for kw in tz_keywords:
        if kw in combined:
            return "tz"
    return "dzo"


# ---------------------------------------------------------------------------
# Middleware: логирование запросов
# ---------------------------------------------------------------------------


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    logger.info(f"→ {request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"← {request.method} {request.url.path} [{response.status_code}]")
    return response


# ---------------------------------------------------------------------------
# Публичные эндпоинты (без аутентификации)
# ---------------------------------------------------------------------------


@app.get("/health", summary="Статус сервиса")
def health():
    """Возвращает статус сервиса, uptime и версию."""
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
    """Возвращает последние N запусков агентов."""
    return {
        "runs": len(_run_log),
        "last_runs": _run_log[-limit:],
    }


@app.get("/agents", summary="Список агентов")
def list_agents():
    """Возвращает список доступных агентов и их описания."""
    return {
        "agents": [
            {
                "id": "dzo",
                "name": "Инспектор заявок ДЗО",
                "description": (
                    "Проверяет входящие заявки от дочерних обществ на полноту и корректность "
                    "перед регистрацией в системе ЭДО «Тезис»"
                ),
                "decisions": ["Заявка полная", "Требуется доработка", "Требуется эскалация"],
            },
            {
                "id": "tz",
                "name": "Инспектор технических заданий",
                "description": (
                    "Проверяет технические задания на соответствие стандартам и "
                    "полноту разделов согласно чек-листу"
                ),
                "decisions": ["Соответствует", "Требует доработки", "Не соответствует"],
            },
        ]
    }


# ---------------------------------------------------------------------------
# Защищённые эндпоинты (требуют X-API-Key)
# ---------------------------------------------------------------------------


@app.post("/api/v1/process/dzo", response_model=JobResponse, summary="Обработать заявку ДЗО")
def process_dzo(
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(_require_api_key),
):
    """Принимает заявку ДЗО и запускает обработку в фоне. Возвращает job_id."""
    job = _new_job("dzo")
    background_tasks.add_task(_process_with_agent, job["job_id"], "dzo", request)
    logger.info(f"Создано задание ДЗО [{job['job_id']}]")
    return JobResponse(**job)


@app.post("/api/v1/process/tz", response_model=JobResponse, summary="Обработать ТЗ")
def process_tz(
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(_require_api_key),
):
    """Принимает техническое задание и запускает обработку в фоне. Возвращает job_id."""
    job = _new_job("tz")
    background_tasks.add_task(_process_with_agent, job["job_id"], "tz", request)
    logger.info(f"Создано задание ТЗ [{job['job_id']}]")
    return JobResponse(**job)


@app.post("/api/v1/process/auto", response_model=JobResponse, summary="Автоопределение типа агента")
def process_auto(
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(_require_api_key),
):
    """Автоматически определяет тип агента (ДЗО или ТЗ) и запускает обработку."""
    agent_type = _detect_agent_type(request)
    job = _new_job(agent_type)
    background_tasks.add_task(_process_with_agent, job["job_id"], agent_type, request)
    logger.info(f"Создано задание AUTO→{agent_type.upper()} [{job['job_id']}]")
    return JobResponse(**job)


@app.get("/api/v1/jobs", summary="Список всех заданий")
def list_jobs(
    agent: Optional[str] = Query(default=None, description="Фильтр по агенту: dzo | tz"),
    status: Optional[str] = Query(default=None, description="Фильтр по статусу: pending | running | done | error"),
    _: str = Depends(_require_api_key),
):
    """Возвращает список всех заданий с опциональной фильтрацией."""
    jobs = list(_jobs.values())
    if agent:
        jobs = [j for j in jobs if j["agent"] == agent]
    if status:
        jobs = [j for j in jobs if j["status"] == status]
    return {"total": len(jobs), "jobs": jobs}


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse, summary="Статус задания")
def get_job(job_id: str, _: str = Depends(_require_api_key)):
    """Возвращает подробный статус и результат конкретного задания."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Задание {job_id!r} не найдено")
    return JobResponse(**job)


@app.delete("/api/v1/jobs/{job_id}", summary="Удалить задание")
def delete_job(job_id: str, _: str = Depends(_require_api_key)):
    """Удаляет задание из истории."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Задание {job_id!r} не найдено")
    del _jobs[job_id]
    logger.info(f"Задание [{job_id}] удалено")
    return {"message": f"Задание {job_id!r} удалено"}


@app.get("/api/v1/history", summary="История обработок")
def history(
    agent: Optional[str] = Query(default=None, description="Фильтр по агенту: dzo | tz"),
    status: Optional[str] = Query(default=None, description="Фильтр по статусу"),
    limit: int = Query(default=50, ge=1, le=500),
    _: str = Depends(_require_api_key),
):
    """Возвращает историю всех обработок с фильтрами по агенту и статусу."""
    jobs = list(_jobs.values())
    if agent:
        jobs = [j for j in jobs if j["agent"] == agent]
    if status:
        jobs = [j for j in jobs if j["status"] == status]
    jobs_sorted = sorted(jobs, key=lambda j: j["created_at"], reverse=True)
    return {"total": len(jobs_sorted), "items": jobs_sorted[:limit]}


# ---------------------------------------------------------------------------
# Обработчик ошибок
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def _generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Необработанная ошибка: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Внутренняя ошибка сервера", "error": str(exc)},
    )
