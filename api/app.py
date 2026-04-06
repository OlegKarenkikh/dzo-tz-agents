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
import importlib.metadata
import json
import logging
import math
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, model_validator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# load_dotenv() must run before first-party imports so that RATE_LIMIT_*
# and other env-vars are available when api.rate_limit / config are imported.
load_dotenv()

from api.metrics import (  # noqa: E402
    API_LATENCY,
    API_REQUESTS,
    DECISIONS_TOTAL,
    JobTimer,
    metrics_router,
)
from api.rate_limit import DEFAULT_RATE_LIMIT, PROCESS_RATE_LIMIT, limiter  # noqa: E402
from config import (  # noqa: E402
    AGENT_JOB_TIMEOUT_SEC,
    AGENT_MAX_RETRIES,
    AGENT_RATE_LIMIT_BACKOFF,
    LLM_BACKEND,
    MODEL_NAME,
    GITHUB_TOKEN,
)
from shared.database import (  # noqa: E402
    close_db,
    count_history as db_count_history,
    create_job,
    delete_job as db_delete_job,
    find_duplicate_job,
    get_history as db_get_history,
    get_job as db_get_job,
    get_stats as db_get_stats,
    init_db,
    update_job,
)

# ---------------------------------------------------------------------------
# Логирование — настраивается как fallback при прямом запуске модуля.
# Если uvicorn/gunicorn уже настроили root-логгер, basicConfig не вызываем,
# чтобы не переопределять их форматирование и обработчики.
# ---------------------------------------------------------------------------
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
logger = logging.getLogger("api")

_API_VERSION: str
try:
    _API_VERSION = importlib.metadata.version("dzo-tz-agents")
except importlib.metadata.PackageNotFoundError:
    _API_VERSION = "unknown"

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:8501").split(",")
    if o.strip()
]


# ---------------------------------------------------------------------------
# Lifespan — заменяет deprecated @app.on_event("startup") / "shutdown".
# Совместимо с FastAPI >= 0.93 и Starlette >= 0.27.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    if not _get_api_key():
        logger.warning("АПИ-ключ не задан! Установите переменную окружения API_KEY.")
    init_db()
    # NOTE: _run_log хранится в памяти одного процесса.
    # При использовании нескольких воркеров Gunicorn/uvicorn каждый воркер
    # ведёт свой независимый лог. Для консолидированного хранилища используйте
    # shared.database (персистит job-события в PostgreSQL, а без БД использует
    # in-memory fallback в рамках процесса).
    logger.info("API запущен. Модель: %s, бэкенд: %s", os.getenv("MODEL_NAME", "gpt-4o"), os.getenv("LLM_BACKEND", "openai"))
    yield
    # --- shutdown ---
    close_db()
    logger.info("API остановлен.")


app = FastAPI(
    title="DZO/TZ Agents API",
    description="REST API для обработки заявок ДЗО и ТЗ",
    version=_API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json" if os.getenv("ENABLE_DOCS", "true") == "true" else None,
    lifespan=lifespan,
)

# Rate limiting — slowapi поверх стандартного ASGI middleware.
# Лимиты задаются через RATE_LIMIT_PROCESS / RATE_LIMIT_DEFAULT в .env.
# Ответ при превышении: HTTP 429 Too Many Requests.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

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
    "tender": {
        "name": "Парсер тендерной документации",
        "description": (
            "Извлекает полный список документов, требуемых от участника закупки, "
            "с указанием раздела документации и требований к содержанию"
        ),
        "decisions": ["documents_found", "tool_error"],
    },
}

# ---------------------------------------------------------------------------
# Словарь ключевых слов для _detect_agent_type.
# Формат: {agent_type: [список ключевых слов]}.
# Списки сортируются по убыванию длины (длинные раньше коротких), чтобы более
# специфичные фразы проверялись первыми; первое совпадение определяет тип агента.
# ---------------------------------------------------------------------------
_AGENT_KEYWORDS: dict[str, list[str]] = {
    "tender": sorted([
        "тендерная документация", "закупочная документация",
        "конкурсная документация", "аукционная документация",
        "извещение о закупке", "документация о закупке",
        "44-фз", "223-фз", "тендер",
    ], key=len, reverse=True),
    "tz": sorted([
        "техническое задание", "техзадание", "технического задания",
        "terms of reference", "tor", "тз №", "тз к", "тз",
        "требования к поставке", "требования к услуге",
        "требования к работе", "технические требования",
    ], key=len, reverse=True),
}


def _get_api_key() -> str:
    return os.getenv("API_KEY", "")


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

# 7 MB base64 ≈ 5.25 MB decoded; generous ceiling for a single attachment.
_MAX_BASE64_CHARS = 7_000_000
# Approximate cap on combined field-value size (not the raw HTTP body size,
# which also includes JSON keys, quotes, braces, etc.).
_MAX_REQUEST_BYTES = 10_000_000  # 10 MB


