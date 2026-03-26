"""
FastAPI REST API для обработки документов агентами ДЗО и ТЗ.

Эндпоинты:
  GET  /health                         — статус сервиса
  GET  /status                         — последние N запусков агентов
  GET  /agents                         — список доступных агентов
  GET  /metrics                        — Prometheus scrape
  POST /api/v1/process/dzo             — обработать заявку ДЗО
  POST /api/v1/process/tz              — обработать ТЗ
  POST /api/v1/process/auto            — автоопределение типа
  GET  /api/v1/check-duplicate         — проверить дубликат без обработки
  GET  /api/v1/jobs                    — список всех заданий (с пагинацией)
  GET  /api/v1/jobs/{job_id}           — статус конкретного задания
  DELETE /api/v1/jobs/{job_id}         — удалить задание
  GET  /api/v1/history                 — история обработок (с пагинацией)
  GET  /api/v1/stats                   — аггрегированная статистика
"""
import base64
import concurrent.futures
import json
import logging
import math
import os
import time
from collections import deque
from datetime import UTC, datetime

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from api.metrics import (
    API_LATENCY,
    API_REQUESTS,
    DECISIONS_TOTAL,
    JobTimer,
    metrics_router,
)
from config import (
    AGENT_JOB_TIMEOUT_SEC,
    AGENT_MAX_RETRIES,
    AGENT_RATE_LIMIT_BACKOFF,
    LLM_BACKEND,
    MODEL_NAME,
    OPENAI_API_KEY,
    GITHUB_TOKEN,
)
from shared.database import (
    create_job,
    delete_job as db_delete_job,
    find_duplicate_job,
    get_history as db_get_history,
    get_job as db_get_job,
    get_stats as db_get_stats,
    init_db,
    update_job,
)

load_dotenv()

logger = logging.getLogger("api")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:8501").split(",")
    if o.strip()
]

app = FastAPI(
    title="DZO/TZ Agents API",
    description="REST API для обработки заявок ДЗО и ТЗ",
    version="1.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json" if os.getenv("ENABLE_DOCS", "true") == "true" else None,
)

app.include_router(metrics_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type", "Accept"],
)

_start_time = datetime.now(UTC)
_run_log: deque[dict] = deque(maxlen=500)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# ---------------------------------------------------------------------------
# Реестр агентов.
# ---------------------------------------------------------------------------
AGENT_REGISTRY: dict[str, dict] = {
    "dzo": {
        "name": "Инспектор ДЗО",
        "description": "Проверяет заявки ДЗО на полноту и соответствие требованиям",
        "decisions": ["Заявка полная", "Требуется доработка", "Требуется эскалация"],
    },
    "tz": {
        "name": "Инспектор ТЗ",
        "description": "Анализирует технические задания на соответствие ГОСТ и внутренним стандартам",
        "decisions": ["Соответствует", "Требует доработки", "Не соответствует"],
    },
}


def _get_api_key() -> str:
    return os.getenv("API_KEY", "")


@app.on_event("startup")
def on_startup():
    if not _get_api_key():
        logger.warning("АПИ-ключ не задан!")
    init_db()


def _require_api_key(key: str | None = Depends(_api_key_header)) -> str:
    api_key = _get_api_key()
    if not api_key:
        return ""
    if key != api_key:
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
    force: bool = Field(
        default=False,
        description="Обработать заново, даже если дубликат уже есть",
    )


class JobResponse(BaseModel):
    job_id: str
    status: str
    agent: str
    created_at: datetime
    result: dict | None = None
    error: str | None = None


class DuplicateResponse(BaseModel):
    duplicate: bool
    existing_job_id: str | None = None
    job: dict | None = None
    message: str = ""


class PaginatedResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    has_next: bool
    items: list[dict]


# ---------------------------------------------------------------------------
# Фоновая обработка
# ---------------------------------------------------------------------------

