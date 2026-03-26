# syntax=docker/dockerfile:1
# ─── Base: пиним по digest — защита от supply-chain атак ──────────────────
FROM python:3.11-slim@sha256:d6e4d224f70f9e0172a06a3a2eba2f768eb146811a349278b38fff3a36463b47 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPYCACHEPREFIX=/tmp/pycache \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get purge -y --auto-remove

WORKDIR /app

# Создаем папку логов заранее с правами 755 (appuser получает chown в production-стадии)
RUN mkdir -p /app/logs && chmod 755 /app/logs

# ─── Зависимости: сборка виртуального окружения ─────────────────────────────
FROM base AS deps
COPY requirements.txt .
RUN python -m venv $VIRTUAL_ENV \
    && pip install --upgrade pip \
    && pip install -r requirements.txt \
    && find /opt/venv/lib -name '*.pyc' -delete \
    && find /opt/venv/lib -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# ─── Production образ ───────────────────────────────────────────
FROM base AS production

RUN groupadd -r -g 1001 appuser \
    && useradd -r -u 1001 -g appuser --no-create-home --shell /sbin/nologin appuser

# Копируем готовое виртуальное окружение из стадии deps
COPY --from=deps /opt/venv /opt/venv

COPY --chown=appuser:appuser . .

RUN mkdir -p /tmp/pycache \
    && chown -R appuser:appuser /app/logs /tmp/pycache

RUN find /app -perm /6000 -type f 2>/dev/null | xargs -r chmod a-s

USER appuser

# Проверка импортов (venv активен через PATH)
RUN python -c "import uvicorn; import shared, api, agent1_dzo_inspector, agent2_tz_inspector; print('Import check OK')"

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "main.py"]