class AttachmentData(BaseModel):
    filename: str = Field(max_length=500)
    content_base64: str = Field(max_length=_MAX_BASE64_CHARS)
    mime_type: str = Field(max_length=200)


class ProcessRequest(BaseModel):
    text: str = Field(default="", description="Текст документа", max_length=5_000_000)
    filename: str = Field(default="", description="Имя исходного файла", max_length=500)
    sender_email: str = Field(default="", description="Email отправителя", max_length=1000)
    subject: str = Field(default="", description="Тема письма", max_length=10_000)
    attachments: list[AttachmentData] = Field(default_factory=list, description="Вложения в base64")
    force: bool = Field(
        default=False,
        description="Обработать заново, даже если дубликат уже есть",
    )

    @model_validator(mode="after")
    def check_total_payload_size(self) -> "ProcessRequest":
        """Reject requests whose approximate combined field-value size exceeds the cap."""
        total = (
            len(self.text)
            + len(self.filename)
            + len(self.sender_email)
            + len(self.subject)
        )
        for att in self.attachments:
            total += (
                len(att.content_base64)
                + len(att.filename)
                + len(att.mime_type)
            )
        if total > _MAX_REQUEST_BYTES:
            raise ValueError(
                f"Суммарный размер полей запроса (~{total} байт) "
                f"превышает лимит {_MAX_REQUEST_BYTES} байт"
            )
        return self


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
            from shared.llm import (
                LOCAL_BACKENDS,
                effective_openai_key,
                build_fallback_chain,
                estimate_tokens,
                probe_local_max_context,
                probe_max_input_tokens,
                resolve_local_base_url,
            )

            fallback_chain = build_fallback_chain(MODEL_NAME)

            if LLM_BACKEND == "github_models" or LLM_BACKEND in LOCAL_BACKENDS:
                if LLM_BACKEND == "github_models":
                    _api_key = effective_openai_key() or GITHUB_TOKEN or ""
                else:
                    _api_key = effective_openai_key() or "not-needed"
                _TOOLS_OVERHEAD = 3000
                _est_input = estimate_tokens(chat_input)

                def _get_ctx(m: str) -> int:
                    if LLM_BACKEND == "github_models":
                        return probe_max_input_tokens(_api_key, m)
                    if LLM_BACKEND in LOCAL_BACKENDS:
                        return probe_local_max_context(resolve_local_base_url(), m)
                    raise RuntimeError(f"Unexpected LLM_BACKEND in _get_ctx: {LLM_BACKEND!r}")

                _best_model = max(fallback_chain, key=lambda m: _get_ctx(m) or 0)
                _best_ctx = _get_ctx(_best_model) or 0
                _chunking_threshold_tok = max(1, (_best_ctx - _TOOLS_OVERHEAD) // 2)

                if _est_input > _chunking_threshold_tok:
                    from shared.chunked_analysis import analyze_document_in_chunks
                    logger.info(
                        "[%s] Документ ~%d токенов > порог %d — запуск поблочного анализа "
                        "(model=%s, context=%d)",
                        job_id, _est_input, _chunking_threshold_tok,
                        _best_model, _best_ctx,
                    )
                    try:
                        _original_len = len(chat_input)
                        _summary = analyze_document_in_chunks(
                            chat_input, _api_key, _best_model, agent_type
                        )
                        if _summary:
                            chat_input = _summary
                            logger.info(
                                "[%s] Поблочный анализ: %d → %d символов резюме (~%d токенов)",
                                job_id, _original_len, len(chat_input), estimate_tokens(chat_input),
                            )
                        else:
                            logger.warning("[%s] Поблочный анализ не дал результата — используем исходный текст", job_id)
                    except Exception as _chunk_err:
                        logger.warning("[%s] Поблочный анализ упал: %s — используем исходный текст", job_id, _chunk_err)

                _est_input = estimate_tokens(chat_input)
                _filtered = [
                    m for m in fallback_chain
                    if (_get_ctx(m) or 0) > _est_input + _TOOLS_OVERHEAD
                ]
                if _filtered:
                    _skipped = [m for m in fallback_chain if m not in _filtered]
                    if _skipped:
                        logger.warning(
                            "[%s] Пропущены модели с малым контекстом "
                            "(вход ~%d + overhead %d = %d токенов): %s",
                            job_id, _est_input, _TOOLS_OVERHEAD,
                            _est_input + _TOOLS_OVERHEAD, ", ".join(_skipped),
                        )
                    fallback_chain = _filtered
                else:
                    _best = max(fallback_chain, key=lambda m: _get_ctx(m) or 0)
                    _best_ctx2 = _get_ctx(_best) or 0
                    _max_input_chars = max(1, _best_ctx2 - _TOOLS_OVERHEAD) * 4
                    if len(chat_input) > _max_input_chars:
                        logger.warning(
                            "[%s] Финальная обрезка: %d → %d символов (модель %s, ctx %d)",
                            job_id, len(chat_input), _max_input_chars, _best, _best_ctx2,
                        )
                        chat_input = chat_input[:_max_input_chars]
                    fallback_chain = [_best] + [m for m in fallback_chain if m != _best]

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
                        elif agent_type == "tender":
                            from agent21_tender_inspector.agent import create_tender_agent
                            agent = create_tender_agent(model_name=model_name)
                        else:
                            import importlib
                            mod = importlib.import_module("agent_" + agent_type + ".agent")
                            agent = mod.create_agent(model_name=model_name)

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
                        break

                    except TimeoutError:
                        raise

                    except Exception as exc:
                        from openai import APIStatusError, RateLimitError as _RLE, AuthenticationError
                        _exc_str = str(exc)

                        is_rate_limit = isinstance(exc, _RLE) or (
                            "429" in _exc_str and "rate" in _exc_str.lower()
                        )
                        is_token_limit = (
                            (isinstance(exc, APIStatusError) and getattr(exc, "status_code", 0) == 413)
                            or "tokens_limit_reached" in _exc_str
                            or ("413" in _exc_str and "too large" in _exc_str.lower())
                        )
                        is_auth_error = isinstance(exc, AuthenticationError) or (
                            isinstance(exc, APIStatusError)
                            and getattr(exc, "status_code", 0) == 401
                        )

                        if is_auth_error:
                            error_msg = str(exc)
                            logger.error(
                                "[%s] Ошибка аутентификации на модели %s: %s",
                                job_id, model_name, error_msg,
                            )
                            if "ollama" in error_msg.lower() or "invalid_request_error" in error_msg.lower():
                                logger.error(
                                    "[%s] Похоже, API key не настроен правильно. "
                                    "Убедитесь, что OPENAI_API_KEY или GITHUB_TOKEN установлены.",
                                    job_id,
                                )
                            raise

                        if not is_rate_limit and not is_token_limit:
                            raise

                        last_exc = exc
                        reason = "429 RateLimit" if is_rate_limit else "413 TokenLimit"
                        logger.warning(
                            "[%s] %s на %s (попытка %d/%d)",
                            job_id, reason, model_name, retry + 1, max(1, AGENT_MAX_RETRIES),
                        )
                        if is_token_limit:
                            logger.warning(
                                "[%s] 413 TokenLimit — пропускаем ретраи, "
                                "переключаемся на следующую модель",
                                job_id,
                            )
                            break
                        if retry + 1 < max(1, AGENT_MAX_RETRIES):
                            time.sleep(AGENT_RATE_LIMIT_BACKOFF)

                if last_exc is None:
                    break

                from openai import APIStatusError as _APIStatusError
                from openai import RateLimitError as _RateLimitError
                _exc_str_sw = str(last_exc)
                _switchable = (
                    isinstance(last_exc, (_RateLimitError, _APIStatusError))
                    or "tokens_limit_reached" in _exc_str_sw
                    or "429" in _exc_str_sw
                    or "413" in _exc_str_sw
                )
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
            artifacts: dict = {}

            for step in result.get("intermediate_steps", []):
                try:
                    obs = json.loads(step[1]) if isinstance(step[1], str) else step[1]
                    if not isinstance(obs, dict):
                        continue

                    if obs.get("decision"):
                        decision = obs["decision"]

                    if obs.get("emailHtml"):
                        artifacts["email_html"] = obs["emailHtml"]
                    if obs.get("tezisFormHtml"):
                        artifacts["tezis_form_html"] = obs["tezisFormHtml"]
                    if obs.get("correctedHtml"):
                        artifacts["corrected_html"] = obs["correctedHtml"]
                    if obs.get("escalationHtml"):
                        artifacts["escalation_html"] = obs["escalationHtml"]
                    if "checklist_required" in obs or "checklist_attachments" in obs:
                        artifacts["validation_report"] = obs
                    if "sections" in obs and isinstance(obs.get("sections"), list):
                        artifacts["json_report"] = obs
                    if "html" in obs and "title" in obs:
                        artifacts["corrected_tz_html"] = obs["html"]

                    if (
                        agent_type == "tender"
                        and isinstance(step, (list, tuple))
                        and len(step) >= 2
                        and step[0] == "generate_document_list"
                    ):
                        if "documents" in obs and isinstance(obs.get("documents"), list):
                            summary = obs.get("summary") or {}
                            if not isinstance(summary, dict):
                                summary = {}
                            total = summary.get("total", len(obs["documents"]))
                            artifacts["document_list"] = {**obs, "total": total}
                            decision = "documents_found"
                        elif "error" in obs and not artifacts.get("document_list"):
                            artifacts["document_list_error"] = obs
                            decision = "tool_error"

                except Exception:
                    pass

            if artifacts:
                logger.info(
                    "[%s] Артефакты сохранены: %s",
                    job_id, ", ".join(artifacts.keys()),
                )

            if decision:
                DECISIONS_TOTAL.labels(agent=agent_type, decision=decision).inc()

            update_job(
                job_id, status="done", decision=decision,
                result={
                    "output": result.get("output", ""),
                    "decision": decision,
                    **artifacts,
                },
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
    """Определяет тип агента по ключевым словам в тексте, теме и имени файла.

    Использует словарь _AGENT_KEYWORDS с приоритетом:
    tender > tz > dzo (dzo — fallback по умолчанию).
    Для повышения точности рекомендуется заменить на ML-классификатор
    (например, fasttext или fine-tuned sentence-transformer).
    """
    combined = (
        request.text[:2000] + " "  # Ограничиваем длину для производительности
        + request.subject + " "
        + request.filename
    ).lower()

    for agent_type, keywords in _AGENT_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                logger.debug("_detect_agent_type: '%s' → %s (ключ: '%s')", request.subject[:50], agent_type, kw)
                return agent_type

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
        "version": _API_VERSION,
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
@limiter.limit(DEFAULT_RATE_LIMIT)
def check_duplicate(
    request: Request,
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
@limiter.limit(PROCESS_RATE_LIMIT)
def process_dzo(
    body: ProcessRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    _: str = Depends(_require_api_key),
):
    return _check_and_process("dzo", body, background_tasks)


@app.post("/api/v1/process/tz", summary="Обработать ТЗ")
@limiter.limit(PROCESS_RATE_LIMIT)
def process_tz(
    body: ProcessRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    _: str = Depends(_require_api_key),
):
    return _check_and_process("tz", body, background_tasks)


@app.post("/api/v1/process/tender", summary="Парсинг тендерной документации")
@limiter.limit(PROCESS_RATE_LIMIT)
def process_tender(
    body: ProcessRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    _: str = Depends(_require_api_key),
):
    """Извлекает список документов, требуемых от участника закупки."""
    return _check_and_process("tender", body, background_tasks)


@app.post("/api/v1/process/auto", summary="Автоопределение типа")
@limiter.limit(PROCESS_RATE_LIMIT)
def process_auto(
    body: ProcessRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    _: str = Depends(_require_api_key),
):
    agent_type = _detect_agent_type(body)
    return _check_and_process(agent_type, body, background_tasks)


@app.get("/api/v1/jobs", summary="Список заданий")
@limiter.limit(DEFAULT_RATE_LIMIT)
def list_jobs(
    request: Request,
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
    total = db_count_history(agent=agent, status=status)
    pages = math.ceil(total / per_page) if per_page else 1
    return PaginatedResponse(
        total=total, page=page, per_page=per_page,
        pages=pages, has_next=has_next, items=items,
    )


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse, summary="Статус задания")
@limiter.limit(DEFAULT_RATE_LIMIT)
def get_job(job_id: str, request: Request, _: str = Depends(_require_api_key)):
    job = db_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Задание " + repr(job_id) + " не найдено")
    return JobResponse(**job)


@app.delete("/api/v1/jobs/{job_id}", summary="Удалить задание")
@limiter.limit(DEFAULT_RATE_LIMIT)
def delete_job(job_id: str, request: Request, _: str = Depends(_require_api_key)):
    if not db_delete_job(job_id):
        raise HTTPException(status_code=404, detail="Задание " + repr(job_id) + " не найдено")
    return {"message": "Задание " + repr(job_id) + " удалено"}


@app.get("/api/v1/history", summary="История")
@limiter.limit(DEFAULT_RATE_LIMIT)
def history(
    request: Request,
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
    total = db_count_history(
        agent=agent, status=status, decision=decision,
        date_from=date_from, date_to=date_to,
    )
    pages = math.ceil(total / per_page) if per_page else 1
    return PaginatedResponse(
        total=total, page=page, per_page=per_page,
        pages=pages, has_next=has_next, items=items,
    )


@app.get("/api/v1/stats", summary="Аггрегированная статистика")
@limiter.limit(DEFAULT_RATE_LIMIT)
def get_stats(request: Request, _: str = Depends(_require_api_key)):
    return db_get_stats()


@app.exception_handler(Exception)
async def _generic_exception_handler(request: Request, exc: Exception):
    logger.error("Необработанная ошибка: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка"})
