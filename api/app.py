"""
FastAPI REST API для обработки документов агентами ДЗО, ТЗ, Tender, Collector.

Эндпоинты:
  GET  /health                         — статус сервиса
  GET  /status                         — последние N запусков агентов
  GET  /agents                         — список доступных агентов
  GET  /.well-known/agent.json         — A2A Agent Card
  GET/POST /mcp                        — MCP streamable HTTP endpoint
  GET  /metrics                        — Prometheus scrape
  POST /api/v1/process                 — автоопределение агента
  POST /api/v1/process/{agent}         — явный выбор агента
  POST /api/v1/resolve-agent           — только определить агента (без обработки)
  GET  /api/v1/check-duplicate         — проверить дубликат без обработки
  POST /api/v1/upload                  — загрузить файл напрямую
  GET  /api/v1/jobs/{job_id}           — статус задачи
  GET  /api/v1/jobs/{job_id}/stream    — SSE-поток прогресса
  DELETE /api/v1/jobs/{job_id}         — удалить задачу
  GET  /api/v1/history                 — история обработок
  GET  /api/v1/stats                   — аггрегированная статистика
  GET  /api/v1/run_log                 — последние 200 запусков
"""
from __future__ import annotations

import logging
import time
from collections import deque
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

load_dotenv()

# ── Роутеры ──────────────────────────────────────────────────────────────────
from api.metrics import API_LATENCY, API_REQUESTS, metrics_router  # noqa: E402
from api.routes.process import router as process_router             # noqa: E402
from api.routes.jobs import router as jobs_router                   # noqa: E402
from api.routes.system import router as system_router               # noqa: E402
from api.security import require_api_key, make_mcp_auth_guard       # noqa: E402
from api.schemas import ProcessRequest                              # noqa: E402
from api.services.routing import detect_agent_type, AGENT_REGISTRY # noqa: E402
from config import (                                                # noqa: E402
    CORS_ORIGINS,
    ENABLE_MCP,
    LOG_LEVEL,
    RATE_LIMIT,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("api")

# ── Run-log (последние 200 запусков, shared с process router) ─────────────────
from api.routes.process import _run_log  # noqa: E402

_STATUS_DEQUE: deque = deque(maxlen=50)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Запуск AISRM API (агенты: %s)", ", ".join(AGENT_REGISTRY.keys()))
    yield
    logger.info("Остановка AISRM API")


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AISRM Document Processing API",
    description="Мульти-агентная система инспекции документов",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ───────────────────────────────────────────────────────────────────────
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ── Rate-limit ────────────────────────────────────────────────────────────────
if RATE_LIMIT:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    limiter = Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

# ── MCP ────────────────────────────────────────────────────────────────────────
_mcp_available = False
if ENABLE_MCP:
    try:
        from shared.mcp_server import mcp as _mcp_server
        app.mount("/mcp", _mcp_server.streamable_http_app())
        _mcp_available = True
        logger.info("MCP endpoint подключён на /mcp")
    except Exception as _e:
        logger.warning("MCP недоступен: %s", _e)

app.middleware("http")(make_mcp_auth_guard(_mcp_available, CORS_ORIGINS))

# ── Латентность middleware ──────────────────────────────────────────────────
@app.middleware("http")
async def _track_latency(request: Request, call_next):
    method = request.method
    path = request.url.path
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    try:
        API_REQUESTS.labels(method=method, endpoint=path,
                            status=str(response.status_code)).inc()
        API_LATENCY.labels(method=method, endpoint=path).observe(elapsed)
    except Exception:
        pass
    return response

# ── Роутеры ───────────────────────────────────────────────────────────────────
app.include_router(system_router)
app.include_router(process_router)
app.include_router(jobs_router)
app.include_router(metrics_router)


# ── /status — последние запуски агентов ───────────────────────────────────────
@app.get("/status")
def get_status(n: int = Query(default=10, ge=1, le=200)):
    return {"run_log": _run_log[-n:]}


# ── /api/v1/resolve-agent — только определить агента ────────────────────────
from fastapi import Depends  # noqa: E402

@app.post("/api/v1/resolve-agent")
def resolve_agent_endpoint(
    request: ProcessRequest,
    _key: str = Depends(require_api_key),
):
    agent_type = detect_agent_type(request)
    agent_info = AGENT_REGISTRY.get(agent_type, {})
    return {
        "agent_type": agent_type,
        "agent_name": agent_info.get("name"),
        "confidence": "keyword_match",
    }


# ── /api/v1/check-duplicate ──────────────────────────────────────────────────
@app.get("/api/v1/check-duplicate")
def check_duplicate(
    agent_type: str = Query(...),
    sender_email: str = Query(default=""),
    subject: str = Query(default=""),
    _key: str = Depends(require_api_key),
):
    from shared.database import find_duplicate_job
    dup = find_duplicate_job(agent_type, sender_email, subject)
    if dup:
        return {"duplicate": True, "existing_job_id": dup["job_id"], "job": dup}
    return {"duplicate": False, "existing_job_id": None, "job": None}


# ── Backward-compat re-exports (тесты импортируют из api.app) ────────────────
# После рефакторинга TD-01 функции переехали в api/services/.
from api.services.decision import (          # noqa: E402
    apply_email_artifact as _apply_email_artifact,
    attachment_meta as _attachment_meta,
    has_tz_agent_analysis_observation as _has_tz_agent_analysis_observation,
    is_result_usable_for_agent as _is_result_usable_for_agent,
    is_token_limit_error_text as _is_token_limit_error_text,
    looks_like_tz_content as _looks_like_tz_content,
    normalize_decision as _normalize_decision,
    _KNOWN_DECISIONS,
    _DECISION_SYNONYMS,
    _TECHNICAL_STATUSES,
)
from api.services.processing import (        # noqa: E402
    process_with_agent as _process_with_agent,
    format_created_at as _format_created_at,
)
from api.services.routing import (           # noqa: E402
    detect_agent_type as _resolve_agent,
    detect_agent_type as _fallback_agent_id,
)