def _process_with_agent(job_id: str, agent_type: str, request: ProcessRequest) -> None:
    job = db_get_job(job_id)
    if not job:
        return

    update_job(job_id, status="running")
    ts = datetime.now(UTC).isoformat()
    logger.info("[%s] Запуск агента %s", job_id, agent_type.upper())

    with JobTimer(agent_type):
        try:
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
                    attachment_texts.append("---- " + att.filename + " ----\n" + text)
                except Exception as e:
                    logger.warning("[%s] Ошибка извлечения %s: %s", job_id, att.filename, e)

            parts: list[str] = []
            if request.sender_email:
                parts.append("От: " + request.sender_email)
            if request.subject:
                parts.append("Тема: " + request.subject)
            if request.text:
                parts.append("\n-- ТЕКСТ --\n" + request.text)
            if attachment_texts:
                parts.append("\n-- ВЛОЖЕНИЯ --\n" + "\n\n".join(attachment_texts))
            chat_input = "\n".join(parts) if parts else "(пустой запрос)"

            if agent_type not in AGENT_REGISTRY:
                raise ValueError("Неизвестный агент: " + agent_type)

            # ── Построить цепочку fallback-моделей ──────────────────────────
            if LLM_BACKEND == "github_models":
                from shared.llm import build_github_fallback_chain
                _api_key = OPENAI_API_KEY or GITHUB_TOKEN or ""
                fallback_chain = build_github_fallback_chain(_api_key, MODEL_NAME)
            else:
                fallback_chain = [MODEL_NAME]

            logger.info(
                "[%s] Fallback-цепочка моделей: %s",
                job_id, " → ".join(fallback_chain),
            )

            # ── Перебор моделей при 429/413 ─────────────────────────────────
            result: dict = {}
            last_exc: BaseException | None = None

            for model_idx, model_name in enumerate(fallback_chain):
                attempt_log = f"модель {model_name} ({model_idx + 1}/{len(fallback_chain)})"
                logger.info("[%s] Запуск с %s", job_id, attempt_log)

                for retry in range(max(1, AGENT_MAX_RETRIES)):
                    try:
                        if agent_type == "dzo":
                            from agent1_dzo_inspector.agent import create_dzo_agent
                            agent = create_dzo_agent(model_name=model_name)
                        elif agent_type == "tz":
                            from agent2_tz_inspector.agent import create_tz_agent
                            agent = create_tz_agent(model_name=model_name)
                        else:
                            import importlib
                            mod = importlib.import_module("agent_" + agent_type + ".agent")
                            agent = mod.create_agent(model_name=model_name)

                        # Вызов с жёстким таймаутом через отдельный тред
                        if AGENT_JOB_TIMEOUT_SEC > 0:
                            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                                future = ex.submit(agent.invoke, {"input": chat_input})
                                try:
                                    result = future.result(timeout=AGENT_JOB_TIMEOUT_SEC)
                                except concurrent.futures.TimeoutError:
                                    raise TimeoutError(
                                        f"Агент не завершился за {AGENT_JOB_TIMEOUT_SEC}с — "
                                        f"превышен AGENT_JOB_TIMEOUT_SEC"
                                    )
                        else:
                            result = agent.invoke({"input": chat_input})

                        last_exc = None
                        break  # успех — выходим из retry-цикла

                    except TimeoutError:
                        raise  # таймаут не ретраим — сразу ошибка

                    except Exception as exc:
                        # Перехватываем только 429 (RateLimitError) и 413 (tokens_limit_reached);
                        # для всех остальных исключений — немедленно пробрасываем.
                        from openai import APIStatusError, RateLimitError as _RLE
                        is_rate_limit = isinstance(exc, _RLE)
                        is_token_limit = (
                            isinstance(exc, APIStatusError)
                            and getattr(exc, "status_code", 0) == 413
                        )
                        if not is_rate_limit and not is_token_limit:
                            raise
                        last_exc = exc
                        reason = "429 RateLimit" if is_rate_limit else "413 TokenLimit"
                        logger.warning(
                            "[%s] %s на %s (попытка %d/%d)",
                            job_id, reason, model_name, retry + 1, max(1, AGENT_MAX_RETRIES),
                        )
                        if retry + 1 < max(1, AGENT_MAX_RETRIES):
                            time.sleep(AGENT_RATE_LIMIT_BACKOFF)
                        # выходим из retry-цикла, перейдём к следующей модели

                if last_exc is None:
                    break  # успех — выходим из fallback-цикла

                # 429/413 исчерпаны для этой модели — пробуем следующую
                from openai import APIStatusError as _APIStatusError
                from openai import RateLimitError as _RateLimitError
                _switchable = isinstance(last_exc, (_RateLimitError, _APIStatusError))
                if _switchable and model_idx + 1 < len(fallback_chain):
                    next_model = fallback_chain[model_idx + 1]
                    logger.warning(
                        "[%s] Переключение модели: %s → %s",
                        job_id, model_name, next_model,
                    )
                    time.sleep(AGENT_RATE_LIMIT_BACKOFF)
                    continue

            if last_exc is not None:
                raise last_exc

            decision = ""
            email_html = ""
            for step in result.get("intermediate_steps", []):
                try:
                    obs = json.loads(step[1]) if isinstance(step[1], str) else step[1]
                    if obs.get("decision"):
                        decision = obs["decision"]
                    if obs.get("emailHtml"):
                        email_html = obs["emailHtml"]
                except Exception:
                    pass

            if decision:
                DECISIONS_TOTAL.labels(agent=agent_type, decision=decision).inc()

            update_job(
                job_id, status="done", decision=decision,
                result={"output": result.get("output", ""), "decision": decision, "email_html": email_html},
            )
            _run_log.append({"agent": agent_type, "ts": ts, "status": "ok", "job_id": job_id})
            logger.info("[%s] Завершено. Решение: %s", job_id, decision or "нет")

        except Exception as e:
            update_job(job_id, status="error", error=str(e))
            _run_log.append({"agent": agent_type, "ts": ts, "status": "error",
                             "job_id": job_id, "error": str(e)})
            logger.error("[%s] Ошибка: %s", job_id, e)
            raise


