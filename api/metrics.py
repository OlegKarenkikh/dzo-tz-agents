"""
Prometheus-метрики для FastAPI.
Подключается через app.include_router(metrics_router) в api/app.py.
"""
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)
from fastapi import APIRouter
from fastapi.responses import Response
import time

metrics_router = APIRouter()

# ── Счётчики ──────────────────────────────────────────────────
JOBS_TOTAL = Counter(
    "dzo_tz_jobs_total",
    "Общее кол-во заданий",
    ["agent", "status"],
)

JOBS_DURATION = Histogram(
    "dzo_tz_job_duration_seconds",
    "Время обработки задания",
    ["agent"],
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

JOBS_IN_PROGRESS = Gauge(
    "dzo_tz_jobs_in_progress",
    "Задания в обработке сейчас",
    ["agent"],
)

DECISIONS_TOTAL = Counter(
    "dzo_tz_decisions_total",
    "Кол-во решений по типу",
    ["agent", "decision"],
)

EMAILS_PROCESSED = Counter(
    "dzo_tz_emails_processed_total",
    "Обработанные письма",
    ["agent"],
)

EMAILS_ERRORS = Counter(
    "dzo_tz_emails_errors_total",
    "Ошибки при обработке писем",
    ["agent", "error_type"],
)

API_REQUESTS = Counter(
    "dzo_tz_api_requests_total",
    "HTTP-запросы к API",
    ["method", "endpoint", "status_code"],
)

API_LATENCY = Histogram(
    "dzo_tz_api_latency_seconds",
    "Задержка HTTP-запросов",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

POLL_CYCLES = Counter(
    "dzo_tz_poll_cycles_total",
    "Циклы опроса почты",
    ["agent"],
)


@metrics_router.get("/metrics", include_in_schema=False)
def metrics():
    """Эндпоинт для Prometheus scrape."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class JobTimer:
    """Контекстный менеджер для измерения времени задания."""
    def __init__(self, agent: str):
        self.agent = agent
        self.start = None

    def __enter__(self):
        self.start = time.time()
        JOBS_IN_PROGRESS.labels(agent=self.agent).inc()
        return self

    def __exit__(self, exc_type, *_):
        duration = time.time() - self.start
        JOBS_DURATION.labels(agent=self.agent).observe(duration)
        JOBS_IN_PROGRESS.labels(agent=self.agent).dec()
        status = "error" if exc_type else "done"
        JOBS_TOTAL.labels(agent=self.agent, status=status).inc()