def _detect_agent_type(request: ProcessRequest) -> str:
    combined = (request.text + " " + request.subject + " " + request.filename).lower()
    for kw in ["техническое задание", "тз", "tor", "техзадание", "требования к"]:
        if kw in combined:
            return "tz"
    return "dzo"


def _check_and_process(
    agent_type: str,
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    if agent_type not in AGENT_REGISTRY:
        raise HTTPException(status_code=400, detail="Неизвестный агент: " + repr(agent_type))
    if not request.force:
        dup = find_duplicate_job(agent_type, request.sender_email, request.subject)
        if dup:
            logger.info(
                "[dedup] Дубликат для %s/%r/%r -> задание %s",
                agent_type, request.sender_email, request.subject, dup["job_id"],
            )
            return {
                "duplicate": True,
                "existing_job_id": dup["job_id"],
                "job": dup,
                "message": (
                    "Письмо уже было обработано ("
                    + str(dup["created_at"])[:10]
                    + "). Добавьте force=true чтобы переобработать."
                ),
            }
    job_id = create_job(agent_type, sender=request.sender_email, subject=request.subject)
    background_tasks.add_task(_process_with_agent, job_id, agent_type, request)
    job = db_get_job(job_id)
    return {"duplicate": False, "existing_job_id": None, "job": job, "message": ""}


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def _log_and_measure(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    path = request.url.path
    if path != "/metrics":
        API_LATENCY.labels(method=request.method, endpoint=path).observe(duration)
        API_REQUESTS.labels(
            method=request.method, endpoint=path,
            status_code=str(response.status_code),
        ).inc()
    logger.info("%s %s [%s] %.3fs", request.method, path, response.status_code, duration)
    return response


# ---------------------------------------------------------------------------
# Публичные эндпоинты
# ---------------------------------------------------------------------------

@app.get("/health", summary="Статус сервиса")
def health():
    return {
        "status": "ok",
        "uptime_sec": int((datetime.now(UTC) - _start_time).total_seconds()),
        "version": "1.2.0",
        "agent_mode": os.getenv("AGENT_MODE", "both"),
        "model": os.getenv("MODEL_NAME", "gpt-4o"),
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/status", summary="Последние запуски")
def status(limit: int = Query(default=10, ge=1, le=100)):
    log_list = list(_run_log)
    return {"runs": len(log_list), "last_runs": log_list[-limit:]}


@app.get("/agents", summary="Список агентов")
def list_agents():
    return {
        "agents": [
            {"id": aid, **info}
            for aid, info in AGENT_REGISTRY.items()
        ]
    }


# ---------------------------------------------------------------------------
# Защищённые эндпоинты
# ---------------------------------------------------------------------------

@app.get("/api/v1/check-duplicate", summary="Проверить дубликат")
def check_duplicate(
    agent: str = Query(..., description="dzo или tz"),
    sender: str = Query(default=""),
    subject: str = Query(default=""),
    _: str = Depends(_require_api_key),
):
    dup = find_duplicate_job(agent, sender, subject)
    if dup:
        return DuplicateResponse(
            duplicate=True,
            existing_job_id=dup["job_id"],
            job=dup,
            message="Обработано " + str(dup["created_at"])[:10] + ", решение: " + str(dup.get("decision", "--")),
        )
    return DuplicateResponse(duplicate=False, message="Дубликатов не найдено")


@app.post("/api/v1/process/dzo", summary="Обработать заявку ДЗО")
def process_dzo(
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(_require_api_key),
):
    return _check_and_process("dzo", request, background_tasks)


@app.post("/api/v1/process/tz", summary="Обработать ТЗ")
def process_tz(
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(_require_api_key),
):
    return _check_and_process("tz", request, background_tasks)


@app.post("/api/v1/process/auto", summary="Автоопределение типа")
def process_auto(
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(_require_api_key),
):
    agent_type = _detect_agent_type(request)
    return _check_and_process(agent_type, request, background_tasks)


@app.get("/api/v1/jobs", summary="Список заданий")
def list_jobs(
    agent: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=100, ge=1, le=500),
    _: str = Depends(_require_api_key),
):
    offset = (page - 1) * per_page
    items = db_get_history(agent=agent, status=status, limit=per_page + 1, offset=offset)
    has_next = len(items) > per_page
    items = items[:per_page]
    total_items = db_get_history(agent=agent, status=status, limit=100_000, offset=0)
    total = len(total_items)
    pages = math.ceil(total / per_page) if per_page else 1
    return PaginatedResponse(
        total=total, page=page, per_page=per_page,
        pages=pages, has_next=has_next, items=items,
    )


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse, summary="Статус задания")
def get_job(job_id: str, _: str = Depends(_require_api_key)):
    job = db_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Задание " + repr(job_id) + " не найдено")
    return JobResponse(**job)


@app.delete("/api/v1/jobs/{job_id}", summary="Удалить задание")
def delete_job(job_id: str, _: str = Depends(_require_api_key)):
    if not db_delete_job(job_id):
        raise HTTPException(status_code=404, detail="Задание " + repr(job_id) + " не найдено")
    return {"message": "Задание " + repr(job_id) + " удалено"}


@app.get("/api/v1/history", summary="История")
def history(
    agent: str | None = Query(default=None),
    status: str | None = Query(default=None),
    decision: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=500),
    _: str = Depends(_require_api_key),
):
    offset = (page - 1) * per_page
    items = db_get_history(
        agent=agent, status=status, decision=decision,
        date_from=date_from, date_to=date_to,
        limit=per_page + 1, offset=offset,
    )
    has_next = len(items) > per_page
    items = items[:per_page]
    total_items = db_get_history(
        agent=agent, status=status, decision=decision,
        date_from=date_from, date_to=date_to,
        limit=100_000, offset=0,
    )
    total = len(total_items)
    pages = math.ceil(total / per_page) if per_page else 1
    return PaginatedResponse(
        total=total, page=page, per_page=per_page,
        pages=pages, has_next=has_next, items=items,
    )


@app.get("/api/v1/stats", summary="Аггрегированная статистика")
def get_stats(_: str = Depends(_require_api_key)):
    return db_get_stats()


@app.exception_handler(Exception)
async def _generic_exception_handler(request: Request, exc: Exception):
    logger.error("Необработанная ошибка: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка"})
